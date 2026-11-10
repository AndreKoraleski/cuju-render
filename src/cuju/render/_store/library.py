# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The library of saved matches, each a `.cjr` file with a small summary beside it.

The files lie side by side in one folder, and each summary names the folder of the page's explorer
that its match sits in, a path such as `League/Week 1`, so moving a match rewrites one small file.
The summary also keeps the favorite mark, tags and notes of the page, and the time a recording
went to the Trash, so marking, tagging and trashing never rewrite the frames.
"""

from __future__ import annotations

import json
import shutil
import struct
import time
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any, TypeVar

from cuju.errors import ArgumentError

from .._format import recording as _recording
from . import home as _home

_SCORE = struct.Struct('<2i')
# The sample matches that ship with the package, which the library receives once each.
_SAMPLES = Path(__file__).parents[1] / 'samples'
# The file of the home folder that names the samples the library has received.
_SEEDED = 'samples.json'
# The limits of the details that the page edits.
_TAGS, _TAG_LENGTH, _NOTES_LENGTH = 20, 40, 10000
# One server thread at a time reads and writes the summaries, so no change undoes another.
_LOCK = RLock()
_Function = TypeVar('_Function', bound=Callable[..., Any])


def _locked(function: _Function) -> _Function:
    """Runs `function` with the lock of the library held."""

    @wraps(function)
    def call(*arguments: Any, **options: Any) -> Any:
        with _LOCK:
            return function(*arguments, **options)

    return call  # type: ignore[return-value]


def _summary(path: Path) -> dict[str, Any]:
    """Returns the summary of a recording, with every field the page reads in its expected type.

    A missing or unreadable summary is made again from the header, and a field of the wrong type,
    from a hand edit or another version, falls back to its default.
    """
    try:
        entry = json.loads(path.with_suffix('.json').read_text())
        if not isinstance(entry, dict):
            raise ValueError('expected a summary object')
    except (OSError, ValueError):
        entry = _summarize(path)
    for key, kind, default in (
        ('folder', str, ''),
        ('provenance', dict, {}),
        ('favorite', bool, False),
        ('tags', list, []),
        ('notes', str, ''),
    ):
        if not isinstance(entry.get(key), kind):
            entry[key] = default
    entry['tags'] = [tag for tag in entry['tags'] if isinstance(tag, str)]
    if not isinstance(entry.get('deleted_at'), str):
        entry.pop('deleted_at', None)
    return entry


def _store(path: Path, summary: dict[str, Any]) -> None:
    """Writes the summary of the recording at `path` through a temporary file."""
    target = path.with_suffix('.json')
    temporary = target.with_name(target.name + '.part')
    temporary.write_text(json.dumps(summary))
    temporary.replace(target)


def save(
    head: bytes,
    frames: list[bytes],
    identifier: str | None = None,
    version: int = _recording.VERSION,
    annotations: list[dict[str, Any]] | None = None,
) -> Path:
    """Writes a recording and its summary into the library and returns the recording's path.

    Args:
        head: The magic, length and header, as `_recording.header` returns them.
        frames: The frames.
        identifier: The name of the files, by default a new one that no recording holds.
        version: The version of the recording file.
        annotations: The records of the annotations, which version 2 keeps.
    """
    if identifier is None:
        path = reserve()
    else:
        path = _home.folder('matches') / f'{identifier}.cjr'
    try:
        _recording.write(path, head, frames, version, annotations)
        document = json.loads(head[len(_recording.MAGIC) + 4 :])
        _write_summary(path, document, frames[-1] if frames else None, len(frames))
    except BaseException:
        if identifier is None:
            path.with_suffix('.json').unlink(missing_ok=True)
        raise
    return path


def reserve() -> Path:
    """Returns the path of a new recording under an identifier that no other recording holds.

    Identifiers sort by the second they are made in, so recorders of several processes that save
    in the same second differ by their random end alone. The summary's file is created at once,
    which only one saver can do, and a draw that is taken is drawn again.
    """
    folder = _home.folder('matches')
    while True:
        path = folder / f'{_home.new_identifier("m")}.cjr'
        if path.exists():
            continue
        try:
            with path.with_suffix('.json').open('x'):
                pass
        except FileExistsError:
            continue
        return path


def _write_summary(
    path: Path, document: dict[str, Any], last: bytes | None, steps: int
) -> dict[str, Any]:
    """Writes the summary of the recording at `path` beside it and returns the summary."""
    summary = {
        'id': path.stem,
        'title': document['title'],
        'scenario': document['scenario'],
        'teams': [team['name'] for team in document['teams']],
        'score': list(_SCORE.unpack_from(last, 8)) if last else [0, 0],
        'steps': steps,
        'created': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'bytes': path.stat().st_size,
        'folder': '',
        # A recording made before provenance, such as a shipped sample, has none to carry.
        'provenance': document.get('provenance')
        if isinstance(document.get('provenance'), dict)
        else {},
    }
    path.with_suffix('.json').write_text(json.dumps(summary))
    return summary


def samples() -> list[str]:
    """Returns the names of the sample matches that ship with the package, such as `sample-5v5`."""
    return sorted(path.stem for path in _SAMPLES.glob('*.cjr'))


def _seeded() -> set[str]:
    """Returns the names of the samples that the library has received."""
    try:
        return set(json.loads((_home.home() / _SEEDED).read_text())['seeded'])
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def _add_sample(name: str) -> Path | None:
    """Copies a sample into the library and returns its path, or `None` when the name is taken.

    The library keeps the sample as it keeps any recording, and a recording or summary of the same
    name stays as it is.
    """
    path = _home.folder('matches') / f'{name}.cjr'
    if path.exists() or path.with_suffix('.json').exists():
        return None
    temporary = path.with_name(path.name + '.part')
    shutil.copyfile(_SAMPLES / f'{name}.cjr', temporary)
    temporary.replace(path)
    document = _recording.read_header(path)
    # A file of version 2 decodes its last frame from the keyframe before it.
    last = None
    for frame in _recording.frames(path, start=max(0, document['frame_count'] - 1)):
        last = frame
    _write_summary(path, document, last, document['frame_count'])
    return path


def add_samples(names: list[str] | None = None, again: bool = True) -> list[Path]:
    """Copies sample matches into the library and returns the paths of those added.

    Each sample is marked as received in the home folder, so a deleted sample stays deleted until
    it is requested again. A request brings a sample in the Trash back with its details, as
    Restore does, and counts it among those added.

    Args:
        names: The samples, by default every one.
        again: Whether to add samples that the library has received before, as a request does,
            or only new ones, as the first start of the server does, which leaves the Trash as it
            is.

    Raises:
        ArgumentError: If a name is not a shipped sample.
    """
    shipped = samples()
    names = shipped if names is None else names
    unknown = [name for name in names if name not in shipped]
    if unknown:
        raise ArgumentError(f'expected a sample from {shipped}, found {unknown}')
    seeded = _seeded()
    wanted = [name for name in names if again or name not in seeded]
    if not wanted:
        return []
    added = [path for path in map(_add_sample, wanted) if path is not None]
    if again:
        added += [path_of(name) for name in wanted if trash(name, restore=True)]
    marker = _home.home() / _SEEDED
    temporary = marker.with_name(marker.name + '.part')
    temporary.write_text(json.dumps({'seeded': sorted(seeded | set(wanted))}))
    temporary.replace(marker)
    return added


@_locked
def matches(trash: bool = False) -> list[dict[str, Any]]:
    """Returns the summary of every recording of the library, or of the Trash, newest first."""
    entries = []
    for path in _home.folder('matches').glob('*.cjr'):
        entry = _summary(path)
        if ('deleted_at' in entry) == trash:
            entries.append(entry)
    entries.sort(key=lambda entry: str(entry.get('created') or ''), reverse=True)
    return entries


def _summarize(path: Path) -> dict[str, Any]:
    """Returns the summary of a recording that has none, such as one copied into the folder."""
    provenance: Any = {}
    try:
        document = _recording.read_header(path)
        teams = [team['name'] for team in document['teams']]
        title, scenario = document['title'], document['scenario']
        provenance = document.get('provenance', {})
    except Exception:
        teams, title, scenario = ['', ''], path.stem, ''
    created = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(path.stat().st_mtime))
    return {
        'id': path.stem,
        'title': title,
        'scenario': scenario,
        'teams': teams,
        'score': None,
        'steps': None,
        'created': created,
        'bytes': path.stat().st_size,
        'provenance': provenance if isinstance(provenance, dict) else {},
    }


def _folder_path(folder: Any) -> str:
    """Returns a folder of the explorer in canonical form, or raises `ArgumentError`."""
    if not isinstance(folder, str):
        raise ArgumentError(f'expected a folder as text, found {folder!r}')
    parts = [part.strip() for part in folder.replace('\\', '/').split('/') if part.strip()]
    if any(part in ('.', '..') or len(part) > 64 for part in parts) or len(parts) > 8:
        raise ArgumentError(
            f'expected a folder of at most 8 names of 64 characters, found {folder!r}'
        )
    return '/'.join(parts)


@_locked
def update(
    identifier: str,
    title: str | None = None,
    folder: str | None = None,
    favorite: bool | None = None,
    tags: list[str] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Renames a recording, moves it to a folder or edits its details, and returns its summary.

    Every change is checked before any is kept, so a refused change leaves the summary as it was.

    Args:
        identifier: The recording.
        title: The new title, or `None` to keep it.
        folder: The folder, such as `League/Week 1`, the empty text for the top, or `None`.
        favorite: Whether the recording is a favorite, or `None` to keep the mark.
        tags: Up to twenty tags of at most forty characters, or `None` to keep them. Repeated
            tags are kept once.
        notes: Notes of at most ten thousand characters, or `None` to keep them.

    Raises:
        ArgumentError: If the recording is unknown or in the Trash, or a change is invalid.
    """
    path = path_of(identifier)
    if path is None:
        raise ArgumentError(f'expected a recording of the library, found {identifier!r}')
    summary = _summary(path)
    if favorite is not None:
        if not isinstance(favorite, bool):
            raise ArgumentError(f'expected favorite as true or false, found {favorite!r}')
        summary['favorite'] = favorite
    if tags is not None:
        if (
            not isinstance(tags, list)
            or len(tags) > _TAGS
            or not all(isinstance(tag, str) and 0 < len(tag.strip()) <= _TAG_LENGTH for tag in tags)
        ):
            raise ArgumentError('expected up to twenty tags, each of one to forty characters')
        summary['tags'] = list(dict.fromkeys(tag.strip() for tag in tags))
    if notes is not None:
        if not isinstance(notes, str) or len(notes) > _NOTES_LENGTH:
            raise ArgumentError('expected notes as text of at most ten thousand characters')
        summary['notes'] = notes
    if title is not None:
        title = str(title).strip()[:120]
        if not title:
            raise ArgumentError('expected a title with at least one character')
        summary['title'] = title
    if folder is not None:
        summary['folder'] = _folder_path(folder)
    _store(path, summary)
    return summary


