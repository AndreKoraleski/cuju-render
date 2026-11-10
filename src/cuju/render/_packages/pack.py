# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The author tools of team presentation packages, `cuju render pack check` and `pack new`.

`check` reads a package the way the server and the page read it and reports what each of them
would make of it, before the author imports the team. It takes a team's submission folder with
`cuju-team` inside, a `cuju-team` folder, a `presentation` folder or a `.zip` export of a team,
which it reads in memory. It runs every check of an import and of serving, the paths, kinds and
sizes of the files, the limits of a package and the manifest's own check, and adds the checks
the page makes as it draws, the static rules of the shaders, the static cost of every model and
attachment against the budgets of each quality, the names that the rig, behaviours and clips give
to nodes and animations of the models, the contact markers of action clips and the loudness and
true peak of every WAV sample.

Errors are what makes the server leave a part out or refuse the package. Warnings are what the
page holds back or degrades as it draws, and information is everything else worth knowing.

`new` writes a small working package for an author to start from, a team submission folder with
an agent, a team file and a package that uses most levels of contract 1.1.

Loudness follows ITU-R BS.1770 with its K weighting, the momentary loudness of 400 ms, the
short-term loudness of 3 s, the gated integrated loudness and the true peak of four times
oversampling, as `web/js/presentation/loudness.js` measures on the page. It uses numpy when it
imports and pure Python otherwise, and reads at most the first 60 seconds of each sample.
"""

from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import struct
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any

from cuju.errors import ArgumentError

from .._registry import teams as _teams
from . import glsl as _glsl
from . import presentation as _presentation
from . import vocabulary as _vocabulary
from .loudness import MAXIMUM_SECONDS as MAXIMUM_SECONDS
from .loudness import MOMENTARY_CEILING as MOMENTARY_CEILING
from .loudness import SHORT_TERM_CEILING as SHORT_TERM_CEILING
from .loudness import TARGET_LUFS as TARGET_LUFS
from .loudness import TRUE_PEAK_CEILING as TRUE_PEAK_CEILING
from .loudness import _wav as _wav
from .loudness import loudness as loudness

FOLDER = _presentation.FOLDER
MANIFEST = _presentation.MANIFEST
QUALITIES = ('high', 'medium', 'low')
_MB = 1024 * 1024
# The budgets of a team that a package's static counts meet, after docs/presentation.md and the
# table of web/js/presentation/budget.js.
BUDGETS = {
    'high': {
        'drawCalls': 150,
        'triangles': 400_000,
        'textureBytes': 128 * _MB,
        'particles': 20_000,
        'lights': 4,
        'localLights': 16,
        'shaders': _glsl.BUDGET['high'],
        'worklets': 4,
        'audioBytes': 64 * _MB,
        'fullscreen': 1,
    },
    'medium': {
        'drawCalls': 100,
        'triangles': 200_000,
        'textureBytes': 64 * _MB,
        'particles': 8_000,
        'lights': 2,
        'localLights': 16,
        'shaders': _glsl.BUDGET['medium'],
        'worklets': 4,
        'audioBytes': 64 * _MB,
        'fullscreen': 0,
    },
    'low': {
        'drawCalls': 60,
        'triangles': 80_000,
        'textureBytes': 32 * _MB,
        'particles': 2_000,
        'lights': 1,
        'localLights': 16,
        'shaders': _glsl.BUDGET['low'],
        'worklets': 2,
        'audioBytes': 32 * _MB,
        'fullscreen': 0,
    },
}
_BUDGET_NAMES = {
    'drawCalls': 'draw calls',
    'triangles': 'triangles',
    'textureBytes': 'bytes of texture memory',
    'particles': 'particles',
    'lights': 'pool lights',
    'localLights': 'local lights',
    'shaders': 'shader programs',
    'worklets': 'worklet nodes',
    'audioBytes': 'bytes of decoded audio',
    'fullscreen': 'full screen passes',
}
# The sample rate at which the page decodes sound, for the estimate of decoded audio.
_DECODE_RATE = 48000
# Features that only a worker uses, whose lack drops the worker and keeps the manifest.
WORKER_FEATURES = ('drivers.worker', 'geometry.worker', 'overlay.offscreen')
# The roles of clips that meet the ball, whose clips may carry a contact marker.
ACTION_ROLES = (
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
    'trap',
    'deflect',
    'restart.kickoff',
    'restart.goal_kick',
    'restart.free_kick',
    'restart.corner',
    'restart.throw_in',
    'restart.penalty',
)
_KINDS = {
    '.glb': 'model',
    '.png': 'texture',
    '.jpg': 'texture',
    '.webp': 'texture',
    '.ktx2': 'texture',
    '.ogg': 'sound',
    '.mp3': 'sound',
    '.wav': 'sound',
    '.js': 'module',
    '.json': 'data',
    '.glsl': 'shader',
    '.wasm': 'webassembly',
}
_TEXTURES = ('.png', '.jpg', '.webp', '.ktx2')
_SOUNDS = ('.ogg', '.mp3', '.wav')
_MAXIMUM_TEAM_FILE = 1024 * 1024
_MAXIMUM_MODEL = 30 * _MB
# The bytes an archive may unpack to before the rest is counted by size alone.
_MAXIMUM_READ = 200 * _MB
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942
# What reading a damaged file may raise.
_UNREADABLE = (ArgumentError, OSError, ValueError, KeyError, TypeError, IndexError, struct.error)


def _sanitized(name: str) -> str:
    """Returns a node name as three.js keeps it, with spaces as underscores and no `[].:/`."""
    return re.sub(r'[\[\].:/]', '', re.sub(r'\s', '_', name))


# Reading a package.


class _Source:
    """The files of a package as read from a folder or an archive, and what lies around them."""

    def __init__(self, label: str) -> None:
        self.label = label
        # The files of the presentation folder by their paths inside it, each with its size.
        self.sizes: dict[str, int] = {}
        self.data: dict[str, bytes] = {}
        self.paths: dict[str, Path] = {}
        self.errors: list[str] = []
        self.info: list[str] = []
        self.team: Any = None
        self.model: bytes | None = None

    def read(self, name: str) -> bytes:
        if name in self.data:
            return self.data[name]
        if name in self.paths:
            return self.paths[name].read_bytes()
        raise ArgumentError(f'expected {name} to be read, an archive member past what is read')


def _team_files(source: _Source, team: bytes | None, model: bytes | None) -> None:
    """Keeps the team file and model of the team around a package."""
    if team is not None:
        try:
            source.team = json.loads(team)
        except (ValueError, UnicodeDecodeError):
            source.errors.append('team.json holds no JSON, so import keeps the defaults of a team')
    source.model = model


def _folder(path: Path) -> _Source:
    """Reads a team's submission folder, its `cuju-team` folder or a `presentation` folder."""
    if (path / _teams.TEAM_FOLDER).is_dir():
        root, team = path, path / _teams.TEAM_FOLDER
        package = team / FOLDER
    elif (path / FOLDER).is_dir():
        root, team, package = None, path, path / FOLDER
    elif (path / MANIFEST).is_file():
        root, team, package = None, path.parent, path
    else:
        raise ArgumentError(
            f'expected a team submission folder, a cuju-team folder or a presentation folder, '
            f'found {str(path)!r}'
        )
    source = _Source(str(path))
    if root is not None and not (root / 'main.py').is_file():
        source.errors.append('the submission holds no main.py, which import needs')
    if (team / 'team.json').is_file() or team.name == _teams.TEAM_FOLDER:
        team_json = team / 'team.json'
        model = team / 'model.glb'
        _team_files(
            source,
            team_json.read_bytes()
            if team_json.is_file() and team_json.stat().st_size <= _MAXIMUM_TEAM_FILE
            else None,
            model.read_bytes()
            if model.is_file() and model.stat().st_size <= _MAXIMUM_MODEL
            else None,
        )
    if not package.is_dir():
        return source
    for directory, folders, files in os.walk(package, followlinks=False):
        here = Path(directory)
        for name in sorted(folders):
            if (here / name).is_symlink():
                relative = (here / name).relative_to(package).as_posix()
                source.errors.append(f'{relative} is a link, which import deletes')
        for name in files:
            item = here / name
            relative = item.relative_to(package).as_posix()
            if item.is_symlink():
                source.errors.append(f'{relative} is a link, which import deletes')
                continue
            source.sizes[relative] = item.stat().st_size
            source.paths[relative] = item
    return source


