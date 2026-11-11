# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The local server of the renderer, which serves the page and its API on the loopback interface.

It lists, sends and annotates recordings, moves them to the Trash and back and deletes them from
there, lists and relays live sources, keeps the team registry and plays requested matches, each in
a process of its own. It uses only Python's standard library.
"""

from __future__ import annotations

import collections
import contextlib
import http.client
import http.server
import json
import logging
import mimetypes
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

from cuju import __version__, bundled_scenarios
from cuju.errors import ArgumentError, Error

from .._export import feed as _feed
from .._export import video_jobs as _video_jobs
from .._format import recording as _recording
from .._guide import doctor as _doctor
from .._guide import help as _help
from .._moments import search as _search
from .._packages import presentation as _presentation
from .._playing import achievements as _achievements
from .._playing import challenges as _challenges
from .._registry import clips as _clips
from .._registry import teams as _teams
from .._store import home as _home
from .._store import library as _library
from .._text import languages as _languages
from .._text import messages as _messages
from .._text.messages import MessageError
from .._tournaments import tournament_runner as _tournament_runner
from .._watch import grid as _grid
from . import headers as _headers
from . import launch as _launch
from . import pwa as _pwa

_WEB = Path(__file__).parents[1] / 'web'
_LOGGER = logging.getLogger('cuju')
# A requested match ends after this many seconds, a full match plays in a few minutes.
_MATCH_SECONDS = 30 * 60
_TYPES = {
    '.js': 'text/javascript',
    '.mjs': 'text/javascript',
    '.css': 'text/css',
    '.html': 'text/html',
    '.json': 'application/json',
    '.glb': 'model/gltf-binary',
    '.webp': 'image/webp',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.webmanifest': 'application/manifest+json',
    '.mp4': 'video/mp4',
}


# The states of a request, and the error of one that a restart of the server interrupted, by
# the id of its message and its English text.
_STATES = ('queued', 'running', 'done', 'failed')
_INTERRUPTED_ID = 'server.requests.interrupted'
_INTERRUPTED_PLAYING_ID = 'server.requests.interrupted_playing'
_INTERRUPTED = _messages.text(_INTERRUPTED_ID)
_INTERRUPTED_PLAYING = _messages.text(_INTERRUPTED_PLAYING_ID)
# The history keeps this many finished requests, the newest, with every waiting or playing one.
_KEPT_REQUESTS = 200


def _number(value: Any) -> bool:
    """Returns whether `value` is a JSON number, which excludes true and false."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# Every field of a stored request with its check, so that a file edited by hand or written by
# a later version is skipped with a warning and the server starts all the same.
_REQUEST_FIELDS: dict[str, Any] = {
    'id': lambda value: isinstance(value, str) and _home.valid_identifier(value),
    'left': lambda value: isinstance(value, str),
    'right': lambda value: isinstance(value, str),
    'scenario': lambda value: isinstance(value, str),
    'seed': lambda value: (
        isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2**64
    ),
    'ability': lambda value: (
        isinstance(value, list)
        and len(value) == 2
        and all(item is None or (_number(item) and 0 <= item <= 1) for item in value)
    ),
    'state': lambda value: value in _STATES,
    'progress': _number,
    'match': lambda value: value is None or isinstance(value, str),
    'error': lambda value: value is None or isinstance(value, str),
    'created': _number,
    'started': lambda value: value is None or _number(value),
    'finished': lambda value: value is None or _number(value),
}
# The fields that a request of an earlier version lacks, the id and values of the message of its
# error, which the page shows in its own language, `None` for an error without an id.
_OPTIONAL_REQUEST_FIELDS: dict[str, Any] = {
    'error_id': lambda value: value is None or value in _messages.MESSAGES,
    'error_values': lambda value: (
        value is None
        or (isinstance(value, dict) and all(isinstance(item, str) for item in value.values()))
    ),
}


def _stored_request(path: Path) -> dict[str, Any] | None:
    """Returns the request that a file of the history holds, or `None` with a warning."""
    try:
        entry = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        _LOGGER.warning('cuju render skips the request file %s, %s', path.name, error)
        return None
    if not isinstance(entry, dict):
        _LOGGER.warning('cuju render skips the request file %s, which holds no object', path.name)
        return None
    wrong = [
        key for key, check in _REQUEST_FIELDS.items() if key not in entry or not check(entry[key])
    ]
    wrong += [
        key
        for key, check in _OPTIONAL_REQUEST_FIELDS.items()
        if key in entry and not check(entry[key])
    ]
    if wrong or entry['id'] != path.stem:
        _LOGGER.warning(
            'cuju render skips the request file %s, whose fields %s are missing or invalid',
            path.name,
            ', '.join(wrong or ['id']),
        )
        return None
    stored = {key: entry[key] for key in _REQUEST_FIELDS}
    stored.update({key: entry.get(key) for key in _OPTIONAL_REQUEST_FIELDS})
    if stored['error_id'] is None or stored['error_values'] is None:
        stored['error_id'] = stored['error_values'] = None
    return stored


