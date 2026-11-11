# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the public names of `cuju.render`."""

import gzip
import json
import logging
import os
import re
import struct
import subprocess
import sys
import time

import numpy as np
import pytest
import torch

import cuju
import cuju.errors
import cuju.state
from conftest import actions_at, tensor_bytes
from support.common import (
    _SEVERAL,
    _control,
    _filtered_episodes,
    _get,
    _goals,
    _short_challenges,
    _short_matches,
    _toy_team,
)


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
    assert source not in batch.observers
    batch.close()


def test_live_environment_switch_changes_no_output(render_home):
    """A switch changes the environment that the source reads, never the batch."""
    outputs = []
    choices = {15: 2, 30: 0, 45: 1}
    for watched in (False, True):
        batch = cuju.BatchEnvironment('5_vs_5_l4_r0', environment_count=3, device='cpu', seed=5)
        source = cuju.render.watch(batch, environment=0, backlog=True) if watched else None
        seen = [tensor_bytes(batch.reset())]
        for step in range(60):
            if source is not None and step in choices:
                source.select_environment(choices[step])
            observation, reward, done, _ = batch.step(actions_at(step, 3, 4, 19))
            seen += [tensor_bytes(observation), tensor_bytes(reward), tensor_bytes(done)]
        seen += [batch.get_state(index) for index in range(3)]
        outputs.append(seen)
        if source is not None:
            assert source.environment == 1 and source._generation == 3
            assert source._history
        batch.close()
    assert outputs[0] == outputs[1]


def test_live_environment_switch_survives_a_failed_announcement(render_home, monkeypatch, caplog):
    import pathlib

    batch = cuju.BatchEnvironment('5_vs_5_l1_r0', environment_count=2, device='cpu')
    try:
        source = cuju.render.watch(batch, backlog=True)
        batch.reset()
        actions = torch.zeros((2, 1), dtype=torch.int32)
        batch.step(actions)

        def full_disk(self, target):
            raise OSError(28, 'No space left on device')

        source.select_environment(1)
        with monkeypatch.context() as patch, caplog.at_level(logging.WARNING, logger='cuju'):
            patch.setattr(pathlib.Path, 'replace', full_disk)
            batch.step(actions)
            batch.step(actions)
        warnings = [record for record in caplog.records if record.name == 'cuju']
        assert len(warnings) == 1
        assert 'could not announce environment 1' in warnings[0].getMessage()
        # The source still runs, shows the new environment, and leaves no partial file behind.
        assert source in batch.observers
        assert source.environment == 1 and len(source._history) == 2
        assert not list((render_home / 'live').glob('*.part'))
        assert json.loads(source._announcement.read_text())['environment'] == 0
        batch.step(actions)
        assert len(source._history) == 3
    finally:
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