def _archive(path: Path) -> _Source:
    """Reads the package of a team's `.zip` export in memory, without unpacking it."""
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as error:
        raise ArgumentError(f'expected a readable .zip archive, found {error}') from error
    source = _Source(str(path))
    with archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        names = {item.filename: item for item in members}
        wanted = f'{_teams.TEAM_FOLDER}/{FOLDER}/{MANIFEST}'
        found = sorted(
            (name for name in names if name == MANIFEST or name.endswith(f'{FOLDER}/{MANIFEST}')),
            key=len,
        )
        if wanted in names:
            prefix = f'{_teams.TEAM_FOLDER}/{FOLDER}/'
        elif found:
            prefix = found[0][: -len(MANIFEST)]
        else:
            raise ArgumentError(f'expected an archive of a team that holds {wanted}')
        if prefix == f'{_teams.TEAM_FOLDER}/{FOLDER}/':
            if 'main.py' not in names:
                source.errors.append('the archive holds no main.py at its top, which import needs')
        elif prefix.endswith(f'{_teams.TEAM_FOLDER}/{FOLDER}/'):
            source.errors.append(
                f'the archive holds its team under {prefix[: -len(FOLDER) - 1]}, and import reads '
                f'{_teams.TEAM_FOLDER} at the top of the archive'
            )
        else:
            source.errors.append(
                f'the archive holds its package as {prefix}{MANIFEST}, and import reads a team '
                f'with main.py and {_teams.TEAM_FOLDER} at the top of the archive'
            )
        try:
            _teams._check_unpacked(len(members), sum(item.file_size for item in members))
            for item in members:
                _teams._check_member(item.filename)
        except ArgumentError as error:
            source.errors.append(f'import refuses the archive, {error}')
        team = prefix[: -len(FOLDER) - 1] if prefix.endswith(f'{FOLDER}/') else None
        read = 0

        def member(name: str, limit: int) -> bytes | None:
            nonlocal read
            item = names.get(name)
            if item is None or item.file_size > limit or read + item.file_size > _MAXIMUM_READ:
                return None
            read += item.file_size
            try:
                return archive.read(item)
            except (zipfile.BadZipFile, OSError, ValueError, RuntimeError, EOFError, zlib.error):
                source.errors.append(f'{name} cannot be read from the archive')
                return None

        if team is not None:
            _team_files(
                source,
                member(f'{team}team.json', _MAXIMUM_TEAM_FILE),
                member(f'{team}model.glb', _MAXIMUM_MODEL),
            )
        for name, item in sorted(names.items()):
            if not name.startswith(prefix) or name == prefix:
                continue
            relative = name[len(prefix) :]
            source.sizes[relative] = item.file_size
            suffix = PurePosixPath(relative).suffix
            data = member(name, _presentation.MAXIMUM_BYTES.get(suffix, 0))
            if data is not None:
                source.data[relative] = data
    return source


# Binary glTF and images.


def _gltf(data: bytes) -> tuple[dict[str, Any], bytes]:
    """Returns the JSON document and the binary chunk of a binary glTF file."""
    size, _ = struct.unpack_from('<II', data, 12)
    document = json.loads(data[20 : 20 + size])
    offset = 20 + size + (-size % 4)
    binary = b''
    if offset + 8 <= len(data):
        length, kind = struct.unpack_from('<II', data, offset)
        if kind == _BIN_CHUNK:
            binary = data[offset + 8 : offset + 8 + length]
    return document, binary


def image_size(data: bytes) -> tuple[int, int] | None:
    """Returns the width and height of a PNG, JPEG, WebP or KTX2 image from its header."""
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 24 and data[12:16] == b'IHDR':
        return struct.unpack_from('>II', data, 16)
    if data.startswith(b'\xab\x4b\x54\x58\x20\x32\x30\xbb\r\n\x1a\n') and len(data) >= 28:
        return struct.unpack_from('<II', data, 20)
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP' and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b'VP8 ':
            width, height = struct.unpack_from('<HH', data, 26)
            return width & 0x3FFF, height & 0x3FFF
        if chunk == b'VP8L':
            (bits,) = struct.unpack_from('<I', data, 21)
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk == b'VP8X':
            width = int.from_bytes(data[24:27], 'little') + 1
            height = int.from_bytes(data[27:30], 'little') + 1
            return width, height
        return None
    if data.startswith(b'\xff\xd8'):
        offset = 2
        while offset + 9 <= len(data):
            if data[offset] != 0xFF:
                offset += 1
                continue
            marker = data[offset + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
                offset += 1 if marker == 0xFF else 2
                continue
            (length,) = struct.unpack_from('>H', data, offset + 2)
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack_from('>HH', data, offset + 5)
                return width, height
            offset += 2 + length
    return None


def _texture_names(value: Any, out: set[int]) -> None:
    """Collects the texture indices that a material, its extensions included, names."""
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                key.endswith('Texture')
                and isinstance(item, dict)
                and isinstance(item.get('index'), int)
            ):
                out.add(item['index'])
            else:
                _texture_names(item, out)
    elif isinstance(value, list):
        for item in value:
            _texture_names(item, out)


