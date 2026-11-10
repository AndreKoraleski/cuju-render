# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Helpers that the renderer's tests of several areas share."""

import json
import os
import struct
import threading
import urllib.request

import torch

import cuju
import cuju.errors
import cuju.state
from cuju.render._format import recording as _recording
from cuju.render._http import launch as _launch
from cuju.render._http import server as _server
from cuju.render._registry import teams as _teams
from cuju.render._store import home as _home
from cuju.render._store import library as _library


def _get(address, path):
    with urllib.request.urlopen(address + path, timeout=10) as response:
        return response.status, response.read()


def _send(address, path, data, method='POST'):
    request = urllib.request.Request(address + path, data=data, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


_CRASH = """
def agent(obs):
    if obs['step'] == 4:
        raise ValueError('the policy broke')
    return [7]
"""


# A toy submission that controls several players and sends each one a direction of its own, by
# the index of its player, so the test sees each action reach its player.
_SEVERAL = """
def agent(obs):
    actions = []
    for raw in obs['players_raw']:
        player = raw['active']
        assert raw['left_team_roles'][player] != 0, 'a goalkeeper reached the submission'
        actions.append(3 if player % 2 else 7)
    assert len(actions) == obs['controlled_players']
    return actions
"""


def _short_matches(monkeypatch, steps):
    """Ends every match that `play` starts after `steps` steps."""
    from cuju.render._playing import play as _play

    real = _play.BatchEnvironment

    def short(*arguments, **options):
        batch = real(*arguments, **options)
        step, count = batch.step, [0]

        def limited(actions):
            observation, reward, done, information = step(actions)
            count[0] += 1
            return observation, reward, done | (count[0] >= steps), information

        batch.step = limited
        return batch

    monkeypatch.setattr(_play, 'BatchEnvironment', short)


def _toy_team(tmp_path, name, source, format, control=None):
    folder = tmp_path / name
    folder.mkdir()
    (folder / 'main.py').write_text(source)
    team = _teams.add_folder(folder, name, format)
    return _teams.update(team['id'], control=control) if control else team


def _frames(path):
    document = _recording.read_header(path)
    return document, list(_recording.frames(path))


def _control(
    players, assignment='dynamic', selection=None, goalkeeper='scenario', action_set='default'
):
    return dict(
        players=players,
        assignment=assignment,
        selection=selection or [],
        goalkeeper=goalkeeper,
        action_set=action_set,
    )


_SAMPLES = ['sample-11v11', 'sample-5v5']


def _serve_once(monkeypatch):
    """Starts the server as `cuju render` does and stops it at once."""

    def stop(server):
        raise KeyboardInterrupt

    monkeypatch.setattr(_server.http.server.ThreadingHTTPServer, 'serve_forever', stop)
    _server.serve(0)


def _library_ids():
    return sorted(entry['id'] for entry in _library.matches())


def _fake_server(render_home, port=8999):
    return _launch.Server(port, os.getpid(), 'key', render_home)


def _one_second(monkeypatch):
    """Makes identifiers of one second whose random ends each come three times."""
    import itertools
    import types

    monkeypatch.setattr(
        _home, 'time', types.SimpleNamespace(strftime=lambda form: '20261109-120000')
    )
    lock = threading.Lock()
    source = itertools.chain.from_iterable([f'{value:04x}'] * 3 for value in itertools.count())

    def token_hex(count):
        with lock:
            return next(source)

    monkeypatch.setattr(_home, 'secrets', types.SimpleNamespace(token_hex=token_hex))


def _sample_head(name, count):
    """Returns the header of a shipped sample as `_recording.header` returns it, and its frames."""
    path = _library._SAMPLES / f'{name}.cjr'
    document = _recording.read_header(path)
    document.pop('keyframe_interval', None)
    document.update(version=1, frame_count=count)
    return _recording._encode_header(document), list(_recording.frames(path, stop=count))


def _filtered_episodes(**filters):
    """Plays episodes of a scenario under an unfiltered recorder and one with `filters`.

    Returns the frames of every episode, the frames that the filtered recorder saved, the
    summaries that a function filter saw, and the filtered recorder.
    """
    batch = cuju.BatchEnvironment(
        'academy_empty_goal_close_l1_r0', environment_count=1, device='cpu', seed=11
    )
    everything = cuju.render.Recorder(batch)
    seen = []
    keep = filters.pop('keep', None)
    if keep == 'record':

        def keep(summary):
            seen.append(summary)
            return summary['length'] % 2 == 0

    filtered = cuju.render.Recorder(batch, keep=keep, **filters)
    batch.reset()
    episode = step = 0
    while everything.episodes < 8:
        # Even episodes shoot at the goal and score, odd ones shoot over the touchline.
        action = (12 if step % 3 else 5) if episode % 2 == 0 else (3 if step % 2 else 12)
        _, _, done, _ = batch.step(torch.tensor([[action]], dtype=torch.int32))
        step += 1
        if bool(done[0]):
            episode, step = episode + 1, 0
    batch.close()
    episodes = [list(_recording.frames(path)) for path in everything.saved]
    kept = [list(_recording.frames(path)) for path in filtered.saved]
    return episodes, kept, seen, filtered


def _goals(frames):
    return sum(struct.unpack_from('<2i', frames[-1], 8))
