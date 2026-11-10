# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Page checks of the 2D view of Watch, which page_check.py runs through its Chrome."""

import time


def _wait_ready(client):
    for _ in range(150):
        if client.evaluate('!!(window.cuju && window.cuju.menus)'):
            return
        time.sleep(0.2)
    raise RuntimeError('Renderer startup failed.')


def _open_match(client):
    """Opens the first recording of the library on Watch, without its lineups."""
    client.evaluate("""
        (async () => {
            const { api } = await import('./js/core/api.js');
            window.checkMatch = (await api.matches())[0].id;
            cuju.openMatchInWatch(window.checkMatch);
        })()
    """)
    for _ in range(100):
        if client.evaluate("""
            !!(cuju.source && cuju.source.id === window.checkMatch && cuju.players
                && cuju.timeline && cuju.timeline.store.size > 1)
        """):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError('The recording did not open.')
    time.sleep(0.3)
    client.evaluate('cuju.director.stop(false)')


def check_flat(client, base):
    """Checks the 2D view, its toggle, playback, skipped replays, the offer and a missing WebGL.

    Args:
        client: The CDP connection of page_check.py, on the page at `base`.
        base: The address of the mock server, such as `http://127.0.0.1:8790/`.

    Returns:
        The number of checks that passed.
    """
    _open_match(client)
    result = client.evaluate("""
        (async () => {
            const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            const tl = cuju.timeline;
            let renders = 0;
            const render = cuju.view.render;
            cuju.view.render = (...args) => { renders++; return render.apply(cuju.view, args); };
            document.getElementById('view-menu-btn').click();
            await sleep(50);
            const item = [...document.querySelectorAll('#view-drawing [role^="menuitem"]')]
                .find((node) => node.dataset.label === '2D view');
            const offered = !!item && item.getAttribute('aria-checked') === 'false';
            item.click();
            await sleep(50);
            const canvas = document.getElementById('flat-view');
            const on = cuju.flat.on && !canvas.hidden && document.getElementById('view-2d').checked
                && localStorage.getItem('cuju.view2d') === 'true'
                && !document.getElementById('view-menu').classList.contains('open');
            cuju.act('play');
            renders = 0;
            const t0 = tl.t;
            await sleep(600);
            const played = tl.t > t0 + 2 && renders === 0;
            const pixel = canvas.getContext('2d').getImageData(4, canvas.height >> 1, 1, 1).data;
            const drawn = pixel[3] === 255 && pixel[1] > pixel[0];
            const before = tl.t;
            cuju.act('forward-5');
            const seeks = tl.t >= before + 4 * tl.sps;
            cuju.setSpeed(3);
            const speed = tl.speed === 2;
            cuju.setSpeed(2);
            const gated = cuju.settings.replays === false && cuju.settings.podium === false;
            cuju.replayGoal({ index: tl.first + 5, team: 0 });
            const skipped = !cuju.director.running;
            const box = document.getElementById('view-2d');
            box.checked = false;
            box.dispatchEvent(new Event('change'));
            await sleep(200);
            const off = !cuju.flat.on && canvas.hidden && renders > 0
                && localStorage.getItem('cuju.view2d') === 'false';
            cuju.view.render = render;
            // A slow 3D picture offers the 2D view once, and Keep 3D declines it.
            cuju.flat.suggested = false;
            localStorage.removeItem('cuju.view2dDeclined');
            // The offer counts frames of a match that plays, so any show or card goes first.
            cuju.director.stop(false);
            if (cuju.postMatch.running) cuju.postMatch.end({ home: false });
            tl.seek(tl.first);
            tl.play(1);
            const playing = tl.playing && !cuju.director.running && !cuju.postMatch.running;
            // A fresh window, so the frames the page drew before count for nothing.
            cuju.flat.frames = 0;
            cuju.flat.seconds = 0;
            for (let i = 0; i < 30; i++) cuju.flat.measure(0.2);
            const prompt = document.getElementById('flat-suggest');
            const suggested = !prompt.hidden && prompt.hasAttribute('data-prompt')
                && /5 frames a second/.test(prompt.textContent);
            const buttons = [...prompt.querySelectorAll('button')];
            buttons.find((b) => b.textContent === 'Keep 3D').click();
            const declined = prompt.hidden
                && localStorage.getItem('cuju.view2dDeclined') === 'true';
            cuju.flat.suggested = false;
            cuju.flat.frames = 0;
            cuju.flat.seconds = 0;
            for (let i = 0; i < 30; i++) cuju.flat.measure(0.2);
            const quiet = prompt.hidden;
            localStorage.removeItem('cuju.view2dDeclined');
            tl.pause();
            const all = {
                offered, on, played, drawn, seeks, speed, gated, skipped, off, suggested,
                declined, quiet, playing,
            };
            return Object.values(all).every(Boolean) || JSON.stringify(all);
        })()
    """)
    assert result is True, f'2D view {result}'
    checks = 1
    # A browser without WebGL opens the page in the 2D view alone.
    client.call(
        'Page.addScriptToEvaluateOnNewDocument',
        {
            'source': """
                if (sessionStorage.getItem('cuju.check.noWebGL') === 'true') {
                    const context = HTMLCanvasElement.prototype.getContext;
                    HTMLCanvasElement.prototype.getContext = function (kind, ...rest) {
                        return /webgl/.test(kind) ? null : context.call(this, kind, ...rest);
                    };
                }
            """
        },
    )
    client.evaluate("sessionStorage.setItem('cuju.check.noWebGL', 'true')")
    client.call('Page.navigate', {'url': base})
    time.sleep(0.5)
    _wait_ready(client)
    _open_match(client)
    result = client.evaluate("""
        (async () => {
            const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            const forced = !!cuju.noWebGL && cuju.view.headless && cuju.flat.wanted
                && document.getElementById('view-2d').disabled;
            cuju.act('play');
            const t0 = cuju.timeline.t;
            await sleep(500);
            const canvas = document.getElementById('flat-view');
            const pixel = canvas.getContext('2d').getImageData(4, canvas.height >> 1, 1, 1).data;
            const drawn = !canvas.hidden && pixel[3] === 255 && cuju.timeline.t > t0;
            document.getElementById('view-menu-btn').click();
            await sleep(50);
            const item = [...document.querySelectorAll('#view-drawing [role^="menuitem"]')]
                .find((node) => node.dataset.label === '2D view');
            const locked = item.getAttribute('aria-disabled') === 'true';
            document.getElementById('view-menu-btn').click();
            cuju.timeline.pause();
            sessionStorage.removeItem('cuju.check.noWebGL');
            const all = { forced, drawn, locked };
            return Object.values(all).every(Boolean) || JSON.stringify(all);
        })()
    """)
    assert result is True, f'2D view without WebGL {result}'
    checks += 1
    client.call('Page.navigate', {'url': base})
    time.sleep(0.5)
    _wait_ready(client)
    assert not client.evaluate('!!cuju.noWebGL')
    return checks