def model_stats(data: bytes) -> dict[str, Any]:
    """Returns the static cost and the names of a binary glTF file as the page loads it.

    Returns:
        A dictionary with `drawCalls`, a draw for each primitive of each mesh node of the scene,
        `triangles`, a third of each primitive's indices or positions, `textureBytes`, four bytes
        for each pixel of each texture its drawn materials name, `nodes`, the names of its nodes,
        and `animations`, each animation's name with its `duration` in seconds and its `contact`
        marker or `None`.
    """
    document, binary = _gltf(data)
    nodes = document.get('nodes') or []
    meshes = document.get('meshes') or []
    accessors = document.get('accessors') or []
    scenes = document.get('scenes') or []
    scene = document.get('scene', 0)
    if isinstance(scene, int) and 0 <= scene < len(scenes) and isinstance(scenes[scene], dict):
        roots = scenes[scene].get('nodes') or []
    else:
        children = {c for n in nodes if isinstance(n, dict) for c in n.get('children') or []}
        roots = [i for i in range(len(nodes)) if i not in children]
    seen: set[int] = set()
    stack = [r for r in roots if isinstance(r, int)]
    draws = triangles = 0
    materials: set[int] = set()
    while stack:
        index = stack.pop()
        if index in seen or not 0 <= index < len(nodes) or not isinstance(nodes[index], dict):
            continue
        seen.add(index)
        node = nodes[index]
        stack.extend(c for c in node.get('children') or [] if isinstance(c, int))
        mesh = node.get('mesh')
        if not isinstance(mesh, int) or not 0 <= mesh < len(meshes):
            continue
        for primitive in meshes[mesh].get('primitives') or []:
            draws += 1
            accessor = primitive.get('indices')
            if not isinstance(accessor, int):
                accessor = (primitive.get('attributes') or {}).get('POSITION')
            if isinstance(accessor, int) and 0 <= accessor < len(accessors):
                triangles += int(accessors[accessor].get('count', 0)) // 3
            if isinstance(primitive.get('material'), int):
                materials.add(primitive['material'])
    textures: set[int] = set()
    for index in materials:
        if 0 <= index < len(document.get('materials') or []):
            _texture_names(document['materials'][index], textures)
    texture_bytes = 0
    images = document.get('images') or []
    views = document.get('bufferViews') or []
    for index in textures:
        texture = (document.get('textures') or [{}] * (index + 1))[index]
        source = texture.get('source') if isinstance(texture, dict) else None
        for extension in (texture.get('extensions') or {}).values() if texture else []:
            if isinstance(extension, dict) and isinstance(extension.get('source'), int):
                source = extension['source']
        if not isinstance(source, int) or not 0 <= source < len(images):
            continue
        image = images[source]
        content = b''
        if isinstance(image.get('bufferView'), int) and image['bufferView'] < len(views):
            view = views[image['bufferView']]
            start = int(view.get('byteOffset', 0))
            content = binary[start : start + int(view.get('byteLength', 0))]
        elif isinstance(image.get('uri'), str) and image['uri'].startswith('data:'):
            content = base64.b64decode(image['uri'].split(',', 1)[-1] + '==')
        size = image_size(content)
        if size:
            texture_bytes += size[0] * size[1] * 4
    animations = {}
    for index, animation in enumerate(document.get('animations') or []):
        if not isinstance(animation, dict):
            continue
        duration = 0.0
        for sampler in animation.get('samplers') or []:
            accessor = sampler.get('input') if isinstance(sampler, dict) else None
            if isinstance(accessor, int) and 0 <= accessor < len(accessors):
                top = accessors[accessor].get('max') or [0]
                if top and isinstance(top[0], (int, float)):
                    duration = max(duration, float(top[0]))
        extras = animation.get('extras')
        markers = _dict(_dict(_dict(extras).get('cuju')).get('markers'))
        contact = markers.get('contact')
        name = animation.get('name') if isinstance(animation.get('name'), str) else ''
        entry = {'duration': duration, 'contact': contact}
        animations[name or f'animation_{index}'] = entry
        # The team editor names an unnamed animation by its place, from one.
        animations.setdefault(f'Animation {index + 1}', entry)
    names = {n['name'] for n in nodes if isinstance(n, dict) and isinstance(n.get('name'), str)}
    return {
        'drawCalls': draws,
        'triangles': triangles,
        'textureBytes': texture_bytes,
        'nodes': names | {_sanitized(name) for name in names},
        'animations': animations,
    }


# The check of a package.


def _wearers(when: Any, size: int) -> int:
    """Returns how many players of a team of `size` a selector picks."""
    if not isinstance(when, dict):
        return size
    counts = [size]
    if when.get('role') == 'goalkeeper':
        counts.append(1)
    elif when.get('role') == 'outfield':
        counts.append(size - 1)
    for key in ('number', 'index'):
        if key in when:
            items = when[key] if isinstance(when[key], list) else [when[key]]
            picked = {i for i in items if isinstance(i, int)}
            if key == 'index':
                picked = {i for i in picked if 0 <= i < size}
            counts.append(len(picked))
    return max(0, min(counts))


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


class _Report:
    """Collects the findings of a check, each said once."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.info: list[str] = []

    def add(self, kind: str, message: str) -> None:
        items = getattr(self, kind)
        if message not in items:
            items.append(message)


def _clip_names(clips: Any) -> list[tuple[str, str]]:
    """Returns each clip name of a manifest's clips with the role that names it."""
    out = []
    for role, entry in _dict(clips).items():
        if isinstance(entry, dict) and entry.get('space') == 'speed':
            entries = _list(entry.get('clips'))
        else:
            entries = entry if isinstance(entry, list) else [entry]
        for item in entries:
            if isinstance(item, list) and item:
                item = item[0]
            if isinstance(item, dict):
                item = item.get('clip')
            if isinstance(item, str):
                out.append((role, item))
    return out


