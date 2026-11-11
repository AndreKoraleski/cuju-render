# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of requested matches, games, the demo, challenges and achievements."""

import json
import logging
import struct
import time

import pytest
import torch

import cuju
import cuju.errors
import cuju.state
from cuju.render._format import recording as _recording
from cuju.render._http import server as _server
from cuju.render._registry import teams as _teams
from cuju.render._store import home as _home
from cuju.render._store import library as _library
from support.common import (
    _ACHIEVEMENT_PLAYERS,
    _CRASH,
    _SINGLE,
    _achievement_frames,
    _achievement_header,
    _challenge_frame,
    _challenge_frames,
    _frames,
    _person_recording,
    _shipped_language,
    _short_challenges,
    _short_matches,
    _toy_team,
)


def test_game_controller_follows_grf():
    """The keys of a step become GRF's actions as GRF's own controller turns them."""
    from cuju.render._playing.game import Controller, own_frame

    controller = Controller()
    none = frozenset()
    steps = [
        # A direction comes first, then stays held without a further action.
        ({'right'}, none),
        ({'right'}, none),
        # Up with right is the diagonal, and letting go releases the direction.
        ({'right', 'up'}, none),
        (set(), none),
        # A tap between two steps still shoots, and its release is idle in the default set.
        (set(), frozenset({'shot'})),
        (set(), none),
        (set(), none),
        # Sprint stays pressed until it is let go.
        ({'sprint'}, none),
        ({'sprint'}, none),
        (set(), none),
        # A key of two buttons gives the first in GRF's order, then the second on the next step.
        ({'high_pass', 'sliding'}, none),
        ({'high_pass', 'sliding'}, none),
        # A change of direction wins over a button in the same step.
        ({'left', 'dribble'}, none),
        # The high pass and the slide release, one a step, before the dribble presses.
        ({'left', 'dribble'}, none),
        ({'left', 'dribble'}, none),
        ({'left', 'dribble'}, none),
        ({'left'}, none),
    ]
    actions = [controller.act(frozenset(held), pressed) for held, pressed in steps]
    assert actions == [5, 0, 4, 14, 12, 0, 0, 13, 0, 15, 10, 16, 1, 0, 0, 17, 18]
    # The right team plays turned half a circle.
    assert own_frame(frozenset({'left', 'up', 'shot'}), 1) == {'right', 'down', 'shot'}


class _Commands:
    """The server's commands to a game, from a test."""

    def __init__(self, *commands):
        import queue

        self.queue = queue.Queue()
        for command in commands:
            self.queue.put(command)


class _Source:
    """A live source that keeps what it is given."""

    def __init__(self):
        self.frames = []

    def push(self, frame, lineup):
        self.frames.append(frame)


def _replayed(game, steps, human_side):
    """Plays `steps` steps of `game` with a person running right, and checks a batch against it."""
    batch = cuju.BatchEnvironment(
        f'{game.scenario}_l{game.counts[0]}_r{game.counts[1]}',
        environment_count=1,
        seed=game.seed,
        device='cpu',
        auto_reset=False,
        representation='raw',
        action_set=game.action_set,
    )
    try:
        batch.reset()
        for _ in range(steps):
            game.step({human_side: (frozenset({'right'}), frozenset())})
            batch.step(torch.tensor([game.actions[-1]], dtype=torch.int32))
            assert game.batch.get_state(0) == batch.get_state(0)
    finally:
        batch.close()


@pytest.mark.parametrize('human_side', [0, 1])
@pytest.mark.parametrize('fixed', [False, True])
def test_game_against_a_registered_team_replays_exactly(render_home, tmp_path, human_side, fixed):
    """A registered team plays the other side, and the recording names it."""
    from cuju.render._playing.game import Game

    control = (
        {'players': 2, 'assignment': 'fixed', 'selection': [1, 2]} if fixed else {'players': 2}
    )
    source = 'def agent(obs):\n    return [7 if obs["step"] % 3 else 3, 0]\n'
    team = _toy_team(tmp_path, 'opponents', source, '5v5', control)
    teams = ['builtin', 'builtin']
    teams[1 - human_side] = team['id']
    game = Game('5_vs_5', (human_side == 0, human_side == 1), seed=42, teams=tuple(teams))
    try:
        assert game.action_set == 'v2'
        assert game.counts[human_side] == 1
        _replayed(game, 20, human_side)
        assert game.teams[1 - human_side]['name'] == 'opponents'
        assert game.teams[human_side]['name'] == 'You'
        split = game.counts[0]
        policy = [row[split:] if human_side == 0 else row[:split] for row in game.actions]
        assert any(7 in row or 3 in row for row in policy)
        provenance = _recording.read_header(game.save())['provenance']
        assert provenance['teams'] == teams
        assert provenance['humans'] == [human_side == 0, human_side == 1]
        assert provenance['agent_counts'] == game.counts
        assert provenance['action_set'] == 'v2'
        assert provenance['late_steps'] == 0
    finally:
        game.close()


def test_game_reports_the_engine_actions_of_people(render_home, tmp_path):
    """The reports of a game name the action that the engine took for each person."""
    from cuju.render._playing import game as _game

    source = 'def agent(obs):\n    return [13, 5]\n'
    mates = _toy_team(tmp_path, 'mates', source, '5v5', {'players': 2})
    game = _game.Game('5_vs_5', (False, True), seed=3, teams=('builtin', mates['id']))
    try:
        assert _game._status(game) == {'controlled': [None, None], 'late': 0, 'streak': 0}
        game.step({1: (frozenset({'right'}), frozenset())})
        status = _game._status(game)
        # The right person runs right on the screen, which is left in the frame of the right team.
        assert status['actions'] == [None, 1]
        assert status['controlled'][0] is None and isinstance(status['controlled'][1], int)
        game.step({1: (frozenset({'right'}), frozenset({'shot'}))})
        assert _game._status(game)['actions'] == [None, 12]
    finally:
        game.close()


