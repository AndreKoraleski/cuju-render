# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The video exports that the page asks the server for, one at a time, each in a child process.

Each export runs `python -m cuju.render._export.video` on a recording of the library and writes into
the folder `videos` of the renderer, where the page downloads the file. The browser that the export
opens encodes the video itself, MP4 where it encodes H.264 and WebM otherwise, so the server needs a
Chrome, Edge or Chromium and nothing beside it. The folder holds the videos
of the running server alone, the latest few, and the server empties it of older files before its
first export.
"""

from __future__ import annotations

import collections
import contextlib
import json
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from cuju.errors import ArgumentError

from .._store import home as _home
from .._store import library as _library
from .._text import messages as _messages
from .._text.messages import MessageError
from . import sizes as _sizes
from . import video as _video

# The videos that the folder keeps, the latest ones, beside the export that runs.
KEPT = 3
# An export ends after this many seconds, longer than the longest range takes on a slow machine.
_EXPORT_SECONDS = 3 * 60 * 60
# The frame rates that the page's dialog offers. An export over HTTP takes any whole rate from 1
# to `_video.MAX_FPS`, as the command line does. The page offers the sizes of `_sizes`, and any
# other size with even sides within its limits.
RATES = (24, 25, 30, 50, 60)


class BusyError(_messages.Message, Exception):
    """Raised when an export is asked for while another one runs, with the id of its message."""


def _seconds(value: Any, name: str) -> float:
    """Returns a number of seconds from the page, or raises `ArgumentError`."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < 1e6:
        raise MessageError('server.video.seconds', name=name, value=repr(value))
    return float(value)


def options_from(document: dict[str, Any]) -> tuple[list[str], _video.Options]:
    """Returns the command line arguments of an export that the page asks for, and its options.

    The page names the start and end in seconds, the camera, the size, the frame rate as a whole
    number from 1 to `_video.MAX_FPS`, the quality, the scale and safe area of the graphics,
    whether the scoreboard and the annotations show and the arena and hour of its field.

    Raises:
        ArgumentError: If a field is missing, unknown or invalid.
    """
    known = {
        'start',
        'end',
        'camera',
        'width',
        'height',
        'fps',
        'quality',
        'score',
        'annotations',
        'arena',
        'time',
        'scale',
        'safe',
    }
    unknown = set(document) - known
    if unknown:
        raise MessageError(
            'server.video.fields', known=', '.join(sorted(known)), unknown=sorted(unknown)
        )
    start = _seconds(document.get('start', 0), 'start')
    end = _seconds(document.get('end'), 'end')
    if end <= start:
        raise MessageError('server.video.range', start=f'{start:g}', end=f'{end:g}')
    size = _sizes.check_size(document.get('width', 1280), document.get('height', 720), even=True)
    graphics = document.get('scale', 1.0)
    if isinstance(graphics, bool) or not isinstance(graphics, (int, float)):
        raise MessageError('server.video.scale', graphics=repr(graphics))
    safe = document.get('safe', 'auto')
    if isinstance(safe, bool) or not isinstance(safe, (str, int, float)):
        raise MessageError('server.video.safe', safe=repr(safe))
    fps = document.get('fps', _video.DEFAULT_FPS)
    if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= _video.MAX_FPS:
        raise MessageError('server.video.rate', most=_video.MAX_FPS, fps=repr(fps))
    score = document.get('score', True)
    if not isinstance(score, bool):
        raise MessageError('server.video.score', score=repr(score))
    annotations = document.get('annotations', False)
    if not isinstance(annotations, bool):
        raise MessageError('server.video.annotations', annotations=repr(annotations))
    options = _video.Options(
        start=_video.Moment(start),
        end=_video.Moment(end),
        camera=str(document.get('camera', 'broadcast')),
        width=size[0],
        height=size[1],
        fps=fps,
        quality=str(document.get('quality', 'standard')),
        score=score,
        annotations=annotations,
        arena=None if document.get('arena') is None else str(document['arena']),
        hour=document.get('time'),
        graphics=graphics,
        safe=safe,
    ).check()
    arguments = [
        '--start',
        f'{start:.3f}',
        '--end',
        f'{end:.3f}',
        '--camera',
        options.camera,
        '--size',
        f'{options.width}x{options.height}',
        '--fps',
        str(options.fps),
        '--quality',
        options.quality,
    ]
    if options.graphics != 1:
        arguments += ['--scale', f'{options.graphics:g}']
    if options.safe != 'auto':
        arguments += ['--safe', str(options.safe)]
    if not options.score:
        arguments.append('--no-score')
    if options.annotations:
        arguments.append('--annotations')
    if options.arena is not None:
        arguments += ['--arena', options.arena]
    if options.hour is not None:
        arguments += ['--time', repr(float(options.hour))]
    return arguments, options