def _references(
    document: dict[str, Any],
    assets: dict[str, str],
    models: dict[str, dict[str, Any]],
    report: _Report,
) -> set[str]:
    """Checks that every name of the manifest names a file, node, clip or part of the package.

    Returns:
        The paths of the files that the manifest names.
    """
    named: set[str] = set()

    def file(value: Any, what: str, suffixes: tuple[str, ...] | None = None) -> None:
        if not isinstance(value, str):
            report.add('errors', f'{what} names no file, found {value!r}')
            return
        named.add(value)
        if value not in assets:
            if not any(value in error for error in report.errors):
                report.add('errors', f'{what} names {value}, which is no file of the package')
        elif suffixes and PurePosixPath(value).suffix not in suffixes:
            report.add('errors', f'{what} names {value}, expected a {"/".join(suffixes)} file')

    def lacks(what: str, kind: str, value: Any, owner: str) -> None:
        report.add('errors', f'{what} names the {kind} {value}, which {owner} lacks')

    rig = _dict(document.get('rig'))
    sockets = set(_dict(rig.get('sockets'))) | {'root'}
    attachments = _dict(rig.get('attachments'))
    lights = _dict(document.get('lights'))
    audio = _dict(document.get('audio'))
    processors = audio.get('processors')
    music = _dict(audio.get('music'))
    nodes = set().union(*(m['nodes'] for m in models.values())) if models else set()
    animations = {n for m in models.values() for n in m['animations']}
    unchecked: list[str] = []

    def node(value: Any, what: str) -> None:
        if not isinstance(value, str):
            report.add('errors', f'{what} names no node, found {value!r}')
        elif not models:
            unchecked.append(what)
        elif value not in nodes:
            report.add('errors', f'{what} names the node {value}, which no model of the team has')

    def clip(value: Any, what: str) -> None:
        if not isinstance(value, str):
            report.add('errors', f'{what} names no clip, found {value!r}')
        elif not models:
            unchecked.append(what)
        elif value not in animations:
            report.add('errors', f'{what} names the clip {value}, which no model of the team holds')

    models_section = _dict(document.get('models'))
    for role in ('outfield', 'goalkeeper'):
        if role in models_section:
            file(models_section[role], f'the {role} model', ('.glb',))
    for number, value in _dict(models_section.get('byNumber')).items():
        file(value, f'the model of number {number}', ('.glb',))
    for name, socket in _dict(rig.get('sockets')).items():
        if isinstance(socket, dict) and socket.get('node'):
            node(socket['node'], f'socket {name}')
    for joint, bone in _dict(rig.get('joints')).items():
        node(bone, f'the joint {joint}')
    for name, item in attachments.items():
        item = _dict(item)
        file(item.get('file'), f'attachment {name}', ('.glb',))
        if item.get('socket', 'root') not in sockets:
            lacks(f'attachment {name}', 'socket', item.get('socket'), 'the rig')
    for name, chain in _dict(rig.get('ik')).items():
        chain = _dict(chain)
        for bone in _list(chain.get('chain')):
            node(bone, f'the chain of ik {name}')
        if 'socket' in chain and chain['socket'] not in sockets:
            lacks(f'ik {name}', 'socket', chain['socket'], 'the rig')
    for index, layer in enumerate(_list(rig.get('layers'))):
        layer = _dict(layer)
        for bone in _list(layer.get('mask')):
            node(bone, f'the mask of layer {index}')
        if 'clip' in layer:
            clip(layer['clip'], f'layer {index}')
        if 'role' in layer and layer['role'] not in _presentation.ROLES:
            lacks(f'layer {index}', 'role', layer['role'], 'the contract')
    for role, name in _clip_names(document.get('clips')):
        clip(name, f'the role {role}')
    for index, spec in enumerate(_list(document.get('behaviours'))):
        spec = _dict(spec)
        what = f'behaviour {spec.get("id", index)}'
        if 'node' in spec:
            node(spec['node'], what)
        if spec.get('type') == 'spin' and 'clip' in spec:
            clip(spec['clip'], what)
        if 'attachment' in spec and spec['attachment'] not in attachments:
            lacks(what, 'attachment', spec['attachment'], 'the rig')
        if 'light' in spec and spec['light'] not in lights:
            lacks(what, 'light', spec['light'], 'the section lights')
        if (
            isinstance(processors, dict)
            and 'processor' in spec
            and spec['processor'] not in processors
        ):
            lacks(what, 'processor', spec['processor'], 'audio')
    for name, light in lights.items():
        light = _dict(light)
        if light.get('socket', 'root') not in sockets:
            lacks(f'light {name}', 'socket', light.get('socket'), 'the rig')
    if 'worker' in document:
        file(document['worker'], 'the worker', ('.js',))
    for name, files in _dict(audio.get('cues')).items():
        for item in files if isinstance(files, list) else [files]:
            file(item, f'cue {name}', _SOUNDS)
    for name, spec in music.items():
        for item in _list(_dict(spec).get('stems')):
            file(item, f'music {name}', _SOUNDS)
    if 'worklet' in audio:
        file(audio['worklet'], 'the worklet', ('.js',))
    for name, effect in _dict(document.get('effects')).items():
        effect = _dict(effect)
        if 'file' in effect:
            kinds = ('.glb',) if effect.get('type') == 'mesh' else None
            file(effect['file'], f'effect {name}', kinds)
        if 'texture' in effect:
            file(effect['texture'], f'the texture of effect {name}', _TEXTURES)
        if 'shader' in effect:
            file(effect['shader'], f'the shader of effect {name}', ('.glsl',))
    materials = document.get('materials')
    entries = list(materials.items()) if isinstance(materials, dict) else []
    for name, look in entries:
        for rule in [_dict(look), *map(_dict, _list(_dict(look).get('rules')))]:
            if 'shader' in rule:
                file(rule['shader'], f'the shader of material {name}', ('.glsl',))
            for key, texture in _dict(rule.get('textures')).items():
                file(texture, f'the texture {key} of material {name}', _TEXTURES)
    for name, layer in _dict(document.get('post')).items():
        if 'shader' in _dict(layer):
            file(layer['shader'], f'the shader of post {name}', ('.glsl',))
    for index, reflex in enumerate(_list(document.get('reflexes'))):
        for action in _list(_dict(reflex).get('do')):
            action = _dict(action)
            if 'music' in action and action['music'] not in music:
                lacks(f'reflex {index}', 'music', action['music'], 'audio')
            attach = action.get('attach')
            socket = _dict(attach).get('socket') if isinstance(attach, dict) else None
            if isinstance(attach, str) and attach.startswith('socket:'):
                socket = attach[len('socket:') :]
            if socket is not None and socket not in sockets:
                lacks(f'reflex {index}', 'socket', socket, 'the rig')
            environment = _dict(action.get('environment'))
            if 'tifo' in environment:
                file(environment['tifo'], f'the tifo of reflex {index}', _TEXTURES)
    if unchecked:
        report.add(
            'info',
            f'the team draws the stock model, so the names of nodes and clips of {unchecked[0]} '
            f'and {len(unchecked) - 1} more stay unchecked'
            if len(unchecked) > 1
            else f'the team draws the stock model, so the names of {unchecked[0]} stay unchecked',
        )
    return named


