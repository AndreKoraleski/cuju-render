# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""Plays a game in which a person controls one player of a side, against a team of the registry.

The server runs this module in a process of its own for the page's Play a game. The process steps
one environment at real time, ten steps a second, and streams every frame to the page through a
live source that stays off the list of sources. Commands come from the server as one JSON line at
a time on standard input, the input of each person's side, pause and quit, and reports go back as
one JSON line at a time on a channel of their own, as for a requested match.

Each person's side is a scenario's agent, as `{scenario}_l1_r0` names it, so the person controls
one player and the engine hands that control to the designated player as play moves, the player
nearest the ball among them, as GRF does for its own human players. The keys and buttons that
the page reads become GRF's 19 default actions through GRF's own controller logic, so a person's
actions are actions like any agent's and the match stays the match the engine would play for them.

The other team, and the person's teammates, are the built-in AI or a submission of the registry.
A submission loads and plays in this process from its own folder, as in a requested match, and its
calls run on a thread of their own, `PolicyRunner`, so it never holds the game back. A step whose
answer comes late goes to the built-in AI, and a submission that fails or stops answering ends the
game, which keeps its recording.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import queue
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any, TextIO

import torch

from cuju import BatchEnvironment, bundled_scenarios

from .._format import recording as _recording
from .._registry import teams as _teams
from .._store import library as _library
from .._text import messages as _messages
from .._text.messages import MessageError
from .._watch import live as _live
from . import achievements as _achievements
from .play import Policies, PolicyError, PolicyMessageError, PolicyRunner, game_title, side_names

# The names of the inputs that the page sends, four directions on the screen and the buttons.
DIRECTIONS = ('left', 'right', 'up', 'down')
BUTTONS = ('long_pass', 'high_pass', 'short_pass', 'shot', 'sliding', 'sprint', 'dribble')
INPUTS = DIRECTIONS + BUTTONS
# GRF: the indices of the default action set.
_IDLE, _LEFT, _TOP_LEFT, _TOP, _TOP_RIGHT, _RIGHT, _BOTTOM_RIGHT, _BOTTOM, _BOTTOM_LEFT = range(9)
_PRESS = {
    'long_pass': 9,
    'high_pass': 10,
    'short_pass': 11,
    'shot': 12,
    'sprint': 13,
    'sliding': 16,
    'dribble': 17,
}
_RELEASE_DIRECTION = 14
# GRF: releasing sprint and dribble are actions of the default set. The engine releases the other
# buttons itself after every step in play, so their releases change nothing and take the place of
# GRF's release actions as idle.
_RELEASE = {
    'long_pass': _IDLE,
    'high_pass': _IDLE,
    'short_pass': _IDLE,
    'shot': _IDLE,
    'sliding': _IDLE,
    'sprint': 15,
    'dribble': 18,
}
# GRF: `get_env_action` checks the buttons in this order, which decides the one action of a step.
_ORDER = ('long_pass', 'high_pass', 'short_pass', 'shot', 'sliding', 'sprint', 'dribble')
STEPS_PER_SECOND = 10
# Without any message from the server for this long the game pauses, and after this long it ends.
PAUSE_AFTER_SECONDS = 8.0
END_AFTER_SECONDS = 120.0
# A submission answers each step within this share of the step's time, measured from when its
# observation is read, or the built-in AI plays its players for the step.
POLICY_BUDGET = 0.9
# Loading the submissions, and their first answer, each get this long, since a Kaggle agent often
# loads its model on the first call. Both together stay well within the server's two minutes for
# the start of a game.
LOAD_SECONDS = 45.0
FIRST_CALL_SECONDS = 45.0
# A submission that has not answered for this long counts as stuck, and the game ends.
HANG_SECONDS = 10.0
# After this many steps in a row without an answer in time, the page hears of it.
LATE_STREAK = 10
_SCORE = struct.Struct('<2i')

# The channel of the reports, standard output until `main` moves everything else away.
_reports: TextIO = sys.stdout


def _report(**entries: Any) -> None:
    """Writes one line of progress for the server."""
    _reports.write(json.dumps(entries) + '\n')
    _reports.flush()