def test_game_beside_a_registered_team(render_home, tmp_path):
    """A team of dynamic assignment plays beside a person, whose agent comes first on the side."""
    from cuju.render._playing.game import Game

    source = 'def agent(obs):\n    return [13, 5]\n'
    mates = _toy_team(tmp_path, 'mates', source, '5v5', {'players': 2})
    game = Game('5_vs_5', (True, False), seed=3, teams=(mates['id'], 'builtin'))
    try:
        assert game.counts == [3, 0]
        _replayed(game, 12, 0)
        assert all(row[1:] == [13, 5] for row in game.actions)
        # The frames mark the players of all three agents, so the game names the person's own.
        assert game.shared == [0] and game.controlled[1] is None
        assert game.controlled[0] == int(game.batch.raw()['active'][0, 0])
        assert game.teams[0]['name'] == 'You with mates'
        assert _recording.read_header(game.save())['provenance']['teams'] == [
            mates['id'],
            'builtin',
        ]
    finally:
        game.close()
    fixed = _toy_team(
        tmp_path, 'fixed', source, '5v5', {'players': 2, 'assignment': 'fixed', 'selection': [1, 2]}
    )
    many = _toy_team(tmp_path, 'many', source, '5v5', {'players': 4})
    for team, message in ((fixed, 'expected dynamic assignment'), (many, 'beside a person')):
        with pytest.raises(cuju.errors.ArgumentError, match=message):
            Game('5_vs_5', (True, False), seed=3, teams=(team['id'], 'builtin'))


_SLOW = """
import time


def agent(obs):
    if obs['step'] == 2:
        time.sleep(0.6)
        return [3]
    return [7]
"""


def test_game_policy_late_for_its_budget_leaves_the_step_to_the_ai(render_home, tmp_path):
    """A policy that misses its budget gives its players to the built-in AI, and its answer goes."""
    from cuju.render._playing.game import Game

    team = _toy_team(tmp_path, 'slow', _SLOW, '5v5')
    game = Game('5_vs_5', (True, False), seed=8, teams=('builtin', team['id']))
    try:
        rows = []
        for _ in range(16):
            game.step({0: (frozenset(), frozenset())}, budget=0.2)
            rows.append(game.actions[-1][1])
            time.sleep(0.1)
        # The first two calls answer in time. The third sleeps past its budget, so the built-in AI
        # plays its step and the steps while it still runs, and its late answer never plays.
        assert rows[:2] == [7, 7]
        assert rows[2] == 19 and rows[3] == 19
        assert 3 not in rows and rows[-1] == 7
        assert game.runner.late == rows.count(19)
        assert game.runner.streak == 0
        assert _recording.read_header(game.save())['provenance']['late_steps'] == rows.count(19)
        # The steps that the built-in AI played replay exactly as well.
        batch = cuju.BatchEnvironment(
            '5_vs_5_l1_r1',
            environment_count=1,
            seed=8,
            device='cpu',
            auto_reset=False,
            representation='raw',
            action_set='v2',
        )
        batch.reset()
        for row in game.actions:
            batch.step(torch.tensor([row], dtype=torch.int32))
        assert batch.get_state(0) == game.batch.get_state(0)
        batch.close()
    finally:
        game.close()


def test_game_policy_first_call_and_load_allowances(render_home, tmp_path):
    """The first call has an allowance of its own, longer than a step's, as does loading."""
    from cuju.render._playing.game import Game
    from cuju.render._playing.play import PolicyError

    lazy = 'import time\n\ndef agent(obs):\n    if obs["step"] == 0:\n        time.sleep(0.5)\n'
    lazy += '    return [7]\n'
    team = _toy_team(tmp_path, 'lazy', lazy, '5v5')
    # A first call within its allowance plays, and the steps after it keep their own budget.
    game = Game('5_vs_5', (True, False), seed=1, teams=('builtin', team['id']))
    try:
        game.step({}, budget=0.2)
        assert game.actions[-1][1] == 7 and game.runner.late == 0
    finally:
        game.close()
    with pytest.raises(PolicyError, match=r'first observation within 0\.1 seconds'):
        Game('5_vs_5', (True, False), seed=1, teams=('builtin', team['id']), first_call_seconds=0.1)
    heavy = _toy_team(
        tmp_path, 'heavy', 'import time\ntime.sleep(1)\n\ndef agent(obs):\n    return [7]\n', '5v5'
    )
    with pytest.raises(PolicyError, match=r'did not load within 0\.2 seconds'):
        Game('5_vs_5', (True, False), seed=1, teams=('builtin', heavy['id']), load_seconds=0.2)
    broken = _toy_team(tmp_path, 'broken', 'def agent(obs):\n    return [99]\n', '5v5')
    with pytest.raises(PolicyError, match='the policy of broken failed, it answered the action 99'):
        Game('5_vs_5', (True, False), seed=1, teams=('builtin', broken['id']))


_HANG = """
import time


def agent(obs):
    if obs['step'] == 4:
        time.sleep(30)
    return [7]
"""


@pytest.mark.parametrize('source', [_CRASH, _HANG])
def test_game_policy_crash_or_hang_ends_and_keeps_the_recording(
    render_home, tmp_path, monkeypatch, source
):
    """A policy that fails or stops answering ends the game, and the game keeps what it played."""
    from cuju.render._playing import game as _game

    monkeypatch.setattr(_game, 'HANG_SECONDS', 0.5)
    team = _toy_team(tmp_path, 'fails', source, '5v5')
    game = _game.Game('5_vs_5', (True, False), seed=2, teams=('builtin', team['id']))
    try:
        played = _game.run(game, _Commands({'paused': False}), _Source(), 50)
        assert played == 'policy'
        expected = 'ValueError: the policy broke' if source == _CRASH else 'has not answered'
        assert expected in game.error
        assert len(game.frames) >= 5
        document, frames = _frames(game.save())
        assert len(frames) == len(game.frames)
        assert document['provenance']['teams'] == ['builtin', team['id']]
    finally:
        game.close()


