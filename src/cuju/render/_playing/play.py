# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""Plays one match between two teams of the registry and saves it.

The server runs this module in a process of its own for each requested match, so a submission that
fails ends only that process, and the server ends one that runs past its time. Progress goes to the
server as one JSON line at a time on a channel of its own, while whatever a submission prints goes
to standard error, so no submission can forge a report. A match played in the caller's process,
from `cuju render play` or `cuju.render.play`, reports progress only to a function it is given.

A policy that fails raises `PolicyError` with a one-line reason. The variable `CUJU_RENDER_DEBUG`,
set to `on`, also prints the full traceback of the policy's error to standard error.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import logging
import os
import queue
import random
import re
import struct
import sys
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

import torch

from cuju import BatchEnvironment, bundled_scenarios
from cuju.kaggle import (
    AgentRunner,
    accepts_configuration,
    action_index,
    action_indices,
    observation,
)

from .._format import recording as _recording
from .._registry import teams as _teams
from .._store import library as _library
from .._text import messages as _messages
from .._text.messages import MessageError
from . import achievements as _achievements
from .errors import PolicyError

# The channel of the reports, which `main` opens on standard output once it has moved the
# submissions' prints away, and `None` for a match played in the caller's process.
_reports: TextIO | None = None
# The variable that prints the traceback of a policy's error, as `on`.
DEBUG_VARIABLE = 'CUJU_RENDER_DEBUG'
# GRF: a full match of the shipped scenarios lasts 3000 steps, so it takes 3001 frames, which the
# progress of a match divides by when its scenario names no duration.
_FRAMES = 3001
# The v2 action that hands a player to the builtin AI for one step.
_BUILTIN_AI = 19
# The actions of the default set.
DEFAULT_ACTIONS = 19
# The score of the left and the right side, at its place in a frame of a recording.
_SCORE = struct.Struct('<2i')


def _report(**entries: Any) -> None:
    """Writes one line of progress for the server, when a server reads them."""
    if _reports is None:
        return
    _reports.write(json.dumps(entries) + '\n')
    _reports.flush()


def debugging() -> bool:
    """Returns whether `CUJU_RENDER_DEBUG` asks for the tracebacks of policy errors."""
    return os.environ.get(DEBUG_VARIABLE, '').strip().lower() not in ('', '0', 'off', 'no')


def _action_values(error: BaseException) -> dict[str, str] | None:
    """Returns the answer and action set of an error for an action outside the set, or `None`."""
    found = re.fullmatch(r'expected an action from -(\d+) to (\d+), found (.+)', str(error))
    if isinstance(error, IndexError) and found:
        count, last, value = found.groups()
        return {'value': value, 'count': count, 'last': last}
    return None


def _reason(error: BaseException) -> str:
    """Returns the reason of a policy's error in one line, with the action set in words."""
    values = _action_values(error)
    if values is not None:
        return (
            f'it answered the action {values["value"]}, outside its action set of '
            f'{values["count"]} actions, 0 to {values["last"]}'
        )
    return f'{type(error).__name__}: {error}'


def _policy_error(error: BaseException, player: str | None = None) -> PolicyError:
    """Returns the `PolicyError` of a policy's error, which names the player when it is given.

    Its text is that of `_reason` after the policy, and an action outside the set has a message
    of its own, so the page shows that reason in its own language too.
    """
    named = {} if player is None else {'player': player}
    message_id = 'server.policy.error' if player is None else 'server.policy.failed'
    values = _action_values(error)
    if values is not None:
        return PolicyMessageError(f'{message_id}_action', **named, **values)
    return PolicyMessageError(message_id, **named, reason=_reason(error))


def game_title(names: list[Any], tournament: dict[str, Any] | None) -> dict[str, Any]:
    """Returns the title of a match as a label, its two sides by name, after its tournament match.

    Args:
        names: The name of each side, text or a label.
        tournament: What the recording keeps of its tournament, whose name and match label come
            before the sides, or `None`.
    """
    if tournament is not None:
        from .._tournaments.tournament import match_title

        return match_title(tournament, names[0], names[1])
    return _messages.label('server.names.against', left=names[0], right=names[1])