def _models(
    document: dict[str, Any], source: _Source, assets: dict[str, str], report: _Report
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Returns the statistics of the models the team draws and how many players draw each."""
    size = _teams.FORMATS.get(_dict(source.team).get('format'), _teams.FORMATS['11v11'])
    section = _dict(document.get('models'))
    numbers = _dict(section.get('byNumber'))
    counts: dict[str, int] = {}
    for value in numbers.values():
        if isinstance(value, str):
            counts[value] = counts.get(value, 0) + 1
    if isinstance(section.get('goalkeeper'), str):
        counts[section['goalkeeper']] = counts.get(section['goalkeeper'], 0) + 1
    if isinstance(section.get('outfield'), str):
        rest = max(0, size - 1 - len(numbers))
        counts[section['outfield']] = counts.get(section['outfield'], 0) + rest
    stats: dict[str, dict[str, Any]] = {}
    for name in counts:
        if name in assets and name.endswith('.glb'):
            try:
                stats[name] = model_stats(source.read(name))
            except _UNREADABLE as error:
                report.add('warnings', f'{name} could not be read for its cost, {error}')
    # A player whom no model of the package picks draws the team's own model.
    if source.model is not None and not (
        isinstance(section.get('outfield'), str) and isinstance(section.get('goalkeeper'), str)
    ):
        try:
            stats['model.glb'] = model_stats(source.model)
        except _UNREADABLE:
            report.add('warnings', 'the team model.glb could not be read for its names')
    return stats, counts


def _budgets(
    document: dict[str, Any],
    source: _Source,
    assets: dict[str, str],
    stats: dict[str, dict[str, Any]],
    counts: dict[str, int],
    named: set[str],
    report: _Report,
) -> dict[str, dict[str, list[int]]]:
    """Returns the static use of each budget at each quality and reports what passes a budget."""
    size = _teams.FORMATS.get(_dict(source.team).get('format'), _teams.FORMATS['11v11'])
    used = dict.fromkeys(BUDGETS['high'], 0)

    def add_model(cost: dict[str, Any], times: int) -> None:
        for key in ('drawCalls', 'triangles', 'textureBytes'):
            used[key] += cost[key] * times

    for name, times in counts.items():
        if name in stats:
            add_model(stats[name], times)
    rig = _dict(document.get('rig'))
    for name, item in _dict(rig.get('attachments')).items():
        item = _dict(item)
        path = item.get('file')
        if path in assets and str(path).endswith('.glb'):
            try:
                add_model(model_stats(source.read(path)), _wearers(item.get('when'), size))
            except _UNREADABLE as error:
                report.add('warnings', f'attachment {name} could not be read for its cost, {error}')
    for name, effect in _dict(document.get('effects')).items():
        effect = _dict(effect)
        kind = effect.get('type')
        if kind == 'mesh' and effect.get('file') in assets:
            try:
                add_model(model_stats(source.read(effect['file'])), 1)
            except _UNREADABLE:
                report.add('warnings', f'effect {name} could not be read for its cost')
        elif kind == 'particles':
            life = [v for v in _list(effect.get('life')) if isinstance(v, (int, float))]
            count, rate = effect.get('count', 0), effect.get('rate', 0)
            count = count if isinstance(count, (int, float)) else 0
            rate = rate if isinstance(rate, (int, float)) else 0
            used['particles'] += int(max(count, rate * max(life, default=1.0)))
        elif kind == 'post' and effect.get('scope') == 'fullscreen':
            used['fullscreen'] += 1
    for name in sorted(named):
        if name in assets and PurePosixPath(name).suffix in _TEXTURES:
            dimensions = image_size(source.read(name))
            if dimensions:
                used['textureBytes'] += dimensions[0] * dimensions[1] * 4
    used['shaders'] = _glsl.programs(document)
    for light in _dict(document.get('lights')).values():
        key = 'lights' if _dict(light).get('kind') == 'pool' else 'localLights'
        used[key] += _wearers(_dict(light).get('when'), size)
    used['worklets'] = len(_dict(_dict(document.get('audio')).get('processors')))
    for name in sorted(named):
        if name in assets and name.endswith('.wav'):
            try:
                _, rate, channels, _, frames, _ = _wav(source.read(name))
                used['audioBytes'] += int(frames / rate * _DECODE_RATE) * channels * 4
            except _UNREADABLE:
                pass
    out: dict[str, dict[str, list[int]]] = {}
    for quality in QUALITIES:
        out[quality] = {}
        for key, limit in BUDGETS[quality].items():
            out[quality][key] = [used[key], limit]
            if used[key] <= limit:
                continue
            if key == 'fullscreen':
                report.add(
                    'info',
                    f'at {quality} quality the page draws no full screen pass, so the '
                    f'{used[key]} of the package stay off there',
                )
            else:
                report.add(
                    'warnings',
                    f'at {quality} quality the package uses {used[key]} of {limit} '
                    f'{_BUDGET_NAMES[key]}, and the page holds back what passes the budget',
                )
    return out


def _markers(document: dict[str, Any], stats: dict[str, dict[str, Any]], report: _Report) -> None:
    """Reports the contact markers of the clips of the roles that meet the ball."""
    animations: dict[str, dict[str, Any]] = {}
    for model in stats.values():
        for name, entry in model['animations'].items():
            animations.setdefault(name, entry)
    for role, name in _clip_names(document.get('clips')):
        if role not in ACTION_ROLES or name not in animations:
            continue
        contact, duration = animations[name]['contact'], animations[name]['duration']
        if contact is None:
            report.add(
                'info',
                f'clip {name} of {role} has no contact marker, so its contact falls at 40 '
                'percent of its length',
            )
        elif (
            isinstance(contact, bool)
            or not isinstance(contact, (int, float))
            or not 0 <= contact <= duration
        ):
            report.add(
                'warnings',
                f'clip {name} of {role} marks its contact at {contact!r}, outside its '
                f'{duration:g} seconds, so the page takes 40 percent of its length',
            )


_FRAME = re.compile(
    r'\bexport\s+(?:async\s+)?function\s*\*?\s*frame\b'
    r'|\bexport\s+(?:const|let|var)\s+frame\b|\bexport\s*\{[^}]*\bframe\b'
)
_REGISTER = re.compile(r'registerProcessor\s*\(\s*[\'"]([^\'"]+)[\'"]')


def _modules(
    document: dict[str, Any], source: _Source, assets: dict[str, str], report: _Report
) -> None:
    """Checks that the worker exports its frame and the worklet registers its processors."""
    worker = document.get('worker')
    if isinstance(worker, str) and worker in assets:
        if not _FRAME.search(source.read(worker).decode('utf-8', 'replace')):
            report.add('warnings', f'the worker {worker} exports no frame, so the page ends it')
    audio = _dict(document.get('audio'))
    worklet = audio.get('worklet')
    if isinstance(worklet, str) and worklet in assets:
        registered = set(_REGISTER.findall(source.read(worklet).decode('utf-8', 'replace')))
        for name, spec in _dict(audio.get('processors')).items():
            processor = _dict(spec).get('processor')
            if isinstance(processor, str) and processor not in registered:
                report.add(
                    'warnings',
                    f'processor {name} names {processor}, which the worklet {worklet} never '
                    'registers',
                )


def _sounds(assets: dict[str, str], source: _Source, report: _Report) -> list[dict[str, Any]]:
    """Measures every WAV sample of the package against the team's ceilings."""
    out = []
    for name in sorted(assets):
        suffix = PurePosixPath(name).suffix
        if suffix in ('.ogg', '.mp3'):
            report.add('info', f'{name} is measured on the page when it loads')
        if suffix != '.wav':
            continue
        try:
            measured = loudness(source.read(name))
        except _UNREADABLE as error:
            report.add('warnings', f'{name} could not be measured, {error}')
            continue
        keys = ('integrated', 'maxMomentary', 'maxShortTerm', 'truePeak')
        out.append({'file': name, **{key: measured[key] for key in keys}})
        if measured['maxMomentary'] is None:
            report.add('info', f'{name} is silent')
            continue
        if measured['measured'] < measured['seconds']:
            report.add('info', f'{name} is measured over its first {MAXIMUM_SECONDS} seconds')
        short = measured['maxShortTerm'] if measured['maxShortTerm'] is not None else -math.inf
        lowering = max(
            0.0, short - SHORT_TERM_CEILING, measured['maxMomentary'] - MOMENTARY_CEILING
        )
        if lowering > 0:
            report.add(
                'info',
                f'{name} reaches {short:.1f} LUFS short-term and {measured["maxMomentary"]:.1f} '
                f'LUFS momentary, so the page lowers it {lowering:.1f} dB to the team ceilings '
                f'of {SHORT_TERM_CEILING:g} and {MOMENTARY_CEILING:g} LUFS',
            )
        else:
            report.add(
                'info',
                f'{name} reaches {short:.1f} LUFS short-term, within the team ceiling of '
                f'{SHORT_TERM_CEILING:g} LUFS',
            )
        if measured['truePeak'] is not None and measured['truePeak'] > TRUE_PEAK_CEILING:
            report.add(
                'warnings',
                f'{name} peaks at {measured["truePeak"]:+.1f} dBTP, over {TRUE_PEAK_CEILING:g} '
                'dBTP, so leave it headroom before the page scales and limits it',
            )
    return out


def _features(document: dict[str, Any], report: _Report) -> dict[str, list[str]]:
    """Returns the features a manifest requires and prefers and those this renderer lacks."""
    required = [f for f in _list(document.get('requires')) if isinstance(f, str)]
    preferred = [f for f in _list(document.get('prefers')) if isinstance(f, str)]
    missing = [f for f in required if f not in _vocabulary.FEATURES]
    lacking = [f for f in preferred if f not in _vocabulary.FEATURES]
    known = (*_vocabulary.FEATURES, *getattr(_vocabulary, 'PLANNED', ()))
    for feature in missing:
        if feature not in known:
            report.add('warnings', f'the package requires {feature}, a feature no renderer names')
        if feature in WORKER_FEATURES:
            report.add(
                'warnings',
                f'this renderer lacks {feature}, which only a worker uses, so the page drops the '
                'worker and keeps the manifest',
            )
        else:
            report.add(
                'warnings',
                f'this renderer lacks the required feature {feature}, so the page draws the team '
                'in its stock look',
            )
    for feature in lacking:
        report.add(
            'info',
            f'this renderer lacks the preferred feature {feature}, which the worker learns from '
            'its Hello',
        )
    return {'required': required, 'preferred': preferred, 'missing': missing, 'lacking': lacking}


def check(path: str | Path) -> dict[str, Any]:
    """Checks a team's presentation package as the server and the page read it.

    Args:
        path: A team's submission folder with `cuju-team` inside, a `cuju-team` folder, a
            `presentation` folder or a `.zip` export of a team.

    Returns:
        A dictionary with `ok`, whether nothing is an error, `errors`, what makes the server
        leave a part out or refuse the package, `warnings`, what the page holds back or degrades,
        `info`, `manifest`, the manifest as the server checks it or `None`, `features`, with the
        `required` and `preferred` features and those this renderer lacks, `missing` and
        `lacking`, `budgets`, each quality's budgets as the static use and the limit, `files`,
        each file's `path`, `bytes` and `kind`, and `loudness`, the levels of each WAV sample.

    Raises:
        ArgumentError: If the path is no folder or archive of a team or a package.
    """
    path = Path(path)
    if path.is_file():
        source = _archive(path)
    elif path.is_dir():
        source = _folder(path)
    else:
        raise ArgumentError(f'expected a folder or a .zip archive of a team, found {str(path)!r}')
    report = _Report()
    for message in source.errors:
        report.add('errors', message)
    for message in source.info:
        report.add('info', message)
    result: dict[str, Any] = {
        'ok': False,
        'errors': report.errors,
        'warnings': report.warnings,
        'info': report.info,
        'manifest': None,
        'features': {'required': [], 'preferred': [], 'missing': [], 'lacking': []},
        'budgets': {},
        'files': [],
        'loudness': [],
    }
    assets = _files(source, result, report)
    if MANIFEST not in source.sizes:
        report.add('errors', f'the package holds no {MANIFEST}, so the team draws its stock look')
        return _finish(result, report)
    if MANIFEST not in assets:
        return _finish(result, report)
    data = source.read(MANIFEST)
    if len(data) > _presentation.MAXIMUM_MANIFEST_BYTES:
        report.add('errors', 'the manifest holds more than 256 KB, so the page draws without it')
        return _finish(result, report)
    document = json.loads(data.decode('utf-8'))
    result['manifest'] = _manifest(document, assets, report)
    if not isinstance(document, dict):
        return _finish(result, report)
    result['features'] = _features(document, report)
    for shader, mode in _glsl.shaders(document):
        if shader in assets:
            text = source.read(shader).decode('utf-8', 'replace')
            for problem in _glsl.check(text, mode):
                report.add('errors', f'{shader} of mode {mode} {problem}')
    stats, counts = _models(document, source, assets, report)
    named = _references(document, assets, stats, report)
    result['budgets'] = _budgets(document, source, assets, stats, counts, named, report)
    _markers(document, stats, report)
    _modules(document, source, assets, report)
    result['loudness'] = _sounds(assets, source, report)
    for name in sorted(set(assets) - named - {MANIFEST}):
        report.add('info', f'{name} is named by no part of the manifest')
    return _finish(result, report)


def _files(source: _Source, result: dict[str, Any], report: _Report) -> dict[str, str]:
    """Checks every file of the package as an import does and returns those that stay."""
    assets: dict[str, str] = {}
    total = 0
    for name in sorted(source.sizes):
        size = source.sizes[name]
        suffix = PurePosixPath(name).suffix
        kind = 'manifest' if name == MANIFEST else _KINDS.get(suffix, 'other')
        result['files'].append({'path': name, 'bytes': size, 'kind': kind})
        try:
            _presentation.check_path(name)
            limit = _presentation.MAXIMUM_BYTES[suffix]
            if size > limit:
                raise ArgumentError(f'expected {name} of at most {limit} bytes, found {size}')
            _presentation.check_file(name, source.read(name))
        except (ArgumentError, OSError) as error:
            report.add('errors', f'{name} fails its check, so import deletes it, {error}')
            continue
        if len(assets) >= _presentation.MAXIMUM_FILES or (
            total + size > _presentation.MAXIMUM_TOTAL_BYTES
        ):
            report.add(
                'errors',
                f'{name} lies past the limits of a package, {_presentation.MAXIMUM_FILES} files '
                f'and {_presentation.MAXIMUM_TOTAL_BYTES // _MB} MB, so import deletes it',
            )
            continue
        total += size
        assets[name] = name
    return assets


def _manifest(document: Any, assets: dict[str, str], report: _Report) -> dict[str, Any] | None:
    """Runs the server's check of the manifest and sorts what it leaves out into the report.

    A manifest of a newer minor contract than this renderer's is read as this renderer's own,
    so its older sections are still checked, and what the check leaves out are warnings, since a
    newer renderer reads more of it.
    """
    version = document.get('contract') if isinstance(document, dict) else None
    match = re.fullmatch(r'(\d+)\.(\d+)', version) if isinstance(version, str) else None
    newer = (
        match is not None
        and int(match.group(1)) == _presentation.MAJOR
        and not _presentation.supported(version)
    )
    found: list[str] = []
    try:
        if newer:
            report.add(
                'warnings',
                f'the manifest is of contract {version}, newer than the contract '
                f'{_presentation.CONTRACT} of this renderer, which draws the team in its stock '
                f'look, so the checks read it as {_presentation.CONTRACT}',
            )
            manifest = _presentation.check(
                {**document, 'contract': _presentation.CONTRACT}, assets, found
            )
            manifest['contract'] = version
        else:
            manifest = _presentation.check(document, assets, found)
    except ArgumentError as error:
        report.add('errors', f'the page draws the team without its manifest, {error}')
        return None
    for message in found:
        report.add('errors' if ' left out' in message and not newer else 'warnings', message)
    return manifest


def _finish(result: dict[str, Any], report: _Report) -> dict[str, Any]:
    result['ok'] = not report.errors
    return result


def text_report(result: dict[str, Any], path: str | Path) -> str:
    """Returns the result of `check` as a readable report."""
    lines = [f'cuju render pack check {path}']
    manifest = result.get('manifest') or {}
    files = result.get('files', [])
    size = sum(item['bytes'] for item in files)
    lines.append(
        f'contract {manifest.get("contract", "unknown")}, {manifest.get("name", "no name")}, '
        f'{len(files)} files, {size / 1024:.1f} KB'
    )
    for title, key in (('errors', 'errors'), ('warnings', 'warnings'), ('information', 'info')):
        if result.get(key):
            lines.append(title)
            lines.extend(f'  {message}' for message in result[key])
    if result.get('budgets'):
        lines.append('budgets')
        for quality, budgets in result['budgets'].items():
            parts = [
                f'{_BUDGET_NAMES[key]} {used:,} of {limit:,}'
                for key, (used, limit) in budgets.items()
                if used or key in ('drawCalls', 'triangles', 'shaders')
            ]
            lines.append(f'  {quality}, ' + ', '.join(parts))
    if result.get('loudness'):
        lines.append('loudness')

        def level(value: float | None, unit: str) -> str:
            return f'{value:.1f} {unit}' if value is not None else 'silence'

        for item in result['loudness']:
            lines.append(
                f'  {item["file"]}, integrated {level(item["integrated"], "LUFS")}, momentary '
                f'{level(item["maxMomentary"], "LUFS")}, short-term '
                f'{level(item["maxShortTerm"], "LUFS")}, true peak '
                f'{level(item["truePeak"], "dBTP")}'
            )
    count = len(result.get('errors', []))
    lines.append('ok' if result.get('ok') else f'{count} error{"s" if count != 1 else ""}')
    return '\n'.join(lines)


# The template of a new package.


def _pad(data: bytes, fill: bytes = b'\0') -> bytes:
    return data + fill * (-len(data) % 4)


class _Writer:
    """Collects the binary buffer, views and accessors of one glTF file."""

    def __init__(self) -> None:
        self.binary = bytearray()
        self.views: list[dict[str, Any]] = []
        self.accessors: list[dict[str, Any]] = []

    def add(self, data: bytes, count: int, kind: str, component: int = 5126, **options: Any) -> int:
        offset = len(self.binary)
        self.binary.extend(_pad(data))
        view = {'buffer': 0, 'byteOffset': offset, 'byteLength': len(data)}
        if options.get('target'):
            view['target'] = options['target']
        self.views.append(view)
        accessor = {
            'bufferView': len(self.views) - 1,
            'componentType': component,
            'count': count,
            'type': kind,
        }
        if options.get('minimum') is not None:
            accessor['min'], accessor['max'] = options['minimum'], options['maximum']
        self.accessors.append(accessor)
        return len(self.accessors) - 1

    def glb(self, document: dict[str, Any]) -> bytes:
        document['buffers'] = [{'byteLength': len(self.binary)}]
        document['bufferViews'] = self.views
        document['accessors'] = self.accessors
        text = _pad(json.dumps(document).encode(), b' ')
        chunks = struct.pack('<II', len(text), _JSON_CHUNK) + text
        chunks += struct.pack('<II', len(self.binary), _BIN_CHUNK) + bytes(self.binary)
        return b'glTF' + struct.pack('<II', 2, 12 + len(chunks)) + chunks


def ring_bytes(segments: int = 24) -> bytes:
    """Returns a flat glowing ring of quads, 0.48 meters across, without a skin, to attach."""
    w = _Writer()
    points: list[float] = []
    for i in range(segments):
        angle = 2 * math.pi * i / segments
        for radius in (0.18, 0.24):
            points += [radius * math.cos(angle), 0.0, radius * math.sin(angle)]
    indices: list[int] = []
    for i in range(segments):
        a, b = 2 * i, 2 * ((i + 1) % segments)
        indices += [a, b, a + 1, b, b + 1, a + 1]
    position = w.add(
        struct.pack(f'<{len(points)}f', *points),
        len(points) // 3,
        'VEC3',
        target=34962,
        minimum=[-0.24, 0, -0.24],
        maximum=[0.24, 0, 0.24],
    )
    index = w.add(
        struct.pack(f'<{len(indices)}H', *indices),
        len(indices),
        'SCALAR',
        component=5123,
        target=34963,
    )
    material = {
        'name': 'Ring',
        'doubleSided': True,
        'emissiveFactor': [1.0, 0.75, 0.3],
        'pbrMetallicRoughness': {'baseColorFactor': [1.0, 0.85, 0.5, 1], 'metallicFactor': 0},
    }
    primitive = {'attributes': {'POSITION': position}, 'indices': index, 'material': 0}
    document = {
        'asset': {'version': '2.0', 'generator': 'cuju render pack new'},
        'scene': 0,
        'scenes': [{'nodes': [0]}],
        'nodes': [{'name': 'Ring', 'mesh': 0}],
        'materials': [material],
        'meshes': [{'primitives': [primitive]}],
    }
    return w.glb(document)


def tone_bytes(seconds: float = 0.15, frequency: float = 880.0, level: float = -12.0) -> bytes:
    """Returns a short sine tone with soft ends as a 16 bit mono WAV file at 48 kHz.

    Args:
        seconds: The length of the tone.
        frequency: Its pitch in hertz.
        level: Its peak in dB below full scale.
    """
    rate = 48000
    count = int(seconds * rate)
    ramp = int(0.005 * rate)
    amplitude = 10 ** (level / 20) * 32767
    values = []
    for i in range(count):
        edge = min(1.0, i / ramp, (count - 1 - i) / ramp)
        envelope = 0.5 - 0.5 * math.cos(math.pi * edge)
        values.append(round(amplitude * envelope * math.sin(2 * math.pi * frequency * i / rate)))
    samples = struct.pack(f'<{count}h', *values)
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',
        36 + len(samples),
        b'WAVE',
        b'fmt ',
        16,
        1,
        1,
        rate,
        rate * 2,
        2,
        16,
        b'data',
        len(samples),
    )
    return header + samples


