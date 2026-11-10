# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""The clean feed of the mock server, `/feed` and its two routes, with the rules of the real one.

`GET /api/feed/resolve?source=...` answers which recording or live source a feed's source names, and
`GET /api/feed` lists the sources a feed may follow, as `src/cuju/render/_export/feed.py` does on
the real server. The rules repeat those of `_feed.resolve` on the data of the mock, since the mock
depends on nothing of cuju.
"""

import re
import urllib.parse

SOURCES = ('auto', 'live', 'latest', 'tournament', 'queue', 'recording')
_IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')


class FeedError(ValueError):
    """Raised for a source that names nothing, which the server answers with 400."""


def parse_source(text):
    value = str(text or '').strip()
    if not value:
        return 'auto', ''
    head, colon, rest = value.partition(':')
    head, rest = head.lower(), rest.strip()
    if head in SOURCES:
        if head == 'recording' and not rest:
            raise FeedError('expected the identifier of a recording after recording:')
        if head in ('auto', 'latest', 'queue') and colon:
            raise FeedError(f'expected nothing after the source {head}, found {value!r}')
        return head, rest
    if _IDENTIFIER.fullmatch(value):
        return 'recording', value
    raise FeedError(f'expected a source of {", ".join(SOURCES)}, found {value!r}')


def _none(message):
    return {'kind': 'none', 'id': '', 'title': '', 'message': message}


def resolve(source, live, recordings, recording, requests, tournaments, tournament):
    """Returns what a feed's source names now, as `_feed.resolve` of the real server does."""
    kind, name = parse_source(source)
    if kind in ('auto', 'live'):
        sources = sorted(live(), key=lambda s: str(s.get('id', '')), reverse=True)
        if name:
            exact = [s for s in sources if s.get('id') == name]
            sources = exact or [
                s for s in sources if str(s.get('title') or '').casefold() == name.casefold()
            ]
        if sources:
            return {'kind': 'live', 'id': sources[0]['id'], 'title': sources[0].get('title') or ''}
        if kind == 'live':
            return _none('No live source streams now')
    if kind in ('auto', 'latest'):
        entries = recordings()
        if entries:
            return {'kind': 'match', 'id': entries[0]['id'], 'title': entries[0].get('title') or ''}
        return _none('The library holds no recording yet')
    if kind == 'recording':
        entry = recording(name)
        if entry is None:
            return _none(f'The library holds no recording {name}')
        return {'kind': 'match', 'id': name, 'title': entry.get('title') or ''}
    if kind == 'queue':
        done = [e for e in requests() if e.get('state') == 'done' and e.get('match')]
        if done:
            return {'kind': 'match', 'id': done[0]['match'], 'title': '', 'request': done[0]['id']}
        return _none('No requested match has finished yet')
    summaries = tournaments()
    chosen = None
    if name:
        chosen = next((t for t in summaries if t.get('id') == name or t.get('name') == name), None)
    elif summaries:
        chosen = summaries[0]
    if chosen is None:
        return _none('No tournament yet')
    full = tournament(chosen['id']) or {}
    played = [
        m['result']['match']
        for m in full.get('matches', [])
        if isinstance(m.get('result'), dict) and isinstance(m['result'].get('match'), str)
    ]
    if not played:
        return _none(f'{chosen.get("name") or "The tournament"} has no finished match yet')
    return {'kind': 'match', 'id': max(played), 'title': chosen.get('name') or ''}


def targets(base, live):
    """Returns the sources a feed may follow, each with its address on `base`."""
    rows = [{'source': kind} for kind in ('auto', 'latest', 'live', 'queue', 'tournament')]
    rows += [{'source': f'live:{s["id"]}'} for s in live]
    for row in rows:
        query = urllib.parse.urlencode({'source': row['source'], 'size': '1080p'}, safe=':')
        row['url'] = f'{base.rstrip("/")}/feed?{query}'
    return rows
