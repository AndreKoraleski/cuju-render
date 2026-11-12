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

A tournament under strict rules plays each match of agents with each registered team in a process
of its own within the limits of its rules, and a side that breaks one forfeits the match at once,
by the forfeit score, and the tournament goes on. A tournament with a pre-flight first checks
every registered team, and leaves out those that fail, before its first match.
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
import shutil
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
from . import results as _results
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
# The key of the pre-flight among the matches that a tournament runs, which no match key takes.
_PREFLIGHT = '#preflight'
# A check of a team ends after this many seconds, as a long load and few calls take at most.
PREFLIGHT_SECONDS = 15 * 60
_KEYS: dict[str, bytes] = {}


def folder() -> Path:
    """Returns the folder of the tournaments, created when missing."""
    return _home.folder('tournaments')


def _threads() -> int:
    """Returns the threads of this machine, which the matches at once share."""
    return max(1, os.cpu_count() or 1)


def replay_path(identifier: str, key: str) -> Path:
    """Returns the file that keeps what replays a match of a tournament, its seed and actions."""
    return folder() / f'{identifier}.replays' / f'{key.replace("/", "_")}.json'


def replay_match(identifier: str, key: str) -> dict[str, Any]:
    """Plays a match of a tournament under strict rules again from its seed and actions.

    Returns:
        The match's key, the steps and score that the replay gave, and those that the match kept,
        with whether they agree.

    Raises:
        ArgumentError: If the match kept nothing to replay.
    """
    from .._playing import strict as _strict

    found = _read(replay_path(identifier, key), None)
    if not isinstance(found, dict) or not isinstance(found.get('actions'), list):
        raise MessageError('server.tournament.no_replay', key=repr(key))
    again = _strict.replay(found)
    kept = {'steps': len(found['actions']), 'score': found.get('score')}
    return {'key': key, 'replay': again, 'kept': kept, 'same': again == kept}


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


def fits(
    entrant: dict[str, Any], scenario: str, entries: dict[str, dict[str, Any]] | None = None
) -> str | dict[str, Any] | None:
    """Returns why an entrant cannot play a scenario on either side, or `None` when it can.

    The reason is a label of its server message when it has one, so the page shows the whole of
    the refusal in its own language, else its text. `entries` holds the teams of the registry by
    identifier, read once for a whole check, since reading the registry for each entrant and
    stage made the review of a few teams take seconds.
    """

    def entry(identifier: str) -> dict[str, Any]:
        if entries is None:
            return _teams.entry(identifier)
        if identifier not in entries:
            raise MessageError('server.teams.unknown', identifier=repr(identifier))
        return entries[identifier]

    builtin = entry(_teams.BUILTIN)
    try:
        # The random entrant's side is no team of the registry, which the rules name apart.
        team = (
            _teams.side_entry(entrant['team'])
            if entrant['team'] == _teams.RANDOM_ACTIONS
            else entry(entrant['team'])
        )
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


def warm() -> None:
    """Loads cuju's scenario builder and the list of scenarios, which every check of a tournament
    reads, so the first review of the page answers at once.

    The builder brings torch along, which takes seconds to import, so the server calls this in a
    thread of its own as it starts. A failure here only leaves the first check to load them.
    """
    try:
        scenarios()
        _teams.scenario_players('5_vs_5', 0)
    except Exception as error:
        _LOGGER.warning('cuju render could not load the scenarios ahead of time: %s', error)


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


