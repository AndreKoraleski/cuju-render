# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The clean feed of the renderer, a picture of fixed size for a streaming program such as OBS.

The page at `/feed` shows the Watch page with its broadcast graphics alone, at the size, scale, safe
area and background that its query names, and follows the source that the query names. This module
reads and writes that query as `web/js/export/feed-params.js` does, answers which match or live
stream a source names at the moment, for the page's `GET /api/feed/resolve`, lists the sources a
feed may follow, for `GET /api/feed`, and runs `cuju render feed`, which prints the addresses of
feeds for people, agents and scripts.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.parse
from collections.abc import Callable
from typing import Any

from cuju.errors import ArgumentError

from .._text import messages as _messages
from .._text.messages import MessageError
from . import sizes as _sizes

# The sources that a feed follows, as the page names them.
SOURCES = ('auto', 'live', 'latest', 'tournament', 'queue', 'recording')
# The sources that follow others, every source but a single recording.
FOLLOWING = ('auto', 'live', 'latest', 'tournament', 'queue')
CAMERAS = ('broadcast', 'tactical', 'goal', 'ball', 'owner')
ARENAS = ('stadium', 'beach', 'rooftop', 'space', 'neon')
HOURS = {'dawn': 6.5, 'day': 15.0, 'dusk': 19.0, 'night': 22.0}
QUALITIES = ('low', 'medium', 'high')
THEMES = ('dark', 'light')
LAYERS = ('full', 'graphics')
BACKGROUNDS = {
    'transparent': 'transparent',
    'black': '#000000',
    'green': '#00b140',
    'blue': '#0047bb',
    'magenta': '#ff00ff',
    'white': '#ffffff',
}
MAX_FPS = 60
# The options of a feed and their defaults, as `FEED_DEFAULTS` of the page.
DEFAULTS: dict[str, Any] = {
    'source': 'auto',
    'size': _sizes.DEFAULT_SIZE,
    'scale': 1.0,
    'safe': 'auto',
    'bg': 'black',
    'layer': 'full',
    'audio': False,
    'volume': 0.5,
    'fps': 0,
    'camera': 'broadcast',
    'loop': False,
    'broadcast': True,
    'show': True,
    'score': True,
    'captions': False,
    'slate': True,
    'quality': 'high',
    'theme': 'dark',
    'arena': None,
    'time': None,
    't': None,
}
_IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')


def parse_source(text: Any) -> tuple[str, str]:
    """Returns the kind of a source and the identifier, title or tournament it names.

    A source is `auto`, `live`, `latest`, `tournament`, `queue`, a kind with a name after a colon,
    such as `live:Evaluation` or `tournament:t-20261110-101500-3fa9`, or the identifier of a
    recording, alone or as `recording:ID`.

    Raises:
        ArgumentError: If the text names no source.
    """
    value = str(text if text is not None else '').strip()
    if not value:
        return 'auto', ''
    head, colon, rest = value.partition(':')
    head, rest = head.lower(), rest.strip()
    if head in SOURCES:
        if head == 'recording' and not rest:
            raise MessageError('server.feed.recording_name')
        if head in ('auto', 'latest', 'queue') and colon:
            raise MessageError('server.feed.nothing_after', source=head, value=repr(value))
        return head, rest
    if _IDENTIFIER.fullmatch(value):
        return 'recording', value
    raise MessageError('server.feed.source', sources=', '.join(SOURCES), value=repr(value))


def source_text(kind: str, name: str) -> str:
    """Writes a source back as an address names it."""
    return f'{kind}:{name}' if name else kind


def parse_background(text: Any) -> str:
    """Returns the CSS color of a background, a name of `BACKGROUNDS` or a hex color."""
    value = str(text).strip().lower()
    if value in BACKGROUNDS:
        return BACKGROUNDS[value]
    digits = value.removeprefix('#')
    if re.fullmatch(r'[0-9a-f]{3}|[0-9a-f]{6}', digits):
        return '#' + (''.join(c * 2 for c in digits) if len(digits) == 3 else digits)
    raise ArgumentError(
        f'expected a background of {", ".join(BACKGROUNDS)} or a hex color, found {text!r}'
    )


