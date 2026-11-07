# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of requested matches, games, the demo, challenges and achievements."""

import pytest
import torch

import cuju
import cuju.errors
import cuju.state
from cuju.render._format import recording as _recording
from cuju.render._http import server as _server


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
    batch.close()
    game.close()


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
    monkeypatch.setattr(_play, 'play', lambda *args: calls.append(args) or tmp_path / 'game')
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