def test_requested_match_records_resolved_seed(render_home, monkeypatch):
    from cuju.render._playing import play as _play

    _short_matches(monkeypatch, 2)
    monkeypatch.setattr(_play.time, 'time', lambda: 123456)
    path = _play.play('builtin', 'builtin', '5_vs_5', ability=(0.3, 0.7))
    provenance = _recording.read_header(path)['provenance']
    assert provenance['source'] == 'requested_match'
    assert provenance['seed'] == 123456
    assert provenance['teams'] == ['builtin', 'builtin']
    assert provenance['agent_counts'] == [0, 0]
    assert provenance['action_set'] == 'default'
    assert provenance['ability'] == [0.3, 0.7]
    assert provenance['cuju_version'] == cuju.__version__
    assert (
        json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))['provenance']
        == provenance
    )
    # A recording copied into the folder without its summary keeps its provenance in the list.
    path.with_suffix('.json').unlink()
    assert _library.matches()[0]['provenance'] == provenance


@pytest.mark.parametrize('side', [0, 1])
def test_fixed_routing_survives_mixed_set_pieces(device, side):
    """Selected players keep their observation order as GRF changes agents at kickoff."""
    from cuju.render._playing import play as _play

    counts = (11, 1) if side == 0 else (1, 11)
    batch = cuju.BatchEnvironment(
        '11_vs_11_kaggle',
        environment_count=1,
        device=device,
        representation='raw',
        agent_counts=[counts],
        action_set='v2',
        seed=2,
        auto_reset=False,
    )
    try:
        batch.reset()
        first = 0 if side == 0 else 1
        columns = list(range(first, first + 11))
        selected = [9, 3, 1]
        assignments = set()
        modes = set()
        cleared = 0
        for _ in range(150):
            raw = {name: tensor.cpu() for name, tensor in batch.raw().items()}
            active = raw['active'][0, columns].tolist()
            actions = torch.zeros((1, 12), dtype=torch.int32, device=batch.torch_device)
            actions[:, columns] = 19
            found = _play._player_columns(raw, columns, selected, {})
            if found is None:
                # GRF clears the side's selection at a set piece, so every agent reports no player
                # until it hands the players out again, and the built-in AI plays the step.
                assert -1 in active
                cleared += 1
            else:
                chosen, missing = found
                assert missing == []
                assert sorted(active) == list(range(11))
                assignments.add(tuple(active))
                assert raw['active'][0, chosen].tolist() == selected
                actions[:, chosen] = torch.tensor(
                    [3, 7, 5], dtype=torch.int32, device=batch.torch_device
                )
                assert all(
                    int(actions[0, column]) == 19 for column in columns if column not in chosen
                )
            modes.add(int(raw['game_mode'][0, first]))
            batch.step(actions)
        # The set pieces cleared the selection, and the players came back to the agents in the
        # same order or, on one side, in another, which the routing follows.
        assert cleared > 0 and assignments
        assert len(modes) > 1
    finally:
        batch.close()


def test_fixed_routing_keeps_a_player_off_the_pitch():
    """A selected player that no agent reports keeps its agent, while a cleared selection skips."""
    from cuju.render._playing import play as _play

    def raw(*active):
        # The side's agents are columns 4 to 6, after four agents of the other side.
        return {'active': torch.tensor([[0, 0, 0, 0, *active]], dtype=torch.int32)}

    columns, selected, held = [4, 5, 6], [9, 3, 1], {}
    assert _play._player_columns(raw(1, 9, 3), columns, selected, held) == ([5, 6, 4], [])
    # Player 3 leaves the pitch, and its agent now holds player 4.
    assert _play._player_columns(raw(1, 9, 4), columns, selected, held) == ([5, 6, 4], [6])
    # Two agents report player 9, so player 3 takes its last agent while that one is free.
    assert _play._player_columns(raw(1, 9, 9), columns, selected, held) == ([5, 6, 4], [6])
    assert _play._player_columns(raw(1, -1, 4), columns, selected, held) is None


def test_cli_dispatch_options(render_home, tmp_path, monkeypatch):
    """The command line forwards every server and match option."""
    from cuju.render import __main__
    from cuju.render._playing import play as _play

    calls = []
    monkeypatch.setattr(_server, 'serve', lambda *args: calls.append(args))
    assert __main__.main(['serve', '--port', '8799', '--open']) == 0
    assert calls.pop() == (8799, True)
    monkeypatch.setattr(
        _play, 'play', lambda *args, **options: calls.append(args) or tmp_path / 'game'
    )
    assert (
        __main__.main(
            [
                '--home',
                str(render_home),
                'play',
                '--left',
                'home',
                '--right',
                'away',
                '--scenario',
                '5_vs_5',
                '--seed',
                '7',
                '--device',
                'cpu',
                '--left-ability',
                '0.2',
                '--right-ability',
                '0.8',
            ]
        )
        == 0
    )
    assert calls.pop() == ('home', 'away', '5_vs_5', 7, None, 'cpu', (0.2, 0.8))


def test_demo_command_options(render_home, monkeypatch):
    """`cuju render demo` picks five a side by default and passes its options on."""
    from cuju.render import __main__
    from cuju.render._playing import demo as _demo

    calls = []
    monkeypatch.setattr(_demo, 'demo', lambda *args: calls.append(args) or 0)
    assert __main__.main(['demo']) == 0
    assert calls.pop() == (8780, '5_vs_5', True, None)
    assert __main__.main(['demo', '--eleven', '--no-open', '--port', '8801', '--seed', '3']) == 0
    assert calls.pop() == (8801, '11_vs_11_stochastic', False, 3)
    assert __main__.main(['demo', '--scenario', 'academy_corner']) == 0
    assert calls.pop()[1] == 'academy_corner'
    for arguments in (['--port', '-1'], ['--scenario', 'no_such'], ['--seed', 'bad']):
        with pytest.raises(SystemExit) as error:
            __main__.main(['demo', *arguments])
        assert error.value.code == 2


