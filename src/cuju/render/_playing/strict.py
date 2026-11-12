# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""Plays the submissions of a match under strict rules, and checks one team before a tournament.

Under strict rules each registered team's policy runs in a process of its own, the script
`policy_worker.py`, with its own import path and a limit of threads, so two teams never share a
module and each computes on the same terms. The match times every call of each policy, and a side
that fails to load or to reset in time, fails in a call, answers late, answers an action outside its
set or computes for longer on average than the rules allow, breaks a rule, which ends the match at
once as that side's forfeit. This is isolation for fairness, not a sandbox for code that one cannot
trust, as the renderer's other ways of playing a submission are.

The check of a team, its pre-flight, loads the team and plays a few steps against the built-in AI
under the same rules, once on the left and once on the right, so the turned view of the right side
is checked too, and reports a pass or the rule it broke, with its timings and warnings. The
command line runs it in a process of its own, as `python -m cuju.render._playing.strict`, which
reports one line of JSON.

Every match plays exactly from its seed and the actions of each step, so the actions that a match
under strict rules stepped with, kept beside its seed, replay it, which `replay` does.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from cuju.kaggle import action_index, action_indices

from .._registry import teams as _teams
from .._store import home as _home
from .._text import messages as _messages
from . import play as _play
from .policy_worker import THREAD_VARIABLES

# The script of a team's process, which runs from its file with nothing of the renderer.
WORKER = Path(__file__).with_name('policy_worker.py')
# The steps that the check of a team plays.
PREFLIGHT_STEPS = 10
# The seconds that a process has to end once the match asks it to.
_END_SECONDS = 2.0
# A team's log starts again once it grows past this many bytes.
_LOG_BYTES = 1024 * 1024
# The share of all its actions above which one action draws a warning in the check of a team.
_ONE_ACTION = 0.9
# The settings that a team's own file of the registry may hold, beside those it names itself.
_TEAM_SETTINGS = {
    'id',
    'name',
    'name_id',
    'name_values',
    'kind',
    'created',
    'format',
    'style',
    'model',
    'control',
    'color',
    'secondary',
    'images',
    'sounds',
    'sounds_version',
    'clips',
    'joints',
    'presentation',
    'source',
    'filename',
    'imported',
}


def _label(name: str, /, **values: Any) -> dict[str, Any]:
    """Returns the label of a broken rule, `server.strict.<name>`, which the page translates."""
    return _messages.label(f'server.strict.{name}', **values)


def _seconds(value: float) -> str:
    return f'{value:g}'


def log_path(team: str) -> Path:
    """Returns the log of a team's processes under strict rules, what its policy printed."""
    folder = _home.folder('logs') / 'policies'
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f'{team}.log'


def _log(team: str) -> Any:
    """Opens the log of a team to add to, started again once it grows too long."""
    path = log_path(team)
    with contextlib.suppress(OSError):
        if path.stat().st_size > _LOG_BYTES:
            path.unlink()
    stream = path.open('a', encoding='utf-8', errors='replace')
    stream.write(f'--- a process of the team started at {time.strftime("%Y-%m-%d %H:%M:%S")}\n')
    stream.flush()
    return stream