def _number(value: Any, name: str, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = math.nan
    if isinstance(value, bool) or not low <= number <= high:
        raise ArgumentError(f'expected {name} from {low:g} to {high:g}, found {value!r}')
    return number


def _choice(value: Any, name: str, choices: tuple[str, ...]) -> str:
    text = str(value).strip().lower()
    if text not in choices:
        raise ArgumentError(f'expected {name} of {", ".join(choices)}, found {value!r}')
    return text


def check(**given: Any) -> dict[str, Any]:
    """Returns the checked options of a feed, its defaults beside the options given.

    The size is a preset or `WxH`, or the width and height given as `width` and `height`. The
    time of day is a name of `HOURS` or an hour.

    Raises:
        ArgumentError: If an option is unknown or out of place.
    """
    width, height = given.pop('width', None), given.pop('height', None)
    unknown = set(given) - set(DEFAULTS)
    if unknown:
        raise ArgumentError(f'expected options of {", ".join(DEFAULTS)}, found {sorted(unknown)}')
    options = {**DEFAULTS, **{key: value for key, value in given.items() if value is not None}}
    options['source'] = source_text(*parse_source(options['source']))
    size = _sizes.parse_size(options['size'])
    if width is not None or height is not None:
        size = _sizes.check_size(
            size[0] if width is None else width, size[1] if height is None else height
        )
    options['size'] = _sizes.size_name(*size)
    options['scale'] = _sizes.parse_graphics(options['scale'])
    options['safe'] = _sizes.parse_safe(options['safe'])
    parse_background(options['bg'])
    options['bg'] = str(options['bg']).strip().lower().removeprefix('#')
    options['layer'] = _choice(options['layer'], 'a layer', LAYERS)
    for flag in ('audio', 'loop', 'broadcast', 'show', 'score', 'captions', 'slate'):
        if not isinstance(options[flag], bool):
            raise ArgumentError(f'expected {flag} as true or false, found {options[flag]!r}')
    options['volume'] = _number(options['volume'], 'a volume', 0, 1)
    fps = options['fps']
    if isinstance(fps, bool) or not isinstance(fps, int) or not 0 <= fps <= MAX_FPS:
        raise ArgumentError(f'expected a frame rate from 0 to {MAX_FPS}, found {fps!r}')
    options['camera'] = _choice(options['camera'], 'a camera', CAMERAS)
    options['quality'] = _choice(options['quality'], 'a quality', QUALITIES)
    options['theme'] = _choice(options['theme'], 'a theme', THEMES)
    if options['arena'] is not None:
        options['arena'] = _choice(options['arena'], 'an arena', ARENAS)
    if options['time'] is not None:
        hour = str(options['time']).strip().lower()
        options['time'] = HOURS[hour] if hour in HOURS else _number(hour, 'an hour', 0, 24)
    if options['t'] is not None:
        options['t'] = _number(options['t'], 'a start', 0, 1e6)
    return options


def _written(value: Any) -> str:
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def query(**given: Any) -> str:
    """Returns the query of a feed's address, the source and size always and every other option
    that differs from its default, in the order of the page's `feedQuery`."""
    options = check(**given)
    pairs = []
    for key, default in DEFAULTS.items():
        value = options[key]
        if key not in ('source', 'size') and (value is None or value == default):
            continue
        pairs.append((key, _written(value)))
    return urllib.parse.urlencode(pairs, safe=':')


def address(base: str, **given: Any) -> str:
    """Returns the whole address of a feed on the server at `base`, such as the server's URL."""
    return f'{base.rstrip("/")}/feed?{query(**given)}'


# The answers of the server, the targets that a source names and the sources there are.


def _newest_live(sources: list[dict[str, Any]], name: str = '') -> dict[str, Any] | None:
    ordered = sorted(sources, key=lambda source: str(source.get('id', '')), reverse=True)
    if name:
        exact = [source for source in ordered if source.get('id') == name]
        if exact:
            return exact[0]
        folded = name.casefold()
        ordered = [s for s in ordered if str(s.get('title') or '').casefold() == folded]
    return ordered[0] if ordered else None


def _target(kind: str, identifier: str, entry: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Returns a target, whose title comes from the summary or the source `entry`, with the
    message of a title that cuju made beside its English text."""
    return {'kind': kind, 'id': identifier, **_messages.named('title', _title(entry)), **extra}


def _title(entry: dict[str, Any] | None) -> dict[str, Any] | str:
    """Returns the title of a summary or a live source, a label when it carries a valid one."""
    entry = entry or {}
    found = {
        'id': entry.get('title_id'),
        'text': str(entry.get('title') or ''),
        'values': entry.get('title_values'),
    }
    return found if _messages.valid_label(found) else found['text']


def _none(message_id: str, **values: Any) -> dict[str, Any]:
    """Returns the answer for a source that names nothing now, with the message of what it waits
    for, whose English text stays in `message`."""
    label = _messages.label(message_id, **values)
    return {'kind': 'none', 'id': '', 'title': '', **_messages.named('message', label)}


def _tournament_match(entry: dict[str, Any]) -> str | None:
    """Returns the recording of the newest finished match of a tournament, or `None`."""
    played = [
        match['result']['match']
        for match in entry.get('matches', [])
        if isinstance(match.get('result'), dict) and isinstance(match['result'].get('match'), str)
    ]
    return max(played) if played else None


def resolve(
    source: str,
    live: Callable[[], list[dict[str, Any]]],
    recordings: Callable[[], list[dict[str, Any]]],
    recording: Callable[[str], dict[str, Any] | None],
    requests: Callable[[], list[dict[str, Any]]],
    tournaments: Callable[[], list[dict[str, Any]]],
    tournament: Callable[[str], dict[str, Any] | None],
) -> dict[str, Any]:
    """Returns what a feed's source names now, a recording, a live source or none.

    Each callable reads one part of the server, the live sources, the recordings newest first,
    one recording's summary, the requests newest first, the tournaments newest first and one
    tournament in full. The answer holds `kind`, `match`, `live` or `none`, the `id` and `title`
    of the target, and for none a `message` that says what the feed waits for.

    Raises:
        ArgumentError: If the text names no source.
    """
    kind, name = parse_source(source)
    if kind in ('auto', 'live'):
        found = _newest_live(live(), name)
        if found is not None:
            return _target('live', found['id'], found)
        if kind == 'live':
            if name:
                return _none('server.feed.no_live_named', name=name)
            return _none('server.feed.no_live')
    if kind in ('auto', 'latest'):
        entries = recordings()
        if entries:
            return _target('match', entries[0]['id'], entries[0])
        return _none('server.feed.no_recordings')
    if kind == 'recording':
        entry = recording(name)
        if entry is None:
            return _none('server.feed.no_recording', name=name)
        return _target('match', name, entry)
    if kind == 'queue':
        done = [
            entry
            for entry in requests()
            if entry.get('state') == 'done' and isinstance(entry.get('match'), str)
        ]
        if done:
            newest = max(done, key=lambda entry: float(entry.get('finished') or 0))
            # The recording's own title names the teams as the match did.
            entry = recording(newest['match']) or {
                'title': f'{newest.get("left", "")} against {newest.get("right", "")}'
            }
            return _target('match', newest['match'], entry, request=newest['id'])
        return _none('server.feed.no_request')
    summaries = tournaments()
    if name:
        chosen = next((t for t in summaries if t.get('id') == name), None) or next(
            (t for t in summaries if str(t.get('name') or '').casefold() == name.casefold()), None
        )
        if chosen is None:
            return _none('server.feed.no_tournament_named', name=name)
    elif summaries:
        chosen = summaries[0]
    else:
        return _none('server.feed.no_tournament')
    entry = tournament(chosen['id'])
    match = _tournament_match(entry) if entry else None
    if match is None:
        if chosen.get('name'):
            return _none('server.feed.tournament_waits', name=str(chosen['name']))
        return _none('server.feed.tournament_waits_unnamed')
    named = {'title': str(chosen.get('name') or '')}
    return _target('match', match, named, tournament=chosen['id'])


def targets(
    base: str,
    live: list[dict[str, Any]],
    tournaments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Returns the sources that a feed may follow now, each with its address on `base`."""
    rows = [
        {'source': kind, **_messages.named('label', _messages.label(f'server.feed.follow.{kind}'))}
        for kind in ('auto', 'latest', 'live', 'queue', 'tournament')
    ]
    # A live source goes by its title, which follows it through its restarts, and a source without
    # a title by its identifier. Sources of one title share a row, the newest of them.
    named = set()
    for source in sorted(live, key=lambda s: str(s.get('id', '')), reverse=True):
        title = str(source.get('title') or '').strip()
        name = title or str(source['id'])
        if name.casefold() in named:
            continue
        named.add(name.casefold())
        shown = _title(source) if title else name
        label = _messages.label('server.feed.follow.live_named', name=shown)
        rows.append({'source': f'live:{name}', **_messages.named('label', label)})
    for entry in tournaments[:8]:
        label = _messages.label(
            'server.feed.follow.tournament_named', name=str(entry.get('name') or entry['id'])
        )
        rows.append({'source': f'tournament:{entry["id"]}', **_messages.named('label', label)})
    for row in rows:
        row['url'] = address(base, source=row['source'])
    return rows


# The command line.


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Adds the arguments of `cuju render feed` to a parser."""
    parser.add_argument(
        'source',
        nargs='?',
        help='what the feed follows, auto, live, latest, tournament, queue, live:NAME, '
        'tournament:ID or a recording identifier, by default a list of every source',
    )
    parser.add_argument(
        '--size', default=None, help='the picture size, as 1920x1080 or a preset, 1080p by default'
    )
    parser.add_argument('--width', type=int, default=None, help='the width in pixels')
    parser.add_argument('--height', type=int, default=None, help='the height in pixels')
    parser.add_argument('--scale', default=None, help='the scale of the graphics, 0.5 to 2')
    parser.add_argument('--safe', default=None, help='the safe area, auto, none, social or percent')
    parser.add_argument(
        '--background',
        dest='bg',
        default=None,
        help='transparent, black, green, blue, magenta, white or a hex color, black by default',
    )
    parser.add_argument(
        '--graphics-only',
        action='store_true',
        help='the graphics alone over the background, without the picture',
    )
    parser.add_argument('--audio', action='store_true', help="the match's sound, silent by default")
    parser.add_argument('--volume', type=float, default=None, help='the volume from 0 to 1')
    parser.add_argument(
        '--fps', type=int, default=None, help='the frame rate, 1 to 60, the display by default'
    )
    parser.add_argument('--camera', choices=CAMERAS, default=None, help='the camera')
    parser.add_argument(
        '--loop', action='store_true', help='play a recording again from its start at its end'
    )
    parser.add_argument(
        '--plain',
        action='store_true',
        help='leave out the lineups, celebrations, replays, restarts and the show after the match',
    )
    parser.add_argument('--no-show', action='store_true', help='leave out the show after the match')
    parser.add_argument('--no-score', action='store_true', help='hide the scoreboard and clock')
    parser.add_argument('--captions', action='store_true', help='show captions of the events')
    parser.add_argument(
        '--no-slate', action='store_true', help='show the background alone while nothing plays'
    )
    parser.add_argument('--quality', choices=QUALITIES, default=None, help='high by default')
    parser.add_argument('--theme', choices=THEMES, default=None, help='dark by default')
    parser.add_argument('--arena', choices=ARENAS, default=None, help='the arena')
    parser.add_argument('--time', default=None, help='dawn, day, dusk, night or an hour')
    parser.add_argument('--start', type=float, default=None, help='the second a recording starts')
    parser.add_argument('--json', action='store_true', help='print JSON, for scripts and agents')
    parser.add_argument('--port', type=int, default=8780, help='the port when no server runs')


def options_from(namespace: argparse.Namespace) -> dict[str, Any]:
    """Returns the checked options of a parsed command line, without its source."""
    given = {
        'size': namespace.size,
        'width': namespace.width,
        'height': namespace.height,
        'scale': namespace.scale,
        'safe': namespace.safe,
        'bg': namespace.bg,
        'layer': 'graphics' if namespace.graphics_only else None,
        'audio': True if namespace.audio else None,
        'volume': namespace.volume,
        'fps': namespace.fps,
        'camera': namespace.camera,
        'loop': True if namespace.loop else None,
        'broadcast': False if namespace.plain else None,
        'show': False if namespace.no_show else None,
        'score': False if namespace.no_score else None,
        'captions': True if namespace.captions else None,
        'slate': False if namespace.no_slate else None,
        'quality': namespace.quality,
        'theme': namespace.theme,
        'arena': namespace.arena,
        'time': namespace.time,
        't': namespace.start,
    }
    return {key: value for key, value in given.items() if value is not None}


def _server_base(port: int) -> tuple[str, bool]:
    """Returns the address of the running server of the home folder, or that of `port`."""
    from .._http import launch as _launch

    server = _launch.running()
    if server is not None:
        return server.url.split('#')[0].rstrip('/') + '/', True
    return f'http://127.0.0.1:{port}/', False


def _listed(base: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns the live sources and tournaments that the running server lists."""
    import urllib.request

    def read(path: str) -> list[dict[str, Any]]:
        try:
            with urllib.request.urlopen(base + path, timeout=5) as response:
                value = json.load(response)
        except (OSError, ValueError):
            return []
        return value if isinstance(value, list) else []

    return read('api/live'), read('api/tournaments')


def run(namespace: argparse.Namespace) -> int:
    """Runs `cuju render feed`, which prints the address of a feed or of every source."""
    if not 0 <= namespace.port <= 65535:
        raise ArgumentError('expected a port from 0 to 65535')
    options = options_from(namespace)
    base, running = _server_base(namespace.port)
    if namespace.source is not None:
        url = address(base, source=namespace.source, **options)
        _check_target(namespace.source, base, running)
        rows = [{'source': source_text(*parse_source(namespace.source)), 'url': url}]
    else:
        check(**options)
        live, cups = _listed(base) if running else ([], [])
        rows = targets(base, live, cups)
        for row in rows:
            row['url'] = address(base, source=row['source'], **options)
    if namespace.json:
        print(json.dumps({'server': base, 'running': running, 'feeds': rows}, indent=2))
    elif namespace.source is not None:
        print(rows[0]['url'])
    else:
        for row in rows:
            print(f'{row["url"]}\n    {row["label"]}')
    if not running:
        print(
            f'cuju render: no server of {_home_text()} answers, start it with cuju render serve '
            f'--port {namespace.port} before adding the feed',
            file=sys.stderr,
        )
    return 0


def _check_target(source: str, base: str, running: bool) -> None:
    """Checks that a feed's recording is in the library and its tournament on the server.

    A live source may start later, so a name of one passes. A recording must be in the library,
    and a named tournament must be one of the running server.

    Raises:
        ArgumentError: If the recording or the tournament is unknown.
    """
    from .._store import library as _library

    kind, name = parse_source(source)
    if kind == 'recording' and _library.path_of(name) is None:
        raise ArgumentError(
            f'expected a recording of the library, found none named {name}, the Recordings page '
            'and cuju render search list them'
        )
    if kind == 'tournament' and name and running:
        cups = _listed(base)[1]
        folded = name.casefold()
        if not any(
            entry.get('id') == name or str(entry.get('name') or '').casefold() == folded
            for entry in cups
        ):
            raise ArgumentError(f'expected a tournament of the server, found none named {name}')


def _home_text() -> str:
    from .._store import home as _home

    return str(_home.home())