def side_names(tournament: dict[str, Any] | None) -> list[Any]:
    """Returns the name of each side that a tournament gives, a label where its rules made one,
    or `None` for each side outside a tournament."""
    tournament = tournament or {}
    labels = tournament.get('labels')
    if isinstance(labels, list) and len(labels) == 2:
        return labels
    return tournament.get('names') or [None, None]


def play(
    left: str,
    right: str,
    scenario: str = '11_vs_11_kaggle',
    seed: int | None = None,
    title: str | dict[str, Any] | None = None,
    device: str = 'cpu',
    ability: tuple[float | None, float | None] = (None, None),
    length: int | None = None,
    tournament: dict[str, Any] | None = None,
    progress: Callable[[float], None] | None = None,
    policy_errors: bool = False,
    draw: dict[str, Any] | None = None,
    strict: dict[str, Any] | None = None,
    stats: dict[str, Any] | None = None,
    steps: int | None = None,
    save: bool = True,
    replay: dict[str, Any] | None = None,
) -> Path | None:
    """Plays a match between two teams of the registry, saves it and returns the recording.

    Args:
        left: The team of the left side, a registry identifier or `builtin`.
        right: The team of the right side.
        scenario: A shipped scenario, without agent counts, which the teams decide.
        seed: The seed of the match, or `None` for one drawn from the clock.
        title: The title of the recording, text or a label of `_messages.label`, by default the
            two sides by name, after the tournament match.
        device: `cpu` or `cuda`.
        ability: The ability of the built-in AI on the left and on the right, each from 0 to 1, or
            `None` for the scenario's. It is GRF's team difficulty, which steers every player that
            the built-in AI controls, the whole team of the built-in AI and the teammates of a
            submission's player alike.
        length: The steps the match lasts, or `None` for the scenario's own duration.
        tournament: The tournament, stage and match that the match belongs to, which its
            provenance keeps, or `None`.
        progress: A function called with the share of the match played, from 0 to 1, every 50
            steps, or `None`.
        policy_errors: Whether a submission that fails raises `PolicyError`, which names the team
            and the reason in one line, in place of the submission's own error.
        draw: What a request drew at random, as `draw.resolve` returns it under `draw`, which the
            provenance keeps, or `None`.
        strict: The limits of strict rules, as `tournament.check_strict` gives them, or `None`.
            Under strict rules each submission plays in a process of its own within the limits,
            and a side that breaks one ends the match at once, which raises `ForfeitError`.
        stats: A dictionary that the match fills with its steps and, for each side, the calls of
            its policy, their compute times and the actions it answered, or `None`.
        steps: The steps after which the match stops, or `None` to play it to its end.
        save: Whether to save the recording, which a check of a team leaves out.
        replay: A dictionary that the match fills with what replays it exactly, its seed, the
            settings of its batch and the actions of every step, or `None`.

    Returns:
        The path of the recording in the renderer's folder, or `None` when `save` is false.

    Raises:
        ArgumentError: If a team is unknown, plays another format than the scenario's, or an
            ability lies outside 0 to 1.
        PolicyError: If a submission fails and `policy_errors` asks for it.
        ForfeitError: If a side breaks a rule under strict rules.
    """
    ability = _teams.check_ability(ability)
    if scenario not in [*bundled_scenarios(), *_teams.renderer_scenarios()]:
        raise MessageError('server.play.scenario', scenario=repr(scenario))
    sides = [_teams.side_entry(left), _teams.side_entry(right)]
    _teams.check_scenario(sides, scenario)
    agents = [_teams.agent_count(team, scenario, side) for side, team in enumerate(sides)]
    controls = [_teams.check_control(team.get('control'), team['format']) for team in sides]
    extended = any(
        team['kind'] != 'builtin' and (c['assignment'] == 'fixed' or c['action_set'] == 'v2')
        for team, c in zip(sides, controls, strict=True)
    )
    seed = int(time.time()) % 2**31 if seed is None else int(seed)
    if length is not None:
        from .._tournaments.tournament_runner import length_scenario

        asset = length_scenario(scenario, length)
    elif scenario in _teams.renderer_scenarios():
        asset = str(_teams.scenario_path(scenario))
    else:
        asset = f'{scenario}_l{agents[0]}_r{agents[1]}'
    batch = BatchEnvironment(
        asset,
        agent_counts=[tuple(agents)],
        environment_count=1,
        representation='raw',
        seed=seed,
        auto_reset=False,
        device=device,
        difficulty=None if ability == (None, None) else [ability],
        # GRF uses builtin AI for each player outside a fixed selection.
        action_set='v2' if extended else 'default',
    )
    try:
        reader = _recording.StateReader(int(batch.left_players[0] + batch.right_players[0]))
        batch.reset()
        state = batch.get_state(0)
        frames = [reader.frame(state)]
        # A failure names the side by its entrant, so two entrants of one team stay apart.
        arguments = (
            batch,
            sides,
            scenario,
            agents,
            extended,
            [0, agents[0]],
            side_names(tournament),
        )
        policies: Policies | None = None
        done = False
        stepped: list[list[int]] = []
        if replay is not None:
            replay.update(
                seed=seed,
                scenario=scenario,
                asset=asset,
                agents=list(agents),
                action_set='v2' if extended else 'default',
                ability=list(ability),
                actions=stepped,
            )
        try:
            if strict is not None:
                from . import strict as _strict

                policies = _strict.StrictPolicies(*arguments, seed=seed, limits=strict)
            else:
                policies = Policies(*arguments, seed=seed)
            lineup = reader.lineup(state)
            timing = _recording.scenario_timing(state)
            # A match takes one frame more than its steps, the scenario's own or those of
            # `length`.
            total = timing['duration'] + 1 if timing['duration'] > 0 else _FRAMES
            while not done and (steps is None or len(frames) <= steps):
                parts = policies.observe()
                try:
                    answers = policies.decide(parts)
                except RuleError:
                    raise
                except PolicyError as error:
                    # A requested match raises the submission's own error, as it always has.
                    if policy_errors:
                        raise
                    raise (error.__cause__ or error) from None
                actions = policies.actions(parts, answers)
                if replay is not None:
                    stepped.append([int(value) for value in actions[0].tolist()])
                _, _, finished, _ = batch.step(actions)
                done = bool(finished[0])
                frames.append(reader.frame(batch.get_state(0), 1 if done else 0))
                if len(frames) % 50 == 0 and progress is not None:
                    progress(min(len(frames) / total, 0.99))
            policies.finish()
        except RuleError as broken:
            found = policies.stats() if policies is not None else broken.stats
            raise ForfeitError(broken, frame_score(frames[-1]), len(frames) - 1, found) from None
        finally:
            if policies is not None:
                policies.close()
                if stats is not None:
                    # A match that ended before its own end, by a rule or a limit of steps, says
                    # so, so that no report takes it for a full match.
                    stats.update(steps=len(frames) - 1, cut_short=not done, sides=policies.stats())
        difficulty = batch.difficulty[0].tolist()
    finally:
        batch.close()
    if not save:
        return None
    # A tournament's match names its sides as the tournament's entrants, such as a renamed team.
    # A name or title that cuju makes travels as a label, and a person's as text.
    entrants = side_names(tournament)
    names = [entrants[side] or _teams.shown_name(team) for side, team in enumerate(sides)]
    if not title:
        title = game_title(names, tournament)
    elif (
        isinstance(title, str)
        and tournament is not None
        and not title.startswith(str(tournament.get('name')))
    ):
        title = f'{tournament.get("name")}, {tournament.get("label")}, {title}'
    # The ability that played, the scenario's where none was given, goes with each team.
    played = [round(float(value), 4) for value in difficulty]
    teams = [
        {
            **{key: value for key, value in team.items() if key not in ('name_id', 'name_values')},
            **_messages.named('name', entrants[side] or _teams.shown_name(team)),
            'ability': played[side],
        }
        for side, team in enumerate(_teams.match_teams(left, right))
    ]
    provenance = {
        'source': 'requested_match',
        'seed': seed,
        'scenario': scenario,
        'teams': [left, right],
        'controls': controls,
        'agent_counts': agents,
        'action_set': 'v2' if extended else 'default',
        'ability': played,
    }
    if length is not None:
        provenance['length'] = int(length)
    if draw is not None:
        provenance['draw'] = draw
    if tournament is not None:
        provenance['tournament'] = tournament
    head = _recording.header(title, scenario, lineup, teams, len(frames), timing, provenance)
    path = _library.save(head, frames)
    try:
        _achievements.award_match(head, frames, [left, right], path.stem)
    except Exception as error:
        logging.getLogger('cuju').warning('cuju render could not record achievements, %s', error)
    return path