class _Requests:
    """The queue of requested matches, played one at a time in child processes.

    Each request lives in a JSON file of the folder `requests`, so the history outlasts the server.
    A request that waited or played when the server stopped is marked as interrupted on the next
    start. A match that was playing then may still finish in its own process and save its
    recording, which then appears in the library while its request stays interrupted.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []
        self._processes: dict[str, subprocess.Popen] = {}
        self._wake = threading.Event()
        self._folder = _home.folder('requests')
        # A write that stopped halfway leaves a temporary file, which holds nothing to keep.
        for path in self._folder.glob('*.part'):
            with contextlib.suppress(OSError):
                path.unlink()
        for path in sorted(self._folder.glob('*.json')):
            entry = _stored_request(path)
            if entry is None:
                continue
            if entry['state'] in ('queued', 'running'):
                error = _INTERRUPTED_PLAYING_ID if entry['state'] == 'running' else _INTERRUPTED_ID
                entry.update(state='failed', finished=time.time(), **_messages.fields(error))
                self._checkpoint(entry)
            self._entries.append(entry)
        self._entries.sort(key=lambda entry: entry['created'])
        self._trim()
        threading.Thread(target=self._run, daemon=True).start()

    def _trim(self) -> None:
        """Forgets the oldest finished requests beyond the newest 200, with the lock held.

        A request that waits or plays always stays, and the file of a forgotten request is deleted,
        so the history and the list of the page stay small however many matches were requested.
        """
        finished = [entry for entry in self._entries if entry['state'] not in ('queued', 'running')]
        for entry in finished[: max(0, len(finished) - _KEPT_REQUESTS)]:
            self._entries.remove(entry)
            with contextlib.suppress(OSError):
                (self._folder / f'{entry["id"]}.json').unlink()

    def _persist(self, entry: dict[str, Any]) -> None:
        """Writes a request to its file through a temporary file, with the lock held."""
        path = self._folder / f'{entry["id"]}.json'
        temporary = path.with_name(path.name + '.part')
        stored = {key: entry[key] for key in _REQUEST_FIELDS}
        stored.update({key: entry.get(key) for key in _OPTIONAL_REQUEST_FIELDS})
        try:
            temporary.write_text(json.dumps(stored), encoding='utf-8')
            os.replace(temporary, path)
        except OSError:
            with contextlib.suppress(OSError):
                temporary.unlink()
            raise

    def _checkpoint(self, entry: dict[str, Any]) -> None:
        """Writes a request, and notes a failed write on the entry instead of stopping the queue."""
        for key in ('persistence_error', 'persistence_error_id', 'persistence_error_values'):
            entry.pop(key, None)
        try:
            self._persist(entry)
        except OSError as error:
            found = _messages.fields('server.requests.history', error=error)
            entry.update({f'persistence_{key}': value for key, value in found.items()})

    def _new_identifier(self) -> str:
        """Draws an identifier that no request and no file of the history holds, with the lock held.

        Identifiers sort by the second they are made in, so requests of the same second differ by
        their random end alone, and a draw that is taken is drawn again.
        """
        taken = {entry['id'] for entry in self._entries}
        while True:
            identifier = _home.new_identifier('r')
            if identifier not in taken and not (self._folder / f'{identifier}.json').exists():
                return identifier

    def add(
        self,
        left: str,
        right: str,
        scenario: str,
        seed: int | None,
        ability: Any = (None, None),
    ) -> dict[str, Any]:
        """Queues a match and returns its entry, with its seed drawn when none is given.

        Raises:
            ArgumentError: If the scenario, a team, the seed or an ability is invalid.
            OSError: If the request cannot be written to the history, and then it is not queued.
        """
        if scenario not in _scenarios():
            raise MessageError('server.scenario', scenario=repr(scenario))
        _teams.check_scenario([_teams.entry(left), _teams.entry(right)], scenario)
        ability = list(_teams.check_ability(ability))
        seed = _seed(seed)
        entry = {
            'id': '',
            'left': left,
            'right': right,
            'scenario': scenario,
            'seed': secrets.randbelow(2**31) if seed is None else seed,
            'ability': ability,
            'state': 'queued',
            'progress': 0.0,
            'match': None,
            'error': None,
            'created': 0.0,
            'started': None,
            'finished': None,
            'error_id': None,
            'error_values': None,
        }
        with self._lock:
            entry['id'] = self._new_identifier()
            entry['created'] = time.time()
            self._persist(entry)
            self._entries.append(entry)
            self._trim()
        self._wake.set()
        return self._public(entry)

    @staticmethod
    def _public(entry: dict[str, Any]) -> dict[str, Any]:
        """Returns a copy of a request for the page, with a seed beyond JavaScript's as text."""
        result = dict(entry)
        result['seed'] = _public_seed(result.get('seed'))
        return result

    def entries(self) -> list[dict[str, Any]]:
        """Returns a copy of every request, newest first."""
        with self._lock:
            return [self._public(entry) for entry in reversed(self._entries)]

    def _run(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            while True:
                with self._lock:
                    queued = [entry for entry in self._entries if entry['state'] == 'queued']
                if not queued:
                    break
                self._play(queued[0])

    def cancel(self, identifier: str) -> bool:
        """Cancels a queued match or ends a running one, and returns whether it existed."""
        with self._lock:
            entry = next((item for item in self._entries if item['id'] == identifier), None)
            if entry is None or entry['state'] not in ('queued', 'running'):
                return False
            process = self._processes.get(identifier)
            entry['state'] = 'failed'
            entry.update(_messages.fields('server.requests.cancelled'))
            entry['finished'] = time.time()
            self._checkpoint(entry)
        if process is not None:
            process.kill()
        return True

    def _play(self, entry: dict[str, Any]) -> None:
        """Plays one requested match in a child process, which nothing it does can stop for good."""
        try:
            self._play_child(entry)
        except Exception as error:
            with self._lock:
                entry['state'] = 'failed'
                entry.update(_messages.entry_fields(error, _messages.described(error)))
                entry['finished'] = time.time()
                self._checkpoint(entry)

    def _play_child(self, entry: dict[str, Any]) -> None:
        command = [
            *_home.python_command(),
            '-m',
            'cuju.render._playing.play',
            '--left',
            entry['left'],
            '--right',
            entry['right'],
            '--scenario',
            entry['scenario'],
        ]
        if entry['seed'] is not None:
            command += ['--seed', str(entry['seed'])]
        for side, value in zip(('left', 'right'), entry['ability'], strict=True):
            if value is not None:
                command += [f'--{side}-ability', repr(value)]
        with self._lock:
            if entry['state'] != 'queued':
                return
            entry['state'] = 'running'
            entry['started'] = time.time()
            self._checkpoint(entry)
            # Starting and registering the child share the cancellation lock. The child runs in the
            # renderer's folder, so no module beside the server's working folder shadows cuju or
            # torch, with that folder off its path of modules, and it reads nothing from the
            # server's terminal.
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                cwd=_home.process_folder(),
                env=_home.process_environment(),
            )
            self._processes[entry['id']] = process
        stderr: collections.deque[str] = collections.deque(maxlen=20)
        threading.Thread(target=lambda: stderr.extend(process.stderr), daemon=True).start()
        expired = threading.Event()

        def expire() -> None:
            expired.set()
            process.kill()

        timer = threading.Timer(_MATCH_SECONDS, expire)
        timer.daemon = True
        timer.start()
        try:
            for line in process.stdout:
                try:
                    report = json.loads(line)
                    progress = float(report.get('progress', entry['progress']))
                except (ValueError, TypeError, AttributeError):
                    continue
                with self._lock:
                    entry['progress'] = progress
                    if isinstance(report.get('match'), str):
                        entry['match'] = report['match']
                    if isinstance(report.get('error'), str):
                        entry.update(_messages.report_fields(report))
            code = process.wait()
        finally:
            timer.cancel()
            with self._lock:
                self._processes.pop(entry['id'], None)
        with self._lock:
            if entry['state'] != 'running':
                return
            if code == 0 and entry['match']:
                entry['state'] = 'done'
            else:
                entry['state'] = 'failed'
                if expired.is_set():
                    entry.update(
                        _messages.fields('server.requests.timeout', minutes=_MATCH_SECONDS // 60)
                    )
                elif not entry['error']:
                    tail = ''.join(stderr).strip()
                    entry.update(_messages.exit_fields('server.requests.exit', code, tail))
            entry['finished'] = time.time()
            self._checkpoint(entry)


class GameBusyError(_messages.Message, Exception):
    """Raised when a game is asked for while another one plays, with the id of its message."""


class NoGameError(_messages.Message, Exception):
    """Raised for a game that is not the latest one, with the id of its message."""


# A game plays this many steps a second, real time, and a test may play faster.
_GAME_PACE = 10
# The page's input of one step names at most this many inputs, the four directions and the buttons.
_GAME_INPUTS = 16
# A stream waits this long for the game's process to start and announce its port.
_GAME_START_SECONDS = 120
# The process of the next game, kept ready by the server, ends after this long without a game.
_WARM_IDLE_SECONDS = 600


class _Games:
    """The game that a person plays on the page, one at a time, in a child process.

    The process reads its commands, the input of each person's side, pause and quit, as JSON lines
    on its standard input, and reports its state, its port and the recording it saved as JSON lines
    on its standard output.

    With `warm`, the server keeps the process of the next game ready once a game's stream opens, a
    process that has loaded torch and cuju and waits for the arguments of its game, so the next
    game starts at once. Each process still plays one game and ends. A process kept ready that
    died, or whose environment changed, gives way to a new process, and one left without a game
    for `_WARM_IDLE_SECONDS` ends.
    """

    def __init__(self, warm: bool = False) -> None:
        self._lock = threading.Lock()
        self._entry: dict[str, Any] | None = None
        self._process: subprocess.Popen | None = None
        self._started = threading.Condition(self._lock)
        self._warm = warm
        self._closed = False
        self._spare: subprocess.Popen | None = None
        self._spare_key: Any = None
        self._spare_timer: threading.Timer | None = None
        self._last = time.monotonic()

    def start(
        self,
        scenario: str,
        humans: Any,
        ability: Any = (None, None),
        seed: int | None = None,
        record: bool = True,
        teams: Any = (_teams.BUILTIN, _teams.BUILTIN),
        length: int | None = None,
        tournament: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Starts a game and returns its entry.

        Args:
            scenario: A shipped scenario.
            humans: Whether a person plays the left side and the right side.
            ability: The ability of the built-in AI on each side.
            seed: The seed, or `None` to draw one.
            record: Whether the game goes to the library.
            teams: The registry team of each side, which plays a side without a person and joins a
                person as teammates.
            length: The steps the game lasts, or `None` for the scenario's own duration.
            tournament: The tournament match that the game plays, or `None`.

        Raises:
            ArgumentError: If the scenario is not shipped, the sides name no person, an ability
                lies outside 0 to 1 or a team cannot play its side.
            GameBusyError: If another game still plays.
        """
        if scenario not in _scenarios():
            raise MessageError('server.scenario', scenario=repr(scenario))
        if (
            not isinstance(humans, (list, tuple))
            or len(humans) != 2
            or not all(isinstance(value, bool) for value in humans)
            or not any(humans)
        ):
            raise MessageError('server.game.humans', humans=repr(humans))
        ability = list(_teams.check_ability(ability))
        if not isinstance(record, bool):
            raise MessageError('server.game.record', record=repr(record))
        if (
            not isinstance(teams, (list, tuple))
            or len(teams) != 2
            or not all(isinstance(value, str) for value in teams)
        ):
            raise MessageError('server.game.teams', teams=repr(teams))
        teams = [str(value) for value in teams]
        _teams.game_agents([_teams.entry(value) for value in teams], scenario, humans)
        entry = {
            'id': _home.new_identifier('g'),
            'scenario': scenario,
            'humans': list(humans),
            'team_ids': teams,
            'ability': ability,
            'seed': seed,
            'record': record,
            'state': 'starting',
            'reason': None,
            'ending': None,
            'step': 0,
            'score': [0, 0],
            'teams': None,
            'team_labels': None,
            'match': None,
            'error': None,
            'error_id': None,
            'error_values': None,
            'late': 0,
            'streak': 0,
            'tournament': tournament,
        }
        command = [
            '--scenario',
            scenario,
            '--left',
            'person' if humans[0] else 'builtin',
            '--right',
            'person' if humans[1] else 'builtin',
            '--left-team',
            teams[0],
            '--right-team',
            teams[1],
            '--pace',
            repr(float(_GAME_PACE)),
        ]
        if seed is not None:
            command += ['--seed', str(seed)]
        if record:
            command.append('--record')
        for side, value in zip(('left', 'right'), ability, strict=True):
            if value is not None:
                command += [f'--{side}-ability', repr(value)]
        if length is not None:
            command += ['--length', str(int(length))]
        if tournament is not None:
            command += ['--tournament', json.dumps(tournament)]
        with self._lock:
            if self._entry is not None and self._entry['state'] not in ('ended', 'failed'):
                raise GameBusyError('server.game.busy')
            process = self._take(command) or self._spawn(command)
            self._entry, self._process = entry, process
            self._last = time.monotonic()
        threading.Thread(target=self._watch, args=(entry, process), daemon=True).start()
        return self._public(entry)

    @staticmethod
    def _key() -> Any:
        """Returns what a process takes from the server as it starts, for a kept one to match."""
        return sys.executable, str(_home.home()), dict(os.environ)

    @staticmethod
    def _spawn(arguments: list[str]) -> subprocess.Popen:
        """Starts the process of a game with its arguments, or with `--warm` to keep it ready."""
        # The child runs in the renderer's folder, with that folder off its path of modules,
        # and writes its errors to a pipe of its own.
        return subprocess.Popen(
            [*_home.python_command(), '-m', 'cuju.render._playing.game', *arguments],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=_home.process_folder(),
            env=_home.process_environment(),
        )

    def _take(self, arguments: list[str]) -> subprocess.Popen | None:
        """Hands the arguments of a game to the process kept ready and returns it, under the lock.

        Returns `None`, after ending the kept process, when there is none, it died, its
        environment differs from the server's now or it cannot read the arguments, and the game
        then starts in a new process.
        """
        spare, self._spare = self._spare, None
        if self._spare_timer is not None:
            self._spare_timer.cancel()
            self._spare_timer = None
        if spare is None:
            return None
        if spare.poll() is None and self._spare_key == self._key():
            try:
                spare.stdin.write(json.dumps(arguments) + '\n')
                spare.stdin.flush()
                return spare
            except (OSError, ValueError):
                pass
        self._end(spare)
        return None

    def _prepare(self) -> None:
        """Readies the process of the next game, when the server keeps one and none waits."""
        with self._lock:
            if not self._warm or self._closed:
                return
            if self._spare is not None:
                if self._spare.poll() is None:
                    return
                self._end(self._spare)
                self._spare = None
            try:
                spare = self._spawn(['--warm'])
            except OSError:
                return
            self._spare, self._spare_key = spare, self._key()
            self._arm(spare, _WARM_IDLE_SECONDS)

    def _arm(self, spare: subprocess.Popen, seconds: float) -> None:
        """Ends the kept process after `seconds` without a game, under the lock."""
        if self._spare_timer is not None:
            self._spare_timer.cancel()
        timer = threading.Timer(max(1.0, seconds), self._expire, args=(spare,))
        timer.daemon = True
        self._spare_timer = timer
        timer.start()

    def _expire(self, spare: subprocess.Popen) -> None:
        """Ends the kept process once no game has started or ended for `_WARM_IDLE_SECONDS`."""
        with self._lock:
            if self._spare is not spare:
                return
            playing = self._entry is not None and self._entry['state'] not in ('ended', 'failed')
            idle = time.monotonic() - self._last
            if playing or idle < _WARM_IDLE_SECONDS:
                self._arm(spare, _WARM_IDLE_SECONDS - (0 if playing else idle))
                return
            self._spare, self._spare_timer = None, None
        self._end(spare)

    @staticmethod
    def _end(process: subprocess.Popen) -> None:
        """Ends a kept process that no game took, and closes its pipes."""
        with contextlib.suppress(OSError):
            process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=10)
        for stream in (process.stdin, process.stdout, process.stderr):
            with contextlib.suppress(OSError, ValueError):
                stream.close()

    def close(self) -> None:
        """Ends the process kept for the next game, as the server ends."""
        with self._lock:
            self._closed = True
            spare, self._spare = self._spare, None
            if self._spare_timer is not None:
                self._spare_timer.cancel()
                self._spare_timer = None
        if spare is not None:
            self._end(spare)

    def current(self) -> dict[str, Any] | None:
        """Returns a copy of the latest game's entry, or `None` before the first."""
        with self._lock:
            return None if self._entry is None else self._public(self._entry)

    @staticmethod
    def _public(entry: dict[str, Any]) -> dict[str, Any]:
        result = {key: value for key, value in entry.items() if key != 'port'}
        result['seed'] = _public_seed(result.get('seed'))
        return result

    def _watch(self, entry: dict[str, Any], process: subprocess.Popen) -> None:
        """Follows the reports of a game's process until it ends."""
        stderr: collections.deque[str] = collections.deque(maxlen=20)
        threading.Thread(target=lambda: stderr.extend(process.stderr), daemon=True).start()
        for line in process.stdout:
            try:
                report = json.loads(line)
            except ValueError:
                continue
            if not isinstance(report, dict):
                continue
            with self._lock:
                for key in (
                    'state',
                    'reason',
                    'ending',
                    'step',
                    'score',
                    'match',
                    'error',
                    'seed',
                    'teams',
                    'team_labels',
                    'late',
                    'streak',
                    'controlled',
                    'actions',
                    'achievements',
                ):
                    if key in report:
                        entry[key] = report[key]
                if 'error' in report:
                    entry.update(_messages.report_fields(report))
                opened = isinstance(report.get('port'), int)
                if opened:
                    entry['port'] = report['port']
                    self._started.notify_all()
            if opened:
                # The next game's process loads while this game plays, so it starts at once.
                self._prepare()
        code = process.wait()
        with self._lock:
            if code == 0 and entry['state'] == 'ended':
                pass
            elif entry['state'] != 'ended':
                entry['state'] = 'failed'
                if not entry['error']:
                    tail = ''.join(stderr).strip()
                    entry.update(_messages.exit_fields('server.game.exit', code, tail))
            self._last = time.monotonic()
            self._started.notify_all()
        self._prepare()

    def port(self, identifier: str) -> int | None:
        """Waits for the game's stream to open and returns its port, or `None` if it never does."""
        with self._lock:
            entry = self._entry
            if entry is None or entry['id'] != identifier:
                return None
            self._started.wait_for(
                lambda: 'port' in entry or entry['state'] in ('ended', 'failed'),
                _GAME_START_SECONDS,
            )
            return entry.get('port') if entry['state'] not in ('ended', 'failed') else None

    def send(self, identifier: str, command: dict[str, Any]) -> dict[str, Any]:
        """Passes a command to the game's process and returns the game's entry.

        Raises:
            NoGameError: If the latest game has another identifier.
        """
        with self._lock:
            entry, process = self._entry, self._process
            if entry is None or entry['id'] != identifier or process is None:
                raise NoGameError('server.game.unknown')
            if entry['state'] in ('ended', 'failed'):
                return self._public(entry)
            try:
                process.stdin.write(json.dumps(command) + '\n')
                process.stdin.flush()
            except (OSError, ValueError):
                pass
            return self._public(entry)

    def input(self, identifier: str, document: dict[str, Any]) -> dict[str, Any]:
        """Checks the input of a person's side and passes it to the game.

        The input names the side, 0 for the left and 1 for the right, the inputs held now and the
        buttons pressed since the last input, each from `cuju.render._playing.game.INPUTS`.

        Raises:
            ArgumentError: If the input holds anything else.
        """
        from .._playing.game import BUTTONS, INPUTS

        unknown = set(document) - {'side', 'held', 'pressed'}
        if unknown:
            raise MessageError('server.game.input_fields', unknown=repr(sorted(unknown)))
        side = document.get('side')
        with self._lock:
            humans = self._entry['humans'] if self._entry is not None else [False, False]
        if not any(humans):
            raise NoGameError('server.game.unknown')
        if isinstance(side, bool) or side not in (0, 1) or not humans[side]:
            raise MessageError('server.game.side', sides=_sides(humans), side=repr(side))
        command: dict[str, Any] = {'side': side}
        for key, allowed in (('held', INPUTS), ('pressed', BUTTONS)):
            value = document.get(key, [])
            if (
                not isinstance(value, list)
                or len(value) > _GAME_INPUTS
                or not all(isinstance(name, str) and name in allowed for name in value)
            ):
                raise MessageError('server.game.input_list', key=key, allowed=', '.join(allowed))
            command[key] = sorted(set(value))
        return self.send(identifier, command)

    def quit(self, identifier: str) -> dict[str, Any]:
        """Asks the game to end, saving it when it records, and ends its process if it hangs."""
        entry = self.send(identifier, {'quit': True})
        with self._lock:
            process = self._process
        if process is not None:

            def stop() -> None:
                # A game still starting reads the quit once it is ready, so the wait for a hang
                # starts when its stream opens.
                self.port(identifier)
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()

            threading.Thread(target=stop, daemon=True).start()
        return entry


def _seed(value: Any) -> int | None:
    """Returns the seed of a request, an integer from 0 to 2**64 - 1, or `None` to draw one."""
    if value in (None, ''):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2**64:
        raise MessageError('server.seed', value=repr(value))
    return value


def _public_seed(seed: Any) -> Any:
    """Returns a seed for the page, as text when JavaScript's numbers cannot hold it exactly."""
    if isinstance(seed, int) and not isinstance(seed, bool) and seed > 2**53 - 1:
        return str(seed)
    return seed


def _loads(data: bytes | str, name: str | None = None) -> Any:
    """Returns the value of the JSON of a request, its body or the parameter `name`.

    Raises:
        MessageError: If the text is no JSON, with the line and column of its first mistake.
    """
    try:
        return json.loads(data)
    except json.JSONDecodeError as error:
        place = {'line': error.lineno, 'column': error.colno}
        if name is None:
            raise MessageError('server.json', **place) from None
        raise MessageError('server.json_query', name=name, **place) from None
    except UnicodeDecodeError:
        raise MessageError('server.json_text') from None


def _control(query: dict[str, str]) -> dict[str, Any] | None:
    """Returns uploaded team control, accepting earlier count and goalkeeper queries."""
    if 'control' in query:
        return _loads(query['control'], 'control')
    if 'players' not in query and 'goalkeeper' not in query:
        return None
    players = query.get('players', '1')
    if not players.isdigit():
        raise MessageError('server.teams.controlled_players', players=repr(players))
    return {'players': int(players), 'goalkeeper': query.get('goalkeeper', 'agent')}


def _scenarios() -> list[str]:
    """Returns the shipped scenarios, without agent counts."""
    return sorted([*bundled_scenarios(), *_teams.renderer_scenarios()])


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _announced(source: Any) -> bool:
    """Returns whether a live announcement holds each field that the server reads, of its kind.

    The server reaches a source at its port of the loopback interface alone, and only at a port
    that no system service takes, from 1024 on.
    """
    return (
        isinstance(source, dict)
        and isinstance(source.get('id'), str)
        and _home.valid_identifier(source['id'])
        and isinstance(source.get('title'), str)
        and isinstance(source.get('scenario'), str)
        and _whole(source.get('environment'))
        and _whole(source.get('environment_count', 1))
        and _whole(source.get('generation', 0))
        and _whole(source.get('port'))
        and 1024 <= source['port'] <= 65535
    )


def _sources() -> list[dict[str, Any]]:
    """Returns the live sources whose process runs, and withdraws the announcements of others."""
    sources = []
    for path in _home.folder('live').glob('*.json'):
        try:
            source = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        # An announcement without a whole number for its process, or with a field that the server
        # cannot read, is skipped alone, and the list goes on.
        pid = source.get('pid') if isinstance(source, dict) else None
        if not _whole(pid) or not _announced(source):
            continue
        if not _alive(pid):
            path.unlink(missing_ok=True)
            continue
        sources.append(source)
    return sources


def _sides(humans: list[bool]) -> dict[str, Any]:
    """Returns the sides that a person plays, as a label for the answer to a wrong side."""
    if all(humans):
        return _messages.label('server.game.sides_both')
    return _messages.label('server.game.sides_right' if humans[1] else 'server.game.sides_left')


def _interrupt(signum: int, frame: Any) -> None:
    """Ends `serve` as Ctrl+C does, so that it withdraws its file and closes its tournaments."""
    raise KeyboardInterrupt


def _alive(pid: int) -> bool:
    """Returns whether a process runs, without signalling it."""
    if pid <= 0:
        return False
    if sys.platform == 'win32':
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        # Windows: 259 is `STILL_ACTIVE`.
        return code.value == 259
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# The names of the loopback interface, which a request's host must carry.
_LOOPBACK = ('127.0.0.1', 'localhost', '::1')
# The largest body a request may send, a submission of 100 MB with room for its index.
_MAXIMUM_BODY = 110 * 1024 * 1024


def make_handler(
    requests: _Requests,
    games: _Games | None = None,
    tournaments: _tournament_runner.Tournaments | None = None,
    videos: _video_jobs.VideoJobs | None = None,
) -> type[http.server.BaseHTTPRequestHandler]:
    """Returns the request handler of the server, which serves the loopback interface alone.

    The tournaments start with the first request that names them, unless the server passes them.
    """
    allowed_hosts = set(_LOOPBACK)
    games = games if games is not None else _Games()
    held = {'tournaments': tournaments}
    held_lock = threading.Lock()

    def cups() -> _tournament_runner.Tournaments:
        with held_lock:
            if held['tournaments'] is None:
                held['tournaments'] = _tournament_runner.Tournaments(games)
            return held['tournaments']

    videos = videos if videos is not None else _video_jobs.VideoJobs()

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = 'cuju-render'
        timeout = 60
        # Each answer leaves at once, its headers and body together, rather than after the delay
        # that holds small writes back, which on Windows costs a fifth of a second a request.
        disable_nagle_algorithm = True

        # How the response being written may be framed, by the rules of `headers`.
        _framing = _headers.DENY

        def end_headers(self) -> None:
            """Adds to every response the headers that keep other sites from framing the page.

            A page asked for with the key of the server, which `show` hands to a notebook, may sit
            in the frame of a notebook on this machine, in VS Code or in Google Colab. The page of
            a clean feed sits in the frame of /feed, and the page that draws a video export in the
            page that encodes it, both pages of this server. The sandbox of team presentation
            workers sends its own policy, which says who may frame it. The mock servers of `ci`
            send the same headers, from the same module.
            """
            for name, value in _headers.security(self._framing):
                self.send_header(name, value)
            super().end_headers()

        def _allowed(self) -> bool:
            """Refuses a request of another site, which could upload and run code.

            A page of another site that names this server, or a host name of another site that
            resolves here, sends another host or origin, so the server answers only requests that
            name it by its own host and come from its own page or from no page at all.
            """
            named = self.headers.get('Host') or ''
            # A server that `show` starts inside Google Colab also answers the names of Colab's
            # proxy, which resolve to Google alone, so no other site makes a browser send them.
            domains = getattr(self.server, 'proxy_domains', ())
            hostname = urllib.parse.urlsplit('//' + named).hostname
            if hostname not in allowed_hosts and not _launch.in_domains(hostname, domains):
                self._refuse(403, 'server.loopback')
                return False
            # A page served by another port of this machine is another site, so the whole
            # origin, scheme, host and port, must be this server's own.
            # The proxy of Google Colab shows the page under https at the same loopback host and
            # port, an origin that no other page can hold while this server holds the port. Behind
            # the proxy the page's origin names the very host the request names, and a page of
            # any other notebook, under another name of Colab's domains, is another site.
            origin = self.headers.get('Origin')
            own = (f'http://{named}', f'https://{named}')
            proxied = origin is not None and origin.startswith('https://')
            if proxied:
                origin_host = urllib.parse.urlsplit(origin).hostname
                proxied = origin_host == hostname and _launch.in_domains(origin_host, domains)
            if origin is not None and self.command != 'GET' and origin not in own and not proxied:
                self._refuse(403, 'server.origin')
                return False
            try:
                length = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                self._refuse(400, 'server.content_length')
                return False
            if length > _MAXIMUM_BODY:
                self._refuse(413, 'server.body_size')
                return False
            return True

        def log_message(self, *arguments: Any) -> None:
            pass

        def _handle(self, method: Any) -> None:
            if not self._allowed():
                return
            try:
                method()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            except (ArgumentError, ValueError, TypeError, KeyError, AttributeError) as error:
                # cuju's own errors say what to do in words, the others name their kind as well.
                if isinstance(error, Error):
                    self._error(400, str(error), error)
                else:
                    self._error(400, _messages.described(error), error)
            except Exception as error:
                where = self.path.split('?')[0]
                _doctor.note_error(f'{self.command} {where}, {_messages.described(error)}')
                self._error(500, _messages.described(error), error)

        def _json(self, value: Any, status: int = 200) -> None:
            """Answers with JSON that every page reads, a number that is NaN or infinite as null."""

            def finite(item: Any) -> Any:
                # A number less itself is zero unless it is NaN or infinite.
                if isinstance(item, float) and item - item != 0:
                    return None
                if isinstance(item, dict):
                    return {key: finite(inner) for key, inner in item.items()}
                if isinstance(item, (list, tuple)):
                    return [finite(inner) for inner in item]
                return item

            try:
                body = json.dumps(value, allow_nan=False).encode()
            except ValueError:
                # A stored file of an older install may still hold such a number.
                body = json.dumps(finite(value), allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def _error(
            self,
            status: int,
            message: str | BaseException,
            message_id: str | BaseException | None = None,
            values: dict[str, Any] | None = None,
        ) -> None:
            """Answers with an error, its English text in `error` as always.

            Args:
                status: The status of the answer.
                message: The text, or an exception whose text the answer gives.
                message_id: The id of the message in `_messages.MESSAGES`, or an exception that
                    carries one, or `None` for the id that `message` carries, if any. The answer
                    then names it in `error_id`, with `values` in `error_values`, so the page
                    shows the message in its own language.
                values: The values of the placeholders of `message_id`.
            """
            text = message if isinstance(message, str) else str(message)
            origin = message_id
            if origin is None and isinstance(message, BaseException):
                origin = message
            if isinstance(origin, str):
                document = {
                    'error': text,
                    'error_id': origin,
                    'error_values': {key: str(value) for key, value in (values or {}).items()},
                }
            elif isinstance(origin, BaseException) and not isinstance(origin, Error):
                # An error of another kind, such as a ValueError of Python, says what went wrong in
                # its own words, which the page shows inside a message of its language.
                document = _messages.error_fields(origin, text)
                if 'error_id' not in document:
                    frame = 'server.invalid' if status < 500 else 'server.unexpected'
                    document.update(error_id=frame, error_values={'error': text})
            elif isinstance(origin, BaseException):
                document = _messages.error_fields(origin, text)
            else:
                document = {'error': text}
            self._json(document, status)

        def _refuse(self, status: int, message_id: str, **values: Any) -> None:
            """Answers with the error of a message of `_messages.MESSAGES`, in English and by id."""
            self._json(_messages.fields(message_id, **values), status)

        def _body(self) -> bytes:
            length = int(self.headers.get('Content-Length') or 0)
            return self.rfile.read(length) if length > 0 else b''

        def _document(self) -> dict[str, Any]:
            document = _loads(self._body() or b'{}')
            if not isinstance(document, dict):
                raise MessageError('server.json_object')
            return document

        def _route(self) -> tuple[list[str], dict[str, str]]:
            parsed = urllib.parse.urlsplit(self.path)
            parts = [urllib.parse.unquote(part) for part in parsed.path.split('/') if part]
            query = dict(urllib.parse.parse_qsl(parsed.query))
            return parts, query

        def do_GET(self) -> None:
            self._handle(self._get)

        def _get(self) -> None:
            parts, _ = self._route()
            try:
                if parts == ['sandbox', 'presentation']:
                    self._sandbox()
                elif parts == ['feed']:
                    self._static(['feed.html'])
                elif parts[:1] != ['api']:
                    self._static(parts)
                elif parts in (['api', 'matches'], ['api', 'trash']):
                    # A group names the recordings of one run of a challenge.
                    group = self._route()[1].get('group') or None
                    self._json(_library.matches(parts[1] == 'trash', group))
                elif parts == ['api', 'search']:
                    query = self._route()[1]
                    limit = query.get('limit')
                    if limit and not (limit.isdigit() and len(limit) <= 9):
                        raise MessageError('server.search.limit', limit=repr(limit))
                    self._json(_search.search(query.get('q', ''), int(limit) if limit else None))
                elif len(parts) == 4 and parts[1] == 'matches' and parts[3] == 'moments':
                    self._moments(parts[2], False)
                elif len(parts) == 4 and parts[1] == 'matches' and parts[3] == 'captions.vtt':
                    self._moments(parts[2], True)
                elif len(parts) == 4 and parts[1] == 'matches' and parts[3] == 'details':
                    try:
                        self._json(_library.details(parts[2]))
                    except ArgumentError as error:
                        self._error(404, error)
                elif len(parts) == 3 and parts[1] == 'matches':
                    self._recording(parts[2])
                elif parts == ['api', 'live']:
                    # A source of 0.2.0 announces neither the number of environments nor the
                    # stream, so those fields read one and zero.
                    self._json(
                        [
                            {
                                **{
                                    key: source[key]
                                    for key in ('id', 'title', 'scenario', 'environment')
                                },
                                # A title that cuju made comes with its message, as a label.
                                **_messages.named('title', _recording.label_of(source, 'title')),
                                'environment_count': source.get('environment_count', 1),
                                'generation': source.get('generation', 0),
                            }
                            for source in _sources()
                        ]
                    )
                elif len(parts) == 4 and parts[1] == 'live' and parts[3] == 'stream':
                    self._relay(parts[2])
                elif len(parts) == 4 and parts[1] == 'live' and parts[3] == 'grid':
                    self._live_grid(parts[2])
                elif parts == ['api', 'feed']:
                    base = f'http://{self.headers.get("Host") or "127.0.0.1"}/'
                    self._json(_feed.targets(base, _sources(), cups().entries()))
                elif parts == ['api', 'feed', 'resolve']:
                    self._json(self._resolve_feed(self._route()[1].get('source', 'auto')))
                elif parts == ['api', 'info']:
                    self._json({'version': __version__})
                elif parts == ['api', 'video']:
                    self._json(_video_jobs.availability())
                elif parts == ['api', 'videos']:
                    self._json(videos.entries())
                elif len(parts) == 3 and parts[1] == 'videos':
                    entry = videos.entry(parts[2])
                    if entry is None:
                        self._refuse(404, 'server.video.unknown')
                    else:
                        self._json(entry)
                elif len(parts) == 4 and parts[1] == 'videos' and parts[3] == 'file':
                    self._video(videos.file(parts[2]))
                elif parts == ['api', 'scenarios']:
                    self._json(_scenarios())
                elif parts == ['api', 'teams']:
                    self._json(_teams.teams())
                elif len(parts) == 4 and parts[1] == 'teams' and parts[3] == 'model':
                    self._model(parts[2])
                elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'images':
                    self._image(parts[2], parts[4])
                elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'sounds':
                    self._sound(parts[2], parts[4])
                elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'clips':
                    self._clip(parts[2], parts[4])
                elif len(parts) == 4 and parts[1] == 'teams' and parts[3] == 'presentation':
                    self._json(_presentation.served(parts[2]))
                elif len(parts) >= 5 and parts[1] == 'teams' and parts[3] == 'presentation':
                    self._package_file(parts[2], '/'.join(parts[4:]))
                elif len(parts) == 4 and parts[1] == 'teams' and parts[3] == 'export':
                    self._export(parts[2])
                elif parts == ['api', 'models']:
                    self._json(_teams.shipped_models())
                elif parts == ['api', 'presentation', 'sides']:
                    self._json(_presentation.sides())
                elif parts == ['api', 'requests']:
                    self._json(requests.entries())
                elif parts == ['api', 'game']:
                    self._json(games.current())
                elif parts[:2] == ['api', 'tournaments']:
                    self._tournament_get(parts[2:])
                elif parts[:2] == ['api', 'challenges']:
                    self._json(*_challenges.get(parts[2:], self._route()[1]))
                elif parts == ['api', 'achievements']:
                    self._json(_achievements.public())
                elif parts[:2] == ['api', 'help']:
                    self._json(*_help.get(parts[2:], self._route()[1]))
                elif parts[:2] == ['api', 'languages']:
                    self._json(*_languages.get(parts[2:]))
                elif len(parts) == 4 and parts[1] == 'game' and parts[3] == 'stream':
                    port = games.port(parts[2])
                    if port is None:
                        self._refuse(404, 'server.game.unknown')
                    else:
                        self._pipe(port, 'game')
                else:
                    self._refuse(404, 'server.no_resource')
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_POST(self) -> None:
            self._handle(self._post)

        def _post(self) -> None:
            parts, query = self._route()
            try:
                if len(parts) == 4 and parts[1] == 'teams' and parts[3] == 'duplicate':
                    self._json(_teams.duplicate(parts[2]), 201)
                elif len(parts) == 4 and parts[1] == 'matches' and parts[3] == 'video':
                    self._json(videos.start(parts[2], self._document()), 201)
                elif len(parts) == 4 and parts[1] == 'live' and parts[3] == 'environment':
                    self._select_environment(parts[2])
                elif parts == ['api', 'teams']:
                    entry = _teams.add(
                        query.get('name', ''),
                        query.get('filename', 'main.py'),
                        self._body(),
                        query.get('format', '11v11'),
                        _control(query),
                    )
                    self._json(entry, 201)
                elif len(parts) == 4 and parts[1] == 'trash' and parts[3] == 'restore':
                    if _library.trash(parts[2], restore=True):
                        self._json(_library.details(parts[2]))
                    else:
                        self._refuse(404, 'server.trash.unknown')
                elif len(parts) == 4 and parts[1] == 'groups' and parts[3] == 'restore':
                    restored = _library.trash_group(parts[2], restore=True)
                    if restored:
                        self._json({'group': parts[2], 'restored': restored})
                    else:
                        self._refuse(404, 'server.library.group_trash')
                elif parts == ['api', 'presentation', 'sides']:
                    self._json(_presentation.assign(self._document()))
                elif parts == ['api', 'requests']:
                    document = self._document()
                    entry = requests.add(
                        str(document.get('left', _teams.BUILTIN)),
                        str(document.get('right', _teams.BUILTIN)),
                        str(document.get('scenario', '11_vs_11_kaggle')),
                        _seed(document.get('seed')),
                        document.get('ability', [None, None]),
                    )
                    self._json(entry, 201)
                elif parts == ['api', 'game']:
                    document = self._document()
                    entry = games.start(
                        str(document.get('scenario', '11_vs_11_kaggle')),
                        document.get('humans', [True, False]),
                        document.get('ability', [None, None]),
                        _seed(document.get('seed')),
                        document.get('record', True),
                        document.get('teams', [_teams.BUILTIN, _teams.BUILTIN]),
                    )
                    self._json(entry, 201)
                elif parts[:2] == ['api', 'tournaments']:
                    self._tournament_post(parts[2:])
                elif parts[:2] == ['api', 'challenges']:
                    self._json(*_challenges.post(parts[2:], self._document()))
                elif parts[:2] == ['api', 'help']:
                    self._json(*_help.post(parts[2:], self._document()))
                elif parts[:2] == ['api', 'languages']:
                    self._json(*_languages.post(parts[2:], self._body()))
                elif len(parts) == 4 and parts[1] == 'game' and parts[3] == 'input':
                    self._json(games.input(parts[2], self._document()))
                elif len(parts) == 4 and parts[1] == 'game' and parts[3] == 'pause':
                    paused = self._document().get('paused')
                    if not isinstance(paused, bool):
                        raise MessageError('server.game.paused', paused=repr(paused))
                    self._json(games.send(parts[2], {'paused': paused}))
                else:
                    self._refuse(404, 'server.no_resource')
            except (GameBusyError, _video_jobs.BusyError) as error:
                self._error(409, error)
            except NoGameError as error:
                self._error(404, error)
            except (ArgumentError, ValueError) as error:
                self._error(400, error)

        def do_PUT(self) -> None:
            self._handle(self._put)

        def _put(self) -> None:
            parts, query = self._route()
            try:
                if len(parts) == 4 and parts[1] == 'teams' and parts[3] == 'model':
                    joints = _loads(query.get('joints') or '{}', 'joints')
                    self._json(_teams.set_model(parts[2], self._body(), joints))
                elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'images':
                    self._json(_teams.set_image(parts[2], parts[4], self._body()))
                elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'sounds':
                    self._json(_teams.set_sound(parts[2], parts[4], self._body()))
                elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'clips':
                    joints = _loads(query['joints'], 'joints') if 'joints' in query else None
                    self._json(_clips.set_clip(parts[2], parts[4], self._body(), joints))
                else:
                    self._refuse(404, 'server.no_resource')
            except (ArgumentError, ValueError) as error:
                self._error(400, error)

        def do_PATCH(self) -> None:
            self._handle(self._patch)

        def _patch(self) -> None:
            parts, _ = self._route()
            try:
                if len(parts) == 3 and parts[1] == 'matches':
                    document = self._document()
                    self._json(
                        _library.update(
                            parts[2],
                            document.get('title'),
                            document.get('folder'),
                            document.get('favorite'),
                            document.get('tags'),
                            document.get('notes'),
                        )
                    )
                elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'clips':
                    joints = self._document().get('joints')
                    self._json(_clips.set_joints(parts[2], parts[4], joints))
                elif len(parts) == 3 and parts[1] == 'teams':
                    document = self._document()
                    self._json(
                        _teams.update(
                            parts[2],
                            document.get('name'),
                            document.get('style'),
                            document.get('format'),
                            document.get('control'),
                        )
                    )
                else:
                    self._refuse(404, 'server.no_resource')
            except (ArgumentError, ValueError) as error:
                self._error(400, error)

        def do_DELETE(self) -> None:
            self._handle(self._delete)

        def _delete(self) -> None:
            parts, _ = self._route()
            if len(parts) == 3 and parts[1] == 'game':
                try:
                    self._json(games.quit(parts[2]))
                except NoGameError:
                    self._refuse(404, 'server.game.unknown')
                return
            if parts[:2] == ['api', 'challenges']:
                self._json(*_challenges.delete(parts[2:]))
                return
            if len(parts) == 3 and parts[1] == 'groups':
                # Deleting a group moves all its recordings to the Trash at once.
                trashed = _library.trash_group(parts[2])
                if trashed:
                    self._json({'group': parts[2], 'trashed': trashed})
                else:
                    self._refuse(404, 'server.library.group_unknown')
                return
            if parts[:2] == ['api', 'languages']:
                self._json(*_languages.delete(parts[2:]))
                return
            if len(parts) == 3 and parts[1] == 'requests':
                removed = requests.cancel(parts[2])
            elif len(parts) == 4 and parts[1:3] == ['tournaments', 'presets']:
                removed = _tournament_runner.remove_preset(parts[3])
            elif len(parts) == 3 and parts[1] == 'tournaments':
                try:
                    removed = cups().remove(parts[2])
                except ArgumentError as error:
                    self._error(409, error)
                    return
            elif len(parts) == 3 and parts[1] == 'videos':
                removed = videos.cancel(parts[2])
            elif len(parts) == 4 and parts[1] == 'teams' and parts[3] == 'model':
                try:
                    removed = _teams.remove_model(parts[2])
                except ArgumentError:
                    removed = False
            elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'images':
                removed = _teams.remove_image(parts[2], parts[4])
            elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'sounds':
                removed = _teams.remove_sound(parts[2], parts[4])
            elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'clips':
                removed = _clips.remove_clip(parts[2], parts[4])
            elif len(parts) == 3 and parts[1] == 'matches':
                # A deleted recording goes to the Trash, and only the Trash deletes it for good.
                removed = _library.trash(parts[2])
            elif len(parts) == 3 and parts[1] == 'trash':
                removed = _library.purge(parts[2])
            elif len(parts) == 3 and parts[1] == 'teams':
                removed = _teams.remove(parts[2])
            else:
                self._refuse(404, 'server.no_resource')
                return
            if removed:
                self.send_response(204)
                self.end_headers()
            else:
                self._refuse(404, 'server.no_item')

        def _tournament_get(self, rest: list[str]) -> None:
            """Answers the reads of tournaments, their list, presets, ratings and one in full."""
            if not rest:
                self._json(cups().entries())
            elif rest == ['presets']:
                self._json(_tournament_runner.presets())
            elif rest == ['ratings']:
                self._json(_tournament_runner.ratings())
            elif len(rest) == 1:
                entry = cups().get(rest[0])
                if entry is None:
                    self._refuse(404, 'server.tournament.unknown')
                else:
                    self._json(entry)
            else:
                self._refuse(404, 'server.no_resource')

        def _tournament_post(self, rest: list[str]) -> None:
            """Creates, checks and changes tournaments, and saves presets."""
            document = self._document()
            if not rest:
                self._json(cups().create(document.get('config', document)), 201)
            elif rest == ['check']:
                self._json(_tournament_runner.preview(document.get('config', document)))
            elif len(rest) == 2 and rest[0] == 'presets':
                self._json(_tournament_runner.save_preset(rest[1], document.get('preset')), 201)
            elif len(rest) == 2 and rest[1] in ('cancel', 'resume', 'play', 'forfeit'):
                identifier, action = rest
                try:
                    if action == 'cancel':
                        if not cups().cancel(identifier):
                            raise KeyError(identifier)
                        self._json(cups().get(identifier))
                    elif action == 'resume':
                        self._json(cups().resume(identifier))
                    elif action == 'play':
                        self._json(cups().play(identifier, str(document.get('key'))), 201)
                    else:
                        winner = document.get('winner')
                        self._json(cups().forfeit(identifier, str(document.get('key')), winner))
                except KeyError:
                    self._refuse(404, 'server.tournament.unknown')
            else:
                self._refuse(404, 'server.no_resource')

        def _resolve_feed(self, source: str) -> dict[str, Any]:
            """Returns what the source of a feed names now, from this server's own lists."""

            def recording(identifier: str) -> dict[str, Any] | None:
                try:
                    return _library.details(identifier)
                except ArgumentError:
                    return None

            return _feed.resolve(
                source,
                live=_sources,
                recordings=_library.matches,
                recording=recording,
                requests=requests.entries,
                tournaments=lambda: cups().entries(),
                tournament=lambda identifier: cups().get(identifier),
            )

        def _static(self, parts: list[str]) -> None:
            relative = Path(*parts) if parts else Path('index.html')
            path = (_WEB / relative).resolve()
            if _WEB.resolve() not in path.parents or not path.is_file():
                self._refuse(404, 'server.no_file')
                return
            data = path.read_bytes()
            kind = _TYPES.get(path.suffix) or mimetypes.guess_type(path.name)[0]
            if relative == Path('manifest.webmanifest'):
                data = _pwa.manifest(data, self._route()[1].get('lang'))
            elif relative == Path('sw.js'):
                data = _pwa.worker(data)
            page = relative == Path('index.html')
            if page or relative == Path('feed.html'):
                data = _languages.inline(data)
            key = getattr(self.server, 'frame_key', None)
            self._framing = _headers.framing(relative.as_posix(), self._route()[1], key)
            self.send_response(200)
            self.send_header('Content-Type', kind or 'application/octet-stream')
            self.send_header('Content-Length', str(len(data)))
            # The service worker of the installable page is checked anew on every registration.
            if relative == Path('sw.js'):
                self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self._framing = _headers.DENY
            self.wfile.write(data)
            reached = getattr(self.server, 'on_page', None)
            if page and reached is not None:
                reached()

        def _sandbox(self) -> None:
            data, policy = _headers.sandbox_page(_WEB)
            self._framing = _headers.OWN
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Content-Security-Policy', policy)
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self._framing = _headers.DENY
            self.wfile.write(data)

        def _package_file(self, identifier: str, name: str) -> None:
            path = _presentation.file_path(identifier, name)
            if path is None:
                self._refuse(404, 'server.no_package_file')
                return
            data = path.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', _presentation.content_type(identifier, name))
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def _model(self, identifier: str) -> None:
            path = _teams.model_path(identifier)
            if path is None:
                self._refuse(404, 'server.no_model')
                return
            data = path.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'model/gltf-binary')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def _clip(self, identifier: str, name: str) -> None:
            path = _clips.clip_path(identifier, name)
            if path is None:
                self._refuse(404, 'server.no_clip')
                return
            data = path.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'model/gltf-binary')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def _export(self, identifier: str) -> None:
            try:
                filename, data = _teams.export(identifier)
            except ArgumentError as error:
                self._error(404, error)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            # A header carries Latin-1 alone, so the name travels encoded with an ASCII fallback.
            fallback = filename.encode('ascii', 'replace').decode().replace('?', '-')
            quoted = urllib.parse.quote(filename)
            self.send_header(
                'Content-Disposition',
                f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quoted}',
            )
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _image(self, identifier: str, slot: str) -> None:
            path = _teams.image_path(identifier, slot)
            if path is None:
                self._refuse(404, 'server.no_image')
                return
            data = path.read_bytes()
            kind = {'.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp'}
            self.send_response(200)
            self.send_header('Content-Type', kind.get(path.suffix, 'application/json'))
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def _sound(self, identifier: str, slot: str) -> None:
            path = _teams.sound_path(identifier, slot)
            if path is None:
                self._refuse(404, 'server.no_sound')
                return
            data = path.read_bytes()
            kind = {'.ogg': 'audio/ogg', '.mp3': 'audio/mpeg', '.wav': 'audio/wav'}
            self.send_response(200)
            self.send_header('Content-Type', kind[path.suffix])
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def _video(self, found: tuple[Path, str] | None) -> None:
            """Sends a finished video export as a download, under the name it suggests."""
            if found is None:
                self._refuse(404, 'server.video.unknown')
                return
            path, filename = found
            size = path.stat().st_size
            self.send_response(200)
            kind = 'video/webm' if path.suffix == '.webm' else 'video/mp4'
            self.send_header('Content-Type', kind)
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.send_header('Content-Length', str(size))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            with path.open('rb') as stream:
                while chunk := stream.read(1 << 20):
                    self.wfile.write(chunk)

        def _moments(self, identifier: str, vtt: bool) -> None:
            """Sends the moments of a recording of the library, or its captions as WebVTT."""
            if _library.path_of(identifier) is None:
                self._refuse(404, 'server.no_match')
                return
            if not vtt:
                self._json(_search.moments_of(identifier))
                return
            body = _search.captions_vtt(identifier).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/vtt; charset=utf-8')
            self.send_header('Content-Disposition', f'attachment; filename="{identifier}.vtt"')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def _recording(self, identifier: str) -> None:
            path = _library.path_of(identifier)
            if path is None:
                self._refuse(404, 'server.no_match')
                return
            size = path.stat().st_size
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(size))
            self.end_headers()
            with path.open('rb') as stream:
                while chunk := stream.read(1 << 20):
                    self.wfile.write(chunk)

        def _select_environment(self, identifier: str) -> None:
            """Passes a viewer's choice of environment on to the live source `identifier`."""
            source = next((entry for entry in _sources() if entry['id'] == identifier), None)
            if source is None:
                self._refuse(404, 'server.live.unknown')
                return
            environment = self._document().get('environment')
            count = source.get('environment_count', 1)
            if (
                isinstance(environment, bool)
                or not isinstance(environment, int)
                or not 0 <= environment < count
            ):
                raise MessageError(
                    'server.live.environment', last=count - 1, environment=repr(environment)
                )
            connection = http.client.HTTPConnection('127.0.0.1', int(source['port']), timeout=10)
            try:
                connection.request(
                    'POST',
                    '/environment',
                    json.dumps({'environment': environment}),
                    {'Content-Type': 'application/json'},
                )
                response = connection.getresponse()
                response.read()
            except OSError as error:
                self._refuse(502, 'server.live.silent', error=error)
                return
            finally:
                connection.close()
            if response.status != 202:
                self._refuse(502, 'server.live.answered', status=response.status)
                return
            self._json({'environment': environment, 'generation': source.get('generation', 0)}, 202)

        def _live_grid(self, identifier: str) -> None:
            """Relays a viewer's request for the grid of the live source `identifier`.

            Each request makes the source read states for up to 15 seconds, so a page of another
            origin is refused here as for requests that change data.
            """
            origin = self.headers.get('Origin')
            if origin is not None and origin != f'http://{self.headers.get("Host")}':
                self._refuse(403, 'server.origin')
                return
            source = next((entry for entry in _sources() if entry['id'] == identifier), None)
            if source is None:
                self._refuse(404, 'server.live.unknown')
                return
            query = self._route()[1]
            count = source.get('environment_count', 1)
            values = []
            for name in ('first', 'count'):
                text = query.get(name, '')
                if not text.isdigit() or len(text) > 9:
                    raise MessageError('server.live.whole_number', name=name, text=repr(text))
                values.append(int(text))
            first, size = values
            if not 0 <= first < count or not 1 <= size <= _grid.MAXIMUM:
                raise MessageError(
                    'server.live.grid_range',
                    last=count - 1,
                    most=_grid.MAXIMUM,
                    first=first,
                    count=size,
                )
            connection = http.client.HTTPConnection('127.0.0.1', int(source['port']), timeout=10)
            try:
                connection.request('GET', f'/grid?first={first}&count={size}')
                response = connection.getresponse()
                body = response.read()
            except OSError as error:
                self._refuse(502, 'server.live.silent', error=error)
                return
            finally:
                connection.close()
            if response.status == 404:
                # A source of 0.2.0 has no grid.
                self._refuse(404, 'server.live.no_grid')
                return
            if response.status != 200:
                self._refuse(502, 'server.live.answered', status=response.status)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def _relay(self, identifier: str) -> None:
            source = next((entry for entry in _sources() if entry['id'] == identifier), None)
            if source is None:
                self._refuse(404, 'server.live.unknown')
                return
            self._pipe(int(source['port']), 'live')

        def _pipe(self, port: int, kind: str) -> None:
            """Relays the stream of a live source or a game, which listens on `port`.

            The kind, `live` or `game`, names the messages of its errors.
            """
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            try:
                connection.connect()
                # A batch pauses between steps for as long as training needs, so once connected
                # the relay waits on the stream without a timeout.
                connection.sock.settimeout(None)
                # A page that reconnects asks for numbered frames, and the relay passes that on,
                # with the annotations that a page which shows them asks for.
                query = self._route()[1]
                sequence = query.get('sequence') == '1'
                path = '/stream?sequence=1' if sequence else '/stream'
                if sequence and query.get('annotations') == '1':
                    path += '&annotations=1'
                connection.request('GET', path)
                response = connection.getresponse()
            except OSError as error:
                connection.close()
                self._refuse(502, f'server.{kind}.silent', error=error)
                return
            if response.status != 200:
                connection.close()
                self._refuse(502, f'server.{kind}.answered', status=response.status)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            try:
                while chunk := response.read1(1 << 16):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except OSError:
                pass
            finally:
                connection.close()

    return Handler


