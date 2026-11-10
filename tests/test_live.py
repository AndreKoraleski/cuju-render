# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of live sources, the grid of environments, show() and notebooks."""

import io
import json
import struct

import numpy as np
import pytest
import torch

import cuju
import cuju.errors
import cuju.state
from conftest import actions_at, tensor_bytes
from cuju.render._format import recording as _recording
from cuju.render._http import server as _server
from cuju.render._watch import grid as _grid
from cuju.render._watch import live as _live


def test_watching_changes_no_output(device, render_home):
    """A batch that a viewer watches returns the same bits as one that nobody watches."""
    outputs = []
    for watched in (False, True):
        batch = cuju.BatchEnvironment('5_vs_5_l4_r0', environment_count=2, device=device, seed=11)
        viewer = None
        if watched:
            source = cuju.render.watch(batch, environment=1)
            viewer = _live._Viewer()
            source._viewers.append(viewer)
        outputs_seen = [tensor_bytes(batch.reset())]
        for step in range(120):
            if viewer is not None:
                while not viewer.frames.empty():
                    viewer.frames.get_nowait()
            observation, reward, done, _ = batch.step(actions_at(step, 2, 4, 19).to(device))
            outputs_seen += [tensor_bytes(observation), tensor_bytes(reward), tensor_bytes(done)]
        outputs_seen += [batch.get_state(0), batch.get_state(1)]
        outputs.append(outputs_seen)
        if watched:
            assert viewer.header is not None
        batch.close()
    assert outputs[0] == outputs[1]


def test_render_variable_changes_no_digest(monkeypatch, render_home):
    plain = cuju.digest('5_vs_5_l4_r0', steps=60)
    monkeypatch.setenv(_live.LIVE_VARIABLE, 'on')
    assert cuju.digest('5_vs_5_l4_r0', steps=60) == plain
    assert not list((render_home / 'live').glob('*.json'))


def _numbered(response, header):
    """Returns the serial and the frame that a numbered stream sends next, or the end marker."""
    (serial,) = struct.unpack('<Q', response.read(8))
    if serial == _live.END:
        return serial, b''
    return serial, response.read(header['frame_bytes'])


def test_live_numbered_stream_resumes_with_the_same_serials(render_home):
    batch = cuju.BatchEnvironment('5_vs_5_l1_r0', environment_count=1, device='cpu')
    source = cuju.render.watch(batch, backlog=True)
    batch.reset()
    actions = torch.zeros((1, 1), dtype=torch.int32)
    connections = []

    def open_stream(path):
        connection = _server.http.client.HTTPConnection('127.0.0.1', source.port, timeout=10)
        connections.append(connection)
        connection.request('GET', path)
        response = connection.getresponse()
        assert response.status == 200
        return response, _recording._parse_header(response)

    try:
        for _ in range(3):
            batch.step(actions)
        first, header = open_stream('/stream?sequence=1')
        assert header['stream_sequence'] == 1
        assert header['stream_id'] == f'{source.identifier}:0'
        received = dict(_numbered(first, header) for _ in range(3))
        assert sorted(received) == [0, 1, 2]
        # The connection is lost, the batch steps on, and a new connection resumes the stream.
        connections[0].close()
        for _ in range(2):
            batch.step(actions)
        again, header_again = open_stream('/stream?sequence=1')
        assert header_again['stream_id'] == header['stream_id']
        resumed = dict(_numbered(again, header) for _ in range(5))
        assert sorted(resumed) == [0, 1, 2, 3, 4]
        assert all(resumed[serial] == received[serial] for serial in received)
        # A viewer that asks for no serials receives the frames as 0.2.0 sends them.
        plain, plain_header = open_stream('/stream')
        assert 'stream_sequence' not in plain_header and 'stream_id' not in plain_header
        assert plain.read(header['frame_bytes']) == resumed[0]
        # The history and its serials stay within ten seconds of steps, side by side.
        for _ in range(_live._HISTORY + 5):
            batch.step(actions)
        assert len(source._history) == len(source._serials) == _live._HISTORY
        assert list(source._serials) == list(range(10, 10 + _live._HISTORY))
        source.close()
        # The numbered stream ends with its marker, the plain one simply closes.
        serial = None
        while serial != _live.END:
            serial, _ = _numbered(again, header)
        while plain.read(1 << 16):
            pass
    finally:
        for connection in connections:
            connection.close()
        source.close()
        batch.close()


