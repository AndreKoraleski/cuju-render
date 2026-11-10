# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""Runs the renderer's tournaments, keeps them in files and reads the results of their matches.

Each tournament lives in a JSON file of the folder `tournaments`, its configuration, the result of
every match played and its state, written through a temporary file as the request history is, so a
tournament outlasts the server and resumes where it stopped. A match whose process was cut short
plays again from the start with the same seed, so it gives the same result.

The matches of agents play headless in processes of their own, as requested matches do, as many at
once as the tournament allows. A match with a person waits for that person to start it on the Play
page, and its result comes from the game's recording. One process at a time runs a tournament, the
server or `cuju render tournament run`, which a lock file beside the tournament names.
"""

from __future__ import annotations

import collections
import contextlib
import json
import logging
import os
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cuju.errors import ArgumentError

from .._format import recording as _recording
from .._registry import teams as _teams
from .._store import home as _home
from .._store import library as _library
from . import tournament as rules

_LOGGER = logging.getLogger('cuju')
_STATES = ('running', 'stopped', 'done', 'cancelled')
# A match of a tournament ends after this many seconds, as a requested match does.
MATCH_SECONDS = 30 * 60
_SCORE = struct.Struct('<2i')
_FILE_VERSION = 1


def folder() -> Path:
    """Returns the folder of the tournaments, created when missing."""
    return _home.folder('tournaments')


def _write(path: Path, value: Any) -> None:
    """Writes JSON through a temporary file, so a stop halfway leaves the old file whole."""
    temporary = path.with_name(path.name + '.part')
    try:
        temporary.write_text(json.dumps(value), encoding='utf-8')
        os.replace(temporary, path)
    except OSError:
        with contextlib.suppress(OSError):
            temporary.unlink()
        raise


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


# Scenarios, fit and results.


def scenario_duration(scenario: str) -> int:
    """Returns the steps that a shipped scenario lasts by its own configuration."""
    from cuju.scenarios import Builder, load_scenario

    builder = Builder(0)
    load_scenario(_teams.scenario_path(scenario))(builder)
    return int(builder.config().game_duration)


def length_scenario(scenario: str, length: int) -> str:
    """Returns a scenario file that plays `scenario` for `length` steps, written once.

    The file builds the shipped scenario and changes only its duration, and the second half
    starts at the same share of the match as in the original, so a shorter full match still has
    two halves.
    """
    if not rules.MIN_LENGTH <= int(length) <= rules.MAX_LENGTH:
        raise ArgumentError(
            f'expected a length from {rules.MIN_LENGTH} to {rules.MAX_LENGTH} steps, '
            f'found {length!r}'
        )
    source = _teams.scenario_path(scenario)
    if not source.is_file():
        raise ArgumentError(f'expected a shipped scenario, found {scenario!r}')
    target = _home.folder('scenarios') / f'{scenario}_steps_{int(length)}.py'
    text = (
        f'"""GRF\'s scenario `{scenario}` for {int(length)} steps, written by cuju render."""\n\n'
        'from cuju.scenarios import load_scenario\n\n'
        f'_BUILD = load_scenario({str(source)!r})\n\n\n'
        'def build_scenario(builder):\n'
        '    _BUILD(builder)\n'
        '    config = builder.config()\n'
        '    duration, half = config.game_duration, config.second_half\n'
        f'    config.game_duration = {int(length)}\n'
        '    if 0 < half < duration:\n'
        f'        config.second_half = max(1, half * {int(length)} // duration)\n'
    )
    if _read_text(target) != text:
        temporary = target.with_name(f'{target.name}.{os.getpid()}.part')
        temporary.write_text(text, encoding='utf-8')
        os.replace(temporary, target)
    return str(target)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding='utf-8')
    except OSError:
        return None


