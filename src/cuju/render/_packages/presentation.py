# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The presentation package of a team, what the page shows of it beyond its kit and roster.

A team package may carry the folder `presentation` in its `cuju-team` folder, with the manifest
`presentation.json` of the presentation contract and the files it names, models, clips, textures,
shaders, sounds and a worker module, in subfolders as the author likes. The contract, version 1.1,
is described in docs/presentation.md, and a package of 1.0 reads as it is. Everything here is
presentation alone, the engine never reads it, so a match plays bit for bit the same with or
without a package.

The manifest and every file are checked when a team is imported and again when it is exported and
served, as the other files of a team are. A part of the manifest that fails its check is left out
with a warning, and the page draws that part as it would without a package. A manifest of a newer
contract stays on disk untouched and the page draws the team in its stock look.

The names of events, reflex actions, effects, sound and features live in `_vocabulary`, apart
from this stable core, since later renderer work adds to them.

Developer mode serves the package of a team from a folder of the user's own choosing, read afresh
on every request, so an author sees each change at once. It is off unless the file
`developer.json` in the renderer's home names such a folder, and an imported archive never turns
it on.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import itertools
import json
import re
import struct
from pathlib import Path, PurePosixPath
from typing import Any

from cuju.errors import ArgumentError

from .._registry import teams as _teams
from .._store import home as _home
from . import glsl as _glsl
from . import vocabulary as _vocabulary

CONTRACT = '1.1'
MAJOR, MINOR = 1, 1
FOLDER = 'presentation'
MANIFEST = 'presentation.json'
DEVELOPER_FILE = 'developer.json'
SIDES_FILE = 'presentation-sides.json'
SIDES = ('left', 'right')

