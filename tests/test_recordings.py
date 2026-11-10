# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the recording format, the recorder, its filters and annotations."""

import gzip
import io
import json
import struct
import threading

import numpy as np
import pytest
import torch

import cuju
import cuju.errors
import cuju.state
from conftest import actions_at
from cuju.render._format import recording as _recording
from cuju.render._http import server as _server
from cuju.render._store import library as _library
from support.common import (
    _SAMPLES,
    _SEVERAL,
    _frames,
    _get,
    _library_ids,
    _one_second,
    _serve_once,
    _short_matches,
    _toy_team,
)


def test_pitch_frame_matches_raw(device):
    """The pitch frame turns every player into the raw observation's positions, bit for bit."""
    batch = cuju.BatchEnvironment(
        '5_vs_5_l4_r1', environment_count=2, device=device, with_raw=True, seed=3
    )
    batch.reset(reverse=[0, 1])
    reader = _recording.StateReader(10)
    for step in range(80):
        batch.step(actions_at(step, 2, 5, 19).to(device))
        raw = {name: tensor.cpu() for name, tensor in batch.raw().items()}
        for environment in range(2):
            state = batch.get_state(environment)
            order = reader._order(reader._values(state, 'pitch'))
            paths = [
                f'match.players[{player}].base.humanoid.spatialState.position'
                for player in range(10)
            ]
            positions = cuju.state.read(state, paths, frame='pitch')
            for player, (team, index) in enumerate(order):
                name = 'left_team' if team == 0 else 'right_team'
                x, y = positions[player][0], positions[player][1]
                expected = raw[name][environment, 0, index]
                # GRF: the raw observation divides by 54.4 and by -83.6 in double precision.
                assert np.float32(np.float64(x) / 54.4) == expected[0]
                assert np.float32(np.float64(y) / -83.6) == expected[1]
            frame = reader.frame(state)
            _, mode, left, right, owned_team, owned = struct.unpack_from('<6i', frame)
            assert [left, right] == raw['score'][environment, 0].tolist()
            assert mode == int(raw['game_mode'][environment, 0])
            assert owned_team == int(raw['ball_owned_team'][environment, 0])
            if owned >= 0:
                assert order[owned][1] == int(raw['ball_owned_player'][environment, 0])


def test_world_transforms_are_upright():
    batch = cuju.BatchEnvironment('5_vs_5_l1_r0', environment_count=1, device='cpu')
    batch.reset()
    reader = _recording.StateReader(10)
    for step in range(20):
        batch.step(actions_at(step, 1, 1, 19))
    frame = reader.frame(batch.get_state(0))
    head = _recording._FRAME_HEAD.size
    packed = np.frombuffer(frame, '<i2', 10 * 14 * 7, head).reshape(10, 14, 7).astype(np.float64)
    scale = [_recording.POSITION_SCALE] * 3 + [_recording.ROTATION_SCALE] * 4
    nodes = packed / np.array(scale)
    neck = _recording.NODES.index('neck')
    ankle = _recording.NODES.index('left_ankle')
    assert (nodes[:, neck, 2] > nodes[:, ankle, 2] + 1.0).all()
    assert np.allclose(np.linalg.norm(nodes[:, :, 3:], axis=2), 1, atol=2e-4)
    assert (np.abs(nodes[:, 0, 0]) < 60).all() and (np.abs(nodes[:, 0, 1]) < 45).all()


