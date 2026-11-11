# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""Exports a recording as a video file, drawn by the renderer's own page frame by frame.

The export serves the page and the recording from a loopback server of its own and opens
`web/export.html` in a locally installed Chrome, Edge or Chromium without a window. That page runs
the browser's own export of `web/js/export/video-browser.js`, which steps the page's clocks by one
frame at a time through the capture hook of `web/js/capture.js` and encodes each frame with the
browser's video encoder into MP4 with H.264 or WebM with VP9 or VP8. The file comes back over the
debugging protocol in pieces, so the export needs the browser alone. Where the browser encodes no
H.264 and an MP4 is asked for, an installed ffmpeg encodes it instead from a picture of each frame,
as the export did before the browser could encode. The browser is found on the path or given by
option, and the export uses only Python's standard library beside it.

`cuju render video` runs an export from the command line, and the server of the page runs the same
export in a child process through `python -m cuju.render._export.video`, which then reports its
progress as JSON lines.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import dataclasses
import json
import math
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cuju.errors import ArgumentError, Error

from . import sizes as _sizes

# The cameras that follow the match by themselves, as the page names them.
CAMERAS = ('broadcast', 'tactical', 'goal', 'ball', 'owner')
# The arenas of the page, as `web/js/world/arenas.js` lists them.
ARENAS = ('stadium', 'beach', 'rooftop', 'space', 'neon')
# The named hours of the page, as `PRESET_HOURS` of `web/js/world/sky.js`.
HOURS = {'dawn': 6.5, 'day': 15.0, 'dusk': 19.0, 'night': 22.0}
# Each quality names the constant rate factor of x264, its preset and the page's drawing quality.
QUALITIES = {
    'draft': (28, 'veryfast', 'medium'),
    'standard': (20, 'medium', 'high'),
    'high': (15, 'slow', 'high'),
}
DEFAULT_SIZE = (1280, 720)
DEFAULT_FPS = 30
# The frame rates and the limits of an export. The sizes follow `_sizes`, with even sides.
MAX_FPS = 60
DEFAULT_MAX_SECONDS = 600.0
LIMIT_SECONDS = 3600.0
DEFAULT_MAX_MEGABYTES = 2048
LIMIT_MEGABYTES = 16384
# The containers of a video, and auto for the best that the browser encodes, MP4 before WebM.
FORMATS = ('auto', 'mp4', 'webm')
SUFFIXES = {'mp4': '.mp4', 'webm': '.webm'}
# The finished file comes back from the browser in pieces of this many bytes.
_PIECE = 4 << 20
# A goal's range starts this long before the goal and ends this long after it.
GOAL_BEFORE, GOAL_AFTER = 8.0, 4.0
# The page plays this long before the first frame, so the camera and graphics have settled.
WARMUP = 1.0
# The identifier under which the export's server offers a recording file outside the library.
_FILE_IDENTIFIER = 'video-source'

# How to install each program. The command names a program with an option or a variable, and a
# server with the variable alone, set before it starts.
_INSTALL_CHROME = (
    'Install Google Chrome or Chromium, from https://www.google.com/chrome/ or with the package '
    'manager, such as apt install chromium, or name the program with {named}.'
)
_INSTALL_FFMPEG = (
    'Install ffmpeg, from https://ffmpeg.org/download.html or with the package manager, such as '
    'apt install ffmpeg, brew install ffmpeg or winget install ffmpeg, or name the program with '
    '{named}.'
)


class VideoError(Error, RuntimeError):
    """Raised when an export cannot run or stops, with what to do about it."""


class CancelledError(VideoError):
    """Raised when an export is cancelled, by Ctrl+C or by the page."""


@dataclasses.dataclass(frozen=True)
class Moment:
    """A moment of a recording, in seconds from its first frame or from one of its goals.

    Attributes:
        seconds: The seconds from the first frame, or from the goal when `goal` is set.
        goal: The number of the goal, counted from 1, or `None`.
    """

    seconds: float
    goal: int | None = None


@dataclasses.dataclass
class Options:
    """The settings of one export, each checked by `check`."""

    start: Moment | None = None
    end: Moment | None = None
    goal: int | None = None
    camera: str = 'broadcast'
    width: int = DEFAULT_SIZE[0]
    height: int = DEFAULT_SIZE[1]
    fps: int = DEFAULT_FPS
    quality: str = 'standard'
    score: bool = True
    annotations: bool = False
    arena: str | None = None
    hour: float | None = None
    broadcast: bool = False
    graphics: float = 1.0
    safe: str | float = 'auto'
    max_seconds: float = DEFAULT_MAX_SECONDS
    max_megabytes: int = DEFAULT_MAX_MEGABYTES
    chrome: str | None = None
    ffmpeg: str | None = None
    software: bool = False
    sandbox: bool = True
    # The container, mp4, webm or auto, or None for the one that the output's suffix names.
    format: str | None = None

    def check(self) -> Options:
        """Returns the options after checking each, or raises `ArgumentError`."""
        if self.format is not None and self.format not in FORMATS:
            raise ArgumentError(f'expected a format of {", ".join(FORMATS)}, found {self.format!r}')
        if self.camera not in CAMERAS:
            raise ArgumentError(f'expected a camera of {", ".join(CAMERAS)}, found {self.camera!r}')
        check_size(self.width, self.height)
        fps = self.fps
        if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= MAX_FPS:
            raise ArgumentError(f'expected a frame rate from 1 to {MAX_FPS}, found {self.fps!r}')
        if not isinstance(self.annotations, bool):
            raise ArgumentError(
                f'expected annotations as true or false, found {self.annotations!r}'
            )
        if self.quality not in QUALITIES:
            raise ArgumentError(
                f'expected a quality of {", ".join(QUALITIES)}, found {self.quality!r}'
            )
        if self.arena is not None and self.arena not in ARENAS:
            raise ArgumentError(f'expected an arena of {", ".join(ARENAS)}, found {self.arena!r}')
        if self.hour is not None and not (_number(self.hour) and 0 <= self.hour <= 24):
            raise ArgumentError(f'expected an hour from 0 to 24, found {self.hour!r}')
        if not _number(self.graphics):
            raise ArgumentError(f'expected a scale of the graphics, found {self.graphics!r}')
        self.graphics = _sizes.parse_graphics(self.graphics)
        self.safe = _sizes.parse_safe(self.safe)
        if self.goal is not None and (
            isinstance(self.goal, bool) or not isinstance(self.goal, int) or self.goal < 1
        ):
            raise ArgumentError(f'expected a goal number from 1, found {self.goal!r}')
        if not (_number(self.max_seconds) and 0 < self.max_seconds <= LIMIT_SECONDS):
            raise ArgumentError(
                f'expected a maximum length above 0 and up to {LIMIT_SECONDS:.0f} seconds, '
                f'found {self.max_seconds!r}'
            )
        if (
            isinstance(self.max_megabytes, bool)
            or not isinstance(self.max_megabytes, int)
            or not 1 <= self.max_megabytes <= LIMIT_MEGABYTES
        ):
            raise ArgumentError(
                f'expected a maximum size from 1 to {LIMIT_MEGABYTES} MB, '
                f'found {self.max_megabytes!r}'
            )
        return self