def test_challenge_catalog_and_seeds():
    import zlib

    from cuju.render._playing import challenges as _challenges

    catalog = _challenges.challenges()
    academies = {name for name in cuju.bundled_scenarios() if name.startswith('academy_')}
    assert {entry['scenario'] for entry in catalog if entry['scenario'].startswith('academy_')} == (
        academies
    )
    ids = [entry['id'] for entry in catalog]
    assert len(set(ids)) == len(ids) and {'one_on_one', 'one_on_one_hard'} <= set(ids)
    for entry in catalog:
        assert _home.valid_identifier(entry['id']) and entry['measure'] in _challenges.MEASURES
        assert (
            entry['targets'] == sorted(entry['targets'])
            and len(entry['seeds']) == entry['attempts']
        )
        base = zlib.crc32(entry['id'].encode())
        assert entry['seeds'] == [(base + 7919 * i) % 2**31 for i in range(entry['attempts'])]
        assert entry['seeds'] == _challenges.seeds(entry['id'], entry['attempts'])
    hard = _challenges.find('one_on_one_hard')
    assert hard['ability'] == [None, 1.0] and hard['played_ability'] == [0.0, 1.0]
    assert _challenges.find('empty_goal_close')['played_ability'] == [1.0, 0.6]
    with pytest.raises(cuju.errors.ArgumentError, match='expected a challenge'):
        _challenges.find('no_such_drill')


def test_challenge_scoring_reads_the_frames():
    from cuju.render._playing import challenges as _challenges

    header = {'steps_per_second': 10}
    scored = _challenges.score_attempt(header, _challenge_frames(goal_at=24))
    assert scored == {'finished': True, 'goals': [1, 0], 'scored': True, 'seconds': 2.4}
    missed = _challenges.score_attempt(header, _challenge_frames())
    assert missed == {'finished': True, 'goals': [0, 0], 'scored': False, 'seconds': None}
    # An attempt that ends before its episode counts its goals against and no goals for.
    quit = _challenges.score_attempt(header, _challenge_frames(10, finished=False, against_at=5))
    assert quit == {'finished': False, 'goals': [0, 1], 'scored': False, 'seconds': None}
    within = _challenges.find('empty_goal_close')
    results = [
        _challenges._attempt_result(within, index, None, score)
        for index, score in enumerate([scored, missed, quit, dict(scored, seconds=3.5), scored])
    ]
    assert [result['counts'] for result in results] == [True, False, False, False, True]
    assert _challenges.score_run(within, results) == {'value': 2, 'seconds': 4.8, 'medal': None}
    counted = _challenges.find('run_to_score_with_keeper')
    assert _challenges.score_run(counted, results) == {
        'value': 3,
        'seconds': 8.3,
        'medal': 'silver',
    }
    margin = _challenges.find('one_on_one')
    two = _challenges.score_attempt(header, _challenge_frames(goal_at=5, against_at=30))
    assert two['goals'] == [1, 1]
    runs = [
        _challenges._attempt_result(margin, i, None, s) for i, s in enumerate([scored, two, quit])
    ]
    assert _challenges.score_run(margin, runs) == {'value': 0, 'seconds': 2.9, 'medal': None}
    assert [_challenges.medal(margin, value) for value in (0, 1, 3, 6, 9)] == [
        None,
        'bronze',
        'silver',
        'gold',
        'gold',
    ]


def test_challenge_person_run_checks_each_recording(render_home):
    from cuju.render._playing import challenges as _challenges

    challenge = _challenges.find('one_on_one')
    goal = _challenge_frames(goal_at=12, length=30)
    first = _person_recording(challenge, 0, goal)
    second = _person_recording(challenge, 1, _challenge_frames(goal_at=20, against_at=25))
    scored = _challenges.score_recording('one_on_one', first, 0)
    assert scored['problem'] is None and scored['result']['seconds'] == 1.2
    assert 'seed' in _challenges.score_recording('one_on_one', first, 1)['problem']
    for changes, word in (
        ({'seed': 5}, 'seed'),
        ({'scenario': 'academy_corner'}, 'scenario'),
        ({'source': 'requested_match'}, 'source'),
        ({'humans': [True, True]}, 'humans'),
        ({'teams': ['t-other', 'builtin']}, 'teams'),
        ({'ability': [0.5, 0.0]}, 'ability'),
    ):
        wrong = _person_recording(challenge, 2, goal, **changes)
        with pytest.raises(cuju.errors.ArgumentError, match=word):
            _challenges.person_run('one_on_one', 'Ana', [first, second, wrong])
    with pytest.raises(cuju.errors.ArgumentError, match='distinct'):
        _challenges.person_run('one_on_one', 'Ana', [first, first, second])
    with pytest.raises(cuju.errors.ArgumentError, match='recordings of the attempts'):
        _challenges.person_run('one_on_one', 'Ana', [first, second])
    with pytest.raises(cuju.errors.ArgumentError, match='name'):
        _challenges.person_run('one_on_one', '  ', [first, second, None])
    with pytest.raises(cuju.errors.ArgumentError, match='recording of the library'):
        _challenges.person_run('one_on_one', 'Ana', [first, second, 'm-missing'])
    assert _challenges.board('one_on_one') == []
    # A missed attempt has no recording and counts nothing.
    outcome = _challenges.person_run('one_on_one', 'Ana', [first, second, None])
    assert (outcome['value'], outcome['seconds'], outcome['medal']) == (1, 3.2, 'bronze')
    assert outcome['rank'] == 1 and outcome['improved'] and not outcome['practice']
    assert [result['match'] for result in outcome['attempts']] == [first, second, None]
    board = _challenges.board('one_on_one')
    assert [(entry['kind'], entry['name'], entry['value']) for entry in board] == [
        ('person', 'Ana', 1)
    ]