class PolicyMessageError(_messages.Message, PolicyError):
    """A `PolicyError` whose text is a message of the server, which the page translates."""

    _wrapper = True


def frame_score(frame: bytes) -> list[int]:
    """Returns the score of the left and the right side in a frame of a recording."""
    return list(_SCORE.unpack_from(frame, 8))


class RuleError(PolicyError):
    """Raised when a side breaks a rule under strict rules, with each side that broke one.

    Attributes:
        breaks: Each side that broke a rule at that moment, as `(side, kind, reason, detail)`,
            the side 0 for the left and 1 for the right, the kind one of `tournament.RULES`, the
            reason a label of a server message and the detail of an invalid action, `count`,
            `type` or `range`, else `None`.
        stats: The calls, timings and actions of each side, for a break before the policies of
            the match have loaded.
    """

    def __init__(self, breaks: list[tuple[Any, ...]], stats: list[Any] | None = None) -> None:
        self.breaks = [(*found, None)[:4] if len(found) == 3 else tuple(found) for found in breaks]
        super().__init__('; '.join(found[2]['text'] for found in self.breaks))
        self.stats = stats or [None, None]


class ForfeitError(Exception):
    """Raised when a match under strict rules ends early, since a side broke a rule.

    Attributes:
        rule: The rule as a tournament's result keeps it, the side that broke it, `home` for the
            left, `away` for the right or `both`, the kind, the reason as text with the id and
            values of its message, the step and the score at that moment.
        stats: The steps of the match and the calls, timings and actions of each side up to
            that moment.
    """

    def __init__(self, broken: RuleError, score: list[int], step: int, stats: list[Any]) -> None:
        sides = {found[0] for found in broken.breaks}
        _, kind, reason, detail = broken.breaks[0]
        if len(broken.breaks) > 1:
            reason = _messages.label(
                'server.strict.both', home=broken.breaks[0][2], away=broken.breaks[1][2]
            )
        side = 'both' if len(sides) > 1 else ('home', 'away')[next(iter(sides))]
        self.rule = {
            'side': side,
            'kind': kind,
            'reason': reason['text'],
            'reason_id': reason['id'],
            'reason_values': reason['values'],
            'detail': detail,
            'step': step,
            'at': score,
        }
        self.stats = {'steps': step, 'cut_short': True, 'sides': stats}
        super().__init__(reason['text'])


