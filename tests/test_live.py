# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of live sources, the grid of environments, show() and notebooks."""

import cuju
import cuju.errors
import cuju.state
from conftest import actions_at, tensor_bytes
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
