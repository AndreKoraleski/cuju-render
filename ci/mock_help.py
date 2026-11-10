# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""The routes of the Help page under /api/help for the mock server, as cuju.render._guide.help has
them.

The samples are the two recordings that cuju ships, read from their files, and the starter team,
registered from its folder. The tutorial keeps the lessons a page reports in memory and checks the
others from the mock's library and registry. The diagnostic report and the build of the page carry
the fields of the real ones with values of the mock.
"""

import gzip
import hashlib
import json
import os
import struct
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / 'src' / 'cuju' / 'render' / 'samples'
LESSONS = ROOT / 'src' / 'cuju' / 'render' / 'web' / 'lessons.json'
WEB = ROOT / 'src' / 'cuju' / 'render' / 'web'
TITLES = {
    'sample-5v5': ('Five a side sample', 'A whole match of five a side between built in AIs'),
    'sample-11v11': ('Eleven a side sample', 'A whole match of eleven a side between built in AIs'),
}
TEAM = {
    'id': 'starter-team',
    'name': 'Starter team',
    'format': '11v11',
    'about': 'A Kaggle submission that runs at the ball, carries it to goal and shoots',
}
PLAYED_STEPS = 300

# The functions and stores of the mock server, which bind hands over.
SERVER = {}
STATE = {'page': {}, 'team': None, 'build': None}


def bind(**functions):
    """Takes the library and registry of the mock server that the routes read and change."""
    SERVER.update(functions)


def add_sample(name, path):
    """Stores a shipped sample under its own name, its file kept as it is, as the server does."""
    data = gzip.decompress(path.read_bytes())
    magic = SERVER['magic']
    (length,) = struct.unpack_from('<I', data, len(magic))
    start = len(magic) + 4
    header = json.loads(data[start : start + length])
    store = SERVER['matches_store']
    identifier = SERVER['save_match'](header, [])
    item = store.pop(identifier)
    item['data'] = path.read_bytes()
    item['summary'].update(
        id=name, steps=header['frame_count'], score=None, bytes=path.stat().st_size
    )
    store[name] = item


def lessons():
    return json.loads(LESSONS.read_text(encoding='utf-8'))['lessons']


def recording_names():
    return sorted(path.stem for path in SAMPLES.glob('*.cjr'))


def listing():
    matches = SERVER['matches_store']
    entries = []
    for name in recording_names():
        title, about = TITLES.get(name, (name, 'A recording that cuju ships'))
        item = matches.get(name)
        if item is None:
            state = 'missing'
        elif 'deleted_at' in item['summary']:
            state = 'trash'
        else:
            state = 'library'
        entries.append(
            {
                'id': name,
                'kind': 'recording',
                'title': title,
                'about': about,
                'state': state,
                'target': name if state == 'library' else None,
            }
        )
    known = {team['id'] for team in SERVER['teams']()}
    held = STATE['team'] if STATE['team'] in known else None
    entries.append(
        {
            'id': TEAM['id'],
            'kind': 'team',
            'title': TEAM['name'],
            'about': TEAM['about'],
            'format': TEAM['format'],
            'state': 'library' if held else 'missing',
            'target': held,
        }
    )
    return entries


def add(names):
    every = [*recording_names(), TEAM['id']]
    wanted = every if names is None else names
    unknown = [name for name in wanted if name not in every]
    if unknown:
        return {'error': f'expected samples from {every}, found {unknown}'}, 400
    before = {entry['id']: entry['state'] for entry in listing()}
    with SERVER['lock']:
        for name in wanted:
            if name == TEAM['id']:
                if before[name] == 'missing':
                    main = (SAMPLES / 'teams' / 'starter' / 'main.py').read_bytes()
                    STATE['team'] = SERVER['add_team'](TEAM['name'], 'main.py', main, '11v11')['id']
            elif before[name] == 'trash':
                SERVER['trash'](name, restore=True)
            elif before[name] == 'missing':
                add_sample(name, SAMPLES / f'{name}.cjr')
    after = listing()
    changes = [
        {'id': entry['id'], 'change': 'restored' if before[entry['id']] == 'trash' else 'added'}
        for entry in after
        if entry['id'] in wanted
        and before[entry['id']] != 'library'
        and entry['state'] == 'library'
    ]
    return {'changes': changes, 'samples': after}, 200


def tutorial_state():
    recordings = SERVER['matches']()
    played = any(
        (entry.get('provenance') or {}).get('source') in ('human_game', 'requested_match')
        and isinstance(entry.get('steps'), int)
        and entry['steps'] >= PLAYED_STEPS
        for entry in recordings
    )
    attempted = any(
        (entry.get('provenance') or {}).get('source') == 'challenge' for entry in recordings
    )
    facts = {
        'recording': bool(recordings),
        'match_played': played,
        'team': any(team.get('kind') != 'builtin' for team in SERVER['teams']()),
        'challenge': attempted,
    }
    entries = []
    for lesson in lessons():
        agent = lesson['agent']
        done = lesson['id'] in STATE['page'] or facts.get(agent['check'], False)
        entries.append(
            {
                'id': lesson['id'],
                'title': lesson['title'],
                'page': lesson['page'],
                'check': agent['check'],
                'goal': agent['goal'],
                'steps': agent['steps'],
                'done': bool(done),
            }
        )
    upcoming = next((entry['id'] for entry in entries if not entry['done']), None)
    return {'lessons': entries, 'next': upcoming, 'page': sorted(STATE['page'])}


def build():
    """Returns the build of the page, a digest of the names, sizes and times of its files."""
    digest = hashlib.sha256()
    for path in sorted(WEB.rglob('*')):
        if path.is_file():
            stat = path.stat()
            digest.update(
                f'{path.relative_to(WEB).as_posix()} {stat.st_size} {stat.st_mtime_ns}\n'.encode()
            )
    return digest.hexdigest()[:12]


def doctor():
    """Returns the server's side of the diagnostic report, with the fields of the real one."""
    recordings = SERVER['matches']()
    return {
        'kind': 'server',
        'created': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'versions': {'cuju': 'mock', 'python': 'mock', 'platform': os.name},
        'home': {'path': '~/.cuju/render', 'exists': True, 'writable': True, 'problems': []},
        'folders': {'matches': {'files': len(recordings), 'bytes': 0}},
        'library': {
            'recordings': len(recordings),
            'trash': len(SERVER['matches'](trash=True)),
            'teams': len(SERVER['teams']()) - 1,
        },
        'errors': [],
        'checks': [{'name': 'home', 'ok': True, 'detail': 'the mock keeps everything in memory'}],
    }