def _key(client, key, code=None, vk=0, text=None):
    params = {'type': 'keyDown', 'key': key, 'code': code or key, 'windowsVirtualKeyCode': vk}
    if text:
        params['text'] = text
    client.call('Input.dispatchKeyEvent', params)
    client.call('Input.dispatchKeyEvent', {**params, 'type': 'keyUp', 'text': ''})


def _until(client, expression, what, tries=100):
    for _ in range(tries):
        if client.evaluate(expression):
            return
        time.sleep(0.1)
    raise RuntimeError(f'{what} did not happen.')


def check_grid(client):
    """Checks the grid of environments of the mock server's source of several environments.

    Returns:
        The number of checks that passed.
    """
    client.evaluate("""
        (async () => {
            const { api } = await import('./js/core/api.js');
            window.checkGrid = (await api.live()).find((s) => s.environment_count > 1).id;
            cuju.openLive(window.checkGrid);
        })()
    """)
    _until(
        client,
        'cuju.source && cuju.source.id === window.checkGrid && cuju.timeline'
        ' && cuju.source.header.environment_count === 12',
        'The source of several environments',
    )
    result = client.evaluate(r"""
        (async () => {
            const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            localStorage.removeItem('cuju.gridSize');
            const button = document.getElementById('live-grid');
            const offered = !button.hidden;
            document.getElementById('view-menu-btn').click();
            await sleep(50);
            const listed = [...document.querySelectorAll('#view-drawing [role^="menuitem"]')]
                .some((node) => node.dataset.label === 'Grid of environments');
            document.getElementById('view-menu-btn').click();
            button.focus();
            button.click();
            await sleep(50);
            const panel = document.getElementById('env-grid');
            const tiles = () => [...panel.querySelectorAll('.env-tile')];
            const shown = !panel.hidden && tiles().length === 9
                && document.activeElement === tiles()[0]
                && tiles()[0].getAttribute('aria-current') === 'true'
                && panel.hasAttribute('data-prompt');
            for (let i = 0; i < 50 && !tiles().every((t) => t.dataset.step); i++) await sleep(100);
            const drawn = tiles().every((t) => t.dataset.step && /Environment \d+, \d+ to \d+/
                .test(t.getAttribute('aria-label')));
            const all = { offered, listed, shown, drawn };
            return Object.values(all).every(Boolean) || JSON.stringify(all);
        })()
    """)
    assert result is True, f'Grid of environments {result}'
    checks = 1
    focused = 'document.activeElement.dataset.environment'
    _key(client, 'ArrowRight', vk=39)
    assert client.evaluate(focused) == '1'
    _key(client, 'ArrowDown', vk=40)
    assert client.evaluate(focused) == '4'
    _key(client, 'End', vk=35)
    assert client.evaluate(focused) == '8'
    _key(client, 'PageDown', vk=34)
    # The last page holds the three environments that remain.
    assert client.evaluate(
        "document.querySelectorAll('#env-grid .env-tile').length === 3"
        " && /9 to 11 of 12/.test(document.getElementById('env-grid').textContent)"
    )
    checks += 1
    result = client.evaluate("""
        (async () => {
            const select = document.getElementById('env-grid-size');
            select.value = '4';
            select.dispatchEvent(new Event('change'));
            const four = document.querySelectorAll('#env-grid .env-tile').length === 4
                && localStorage.getItem('cuju.gridSize') === '4';
            select.value = '16';
            select.dispatchEvent(new Event('change'));
            const all = document.querySelectorAll('#env-grid .env-tile').length === 12;
            return (four && all) || JSON.stringify({ four, all });
        })()
    """)
    assert result is True, f'Grid sizes {result}'
    client.evaluate(
        'document.querySelector(\'#env-grid .env-tile[data-environment="10"]\').focus()'
    )
    _key(client, 'Enter', vk=13, text='\r')
    assert client.evaluate("document.getElementById('env-grid').hidden")
    _until(
        client,
        'cuju.source && cuju.source.header.provenance.environment === 10'
        ' && !cuju.source.live.ended',
        'The switch to environment 10',
    )
    checks += 1
    # Escape closes the grid and gives the focus back to its button.
    client.evaluate("document.getElementById('live-grid').focus()")
    client.evaluate("document.getElementById('live-grid').click()")
    assert client.evaluate(
        "document.activeElement.dataset.environment === '10'"
        " && document.activeElement.getAttribute('aria-current') === 'true'"
    )
    _key(client, 'Escape', vk=27)
    assert client.evaluate(
        "document.getElementById('env-grid').hidden"
        " && document.activeElement === document.getElementById('live-grid')"
    )
    client.evaluate('cuju.source.live.stop()')
    checks += 1
    return checks