class Controller:
    """GRF's controller of a person's player, `controller_base.Controller`, on the 19 actions.

    Each step yields one action. A change of direction comes first, the new direction or a release
    of the direction, and otherwise the first button in GRF's order whose state changed, its press
    or its release. Sprint and dribble stay pressed in the engine until released, while the passes,
    the shot and the slide act on the step they are pressed.
    """

    def __init__(self) -> None:
        self._direction = _IDLE
        self._buttons: dict[str, bool] = {}

    def act(self, held: frozenset[str], pressed: frozenset[str]) -> int:
        """Returns the action of one step.

        Args:
            held: The inputs held at the step, directions and buttons, in the side's own frame.
            pressed: The buttons pressed since the last step, even if already let go, as GRF's
                queue of key presses holds them.
        """
        left, right = 'left' in held, 'right' in held
        top, bottom = 'up' in held, 'down' in held
        direction = _IDLE
        for action, on in (
            (_TOP_LEFT, top and left),
            (_TOP_RIGHT, top and right),
            (_BOTTOM_LEFT, bottom and left),
            (_BOTTOM_RIGHT, bottom and right),
            (_RIGHT, right),
            (_LEFT, left),
            (_TOP, top),
            (_BOTTOM, bottom),
        ):
            if on:
                direction = action
                break
        if direction != self._direction:
            self._direction = direction
            return _RELEASE_DIRECTION if direction == _IDLE else direction
        active = held | pressed
        for name in _ORDER:
            state = name in active
            if self._buttons.get(name, False) != state:
                self._buttons[name] = state
                return _PRESS[name] if state else _RELEASE[name]
        return _IDLE


def own_frame(held: frozenset[str], side: int) -> frozenset[str]:
    """Returns the inputs of a side in its own frame from the directions on the screen.

    The page's broadcast camera looks across the pitch from the main stand, so right on the screen
    points along the pitch's x axis and up points away from the camera. GRF's right team plays in a
    frame turned half a circle, so its directions swap left with right and up with down.
    """
    if side == 0:
        return held
    swap = {'left': 'right', 'right': 'left', 'up': 'down', 'down': 'up'}
    return frozenset(swap.get(name, name) for name in held)