def fits(entrant: dict[str, Any], scenario: str) -> str | None:
    """Returns why an entrant cannot play a scenario on either side, or `None` when it can."""
    builtin = _teams.entry(_teams.BUILTIN)
    try:
        team = _teams.entry(entrant['team'])
        if entrant['kind'] == 'person':
            for humans in ((True, False), (False, True)):
                sides = [team, builtin] if humans[0] else [builtin, team]
                _teams.game_agents(sides, scenario, humans)
        else:
            _teams.check_scenario([team, builtin], scenario)
            _teams.check_scenario([builtin, team], scenario)
    except ArgumentError as error:
        return str(error)
    return None


def scenarios() -> list[str]:
    """Returns the scenarios that a stage may name."""
    from cuju import bundled_scenarios

    return sorted([*bundled_scenarios(), *_teams.renderer_scenarios()])


def recording_result(identifier: str) -> dict[str, Any]:
    """Returns the score and cards of each side at the end of a recording of the library.

    A player counts a yellow card when the last frame shows one and no red, and a red card when it
    shows a red, so a second yellow counts as a red alone, as fair play rules count it.
    """
    path = _library.path_of(identifier)
    if path is None:
        raise ArgumentError(f'expected a recording of the library, found {identifier!r}')
    header = _recording.read_header(path)
    last = None
    # A recording of version 2 decodes its last frame from the keyframe before it.
    for frame in _recording.frames(path, start=max(0, (header.get('frame_count') or 0) - 1)):
        last = frame
    if last is None:
        raise ArgumentError(f'the recording {identifier} holds no frame')
    players = header['players']
    offset = _recording._FRAME_HEAD.size + len(players) * len(_recording.NODES) * 14
    cards = [[0, 0], [0, 0]]
    for index, player in enumerate(players):
        state = last[offset + index]
        team = 1 if player['team'] else 0
        if state & 4:
            cards[team][1] += 1
        elif state & 2:
            cards[team][0] += 1
    return {'score': list(_SCORE.unpack_from(last, 8)), 'cards': cards, 'match': identifier}


# Ratings and presets.


def ratings() -> dict[str, dict[str, Any]]:
    """Returns the rating of every entrant that has played a tournament match, by entrant key."""
    stored = _read(folder() / 'ratings.json', {})
    if not isinstance(stored, dict):
        return {}
    return {
        key: value
        for key, value in stored.items()
        if isinstance(value, dict) and rules._number(value.get('rating'))
    }


def _rating_values() -> dict[str, float]:
    return {key: float(value['rating']) for key, value in ratings().items()}


def presets() -> dict[str, dict[str, Any]]:
    """Returns the presets, those that ship first and then the user's, by name."""
    shipped = {name: {**preset, 'shipped': True} for name, preset in rules.PRESETS.items()}
    own = _read(folder() / 'presets.json', {})
    if isinstance(own, dict):
        for name, preset in own.items():
            try:
                shipped[name] = {**rules.check_preset(preset), 'shipped': False}
            except rules.TournamentError:
                continue
    return shipped


def save_preset(name: str, preset: Any) -> dict[str, Any]:
    """Saves a preset of the user under `name` and returns it.

    Raises:
        ArgumentError: If the name is no plain identifier or names a shipped preset, or the
            preset is invalid.
    """
    if not isinstance(name, str) or not _home.valid_identifier(name) or name in rules.PRESETS:
        raise ArgumentError(
            f'expected a preset name of small letters, digits, dashes and underscores that '
            f'names no shipped preset, found {name!r}'
        )
    try:
        checked = rules.check_preset(preset)
    except rules.TournamentError as error:
        raise ArgumentError(str(error)) from error
    path = folder() / 'presets.json'
    own = _read(path, {})
    own = own if isinstance(own, dict) else {}
    own[name] = checked
    _write(path, own)
    return {**checked, 'shipped': False}


def remove_preset(name: str) -> bool:
    """Removes a preset of the user and returns whether it existed."""
    path = folder() / 'presets.json'
    own = _read(path, {})
    if not isinstance(own, dict) or name not in own:
        return False
    del own[name]
    _write(path, own)
    return True