@_locked
def path_of(identifier: str, include_trash: bool = False) -> Path | None:
    """Returns the path of a recording, or `None` for an unknown or unsafe identifier.

    The identifier must be a plain file name, so no request reaches outside the library's folder.
    A recording in the Trash counts as unknown unless `include_trash` is true.
    """
    if not isinstance(identifier, str) or not _home.valid_identifier(identifier):
        return None
    path = _home.folder('matches') / f'{identifier}.cjr'
    if not path.is_file() or (not include_trash and 'deleted_at' in _summary(path)):
        return None
    return path


@_locked
def details(identifier: str) -> dict[str, Any]:
    """Returns the summary of a recording of the library, with its details and provenance.

    Raises:
        ArgumentError: If the recording is unknown or in the Trash.
    """
    path = path_of(identifier)
    if path is None:
        raise ArgumentError(f'expected a recording of the library, found {identifier!r}')
    return _summary(path)


@_locked
def trash(identifier: str, restore: bool = False) -> bool:
    """Moves a recording to the Trash, or restores it, and returns whether it existed.

    Only the summary changes, so a restored recording keeps its frames, folder and details.
    """
    path = path_of(identifier, include_trash=True)
    if path is None:
        return False
    summary = _summary(path)
    if restore:
        if 'deleted_at' not in summary:
            return False
        del summary['deleted_at']
    else:
        if 'deleted_at' in summary:
            return False
        summary['deleted_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    _store(path, summary)
    return True


@_locked
def purge(identifier: str) -> bool:
    """Deletes a recording of the Trash for good, and returns whether there was one to delete.

    A recording outside the Trash stays, so a permanent deletion always passes through the Trash.
    """
    path = path_of(identifier, include_trash=True)
    if path is None or 'deleted_at' not in _summary(path):
        return False
    path.unlink()
    path.with_suffix('.json').unlink(missing_ok=True)
    return True


@_locked
def remove(identifier: str) -> bool:
    """Deletes a recording and its summary at once, in the Trash or not, and says if it existed."""
    path = path_of(identifier, include_trash=True)
    if path is None:
        return False
    path.unlink()
    path.with_suffix('.json').unlink(missing_ok=True)
    return True
