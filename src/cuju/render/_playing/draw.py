# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The draw of a requested match, the teams and the scenario that its seed picks at random.

A side of a requested match may name `random` in place of a team, and its scenario may name
`random` too. The draw then picks, from the seed of the request, a team of the registry that can
play the side, or of the pool when the request names one, and a scenario that both sides can
play. The same seed and the same registry always draw the same match, so a retry with the seed
of a request draws its teams again, and a new seed draws anew. Two sides that draw differ
whenever another team fits, unless the request lets a team meet itself.

The module keeps no relative imports at the top, since the mock server loads it from its file
alone, and `draw_request` imports the registry when it runs.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable, Sequence
from typing import Any

# The word that stands for a team or a scenario drawn at random.
RANDOM = 'random'
# The scenarios that the lists of the page leave out, the training variants of GRF MARL and the
# examples, which web/js/core/scenarios.js leaves out alike. A random scenario comes from the rest.
_HIDDEN = re.compile(r'(benchmark_full_game_|test_)')
_SIDES = ('left', 'right')


def listed(scenarios: Sequence[str]) -> list[str]:
    """Returns the scenarios that the page lists, in order, which a random scenario comes from."""
    return sorted(name for name in scenarios if not _HIDDEN.match(name))


def generator(seed: int) -> random.Random:
    """Returns the generator of the draw of a seed, which Python makes alike on every system."""
    return random.Random(f'cuju.render.draw {int(seed)}')


def pick(
    seed: int,
    options: Sequence[tuple[str, Sequence[str], Sequence[str]]],
    same_team: bool = False,
) -> tuple[str, str, str] | None:
    """Returns the scenario, the left team and the right team that a seed draws, or `None`.

    Args:
        seed: The seed of the request.
        options: Each scenario that may be drawn, with the teams that can play its left side and
            its right side, every list in a fixed order.
        same_team: Whether one team may play both sides while another team fits.
    """
    options = [option for option in options if option[1] and option[2]]
    if not options:
        return None
    draw = generator(seed)
    scenario, lefts, rights = draw.choice(options)
    every = [(left, right) for left in lefts for right in rights]
    pairs = every if same_team else [(left, right) for left, right in every if left != right]
    left, right = draw.choice(pairs or every)
    return scenario, left, right


def resolve(
    sides: Sequence[str],
    scenario: str,
    seed: int,
    pool: Any,
    same_team: Any,
    teams: Sequence[str],
    scenarios: Sequence[str],
    fits: Callable[[str, str, int], bool],
    fail: Callable[..., Exception],
) -> dict[str, Any] | None:
    """Draws the random parts of a request and returns the match, or `None` when none is random.

    Args:
        sides: The team of the left and the right side, an identifier or `random`.
        scenario: The scenario, or `random`.
        seed: The seed of the request, which the draw follows.
        pool: The teams that a random side may draw, a list of identifiers, or `None` for every
            team of the registry.
        same_team: Whether one team may play both sides while another team fits.
        teams: The identifier of every team of the registry.
        scenarios: The scenarios of the server, of which a random scenario takes a listed one.
        fits: Returns whether a team can play a side of a scenario, by identifier, scenario and
            side, 0 on the left.
        fail: Returns the error of a message, by its id and values, which `resolve` raises.

    Returns:
        A plain dictionary of the `left` team, the `right` team, the `scenario` and the `draw`,
        which names the random sides as `sides`, whether the `scenario` was drawn, the `pool`
        and `same_team`.

    Raises:
        Exception: The error that `fail` returns, if the pool or `same_team` is malformed, a team
            of the pool is unknown, or no team or scenario fits.
    """
    drawn = [team == RANDOM for team in sides]
    drawn_scenario = scenario == RANDOM
    if not any(drawn) and not drawn_scenario:
        return None
    if not isinstance(same_team, bool):
        raise fail('server.draw.same_team', value=repr(same_team))
    known = sorted(set(teams))
    if pool is not None:
        if (
            not isinstance(pool, list)
            or not pool
            or not all(isinstance(item, str) for item in pool)
        ):
            raise fail('server.draw.pool', pool=repr(pool))
        for item in pool:
            if item not in known:
                raise fail('server.teams.unknown', identifier=repr(item))
        pool = sorted(set(pool))
    for team, random_side in zip(sides, drawn, strict=True):
        if not random_side and team not in known:
            raise fail('server.teams.unknown', identifier=repr(team))
    choices = pool if pool is not None else known
    names = listed(scenarios) if drawn_scenario else [scenario]
    options = []
    for name in names:
        candidates = []
        for side, team in enumerate(sides):
            if drawn[side]:
                candidates.append([item for item in choices if fits(item, name, side)])
            else:
                # A side of a named scenario keeps its team, whose own check names what is wrong.
                keep = not drawn_scenario or fits(team, name, side)
                candidates.append([team] if keep else [])
        options.append((name, *candidates))
    found = pick(seed, options, same_team)
    if found is None:
        if drawn_scenario:
            raise fail('server.draw.scenario')
        empty = next(side for side in (0, 1) if not options[0][side + 1])
        raise fail(f'server.draw.{_SIDES[empty]}', scenario=scenario)
    chosen, left, right = found
    return {
        'left': left,
        'right': right,
        'scenario': chosen,
        'draw': {'sides': drawn, 'scenario': drawn_scenario, 'pool': pool, 'same_team': same_team},
    }


def valid(draw: Any) -> bool:
    """Returns whether a stored draw of a request is well formed, `None` for a request without."""
    if draw is None:
        return True
    return (
        isinstance(draw, dict)
        and set(draw) == {'sides', 'scenario', 'pool', 'same_team'}
        and isinstance(draw['sides'], list)
        and len(draw['sides']) == 2
        and all(isinstance(item, bool) for item in draw['sides'])
        and isinstance(draw['scenario'], bool)
        and isinstance(draw['same_team'], bool)
        and (
            draw['pool'] is None
            or (
                isinstance(draw['pool'], list)
                and all(isinstance(item, str) for item in draw['pool'])
            )
        )
    )


def draw_request(
    left: str,
    right: str,
    scenario: str,
    seed: int,
    pool: Any = None,
    same_team: Any = False,
) -> dict[str, Any] | None:
    """Draws the random parts of a request from the registry, as `resolve` describes.

    Raises:
        ArgumentError: If the pool or `same_team` is malformed, a team is unknown, or no team or
            scenario fits.
    """
    from cuju import bundled_scenarios
    from cuju.errors import ArgumentError

    from .._registry import teams as _teams
    from .._text import messages as _messages

    entries = {team['id']: team for team in _teams.teams()}
    builtin = entries[_teams.BUILTIN]

    def fits(identifier: str, name: str, side: int) -> bool:
        team = entries[identifier]
        try:
            _teams.check_scenario([team, builtin] if side == 0 else [builtin, team], name)
        except ArgumentError:
            return False
        return True

    def fail(message_id: str, **values: Any) -> Exception:
        if 'scenario' in values:
            values['scenario'] = _messages.scenario(values['scenario'])
        return _messages.MessageError(message_id, **values)

    scenarios = [*bundled_scenarios(), *_teams.renderer_scenarios()]
    return resolve(
        (left, right), scenario, seed, pool, same_team, list(entries), scenarios, fits, fail
    )