def check_config(config: Any) -> dict[str, Any]:
    """Returns a configuration resolved against the registry, the scenarios and the ratings.

    A configuration that names a preset takes the preset's settings for those it leaves out.

    Raises:
        ArgumentError: With the reason, if it cannot make a tournament.
    """
    if (
        isinstance(config, dict)
        and isinstance(config.get('preset'), str)
        and ('stages' not in config)
    ):
        try:
            base = rules.preset_config(config['preset'], presets())
        except rules.TournamentError as error:
            raise ArgumentError(str(error)) from error
        config = {**base, **config}
    try:
        return rules.check(config, _teams.teams(), fits, _rating_values(), scenarios())
    except rules.TournamentError as error:
        raise ArgumentError(str(error)) from error


def preview(config: Any) -> dict[str, Any]:
    """Returns a configuration resolved, with the draw and first matches it would give.

    Raises:
        ArgumentError: With the reason, if it cannot make a tournament.
    """
    checked = check_config(config)
    view = rules.evaluate(checked, {})
    stages = [
        {key: stage[key] for key in ('name', 'format', 'entrants', 'advance', 'rounds', 'tables')}
        for stage in view['stages']
    ]
    return {'config': checked, 'stages': stages, 'matches': len(view['matches'])}


# The stored tournaments.


def _stored(path: Path) -> dict[str, Any] | None:
    """Returns the tournament that a file holds, or `None` with a warning."""
    entry = _read(path, None)
    problem = None
    if not isinstance(entry, dict):
        problem = 'which holds no object'
    elif entry.get('id') != path.stem or not _home.valid_identifier(path.stem):
        problem = 'whose identifier differs from its name'
    elif entry.get('state') not in _STATES:
        problem = 'whose state is unknown'
    elif not isinstance(entry.get('config'), dict) or not isinstance(entry.get('results'), dict):
        problem = 'whose configuration or results are missing'
    else:
        try:
            config = entry['config']
            if not (
                isinstance(config.get('entrants'), list)
                and isinstance(config.get('stages'), list)
                and rules._integer(config.get('seed'))
            ):
                raise rules.TournamentError('expected entrants, stages and a seed')
            entry['results'] = {
                str(key): rules.check_result(value) for key, value in entry['results'].items()
            }
            rules.evaluate(config, entry['results'])
        except (rules.TournamentError, KeyError, TypeError, ValueError, IndexError) as error:
            problem = f'whose tournament cannot be read, {error}'
    if problem:
        _LOGGER.warning('cuju render skips the tournament file %s, %s', path.name, problem)
        return None
    for key, kind, default in (
        ('error', str, None),
        ('failures', dict, {}),
        ('games', dict, {}),
        ('notes', dict, {}),
        ('created', (int, float), time.time()),
        ('finished', (int, float), None),
    ):
        if not isinstance(entry.get(key), kind):
            entry[key] = default
    return entry


def _alive(pid: int) -> bool:
    from .._http.server import _alive as alive

    return alive(pid)