def test_live_environment_switch_waits_for_step_and_resets_history(render_home):
    batch = cuju.BatchEnvironment('5_vs_5_l1_r0', environment_count=2, device='cpu')
    try:
        source = cuju.render.watch(batch, backlog=True)
        batch.reset()
        actions = torch.zeros((2, 1), dtype=torch.int32)
        batch.step(actions)
        batch.step(actions)
        assert len(source._history) == 2
        viewer = _live._Viewer(sequence=True)
        source._viewers.append(viewer)
        source.select_environment(1)
        # The choice waits for the end of the next step.
        assert source.environment == 0 and source._viewers == [viewer]
        batch.step(actions)
        assert source.environment == 1
        assert source._generation == 1
        assert source.title.startswith('5_vs_5_l1_r0, environment 1,')
        assert len(source._history) == 1
        assert list(source._serials) == [0]
        # The stream of the last environment ended, without frames of the new one.
        assert viewer.frames.get_nowait() is None and viewer not in source._viewers
        announcement = json.loads(source._announcement.read_text())
        assert announcement['environment'] == 1 and announcement['generation'] == 1
        assert announcement['environment_count'] == 2
        header = _recording._parse_header(io.BytesIO(source._header(True)))
        assert header['stream_id'] == f'{source.identifier}:1'
        assert header['environment_count'] == 2
        assert header['provenance']['environment'] == 1
        # Choosing the environment that shows withdraws a choice that waits.
        source.select_environment(0)
        source.select_environment(1)
        batch.step(actions)
        assert source.environment == 1 and source._generation == 1
        for invalid in (-1, 2, True, 0.5, '1', None):
            with pytest.raises(cuju.ArgumentError):
                source.select_environment(invalid)
        source.close()
        with pytest.raises(cuju.ArgumentError):
            source.select_environment(0)
    finally:
        batch.close()


def test_render_variable_attaches_a_source_as_an_observer(monkeypatch, render_home):
    monkeypatch.setenv(_live.LIVE_VARIABLE, '1')
    batch = cuju.BatchEnvironment('5_vs_5_l1_r0', environment_count=2, device='cpu')
    (source,) = batch.observers
    assert isinstance(source, _live.LiveSource) and source.environment == 1
    assert source._scenario == batch.scenario_name == '5_vs_5_l1_r0'
    assert list((render_home / 'live').glob('*.json'))
    # A source from `watch` takes the place of the one from the variable.
    watched = cuju.render.watch(batch)
    assert batch.observers == (watched,) and source._closed
    batch.close()
    assert watched._closed and not list((render_home / 'live').glob('*.json'))
    monkeypatch.setenv(_live.LIVE_VARIABLE, 'off')
    batch = cuju.BatchEnvironment('5_vs_5_l1_r0', environment_count=2, device='cpu')
    assert batch.observers == ()
    batch.close()


def test_live_close_with_full_viewer_queue(render_home):
    batch = cuju.BatchEnvironment('5_vs_5_l1_r0', environment_count=1, device='cpu')
    batch.reset()
    source = _live.LiveSource(batch, announce=False)
    viewer = _live._Viewer()
    for _ in range(_live._BUFFER):
        viewer.frames.put_nowait(b'frame')
    source._viewers.append(viewer)
    try:
        source.close()
        assert viewer.frames.get(timeout=1) is None
        assert viewer.frames.empty()
    finally:
        source.close()
        batch.close()