def _number(value: Any) -> bool:
    """Returns whether `value` is a finite number, which excludes true and false."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_size(width: Any, height: Any) -> None:
    """Checks a picture size as `_sizes.check_size` does, with even sides for the encoder."""
    _sizes.check_size(width, height, even=True)


_SECONDS = r'\d+(?:\.\d+)?'
_MOMENT = re.compile(
    rf'(?:(?P<minutes>\d+):(?P<clock>\d{{1,2}}(?:\.\d+)?)|(?P<seconds>{_SECONDS}))'
)
_GOAL = re.compile(rf'goal:?(?P<goal>\d+)(?:(?P<sign>[+-])(?P<offset>{_SECONDS}))?')


def parse_moment(text: str) -> Moment:
    """Returns the moment that a range option names.

    A moment is a number of seconds such as `75` or `75.5`, minutes and seconds such as `1:15`,
    or a goal such as `goal:2`, optionally with seconds before or after it, as in `goal:2-8` or
    `goal:2+4`.

    Raises:
        ArgumentError: If the text names no moment.
    """
    value = str(text).strip().lower()
    goal = _GOAL.fullmatch(value)
    if goal:
        number = int(goal['goal'])
        if number < 1:
            raise ArgumentError(f'expected goals counted from 1, found {text!r}')
        offset = float(goal['offset'] or 0)
        return Moment(-offset if goal['sign'] == '-' else offset, number)
    moment = _MOMENT.fullmatch(value)
    if not moment:
        raise ArgumentError(
            f'expected seconds such as 75, minutes and seconds such as 1:15, or a goal such as '
            f'goal:2 or goal:2-8, found {text!r}'
        )
    if moment['seconds'] is not None:
        return Moment(float(moment['seconds']))
    clock = float(moment['clock'])
    if clock >= 60:
        raise ArgumentError(f'expected seconds below 60 after the colon, found {text!r}')
    return Moment(int(moment['minutes']) * 60 + clock)


def parse_size(text: str) -> tuple[int, int]:
    """Returns the width and height of a size such as `1280x720`, `1080p` or `vertical`.

    The sizes are those of `_sizes`, shared with the feed and the page, with even sides.
    """
    return _sizes.parse_size(text, even=True)


def parse_hour(text: str) -> float:
    """Returns the hour of a time of day, a name such as `dusk` or an hour such as `21.5`."""
    value = str(text).strip().lower()
    if value in HOURS:
        return HOURS[value]
    try:
        hour = float(value)
    except ValueError:
        hour = math.nan
    if not 0 <= hour <= 24:
        raise ArgumentError(f'expected {", ".join(HOURS)} or an hour from 0 to 24, found {text!r}')
    return hour


@dataclasses.dataclass(frozen=True)
class Facts:
    """What an export needs to know of a recording.

    Attributes:
        title: The title of the recording.
        frames: The number of frames.
        steps_per_second: The frames of one second of play.
        goals: The second of each goal, the first frame that shows the new score.
    """

    title: str
    frames: int
    steps_per_second: float
    goals: tuple[float, ...]

    @property
    def duration(self) -> float:
        """The seconds from the first frame to the last."""
        return max(0, self.frames - 1) / self.steps_per_second


def recording_facts(path: Path) -> Facts:
    """Reads the title, the length and the goals of a recording file.

    A goal is a frame whose score is higher on either side than the frame before, as the page
    finds them.

    Raises:
        VideoError: If the file is not a readable recording.
    """
    from .._format import recording as _recording

    try:
        header = _recording.read_header(path)
        sps = float(header.get('steps_per_second') or 10)
        goals, previous, count = [], None, 0
        for frame in _recording.frames(path):
            score = struct.unpack_from('<2i', frame, 8)
            if previous is not None and (score[0] > previous[0] or score[1] > previous[1]):
                goals.append(count / sps)
            previous = score
            count += 1
    except (OSError, EOFError, ValueError, KeyError, struct.error, Error) as error:
        raise VideoError(f'{path} is not a readable recording, {error}') from error
    if count == 0:
        raise VideoError(f'{path} holds no frames')
    return Facts(str(header.get('title') or path.stem), count, sps, tuple(goals))


def resolve_range(options: Options, facts: Facts) -> tuple[float, float]:
    """Returns the start and end of the export in seconds from the first frame.

    The range runs by default over the whole recording, or from `GOAL_BEFORE` seconds before to
    `GOAL_AFTER` seconds after the goal of `options.goal`. A start or end given as a moment takes
    the place of either, and the range is then kept within the recording.

    Raises:
        ArgumentError: If a goal is missing from the recording or the range holds no frames.
    """

    def goal_time(number: int) -> float:
        if number > len(facts.goals):
            count = len(facts.goals)
            raise ArgumentError(
                f'expected a goal from 1 to {count}, found goal {number}'
                if count
                else f'expected a goal, found none in the recording, asked for goal {number}'
            )
        return facts.goals[number - 1]

    def at(moment: Moment) -> float:
        return moment.seconds if moment.goal is None else goal_time(moment.goal) + moment.seconds

    start, end = 0.0, facts.duration
    if options.goal is not None:
        moment = goal_time(options.goal)
        start, end = moment - GOAL_BEFORE, moment + GOAL_AFTER
    if options.start is not None:
        start = at(options.start)
    if options.end is not None:
        end = at(options.end)
    start, end = max(0.0, start), min(facts.duration, end)
    if end - start < 1 / facts.steps_per_second:
        raise ArgumentError(
            f'expected a range that holds frames, the recording runs from 0 to '
            f'{facts.duration:.1f} seconds, found {start:.1f} to {end:.1f}'
        )
    return start, end


def frame_count(start: float, end: float, fps: int) -> int:
    """Returns the number of frames of a range, one per frame interval and at least one."""
    return max(1, round((end - start) * fps))


def find_program(names: tuple[str, ...], explicit: str | None, variable: str) -> str | None:
    """Returns the path of a program named by option, by variable or on the path, or `None`."""
    for given in (explicit, os.environ.get(variable)):
        if given:
            found = shutil.which(given) or (given if Path(given).is_file() else None)
            if found is None:
                raise VideoError(f'expected a program at {given}, found none')
            return found
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _chrome_locations() -> list[str]:
    """Returns the usual places of Chrome, Chromium and Edge outside the path."""
    if sys.platform == 'win32':
        roots = [
            os.environ.get(key) for key in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')
        ]
        tails = [
            r'Google\Chrome\Application\chrome.exe',
            r'Chromium\Application\chrome.exe',
            r'Microsoft\Edge\Application\msedge.exe',
        ]
        return [str(Path(root) / tail) for root in roots if root for tail in tails]
    if sys.platform == 'darwin':
        return [
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
            '/Applications/Chromium.app/Contents/MacOS/Chromium',
            '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
        ]
    return ['/opt/google/chrome/chrome', '/snap/bin/chromium']


def find_chrome(explicit: str | None = None) -> str | None:
    """Returns the path of Chrome or Chromium, or `None` when this machine has neither."""
    names = ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome')
    found = find_program(names, explicit, 'CUJU_CHROME')
    if found:
        return found
    return next((path for path in _chrome_locations() if Path(path).is_file()), None)


def find_ffmpeg(explicit: str | None = None) -> str | None:
    """Returns the path of ffmpeg, or `None` when it is neither on the path nor named."""
    return find_program(('ffmpeg',), explicit, 'CUJU_FFMPEG')


def tools(options: Options, server: bool = False) -> tuple[str | None, str | None, list[str]]:
    """Returns the paths of Chrome and ffmpeg and a message for each one missing.

    Args:
        options: The options, which may name either program.
        server: Whether the messages are for the page's server, which takes the variables alone.
    """

    def named(option: str, variable: str) -> str:
        if server:
            return f'${variable} in the environment of cuju render serve'
        return f'{option} or ${variable}'

    missing = []
    chrome = find_chrome(options.chrome)
    if chrome is None:
        missing.append(chrome_missing(server))
    ffmpeg = find_ffmpeg(options.ffmpeg)
    if ffmpeg is None:
        hint = _INSTALL_FFMPEG.format(named=named('--ffmpeg', 'CUJU_FFMPEG'))
        missing.append(f'Video export needs ffmpeg, found none. {hint}')
    return chrome, ffmpeg, missing


def chrome_missing(server: bool = False) -> str:
    """Returns the message of a missing Chrome, for the command or for the page's server."""
    if server:
        named = '$CUJU_CHROME in the environment of cuju render serve'
    else:
        named = '--chrome or $CUJU_CHROME'
    hint = _INSTALL_CHROME.format(named=named)
    return f'Video export needs Chrome or Chromium, found neither. {hint}'


