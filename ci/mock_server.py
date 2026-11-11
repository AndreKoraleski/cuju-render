# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""A development server for the browser viewer, with the viewer's API on data held in memory.

It serves the web folder of the renderer and answers its API as the real server does, with the
same checks, status codes and errors, but keeps recordings, teams and requests in memory. It
starts with two synthetic recordings from mock_sample.py, runs one live source that replays
synthetic episodes forever at 10 steps per second and greets each viewer with the last 10 seconds,
and plays each requested match as a synthetic one. Nothing here depends on cuju.

A viewer that asks for `?sequence=1` receives numbered frames, as from a source of cuju. Two routes
that only the mock has let a page check test a viewer's reconnection. `POST /api/mock/live/ID/drop`
closes every stream of the source without its end marker and loses the next second of frames.
`POST /api/mock/live/ID/end` closes the source as a process that stops does, so it leaves the
list and every stream ends with its end marker, and a new source takes its place.
`GET /api/mock/samples/NAME` returns a sample match that cuju ships, such as `sample-5v5`, as its
file holds it, so a page check reads a recording of version 2.

Usage:
    python ci/mock_server.py [--port 8765]
Then open http://127.0.0.1:8765/ in a browser.
"""

import argparse
import contextlib
import functools
import gzip
import http.server
import io
import json
import mimetypes
import os
import queue
import re
import secrets
import struct
import sys
import tarfile
import tempfile
import threading
import time
import urllib.parse
import zipfile
import zlib
from pathlib import Path, PurePosixPath

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mock_feed
import mock_grid
import mock_help
import mock_language
import mock_sample
import mock_search
import mock_tournaments

# The sample matches that cuju ships.
SAMPLES = Path(__file__).resolve().parents[1] / 'src' / 'cuju' / 'render' / 'samples'
WEB_ROOT = os.path.realpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src', 'cuju', 'render', 'web')
)
# The scenarios that cuju ships, as the real server lists them.
SCENARIOS = [
    '11_vs_11_competition',
    '11_vs_11_easy_stochastic',
    '11_vs_11_hard_stochastic',
    '11_vs_11_kaggle',
    '11_vs_11_stochastic',
    '1_vs_1_easy',
    '5_vs_5',
    'academy_3_vs_1_with_keeper',
    'academy_corner',
    'academy_counterattack_easy',
    'academy_counterattack_hard',
    'academy_empty_goal',
    'academy_empty_goal_close',
    'academy_pass_and_shoot_with_keeper',
    'academy_run_pass_and_shoot_with_keeper',
    'academy_run_to_score',
    'academy_run_to_score_with_keeper',
    'academy_single_goal_versus_lazy',
    'test_example_multiagent',
]
TYPES = {
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
}
LOOPBACK = ('127.0.0.1', 'localhost', '::1')
MAXIMUM_BODY = 110 * 1024 * 1024
MAXIMUM_SUBMISSION = 100 * 1024 * 1024
MAXIMUM_UNPACKED = 500 * 1024 * 1024
MAXIMUM_FILES = 10000
MAXIMUM_IMAGE = 8 * 1024 * 1024
MAXIMUM_MODEL = 30 * 1024 * 1024
IDENTIFIER = re.compile(r'[a-z0-9][a-z0-9_-]{0,63}')

BUILTIN = 'builtin'
BUILTIN_ENTRY = {'id': BUILTIN, 'name': "GRF's built-in AI", 'kind': 'builtin', 'created': None}
FOLDER_MAGIC = b'CUJDIR1\n'
MAIN = 'main.py'
TEAM_FOLDER = 'cuju-team'
META = f'{TEAM_FOLDER}/team.json'
MODEL = 'model.glb'
PATTERNS = ('plain', 'stripes', 'hoops', 'halves', 'sash', 'checkers')
SKINS = ('grf', 'light', 'tan', 'medium', 'dark')
HAIRS = ('grf', 'bald', 'short01', 'short02', 'medium01', 'long01', 'long02')
HAIR_COLORS = ('grf', 'black', 'brown', 'darkblonde', 'blonde', 'red')
NUMBERS = ('white', 'black', 'secondary')
PARTS = ('primary', 'secondary', 'shorts', 'socks')
FORMATS = {'5v5': 5, '11v11': 11}
IMAGE_SLOTS = (
    'shirt-front',
    'shirt-back',
    'shirt-front-edit',
    'shirt-back-edit',
    'sponsor-1',
    'sponsor-2',
    'sponsor-3',
    'sponsor-4',
    'sponsor-1-edit',
    'sponsor-2-edit',
    'sponsor-3-edit',
    'sponsor-4-edit',
)
IMAGE_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp'}
# The sounds a team may hold, each played when one of its players does that, or its fans sing.
SOUND_SLOTS = ('goal', 'shot', 'pass', 'tackle', 'save', 'kick', 'celebration', 'chant')
MAXIMUM_SOUND = 2 * 1024 * 1024
SOUND_TYPES = {'.ogg': 'audio/ogg', '.mp3': 'audio/mpeg', '.wav': 'audio/wav'}
JOINTS = tuple(mock_sample.NODES[1:])
KIT = {
    'pattern': 'plain',
    'primary': [214, 48, 49],
    'secondary': [255, 255, 255],
    'shorts': [255, 255, 255],
    'socks': [214, 48, 49],
}
GOALKEEPER = {
    'primary': [46, 204, 113],
    'secondary': [20, 20, 20],
    'shorts': [20, 20, 20],
    'socks': [46, 204, 113],
}
BUILTIN_KIT = {
    'pattern': 'plain',
    'primary': [9, 132, 227],
    'secondary': [255, 255, 255],
    'shorts': [9, 132, 227],
    'socks': [255, 255, 255],
}
# The header teams of a live source, which names none of its own.
DEFAULT_TEAMS = [
    {'name': 'Left', 'color': [214, 48, 49], 'secondary': [255, 255, 255]},
    {'name': 'Right', 'color': [9, 132, 227], 'secondary': [255, 255, 255]},
]
CLASH = 120
# The frames of a requested match, as a full match of 3000 steps gives.
MATCH_FRAMES = 3001
# A viewer that joins a live source first receives this many seconds of frames.
BACKLOG_SECONDS = 10
# A simulated drop of a live source loses this many frames, one second of play.
DROP_FRAMES = 10
# The serial that ends a numbered stream, which no frame carries.
END = struct.pack('<Q', 2**64 - 1)
# Member paths are checked against this folder as the real server checks them against its own.
UNPACK_ROOT = Path(tempfile.gettempdir()) / 'cuju-mock-team'


class ArgumentError(ValueError):
    """A request that the real server refuses with its own ArgumentError."""


# The teams folder, each team a mapping of the paths of its files to their bytes.
FOLDERS = {}
# The library, each match its summary and its compressed recording.
MATCHES = {}
LIVE = {}
LOCK = threading.RLock()


def locked(function):
    """Runs a function while it holds the lock of all state."""

    @functools.wraps(function)
    def run(*arguments, **options):
        with LOCK:
            return function(*arguments, **options)

    return run


def new_identifier(prefix):
    return f'{prefix}-{time.strftime("%Y%m%d-%H%M%S")}-{secrets.token_hex(2)}'


def valid_identifier(identifier):
    return bool(IDENTIFIER.fullmatch(identifier))


def player_style(index):
    return {
        'name': '',
        'number': index + 1,
        'skin': 'grf',
        'hair': 'grf',
        'hair_color': 'grf',
        'model': 'team',
        'celebration': 'team',
    }


def default_style(format='11v11', kit=None):
    colors = kit or KIT
    return {
        'model': 'grf',
        'kit': dict(colors),
        'goalkeeper': dict(GOALKEEPER),
        'badge': '',
        'number': 'white',
        'colors': {},
        # The fans wear the kit's colors unless the team picks colors of their own.
        'crowd': {'colors': [list(colors['primary']), list(colors['secondary'])]},
        # The celebrations the page picks from after a goal, empty for every one it knows.
        'celebrations': [],
        # The models on whose backs the page leaves out the shirt numbers.
        'hidden_numbers': [],
        'players': [player_style(index) for index in range(FORMATS[format])],
    }


def color(value, name):
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or not all(
            isinstance(part, int) and not isinstance(part, bool) and 0 <= part <= 255
            for part in value
        )
    ):
        raise ArgumentError(f'expected {name} as three integers from 0 to 255, found {value!r}')
    return [int(part) for part in value]


def choice(value, choices, name):
    if value not in choices:
        raise ArgumentError(f'expected {name} as one of {", ".join(choices)}, found {value!r}')
    return value


def players(value, current, models=()):
    """Returns the roster with the changes of value, a list of player dictionaries."""
    if not isinstance(value, list) or len(value) > len(current):
        raise ArgumentError(f'expected at most {len(current)} player entries, found {value!r}')
    roster = [dict(player) for player in current]
    for index, changes in enumerate(value):
        if not isinstance(changes, dict):
            raise ArgumentError(f'expected player {index} as a dictionary, found {changes!r}')
        for key, entry in changes.items():
            if key == 'name':
                if not isinstance(entry, str) or len(entry) > 24:
                    raise ArgumentError(
                        f'expected a name of at most 24 characters, found {entry!r}'
                    )
                roster[index][key] = entry
            elif key == 'number':
                if not isinstance(entry, int) or not 0 <= entry <= 99:
                    raise ArgumentError(f'expected a shirt number from 0 to 99, found {entry!r}')
                roster[index][key] = entry
            elif key == 'skin':
                roster[index][key] = choice(entry, SKINS, 'the skin')
            elif key == 'hair':
                roster[index][key] = choice(entry, HAIRS, 'the hair')
            elif key == 'hair_color':
                roster[index][key] = choice(entry, HAIR_COLORS, 'the hair color')
            elif key == 'celebration':
                # team picks among the team's celebrations, any other value is the player's own.
                roster[index][key] = celebration(entry)
            elif key == 'model':
                # team follows the team's model, any other value gives the player one of its own.
                roster[index][key] = choice(
                    entry, ('team', 'grf', 'custom', *models), 'the player model'
                )
            else:
                raise ArgumentError(f'expected an entry of a player, found {key!r}')
    return roster


HEX = re.compile(r'#[0-9a-f]{6}')
# A celebration is named by the page, such as knee_slide, or clip and an animation of a model.
CELEBRATION = re.compile(r'[a-z0-9_]{1,40}(:[A-Za-z0-9_. -]{1,60})?')


def celebration(value):
    if not isinstance(value, str) or not CELEBRATION.fullmatch(value):
        raise ArgumentError(f'expected the name of a celebration, found {value!r}')
    return value


# A model's colors to replace, at most this many per model.
MAXIMUM_RECOLORS = 32


def recolors(value, models):
    """Returns the colors that replace others on each model, as #rrggbb pairs by model."""
    if not isinstance(value, dict):
        raise ArgumentError(f'expected the colors as a dictionary by model, found {value!r}')
    result = {}
    for model, pairs in value.items():
        choice(model, models, 'the model of the colors')
        if not isinstance(pairs, dict) or len(pairs) > MAXIMUM_RECOLORS:
            raise ArgumentError(f'expected at most {MAXIMUM_RECOLORS} colors for {model!r}')
        result[model] = {}
        for old, new in pairs.items():
            if not (
                isinstance(old, str)
                and isinstance(new, str)
                and HEX.fullmatch(old.lower())
                and HEX.fullmatch(new.lower())
            ):
                raise ArgumentError(f'expected colors as #rrggbb, found {old!r} and {new!r}')
            result[model][old.lower()] = new.lower()
    return result


