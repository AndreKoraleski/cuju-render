# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The celebration clips that a team uploads, animations on a skinned skeleton in binary glTF.

A clip is a binary glTF 2.0 file, `.glb`, with a skinned skeleton and one or more animations. The
page turns each animation into poses of GRF's skeleton by a joint mapping, as it does for a custom
model, so any model of a team plays it after a goal. The files live in the folder `clips` of the
team's `cuju-team` folder, each beside a small JSON file with its joint mapping and the names of its
animations, and travel with the team when it is exported.

Every file is checked as it arrives and again when an exported team comes back. A clip holds at
most 10 MB, a team at most 16 clips and 40 MB of them, and a name of the page's own making, so no
request reaches outside the team's folder.
"""

from __future__ import annotations

import contextlib
import json
import re
import struct
from pathlib import Path
from typing import Any

from cuju.errors import ArgumentError

from .._text.messages import MessageError
from . import teams as _teams

FOLDER = 'clips'
MAXIMUM_CLIP_BYTES = 10 * 1024 * 1024
MAXIMUM_TEAM_BYTES = 40 * 1024 * 1024
MAXIMUM_CLIPS = 16
MAXIMUM_ANIMATIONS = 32
# A clip's name, which the page makes from the file's name, is its file's name too.
_NAME = re.compile(r'[a-z0-9_]{1,40}')
# glTF: the chunk types of a binary file, its JSON and its binary buffer.
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942
# Extensions whose decoders the page leaves out, so a file that requires one cannot load there.
_UNSUPPORTED = ('KHR_draco_mesh_compression', 'EXT_meshopt_compression', 'KHR_texture_basisu')


def check_name(name: Any) -> str:
    """Returns the name of a clip, or raises `ArgumentError` for one that is no safe file name."""
    if not isinstance(name, str) or not _NAME.fullmatch(name) or _teams._device(name):
        raise MessageError('server.clips.name', name=repr(name))
    return name


def _uris(value: Any) -> list[str]:
    """Returns every `uri` string of a glTF document that names something outside the file."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'uri' and isinstance(item, str) and not item.startswith('data:'):
                found.append(item)
            else:
                found.extend(_uris(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_uris(item))
    return found


def check(data: bytes) -> dict[str, Any]:
    """Checks the bytes of a clip and returns the names of its animations and skinned bones.

    Returns:
        A dictionary with `animations`, the names of the animations in file order, and `bones`,
        the names of the joints of every skin.

    Raises:
        ArgumentError: If the bytes are too many, are no binary glTF 2.0 file of sound chunks,
            link to outside files, need a decoder that the page lacks, or hold no skin or no
            animation.
    """
    if len(data) > MAXIMUM_CLIP_BYTES:
        raise MessageError('server.clips.size', size=len(data))
    # glTF: a binary file opens with `glTF`, the version and the length, then its chunks, each
    # with its length and type, padded to four bytes, the JSON chunk first.
    if len(data) < 20 or data[:4] != b'glTF':
        raise MessageError('server.clips.binary')
    version, length = struct.unpack_from('<II', data, 4)
    if version != 2:
        raise MessageError('server.clips.version', version=version)
    if length != len(data):
        raise MessageError('server.clips.length', length=length, size=len(data))
    chunks = []
    offset = 12
    while offset < length:
        if offset + 8 > length:
            raise MessageError('server.clips.cut')
        size, kind = struct.unpack_from('<II', data, offset)
        if size % 4 or offset + 8 + size > length:
            raise MessageError('server.clips.padding')
        chunks.append((kind, offset + 8, size))
        offset += 8 + size
    if not chunks or chunks[0][0] != _JSON_CHUNK:
        raise MessageError('server.clips.json_first')
    if any(kind == _JSON_CHUNK for kind, _, _ in chunks[1:]) or (
        sum(kind == _BIN_CHUNK for kind, _, _ in chunks) > 1
        or any(kind == _BIN_CHUNK for kind, _, _ in chunks[2:])
    ):
        raise MessageError('server.clips.chunks')
    _, start, size = chunks[0]
    try:
        document = json.loads(data[start : start + size])
        outside = _uris(document)
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise MessageError('server.clips.json', error=error) from error
    if not isinstance(document, dict):
        raise MessageError('server.clips.json_object')
    asset = document.get('asset')
    if not isinstance(asset, dict) or not str(asset.get('version', '')).startswith('2.'):
        raise MessageError('server.clips.asset_version')
    if outside:
        raise MessageError('server.clips.link', uri=repr(outside[0]))
    binary = next((size for kind, _, size in chunks if kind == _BIN_CHUNK), None)
    for buffer in _teams._array(document.get('buffers')):
        if isinstance(buffer, dict) and 'uri' not in buffer:
            if binary is None or not isinstance(buffer.get('byteLength'), int):
                raise MessageError('server.clips.buffer')
            if buffer['byteLength'] > binary:
                raise MessageError('server.clips.buffer_length')
    required = [
        name for name in _teams._array(document.get('extensionsRequired')) if name in _UNSUPPORTED
    ]
    if required:
        raise MessageError('server.clips.extension', extension=required[0])
    nodes = document.get('nodes') or []
    skins = document.get('skins') or []
    if not isinstance(nodes, list) or not isinstance(skins, list) or not skins:
        raise MessageError('server.clips.skinned')
    bones = set()
    for skin in skins:
        for joint in _teams._array(skin.get('joints')) if isinstance(skin, dict) else []:
            if (
                isinstance(joint, int)
                and 0 <= joint < len(nodes)
                and isinstance(nodes[joint], dict)
            ):
                bones.add(str(nodes[joint].get('name', '')))
    if not bones:
        raise MessageError('server.clips.skin_joints')
    animations = document.get('animations') or []
    if not isinstance(animations, list) or not animations:
        raise MessageError('server.clips.animations_none')
    if len(animations) > MAXIMUM_ANIMATIONS:
        raise MessageError(
            'server.clips.animations_count', most=MAXIMUM_ANIMATIONS, count=len(animations)
        )
    names = []
    for index, animation in enumerate(animations):
        channels = animation.get('channels') if isinstance(animation, dict) else None
        samplers = animation.get('samplers') if isinstance(animation, dict) else None
        if not isinstance(channels, list) or not channels or not isinstance(samplers, list):
            raise MessageError('server.clips.animation', index=index)
        for channel in channels:
            target = channel.get('target') if isinstance(channel, dict) else None
            node = target.get('node') if isinstance(target, dict) else None
            sampler = channel.get('sampler') if isinstance(channel, dict) else None
            if not (
                isinstance(node, int)
                and 0 <= node < len(nodes)
                and isinstance(sampler, int)
                and 0 <= sampler < len(samplers)
            ):
                raise MessageError('server.clips.channels', index=index)
        name = animation.get('name')
        name = _teams._printable(name).strip()[:60] if isinstance(name, str) else ''
        names.append(name or f'Animation {index + 1}')
    return {'animations': names, 'bones': bones}


def _check_joints(joints: Any, bones: set[str]) -> dict[str, str]:
    """Returns a joint mapping of a clip, empty for one that the page guesses from bone names."""
    if joints is None:
        return {}
    if not isinstance(joints, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in joints.items()
    ):
        raise MessageError('server.clips.joints', joints=repr(joints))
    if not joints:
        return {}
    if 'body' not in joints:
        raise MessageError('server.clips.body')
    unknown = [joint for joint in joints if joint not in (*_teams.JOINTS, 'player')]
    if unknown:
        raise MessageError('server.clips.unknown_joints', joints=', '.join(unknown))
    absent = [bone for bone in joints.values() if bone not in bones]
    if absent:
        raise MessageError('server.clips.missing_bones', bones=', '.join(absent))
    return dict(joints)


def _folder(identifier: str) -> Path:
    """Returns the folder of a team's clips, without creating it."""
    return _teams._meta_path(identifier).parent / FOLDER


def _sidecar(path: Path) -> Path:
    """Returns the JSON file beside a clip, which keeps its mapping and animation names."""
    return path.with_suffix('.json')


def _clip_files(folder: Path) -> list[Path]:
    """Returns the clips of a folder of clips, the files named exactly as a clip, in name order.

    Windows and macOS find a file whatever the case of its name, so the names come from the
    folder's own listing, and a link, which could point outside the team's folder, is left out.
    """
    return sorted(
        path
        for name in _teams._names(folder)
        if name.endswith('.glb') and _NAME.fullmatch(name[: -len('.glb')])
        if (path := folder / name).is_file() and not path.is_symlink()
    )


def listing(team_folder: Path) -> list[dict[str, Any]]:
    """Returns the clips of a team's `cuju-team` folder, each its name, size, animations and joints.

    The JSON file beside each clip, which the server wrote after checking the clip, gives the
    animations and the joints. A clip whose JSON file is missing or damaged is checked again.
    """
    folder = team_folder / FOLDER
    clips = []
    for path in _clip_files(folder):
        try:
            meta = json.loads(_sidecar(path).read_text())
            animations = meta['animations']
            joints = meta['joints']
            if not (isinstance(animations, list) and isinstance(joints, dict)):
                raise ValueError('expected the animations and joints of a clip')
        except (OSError, ValueError, KeyError, TypeError):
            try:
                found = check(path.read_bytes())
            except (OSError, ArgumentError):
                continue
            animations, joints = found['animations'], {}
            with contextlib.suppress(OSError):
                _write_sidecar(path, animations, joints)
        clips.append(
            {
                'name': path.stem,
                'bytes': path.stat().st_size,
                'animations': animations,
                'joints': joints,
            }
        )
    return clips


def _write_sidecar(path: Path, animations: list[str], joints: dict[str, str]) -> None:
    """Writes the JSON file beside a clip."""
    _teams._replace(
        _sidecar(path), json.dumps({'animations': animations, 'joints': joints}).encode()
    )


def set_clip(
    identifier: str, name: str, data: bytes, joints: dict[str, str] | None = None
) -> dict[str, Any]:
    """Stores a celebration clip of a team, or replaces the clip of that name.

    Args:
        identifier: The team, the built-in AI included.
        name: The clip's name, up to 40 lowercase letters, digits and underscores.
        data: The binary glTF 2.0 file, with a skinned skeleton and at least one animation.
        joints: The bone that each joint of GRF's skeleton follows, `body` always, or an empty
            mapping or `None` for the page to map the bones by their names.

    Returns:
        The team's new entry.

    Raises:
        ArgumentError: If the team is unknown, the name unsafe, the file fails a check of
            `check`, the mapping names an unknown joint or bone, or the team would hold more
            than 16 clips or 40 MB of them.
    """
    _teams.entry(identifier)
    check_name(name)
    found = check(data)
    mapping = _check_joints(joints, found['bones'])
    folder = _folder(identifier)
    path = folder / f'{name}.glb'
    with _teams._LOCK:
        others = [other for other in _clip_files(folder) if other != path]
        if len(others) >= MAXIMUM_CLIPS:
            raise MessageError('server.clips.count', most=MAXIMUM_CLIPS)
        total = sum(other.stat().st_size for other in others) + len(data)
        if total > MAXIMUM_TEAM_BYTES:
            raise MessageError('server.clips.total', total=total)
        _teams._replace(path, data)
        _write_sidecar(path, found['animations'], mapping)
    return _teams.entry(identifier)


def set_joints(identifier: str, name: str, joints: Any) -> dict[str, Any]:
    """Changes the joint mapping of a team's clip and returns the team's new entry."""
    path = clip_path(identifier, name)
    if path is None:
        raise MessageError('server.clips.unknown', name=repr(name))
    found = check(path.read_bytes())
    mapping = _check_joints(joints, found['bones'])
    with _teams._LOCK:
        _write_sidecar(path, found['animations'], mapping)
    return _teams.entry(identifier)


def clip_path(identifier: str, name: str) -> Path | None:
    """Returns the file of a team's clip, or `None`."""
    if identifier != _teams.BUILTIN and not _teams._home.valid_identifier(identifier):
        return None
    try:
        check_name(name)
    except ArgumentError:
        return None
    return _teams._exact(_folder(identifier), f'{name}.glb')


def remove_clip(identifier: str, name: str) -> bool:
    """Deletes a team's clip and returns whether it existed.

    The team's celebrations that named the clip's animations go with it, and a player who had
    one of them as his own takes the team's celebrations again.
    """
    path = clip_path(identifier, name)
    if path is None:
        return False
    with _teams._LOCK:
        path.unlink()
        _sidecar(path).unlink(missing_ok=True)
        current = _teams.entry(identifier)
        prefix = f'upload:{name}.'
        style = current['style']
        style['celebrations'] = [
            item for item in style['celebrations'] if not item.startswith(prefix)
        ]
        for player in style['players']:
            if str(player.get('celebration', '')).startswith(prefix):
                player['celebration'] = 'team'
        _teams._write(identifier, current)
    return True


def import_folder(team_folder: Path) -> None:
    """Checks the clips of an exported team as uploads are checked, and sets aside what fails.

    The mapping of a clip comes back when it names joints and bones of the clip, and is left to
    the page's guess otherwise. Clips beyond the limits of a team are set aside in name order.
    A clip set aside keeps its bytes under its name followed by `.rejected`, and files that the
    page never reads as clips stay as they are.
    """
    folder = team_folder / FOLDER
    if not (folder.exists() or folder.is_symlink()) or not _teams._kept(folder):
        return
    if not folder.is_dir():
        _teams.set_aside(folder, 'it is no folder of clips')
        return
    kept = 0
    total = 0
    for path in sorted(folder.iterdir()):
        if not _teams._kept(path):
            continue
        if path.suffix != '.glb' or not _NAME.fullmatch(path.stem):
            # A name that is a clip's name in another case, such as `foo.GLB`, is set aside, so no
            # system that finds names whatever their case reads it as a clip.
            lower = path.name.lower()
            if lower.endswith('.glb') and _NAME.fullmatch(lower[: -len('.glb')]):
                _teams.set_aside(path, 'its name is the name of a clip in another case')
            continue
        try:
            data = path.read_bytes()
            found = check(data)
            valid = kept < MAXIMUM_CLIPS and total + len(data) <= MAXIMUM_TEAM_BYTES
        except Exception:
            # A clip that fails any part of its check, however it fails, counts as failing.
            valid = False
        if not valid:
            _teams.set_aside(path, 'it fails the checks of a clip or the limits of a team')
            continue
        kept += 1
        total += len(data)
        joints: Any = None
        with contextlib.suppress(OSError, ValueError, KeyError, TypeError, AttributeError):
            joints = json.loads(_sidecar(path).read_text()).get('joints')
        try:
            mapping = _check_joints(joints, found['bones'])
        except ArgumentError:
            mapping = {}
        _write_sidecar(path, found['animations'], mapping)