class CallStats:
    """The calls of one side's policy in a match, their compute times and the actions answered."""

    def __init__(self) -> None:
        self.calls = 0
        self.total = 0.0
        self.largest = 0.0
        self.first: float | None = None
        self.actions: collections.Counter[int] = collections.Counter()
        self.load: float | None = None
        self.reset: float | None = None
        self.memory: float | None = None

    def add(self, seconds: float, actions: list[int]) -> None:
        """Counts one call that took `seconds` and answered `actions`."""
        self.calls += 1
        self.total += seconds
        self.largest = max(self.largest, seconds)
        if self.first is None:
            self.first = seconds
        self.actions.update(actions)

    def mean(self, after_first: bool = False) -> float:
        """Returns the mean seconds of a call, those after the first alone when asked."""
        if after_first and self.calls > 1:
            return (self.total - (self.first or 0.0)) / (self.calls - 1)
        return self.total / self.calls if self.calls else 0.0

    def summary(self) -> dict[str, Any]:
        """Returns the calls, the first, mean and largest compute time in ms and the actions."""

        def ms(value: float | None) -> float | None:
            return None if value is None else round(value * 1000, 3)

        found = {
            'calls': self.calls,
            'first_ms': ms(self.first),
            'mean_ms': ms(self.mean()) if self.calls else None,
            'max_ms': ms(self.largest) if self.calls else None,
            'mean_after_first_ms': ms(self.mean(True)) if self.calls else None,
            'actions': {str(action): count for action, count in sorted(self.actions.items())},
        }
        if self.load is not None:
            found['load_seconds'] = round(self.load, 3)
        if self.reset is not None:
            found['reset_seconds'] = round(self.reset, 3)
        if self.memory:
            found['memory_mb'] = round(self.memory, 1)
        return found