class Worker:
    """One team's process, the requests it is sent and the lines it answers with.

    Attributes:
        process: The process.
        started: When the process started, on the clock of `time.perf_counter`.
        calls: The calls that the policy has answered.
        translate: Whether the policy answers the default set in a batch of the v2 set.
    """

    def __init__(self, team: dict[str, Any], threads: int, translate: bool) -> None:
        folder = _home.folder('teams') / team['id']
        # The variables of Python that a renderer's process may carry, such as PYTHONPATH, stay
        # out, as `-I` leaves them out too, and the threads of each library follow the rules.
        environment = {
            key: value
            for key, value in _home.process_environment().items()
            if not key.upper().startswith('PYTHON')
        }
        environment.update({name: str(threads) for name in THREAD_VARIABLES})
        self.started = time.perf_counter()
        self.calls = 0
        self.translate = translate
        self._lines: queue.Queue[str | None] = queue.Queue()
        # A private working folder, which the match removes once the process ends.
        self.folder = tempfile.mkdtemp(prefix='cuju-policy-')
        self._log = _log(team['id'])
        # The team's prints go to its log, and its answers come on a pipe of their own, which no
        # other team reaches.
        self.process = subprocess.Popen(
            [sys.executable, '-I', '-X', 'utf8', str(WORKER), str(folder), str(threads)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._log,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=self.folder,
            env=environment,
        )
        threading.Thread(target=self._read, daemon=True, name='cuju-strict-worker').start()

    def _read(self) -> None:
        try:
            for line in self.process.stdout:
                self._lines.put(line)
        except (OSError, ValueError):
            pass
        self._lines.put(None)

    def send(self, request: dict[str, Any]) -> None:
        """Sends one request, and leaves a process that has ended to answer that it has."""
        with contextlib.suppress(OSError, ValueError):
            self.process.stdin.write(json.dumps(request) + '\n')
            self.process.stdin.flush()

    def receive(self, timeout: float) -> dict[str, Any] | None:
        """Returns the next answer within `timeout` seconds, `{'closed': True}` once the process
        has ended, or `None` when no answer came in time."""
        deadline = time.perf_counter() + max(0.0, timeout)
        while True:
            try:
                line = self._lines.get(timeout=max(0.0, deadline - time.perf_counter()))
            except queue.Empty:
                return None
            if line is None:
                # The process ended, so its last lines have all been read.
                self._lines.put(None)
                return {'closed': True}
            try:
                found = json.loads(line)
            except ValueError:
                continue
            if isinstance(found, dict):
                return found

    def exit_text(self) -> str:
        """Returns how the process ended, with its exit code once it has one."""
        with contextlib.suppress(subprocess.TimeoutExpired):
            code = self.process.wait(1.0)
            return f'its process ended with exit code {code}'
        return 'its process stopped answering'

    def close(self) -> None:
        """Asks the process to end and ends it when it does not in time."""
        self.send({'end': True})
        with contextlib.suppress(OSError, ValueError):
            self.process.stdin.close()
        try:
            self.process.wait(_END_SECONDS)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):
                self.process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.process.wait(_END_SECONDS)
        with contextlib.suppress(OSError):
            self._log.close()
        shutil.rmtree(self.folder, ignore_errors=True)