def test_challenge_headless_run_with_a_registered_team(render_home, tmp_path, monkeypatch):
    from cuju.render._playing import challenges as _challenges

    team = _toy_team(tmp_path, 'toy', _SINGLE, '11v11')
    _short_challenges(monkeypatch, 6)
    seen = []
    practice = _challenges.run(
        'empty_goal_close', team=team['id'], attempts=2, progress=seen.append
    )
    assert practice['practice'] and practice['medal'] is None and practice['rank'] is None
    assert [result['index'] for result in seen] == [0, 1]
    assert _challenges.board('empty_goal_close') == []
    seeds = _challenges.find('empty_goal_close')['seeds']
    for result in practice['attempts']:
        document, frames = _frames(render_home / 'matches' / f'{result["match"]}.cjr')
        provenance = document['provenance']
        assert provenance['source'] == 'challenge' and provenance['challenge'] == 'empty_goal_close'
        assert (
            provenance['attempt'] == result['index']
            and provenance['seed'] == seeds[result['index']]
        )
        assert provenance['teams'] == [team['id'], 'builtin'] and provenance['agent_counts'] == [
            1,
            0,
        ]
        assert provenance['ability'] == [1.0, 0.6] and provenance['competitor'] == 'toy'
        assert len(frames) == 7 and struct.unpack_from('<i', frames[-1], 28)[0] & 1
        assert document['teams'][0]['id'] == team['id']
    outcome = _challenges.run('empty_goal_close', team=team['id'])
    assert not outcome['practice'] and len(outcome['attempts']) == 5 and outcome['rank'] == 1
    board = _challenges.board('empty_goal_close')
    assert [(entry['kind'], entry['team'], entry['name']) for entry in board] == [
        ('agent', team['id'], 'toy')
    ]
    assert [attempt['match'] for attempt in board[0]['attempts']] == [
        result['match'] for result in outcome['attempts']
    ]


def test_challenge_person_and_agent_face_the_same_episode(render_home, tmp_path, monkeypatch):
    """A team of one dynamic agent plays the very episode of a person's game of the attempt."""
    from cuju.render._playing import challenges as _challenges
    from cuju.render._playing import game as _game

    idle = _toy_team(tmp_path, 'idle', 'def agent(obs):\n    return [0]\n', '11v11')
    _short_challenges(monkeypatch, 12)
    outcome = _challenges.run('run_to_score', team=idle['id'], attempts=1)
    _, agent_frames = _frames(render_home / 'matches' / f'{outcome["attempts"][0]["match"]}.cjr')
    challenge = _challenges.find('run_to_score')
    game = _game.Game(
        challenge['scenario'], (True, False), tuple(challenge['ability']), challenge['seeds'][0]
    )
    try:
        for _ in range(12):
            game.step({0: (frozenset(), frozenset())})
        # The last frame of the attempt carries the end of its shortened episode as well.
        assert len(game.frames) == len(agent_frames) == 13
        assert game.frames[:12] == agent_frames[:12]
        assert game.frames[12][32:] == agent_frames[12][32:]
    finally:
        game.close()


def test_challenge_policy_runs_and_failures(render_home, monkeypatch):
    from cuju.render._playing import challenges as _challenges
    from cuju.render._playing import play as _play

    _short_challenges(monkeypatch, 4)
    calls = []

    def striker(obs):
        calls.append(obs['step'])
        return [12]

    outcome = cuju.render.challenge('corner', policy=striker, attempts=1)
    assert outcome['name'] == 'striker' and outcome['team'] is None and outcome['practice']
    assert calls == [0, 1, 2, 3]
    document = _recording.read_header(
        render_home / 'matches' / f'{outcome["attempts"][0]["match"]}.cjr'
    )
    assert (
        document['provenance']['policy'] == 'striker' and document['teams'][0]['name'] == 'striker'
    )
    full = cuju.render.challenge('one_on_one', policy=striker, name='Striker bot')
    assert full['rank'] == 1 and _challenges.board('one_on_one')[0]['name'] == 'Striker bot'

    def broken(obs):
        raise RuntimeError('no idea')

    with pytest.raises(_play.PolicyError, match='no idea'):
        cuju.render.challenge('corner', policy=broken)
    with pytest.raises(_play.PolicyError):
        cuju.render.challenge('corner', policy=lambda obs: [99], name='wild')
    assert _challenges.board('corner') == []
    for options in (
        {},
        {'team': 'builtin', 'policy': striker},
        {'team': 'no-such-team'},
        {'policy': striker, 'attempts': 6},
        {'policy': striker, 'attempts': 0},
    ):
        with pytest.raises(cuju.errors.ArgumentError):
            cuju.render.challenge('corner', **options)