def style(changes, base, models=()):
    """Returns the complete style base with changes applied, refusing any unknown entry."""
    result = json.loads(json.dumps(base))
    changes = changes or {}
    if not isinstance(changes, dict):
        raise ArgumentError(f'expected a style as a dictionary, found {changes!r}')
    for key, value in changes.items():
        if key in ('kit', 'goalkeeper'):
            if not isinstance(value, dict):
                raise ArgumentError(f'expected {key} as a dictionary, found {value!r}')
            for part, entry in value.items():
                if key == 'kit' and part == 'pattern':
                    result[key][part] = choice(entry, PATTERNS, 'the pattern')
                elif part in PARTS:
                    result[key][part] = color(entry, f'{key} {part}')
                else:
                    raise ArgumentError(f'expected a part of {key}, found {part!r}')
        elif key == 'model':
            result[key] = choice(value, ('grf', 'custom', *models), 'the model')
        elif key == 'number':
            result[key] = choice(value, NUMBERS, 'the numbers')
        elif key == 'badge':
            if not isinstance(value, str) or len(value) > 3:
                raise ArgumentError(
                    f'expected a badge of at most three characters, found {value!r}'
                )
            result[key] = value
        elif key == 'players':
            result[key] = players(value, result[key], models)
        elif key == 'colors':
            result[key] = recolors(value, ('custom', *models))
        elif key == 'celebrations':
            if not isinstance(value, list) or len(value) > 32:
                raise ArgumentError('expected a list of at most 32 celebrations')
            result[key] = [celebration(item) for item in value]
        elif key == 'hidden_numbers':
            if not isinstance(value, list) or len(value) > 64:
                raise ArgumentError('expected hidden_numbers as a list of model names')
            if not all(isinstance(model, str) and len(model) <= 64 for model in value):
                raise ArgumentError('expected hidden_numbers as a list of model names')
            known = ('custom', *models)
            result[key] = list(dict.fromkeys(model for model in value if model in known))
        elif key == 'crowd':
            if not isinstance(value, dict) or set(value) - {'colors'}:
                raise ArgumentError(f'expected the crowd as {{"colors": [...]}}, found {value!r}')
            colors = value.get('colors', result[key]['colors'])
            if not isinstance(colors, list) or not 1 <= len(colors) <= 4:
                raise ArgumentError('expected one to four colors of the fans')
            result[key] = {'colors': [color(entry, 'a color of the fans') for entry in colors]}
        else:
            raise ArgumentError(f'expected an entry of a style, found {key!r}')
    return result


def resize(style_, format):
    size = FORMATS[format]
    roster = style_['players'][:size]
    roster += [player_style(index) for index in range(len(roster), size)]
    return {**style_, 'players': roster}


def known(saved, base):
    return {key: value for key, value in saved.items() if key in base and key != 'players'}


def shipped_models():
    """Returns the description of every model in the web assets, each json with a glb beside it."""
    folder = Path(WEB_ROOT) / 'assets' / 'models'
    models = []
    for path in sorted(folder.glob('*.json')):
        with contextlib.suppress(OSError, ValueError):
            description = json.loads(path.read_text())
            if path.with_suffix('.glb').is_file():
                description['url'] = f'assets/models/{path.stem}.glb'
                models.append(description)
    return models


def model_names():
    return tuple(model['id'] for model in shipped_models())


def image_file(identifier, slot):
    """Returns the path of the file of an image slot of a team, whatever its extension, or None."""
    for path in FOLDERS.get(identifier, {}):
        name = path[len(TEAM_FOLDER) + 1 :]
        if (
            path.startswith(TEAM_FOLDER + '/')
            and '/' not in name
            and name.startswith(slot + '.')
            and PurePosixPath(name).suffix in ('.png', '.jpg', '.webp', '.json')
        ):
            return path
    return None


def sound_file(identifier, slot):
    """Returns the path of the file of a sound slot of a team, whatever its extension, or None."""
    for path in FOLDERS.get(identifier, {}):
        name = path[len(TEAM_FOLDER) + 1 :]
        if (
            path.startswith(TEAM_FOLDER + '/')
            and '/' not in name
            and name.startswith(f'sound-{slot}.')
            and PurePosixPath(name).suffix in SOUND_TYPES
        ):
            return path
    return None


def sound_suffix(data):
    if data.startswith(b'OggS'):
        return '.ogg'
    if data[:4] == b'RIFF' and data[8:12] == b'WAVE':
        return '.wav'
    # MP3, a tag of ID3 or the sync bits of a first frame.
    if data.startswith(b'ID3') or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return '.mp3'
    raise ArgumentError('expected an Ogg, MP3 or WAV sound')


@locked
def set_sound(identifier, slot, data):
    entry(identifier)
    choice(slot, SOUND_SLOTS, 'the sound slot')
    if len(data) > MAXIMUM_SOUND:
        raise ArgumentError(f'expected a sound of at most 2 MB, found {len(data)} bytes')
    suffix = sound_suffix(data)
    old = sound_file(identifier, slot)
    files = FOLDERS.setdefault(identifier, {})
    files[f'{TEAM_FOLDER}/sound-{slot}{suffix}'] = data
    if old is not None and old != f'{TEAM_FOLDER}/sound-{slot}{suffix}':
        del files[old]
    return entry(identifier)


@locked
def sound_path(identifier, slot):
    if slot not in SOUND_SLOTS:
        return None
    if identifier != BUILTIN and not valid_identifier(identifier):
        return None
    return sound_file(identifier, slot)


@locked
def remove_sound(identifier, slot):
    path = sound_path(identifier, slot)
    if path is None:
        return False
    del FOLDERS[identifier][path]
    return True


def complete(entry, kit=None):
    """Returns a stored entry with its format, style, model and images filled and checked."""
    entry = dict(entry)
    if entry.get('format') not in FORMATS:
        entry['format'] = '11v11'
    base = default_style(entry['format'], kit)
    saved = entry.get('style') or {}
    try:
        entry['style'] = resize(
            style(saved, {**base, **known(saved, base)}, model_names()), entry['format']
        )
    except ArgumentError:
        entry['style'] = base
    entry.setdefault('model', None)
    entry['images'] = [slot for slot in IMAGE_SLOTS if image_file(entry['id'], slot) is not None]
    entry['sounds'] = [slot for slot in SOUND_SLOTS if sound_file(entry['id'], slot) is not None]
    entry['clips'] = clip_listing(entry['id'])
    return entry


def builtin():
    entry = dict(BUILTIN_ENTRY)
    with contextlib.suppress(OSError, ValueError):
        meta = FOLDERS.get(BUILTIN, {}).get(META)
        if meta is None:
            raise FileNotFoundError(META)
        saved = json.loads(meta)
        entry.update(
            {key: saved[key] for key in ('name', 'style', 'model', 'format') if key in saved}
        )
    # The default name travels as a label, which the page shows in its language, as the server's.
    if entry.get('name') == BUILTIN_ENTRY['name']:
        entry.update(name_id='server.names.builtin', name_values={})
    return complete(entry, BUILTIN_KIT)


@locked
def teams():
    """Returns every team, the builtin team first, then the submissions from newest to oldest."""
    entries = []
    for identifier in sorted(FOLDERS):
        meta = FOLDERS[identifier].get(META)
        if identifier == BUILTIN or meta is None:
            continue
        try:
            entry = complete(json.loads(meta))
        except (OSError, ValueError, KeyError):
            continue
        entries.append(entry)
    entries.sort(key=lambda entry: entry.get('created') or '', reverse=True)
    return [builtin(), *entries]


@locked
def entry(identifier):
    for team in teams():
        if team['id'] == identifier:
            return team
    raise ArgumentError(f'expected a team of the registry, found {identifier!r}')


def write(identifier, current):
    stored = {
        key: value
        for key, value in current.items()
        if key not in ('images', 'sounds', 'clips', 'name_id', 'name_values')
    }
    FOLDERS.setdefault(identifier, {})[META] = json.dumps(stored).encode()


@locked
def update(identifier, name=None, changes=None, format=None):
    current = entry(identifier)
    if name is not None:
        name = str(name).strip()[:80]
        if not name:
            raise ArgumentError('expected a team name with at least one character')
        current['name'] = name
        current.pop('name_id', None)
        current.pop('name_values', None)
        if identifier == BUILTIN and name == BUILTIN_ENTRY['name']:
            current.update(name_id='server.names.builtin', name_values={})
    if format is not None:
        current['format'] = choice(format, tuple(FORMATS), 'the format')
        current['style'] = resize(current['style'], current['format'])
    current['style'] = style(changes, current['style'], model_names())
    roster = current['style']['players']
    chosen = {current['style']['model'], *(player['model'] for player in roster)}
    if 'custom' in chosen and model_path(identifier) is None:
        raise ArgumentError('expected an uploaded model before choosing the custom model')
    write(identifier, current)
    return current


def image_suffix(slot, data):
    if slot.endswith('-edit'):
        try:
            json.loads(data)
        except ValueError as error:
            raise ArgumentError(
                f'expected the JSON document of the editor, found {error}'
            ) from error
        return '.json'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if data.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return '.webp'
    raise ArgumentError('expected a PNG, JPEG or WebP image')


@locked
def set_image(identifier, slot, data):
    entry(identifier)
    choice(slot, IMAGE_SLOTS, 'the image slot')
    if len(data) > MAXIMUM_IMAGE:
        raise ArgumentError(f'expected an image of at most 8 MB, found {len(data)} bytes')
    suffix = image_suffix(slot, data)
    old = image_file(identifier, slot)
    files = FOLDERS.setdefault(identifier, {})
    files[f'{TEAM_FOLDER}/{slot}{suffix}'] = data
    if old is not None and old != f'{TEAM_FOLDER}/{slot}{suffix}':
        del files[old]
    return entry(identifier)


@locked
def image_path(identifier, slot):
    if slot not in IMAGE_SLOTS:
        return None
    if identifier != BUILTIN and not valid_identifier(identifier):
        return None
    return image_file(identifier, slot)


@locked
def image(identifier, slot):
    """Returns the path and bytes of a team's image slot, or None."""
    path = image_path(identifier, slot)
    return None if path is None else (path, FOLDERS[identifier][path])


@locked
def remove_image(identifier, slot):
    path = image_path(identifier, slot)
    if path is None:
        return False
    del FOLDERS[identifier][path]
    return True


def skin_joints(data):
    """Returns the names of the joints of every skin of a binary glTF 2.0 file."""
    if len(data) < 20 or data[:4] != b'glTF':
        raise ArgumentError('expected a binary glTF file, .glb, found other bytes')
    version, length = struct.unpack_from('<II', data, 4)
    chunk_length, chunk_type = struct.unpack_from('<II', data, 12)
    if version != 2 or length > len(data) or chunk_type != 0x4E4F534A:
        raise ArgumentError('expected a binary glTF 2.0 file with its JSON chunk first')
    try:
        document = json.loads(data[20 : 20 + chunk_length])
    except ValueError as error:
        raise ArgumentError(f'expected the JSON chunk of a glTF file, found {error}') from error
    if not isinstance(document, dict):
        raise ArgumentError('expected the JSON chunk of a glTF file to hold an object')
    for kind in ('buffers', 'images'):
        for item in document.get(kind) or []:
            uri = item.get('uri') if isinstance(item, dict) else None
            if isinstance(uri, str) and not uri.startswith('data:'):
                raise ArgumentError(f'expected a self-contained model, found a link to {uri!r}')
    nodes = document.get('nodes') or []
    skins = document.get('skins') or []
    if not skins:
        raise ArgumentError('expected a rigged model, a glTF file with a skin, found none')
    names = set()
    for skin in skins:
        joints = skin.get('joints', []) if isinstance(skin, dict) else []
        for joint in joints:
            if (
                isinstance(joint, int)
                and 0 <= joint < len(nodes)
                and isinstance(nodes[joint], dict)
            ):
                names.add(str(nodes[joint].get('name', '')))
    return names


