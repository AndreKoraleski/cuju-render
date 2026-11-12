# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The team registry of the renderer, Kaggle submissions kept in the renderer's folder.

A team is a submission of Kaggle's GRF competition, a folder whose `main.py` defines the agent, as
Kaggle receives it, also accepted as one Python file or an archive. The built-in AI of GRF is always
a team as well. A submission is code, which runs with the permissions of the process that plays
it.

Each team carries a format, `5v5` or `11v11`, and a style, its kit, its goalkeeper's kit, its
players' names, numbers, skin and hair, its shirt's painted front and back, its sponsors and its
player model, GRF's, a shipped one or its own rigged binary glTF file. Only the renderer draws them,
and none reaches a match. They live in the folder `cuju-team` inside the submission, so a team
exported from the page carries them along, and a submission folder that holds one brings them back.
"""

from __future__ import annotations

import bz2
import collections
import contextlib
import functools
import gzip
import hashlib
import io
import json
import logging
import os
import re
import shutil
import struct
import sys
import tarfile
import tempfile
import threading
import time
import types
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any

from cuju.errors import ArgumentError

from .._store import home as _home
from .._text import messages as _messages
from .._text.messages import MessageError

try:
    import lzma
except ImportError:
    # A Python built without lzma reads no xz archive, as tarfile does then.
    lzma = None  # type: ignore[assignment]
_LZMA_ERRORS = () if lzma is None else (lzma.LZMAError,)

BUILTIN = 'builtin'
# The start of a submission folder as the page uploads it, an index and the files' bytes.
FOLDER_MAGIC = b'CUJDIR1\n'
# The built-in AI's name until a person renames it, a label that the page shows in its language.
_BUILTIN_NAME = 'server.names.builtin'
_BUILTIN_ENTRY = {
    'id': BUILTIN,
    'name': _messages.text(_BUILTIN_NAME),
    'kind': 'builtin',
    'created': None,
}
# Kaggle: the file that an archive's agent lives in.
_MAIN = 'main.py'
# Submissions larger than this are refused, as Kaggle limits them too.
_MAXIMUM_BYTES = 100 * 1024 * 1024
# An archive may unpack to this much and this many files, so a small upload cannot fill the disk.
_MAXIMUM_UNPACKED = 500 * 1024 * 1024
_MAXIMUM_FILES = 10000
# The bytes of a tar archive after decompression that an upload reads at most, its members and
# their headers, and the bytes of the headers of one member, so a small compressed archive cannot
# make the server read or hold without end.
_MAXIMUM_TAR_BYTES = _MAXIMUM_UNPACKED + 64 * 1024 * 1024
_MAXIMUM_TAR_HEADER = 1024 * 1024
_LOGGER = logging.getLogger('cuju')
# One lock serializes every change of the registry, which the server makes from several threads.
_LOCK = threading.RLock()


_PATTERNS = ('plain', 'stripes', 'hoops', 'halves', 'sash', 'checkers')
# `grf` keeps the skin or hair that GRF gives the player's index.
_SKINS = ('grf', 'light', 'tan', 'medium', 'dark')
_HAIRS = ('grf', 'bald', 'short01', 'short02', 'medium01', 'long01', 'long02')
_HAIR_COLORS = ('grf', 'black', 'brown', 'darkblonde', 'blonde', 'red')
_NUMBERS = ('white', 'black', 'secondary')
_PARTS = ('primary', 'secondary', 'shorts', 'socks')
# The sizes of a team for competition, the players a side of `5_vs_5` and of the full matches.
FORMATS = {'5v5': 5, '11v11': 11}
ROLES = ('GK', 'CB', 'LB', 'RB', 'DM', 'CM', 'LM', 'RM', 'AM', 'CF')
# The players that a submission of each format may control, as agents of its side. GRF: the
# goalkeeper of `5_vs_5` is not controllable, every player of the eleven a side scenarios is.
CONTROLLABLE = {'5v5': 4, '11v11': 11}
# A submission controls the active player alone by default, as on Kaggle.
DEFAULT_CONTROL = {
    'players': 1,
    'assignment': 'dynamic',
    'selection': [],
    'goalkeeper': 'scenario',
    'action_set': 'default',
}
# The images that a team may hold, the flat front and back of its shirt, the editor's documents
# that made them, and the sponsors that the adboards show while the team plays.
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
# The fields of an entry that the team's folder implies, which its file never stores.
_IMPLIED = ('images', 'sounds', 'sounds_version', 'clips', 'name_id', 'name_values')
# The folder of a submission that holds the renderer's files of its team.
TEAM_FOLDER = 'cuju-team'
_MAXIMUM_IMAGE_BYTES = 8 * 1024 * 1024
# The longest file of a team's entry that the registry reads, in bytes.
_MAXIMUM_ENTRY_BYTES = 1024 * 1024
# The sounds a team may hold, each played when one of its players does that, or its fans sing.
SOUND_SLOTS = ('goal', 'shot', 'pass', 'tackle', 'save', 'kick', 'celebration', 'chant')
_MAXIMUM_SOUND_BYTES = 2 * 1024 * 1024
_SOUND_SUFFIXES = ('.ogg', '.mp3', '.wav')
_IMAGE_SUFFIXES = ('.png', '.jpg', '.webp', '.json')
# An imported file that fails its checks keeps its bytes under its name followed by this.
_REJECTED = '.rejected'
# Windows: these names open a device in any folder, whatever their extension or case, the ports
# with a superscript digit as well.
_SUPERSCRIPTS = r'\N{SUPERSCRIPT ONE}\N{SUPERSCRIPT TWO}\N{SUPERSCRIPT THREE}'
_DEVICES = re.compile(
    rf'(con|prn|aux|nul|conin\$|conout\$|(com|lpt)[0-9{_SUPERSCRIPTS}])', re.IGNORECASE
)
_KIT = {
    'pattern': 'plain',
    'primary': [214, 48, 49],
    'secondary': [255, 255, 255],
    'shorts': [255, 255, 255],
    'socks': [214, 48, 49],
}
_GOALKEEPER = {
    'primary': [46, 204, 113],
    'secondary': [20, 20, 20],
    'shorts': [20, 20, 20],
    'socks': [46, 204, 113],
}


# The kits that new teams take in turn, so that two teams added one after the other differ. Each
# is a primary color and the color of the shorts, away from the built-in AI's blue and from the
# goalkeepers' green.
_NEW_KITS = (
    ([214, 48, 49], [255, 255, 255]),
    ([230, 126, 34], [20, 20, 20]),
    ([142, 68, 173], [255, 255, 255]),
    ([241, 196, 15], [20, 20, 20]),
    ([45, 52, 54], [255, 255, 255]),
    ([232, 67, 147], [255, 255, 255]),
    ([255, 255, 255], [20, 20, 20]),
    ([127, 0, 32], [255, 255, 255]),
)


def _new_kit() -> dict[str, Any]:
    """Returns the kit of the next new team, the first of `_NEW_KITS` that fewest teams wear."""
    worn: collections.Counter[tuple[int, ...]] = collections.Counter()
    for path in _home.folder('teams').glob(f'*/{TEAM_FOLDER}/team.json'):
        with contextlib.suppress(OSError, ValueError, TypeError, KeyError, AttributeError):
            team = _read_entry(path)
            worn[tuple(team['style']['kit']['primary'])] += 1
    primary, shorts = min(_NEW_KITS, key=lambda kit: worn[tuple(kit[0])])
    return {
        **_KIT,
        'primary': list(primary),
        'shorts': list(shorts),
        'socks': list(primary),
        'secondary': [20, 20, 20] if primary == [255, 255, 255] else [255, 255, 255],
    }


def _player_style(index: int) -> dict[str, Any]:
    """Returns the default style of the player at `index` of a team, GRF's own look."""
    return {
        'name': '',
        'number': index + 1,
        'skin': 'grf',
        'hair': 'grf',
        'hair_color': 'grf',
        'model': 'team',
        'celebration': 'team',
    }


def default_style(format: str = '11v11', kit: dict[str, Any] | None = None) -> dict[str, Any]:
    """Returns the style of a new team of `format`, GRF's model in a plain kit."""
    colors = kit or _KIT
    return {
        'model': 'grf',
        'kit': dict(colors),
        'goalkeeper': dict(_GOALKEEPER),
        'badge': '',
        'number': 'white',
        'colors': {},
        # The fans wear the kit's colors unless the team picks colors of their own.
        'crowd': {'colors': [list(colors['primary']), list(colors['secondary'])]},
        # The celebrations the page picks from after a goal, empty for every one it knows.
        'celebrations': [],
        # The models on whose backs the page leaves out the shirt numbers, which every model but
        # GRF's, which paints its own, wears where its torso holds one.
        'hidden_numbers': [],
        'players': [_player_style(index) for index in range(FORMATS[format])],
    }


_BUILTIN_KIT = {
    'pattern': 'plain',
    'primary': [9, 132, 227],
    'secondary': [255, 255, 255],
    'shorts': [9, 132, 227],
    'socks': [255, 255, 255],
}


def _color(value: Any, name: Any) -> list[int]:
    """Returns an RGB color as three integers from 0 to 255, or raises `ArgumentError`."""
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or not all(
            isinstance(part, int) and not isinstance(part, bool) and 0 <= part <= 255
            for part in value
        )
    ):
        raise MessageError('server.teams.color', name=name, value=repr(value))
    return [int(part) for part in value]