class StrictPolicies(_play.Policies):
    """The policies of a match under strict rules, each submission in a process of its own.

    The processes start together and load at once, so the limit of loading counts from each
    process's start. The random entrant plays in the match's own process, as it is no team.

    The mean compute time of a call, which the rules limit over the whole match, leaves out the
    first call, which may well load a model or compile, and the first call has a limit of its own.

    Args:
        limits: The limits, as `tournament.check_strict` gives them.
        mean_after_first: Whether the mean of a call leaves out the first, true unless a test asks
            for the plain mean.
    """

    def __init__(
        self,
        *arguments: Any,
        seed: int = 0,
        limits: dict[str, Any],
        mean_after_first: bool = True,
    ) -> None:
        self.limits = limits
        self.mean_after_first = mean_after_first
        self.workers: list[Worker] = []
        try:
            super().__init__(*arguments, seed=seed)
            self._start()
        except _play.RuleError as broken:
            broken.stats = self._safe_stats()
            self.close()
            raise
        except BaseException:
            self.close()
            raise

    def _safe_stats(self) -> list[Any]:
        try:
            return self.stats()
        except AttributeError:
            return [None, None]

    def _runner(
        self,
        team: dict[str, Any],
        side: int,
        extended: bool,
        control: dict[str, Any],
        seed: int,
        name: Any,
    ) -> Any:
        if team['kind'] == 'random':
            return super()._runner(team, side, extended, control, seed, name)
        worker = Worker(
            team, self.limits['threads'], extended and control['action_set'] == 'default'
        )
        self.workers.append(worker)
        return worker

    def _players(self) -> list[tuple[dict[str, Any], Worker]]:
        return [
            (player, player['runner'])
            for player in self.players
            if isinstance(player['runner'], Worker)
        ]

    def _start(self) -> None:
        """Waits for every process to load and then to reset, each within its limit.

        Raises:
            RuleError: If a side fails or runs out of time in either.
        """
        breaks: list[tuple[int, str, dict[str, Any]]] = []
        load = self.limits['load_seconds']
        for player, worker in self._players():
            found = worker.receive(worker.started + load - time.perf_counter())
            name = player['name']
            if found is None:
                breaks.append(
                    (player['side'], 'load', _label('load_time', player=name, count=_seconds(load)))
                )
            elif found.get('closed') or 'error' in found:
                reason = str(found.get('error') or worker.exit_text())
                breaks.append((player['side'], 'load', _label('load', player=name, reason=reason)))
            else:
                player['stats'].load = time.perf_counter() - worker.started
        if breaks:
            raise _play.RuleError(breaks)
        reset = self.limits['reset_seconds']
        asked = {}
        for _, worker in self._players():
            worker.send({'reset': True})
            asked[id(worker)] = time.perf_counter()
        for player, worker in self._players():
            found = worker.receive(asked[id(worker)] + reset - time.perf_counter())
            name = player['name']
            if found is None:
                breaks.append(
                    (
                        player['side'],
                        'reset',
                        _label('reset_time', player=name, count=_seconds(reset)),
                    )
                )
            elif found.get('closed') or 'error' in found:
                reason = str(found.get('error') or worker.exit_text())
                breaks.append(
                    (player['side'], 'reset', _label('reset', player=name, reason=reason))
                )
            else:
                player['stats'].reset = time.perf_counter() - asked[id(worker)]
        if breaks:
            raise _play.RuleError(breaks)

    def _actions(self, worker: Worker, answer: Any, players: int) -> list[int]:
        """Returns the actions of an answer, checked as Kaggle checks them, or raises."""
        count = _play.DEFAULT_ACTIONS if worker.translate else self.batch.action_count
        values = (
            [action_index(answer, count)]
            if players == 1
            else action_indices(answer, count, players)
        )
        return [value % _play.DEFAULT_ACTIONS for value in values] if worker.translate else values

    def decide(self, parts: list[Any]) -> list[Any]:
        """Sends each process its observation at once, and takes each answer within its limit.

        Raises:
            RuleError: If a side fails in its call, answers late or answers an invalid action.
        """
        sent: dict[int, float] = {}
        for index, (player, part) in enumerate(zip(self.players, parts, strict=True)):
            if part is not None and isinstance(player['runner'], Worker):
                player['runner'].send({'obs': part[2]})
                sent[index] = time.perf_counter()
        answers: list[Any] = []
        breaks: list[tuple[int, str, dict[str, Any]]] = []
        for index, (player, part) in enumerate(zip(self.players, parts, strict=True)):
            if part is None:
                answers.append(None)
                continue
            runner, name, side = player['runner'], player['name'], player['side']
            if not isinstance(runner, Worker):
                started = time.perf_counter()
                answer = runner.act(part[2], self.batch.action_count)
                player['stats'].add(time.perf_counter() - started, answer)
                answers.append(answer)
                continue
            first = runner.calls == 0
            limit = self.limits['first_call_seconds' if first else 'call_seconds']
            found = runner.receive(sent[index] + limit - time.perf_counter())
            wall = time.perf_counter() - sent[index]
            answers.append(None)
            if found is None:
                reason = (
                    _label('first_time', player=name, count=_seconds(limit))
                    if first
                    else _label(
                        'call_time', player=name, call=runner.calls + 1, count=_seconds(limit)
                    )
                )
                breaks.append((side, 'timeout', reason))
                continue
            if found.get('closed') or 'error' in found:
                reason = str(found.get('error') or runner.exit_text())
                if found.get('stage') == 'answer':
                    breaks.append(
                        (
                            side,
                            'invalid',
                            _label('invalid_type', player=name, reason=reason),
                            'type',
                        )
                    )
                else:
                    breaks.append((side, 'crash', _label('crash', player=name, reason=reason)))
                continue
            try:
                actions = self._actions(runner, found.get('answer'), len(part[2]['players_raw']))
            except (TypeError, ValueError, IndexError) as error:
                # A wrong count of actions, an action of another type or one outside the set.
                detail = {TypeError: 'type', ValueError: 'count', IndexError: 'range'}[type(error)]
                reason = _label(f'invalid_{detail}', player=name, reason=_play._reason(error))
                breaks.append((side, 'invalid', reason, detail))
                continue
            compute = found.get('compute')
            valid = isinstance(compute, (int, float)) and not isinstance(compute, bool)
            # The time that the process reports for its call counts, within the time it took.
            compute = min(float(compute), wall) if valid and compute >= 0 else wall
            runner.calls += 1
            player['stats'].add(compute, actions)
            answers[-1] = actions
        if breaks:
            raise _play.RuleError(breaks)
        return answers

    def finish(self) -> None:
        """Checks the mean compute time of a call of each side against its limit.

        Raises:
            RuleError: If a side computed for longer on average than the rules allow.
        """
        limit = self.limits['mean_call_ms']
        breaks = []
        for player, _ in self._players():
            mean = player['stats'].mean(self.mean_after_first) * 1000
            if player['stats'].calls and mean > limit:
                reason = _label(
                    'mean', player=player['name'], mean=f'{mean:.1f}', limit=_seconds(limit)
                )
                breaks.append((player['side'], 'mean', reason))
        if breaks:
            raise _play.RuleError(breaks)

    def close(self) -> None:
        """Ends every team's process."""
        for worker in self.workers:
            worker.close()