class RandomPolicy:
    """The policy of the random entrant, an action of the default set at random for each call.

    Its generator is seeded from the seed of the match and its side, so a match plays the same
    actions again with the same seed.
    """

    def __init__(self, seed: int, side: int) -> None:
        self.random = random.Random(hashlib.sha256(f'{seed}/random/{side}'.encode()).digest())

    def act(self, obs: Any, count: int) -> list[int]:
        """Returns one action of the 19 of the default set for each controlled player."""
        del count
        return [self.random.randrange(DEFAULT_ACTIONS) for _ in obs['players_raw']]


class Policies:
    """The registered policies of a match, the agents each one plays and the actions they return.

    A step comes in three parts, so the calls of the policies may run on a thread of their own
    while another thread steps the batch. `observe` reads the batch, on the thread that steps it,
    `decide` calls the policies with what `observe` read and touches nothing else, and `actions`
    puts their answers into the actions of the step. Each policy counts Kaggle's `step` by its
    own calls, as `KaggleAgent` does.

    Attributes:
        batch: The batch, with the raw representation.
        players: One entry for each submission, its side, name, function and columns.
    """

    def __init__(
        self,
        batch: Any,
        sides: list[dict[str, Any]],
        scenario: str,
        agents: list[int],
        extended: bool,
        firsts: list[int],
        names: list[Any] | None = None,
        fits: list[dict[str, Any] | None] | None = None,
        seed: int = 0,
    ) -> None:
        """Loads the submission of each side that has one, and the random entrant's policy.

        Args:
            batch: The batch, which only `observe` reads.
            sides: The registry entries of the left and the right team.
            scenario: The scenario, which places the selected players of a fixed assignment.
            agents: The agents of each side that its team plays.
            extended: Whether the batch plays the v2 action set, so that a submission of the
                default set has its answers checked against 19 actions.
            firsts: The column of the first agent that each side's team plays.
            names: The name of each side that its failure gives, text, a label or `None` for
                the team's own, such as the entrants of a tournament, or `None` for both.
            fits: How each side plays a challenge, as `challenge_fit` of the registry gives it,
                with its selected players and its players out, or `None` for both sides of a
                match, whose teams play every player they control.
            seed: The seed of the match, from which the random entrant draws its actions.
        """
        self.batch = batch
        self.players: list[dict[str, Any]] = []
        for side, team in enumerate(sides):
            if team['kind'] == 'builtin' or not agents[side]:
                continue
            columns = list(range(firsts[side], firsts[side] + agents[side]))
            control = _teams.check_control(team.get('control'), team['format'])
            fit = (fits or [None, None])[side]
            selected = None
            if fit is not None:
                selected = fit['selected']
            elif control['assignment'] == 'fixed':
                selected = _teams.selected_players(control, _teams.scenario_players(scenario, side))
            name = (names or [None, None])[side] or team['name']
            self.players.append(
                {
                    'side': side,
                    'name': name,
                    'runner': self._runner(team, side, extended, control, seed, name),
                    'columns': columns,
                    'selected': selected,
                    'slots': None if fit is None else fit['slots'],
                    'held': {},
                    'calls': 0,
                    'stats': CallStats(),
                }
            )

    def _runner(
        self,
        team: dict[str, Any],
        side: int,
        extended: bool,
        control: dict[str, Any],
        seed: int,
        name: Any,
    ) -> Any:
        """Returns what answers the calls of a side's policy, loaded in this process."""
        del name
        if team['kind'] == 'random':
            return RandomPolicy(seed, side)
        function = _teams.load_agent(team['id'])
        if extended and control['action_set'] == 'default':
            function = _default_actions(function)
        return AgentRunner(function)

    def stats(self) -> list[dict[str, Any] | None]:
        """Returns the calls, timings and actions of each side, `None` for a side without one."""
        found: list[dict[str, Any] | None] = [None, None]
        for player in self.players:
            found[player['side']] = player.setdefault('stats', CallStats()).summary()
        return found

    def finish(self) -> None:
        """Checks what only the whole match tells, as strict rules do for the mean of a call."""

    def close(self) -> None:
        """Ends what the policies hold, such as the processes of strict rules."""

    def observe(self) -> list[Any]:
        """Returns what each policy sees at the current step, on the thread that steps the batch.

        Each entry holds the columns that the policy plays at the step, the columns of its selected
        players who left the pitch, its observation, and the answers that count, in the order of
        the columns, or `None` for all of them. An entry is `None` when GRF hands the players of a
        fixed assignment over again, and the built-in AI plays them for that step. A team that
        plays a challenge with players out still sees one observation for each player it
        controls, and a player out sees the observation of its first player that plays.
        """
        raw = {name: tensor.cpu() for name, tensor in self.batch.raw().items()}
        parts: list[Any] = []
        for player in self.players:
            columns, missing = player['columns'], []
            if player['selected'] is not None:
                found = _player_columns(raw, columns, player['selected'], player['held'])
                if found is None:
                    parts.append(None)
                    continue
                columns, missing = found
            seen, pick = list(columns), None
            slots = player.get('slots')
            if slots is not None:
                seen = [columns[0] if place is None else columns[place] for place in slots]
                pick = [slots.index(place) for place in range(len(columns))]
            obs = observation(self.batch, 0, seen, step=player['calls'], raw=raw)
            player['calls'] += 1
            parts.append((columns, missing, obs, pick))
        return parts

    def decide(self, parts: list[Any]) -> list[Any]:
        """Calls each policy with its observation and returns its actions, checked.

        Raises:
            PolicyError: If a policy raises, or answers with anything but actions of the set.
        """
        count = self.batch.action_count
        answers: list[Any] = []
        for player, part in zip(self.players, parts, strict=True):
            if part is None:
                answers.append(None)
                continue
            obs = part[2]
            started = time.perf_counter()
            try:
                # Kaggle's single form for one player, and its multi agent form for several.
                answer = player['runner'].act(obs, count)
            except Exception as error:
                raise _policy_error(error, player['name']) from error
            # A player that a caller added by hand, as a challenge does, counts its calls too.
            player.setdefault('stats', CallStats()).add(time.perf_counter() - started, answer)
            answers.append(answer)
        return answers

    def actions(self, parts: list[Any] | None, answers: list[Any] | None) -> torch.Tensor:
        """Returns the actions of a step, `[1, agents]`, idle in the columns of no policy.

        Without answers, the built-in AI plays every agent of the policies for the step, as the
        v2 action set allows. It also plays the agents of a fixed assignment outside the selection,
        and the selected players off the pitch.

        Raises:
            PolicyError: If the built-in AI should play an agent of a batch without the v2 set.
        """
        actions = torch.zeros((1, self.batch.agents), dtype=torch.int32)
        for index, player in enumerate(self.players):
            part = None if parts is None or answers is None else parts[index]
            if part is None or player['selected'] is not None:
                if part is None and self.batch.action_count <= _BUILTIN_AI:
                    raise PolicyMessageError('server.policy.action_set')
                actions[:, player['columns']] = _BUILTIN_AI
            if part is None:
                continue
            columns, missing, _, pick = part
            answer = answers[index] if pick is None else [answers[index][slot] for slot in pick]
            actions[:, columns] = torch.tensor(answer, dtype=torch.int32).reshape(1, -1)
            # A selected player off the pitch, after a red card for one, is left to the built-in
            # AI, and the submission keeps playing the others.
            actions[:, missing] = _BUILTIN_AI
        return actions


