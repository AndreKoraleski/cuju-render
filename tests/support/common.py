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
_SINGLE = """
def agent(obs):
    return [5 if obs['step'] % 7 else 12]
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


def _package_team(name='Test package', extra=None):
    from support.package import package_zip

    return _teams.add(name, 'team.zip', package_zip(name, extra))


# Challenges.


# The two players of the recordings of challenge attempts, one a side, which stand still.
_CHALLENGE_PLAYERS = [
    {'team': team, 'index': 0, 'goalkeeper': False, 'controlled': team == 0} for team in (0, 1)
]


def _challenge_frame(step, score=(0, 0), flags=0, mode=0):
    """Returns a frame of a recording of two still players, with its step, score and flags."""
    head = struct.pack('<8i', step, mode, score[0], score[1], -1, -1, step * 100, flags)
    frame = head + struct.pack('<7f4i', 0, 0, 0, 0, 0, 0, 1, -1, -1, 0, -1)
    return frame + bytes(_recording.frame_bytes(len(_CHALLENGE_PLAYERS)) - len(frame))


def _challenge_frames(goal_at=None, length=40, finished=True, against_at=None):
    frames = []
    for step in range(length):
        left = int(goal_at is not None and step >= goal_at)
        right = int(against_at is not None and step >= against_at)
        flags = 1 if finished and step == length - 1 else 0
        frames.append(_challenge_frame(step, (left, right), flags))
    return frames


def _person_recording(challenge, index, frames, **changes):
    """Saves a recording as the Play page saves a person's attempt of a challenge."""
    provenance = {
        'source': 'human_game',
        'seed': challenge['seeds'][index],
        'scenario': challenge['scenario'],
        'humans': [True, False],
        'teams': ['builtin', 'builtin'],
        'agent_counts': [1, 0],
        'action_set': 'default',
        'ability': list(challenge['played_ability']),
        **changes,
    }
    head = _recording.header(
        'You against the AI',
        challenge['scenario'],
        _CHALLENGE_PLAYERS,
        None,
        len(frames),
        {'duration': 400, 'second_half': None, 'full_match': False},
        provenance,
    )
    return _library.save(head, frames).stem


def _short_challenges(monkeypatch, steps):
    """Ends every attempt of a challenge after `steps` steps."""
    from cuju.render._playing import challenges as _challenges

    real = _challenges.BatchEnvironment

    def short(*arguments, **options):
        batch = real(*arguments, **options)
        step, count = batch.step, [0]

        def limited(actions):
            observation, reward, done, information = step(actions)
            count[0] += 1
            return observation, reward, done | (count[0] >= steps), information

        batch.step = limited
        return batch

    monkeypatch.setattr(_challenges, 'BatchEnvironment', short)


# Achievements.

# Two players a side, the goalkeeper first, as a header lists them.
_ACHIEVEMENT_PLAYERS = [
    {'team': team, 'index': index, 'goalkeeper': index == 0, 'controlled': False}
    for team in (0, 1)
    for index in (0, 1)
]


def _achievement_header(scenario='5_vs_5', full_match=True, ability=1.0, opponent='builtin'):
    return {
        'engine_scorer': True,
        'scenario': scenario,
        'full_match': full_match,
        'steps_per_second': 10,
        'players': _ACHIEVEMENT_PLAYERS,
        'teams': [{'id': 't-left', 'ability': 1.0}, {'id': opponent, 'ability': ability}],
    }


def _achievement_frames(length, goals=(), modes=(), touches=(), finished=True, minutes=3.0):
    """Returns frames of four players with goals, restarts and touches at the frames they name.

    Args:
        goals: `(frame, team, scorer)` for each goal.
        modes: `(first, last, mode, ball x)` for each restart.
        touches: `(frame, player, ball x)` for each touch.
    """
    frames, score = [], [0, 0]
    size = _recording.frame_bytes(len(_ACHIEVEMENT_PLAYERS))
    for step in range(length):
        flags = 1 if finished and step == length - 1 else 0
        mode, ball = 0, 0.0
        for first, last, kind, x in modes:
            if first <= step <= last:
                mode, ball = kind, x
        touched = bytearray(4)
        for at, player, x in touches:
            if at == step:
                touched[player], ball = 1, x
        for at, team, scorer in goals:
            if at == step:
                score[team] += 1
                flags |= (scorer + 1) << 8
        clock = int(step * minutes * 60000 / max(1, length - 1))
        head = struct.pack(
            '<8i7f4i',
            step,
            mode,
            score[0],
            score[1],
            -1,
            -1,
            clock,
            flags,
            ball,
            0,
            0,
            0,
            0,
            0,
            1,
            -1,
            -1,
            0,
            -1,
        )
        body = bytes(size - len(head) - 4) + bytes(touched)
        frames.append(head + body)
    return frames


def _help_server():
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{server.server_address[1]}'


def _help_json(address, path, document=None, headers=None):
    """Returns the status and JSON body of a request to the server, an error's too."""
    data = None if document is None else json.dumps(document).encode()
    request = urllib.request.Request(
        address + path, data=data, method='GET' if data is None else 'POST', headers=headers or {}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b'null')
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b'null')


# The moments of the library, its search and the captions.

_REPOSITORY = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SAMPLE_FOLDER = os.path.join(_REPOSITORY, 'src', 'cuju', 'render', 'samples')