_MAIN = '''"""The agent of the team, which Kaggle calls with each observation."""


def agent(obs):
    """Answers every player the team controls with the action 0, which keeps him idle."""
    return [0] * max(1, len(obs.get('players_raw') or []))
'''

_WORKER = """\
// The worker of the package, one module of its own without imports. The renderer runs it in a
// sandbox with no network, no files and no page, hands it the Hello once and then one Frame at a
// time, and draws the commands of each answer. docs/presentation.md describes every field.

let hello = null;
let frames = 0;

// Keeps the Hello, which names the team, its roster, the quality and the features at hand.
export function init(h) {
    hello = h;
    frames = 0;
}

// Answers each Frame. A reset starts a new epoch, after a seek, a cut or a restart of the worker,
// so the worker sets its behaviours again then, here a slow bob of every player of the team.
export function frame(f) {
    frames += 1;
    const out = { behaviours: [], log: [] };
    if (frames === 1 || f.reset) {
        out.behaviours.push({
            op: 'set',
            id: 'bob',
            behaviour: { type: 'oscillate', channel: 'y', amp: 0.02, freq: 0.6 },
        });
        out.log.push(`epoch ${f.epoch}, ${f.reset ? f.reset.reason : 'start'}, team ${hello.team}`);
    }
    // The log shows in the browser console, here each goal of the team.
    for (const e of f.events) {
        if (e.kind === 'goal' && e.phase === 'occur' && e.team === hello.team) {
            out.log.push(`goal at ${e.t.toFixed(1)} seconds`);
        }
    }
    return out;
}
"""