class _Job:
    """One call on the thread of the policies, its answer or its error, and when it was asked."""

    def __init__(self, function: Callable[[], Any]) -> None:
        self.function = function
        self.started = time.monotonic()
        self.done = threading.Event()
        self.value: Any = None
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            self.value = self.function()
        except BaseException as error:
            # A policy may raise anything, even an exit, and the caller hears of it all.
            self.error = error
            if debugging():
                traceback.print_exc()
        finally:
            self.done.set()

    def result(self) -> Any:
        """Returns the answer, or raises the error as a `PolicyError`."""
        if isinstance(self.error, PolicyError):
            raise self.error
        if self.error is not None:
            raise _policy_error(self.error) from self.error
        return self.value


class PolicyRunner:
    """Runs the registered policies of a match on a thread of their own, one step at a time.

    The thread that steps the batch asks for the actions of a step in two calls. `request` reads
    the observations and starts the call of the policies, and `actions` waits for the answer
    within a budget and returns the actions of the step. A policy that misses the budget leaves
    its players to the built-in AI for that step, and its late answer is discarded. While a late
    call still runs, the steps that follow go to the built-in AI without a call, since a policy
    answers one observation at a time. The runner keeps no clock beyond the budget, so a game at
    real time and a run faster than real time use it alike, the second without a budget.

    Attributes:
        policies: The policies, once `load` has returned.
        hang: The seconds a call may run before the policy counts as stuck, or `None`.
        late: The steps that the built-in AI played in place of the policies.
        streak: The steps in a row, up to the last one, that the built-in AI played in their place.
    """

    def __init__(self, hang: float | None = None) -> None:
        self.policies: Policies | None = None
        self.hang = hang
        self.late = 0
        self.streak = 0
        self._jobs: queue.Queue[_Job | None] = queue.Queue()
        self._busy: _Job | None = None
        self._turn: tuple[Any, _Job] | None = None
        # A daemon thread, so that a policy that never returns cannot keep the process alive.
        threading.Thread(target=self._work, daemon=True, name='cuju-policies').start()

    def _work(self) -> None:
        while (job := self._jobs.get()) is not None:
            job.run()

    def _submit(self, function: Callable[[], Any]) -> _Job:
        job = _Job(function)
        self._busy = job
        self._jobs.put(job)
        return job

    def load(self, factory: Callable[[], Policies], timeout: float | None) -> None:
        """Loads the policies on their thread, within `timeout` seconds or without a limit.

        Raises:
            PolicyError: If loading fails or takes longer than `timeout`.
        """
        job = self._submit(factory)
        if not job.done.wait(timeout):
            raise PolicyMessageError('server.policy.load', count=f'{timeout:g}')
        self.policies = job.result()

    def _check(self) -> None:
        """Raises for a call that failed, even a late one, and for a call that runs too long."""
        job = self._busy
        if job is None:
            return
        if job.done.is_set():
            if job.error is not None:
                job.result()
            return
        if self.hang is not None and time.monotonic() - job.started > self.hang:
            raise PolicyMessageError('server.policy.silent', count=f'{self.hang:g}')

    def request(self) -> None:
        """Reads the observations of the current step and starts the call of the policies.

        Raises:
            PolicyError: If a call failed, or has run longer than `hang`.
        """
        self._check()
        if self._busy is not None and not self._busy.done.is_set():
            # A late call still runs, so the built-in AI plays this step.
            self._turn = None
            return
        policies = self.policies
        parts = policies.observe()
        self._turn = (parts, self._submit(lambda: policies.decide(parts)))

    def wait(self, timeout: float | None) -> bool:
        """Waits for the answer to the step requested last and returns whether it came in time.

        Raises:
            PolicyError: If the call failed.
        """
        if self._turn is None:
            return False
        job = self._turn[1]
        if not job.done.wait(timeout):
            return False
        job.result()
        return True

    def actions(self, budget: float | None = None) -> torch.Tensor:
        """Returns the actions of the step requested last, `[1, agents]`.

        Args:
            budget: The seconds from the request within which the answer counts, or `None` to wait
                for the answer however long it takes.

        Raises:
            PolicyError: If the call failed.
        """
        turn, self._turn = self._turn, None
        if turn is not None:
            parts, job = turn
            wait = None if budget is None else max(0.0, job.started + budget - time.monotonic())
            if job.done.wait(wait):
                answers = job.result()
                self.streak = 0
                return self.policies.actions(parts, answers)
        self.late += 1
        self.streak += 1
        return self.policies.actions(None, None)

    def close(self) -> None:
        """Lets the thread of the policies end as soon as it is free."""
        self._jobs.put(None)