class Game:
    """One environment in which people control one player of a side each, stepped on request.

    Attributes:
        humans: Whether a person plays the left side and the right side.
        team_ids: The registry team of each side, the person's teammates on a person's side.
        counts: The agents of each side, a person's first.
        action_set: `v2` when a submission plays, so the built-in AI may stand in for it, or
            `default`.
        actions: The actions of every step so far, one list per step, the left agents first.
        frames: The frames of every step so far, the reset first.
        lineup: The header entry of each player.
        teams: The left and right team, as a recording's header holds them.
        runner: The runner of the submissions, or `None` when the built-in AI plays every player.
        error: Why a submission ended the game, or `None`.
        error_ids: The id and values of the message of `error`, when it has one, for the page.
        controlled: The player in its team that each person controls, on a side shared with a
            submission, where the frames mark every player of the side's agents, or `None`.
    """

    def __init__(
        self,
        scenario: str,
        humans: tuple[bool, bool],
        ability: tuple[float | None, float | None] = (None, None),
        seed: int | None = None,
        device: str = 'cpu',
        teams: tuple[str, str] = (_teams.BUILTIN, _teams.BUILTIN),
        load_seconds: float | None = LOAD_SECONDS,
        first_call_seconds: float | None = FIRST_CALL_SECONDS,
        length: int | None = None,
        tournament: dict[str, Any] | None = None,
    ) -> None:
        """Creates and resets the environment, and loads the submissions that play.

        Args:
            scenario: A shipped scenario, without agent counts.
            humans: Whether a person plays the left side and the right side, at least one.
            ability: The ability of the built-in AI on the left and on the right, each from 0 to
                1, or `None` for the scenario's.
            seed: The seed of the game, or `None` for one drawn from the clock.
            device: `cpu` or `cuda`.
            teams: The registry team of each side. A side without a person is that team, and a
                person's side takes it as the person's teammates, the built-in AI by default.
            load_seconds: How long the submissions may take to load, or `None` without a limit.
            first_call_seconds: How long the submissions may take to answer the first
                observation, or `None` without a limit.
            length: The steps the game lasts, or `None` for the scenario's own duration.
            tournament: The tournament match that the game plays, which its provenance keeps,
                with the names of the people in `names`, or `None`.

        Raises:
            ArgumentError: If the scenario is not shipped, no side has a person, an ability lies
                outside 0 to 1, or a team cannot play its side.
            PolicyError: If a submission fails to load, fails on its first observation or misses
                its allowance for either.
        """
        ability = _teams.check_ability(ability)
        if scenario not in [*bundled_scenarios(), *_teams.renderer_scenarios()]:
            raise MessageError('server.scenario', scenario=repr(scenario))
        if not any(humans):
            raise MessageError('server.game.person')
        if (
            not isinstance(teams, (tuple, list))
            or len(teams) != 2
            or not all(isinstance(value, str) for value in teams)
        ):
            raise MessageError('server.game.registry_teams', teams=repr(teams))
        self.humans = (bool(humans[0]), bool(humans[1]))
        self.scenario = scenario
        self.seed = int(time.time()) % 2**31 if seed is None else int(seed)
        self.team_ids = [str(teams[0]), str(teams[1])]
        entries = [_teams.entry(identifier) for identifier in self.team_ids]
        agents = _teams.game_agents(entries, scenario, self.humans)
        self.counts = [int(self.humans[side]) + agents[side] for side in (0, 1)]
        self.action_set = 'v2' if any(agents) else 'default'
        self.length = None if length is None else int(length)
        self.tournament = tournament
        if self.length is not None:
            from .._tournaments.tournament_runner import length_scenario

            asset = length_scenario(scenario, self.length)
        elif scenario in _teams.renderer_scenarios():
            asset = str(_teams.scenario_path(scenario))
        else:
            asset = f'{scenario}_l{self.counts[0]}_r{self.counts[1]}'
        self.batch = BatchEnvironment(
            asset,
            agent_counts=[tuple(self.counts)],
            environment_count=1,
            representation='raw',
            seed=self.seed,
            auto_reset=False,
            device=device,
            difficulty=None if ability == (None, None) else [ability],
            action_set=self.action_set,
        )
        self.sides = [side for side in (0, 1) if self.humans[side]]
        # A person's agent comes first on the side, and the teammates' agents follow it.
        self.person_column = {0: 0, 1: self.counts[0]}
        self.shared = [side for side in self.sides if self.counts[side] > 1]
        self.controlled: list[int | None] = [None, None]
        self.controllers = {side: Controller() for side in self.sides}
        self.reader = _recording.StateReader(
            int(self.batch.left_players[0] + self.batch.right_players[0])
        )
        self.batch.reset()
        self.runner: PolicyRunner | None = None
        self.error: str | None = None
        self.error_ids: dict[str, Any] = {}
        self._failure: PolicyError | None = None
        if any(agents):
            firsts = [int(self.humans[0]), self.counts[0] + int(self.humans[1])]
            batch, runner = self.batch, PolicyRunner(hang=HANG_SECONDS)
            try:
                runner.load(
                    lambda: Policies(batch, entries, scenario, agents, True, firsts), load_seconds
                )
                runner.request()
                if not runner.wait(first_call_seconds):
                    raise PolicyMessageError(
                        'server.policy.first', seconds=f'{first_call_seconds:g}'
                    )
            except BaseException:
                runner.close()
                self.batch.close()
                raise
            self.runner = runner
        state = self.batch.get_state(0)
        self.lineup = self.reader.lineup(state)
        self.frames = [self.reader.frame(state)]
        self.actions: list[list[int]] = []
        self.done = False
        played = [round(float(value), 4) for value in self.batch.difficulty[0].tolist()]
        two = all(self.humans)
        named = side_names(tournament)
        self.teams = []
        for side, team in enumerate(_teams.match_teams(*self.team_ids)):
            # A tournament names the side of an agent as its entrant, such as Built-in AI 0.80.
            # Names that cuju makes, such as You, travel as labels, and a person's name as text.
            name = _teams.shown_name(team)
            if not self.humans[side]:
                name = named[side] or name
            else:
                person = named[side] or (
                    _messages.label('server.names.player', number=side + 1)
                    if two
                    else _messages.label('server.names.you')
                )
                if team['id'] != _teams.BUILTIN:
                    person = _messages.label('server.names.person_with', person=person, team=name)
                name = person
            made = ('name_id', 'name_values')
            kept = {key: value for key, value in team.items() if key not in made}
            self.teams.append(
                {
                    **kept,
                    **_messages.named('name', name),
                    'ability': played[side],
                    'person': self.humans[side],
                }
            )

    @property
    def title(self) -> dict[str, Any]:
        """Returns the title of the game as a label, its teams by name, after its tournament
        match, which reads as English text in `title['text']`."""
        return game_title([_teams.shown_name(team) for team in self.teams], self.tournament)

    def step(
        self,
        inputs: dict[int, tuple[frozenset[str], frozenset[str]]],
        budget: float | None = None,
    ) -> bytes:
        """Plays one step with the held and pressed inputs of each person's side, on the screen.

        Args:
            inputs: The held inputs and the pressed buttons of each person's side.
            budget: The seconds that the submissions have for their answer from when they saw the
                step, or `None` to wait for it however long it takes.

        Returns:
            The frame of the step.

        Raises:
            PolicyError: If a submission failed or stopped answering, before the step is played.
        """
        if self._failure is not None:
            raise self._failure
        if self.runner is not None:
            row = self.runner.actions(budget)[0].tolist()
        else:
            row = [0] * sum(self.counts)
        for side in self.sides:
            held, pressed = inputs.get(side, (frozenset(), frozenset()))
            row[self.person_column[side]] = self.controllers[side].act(
                own_frame(held, side), pressed
            )
        self.actions.append(row)
        _, _, finished, _ = self.batch.step(torch.tensor([row], dtype=torch.int32))
        self.done = bool(finished[0])
        frame = self.reader.frame(self.batch.get_state(0), 1 if self.done else 0)
        self.frames.append(frame)
        if self.shared:
            active = self.batch.raw()['active'][0].tolist()
            for side in self.shared:
                self.controlled[side] = int(active[self.person_column[side]])
        if self.runner is not None and not self.done:
            # The submissions see the new step at once, and answer while the game waits for it.
            try:
                self.runner.request()
            except PolicyError as error:
                self._failure = error
        return frame

    def header(self) -> bytes:
        """Returns the header of the game so far, as its recording holds it."""
        provenance = {
            'source': 'human_game',
            'seed': self.seed,
            'scenario': self.scenario,
            'humans': list(self.humans),
            'teams': list(self.team_ids),
            'agent_counts': list(self.counts),
            'action_set': self.action_set,
            'ability': [team['ability'] for team in self.teams],
        }
        if self.runner is not None:
            provenance['late_steps'] = self.runner.late
        if self.length is not None:
            provenance['length'] = self.length
        if self.tournament is not None:
            provenance['tournament'] = self.tournament
        return _recording.header(
            self.title,
            self.scenario,
            self.lineup,
            self.teams,
            len(self.frames),
            _recording.scenario_timing(self.batch.get_state(0)),
            provenance,
        )

    def save(self) -> Path:
        """Saves the game so far as a recording in the library and returns its path."""
        return _library.save(self.header(), self.frames)

    def close(self) -> None:
        """Frees the environment and lets the thread of the submissions end."""
        if self.runner is not None:
            self.runner.close()
        self.batch.close()


