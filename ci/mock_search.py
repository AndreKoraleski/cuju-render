# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""The search of moments for the mock server, on the recordings it holds in memory.

It reads the moments with the renderer's own rules, `_events.py`, and words them with its
captions, `_captions.py`, both loaded from their files alone, so the mock still depends on nothing
of cuju's package. The query takes the words of kinds, `team:left` or `team:right`, `match:` and
`limit:`, enough for a page check, and refuses any other filter as the real server does.
"""

import importlib.util
import json
import struct
import threading
from pathlib import Path

RENDER = Path(__file__).resolve().parents[1] / 'src' / 'cuju' / 'render'


def _load(name):
    spec = importlib.util.spec_from_file_location(
        f'mock_{name}', RENDER / '_moments' / f'{name.removeprefix("_")}.py'
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_events = _load('_events')
_captions = _load('_captions')
_KINDS = {
    'goal': 'goal',
    'goals': 'goal',
    'shot': 'shot',
    'shots': 'shot',
    'save': 'save',
    'pass': 'pass',
    'passes': 'pass',
    'tackle': 'tackle',
    'card': 'card',
    'foul': 'foul',
    'offside': 'offside',
    'restart': 'restart',
    'possession': 'possession',
}
_FILTERS = ('kind', 'team', 'player', 'scenario', 'source', 'tournament', 'challenge', 'match')
_FILTERS += ('date', 'since', 'until', 'after', 'before', 'score', 'outcome', 'limit')
_CACHE = {}
# One request reads the moments of a recording, and others wait for them.
_LOCK = threading.Lock()


class QueryError(ValueError):
    """A query that the real server refuses too."""


def _header(data):
    start = len(b'CUJREC1\n') + 4
    (length,) = struct.unpack_from('<I', data, start - 4)
    return json.loads(data[start : start + length])


def _moments(identifier, recording, frames):
    with _LOCK:
        return _read_moments(identifier, recording, frames)


def _read_moments(identifier, recording, frames):
    held = _CACHE.get(identifier)
    if held is None:
        import gzip

        header = _header(gzip.decompress(recording(identifier)))
        held = (header, _events.moments(header, frames(identifier), timing=True))
        _CACHE[identifier] = held
    return held


def _result(identifier, summary, header, moment, context):
    made = _captions.caption(moment, context)
    text = _captions.format_message(_captions.messages(), *made) if made else moment['kind']
    clock = int(moment.get('clock', 0))
    seek = max(0.0, round(moment['t'] - 4.0, 1))
    k = moment.get('player')
    player = context['players'][k] if k is not None else None
    side = moment.get('team')
    return {
        'match': identifier,
        'title': summary['title'],
        'scenario': summary['scenario'],
        'created': summary['created'],
        'source': (summary.get('provenance') or {}).get('source'),
        'id': moment['id'],
        'kind': moment['kind'],
        'step': moment['step'],
        't': moment['t'],
        'seek': seek,
        'clock': clock,
        'minute': f'{clock // 60000}:{clock // 1000 % 60:02d}',
        'team': side,
        'team_name': context['teams'][side] if side in (0, 1) else None,
        'player': k,
        'number': player['number'] if player else None,
        'name': (player['name'] or None) if player else None,
        'score': moment.get('score'),
        'text': text,
        'data': moment.get('data') or {},
        'url': f'#match={identifier}&t={seek:g}',
    }


def search(query, limit, summaries, recording, frames):
    """Returns what `GET /api/search` returns for the recordings of the mock."""
    kinds, team, match = set(), None, None
    for word in (query or '').split():
        key, _, value = word.partition(':')
        if not value:
            if word.lower() in _KINDS:
                kinds.add(_KINDS[word.lower()])
            continue
        if key not in _FILTERS:
            raise QueryError(f'expected a filter of {", ".join(_FILTERS)}, found {key}:')
        if key == 'team':
            team = {'left': 0, 'right': 1}.get(value.lower())
        elif key == 'match':
            match = value
        elif key == 'kind':
            kinds |= {_KINDS.get(name, name) for name in value.split(',')}
        elif key == 'limit':
            limit = int(value)
    found = []
    contexts = {}
    for summary in summaries:
        identifier = summary['id']
        if match is not None and identifier != match:
            continue
        header, moments = _moments(identifier, recording, frames)
        for moment in moments:
            if kinds and moment['kind'] not in kinds:
                continue
            if team is not None and moment.get('team') != team:
                continue
            found.append((identifier, summary, header, moment))
    results = []
    # The lines of text are made for the results shown alone, as the real server makes them.
    for identifier, summary, header, moment in found[: limit or 50]:
        if identifier not in contexts:
            contexts[identifier] = _captions.context(header, [])
        results.append(_result(identifier, summary, header, moment, contexts[identifier]))
    return {
        'query': query,
        'results': results,
        'total': len(found),
        'recordings': len(summaries),
        'index': {'recordings': len(summaries), 'built': 0, 'removed': 0, 'failed': 0},
    }


def captions_vtt(identifier, recording, frames):
    """Returns the captions of a recording of the mock as WebVTT."""
    header, moments = _moments(identifier, recording, frames)
    return _captions.to_vtt(_captions.cues(moments, _captions.context(header, [])))
