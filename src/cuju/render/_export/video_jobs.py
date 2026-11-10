# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The video exports that the page asks the server for, one at a time, each in a child process.

Each export runs `python -m cuju.render._export.video` on a recording of the library and writes into
the folder `videos` of the renderer, where the page downloads the file. The folder holds the videos
of the running server alone, the latest few, and the server empties it of older files before its
first export.
"""

from __future__ import annotations

import collections
import contextlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from cuju.errors import ArgumentError

from .._store import home as _home
from .._store import library as _library
from . import video as _video

# The videos that the folder keeps, the latest ones, beside the export that runs.
KEPT = 3
# An export ends after this many seconds, longer than the longest range takes on a slow machine.
_EXPORT_SECONDS = 3 * 60 * 60
# The sizes, frame rates and qualities that the page offers.
SIZES = ((854, 480), (1280, 720), (1920, 1080))
RATES = (24, 25, 30, 50, 60)


class BusyError(Exception):
    """Raised when an export is asked for while another one runs."""


def _seconds(value: Any, name: str) -> float:
    """Returns a number of seconds from the page, or raises `ArgumentError`."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < 1e6:
        raise ArgumentError(f'expected {name} as seconds from 0, found {value!r}')
    return float(value)


def options_from(document: dict[str, Any]) -> tuple[list[str], _video.Options]:
    """Returns the command line arguments of an export that the page asks for, and its options.

    The page names the start and end in seconds, the camera, the size and frame rate from those it
    offers, the quality, whether the scoreboard shows and the arena and hour of its field.

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
        'arena',
        'time',
    }
    unknown = set(document) - known
    if unknown:
        raise ArgumentError(
            f'expected the fields {", ".join(sorted(known))}, found {sorted(unknown)}'
        )
    start = _seconds(document.get('start', 0), 'start')
    end = _seconds(document.get('end'), 'end')
    if end <= start:
        raise ArgumentError(f'expected an end after the start, found {start:g} to {end:g}')
    size = (document.get('width', 1280), document.get('height', 720))
    if size not in SIZES:
        raise ArgumentError(f'expected a size of {", ".join(f"{w}x{h}" for w, h in SIZES)}')
    fps = document.get('fps', _video.DEFAULT_FPS)
    if fps not in RATES or isinstance(fps, bool):
        raise ArgumentError(f'expected a frame rate of {", ".join(map(str, RATES))}, found {fps!r}')
    score = document.get('score', True)
    if not isinstance(score, bool):
        raise ArgumentError(f'expected score as true or false, found {score!r}')
    options = _video.Options(
        start=_video.Moment(start),
        end=_video.Moment(end),
        camera=str(document.get('camera', 'broadcast')),
        width=size[0],
        height=size[1],
        fps=fps,
        quality=str(document.get('quality', 'standard')),
        score=score,
        arena=None if document.get('arena') is None else str(document['arena']),
        hour=document.get('time'),
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
    if not options.score:
        arguments.append('--no-score')
    if options.arena is not None:
        arguments += ['--arena', options.arena]
    if options.hour is not None:
        arguments += ['--time', repr(float(options.hour))]
    return arguments, options


def availability() -> dict[str, Any]:
    """Returns whether this machine can export videos, and what is missing when it cannot."""
    try:
        _, _, missing = _video.tools(_video.Options())
    except _video.VideoError as error:
        missing = [str(error)]
    return {'available': not missing, 'missing': missing}


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
            raise ArgumentError(f'expected a recording of the library, found {match!r}')
        arguments, options = options_from(document)
        try:
            facts = _video.recording_facts(path)
        except _video.VideoError as error:
            raise ArgumentError(str(error)) from error
        start, end = _video.resolve_range(options, facts)
        if end - start > _video.DEFAULT_MAX_SECONDS:
            raise ArgumentError(
                f'expected at most {_video.DEFAULT_MAX_SECONDS:g} seconds of video, found '
                f'{end - start:.0f} seconds'
            )
        status = availability()
        if not status['available']:
            raise ArgumentError(' '.join(status['missing']))
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise BusyError('an export already runs, wait for it or cancel it')
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
                'bytes': None,
                'filename': _filename(facts.title, start, end),
                'created': time.time(),
                '_path': str(output),
            }
            command = [sys.executable, '-m', 'cuju.render._export.video', match, '-o', str(output)]
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
                cwd=_home.home(),
                env=os.environ.copy(),
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
                        entry['error'] = report['error']
                    if report.get('stage') == 'encoding':
                        entry['progress'] = 1.0
                    if isinstance(report.get('bytes'), int):
                        entry['bytes'] = report['bytes']
            code = process.wait()
        finally:
            timer.cancel()
        with self._lock:
            if entry['state'] == 'running':
                if code == 0 and Path(entry['_path']).is_file():
                    entry['state'] = 'done'
                elif entry.get('_cancelled'):
                    entry['state'], entry['error'] = 'cancelled', None
                else:
                    entry['state'] = 'failed'
                    if not entry['error']:
                        tail = ''.join(stderr).strip()[-400:]
                        entry['error'] = f'the export ended with exit code {code}' + (
                            f', {tail}' if tail else ''
                        )
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