_GLOW = """\
// The glow of the team, a shader of mode chunks. The renderer declares every uniform, uPulse,
// which rises with each event of the team and decays, uTeamColor, the team's colour, and uGlow,
// the uniform that the manifest gives this material.

vec3 cujuEmissive(vec3 emissive, vec2 uv) {
    return emissive + uTeamColor * (uPulse * uGlow);
}
"""


def template_manifest(name: str = 'My team') -> dict[str, Any]:
    """Returns the manifest of the template package, of contract 1.1."""
    return {
        'contract': '1.1',
        'name': name,
        'requires': ['drivers.grf'],
        'prefers': ['shader.custom'],
        'rig': {
            'driver': 'grf',
            'sockets': {'crown': {'offset': [0, 2.05, 0]}},
            'attachments': {
                'ring': {'file': 'models/ring.glb', 'socket': 'crown', 'shadows': False}
            },
        },
        'behaviours': [
            {
                'id': 'ringSpin',
                'type': 'spin',
                'attachment': 'ring',
                'axis': [0, 1, 0],
                'rate': {'input': 'speed', 'keys': [[0, 1], [7, 4]]},
            }
        ],
        'materials': {
            'glow': {
                'match': '*',
                'shader': 'shaders/glow.glsl',
                'mode': 'chunks',
                'uniforms': {'uGlow': 0.6},
            }
        },
        'effects': {
            'spark': {
                'type': 'particles',
                'count': 40,
                'duration': 0,
                'life': [0.2, 0.5],
                'speed': [1, 4],
                'spread': 0.8,
                'gravity': -9.8,
                'size': [0.06, 0],
                'color': [[255, 230, 160], [255, 120, 40]],
                'opacity': [1, 0],
                'blend': 'additive',
            },
            'streak': {
                'type': 'trail',
                'length': 0.4,
                'width': [0.12, 0],
                'color': [[255, 255, 255], [255, 200, 120]],
                'opacity': [0.8, 0],
                'blend': 'additive',
                'duration': 1.2,
            },
            'flare': {
                'type': 'light',
                'color': [255, 220, 150],
                'intensity': 8,
                'distance': 12,
                'decay': 2,
                'duration': 1.5,
                'attack': 0.1,
                'release': 1,
            },
        },
        'audio': {'cues': {'tick': ['audio/tick.wav']}},
        'reflexes': [
            {
                'on': 'touch',
                'where': {'team': 'self'},
                'do': [
                    {'audio': 'tick', 'at': 'contact', 'replay': 'quiet'},
                    {'effect': 'spark', 'attach': 'ball', 'claim': 'ball'},
                ],
            },
            {
                'on': 'shot',
                'where': {'team': 'self'},
                'do': [{'effect': 'streak', 'attach': 'ball', 'claim': 'ball'}],
            },
            {
                'on': 'goal',
                'where': {'team': 'self'},
                'do': [{'effect': 'flare', 'attach': 'self'}],
            },
        ],
        'worker': 'worker.js',
        'reducedMotion': {'amplitude': 0.3},
    }