def test_recorder_writes_episodes(render_home):
    batch = cuju.BatchEnvironment(
        'academy_empty_goal_close_l1_r0', environment_count=1, device='cpu'
    )
    recorder = cuju.render.Recorder(batch)
    batch.reset()
    recorder.capture()
    step = 0
    while len(recorder.saved) < 2:
        _, _, done, _ = batch.step(torch.tensor([[12 if step % 3 else 5]], dtype=torch.int32))
        recorder.capture(done)
        step += 1
    first = recorder.saved[0]
    document = _recording.read_header(first)
    frames = list(_recording.frames(first))
    assert document['frame_count'] == len(frames)
    assert document['second_half'] is None
    assert document['duration'] > 0
    assert document['engine_scorer']
    assert document['offside_called']
    assert all(len(frame) == document['frame_bytes'] for frame in frames)
    assert [struct.unpack_from('<i', frame)[0] for frame in frames] == list(range(len(frames)))
    summary = {entry['id']: entry for entry in _library.matches()}[first.stem]
    assert summary['steps'] == len(frames)
    provenance = {'source': 'recorder', 'environment': 0, 'cuju_version': cuju.__version__}
    assert document['provenance'] == provenance
    assert summary['provenance'] == provenance
    assert summary['scenario'] == 'academy_empty_goal_close_l1_r0'
    # The shots of the episode show as touches during shot animations of the agent's player.
    players = len(document['players'])
    padded = -(-players // 4) * 4
    start = _recording._FRAME_HEAD.size + players * 14 * 14 + padded
    actions = [frame[start : start + players] for frame in frames]
    touches = [frame[start + padded : start + padded + players] for frame in frames]
    shots = [
        index
        for index in range(len(frames))
        if any(t and a == 8 for a, t in zip(actions[index], touches[index], strict=True))
    ]
    assert shots


def test_late_viewer_gets_history(render_home):
    batch = cuju.BatchEnvironment('5_vs_5_l4_r0', environment_count=1, device='cpu')
    source = cuju.render.watch(batch, backlog=True)
    batch.reset()
    for step in range(40):
        batch.step(actions_at(step, 1, 4, 19))
    connection = _server.http.client.HTTPConnection('127.0.0.1', source.port, timeout=10)
    connection.request('GET', '/stream')
    response = connection.getresponse()
    start = response.read(12)
    (length,) = struct.unpack_from('<I', start, 8)
    document = json.loads(response.read(length))
    assert document['second_half'] == _recording.scenario_timing(batch.get_state(0))['second_half']
    size = document['frame_bytes']
    history = [response.read(size) for _ in range(40)]
    steps = [struct.unpack_from('<i', frame)[0] for frame in history]
    assert steps == list(range(1, 41))
    connection.close()
    batch.close()


def test_live_stream_through_the_server(render_home):
    batch = cuju.BatchEnvironment('5_vs_5_l4_r0', environment_count=1, device='cpu')
    source = cuju.render.watch(batch, backlog=True)
    batch.reset()
    for step in range(5):
        batch.step(actions_at(step, 1, 4, 19))
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        listed = json.loads(_get(f'http://127.0.0.1:{port}', '/api/live')[1])
        assert [entry['id'] for entry in listed] == [source.identifier]
        connection = _server.http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        connection.request('GET', f'/api/live/{source.identifier}/stream')
        response = connection.getresponse()
        assert response.status == 200
        assert response.read(8) == _recording.MAGIC
        connection.close()
        # The relay passes on a request for numbered frames.
        connection = _server.http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        connection.request('GET', f'/api/live/{source.identifier}/stream?sequence=1')
        response = connection.getresponse()
        assert _recording._parse_header(response)['stream_sequence'] == 1
        connection.close()
        provenance = _recording._parse_header(io.BytesIO(source._header()))['provenance']
        assert provenance == {'source': 'live', 'environment': 0, 'cuju_version': cuju.__version__}
    finally:
        server.shutdown()
        server.server_close()
        source.close()
    # A closed source lets go of its batch.
    assert source not in batch.observers
    batch.close()


def test_recorder_keeps_the_final_goal_with_automatic_resets(render_home):
    batch = cuju.BatchEnvironment(
        'academy_empty_goal_close_l1_r0', environment_count=1, device='cpu'
    )
    recorder = cuju.render.Recorder(batch)
    batch.reset()
    recorder.capture()
    step = 0
    while not recorder.saved:
        _, reward, done, _ = batch.step(torch.tensor([[12 if step % 3 else 5]], dtype=torch.int32))
        recorder.capture(done)
        step += 1
    scored = float(reward[0, 0]) > 0
    last = list(_recording.frames(recorder.saved[0]))[-1]
    assert struct.unpack_from('<2i', last, 8) == ((1, 0) if scored else (0, 0))
    assert struct.unpack_from('<i', last, 28)[0] & 1


@pytest.mark.parametrize('auto_reset', [True, False])
def test_recorder_captures_by_itself_as_by_hand(render_home, auto_reset):
    recorded = []
    for by_hand in (False, True):
        batch = cuju.BatchEnvironment(
            'academy_empty_goal_close_l1_r0',
            environment_count=2,
            device='cpu',
            seed=3,
            auto_reset=auto_reset,
        )
        recorder = cuju.render.Recorder(batch, environment=1)
        assert recorder in batch.observers
        batch.reset()
        if by_hand:
            recorder.capture()
        step = 0
        while len(recorder.saved) < 2:
            actions = torch.tensor([[12 if step % 3 else 5]] * 2, dtype=torch.int32)
            _, _, done, _ = batch.step(actions)
            if by_hand:
                recorder.capture(done)
            if not auto_reset and bool(done.any()):
                # The reset clears the done flags that `done` views.
                ended = bool(done[1])
                batch.reset_done()
                if by_hand and ended:
                    recorder.capture()
            step += 1
        # A reset of the other environment adds no frame to the recording of this one.
        frames = len(recorder._frames)
        batch.reset(mask=[True, False])
        assert len(recorder._frames) == frames
        recorded.append([list(_recording.frames(path)) for path in recorder.saved])
        batch.close()
    assert recorded[0] == recorded[1]


def test_game_actions_are_the_actions_of_a_batch(render_home):
    """A game plays exactly the match that a batch plays for the same actions."""
    from cuju.render._playing.game import Game

    game = Game('5_vs_5', (True, True), ability=(0.3, None), seed=5)
    keys = [('right', 'sprint'), ('up',), (), ('shot',), ('left', 'down'), ('dribble',)]
    for step in range(60):
        held = frozenset(keys[(step // 5) % len(keys)])
        game.step({0: (held, frozenset()), 1: (held, frozenset({'short_pass'}))})
    batch = cuju.BatchEnvironment(
        '5_vs_5_l1_r1',
        environment_count=1,
        representation='raw',
        seed=5,
        auto_reset=False,
        device='cpu',
        difficulty=[(0.3, None)],
    )
    batch.reset()
    for row in game.actions:
        batch.step(torch.tensor([row], dtype=torch.int32))
    assert batch.get_state(0) == game.batch.get_state(0)
    assert len({tuple(row) for row in game.actions}) > 3
    # Each frame marks the players that the people control, one a side.
    start = _recording._FRAME_HEAD.size + 10 * 14 * 14
    for frame in game.frames[1:]:
        controlled = [k for k in range(10) if frame[start + k] & 8]
        assert len(controlled) == 2
        assert {game.lineup[k]['team'] for k in controlled} == {0, 1}
    provenance = _recording.read_header(game.save())['provenance']
    assert provenance == {
        'source': 'human_game',
        'seed': 5,
        'scenario': '5_vs_5',
        'humans': [True, True],
        'teams': ['builtin', 'builtin'],
        'agent_counts': [1, 1],
        'action_set': 'default',
        'ability': [team['ability'] for team in game.teams],
        'cuju_version': cuju.__version__,
    }
    batch.close()
    game.close()


def test_recording_provenance_preserves_frame_format():
    head = _recording.header('Match', 'custom', [], provenance={'source': 'recorder'})
    document = _recording._parse_header(io.BytesIO(head))
    assert document['version'] == 1
    assert len(head) % 4 == 0
    assert document['provenance'] == {'source': 'recorder', 'cuju_version': cuju.__version__}
    document.pop('provenance')
    text = json.dumps(document).encode()
    old = _recording.MAGIC + struct.pack('<I', len(text)) + text
    assert 'provenance' not in _recording._parse_header(io.BytesIO(old))
    for seed, kept in ((2**53 - 1, 2**53 - 1), (2**53, str(2**53)), (2**64 - 1, str(2**64 - 1))):
        large = _recording.header('Match', 'custom', [], provenance={'seed': seed})
        assert _recording._parse_header(io.BytesIO(large))['provenance']['seed'] == kept


def _moved(document, frames, team, steps):
    """Returns the change of y of each player of `team` over `steps` steps, by index."""
    players = len(document['players'])
    start, end = frames[0], frames[steps]
    head = _recording._FRAME_HEAD.size
    moves = {}
    for k, entry in enumerate(document['players']):
        if entry['team'] != team:
            continue
        y0 = struct.unpack_from('<h', start, head + k * 196 + 2)[0]
        y1 = struct.unpack_from('<h', end, head + k * 196 + 2)[0]
        moves[entry['index']] = (y1 - y0) / _recording.POSITION_SCALE
    assert len(moves) == (5 if players == 10 else 11)
    return moves


@pytest.mark.parametrize(
    ('format', 'scenario', 'control', 'moving'),
    [
        ('5v5', '5_vs_5', {'players': 4, 'goalkeeper': 'agent'}, range(1, 5)),
        ('11v11', '11_vs_11_kaggle', {'players': 10, 'goalkeeper': 'builtin'}, range(1, 11)),
    ],
)
def test_team_controls_several_players(
    render_home, tmp_path, monkeypatch, format, scenario, control, moving
):
    """Each controlled player follows its own action, and the goalkeeper stays with the AI."""
    _short_matches(monkeypatch, 60)
    team = _toy_team(tmp_path, 'several', _SEVERAL, format, control)
    path = cuju.render.play(team['id'], 'builtin', scenario, seed=2)
    document, frames = _frames(path)
    moves = _moved(document, frames, 0, 60)
    # Odd players run up the pitch, towards positive y, and even players down.
    obeyed = [index for index in moving if (moves[index] > 1) == bool(index % 2)]
    assert len(obeyed) >= len(moving) - 1, moves
    assert all(abs(moves[index]) > 1 for index in obeyed)
    # Every frame marks the controlled players of the left team, and none of the right.
    head = _recording._FRAME_HEAD.size + len(document['players']) * 196
    marked = {
        k for frame in frames[1:] for k in range(len(document['players'])) if frame[head + k] & 8
    }
    assert {document['players'][k]['team'] for k in marked} == {0}


@pytest.mark.parametrize('reverse', [0, 1])
def test_recorded_engine_scorer_and_called_offside(monkeypatch, reverse):
    batch = cuju.BatchEnvironment('5_vs_5_l1_r0', environment_count=1, device='cpu')
    try:
        batch.reset(reverse=[reverse])
        reader = _recording.StateReader(10)
        state = batch.get_state(0)
        values = reader._values(state, 'pitch')
        values = {name: values[name].copy() for name in values.dtype.names}
        values.update(
            buffer_active=True,
            set_piece=3,
            foul_type=0,
            offside_count=2,
            offside_first=1,
            touch_team=0,
            scorer=7,
        )
        first = reader._order(values)[0][0]
        values['touch_first' if first == 0 else 'touch_second'] = 3
        monkeypatch.setattr(reader, '_values', lambda state, frame: values)
        frame = reader.frame(state)
        flags = struct.unpack_from('<i', frame, 28)[0]
        assert flags & 4
        assert (flags >> 8) & 31 == 8
        assert struct.unpack_from('<i', frame, 72)[0] == 3
    finally:
        batch.close()


@pytest.mark.parametrize(
    'duration,second,expected',
    [(3000, 1500, 1500), (400, 999999999, None), (100, 1500, None)],
)
def test_recording_scenario_timing(monkeypatch, duration, second, expected):
    monkeypatch.setattr(
        _recording._state, 'read', lambda state, fields: [duration, second, False, False, False]
    )
    timing = _recording.scenario_timing(b'')
    document = _recording._parse_header(
        io.BytesIO(_recording.header('Match', 'custom', [], timing=timing))
    )
    assert document['second_half'] == expected
    assert document['duration'] == duration
    assert document['full_match'] == (duration >= 3000)


def test_new_home_gets_the_samples_once(render_home, monkeypatch):
    _serve_once(monkeypatch)
    assert _library_ids() == _SAMPLES
    for entry in _library.matches():
        assert entry['title'].startswith('Sample match')
        assert entry['folder'] == ''
        assert (
            entry['steps'] == _recording.read_header(_library.path_of(entry['id']))['frame_count']
        )
    _serve_once(monkeypatch)
    assert _library_ids() == _SAMPLES
    assert sorted(path.name for path in (render_home / 'matches').iterdir()) == sorted(
        f'{name}.{suffix}' for name in _SAMPLES for suffix in ('cjr', 'json')
    )


def test_recording_identifiers_are_unique_within_a_second(render_home, monkeypatch):
    data = gzip.decompress((_library._SAMPLES / 'sample-5v5.cjr').read_bytes())
    (length,) = struct.unpack_from('<I', data, len(_recording.MAGIC))
    end = len(_recording.MAGIC) + 4 + length
    size = json.loads(data[len(_recording.MAGIC) + 4 : end])['frame_bytes']
    head, frames = data[:end], [data[end + k * size : end + (k + 1) * size] for k in range(3)]
    _one_second(monkeypatch)
    saved = []

    def save_many():
        for _ in range(10):
            saved.append(_library.save(head, frames).stem)

    workers = [threading.Thread(target=save_many) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(60)
    assert len(saved) == len(set(saved)) == 40
    assert sorted(saved) == _library_ids()
    for name in saved:
        assert list(_recording.frames(_library.path_of(name))) == frames
        assert _library.details(name)['steps'] == 3


@pytest.mark.parametrize('name,players', [('sample-11v11', 22), ('sample-5v5', 10)])
def test_bundled_samples_are_full_recordings(name, players):
    path = _library._SAMPLES / f'{name}.cjr'
    document = _recording.read_header(path)
    frames = list(_recording.frames(path))
    assert len(document['players']) == players
    assert len(frames) == document['frame_count'] == 3002
    assert all(len(frame) == document['frame_bytes'] for frame in frames)
    assert struct.unpack_from('<i', frames[-1], 28)[0] & 1
    assert document['title'].startswith('Sample match')
    left, right = document['teams']
    assert left['name'] != right['name'] and left['color'] != right['color']
    assert sum(struct.unpack_from('<2i', frames[-1], 8)) >= 2