def _printable(text: str) -> str:
    """Returns `text` with every character that prints nothing of its own turned into a space.

    These are the control characters, the escapes of a terminal and line breaks among them, and
    the format characters, the marks that turn the direction of text around among them, which
    `str.isprintable` finds, and every space but the plain one.
    """
    return ''.join(character if character.isprintable() else ' ' for character in text)


def _field(name: str) -> dict[str, Any]:
    """Returns the name of a field of a team in a message, the label `server.teams.field.<name>`."""
    return _messages.label(f'server.teams.field.{name}')


def _choice(value: Any, choices: tuple[str, ...], name: Any) -> str:
    """Returns `value` if it is one of `choices`, or raises `ArgumentError`."""
    if value not in choices:
        raise MessageError(
            'server.teams.choice', name=name, choices=', '.join(choices), value=repr(value)
        )
    return value


def _players(
    value: Any, current: list[dict[str, Any]], models: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    """Returns the roster with the changes of `value`, a list of per-player dictionaries."""
    if not isinstance(value, list) or len(value) > len(current):
        raise MessageError('server.teams.players', count=len(current), value=repr(value))
    roster = [dict(player) for player in current]
    for index, changes in enumerate(value):
        if not isinstance(changes, dict):
            raise MessageError('server.teams.player', index=index, value=repr(changes))
        for key, entry in changes.items():
            if key == 'name':
                if not isinstance(entry, str) or len(entry) > 24:
                    raise MessageError('server.teams.player_name', name=repr(entry))
                roster[index][key] = _printable(entry)
            elif key == 'number':
                if isinstance(entry, bool) or not isinstance(entry, int) or not 0 <= entry <= 99:
                    raise MessageError('server.teams.shirt_number', number=repr(entry))
                roster[index][key] = entry
            elif key == 'skin':
                roster[index][key] = _choice(entry, _SKINS, _field('skin'))
            elif key == 'hair':
                roster[index][key] = _choice(entry, _HAIRS, _field('hair'))
            elif key == 'hair_color':
                roster[index][key] = _choice(entry, _HAIR_COLORS, _field('hair_color'))
            elif key == 'celebration':
                # `team` picks among the team's celebrations, any other value is the player's own.
                roster[index][key] = _celebration(entry)
            elif key == 'model':
                # `team` follows the team's model, any other value gives the player one of its own.
                roster[index][key] = _choice(
                    entry, ('team', 'grf', 'custom', *models), _field('player_model')
                )
            else:
                raise MessageError('server.teams.player_entry', key=repr(key))
    return roster


_HEX = re.compile(r'#[0-9a-f]{6}')
# A celebration is named by the page, such as `knee_slide`, or `clip:` and an animation of a model.
_CELEBRATION = re.compile(r'[a-z0-9_]{1,40}(:[A-Za-z0-9_. -]{1,60})?')


def _celebration(value: Any) -> str:
    """Returns the name of a celebration, which the page knows or finds among a model's clips."""
    if not isinstance(value, str) or not _CELEBRATION.fullmatch(value):
        raise MessageError('server.teams.celebration', value=repr(value))
    return value


# A model's colors to replace, at most this many per model.
_MAXIMUM_RECOLORS = 32


def _colors(value: Any, models: tuple[str, ...]) -> dict[str, dict[str, str]]:
    """Returns the colors that replace others on each model, as `#rrggbb` pairs by model.

    The page lists the colors present in a model's textures and materials, and each pair maps one
    of them to the color the team wants instead. GRF's own model takes the kit's colors instead.
    """
    if not isinstance(value, dict):
        raise MessageError('server.teams.colors', value=repr(value))
    result: dict[str, dict[str, str]] = {}
    for model, pairs in value.items():
        _choice(model, models, _field('colors_model'))
        if not isinstance(pairs, dict) or len(pairs) > _MAXIMUM_RECOLORS:
            raise MessageError(
                'server.teams.colors_count', count=_MAXIMUM_RECOLORS, model=repr(model)
            )
        result[model] = {}
        for old, new in pairs.items():
            if not (
                isinstance(old, str)
                and isinstance(new, str)
                and _HEX.fullmatch(old.lower())
                and _HEX.fullmatch(new.lower())
            ):
                raise MessageError('server.teams.color_pair', old=repr(old), new=repr(new))
            result[model][old.lower()] = new.lower()
    return result


def _hidden_numbers(value: Any, models: tuple[str, ...]) -> list[str]:
    """Returns the models on which a team hides its shirt numbers, each listed once.

    A model that is no longer shipped is left out, so a style saved with it still loads.
    """
    if (
        not isinstance(value, list)
        or len(value) > 64
        or not all(isinstance(model, str) and len(model) <= 64 for model in value)
    ):
        raise MessageError('server.teams.hidden_numbers', value=repr(value))
    return list(dict.fromkeys(model for model in value if model in models))


def style(
    changes: dict[str, Any] | None, base: dict[str, Any], models: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Returns the complete style `base` with `changes` applied and checked.

    Args:
        changes: Entries of the style to change, or `None`.
        base: The style to change, whose roster sets the team's size.
        models: The shipped models a team may choose besides `grf` and `custom`.

    Raises:
        ArgumentError: If a change names an unknown entry or holds a value outside its choices.
    """
    result = json.loads(json.dumps(base))
    changes = changes or {}
    if not isinstance(changes, dict):
        raise MessageError('server.teams.style', value=repr(changes))
    for key, value in changes.items():
        if key in ('kit', 'goalkeeper'):
            if not isinstance(value, dict):
                raise MessageError('server.teams.style_part_object', key=key, value=repr(value))
            for part, entry in value.items():
                if key == 'kit' and part == 'pattern':
                    result[key][part] = _choice(entry, _PATTERNS, _field('pattern'))
                elif part in _PARTS:
                    result[key][part] = _color(entry, f'{key} {part}')
                else:
                    raise MessageError('server.teams.style_part', key=key, part=repr(part))
        elif key == 'model':
            result[key] = _choice(value, ('grf', 'custom', *models), _field('model'))
        elif key == 'number':
            result[key] = _choice(value, _NUMBERS, _field('numbers'))
        elif key == 'badge':
            if not isinstance(value, str) or len(value) > 3:
                raise MessageError('server.teams.badge', value=repr(value))
            result[key] = value
        elif key == 'players':
            result[key] = _players(value, result[key], models)
        elif key == 'colors':
            result[key] = _colors(value, ('custom', *models))
        elif key == 'celebrations':
            if not isinstance(value, list) or len(value) > 32:
                raise MessageError('server.teams.celebrations')
            result[key] = [_celebration(item) for item in value]
        elif key == 'hidden_numbers':
            result[key] = _hidden_numbers(value, ('custom', *models))
        elif key == 'crowd':
            if not isinstance(value, dict) or set(value) - {'colors'}:
                raise MessageError('server.teams.crowd', value=repr(value))
            colors = value.get('colors', result[key]['colors'])
            if not isinstance(colors, list) or not 1 <= len(colors) <= 4:
                raise MessageError('server.teams.crowd_colors')
            result[key] = {'colors': [_color(color, _field('fans_color')) for color in colors]}
        else:
            raise MessageError('server.teams.style_entry', key=repr(key))
    return result


def _resize(style_: dict[str, Any], format: str) -> dict[str, Any]:
    """Returns the style with its roster cut or extended to the size of `format`."""
    size = FORMATS[format]
    roster = style_['players'][:size]
    roster += [_player_style(index) for index in range(len(roster), size)]
    return {**style_, 'players': roster}


def shipped_models() -> list[dict[str, Any]]:
    """Returns the description of every player model that the package ships."""
    folder = Path(__file__).parents[1] / 'web' / 'assets' / 'models'
    models = []
    for path in sorted(folder.glob('*.json')):
        with contextlib.suppress(OSError, ValueError):
            description = json.loads(path.read_text(encoding='utf-8'))
            if path.with_suffix('.glb').is_file():
                description['url'] = f'assets/models/{path.stem}.glb'
                models.append(description)
    return models


def _model_names() -> tuple[str, ...]:
    """Returns the identifiers of the shipped models."""
    return tuple(model['id'] for model in shipped_models())


def _complete(entry: dict[str, Any], kit: dict[str, Any] | None = None) -> dict[str, Any]:
    """Returns a stored entry with its format, style, model and images filled and checked."""
    entry = dict(entry)
    if not isinstance(entry.get('format'), str) or entry['format'] not in FORMATS:
        entry['format'] = '11v11'
    base = default_style(entry['format'], kit)
    saved = entry.get('style') if isinstance(entry.get('style'), dict) else {}
    try:
        entry['style'] = _resize(
            style(saved, {**base, **_known(saved, base)}, _model_names()), entry['format']
        )
    except ArgumentError:
        entry['style'] = base
    entry.setdefault('model', None)
    try:
        entry['control'] = check_control(entry.get('control'), entry['format'])
    except ArgumentError:
        entry['control'] = dict(DEFAULT_CONTROL)
    folder = _meta_path(entry['id']).parent
    names = _names(folder)
    entry['images'] = [slot for slot in IMAGE_SLOTS if _image_file(folder, slot, names)]
    entry['sounds'] = [slot for slot in SOUND_SLOTS if _sound_file(folder, slot, names)]
    entry['sounds_version'] = _sounds_version(folder)
    from . import clips as _clips

    entry['clips'] = _clips.listing(folder)
    return entry


def _sounds_version(folder: Path) -> str:
    """Returns a short text that changes whenever a sound of a team's folder changes.

    The page keeps the sounds it decoded under this text, so a sound replaced under the same slot
    loads again. Each file's size, modification time and file number go in, and a sound stored
    anew always lands as a new file.
    """
    parts = []
    names = _names(folder)
    for slot in SOUND_SLOTS:
        path = _sound_file(folder, slot, names)
        with contextlib.suppress(OSError):
            if path is not None:
                stat = path.stat()
                parts.append(f'{path.name}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}')
    if not parts:
        return ''
    return hashlib.sha256('/'.join(parts).encode()).hexdigest()[:16]


def _known(saved: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """Returns the entries of a saved style that the current style still has, for old files."""
    return {key: value for key, value in saved.items() if key in base and key != 'players'}


def _meta_path(identifier: str) -> Path:
    """Returns the file of a team's entry, the built-in AI's included.

    Raises:
        ArgumentError: If the identifier could name a file outside the folder of teams.
    """
    if not isinstance(identifier, str) or not _home.valid_identifier(identifier):
        raise MessageError('server.teams.unknown', identifier=repr(identifier))
    return _home.folder('teams') / identifier / TEAM_FOLDER / 'team.json'


def _read_entry(path: Path) -> dict[str, Any]:
    """Returns the stored entry of a team's file, or raises `ValueError` for any other content.

    The file is at most `_MAXIMUM_ENTRY_BYTES` long and holds a JSON object.
    """
    with path.open('rb') as stream:
        data = stream.read(_MAXIMUM_ENTRY_BYTES + 1)
    if len(data) > _MAXIMUM_ENTRY_BYTES:
        raise ValueError('the file of the team is too long')
    try:
        saved = json.loads(data)
    except RecursionError as error:
        raise ValueError('the file of the team nests too deeply') from error
    if not isinstance(saved, dict):
        raise ValueError('the file of the team holds no object')
    return saved


def _builtin() -> dict[str, Any]:
    """Returns the entry of the built-in AI, with the name and style its file keeps, if any."""
    entry = dict(_BUILTIN_ENTRY)
    with contextlib.suppress(OSError, ValueError):
        saved = _read_entry(_meta_path(BUILTIN))
        entry.update({key: saved[key] for key in ('style', 'model', 'format') if key in saved})
        name = _printable(saved['name']).strip()[:80] if isinstance(saved.get('name'), str) else ''
        if name:
            entry['name'] = name
    return _complete(_builtin_name(entry), _BUILTIN_KIT)


def _builtin_name(entry: dict[str, Any]) -> dict[str, Any]:
    """Returns the built-in AI's entry with the message of its name while it keeps the default.

    The page sends the name back with every change of the style, so a stored name equal to the
    English default still counts as the default.
    """
    entry = {key: value for key, value in entry.items() if key not in ('name_id', 'name_values')}
    if entry.get('name') == _BUILTIN_ENTRY['name']:
        entry.update(_messages.named('name', _messages.label(_BUILTIN_NAME)))
    return entry


def _reason(error: BaseException) -> dict[str, Any] | str:
    """Returns an error as a value of another message, a label when it carries a message id."""
    message_id = getattr(error, 'message_id', None)
    if isinstance(message_id, str) and message_id in _messages.MESSAGES:
        return _messages.label(message_id, **getattr(error, 'values', {}))
    return str(error)


def shown_name(team: dict[str, Any]) -> dict[str, Any] | str:
    """Returns the name of a team as a message value, a label for a name that cuju made."""
    found = {'id': team.get('name_id'), 'text': team.get('name'), 'values': team.get('name_values')}
    return found if _messages.valid_label(found) else str(team.get('name'))


def teams() -> list[dict[str, Any]]:
    """Returns every team, the built-in AI first, then the submissions from newest to oldest.

    A team's identifier is the name of its folder, whatever its file says, and a folder whose
    name is no identifier, or whose file fails to read as an entry, is left out alone.
    """
    entries = []
    for folder in _home.folder('teams').iterdir():
        if folder.name == BUILTIN or not _home.valid_identifier(folder.name):
            continue
        meta = folder / TEAM_FOLDER / 'team.json'
        try:
            if not (folder.is_dir() and meta.is_file()):
                continue
            saved = _read_entry(meta)
            if not isinstance(saved.get('created'), str):
                saved['created'] = ''
            # A name of a file edited by hand prints in a terminal too, so its control and format
            # characters, such as escapes and the marks that turn text around, become spaces.
            name = saved.get('name')
            name = _printable(name).strip()[:80] if isinstance(name, str) else ''
            saved['name'] = name or folder.name
            entry = _complete({**saved, 'id': folder.name, 'kind': 'kaggle'})
        except Exception as error:
            _LOGGER.warning('cuju render leaves out the team %s, %s', folder.name, error)
            continue
        entries.append(entry)
    entries.sort(key=lambda entry: entry.get('created') or '', reverse=True)
    return [_builtin(), *entries]


def check_control(control: Any, format: str) -> dict[str, Any]:
    """Returns normalized team control and migrates earlier settings."""
    control = dict(DEFAULT_CONTROL) if control is None else control
    allowed = {'players', 'goalkeeper', 'assignment', 'selection', 'action_set'}
    if not isinstance(control, dict) or set(control) - allowed:
        raise MessageError('server.teams.control.fields')
    players = control.get('players', 1)
    most = FORMATS[format]
    if isinstance(players, bool) or not isinstance(players, int) or not 1 <= players <= most:
        raise MessageError('server.teams.control.players', most=most)
    legacy = 'assignment' not in control
    keeper = _choice(
        control.get('goalkeeper', 'scenario'),
        ('agent', 'builtin', 'scenario'),
        _field('goalkeeper'),
    )
    assignment = control.get('assignment', 'fixed' if keeper == 'builtin' else 'dynamic')
    _choice(assignment, ('dynamic', 'fixed'), _field('assignment'))
    if legacy and keeper == 'builtin' and (format != '11v11' or players != 10):
        raise MessageError('server.teams.control.legacy_goalkeeper')
    if legacy and keeper == 'agent':
        keeper = 'scenario'
    if assignment == 'dynamic' and keeper == 'builtin':
        raise MessageError('server.teams.control.goalkeeper_fixed')
    selection = control.get('selection', [])
    if legacy and assignment == 'fixed':
        selection = list(range(1, players + 1))
    if not isinstance(selection, list):
        raise MessageError('server.teams.control.selection_list')
    if assignment == 'fixed' and len(selection) != players:
        raise MessageError('server.teams.control.selection_count')
    if assignment == 'dynamic' and selection:
        raise MessageError('server.teams.control.selection_empty')
    if selection:
        indices = all(type(item) is int and 0 <= item <= 10 for item in selection)
        roles = all(isinstance(item, str) and item in ROLES for item in selection)
        if not (indices or roles) or (indices and len(set(selection)) != len(selection)):
            raise MessageError('server.teams.control.selection_distinct')
    action_set = _choice(
        control.get('action_set', 'default'), ('default', 'v2'), _field('action_set')
    )
    return dict(
        players=players,
        assignment=assignment,
        selection=list(selection),
        goalkeeper=keeper,
        action_set=action_set,
    )


def scenario_path(scenario: str) -> Path:
    """Returns the source of a shipped or renderer scenario."""
    local = Path(__file__).parents[1] / 'scenarios' / f'{scenario}.py'
    if local.is_file():
        return local
    import cuju

    return Path(cuju.__file__).parent / 'data' / 'scenarios' / f'{scenario}.py'


def renderer_scenarios() -> list[str]:
    """Returns the additional training scenarios."""
    return sorted(path.stem for path in (Path(__file__).parents[1] / 'scenarios').glob('*.py'))


def scenario_players(scenario: str, side: int) -> list[Any]:
    """Returns the initial formation of a side."""
    from cuju.scenarios import Builder, load_scenario

    builder = Builder(0)
    load_scenario(scenario_path(scenario))(builder)
    config = builder.config()
    return config.left_team if side == 0 else config.right_team


def agent_count(team: dict[str, Any], scenario: str | None = None, side: int = 0) -> int:
    """Returns the engine agents required by a side."""
    if team['kind'] == 'builtin':
        return 0
    control = check_control(team.get('control'), team['format'])
    if control['assignment'] == 'dynamic':
        return control['players']
    if scenario is None:
        return CONTROLLABLE[team['format']]
    return sum(player.controllable for player in scenario_players(scenario, side))


def selected_players(control: dict[str, Any], formation: list[Any]) -> list[int]:
    """Resolves selections in agent order, with repeated roles in lineup order."""
    available = [index for index, player in enumerate(formation) if player.controllable]
    if control['players'] > len(available):
        raise MessageError('server.teams.control.too_few', count=len(available))
    keeper = [index for index, player in enumerate(formation) if player.role == 0]
    if control['assignment'] == 'dynamic':
        if control['goalkeeper'] == 'agent' and not any(i in available for i in keeper):
            raise MessageError('server.teams.control.goalkeeper_uncontrollable')
        return available
    selected = []
    for item in control['selection']:
        candidates = (
            [item]
            if type(item) is int
            else [index for index in available if formation[index].role == ROLES.index(item)]
        )
        found = next((i for i in candidates if i in available and i not in selected), None)
        if found is None:
            raise MessageError('server.teams.control.select_player', player=item)
        selected.append(found)
    if control['goalkeeper'] == 'builtin' and not any(i in available for i in keeper):
        raise MessageError('server.teams.control.goalkeeper_builtin')
    owns_keeper = any(i in keeper for i in selected)
    if control['goalkeeper'] == 'agent' and not owns_keeper:
        raise MessageError('server.teams.control.goalkeeper_selected')
    if control['goalkeeper'] in ('builtin', 'scenario') and owns_keeper:
        raise MessageError('server.teams.control.goalkeeper_outside')
    if control['goalkeeper'] == 'scenario' and any(i in available for i in keeper):
        raise MessageError('server.teams.control.goalkeeper_scenario')
    return selected


def update(
    identifier: str,
    name: str | None = None,
    changes: dict[str, Any] | None = None,
    format: str | None = None,
    control: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Renames a team, changes its format, its control or its style, and returns its new entry.

    Args:
        identifier: The team, the built-in AI included.
        name: The new name, or `None` to keep it.
        changes: Entries of the style to change, or `None`.
        format: `5v5` or `11v11`, the size of the team for competition, which sets the length of
            its roster, or `None` to keep it.
        control: The players that the submission controls, as `check_control` takes them, or
            `None` to keep them, or the default where the new format refuses them.

    Raises:
        ArgumentError: If the team is unknown or a change is invalid.
    """
    current = entry(identifier)
    if name is not None:
        name = _printable(str(name)).strip()[:80]
        if not name:
            raise MessageError('server.teams.name')
        current['name'] = name
        if identifier == BUILTIN:
            current = _builtin_name(current)
        else:
            current.pop('name_id', None)
            current.pop('name_values', None)
    if format is not None:
        current['format'] = _choice(format, tuple(FORMATS), _field('format'))
        current['style'] = _resize(current['style'], current['format'])
    if control is not None:
        current['control'] = check_control(control, current['format'])
    else:
        try:
            current['control'] = check_control(current.get('control'), current['format'])
        except ArgumentError:
            current['control'] = dict(DEFAULT_CONTROL)
    current['style'] = style(changes, current['style'], _model_names())
    chosen = {
        current['style']['model'],
        *(player['model'] for player in current['style']['players']),
    }
    if 'custom' in chosen and model_path(identifier) is None:
        raise MessageError('server.teams.custom_model')
    _write(identifier, current)
    return current


def _names(folder: Path) -> set[str]:
    """Returns the names of the entries of a folder as written, or none if it is missing."""
    try:
        return set(os.listdir(folder))
    except OSError:
        return set()


def _exact(folder: Path, name: str, names: set[str] | None = None) -> Path | None:
    """Returns the file of a folder named exactly `name`, or `None`.

    Windows and macOS find a file whatever the case of its name, so the name must be one of the
    folder's own, `names` when given. A link, which could point outside the team's folder, counts
    as no file.
    """
    if name not in (_names(folder) if names is None else names):
        return None
    path = folder / name
    return path if path.is_file() and not path.is_symlink() else None


def _image_file(folder: Path, slot: str, names: set[str] | None = None) -> Path | None:
    """Returns the file of an image slot of a team's folder, of any of its extensions, or `None`.

    Only the slot's own name with an extension of `_IMAGE_SUFFIXES`, in that case, names it.
    """
    names = _names(folder) if names is None else names
    for suffix in _IMAGE_SUFFIXES:
        path = _exact(folder, f'{slot}{suffix}', names)
        if path is not None:
            return path
    return None


def _image_suffix(slot: str, data: bytes) -> str:
    """Returns the extension of an image's bytes, or raises `ArgumentError` for another kind."""
    if slot.endswith('-edit'):
        try:
            json.loads(data)
        except (ValueError, RecursionError) as error:
            raise MessageError('server.teams.editor', error=error) from error
        return '.json'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if data.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return '.webp'
    raise MessageError('server.teams.image_type')


def set_image(identifier: str, slot: str, data: bytes) -> dict[str, Any]:
    """Stores an image of a team, a shirt side, its editor document or a sponsor.

    Args:
        identifier: The team, the built-in AI included.
        slot: One of `IMAGE_SLOTS`.
        data: The image, PNG, JPEG or WebP, or for an `-edit` slot the editor's JSON document.

    Returns:
        The team's new entry.

    Raises:
        ArgumentError: If the team or slot is unknown, or the data is too large or of another kind.
    """
    entry(identifier)
    _choice(slot, IMAGE_SLOTS, _field('image_slot'))
    if len(data) > _MAXIMUM_IMAGE_BYTES:
        raise MessageError('server.teams.image_size', size=len(data))
    suffix = _image_suffix(slot, data)
    folder = _meta_path(identifier).parent
    with _LOCK:
        old = _image_file(folder, slot)
        _replace(folder / f'{slot}{suffix}', data)
        if old is not None and old.name != f'{slot}{suffix}':
            old.unlink()
    return entry(identifier)


def image_path(identifier: str, slot: str) -> Path | None:
    """Returns the file of a team's image slot, or `None`."""
    if slot not in IMAGE_SLOTS:
        return None
    if identifier != BUILTIN and not _home.valid_identifier(identifier):
        return None
    return _image_file(_meta_path(identifier).parent, slot)


def remove_image(identifier: str, slot: str) -> bool:
    """Deletes a team's image slot and returns whether it held an image."""
    path = image_path(identifier, slot)
    if path is None:
        return False
    path.unlink()
    return True


def _sound_file(folder: Path, slot: str, names: set[str] | None = None) -> Path | None:
    """Returns the file of a sound slot of a team's folder, of any of its extensions, or `None`.

    Only `sound-` and the slot with an extension of `_SOUND_SUFFIXES`, in that case, names it.
    """
    names = _names(folder) if names is None else names
    for suffix in _SOUND_SUFFIXES:
        path = _exact(folder, f'sound-{slot}{suffix}', names)
        if path is not None:
            return path
    return None


def _wav_whole(data: bytes) -> bool:
    """Returns whether a RIFF WAVE file holds a format chunk the page reads and some samples."""
    offset, form, samples = 12, None, False
    while offset + 8 <= len(data):
        kind = data[offset : offset + 4]
        size = int.from_bytes(data[offset + 4 : offset + 8], 'little')
        body = data[offset + 8 : offset + 8 + size]
        if kind == b'fmt ' and len(body) >= 16:
            tag = int.from_bytes(body[0:2], 'little')
            channels = int.from_bytes(body[2:4], 'little')
            rate = int.from_bytes(body[4:8], 'little')
            bits = int.from_bytes(body[14:16], 'little')
            form = tag in (1, 3, 0xFFFE) and 0 < channels <= 8 and 8000 <= rate <= 192000
            form = form and bits in (8, 16, 24, 32)
        elif kind == b'data':
            samples = len(body) > 0
        offset += 8 + size + (size & 1)
    return bool(form) and samples


def _mp3_frame(data: bytes, offset: int) -> bool:
    """Returns whether a valid MPEG audio frame header starts at `offset`."""
    if offset + 4 > len(data) or data[offset] != 0xFF or data[offset + 1] & 0xE0 != 0xE0:
        return False
    version = (data[offset + 1] >> 3) & 3
    layer = (data[offset + 1] >> 1) & 3
    bitrate = data[offset + 2] >> 4
    rate = (data[offset + 2] >> 2) & 3
    return version != 1 and layer != 0 and bitrate not in (0, 15) and rate != 3


def _sound_suffix(data: bytes) -> str:
    """Returns the extension of a sound's bytes, or raises `ArgumentError` for another kind.

    Each kind is read past its first bytes, so a file that only starts like a sound is refused.
    A WAV file holds a format chunk the page reads and a data chunk of samples, an Ogg file starts
    with a page of Vorbis, Opus or FLAC, and an MP3 file holds a valid frame header after its tag.
    """
    if data.startswith(b'OggS'):
        segments = data[26] if len(data) > 26 else 0
        packet = data[27 + segments : 27 + segments + 8]
        if data[4:5] == b'\0' and packet.startswith((b'\x01vorbis', b'OpusHead', b'\x7fFLAC')):
            return '.ogg'
        raise MessageError('server.teams.sound_damaged', kind='Ogg')
    if data[:4] == b'RIFF' and data[8:12] == b'WAVE':
        if _wav_whole(data):
            return '.wav'
        raise MessageError('server.teams.sound_damaged', kind='WAV')
    if data.startswith(b'ID3') and len(data) >= 10:
        size = 0
        for byte in data[6:10]:
            size = size << 7 | (byte & 0x7F)
        start = 10 + size + (10 if data[5] & 0x10 else 0)
        # Padding may sit between the tag and the first frame.
        if any(_mp3_frame(data, at) for at in range(start, min(len(data), start + 4096))):
            return '.mp3'
        raise MessageError('server.teams.sound_damaged', kind='MP3')
    # A bare MP3 file starts with its first frame and holds more than one header's worth.
    if _mp3_frame(data, 0) and len(data) >= 128:
        return '.mp3'
    raise MessageError('server.teams.sound_type')


def set_sound(identifier: str, slot: str, data: bytes) -> dict[str, Any]:
    """Stores a sound of a team, which the page plays when one of its players does that.

    Args:
        identifier: The team, the built-in AI included.
        slot: One of `SOUND_SLOTS`.
        data: The sound, Ogg, MP3 or WAV, of at most 2 MB.

    Returns:
        The team's new entry.

    Raises:
        ArgumentError: If the team or slot is unknown, or the data is too large or of another kind.
    """
    entry(identifier)
    _choice(slot, SOUND_SLOTS, _field('sound_slot'))
    if len(data) > _MAXIMUM_SOUND_BYTES:
        raise MessageError('server.teams.sound_size', size=len(data))
    suffix = _sound_suffix(data)
    folder = _meta_path(identifier).parent
    with _LOCK:
        old = _sound_file(folder, slot)
        _replace(folder / f'sound-{slot}{suffix}', data)
        if old is not None and old.name != f'sound-{slot}{suffix}':
            old.unlink()
    return entry(identifier)


def sound_path(identifier: str, slot: str) -> Path | None:
    """Returns the file of a team's sound slot, or `None`."""
    if slot not in SOUND_SLOTS:
        return None
    if identifier != BUILTIN and not _home.valid_identifier(identifier):
        return None
    return _sound_file(_meta_path(identifier).parent, slot)


def remove_sound(identifier: str, slot: str) -> bool:
    """Deletes a team's sound slot and returns whether it held a sound."""
    path = sound_path(identifier, slot)
    if path is None:
        return False
    path.unlink()
    return True


# The joints of GRF's skeleton that a model may map. Only `body`, the pelvis, is required, so a
# simple rig without elbows or knees maps what it has, and its bones follow their parents.
JOINTS = (
    'body',
    'middle',
    'neck',
    'left_shoulder',
    'left_elbow',
    'right_shoulder',
    'right_elbow',
    'left_thigh',
    'left_knee',
    'left_ankle',
    'right_thigh',
    'right_knee',
    'right_ankle',
)
_MODEL = 'model.glb'
_MAXIMUM_MODEL_BYTES = 30 * 1024 * 1024


def _array(value: Any) -> list[Any]:
    """Returns a value of a glTF document that should be an array, or an empty one if it is not."""
    return value if isinstance(value, list) else []


def _skin_joints(data: bytes) -> set[str]:
    """Returns the names of the joints of every skin of a binary glTF 2.0 file.

    Raises:
        ArgumentError: If the bytes are no binary glTF 2.0 file or hold no skin.
    """
    # glTF: a binary file opens with `glTF`, the version, the length and a JSON chunk.
    if len(data) < 20 or data[:4] != b'glTF':
        raise MessageError('server.teams.model.binary')
    version, length = struct.unpack_from('<II', data, 4)
    chunk_length, chunk_type = struct.unpack_from('<II', data, 12)
    if version != 2 or length > len(data) or chunk_type != 0x4E4F534A:
        raise MessageError('server.teams.model.json_first')
    try:
        document = json.loads(data[20 : 20 + chunk_length])
    except (ValueError, RecursionError) as error:
        raise MessageError('server.teams.model.json', error=error) from error
    if not isinstance(document, dict):
        raise MessageError('server.teams.model.json_object')
    for kind in ('buffers', 'images'):
        for item in _array(document.get(kind)):
            uri = item.get('uri') if isinstance(item, dict) else None
            if isinstance(uri, str) and not uri.startswith('data:'):
                raise MessageError('server.teams.model.link', uri=repr(uri))
    nodes = _array(document.get('nodes'))
    skins = _array(document.get('skins'))
    if not skins:
        raise MessageError('server.teams.model.rigged')
    names = set()
    for skin in skins:
        joints = _array(skin.get('joints')) if isinstance(skin, dict) else []
        for joint in joints:
            if (
                isinstance(joint, int)
                and 0 <= joint < len(nodes)
                and isinstance(nodes[joint], dict)
            ):
                names.add(str(nodes[joint].get('name', '')))
    return names


def set_model(identifier: str, data: bytes, joints: dict[str, str]) -> dict[str, Any]:
    """Gives a team a player model of its own and returns the team's new entry.

    Args:
        identifier: The team, the built-in AI included.
        data: The binary glTF 2.0 file, with a skinned mesh.
        joints: The bone of the model that each joint of GRF's skeleton drives, `body` always and
            any other joint of `JOINTS` or `player` that the rig has.

    Raises:
        ArgumentError: If the file is too large, is no rigged binary glTF file, or the mapping
            lacks `body` or names a bone outside the model's skins.
    """
    current = entry(identifier)
    if len(data) > _MAXIMUM_MODEL_BYTES:
        raise MessageError('server.teams.model.size', size=len(data))
    bones = _skin_joints(data)
    if not isinstance(joints, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in joints.items()
    ):
        raise MessageError('server.teams.model.joints', joints=repr(joints))
    if 'body' not in joints:
        raise MessageError('server.teams.model.body')
    unknown = [joint for joint in joints if joint not in (*JOINTS, 'player')]
    if unknown:
        raise MessageError('server.teams.model.unknown_joints', joints=', '.join(unknown))
    absent = [bone for bone in joints.values() if bone not in bones]
    if absent:
        raise MessageError('server.teams.model.missing_bones', bones=', '.join(map(str, absent)))
    folder = _meta_path(identifier).parent
    _replace(folder / _MODEL, data)
    current['model'] = {
        'joints': {key: str(value) for key, value in joints.items()},
        'bytes': len(data),
    }
    current['style']['model'] = 'custom'
    _write(identifier, current)
    return current


def remove_model(identifier: str) -> bool:
    """Takes a team's own player model away and returns whether it had one."""
    current = entry(identifier)
    path = _exact(_meta_path(identifier).parent, _MODEL)
    if path is None:
        return False
    path.unlink()
    had = True
    current['model'] = None
    if current['style']['model'] == 'custom':
        current['style']['model'] = 'grf'
    _write(identifier, current)
    return had


def model_path(identifier: str) -> Path | None:
    """Returns the file of a team's player model, or `None`."""
    if identifier != BUILTIN and not _home.valid_identifier(identifier):
        return None
    return _exact(_meta_path(identifier).parent, _MODEL)


def _replace(path: Path, data: bytes) -> None:
    """Writes `path` through a temporary file of its own, so no reader sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix='.part')
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def _write(identifier: str, current: dict[str, Any]) -> None:
    """Writes a team's entry, without the fields the folder implies."""
    stored = {key: value for key, value in current.items() if key not in _IMPLIED}
    _replace(_meta_path(identifier), json.dumps(stored).encode())


# Kits whose shirts lie closer than this in RGB look alike on the pitch.
_CLASH = 120


def scenario_size(scenario: str) -> int | None:
    """Returns the players a side of a full-match scenario, 5 or 11, or `None` for the others."""
    for size in (5, 11):
        if scenario.startswith(f'{size}_vs_{size}'):
            return size
    return None


def check_ability(ability: Any) -> tuple[float | None, float | None]:
    """Returns a pair of abilities, each a number from 0 to 1 or `None` for the scenario's.

    Raises:
        ArgumentError: If `ability` is no pair, or a value is no number from 0 to 1.
    """
    if not isinstance(ability, (list, tuple)) or len(ability) != 2:
        raise MessageError('server.teams.ability_pair', ability=repr(ability))
    pair = []
    for value in ability:
        if value is None:
            pair.append(None)
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise MessageError('server.teams.ability', value=repr(value))
        pair.append(float(value))
    return (pair[0], pair[1])


def _check_size(team: dict[str, Any], scenario: str) -> None:
    """Checks that a team plays a full-match scenario of its own size, 5v5 or 11v11.

    Raises:
        ArgumentError: If the scenario is a full match of the other size.
    """
    size = scenario_size(scenario.removeprefix('benchmark_full_game_'))
    if size is not None and size != FORMATS[team['format']]:
        raise MessageError(
            'server.teams.scenario_format',
            format=team['format'],
            team=shown_name(team),
            scenario=_messages.scenario(scenario),
        )


def check_scenario(teams_: list[dict[str, Any]], scenario: str) -> None:
    """Checks the format, count, selected players and goalkeeper on each scenario side."""
    for side, team in enumerate(teams_):
        if team['kind'] == 'builtin':
            continue
        _check_size(team, scenario)
        control = check_control(team.get('control'), team['format'])
        try:
            selected_players(control, scenario_players(scenario, side))
        except ArgumentError as error:
            raise MessageError(
                'server.teams.cannot_play',
                team=shown_name(team),
                scenario=_messages.scenario(scenario),
                reason=_reason(error),
            ) from error


def challenge_fit(team: dict[str, Any], scenario: str, side: int = 0) -> dict[str, Any]:
    """Returns how a team plays its side of a challenge's scenario, with any extra players out.

    A challenge's scenario may hold fewer controllable players than a team controls, as an academy
    drill does for a team trained for full games. The team's extra players are then out, as a
    selected player off the pitch after a red card is, and the team plays the players that the
    scenario has. With dynamic assignment the team plays as many agents as the side has
    controllable players. With fixed assignment the players of its selection that the side holds
    play, each found as before, and the others are out, while the built-in AI plays the side's
    players outside the selection, its goalkeeper among them. The policy is still called in its
    own form, one observation for each player it controls, and a player out sees the observation
    of the team's first player that plays, whose answer for the player out counts for nothing.

    Args:
        team: The registry entry, or the entry of a policy with its control.
        scenario: The challenge's scenario.
        side: The side the team plays, 0 for the left one.

    Returns:
        `agents`, the engine agents of the side, `players`, the players the team controls,
        `playing`, those that play, `slots`, the place among the players that play of each player
        the team controls in the order of its submission, `None` for a player out, or `None`
        itself when every player plays, and `selected`, the formation indices of the players of a
        fixed assignment that play, or `None` for dynamic assignment.

    Raises:
        ArgumentError: If the scenario is a full match of the other size, or the team cannot play
            the side, such as a fixed selection of which the side holds no player.
    """
    if team['kind'] == 'builtin':
        return {'agents': 0, 'players': 0, 'playing': 0, 'slots': None, 'selected': None}
    _check_size(team, scenario)
    control = check_control(team.get('control'), team['format'])
    formation = scenario_players(scenario, side)
    available = [index for index, player in enumerate(formation) if player.controllable]
    count = control['players']

    def refused(error: BaseException) -> MessageError:
        return MessageError(
            'server.teams.cannot_play',
            team=shown_name(team),
            scenario=_messages.scenario(scenario),
            reason=_reason(error),
        )

    if control['assignment'] == 'dynamic':
        if count <= len(available):
            try:
                selected_players(control, formation)
            except ArgumentError as error:
                raise refused(error) from error
            return {
                'agents': count,
                'players': count,
                'playing': count,
                'slots': None,
                'selected': None,
            }
        if not available:
            raise refused(MessageError('server.teams.control.too_few', count=0))
        playing = len(available)
        slots = [*range(playing), *[None] * (count - playing)]
        return {
            'agents': playing,
            'players': count,
            'playing': playing,
            'slots': slots,
            'selected': None,
        }
    chosen: list[int] = []
    slots: list[int | None] = []
    for item in control['selection']:
        candidates = (
            [item]
            if type(item) is int
            else [index for index in available if formation[index].role == ROLES.index(item)]
        )
        found = next((i for i in candidates if i in available and i not in chosen), None)
        slots.append(None if found is None else len(chosen))
        if found is not None:
            chosen.append(found)
    if None not in slots:
        try:
            selected = selected_players(control, formation)
        except ArgumentError as error:
            raise refused(error) from error
        return {
            'agents': len(available),
            'players': count,
            'playing': count,
            'slots': None,
            'selected': selected,
        }
    if not chosen:
        raise refused(MessageError('server.teams.control.none_present'))
    keeper = [index for index, player in enumerate(formation) if player.role == 0]
    if control['goalkeeper'] in ('builtin', 'scenario') and any(i in keeper for i in chosen):
        raise refused(MessageError('server.teams.control.goalkeeper_outside'))
    return {
        'agents': len(available),
        'players': count,
        'playing': len(chosen),
        'slots': slots,
        'selected': chosen,
    }


def game_agents(teams_: list[dict[str, Any]], scenario: str, humans: Any) -> list[int]:
    """Returns the agents of the team on each side of a game that people play, after checks.

    A side without a person belongs to its team, the built-in AI or a submission, as in a requested
    match. A side with a person takes its team as the person's teammates, a submission with dynamic
    assignment whose players join the person's one, so the side needs one controllable player more
    than the team asks for.

    Raises:
        ArgumentError: If a team cannot play its side of the scenario, or a team beside a person
            uses fixed assignment or asks for more players than the side has left.
    """
    check_scenario(teams_, scenario)
    agents = []
    for side, team in enumerate(teams_):
        count = agent_count(team, scenario, side)
        if humans[side] and count:
            control = check_control(team.get('control'), team['format'])
            if control['assignment'] != 'dynamic':
                raise MessageError('server.teams.beside_dynamic', team=shown_name(team))
            available = sum(player.controllable for player in scenario_players(scenario, side))
            if count + 1 > available:
                raise MessageError(
                    'server.teams.beside_count',
                    team=shown_name(team),
                    scenario=_messages.scenario(scenario),
                    count=available,
                )
        agents.append(count)
    return agents


def match_teams(left: str, right: str) -> list[dict[str, Any]]:
    """Returns the two teams of a match as a recording's header holds them.

    The right team plays in its away kit, its shirt and shorts colors swapped with its trim, when
    its shirt would look like the left team's, as a team of the same registry entry always does.
    """
    teams = [header_team(left), header_team(right)]
    first, second = teams[0]['style']['kit'], teams[1]['style']['kit']
    distance = sum((a - b) ** 2 for a, b in zip(first['primary'], second['primary'], strict=True))
    if distance < _CLASH**2:
        kit = dict(second)
        kit['primary'], kit['secondary'] = second['secondary'], second['primary']
        kit['shorts'], kit['socks'] = second['socks'], second['shorts']
        if sum((a - b) ** 2 for a, b in zip(first['primary'], kit['primary'], strict=True)) < (
            _CLASH**2
        ):
            kit['primary'] = [255 - value for value in first['primary']]
        teams[1] = {
            **teams[1],
            'color': kit['primary'],
            'secondary': kit['secondary'],
            'style': {**teams[1]['style'], 'kit': kit},
            'away': True,
        }
    return teams


def header_team(identifier: str) -> dict[str, Any]:
    """Returns a team as a recording's header holds it, with its identifier, name and style."""
    team = entry(identifier)
    kit = team['style']['kit']
    return {
        'id': team['id'],
        **_messages.named('name', shown_name(team)),
        'format': team['format'],
        'control': team.get('control', dict(DEFAULT_CONTROL)),
        'color': kit['primary'],
        'secondary': kit['secondary'],
        'style': team['style'],
    }


def folder_bundle(files: list[tuple[str, bytes]]) -> bytes:
    """Returns the bytes of a submission folder as the page uploads it.

    Args:
        files: The path of each file relative to the folder, with `/` between parts, and its bytes.
    """
    index = json.dumps([{'path': path, 'size': len(data)} for path, data in files]).encode()
    return (
        FOLDER_MAGIC + struct.pack('<I', len(index)) + index + b''.join(data for _, data in files)
    )


def _unbundle(data: bytes, target: Path) -> None:
    """Writes the files of a folder bundle into `target`, without the folder's own name.

    A browser names each file of a chosen folder with the folder in front, such as
    `submission/main.py`, so a single top folder above `main.py` is dropped.
    """
    if len(data) < len(FOLDER_MAGIC) + 4:
        raise MessageError('server.teams.folder.short')
    (length,) = struct.unpack_from('<I', data, len(FOLDER_MAGIC))
    start = len(FOLDER_MAGIC) + 4
    try:
        index = json.loads(data[start : start + length])
    except ValueError as error:
        raise MessageError('server.teams.folder.index', error=error) from error
    if not isinstance(index, list) or len(index) > _MAXIMUM_FILES:
        raise MessageError('server.teams.folder.index_list')
    paths = [_check_member(str(entry['path'])) for entry in index]
    tops = {path.parts[0] for path in paths if len(path.parts) > 1}
    if (
        PurePosixPath(_MAIN) not in paths
        and len(tops) == 1
        and all(len(p.parts) > 1 for p in paths)
    ):
        paths = [PurePosixPath(*path.parts[1:]) for path in paths]
    position = start + length
    for path, entry in zip(paths, index, strict=True):
        size = int(entry['size'])
        if size < 0 or position + size > len(data):
            raise MessageError('server.teams.folder.files')
        destination = _inside(target, path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data[position : position + size])
        position += size


def _extract(data: bytes, filename: str, target: Path) -> None:
    """Writes a submission into `target`, a folder bundle, a Python file or an archive."""
    lower = filename.lower()
    if data.startswith(FOLDER_MAGIC):
        _unbundle(data, target)
    elif lower.endswith('.py'):
        (target / _MAIN).write_bytes(data)
    elif lower.endswith(('.tar.gz', '.tgz', '.tar')):
        _untar(data, target)
    elif lower.endswith('.zip'):
        # zipfile reads every entry of the central directory as it opens, so their count comes
        # first, from the bytes alone.
        _check_unpacked(_zip_entries(data), 0)
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except (zipfile.BadZipFile, OSError, ValueError, EOFError) as error:
            raise MessageError('server.teams.archive.zip', error=error) from error
        with archive:
            members = archive.infolist()
            _check_unpacked(len(members), sum(member.file_size for member in members))
            for member in members:
                _inside(target, _check_member(member.filename))
            archive.extractall(target)
    else:
        raise MessageError('server.teams.submission.kind', filename=repr(filename))
    if not (target / _MAIN).is_file():
        raise MessageError('server.teams.submission.main_top', main=_MAIN)


class _Bounded:
    """The bytes of a tar archive after decompression, read within limits.

    No read or move goes past `_MAXIMUM_TAR_BYTES` from the start. While `scanning` holds, the
    reads after each move, which are the headers of one member, take at most
    `_MAXIMUM_TAR_HEADER` bytes, so a long name, pax records or a sparse map never grows without
    end. tarfile moves past the bytes of each member to its next header, so the bytes of the
    members are never read while it scans.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._start = 0
        self.scanning = True

    def tell(self) -> int:
        return self._inner.tell()

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence != 0 or offset > _MAXIMUM_TAR_BYTES:
            raise MessageError('server.teams.archive.limits')
        self._start = offset
        return self._inner.seek(offset)

    def read(self, size: int = -1) -> bytes:
        end = _MAXIMUM_TAR_BYTES
        if self.scanning:
            end = min(end, self._start + _MAXIMUM_TAR_HEADER)
        if size is None or size < 0 or self._inner.tell() + size > end:
            raise MessageError('server.teams.archive.limits')
        return self._inner.read(size)


def _decompressed(data: bytes) -> Any:
    """Returns a file of a tar archive's bytes, decompressed as they are read when compressed.

    gzip, bzip2 and xz are told apart by their first bytes, as tarfile tells them apart.
    """
    stream = io.BytesIO(data)
    if data.startswith(b'\x1f\x8b'):
        return gzip.GzipFile(fileobj=stream, mode='rb')
    if data.startswith(b'BZh'):
        return bz2.BZ2File(stream)
    if data.startswith(b'\xfd7zXZ\x00') and lzma is not None:
        return lzma.LZMAFile(stream)
    return stream


def _untar(data: bytes, target: Path) -> None:
    """Writes the members of a tar archive into `target`, after checking every one of them.

    The members are read one at a time and counted against the limits of an archive as they come,
    so a small compressed archive of a great many members, or of members that claim a great size,
    is refused at the first member past a limit, before any member is written.
    """
    stream = _Bounded(_decompressed(data))
    unreadable = (tarfile.TarError, EOFError, OSError, zlib.error, RecursionError, *_LZMA_ERRORS)
    try:
        archive = tarfile.open(fileobj=stream, mode='r:')
    except unreadable as error:
        raise MessageError('server.teams.archive.tar', error=error) from error
    with archive:
        count = size = 0
        try:
            while (member := archive.next()) is not None:
                count += 1
                size += member.size
                _check_unpacked(count, size)
                _inside(target, _check_member(member.name))
                if not (member.isfile() or member.isdir()):
                    raise MessageError('server.teams.archive.plain', member=member.name)
        except unreadable as error:
            raise MessageError('server.teams.archive.tar', error=error) from error
        stream.scanning = False
        try:
            # Python 3.12, 3.11.4 and 3.10.12 brought the data filter. Older versions write each
            # member without its mode, owner or times, and the checks above cover the rest.
            if hasattr(tarfile, 'data_filter'):
                archive.extractall(target, filter='data')
            else:
                for member in archive.getmembers():
                    archive.extract(member, target, set_attrs=False)
        except (tarfile.TarError, EOFError, zlib.error, *_LZMA_ERRORS) as error:
            raise MessageError('server.teams.archive.tar', error=error) from error


def _zip_entries(data: bytes) -> int:
    """Returns at least as many entries as the central directory of a zip file can hold.

    Every entry that zipfile reads from the central directory starts with the signature of an
    entry, and no two overlap, so the signatures of the whole file bound the entries, whichever end
    record and zip64 record a version of zipfile trusts.
    """
    return data.count(b'PK\x01\x02')


def add_folder(
    folder: str | Path,
    name: str | None = None,
    format: str = '11v11',
    control: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stores a submission folder or archive as a new team and returns its entry.

    Args:
        folder: A submission folder, submission file or exported archive.
        name: The name of the team, by default the folder's name.
        format: `5v5` or `11v11`, the size of the team for competition.
        control: The players that the submission controls, as `check_control` takes them, or
            `None` for the active player alone, or for the setting of an exported folder.
    """
    folder = Path(folder)
    if folder.is_file():
        return add(name or '', folder.name, folder.read_bytes(), format, control)
    if not folder.is_dir():
        raise ArgumentError(
            f'expected a submission folder or archive, found nothing at {str(folder)!r}'
        )
    if not (folder / _MAIN).is_file():
        raise MessageError(
            'server.teams.submission.main_folder', main=_MAIN, folder=repr(str(folder))
        )
    # A link inside the folder could point anywhere, such as at a key of the user's, and its
    # target would then travel with every export of the team, so links are left out and logged.
    paths = []
    for root, folders, names in os.walk(folder):
        here = Path(root)
        for item in [*folders, *names]:
            if (here / item).is_symlink():
                _LOGGER.warning(
                    'cuju render leaves out %s of the submission folder, since it is a link',
                    (here / item).relative_to(folder).as_posix(),
                )
        folders[:] = [item for item in folders if item != '__pycache__']
        paths += [here / item for item in names if not (here / item).is_symlink()]
    files = [
        (path.relative_to(folder).as_posix(), path.read_bytes())
        for path in sorted(paths)
        if path.is_file()
    ]
    return add(name or folder.resolve().name, folder.name, folder_bundle(files), format, control)


def _check_member(name: str) -> PurePosixPath:
    """Returns an archive member's path, refusing one that could land outside the team's folder.

    Windows reads `D:name` as a path on another drive and a backslash as a separator, so a part
    may hold neither a colon, a backslash nor a null, whatever system unpacks it. A part that
    opens a device on Windows, or ends in a dot or a space, is refused on every system too, so a
    submission imports alike everywhere.
    """
    path = PurePosixPath(name)
    if (
        not name
        or not path.parts
        or path.is_absolute()
        or any(part in ('', '.', '..') or any(c in part for c in ':\\\0') for part in path.parts)
    ):
        raise MessageError('server.teams.archive.outside', member=repr(name))
    if any(_device(part) for part in path.parts):
        raise MessageError('server.teams.archive.device', member=repr(name))
    return path


def _device(part: str) -> bool:
    """Returns whether a part of a path opens a device on Windows or names another file there.

    Windows reads the part before the first dot, without the spaces at its end, as a device's
    name, and drops the dots and spaces at the end of a part, so `nul.txt`, `con .py` and
    `main.py.` all name something else than they seem.
    """
    return part.endswith(('.', ' ')) or bool(_DEVICES.fullmatch(part.split('.')[0].rstrip(' ')))


def _inside(target: Path, path: PurePosixPath) -> Path:
    """Returns `target / path`, refusing it unless it resolves inside `target`."""
    destination = target.joinpath(*path.parts)
    if not destination.resolve().is_relative_to(target.resolve()):
        raise MessageError('server.teams.archive.outside', member=repr(str(path)))
    return destination


def _check_unpacked(count: int, size: int) -> None:
    """Refuses an archive of too many files or too large once unpacked."""
    if count > _MAXIMUM_FILES or size > _MAXIMUM_UNPACKED:
        raise MessageError('server.teams.archive.limits')


def add(
    name: str,
    filename: str,
    data: bytes,
    format: str = '11v11',
    control: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stores a Kaggle submission as a new team and returns its entry.

    Args:
        name: The name that the page and recordings show.
        filename: The name of the uploaded file, whose extension says how to read it.
        data: The file's bytes.
        format: `5v5` or `11v11`, the size of the team for competition, which decides the
            scenarios it plays and the length of its roster.
        control: The players that the submission controls, as `check_control` takes them, or
            `None` for the active player alone, or for the setting of an exported folder.

    Raises:
        ArgumentError: If the submission is too large, of another kind, holds no `main.py` or
            the control does not fit the format.
    """
    if len(data) > _MAXIMUM_BYTES:
        raise MessageError('server.teams.submission.size', size=len(data))
    _choice(format, tuple(FORMATS), _field('format'))
    if control is not None:
        check_control(control, format)
    name_given = bool(name and name.strip())
    name = _printable((name or '').strip() or Path(filename).stem.strip() or 'team').strip()[:80]
    identifier, folder = _new_folder()
    # Every failure after the folder is made removes it, so no half imported folder, with the
    # unchecked team file of an archive, is ever left for the list of teams to read.
    try:
        try:
            _extract(data, filename, folder)
        except OSError as error:
            raise MessageError('server.teams.submission.unpack', error=error) from error
        entry = {
            'id': identifier,
            'name': name,
            'kind': 'kaggle',
            'created': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'format': format,
            'style': default_style(format, _new_kit()),
            'model': None,
        }
        # A folder exported from the page brings its format, style, images and model along, each
        # checked as an upload is. Whatever fails a check is set aside under a name that the page
        # never reads, and the other files of the folder stay as they came.
        try:
            _import(folder / TEAM_FOLDER, entry, name_given)
        except ArgumentError:
            raise
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
            raise MessageError('server.teams.submission.unpack', error=error) from error
        if control is not None:
            entry['control'] = check_control(control, entry['format'])
        completed = _complete(entry)
        _write(identifier, completed)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return completed


def _new_folder() -> tuple[str, Path]:
    """Creates the folder of a new team and returns its identifier and path.

    Identifiers sort by the second they are made in, so teams added in the same second differ by
    their random end alone. Creating the folder claims the identifier, and a draw that is taken
    is drawn again.
    """
    while True:
        identifier = _home.new_identifier('t')
        folder = _home.folder('teams') / identifier
        try:
            folder.mkdir()
        except FileExistsError:
            continue
        return identifier, folder


def set_aside(path: Path, reason: str) -> None:
    """Renames a file of an imported `cuju-team` folder that fails its checks, and logs why.

    The file keeps its bytes under its name followed by `.rejected`, which the page never reads,
    so the team plays without it and the owner still finds it in the folder.
    """
    target = path.with_name(f'{path.name}{_REJECTED}')
    count = 1
    while target.exists() or target.is_symlink():
        count += 1
        target = path.with_name(f'{path.name}.{count}{_REJECTED}')
    try:
        path.rename(target)
    except OSError as error:
        _LOGGER.warning('cuju render leaves out %s of an imported team, %s', path.name, error)
        return
    _LOGGER.warning(
        'cuju render sets aside %s of an imported team as %s, since %s',
        path.name,
        target.name,
        reason,
    )


def _kept(path: Path) -> bool:
    """Returns whether a file of an imported `cuju-team` folder may stay, and removes it if not.

    A link could point outside the team's folder and a name such as `con.txt` opens a device on
    Windows, so either is removed, the link alone and never what it points to, and logged. Every
    other file stays.
    """
    if path.is_symlink():
        reason = 'it is a link'
    elif _device(path.name):
        reason = 'its name opens a device on Windows or ends in a dot or a space'
    else:
        return True
    _LOGGER.warning('cuju render removes %s of an imported team, since %s', path.name, reason)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)
    return False


def _near_slot(name: str) -> bool:
    """Returns whether a name that no slot reads starts as the file of an image, sound or model."""
    lower = name.lower()
    if lower.endswith(_REJECTED):
        return False
    starts = [f'{slot}.' for slot in IMAGE_SLOTS] + [f'sound-{slot}.' for slot in SOUND_SLOTS]
    return lower == _MODEL or lower.startswith(tuple(starts))


def _import(team_folder: Path, entry: dict[str, Any], name_given: bool) -> None:
    """Takes the format, style, images and model of an exported team into `entry`."""
    if not team_folder.is_dir():
        return
    saved: dict[str, Any] = {}
    with contextlib.suppress(OSError, ValueError):
        saved = _read_entry(team_folder / 'team.json')
    if isinstance(saved.get('format'), str) and saved['format'] in FORMATS:
        entry['format'] = saved['format']
    with contextlib.suppress(ArgumentError, TypeError, KeyError, AttributeError, ValueError):
        entry['control'] = check_control(saved.get('control'), entry['format'])
    with contextlib.suppress(ArgumentError, TypeError, KeyError, AttributeError, ValueError):
        # A team file that names no kit keeps the kit the new team took in turn, so teams of
        # such files differ as teams added on the page do.
        base = default_style(entry['format'], (entry.get('style') or {}).get('kit'))
        entry['style'] = _resize(
            style(_known(saved.get('style') or {}, base), base, _model_names()), entry['format']
        )
        if isinstance((saved.get('style') or {}).get('players'), list):
            entry['style']['players'] = _players(
                saved['style']['players'][: FORMATS[entry['format']]],
                entry['style']['players'],
                _model_names(),
            )
    name = _printable(saved['name']).strip()[:80] if isinstance(saved.get('name'), str) else ''
    if not name_given and name:
        entry['name'] = name
    for path in list(team_folder.iterdir()):
        slot, suffix = path.stem, path.suffix
        if path.name in ('team.json', _MODEL, 'clips', 'presentation') or not _kept(path):
            continue
        sound = slot.startswith('sound-')
        served = (sound and slot[len('sound-') :] in SOUND_SLOTS and suffix in _SOUND_SUFFIXES) or (
            not sound and slot in IMAGE_SLOTS and suffix in _IMAGE_SUFFIXES
        )
        if not served:
            # A name that differs from a slot's file only in its case, or holds more after the
            # slot, is set aside, so no system that finds names whatever their case reads it.
            if _near_slot(path.name):
                set_aside(path, 'its name is close to the name of a file the page reads')
            continue
        # A file that the page would read as an image or a sound is checked as an upload is, and
        # one that fails is set aside. Every other file stays as the submission brought it.
        try:
            data = path.read_bytes()
            if sound:
                valid = len(data) <= _MAXIMUM_SOUND_BYTES and _sound_suffix(data) == suffix
            else:
                valid = len(data) <= _MAXIMUM_IMAGE_BYTES and _image_suffix(slot, data) == suffix
        except Exception:
            # A file that fails any part of its check, however it fails, counts as failing.
            valid = False
        if not valid:
            set_aside(path, 'it fails the checks of an upload')
    from .._packages import presentation as _presentation
    from . import clips as _clips

    _clips.import_folder(team_folder)
    _presentation.import_folder(team_folder)
    model = team_folder / _MODEL
    joints = (
        (saved.get('model') or {}).get('joints') if isinstance(saved.get('model'), dict) else None
    )
    try:
        data = model.read_bytes()
        if len(data) > _MAXIMUM_MODEL_BYTES:
            raise MessageError('server.teams.model.too_large')
        # A model without joints in team.json takes those the team editor guesses from its bones.
        from . import joints as _joints

        joints, guessed = _joints.resolve(joints, _skin_joints(data))
        entry['model'] = {'joints': joints, 'bytes': len(data)}
        style_saved = saved.get('style')
        if guessed and not (style_saved.get('model') if isinstance(style_saved, dict) else None):
            entry['style']['model'] = 'custom'
    except Exception:
        if model.exists() or model.is_symlink():
            set_aside(model, 'it fails the checks of an uploaded model')
        entry['model'] = None
        if entry['style'].get('model') == 'custom':
            entry['style']['model'] = 'grf'


def duplicate(identifier: str) -> dict[str, Any]:
    """Copies a registered submission as a new team and returns the copy's entry.

    The copy takes the submission's files, its format, controls, style, roster, images, sounds and
    model as they were last saved, under the name of the team followed by `copy`, and from then on
    each team changes alone.

    Raises:
        ArgumentError: If the team is unknown or is the built-in AI, which has no files to copy.
    """
    team = entry(identifier)
    if team['kind'] == 'builtin':
        raise MessageError('server.teams.duplicate_builtin')
    filename, data = export(identifier)
    return add(f'{team["name"]} copy', filename, data, team['format'])


def export(identifier: str) -> tuple[str, bytes]:
    """Returns a team as a zip of its submission folder, with its `cuju-team` folder inside.

    The archive holds `main.py` and the submission's files at its top, as Kaggle reads them, and
    `cuju-team` with the team's format, style, images and model, which the page reads back when
    the folder is uploaded again. The built-in AI exports only its `cuju-team` folder.

    Returns:
        A file name for the archive and its bytes.
    """
    team = entry(identifier)
    root = _meta_path(identifier).parent.parent
    meta = _meta_path(identifier)
    stored = {key: value for key, value in team.items() if key not in _IMPLIED}
    from .._packages import presentation as _presentation

    # A package's files go out only as they pass their check again.
    failing = _presentation.left_out(root) if root.is_dir() else set()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f'{TEAM_FOLDER}/team.json', json.dumps(stored))
        for path in sorted(root.rglob('*')) if root.is_dir() else []:
            if (
                path.is_file()
                and path != meta
                and path not in failing
                and not path.name.endswith('.part')
                and '__pycache__' not in path.parts
            ):
                archive.write(path, path.relative_to(root).as_posix())
    safe = ''.join(character if character.isalnum() else '-' for character in team['name'])
    return f'{safe.strip("-") or "team"}.zip', buffer.getvalue()


def remove(identifier: str) -> bool:
    """Deletes a team's folder and returns whether it existed.

    The built-in AI stays, and removing it only resets its name, style, model and images.
    """
    if identifier == BUILTIN:
        shutil.rmtree(_meta_path(BUILTIN).parent.parent, ignore_errors=True)
        return True
    if not _home.valid_identifier(identifier):
        return False
    folder = _home.folder('teams') / identifier
    if not folder.is_dir():
        return False
    shutil.rmtree(folder)
    return True


def entry(identifier: str) -> dict[str, Any]:
    """Returns the entry of a team, or raises `ArgumentError` for an unknown one."""
    for team in teams():
        if team['id'] == identifier:
            return team
    raise MessageError('server.teams.unknown', identifier=repr(identifier))


def load_agent(identifier: str) -> Any:
    """Loads a submission's agent function as Kaggle does, the last callable its `main.py` defines.

    The agent runs from its folder, which comes first on `sys.path`, as on Kaggle, so its own
    modules import and its working files resolve. The modules it imports from its folder leave
    `sys.modules` afterwards, so a second submission with modules of the same names gets its own.
    """
    folder = _home.folder('teams') / identifier
    main = folder / _MAIN
    if not _home.valid_identifier(identifier) or not main.is_file():
        raise MessageError('server.teams.unknown_kaggle', identifier=repr(identifier))
    module = types.ModuleType(f'cuju_team_{identifier.replace("-", "_")}')
    module.__file__ = str(main)
    with _from_folder(folder):
        before = set(sys.modules)
        # Kaggle: `get_last_callable` runs the file and takes the last callable it defined. The
        # bytes go to `compile`, so the file's own encoding line or UTF-8 decides how it reads.
        exec(compile(main.read_bytes(), str(main), 'exec'), module.__dict__)
        resolved = folder.resolve()
        for name in set(sys.modules) - before:
            origin = getattr(sys.modules[name], '__file__', None)
            if origin and Path(origin).resolve().is_relative_to(resolved):
                del sys.modules[name]
    callables = [value for value in module.__dict__.values() if callable(value)]
    if not callables:
        raise MessageError('server.teams.agent_function', identifier=repr(identifier))
    agent = callables[-1]

    @functools.wraps(agent)
    def run(*arguments: Any) -> Any:
        with _from_folder(folder):
            return agent(*arguments)

    return run


@contextlib.contextmanager
def _from_folder(folder: Path) -> Any:
    """Runs a block from a submission's folder, first on `sys.path`, as Kaggle runs an agent."""
    previous = os.getcwd()
    sys.path.insert(0, str(folder))
    os.chdir(folder)
    try:
        yield
    finally:
        os.chdir(previous)
        with contextlib.suppress(ValueError):
            sys.path.remove(str(folder))
