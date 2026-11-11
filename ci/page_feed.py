# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Page checks of the clean feed at /feed, which page_check.py runs through its Chrome.

Each check opens the feed in a tab of its own at a window size of its own, reads the state of the
page inside the feed's frame and closes the tab, so the tab of the other checks keeps its state.
The windows stay small and the feeds draw at low quality, so software drawing keeps up.
"""

import base64
import json
import struct
import time
import urllib.parse
import urllib.request
import zlib

# The page inside the frame of /feed.
_INNER = "document.getElementById('feed-frame').contentWindow"


class _Tab:
    """A tab of its own at a window size, with a connection to it."""

    def __init__(self, client, debug, connect, width, height):
        self.client = client
        # A window of its own, in front, since a tab behind another draws no frames.
        created = client.call('Target.createTarget', {'url': 'about:blank', 'newWindow': True})
        self.target = created['targetId']
        self.tab = connect(f'ws://127.0.0.1:{debug}/devtools/page/{self.target}')
        # A page that loads its art in software holds its thread for a while.
        self.tab.socket.settimeout(300)
        self.tab.call('Runtime.enable')
        self.tab.call('Page.enable')
        self.tab.call(
            'Emulation.setDeviceMetricsOverride',
            {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': False},
        )
        self.tab.call('Page.bringToFront')

    def open(self, url):
        self.tab.call('Page.navigate', {'url': url})

    def evaluate(self, expression):
        return self.tab.evaluate(expression)

    def state(self):
        return self.evaluate(f"""(() => {{
            try {{
                const app = {_INNER}.cuju;
                return app && app.feed ? app.feed.state() : null;
            }} catch (err) {{
                return null;
            }}
        }})()""")

    # A loaded machine draws in software slowly, so a feed gets a while to open its source.
    def until(self, test, seconds=240, what='the feed'):
        deadline = time.monotonic() + seconds
        state = None
        while time.monotonic() < deadline:
            state = self.state()
            if state and test(state):
                return state
            time.sleep(0.25)
        raise RuntimeError(f'{what} did not settle, {state}')

    def close(self):
        errors = list(self.tab.errors)
        self.tab.call('Emulation.clearDeviceMetricsOverride')
        self.tab.socket.close()
        self.client.call('Target.closeTarget', {'targetId': self.target})
        return errors


# Reads where the graphics lie against the safe area, inside the frame, in its CSS pixels.
_PLACES = f"""(() => {{
    const w = {_INNER};
    const d = w.document;
    const rect = (sel) => {{
        const e = d.querySelector(sel);
        if (!e) return null;
        // The box as laid out, before the transforms of an entrance that may still run.
        let left = 0, top = 0;
        for (let n = e; n && n !== d.body; n = n.offsetParent) {{
            left += n.offsetLeft;
            top += n.offsetTop;
        }}
        return {{ left, top, right: left + e.offsetWidth, bottom: top + e.offsetHeight }};
    }};
    const shown = (sel) => {{
        const e = d.querySelector(sel);
        return !!e && w.getComputedStyle(e).display !== 'none'
            && w.getComputedStyle(e).visibility !== 'hidden';
    }};
    const app = d.getElementById('app');
    return {{
        view: {{ width: w.innerWidth, height: w.innerHeight }},
        shape: ['wide', 'square', 'tall'].find((s) => app.classList.contains('shape-' + s)),
        scoreboard: rect('#scoreboard'),
        goal: rect('#goal-banner'),
        shown: Object.fromEntries(['#topbar', '#watch-bar', '#controls', '#toast', '#tip',
            '#scoreboard', '#stage', '#watch-empty'].map((s) => [s, shown(s)])),
        cursor: w.getComputedStyle(d.body).cursor,
        muted: w.cuju.settings.muted,
        storedMuted: localStorage.getItem('cuju.muted'),
        storedTv: localStorage.getItem('cuju.tvMode'),
        innerTv: w.localStorage.getItem('cuju.tvMode'),
        locked: !!d.pointerLockElement,
        gate: typeof w.cuju.frameGate === 'function',
        background: getComputedStyle(document.body).backgroundColor,
        frame: document.getElementById('feed-frame').style.transform,
    }};
}})()"""


def _corner_alpha(tab):
    """Returns the opacity from 0 to 255 of the top left pixel of a tab's picture.

    The tab draws over a transparent default background, so only what the page paints shows. The
    first pixel of a PNG reads the same under every filter of its first row.
    """
    transparent = {'color': {'r': 0, 'g': 0, 'b': 0, 'a': 0}}
    tab.tab.call('Emulation.setDefaultBackgroundColorOverride', transparent)
    try:
        clip = {'x': 0, 'y': 0, 'width': 4, 'height': 4, 'scale': 1}
        shot = tab.tab.call('Page.captureScreenshot', {'format': 'png', 'clip': clip})
    finally:
        tab.tab.call('Emulation.setDefaultBackgroundColorOverride', {})
    data = base64.b64decode(shot['data'])
    position, kind, compressed = 8, None, b''
    while position < len(data):
        (length,) = struct.unpack('>I', data[position : position + 4])
        name = data[position + 4 : position + 8]
        body = data[position + 8 : position + 8 + length]
        position += 12 + length
        if name == b'IHDR':
            kind = body[9]
        elif name == b'IDAT':
            compressed += body
    raw = zlib.decompress(compressed)
    return raw[4] if kind == 6 else 255


def _inside(box, safe, view, slack=1.5):
    """Returns whether a box lies inside the safe area of a view."""
    return (
        box is not None
        and box['left'] >= safe['left'] - slack
        and box['top'] >= safe['top'] - slack
        and box['right'] <= view['width'] - safe['right'] + slack
        and box['bottom'] <= view['height'] - safe['bottom'] + slack
    )


def _recordings(base):
    with urllib.request.urlopen(base + 'api/matches', timeout=10) as response:
        return [entry['id'] for entry in json.load(response)]


def _live(base):
    with urllib.request.urlopen(base + 'api/live', timeout=10) as response:
        return [entry['id'] for entry in json.load(response)]


def _process_title(base):
    """Returns the title of a live source of a process, which a new process of it takes again."""
    with urllib.request.urlopen(base + 'api/live', timeout=10) as response:
        sources = json.load(response)
    return next(entry['title'] for entry in sources if entry.get('environment_count', 1) == 1)


def check_feed(client, base, debug, connect):
    """Checks the feed at several sizes, its sources, its slate, its recovery and its options.

    Args:
        client: The CDP connection of page_check.py.
        base: The address of the mock server, such as `http://127.0.0.1:8790/`.
        debug: The port of Chrome's debugging connection.
        connect: Makes a CDP connection from the address of a tab.

    Returns:
        The number of checks that passed.
    """
    checks = 0
    # The tab of the other checks rests on a page that draws nothing, so the feeds draw alone.
    client.socket.settimeout(300)
    client.evaluate("cuju.timeline && cuju.timeline.pause(); cuju.showPage('recordings')")
    match = _recordings(base)[0]
    stored_tv = client.evaluate("localStorage.getItem('cuju.tvMode')")
    sizes = [
        ('1080p', 640, 360, (1280, 720), 'wide'),
        ('vertical', 360, 640, (720, 1280), 'tall'),
        ('square', 400, 400, (720, 720), 'square'),
        ('4k', 480, 270, (1280, 720), 'wide'),
        ('640x360', 640, 360, (640, 360), 'wide'),
    ]
    for size, width, height, view, shape in sizes:
        tab = _Tab(client, debug, connect, width, height)
        try:
            tab.open(
                f'{base}feed?source=recording:{match}&size={size}&quality=low&fps=30&broadcast=0'
            )
            state = tab.until(
                lambda s: s['showing'] and s['showing']['id'] == match and s['playing'],
                what=f'the feed at {size}',
            )
            places = tab.evaluate(_PLACES)
            assert places['view'] == {'width': view[0], 'height': view[1]}, (size, places)
            assert state['view'] == {'width': view[0], 'height': view[1]}, (size, state)
            assert places['shape'] == shape, (size, places)
            assert _inside(places['scoreboard'], state['safe'], places['view']), (size, places)
            if shape != 'wide':
                # A square or tall picture gives the scoreboard the width of the safe area.
                room = view[0] - state['safe']['left'] - state['safe']['right']
                board = places['scoreboard']['right'] - places['scoreboard']['left']
                assert board >= 0.95 * room, (size, board, room)
            assert state['safe']['top'] > 0 and state['safe']['left'] > 0, state
            shown = places['shown']
            assert shown['#scoreboard'] and shown['#stage'], (size, shown)
            hidden = ('#topbar', '#watch-bar', '#controls', '#toast', '#tip', '#watch-empty')
            assert not any(shown[s] for s in hidden), (size, shown)
            assert places['cursor'] == 'none' and places['muted'] and places['gate'], places
            assert places['innerTv'] == 'true' and places['storedTv'] == stored_tv, places
            assert places['storedMuted'] in ('true', None) and not places['locked'], places
            fitted = min(width / state['width'], height / state['height'])
            ratio = state['layout']['scale'] * fitted
            assert abs(state['ratio'] - ratio) < 1e-3, (size, state, ratio)
            # The goal graphic stays inside the safe area at every shape.
            tab.evaluate(f'{_INNER}.cuju.hud.showGoal(0, true)')
            time.sleep(0.8)
            goal = tab.evaluate(_PLACES)['goal']
            assert _inside(goal, state['safe'], places['view']), (size, goal, state['safe'])
            checks += 1
        finally:
            errors = tab.close()
        assert not errors, (size, errors)

    # A transparent feed of the graphics alone, and a feed whose address holds a mistake.
    tab = _Tab(client, debug, connect, 640, 360)
    try:
        tab.open(
            f'{base}feed?source={match}&bg=transparent&layer=graphics&size=huge&quality=low'
            '&broadcast=0'
        )
        state = tab.until(lambda s: s['showing'] and s['playing'], what='the graphics alone')
        places = tab.evaluate(_PLACES)
        assert places['background'] == 'rgba(0, 0, 0, 0)', places
        # The frame draws no opaque backdrop, so a corner that the graphics leave empty stays clear.
        assert _corner_alpha(tab) == 0, 'the transparent feed drew an opaque backdrop'
        assert not places['shown']['#stage'] and places['shown']['#scoreboard'], places
        assert (state['width'], state['height']) == (1920, 1080), state
        assert len(state['problems']) == 1 and 'size' in state['problems'][0], state
        checks += 1
    finally:
        assert not tab.close()

    # A feed that waits shows its slate, and a feed of a live source follows the source when it
    # ends and a new one takes its place.
    tab = _Tab(client, debug, connect, 640, 360)
    try:
        # The queue shows the newest finished request, which an earlier check may have left, and
        # waits on its slate while none has finished.
        with urllib.request.urlopen(base + 'api/requests', timeout=10) as response:
            done = [e for e in json.load(response) if e.get('state') == 'done' and e.get('match')]
        tab.open(f'{base}feed?source=queue&quality=low')
        if done:
            state = tab.until(
                lambda s: s['showing'] and s['showing']['id'] == done[0]['match'],
                what='the newest requested match',
            )
        else:
            state = tab.until(lambda s: s['slate'] and s['online'], what='the slate')
            assert state['showing'] is None and 'requested match' in state['message'], state
        checks += 1
    finally:
        assert not tab.close()
    tab = _Tab(client, debug, connect, 640, 360)
    try:
        # The feed follows a training process by its title, past the restart of the process.
        title = urllib.parse.quote(_process_title(base), safe='')
        tab.open(f'{base}feed?source=live:{title}&quality=low')
        first = tab.until(
            lambda s: s['showing'] and s['showing']['kind'] == 'live' and not s['slate'],
            what='the live feed',
        )['showing']['id']
        assert first in _live(base)
        request = urllib.request.Request(f'{base}api/mock/live/{first}/end', method='POST')
        urllib.request.urlopen(request, timeout=10).close()
        state = tab.until(
            lambda s: s['showing'] and s['showing']['id'] != first and not s['finished'],
            seconds=90,
            what='the feed after its source ended',
        )
        assert state['showing']['id'] in _live(base), state
        checks += 1
    finally:
        assert not tab.close()
    return checks