def requested_format(output: Path, options: Options) -> str | None:
    """Returns the container that an export must write, or `None` for the browser's best.

    The format `auto` leaves the choice to the browser, and the output then takes the suffix of the
    container chosen. A format of mp4 or webm, or without a format the suffix of the output, asks
    for that container alone.

    Raises:
        ArgumentError: If the output ends in neither .mp4 nor .webm, or in the other one's suffix.
    """
    suffix = output.suffix.lower()
    if suffix not in SUFFIXES.values():
        raise ArgumentError(f'expected an output file ending in .mp4 or .webm, found {output.name}')
    if options.format == 'auto':
        return None
    if options.format in SUFFIXES:
        if SUFFIXES[options.format] != suffix:
            raise ArgumentError(
                f'expected an output file ending in {SUFFIXES[options.format]} for the format '
                f'{options.format}, found {output.name}'
            )
        return options.format
    return 'mp4' if suffix == '.mp4' else 'webm'


def choose_encoding(
    wanted: str | None, support: dict[str, Any], ffmpeg: str | None, browser: str = 'the browser'
) -> tuple[str, str]:
    """Returns how an export encodes, `browser` or `ffmpeg`, and the container it writes.

    The browser encodes whatever it can, MP4 first. ffmpeg encodes an MP4 only where the browser
    encodes no H.264, or cannot read back the page's graphics, and only when it is installed.

    Args:
        wanted: The container asked for, or `None` for the best one.
        support: What the browser encodes, the codec of `mp4` and of `webm` or `None` for each, and
            `pictures`, whether it reads back the page's graphics.
        ffmpeg: The path of ffmpeg, or `None`.
        browser: The browser's name for the messages.

    Raises:
        VideoError: If neither the browser nor ffmpeg writes the container asked for.
    """
    usable = bool(support.get('pictures'))
    mp4 = usable and bool(support.get('mp4'))
    webm = usable and bool(support.get('webm'))
    if wanted in (None, 'mp4'):
        if mp4:
            return 'browser', 'mp4'
        if ffmpeg:
            return 'ffmpeg', 'mp4'
    if wanted in (None, 'webm') and webm:
        return 'browser', 'webm'
    if wanted == 'mp4':
        alternative = ' or ask for WebM with --format webm,' if webm else ''
        raise VideoError(
            f'expected a browser that encodes H.264 for an MP4, found none in {browser}, so use '
            f'Google Chrome or Edge,{alternative} or install ffmpeg, which then encodes the MP4'
        )
    raise VideoError(
        f'expected a browser that encodes {"VP9 or VP8 for a WebM" if wanted else "video"}, found '
        f'none in {browser}, so update it or use Google Chrome or Edge'
        + ('' if wanted else ', or install ffmpeg, which then encodes an MP4')
    )


def view(width: int, height: int, graphics: float = 1.0) -> tuple[int, int, float]:
    """Returns the page's width and height in CSS pixels and the scale that gives the picture.

    The page lays out with its shorter side at 720 CSS pixels, so its graphics keep their
    proportion at every size and shape, and a smaller picture lays out at its own size, as
    `_sizes.layout` gives it with the scale of the graphics.
    """
    return _sizes.layout(width, height, graphics)


def chrome_command(
    chrome: str, profile: str, options: Options, extra: tuple[str, ...] = ()
) -> list[str]:
    """Returns the command line of a headless Chrome that serves its debugging protocol.

    Chrome picks a free port for the protocol and writes it into the profile. A proxy that answers
    nothing keeps every address other than the loopback server out of reach.
    """
    css_width, css_height, _ = view(options.width, options.height, options.graphics)
    flags = [
        chrome,
        '--headless=new',
        '--mute-audio',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-background-networking',
        '--disable-component-update',
        '--disable-sync',
        '--disable-default-apps',
        '--disable-extensions',
        '--disable-background-timer-throttling',
        '--disable-renderer-backgrounding',
        '--disable-backgrounding-occluded-windows',
        '--autoplay-policy=user-gesture-required',
        '--proxy-server=http://127.0.0.1:9',
        '--proxy-bypass-list=127.0.0.1',
        '--remote-debugging-port=0',
        f'--user-data-dir={profile}',
        f'--window-size={css_width},{css_height}',
        '--hide-scrollbars',
        '--ignore-gpu-blocklist',
        '--enable-unsafe-swiftshader',
    ]
    if options.software:
        flags.append('--use-angle=swiftshader')
    # Chrome refuses its sandbox to the root user, as in many containers.
    if not options.sandbox or (hasattr(os, 'geteuid') and os.geteuid() == 0):
        flags.append('--no-sandbox')
    return [*flags, *extra, 'about:blank']