class _Commands:
    """Reads the server's commands from standard input on a thread of its own."""

    def __init__(self, stream: TextIO) -> None:
        self.queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        threading.Thread(target=self._read, args=(stream,), daemon=True).start()

    def _read(self, stream: TextIO) -> None:
        for line in stream:
            try:
                command = json.loads(line)
            except ValueError:
                continue
            if isinstance(command, dict):
                self.queue.put(command)
        # The server closed the channel, so the game ends.
        self.queue.put(None)


def run(game: Game, commands: _Commands, source: _live.LiveSource, pace: float) -> str:
    """Steps the game at `pace` steps a second while it plays, and returns why it ended.

    The game waits for its first resume, so the page sees the kick-off. Each step takes the inputs
    that arrived last, together with every button pressed since the step before. A submission that
    fails or stops answering ends the game, with the reason in `game.error`.
    """
    held: dict[int, frozenset[str]] = {side: frozenset() for side in game.sides}
    pressed: dict[int, set[str]] = {side: set() for side in game.sides}
    paused, reason = True, 'ready'
    contact = time.monotonic()
    due = contact
    score = None
    controlled = list(game.controlled)
    _report(state='ready', step=0, score=[0, 0])
    while not game.done:
        timeout = max(0.0, due - time.monotonic()) if not paused else 0.25
        try:
            command = commands.queue.get(timeout=timeout)
        except queue.Empty:
            command = {}
        now = time.monotonic()
        if command is None or command.get('quit'):
            return 'quit'
        if command:
            contact = now
            # A pause for silence lifts by itself once the page is heard again, and a pause the
            # person chose waits for the person.
            if paused and reason == 'input' and 'paused' not in command:
                paused, reason = False, 'page'
                due = now
                _report(state='playing', reason='input', step=len(game.actions))
        side = command.get('side')
        if isinstance(side, int) and side in held:
            held[side] = frozenset(command.get('held', ())) & frozenset(INPUTS)
            pressed[side].update(frozenset(command.get('pressed', ())) & frozenset(BUTTONS))
        if 'paused' in command and bool(command['paused']) != paused:
            paused, reason = bool(command['paused']), 'page'
            due = now
            _report(state='paused' if paused else 'playing', reason=reason, step=len(game.actions))
        if now - contact > END_AFTER_SECONDS:
            return 'timeout'
        if not paused and now - contact > PAUSE_AFTER_SECONDS:
            paused, reason = True, 'input'
            _report(state='paused', reason=reason, step=len(game.actions))
        if paused or time.monotonic() < due:
            continue
        inputs = {side: (held[side], frozenset(pressed[side])) for side in game.sides}
        for side in game.sides:
            pressed[side].clear()
        try:
            frame = game.step(inputs, POLICY_BUDGET / pace)
        except PolicyError as error:
            game.error = str(error)
            game.error_ids = _messages.id_fields(error)
            return 'policy'
        source.push(frame, game.lineup)
        # A late step starts the clock again, so a slow moment never brings a burst of steps.
        due = max(due + 1 / pace, time.monotonic() - 2 / pace)
        now_score = list(_SCORE.unpack_from(frame, 8))
        streak = game.runner.streak if game.runner is not None else 0
        moved = game.controlled != controlled
        if now_score != score or len(game.actions) % 10 == 0 or streak == LATE_STREAK or moved:
            score, controlled = now_score, list(game.controlled)
            _report(state='playing', step=len(game.actions), score=score, **_status(game))
    # A full match ends at full time, and any other scenario at the end of its episode.
    timing = _recording.scenario_timing(game.batch.get_state(0))
    return 'full time' if timing['full_match'] else 'episode'