def availability() -> dict[str, Any]:
    """Returns whether this machine can export videos, and what is missing when it cannot.

    The export needs a browser alone, which encodes the video itself, so ffmpeg is never missing.
    `missing` holds the English text of the missing browser, and `missing_labels` the same as
    labels of `_messages.label`, which the page shows in its own language.
    """
    try:
        labels = [] if _video.find_chrome() else [_video.chrome_missing(server=True)]
    except _video.VideoError as error:
        found = _messages.id_fields(error)
        labels = [
            _messages.label(found['error_id'], **found['error_values'])
            if found
            else {'id': None, 'text': str(error), 'values': {}}
        ]
    return {
        'available': not labels,
        'missing': [label['text'] for label in labels],
        'missing_labels': labels,
    }


def _filename(title: str, start: float, end: float) -> str:
    """Returns the name that a downloaded video suggests, from the title and the range."""
    stem = re.sub(r'[^A-Za-z0-9 _.,-]+', '', title).strip(' .') or 'match'
    first, last = (f'{int(value) // 60}m{int(value) % 60:02d}' for value in (start, end))
    return f'{stem[:60]} {first}-{last}.mp4'


class VideoJobs:
    """The exports of the page, one running at a time, each in a child process.

    The folder is touched on the first export alone, so a server that never exports leaves it as
    it was.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []
        self._process: subprocess.Popen | None = None
        self._cleaned = False

    def _folder(self) -> Path:
        folder = _home.folder('videos')
        if not self._cleaned:
            # The videos of an earlier server have no entry to download them by.
            for path in folder.iterdir():
                if path.is_file():
                    with contextlib.suppress(OSError):
                        path.unlink()
            self._cleaned = True
        return folder

    @staticmethod
    def _public(entry: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in entry.items() if not key.startswith('_')}

    def entries(self) -> list[dict[str, Any]]:
        """Returns a copy of every export, newest first."""
        with self._lock:
            return [self._public(entry) for entry in reversed(self._entries)]

    def entry(self, identifier: str) -> dict[str, Any] | None:
        """Returns a copy of one export, or `None`."""
        with self._lock:
            found = next((e for e in self._entries if e['id'] == identifier), None)
            return None if found is None else self._public(found)

    def file(self, identifier: str) -> tuple[Path, str] | None:
        """Returns the file and the suggested name of a finished export, or `None`."""
        with self._lock:
            found = next((e for e in self._entries if e['id'] == identifier), None)
            if found is None or found['state'] != 'done':
                return None
            path = Path(found['_path'])
            return (path, found['filename']) if path.is_file() else None

    def start(self, match: str, document: dict[str, Any]) -> dict[str, Any]:
        """Starts an export of a recording of the library and returns its entry.

        Raises:
            ArgumentError: If the recording is unknown or an option is invalid.
            BusyError: If another export runs.
        """
        path = _library.path_of(match)
        if path is None:
            raise MessageError('server.video.unknown_match', match=repr(match))
        arguments, options = options_from(document)
        try:
            facts = _video.recording_facts(path)
        except _video.VideoError as error:
            raise _messages.argument_error(error) from error
        start, end = _video.resolve_range(options, facts)
        if end - start > _video.DEFAULT_MAX_SECONDS:
            raise MessageError(
                'server.video.length',
                most=f'{_video.DEFAULT_MAX_SECONDS:g}',
                length=f'{end - start:.0f}',
            )
        status = availability()
        if not status['available']:
            labels = status.get('missing_labels') or []
            if labels and all(label.get('id') for label in labels):
                found = _video.missing_label(labels)
                raise MessageError(found['id'], **found['values'])
            raise ArgumentError(' '.join(status['missing']))
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise BusyError('server.video.busy')
            folder = self._folder()
            identifier = _home.new_identifier('v')
            output = folder / f'{identifier}.mp4'
            entry = {
                'id': identifier,
                'match': match,
                'title': facts.title,
                'start': start,
                'end': end,
                'state': 'running',
                'progress': 0.0,
                'frame': 0,
                'frames': _video.frame_count(start, end, options.fps),
                'error': None,
                'error_id': None,
                'error_values': None,
                'bytes': None,
                'filename': _filename(facts.title, start, end),
                'created': time.time(),
                '_path': str(output),
            }
            command = [
                *_home.python_command(),
                '-m',
                'cuju.render._export.video',
                match,
                '-o',
                str(output),
                '--format',
                'auto',
            ]
            # The child runs in the renderer's folder, so no module beside the server's working
            # folder shadows cuju, and reads its cancellation from a pipe of its own.
            process = subprocess.Popen(
                [*command, *arguments],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                cwd=_home.process_folder(),
                env=_home.process_environment(),
            )
            self._process = process
            self._entries.append(entry)
            self._prune()
        threading.Thread(target=self._watch, args=(entry, process), daemon=True).start()
        return self._public(entry)

    def _prune(self) -> None:
        """Removes the files and entries of older exports beyond `KEPT`, with the lock held."""
        finished = [e for e in self._entries if e['state'] != 'running']
        for entry in finished[: max(0, len(finished) - KEPT)]:
            with contextlib.suppress(OSError):
                Path(entry['_path']).unlink(missing_ok=True)
            self._entries.remove(entry)

    @staticmethod
    def _moved(entry: dict[str, Any], reported: Any) -> None:
        """Follows the file of an export to the suffix of the container that it was written in.

        The child process names the file it wrote, which keeps the folder and the name of the
        export and may take the suffix of another container, with the lock held.
        """
        if not isinstance(reported, str):
            return
        planned = Path(entry['_path'])
        written = Path(reported)
        if written.parent == planned.parent and written.stem == planned.stem:
            if written.suffix in _video.SUFFIXES.values():
                entry['_path'] = str(written)
                entry['filename'] = str(Path(entry['filename']).with_suffix(written.suffix))

    def _watch(self, entry: dict[str, Any], process: subprocess.Popen) -> None:
        """Follows the reports of an export's process until it ends."""
        stderr: collections.deque[str] = collections.deque(maxlen=20)
        threading.Thread(target=lambda: stderr.extend(process.stderr), daemon=True).start()
        timer = threading.Timer(_EXPORT_SECONDS, process.kill)
        timer.daemon = True
        timer.start()
        try:
            for line in process.stdout:
                try:
                    report = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(report, dict):
                    continue
                with self._lock:
                    if isinstance(report.get('progress'), (int, float)):
                        entry['progress'] = float(report['progress'])
                    if isinstance(report.get('frame'), int):
                        entry['frame'] = report['frame']
                    if isinstance(report.get('error'), str):
                        entry.update(_messages.report_fields(report))
                    if report.get('stage') == 'encoding':
                        entry['progress'] = 1.0
                    if isinstance(report.get('bytes'), int):
                        entry['bytes'] = report['bytes']
                    self._moved(entry, report.get('path'))
            code = process.wait()
        finally:
            timer.cancel()
        with self._lock:
            if entry['state'] == 'running':
                if code == 0 and Path(entry['_path']).is_file():
                    entry['state'] = 'done'
                elif entry.get('_cancelled'):
                    entry['state'] = 'cancelled'
                    entry.update(_messages.entry_fields(None))
                else:
                    entry['state'] = 'failed'
                    if not entry['error']:
                        tail = ''.join(stderr).strip()[-400:]
                        entry.update(_messages.exit_fields('server.video.exit', code, tail))
            if self._process is process:
                self._process = None

    def cancel(self, identifier: str) -> bool:
        """Cancels a running export, or removes a finished one and its file.

        A running export reads the cancellation, closes Chrome and removes its partial file, and
        one that does not end within half a minute is ended.
        """
        with self._lock:
            entry = next((e for e in self._entries if e['id'] == identifier), None)
            if entry is None:
                return False
            if entry['state'] != 'running':
                with contextlib.suppress(OSError):
                    Path(entry['_path']).unlink(missing_ok=True)
                self._entries.remove(entry)
                return True
            entry['_cancelled'] = True
            process = self._process
        if process is not None:
            with contextlib.suppress(OSError, ValueError):
                process.stdin.write('cancel\n')
                process.stdin.flush()

            def end() -> None:
                try:
                    process.wait(30)
                except subprocess.TimeoutExpired:
                    process.kill()

            threading.Thread(target=end, daemon=True).start()
        return True