@pytest.mark.parametrize(
    ('frames', 'header', 'left', 'right'),
    [
        # Player 1 scores three, a win at ability 1.0 in a full match without a goal conceded.
        (
            dict(length=60, goals=[(10, 0, 1), (20, 0, 1), (30, 0, 1)]),
            {},
            ['off_the_mark', 'hat_trick', 'giant_slayer', 'clean_sheet'],
            [],
        ),
        # Two scorers make no hat trick, an opponent at 0.6 no giant, a conceded goal no clean
        # sheet, and the loser comes back from nothing.
        (
            dict(length=60, goals=[(10, 0, 1), (20, 0, 1), (30, 0, 0), (40, 1, 3)]),
            {'ability': 0.6},
            ['off_the_mark', 'keeper_goal'],
            ['off_the_mark'],
        ),
        # The right side leads, then the left side wins late after trailing.
        (
            dict(length=100, goals=[(10, 1, 3), (50, 0, 1), (95, 0, 1)]),
            {'full_match': False},
            ['off_the_mark', 'giant_slayer', 'comeback', 'last_gasp'],
            ['off_the_mark'],
        ),
        # A goal from the own corner, within ten seconds and with play running on.
        (
            dict(length=100, goals=[(60, 0, 1)], modes=[(40, 45, 4, 54.0)]),
            {'scenario': 'academy_corner', 'full_match': False},
            ['off_the_mark', 'corner_goal'],
            [],
        ),
        # The corner of the other side, a free kick in between, or a goal too late count none.
        (
            dict(length=100, goals=[(60, 0, 1)], modes=[(40, 45, 4, -54.0)]),
            {'scenario': 'academy_corner', 'full_match': False},
            ['off_the_mark'],
            [],
        ),
        (
            dict(length=100, goals=[(60, 0, 1)], modes=[(30, 35, 4, 54.0), (50, 52, 3, 30.0)]),
            {'scenario': 'academy_corner', 'full_match': False},
            ['off_the_mark'],
            [],
        ),
        (
            dict(length=200, goals=[(160, 0, 1)], modes=[(40, 45, 4, 54.0)]),
            {'scenario': 'academy_corner', 'full_match': False},
            ['off_the_mark'],
            [],
        ),
        # A penalty of the right side, which attacks the goal at negative x.
        (
            dict(length=60, goals=[(30, 1, 3)], modes=[(10, 20, 6, -44.0)]),
            {},
            [],
            ['off_the_mark', 'penalty_goal', 'clean_sheet'],
        ),
        # The scorer's last touch 35 meters out is a screamer, one 5 meters out is not.
        (
            dict(length=60, goals=[(30, 0, 1)], touches=[(20, 1, 20.0)]),
            {'scenario': 'academy_run_to_score', 'full_match': False},
            ['off_the_mark', 'screamer'],
            [],
        ),
        (
            dict(length=60, goals=[(30, 0, 1)], touches=[(10, 1, 20.0), (25, 1, 50.0)]),
            {'scenario': 'academy_run_to_score', 'full_match': False},
            ['off_the_mark'],
            [],
        ),
        # An own goal counts for the other side, but for nobody's hat trick or keeper.
        (
            dict(length=60, goals=[(10, 0, 2), (20, 0, 3), (30, 0, 3)]),
            {'ability': 0.5},
            ['off_the_mark', 'clean_sheet'],
            [],
        ),
        # Five ahead is a rout, and an episode cut short wins nothing.
        (
            dict(length=60, goals=[(5 * k, 0, 1) for k in range(1, 6)]),
            {'opponent': 't-other'},
            ['off_the_mark', 'hat_trick', 'clean_sheet', 'rout'],
            [],
        ),
        (
            dict(length=60, goals=[(5 * k, 0, 1) for k in range(1, 6)], finished=False),
            {},
            ['off_the_mark', 'hat_trick'],
            [],
        ),
    ],
)
def test_achievements_from_frames(frames, header, left, right):
    from cuju.render._playing import achievements as _achievements

    document = _achievement_header(**header)
    built = _achievement_frames(**frames)
    assert _achievements.detect(document, built, 0) == left
    assert _achievements.detect(document, built, 1) == right
    # Without the engine's scorer the scorers stay unknown.
    unknown = {**document, 'engine_scorer': False}
    assert 'hat_trick' not in _achievements.detect(unknown, built, 0)


def test_achievements_of_teams_stay_on_disk(render_home, caplog):

    from cuju.render._playing import achievements as _achievements

    header = _achievement_header()
    frames = _achievement_frames(60, goals=[(10, 0, 1), (20, 0, 1), (30, 0, 1)])
    timing = {'duration': 3000, 'second_half': None, 'full_match': True}
    head = _recording.header('Match', '5_vs_5', _ACHIEVEMENT_PLAYERS, None, len(frames), timing, {})
    awarded = _achievements.award_match(head, frames, ['t-left', 'builtin'], 'm-first')
    assert awarded == {'t-left': ['off_the_mark', 'hat_trick', 'clean_sheet']}
    again = _achievements.award_match(header, frames, ['t-left', None], 'm-second')
    assert again['t-left'][0] == 'off_the_mark'
    kept = _achievements.earned('t-left')
    assert kept['off_the_mark']['count'] == 2 and kept['off_the_mark']['match'] == 'm-first'
    assert kept['giant_slayer'] == {**kept['giant_slayer'], 'count': 1, 'match': 'm-second'}
    folder = render_home / 'achievements'
    assert sorted(path.name for path in folder.iterdir()) == ['t-left.json']
    public = _achievements.public()
    assert [entry['id'] for entry in public['catalog']] == list(_achievements.IDENTIFIERS)
    assert set(public['teams']) == {'t-left'}
    document = json.loads((folder / 't-left.json').read_text(encoding='utf-8'))
    document['earned']['rout'] = {'first': 'today', 'count': 1}
    document['earned']['flying'] = {'first': 1, 'count': 1}
    (folder / 't-left.json').write_text(json.dumps(document), encoding='utf-8')
    (folder / 't-broken.json').write_text('[', encoding='utf-8')
    with caplog.at_level(logging.WARNING, logger='cuju'):
        assert set(_achievements.earned('t-left')) == set(kept)
        assert _achievements.earned('t-broken') == {}
    warnings = [record.getMessage() for record in caplog.records if record.name == 'cuju']
    assert len(warnings) == 2 and '2 invalid entries' in warnings[0]


def test_requested_match_awards_its_teams(render_home, tmp_path, monkeypatch, caplog):

    from cuju.render._playing import achievements as _achievements
    from cuju.render._playing import play as _play

    team = _toy_team(tmp_path, 'toy', _SINGLE, '5v5')
    _short_matches(monkeypatch, 3)
    seen = []
    real = _achievements.detect

    def detect(header, frames, side):
        seen.append((header['provenance']['source'], len(frames), side))
        return ['rout'] if side == 0 else real(header, frames, side)

    monkeypatch.setattr(_achievements, 'detect', detect)
    path = _play.play(team['id'], 'builtin', '5_vs_5', seed=3)
    assert seen == [('requested_match', 4, 0)]
    assert _achievements.earned(team['id'])['rout']['match'] == path.stem

    # A failed write leaves the recording saved, with a warning.
    def full(target, data):
        raise OSError('disk full')

    monkeypatch.setattr(_teams, '_replace', full)
    with caplog.at_level(logging.WARNING, logger='cuju'):
        second = _play.play(team['id'], 'builtin', '5_vs_5', seed=4)
    assert second.is_file()
    assert any('achievements' in record.getMessage() for record in caplog.records)