@locked
def set_model(identifier, data, joints):
    current = entry(identifier)
    if len(data) > MAXIMUM_MODEL:
        raise ArgumentError(f'expected a model of at most 30 MB, found {len(data)} bytes')
    bones = skin_joints(data)
    if not isinstance(joints, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in joints.items()
    ):
        raise ArgumentError(f'expected the joints as names of bones by joint, found {joints!r}')
    if 'body' not in joints:
        raise ArgumentError('expected a bone for the joint body, the pelvis, which every rig has')
    unknown = [joint for joint in joints if joint not in (*JOINTS, 'player')]
    if unknown:
        raise ArgumentError(f"expected joints of GRF's skeleton, found {', '.join(unknown)}")
    absent = [bone for bone in joints.values() if bone not in bones]
    if absent:
        raise ArgumentError(f'expected bones of the model, found {", ".join(map(str, absent))}')
    FOLDERS.setdefault(identifier, {})[f'{TEAM_FOLDER}/{MODEL}'] = data
    current['model'] = {
        'joints': {key: str(value) for key, value in joints.items()},
        'bytes': len(data),
    }
    current['style']['model'] = 'custom'
    write(identifier, current)
    return current


@locked
def remove_model(identifier):
    current = entry(identifier)
    had = FOLDERS.get(identifier, {}).pop(f'{TEAM_FOLDER}/{MODEL}', None) is not None
    current['model'] = None
    if current['style']['model'] == 'custom':
        current['style']['model'] = 'grf'
    write(identifier, current)
    return had


@locked
def model_path(identifier):
    if identifier != BUILTIN and not valid_identifier(identifier):
        return None
    return FOLDERS.get(identifier, {}).get(f'{TEAM_FOLDER}/{MODEL}')


# The celebration clips of a team, as _clips.py keeps them, beside a JSON file of each.
CLIPS = 'clips'
CLIP_NAME = re.compile(r'[a-z0-9_]{1,40}')
CLIP_DEVICES = re.compile(r'(con|prn|aux|nul|com[0-9]|lpt[0-9])', re.IGNORECASE)
MAXIMUM_CLIP = 10 * 1024 * 1024
MAXIMUM_TEAM_CLIPS = 40 * 1024 * 1024
MAXIMUM_CLIP_COUNT = 16


def clip_key(name, suffix='.glb'):
    return f'{TEAM_FOLDER}/{CLIPS}/{name}{suffix}'


def check_clip(data):
    """Returns the animation names and bones of a clip, or raises ArgumentError."""
    if len(data) > MAXIMUM_CLIP:
        raise ArgumentError(f'expected a clip of at most 10 MB, found {len(data)} bytes')
    bones = skin_joints(data)
    if struct.unpack_from('<I', data, 8)[0] != len(data):
        raise ArgumentError('expected a binary glTF file of the length its header gives')
    (size,) = struct.unpack_from('<I', data, 12)
    document = json.loads(data[20 : 20 + size])
    animations = document.get('animations') or []
    if not isinstance(animations, list) or not animations:
        raise ArgumentError('expected a clip with at least one animation, found none')
    names = [
        (item.get('name') if isinstance(item, dict) and isinstance(item.get('name'), str) else '')
        or f'Animation {index + 1}'
        for index, item in enumerate(animations)
    ]
    return names, bones


def check_clip_name(name):
    if not CLIP_NAME.fullmatch(name or '') or CLIP_DEVICES.fullmatch(name):
        raise ArgumentError(f'expected a clip name of lowercase letters, found {name!r}')
    return name


def check_clip_joints(joints, bones):
    if not joints:
        return {}
    if not isinstance(joints, dict) or 'body' not in joints:
        raise ArgumentError('expected a bone for the joint body, the pelvis, which every rig has')
    if any(key not in (*JOINTS, 'player') or value not in bones for key, value in joints.items()):
        raise ArgumentError('expected joints of GRF and bones of the clip')
    return dict(joints)


def clip_listing(identifier):
    files = FOLDERS.get(identifier, {})
    out = []
    for path in sorted(files):
        if path.startswith(f'{TEAM_FOLDER}/{CLIPS}/') and path.endswith('.glb'):
            name = path[len(f'{TEAM_FOLDER}/{CLIPS}/') : -4]
            meta = json.loads(files.get(clip_key(name, '.json'), b'{}'))
            out.append(
                {
                    'name': name,
                    'bytes': len(files[path]),
                    'animations': meta.get('animations', []),
                    'joints': meta.get('joints', {}),
                }
            )
    return out


@locked
def set_clip(identifier, name, data, joints):
    entry(identifier)
    check_clip_name(name)
    animations, bones = check_clip(data)
    mapping = check_clip_joints(joints, bones)
    files = FOLDERS.setdefault(identifier, {})
    others = [item for item in clip_listing(identifier) if item['name'] != name]
    if len(others) >= MAXIMUM_CLIP_COUNT:
        raise ArgumentError(f'expected at most {MAXIMUM_CLIP_COUNT} clips for a team')
    if sum(item['bytes'] for item in others) + len(data) > MAXIMUM_TEAM_CLIPS:
        raise ArgumentError('expected at most 40 MB of clips for a team')
    files[clip_key(name)] = data
    files[clip_key(name, '.json')] = json.dumps(
        {'animations': animations, 'joints': mapping}
    ).encode()
    return entry(identifier)


@locked
def set_clip_joints(identifier, name, joints):
    data = clip_bytes(identifier, name)
    if data is None:
        raise ArgumentError(f'expected a clip of the team, found {name!r}')
    animations, bones = check_clip(data)
    FOLDERS[identifier][clip_key(name, '.json')] = json.dumps(
        {'animations': animations, 'joints': check_clip_joints(joints, bones)}
    ).encode()
    return entry(identifier)


@locked
def clip_bytes(identifier, name):
    if identifier != BUILTIN and not valid_identifier(identifier):
        return None
    with contextlib.suppress(ArgumentError):
        return FOLDERS.get(identifier, {}).get(clip_key(check_clip_name(name)))
    return None


@locked
def remove_clip(identifier, name):
    if clip_bytes(identifier, name) is None:
        return False
    files = FOLDERS[identifier]
    del files[clip_key(name)]
    files.pop(clip_key(name, '.json'), None)
    current = entry(identifier)
    gone = f'upload:{name}.'
    current['style']['celebrations'] = [
        item for item in current['style']['celebrations'] if not item.startswith(gone)
    ]
    for player in current['style']['players']:
        if player.get('celebration', '').startswith(gone):
            player['celebration'] = 'team'
    write(identifier, current)
    return True


def import_clips(files):
    """Keeps the clips of an exported team that pass the checks of an upload."""
    prefix = f'{TEAM_FOLDER}/{CLIPS}/'
    for path in [path for path in files if path.startswith(prefix) and path.endswith('.glb')]:
        stem = path[len(prefix) : -4]
        try:
            check_clip_name(stem)
            animations, bones = check_clip(files[path])
        except (ArgumentError, ValueError):
            del files[path]
            continue
        try:
            meta = json.loads(files.get(clip_key(stem, '.json'), b'{}'))
            mapping = check_clip_joints(meta.get('joints'), bones)
        except (ArgumentError, ValueError, AttributeError):
            mapping = {}
        files[clip_key(stem, '.json')] = json.dumps(
            {'animations': animations, 'joints': mapping}
        ).encode()
    for path in [path for path in files if path.startswith(prefix)]:
        sibling = path.endswith('.json') and path[:-5] + '.glb' in files
        if not (path.endswith('.glb') or sibling):
            del files[path]


def header_team(identifier):
    team = entry(identifier)
    kit = team['style']['kit']
    return {
        'id': team['id'],
        'name': team['name'],
        'format': team['format'],
        'color': kit['primary'],
        'secondary': kit['secondary'],
        'style': team['style'],
    }


@locked
def match_teams(left, right):
    """Returns the header teams of a match, the right one in its away kit on a clash of shirts."""
    sides = [header_team(left), header_team(right)]
    first, second = sides[0]['style']['kit'], sides[1]['style']['kit']
    distance = sum((a - b) ** 2 for a, b in zip(first['primary'], second['primary'], strict=True))
    if distance < CLASH**2:
        kit = dict(second)
        kit['primary'], kit['secondary'] = second['secondary'], second['primary']
        kit['shorts'], kit['socks'] = second['socks'], second['shorts']
        if sum((a - b) ** 2 for a, b in zip(first['primary'], kit['primary'], strict=True)) < (
            CLASH**2
        ):
            kit['primary'] = [255 - value for value in first['primary']]
        sides[1] = {
            **sides[1],
            'color': kit['primary'],
            'secondary': kit['secondary'],
            'style': {**sides[1]['style'], 'kit': kit},
            'away': True,
        }
    return sides


def check_member(name):
    """Returns an archive member's path, refusing one that could land outside the team's folder."""
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or any(part in ('', '.', '..') or any(c in part for c in ':\\\0') for part in path.parts)
    ):
        raise ArgumentError(f'expected archive members inside the archive, found {name!r}')
    return path


def inside(path):
    """Returns the key of a member path, refusing one that resolves outside the folder."""
    destination = UNPACK_ROOT.joinpath(*path.parts)
    if not destination.resolve().is_relative_to(UNPACK_ROOT.resolve()):
        raise ArgumentError(f'expected archive members inside the archive, found {str(path)!r}')
    return '/'.join(path.parts)


def check_unpacked(count, size):
    if count > MAXIMUM_FILES or size > MAXIMUM_UNPACKED:
        raise ArgumentError('expected an archive of at most 10,000 files and 500 MB unpacked')


def unbundle(data, files):
    """Reads the files of a folder bundle, dropping a single top folder above main.py."""
    if len(data) < len(FOLDER_MAGIC) + 4:
        raise ArgumentError('expected the files of a submission folder, found too few bytes')
    (length,) = struct.unpack_from('<I', data, len(FOLDER_MAGIC))
    start = len(FOLDER_MAGIC) + 4
    try:
        index = json.loads(data[start : start + length])
    except ValueError as error:
        raise ArgumentError(f'expected the index of a submission folder, found {error}') from error
    if not isinstance(index, list) or len(index) > MAXIMUM_FILES:
        raise ArgumentError('expected the index of a submission folder, a list of its files')
    paths = [check_member(str(item['path'])) for item in index]
    tops = {path.parts[0] for path in paths if len(path.parts) > 1}
    if PurePosixPath(MAIN) not in paths and len(tops) == 1 and all(len(p.parts) > 1 for p in paths):
        paths = [PurePosixPath(*path.parts[1:]) for path in paths]
    position = start + length
    for path, item in zip(paths, index, strict=True):
        size = int(item['size'])
        if size < 0 or position + size > len(data):
            raise ArgumentError('expected the files that the index of the folder lists')
        files[inside(path)] = data[position : position + size]
        position += size


def extract(data, filename, files):
    """Reads a submission into files, a folder bundle, a Python file or an archive."""
    lower = filename.lower()
    if data.startswith(FOLDER_MAGIC):
        unbundle(data, files)
    elif lower.endswith('.py'):
        files[MAIN] = data
    elif lower.endswith(('.tar.gz', '.tgz', '.tar')):
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            members = archive.getmembers()
            check_unpacked(len(members), sum(member.size for member in members))
            for member in members:
                inside(check_member(member.name))
                if not (member.isfile() or member.isdir()):
                    raise ArgumentError(f'expected plain files in the archive, found {member.name}')
            for member in members:
                if member.isfile():
                    files[inside(check_member(member.name))] = archive.extractfile(member).read()
    elif lower.endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            check_unpacked(len(members), sum(member.file_size for member in members))
            for member in members:
                inside(check_member(member.filename))
            for member in members:
                if not member.is_dir():
                    files[inside(check_member(member.filename))] = archive.read(member)
    else:
        raise ArgumentError(
            f'expected a submission folder, a .py file or a .tar.gz or .zip archive, found '
            f'{filename!r}'
        )
    if MAIN not in files:
        raise ArgumentError(f'expected {MAIN} at the top of the submission, as Kaggle requires')