@pytest.mark.skipif(os.name != 'posix', reason='sends SIGINT as Ctrl+C does')
def test_demo_starts_its_server_and_ends_cleanly_on_ctrl_c(render_home):
    """Without a server the demo starts one, and Ctrl+C ends the match, the server and itself."""
    import signal
    import subprocess
    import sys

    process = subprocess.Popen(
        [sys.executable, '-m', 'cuju.render', 'demo', '--port', '0', '--no-open'],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        address = None
        for line in process.stdout:
            if 'serves http://' in line:
                address = line[line.index('http://') :].split()[0]
            if 'Ctrl+C' in line:
                break
        assert address and '#live=' in line
        assert len(json.loads(_get(address, 'api/live')[1])) == 1
        process.send_signal(signal.SIGINT)
        assert process.wait(30) == 0
        assert 'stopped' in process.stdout.read()
        assert not list((render_home / 'live').glob('*.json'))
        with pytest.raises(OSError):
            _get(address, 'api/info')
    finally:
        if process.poll() is None:
            process.kill()


def test_recorder_keeps_every_nth_episode_and_a_reward_threshold(render_home):
    episodes, kept, _, _ = _filtered_episodes(every=3)
    assert kept == episodes[::3]
    episodes, kept, _, _ = _filtered_episodes(min_reward=0.5)
    # GRF: the left team's agent receives 1 for its goal, the scenario's only reward.
    assert kept == [frames for frames in episodes if struct.unpack_from('<i', frames[-1], 8)[0]]


def test_recorder_keeps_what_a_function_chooses_from_the_summary(render_home):
    episodes, kept, seen, _ = _filtered_episodes(keep='record')
    assert [summary['episode'] for summary in seen] == list(range(len(episodes)))
    for summary, frames in zip(seen, episodes, strict=True):
        assert summary['length'] == len(frames)
        assert summary['score'] == list(struct.unpack_from('<2i', frames[-1], 8))
        assert summary['goals'] == _goals(frames)
        assert summary['steps'] == struct.unpack_from('<i', frames[-1], 0)[0]
        assert summary['environment'] == 0
        assert summary['reward'] == sum(summary['rewards']) == summary['score'][0]
    assert kept == [frames for frames in episodes if len(frames) % 2 == 0]


def test_recorder_filters_refuse_invalid_values(render_home):
    batch = cuju.BatchEnvironment(
        'academy_empty_goal_close_l1_r0', environment_count=1, device='cpu'
    )
    for options in (
        {'keep': 'shots'},
        {'every': 0},
        {'every': 1.5},
        {'min_reward': float('nan')},
        {'min_reward': 'high'},
    ):
        with pytest.raises(cuju.errors.ArgumentError):
            cuju.render.Recorder(batch, **options)
    batch.close()


def test_recorder_filters_leave_the_outputs_as_they_were(render_home):
    """A batch steps the same bits with a filtering recorder as with none."""
    outputs = []
    for watched in (False, True):
        batch = cuju.BatchEnvironment(
            'academy_empty_goal_close_l1_r0', environment_count=2, device='cpu', seed=4
        )
        if watched:
            cuju.render.Recorder(batch, keep=lambda summary: summary['goals'] > 0, every=2)
        steps = [batch.reset().clone()]
        for step in range(120):
            observation, reward, done, _ = batch.step(actions_at(step, 2, 1, 19))
            steps.append((observation.clone(), reward.clone(), done.clone()))
        steps.append(batch.get_state(0))
        outputs.append(steps)
        batch.close()
    assert torch.equal(outputs[0][0], outputs[1][0])
    for first, second in zip(outputs[0][1:-1], outputs[1][1:-1], strict=True):
        assert all(torch.equal(a, b) for a, b in zip(first, second, strict=True))
    assert outputs[0][-1] == outputs[1][-1]


def test_recorder_annotate_refuses_invalid_input(render_home):
    batch = cuju.BatchEnvironment(
        'academy_empty_goal_close_l1_r0', environment_count=1, device='cpu'
    )
    recorder = cuju.render.Recorder(batch)
    with pytest.raises(cuju.errors.ArgumentError):
        recorder.annotate(text='before the first step')
    batch.reset()
    for options in (
        {},
        {'player': 1},
        {'text': 'x', 'player': 99},
        {'text': 'x', 'player': (1, 5)},
        {'values': {'value': float('nan')}},
        {'values': {'': 1.0}},
        {'values': {f'v{k}': k for k in range(17)}},
        {'text': 3},
        {'action': -1},
        {'probabilities': 'likely'},
        {'probabilities': [0.5, float('inf')]},
        {'text': 'x', 'step': 7},
    ):
        with pytest.raises(cuju.errors.ArgumentError):
            recorder.annotate(**options)
    recorder.annotate(text='a' * 300)
    assert recorder._notes[(0, -1)]['t'] == 'a' * 200
    batch.close()


def test_annotations_leave_the_outputs_as_they_were(render_home):
    outputs = []
    for watched in (False, True):
        batch = cuju.BatchEnvironment(
            'academy_empty_goal_close_l1_r0', environment_count=1, device='cpu', seed=4
        )
        recorder = cuju.render.Recorder(batch) if watched else None
        source = cuju.render.watch(batch, backlog=True) if watched else None
        steps = [batch.reset().clone()]
        for step in range(60):
            if watched:
                recorder.annotate(values={'value': step}, text=f'step {step}', player=0)
                source.annotate(values={'value': step}, player=0)
            observation, reward, done, _ = batch.step(actions_at(step, 1, 1, 19))
            steps.append((observation.clone(), reward.clone(), done.clone()))
        steps.append(batch.get_state(0))
        outputs.append(steps)
        if source:
            source.close()
        batch.close()
    assert torch.equal(outputs[0][0], outputs[1][0])
    for first, second in zip(outputs[0][1:-1], outputs[1][1:-1], strict=True):
        assert all(torch.equal(a, b) for a, b in zip(first, second, strict=True))
    assert outputs[0][-1] == outputs[1][-1]


def test_policy_errors_are_public_and_quiet(render_home, monkeypatch, capsys):
    """A failing policy raises the public PolicyError in one line, with a traceback on request."""
    _short_challenges(monkeypatch, 4)
    assert issubclass(cuju.render.PolicyError, cuju.errors.Error)
    assert issubclass(cuju.render.PolicyError, RuntimeError)
    assert 'PolicyError' in cuju.render.__all__
    message = 'the policy of wild failed, it answered the action 99, outside its action set of 19'
    with pytest.raises(cuju.render.PolicyError, match=re.escape(message)) as caught:
        cuju.render.challenge('corner', policy=lambda obs: [99], name='wild', attempts=1)
    assert str(caught.value).endswith('actions, 0 to 18')
    assert isinstance(caught.value.__cause__, IndexError)
    assert 'Traceback' not in capsys.readouterr().err
    monkeypatch.setenv('CUJU_RENDER_DEBUG', 'on')
    with pytest.raises(cuju.render.PolicyError):
        cuju.render.challenge('corner', policy=lambda obs: [99], name='wild', attempts=1)
    assert 'Traceback' in capsys.readouterr().err


def test_watch_checks_the_environment_before_closing_the_earlier_source(render_home):
    batch = cuju.BatchEnvironment('5_vs_5', environment_count=2, device='cpu', seed=3)
    try:
        source = cuju.render.watch(batch)
        assert repr(source).startswith(f'LiveSource({source.identifier!r}, environment 0 of 2')
        with pytest.raises(cuju.errors.ArgumentError, match='from 0 to 1, found 5'):
            cuju.render.watch(batch, environment=5)
        with pytest.raises(cuju.errors.ArgumentError, match='as an integer'):
            cuju.render.watch(batch, environment=1.5)
        # The mistake leaves the earlier source streaming and listed.
        assert not source._closed and source in batch.observers
        source.close()
        assert repr(source).endswith('closed)')
    finally:
        batch.close()


def test_recorder_repr_names_its_state(render_home):
    batch = cuju.BatchEnvironment(
        'academy_empty_goal_close_l1_r0', environment_count=1, device='cpu'
    )
    recorder = cuju.render.Recorder(batch)
    batch.reset()
    batch.step(torch.tensor([[5]], dtype=torch.int32))
    shown = repr(recorder)
    assert shown.startswith('Recorder(environment 0, ') and 'version 2, capturing, ' in shown
    assert '2 frames of the current episode, 0 episodes ended, 0 saved, 0 dropped)' in shown
    recorder.close()
    assert 'detached, 0 frames' in repr(recorder) and '1 saved' in repr(recorder)
    batch.close()


@pytest.mark.skipif(os.name != 'posix', reason='sends SIGINT to the group as Ctrl+C does')
def test_demo_ends_within_about_a_second_of_ctrl_c(render_home):
    """Ctrl+C reaches the command, the match and the server, and all of them end at once."""
    import contextlib
    import signal

    process = subprocess.Popen(
        [sys.executable, '-m', 'cuju.render', 'demo', '--port', '0', '--no-open'],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        for line in process.stdout:
            if 'Ctrl+C' in line:
                break
        time.sleep(1)
        started = time.monotonic()
        os.killpg(process.pid, signal.SIGINT)
        assert process.wait(30) == 0
        took = time.monotonic() - started
        assert took < 2.5, took
        assert not list((render_home / 'live').glob('*.json'))
        time.sleep(0.5)
        with pytest.raises(ProcessLookupError):
            os.killpg(process.pid, 0)
    finally:
        if process.poll() is None:
            process.kill()
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
