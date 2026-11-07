# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the team registry, its kits, styles, models and clips."""

import json

import pytest
import torch

import cuju
import cuju.errors
import cuju.state
from cuju.render._format import recording as _recording
from cuju.render._http import server as _server
from cuju.render._registry import teams as _teams
from support.common import _SEVERAL, _control, _frames, _short_matches, _toy_team


@pytest.mark.parametrize(
    'name', ['D:evil.py', '../out.py', '/etc/x', 'a\\b.py', 'a/../../b.py', 'a\x00b']
)
def test_hostile_member_names_are_refused(name):
    with pytest.raises(cuju.ArgumentError):
        _teams._check_member(name)


_SINGLE = """
def agent(obs):
    return [5 if obs['step'] % 7 else 12]
"""


def test_team_control_is_checked_and_travels(render_home, tmp_path):
    team = _toy_team(tmp_path, 'several', _SEVERAL, '11v11')
    assert team['control'] == _teams.DEFAULT_CONTROL
    for wrong in (
        {'players': 12},
        {'players': 0},
        {'players': True},
        {'players': 9, 'goalkeeper': 'builtin'},
        {'players': 10, 'goalkeeper': 'nobody'},
        {'players': 2, 'extra': 1},
    ):
        with pytest.raises(cuju.ArgumentError):
            _teams.update(team['id'], control=wrong)
    keeper = {'players': 10, 'goalkeeper': 'builtin'}
    team = _teams.update(team['id'], control=keeper)
    assert _teams.agent_count(team) == 11
    # A change of format that the control does not fit returns it to the default.
    assert _teams.update(team['id'], format='5v5')['control']['players'] == 1
    team = _teams.update(team['id'], format='11v11', control=keeper)
    _, archive = _teams.export(team['id'])
    copy = _teams.add('copy', 'copy.zip', archive)
    assert copy['control'] == _teams.check_control(keeper, '11v11')
    with pytest.raises(cuju.ArgumentError):
        _teams.add('wrong', 'main.py', b'def agent(obs):\n    return [0]\n', '5v5', {'players': 6})


def test_single_player_team_plays_as_before(render_home, tmp_path, monkeypatch):
    """A team of one controlled player plays the match of one agent, frame for frame."""
    from cuju.kaggle import KaggleAgent

    _short_matches(monkeypatch, 80)
    team = _toy_team(tmp_path, 'single', _SINGLE, '5v5')
    path = cuju.render.play(team['id'], 'builtin', '5_vs_5', seed=9)
    _, frames = _frames(path)
    batch = cuju.BatchEnvironment(
        '5_vs_5_l1_r0',
        environment_count=1,
        representation='raw',
        seed=9,
        auto_reset=False,
        device='cpu',
    )
    player = KaggleAgent(_teams.load_agent(team['id']), batch, 0)
    reader = _recording.StateReader(10)
    batch.reset()
    expected = [reader.frame(batch.get_state(0))]
    for step in range(80):
        batch.step(player.act().reshape(1, 1))
        expected.append(reader.frame(batch.get_state(0), 1 if step == 79 else 0))
    assert frames == expected
    batch.close()


@pytest.mark.parametrize(
    ('scenario', 'format', 'control', 'active', 'engine_count', 'side', 'opponent'),
    [
        ('5_vs_5', '5v5', _control(2), None, 2, 0, False),
        (
            '11_vs_11_kaggle',
            '11v11',
            _control(3, 'fixed', ['CF', 'CB', 'CB'], 'builtin'),
            [9, 2, 3],
            11,
            0,
            True,
        ),
        ('11_vs_11_kaggle', '11v11', _control(2, 'fixed', [0, 9], 'agent'), [0, 9], 11, 1, True),
        (
            'benchmark_full_game_11_vs_11_hard',
            '11v11',
            _control(10, 'fixed', list(range(1, 11))),
            list(range(1, 11)),
            10,
            0,
            False,
        ),
        ('5_vs_5', '5v5', _control(2, action_set='v2'), None, 2, 1, True),
        (
            'academy_3_vs_1_with_keeper',
            '11v11',
            _control(2, 'fixed', [3, 1], 'builtin'),
            [3, 1],
            4,
            0,
            True,
        ),
        (
            'academy_3_vs_1_with_keeper',
            '11v11',
            _control(1, 'fixed', ['CB'], 'builtin'),
            [1],
            2,
            1,
            False,
        ),
    ],
)
def test_team_assignments_match_engine(
    render_home,
    tmp_path,
    monkeypatch,
    scenario,
    format,
    control,
    active,
    engine_count,
    side,
    opponent,
):
    """Toy actions reach their selected players in either side of a mixed match."""
    from cuju.raw import grf_observation, team_sizes

    steps = 80
    _short_matches(monkeypatch, steps)
    source = f"""
expected = {active!r}
count = {control['players']}
hand = {control['action_set'] == 'v2'}

def agent(obs):
    players = [raw['active'] for raw in obs['players_raw']]
    assert obs['controlled_players'] == count
    assert expected is None or players == expected
    return [19 if hand and k == 0 else (3 if player % 2 else 7)
            for k, player in enumerate(players)]
"""
    team = _toy_team(tmp_path, 'selected', source, format, control)
    other = _toy_team(tmp_path, 'single', 'def agent(obs):\n    return [-1]\n', format)
    sides = [team['id'], other['id'] if opponent else 'builtin']
    if side:
        sides.reverse()
    path = cuju.render.play(*sides, scenario, seed=7, device='cpu')
    document, frames = _frames(path)
    counts = [engine_count, int(opponent)]
    if side:
        counts.reverse()
    extended = control['assignment'] == 'fixed' or control['action_set'] == 'v2'
    asset = str(_teams.scenario_path(scenario)) if scenario.startswith('benchmark_') else scenario
    batch = cuju.BatchEnvironment(
        asset,
        environment_count=1,
        representation='raw',
        seed=7,
        auto_reset=False,
        device='cpu',
        agent_counts=[tuple(counts)],
        action_set='v2' if extended else 'default',
    )
    try:
        batch.reset()
        reader = _recording.StateReader(len(document['players']))
        expected = [reader.frame(batch.get_state(0))]
        first = 0 if side == 0 else counts[0]
        for step in range(steps):
            raw = batch.raw()
            columns = list(range(first, first + engine_count))
            by_player = {
                int(
                    grf_observation(raw, 0, column, *team_sizes(batch, 0, column))['active']
                ): column
                for column in columns
            }
            # A step on which GRF hands the players out again leaves them to the built-in AI,
            # as the runner does.
            complete = len(by_player) == len(columns) and all(i in by_player for i in active or ())
            chosen = (
                columns
                if active is None
                else ([by_player[index] for index in active] if complete else [])
            )
            actions = torch.zeros((1, sum(counts)), dtype=torch.int32)
            if opponent:
                actions[0, counts[0] if side == 0 else 0] = 18
            for column in columns:
                actions[0, column] = 19
            for k, column in enumerate(chosen):
                player = int(
                    grf_observation(raw, 0, column, *team_sizes(batch, 0, column))['active']
                )
                actions[0, column] = (
                    19 if control['action_set'] == 'v2' and k == 0 else 3 if player % 2 else 7
                )
            _, _, done, _ = batch.step(actions)
            final = bool(done[0]) or step == steps - 1
            expected.append(reader.frame(batch.get_state(0), int(final)))
            if final:
                break
        assert frames == expected
    finally:
        batch.close()