def import_team(files, entry, name_given):
    """Takes the format, style, images and model of an exported team into entry."""
    prefix = TEAM_FOLDER + '/'
    if not any(path.startswith(prefix) for path in files):
        return
    saved = {}
    with contextlib.suppress(OSError, ValueError):
        saved = json.loads(files.get(META, b''))
    if not isinstance(saved, dict):
        saved = {}
    if saved.get('format') in FORMATS:
        entry['format'] = saved['format']
    with contextlib.suppress(ArgumentError, TypeError, KeyError, AttributeError):
        base = default_style(entry['format'])
        entry['style'] = resize(
            style(known(saved.get('style') or {}, base), base, model_names()), entry['format']
        )
        if isinstance((saved.get('style') or {}).get('players'), list):
            entry['style']['players'] = players(
                saved['style']['players'][: FORMATS[entry['format']]],
                entry['style']['players'],
                model_names(),
            )
    if not name_given and isinstance(saved.get('name'), str) and saved['name'].strip():
        entry['name'] = saved['name'].strip()[:80]
    children = {path[len(prefix) :].split('/')[0] for path in files if path.startswith(prefix)}
    for name in children:
        if name in ('team.json', MODEL, CLIPS, PRESENTATION_FOLDER):
            continue
        key = prefix + name
        child = PurePosixPath(name)
        data = files.get(key)
        valid = False
        with contextlib.suppress(ArgumentError):
            if child.stem.startswith('sound-'):
                valid = (
                    data is not None
                    and child.stem[len('sound-') :] in SOUND_SLOTS
                    and len(data) <= MAXIMUM_SOUND
                    and sound_suffix(data) == child.suffix
                )
            else:
                valid = (
                    data is not None
                    and child.stem in IMAGE_SLOTS
                    and len(data) <= MAXIMUM_IMAGE
                    and image_suffix(child.stem, data) == child.suffix
                )
        if not valid:
            for path in [path for path in files if path == key or path.startswith(key + '/')]:
                del files[path]
    import_clips(files)
    import_presentation(files)
    joints = (
        (saved.get('model') or {}).get('joints') if isinstance(saved.get('model'), dict) else None
    )
    try:
        data = files.get(prefix + MODEL)
        if data is None:
            raise FileNotFoundError(MODEL)
        bones = skin_joints(data)
        if len(data) > MAXIMUM_MODEL or not isinstance(joints, dict) or 'body' not in joints:
            raise ArgumentError('expected a model of the limits with a joint for body')
        if not all(isinstance(bone, str) and bone in bones for bone in joints.values()):
            raise ArgumentError('expected bones of the model')
        entry['model'] = {
            'joints': {
                str(key): value for key, value in joints.items() if key in (*JOINTS, 'player')
            },
            'bytes': len(data),
        }
    except (OSError, ArgumentError, AttributeError):
        files.pop(prefix + MODEL, None)
        entry['model'] = None
        if entry['style'].get('model') == 'custom':
            entry['style']['model'] = 'grf'


# A team presentation package, the folder presentation with its manifest and files, kept as the
# real server keeps them. The mock reads the manifest as it is, and the page fills what it lacks.
PRESENTATION_FOLDER = 'presentation'
# The registered team whose presentation each side draws, the viewer's choice of section Q11.
PRESENTATION_SIDES = {'left': None, 'right': None}
PRESENTATION_MANIFEST = 'presentation.json'
PRESENTATION_PART = re.compile(r'[a-z0-9][a-z0-9_.-]{0,59}')
PRESENTATION_TYPES = {
    '.glb': 'model/gltf-binary',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.webp': 'image/webp',
    '.ktx2': 'image/ktx2',
    '.ogg': 'audio/ogg',
    '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav',
    '.js': 'text/javascript',
    '.json': 'application/json',
    '.glsl': 'text/plain',
    '.wasm': 'application/wasm',
}
SANDBOX_POLICY = (
    'sandbox allow-scripts; '
    "default-src 'none'; script-src '{hash}' blob: 'wasm-unsafe-eval'; worker-src blob:; "
    "connect-src 'none'; img-src blob: data:; frame-ancestors 'self'; base-uri 'none'; "
    "form-action 'none'"
)


def presentation_path(name):
    """Returns whether a path inside a package is one the real server keeps."""
    parts = name.split('/')
    return (
        0 < len(parts) <= 4
        and all(PRESENTATION_PART.fullmatch(part) and '..' not in part for part in parts)
        and PurePosixPath(name).suffix in PRESENTATION_TYPES
    )


def import_presentation(files):
    """Keeps the files of a package of the right paths and sizes."""
    prefix = f'{TEAM_FOLDER}/{PRESENTATION_FOLDER}/'
    for path in [path for path in files if path.startswith(prefix)]:
        if not presentation_path(path[len(prefix) :]) or len(files[path]) > 30 * 1024 * 1024:
            del files[path]


def presentation(identifier):
    """Returns what the page reads of a team's package."""
    files = FOLDERS.get(identifier, {})
    prefix = f'{TEAM_FOLDER}/{PRESENTATION_FOLDER}/'
    out = {
        'manifest': None,
        'warnings': [],
        'files': [],
        'developer': False,
        'contract': '1.1',
        'features': [],
        'missing': [],
    }
    data = files.get(prefix + PRESENTATION_MANIFEST)
    if data is None:
        return out
    out['files'] = sorted(
        path[len(prefix) :]
        for path in files
        if path.startswith(prefix) and path != prefix + PRESENTATION_MANIFEST
    )
    with contextlib.suppress(ValueError):
        document = json.loads(data)
        if isinstance(document, dict) and document.get('contract') in ('1.0', '1.1'):
            out['manifest'] = document
    return out


def presentation_type(identifier, name):
    """Returns the type a file of a package goes out with, a module as text but for the worklet."""
    kind = PRESENTATION_TYPES[PurePosixPath(name).suffix]
    if kind != 'text/javascript':
        return kind
    manifest = presentation(identifier)['manifest'] or {}
    audio = manifest.get('audio') if isinstance(manifest.get('audio'), dict) else {}
    return kind if audio.get('worklet') == name else 'text/plain; charset=utf-8'


def presentation_file(identifier, name):
    """Returns the bytes of a file of a team's package, or None."""
    if not presentation_path(name):
        return None
    return FOLDERS.get(identifier, {}).get(f'{TEAM_FOLDER}/{PRESENTATION_FOLDER}/{name}')


def page_digests(worker):
    """Returns the service worker with the SHA-256 of every file of the page, as the server does."""
    import hashlib

    digests = {}
    for path in sorted(Path(WEB_ROOT).rglob('*')):
        if path.is_file():
            name = path.relative_to(WEB_ROOT).as_posix()
            data = path.read_bytes()
            if name in ('index.html', 'feed.html'):
                data = mock_language.inline(data)
            digests[name] = hashlib.sha256(data).hexdigest()
    filled = json.dumps(digests, sort_keys=True, separators=(',', ':')).encode()
    return worker.replace(b'const DIGESTS = null;', b'const DIGESTS = ' + filled + b';', 1)


def sandbox_page():
    """Returns the sandbox page of team workers and its policy, as the real server makes them."""
    import base64
    import hashlib

    path = Path(WEB_ROOT) / 'js' / 'presentation' / 'sandbox.js'
    script = path.read_text(encoding='utf-8')
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    page = f'<!doctype html><meta charset="utf-8"><title>sandbox</title><script>{script}</script>'
    return page.encode(), SANDBOX_POLICY.format(hash=f'sha256-{digest}')


@locked
def add(name, filename, data, format='11v11'):
    """Stores a Kaggle submission as a new team and returns its entry."""
    if len(data) > MAXIMUM_SUBMISSION:
        raise ArgumentError(f'expected a submission of at most 100 MB, found {len(data)} bytes')
    choice(format, tuple(FORMATS), 'the format')
    name_given = bool(name and name.strip())
    name = (name or Path(filename).stem or 'team').strip()[:80]
    identifier = new_identifier('t')
    while identifier in FOLDERS:
        identifier = new_identifier('t')
    files = {}
    extract(data, filename, files)
    FOLDERS[identifier] = files
    entry = {
        'id': identifier,
        'name': name,
        'kind': 'kaggle',
        'created': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'format': format,
        'style': default_style(format),
        'model': None,
    }
    import_team(files, entry, name_given)
    completed = complete(entry)
    write(identifier, completed)
    return completed


@locked
def export(identifier):
    """Returns a file name and the bytes of a zip of a team's folder, its team.json first."""
    team = entry(identifier)
    stored = {key: value for key, value in team.items() if key not in ('images', 'sounds', 'clips')}
    files = FOLDERS.get(identifier, {})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(META, json.dumps(stored))
        for path in sorted(files, key=lambda path: Path(*path.split('/'))):
            if path != META and not path.endswith('.part') and '__pycache__' not in path.split('/'):
                archive.writestr(path, files[path])
    safe = ''.join(character if character.isalnum() else '-' for character in team['name'])
    return f'{safe.strip("-") or "team"}.zip', buffer.getvalue()


@locked
def duplicate(identifier):
    """Copies a submission team with its files, controls and look, and returns the copy."""
    team = entry(identifier)
    if team['kind'] == 'builtin':
        raise ArgumentError('expected a registered submission to duplicate, found the built-in AI')
    filename, data = export(identifier)
    return add(f'{team["name"]} copy', filename, data, team['format'])


@locked
def remove(identifier):
    if identifier == BUILTIN:
        FOLDERS.pop(BUILTIN, None)
        return True
    if not valid_identifier(identifier) or identifier not in FOLDERS:
        return False
    del FOLDERS[identifier]
    return True


@locked
def save_match(header, frames):
    """Stores a recording in the library and returns its identifier, which no other one holds."""
    identifier = new_identifier('m')
    while identifier in MATCHES:
        identifier = new_identifier('m')
    data = gzip.compress(mock_sample.encode_recording(header, frames), 6)
    score = list(struct.unpack_from('<2i', frames[-1], 8)) if frames else [0, 0]
    MATCHES[identifier] = {
        'summary': {
            'id': identifier,
            'title': header['title'],
            'scenario': header['scenario'],
            'teams': [team['name'] for team in header['teams']],
            'score': score,
            'steps': len(frames),
            'created': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'bytes': len(data),
            'folder': '',
            'provenance': header.get('provenance') or {},
            'favorite': False,
            'tags': [],
            'notes': '',
        },
        'data': data,
    }
    return identifier


@locked
def matches(trash=False, group=None):
    """Returns the summaries of the library, or of the Trash, newest first, or of one group."""
    entries = [
        dict(item['summary'])
        for item in MATCHES.values()
        if ('deleted_at' in item['summary']) == trash
        and (group is None or (item['summary'].get('group') or {}).get('id') == group)
    ]
    entries.sort(key=lambda entry: entry.get('created') or '', reverse=True)
    if group is not None:
        entries.sort(key=lambda entry: entry['group'].get('attempt', 0))
    return entries


@locked
def trash_group(group, restore=False):
    """Moves every recording of a group to the Trash, or back, and returns their identifiers."""
    return [entry['id'] for entry in matches(restore, group) if trash(entry['id'], restore)]


def label(message, text, **values):
    """Returns a label of the server, its message id, English text and values."""
    return {'id': message, 'text': text, 'values': values}


def named(field, value):
    """Returns the fields of a name, with its message beside the text for a label."""
    if isinstance(value, dict):
        return {
            field: value['text'],
            f'{field}_id': value['id'],
            f'{field}_values': value['values'],
        }
    return {field: value}