class Tournaments:
    """The tournaments of the renderer's folder, and the matches they play.

    Args:
        games: The server's games, which play the matches of people, or `None` without people.
        player: Plays one match of agents and returns its result, by default in a child process.
            A test passes a function of its own.
        only: The one tournament to run, or `None` for every tournament of the folder.
        start: Whether to start the thread that runs the matches.
        interval: The seconds between two looks at the tournaments.
    """

    def __init__(
        self,
        games: Any = None,
        player: Callable[..., dict[str, Any]] | None = None,
        only: str | None = None,
        start: bool = True,
        interval: float = 0.5,
    ) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, dict[str, Any]] = {}
        self._stamps: dict[str, float] = {}
        self._views: dict[str, tuple[int, dict[str, Any]]] = {}
        self._versions: dict[str, int] = collections.defaultdict(int)
        self._running: dict[tuple[str, str], dict[str, Any]] = {}
        self._owned: set[str] = set()
        self._games = games
        self._player = player or self._play_process
        self._only = only
        self._interval = interval
        self._stop = threading.Event()
        self._folder = folder()
        for path in self._folder.glob('*.part'):
            with contextlib.suppress(OSError):
                path.unlink()
        self._scan()
        if start:
            threading.Thread(target=self._loop, daemon=True, name='cuju-tournaments').start()

    # Files.

    def _path(self, identifier: str) -> Path:
        return self._folder / f'{identifier}.json'

    def _scan(self) -> None:
        """Loads new tournaments and those that another process changed, and applies cancels."""
        with self._lock:
            for path in self._folder.glob('*.json'):
                if path.name in ('ratings.json', 'presets.json'):
                    continue
                identifier = path.stem
                if self._only is not None and identifier != self._only:
                    continue
                try:
                    stamp = path.stat().st_mtime_ns
                except OSError:
                    continue
                if identifier in self._owned and identifier in self._records:
                    continue
                if self._stamps.get(identifier) == stamp:
                    continue
                record = _stored(path)
                self._stamps[identifier] = stamp
                if record is not None:
                    self._records[identifier] = record
                    self._versions[identifier] += 1
            for identifier in list(self._records):
                if not self._path(identifier).exists():
                    self._forget(identifier)
            for marker in self._folder.glob('*.cancel'):
                record = self._records.get(marker.stem)
                if record is not None and self._claim(record):
                    with contextlib.suppress(OSError):
                        marker.unlink()
                    self._cancel(record)

    def _forget(self, identifier: str) -> None:
        self._records.pop(identifier, None)
        self._views.pop(identifier, None)
        self._stamps.pop(identifier, None)
        self._release(identifier)

    def _persist(self, record: dict[str, Any]) -> None:
        """Writes a tournament, and keeps a failed write as its error instead of stopping."""
        self._versions[record['id']] += 1
        try:
            _write(self._path(record['id']), record)
            self._stamps[record['id']] = self._path(record['id']).stat().st_mtime_ns
            record.pop('persistence_error', None)
        except OSError as error:
            record['persistence_error'] = f'could not save the tournament, {error}'

    # The lock between processes.

    def _lock_path(self, identifier: str) -> Path:
        return self._folder / f'{identifier}.lock'

    def _claim(self, record: dict[str, Any]) -> bool:
        """Makes this process the one that runs a tournament, unless another live one does."""
        identifier = record['id']
        if identifier in self._owned:
            return True
        path = self._lock_path(identifier)
        for _ in range(2):
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                text = _read_text(path) or ''
                pid = int(text) if text.strip().isdigit() else 0
                if pid and pid != os.getpid() and _alive(pid):
                    return False
                with contextlib.suppress(OSError):
                    path.unlink()
                continue
            except OSError:
                return False
            with os.fdopen(descriptor, 'w') as stream:
                stream.write(str(os.getpid()))
            self._owned.add(identifier)
            # A game lives no longer than the process that started it, so the games of people
            # that an earlier process followed are gone, and their matches wait to be played.
            if record['games']:
                for key in record['games']:
                    record['notes'][key] = 'The game of this match ended without a result.'
                record['games'] = {}
                self._persist(record)
            return True
        return False

    def owner(self, identifier: str) -> int | None:
        """Returns the process that runs a tournament, when another live process does."""
        text = _read_text(self._lock_path(identifier)) or ''
        pid = int(text) if text.strip().isdigit() else 0
        return pid if pid and pid != os.getpid() and _alive(pid) else None

    def _release(self, identifier: str) -> None:
        if identifier in self._owned:
            self._owned.discard(identifier)
            with contextlib.suppress(OSError):
                self._lock_path(identifier).unlink()

    def close(self) -> None:
        """Stops the thread, ends the matches it plays and lets other processes run them."""
        self._stop.set()
        with self._lock:
            for running in self._running.values():
                process = running.get('process')
                if process is not None:
                    with contextlib.suppress(OSError):
                        process.kill()
            for identifier in list(self._owned):
                self._release(identifier)

    # Views.

    def _view(self, record: dict[str, Any]) -> dict[str, Any]:
        version = self._versions[record['id']]
        cached = self._views.get(record['id'])
        if cached is None or cached[0] != version:
            cached = (version, rules.evaluate(record['config'], record['results']))
            self._views[record['id']] = cached
        return cached[1]

    def _summary(self, record: dict[str, Any]) -> dict[str, Any]:
        view = self._view(record)
        config = record['config']
        champion = view['champion']
        running = sum(1 for key in self._running if key[0] == record['id'])
        waiting = [m for m in rules.ready(view) if m['person']]
        return {
            'id': record['id'],
            'name': config['name'],
            'state': record['state'],
            'error': record['error'],
            'created': record['created'],
            'finished': record['finished'],
            'seed': config['seed'],
            'entrants': len(config['entrants']),
            'stages': [
                {'name': stage['name'], 'format': stage['format'], 'scenario': stage['scenario']}
                for stage in config['stages']
            ],
            'played': view['played'],
            'scheduled': len(view['matches']),
            'running': running,
            'people_waiting': len(waiting),
            'champion': None if champion is None else config['entrants'][champion]['name'],
            'champion_color': None if champion is None else config['entrants'][champion]['color'],
            'owner': self.owner(record['id']) if record['id'] not in self._owned else None,
            'persistence_error': record.get('persistence_error'),
        }

    def entries(self) -> list[dict[str, Any]]:
        """Returns a summary of every tournament, newest first."""
        with self._lock:
            records = sorted(self._records.values(), key=lambda r: r['created'], reverse=True)
            return [self._summary(record) for record in records]

    def get(self, identifier: str) -> dict[str, Any] | None:
        """Returns a tournament in full, with the state of every match, or `None`."""
        with self._lock:
            record = self._records.get(identifier)
            if record is None:
                return None
            view = self._view(record)
            current = self._games.current() if self._games is not None else None
            matches = []
            for match in view['matches']:
                entry = dict(match)
                running = self._running.get((identifier, match['key']))
                game = record['games'].get(match['key'])
                if match['result'] is not None:
                    entry['state'] = 'done'
                elif running is not None:
                    entry['state'] = 'running'
                    entry['progress'] = running['progress']
                elif game is not None:
                    entry['state'] = 'playing'
                    entry['game'] = game
                    if current is not None and current.get('id') == game:
                        entry['score'] = current.get('score')
                elif match['key'] in record['failures']:
                    entry['state'] = 'failed'
                    entry['error'] = record['failures'][match['key']]
                else:
                    entry['state'] = 'person' if match['person'] else 'ready'
                if match['key'] in record['notes']:
                    entry['note'] = record['notes'][match['key']]
                matches.append(entry)
            return {
                **self._summary(record),
                'config': record['config'],
                'stages_view': view['stages'],
                'matches': matches,
                'ranking': view['ranking'],
                'champion_index': view['champion'],
            }

    # Changes.

    def create(self, config: Any, run: bool = True) -> dict[str, Any]:
        """Checks a configuration, stores the tournament and returns its summary.

        Raises:
            ArgumentError: If the configuration cannot make a tournament.
            OSError: If the tournament cannot be written.
        """
        checked = check_config(config)
        with self._lock:
            identifier = _home.new_identifier('t')
            while identifier in self._records or self._path(identifier).exists():
                identifier = _home.new_identifier('t')
            record = {
                'version': _FILE_VERSION,
                'id': identifier,
                'created': time.time(),
                'finished': None,
                'config': checked,
                'results': {},
                'state': 'running' if run else 'stopped',
                'error': None if run else 'waiting for cuju render tournament run',
                'failures': {},
                'games': {},
                'notes': {},
            }
            _write(self._path(identifier), record)
            self._stamps[identifier] = self._path(identifier).stat().st_mtime_ns
            self._records[identifier] = record
            return self._summary(record)

    def _record(self, identifier: str) -> dict[str, Any]:
        record = self._records.get(identifier)
        if record is None:
            raise KeyError(identifier)
        if not self._claim(record):
            raise ArgumentError(
                f'the tournament runs in another process, {self.owner(identifier)}, which can '
                'change it'
            )
        return record

    def cancel(self, identifier: str) -> bool:
        """Cancels a tournament, ending its matches, and returns whether it existed.

        A tournament that another process runs gets a cancel marker, which that process applies.
        """
        with self._lock:
            record = self._records.get(identifier)
            if record is None:
                return False
            if not self._claim(record):
                (self._folder / f'{identifier}.cancel').write_text('', encoding='utf-8')
                return True
            self._cancel(record)
            return True

    def _cancel(self, record: dict[str, Any]) -> None:
        if record['state'] in ('done', 'cancelled'):
            return
        record.update(state='cancelled', error=None, finished=time.time(), games={})
        for key, running in list(self._running.items()):
            if key[0] == record['id'] and running.get('process') is not None:
                with contextlib.suppress(OSError):
                    running['process'].kill()
        self._persist(record)
        self._release(record['id'])

    def resume(self, identifier: str) -> dict[str, Any]:
        """Runs a stopped tournament again, retrying the matches that failed."""
        with self._lock:
            record = self._record(identifier)
            if record['state'] != 'stopped':
                raise ArgumentError(f'expected a stopped tournament, found it {record["state"]}')
            record.update(state='running', error=None, failures={})
            self._persist(record)
            return self._summary(record)

    def remove(self, identifier: str) -> bool:
        """Deletes a tournament that no longer runs, and returns whether it existed."""
        with self._lock:
            record = self._records.get(identifier)
            if record is None:
                return False
            if record['state'] == 'running':
                raise ArgumentError('expected a tournament that has ended, cancel it first')
            if not self._claim(record):
                raise ArgumentError('the tournament belongs to another process')
            self._path(identifier).unlink(missing_ok=True)
            self._forget(identifier)
            return True

    def _match(self, record: dict[str, Any], key: str) -> dict[str, Any]:
        view = self._view(record)
        match = next((m for m in view['matches'] if m['key'] == key), None)
        if match is None or match['result'] is not None:
            raise ArgumentError(f'expected a match of the tournament still to play, found {key!r}')
        return match

    def forfeit(self, identifier: str, key: str, side: Any) -> dict[str, Any]:
        """Awards a match to one side, by the forfeit score, and returns the tournament.

        Args:
            identifier: The tournament.
            key: The match.
            side: The side that wins, `home` or `away`.
        """
        if side not in ('home', 'away'):
            raise ArgumentError(f'expected the winning side as home or away, found {side!r}')
        with self._lock:
            record = self._record(identifier)
            match = self._match(record, key)
            if (identifier, key) in self._running or key in record['games']:
                raise ArgumentError('the match is playing now')
            goals = record['config']['forfeit_score']
            score = [goals, 0] if side == 'home' else [0, goals]
            self._finish(
                record, match, {'score': score, 'cards': [[0, 0], [0, 0]], 'forfeit': True}
            )
        return self.get(identifier)

    def play(self, identifier: str, key: str) -> dict[str, Any]:
        """Starts a match of a person as a game of the Play page and returns the game.

        Raises:
            ArgumentError: If the match has no person or cannot play now.
            GameBusyError: If another game plays.
        """
        if self._games is None:
            raise ArgumentError('the matches of people play on the page of the server')
        with self._lock:
            record = self._record(identifier)
            if record['state'] != 'running':
                raise ArgumentError(f'expected a running tournament, found it {record["state"]}')
            match = self._match(record, key)
            if not match['person']:
                raise ArgumentError('expected a match of a person')
            if key in record['games']:
                raise ArgumentError('the match is playing now')
            entrants = record['config']['entrants']
            sides = [entrants[match['home']], entrants[match['away']]]
            names = [side['name'] if side['kind'] == 'person' else None for side in sides]
            entry = self._games.start(
                match['scenario'],
                match['persons'],
                match['ability'],
                match['seed'],
                True,
                [side['team'] for side in sides],
                length=match['length'],
                tournament=self._provenance(record, match, names),
            )
            record['games'][key] = entry['id']
            record['notes'].pop(key, None)
            self._persist(record)
            return entry

    @staticmethod
    def _provenance(
        record: dict[str, Any], match: dict[str, Any], names: list[str | None] | None = None
    ) -> dict[str, Any]:
        stage = record['config']['stages'][match['stage']]
        provenance = {
            'id': record['id'],
            'name': record['config']['name'],
            'stage': stage['name'],
            'label': match['label'],
            'key': match['key'],
        }
        if names is not None:
            provenance['names'] = names
        return provenance

    def _finish(
        self, record: dict[str, Any], match: dict[str, Any], result: dict[str, Any]
    ) -> None:
        """Keeps a match's result, moves the ratings, and ends a tournament that is complete."""
        record['results'][match['key']] = rules.check_result(result)
        record['failures'].pop(match['key'], None)
        record['games'].pop(match['key'], None)
        entrants = record['config']['entrants']
        try:
            table = ratings()
            rules.update_ratings(
                table, entrants[match['home']], entrants[match['away']], result['score']
            )
            _write(folder() / 'ratings.json', table)
        except OSError as error:
            _LOGGER.warning('cuju render could not save the ratings, %s', error)
        self._versions[record['id']] += 1
        if self._view(record)['complete'] and record['state'] == 'running':
            record.update(state='done', finished=time.time())
        self._persist(record)
        if record['state'] == 'done':
            self._release(record['id'])

    # Running.

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.tick()
            except Exception as error:
                _LOGGER.warning('cuju render tournaments, %s: %s', type(error).__name__, error)

    def tick(self) -> None:
        """Starts the matches that can play, and takes the results of games that ended."""
        self._scan()
        with self._lock:
            for record in list(self._records.values()):
                if record['state'] != 'running' or not self._claim(record):
                    continue
                self._follow_games(record)
                view = self._view(record)
                if view['complete']:
                    record.update(state='done', finished=time.time())
                    self._persist(record)
                    self._release(record['id'])
                    continue
                busy = sum(1 for key in self._running if key[0] == record['id'])
                for match in rules.ready(view):
                    if busy >= record['config']['concurrency']:
                        break
                    key = (record['id'], match['key'])
                    if (
                        match['person']
                        or key in self._running
                        or match['key'] in record['failures']
                    ):
                        continue
                    self._running[key] = {'progress': 0.0, 'process': None}
                    busy += 1
                    threading.Thread(
                        target=self._run_match, args=(record['id'], dict(match)), daemon=True
                    ).start()

    def _follow_games(self, record: dict[str, Any]) -> None:
        """Takes the result of a person's game that ended, or frees a match whose game is gone."""
        if not record['games'] or self._games is None:
            return
        current = self._games.current()
        view = self._view(record)
        for key, game in list(record['games'].items()):
            if current is None or current.get('id') != game:
                record['games'].pop(key)
                record['notes'][key] = 'The game of this match ended without a result.'
                self._persist(record)
                continue
            if current.get('state') not in ('ended', 'failed'):
                continue
            match = next((m for m in view['matches'] if m['key'] == key), None)
            natural = current.get('ending') in ('full time', 'episode')
            if match is not None and natural and current.get('match'):
                try:
                    self._finish(record, match, recording_result(current['match']))
                    continue
                except (ArgumentError, OSError, ValueError) as error:
                    record['notes'][key] = f'The result could not be read, {error}'
            else:
                record['notes'][key] = (
                    'The game ended before full time, so the match waits to be played again.'
                )
            record['games'].pop(key, None)
            self._persist(record)

    def _run_match(self, identifier: str, match: dict[str, Any]) -> None:
        key = (identifier, match['key'])
        result, error = None, None
        try:
            with self._lock:
                record = self._records[identifier]
                provenance = self._provenance(record, match)
                entrants = record['config']['entrants']
                teams = [entrants[match['home']]['team'], entrants[match['away']]['team']]
            result = self._player(
                match, teams, provenance, lambda share: self._progress(key, share)
            )
        except Exception as failure:
            error = (
                f'{type(failure).__name__}: {failure}'
                if not isinstance(failure, (ArgumentError, RuntimeError))
                else str(failure)
            )
        with self._lock:
            self._running.pop(key, None)
            record = self._records.get(identifier)
            if record is None or record['state'] != 'running':
                return
            if result is not None:
                try:
                    self._finish(record, match, result)
                    return
                except rules.TournamentError as failure:
                    error = str(failure)
            record['failures'][match['key']] = error or 'the match gave no result'
            record.update(state='stopped', error=f'{match["label"]} failed, {error}')
            self._persist(record)

    def _progress(self, key: tuple[str, str], share: float, process: Any = None) -> None:
        with self._lock:
            running = self._running.get(key)
            if running is not None:
                running['progress'] = share
                if process is not None:
                    running['process'] = process

    def _play_process(
        self,
        match: dict[str, Any],
        teams: list[str],
        provenance: dict[str, Any],
        progress: Callable[..., None],
    ) -> dict[str, Any]:
        """Plays a match of agents in a child process and returns its result."""
        command = [
            sys.executable,
            '-m',
            'cuju.render._playing.play',
            '--left',
            teams[0],
            '--right',
            teams[1],
            '--scenario',
            match['scenario'],
            '--seed',
            str(match['seed']),
            '--tournament',
            json.dumps(provenance),
        ]
        if match['length'] is not None:
            command += ['--length', str(match['length'])]
        for side, value in zip(('left', 'right'), match['ability'], strict=True):
            if value is not None:
                command += [f'--{side}-ability', repr(value)]
        _home.home().mkdir(parents=True, exist_ok=True)
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
        key = (provenance['id'], match['key'])
        self._progress(key, 0.0, process)
        with self._lock:
            record = self._records.get(provenance['id'])
            stopped = record is None or record['state'] != 'running' or self._stop.is_set()
        if stopped:
            process.kill()
        stderr: collections.deque[str] = collections.deque(maxlen=20)
        threading.Thread(target=lambda: stderr.extend(process.stderr), daemon=True).start()
        timer = threading.Timer(MATCH_SECONDS, process.kill)
        timer.daemon = True
        timer.start()
        saved, failure = None, None
        try:
            for line in process.stdout:
                try:
                    report = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(report, dict):
                    continue
                if isinstance(report.get('progress'), (int, float)):
                    progress(float(report['progress']))
                if isinstance(report.get('match'), str):
                    saved = report['match']
                if isinstance(report.get('error'), str):
                    failure = report['error']
            code = process.wait()
        finally:
            timer.cancel()
        if code != 0 or saved is None:
            tail = ''.join(stderr).strip()
            raise RuntimeError(
                failure or f'the match ended with exit code {code}' + (f', {tail}' if tail else '')
            )
        return recording_result(saved)

    def run(self, identifier: str, report: Callable[[str], None] = print) -> str:
        """Runs one tournament in this process until it ends or waits for people.

        Returns:
            The state it stops in, `done`, `cancelled`, `stopped` or `people`.
        """
        with self._lock:
            record = self._records.get(identifier)
            if record is None:
                raise ArgumentError(f'expected a tournament, found {identifier!r}')
            if not self._claim(record):
                raise ArgumentError(
                    f'the tournament runs in another process, {self.owner(identifier)}'
                )
            if record['state'] == 'stopped':
                record.update(state='running', error=None, failures={})
                self._persist(record)
        played = -1
        while True:
            self.tick()
            with self._lock:
                record = self._records.get(identifier)
                if record is None:
                    return 'cancelled'
                view = self._view(record)
                busy = any(key[0] == identifier for key in self._running)
                state = record['state']
                if view['played'] != played:
                    played = view['played']
                    report(f'{played} of {len(view["matches"])} scheduled matches played')
            if state != 'running' and not busy:
                if state == 'stopped':
                    report(record['error'] or 'stopped')
                return state
            if not busy and all(m['person'] for m in rules.ready(view)) and rules.ready(view):
                return 'people'
            time.sleep(self._interval)