def _player_columns(
    raw: dict[str, torch.Tensor], columns: list[int], selected: list[int], held: dict[int, int]
) -> tuple[list[int], list[int]] | None:
    """Finds the agents holding the selected players in submission order, and those left over.

    GRF clears the selection of a side at a set piece, and for that step an agent reports no player,
    a step that returns `None`. A selected player that no agent reports for another reason, such as
    a red card, keeps the agent it held last, or else an agent that holds no selected player, and
    that agent is the second list. `held` keeps the agent each selected player held last.
    """
    active = [int(raw['active'][0, column]) for column in columns]
    if -1 in active:
        return None
    by_player = {}
    for column, index in zip(columns, active, strict=True):
        if index in selected and index not in by_player:
            by_player[index] = column
    held.update(by_player)
    free = [column for column in columns if column not in by_player.values()]
    missing = []
    for index in selected:
        if index in by_player:
            continue
        column = held.get(index)
        if column not in free:
            column = free[0]
        free.remove(column)
        by_player[index] = column
        missing.append(column)
    return [by_player[index] for index in selected], missing


def _default_actions(function: Any) -> Any:
    """Checks the submission set before translating negative indices to the batch set."""
    two = accepts_configuration(function)

    def run(obs: Any, configuration: Any) -> list[int]:
        answer = function(obs, configuration) if two else function(obs)
        count = len(obs['players_raw'])
        values = [action_index(answer, 19)] if count == 1 else action_indices(answer, 19, count)
        return [value % 19 for value in values]

    return run


