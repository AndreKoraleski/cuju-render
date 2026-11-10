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
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

from cuju import __version__, bundled_scenarios
from cuju.errors import ArgumentError

from .._registry import clips as _clips
from .._registry import teams as _teams
from .._store import home as _home
from .._store import library as _library
from .._tournaments import tournament_runner as _tournament_runner
from .._watch import grid as _grid
from . import launch as _launch

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
}


# The states of a request, and the error of one that a restart of the server interrupted.
_STATES = ('queued', 'running', 'done', 'failed')
_INTERRUPTED = 'interrupted by a server restart'
_INTERRUPTED_PLAYING = (
    'interrupted by a server restart while playing, its recording may still appear in the library'
)
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
    if wrong or entry['id'] != path.stem:
        _LOGGER.warning(
            'cuju render skips the request file %s, whose fields %s are missing or invalid',
            path.name,
            ', '.join(wrong or ['id']),
        )
        return None
    return {key: entry[key] for key in _REQUEST_FIELDS}


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
                error = _INTERRUPTED_PLAYING if entry['state'] == 'running' else _INTERRUPTED
                entry.update(state='failed', error=error, finished=time.time())
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
        try:
            temporary.write_text(json.dumps(stored), encoding='utf-8')
            os.replace(temporary, path)
        except OSError:
            with contextlib.suppress(OSError):
                temporary.unlink()
            raise

    def _checkpoint(self, entry: dict[str, Any]) -> None:
        """Writes a request, and notes a failed write on the entry instead of stopping the queue."""
        entry.pop('persistence_error', None)
        try:
            self._persist(entry)
        except OSError as error:
            entry['persistence_error'] = f'could not save the request history, {error}'

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
            raise ArgumentError(f'expected a shipped scenario, found {scenario!r}')
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
            entry['state'], entry['error'] = 'failed', 'cancelled'
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
                entry['state'], entry['error'] = 'failed', f'{type(error).__name__}: {error}'
                entry['finished'] = time.time()
                self._checkpoint(entry)

    def _play_child(self, entry: dict[str, Any]) -> None:
        command = [
            sys.executable,
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
            # torch, and it reads nothing from the server's terminal.
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                cwd=_home.home(),
                env=os.environ.copy(),
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
                        entry['error'] = report['error']
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
                    entry['error'] = f'the match ran past {_MATCH_SECONDS // 60} minutes'
                elif not entry['error']:
                    tail = ''.join(stderr).strip()
                    entry['error'] = f'the match ended with exit code {code}' + (
                        f', {tail}' if tail else ''
                    )
            entry['finished'] = time.time()
            self._checkpoint(entry)


class GameBusyError(Exception):
    """Raised when a game is asked for while another one plays."""


class NoGameError(Exception):
    """Raised for a game that is not the latest one."""


# A game plays this many steps a second, real time, and a test may play faster.
_GAME_PACE = 10
# The page's input of one step names at most this many inputs, the four directions and the buttons.
_GAME_INPUTS = 16
# A stream waits this long for the game's process to start and announce its port.
_GAME_START_SECONDS = 120


class _Games:
    """The game that a person plays on the page, one at a time, in a child process.

    The process reads its commands, the input of each person's side, pause and quit, as JSON lines
    on its standard input, and reports its state, its port and the recording it saved as JSON lines
    on its standard output.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entry: dict[str, Any] | None = None
        self._process: subprocess.Popen | None = None
        self._started = threading.Condition(self._lock)

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
            raise ArgumentError(f'expected a shipped scenario, found {scenario!r}')
        if (
            not isinstance(humans, (list, tuple))
            or len(humans) != 2
            or not all(isinstance(value, bool) for value in humans)
            or not any(humans)
        ):
            raise ArgumentError(
                f'expected two flags for a person on the left and right, one true, found {humans!r}'
            )
        ability = list(_teams.check_ability(ability))
        if not isinstance(record, bool):
            raise ArgumentError(f'expected record as true or false, found {record!r}')
        if (
            not isinstance(teams, (list, tuple))
            or len(teams) != 2
            or not all(isinstance(value, str) for value in teams)
        ):
            raise ArgumentError(f'expected two registry teams, left and right, found {teams!r}')
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
            'match': None,
            'error': None,
            'late': 0,
            'streak': 0,
            'tournament': tournament,
        }
        command = [
            sys.executable,
            '-m',
            'cuju.render._playing.game',
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
                raise GameBusyError('a game already plays, quit it first')
            # The child runs in the renderer's folder and writes its errors to a pipe of its own.
            _home.home().mkdir(parents=True, exist_ok=True)
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                cwd=_home.home(),
                env=os.environ.copy(),
            )
            self._entry, self._process = entry, process
        threading.Thread(target=self._watch, args=(entry, process), daemon=True).start()
        return self._public(entry)

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
                    'late',
                    'streak',
                    'controlled',
                    'actions',
                ):
                    if key in report:
                        entry[key] = report[key]
                if isinstance(report.get('port'), int):
                    entry['port'] = report['port']
                    self._started.notify_all()
        code = process.wait()
        with self._lock:
            if code == 0 and entry['state'] == 'ended':
                pass
            elif entry['state'] != 'ended':
                entry['state'] = 'failed'
                if not entry['error']:
                    tail = ''.join(stderr).strip()
                    entry['error'] = f'the game ended with exit code {code}' + (
                        f', {tail}' if tail else ''
                    )
            self._started.notify_all()

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
                raise NoGameError('no such game')
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
            raise ArgumentError(f'expected side, held and pressed, found {sorted(unknown)!r}')
        side = document.get('side')
        with self._lock:
            humans = self._entry['humans'] if self._entry is not None else [False, False]
        if isinstance(side, bool) or side not in (0, 1) or not humans[side]:
            raise ArgumentError(f'expected the side of a person, 0 or 1, found {side!r}')
        command: dict[str, Any] = {'side': side}
        for key, allowed in (('held', INPUTS), ('pressed', BUTTONS)):
            value = document.get(key, [])
            if (
                not isinstance(value, list)
                or len(value) > _GAME_INPUTS
                or not all(isinstance(name, str) and name in allowed for name in value)
            ):
                raise ArgumentError(f'expected {key} as a list of {", ".join(allowed)}')
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
        raise ArgumentError(f'expected a seed from 0 to 2**64 - 1, found {value!r}')
    return value


def _public_seed(seed: Any) -> Any:
    """Returns a seed for the page, as text when JavaScript's numbers cannot hold it exactly."""
    if isinstance(seed, int) and not isinstance(seed, bool) and seed > 2**53 - 1:
        return str(seed)
    return seed


def _control(query: dict[str, str]) -> dict[str, Any] | None:
    """Returns uploaded team control, accepting earlier count and goalkeeper queries."""
    if 'control' in query:
        return json.loads(query['control'])
    if 'players' not in query and 'goalkeeper' not in query:
        return None
    players = query.get('players', '1')
    if not players.isdigit():
        raise ArgumentError(f'expected a number of controlled players, found {players!r}')
    return {'players': int(players), 'goalkeeper': query.get('goalkeeper', 'agent')}


def _scenarios() -> list[str]:
    """Returns the shipped scenarios, without agent counts."""
    return sorted([*bundled_scenarios(), *_teams.renderer_scenarios()])


def _sources() -> list[dict[str, Any]]:
    """Returns the live sources whose process runs, and withdraws the announcements of others."""
    sources = []
    for path in _home.folder('live').glob('*.json'):
        try:
            source = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        # An announcement without a whole number for its process is skipped, and the list goes on.
        pid = source.get('pid') if isinstance(source, dict) else None
        if not isinstance(pid, int) or isinstance(pid, bool):
            continue
        if not _alive(pid):
            path.unlink(missing_ok=True)
            continue
        sources.append(source)
    return sources


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

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = 'cuju-render'
        timeout = 60

        def end_headers(self) -> None:
            """Adds to every response the headers that keep other sites from framing the page.

            A page asked for with the key of the server, which `show` hands to a notebook, may sit
            in the frame of a notebook on this machine, in VS Code or in Google Colab.
            """
            if getattr(self, '_framed', False):
                ancestors = _launch.FRAME_ANCESTORS
                self.send_header('Content-Security-Policy', f'frame-ancestors {ancestors}')
            else:
                self.send_header('X-Frame-Options', 'DENY')
                self.send_header('Content-Security-Policy', "frame-ancestors 'none'")
            self.send_header('X-Content-Type-Options', 'nosniff')
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
                self._error(403, 'expected a request to this server by its loopback address')
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
                self._error(403, 'expected a request from the page of this server')
                return False
            try:
                length = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                self._error(400, 'expected a Content-Length of digits')
                return False
            if length > _MAXIMUM_BODY:
                self._error(413, 'expected a request body of at most 110 MB')
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
                self._error(400, f'{type(error).__name__}: {error}')
            except Exception as error:
                self._error(500, f'{type(error).__name__}: {error}')

        def _json(self, value: Any, status: int = 200) -> None:
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, message: str) -> None:
            self._json({'error': message}, status)

        def _body(self) -> bytes:
            length = int(self.headers.get('Content-Length') or 0)
            return self.rfile.read(length) if length > 0 else b''

        def _document(self) -> dict[str, Any]:
            document = json.loads(self._body() or b'{}')
            if not isinstance(document, dict):
                raise ArgumentError('expected a JSON object')
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
                if parts[:1] != ['api']:
                    self._static(parts)
                elif parts == ['api', 'matches']:
                    self._json(_library.matches())
                elif parts == ['api', 'trash']:
                    self._json(_library.matches(trash=True))
                elif len(parts) == 4 and parts[1] == 'matches' and parts[3] == 'details':
                    try:
                        self._json(_library.details(parts[2]))
                    except ArgumentError as error:
                        self._error(404, str(error))
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
                elif parts == ['api', 'info']:
                    self._json({'version': __version__})
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
                elif len(parts) == 4 and parts[1] == 'teams' and parts[3] == 'export':
                    self._export(parts[2])
                elif parts == ['api', 'models']:
                    self._json(_teams.shipped_models())
                elif parts == ['api', 'requests']:
                    self._json(requests.entries())
                elif parts == ['api', 'game']:
                    self._json(games.current())
                elif parts[:2] == ['api', 'tournaments']:
                    self._tournament_get(parts[2:])
                elif len(parts) == 4 and parts[1] == 'game' and parts[3] == 'stream':
                    port = games.port(parts[2])
                    if port is None:
                        self._error(404, 'no such game')
                    else:
                        self._pipe(port, 'game')
                else:
                    self._error(404, 'no such resource')
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_POST(self) -> None:
            self._handle(self._post)

        def _post(self) -> None:
            parts, query = self._route()
            try:
                if len(parts) == 4 and parts[1] == 'teams' and parts[3] == 'duplicate':
                    self._json(_teams.duplicate(parts[2]), 201)
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
                        self._error(404, 'no such recording in the Trash')
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
                elif len(parts) == 4 and parts[1] == 'game' and parts[3] == 'input':
                    self._json(games.input(parts[2], self._document()))
                elif len(parts) == 4 and parts[1] == 'game' and parts[3] == 'pause':
                    paused = self._document().get('paused')
                    if not isinstance(paused, bool):
                        raise ArgumentError(f'expected paused as true or false, found {paused!r}')
                    self._json(games.send(parts[2], {'paused': paused}))
                else:
                    self._error(404, 'no such resource')
            except GameBusyError as error:
                self._error(409, str(error))
            except NoGameError as error:
                self._error(404, str(error))
            except (ArgumentError, ValueError) as error:
                self._error(400, str(error))

        def do_PUT(self) -> None:
            self._handle(self._put)

        def _put(self) -> None:
            parts, query = self._route()
            try:
                if len(parts) == 4 and parts[1] == 'teams' and parts[3] == 'model':
                    joints = json.loads(query.get('joints') or '{}')
                    self._json(_teams.set_model(parts[2], self._body(), joints))
                elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'images':
                    self._json(_teams.set_image(parts[2], parts[4], self._body()))
                elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'sounds':
                    self._json(_teams.set_sound(parts[2], parts[4], self._body()))
                elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'clips':
                    joints = json.loads(query['joints']) if 'joints' in query else None
                    self._json(_clips.set_clip(parts[2], parts[4], self._body(), joints))
                else:
                    self._error(404, 'no such resource')
            except (ArgumentError, ValueError) as error:
                self._error(400, str(error))

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
                    self._error(404, 'no such resource')
            except (ArgumentError, ValueError) as error:
                self._error(400, str(error))

        def do_DELETE(self) -> None:
            self._handle(self._delete)

        def _delete(self) -> None:
            parts, _ = self._route()
            if len(parts) == 3 and parts[1] == 'game':
                try:
                    self._json(games.quit(parts[2]))
                except NoGameError:
                    self._error(404, 'no such game')
                return
            if len(parts) == 3 and parts[1] == 'requests':
                removed = requests.cancel(parts[2])
            elif len(parts) == 4 and parts[1:3] == ['tournaments', 'presets']:
                removed = _tournament_runner.remove_preset(parts[3])
            elif len(parts) == 3 and parts[1] == 'tournaments':
                try:
                    removed = cups().remove(parts[2])
                except ArgumentError as error:
                    self._error(409, str(error))
                    return
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
                self._error(404, 'no such resource')
                return
            if removed:
                self.send_response(204)
                self.end_headers()
            else:
                self._error(404, 'no such item')

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
                    self._error(404, 'no such tournament')
                else:
                    self._json(entry)
            else:
                self._error(404, 'no such resource')

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
                    self._error(404, 'no such tournament')
            else:
                self._error(404, 'no such resource')

        def _static(self, parts: list[str]) -> None:
            relative = Path(*parts) if parts else Path('index.html')
            path = (_WEB / relative).resolve()
            if _WEB.resolve() not in path.parents or not path.is_file():
                self._error(404, 'no such file')
                return
            data = path.read_bytes()
            kind = _TYPES.get(path.suffix) or mimetypes.guess_type(path.name)[0]
            page = relative == Path('index.html')
            key = getattr(self.server, 'frame_key', None)
            given = self._route()[1].get('embed', '').encode()
            self._framed = page and bool(key) and secrets.compare_digest(given, key.encode())
            self.send_response(200)
            self.send_header('Content-Type', kind or 'application/octet-stream')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self._framed = False
            self.wfile.write(data)
            reached = getattr(self.server, 'on_page', None)
            if page and reached is not None:
                reached()

        def _model(self, identifier: str) -> None:
            path = _teams.model_path(identifier)
            if path is None:
                self._error(404, 'no such model')
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
                self._error(404, 'no such clip')
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
                self._error(404, str(error))
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
                self._error(404, 'no such image')
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
                self._error(404, 'no such sound')
                return
            data = path.read_bytes()
            kind = {'.ogg': 'audio/ogg', '.mp3': 'audio/mpeg', '.wav': 'audio/wav'}
            self.send_response(200)
            self.send_header('Content-Type', kind[path.suffix])
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def _recording(self, identifier: str) -> None:
            path = _library.path_of(identifier)
            if path is None:
                self._error(404, 'no such match')
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
                self._error(404, 'no such live source')
                return
            environment = self._document().get('environment')
            count = source.get('environment_count', 1)
            if (
                isinstance(environment, bool)
                or not isinstance(environment, int)
                or not 0 <= environment < count
            ):
                raise ArgumentError(
                    f'expected an environment from 0 to {count - 1}, found {environment!r}'
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
                self._error(502, f'the live source did not answer, {error}')
                return
            finally:
                connection.close()
            if response.status != 202:
                self._error(502, f'the live source answered {response.status}')
                return
            self._json({'environment': environment, 'generation': source.get('generation', 0)}, 202)

        def _live_grid(self, identifier: str) -> None:
            """Relays a viewer's request for the grid of the live source `identifier`.

            Each request makes the source read states for a few seconds, so a page of another
            origin is refused here as for requests that change data.
            """
            origin = self.headers.get('Origin')
            if origin is not None and origin != f'http://{self.headers.get("Host")}':
                self._error(403, 'expected a request from the page of this server')
                return
            source = next((entry for entry in _sources() if entry['id'] == identifier), None)
            if source is None:
                self._error(404, 'no such live source')
                return
            query = self._route()[1]
            count = source.get('environment_count', 1)
            values = []
            for name in ('first', 'count'):
                text = query.get(name, '')
                if not text.isdigit() or len(text) > 9:
                    raise ArgumentError(f'expected a whole number for {name}, found {text!r}')
                values.append(int(text))
            first, size = values
            if not 0 <= first < count or not 1 <= size <= _grid.MAXIMUM:
                raise ArgumentError(
                    f'expected a first environment from 0 to {count - 1} and a count from 1 to '
                    f'{_grid.MAXIMUM}, found {first} and {size}'
                )
            connection = http.client.HTTPConnection('127.0.0.1', int(source['port']), timeout=10)
            try:
                connection.request('GET', f'/grid?first={first}&count={size}')
                response = connection.getresponse()
                body = response.read()
            except OSError as error:
                self._error(502, f'the live source did not answer, {error}')
                return
            finally:
                connection.close()
            if response.status == 404:
                # A source of 0.2.0 has no grid.
                self._error(404, 'this live source offers no grid, it comes from an older cuju')
                return
            if response.status != 200:
                self._error(502, f'the live source answered {response.status}')
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
                self._error(404, 'no such live source')
                return
            self._pipe(int(source['port']), 'live source')

        def _pipe(self, port: int, kind: str) -> None:
            """Relays the stream of a live source or a game, which listens on `port`."""
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            try:
                connection.connect()
                # A batch pauses between steps for as long as training needs, so once connected
                # the relay waits on the stream without a timeout.
                connection.sock.settimeout(None)
                # A page that reconnects asks for numbered frames, and the relay passes that on.
                sequence = self._route()[1].get('sequence') == '1'
                connection.request('GET', '/stream?sequence=1' if sequence else '/stream')
                response = connection.getresponse()
            except OSError as error:
                connection.close()
                self._error(502, f'the {kind} did not answer, {error}')
                return
            if response.status != 200:
                connection.close()
                self._error(502, f'the {kind} answered {response.status}')
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
    games = _Games()
    # The tournaments resume as the server starts, each match where it stopped.
    tournaments = _tournament_runner.Tournaments(games)
    try:
        server = _launch.LoopbackServer(
            ('127.0.0.1', port), make_handler(_Requests(), games, tournaments)
        )
    except OSError as error:
        tournaments.close()
        raise _launch.port_error(port, error) from None
    server.frame_key = secrets.token_urlsafe(18)
    server.proxy_domains = _launch.COLAB_DOMAINS if colab else ()
    # The library receives each shipped sample match once, and keeps a deleted one deleted.
    try:
        _library.add_samples(again=False)
    except OSError as error:
        print(f'cuju render could not add the sample matches: {error}', flush=True)
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
        _launch.withdraw(announcement)
        server.server_close()