def test_challenge_runs_award_achievements(render_home, tmp_path, monkeypatch):
    from cuju.render._playing import achievements as _achievements
    from cuju.render._playing import challenges as _challenges

    challenge = _challenges.find('one_on_one')
    goals = [_challenge_frames(goal_at=5 + index, length=30) for index in range(3)]
    for frames in goals:
        for step in range(15, 30):
            frames[step] = _challenge_frame(step, (2, 0) if step < 29 else (3, 0), frames[step][28])
    matches = [_person_recording(challenge, index, frames) for index, frames in enumerate(goals)]
    outcome = _challenges.person_run('one_on_one', 'Ana', matches)
    assert outcome['medal'] == 'gold'
    assert outcome['achievements'] == ['off_the_mark', 'podium', 'gold_standard']
    # A team earns the achievements of its attempts and medals on disk, and a policy keeps none.
    team = _toy_team(tmp_path, 'toy', _SINGLE, '11v11')
    _short_challenges(monkeypatch, 4)
    monkeypatch.setattr(_challenges, 'medal', lambda challenge, value: 'gold')
    run = _challenges.run('corner', team=team['id'])
    assert run['achievements'] == ['podium', 'gold_standard']
    assert set(_achievements.earned(team['id'])) == {'podium', 'gold_standard'}
    policy = _challenges.run('corner', policy=lambda obs: [0], name='calm')
    assert policy['achievements'] == []
    assert set(_achievements.public()['teams']) == {team['id']}
    practice = _challenges.run('corner', team=team['id'], attempts=1)
    assert practice['achievements'] == []
    monkeypatch.setattr(
        _challenges,
        'personal_bests',
        lambda *arguments: {entry['id']: {'medal': 'gold'} for entry in _challenges.CATALOG},
    )
    graduate = _challenges.run('corner', team=team['id'])
    assert graduate['achievements'] == ['podium', 'gold_standard', 'academy_graduate']
    assert _achievements.earned(team['id'])['podium']['count'] == 2


def test_play_reports_progress_only_to_its_function(render_home, tmp_path, monkeypatch, capsys):
    """A match in the caller's process prints no progress, and the command prints one line."""
    from cuju.render.__main__ import main
    from cuju.render._playing import play as _play

    _short_matches(monkeypatch, 120)
    seen = []
    path = _play.play('builtin', 'builtin', '5_vs_5', seed=1, progress=seen.append)
    assert path.is_file() and seen and all(0 < share < 1 for share in seen)
    assert 'progress' not in capsys.readouterr().out
    assert main(['play', '--scenario', '5_vs_5', '--seed', '1', '--json']) == 0
    printed = json.loads(capsys.readouterr().out)
    assert (render_home / 'matches' / f'{printed["match"]}.cjr').is_file()
    assert printed['path'].endswith(f'{printed["match"]}.cjr')
    crash = _toy_team(
        tmp_path, 'crash', 'def agent(obs):\n    raise RuntimeError("broke")\n', '5v5'
    )
    assert main(['play', '--left', crash['id'], '--scenario', '5_vs_5']) == 1
    captured = capsys.readouterr()
    assert captured.err.strip() == 'cuju render: the policy of crash failed, RuntimeError: broke'
    # A Python caller still gets the submission's own error.
    with pytest.raises(RuntimeError, match='broke') as caught:
        cuju.render.play(crash['id'], 'builtin', '5_vs_5', seed=1)
    assert not isinstance(caught.value, cuju.render.PolicyError)


def test_challenge_agents_keep_names_and_only_stored_achievements(render_home, monkeypatch, capsys):
    """A lambda plays as Python policy, and the runs that keep nothing return no achievements."""
    from cuju.render.__main__ import main
    from cuju.render._playing import achievements as _achievements
    from cuju.render._playing import challenges as _challenges

    _short_challenges(monkeypatch, 4)
    monkeypatch.setattr(_achievements, 'detect', lambda header, frames, side: ['off_the_mark'])
    run = cuju.render.challenge('corner', policy=lambda obs: [0], attempts=1)
    assert run['name'] == _challenges.POLICY_NAME == 'Python policy'
    assert run['achievements'] == []

    def striker(obs):
        return [12]

    assert cuju.render.challenge('corner', policy=striker, attempts=1)['name'] == 'striker'
    assert cuju.render.challenge('corner', team='builtin', attempts=1)['achievements'] == []
    assert _achievements.public()['teams'] == {}
    assert main(['challenge', 'list', '--json']) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [entry['id'] for entry in listed] == [entry['id'] for entry in _challenges.CATALOG]
    assert main(['challenge', 'corner', '--team', 'builtin', '--attempts', '1', '--json']) == 0
    outcome = json.loads(capsys.readouterr().out)
    assert outcome['practice'] and outcome['achievements'] == [] and len(outcome['attempts']) == 1
    # A goal after the time limit says so, and the run names that no attempt counts.
    late = {'finished': True, 'goals': [1, 0], 'scored': True, 'seconds': 12.2}
    monkeypatch.setattr(_challenges, 'score_attempt', lambda header, frames, side=0: dict(late))
    assert main(['challenge', 'empty_goal_close', '--team', 'builtin', '--attempts', '1']) == 0
    out = capsys.readouterr().out
    assert 'scored after 12.2 seconds, past the limit of 3 seconds' in out
    assert 'value 0, no attempt counts towards it' in out and '0 seconds to score' not in out