def _warm_index() -> None:
    """Brings the index of moments up to date, so the first search finds it ready."""
    try:
        _search.sync()
    except Exception as error:
        _LOGGER.warning('cuju render could not index the moments of the library: %s', error)


def serve(
    port: int = 8780,
    open_browser: bool = False,
    *,
    page: str = '',
    remote: bool = False,
    parent: int | None = None,
    colab: bool = False,
) -> None:
    """Serves the renderer's page and API on the loopback interface until interrupted.

    The API deletes files and plays submitted code, so it listens on the loopback interface alone,
    and another machine reaches it through a tunnel, such as the port forwarding of SSH. While it
    runs, the file `server.json` of the home folder names it, so that `show` and
    `cuju render open` find it.

    Args:
        port: The port, and 0 picks a free one.
        open_browser: Whether to open the page in the default browser.
        page: The end of the address to open, from `#` on, such as `#match=sample-5v5`.
        remote: Whether to print the SSH command that reaches the page from another machine, and
            a line when a browser first reaches the page.
        parent: A process whose end stops the server, as `show` asks for.
        colab: Whether the server also answers through the port proxy of Google Colab, as `show`
            asks for inside Colab.

    Raises:
        Error: If the port is in use, with what to do.
    """
    # The diagnostic report of Help shows the server's recent warnings and errors.
    _doctor.install_capture()
    games = _Games(warm=True)
    # The tournaments resume as the server starts, each match where it stopped.
    tournaments = _tournament_runner.Tournaments(games)
    try:
        server = _launch.LoopbackServer(
            ('127.0.0.1', port), make_handler(_Requests(), games, tournaments)
        )
    except OSError as error:
        tournaments.close()
        raise _launch.port_error(port, error, remote) from None
    server.frame_key = secrets.token_urlsafe(18)
    server.proxy_domains = _launch.COLAB_DOMAINS if colab else ()
    # The library receives each shipped sample match once, and keeps a deleted one deleted.
    try:
        _library.add_samples(again=False)
    except OSError as error:
        print(f'cuju render could not add the sample matches: {error}', flush=True)
    # The index of the moments of the library catches up while the page loads.
    threading.Thread(target=_warm_index, daemon=True).start()
    port = server.server_address[1]
    address = f'http://127.0.0.1:{port}/'
    print(f'cuju render serves {address} from {_home.home()}', flush=True)
    announcement = _launch.announce(port, server.frame_key)
    if remote:
        print(_launch.remote_note(port), flush=True)
        print('Waiting for a browser to reach the page.', flush=True)

        def reached() -> None:
            server.on_page = None
            print(f'A browser reached the page at {time.strftime("%H:%M:%S")}.', flush=True)

        server.on_page = reached
    if parent is not None:

        def watch_parent() -> None:
            while _alive(parent):
                time.sleep(1)
            server.shutdown()

        threading.Thread(target=watch_parent, daemon=True).start()
    if threading.current_thread() is threading.main_thread():
        # A server that `show` started ends with a terminate signal when its parent ends, and it
        # still removes its file of the home folder on the way out.
        signal.signal(signal.SIGTERM, _interrupt)
    if open_browser:

        def opening() -> None:
            if not _launch.open_browser(address + page):
                print(f'Open {address + page} in a browser.', flush=True)

        threading.Timer(0.5, opening).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        tournaments.close()
        games.close()
        _launch.withdraw(announcement)
        server.server_close()