def preflight(
    team: str, scenario: str | None = None, limits: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Checks a team in a process of its own, loading it and playing a few steps under strict rules.

    Args:
        team: The team of the registry.
        scenario: The scenario, by default the one of the team's size.
        limits: The limits of strict rules, or `None` to check only that the team loads and plays.

    Returns:
        The report of `strict.preflight`, whether the team passed, the rule it broke otherwise and
        its timings.

    Raises:
        ArgumentError: If the team is unknown, or the check itself fails.
    """
    _teams.entry(team)
    command = [*_home.python_command(), '-m', 'cuju.render._playing.strict', '--team', team]
    if scenario is not None:
        command += ['--scenario', scenario]
    if limits is not None:
        command += ['--limits', json.dumps(limits)]
    try:
        done = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=_home.process_folder(),
            env=_home.process_environment(),
            timeout=PREFLIGHT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise MessageError('server.preflight.timeout', count=PREFLIGHT_SECONDS // 60) from error
    report = None
    for line in done.stdout.splitlines():
        with contextlib.suppress(ValueError):
            found = json.loads(line)
            report = found if isinstance(found, dict) else report
    if report is None:
        found = _messages.exit_fields('server.requests.exit', done.returncode, done.stderr.strip())
        raise MessageError('server.preflight.failed', reason=found['error'])
    if 'error' in report and 'ok' not in report:
        reported = _messages.report_fields(report)
        if reported['error_id'] is not None:
            raise MessageError(reported['error_id'], **reported['error_values'])
        raise MessageError('server.preflight.failed', reason=reported['error'])
    return report


def check_team(team: str, document: Any) -> dict[str, Any]:
    """Checks one team as the Teams page asks, under strict rules with the limits it gives.

    Args:
        team: The team of the registry.
        document: An object with an optional `scenario` and optional `strict`, true or an object
            of limits as a tournament takes them, the default limits when absent.
    """
    document = document if isinstance(document, dict) else {}
    scenario = document.get('scenario')
    if scenario is not None and scenario not in scenarios():
        raise MessageError('server.scenario', scenario=repr(scenario))
    try:
        limits = rules.check_strict(document.get('strict', True))
    except rules.TournamentError as error:
        raise _messages.argument_error(error) from error
    return preflight(team, scenario, limits)


def preflight_config(config: Any) -> dict[str, Any]:
    """Checks every registered team of a tournament still to start, as its pre-flight will.

    Returns:
        The check of each team, under the tournament's strict rules or, without them, as a check
        that each team loads and plays, and the entrants that a pre-flight now would leave out.
    """
    checked = check_config(config)
    scenario = checked['stages'][0]['scenario']
    teams = list(dict.fromkeys(e['team'] for e in checked['entrants'] if e['kind'] == 'team'))
    checks = {team: preflight(team, scenario, checked.get('strict')) for team in teams}
    failed = {team for team, report in checks.items() if not report.get('ok')}
    return {
        'scenario': scenario,
        'checks': list(checks.values()),
        'excluded': [
            {
                **rules.named_from('name', entrant),
                'team': entrant['team'],
                **{
                    key: (checks[entrant['team']].get('rule') or {}).get(key)
                    for key in ('reason', 'reason_id', 'reason_values')
                },
            }
            for entrant in checked['entrants']
            if entrant['kind'] == 'team' and entrant['team'] in failed
        ],
    }


def forfeit_result(result: dict[str, Any], goals: int) -> dict[str, Any]:
    """Returns the result of a match that a side ended by breaking a rule, at the forfeit score.

    The side that broke the rule loses by the forfeit score, and two sides that broke one at the
    same step both lose, 0 to 0, while the rule keeps the reason and the score at that moment.
    """
    side = result['rule']['side']
    score = {'home': [0, goals], 'away': [goals, 0]}.get(side, [0, 0])
    return {**result, 'score': score, 'cards': [[0, 0], [0, 0]], 'match': None, 'forfeit': True}


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
    registry = _teams.teams()
    entries = {team['id']: team for team in registry}
    try:
        return rules.check(
            config,
            registry,
            lambda entrant, scenario: fits(entrant, scenario, entries),
            _rating_values(),
            scenarios(),
        )
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
        ('preflight', dict, None),
        ('excluded', list, []),
        ('digests', dict, {}),
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
        checker: Checks one team before a tournament's first match and returns its report, by
            default `preflight` in a child process. A test passes a function of its own.
    """

    def __init__(
        self,
        games: Any = None,
        player: Callable[..., dict[str, Any]] | None = None,
        only: str | None = None,
        start: bool = True,
        interval: float = 0.5,
        checker: Callable[..., dict[str, Any]] | None = None,
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
        self._checker = checker or preflight
        self._analyses: dict[str, tuple[int, dict[str, Any]]] = {}
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
        if not isinstance(asked, dict) or asked.get('action') not in ('forfeit', 'resume', 'legs'):
            return
        try:
            if asked['action'] == 'forfeit':
                self.forfeit(record['id'], str(asked.get('key')), asked.get('winner'))
            elif asked['action'] == 'legs':
                self.add_legs(record['id'], asked.get('legs'))
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
        self._analyses.pop(identifier, None)
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
            'strict': config.get('strict') is not None,
            'preflight': self._preflight_state(record),
            'excluded_count': len(record.get('excluded') or []),
        }

    def _preflight_state(self, record: dict[str, Any]) -> str | None:
        """Returns where a tournament's pre-flight stands, `None` for a tournament without one."""
        if not record['config'].get('preflight'):
            return None
        if record.get('preflight') is not None:
            return 'done'
        if (record['id'], _PREFLIGHT) in self._running:
            return 'running'
        return 'waiting'

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
                'checks': (record.get('preflight') or {}).get('checks', []),
                'excluded': list(record.get('excluded') or []),
            }

    def analysis(self, identifier: str) -> dict[str, Any] | None:
        """Returns the ratings, matrix, standings and matches of a tournament, or `None`.

        The analysis keeps until a result changes the tournament, since its bootstrap takes a
        while for a long league.
        """
        with self._lock:
            record = self._records.get(identifier)
            if record is None:
                return None
            version = self._versions[identifier]
            cached = self._analyses.get(identifier)
            if cached is not None and cached[0] == version:
                return cached[1]
            entry = self.get(identifier)
        found = _results.analysis(entry)
        with self._lock:
            self._analyses[identifier] = (version, found)
        return found

    def files(self, identifier: str) -> dict[str, str] | None:
        """Returns the text of each file of a tournament's results by its name, or `None`."""
        found = self.analysis(identifier)
        if found is None:
            return None
        return _results.files(self.get(identifier), found)

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
                'preflight': None,
                'excluded': [],
                'digests': {},
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

    def add_legs(self, identifier: str, legs: Any) -> dict[str, Any]:
        """Adds legs to the last stage of a tournament, a league or groups, and returns it.

        The matches of before keep their keys, seeds and results, so only the added matches play.
        A finished tournament runs again to play them, and a running or stopped one keeps its
        state.

        Raises:
            ArgumentError: If the tournament was cancelled, its last stage takes no legs, or the
                legs would pass the most.
        """
        with self._lock:
            record = self._records.get(identifier)
            if record is None:
                raise KeyError(identifier)
            if record['state'] == 'cancelled':
                raise MessageError('server.tournament.legs_cancelled')
            try:
                rules.add_legs(record['config'], legs)
            except rules.TournamentError as error:
                raise _messages.argument_error(error) from error
            asked = not self._claim(record)
        if asked:
            return self._ask_owner(identifier, {'action': 'legs', 'legs': legs})
        with self._lock:
            record = self._record(identifier)
            try:
                record['config'] = rules.add_legs(record['config'], legs)
            except rules.TournamentError as error:
                raise _messages.argument_error(error) from error
            if record['state'] == 'done':
                record.update(state='running', finished=None, **_messages.entry_fields(None))
            self._persist(record)
            return self.get(identifier)

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
            shutil.rmtree(folder() / f'{identifier}.replays', ignore_errors=True)
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

        A match awarded by forfeit was never played, so it leaves the ratings as they are, and so
        does a match that a side ended by breaking a rule, at the forfeit score.
        """
        replay = result.pop('replay', None) if isinstance(result, dict) else None
        if isinstance(result.get('rule'), dict):
            score = list(result['rule'].get('at') or [0, 0])
            result = forfeit_result(result, record['config']['forfeit_score'])
        else:
            score = list(result.get('score') or [0, 0])
        checked = rules.check_result(result)
        if isinstance(replay, dict) and isinstance(replay.get('actions'), list):
            # A match under strict rules keeps its seed and the actions of every step, which
            # replay it exactly, beside the tournament's file.
            path = replay_path(record['id'], match['key'])
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                _write(path, {**replay, 'key': match['key'], 'score': score})
            except OSError as error:
                _LOGGER.warning('cuju render could not keep the actions of a match, %s', error)
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
                if self._preflight_pending(record):
                    continue
                view = self._view(record)
                if view['complete']:
                    record.update(state='done', finished=time.time())
                    self._persist(record)
                    self._release(record['id'])
                    continue
                busy = sum(1 for key in self._running if key[0] == record['id'])
                load = sum(running.get('cost', 1) for running in self._running.values())
                for match in rules.ready(view):
                    if busy >= record['config']['concurrency']:
                        break
                    cost = self._cost(record, match)
                    # The processes of strict rules count against the threads of the machine,
                    # so matches at once never crowd each other into timeouts that no team caused.
                    if busy and load + cost > _threads():
                        break
                    key = (record['id'], match['key'])
                    if (
                        match['person']
                        or key in self._running
                        or match['key'] in record['failures']
                    ):
                        continue
                    self._running[key] = {'progress': 0.0, 'process': None, 'cost': cost}
                    busy += 1
                    load += cost
                    threading.Thread(
                        target=self._run_match, args=(record['id'], dict(match)), daemon=True
                    ).start()
                if record['failures'] and not self._playable(record, view):
                    self._halt(record, view)

    @staticmethod
    def _cost(record: dict[str, Any], match: dict[str, Any]) -> int:
        """Returns the threads that a match takes, its own and those of each team's process.

        Under strict rules each registered team plays in a process of its own with the threads
        that the rules give, beside the match's process, and a match without them takes one.
        """
        strict = record['config'].get('strict')
        if not strict:
            return 1
        entrants = record['config']['entrants']
        teams = sum(
            1 for side in (match['home'], match['away']) if entrants[side]['kind'] == 'team'
        )
        return 1 + teams * int(strict.get('threads', 1))

    def _preflight_pending(self, record: dict[str, Any]) -> bool:
        """Starts a tournament's pre-flight when it is due, and returns whether it holds matches.

        A tournament with a pre-flight checks its registered teams before its first match, so a
        file of before, or one that has played a match, plays on without one.
        """
        if not record['config'].get('preflight') or record.get('preflight') is not None:
            return False
        if record['results']:
            return False
        key = (record['id'], _PREFLIGHT)
        if key not in self._running:
            self._running[key] = {'progress': 0.0, 'process': None}
            threading.Thread(target=self._run_preflight, args=(record['id'],), daemon=True).start()
        return True

    def _run_preflight(self, identifier: str) -> None:
        """Checks every registered team of a tournament and leaves out those that fail."""
        key = (identifier, _PREFLIGHT)
        try:
            with self._lock:
                record = self._records[identifier]
                config = record['config']
                scenario = config['stages'][0]['scenario']
                limits = config.get('strict')
                teams = list(
                    dict.fromkeys(e['team'] for e in config['entrants'] if e['kind'] == 'team')
                )
            checks: dict[str, dict[str, Any]] = {}
            for number, team in enumerate(teams):
                try:
                    report = self._checker(team, scenario, limits)
                except Exception as error:
                    ids = _messages.id_fields(error)
                    report = {
                        'team': team,
                        'ok': False,
                        'rule': {
                            'side': 'home',
                            'kind': 'load',
                            'reason': str(error),
                            'reason_id': ids.get('error_id'),
                            'reason_values': ids.get('error_values'),
                            'step': 0,
                            'at': [0, 0],
                        },
                        'timings': {},
                    }
                checks[team] = report
                self._progress(key, (number + 1) / max(1, len(teams)))
        except Exception as error:
            _LOGGER.warning('cuju render could not check the teams, %s', error)
            checks = None
        with self._lock:
            self._running.pop(key, None)
            record = self._records.get(identifier)
            if (
                record is None
                or record['state'] != 'running'
                or record['results']
                or checks is None
            ):
                return
            self._apply_preflight(record, checks, scenario)

    def _apply_preflight(
        self, record: dict[str, Any], checks: dict[str, dict[str, Any]], scenario: str
    ) -> None:
        """Keeps the checks of a pre-flight, and makes the tournament again without the teams
        that failed, from its stages as given, so its draw fits the entrants that remain."""
        config = record['config']
        failed = {team for team, report in checks.items() if not report.get('ok')}
        excluded = []
        kept = []
        given = config.get('given_entrants') or []
        for index, entrant in enumerate(config['entrants']):
            if entrant['kind'] == 'team' and entrant['team'] in failed:
                rule = checks[entrant['team']].get('rule') or {}
                excluded.append(
                    {
                        **rules.named_from('name', entrant),
                        'kind': entrant['kind'],
                        'team': entrant['team'],
                        'reason': rule.get('reason', ''),
                        'reason_id': rule.get('reason_id'),
                        'reason_values': rule.get('reason_values'),
                        'rule': rule.get('kind'),
                        'timings': checks[entrant['team']].get('timings') or {},
                    }
                )
            elif index < len(given):
                kept.append(given[index])
        record['preflight'] = {
            'scenario': scenario,
            'checked': time.time(),
            'checks': [
                {
                    'team': team,
                    **rules.named_from('name', report),
                    'ok': bool(report.get('ok')),
                    'rule': report.get('rule'),
                    'timings': report.get('timings') or {},
                }
                for team, report in checks.items()
            ],
        }
        record['excluded'] = excluded
        # The digest of each team's folder that passed, which its matches hold it to.
        record['digests'] = {
            team: report['digest']
            for team, report in checks.items()
            if report.get('ok') and isinstance(report.get('digest'), str)
        }
        if excluded:
            source: dict[str, Any] = {
                key: config[key]
                for key in (
                    'seed',
                    'seeding',
                    'concurrency',
                    'forfeit_score',
                    'ability',
                    'preset',
                    'strict',
                    'preflight',
                )
                if key in config
            }
            if config.get('name_id') is None:
                source['name'] = config['name']
            source.update(
                entrants=kept,
                stages=config['given']['stages'],
                defaults=config['given']['defaults'],
            )
            try:
                changed = check_config(source)
            except ArgumentError as error:
                record.update(
                    state='stopped',
                    **_messages.fields(
                        'server.preflight.left_out',
                        error=_error_label(str(error), _messages.id_fields(error)),
                    ),
                )
                self._persist(record)
                self._release(record['id'])
                return
            changed['include'] = config.get('include', [])
            changed['given_entrants'] = kept
            record['config'] = changed
        self._persist(record)

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

    def _changed(
        self, identifier: str, match: dict[str, Any], teams: list[str], kinds: list[str]
    ) -> dict[str, Any] | None:
        """Returns the forfeit of a match whose team's files changed since its pre-flight, or None.

        Under strict rules with frozen folders, each team's folder keeps the digest that its
        pre-flight read, or that its first match read in a tournament without a pre-flight, and
        a team whose files differ at a later match breaks the rule `changed` before it plays.
        """
        from .._playing import strict as _strict

        strict = match.get('strict')
        if not strict or not strict.get('frozen', True):
            return None
        breaks = []
        for side, (team, kind) in enumerate(zip(teams, kinds, strict=True)):
            if kind != 'team':
                continue
            try:
                found = _strict.folder_digest(team)
            except OSError:
                found = None
            with self._lock:
                record = self._records.get(identifier)
                if record is None or found is None:
                    continue
                kept = record.setdefault('digests', {}).get(team)
                if kept is None:
                    record['digests'][team] = found
                    self._persist(record)
                elif kept != found:
                    name = record['config']['entrants'][match['home' if side == 0 else 'away']]
                    breaks.append(
                        (
                            side,
                            _messages.label('server.strict.changed', player=rules.label_of(name)),
                        )
                    )
        if not breaks:
            return None
        sides = {side for side, _ in breaks}
        reason = breaks[0][1]
        rule = {
            'side': 'both' if len(sides) > 1 else ('home', 'away')[breaks[0][0]],
            'kind': 'changed',
            'reason': reason['text'],
            'reason_id': reason['id'],
            'reason_values': reason['values'],
            'step': 0,
            'at': [0, 0],
        }
        stats = {'steps': 0, 'cut_short': True, 'sides': [None, None]}
        return {'score': [0, 0], 'rule': rule, 'forfeit': True, 'match': None, 'stats': stats}

    def _run_match(self, identifier: str, match: dict[str, Any]) -> None:
        key = (identifier, match['key'])
        result, error, ids = None, None, {}
        try:
            with self._lock:
                record = self._records[identifier]
                provenance = self._provenance(record, match)
                entrants = record['config']['entrants']
                teams = [entrants[match['home']]['team'], entrants[match['away']]['team']]
                match = {**match, 'strict': record['config'].get('strict')}
                kinds = [entrants[match['home']]['kind'], entrants[match['away']]['kind']]
            result = self._changed(identifier, match, teams, kinds) or self._player(
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
        if match.get('strict') is not None:
            command += ['--strict', json.dumps(match['strict']), '--replay']
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
        saved, failure, reported, stats, rule, replay = None, None, {}, None, None, None
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
                if isinstance(report.get('stats'), dict):
                    stats = report['stats']
                if isinstance(report.get('forfeit'), dict):
                    rule = report['forfeit']
                if isinstance(report.get('replay'), dict):
                    replay = report['replay']
                if isinstance(report.get('error'), str):
                    failure, reported = report['error'], report
            code = process.wait()
        finally:
            timer.cancel()
        if code == 0 and rule is not None:
            # A side broke a rule of strict rules, which the runner scores as its forfeit.
            found = {'score': [0, 0], 'rule': rule, 'stats': stats, 'forfeit': True, 'match': None}
            return {**found, 'replay': replay} if replay else found
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
        result = recording_result(saved)
        if stats is not None:
            result['stats'] = stats
        if replay:
            result['replay'] = replay
        return result

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