class _Clock:
    """A clock that a test moves by hand, for the pacing of the grid."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_grid_reads_only_while_asked_and_within_its_bounds(render_home, monkeypatch):
    monkeypatch.setattr(_grid, '_PER_STEP', 8)
    batch = cuju.BatchEnvironment('5_vs_5_l1_r0', environment_count=12, device='cpu', seed=3)
    try:
        source = cuju.render.watch(batch)
        grid = source._grid
        clock = grid._clock = _Clock()
        # Reads take no time on the test's clocks, so a loaded machine paces them as an idle one.
        grid._timer = lambda: 0.0
        batch.reset()
        actions = torch.zeros((12, 1), dtype=torch.int32)
        # Nobody asked, so the steps read nothing for the grid.
        for _ in range(3):
            batch.step(actions)
        assert grid.reads == 0 and not grid.watched
        document = grid.request(0, 12)
        assert document == {'environment_count': 12, 'first': 0, 'count': 12, 'tiles': [None] * 12}
        assert grid.watched
        # A step reads at most eight states here, and the next read waits until the grid has read
        # at most ten states a second and spent at most a twentieth of the wall time.
        batch.step(actions)
        assert grid.reads == _grid._PER_STEP
        assert clock.now + 8 / _grid._RATE <= grid._next < clock.now + 2
        batch.step(actions)
        assert grid.reads == _grid._PER_STEP
        # Without those bounds, the pass ends on the next step and the next pass waits its period.
        monkeypatch.setattr(_grid, '_SHARE', 1.0)
        monkeypatch.setattr(_grid, '_RATE', 1e9)
        clock.now += 1.0
        batch.step(actions)
        assert grid.reads == 12
        start = grid._pass_start
        clock.now = start + 1.4
        batch.step(actions)
        assert grid.reads == 20
        start = grid._pass_start
        clock.now = start + 0.1
        batch.step(actions)
        assert grid.reads == 24
        clock.now = start + 0.4
        batch.step(actions)
        assert grid.reads == 24
        clock.now = start + _grid._PERIOD + 0.01
        batch.step(actions)
        assert grid.reads == 32
        # Every tile holds its environment as the frame of a recording holds it.
        tiles = grid.request(0, 12)['tiles']
        assert [tile['environment'] for tile in tiles] == list(range(12))
        reader = _recording.StateReader(10)
        for index in (0, 7):
            tile = tiles[index]
            state = batch.get_state(index)
            frame = reader.frame(state)
            head = _recording._FRAME_HEAD.unpack_from(frame)
            assert tile['step'] == head[0] and tile['score'] == [head[2], head[3]]
            assert tile['clock'] == head[6] and tile['mode'] == head[1]
            assert np.allclose(tile['ball'], head[8:11], atol=0.006)
            nodes = np.frombuffer(frame, '<i2', 10 * 14 * 7, _recording._FRAME_HEAD.size)
            roots = nodes.reshape(10, 14, 7)[:, 0, :2] / _recording.POSITION_SCALE
            assert np.allclose(np.reshape(tile['players'], (10, 2)), roots, atol=0.006)
            teams = [entry['team'] for entry in reader.lineup(state)]
            assert tile['teams'] == teams and sorted(teams) == [0] * 5 + [1] * 5
            assert tile['active'] == [1] * 10
        # Another range keeps the tiles inside it and starts a pass of its own.
        document = grid.request(10, 64)
        assert document['count'] == 2
        assert [tile and tile['environment'] for tile in document['tiles']] == [10, 11]
        assert sorted(grid._tiles) == [10, 11]
        for first, count in ((12, 1), (-1, 1), (0, 0), (0, 65), (True, 1), (0, 1.5)):
            with pytest.raises(ValueError):
                grid.request(first, count)
        # A grid that nobody asks for again stops reading after a few seconds and forgets it all.
        clock.now += _grid._LINGER + 0.1
        reads = grid.reads
        batch.step(actions)
        batch.step(actions)
        assert grid.reads == reads and not grid.watched and not grid._tiles
    finally:
        batch.close()


def test_grid_changes_no_output(device, render_home, monkeypatch):
    """A batch whose grid a viewer watches returns the same bits as one that nobody watches."""
    monkeypatch.setattr(_grid, '_PERIOD', 0.0)
    monkeypatch.setattr(_grid, '_SHARE', 1e9)
    monkeypatch.setattr(_grid, '_RATE', 1e9)
    outputs = []
    for watched in (False, True):
        batch = cuju.BatchEnvironment('5_vs_5_l4_r0', environment_count=3, device=device, seed=7)
        source = cuju.render.watch(batch) if watched else None
        seen = [tensor_bytes(batch.reset())]
        for step in range(80):
            if source is not None:
                source._grid.request(0, 3)
            observation, reward, done, _ = batch.step(actions_at(step, 3, 4, 19).to(device))
            seen += [tensor_bytes(observation), tensor_bytes(reward), tensor_bytes(done)]
        seen += [batch.get_state(index) for index in range(3)]
        outputs.append(seen)
        if source is not None:
            # Every step read the whole grid.
            assert source._grid.reads == 80 * 3
        batch.close()
    assert outputs[0] == outputs[1]