def ffmpeg_command(ffmpeg: str, output: Path, options: Options) -> list[str]:
    """Returns the command line of ffmpeg that encodes the PNG pictures of its input into MP4."""
    crf, preset, _ = QUALITIES[options.quality]
    return [
        ffmpeg,
        '-hide_banner',
        '-loglevel',
        'error',
        '-y',
        '-f',
        'image2pipe',
        '-framerate',
        str(options.fps),
        '-c:v',
        'png',
        '-i',
        '-',
        '-vf',
        f'scale={options.width}:{options.height}:flags=lanczos,format=yuv420p',
        '-c:v',
        'libx264',
        '-preset',
        preset,
        '-crf',
        str(crf),
        '-r',
        str(options.fps),
        '-an',
        '-movflags',
        '+faststart',
        '-fs',
        str(options.max_megabytes * 1024 * 1024),
        '-f',
        'mp4',
        str(output),
    ]


def preload_script(options: Options) -> str:
    """Returns the script that sets the page's settings before the page itself runs.

    Sound stays muted, the pointer stays free and controllers stay unseen. The page shows the
    picture alone in its broadcast mode. Without `broadcast` it keeps the team sheets, the
    presentation of restarts, celebrations, replays and the show after the match off, which hold
    or stop play, so the video follows the match clock. The labels and the box of a recording's
    annotations show only with `annotations`, and then with their numbers, actions and text.
    """
    _, _, drawing = QUALITIES[options.quality]
    field: dict[str, Any] = {}
    if options.arena is not None:
        field['arena'] = options.arena
    if options.hour is not None:
        field['time'] = options.hour
    settings: dict[str, Any] = {
        'muted': True,
        'volume': 0,
        'music': False,
        'quality': drawing,
        'theme': 'dark',
        'tvMode': True,
        'idleReturn': False,
        'pointerLock': False,
        'camera': options.camera if options.camera in CAMERAS[:3] else 'broadcast',
        'lineups': options.broadcast,
        'celebrations': options.broadcast,
        'replays': options.broadcast,
        'decisionReplays': options.broadcast,
        'transitions': options.broadcast,
        'podium': False,
        'motion': 'full',
        'annotations': dict.fromkeys(('players', 'actions', 'text'), options.annotations),
    }
    if field:
        settings['field'] = field
    lines = [
        f'localStorage.setItem({json.dumps("cuju." + key)}, {json.dumps(json.dumps(value))});'
        for key, value in settings.items()
    ]
    lines += [
        "Object.defineProperty(navigator, 'getGamepads', { configurable: true, value: () => [] });",
        'Element.prototype.requestPointerLock = function () {',
        "    return Promise.reject(new Error('The pointer stays free while exporting.'));",
        '};',
    ]
    return '\n'.join(lines)


# The page is ready once the recording is open, its players drawn and the shipped assets loaded.
_READY = """(() => {
    const fatal = document.getElementById('fatal');
    if (fatal && !fatal.hidden && fatal.textContent) return { fatal: fatal.textContent };
    const app = window.cuju;
    const ready = !!(window.cujuCapture && app && app.source && app.source.id === %s
        && app.timeline && app.players && app.assets && (app.assets.manifest || app.assets.error)
        && document.getElementById('loading').hidden);
    return { ready };
})()"""

# Holds the page at the first frame of the warm-up with the camera of the export in place.
_HOLD = """(() => {
    const app = cuju;
    if (app.director.lineup && (%(broadcast)s === false || %(at)s > 0)) {
        app.director.closeLineups(false);
    }
    app.timeline.pause();
    app.setCamera(%(camera)s);
    const tl = app.timeline;
    tl.seek(tl.first + %(at)s * tl.sps);
    app.afterSeek();
    if (app.cameras.jump) app.cameras.jump();
    if (%(score)s === false) {
        const style = document.createElement('style');
        style.textContent = '#scoreboard { display: none !important; }';
        document.head.append(style);
    }
    return true;
})()"""

# Seeks the held frame again, since the page may have moved while it settled, freezes the page's
# clocks and plays the match from there, or leaves the team sheets to start play when they show.
_PLAY = """(() => {
    const app = cuju;
    const tl = app.timeline;
    tl.pause();
    tl.seek(tl.first + %(at)s * tl.sps);
    app.afterSeek();
    if (app.cameras.jump) app.cameras.jump();
    cujuCapture.start();
    // The first stepped frame measures its time from the frozen clock, never from the last frame
    // that Chrome drew before the page settled.
    app.lastTime = performance.now();
    if (!app.director.lineup) tl.play(1);
    return (tl.t - tl.first) / tl.sps;
})()"""

# Moves the page by one frame and returns where the match then stands, in seconds.
_STEP = '(cujuCapture.step(%s), (cuju.timeline.t - cuju.timeline.first) / cuju.timeline.sps)'