def run_group(challenge, identifier, competitor, state, played, outcome=None):
    """Returns the group of a run's recordings, as cuju.render._playing.challenges keeps it."""
    count = challenge['attempts']
    shown = competitor['text'] if isinstance(competitor, dict) else competitor
    title = label(
        'server.names.challenge_run',
        f'{challenge["title"]}, {shown}',
        challenge={'kind': 'challenge', 'name': challenge['id'], 'text': challenge['title']},
        competitor=competitor,
    )
    if outcome is None:
        result = label(
            f'server.names.run_{state}',
            f'{state} after {played} of {count}',
            played=str(played),
            attempts=str(count),
        )
    else:
        value = outcome['value']
        if challenge['measure'] == 'margin':
            text = f'{value:+d}' if value else '0'
            shown_value = label('server.names.run_margin', f'goal difference {text}', value=text)
        else:
            shown_value = label(
                'server.names.run_attempts',
                f'{value} of {count}',
                value=str(value),
                attempts=str(count),
            )
        medal = outcome['medal']
        if medal:
            result = label(
                'server.names.run_medal',
                f'{shown_value["text"]}, {medal} medal',
                value=shown_value,
                medal=label(f'server.names.medal_{medal}', medal),
            )
        else:
            result = label(
                'server.names.run_no_medal', f'{shown_value["text"]}, no medal', value=shown_value
            )
    return {
        'id': identifier,
        'kind': 'challenge',
        'challenge': challenge['id'],
        **named('title', title),
        **named('competitor', competitor),
        **named('result', result),
        'state': state,
        'attempts': count,
        'value': None if outcome is None else outcome['value'],
        'seconds': None if outcome is None else outcome['seconds'],
        'medal': None if outcome is None else outcome['medal'],
        'practice': False,
    }


@locked
def keep_group(group, recordings):
    """Writes a group into the summary of each recording of its attempts."""
    for attempt, identifier in enumerate(recordings):
        if identifier in MATCHES:
            MATCHES[identifier]['summary']['group'] = {**group, 'attempt': attempt}


def end_person_run(challenge, name, recordings, keep, state, outcome):
    """Groups the recordings of a person's run, or removes them, and returns the group."""
    named_ = [match for match in recordings if match is not None]
    if not keep:
        with LOCK:
            for match in named_:
                MATCHES.pop(match, None)
        return None
    if not named_:
        return None
    group = new_identifier('g')
    keep_group(run_group(challenge, group, name, state, len(recordings), outcome), recordings)
    return group


def seed_group():
    """Adds a run of three attempts of One on one by the built-in AI, a day old, as one group."""
    challenge = find_challenge('one_on_one')
    builtin = label('server.names.builtin', "GRF's built-in AI")
    outcome = {'value': 3, 'seconds': 9.5, 'medal': 'silver'}
    group = new_identifier('g')
    day = time.strftime('%Y-%m-%dT%H:%M', time.localtime(time.time() - 86400))
    recordings = []
    for attempt in range(challenge['attempts']):
        header, frames = mock_sample.generate_frames(
            5, 40, 10 + attempt, ('Built-in AI', 'Built-in AI')
        )
        header['provenance'] = {
            'source': 'challenge',
            'challenge': 'one_on_one',
            'attempt': attempt,
            'seed': challenge['seeds'][attempt],
        }
        identifier = save_match(header, frames)
        title = label(
            'server.names.challenge_attempt',
            f'One on one, attempt {attempt + 1}, {builtin["text"]}',
            challenge={'kind': 'challenge', 'name': 'one_on_one', 'text': 'One on one'},
            attempt=str(attempt + 1),
            competitor=builtin,
        )
        MATCHES[identifier]['summary'].update(
            scenario='1_vs_1_easy', created=f'{day}:{10 + attempt:02d}', **named('title', title)
        )
        recordings.append(identifier)
    keep_group(run_group(challenge, group, builtin, 'done', 3, outcome), recordings)


@locked
def recording(identifier, include_trash=False):
    """Returns the bytes of a recording, of the Trash too when include_trash is true."""
    if not valid_identifier(identifier) or identifier not in MATCHES:
        return None
    if not include_trash and 'deleted_at' in MATCHES[identifier]['summary']:
        return None
    return MATCHES[identifier]['data']


@locked
def details(identifier):
    if recording(identifier) is None:
        raise ArgumentError(f'expected a recording of the library, found {identifier!r}')
    return dict(MATCHES[identifier]['summary'])


