# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the public names of `cuju.render`."""

import gzip
import json
import struct

import numpy as np
import pytest
import torch

import cuju
import cuju.errors
import cuju.state
from conftest import actions_at
from support.common import _SEVERAL, _control, _short_matches, _toy_team


def test_layout_offsets():
    layout = cuju.state.layout()
    position = layout['match.players[0].base.humanoid.nodes[0].position']
    assert (position.size, position.type) == (12, 'N7blunted7Vector3E')
    # GRF: a node holds 44 bytes, so the fourteen nodes of a player lie one after another.
    last = layout['match.players[0].base.humanoid.nodes[13].position']
    assert last.offset - position.offset == 13 * 44
    assert layout['match.goalCount[1]'].offset == layout['match.goalCount[0]'].offset + 4
    assert all(field.offset >= 0 and field.size > 0 for field in layout.values())


def test_gather_refuses_bad_input():
    with pytest.raises(cuju.StateError):
        cuju.state.gather(b'abc', ['environment.step'])
    batch = cuju.BatchEnvironment('5_vs_5_l1_r0', environment_count=1, device='cpu')
    batch.reset()
    state = batch.get_state(0)
    with pytest.raises(cuju.ArgumentError):
        cuju.state.gather(state, ['no.such.field'])
    with pytest.raises(cuju.ChoiceError):
        cuju.state.gather(state, ['environment.step'], frame='mirror')


def test_every_field_reads_and_mirrored_arrays_agree():
    layout = cuju.state.layout()
    batch = cuju.BatchEnvironment('5_vs_5_l4_r0', environment_count=2, device='cpu', seed=3)
    batch.reset(reverse=[0, 1])
    for step in range(30):
        batch.step(actions_at(step, 2, 4, 19))
    for environment in range(2):
        state = batch.get_state(environment)
        # Every field of the layout lies inside the match, so all of them read at once.
        assert len(cuju.state.gather(state, list(layout.values()))) == sum(
            field.size for field in layout.values()
        )
        position, prediction = cuju.state.read(
            state, ['match.ball.positionBuffer', 'match.ball.predictions[0]'], frame='pitch'
        )
        assert np.sign(position[:2]).tolist() == np.sign(prediction[:2]).tolist()


def test_stacked_batch_shows_and_a_failing_source_spares_the_step(render_home, monkeypatch):
    batch = cuju.BatchEnvironment('5_vs_5_l1_r0', environment_count=2, device='cpu', stacked=True)
    source = cuju.render.watch(batch, backlog=True)
    batch.reset()
    batch.step(torch.zeros((2, 1), dtype=torch.int32))
    assert len(source._history) == 1

    def fail(done):
        raise OSError('disk full')

    monkeypatch.setattr(source, 'after_step', fail)
    batch.step(torch.zeros((2, 1), dtype=torch.int32))
    assert batch._live is None
    batch.close()


def test_ability_sets_the_difficulty_that_plays(render_home):
    path = cuju.render.play(
        'builtin', 'builtin', 'academy_empty_goal_close', seed=3, ability=(0.2, None)
    )
    raw = gzip.decompress(path.read_bytes())
    (length,) = struct.unpack_from('<I', raw, 8)
    header = json.loads(raw[12 : 12 + length])
    # The left plays the ability given, the right the scenario's own.
    assert header['teams'][0]['ability'] == 0.2
    assert 0 <= header['teams'][1]['ability'] <= 1
    with pytest.raises(cuju.errors.ArgumentError):
        cuju.render.play('builtin', 'builtin', 'academy_empty_goal_close', ability=(-0.1, None))


@pytest.mark.parametrize(
    ('scenario', 'control', 'message'),
    [
        ('5_vs_5', _control(5), 'only 4 controllable players'),
        ('academy_3_vs_1_with_keeper', _control(5), 'only 4 controllable players'),
        ('11_vs_11_kaggle', _control(1, 'fixed', ['AM'], 'builtin'), 'cannot select player AM'),
        (
            'benchmark_full_game_11_vs_11_easy',
            _control(1, 'fixed', ['GK'], 'agent'),
            'cannot select player GK',
        ),
        ('11_vs_11_kaggle', _control(1, 'fixed', ['CF']), 'controllable goalkeeper'),
    ],
)
def test_team_scenario_refusal(render_home, tmp_path, scenario, control, message):
    """A refused match identifies the scenario and the conflicting setting."""
    format = '5v5' if scenario == '5_vs_5' else '11v11'
    team = _toy_team(tmp_path, 'refused', _SEVERAL, format, control)
    with pytest.raises(cuju.ArgumentError, match=message) as caught:
        cuju.render.play(team['id'], 'builtin', scenario, seed=1)
    assert scenario in str(caught.value)


def test_default_submission_rejects_builtin_action(render_home, tmp_path, monkeypatch):
    """Each submission uses its own action range in a mixed action set match."""
    _short_matches(monkeypatch, 1)
    default = _toy_team(tmp_path, 'default', 'def agent(obs):\n    return [19]\n', '5v5')
    v2 = _toy_team(
        tmp_path, 'v2', 'def agent(obs):\n    return [19]\n', '5v5', _control(1, action_set='v2')
    )
    with pytest.raises(IndexError, match='to 18'):
        cuju.render.play(default['id'], v2['id'], '5_vs_5', seed=1)