# A check of a team without strict rules only asks that it loads and plays.
LENIENT = {
    'threads': 1,
    'load_seconds': 600.0,
    'first_call_seconds': 600.0,
    'call_seconds': 600.0,
    'reset_seconds': 600.0,
    'mean_call_ms': 10000.0,
    'folder_mb': 10000.0,
}


def _folder_bytes(folder: Path) -> int:
    """Returns the bytes of every file of a folder and its subfolders, links left out."""
    total = 0
    for path in folder.rglob('*'):
        with contextlib.suppress(OSError):
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
    return total


def _rule(kind: str, reason: dict[str, Any], detail: str | None = None) -> dict[str, Any]:
    return {
        'side': 'home',
        'kind': kind,
        'reason': reason['text'],
        'reason_id': reason.get('id'),
        'reason_values': reason.get('values'),
        'detail': detail,
        'step': 0,
        'at': [0, 0],
    }


def _setting_warnings(team: str) -> list[dict[str, Any]]:
    """Returns a warning for each setting of a team's file that the renderer does not know."""
    path = _home.folder('teams') / team / _teams.TEAM_FOLDER / 'team.json'
    try:
        saved = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    if not isinstance(saved, dict):
        return []
    unknown = sorted(str(key) for key in saved if key not in _TEAM_SETTINGS)
    return [_label('warning_setting', setting=key, file='team.json') for key in unknown]