MAXIMUM_MANIFEST_BYTES = 256 * 1024
MAXIMUM_FILES = 256
MAXIMUM_TOTAL_BYTES = 80 * 1024 * 1024
MAXIMUM_DEPTH = 4
# The largest file of each kind, by its extension.
MAXIMUM_BYTES = {
    '.glb': 30 * 1024 * 1024,
    '.png': 16 * 1024 * 1024,
    '.jpg': 16 * 1024 * 1024,
    '.webp': 16 * 1024 * 1024,
    '.ktx2': 30 * 1024 * 1024,
    '.ogg': 16 * 1024 * 1024,
    '.mp3': 16 * 1024 * 1024,
    '.wav': 30 * 1024 * 1024,
    '.js': 2 * 1024 * 1024,
    '.json': 2 * 1024 * 1024,
    '.glsl': 256 * 1024,
    '.wasm': 8 * 1024 * 1024,
}
CONTENT_TYPES = {
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
# One part of a file's path inside the package, lowercase.
_PART = re.compile(r'[a-z0-9][a-z0-9_.-]{0,59}')
_DEVICES = re.compile(r'(con|prn|aux|nul|com[0-9]|lpt[0-9])', re.IGNORECASE)
_ID = re.compile(r'[A-Za-z0-9_.-]{1,40}')
# The pieces of JavaScript that `module_problem` tells apart, to find imports and re-exports.
_LINE_ENDS = '\n\r\u2028\u2029'
_NUMBER = re.compile(
    r'0[xXoObB][0-9a-fA-F_]*n?|(?:\d[\d_]*\.?[\d_]*|\.\d[\d_]*)(?:[eE][+-]?[\d_]*)?n?'
)
_ESCAPE = re.compile(r'\\u(?:\{([0-9a-fA-F]{1,6})\}|([0-9a-fA-F]{4}))')
_PUNCTUATORS = ('>>>=', '...', '=>', '++', '--')
# The words after which a slash starts a regular expression rather than a division.
_BEFORE_REGEX = frozenset(
    (
        'return',
        'typeof',
        'instanceof',
        'in',
        'of',
        'new',
        'delete',
        'void',
        'throw',
        'case',
        'do',
        'else',
        'yield',
        'await',
        'extends',
    )
)
# The words of a statement whose head in parentheses a regular expression may follow.
_HEADS = frozenset(('if', 'while', 'for', 'with'))
_DOTS = (('punct', '.'), ('punct', '?.'))

DRIVERS = ('grf', 'grf+layers', 'team', 'worker')
ROOT_MOTION = ('ignore', 'cosmetic')
# The semantic roles a clip may play.
ROLES = (
    'idle.calm',
    'idle.alert',
    'move',
    'turn',
    'brake',
    'kick',
    'pass.short',
    'pass.long',
    'pass.high',
    'shot',
    'header',
    'volley',
    'slide',
    'trip',
    'catch',
    'parry',
    'dive.left',
    'dive.right',
    'throwIn',
    'restart.kickoff',
    'restart.goal_kick',
    'restart.free_kick',
    'restart.corner',
    'restart.throw_in',
    'restart.penalty',
    'trap',
    'deflect',
    'celebration',
    'reaction.win',
    'reaction.loss',
    'lineup',
    'salute',
    'lament',
    'recovery',
    'podium',
)
BEHAVIOURS = (
    'spin',
    'oscillate',
    'spring',
    'lookAt',
    'bank',
    'follow',
    'curve',
    'materialParam',
    'audioParam',
    'lightParam',
)
CHANNELS = ('x', 'y', 'z', 'rotX', 'rotY', 'rotZ', 'scale')
INPUTS = (
    'speed',
    'accel',
    'ballDistance',
    'excitement',
    'ceremony.amount',
    'ballX.attack',
    'alert',
)
CLOCKS = ('sim', 'cosmetic', 'ceremony')
QUALITIES = ('low', 'medium', 'high')
_SECTIONS = (
    'contract',
    'name',
    'requires',
    'prefers',
    'models',
    'rig',
    'clips',
    'behaviours',
    'materials',
    'effects',
    'audio',
    'reflexes',
    'worker',
    'reducedMotion',
    'quality',
    'lights',
    'post',
    'overlays',
)


def words(values: Any, last: str = 'or') -> str:
    """Returns names as a list in words, such as `spin, oscillate or curve`."""
    values = [str(value) for value in values]
    if len(values) < 2:
        return ''.join(values)
    return f'{", ".join(values[:-1])} {last} {values[-1]}'


def _number(value: Any, low: float, high: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ArgumentError(f'expected {name} from {low} to {high}, found {value!r}')
    return float(value)


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ArgumentError(f'expected {name} of up to 40 letters, digits, dots and underscores')
    return value


def _text(value: Any, name: str, size: int = 80) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= size:
        raise ArgumentError(f'expected {name} of 1 to {size} characters, found {value!r}')
    return _teams._printable(value)


def _vector(value: Any, size: int, limit: float, name: str) -> list[float]:
    if not isinstance(value, list) or len(value) != size:
        raise ArgumentError(f'expected {name} as {size} numbers')
    return [_number(v, -limit, limit, name) for v in value]


def _mapping(value: Any, size: int, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or len(value) > size:
        raise ArgumentError(f'expected {name} as a mapping of at most {size} entries')
    return value


def _ignored(spec: dict[str, Any], known: set[str], what: str, warnings: list[str]) -> None:
    warnings.extend(f'{what} ignores {key}' for key in sorted(set(spec) - known))


def _files(assets: dict[str, str]) -> Any:
    """Returns a check that a value names a file of the package of one of the given kinds."""

    def check(value: Any, name: str, suffixes: tuple[str, ...] | None = None) -> str:
        if not isinstance(value, str) or value not in assets:
            raise ArgumentError(f'expected {name} to name a file of the package, found {value!r}')
        if suffixes and PurePosixPath(value).suffix not in suffixes:
            raise ArgumentError(f'expected {name} to name a {"/".join(suffixes)} file')
        return value

    return check


def _selector(value: Any, name: str) -> dict[str, Any]:
    spec = _mapping(value, 3, f'the selector of {name}')
    out: dict[str, Any] = {}
    if 'role' in spec:
        if spec['role'] not in ('goalkeeper', 'outfield'):
            raise ArgumentError(f'expected the role of {name} as goalkeeper or outfield')
        out['role'] = spec['role']
    for key in ('number', 'index'):
        if key in spec:
            items = spec[key] if isinstance(spec[key], list) else [spec[key]]
            if not all(isinstance(i, int) and not isinstance(i, bool) for i in items):
                raise ArgumentError(f'expected the {key} of {name} as integers')
            out[key] = items
    if set(spec) - {'role', 'number', 'index'}:
        raise ArgumentError(f'expected {name} to select by role, number or index')
    return out


def _models(value: Any, file: Any) -> dict[str, Any]:
    spec = _mapping(value, 3, 'models')
    out: dict[str, Any] = {}
    for role in ('outfield', 'goalkeeper'):
        if role in spec:
            out[role] = file(spec[role], f'the {role} model', ('.glb',))
    if 'byNumber' in spec:
        numbers = _mapping(spec['byNumber'], 100, 'models by number')
        out['byNumber'] = {}
        for number, path in numbers.items():
            if not str(number).isdigit() or not 0 <= int(number) <= 99:
                raise ArgumentError(f'expected shirt numbers from 0 to 99, found {number!r}')
            out['byNumber'][str(int(number))] = file(path, f'model {number}', ('.glb',))
    if set(spec) - {'outfield', 'goalkeeper', 'byNumber'}:
        raise ArgumentError('expected models by outfield, goalkeeper and byNumber')
    return out


def _socket(name: str, spec: Any, warnings: list[str]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ArgumentError(f'expected socket {name} as a description')
    item: dict[str, Any] = {
        'node': _text(spec['node'], 'a node name') if spec.get('node') else None,
        'offset': _vector(spec.get('offset', [0, 0, 0]), 3, 10, 'a socket offset'),
        'forward': _vector(spec.get('forward', [0, 0, 1]), 3, 1e3, 'a forward axis'),
        'up': _vector(spec.get('up', [0, 1, 0]), 3, 1e3, 'an up axis'),
        'rotation': _vector(spec.get('rotation', [0, 0, 0]), 3, 360, 'a socket rotation'),
    }
    forward, up = item['forward'], item['up']
    if sum(c * c for c in forward) < 1e-12:
        raise ArgumentError(f'expected socket {name} to have a forward axis')
    cross = [
        up[1] * forward[2] - up[2] * forward[1],
        up[2] * forward[0] - up[0] * forward[2],
        up[0] * forward[1] - up[1] * forward[0],
    ]
    if sum(c * c for c in cross) < 1e-12:
        raise ArgumentError(f'expected socket {name} to have up apart from forward')
    _ignored(spec, {'node', 'offset', 'forward', 'up', 'rotation'}, f'socket {name}', warnings)
    return item


def _rig(value: Any, file: Any, warnings: list[str]) -> dict[str, Any]:
    spec = _mapping(value, 16, 'rig')
    out: dict[str, Any] = {}
    driver = spec.get('driver', 'grf')
    if isinstance(driver, str):
        driver = {'outfield': driver, 'goalkeeper': driver}
    if not isinstance(driver, dict) or not all(
        role in ('outfield', 'goalkeeper') and d in DRIVERS for role, d in driver.items()
    ):
        raise ArgumentError(f'expected the drivers of the roles among {words(DRIVERS)}')
    out['driver'] = dict(driver)
    out['sockets'] = {}
    for name, socket in _mapping(spec.get('sockets', {}), 64, 'sockets').items():
        try:
            out['sockets'][_identifier(name, 'the name of a socket')] = _socket(
                name, socket, warnings
            )
        except ArgumentError as error:
            warnings.append(f'socket {name} left out, {error}')
    if 'bounds' in spec:
        bounds = _mapping(spec['bounds'], 4, 'bounds')
        out['bounds'] = {
            'radius': _number(bounds.get('radius'), 0.05, 5, 'the bounds radius'),
            'height': _number(bounds.get('height'), 0.2, 8, 'the bounds height'),
        }
        for key, high in (('top', 8), ('clearance', 2)):
            if key in bounds:
                out['bounds'][key] = _number(bounds[key], 0, high, f'the bounds {key}')
    out['rootMotion'] = spec.get('rootMotion', 'ignore')
    if out['rootMotion'] not in ROOT_MOTION:
        raise ArgumentError(f'expected root motion among {words(ROOT_MOTION)}')
    if 'blend' in spec:
        out['blend'] = _number(spec['blend'], 0.01, 2, 'the blend time')
    if 'joints' in spec:
        joints = _mapping(spec['joints'], 16, 'joints')
        if not all(
            n in (*_teams.JOINTS, 'player') and isinstance(b, str) for n, b in joints.items()
        ):
            raise ArgumentError('expected joints that map GRF nodes to bone names')
        out['joints'] = dict(joints)
    out['attachments'] = {}
    for name, item in _mapping(spec.get('attachments', {}), 32, 'attachments').items():
        try:
            if not isinstance(item, dict):
                raise ArgumentError('expected a description')
            socket = item.get('socket', 'root')
            if socket != 'root' and socket not in out['sockets']:
                raise ArgumentError('expected a socket of the rig')
            entry = {
                'file': file(item.get('file'), f'attachment {name}', ('.glb',)),
                'socket': socket,
                'offset': _vector(item.get('offset', [0, 0, 0]), 3, 10, 'an offset'),
                'rotation': _vector(item.get('rotation', [0, 0, 0]), 3, 360, 'a rotation'),
                'scale': _number(item.get('scale', 1), 0.01, 10, 'a scale'),
                'shadows': bool(item.get('shadows', True)),
            }
            if 'when' in item:
                entry['when'] = _selector(item['when'], f'attachment {name}')
            out['attachments'][_identifier(name, 'the name of an attachment')] = entry
        except ArgumentError as error:
            warnings.append(f'attachment {name} left out, {error}')
    if 'ik' in spec:
        out['ik'] = {}
        for name, item in _mapping(spec['ik'], 8, 'ik chains').items():
            try:
                out['ik'][_identifier(name, 'the name of a chain')] = _chain(item, out['sockets'])
            except ArgumentError as error:
                warnings.append(f'ik chain {name} left out, {error}')
    if 'layers' in spec:
        if not isinstance(spec['layers'], list) or len(spec['layers']) > 8:
            raise ArgumentError('expected the layers of the rig as a list of at most 8')
        out['layers'] = []
        for index, item in enumerate(spec['layers'], 1):
            try:
                out['layers'].append(_layer(item))
            except ArgumentError as error:
                warnings.append(f'layer {index} left out, {error}')
    known = {
        'driver',
        'sockets',
        'bounds',
        'rootMotion',
        'blend',
        'joints',
        'attachments',
        'ik',
        'layers',
    }
    _ignored(spec, known, 'rig', warnings)
    return out


def _bones(value: Any, low: int, high: int, what: str) -> list[str]:
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise ArgumentError(f'expected {what} as {low} to {high} bone names')
    return [_text(bone, 'a bone name') for bone in value]


def _chain(item: Any, sockets: dict[str, Any]) -> dict[str, Any]:
    """Checks one chain of the reach of section 7.2, solved by FABRIK toward the ball."""
    if not isinstance(item, dict):
        raise ArgumentError('expected a description')
    out: dict[str, Any] = {
        'chain': _bones(item.get('chain'), 2, 8, 'the chain'),
        'target': 'ball',
        'window': _number(item.get('window', 0.15), 0, 0.5, 'the window'),
        'weight': _number(item.get('weight', 1), 0, 1, 'the weight'),
        'iterations': int(_number(item.get('iterations', 8), 1, 16, 'the iterations')),
    }
    if item.get('target', 'ball') != 'ball':
        raise ArgumentError('expected the chain to reach the ball')
    if 'socket' in item:
        if item['socket'] not in sockets:
            raise ArgumentError('expected the socket of the chain among the sockets of the rig')
        out['socket'] = item['socket']
    if 'roles' in item:
        roles = item['roles'] if isinstance(item['roles'], list) else [item['roles']]
        if not all(role in ROLES for role in roles):
            raise ArgumentError('expected the roles of the chain among the clip roles')
        out['roles'] = roles
    if 'when' in item:
        out['when'] = _selector(item['when'], 'the chain')
    return out


def _layer(item: Any) -> dict[str, Any]:
    """Checks one layer of the driver grf+layers, a clip over the bones of its mask."""
    if not isinstance(item, dict) or not ('role' in item or 'clip' in item):
        raise ArgumentError('expected a layer with a role or a clip')
    out: dict[str, Any] = {'mask': _bones(item.get('mask'), 1, 32, 'the mask')}
    if 'role' in item:
        if item['role'] not in ROLES:
            raise ArgumentError('expected the role of the layer among the clip roles')
        out['role'] = item['role']
    if 'clip' in item:
        out['clip'] = _text(item['clip'], 'the clip of the layer')
    out['weight'] = _curve(item.get('weight', 1), 'the weight of the layer')
    out['rate'] = _number(item.get('rate', 1), 0.05, 8, 'the rate of the layer')
    return out


def _clip(value: Any, name: str) -> dict[str, Any]:
    if isinstance(value, str):
        value = {'clip': value}
    if not isinstance(value, dict):
        raise ArgumentError(f'expected {name} as a clip name or a description of one')
    out: dict[str, Any] = {'clip': _text(value.get('clip'), f'the clip of {name}')}
    for key, low, high in (('speed', 0, 15), ('stride', 0.05, 50), ('rate', 0.05, 8)):
        if key in value:
            out[key] = _number(value[key], low, high, f'the {key} of {name}')
    return out


def _clips(value: Any, warnings: list[str]) -> dict[str, Any]:
    spec = _mapping(value, len(ROLES) + 16, 'clips')
    out: dict[str, Any] = {}
    for role, entry in spec.items():
        if role not in ROLES:
            warnings.append(f'clips ignore the unknown role {role}')
            continue
        if isinstance(entry, dict) and entry.get('space') == 'speed':
            items = entry.get('clips')
            if not isinstance(items, list) or not 0 < len(items) <= 8:
                raise ArgumentError(f'expected one to eight clips in the speed space of {role}')
            space = []
            for item in items:
                if isinstance(item, list) and 2 <= len(item) <= 3:
                    item = {
                        'clip': item[0],
                        'speed': item[1],
                        **({'stride': item[2]} if len(item) > 2 else {}),
                    }
                space.append(_clip(item, role))
            out[role] = {'space': 'speed', 'clips': sorted(space, key=lambda c: c.get('speed', 0))}
            continue
        entries = entry if isinstance(entry, list) else [entry]
        if not 0 < len(entries) <= 8:
            raise ArgumentError(f'expected one to eight clips for {role}')
        out[role] = [_clip(item, role) for item in entries]
    return out


def _curve(value: Any, name: str) -> Any:
    """Checks a curve, a number or the keys of one input of the entity, or a sum of curves."""
    if not isinstance(value, dict):
        return _number(value, -1e4, 1e4, name)
    if 'sum' in value:
        if not isinstance(value['sum'], list) or not 0 < len(value['sum']) <= 8:
            raise ArgumentError(f'expected the sum of {name} as one to eight curves')
        return {'sum': [_curve(part, name) for part in value['sum']]}
    source = value.get('input')
    if not isinstance(source, str) or not (
        source in INPUTS
        or re.fullmatch(r'jointSpeed:.{1,80}', source)
        or re.fullmatch(r'role:[a-z.]{1,40}', source)
    ):
        inputs = words([*INPUTS, 'jointSpeed', 'role'])
        raise ArgumentError(f'expected an input of {name} among {inputs}')
    out: dict[str, Any] = {'input': source}
    if 'keys' in value:
        keys = value['keys']
        if not isinstance(keys, list) or not 0 < len(keys) <= 32:
            raise ArgumentError(f'expected the keys of {name} as 1 to 32 points')
        points = [_vector(key, 2, 1e6, f'a key of {name}') for key in keys]
        if any(b[0] <= a[0] for a, b in itertools.pairwise(points)):
            raise ArgumentError(f'expected the keys of {name} in rising order')
        out['keys'] = points
    return out


def _behaviour_name(spec: Any, index: int) -> str:
    """Returns how messages name a behaviour, by its id or by its place counted from 1."""
    identifier = spec.get('id') if isinstance(spec, dict) else None
    return f'behaviour {identifier if isinstance(identifier, str) else index + 1}'


def behaviour(spec: Any, index: int = 0) -> dict[str, Any]:
    """Checks one persistent behaviour of section 7.5 and returns it.

    Args:
        spec: The behaviour as the manifest or a worker gives it.
        index: Its place in the list from 0, which names it in messages from 1 when it has no id.

    Raises:
        ArgumentError: If the behaviour is of an unknown type or holds a value out of range.
    """
    name = _behaviour_name(spec, index)
    if not isinstance(spec, dict) or spec.get('type') not in BEHAVIOURS:
        found = spec.get('type') if isinstance(spec, dict) else spec
        raise ArgumentError(f'expected {name} of a type among {words(BEHAVIOURS)}, found {found!r}')
    kind = spec['type']
    out: dict[str, Any] = dict(spec)
    out['id'] = _identifier(spec.get('id', f'{kind}{index}'), 'the id of a behaviour')
    if 'weight' in spec:
        out['weight'] = _curve(spec['weight'], name)
    if 'when' in spec:
        out['when'] = _selector(spec['when'], name)
    if 'node' in spec:
        out['node'] = _text(spec['node'], f'the node of {name}')
    if 'attachment' in spec:
        out['attachment'] = _identifier(spec['attachment'], f'the attachment of {name}')
    seed = spec.get('seed', 'entity')
    if seed not in ('entity', 'number', 'index') and not (
        isinstance(seed, int) and not isinstance(seed, bool) and 0 <= seed < 2**31
    ):
        raise ArgumentError(f'expected the seed of {name} as entity, number, index or an integer')
    if 'channel' in spec and spec['channel'] not in CHANNELS:
        raise ArgumentError(f'expected the channel of {name} among {words(CHANNELS)}')
    for key in ('rate', 'amp', 'freq', 'offset', 'goal', 'gain', 'value'):
        if key in spec:
            out[key] = _curve(spec[key], name)
    if kind == 'spin':
        if not any(key in spec for key in ('node', 'clip', 'attachment')):
            raise ArgumentError(f'expected {name} to turn a node, an attachment or a clip')
        if spec.get('phaseFrom', 'cosmetic') not in ('cosmetic', 'distance', 'both'):
            raise ArgumentError(f'expected the phase of {name} from cosmetic, distance or both')
        if 'axis' in spec:
            out['axis'] = _vector(spec['axis'], 3, 1e3, f'the axis of {name}')
    elif kind in ('lookAt', 'follow'):
        if 'node' not in spec:
            raise ArgumentError(f'expected the node of {name}')
        target = spec.get('target', 'ball')
        if target not in ('ball', 'subject', 'camera') and not re.fullmatch(r'p\d+', str(target)):
            raise ArgumentError(f'expected {name} to follow the ball, the subject or the camera')
    elif kind == 'curve':
        keys = spec.get('keys')
        if not isinstance(keys, list) or not 1 < len(keys) <= 64:
            raise ArgumentError(f'expected the keys of {name} as 2 to 64 points')
        out['keys'] = [_vector(key, 2, 1e6, f'a key of {name}') for key in keys]
        if spec.get('clock', 'cosmetic') not in CLOCKS:
            raise ArgumentError(f'expected the clock of {name} among {words(CLOCKS)}')
    elif kind == 'materialParam' and not spec.get('uniform'):
        raise ArgumentError(f'expected the uniform of {name}')
    elif kind == 'audioParam' and not (spec.get('processor') and spec.get('param')):
        raise ArgumentError(f'expected the processor and parameter of {name}')
    elif kind == 'lightParam' and not (
        spec.get('light') and spec.get('param', 'intensity') in ('intensity', 'distance')
    ):
        raise ArgumentError(
            f'expected the light and the parameter, intensity or distance, of {name}'
        )
    for key in ('stiffness', 'damping', 'mass', 'limit', 'slew', 'pitchLimit', 'smoothing'):
        if key in spec:
            out[key] = _number(spec[key], 0, 1e4, f'the {key} of {name}')
    return out


def _behaviours(value: Any, warnings: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 64:
        raise ArgumentError('expected behaviours as a list of at most 64')
    out = []
    for index, spec in enumerate(value):
        try:
            out.append(behaviour(spec, index))
        except ArgumentError as error:
            warnings.append(f'{_behaviour_name(spec, index)} left out, {error}')
    if len({item['id'] for item in out}) != len(out):
        raise ArgumentError('expected behaviours of distinct ids')
    return out


def _materials(value: Any, file: Any, warnings: list[str]) -> dict[str, Any]:
    spec = _mapping(value, 64, 'materials')
    out = {}
    for name, item in spec.items():
        _identifier(name, 'the name of a material')
        if not isinstance(item, dict):
            raise ArgumentError(f'expected material {name} as a description')
        entry = dict(item)
        if 'shader' in item:
            entry['shader'] = file(item['shader'], f'the shader of {name}', ('.glsl',))
            entry.update(_shader_entry(item, name, file))
        if 'when' in item:
            entry['when'] = _selector(item['when'], f'material {name}')
        for key in ('baseColor', 'emissive'):
            if key in item:
                color = item[key]
                if (
                    not isinstance(color, list)
                    or len(color) != 3
                    or not all(isinstance(c, int) and 0 <= c <= 255 for c in color)
                ):
                    raise ArgumentError(f'expected the {key} of {name} as three integers')
        for key, high in (
            ('roughness', 1),
            ('metalness', 1),
            ('opacity', 1),
            ('emissiveIntensity', 10),
        ):
            if key in item:
                entry[key] = _number(item[key], 0, high, f'the {key} of {name}')
        out[name] = entry
    return out


_UNIFORM = re.compile(r'[a-z][A-Za-z0-9_]{0,30}')


def _uniform(key: Any, value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) != {'seed'} or value['seed'] not in ('entity', 'number', 'index'):
            raise ArgumentError(f'expected the seed of uniform {key} by entity, number or index')
        return {'seed': value['seed']}
    if isinstance(value, list):
        if not 2 <= len(value) <= 4:
            raise ArgumentError(f'expected uniform {key} of two to four numbers')
        return _vector(value, len(value), 1e6, f'uniform {key}')
    return _number(value, -1e6, 1e6, f'uniform {key}')


def _shader_entry(item: dict[str, Any], name: str, file: Any) -> dict[str, Any]:
    """Checks the mode, uniforms, textures and options of the custom shader of a material."""
    out: dict[str, Any] = {'mode': item.get('mode', 'chunks')}
    if out['mode'] not in _glsl.MODES:
        raise ArgumentError(f'expected the mode of the shader of {name} among {words(_glsl.MODES)}')
    out['uniforms'] = {}
    for key, value in _mapping(item.get('uniforms', {}), 16, f'the uniforms of {name}').items():
        if not _UNIFORM.fullmatch(str(key)):
            raise ArgumentError(f'expected the uniforms of {name} to start with a small letter')
        out['uniforms'][key] = _uniform(key, value)
    out['textures'] = {}
    for key, path in _mapping(item.get('textures', {}), 4, f'the textures of {name}').items():
        if not _UNIFORM.fullmatch(str(key)):
            raise ArgumentError(f'expected the textures of {name} to start with a small letter')
        out['textures'][key] = file(path, f'texture {key}', ('.png', '.jpg', '.webp', '.ktx2'))
    for key, choices in (
        ('blending', ('additive', 'normal')),
        ('side', ('front', 'back', 'double')),
    ):
        if key in item:
            if item[key] not in choices:
                raise ArgumentError(f'expected the {key} of {name} among {words(choices)}')
            out[key] = item[key]
    for key in ('transparent', 'depthWrite'):
        if key in item:
            out[key] = bool(item[key])
    return out


def _shaders(out: dict[str, Any], assets: dict[str, str], warnings: list[str]) -> None:
    """Leaves out every part whose shader fails the static checks of `_glsl`, with a warning."""
    cache: dict[tuple[str, str], list[str]] = {}

    def failed(path: str, mode: str, what: str) -> bool:
        if (path, mode) not in cache:
            source = Path(assets.get(path, ''))
            try:
                cache[path, mode] = _glsl.check(source.read_text('utf-8'), mode)
            except UnicodeDecodeError as error:
                cache[path, mode] = [f'could not be read, {error}']
            except OSError:
                # A check of a manifest away from its files, as the pack tools make, leaves the
                # shaders to the checks that read them.
                cache[path, mode] = []
        found = cache[path, mode]
        warnings.extend(f'{what} left out, {path} of mode {mode} {p}' for p in found[:4])
        return bool(found)

    for name, item in list(out.get('materials', {}).items()):
        mode = item.get('mode', 'chunks')
        if item.get('shader') and failed(item['shader'], mode, f'material {name}'):
            del out['materials'][name]
    for name, item in list(out.get('effects', {}).items()):
        if item.get('shader') and failed(item['shader'], 'material', f'effect {name}'):
            del out['effects'][name]
    layer = (out.get('post') or {}).get('layer')
    if layer and layer.get('shader') and failed(layer['shader'], 'material', 'the layer pass'):
        del out['post']
    programs = _glsl.programs(out)
    if programs > _glsl.BUDGET['low']:
        warnings.append(f'the package compiles {programs} shader programs, low quality keeps 8')


def _quality(value: Any) -> dict[str, Any]:
    spec = _mapping(value, 3, 'quality')
    out = {}
    for level, item in spec.items():
        if level not in QUALITIES or not isinstance(item, dict):
            raise ArgumentError(f'expected quality by {words(QUALITIES)}')
        drop = item.get('drop', [])
        if not isinstance(drop, list) or not all(isinstance(d, str) and len(d) <= 60 for d in drop):
            raise ArgumentError('expected what a quality drops as a list of names')
        out[level] = {'drop': list(drop)}
    return out


def supported(version: Any) -> bool:
    """Returns whether a contract version is one this renderer serves, 1.0 and 1.1."""
    match = re.fullmatch(r'(\d+)\.(\d+)', str(version)) if isinstance(version, str) else None
    return bool(match) and int(match.group(1)) == MAJOR and int(match.group(2)) <= MINOR


def check(
    document: Any, assets: dict[str, str], warnings: list[str] | None = None
) -> dict[str, Any]:
    """Checks a manifest against the files of its package and returns it as the page reads it.

    A section that fails its check is left out with a warning, so the page draws that part as it
    would without a package.

    Args:
        document: The manifest as read from JSON.
        assets: The files of the package, each path inside the folder to its path on disk.
        warnings: A list that collects what the check left out.

    Raises:
        ArgumentError: If the document is no manifest or names a contract this renderer lacks.
    """
    warnings = warnings if warnings is not None else []
    if not isinstance(document, dict):
        raise ArgumentError('expected a presentation manifest, a JSON object')
    version = document.get('contract')
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+', version):
        raise ArgumentError('expected contract to give the version of the manifest, such as 1.0')
    if not supported(version):
        raise ArgumentError(f'expected a manifest of contract {CONTRACT}, found contract {version}')
    file = _files(assets)
    out: dict[str, Any] = {'contract': version}
    warnings.extend(f'the manifest ignores {key}' for key in sorted(set(document) - set(_SECTIONS)))

    def section(key: str, read: Any) -> None:
        if key not in document:
            return
        try:
            out[key] = read(document[key])
        except (ArgumentError, OSError, TypeError, ValueError, KeyError) as error:
            warnings.append(f'{key} left out, {error}')

    section('name', lambda value: _text(value, 'the name of the package'))
    section('requires', lambda value: _vocabulary.features(value, 'requires'))
    section('prefers', lambda value: _vocabulary.features(value, 'prefers'))
    section('models', lambda value: _models(value, file))
    section('rig', lambda value: _rig(value, file, warnings))
    section('clips', lambda value: _clips(value, warnings))
    section('behaviours', lambda value: _behaviours(value, warnings))
    section('materials', lambda value: _materials(value, file, warnings))
    section('effects', lambda value: _vocabulary.effects(value, file, warnings))
    section('audio', lambda value: _vocabulary.audio(value, file, warnings))
    sockets = (out.get('rig') or {}).get('sockets', {})
    section('lights', lambda value: _vocabulary.lights(value, sockets, warnings))
    section('post', lambda value: _vocabulary.post(value, file))
    section('overlays', _vocabulary.overlays)
    _shaders(out, assets, warnings)
    names = {
        'cues': (out.get('audio') or {}).get('cues', {}),
        'music': (out.get('audio') or {}).get('music', {}),
        'effects': out.get('effects', {}),
        'files': set(assets),
    }
    section('reflexes', lambda value: _vocabulary.reflexes(value, names, warnings))
    section('worker', lambda value: file(value, 'the worker', ('.js',)))
    section(
        'reducedMotion',
        lambda value: {
            'amplitude': _number(
                _mapping(value, 4, 'reducedMotion').get('amplitude', 0.3), 0, 1, 'the amplitude'
            )
        },
    )
    section('quality', _quality)
    return out


def missing(manifest: dict[str, Any]) -> list[str]:
    """Returns the features a manifest requires that this renderer lacks."""
    return [f for f in manifest.get('requires', []) if f not in _vocabulary.FEATURES]


def _glb(data: bytes) -> None:
    """Raises `ArgumentError` for bytes that are no self-contained binary glTF 2.0 file."""
    if len(data) < 20 or data[:4] != b'glTF':
        raise ArgumentError('expected a binary glTF file')
    version, length = struct.unpack_from('<II', data, 4)
    size, kind = struct.unpack_from('<II', data, 12)
    if version != 2 or length != len(data) or kind != 0x4E4F534A or 20 + size > len(data):
        raise ArgumentError('expected a whole binary glTF 2.0 file')
    try:
        document = json.loads(data[20 : 20 + size])
    except (ValueError, UnicodeDecodeError) as error:
        raise ArgumentError(f'expected the JSON chunk of a glTF file, found {error}') from error
    if not isinstance(document, dict):
        raise ArgumentError('expected the JSON chunk of a glTF file to hold an object')
    from .._registry import clips as _clips

    if _clips._uris(document):
        raise ArgumentError('expected a self-contained file')
    if any(name in _clips._UNSUPPORTED for name in document.get('extensionsRequired') or []):
        raise ArgumentError('expected a file without an extension that the page cannot read')


def check_path(name: str) -> str:
    """Returns the path of a file inside a package, or raises `ArgumentError` for a bad one."""
    parts = name.split('/') if isinstance(name, str) else []
    if len(parts) > MAXIMUM_DEPTH:
        raise ArgumentError(
            f'expected a file in at most {MAXIMUM_DEPTH - 1} folders of the package, found '
            f'{name!r} in {len(parts) - 1}'
        )
    if (
        not parts
        or not all(_PART.fullmatch(part) and '..' not in part for part in parts)
        or any(_DEVICES.fullmatch(part.split('.')[0]) for part in parts)
    ):
        raise ArgumentError(
            'expected a path of lowercase letters, digits, dots, dashes and underscores, found '
            f'{name!r}'
        )
    if PurePosixPath(name).suffix not in MAXIMUM_BYTES:
        raise ArgumentError(
            f'expected a known kind of file, {", ".join(MAXIMUM_BYTES)}, found {name!r}'
        )
    return name


def _js_name(text: str, i: int) -> tuple[str, int] | None:
    """Reads the name at `i` with its escapes decoded, and returns it and the offset past it."""
    out = []
    j = i
    if text[j] == '#':
        out.append('#')
        j += 1
    while j < len(text):
        c = text[j]
        if c == '\\':
            match = _ESCAPE.match(text, j)
            code = int(match.group(1) or match.group(2), 16) if match else 0x110000
            if code > 0x10FFFF:
                return None
            out.append(chr(code))
            j = match.end()
        elif c in '$\u200c\u200d' or ('a' + c).isidentifier():
            out.append(c)
            j += 1
        else:
            break
    return ''.join(out), j


def _quoted(text: str, i: int) -> int:
    """Returns the offset past the string that opens at `i`, or -1 for one left open."""
    quote = text[i]
    j = i + 1
    while j < len(text):
        c = text[j]
        if c == '\\':
            j += 3 if text.startswith('\r\n', j + 1) else 2
        elif c == quote:
            return j + 1
        elif c in '\n\r':
            return -1
        else:
            j += 1
    return -1


def _regex(text: str, i: int) -> int:
    """Returns the offset past the regular expression that opens at `i`, or -1 for one left open."""
    j = i + 1
    inside = False
    while j < len(text):
        c = text[j]
        if c in _LINE_ENDS:
            return -1
        if c == '\\':
            if j + 1 < len(text) and text[j + 1] in _LINE_ENDS:
                return -1
            j += 2
            continue
        if c == '[':
            inside = True
        elif c == ']':
            inside = False
        elif c == '/' and not inside:
            flags = _js_name(text, j + 1) if j + 1 < len(text) else None
            return flags[1] if flags else j + 1
        j += 1
    return -1


def _template(text: str, i: int) -> tuple[int, bool]:
    """Reads the text of a template from `i` to its end or to a substitution.

    Returns the offset past what it read, -1 for a template left open, and whether a
    substitution opens there.
    """
    j = i
    while j < len(text):
        c = text[j]
        if c == '\\':
            j += 2
        elif c == '`':
            return j + 1, False
        elif text.startswith('${', j):
            return j + 2, True
        else:
            j += 1
    return -1, False


def _tokens(text: str) -> list[tuple[str, str]] | str:
    """Splits a module into the tokens that `module_problem` reads, or returns what stops it.

    Comments go, and strings, templates, regular expressions and numbers stay as one token of
    their kind without their text, so only words and punctuators keep their value.
    """
    tokens: list[tuple[str, str]] = []
    # Each open brace, `brace`, or open substitution of a template, `template`.
    braces: list[str] = []
    # Each open parenthesis, and whether it holds the head of an if, while, for or with.
    parens: list[bool] = []
    n = len(text)
    i = 0
    # Whether a line ends between the last token and the next, which ends a statement before a
    # `++` or `--`.
    newline = False

    def add(kind: str, value: str) -> None:
        nonlocal newline
        if value in ('++', '--') and tokens and not newline:
            last = tokens[-1]
            ends = last[0] in ('number', 'string', 'template', 'regex', 'postfix') or (
                last[0] == 'word' and last[1] not in _BEFORE_REGEX
            )
            if ends or last in (('punct', ')'), ('punct', ']')):
                kind = 'postfix'
        tokens.append((kind, value))
        newline = False

    if text.startswith('#!'):
        while i < n and text[i] not in _LINE_ENDS:
            i += 1

    def regex_allowed() -> bool | None:
        # Whether a slash here starts a regular expression, None when only a parser could say.
        if not tokens:
            return True
        kind, value = tokens[-1]
        if kind in ('number', 'string', 'template', 'regex'):
            return False
        if kind == 'word':
            return value in _BEFORE_REGEX and not (len(tokens) > 1 and tokens[-2] in _DOTS)
        if kind == 'head':
            return True
        if kind == 'postfix' or value in (')', ']'):
            return False
        if value == '}':
            return None
        return True

    while i < n:
        c = text[i]
        if c.isspace() or c == '\ufeff':
            newline = newline or c in _LINE_ENDS
            i += 1
        elif text.startswith('//', i):
            while i < n and text[i] not in _LINE_ENDS:
                i += 1
        elif text.startswith('/*', i):
            end = text.find('*/', i + 2)
            if end < 0:
                return 'found a comment left open'
            newline = newline or any(c in _LINE_ENDS for c in text[i:end])
            i = end + 2
        elif c in '\'"':
            i = _quoted(text, i)
            if i < 0:
                return 'found a string left open'
            add('string', '')
        elif c == '`' or (c == '}' and braces and braces[-1] == 'template'):
            if c == '}':
                braces.pop()
            i, opens = _template(text, i + 1)
            if i < 0:
                return 'found a template left open'
            if opens:
                braces.append('template')
                add('punct', '${')
            else:
                add('template', '')
        elif c == '/':
            allowed = regex_allowed()
            if allowed is None:
                return (
                    'found a slash right after a closing brace, which reads two ways, put the '
                    'expression in parentheses'
                )
            if allowed:
                i = _regex(text, i)
                if i < 0:
                    return 'found a regular expression left open'
                add('regex', '')
            else:
                add('punct', '/')
                i += 1
        elif c.isdigit() or (c == '.' and i + 1 < n and text[i + 1].isdigit()):
            i = _NUMBER.match(text, i).end()
            add('number', '')
        elif c in '#\\$' or c.isidentifier():
            word = _js_name(text, i)
            if word is None or word[1] == i:
                return 'found an escape that names no character'
            add('word', word[0])
            i = word[1]
        elif text.startswith('?.', i) and not (i + 2 < n and text[i + 2].isdigit()):
            add('punct', '?.')
            i += 2
        else:
            value = next((p for p in _PUNCTUATORS if text.startswith(p, i)), c)
            if value == '(':
                last = tokens[-1] if tokens else ('', '')
                before = tokens[-2] if len(tokens) > 1 else ('', '')
                head = last[0] == 'word' and (
                    (last[1] in _HEADS and before not in _DOTS)
                    or (last[1] == 'await' and before == ('word', 'for'))
                )
                parens.append(head)
            elif value == ')' and parens and parens.pop():
                add('head', ')')
                i += 1
                continue
            elif value == '{':
                braces.append('brace')
            elif value == '}' and braces:
                braces.pop()
            add('punct', value)
            i += len(value)
    if 'template' in braces:
        return 'found a template left open'
    return tokens


def module_problem(text: str) -> str | None:
    """Returns why a module may not run as a single file module, or `None` when it may.

    The reader walks the text as JavaScript does, past comments, strings, template literals and
    regular expressions, and refuses every `import`, static, dynamic or `import.meta`, and every
    `export` that names a module with `from`. It also refuses a comment, string, template or
    regular expression left open, and a slash right after a closing brace, whose reading only a
    parser could tell, so no import hides in what the reader takes for text.
    """
    tokens = _tokens(text)
    if isinstance(tokens, str):
        return tokens
    for k, (kind, value) in enumerate(tokens):
        if kind != 'word' or value not in ('import', 'export') or (k and tokens[k - 1] in _DOTS):
            continue
        if value == 'import':
            return 'found import'
        after = tokens[k + 1] if k + 1 < len(tokens) else None
        if after == ('punct', '*'):
            return 'found export from'
        if after == ('punct', '{'):
            close = next((m for m in range(k + 2, len(tokens)) if tokens[m][1] == '}'), None)
            if close is not None and tokens[close + 1 : close + 2] == [('word', 'from')]:
                return 'found export from'
    return None


def check_file(name: str, data: bytes) -> None:
    """Raises `ArgumentError` for a file of a package of the wrong path, kind or size."""
    check_path(name)
    suffix = PurePosixPath(name).suffix
    if len(data) > MAXIMUM_BYTES[suffix]:
        raise ArgumentError(f'expected {name} of at most {MAXIMUM_BYTES[suffix]} bytes')
    if suffix == '.glb':
        _glb(data)
    elif suffix in ('.png', '.jpg', '.webp'):
        if _teams._image_suffix('art', data) != suffix:
            raise ArgumentError(f'expected {name} to hold an image of its kind')
    elif suffix == '.ktx2':
        if not data.startswith(b'\xabKTX 20\xbb\r\n\x1a\n'):
            raise ArgumentError(f'expected {name} to hold a KTX2 texture')
    elif suffix in ('.ogg', '.mp3', '.wav'):
        if _teams._sound_suffix(data) != suffix:
            raise ArgumentError(f'expected {name} to hold a sound of its kind')
    elif suffix == '.wasm':
        if not data.startswith(b'\0asm'):
            raise ArgumentError(f'expected {name} to hold WebAssembly')
    else:
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError as error:
            raise ArgumentError(f'expected {name} as UTF-8 text') from error
        if suffix == '.json':
            try:
                json.loads(text)
            except ValueError as error:
                raise ArgumentError(f'expected {name} as JSON, found {error}') from error
        problem = module_problem(text) if suffix == '.js' else None
        if problem:
            raise ArgumentError(
                f'expected {name} as a single file module without imports, {problem}'
            )


def _assets(team_folder: Path, remove: bool) -> dict[str, str]:
    """Returns the sound files of a package by their paths, and deletes the others when asked."""
    folder = team_folder / FOLDER
    found: dict[str, str] = {}
    if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
        if remove:
            folder.unlink()
        return found
    if not folder.is_dir():
        return found
    total = 0
    for path in sorted(folder.rglob('*')):
        if path.is_dir() and not path.is_symlink():
            continue
        name = path.relative_to(folder).as_posix()
        valid = False
        if (
            path.is_file()
            and not path.is_symlink()
            and not any(p.is_symlink() for p in path.parents if folder in p.parents)
        ):
            try:
                data = path.read_bytes()
                check_file(name, data)
                valid = len(found) < MAXIMUM_FILES and total + len(data) <= MAXIMUM_TOTAL_BYTES
            except (OSError, ArgumentError):
                valid = False
        if valid:
            total += len(data)
            found[name] = str(path)
        elif remove:
            path.unlink(missing_ok=True)
    if remove:
        for path in sorted(folder.rglob('*'), reverse=True):
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
    return found


def _read(team_folder: Path) -> Any:
    path = team_folder / FOLDER / MANIFEST
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAXIMUM_MANIFEST_BYTES:
        raise ArgumentError('expected a presentation manifest of at most 256 KB')
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeDecodeError) as error:
        raise ArgumentError(f'expected the manifest as JSON, found {error}') from error


def import_folder(team_folder: Path) -> None:
    """Checks the package of an imported team as uploads are checked, and deletes what fails.

    Files of a wrong path, kind or size and files past the limits of a package go, the manifest
    among them when it is no JSON. A manifest of a newer contract stays, untouched.
    """
    _assets(team_folder, remove=True)


def left_out(root: Path) -> set[Path]:
    """Returns the files of a team's folder that an export leaves out, those failing their check.

    Args:
        root: The submission folder of the team, with `cuju-team` inside.
    """
    team_folder = root / _teams.TEAM_FOLDER
    folder = team_folder / FOLDER
    kept = {Path(path) for path in _assets(team_folder, remove=False).values()}
    return {path for path in folder.rglob('*') if path.is_file() and path not in kept}


def developer_folders() -> dict[str, Path]:
    """Returns the trusted folders of developer mode by team, empty while it is off.

    Developer mode is on only when `developer.json` in the renderer's home holds
    `{"presentation": {"team id": "folder"}}`, each folder an absolute `cuju-team` folder of the
    author's own that holds `presentation/presentation.json`.
    """
    path = _home.home() / DEVELOPER_FILE
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    folders = document.get('presentation') if isinstance(document, dict) else None
    out = {}
    for identifier, folder in (folders or {}).items() if isinstance(folders, dict) else []:
        if isinstance(identifier, str) and isinstance(folder, str):
            candidate = Path(folder).expanduser()
            if candidate.is_absolute() and (candidate / FOLDER / MANIFEST).is_file():
                out[identifier] = candidate
    return out


def _team_folder(identifier: str) -> tuple[Path | None, bool]:
    """Returns the folder that holds a team's package and whether developer mode serves it."""
    developer = developer_folders().get(identifier)
    if developer is not None:
        return developer, True
    if identifier != _teams.BUILTIN and not _home.valid_identifier(identifier):
        return None, False
    folder = _home.folder('teams') / identifier / _teams.TEAM_FOLDER
    return (folder if folder.is_dir() else None), False


def served(identifier: str) -> dict[str, Any]:
    """Returns what the page reads of a team's package, its checked manifest and its files.

    Returns:
        A dictionary with `manifest`, the checked manifest or `None` for a team without one or
        with one this renderer cannot serve, `warnings`, `files`, the paths of the package's
        files, `developer`, whether developer mode serves it, `contract`, the version this
        renderer serves, `features`, those it implements, and `missing`, the features the
        manifest requires that it lacks.
    """
    folder, developer = _team_folder(identifier)
    out: dict[str, Any] = {
        'manifest': None,
        'warnings': [],
        'files': [],
        'developer': developer,
        'contract': CONTRACT,
        'features': list(_vocabulary.FEATURES),
        'missing': [],
    }
    if folder is None or not (folder / FOLDER / MANIFEST).is_file():
        return out
    assets = _assets(folder, remove=False)
    out['files'] = sorted(name for name in assets if name != MANIFEST)
    try:
        out['manifest'] = check(_read(folder), assets, out['warnings'])
        out['missing'] = missing(out['manifest'])
    except (ArgumentError, OSError) as error:
        out['warnings'].append(f'the package is drawn without its manifest, {error}')
    return out


def file_path(identifier: str, name: str) -> Path | None:
    """Returns the path of a file of a team's package, or `None` for an unknown or failing one."""
    folder, _ = _team_folder(identifier)
    try:
        check_path(name)
    except ArgumentError:
        return None
    if folder is None:
        return None
    path = folder / FOLDER / name
    with contextlib.suppress(OSError, ArgumentError):
        if path.is_file() and (folder / FOLDER).resolve() in path.resolve().parents:
            check_file(name, path.read_bytes())
            return path
    return None


def content_type(identifier: str, name: str) -> str:
    """Returns the type that a file of a team's package is served with.

    The page reads a worker as text and hands it to its sandbox, so a module of JavaScript goes
    out as plain text, which no page runs from its address. Only the sound worklet that the
    manifest names, which the page loads by its address into an audio context of the team's own,
    and every module of developer mode, which the page imports, go out as JavaScript.
    """
    suffix = PurePosixPath(name).suffix
    if suffix != '.js':
        return CONTENT_TYPES[suffix]
    folder, developer = _team_folder(identifier)
    if developer:
        return CONTENT_TYPES[suffix]
    manifest = None
    if folder is not None:
        with contextlib.suppress(ArgumentError, OSError):
            manifest = _read(folder)
    audio = manifest.get('audio') if isinstance(manifest, dict) else None
    worklet = audio.get('worklet') if isinstance(audio, dict) else None
    return CONTENT_TYPES[suffix] if worklet == name else 'text/plain; charset=utf-8'


def sides() -> dict[str, str | None]:
    """Returns the registered team whose presentation each side draws, by the viewer's choice.

    A side without a choice draws the presentation of the team that plays it. The choice serves
    matches whose header names no registered team, such as the live batches of a training run,
    section Q11 of the contract, and stays in the renderer's home until it is changed.
    """
    try:
        document = json.loads((_home.home() / SIDES_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeDecodeError):
        document = {}
    out: dict[str, str | None] = {}
    for side in SIDES:
        value = document.get(side) if isinstance(document, dict) else None
        out[side] = value if isinstance(value, str) and _home.valid_identifier(value) else None
    return out


def assign(changes: Any) -> dict[str, str | None]:
    """Sets the registered team whose presentation a side draws, or none, and returns them all.

    Args:
        changes: A mapping of `left` and `right` to a team identifier, or `None` for the team that
            plays the side.

    Raises:
        ArgumentError: If a side or a team is unknown.
    """
    if not isinstance(changes, dict) or not set(changes) <= set(SIDES):
        raise ArgumentError('expected the presentation of the sides left and right')
    out = sides()
    for side, identifier in changes.items():
        if identifier is not None and (
            not isinstance(identifier, str)
            or not _home.valid_identifier(identifier)
            or not (_home.folder('teams') / identifier / _teams.TEAM_FOLDER).is_dir()
        ):
            raise ArgumentError(
                f'expected a registered team for the {side} side, found {identifier!r}'
            )
        out[side] = identifier
    path = _home.home() / SIDES_FILE
    path.write_text(json.dumps(out), encoding='utf-8')
    return out


# The policy of the sandbox page, which runs its own bootstrap, blob scripts and WebAssembly alone,
# connects nowhere and may be framed by the pages it names. Its sandbox directive gives the page an
# opaque origin wherever it loads, in the renderer's frame or opened on its own as a whole window,
# so it never holds the storage, caches or service worker of the server's origin.
SANDBOX_POLICY = (
    'sandbox allow-scripts; '
    "default-src 'none'; script-src '{hash}' blob: 'wasm-unsafe-eval'; worker-src blob:; "
    "connect-src 'none'; img-src blob: data:; frame-ancestors {ancestors}; base-uri 'none'; "
    "form-action 'none'"
)


def sandbox_page(ancestors: str = "'self'") -> tuple[bytes, str]:
    """Returns the page of the sandbox of team workers and its policy, which allows its script.

    The page inlines `web/js/presentation/sandbox.js`, and the policy names the digest of that
    script, so nothing else runs in the sandbox but blob modules it starts itself. Every page
    above the sandbox must be among `ancestors`, so a viewer in the frame of a notebook passes the
    notebooks that may frame it.
    """
    script = (Path(__file__).parents[1] / 'web/js/presentation/sandbox.js').read_text(
        encoding='utf-8'
    )
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    page = f'<!doctype html><meta charset="utf-8"><title>sandbox</title><script>{script}</script>'
    return page.encode(), SANDBOX_POLICY.format(hash=f'sha256-{digest}', ancestors=ancestors)