@locked
def trash(identifier, restore=False):
    """Moves a recording to the Trash, or restores it, and returns whether it existed."""
    if recording(identifier, include_trash=True) is None:
        return False
    summary = MATCHES[identifier]['summary']
    if ('deleted_at' in summary) != restore:
        return False
    if restore:
        del summary['deleted_at']
    else:
        summary['deleted_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    return True


@locked
def purge(identifier):
    """Deletes a recording of the Trash for good, and returns whether there was one."""
    if recording(identifier, include_trash=True) is None:
        return False
    if 'deleted_at' not in MATCHES[identifier]['summary']:
        return False
    del MATCHES[identifier]
    return True


def folder_path(folder):
    if not isinstance(folder, str):
        raise ArgumentError(f'expected a folder as text, found {folder!r}')
    parts = [part.strip() for part in folder.replace('\\', '/').split('/') if part.strip()]
    if any(part in ('.', '..') or len(part) > 64 for part in parts) or len(parts) > 8:
        raise ArgumentError(
            f'expected a folder of at most 8 names of 64 characters, found {folder!r}'
        )
    return '/'.join(parts)


@locked
def update_match(identifier, title=None, folder=None, favorite=None, tags=None, notes=None):
    if recording(identifier) is None:
        raise ArgumentError(f'expected a recording of the library, found {identifier!r}')
    summary = dict(MATCHES[identifier]['summary'])
    if favorite is not None:
        if not isinstance(favorite, bool):
            raise ArgumentError(f'expected favorite as true or false, found {favorite!r}')
        summary['favorite'] = favorite
    if tags is not None:
        if (
            not isinstance(tags, list)
            or len(tags) > 20
            or not all(isinstance(tag, str) and 0 < len(tag.strip()) <= 40 for tag in tags)
        ):
            raise ArgumentError('expected up to twenty tags, each of one to forty characters')
        summary['tags'] = list(dict.fromkeys(tag.strip() for tag in tags))
    if notes is not None:
        if not isinstance(notes, str) or len(notes) > 10000:
            raise ArgumentError('expected notes as text of at most ten thousand characters')
        summary['notes'] = notes
    if title is not None:
        title = str(title).strip()[:120]
        if not title:
            raise ArgumentError('expected a title with at least one character')
        summary['title'] = title
    if folder is not None:
        summary['folder'] = folder_path(folder)
    summary.setdefault('folder', '')
    MATCHES[identifier]['summary'] = summary
    return summary


def scenario_size(scenario):
    for size in (5, 11):
        if scenario.startswith(f'{size}_vs_{size}'):
            return size
    return None


def check_scenario(sides, scenario):
    """Refuses a scenario whose size differs from the format of a submitted team."""
    size = scenario_size(scenario)
    for team in sides:
        if team['kind'] != 'builtin' and size != FORMATS[team['format']]:
            raise ArgumentError(
                f'expected a scenario of {team["format"]} for {team["name"]}, found {scenario}'
            )


class Requests:
    """The queue of requested matches, played one at a time as synthetic matches."""

    def __init__(self):
        self.lock = threading.Lock()
        self.entries_ = []
        self.wake = threading.Event()
        threading.Thread(target=self.run, daemon=True).start()

    def add(self, left, right, scenario, seed):
        if scenario not in SCENARIOS:
            raise ArgumentError(f'expected a shipped scenario, found {scenario!r}')
        check_scenario([entry(left), entry(right)], scenario)
        item = {
            'id': new_identifier('r'),
            'left': left,
            'right': right,
            'scenario': scenario,
            'seed': seed,
            'state': 'queued',
            'progress': 0.0,
            'match': None,
            'error': None,
        }
        with self.lock:
            self.entries_.append(item)
        self.wake.set()
        return dict(item)

    def entries(self):
        with self.lock:
            return [dict(item) for item in reversed(self.entries_)]

    def cancel(self, identifier):
        with self.lock:
            item = next((item for item in self.entries_ if item['id'] == identifier), None)
            if item is None or item['state'] not in ('queued', 'running'):
                return False
            item['state'], item['error'] = 'failed', 'cancelled'
        return True

    def run(self):
        while True:
            self.wake.wait()
            self.wake.clear()
            while True:
                with self.lock:
                    queued = [item for item in self.entries_ if item['state'] == 'queued']
                if not queued:
                    break
                self.play(queued[0])

    def play(self, item):
        with self.lock:
            if item['state'] != 'queued':
                return
            item['state'] = 'running'
        try:
            teams_ = [entry(item['left']), entry(item['right'])]
            check_scenario(teams_, item['scenario'])
            names = [team['name'] for team in teams_]
            sides = match_teams(item['left'], item['right'])
        except ArgumentError as error:
            with self.lock:
                item['state'], item['error'] = 'failed', f'ArgumentError: {error}'
            return
        for k in range(10):
            time.sleep(0.3)
            with self.lock:
                if item['state'] != 'running':
                    return
                item['progress'] = (k + 1) / 12
        per_team = 5 if scenario_size(item['scenario']) == 5 else 11
        seed = 7 if item['seed'] is None else item['seed']
        header, frames = mock_sample.generate_frames(
            per_team, MATCH_FRAMES, seed, tuple(names), sides
        )
        header['title'] = f'{names[0]} against {names[1]}'
        header['scenario'] = item['scenario']
        with self.lock:
            if item['state'] != 'running':
                return
        match = save_match(header, frames)
        with self.lock:
            item['progress'], item['match'], item['state'] = 1.0, match, 'done'


def with_flags(frame, flags):
    return frame[:28] + struct.pack('<i', flags) + frame[32:]


class LiveSource:
    """Replays synthetic episodes forever, each frame published at real time.

    A batch resets itself after an episode, so the step that ends one shows the next kick off with
    flags 2, and the frame of the reset before the first step is never shown. Every frame has a
    serial, and the source keeps its newest frames with their serials. A drop closes every stream
    and skips the frames of the next second, so a viewer that reconnects sees them as a gap.
    """

    def __init__(self, per_team):
        self.id = new_identifier('live')
        self.per_team = per_team
        self.scenario = '11_vs_11_stochastic' if per_team == 11 else '5_vs_5'
        self.title = f'{self.scenario}, environment 0, process {os.getpid()}'
        self.cond = threading.Condition()
        self.header = None
        # The newest frames as pairs of serial and bytes, and the serial of the next frame.
        self.frames = []
        self.serial = 0
        self.skip = 0
        # Counts of the drops and ends so far, which every stream compares with its own.
        self.drops = 0
        self.ends = 0
        # The serial of the first frame that the latest drop loses.
        self.dropped = 0
        self.closed = False
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        seed = 10
        while not self.closed:
            header, frames = mock_sample.generate_frames(
                self.per_team, 600, seed, ('Left', 'Right'), DEFAULT_TEAMS
            )
            header['title'] = self.title
            header['scenario'] = self.scenario
            header['frame_count'] = None
            for index, frame in enumerate(frames[:-1]):
                if index == 0:
                    if self.header is None:
                        continue
                    frame = with_flags(frame, 2)
                time.sleep(1.0 / mock_sample.STEPS_PER_SECOND)
                if self.closed:
                    return
                with self.cond:
                    serial = self.serial
                    self.serial += 1
                    if self.skip:
                        self.skip -= 1
                        continue
                    if self.header is None:
                        self.header = header
                    self.frames.append((serial, frame))
                    self.frames = self.frames[-BACKLOG_SECONDS * mock_sample.STEPS_PER_SECOND :]
                    self.cond.notify_all()
            seed += 1

    def backlog(self):
        """Returns the newest frames that follow each other step by step, under the lock."""
        frames = self.frames
        start = len(frames) - 1
        while start > 0:
            if (
                struct.unpack_from('<i', frames[start][1])[0]
                != struct.unpack_from('<i', frames[start - 1][1])[0] + 1
            ):
                break
            start -= 1
        return frames[max(0, start) :]

    def drop(self):
        """Closes every stream without its end marker and loses the frames of the next second."""
        with self.cond:
            self.drops += 1
            self.dropped = self.serial
            self.skip = DROP_FRAMES
            self.cond.notify_all()

    def end(self):
        """Stops the source and ends every stream with its end marker."""
        with self.cond:
            self.closed = True
            self.ends += 1
            self.cond.notify_all()

    def describe(self):
        return {
            'id': self.id,
            'title': self.title,
            'scenario': self.scenario,
            'environment': 0,
            'environment_count': 1,
            'generation': 0,
        }


# Challenges, as cuju.render._playing.challenges keeps them. The catalog copies part of the real
# one, and the mock scores each attempt from the frames of its recording by the same rules, without
# the checks of provenance, since its recordings are synthetic. A run of a team plays no match, it
# advances one attempt every 0.3 seconds and lands on the board with a value drawn from the seeds.
CHALLENGES = [
    {
        'id': cid,
        'title': title,
        'scenario': scenario,
        'ability': [None, None],
        'attempts': attempts,
        'measure': measure,
        'targets': list(targets),
        'limit': limit,
        'goal': goal,
        'played_ability': list(played),
        'seeds': [(zlib.crc32(cid.encode()) + 7919 * i) % 2**31 for i in range(attempts)],
    }
    for cid, title, scenario, attempts, measure, targets, limit, goal, played in (
        (
            'empty_goal_close',
            'Empty goal from close range',
            'academy_empty_goal_close',
            5,
            'within',
            (3, 4, 5),
            3.0,
            'Score into the empty goal within 3 seconds of play in each attempt.',
            (1.0, 0.6),
        ),
        (
            'corner',
            'Corner',
            'academy_corner',
            5,
            'scored',
            (1, 2, 4),
            None,
            'Score from the corner before the ball goes out or the clock runs down.',
            (1.0, 0.6),
        ),
        (
            'one_on_one',
            'One on one',
            '1_vs_1_easy',
            3,
            'margin',
            (1, 3, 6),
            None,
            'Outscore a single opponent over three short matches, goals for minus against.',
            (0.0, 0.0),
        ),
    )
]
BOARDS = {challenge['id']: [] for challenge in CHALLENGES}
# The catalog of achievements, as cuju.render._playing.achievements lists it, with no team's earned.
ACHIEVEMENTS = [
    {'id': aid, 'name': name, 'glyph': glyph, 'description': description}
    for aid, name, glyph, description in (
        ('off_the_mark', 'Off the mark', 'OM', 'Score a goal.'),
        ('hat_trick', 'Hat trick', 'HT', 'One player scores three goals or more in one recording.'),
        ('clean_sheet', 'Clean sheet', 'CS', 'Finish a full match without conceding.'),
        ('podium', 'On the podium', 'MD', 'Win a medal in a challenge.'),
        ('gold_standard', 'Gold standard', 'AU', 'Win a gold medal in a challenge.'),
    )
]
JOBS = []
MEDALS = ('bronze', 'silver', 'gold')
SHORT = ('rank', 'kind', 'name', 'team', 'value', 'seconds', 'medal')


def find_challenge(identifier):
    """Returns the challenge of an identifier, or raises KeyError."""
    challenge = next((item for item in CHALLENGES if item['id'] == identifier), None)
    if challenge is None:
        raise KeyError(identifier)
    return challenge


def challenge_medal(challenge, value):
    won = None
    for name, target in zip(MEDALS, challenge['targets'], strict=True):
        if value >= target:
            won = name
    return won


def score_frames(frames):
    """Scores the frames of one attempt for the left side, as score_attempt does."""
    if not frames:
        return {'finished': False, 'goals': [0, 0], 'scored': False, 'seconds': None}
    first = struct.unpack_from('<2i', frames[0], 8)
    last = struct.unpack_from('<2i', frames[-1], 8)
    finished = bool(struct.unpack_from('<i', frames[-1], 28)[0] & 1)
    goals = max(0, last[0] - first[0]) if finished else 0
    seconds = None
    if goals:
        seconds = next(
            round(i / 10, 1)
            for i, frame in enumerate(frames)
            if struct.unpack_from('<2i', frame, 8)[0] > first[0]
        )
    against = max(0, last[1] - first[1])
    return {
        'finished': finished,
        'goals': [goals, against],
        'scored': goals > 0,
        'seconds': seconds,
    }


def attempt_result(challenge, index, match, scored):
    counts = scored['scored'] and (
        challenge['measure'] != 'within' or scored['seconds'] <= challenge['limit']
    )
    return {
        'index': index,
        'seed': challenge['seeds'][index],
        'match': match,
        **scored,
        'counts': counts,
    }


def run_totals(challenge, results):
    if challenge['measure'] == 'margin':
        value = sum(r['goals'][0] - r['goals'][1] for r in results)
        counted = [r for r in results if r['scored']]
    else:
        counted = [r for r in results if r['counts']]
        value = len(counted)
    seconds = round(sum(r['seconds'] for r in counted), 1)
    return {'value': value, 'seconds': seconds, 'medal': challenge_medal(challenge, value)}


def competitor(entry):
    if entry['kind'] == 'agent' and entry['team']:
        return ('team', entry['team'])
    return (entry['kind'], entry['name'])


def rank_key(entry):
    return (-entry['value'], entry['seconds'], entry['time'])


@locked
def record_run(identifier, kind, name, team, totals, results):
    """Keeps each competitor's best run on the board, as record does."""
    board = BOARDS[identifier]
    entry = {
        'kind': kind,
        'name': name,
        'team': team,
        **totals,
        'time': time.time(),
        'attempts': results,
        'cuju_version': 'mock',
    }
    who = competitor(entry)
    before = next((e for e in board if competitor(e) == who), None)
    improved = before is None or rank_key(entry) < rank_key(before)
    if improved:
        kept = [e for e in board if competitor(e) != who] + [entry]
        board[:] = sorted(kept, key=rank_key)[:100]
    rank = next((i for i, e in enumerate(board, 1) if competitor(e) == who), None)
    best = next((e for e in board if competitor(e) == who), entry)
    return {
        'personal_best': {**best, 'rank': rank},
        'rank': rank,
        'improved': improved,
        'first': before is None,
    }


def recording_frames(identifier):
    item = MATCHES.get(identifier)
    if item is None or 'deleted_at' in item['summary']:
        raise ArgumentError(f'expected a recording of the library, found {identifier!r}')
    data = gzip.decompress(item['data'])
    start = len(mock_sample.MAGIC) + 4
    (length,) = struct.unpack_from('<I', data, len(mock_sample.MAGIC))
    header = json.loads(data[start : start + length])
    size = header['frame_bytes']
    body = data[start + length :]
    return [body[i : i + size] for i in range(0, len(body) - size + 1, size)]


def board_entries(identifier):
    return [{**entry, 'rank': rank} for rank, entry in enumerate(BOARDS[identifier], 1)]


def challenge_list(person):
    listed = []
    for challenge in CHALLENGES:
        entries = board_entries(challenge['id'])
        mine = next((e for e in entries if competitor(e) == ('person', person)), None)
        board = {
            'entries': len(entries),
            'people': sum(e['kind'] == 'person' for e in entries),
            'agents': sum(e['kind'] == 'agent' for e in entries),
            'top': [{k: e[k] for k in SHORT} for e in entries[:3]],
            'mine': {k: mine[k] for k in SHORT} if mine else None,
        }
        listed.append({**challenge, 'board': board})
    return listed


def person_run(identifier, person, matches, keep=True):
    challenge = find_challenge(identifier)
    if not isinstance(person, str) or not 0 < len(person.strip()) <= 40:
        raise ArgumentError(f'expected a name of 1 to 40 characters, found {person!r}')
    if not isinstance(matches, list) or len(matches) != challenge['attempts']:
        raise ArgumentError(f'expected the {challenge["attempts"]} recordings of the attempts')
    named = [m for m in matches if m is not None]
    if len(set(named)) != len(named):
        raise ArgumentError('expected a distinct recording for each attempt')
    results = []
    for index, match in enumerate(matches):
        missed = {'finished': False, 'goals': [0, 0], 'scored': False, 'seconds': None}
        scored = missed if match is None else score_frames(recording_frames(match))
        results.append(attempt_result(challenge, index, match, scored))
    totals = run_totals(challenge, results)
    name = person.strip()
    outcome = {
        'challenge': identifier,
        'kind': 'person',
        'name': name,
        'team': None,
        'practice': False,
        'attempts': results,
        **totals,
    }
    outcome.update(record_run(identifier, 'person', name, None, totals, results))
    medal = totals['medal']
    outcome['achievements'] = (['podium'] if medal else []) + (
        ['gold_standard'] * (medal == 'gold')
    )
    if not keep:
        outcome['attempts'] = [{**result, 'match': None} for result in results]
    outcome['group'] = end_person_run(challenge, name, matches, keep, 'done', outcome)
    return outcome


@locked
def advance_jobs():
    """Moves each mock run on by the time since its start, one attempt every 0.3 seconds."""
    for job in JOBS:
        if job['state'] not in ('queued', 'running'):
            continue
        challenge = find_challenge(job['challenge'])
        done = min(job['attempts'], int((time.time() - job['created']) / 0.3))
        job['state'] = 'running'
        while len(job['results']) < done:
            index = len(job['results'])
            seconds = round(1.5 + (challenge['seeds'][index] % 20) / 10, 1)
            scored = {'finished': True, 'goals': [1, 0], 'scored': True, 'seconds': seconds}
            job['results'] = [*job['results'], attempt_result(challenge, index, None, scored)]
        job['progress'] = len(job['results']) / job['attempts']
        if len(job['results']) < job['attempts']:
            continue
        totals = run_totals(challenge, job['results'])
        practice = job['attempts'] < challenge['attempts']
        result = {
            'challenge': challenge['id'],
            'kind': 'agent',
            'name': job['name'],
            'team': job['team'],
            'practice': practice,
            'attempts': job['results'],
            **totals,
            'achievements': [],
        }
        if practice:
            result.update(medal=None, rank=None, personal_best=None, improved=False)
        else:
            board = record_run(
                challenge['id'], 'agent', job['name'], job['team'], totals, job['results']
            )
            result.update(board)
        job.update(state='done', result=result)


def challenges_get(parts, query):
    """Answers GET /api/challenges/..., with a status."""
    if not parts:
        return challenge_list(query.get('person') or None), 200
    if parts == ['jobs']:
        advance_jobs()
        return [dict(job) for job in reversed(JOBS)], 200
    if parts[0] not in BOARDS:
        return {'error': f'no challenge {parts[0]!r}'}, 404
    if len(parts) == 1:
        return {'challenge': find_challenge(parts[0]), 'entries': board_entries(parts[0])}, 200
    if parts[1:] == ['score']:
        challenge = find_challenge(parts[0])
        index = int(query.get('attempt', ''))
        if not 0 <= index < challenge['attempts']:
            raise ArgumentError(f'expected an attempt from 0 to {challenge["attempts"] - 1}')
        try:
            frames = recording_frames(query.get('match', ''))
        except ArgumentError as error:
            return {'error': str(error)}, 404
        result = attempt_result(challenge, index, query['match'], score_frames(frames))
        return {'challenge': parts[0], 'result': result, 'problem': None}, 200
    return {'error': 'no such resource'}, 404


def challenges_post(parts, document):
    """Answers POST /api/challenges/ID/runs, with a status."""
    if len(parts) != 2 or parts[1] not in ('runs', 'leave') or parts[0] not in BOARDS:
        return {'error': 'no such resource'}, 404
    keep = document.get('keep_recordings', True)
    if not isinstance(keep, bool):
        raise ArgumentError(f'expected keep_recordings as true or false, found {keep!r}')
    if parts[1] == 'leave':
        played = document.get('matches')
        if not isinstance(played, list) or not played:
            raise ArgumentError('expected the recordings of the attempts played')
        challenge = find_challenge(parts[0])
        group = end_person_run(challenge, str(document.get('person')), played, keep, 'left', None)
        removed = [] if keep else [match for match in played if match is not None]
        return {'challenge': parts[0], 'group': group, 'removed': removed}, 200
    if 'person' in document:
        return person_run(parts[0], document['person'], document.get('matches'), keep), 201
    challenge = find_challenge(parts[0])
    team = entry(str(document.get('team')))
    attempts = document.get('attempts')
    if attempts is not None and not (
        isinstance(attempts, int) and 1 <= attempts <= challenge['attempts']
    ):
        raise ArgumentError(f'expected from 1 to {challenge["attempts"]} attempts')
    job = {
        'id': new_identifier('j'),
        'challenge': parts[0],
        'team': team['id'],
        'name': team['name'],
        'attempts': attempts or challenge['attempts'],
        'state': 'queued',
        'progress': 0.0,
        'results': [],
        'result': None,
        'error': None,
        'created': time.time(),
    }
    with LOCK:
        JOBS.append(job)
    return dict(job), 201


def challenges_delete(parts):
    """Answers DELETE /api/challenges/jobs/ID, with a status."""
    with LOCK:
        wanted = parts[1] if len(parts) == 2 and parts[0] == 'jobs' else None
        job = next((j for j in JOBS if j['id'] == wanted), None)
        if job is None or job['state'] not in ('queued', 'running'):
            return {'error': 'no such run'}, 404
        job.update(state='failed', error='cancelled')
    return {'cancelled': job['id']}, 200


def make_handler(requests):
    """Returns the request handler, the real server's checks and routes on the data above."""
    allowed_hosts = set(LOOPBACK)
    cups = mock_tournaments.MockTournaments(
        teams, SCENARIOS, lambda: (matches() or [{'id': None}])[-1]['id']
    )

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = 'cuju-render-mock'
        # Each answer goes out at once, as the server sends it.
        disable_nagle_algorithm = True

        def end_headers(self):
            # Every window of the server stays apart from a window of another site that opened it.
            self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
            super().end_headers()

        def _tournaments(self, method):
            """Answers the tournament routes from the mock's tournaments."""
            parts, _ = self._route()
            document = self._document() if method == 'POST' else {}
            status, body = cups.respond(method, parts[2:], document)
            if status == 204:
                self.send_response(204)
                self.end_headers()
            else:
                self._json(body, status)

        def _allowed(self):
            named = self.headers.get('Host') or ''
            if urllib.parse.urlsplit('//' + named).hostname not in allowed_hosts:
                self._error(403, 'expected a request to this server by its loopback address')
                return False
            origin = self.headers.get('Origin')
            if origin is not None and self.command != 'GET' and origin != f'http://{named}':
                self._error(403, 'expected a request from the page of this server')
                return False
            try:
                length = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                self._error(400, 'expected a Content-Length of digits')
                return False
            if length > MAXIMUM_BODY:
                self._error(413, 'expected a request body of at most 110 MB')
                return False
            return True

        def log_message(self, fmt, *arguments):
            sys.stderr.write(f'{self.address_string()} {fmt % arguments}\n')

        def _handle(self, method):
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

        def _json(self, value, status=200):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status, message):
            self._json({'error': message}, status)

        def _bytes(self, data, kind, no_store=False, policy=None):
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            if no_store:
                self.send_header('Cache-Control', 'no-store')
            if policy:
                self.send_header('Content-Security-Policy', policy)
            self.end_headers()
            self.wfile.write(data)

        def _body(self):
            length = int(self.headers.get('Content-Length') or 0)
            return self.rfile.read(length) if length > 0 else b''

        def _document(self):
            document = json.loads(self._body() or b'{}')
            if not isinstance(document, dict):
                raise ArgumentError('expected a JSON object')
            return document

        def _route(self):
            parsed = urllib.parse.urlsplit(self.path)
            parts = [urllib.parse.unquote(part) for part in parsed.path.split('/') if part]
            query = dict(urllib.parse.parse_qsl(parsed.query))
            return parts, query

        def do_GET(self):
            self._handle(self._get)

        def _get(self):
            parts, query = self._route()
            try:
                if parts == ['sandbox', 'presentation']:
                    page, policy = sandbox_page()
                    self._bytes(page, 'text/html; charset=utf-8', no_store=True, policy=policy)
                elif parts == ['feed']:
                    self._static(['feed.html'])
                elif parts == ['api', 'feed']:
                    base = f'http://{self.headers.get("Host")}/'
                    self._json(mock_feed.targets(base, [s.describe() for s in LIVE.values()]))
                elif parts == ['api', 'feed', 'resolve']:
                    self._feed(query.get('source', 'auto'))
                elif parts[:1] != ['api']:
                    self._static(parts)
                elif parts[:2] == ['api', 'tournaments']:
                    self._tournaments('GET')
                elif parts in (['api', 'matches'], ['api', 'trash']):
                    self._json(matches(parts[1] == 'trash', query.get('group') or None))
                elif parts == ['api', 'search']:
                    try:
                        limit = int(query['limit']) if query.get('limit') else None
                        found = mock_search.search(
                            query.get('q', ''), limit, matches(), recording, recording_frames
                        )
                    except ValueError as error:
                        self._error(400, str(error))
                    else:
                        self._json(found)
                elif len(parts) == 4 and parts[1] == 'matches' and parts[3] == 'captions.vtt':
                    if recording(parts[2]) is None:
                        self._error(404, 'no such match')
                    else:
                        text = mock_search.captions_vtt(parts[2], recording, recording_frames)
                        self._bytes(text.encode(), 'text/vtt; charset=utf-8', no_store=True)
                elif len(parts) == 4 and parts[1] == 'matches' and parts[3] == 'details':
                    try:
                        self._json(details(parts[2]))
                    except ArgumentError as error:
                        self._error(404, str(error))
                elif len(parts) == 3 and parts[1] == 'matches':
                    data = recording(parts[2])
                    if data is None:
                        self._error(404, 'no such match')
                    else:
                        self._bytes(data, 'application/octet-stream')
                elif len(parts) == 4 and parts[1] == 'live' and mock_grid.owns(parts[2]):
                    mock_grid.get(self, parts[2], parts[3], self._route()[1])
                elif parts == ['api', 'live']:
                    self._json([source.describe() for source in list(LIVE.values())])
                elif len(parts) == 4 and parts[1] == 'live' and parts[3] == 'stream':
                    self._relay(parts[2], query.get('sequence') == '1')
                elif parts == ['api', 'scenarios']:
                    self._json(SCENARIOS)
                elif parts[:2] == ['api', 'challenges']:
                    self._json(*challenges_get(parts[2:], query))
                elif parts == ['api', 'achievements']:
                    self._json({'catalog': ACHIEVEMENTS, 'teams': {}})
                elif parts[:2] == ['api', 'help']:
                    self._json(*mock_help.get(parts[2:], query))
                elif parts[:2] == ['api', 'languages']:
                    self._json(*mock_language.get(parts[2:]))
                elif parts == ['api', 'teams']:
                    self._json(teams())
                elif len(parts) == 4 and parts[1] == 'teams' and parts[3] == 'model':
                    data = model_path(parts[2])
                    if data is None:
                        self._error(404, 'no such model')
                    else:
                        self._bytes(data, 'model/gltf-binary', no_store=True)
                elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'images':
                    self._image(parts[2], parts[4])
                elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'sounds':
                    path = sound_path(parts[2], parts[4])
                    if path is None:
                        self._error(404, 'no such sound')
                    else:
                        data = FOLDERS[parts[2]][path]
                        self._bytes(data, SOUND_TYPES[PurePosixPath(path).suffix], no_store=True)
                elif len(parts) == 4 and parts[1] == 'teams' and parts[3] == 'export':
                    self._export(parts[2])
                elif len(parts) == 4 and parts[1] == 'teams' and parts[3] == 'presentation':
                    self._json(presentation(parts[2]))
                elif len(parts) >= 5 and parts[1] == 'teams' and parts[3] == 'presentation':
                    name = '/'.join(parts[4:])
                    data = presentation_file(parts[2], name)
                    if data is None:
                        self._error(404, 'no such file of the package')
                    else:
                        self._bytes(data, presentation_type(parts[2], name), no_store=True)
                elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'clips':
                    data = clip_bytes(parts[2], parts[4])
                    if data is None:
                        self._error(404, 'no such clip')
                    else:
                        self._bytes(data, 'model/gltf-binary', no_store=True)
                elif parts[1:3] == ['mock', 'samples'] and parts[3:] in (
                    ['sample-5v5'],
                    ['sample-11v11'],
                ):
                    self._bytes(
                        (SAMPLES / f'{parts[3]}.cjr').read_bytes(), 'application/octet-stream'
                    )
                elif parts == ['api', 'models']:
                    self._json(shipped_models())
                elif parts == ['api', 'presentation', 'sides']:
                    self._json(PRESENTATION_SIDES)
                elif parts == ['api', 'requests']:
                    self._json(requests.entries())
                else:
                    self._error(404, 'no such resource')
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_POST(self):
            self._handle(self._post)

        def _post(self):
            parts, query = self._route()
            try:
                if parts[:2] == ['api', 'tournaments']:
                    self._tournaments('POST')
                elif len(parts) == 4 and parts[1] == 'teams' and parts[3] == 'duplicate':
                    self._json(duplicate(parts[2]), 201)
                elif len(parts) == 4 and parts[1] == 'trash' and parts[3] == 'restore':
                    if trash(parts[2], restore=True):
                        self._json(details(parts[2]))
                    else:
                        self._error(404, 'no such recording in the Trash')
                elif len(parts) == 4 and parts[1] == 'groups' and parts[3] == 'restore':
                    restored = trash_group(parts[2], restore=True)
                    if restored:
                        self._json({'group': parts[2], 'restored': restored})
                    else:
                        self._error(404, 'no such group of recordings in the Trash')
                elif parts[1:3] == ['mock', 'live'] and parts[4:] in (['drop'], ['end']):
                    source = LIVE.get(parts[3])
                    if not isinstance(source, LiveSource):
                        # The grid's source has no process to drop or end.
                        self._error(404, 'no such live source of a process')
                    else:
                        if parts[4] == 'drop':
                            source.drop()
                        else:
                            # A source that closes leaves the list before its streams end, and
                            # a new one takes its place, as a new process would.
                            LIVE.pop(source.id, None)
                            replacement = LiveSource(source.per_team)
                            LIVE[replacement.id] = replacement
                            source.end()
                        self.send_response(204)
                        self.end_headers()
                elif parts[:2] == ['api', 'challenges']:
                    self._json(*challenges_post(parts[2:], self._document()))
                elif parts[:2] == ['api', 'help']:
                    self._json(*mock_help.post(parts[2:], self._document()))
                elif parts[:2] == ['api', 'languages']:
                    self._json(*mock_language.post(parts[2:], self._body()))
                elif parts == ['api', 'teams']:
                    team = add(
                        query.get('name', ''),
                        query.get('filename', 'main.py'),
                        self._body(),
                        query.get('format', '11v11'),
                    )
                    self._json(team, 201)
                elif parts == ['api', 'presentation', 'sides']:
                    document = self._document()
                    for side in ('left', 'right'):
                        if side in document:
                            team = document[side]
                            if team is not None and team not in FOLDERS:
                                self._error(400, 'expected a registered team')
                                return
                            PRESENTATION_SIDES[side] = team
                    self._json(PRESENTATION_SIDES)
                elif parts == ['api', 'requests']:
                    document = self._document()
                    seed = document.get('seed')
                    item = requests.add(
                        str(document.get('left', BUILTIN)),
                        str(document.get('right', BUILTIN)),
                        str(document.get('scenario', '11_vs_11_kaggle')),
                        None if seed in (None, '') else int(seed),
                    )
                    self._json(item, 201)
                elif len(parts) == 4 and parts[1] == 'live' and mock_grid.owns(parts[2]):
                    mock_grid.post(self, parts[2], parts[3])
                else:
                    self._error(404, 'no such resource')
            except (ArgumentError, ValueError) as error:
                self._error(400, str(error))

        def do_PUT(self):
            self._handle(self._put)

        def _put(self):
            parts, query = self._route()
            try:
                if len(parts) == 4 and parts[1] == 'teams' and parts[3] == 'model':
                    joints = json.loads(query.get('joints') or '{}')
                    self._json(set_model(parts[2], self._body(), joints))
                elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'images':
                    self._json(set_image(parts[2], parts[4], self._body()))
                elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'sounds':
                    self._json(set_sound(parts[2], parts[4], self._body()))
                elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'clips':
                    joints = json.loads(query['joints']) if 'joints' in query else None
                    self._json(set_clip(parts[2], parts[4], self._body(), joints))
                else:
                    self._error(404, 'no such resource')
            except (ArgumentError, ValueError) as error:
                self._error(400, str(error))

        def do_PATCH(self):
            self._handle(self._patch)

        def _patch(self):
            parts, _ = self._route()
            try:
                if len(parts) == 3 and parts[1] == 'matches':
                    document = self._document()
                    self._json(
                        update_match(
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
                    self._json(set_clip_joints(parts[2], parts[4], joints))
                elif len(parts) == 3 and parts[1] == 'teams':
                    document = self._document()
                    self._json(
                        update(
                            parts[2],
                            document.get('name'),
                            document.get('style'),
                            document.get('format'),
                        )
                    )
                else:
                    self._error(404, 'no such resource')
            except (ArgumentError, ValueError) as error:
                self._error(400, str(error))

        def do_DELETE(self):
            self._handle(self._delete)

        def _delete(self):
            parts, _ = self._route()
            if parts[:2] == ['api', 'tournaments']:
                self._tournaments('DELETE')
                return
            if parts[:2] == ['api', 'challenges']:
                self._json(*challenges_delete(parts[2:]))
                return
            if len(parts) == 3 and parts[1] == 'groups':
                trashed = trash_group(parts[2])
                if trashed:
                    self._json({'group': parts[2], 'trashed': trashed})
                else:
                    self._error(404, 'no such group of recordings in the library')
                return
            if parts[:2] == ['api', 'languages']:
                self._json(*mock_language.delete(parts[2:]))
                return
            if len(parts) == 3 and parts[1] == 'requests':
                removed = requests.cancel(parts[2])
            elif len(parts) == 4 and parts[1] == 'teams' and parts[3] == 'model':
                try:
                    removed = remove_model(parts[2])
                except ArgumentError:
                    removed = False
            elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'images':
                removed = remove_image(parts[2], parts[4])
            elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'sounds':
                removed = remove_sound(parts[2], parts[4])
            elif len(parts) == 5 and parts[1] == 'teams' and parts[3] == 'clips':
                removed = remove_clip(parts[2], parts[4])
            elif len(parts) == 3 and parts[1] == 'matches':
                removed = trash(parts[2])
            elif len(parts) == 3 and parts[1] == 'trash':
                removed = purge(parts[2])
            elif len(parts) == 3 and parts[1] == 'teams':
                removed = remove(parts[2])
            else:
                self._error(404, 'no such resource')
                return
            if removed:
                self.send_response(204)
                self.end_headers()
            else:
                self._error(404, 'no such item')

        def _feed(self, source):
            """Answers what the source of a feed names, as the real server does."""

            def recording_of(identifier):
                try:
                    return details(identifier)
                except ArgumentError:
                    return None

            def read(*rest):
                status, body = cups.respond('GET', list(rest), {})
                return body if status == 200 else None

            try:
                self._json(
                    mock_feed.resolve(
                        source,
                        live=lambda: [s.describe() for s in list(LIVE.values())],
                        recordings=matches,
                        recording=recording_of,
                        requests=requests.entries,
                        tournaments=lambda: read() or [],
                        tournament=lambda identifier: read(identifier),
                    )
                )
            except mock_feed.FeedError as error:
                self._error(400, str(error))

        def _static(self, parts):
            path = os.path.realpath(os.path.join(WEB_ROOT, *(parts or ['index.html'])))
            try:
                inside_root = os.path.commonpath([WEB_ROOT, path]) == WEB_ROOT
            except ValueError:
                inside_root = False
            if not inside_root or path == WEB_ROOT or not os.path.isfile(path):
                self._error(404, 'no such file')
                return
            with open(path, 'rb') as f:
                data = f.read()
            if os.path.basename(path) in ('index.html', 'feed.html'):
                data = mock_language.inline(data)
            kind = TYPES.get(os.path.splitext(path)[1]) or mimetypes.guess_type(path)[0]
            # The service worker is checked anew on every registration, as the server sends it,
            # with the digests of the files it may answer from its cache.
            if parts == ['sw.js']:
                self._bytes(page_digests(data), kind, no_store=True)
                return
            self._bytes(data, kind or 'application/octet-stream')

        def _image(self, identifier, slot):
            found = image(identifier, slot)
            if found is None:
                self._error(404, 'no such image')
                return
            path, data = found
            kind = IMAGE_TYPES.get(PurePosixPath(path).suffix, 'application/json')
            self._bytes(data, kind, no_store=True)

        def _export(self, identifier):
            try:
                filename, data = export(identifier)
            except ArgumentError as error:
                self._error(404, str(error))
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            fallback = filename.encode('ascii', 'replace').decode().replace('?', '-')
            quoted = urllib.parse.quote(filename)
            self.send_header(
                'Content-Disposition',
                f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quoted}',
            )
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _relay(self, identifier, sequence=False):
            """Streams a live source, numbering its frames when sequence is true.

            A numbered stream announces itself in the header and ends with the end marker, and a
            drop closes the connection without it, as a lost connection does.
            """
            source = LIVE.get(identifier)
            if source is None:
                self._error(404, 'no such live source')
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()

            def pack(items):
                return b''.join(
                    (struct.pack('<Q', serial) if sequence else b'') + frame
                    for serial, frame in items
                )

            with source.cond:
                source.cond.wait_for(lambda: source.header is not None)
                header = dict(source.header)
                if sequence:
                    header.update(stream_sequence=1, stream_id=f'{source.id}:0')
                head = mock_sample.encode_header(header)
                backlog = source.backlog()
                last = source.serial - 1
                drops, ends = source.drops, source.ends
            self.wfile.write(head + pack(backlog))
            self.wfile.flush()
            while True:
                with source.cond:
                    source.cond.wait_for(
                        lambda last=last: (
                            source.serial - 1 > last or source.drops != drops or source.ends != ends
                        ),
                        timeout=5.0,
                    )
                    # The frames published before a drop still reach the viewer, however far
                    # this stream lags, so a reconnection loses the drop's frames alone.
                    dropped = source.drops != drops
                    ended = source.ends != ends
                    batch = [
                        item
                        for item in source.frames
                        if item[0] > last and (not dropped or item[0] < source.dropped)
                    ]
                    last = source.serial - 1
                if batch:
                    self.wfile.write(pack(batch))
                    self.wfile.flush()
                if dropped:
                    return
                if ended:
                    if sequence:
                        self.wfile.write(END)
                        self.wfile.flush()
                    return

    return Handler


def load_recordings(folder):
    """Adds every .cjr file of a folder to the library, oldest first.

    A recording of version 2 keeps its file as it is, with its score left at none, since the mock
    reads no coded frames.
    """
    for path in sorted(Path(folder).glob('*.cjr')):
        data = gzip.decompress(path.read_bytes())
        if not data.startswith(mock_sample.MAGIC):
            raise ValueError(f'expected a cuju recording, found {path}')
        start = len(mock_sample.MAGIC) + 4
        (length,) = struct.unpack_from('<I', data, len(mock_sample.MAGIC))
        header = json.loads(data[start : start + length])
        if header.get('version') == 2:
            identifier = save_match(header, [])
            MATCHES[identifier]['data'] = path.read_bytes()
            MATCHES[identifier]['summary'].update(
                steps=header['frame_count'], score=None, bytes=path.stat().st_size
            )
            continue
        size = mock_sample.frame_bytes(len(header['players']))
        body = data[start + length :]
        save_match(header, [body[i : i + size] for i in range(0, len(body) - size + 1, size)])


class ReusedThreadsServer(http.server.ThreadingHTTPServer):
    """Runs each request on a thread of its own, keeping finished threads for the next requests.

    The server of cuju does the same, see cuju.render._http.launch.LoopbackServer, since a new
    thread is slow to start on a loaded Windows machine and a page asks for some three hundred
    files.
    """

    daemon_threads = True
    idle_seconds = 30.0
    # The connections that wait to be accepted, as the server of cuju keeps them, since Windows
    # refuses a connection beyond the queue.
    request_queue_size = 128

    def __init__(self, *arguments, **options):
        self._pool_lock = threading.Lock()
        self._requests = queue.Queue()
        self._waiting = 0
        super().__init__(*arguments, **options)

    def process_request(self, request, client_address):
        with self._pool_lock:
            spawn = not self._waiting
            if not spawn:
                self._waiting -= 1
        self._requests.put((request, client_address))
        if spawn:
            threading.Thread(target=self._serve_requests, daemon=True).start()

    def _serve_requests(self):
        while True:
            try:
                request, client_address = self._requests.get(timeout=self.idle_seconds)
            except queue.Empty:
                with self._pool_lock:
                    if not self._waiting or not self._requests.empty():
                        continue
                    self._waiting -= 1
                return
            self.process_request_thread(request, client_address)
            with self._pool_lock:
                self._waiting += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--short', action='store_true', help='use short sample matches')
    parser.add_argument('--recordings', help='a folder of .cjr files to add to the library')
    args = parser.parse_args()
    print('generating synthetic recordings')
    reds = {'name': 'Reds', 'color': [200, 30, 40], 'secondary': [250, 250, 250]}
    builtin_name = entry(BUILTIN)['name']
    for per_team, steps, names, sides in (
        (11, 2400, ('Reds', builtin_name), [reds, header_team(BUILTIN)]),
        (5, 1800, ('Greens', 'Golds'), None),
    ):
        header, frames = mock_sample.generate_frames(
            per_team, min(steps, 120) if args.short else steps, 1, names, sides
        )
        save_match(header, frames)
    seed_group()
    if args.recordings:
        load_recordings(args.recordings)
    source = LiveSource(11)
    LIVE[source.id] = source
    mock_grid.start(LIVE, new_identifier('live'))
    mock_help.bind(
        matches=matches,
        matches_store=MATCHES,
        save_match=save_match,
        trash=trash,
        teams=teams,
        add_team=add,
        lock=LOCK,
        magic=mock_sample.MAGIC,
    )
    server = ReusedThreadsServer(('127.0.0.1', args.port), make_handler(Requests()))
    print(f'serving {WEB_ROOT} on http://127.0.0.1:{server.server_address[1]}/', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