def _side_check(
    team: str, scenario: str, limits: dict[str, Any], left: bool
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Plays a few steps with the team on one side and returns the rule it broke and its stats."""
    stats: dict[str, Any] = {}
    sides = (team, _teams.BUILTIN) if left else (_teams.BUILTIN, team)
    try:
        _play.play(
            *sides,
            scenario,
            seed=0,
            strict=limits,
            stats=stats,
            steps=PREFLIGHT_STEPS,
            save=False,
        )
    except _play.ForfeitError as forfeit:
        rule = dict(forfeit.rule)
        rule['side'] = 'home'
        return rule, forfeit.stats
    except Exception as error:
        ids = _messages.id_fields(error)
        found = {'text': str(error), 'id': ids.get('error_id'), 'values': ids.get('error_values')}
        return _rule('load', found), stats
    return None, stats


def _timings(side: dict[str, Any]) -> dict[str, Any]:
    return {
        'load_seconds': side.get('load_seconds'),
        'reset_seconds': side.get('reset_seconds'),
        'calls': side.get('calls', 0),
        'first_ms': side.get('first_ms'),
        'mean_ms': side.get('mean_ms'),
        'max_ms': side.get('max_ms'),
        'mean_after_first_ms': side.get('mean_after_first_ms'),
    }


def preflight(
    team: str, scenario: str | None = None, limits: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Loads a team and plays a few steps against the built-in AI on each side, under strict rules.

    The team plays once on the left and once on the right, where it sees the match turned, so a
    policy that reads the turned view wrong fails before its tournament. Its folder may hold at
    most the size of the limit `folder_mb`. Warnings, which never fail the check, name the
    settings of the team's file that the renderer does not know, and an action that makes up more
    than nine in ten of all the actions the team answered.

    Args:
        team: The team of the registry.
        scenario: The scenario, by default five against five for a team of five a side and the
            Kaggle match for one of eleven.
        limits: The limits of strict rules, or `None` for limits so wide that only a team that
            fails to load or to play breaks them.

    Returns:
        Whether the team passed, the rule it broke otherwise with its reason, its timings on the
        left, the seconds to load and to reset, its calls and the first, mean and largest compute
        time of a call in milliseconds with the mean after the first call, the same for each
        side under `sides`, its actions and its warnings.
    """
    entry = _teams.entry(team)
    if scenario is None:
        scenario = '5_vs_5' if entry.get('format') == '5v5' else '11_vs_11_kaggle'
    limits = limits or LENIENT
    name = _teams.shown_name(entry)
    rule = None
    sides: dict[str, Any] = {}
    actions: dict[str, int] = {}
    folder = _home.folder('teams') / team
    size = _folder_bytes(folder) / 1e6 if entry.get('kind') != 'builtin' else 0.0
    most = limits.get('folder_mb', LENIENT['folder_mb'])
    if size > most:
        reason = _label('folder_size', player=name, size=f'{size:.1f}', limit=_seconds(most))
        rule = _rule('load', reason, 'size')
    else:
        for left in (True, False):
            broken, stats = _side_check(team, scenario, limits, left)
            side = (stats.get('sides') or [None, None])[0 if left else 1] or {}
            sides['left' if left else 'right'] = {
                'ok': broken is None,
                'rule': broken,
                'timings': _timings(side),
            }
            for action, count in (side.get('actions') or {}).items():
                actions[action] = actions.get(action, 0) + count
            if broken is not None:
                rule = broken
                break
    warnings = _setting_warnings(team)
    total = sum(actions.values())
    if total:
        action, count = max(actions.items(), key=lambda item: item[1])
        if count > _ONE_ACTION * total:
            share = f'{100 * count / total:.0f}'
            warnings.append(_label('warning_action', player=name, action=action, share=share))
    return {
        'team': team,
        **_messages.named('name', name),
        'scenario': scenario,
        'ok': rule is None,
        'rule': rule,
        'timings': (sides.get('left') or {}).get('timings') or _timings({}),
        'sides': sides,
        'actions': dict(sorted(actions.items(), key=lambda item: int(item[0]))),
        'folder_mb': round(size, 3),
        'warnings': warnings,
        'limits': dict(limits),
        'strict': limits is not LENIENT,
    }


def replay(found: dict[str, Any], device: str = 'cpu') -> dict[str, Any]:
    """Plays a match again from its seed and the actions of each step, as a match kept them.

    Args:
        found: What `play` filled under `replay`, the seed, the scenario file, the agents, the
            action set, the ability of each side and the actions of every step.
        device: `cpu` or `cuda`.

    Returns:
        The steps played and the score of the left and the right side at the end.
    """
    import torch

    from cuju import BatchEnvironment

    from .._format import recording as _recording

    ability = tuple(found.get('ability') or (None, None))
    batch = BatchEnvironment(
        found['asset'],
        agent_counts=[tuple(found['agents'])],
        environment_count=1,
        representation='raw',
        seed=int(found['seed']),
        auto_reset=False,
        device=device,
        difficulty=None if ability == (None, None) else [ability],
        action_set=found['action_set'],
    )
    try:
        reader = _recording.StateReader(int(batch.left_players[0] + batch.right_players[0]))
        batch.reset()
        steps = 0
        for row in found['actions']:
            batch.step(torch.tensor([row], dtype=torch.int32))
            steps += 1
        score = _play.frame_score(reader.frame(batch.get_state(0)))
    finally:
        batch.close()
    return {'steps': steps, 'score': score}


def main(arguments: list[str] | None = None) -> None:
    """Checks the team that the command line names and reports one line of JSON."""
    parser = argparse.ArgumentParser(prog='python -m cuju.render._playing.strict')
    parser.add_argument('--team', required=True)
    parser.add_argument('--scenario', default=None)
    parser.add_argument('--limits', type=json.loads, default=None)
    options = parser.parse_args(arguments)
    # The report keeps a copy of standard output, and everything else written there goes to
    # standard error, as a match's reports do.
    sys.stdout.flush()
    reports = os.fdopen(os.dup(1), 'w', encoding='utf-8')
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    try:
        report = preflight(options.team, options.scenario, options.limits)
    except Exception as error:
        report = {'error': _messages.described(error), **_messages.id_fields(error)}
    reports.write(json.dumps(report) + '\n')
    reports.flush()


if __name__ == '__main__':
    # The check runs from the module as the package imports it, as a match does.
    from cuju.render._playing import strict as _module

    _module.main()