class _CDP:
    """A connection to one page of Chrome over its debugging protocol, on the standard library."""

    def __init__(self, url: str, timeout: float = 120) -> None:
        address = urllib.parse.urlsplit(url)
        self.socket = socket.create_connection((address.hostname, address.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.socket.sendall(
            (
                f'GET {address.path} HTTP/1.1\r\nHost: {address.netloc}\r\n'
                f'Upgrade: websocket\r\nConnection: Upgrade\r\n'
                f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n'
            ).encode()
        )
        header = b''
        while not header.endswith(b'\r\n\r\n'):
            chunk = self.socket.recv(1)
            if not chunk:
                raise VideoError('Chrome closed the debugging connection at its start')
            header += chunk
        if b' 101 ' not in header.split(b'\r\n')[0]:
            raise VideoError(f'Chrome refused the debugging connection, {header[:80]!r}')
        self.sequence = 0
        self.errors: list[str] = []

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self.socket.close()

    def _read(self, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = self.socket.recv(min(size - len(data), 1 << 20))
            if not chunk:
                raise VideoError('Chrome closed the debugging connection')
            data += chunk
        return bytes(data)

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.sequence += 1
        data = json.dumps({'id': self.sequence, 'method': method, 'params': params or {}}).encode()
        mask = os.urandom(4)
        size = len(data)
        if size < 126:
            header = bytes([129, 128 | size])
        elif size < 65536:
            header = bytes([129, 254]) + struct.pack('!H', size)
        else:
            header = bytes([129, 255]) + struct.pack('!Q', size)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
        self.socket.sendall(header + mask + masked)
        while True:
            first, second = self._read(2)
            size = second & 127
            if size == 126:
                size = struct.unpack('!H', self._read(2))[0]
            elif size == 127:
                size = struct.unpack('!Q', self._read(8))[0]
            payload = self._read(size)
            if first & 15 == 8:
                raise VideoError('Chrome closed the debugging connection')
            if first & 15 != 1:
                continue
            message = json.loads(payload)
            if message.get('method') == 'Runtime.exceptionThrown':
                details = message['params']['exceptionDetails']
                self.errors.append(str(details.get('exception', {}).get('description', details)))
            if message.get('id') == self.sequence:
                if 'error' in message:
                    raise VideoError(f'Chrome could not run {method}, {message["error"]}')
                return message.get('result', {})

    def evaluate(self, expression: str) -> Any:
        result = self.call(
            'Runtime.evaluate',
            {'expression': expression, 'returnByValue': True, 'awaitPromise': True},
        )
        if 'exceptionDetails' in result:
            details = result['exceptionDetails']
            text = details.get('exception', {}).get('description') or details.get('text')
            raise VideoError(f'the page failed, {text}')
        return result.get('result', {}).get('value')


class _NoRequests:
    """Stands in for the queue of requested matches, which an export leaves alone."""

    def entries(self) -> list[dict[str, Any]]:
        return []

    def add(self, *arguments: Any) -> dict[str, Any]:
        raise ArgumentError('expected no requested matches while exporting a video')

    def cancel(self, identifier: str) -> bool:
        return False


@contextlib.contextmanager
def _page_server(path: Path, identifier: str) -> Any:
    """Serves the page and its API on a free loopback port, with the recording at `identifier`."""
    from .._http import server as _server

    base = _server.make_handler(_NoRequests())  # type: ignore[arg-type]

    class Handler(base):  # type: ignore[misc, valid-type]
        def _recording(self, name: str) -> None:
            if name != identifier:
                super()._recording(name)
                return
            size = path.stat().st_size
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(size))
            self.end_headers()
            with path.open('rb') as stream:
                while chunk := stream.read(1 << 20):
                    self.wfile.write(chunk)

    # The server of the renderer, whose queue of connections holds the bursts of the page.
    from .._http.launch import LoopbackServer

    server = LoopbackServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_address[1]}/'
    finally:
        server.shutdown()
        server.server_close()


def _spawn(command: list[str], **options: Any) -> subprocess.Popen:
    """Starts a child process in a group of its own, so Ctrl+C reaches the export alone."""
    if sys.platform == 'win32':
        options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options['start_new_session'] = True
    return subprocess.Popen(command, **options)


def _stop(process: subprocess.Popen | None, grace: float = 10) -> None:
    """Ends a child process, waiting `grace` seconds before it is killed."""
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(grace)
    except subprocess.TimeoutExpired:
        process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(grace)


def _remove(path: Path) -> None:
    """Removes a file or folder, waiting a moment for a program that still holds it."""
    for _ in range(20):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
            return
        except OSError:
            time.sleep(0.25)


class _Chrome:
    """A headless Chrome with one page, started in a temporary profile that is removed after."""

    def __init__(self, chrome: str, options: Options) -> None:
        self.profile = Path(tempfile.mkdtemp(prefix='cuju-video-'))
        self.process: subprocess.Popen | None = None
        self.client: _CDP | None = None
        self.command = chrome_command(chrome, str(self.profile), options)

    def start(self, timeout: float = 60) -> _CDP:
        self.process = _spawn(
            self.command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        marker = self.profile / 'DevToolsActivePort'
        deadline = time.monotonic() + timeout
        port = None
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise VideoError(
                    f'Chrome stopped at its start with exit code {self.process.returncode}. '
                    'Chrome in some containers needs --no-sandbox.'
                )
            with contextlib.suppress(OSError, ValueError, IndexError):
                port = int(marker.read_text(encoding='utf-8').split()[0])
                break
            time.sleep(0.1)
        if port is None:
            raise VideoError(f'Chrome did not open its debugging port within {timeout:.0f} s')
        targets: list[dict[str, Any]] = []
        while time.monotonic() < deadline and not targets:
            with contextlib.suppress(OSError, ValueError):
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list', timeout=5) as r:
                    targets = [t for t in json.load(r) if t.get('type') == 'page']
            if not targets:
                time.sleep(0.1)
        if not targets:
            raise VideoError('Chrome opened no page')
        self.client = _CDP(targets[0]['webSocketDebuggerUrl'])
        return self.client

    def stop(self) -> None:
        if self.client is not None:
            # A connection cut off in the middle of a message closes Chrome by its process alone.
            with contextlib.suppress(Exception):
                self.client.socket.settimeout(3)
                self.client.call('Browser.close')
            self.client.close()
        _stop(self.process, 5)
        _remove(self.profile)


Report = Callable[[dict[str, Any]], None]


def _wait_ready(client: _CDP, identifier: str, timeout: float = 120) -> None:
    """Waits until the page has opened the recording and loaded what it draws."""
    expression = _READY % json.dumps(identifier)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.evaluate(expression) or {}
        if state.get('fatal'):
            raise VideoError(f'the page cannot draw in this Chrome, {state["fatal"]}')
        if state.get('ready'):
            return
        time.sleep(0.2)
    errors = '; '.join(client.errors[:3])
    raise VideoError(
        f'the page did not open the recording within {timeout:.0f} s'
        + (f', {errors}' if errors else '')
    )


def _wait_host(client: _CDP, options: Options, timeout: float = 120) -> dict[str, Any]:
    """Waits until the page of the export has loaded and returns what the browser encodes."""
    expression = (
        'window.cujuVideoExport ? cujuVideoExport.support('
        f'{options.width}, {options.height}, {options.fps}, {json.dumps(options.quality)}) : null'
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        support = client.evaluate(expression)
        if support:
            return support
        time.sleep(0.2)
    errors = '; '.join(client.errors[:3])
    raise VideoError(
        f'the page of the export did not load within {timeout:.0f} s'
        + (f', {errors}' if errors else '')
    )


def _browser_error(state: dict[str, Any], options: Options) -> str:
    """Returns the message of an export that failed in the browser, from the state it left."""
    found = state.get('id')
    values = state.get('values') or {}
    if found == 'video.browser.error.size':
        return (
            f'the video reached its maximum size of {options.max_megabytes} MB, '
            'so choose a shorter range or raise the maximum size'
        )
    if found == 'video.browser.error.page':
        return f'the page cannot draw in this Chrome, {values.get("error")}'
    if found == 'video.browser.error.timeout':
        return f'the page did not open the recording within {values.get("seconds")} s'
    if found == 'video.browser.error.encoder':
        return f"the browser's video encoder stopped, {values.get('error')}"
    if found == 'video.browser.error.codec':
        return 'expected a browser that encodes the format asked for, found none at this size'
    return f'the page failed, {state.get("message")}'


def _draw_in_browser(
    client: _CDP,
    page_id: str,
    title: str,
    options: Options,
    container: str,
    span: tuple[float, float],
    limit: int,
    partial: Path,
    summary: dict[str, Any],
    report: Report,
    cancelled: threading.Event,
) -> tuple[int, bool, str]:
    """Runs the browser's own export and writes the file it makes to `partial`.

    Returns:
        The frames written, whether the video reached its maximum length and the codec.
    """
    start, end = span
    body: dict[str, Any] = {
        'start': start,
        'end': end,
        'camera': options.camera,
        'width': options.width,
        'height': options.height,
        'fps': options.fps,
        'quality': options.quality,
        'score': options.score,
        'annotations': options.annotations,
        'scale': options.graphics,
        'safe': options.safe,
        'broadcast': options.broadcast,
    }
    if options.arena is not None:
        body['arena'] = options.arena
    if options.hour is not None:
        body['time'] = options.hour
    request = {
        'match': page_id,
        'title': title,
        'body': body,
        'container': container,
        'maxFrames': limit,
        'maxBytes': options.max_megabytes * 1024 * 1024,
    }
    client.evaluate(f'cujuVideoExport.start({json.dumps(request)})')
    report({'stage': 'drawing', 'frame': 0, 'progress': 0.0, **summary})
    reported = time.monotonic()
    asked = False
    while True:
        if cancelled.is_set() and not asked:
            client.evaluate('cujuVideoExport.cancel()')
            asked = True
        state = client.evaluate('cujuVideoExport.state()') or {}
        stage = state.get('state')
        if stage == 'cancelled':
            raise CancelledError('the export was cancelled')
        if stage == 'failed':
            raise VideoError(_browser_error(state, options))
        if stage == 'done':
            break
        now = time.monotonic()
        if stage == 'running' and state.get('frame') and now - reported >= 0.5:
            reported = now
            progress = min(1.0, max(0.0, float(state.get('progress') or 0)))
            report(
                {'stage': 'drawing', 'frame': int(state['frame']), 'progress': progress, **summary}
            )
        time.sleep(0.1 if asked else 0.25)
    written = int(state.get('frames') or 0)
    report({'stage': 'drawing', 'frame': written, 'progress': 1.0, **summary})
    limited = bool(state.get('limited'))
    if limited:
        report({'stage': 'limited', 'frame': written, **summary})
    report({'stage': 'encoding', 'frame': written, **summary})
    size = int(state.get('bytes') or 0)
    with partial.open('wb') as stream:
        for offset in range(0, size, _PIECE):
            if cancelled.is_set():
                raise CancelledError('the export was cancelled')
            piece = base64.b64decode(client.evaluate(f'cujuVideoExport.read({offset}, {_PIECE})'))
            if not piece:
                raise VideoError('the browser lost the finished video before it was saved')
            stream.write(piece)
    client.evaluate('cujuVideoExport.clear()')
    if partial.stat().st_size != size:
        raise VideoError(
            f'expected {size} bytes of video from the browser, found {partial.stat().st_size}'
        )
    return written, limited, str(state.get('codec') or '')


def _draw_with_ffmpeg(
    client: _CDP,
    address: str,
    page_id: str,
    options: Options,
    ffmpeg: str,
    span: tuple[float, float],
    limit: int,
    partial: Path,
    summary: dict[str, Any],
    report: Report,
    cancelled: threading.Event,
) -> tuple[int, bool]:
    """Draws the export on the Watch page, takes a picture of each frame and encodes them with
    ffmpeg into `partial`, for an MP4 where the browser encodes no H.264.

    Returns:
        The frames written and whether the video reached its maximum length.
    """
    start, end = span
    frames = summary['frames']
    warm = min(start, WARMUP)
    warm_frames = round(warm * options.fps)
    warm_from = start - warm_frames / options.fps
    step = 1000 / options.fps
    client.call('Page.addScriptToEvaluateOnNewDocument', {'source': preload_script(options)})
    css_width, css_height, scale = view(options.width, options.height, options.graphics)
    client.call(
        'Emulation.setDeviceMetricsOverride',
        {'width': css_width, 'height': css_height, 'deviceScaleFactor': scale, 'mobile': False},
    )
    safe = urllib.parse.quote(str(options.safe))
    target = f'{address}?capture=1&safe={safe}#match={urllib.parse.quote(page_id)}'
    client.call('Page.navigate', {'url': target})
    _wait_ready(client, page_id)
    client.evaluate(
        _HOLD
        % {
            'broadcast': json.dumps(options.broadcast),
            'camera': json.dumps(options.camera),
            'at': json.dumps(warm_from),
            'score': json.dumps(options.score),
        }
    )
    # The page settles in real time, players rebuilt in their kits and the camera in place.
    time.sleep(1.0)
    if cancelled.is_set():
        raise CancelledError('the export was cancelled')
    client.evaluate(_PLAY % {'at': json.dumps(warm_from)})
    for _ in range(warm_frames):
        client.evaluate(_STEP % step)
    encoder = _spawn(
        ffmpeg_command(ffmpeg, partial, options),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        stderr: list[bytes] = []
        threading.Thread(target=lambda: stderr.extend(encoder.stderr), daemon=True).start()
        report({'stage': 'drawing', 'frame': 0, 'progress': 0.0, **summary})
        reported = time.monotonic()
        total = frames if not options.broadcast else limit
        index = 0
        while index < total:
            if cancelled.is_set():
                raise CancelledError('the export was cancelled')
            position = client.evaluate(_STEP % (0 if index == 0 else step))
            if options.broadcast and index >= 1 and position >= end:
                break
            picture = client.call(
                'Page.captureScreenshot', {'format': 'png', 'optimizeForSpeed': True}
            )
            try:
                encoder.stdin.write(base64.b64decode(picture['data']))
            except (BrokenPipeError, OSError) as error:
                encoder.wait(30)
                limit_bytes = options.max_megabytes * 1024 * 1024
                if partial.exists() and partial.stat().st_size >= 0.9 * limit_bytes:
                    raise VideoError(
                        f'the video reached its maximum size of {options.max_megabytes} MB, '
                        'so choose a shorter range or raise the maximum size'
                    ) from error
                tail = b''.join(stderr).decode(errors='replace').strip()[-400:]
                raise VideoError(f'ffmpeg stopped while encoding, {tail}') from error
            index += 1
            now = time.monotonic()
            if now - reported >= 0.5 or index == total:
                reported = now
                if options.broadcast:
                    progress = (position - start) / max(1e-9, end - start)
                else:
                    progress = index / total
                report(
                    {
                        'stage': 'drawing',
                        'frame': index,
                        'progress': min(1.0, max(0.0, progress)),
                        **summary,
                    }
                )
        limited = options.broadcast and index >= total
        if limited:
            report({'stage': 'limited', 'frame': index, **summary})
        report({'stage': 'encoding', 'frame': index, **summary})
        encoder.stdin.close()
        code = encoder.wait()
        if code != 0:
            tail = b''.join(stderr).decode(errors='replace').strip()[-400:]
            raise VideoError(f'ffmpeg failed with exit code {code}, {tail}')
        return index, limited
    finally:
        if encoder.poll() is None:
            with contextlib.suppress(OSError):
                encoder.stdin.close()
            _stop(encoder, 5)


def export(
    path: Path,
    output: Path,
    options: Options,
    identifier: str | None = None,
    report: Report | None = None,
    cancelled: threading.Event | None = None,
    overwrite: bool = True,
) -> dict[str, Any]:
    """Exports a range of a recording as a video file and returns what was written.

    The browser encodes the video, MP4 with H.264 where it can and WebM otherwise, as `Options`
    asks through its format or the output's suffix, and an installed ffmpeg encodes an MP4 that
    the browser cannot. With the format auto the output takes the suffix of the container that the
    export writes. The video goes to a temporary file beside the output, which takes its name once
    complete, so an export that fails or is cancelled leaves no partial file behind.

    Args:
        path: The recording file.
        output: The MP4 or WebM file to write.
        options: The checked options.
        identifier: The recording's identifier in the library, or `None` for a file outside it.
        report: Called with each report of progress, a dictionary with `stage` and, while
            drawing, `frame`, `frames` and `progress` from 0 to 1.
        cancelled: An event that cancels the export once set, beside Ctrl+C.
        overwrite: Whether the export may replace a file of the output's name.

    Raises:
        ArgumentError: If an option or the range is invalid, or the output exists.
        VideoError: If the browser is missing, encodes nothing that is asked for, or stops, or
            the export is cancelled.
    """
    options.check()
    report = report or (lambda _: None)
    cancelled = cancelled or threading.Event()
    output = Path(output)
    wanted = requested_format(output, options)
    # The range is checked before the programs are looked for, so a mistake in it shows at once.
    facts = recording_facts(Path(path))
    start, end = resolve_range(options, facts)
    frames = frame_count(start, end, options.fps)
    limit = round(options.max_seconds * options.fps)
    if not options.broadcast and frames > limit:
        raise ArgumentError(
            f'expected at most {options.max_seconds:g} seconds of video, the range from '
            f'{start:.1f} to {end:.1f} runs {end - start:.1f} seconds, so choose a shorter range '
            'or raise the maximum length'
        )
    chrome = find_chrome(options.chrome)
    if chrome is None:
        raise VideoError(chrome_missing())
    # ffmpeg is optional and serves only an MP4 that the browser cannot encode.
    ffmpeg = find_ffmpeg(options.ffmpeg) if wanted != 'webm' else None
    summary = {
        'title': facts.title,
        'start': start,
        'end': end,
        'frames': frames,
        'width': options.width,
        'height': options.height,
        'fps': options.fps,
    }
    report({'stage': 'starting', **summary})
    output.parent.mkdir(parents=True, exist_ok=True)
    page_id = identifier or _FILE_IDENTIFIER
    browser = _Chrome(chrome, options)
    partial: Path | None = None
    final = output
    written, limited, codec, way, container = 0, False, '', 'browser', wanted or 'mp4'
    try:
        with _page_server(Path(path), page_id) as address:
            client = browser.start()
            client.call('Runtime.enable')
            client.call('Page.enable')
            css_width, css_height, _ = view(options.width, options.height, options.graphics)
            client.call(
                'Emulation.setDeviceMetricsOverride',
                {'width': css_width, 'height': css_height, 'deviceScaleFactor': 1, 'mobile': False},
            )
            client.call(
                'Emulation.setEmulatedMedia',
                {
                    'features': [
                        {'name': 'prefers-color-scheme', 'value': 'dark'},
                        {'name': 'prefers-reduced-motion', 'value': 'no-preference'},
                    ]
                },
            )
            client.call('Page.navigate', {'url': f'{address}export.html'})
            support = _wait_host(client, options)
            way, container = choose_encoding(wanted, support, ffmpeg, Path(chrome).name)
            final = output.with_suffix(SUFFIXES[container])
            if not overwrite and final.exists():
                raise ArgumentError(f'expected a new output file, {final} exists, add --overwrite')
            partial = final.with_name(f'.{final.stem}.part{final.suffix}')
            summary['format'] = container
            if cancelled.is_set():
                raise CancelledError('the export was cancelled')
            if way == 'browser':
                written, limited, codec = _draw_in_browser(
                    client, page_id, facts.title, options, container, (start, end), limit,
                    partial, summary, report, cancelled,
                )  # fmt: skip
            else:
                written, limited = _draw_with_ffmpeg(
                    client, address, page_id, options, ffmpeg, (start, end), limit, partial,
                    summary, report, cancelled,
                )  # fmt: skip
                codec = 'h264'
            errors = client.errors[:3]
        os.replace(partial, final)
    except KeyboardInterrupt as error:
        raise CancelledError('the export was cancelled') from error
    finally:
        browser.stop()
        if partial is not None and partial.exists():
            _remove(partial)
    result = {
        **summary,
        'frames': written,
        'seconds': written / options.fps,
        'bytes': final.stat().st_size,
        'path': str(final),
        'format': container,
        'codec': codec,
        'encoder': way,
        'limited': limited,
        'page_errors': errors,
    }
    report({'stage': 'done', **result})
    return result


def resolve_source(source: str) -> tuple[Path, str | None]:
    """Returns the recording file that a source names, a path or a library identifier.

    Raises:
        ArgumentError: If the source is neither a file nor a recording of the library.
    """
    from .._store import library as _library

    path = Path(source).expanduser()
    if path.is_file():
        return path, None
    found = _library.path_of(source)
    if found is not None:
        return found, source
    raise ArgumentError(
        f'expected a .cjr file or the identifier of a recording of the library, found {source!r}'
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Adds the arguments of an export to a parser."""
    parser.add_argument('source', help='a .cjr recording file or the identifier of a recording')
    parser.add_argument(
        '-o',
        '--output',
        help='the MP4 or WebM file to write, by default the name of the source',
    )
    parser.add_argument(
        '--format',
        choices=FORMATS,
        help='the container, mp4 with H.264 or webm with VP9 or VP8, by default the suffix of '
        '--output, or auto, mp4 where the browser encodes H.264 and webm otherwise',
    )
    parser.add_argument(
        '--overwrite', action='store_true', help='replace the output file when it exists'
    )
    parser.add_argument(
        '--start',
        type=_moment,
        help='where the video starts, as seconds, minutes:seconds or goal:N with an offset',
    )
    parser.add_argument('--end', type=_moment, help='where the video ends, as --start takes it')
    parser.add_argument(
        '--goal',
        type=int,
        help=f'the range around goal N, from {GOAL_BEFORE:g} s before to {GOAL_AFTER:g} s after',
    )
    parser.add_argument('--camera', choices=CAMERAS, default='broadcast', help='the camera')
    parser.add_argument(
        '--size',
        type=_size,
        default=DEFAULT_SIZE,
        help='the picture size, as 1280x720 or a preset such as 1080p or vertical, '
        '1280x720 by default',
    )
    parser.add_argument(
        '--scale',
        type=_graphics,
        dest='graphics',
        default=1.0,
        help='the scale of the graphics, from 0.5 to 2, 1 by default',
    )
    parser.add_argument(
        '--safe',
        type=_safe,
        default='auto',
        help='the safe area of the graphics, auto, none, social or a percentage, auto by default',
    )
    parser.add_argument(
        '--fps', type=int, default=DEFAULT_FPS, help=f'frames a second, {DEFAULT_FPS} by default'
    )
    parser.add_argument(
        '--quality', choices=tuple(QUALITIES), default='standard', help='standard by default'
    )
    parser.add_argument(
        '--no-score', dest='score', action='store_false', help='hide the scoreboard and clock'
    )
    parser.add_argument('--arena', choices=ARENAS, help='the arena, by default the stadium')
    parser.add_argument(
        '--time',
        type=_hour,
        dest='hour',
        help='the time of day, as dawn, day, dusk, night or an hour from 0 to 24',
    )
    parser.add_argument(
        '--annotations',
        action='store_true',
        help="show the labels and the box of the recording's annotations",
    )
    parser.add_argument(
        '--broadcast',
        action='store_true',
        help='keep the team sheets, restarts, celebrations and replays, which lengthen the video',
    )
    parser.add_argument(
        '--max-seconds',
        type=float,
        default=DEFAULT_MAX_SECONDS,
        help=f'the longest video in seconds, {DEFAULT_MAX_SECONDS:g} by default',
    )
    parser.add_argument(
        '--max-size',
        type=int,
        dest='max_megabytes',
        default=DEFAULT_MAX_MEGABYTES,
        help=f'the largest file in MB, {DEFAULT_MAX_MEGABYTES} by default',
    )
    parser.add_argument(
        '--chrome', help='the Chrome, Edge or Chromium program that draws and encodes the video'
    )
    parser.add_argument(
        '--ffmpeg',
        help='the ffmpeg program, optional, which encodes an MP4 where the browser has no H.264',
    )
    parser.add_argument(
        '--software', action='store_true', help='draw without the graphics card, slower'
    )
    parser.add_argument(
        '--no-sandbox',
        dest='sandbox',
        action='store_false',
        help="turn off Chrome's sandbox, which Chrome needs as root or in some containers",
    )


def _moment(text: str) -> Moment:
    try:
        return parse_moment(text)
    except ArgumentError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def _size(text: str) -> tuple[int, int]:
    try:
        return parse_size(text)
    except ArgumentError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def _graphics(text: str) -> float:
    try:
        return _sizes.parse_graphics(text)
    except ArgumentError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def _safe(text: str) -> str | float:
    try:
        return _sizes.parse_safe(text)
    except ArgumentError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def _hour(text: str) -> float:
    try:
        return parse_hour(text)
    except ArgumentError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def options_from(namespace: argparse.Namespace) -> Options:
    """Returns the checked options of a parsed command line."""
    width, height = namespace.size
    return Options(
        start=namespace.start,
        end=namespace.end,
        goal=namespace.goal,
        camera=namespace.camera,
        width=width,
        height=height,
        fps=namespace.fps,
        quality=namespace.quality,
        score=namespace.score,
        annotations=namespace.annotations,
        arena=namespace.arena,
        hour=namespace.hour,
        broadcast=namespace.broadcast,
        graphics=namespace.graphics,
        safe=namespace.safe,
        max_seconds=namespace.max_seconds,
        max_megabytes=namespace.max_megabytes,
        chrome=namespace.chrome,
        ffmpeg=namespace.ffmpeg,
        software=namespace.software,
        sandbox=namespace.sandbox,
        format=getattr(namespace, 'format', None),
    ).check()


def _clock(seconds: float) -> str:
    whole = int(seconds)
    return f'{whole // 60}:{whole % 60:02d}' + (f'.{int(seconds * 10) % 10}' if seconds % 1 else '')


def _console(stream: Any) -> Report:
    """Returns a report of progress for a terminal, one updating line, or a line a tenth."""
    live = stream.isatty()
    state = {'tenth': -1, 'started': time.monotonic()}

    def report(entry: dict[str, Any]) -> None:
        stage = entry['stage']
        if stage == 'starting':
            print(
                f'Exporting {entry["title"]} from {_clock(entry["start"])} to '
                f'{_clock(entry["end"])}, {entry["frames"]} frames of {entry["width"]}x'
                f'{entry["height"]} at {entry["fps"]} frames a second',
                file=stream,
                flush=True,
            )
        elif stage == 'drawing' and not entry['frame']:
            state['started'] = time.monotonic()
        elif stage == 'drawing':
            progress = entry['progress']
            elapsed = time.monotonic() - state['started']
            left = elapsed / progress - elapsed if progress > 0 else 0
            line = f'frame {entry["frame"]}, {progress:.0%}, about {left:.0f} s left'
            if live:
                print(f'\r{line}   ', end='', file=stream, flush=True)
            elif int(progress * 10) > state['tenth']:
                state['tenth'] = int(progress * 10)
                print(line, file=stream, flush=True)
        elif stage == 'limited':
            print(
                '\nthe video reached its maximum length before the end of the range',
                file=stream,
                flush=True,
            )
        elif stage == 'encoding' and live:
            print(file=stream, flush=True)

    return report


def run(namespace: argparse.Namespace) -> int:
    """Runs the export of a parsed command line, printing progress, and returns the exit status."""
    options = options_from(namespace)
    path, identifier = resolve_source(namespace.source)
    if namespace.output:
        output = Path(namespace.output)
        if output.exists() and not namespace.overwrite:
            raise ArgumentError(f'expected a new output file, {output} exists, add --overwrite')
    else:
        # Without a file the video takes the name of the source and the suffix of its container.
        output = Path(f'{path.stem}{SUFFIXES.get(options.format or "", ".mp4")}')
        if options.format is None:
            options.format = 'auto'
    try:
        result = export(
            path, output, options, identifier, _console(sys.stderr), overwrite=namespace.overwrite
        )
    except (CancelledError, KeyboardInterrupt):
        print('\ncuju render: the export was cancelled, nothing was written', file=sys.stderr)
        return 130
    for error in result['page_errors']:
        print(f'cuju render: the page reported {error}', file=sys.stderr)
    print(
        f'saved {result["path"]}, {result["frames"]} frames, {result["seconds"]:.1f} s, '
        f'{file_size(result["bytes"])}'
    )
    return 0


def file_size(count: int) -> str:
    """Returns the size of a file for people, in KB below a megabyte and in MB from there."""
    if count < 1e6:
        return f'{max(1, round(count / 1e3))} KB'
    return f'{count / 1e6:.1f} MB'


def main(arguments: list[str] | None = None) -> int:
    """Runs one export for the page's server and reports its progress as JSON lines.

    A line `cancel` on the standard input, or its end, cancels the export.
    """
    parser = argparse.ArgumentParser(prog='python -m cuju.render._export.video')
    add_arguments(parser)
    namespace = parser.parse_args(arguments)

    def emit(entry: dict[str, Any]) -> None:
        print(json.dumps(entry), flush=True)

    cancelled = threading.Event()

    def watch() -> None:
        for line in sys.stdin:
            if line.strip() == 'cancel':
                break
        cancelled.set()

    threading.Thread(target=watch, daemon=True).start()
    try:
        options = options_from(namespace)
        path, identifier = resolve_source(namespace.source)
        export(path, Path(namespace.output), options, identifier, emit, cancelled)
    except CancelledError:
        emit({'stage': 'cancelled'})
        return 130
    except (Error, OSError) as error:
        emit({'stage': 'failed', 'error': str(error)})
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