def get(parts, query):
    """Answers GET /api/help/..., with a status."""
    if parts == ['samples']:
        return listing(), 200
    if parts == ['tutorial']:
        return tutorial_state(), 200
    if len(parts) == 2 and parts[0] == 'tutorial':
        for entry in tutorial_state()['lessons']:
            if entry['id'] == parts[1]:
                return entry, 200
        return {'error': f'expected a lesson, found {parts[1]!r}'}, 404
    if parts == ['doctor']:
        return doctor(), 200
    if parts == ['app']:
        return {'version': 'mock', 'build': STATE['build'] or build()}, 200
    return {'error': 'no such resource'}, 404


def post(parts, document):
    """Answers POST /api/help/..., with a status."""
    if parts == ['samples']:
        names = document.get('names')
        if names is not None and (
            not isinstance(names, list) or not all(isinstance(name, str) for name in names)
        ):
            return {'error': f'expected names as a list of samples, found {names!r}'}, 400
        return add(names)
    if parts == ['tutorial']:
        if document.get('reset') is True:
            STATE['page'].clear()
            return tutorial_state(), 200
        done = document.get('done')
        known = [lesson['id'] for lesson in lessons()]
        if not isinstance(done, list) or not all(item in known for item in done):
            return {
                'error': f'expected done as a list of lessons from {known}, found {done!r}'
            }, 400
        for item in done:
            STATE['page'].setdefault(item, time.strftime('%Y-%m-%dT%H:%M:%S'))
        return tutorial_state(), 200
    if parts == ['mock-build']:
        # The page check moves the build, as a new version of the page does.
        STATE['build'] = str(document.get('build') or '') or None
        return {'build': STATE['build']}, 200
    return {'error': 'no such resource'}, 404