def template_files(name: str = 'My team') -> dict[str, bytes]:
    """Returns every file of the template by its path in a team's submission folder."""
    team = {'name': name, 'format': '11v11', 'style': {'model': 'grf'}}
    folder = f'{_teams.TEAM_FOLDER}/{FOLDER}'
    return {
        'main.py': _MAIN.encode(),
        f'{_teams.TEAM_FOLDER}/team.json': (json.dumps(team, indent=4) + '\n').encode(),
        f'{folder}/{MANIFEST}': (json.dumps(template_manifest(name), indent=4) + '\n').encode(),
        f'{folder}/worker.js': _WORKER.encode(),
        f'{folder}/shaders/glow.glsl': _GLOW.encode(),
        f'{folder}/models/ring.glb': ring_bytes(),
        f'{folder}/audio/tick.wav': tone_bytes(),
    }


def preview(path: str | Path, side: str = 'left') -> str:
    """Registers a package as a team, sets the side that draws it and returns the page to open.

    A zip registers as it is, a folder as the zip an export of it would make. The team draws on
    `side` of the shipped five a side sample, with the preview panel of the page open.

    Raises:
        ArgumentError: If the path is neither a team folder nor a zip, or import refuses it.
    """
    from .._http import launch as _launch
    from .._registry import teams as _teams
    from .._store import library as _library

    source = Path(path).expanduser()
    if source.is_file() and source.suffix == '.zip':
        data, name = source.read_bytes(), source.stem
    elif source.is_dir():
        root = source
        if (root / 'presentation.json').is_file():
            root = root.parent.parent
        elif root.name == _teams.TEAM_FOLDER:
            root = root.parent
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            for item in sorted(root.rglob('*')):
                if item.is_file() and not item.is_symlink() and '__pycache__' not in item.parts:
                    archive.write(item, item.relative_to(root).as_posix())
        data, name = buffer.getvalue(), root.name
    else:
        raise ArgumentError(f'expected a team folder or a zip to preview, found {path}')
    team = _teams.add(f'Preview of {name}'[:60], 'team.zip', data)
    _presentation.assign({side: team['id']})
    place = _launch.resolve(str(_library._SAMPLES / 'sample-5v5.cjr'))
    return f'{place}&preview=1'


def new(folder: str | Path, name: str = 'My team') -> list[Path]:
    """Writes a small working team with a presentation package into a new folder.

    Args:
        folder: The folder to write, absent or empty.
        name: The name of the team and of its package.

    Returns:
        The paths of the files written.

    Raises:
        ArgumentError: If the folder holds anything already, or the name is empty.
    """
    folder = Path(folder)
    if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
        raise ArgumentError(f'expected an empty folder for the new team, found {str(folder)!r}')
    name = _teams._printable(str(name)).strip()[:80]
    if not name:
        raise ArgumentError('expected a name of the team')
    written = []
    for relative, data in template_files(name).items():
        target = folder.joinpath(*relative.split('/'))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.append(target)
    return written
