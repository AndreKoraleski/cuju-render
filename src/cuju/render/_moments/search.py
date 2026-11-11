# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The index of the moments of every recording of the library, and the search over it.

The index keeps one small file per recording in the folder `index` of the renderer's home, with
the moments that `_events` finds in its frames. Each search first brings the index up to date, so
a recording that arrives is read once, a recording whose file changes is read again, and the file
of a recording deleted for good goes. A recording in the Trash keeps its file, so a restore finds
it at once, and a change of the version of the moments or of the index rebuilds every file.

A query is a line of words and filters, such as `goal team:Greens after:60`, as `QUERY_HELP`
describes and the guide documents under Searching moments.
"""

from __future__ import annotations

import json
import re
import threading
import unicodedata
from pathlib import Path
from typing import Any

from cuju.errors import ArgumentError

from .._format import recording as _recording
from .._store import home as _home
from .._store import library as _library
from . import captions as _captions
from . import events as _events

# The version of the files of the index, beside the version of the moments.
INDEX_VERSION = 1
VERSION = f'{INDEX_VERSION}.{_events.VERSION}'
# The most results a search returns unless it asks for others, and the most it may ask for.
LIMIT = 50
MAXIMUM_LIMIT = 1000
# Seconds before a moment that its result opens Watch at.
LEAD_SECONDS = 4.0
_LOCK = threading.RLock()
# The entries of each renderer folder by recording, so a sync that started for one folder keeps
# to it while another one becomes the home.
_CACHES: dict[str, dict[str, tuple[list[int], dict[str, Any]]]] = {}

# The words that name kinds of moments, each with the kind and a test of its data.
_WORDS: dict[str, tuple[str, Any]] = {}


def _word(names: str, kind: str, test: Any = None) -> None:
    for name in names.split():
        _WORDS[name] = (kind, test)


_word('goal goals', 'goal')
_word('own-goal own-goals owngoal', 'goal', lambda d: bool(d.get('ownGoal')))
_word('shot shots', 'shot')
_word('header headers', 'shot', lambda d: bool(d.get('header')))
_word('save saves', 'save')
_word('block blocks', 'block')
_word('woodwork', 'woodwork')
_word('post posts', 'woodwork', lambda d: d.get('part') != 'bar')
_word('bar crossbar', 'woodwork', lambda d: d.get('part') == 'bar')
_word('near-miss near-misses nearmiss miss misses', 'nearMiss')
_word('pass passes', 'pass')
_word('tackle tackles slide slides', 'tackle')
_word('foul fouls', 'foul')
_word('card cards', 'card')
_word('yellow yellows yellow-card', 'card', lambda d: d.get('colour') == 'yellow')
_word('red reds red-card', 'card', lambda d: d.get('colour') == 'red')
_word('offside offsides', 'offside')
_word('restart restarts', 'restart')
_word('set-piece set-pieces setpiece', 'restart', lambda d: d.get('restart') != 'kickoff')
for _name, _restart in (
    ('corner corners', 'corner'),
    ('free-kick free-kicks freekick', 'free_kick'),
    ('penalty penalties', 'penalty'),
    ('throw-in throw-ins throwin', 'throw_in'),
    ('goal-kick goal-kicks goalkick', 'goal_kick'),
    ('kickoff kick-off kickoffs', 'kickoff'),
):
    _word(_name, 'restart', lambda d, restart=_restart: d.get('restart') == restart)
_word('possession turnover turnovers', 'possession')
_word('halftime half-time', 'halftime')
_word('fulltime full-time', 'fulltime')

_KEYS = (
    'kind',
    'team',
    'player',
    'scenario',
    'source',
    'tournament',
    'challenge',
    'match',
    'date',
    'since',
    'until',
    'after',
    'before',
    'score',
    'outcome',
    'limit',
)
_SOURCES = {
    'requested': 'requested_match',
    'requested_match': 'requested_match',
    'match': 'requested_match',
    'game': 'human_game',
    'played': 'human_game',
    'human_game': 'human_game',
    'challenge': 'challenge',
    'recorder': 'recorder',
    'live': 'live',
}
_STATES = {
    'leading': 1,
    'winning': 1,
    'ahead': 1,
    'level': 0,
    'drawing': 0,
    'tied': 0,
    'trailing': -1,
    'losing': -1,
    'behind': -1,
}
_TERM = re.compile(r'(-?)(?:([A-Za-z]+):)?(?:"([^"]*)"?|(\S+))')
_DATE = re.compile(r'\d{4}(-\d{2}(-\d{2})?)?')
_SCORE = re.compile(r'(\d+)-(\d+)')

QUERY_HELP = (
    'words name kinds, such as goal, shot, save, pass, tackle, card, yellow, red, foul, '
    'offside, corner, free-kick, penalty, throw-in, goal-kick, set-piece, possession, '
    'woodwork and near-miss, and other words match the title, scenario, teams and players. '
    'Filters are kind:, team:, player:, scenario:, source:, tournament:, challenge:, match:, '
    'date:, since:, until:, after:, before:, score:, outcome: and limit:, a minus sign before a '
    'term excludes what it matches, and quotes hold words together, as in team:"Harbour Rovers".'
)


def fold(text: Any) -> str:
    """Returns text in lower case without accents, so a query matches whatever way it is typed."""
    normal = unicodedata.normalize('NFD', str(text if text is not None else ''))
    return ''.join(c for c in normal if not unicodedata.combining(c)).lower()


def _cache(home: Path) -> dict[str, tuple[list[int], dict[str, Any]]]:
    return _CACHES.setdefault(str(home), {})


def _signature(path: Path) -> list[int]:
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns]


def _header(document: dict[str, Any]) -> dict[str, Any]:
    """Returns what the index keeps of a header, the teams with their rosters and the players."""
    teams = []
    for team in document.get('teams') or []:
        team = team if isinstance(team, dict) else {}
        style = team.get('style') if isinstance(team.get('style'), dict) else {}
        kept = {'name': team.get('name'), 'style': {'players': style.get('players') or []}}
        if team.get('id') is not None:
            kept['id'] = team['id']
        teams.append(kept)
    players = [
        {key: player.get(key) for key in ('team', 'index', 'goalkeeper')}
        for player in document.get('players') or []
    ]
    return {
        'title': document.get('title'),
        'scenario': document.get('scenario'),
        'steps_per_second': document.get('steps_per_second') or 10,
        'teams': teams,
        'players': players,
    }


def build(path: Path) -> dict[str, Any]:
    """Returns the index entry of the recording file at `path`, its header and moments."""
    document = _recording.read_header(path)
    moments = _events.moments(document, _recording.frames(path), timing=True)
    return {
        'version': VERSION,
        'id': path.stem,
        'signature': _signature(path),
        'header': _header(document),
        'moments': moments,
    }


def _write(folder: Path, entry: dict[str, Any]) -> None:
    target = folder / f'{entry["id"]}.json'
    temporary = target.with_name(target.name + '.part')
    temporary.write_text(json.dumps(entry, separators=(',', ':')))
    temporary.replace(target)


def _read(folder: Path, identifier: str) -> dict[str, Any] | None:
    try:
        entry = json.loads((folder / f'{identifier}.json').read_text())
    except (OSError, ValueError):
        return None
    return entry if isinstance(entry, dict) else None


def sync() -> dict[str, int]:
    """Brings the index up to date with the library and returns what it did.

    Returns:
        The number of `recordings` the index holds, those it `built` now, those it `removed` and
        those it `failed` to read, which keep an empty entry until their file changes.
    """
    home = _home.home()
    with _LOCK:
        cache = _cache(home)
        matches = home / 'matches'
        matches.mkdir(parents=True, exist_ok=True)
        recordings = {path.stem: path for path in matches.glob('*.cjr')}
        index = home / 'index'
        index.mkdir(parents=True, exist_ok=True)
        removed = 0
        for path in index.glob('*.json'):
            if path.stem not in recordings:
                path.unlink(missing_ok=True)
                removed += 1
        for path in index.glob('*.json.part'):
            path.unlink(missing_ok=True)
        for identifier in list(cache):
            if identifier not in recordings:
                del cache[identifier]
        built = failed = 0
        for identifier, path in recordings.items():
            try:
                signature = _signature(path)
            except OSError:
                continue
            held = cache.get(identifier)
            if held is not None and held[0] == signature and held[1].get('version') == VERSION:
                continue
            entry = _read(index, identifier)
            if (
                entry is None
                or entry.get('version') != VERSION
                or entry.get('signature') != signature
            ):
                try:
                    entry = build(path)
                except Exception as error:
                    entry = {
                        'version': VERSION,
                        'id': identifier,
                        'signature': signature,
                        'header': {'teams': [], 'players': []},
                        'moments': [],
                        'error': f'{type(error).__name__}: {error}',
                    }
                    failed += 1
                _write(index, entry)
                built += 1
            cache[identifier] = (signature, entry)
        return {'recordings': len(cache), 'built': built, 'removed': removed, 'failed': failed}


def entry(identifier: str) -> dict[str, Any]:
    """Returns the index entry of a recording of the library, bringing the index up to date.

    Raises:
        ArgumentError: If the library holds no such recording outside the Trash.
    """
    if _library.path_of(identifier) is None:
        raise ArgumentError(f'expected a recording of the library, found {identifier!r}')
    sync()
    with _LOCK:
        return _cache(_home.home())[identifier][1]


def _terms(query: str) -> list[tuple[bool, str | None, str]]:
    """Returns the terms of a query, each whether it is negated, its key or `None`, its value."""
    terms = []
    for match in _TERM.finditer(query or ''):
        negated, key, quoted, plain = match.groups()
        value = quoted if quoted is not None else plain
        if key is None and not value:
            continue
        if key is not None:
            key = key.lower()
            if key not in _KEYS:
                raise ArgumentError(
                    f'expected a filter of {", ".join(k + ":" for k in _KEYS)}, found {key}:'
                )
        terms.append((bool(negated), key, value))
    return terms


def _minutes(value: str, key: str) -> float:
    """Returns a time of the match clock, given as minutes, mm:ss, 90s or 60m, in milliseconds."""
    text = value.strip().lower()
    try:
        if ':' in text:
            minutes, seconds = text.split(':', 1)
            return (float(minutes) * 60 + float(seconds)) * 1000
        if text.endswith('s'):
            return float(text[:-1]) * 1000
        return float(text.removesuffix('m')) * 60000
    except ValueError:
        raise ArgumentError(
            f'expected {key}: as minutes of the clock, such as 60, 60:30 or 90s, found {value!r}'
        ) from None


class _Moment:
    """One moment of one recording with what the filters read of it."""

    def __init__(self, moment: dict[str, Any], record: dict[str, Any]) -> None:
        self.moment = moment
        self.record = record

    @property
    def data(self) -> dict[str, Any]:
        return self.moment.get('data') or {}

    def player(self) -> dict[str, Any] | None:
        k = self.moment.get('player')
        players = self.record['context']['players']
        return players[k] if k is not None and 0 <= k < len(players) else None

    def before(self) -> list[int] | None:
        """Returns the score of the left and the right team just before the moment."""
        score = self.moment.get('score')
        if not isinstance(score, list):
            return None
        if self.moment['kind'] == 'goal' and self.moment.get('team') in (0, 1):
            score = list(score)
            score[self.moment['team']] -= 1
        return score


def _kind_test(value: str) -> Any:
    names = [fold(name) for name in value.split(',') if name.strip()]
    tests = []
    for name in names:
        if name not in _WORDS:
            raise ArgumentError(f'expected a kind of moment such as goal or corner, found {name!r}')
        tests.append(_WORDS[name])

    def test(item: _Moment) -> bool:
        return any(
            item.moment['kind'] == kind and (check is None or check(item.data))
            for kind, check in tests
        )

    return test


def _filter(key: str, value: str) -> Any:
    """Returns the test of one filter of a query."""
    text = fold(value).strip()
    if key == 'kind':
        return _kind_test(value)
    if key == 'team':
        if text in ('left', 'home', '0'):
            return lambda item: item.moment.get('team') == 0
        if text in ('right', 'away', '1'):
            return lambda item: item.moment.get('team') == 1

        def team(item: _Moment) -> bool:
            side = item.moment.get('team')
            names = item.record['context']['teams']
            return side in (0, 1) and text in fold(names[side] or '')

        return team
    if key == 'player':
        if text.isdigit():
            number = int(text)
            return lambda item: (item.player() or {}).get('number') == number
        return lambda item: bool(text) and text in fold((item.player() or {}).get('name'))
    if key == 'scenario':

        def scenario(item: _Moment) -> bool:
            name = str(item.record['scenario'] or '')
            return text in fold(name) or text.replace(' ', '_') in fold(name)

        return scenario
    if key == 'source':
        if text == 'tournament':
            return lambda item: isinstance(item.record['provenance'].get('tournament'), dict)
        if text == 'unknown':
            return lambda item: not item.record['provenance'].get('source')
        if text not in _SOURCES:
            raise ArgumentError(
                'expected source: as requested, game, challenge, recorder, live, tournament or '
                f'unknown, found {value!r}'
            )
        wanted = _SOURCES[text]
        return lambda item: item.record['provenance'].get('source') == wanted
    if key == 'tournament':

        def tournament(item: _Moment) -> bool:
            held = item.record['provenance'].get('tournament')
            if not isinstance(held, dict):
                return False
            return any(text in fold(held.get(field)) for field in ('name', 'id', 'stage'))

        return tournament
    if key == 'challenge':

        def challenge(item: _Moment) -> bool:
            held = item.record['provenance'].get('challenge')
            return held is not None and text in fold(held)

        return challenge
    if key == 'match':
        return lambda item: text == fold(item.record['id']) or text in fold(item.record['title'])
    if key in ('date', 'since', 'until'):
        if not _DATE.fullmatch(text):
            raise ArgumentError(f'expected {key}: as a date such as 2026-11-10, found {value!r}')
        if key == 'date':
            return lambda item: str(item.record['created'] or '').startswith(text)
        if key == 'since':
            return lambda item: str(item.record['created'] or '')[: len(text)] >= text
        return lambda item: str(item.record['created'] or '')[: len(text)] <= text
    if key in ('after', 'before'):
        bound = _minutes(value, key)
        if key == 'after':
            return lambda item: item.moment.get('clock', 0) >= bound
        return lambda item: item.moment.get('clock', 0) < bound
    if key == 'score':
        exact = _SCORE.fullmatch(text)
        if exact:
            wanted = [int(exact.group(1)), int(exact.group(2))]
            return lambda item: item.moment.get('score') == wanted
        if text not in _STATES:
            raise ArgumentError(
                'expected score: as leading, level, trailing or a score such as 2-1, '
                f'found {value!r}'
            )
        state = _STATES[text]

        def standing(item: _Moment) -> bool:
            score, side = item.before(), item.moment.get('team')
            if score is None or side not in (0, 1):
                return False
            margin = score[side] - score[1 - side]
            return (margin > 0) - (margin < 0) == state

        return standing
    if key == 'outcome':

        def outcome(item: _Moment) -> bool:
            data = item.data
            if fold(data.get('outcome')) == text:
                return True
            if 'won' in data and text in ('won', 'lost'):
                return data['won'] is (text == 'won')
            if 'saved' in data and text in ('saved', 'scored'):
                return data['saved'] is (text == 'saved')
            return False

        return outcome
    raise ArgumentError(f'expected a filter, found {key}:')


def _record(entry_: dict[str, Any], summary: dict[str, Any], registry: list[Any]) -> dict[str, Any]:
    header = entry_['header']
    return {
        'id': entry_['id'],
        'title': summary.get('title') or header.get('title') or entry_['id'],
        'scenario': summary.get('scenario') or header.get('scenario') or '',
        'created': summary.get('created') or '',
        'provenance': summary.get('provenance') or {},
        'teams': summary.get('teams') or [team.get('name') for team in header.get('teams', [])],
        'tags': summary.get('tags') or [],
        'folder': summary.get('folder') or '',
        'context': _captions.context(header, registry),
        'steps_per_second': header.get('steps_per_second') or 10,
    }


def describe(moment: dict[str, Any], context: dict[str, Any]) -> str:
    """Returns a short plain line of a moment, its caption or, for a pass, a change of
    possession and a kick off, a line of the same table."""
    table = _captions.messages()
    made = _captions.caption(moment, context, table)
    if made is not None:
        return _captions.format_message(table, *made)
    data = moment.get('data') or {}
    side = moment.get('team')
    team = _captions._team(table, context, side) if side in (0, 1) else None
    k = moment.get('player')
    known = k is not None and 0 <= k < len(context['players'])
    if moment['kind'] == 'pass' and known:
        own = _captions._team(table, context, context['players'][k]['team'])
        player = _captions._player(table, context, k)
        identifier = {
            'complete': 'describe.pass.complete',
            'intercepted': 'describe.pass.intercepted',
        }.get(data.get('outcome'), 'describe.pass')
        return _captions.format_message(table, identifier, {'player': player, 'team': own})
    if moment['kind'] == 'possession' and team:
        return _captions.format_message(table, 'describe.possession', {'team': team})
    if moment['kind'] == 'restart':
        if data.get('restart') == 'kickoff' and team:
            return _captions.format_message(table, 'describe.restart.kickoff', {'team': team})
        return _captions.format_message(table, 'describe.restart', {})
    return _captions.format_message(table, 'describe.moment', {'kind': moment['kind']})


def _result(item: _Moment) -> dict[str, Any]:
    moment, record = item.moment, item.record
    player = item.player()
    seek = max(0.0, round(moment['t'] - LEAD_SECONDS, 1))
    side = moment.get('team')
    clock = int(moment.get('clock', 0))
    result = {
        'match': record['id'],
        'title': record['title'],
        'scenario': record['scenario'],
        'created': record['created'],
        'source': record['provenance'].get('source'),
        'id': moment['id'],
        'kind': moment['kind'],
        'step': moment['step'],
        't': moment['t'],
        'seek': seek,
        'clock': clock,
        'minute': f'{clock // 60000}:{clock // 1000 % 60:02d}',
        'team': side,
        'team_name': record['context']['teams'][side] if side in (0, 1) else None,
        'player': moment.get('player'),
        'number': player['number'] if player else None,
        'name': (player['name'] or None) if player else None,
        'score': moment.get('score'),
        'text': describe(moment, record['context']),
        'data': moment.get('data') or {},
        'url': f'#match={record["id"]}&t={seek:g}',
    }
    return result


def search(query: str = '', limit: int | None = None) -> dict[str, Any]:
    """Finds the moments of the library that a query names, newest recording first.

    Args:
        query: Words and filters, as `QUERY_HELP` describes, such as `goal team:Greens after:60`.
        limit: The most results to return, by default the query's `limit:` or 50.

    Returns:
        The `query`, the `results` with their recording, moment, time to open Watch at, team,
        player, score and a plain line of `text` each, the `total` number of matches before the
        limit, the number of `recordings` searched and what the index did in `index`.

    Raises:
        ArgumentError: If the query holds an unknown filter or a value out of place.
    """
    terms = _terms(query)
    kinds = []
    tests = []
    words = []
    for negated, key, value in terms:
        if key == 'limit':
            try:
                limit = int(value) if limit is None else limit
            except ValueError:
                raise ArgumentError(f'expected limit: as a whole number, found {value!r}') from None
            continue
        if key is None and fold(value) in _WORDS:
            test = _kind_test(value)
            if negated:
                tests.append(lambda item, test=test: not test(item))
            else:
                kinds.append(test)
            continue
        if key is None:
            words.append((negated, fold(value)))
            continue
        test = _filter(key, value)
        tests.append((lambda item, test=test: not test(item)) if negated else test)
    limit = LIMIT if limit is None else limit
    if not 1 <= limit <= MAXIMUM_LIMIT:
        raise ArgumentError(f'expected a limit from 1 to {MAXIMUM_LIMIT}, found {limit}')
    index = sync()
    summaries = {summary['id']: summary for summary in _library.matches()}
    try:
        from .._registry import teams as _teams

        registry = _teams.teams()
    except Exception:
        registry = []
    with _LOCK:
        entries = [(identifier, held[1]) for identifier, held in _cache(_home.home()).items()]
    found = []
    searched = 0
    for identifier, held in entries:
        summary = summaries.get(identifier)
        if summary is None:
            continue
        searched += 1
        record = _record(held, summary, registry)
        text = fold(
            ' '.join(
                [
                    record['id'],
                    record['title'],
                    record['scenario'].replace('_', ' '),
                    record['folder'],
                    *[str(name) for name in record['teams'] if name],
                    *record['tags'],
                ]
            )
        )
        for moment in held['moments']:
            item = _Moment(moment, record)
            if kinds and not any(test(item) for test in kinds):
                continue
            if not all(test(item) for test in tests):
                continue
            if words:
                name = fold((item.player() or {}).get('name'))
                if not all(((word in text) or word in name) != out for out, word in words):
                    continue
            found.append(item)
    found.sort(
        key=lambda item: (item.record['created'], item.record['id'], -item.moment['t']),
        reverse=True,
    )
    return {
        'query': query,
        'results': [_result(item) for item in found[:limit]],
        'total': len(found),
        'recordings': searched,
        'index': index,
    }


def moments_of(identifier: str) -> dict[str, Any]:
    """Returns the moments of a recording of the library, each with its plain line of text."""
    held = entry(identifier)
    summary = _library.details(identifier)
    try:
        from .._registry import teams as _teams

        registry = _teams.teams()
    except Exception:
        registry = []
    record = _record(held, summary, registry)
    return {
        'match': identifier,
        'version': VERSION,
        'moments': [_result(_Moment(moment, record)) for moment in held['moments']],
    }


def _source(target: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Returns the header and moments of a library recording or of a recording file."""
    if isinstance(target, str) and _library.path_of(target) is not None:
        held = entry(target)
        return held['header'], held['moments']
    path = Path(target)
    if not path.is_file():
        raise ArgumentError(f'expected a recording of the library or a .cjr file, found {target!r}')
    document = _recording.read_header(path)
    return document, _events.moments(document, _recording.frames(path), timing=True)


def _cues(target: str | Path) -> list[dict[str, Any]]:
    """Returns the caption cues of a recording, with their times as the page computes them."""
    header, moments = _source(target)
    return _captions.cues(moments, _captions.context(header))


def captions(target: str | Path) -> list[dict[str, Any]]:
    """Returns the caption cues of a recording of the library or of a recording file.

    The times of the cues are in seconds to the millisecond, as a WebVTT file writes them.
    """
    found = _cues(target)
    for cue in found:
        cue['start'], cue['end'] = round(cue['start'], 3), round(cue['end'], 3)
    return found


def captions_vtt(target: str | Path) -> str:
    """Returns the captions of a recording of the library or of a recording file as WebVTT."""
    return _captions.to_vtt(_cues(target))