def test_earlier_team_control_migrates(render_home, tmp_path):
    """Earlier metadata selects the same players after loading and export."""
    team = _toy_team(tmp_path, 'earlier', _SEVERAL, '11v11')
    meta = _teams._meta_path(team['id'])
    saved = json.loads(meta.read_text())
    saved['control'] = {'players': 10, 'goalkeeper': 'builtin'}
    meta.write_text(json.dumps(saved))
    control = _teams.entry(team['id'])['control']
    assert control == _control(10, 'fixed', list(range(1, 11)), 'builtin')
    _, archive = _teams.export(team['id'])
    assert _teams.add('copy', 'copy.zip', archive)['control'] == control
    saved['control'] = {'players': 2, 'goalkeeper': 'agent'}
    meta.write_text(json.dumps(saved))
    assert _teams.entry(team['id'])['control'] == _control(2)


@pytest.mark.parametrize('size', [5, 11])
@pytest.mark.parametrize(('level', 'difficulty'), [('easy', 0.05), ('medium', 0.6), ('hard', 1.0)])
def test_training_scenario_description(size, level, difficulty):
    """Training scenarios keep the upstream formation, timing and episode parity."""
    from cuju.scenarios import Builder, load_scenario

    name = f'benchmark_full_game_{size}_vs_{size}_{level}'
    assert name in _server._scenarios()
    build = load_scenario(_teams.scenario_path(name))
    configs = []
    for episode in (0, 1):
        builder = Builder(episode)
        build(builder)
        config = builder.config()
        assert config.game_duration == 3000
        assert config.second_half == 1500
        assert config.deterministic is False
        assert config.left_team_difficulty == difficulty
        assert config.right_team_difficulty == difficulty
        for formation in (config.left_team, config.right_team):
            assert len(formation) == size
            assert formation[0].role == 0
            assert formation[0].lazy is False
            assert formation[0].controllable is False
            assert all(player.controllable for player in formation[1:])
        configs.append(config)
    assert [p.key() for p in configs[0].left_team] == [p.key() for p in configs[1].right_team]
    assert [p.key() for p in configs[0].right_team] == [p.key() for p in configs[1].left_team]


def test_cli_team_archive_round_trip(render_home, tmp_path, capsys):
    """The command line imports its own export with the team settings intact."""
    from cuju.render.__main__ import main

    folder = tmp_path / 'submission'
    folder.mkdir()
    (folder / 'main.py').write_text('def agent(obs):\n    return [0]\n')
    assert main(['team', 'add', str(folder), '--name', 'Visitors', '--format', '5v5']) == 0
    team = _teams.teams()[-1]
    control = {'players': 2, 'assignment': 'fixed', 'selection': [1, 2]}
    team = _teams.update(team['id'], control=control)
    archive = tmp_path / 'team.zip'
    assert main(['team', 'export', team['id'], '--out', str(archive)]) == 0
    assert main(['team', 'add', str(archive)]) == 0
    copy = _teams.teams()[-1]
    assert copy['control'] == team['control']
    assert copy['style'] == team['style']
    assert copy['format'] == '5v5'
    assert copy['name'] == 'Visitors'
    assert main(['team', 'list']) == 0
    assert 'Visitors' in capsys.readouterr().out
    assert main(['team', 'remove', copy['id']]) == 0
    assert all(entry['id'] != copy['id'] for entry in _teams.teams())
    assert main(['team', 'add', str(tmp_path / 'missing.zip')]) == 1
    broken = tmp_path / 'broken.zip'
    broken.write_bytes(b'bad archive')
    assert main(['team', 'add', str(broken)]) == 1