def _status(game: Game) -> dict[str, Any]:
    """Returns what a report says of the play, the people's actions, players and late steps.

    The actions are those that the engine took for each person's agent on the last step, as GRF's
    controller logic turned the keys and buttons into them, and `None` on a side without a person.
    """
    report: dict[str, Any] = {}
    if game.actions:
        report['actions'] = [
            game.actions[-1][game.person_column[side]] if side in game.sides else None
            for side in (0, 1)
        ]
    if game.shared:
        report['controlled'] = game.controlled
    if game.runner is not None:
        report.update(late=game.runner.late, streak=game.runner.streak)
    return report


def _waited_arguments(stream: TextIO) -> list[str] | None:
    """Returns the arguments of a game that a process kept ready reads from its first line.

    The server writes them as one JSON list of strings, and a closed or unreadable channel yields
    `None`, for a process the server no longer needs.
    """
    try:
        arguments = json.loads(stream.readline() or 'null')
    except (OSError, ValueError):
        return None
    if isinstance(arguments, list) and all(isinstance(value, str) for value in arguments):
        return arguments
    return None


def main(arguments: list[str] | None = None) -> None:
    """Plays the game that the command line names, as the server asks.

    With `--warm` alone, the process has already loaded torch, cuju and every module of a game,
    and waits for the arguments of its game as one JSON list on the first line of standard input,
    so the game starts as soon as the server sends them. Such a process plays that one game exactly
    as a process started with the arguments would, and it ends without a game when its input
    closes.
    """
    global _reports
    if arguments is None:
        arguments = sys.argv[1:]
    if arguments == ['--warm']:
        arguments = _waited_arguments(sys.stdin)
        if arguments is None:
            return
    parser = argparse.ArgumentParser(prog='python -m cuju.render._playing.game')
    parser.add_argument('--scenario', default='11_vs_11_kaggle')
    parser.add_argument('--left', choices=('person', 'builtin'), default='person')
    parser.add_argument('--right', choices=('person', 'builtin'), default='builtin')
    parser.add_argument('--left-team', default=_teams.BUILTIN)
    parser.add_argument('--right-team', default=_teams.BUILTIN)
    parser.add_argument('--seed', type=int, default=None)
    parser.add_argument('--left-ability', type=float, default=None)
    parser.add_argument('--right-ability', type=float, default=None)
    parser.add_argument('--record', action='store_true')
    parser.add_argument('--pace', type=float, default=STEPS_PER_SECOND)
    parser.add_argument('--length', type=int, default=None)
    parser.add_argument('--tournament', type=json.loads, default=None)
    options = parser.parse_args(arguments)
    # The reports keep a copy of standard output, and everything else written there goes to
    # standard error, so nothing printed by a library can pass for a report.
    sys.stdout.flush()
    _reports = os.fdopen(os.dup(1), 'w', encoding='utf-8')
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    commands = _Commands(sys.stdin)
    try:
        game = Game(
            options.scenario,
            (options.left == 'person', options.right == 'person'),
            (options.left_ability, options.right_ability),
            options.seed,
            teams=(options.left_team, options.right_team),
            length=options.length,
            tournament=options.tournament,
        )
    except PolicyError as error:
        _report(error=str(error), **_messages.id_fields(error))
        sys.exit(1)
    except Exception as error:
        _report(error=_messages.described(error), **_messages.id_fields(error))
        sys.exit(1)
    source = _live.LiveSource(game.batch, 0, game.title, game.teams, game.scenario, announce=False)
    saved = None
    try:
        source.push(game.frames[0], game.lineup)
        _report(
            port=source.port,
            seed=game.seed,
            teams=[team['name'] for team in game.teams],
            team_labels=[
                label if isinstance(label := _teams.shown_name(team), dict) else None
                for team in game.teams
            ],
        )
        ending = run(game, commands, source, max(0.1, options.pace))
        if options.record and len(game.frames) > 1:
            saved = game.save().stem
        # The people's achievements, by the rules that teams earn by, saved or not.
        earned = None
        with contextlib.suppress(Exception):
            earned = _achievements.for_game(game.header(), game.frames, game.sides)
        _report(
            state='ended',
            ending=ending,
            step=len(game.actions),
            match=saved,
            error=game.error,
            **game.error_ids,
            achievements=earned,
            **_status(game),
        )
        # The page reads the last frames before the stream closes.
        time.sleep(0.5)
    except Exception as error:
        # A game that stops for any other reason still keeps what it played.
        if options.record and saved is None and len(game.frames) > 1:
            with contextlib.suppress(Exception):
                saved = game.save().stem
        _report(error=_messages.described(error), match=saved, **_messages.id_fields(error))
        sys.exit(1)
    finally:
        source.close()
        game.close()


if __name__ == '__main__':
    main()