def test_server_catalogs_match_the_language_files():
    from cuju.render._playing import achievements as _achievements
    from cuju.render._playing import challenges as _challenges
    from cuju.render._store import samples as _samples
    from cuju.render._tournaments import tournament as _tournament

    english = _shipped_language('en')
    portuguese = _shipped_language('pt')
    expected = {}
    for entry in _challenges.CATALOG:
        expected[f'challenge.{entry["id"]}.title'] = entry['title']
        expected[f'challenge.{entry["id"]}.goal'] = entry['goal']
    for entry in _achievements.CATALOG:
        expected[f'achievement.{entry["id"]}.name'] = entry['name']
        expected[f'achievement.{entry["id"]}.description'] = entry['description']
        # A badge's letters come in the language of the page too.
        expected[f'achievement.{entry["id"]}.glyph'] = entry['glyph']
    for key, preset in _tournament.PRESETS.items():
        expected[f'tournament.preset.{key}.title'] = preset['title']
        expected[f'tournament.preset.{key}.description'] = preset['description']
    for name, (title, about) in _samples._TITLES.items():
        expected[f'helpcenter.sample.{name}.title'] = title
        expected[f'helpcenter.sample.{name}.about'] = about
    for name, team in _samples.TEAMS.items():
        expected[f'helpcenter.sample.{name}.title'] = team['name']
        expected[f'helpcenter.sample.{name}.about'] = team['about']
    lessons = json.loads((_server._WEB / 'lessons.json').read_text(encoding='utf-8'))['lessons']
    for lesson in lessons:
        for field in ('title', 'ask', 'praise'):
            expected[f'lesson.{lesson["id"]}.{field}'] = lesson[field]
    assert {key: english.get(key) for key in expected} == expected
    prefixes = ('challenge.', 'achievement.', 'tournament.preset.', 'lesson.')
    assert sorted(k for k in english if k.startswith(prefixes) and k not in expected) == []
    assert all(key in portuguese and portuguese[key] != english[key] for key in expected)
    from cuju.render._moments import captions as _captions

    table = _captions.messages()
    assert 'caption.goal' in table and 'describe.pass' in table
    assert all(key.startswith(('caption.', 'describe.')) for key in table)


def test_policy_errors_carry_message_ids():
    from cuju.render._playing import play as _play
    from cuju.render._text import messages as _messages

    outside = IndexError('expected an action from -19 to 18, found 25')
    error = _play._policy_error(outside, 'Reds')
    assert str(error) == (
        'the policy of Reds failed, it answered the action 25, outside its action set of 19 '
        'actions, 0 to 18'
    )
    assert isinstance(error, cuju.render.PolicyError)
    assert _messages.id_fields(error) == {
        'error_id': 'server.policy.failed_action',
        'error_values': {'player': 'Reds', 'value': '25', 'count': '19', 'last': '18'},
    }
    error = _play._policy_error(ValueError('no'))
    assert str(error) == 'the policy failed, ValueError: no'
    assert (error.message_id, error.values) == ('server.policy.error', {'reason': 'ValueError: no'})


def test_tournament_failures_carry_message_ids(render_home):
    from cuju.render._playing import play as _play
    from cuju.render._text import messages as _messages
    from cuju.render._tournaments import tournament_runner as runner

    def player(match, teams, provenance, progress):
        if match['key'] == '0/w4-1/1':
            raise _play.PolicyMessageError(
                'server.policy.failed', player='Reds', reason='ValueError: no'
            )
        return None

    entrants = [{'kind': 'builtin', 'ability': index / 4} for index in range(4)]
    stage = {'format': 'knockout', 'scenario': 'academy_empty_goal_close', 'settle': ['lots']}
    config = {'name': 'Spring cup', 'seed': 9, 'entrants': entrants, 'stages': [stage]}
    cups = runner.Tournaments(player=player, start=False)
    try:
        entry = cups.create(config)
        assert cups.run(entry['id'], report=lambda line: None) == 'stopped'
        view = cups.get(entry['id'])
        matches = {match['key']: match for match in view['matches']}
        first, second = matches['0/w4-1/1'], matches['0/w4-2/1']
        assert first['error'] == 'the policy of Reds failed, ValueError: no'
        assert (first['error_id'], first['error_values']) == (
            'server.policy.failed',
            {'player': 'Reds', 'reason': 'ValueError: no'},
        )
        assert (second['error'], second['error_id']) == (
            'the match gave no result',
            'server.tournament.no_result',
        )
        assert view['error'] == (
            'Semi-final 1 failed, the policy of Reds failed, ValueError: no, and 1 more match '
            'failed'
        )
        assert view['error_id'] == 'server.tournament.match_failed_one_more'
        assert _messages.text(view['error_id'], **view['error_values']) == view['error']
        # A file of an earlier version, without the ids of its failures, loads all the same.
        stored = json.loads((runner.folder() / f'{entry["id"]}.json').read_text(encoding='utf-8'))
        del stored['failure_ids']
        (runner.folder() / f'{entry["id"]}.json').write_text(json.dumps(stored), encoding='utf-8')
        cups.close()
        cups = runner.Tournaments(player=player, start=False)
        failed = {match['key']: match for match in cups.get(entry['id'])['matches']}
        assert failed['0/w4-1/1']['error'] == first['error']
        assert failed['0/w4-1/1']['error_id'] is None
        cups.cancel(entry['id'])
        with pytest.raises(cuju.errors.ArgumentError) as caught:
            cups.cancel(entry['id'])
        assert str(caught.value) == 'expected a tournament that runs or stopped, found it cancelled'
        assert caught.value.message_id == 'server.tournament.cancel_state'
    finally:
        cups.close()


def test_render_errors_read_as_public_classes_and_dir_lists_the_public_names():
    import pickle
    import traceback

    from cuju.render._playing import errors as _errors
    from cuju.render._playing import play as _play
    from cuju.render._text import messages as _messages

    error = _messages.MessageError('server.game.unknown')
    assert (type(error).__module__, type(error).__qualname__) == ('cuju.errors', 'ArgumentError')
    assert repr(error).startswith('ArgumentError(')
    shown = traceback.format_exception_only(type(error), error)[-1]
    assert shown.startswith('cuju.errors.ArgumentError: ')
    assert isinstance(error, cuju.errors.ArgumentError) and _messages.kind(error) == 'ArgumentError'
    again = pickle.loads(pickle.dumps(error))
    assert type(again) is _messages.MessageError and again.message_id == 'server.game.unknown'
    assert str(again) == str(error)
    policy = _play.PolicyMessageError('server.game.unknown')
    assert f'{type(policy).__module__}.{type(policy).__qualname__}' == 'cuju.render.PolicyError'
    assert isinstance(policy, cuju.render.PolicyError)
    assert _errors.PolicyError.__module__ == 'cuju.render'
    assert dir(cuju.render) == sorted(cuju.render.__all__)
    assert 'threading' not in dir(cuju.render) and 'Recorder' in dir(cuju.render)
