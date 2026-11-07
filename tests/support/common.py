# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Helpers that the renderer's tests of several areas share."""

from cuju.render._format import recording as _recording
from cuju.render._http import server as _server
from cuju.render._registry import teams as _teams
from cuju.render._store import library as _library

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
