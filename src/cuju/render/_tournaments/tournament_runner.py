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

Every file that the renderer writes carries a seal, a keyed digest of its content under a key that
only this home folder holds. A file without a valid seal, one dropped into the folder or edited by
hand, loads stopped, so it plays only once a person resumes it, and every file plays at most as
many matches at once as the rules allow.
"""

from __future__ import annotations

import collections
import contextlib
import hashlib
import hmac
import json
import logging
import os
import secrets
import struct
import subprocess
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
from .._text import messages as _messages
from .._text.messages import MessageError
from . import tournament as rules

_LOGGER = logging.getLogger('cuju')
_STATES = ('running', 'stopped', 'done', 'cancelled')
# A match of a tournament ends after this many seconds, as a requested match does.
MATCH_SECONDS = 30 * 60
_SCORE = struct.Struct('<2i')
_FILE_VERSION = 1
# How long a change waits for the process that runs its tournament to apply it, in seconds.
_ASK_SECONDS = 10.0
# The file of the home folder that holds the key of the seals of its tournament files.
_KEY_FILE = 'tournaments.key'
_KEYS: dict[str, bytes] = {}


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


def _key() -> bytes | None:
    """Returns the key that seals the tournament files of this home folder, made on first use.

    Returns `None` when the key cannot be read or made, and every file then loads as one that
    another install wrote.
    """
    path = _home.home() / _KEY_FILE
    if str(path) in _KEYS:
        return _KEYS[str(path)]
    for _ in range(50):
        try:
            text = path.read_text(encoding='ascii').strip()
        except FileNotFoundError:
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                continue
            except OSError as error:
                _LOGGER.warning('cuju render cannot make the key of its tournaments, %s', error)
                return None
            with os.fdopen(descriptor, 'w', encoding='ascii') as stream:
                stream.write(secrets.token_hex(32))
            continue
        except (OSError, ValueError) as error:
            _LOGGER.warning('cuju render cannot read the key of its tournaments, %s', error)
            return None
        if len(text) == 64:
            with contextlib.suppress(ValueError):
                _KEYS[str(path)] = bytes.fromhex(text)
                return _KEYS[str(path)]
        # Another process may be writing the key this moment.
        time.sleep(0.02)
    _LOGGER.warning('cuju render reads no key of its tournaments in %s', path.name)
    return None


def _seal(text: str) -> str | None:
    """Returns the seal of the text of a tournament file, or `None` without a key."""
    key = _key()
    return None if key is None else hmac.new(key, text.encode(), hashlib.sha256).hexdigest()


def _write_record(path: Path, record: dict[str, Any]) -> None:
    """Writes a tournament with the seal of its content last, which `_sealed` checks."""
    body = {key: value for key, value in record.items() if key != 'seal'}
    seal = _seal(json.dumps(body))
    _write(path, body if seal is None else {**body, 'seal': seal})


def _sealed(entry: dict[str, Any]) -> bool:
    """Takes the seal out of a tournament read from its file and returns whether it is valid.

    The JSON text of what a file holds, written again, is the text it was written from, so the
    seal of the rest of the entry is the seal written beside it.
    """
    seal = entry.pop('seal', None)
    if not isinstance(seal, str):
        return False
    expected = _seal(json.dumps(entry))
    return expected is not None and hmac.compare_digest(seal, expected)


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
        raise MessageError(
            'server.tournament.length',
            lowest=rules.MIN_LENGTH,
            highest=rules.MAX_LENGTH,
            length=repr(length),
        )
    source = _teams.scenario_path(scenario)
    if not source.is_file():
        raise MessageError('server.scenario', scenario=repr(scenario))
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


def fits(entrant: dict[str, Any], scenario: str) -> str | dict[str, Any] | None:
    """Returns why an entrant cannot play a scenario on either side, or `None` when it can.

    The reason is a label of its server message when it has one, so the page shows the whole of
    the refusal in its own language, else its text.
    """
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
        ids = _messages.id_fields(error)
        values = ids.get('error_values') if isinstance(ids, dict) else None
        # A team of the other size needs only its size, since the message names the rest.
        if (
            isinstance(ids, dict)
            and ids.get('error_id') == 'server.teams.scenario_format'
            and isinstance(values, dict)
        ):
            return _messages.label('server.tournament.team_format', format=values.get('format'))
        # The team's own refusal names the team and the scenario, which the tournament's message
        # names too, so the tournament keeps only its reason.
        if (
            isinstance(ids, dict)
            and ids.get('error_id') == 'server.teams.cannot_play'
            and isinstance(values, dict)
            and values.get('reason')
        ):
            return values['reason']
        return _error_label(str(error), ids)
    return None


def _error_label(error: str, ids: dict[str, Any] | None) -> str | dict[str, Any]:
    """Returns an error as a label of its message, the value of another message, else its text.

    The label passes on only with the values that its message names, as a report of a child
    process does, so an error of a file of before stays its text.
    """
    ids = ids if isinstance(ids, dict) else {}
    found = {'id': ids.get('error_id'), 'text': error, 'values': ids.get('error_values')}
    return found if _messages.valid_label(found) else error


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
        raise MessageError('server.library.unknown', identifier=repr(identifier))
    header = _recording.read_header(path)
    last = None
    # A recording of version 2 decodes its last frame from the keyframe before it.
    for frame in _recording.frames(path, start=max(0, (header.get('frame_count') or 0) - 1)):
        last = frame
    if last is None:
        raise MessageError('server.tournament.no_frame', identifier=identifier)
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
        raise MessageError('server.tournament.preset_name', name=repr(name))
    try:
        checked = rules.check_preset(preset)
    except rules.TournamentError as error:
        raise _messages.argument_error(error) from error
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
            raise _messages.argument_error(error) from error
        config = {**base, **config}
    try:
        return rules.check(config, _teams.teams(), fits, _rating_values(), scenarios())
    except rules.TournamentError as error:
        raise _messages.argument_error(error) from error


def preview(config: Any) -> dict[str, Any]:
    """Returns a configuration resolved, with the draw and first matches it would give.

    Raises:
        ArgumentError: With the reason, if it cannot make a tournament.
    """
    checked = check_config(config)
    view = rules.evaluate(checked, {})
    stages = [
        {
            **{key: stage[key] for key in ('format', 'entrants', 'advance', 'rounds', 'tables')},
            **rules.named_from('name', stage),
        }
        for stage in view['stages']
    ]
    return {'config': checked, 'stages': stages, 'matches': len(view['matches'])}


# The stored tournaments.


def _stored(path: Path) -> dict[str, Any] | None:
    """Returns the tournament that a file holds, or `None` with a warning."""
    entry = _read(path, None)
    sealed = isinstance(entry, dict) and _sealed(entry)
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
            # No file plays more matches at once than the rules allow a new tournament.
            concurrency = config.get('concurrency')
            if not isinstance(concurrency, int) or isinstance(concurrency, bool):
                concurrency = 1
            config['concurrency'] = min(max(concurrency, 1), rules.MAX_CONCURRENCY)
        except (rules.TournamentError, KeyError, TypeError, ValueError, IndexError) as error:
            problem = f'whose tournament cannot be read, {error}'
    if problem:
        _LOGGER.warning('cuju render skips the tournament file %s, %s', path.name, problem)
        return None
    for key, kind, default in (
        ('error', str, None),
        ('error_id', str, None),
        ('error_values', dict, None),
        ('failures', dict, {}),
        ('failure_ids', dict, {}),
        ('games', dict, {}),
        ('notes', dict, {}),
        ('created', (int, float), time.time()),
        ('finished', (int, float), None),
    ):
        if not isinstance(entry.get(key), kind):
            entry[key] = default
    # The id of the error's message passes on only with the error and the values it names.
    if entry['error'] is None or entry['error_id'] not in _messages.MESSAGES:
        entry['error_id'] = entry['error_values'] = None
    elif entry['error_values'] is None:
        entry['error_id'] = None
    # A running file that this install did not write, or that changed since, waits for a person.
    if not sealed and entry['state'] == 'running':
        _LOGGER.warning(
            'cuju render loads the tournament file %s stopped, since this install did not write it',
            path.name,
        )
        entry.update(state='stopped', **_messages.fields('server.tournament.foreign'))
    return entry


def _note(name: str, **values: Any) -> dict[str, Any]:
    """Returns a note of a match, such as a game that ended without a result, as a label."""
    return _messages.label(f'server.tournament.note.{name}', **values)


def _stored_note(note: Any) -> str | dict[str, Any] | None:
    """Returns a note that a file keeps, a label when it is a valid one, else its text."""
    if _messages.valid_label(note):
        return note
    return note if isinstance(note, str) else None


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
            for request in self._folder.glob('*.request'):
                self._answer(request)

    # Changes that another process asks for.

    def _answer(self, request: Path) -> None:
        """Applies an award or a resume that another process asked for, and writes the answer.

        The request names its tournament before its first dot, and the answer takes the same name
        with `.answer` in place of `.request`, holding `ok` or the error fields of the refusal.
        """
        record = self._records.get(request.name.split('.', 1)[0])
        if record is None or record['id'] not in self._owned:
            return
        try:
            asked = json.loads(request.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            asked = None
        with contextlib.suppress(OSError):
            request.unlink()
        if not isinstance(asked, dict) or asked.get('action') not in ('forfeit', 'resume'):
            return
        try:
            if asked['action'] == 'forfeit':
                self.forfeit(record['id'], str(asked.get('key')), asked.get('winner'))
            else:
                self.resume(record['id'])
            answer: dict[str, Any] = {'ok': True}
        except ArgumentError as error:
            answer = {'ok': False, **_messages.error_fields(error)}
        with contextlib.suppress(OSError):
            _write(request.with_suffix('.answer'), answer)

    def _ask_owner(self, identifier: str, action: dict[str, Any]) -> dict[str, Any]:
        """Asks the process that runs a tournament for a change and returns the tournament after.

        Raises:
            ArgumentError: If that process refuses the change, or does not answer in time.
        """
        request = self._folder / f'{identifier}.{os.getpid()}-{time.monotonic_ns()}.request'
        answer = request.with_suffix('.answer')
        _write(request, action)
        reply = None
        deadline = time.monotonic() + _ASK_SECONDS
        try:
            while reply is None and time.monotonic() < deadline:
                with contextlib.suppress(ValueError):
                    found = json.loads(_read_text(answer) or 'null')
                    reply = found if isinstance(found, dict) else None
                if reply is None:
                    time.sleep(0.05)
        finally:
            for path in (request, answer):
                with contextlib.suppress(OSError):
                    path.unlink()
        if reply is None:
            raise MessageError(
                'server.tournament.other_process_silent',
                owner=self.owner(identifier),
                route=f'POST /api/tournaments/{identifier}/{action["action"]}',
            )
        if not reply.get('ok'):
            reported = _messages.report_fields(reply)
            if reported['error_id'] is not None:
                raise MessageError(reported['error_id'], **reported['error_values'])
            if reported['error']:
                raise ArgumentError(reported['error'])
            raise MessageError('server.tournament.refused')
        self._scan()
        return self.get(identifier)

    def _forget(self, identifier: str) -> None:
        self._records.pop(identifier, None)
        self._views.pop(identifier, None)
        self._stamps.pop(identifier, None)
        self._release(identifier)

    def _persist(self, record: dict[str, Any]) -> None:
        """Writes a tournament, and keeps a failed write as its error instead of stopping."""
        self._versions[record['id']] += 1
        try:
            _write_record(self._path(record['id']), record)
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
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                stream.write(str(os.getpid()))
            self._owned.add(identifier)
            # A game lives no longer than the process that started it, so the games of people
            # that an earlier process followed are gone, and their matches wait to be played.
            if record['games']:
                for key in record['games']:
                    record['notes'][key] = _note('gone')
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
            **rules.named_from('name', config),
            'state': record['state'],
            'error': record['error'],
            'error_id': record.get('error_id'),
            'error_values': record.get('error_values'),
            'created': record['created'],
            'finished': record['finished'],
            'seed': config['seed'],
            'entrants': len(config['entrants']),
            'stages': [
                {
                    **rules.named_from('name', stage),
                    'format': stage['format'],
                    'scenario': stage['scenario'],
                }
                for stage in config['stages']
            ],
            'played': view['played'],
            'scheduled': len(view['matches']),
            'expected': view['expected'],
            'running': running,
            'failed': len(record['failures']),
            'people_waiting': len(waiting),
            **_messages.named(
                'champion',
                None if champion is None else rules.label_of(config['entrants'][champion]),
            ),
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
                    entry.update(self._failure(record, match['key']))
                else:
                    entry['state'] = 'person' if match['person'] else 'ready'
                if match['key'] in record['notes']:
                    entry.update(
                        _messages.named('note', _stored_note(record['notes'][match['key']]))
                    )
                matches.append(entry)
            return {
                **self._summary(record),
                'config': record['config'],
                'stages_view': view['stages'],
                'matches': matches,
                'ranking': view['ranking'],
                'champion_index': view['champion'],
            }

    def without_spoilers(self, identifier: str, watched: Any) -> dict[str, Any] | None:
        """Returns a tournament as a person sees it who watched only the matches of `watched`.

        Raises:
            ArgumentError: If `watched` is no list of match keys.
        """
        with self._lock:
            entry = self.get(identifier)
            if entry is None:
                return None
            results = dict(self._records[identifier]['results'])
        try:
            return rules.without_spoilers(entry, results, watched)
        except rules.TournamentError as error:
            raise _messages.argument_error(error) from error

    # Changes.

    def create(self, config: Any, run: bool = True) -> dict[str, Any]:
        """Checks a configuration, stores the tournament and returns its summary.

        Raises:
            ArgumentError: If the configuration cannot make a tournament.
            OSError: If the tournament cannot be written.
        """
        checked = check_config(config)
        with self._lock:
            identifier = _home.new_identifier('cup')
            while identifier in self._records or self._path(identifier).exists():
                identifier = _home.new_identifier('cup')
            record = {
                'version': _FILE_VERSION,
                'id': identifier,
                'created': time.time(),
                'finished': None,
                'config': checked,
                'results': {},
                'state': 'running' if run else 'stopped',
                **(
                    _messages.entry_fields(None)
                    if run
                    else _messages.fields('server.tournament.waiting')
                ),
                'failures': {},
                'failure_ids': {},
                'games': {},
                'notes': {},
            }
            _write_record(self._path(identifier), record)
            self._stamps[identifier] = self._path(identifier).stat().st_mtime_ns
            self._records[identifier] = record
            return self._summary(record)

    def _record(self, identifier: str) -> dict[str, Any]:
        record = self._records.get(identifier)
        if record is None:
            raise KeyError(identifier)
        if not self._claim(record):
            raise MessageError(
                'server.tournament.other_process_change', owner=self.owner(identifier)
            )
        return record

    def cancel(self, identifier: str) -> bool:
        """Cancels a tournament, ending its matches, and returns whether it existed.

        A tournament that another process runs gets a cancel marker, which that process applies.

        Raises:
            ArgumentError: If the tournament has already ended, done or cancelled.
        """
        with self._lock:
            record = self._records.get(identifier)
            if record is None:
                return False
            if record['state'] in ('done', 'cancelled'):
                raise MessageError('server.tournament.cancel_state', state=record['state'])
            if not self._claim(record):
                (self._folder / f'{identifier}.cancel').write_text('', encoding='utf-8')
                return True
            self._cancel(record)
            return True

    def _cancel(self, record: dict[str, Any]) -> None:
        if record['state'] in ('done', 'cancelled'):
            return
        record.update(
            state='cancelled', finished=time.time(), games={}, **_messages.entry_fields(None)
        )
        for key, running in list(self._running.items()):
            if key[0] == record['id'] and running.get('process') is not None:
                with contextlib.suppress(OSError):
                    running['process'].kill()
        self._persist(record)
        self._release(record['id'])

    def resume(self, identifier: str) -> dict[str, Any]:
        """Runs a stopped tournament again, retrying the matches that failed.

        A running tournament with failed matches, which plays on while people play theirs, also
        retries them.
        """
        with self._lock:
            record = self._records.get(identifier)
            if record is None:
                raise KeyError(identifier)
            if record['state'] != 'stopped' and not (
                record['state'] == 'running' and record['failures']
            ):
                raise MessageError('server.tournament.stopped', state=record['state'])
            asked = not self._claim(record)
        if asked:
            return self._ask_owner(identifier, {'action': 'resume'})
        with self._lock:
            record = self._record(identifier)
            if record['state'] != 'stopped' and not (
                record['state'] == 'running' and record['failures']
            ):
                raise MessageError('server.tournament.stopped', state=record['state'])
            record.update(
                state='running', failures={}, failure_ids={}, **_messages.entry_fields(None)
            )
            self._persist(record)
            return self._summary(record)

    def remove(self, identifier: str) -> bool:
        """Deletes a tournament that no longer runs, and returns whether it existed."""
        with self._lock:
            record = self._records.get(identifier)
            if record is None:
                return False
            if record['state'] == 'running':
                raise MessageError('server.tournament.ended')
            if not self._claim(record):
                raise MessageError('server.tournament.other_process')
            self._path(identifier).unlink(missing_ok=True)
            self._forget(identifier)
            return True

    def _match(self, record: dict[str, Any], key: str) -> dict[str, Any]:
        view = self._view(record)
        match = next((m for m in view['matches'] if m['key'] == key), None)
        if match is None or match['result'] is not None:
            raise MessageError('server.tournament.match_key', key=repr(key))
        return match

    def forfeit(self, identifier: str, key: str, side: Any) -> dict[str, Any]:
        """Awards a match to one side, by the forfeit score, and returns the tournament.

        An awarded match leaves the ratings as they are. A tournament that stopped on failed
        matches runs again when the award leaves a match that can play.

        Args:
            identifier: The tournament.
            key: The match.
            side: The side that wins, `home` or `away`.
        """
        if side not in ('home', 'away'):
            raise MessageError('server.tournament.winner', side=repr(side))
        with self._lock:
            record = self._records.get(identifier)
            if record is None:
                raise KeyError(identifier)
            # The key is checked first, so a wrong one reads as such whichever process runs it.
            self._match(record, key)
            asked = not self._claim(record)
        if asked:
            return self._ask_owner(identifier, {'action': 'forfeit', 'key': key, 'winner': side})
        with self._lock:
            record = self._record(identifier)
            match = self._match(record, key)
            if (identifier, key) in self._running or key in record['games']:
                raise MessageError('server.tournament.playing')
            goals = record['config']['forfeit_score']
            score = [goals, 0] if side == 'home' else [0, goals]
            held = record['state'] == 'stopped' and bool(record['failures'])
            self._finish(
                record, match, {'score': score, 'cards': [[0, 0], [0, 0]], 'forfeit': True}
            )
            if record['state'] == 'stopped' and (held or self._view(record)['complete']):
                view = self._view(record)
                if view['complete']:
                    record.update(
                        state='done', finished=time.time(), **_messages.entry_fields(None)
                    )
                elif self._playable(record, view):
                    record.update(state='running', **_messages.entry_fields(None))
                else:
                    record.update(self._failure_fields(record, view))
                self._persist(record)
                if record['state'] == 'done':
                    self._release(record['id'])
        return self.get(identifier)

    def play(self, identifier: str, key: str) -> dict[str, Any]:
        """Starts a match of a person as a game of the Play page and returns the game.

        Raises:
            ArgumentError: If the match has no person or cannot play now.
            GameBusyError: If another game plays.
        """
        if self._games is None:
            raise MessageError('server.tournament.people_page')
        with self._lock:
            record = self._record(identifier)
            if record['state'] != 'running':
                raise MessageError('server.tournament.running', state=record['state'])
            match = self._match(record, key)
            if not match['person']:
                raise MessageError('server.tournament.person_match')
            if key in record['games']:
                raise MessageError('server.tournament.playing')
            entrants = record['config']['entrants']
            sides = [entrants[match['home']], entrants[match['away']]]
            entry = self._games.start(
                match['scenario'],
                match['persons'],
                match['ability'],
                match['seed'],
                True,
                [side['team'] for side in sides],
                length=match['length'],
                tournament=self._provenance(record, match),
            )
            record['games'][key] = entry['id']
            record['notes'].pop(key, None)
            self._persist(record)
            return entry

    @staticmethod
    def _provenance(record: dict[str, Any], match: dict[str, Any]) -> dict[str, Any]:
        """Returns what a match's recording keeps of its tournament.

        The names are those of the two entrants, home first, as the tournament shows them, so a
        renamed team or a built-in AI at an ability keeps its name on Watch, in feeds and videos.
        The abilities are those that the tournament gives the built-in AI of each side, home
        first, from the entrant, the stage or the standard, with `None` for the scenario's own,
        beside the abilities that played, which the provenance keeps as `ability`.
        """
        stage = record['config']['stages'][match['stage']]
        entrants = record['config']['entrants']
        sides = [entrants[match['home']], entrants[match['away']]]
        return {
            'id': record['id'],
            **rules.named_from('name', record['config']),
            **rules.named_from('stage', stage),
            **rules.named_from('label', match, 'label'),
            'key': match['key'],
            'names': [side['name'] for side in sides],
            # The names again as labels where the rules made them, for the title of the recording.
            'labels': [rules.label_of(side) for side in sides],
            'ability': list(match['ability']),
        }

    def _finish(
        self, record: dict[str, Any], match: dict[str, Any], result: dict[str, Any]
    ) -> None:
        """Keeps a match's result, moves the ratings, and ends a tournament that is complete.

        A match awarded by forfeit was never played, so it leaves the ratings as they are.
        """
        checked = rules.check_result(result)
        record['results'][match['key']] = checked
        record['failures'].pop(match['key'], None)
        record['failure_ids'].pop(match['key'], None)
        record['games'].pop(match['key'], None)
        entrants = record['config']['entrants']
        try:
            if not checked['forfeit']:
                table = ratings()
                rules.update_ratings(
                    table, entrants[match['home']], entrants[match['away']], checked['score']
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

    def _playable(self, record: dict[str, Any], view: dict[str, Any]) -> bool:
        """Returns whether a match of a tournament plays now or can start, besides failed ones."""
        if record['games'] or any(key[0] == record['id'] for key in self._running):
            return True
        return any(match['key'] not in record['failures'] for match in rules.ready(view))

    @staticmethod
    def _failure(record: dict[str, Any], key: str) -> dict[str, Any]:
        """Returns the error fields of a failed match, with the id of its message when it has one.

        The id passes on only with a text and the values that its message names, as a report of a
        child process does, so a file of an earlier version leaves the error without one.
        """
        ids = record.get('failure_ids', {}).get(key)
        ids = ids if isinstance(ids, dict) else {}
        return _messages.report_fields({'error': record['failures'][key], **ids})

    @staticmethod
    def _failure_fields(record: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
        """Returns the error fields of a tournament with failed matches, the first named in full.

        The match and its error travel as labels, so the page shows the whole line in its own
        language.
        """
        labels = {match['key']: rules.label_of(match, 'label') for match in view['matches']}
        first, *others = record['failures']
        error = _error_label(record['failures'][first], record['failure_ids'].get(first))
        values = {'label': labels.get(first, first), 'error': error}
        if not others:
            return _messages.fields('server.tournament.match_failed', **values)
        if len(others) == 1:
            return _messages.fields('server.tournament.match_failed_one_more', **values)
        return _messages.fields('server.tournament.match_failed_more', **values, count=len(others))

    def _halt(self, record: dict[str, Any], view: dict[str, Any]) -> None:
        """Stops a tournament that only failed matches hold up, until an award or a retry.

        The stopped tournament is free for any process to change, so an award or a resume from
        the command line reaches it while the server runs.
        """
        record.update(state='stopped', **self._failure_fields(record, view))
        self._persist(record)
        self._release(record['id'])

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
                if record['failures'] and not self._playable(record, view):
                    self._halt(record, view)

    def _follow_games(self, record: dict[str, Any]) -> None:
        """Takes the result of a person's game that ended, or frees a match whose game is gone."""
        if not record['games'] or self._games is None:
            return
        current = self._games.current()
        view = self._view(record)
        for key, game in list(record['games'].items()):
            if current is None or current.get('id') != game:
                record['games'].pop(key)
                record['notes'][key] = _note('gone')
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
                    found = _error_label(str(error), _messages.id_fields(error))
                    record['notes'][key] = _note('unreadable', error=found)
            elif isinstance(current.get('error'), str) and current['error']:
                # A game that a policy or its process ended names the failure, and Award settles
                # the match as well as another game does.
                ids = {k: current.get(k) for k in ('error_id', 'error_values')}
                if match is not None:
                    error, ids = self._entrant_failure(record, match, current['error'], ids)
                    found = _error_label(error, ids)
                else:
                    found = _error_label(current['error'], ids)
                record['notes'][key] = _note('failed', error=found)
            else:
                record['notes'][key] = _note('early')
            record['games'].pop(key, None)
            self._persist(record)

    def _run_match(self, identifier: str, match: dict[str, Any]) -> None:
        key = (identifier, match['key'])
        result, error, ids = None, None, {}
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
            if isinstance(failure, (ArgumentError, RuntimeError)):
                error, ids = str(failure), _messages.id_fields(failure)
            else:
                error = _messages.described(failure)
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
                    error, ids = str(failure), _messages.id_fields(failure)
            if not error:
                found = _messages.fields('server.tournament.no_result')
                error, ids = found.pop('error'), found
            error, ids = self._entrant_failure(record, match, error, ids)
            # A failed match waits for an award or a retry, and the matches that do not
            # depend on it play on. The tournament stops once nothing else can play. Its error
            # keeps the id of its message beside it, as a requested match's does.
            record['failures'][match['key']] = error
            record['failure_ids'].pop(match['key'], None)
            if ids:
                record['failure_ids'][match['key']] = ids
            self._persist(record)
            view = self._view(record)
            if not self._playable(record, view):
                self._halt(record, view)

    @staticmethod
    def _entrant_failure(
        record: dict[str, Any], match: dict[str, Any], error: str, ids: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Returns a failure that names the player of a policy as its entrant, with its ids.

        A match plays a team of the registry under the name of its entrant, so the failure of
        the team Crashers entered as Crash FC reads as the policy of Crash FC.
        """
        values = ids.get('error_values') if isinstance(ids, dict) else None
        if not isinstance(values, dict) or not isinstance(values.get('player'), str):
            return error, ids
        entrants = record['config']['entrants']
        found = []
        for side in (match['home'], match['away']):
            entrant = entrants[side]
            if entrant['kind'] != 'team':
                continue
            try:
                team = _teams.entry(entrant['team'])
            except (ArgumentError, KeyError, OSError, ValueError):
                continue
            if team.get('name') == values['player']:
                found.append(entrant)
        # Two entrants of one team leave the failure as it reads, since either may have failed.
        if len(found) != 1 or found[0]['name'] == values['player']:
            return error, ids
        named = {**values, 'player': rules.label_of(found[0])}
        try:
            text = _messages.text(ids['error_id'], **named)
        except KeyError:
            return error, ids
        return text, {**ids, 'error_values': named}

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
            *_home.python_command(),
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
        saved, failure, reported = None, None, {}
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
                    failure, reported = report['error'], report
            code = process.wait()
        finally:
            timer.cancel()
        if code != 0 or saved is None:
            # The error that the match reported, or its exit code, with the id of its message.
            found = (
                _messages.report_fields(reported)
                if failure
                else _messages.exit_fields('server.requests.exit', code, ''.join(stderr).strip())
            )
            error = RuntimeError(found['error'])
            if found['error_id'] is not None:
                error.message_id, error.values = found['error_id'], found['error_values']
            raise error
        return recording_result(saved)

    def run(self, identifier: str, report: Callable[[str], None] = print) -> str:
        """Runs one tournament in this process until it ends or waits for people.

        Returns:
            The state it stops in, `done`, `cancelled`, `stopped` or `people`.
        """
        with self._lock:
            record = self._records.get(identifier)
            if record is None:
                raise MessageError(
                    'server.tournament.unknown_identifier', identifier=repr(identifier)
                )
            if not self._claim(record):
                raise MessageError(
                    'server.tournament.other_process_runs', owner=self.owner(identifier)
                )
            if record['state'] == 'stopped':
                record.update(
                    state='running', failures={}, failure_ids={}, **_messages.entry_fields(None)
                )
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
            waiting = [m for m in rules.ready(view) if m['key'] not in record['failures']]
            if not busy and waiting and all(m['person'] for m in waiting):
                if record['failures']:
                    report(self._failure_fields(record, view)['error'])
                return 'people'
            time.sleep(self._interval)