def main(arguments: list[str] | None = None) -> None:
    """Plays the match that the command line names and reports the recording."""
    global _reports
    parser = argparse.ArgumentParser(prog='python -m cuju.render._playing.play')
    parser.add_argument('--left', required=True)
    parser.add_argument('--right', required=True)
    parser.add_argument('--scenario', default='11_vs_11_kaggle')
    parser.add_argument('--seed', type=int, default=None)
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--left-ability', type=float, default=None)
    parser.add_argument('--right-ability', type=float, default=None)
    parser.add_argument('--length', type=int, default=None)
    parser.add_argument('--tournament', type=json.loads, default=None)
    parser.add_argument('--draw', type=json.loads, default=None)
    parser.add_argument('--strict', type=json.loads, default=None)
    parser.add_argument('--replay', action='store_true')
    options = parser.parse_args(arguments)
    # The reports keep a copy of standard output, and everything else written there, by Python or
    # by native code, goes to standard error.
    sys.stdout.flush()
    _reports = os.fdopen(os.dup(1), 'w', encoding='utf-8')
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    stats: dict[str, Any] = {}
    replay: dict[str, Any] | None = {} if options.replay else None
    try:
        path = play(
            options.left,
            options.right,
            options.scenario,
            options.seed,
            None,
            options.device,
            (options.left_ability, options.right_ability),
            options.length,
            options.tournament,
            lambda share: _report(progress=share),
            # A tournament's failure names the team that failed, a requested match's stays.
            policy_errors=options.tournament is not None,
            draw=options.draw,
            strict=options.strict,
            stats=stats,
            replay=replay,
        )
    except ForfeitError as forfeit:
        # A side that broke a rule of strict rules ends the match, which reports the forfeit.
        _report(progress=1.0, forfeit=forfeit.rule, stats=forfeit.stats, replay=replay)
        return
    except PolicyError as error:
        _report(error=str(error), **_messages.id_fields(error))
        sys.exit(1)
    except Exception as error:
        _report(error=_messages.described(error), **_messages.id_fields(error))
        sys.exit(1)
    _report(progress=1.0, match=path.stem, stats=stats, replay=replay)


if __name__ == '__main__':
    # The match runs from the module as the package imports it, so its errors are the classes
    # that strict rules raise, which a copy of this file run as the main module would not catch.
    from cuju.render._playing import play as _module

    _module.main()
