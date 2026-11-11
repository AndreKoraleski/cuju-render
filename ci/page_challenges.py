# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks the cards of the challenges on the Play page, their pictures, teasers and labels.

ci/page_check.py runs card_checks with the other checks of the page. Run alone, this file starts
the mock server and Chrome itself and runs these checks with the checks of a challenge's run in
ci/page_check.py.

The mock server's catalog holds three challenges of three kinds, and the page reads their stills
and teasers from the shipped folder of the page. The checks rest the pointer on a card and see its
teaser play and stop, move the keyboard focus into a card and out of it, see one teaser play at a
time, and under reduced motion see the teasers keep still until the play button asks.

Usage:
    python ci/page_challenges.py [--port 8790] [--debug-port 8791] [--chrome google-chrome]
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WAIT = """
    const wait = async (test, ms = 15000) => {
        const end = performance.now() + ms;
        while (performance.now() < end) {
            let value = null;
            try {
                value = await test();
            } catch {
                value = null;
            }
            if (value) {
                return value;
            }
            await new Promise((resolve) => setTimeout(resolve, 50));
        }
        return null;
    };
    const card = (id) => document.querySelector(`.challenge-item[data-id="${id}"]`);
    const media = (id) => card(id).querySelector('.challenge-media');
    const video = (id) => card(id).querySelector('video');
    const playing = (id) => {
        const v = video(id);
        return !!v && !v.paused && v.currentTime > 0 && media(id).dataset.playing === 'true';
    };
    const still = (id) => {
        const v = video(id);
        return (!v || v.paused) && media(id).dataset.playing === 'false';
    };
    const pressed = (id) => card(id).querySelector('[data-action="teaser"]')
        .getAttribute('aria-pressed');
"""


def _run(client, body, name):
    result = client.evaluate(f'(async () => {{ {WAIT} {body} }})()')
    assert result is True, f'{name} {result}'
    return 1


def _point(client, selector):
    """Returns the middle of an element in the viewport, scrolled into view."""
    return client.evaluate(
        f"""(() => {{
            const node = document.querySelector({json.dumps(selector)});
            node.scrollIntoView({{ block: 'center' }});
            const r = node.getBoundingClientRect();
            return [r.left + r.width / 2, r.top + r.height / 2];
        }})()"""
    )


def _move(client, x, y):
    client.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x, 'y': y})


def _key(client, key, code):
    for kind in ('keyDown', 'keyUp'):
        client.call('Input.dispatchKeyEvent', {'type': kind, 'key': key, 'code': code})


def _focus(client, identifier, action):
    client.evaluate(
        f'document.querySelector(\'.challenge-item[data-id="{identifier}"] '
        f'[data-action="{action}"]\').focus()'
    )


def _motion(client, value):
    client.call(
        'Emulation.setEmulatedMedia',
        {'features': [{'name': 'prefers-reduced-motion', 'value': value}]},
    )


def card_checks(client):
    """Checks the cards' pictures and names, then their teasers by pointer, focus and button."""
    checks = _run(
        client,
        """
        cuju.showPage('play');
        await wait(() => document.querySelectorAll('.challenge-item .challenge-media').length === 3
            && Object.keys(cuju.play.challenges.teaserFiles || {}).length);
        const ids = ['empty_goal_close', 'corner', 'one_on_one'];
        const text = (id, selector) => card(id).querySelector(selector).textContent;
        const named = ids.every((id) => {
            const heading = document.getElementById(card(id).getAttribute('aria-labelledby'));
            return heading && heading.textContent === text(id, 'h3')
                && !/Gold|Silver|Bronze|Easy|Hard/.test(heading.textContent);
        });
        const kinds = ids.map((id) => text(id, '.challenge-chip')).join();
        const levels = ids.map((id) => text(id, '.challenge-difficulty .sr-only')).join();
        // The stills load lazily, as each card comes into view.
        const lazy = ids.every((id) => card(id).querySelector('img.challenge-still')
            .getAttribute('loading') === 'lazy');
        for (const id of ids) {
            card(id).scrollIntoView({ block: 'center' });
            await wait(() => card(id).querySelector('img.challenge-still').complete);
        }
        const stills = await wait(() => ids.every((id) => {
            const img = card(id).querySelector('img.challenge-still');
            return img && img.complete && img.naturalWidth === 480 && img.alt === ''
                && media(id).dataset.picture === 'still';
        }));
        const top = (id) => getComputedStyle(card(id)).borderTopColor;
        const buttons = ids.every((id) => {
            const b = card(id).querySelector('[data-action="teaser"]');
            return b && !b.hidden && pressed(id) === 'false'
                && b.getAttribute('aria-label') === `Play the preview of ${text(id, 'h3')}`;
        });
        const all = {
            named, lazy, stills: !!stills, buttons, styled: top('corner') !== top('one_on_one'),
            kinds: kinds === 'Finishing,Set piece,Duel' || kinds,
            levels: levels === 'Difficulty, Easy,Difficulty, Hard,Difficulty, Medium' || levels,
            none: ids.every((id) => !video(id)),
        };
        return Object.values(all).every((v) => v === true) || all;
        """,
        'Challenge cards',
    )
    # The pointer rests on a card, then leaves it.
    _move(client, *_point(client, '.challenge-item[data-id="corner"] .challenge-media'))
    checks += _run(
        client,
        """
        const played = !!(await wait(() => playing('corner')));
        const v = video('corner');
        const quiet = v && v.muted && v.volume === 0 && v.getAttribute('aria-hidden') === 'true'
            && v.loop && v.hasAttribute('playsinline') && v.tabIndex === -1;
        return (played && quiet) || { played, quiet };
        """,
        'Teaser on hover',
    )
    _move(client, 2, 2)
    checks += _run(
        client,
        """
        const stopped = !!(await wait(() => still('corner')));
        return stopped || { stopped, playing: media('corner').dataset.playing };
        """,
        'Teaser stops on leave',
    )
    # The keyboard moves the focus into a card, and one teaser plays at a time. A key press makes
    # the next focus keyboard focus, as the Tab key would.
    _key(client, 'Shift', 'ShiftLeft')
    _focus(client, 'one_on_one', 'start')
    checks += _run(
        client,
        """
        const focused = !!(await wait(() => playing('one_on_one')));
        const active = document.activeElement && document.activeElement.outerHTML.slice(0, 80);
        return focused || { focused, active };
        """,
        'Teaser on keyboard focus',
    )
    _move(client, *_point(client, '.challenge-item[data-id="empty_goal_close"] .challenge-media'))
    checks += _run(
        client,
        """
        const other = !!(await wait(() => playing('empty_goal_close')));
        const one = still('one_on_one') && still('corner');
        const count = [...document.querySelectorAll('.challenge-item video')]
            .filter((v) => !v.paused).length;
        return (other && one && count === 1) || { other, one, count };
        """,
        'One teaser at a time',
    )
    _move(client, 2, 2)
    _key(client, 'Shift', 'ShiftLeft')
    _focus(client, 'one_on_one', 'start')
    client.evaluate("document.querySelector('.challenge-name').focus()")
    checks += _run(
        client,
        """
        return !!(await wait(() => still('empty_goal_close') && still('one_on_one')));
        """,
        'Teasers stop on blur',
    )
    # Reduced motion keeps every teaser still until the play button asks for it.
    _motion(client, 'reduce')
    checks += _run(client, 'return !!(await wait(() => cuju.reducedMotion));', 'Reduced motion')
    _move(client, *_point(client, '.challenge-item[data-id="corner"] .challenge-media'))
    _key(client, 'Shift', 'ShiftLeft')
    _focus(client, 'corner', 'start')
    checks += _run(
        client,
        """
        await new Promise((resolve) => setTimeout(resolve, 800));
        const kept = still('corner');
        const button = card('corner').querySelector('[data-action="teaser"]');
        button.click();
        const asked = !!(await wait(() => playing('corner'))) && pressed('corner') === 'true';
        button.click();
        const stopped = !!(await wait(() => still('corner'))) && pressed('corner') === 'false';
        return (kept && asked && stopped) || { kept, asked, stopped };
        """,
        'Teasers under reduced motion',
    )
    _move(client, 2, 2)
    _motion(client, 'no-preference')
    # A still that fails to load leaves the drawing of the card's kind, and nothing ever sounds.
    checks += _run(
        client,
        """
        await wait(() => !cuju.reducedMotion);
        const img = card('corner').querySelector('img.challenge-still');
        img.dispatchEvent(new Event('error'));
        const drawing = card('corner').querySelector('.challenge-drawn');
        const drawn = media('corner').dataset.picture === 'drawn'
            && getComputedStyle(drawing).display !== 'none';
        const muted = [...document.querySelectorAll('video')].every((v) => v.muted || v.paused);
        await cuju.play.challenges.show();
        const back = !!(await wait(() => card('corner').querySelector('img.challenge-still')));
        document.activeElement.blur();
        const kept = localStorage.getItem('cuju.muted') === 'true';
        return (drawn && muted && back && kept) || { drawn, muted, back, kept };
        """,
        'Card fallback and sound',
    )
    return checks


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import page_check as page

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--port', type=int, default=8790)
    parser.add_argument('--debug-port', type=int, default=8791)
    parser.add_argument('--chrome', default='google-chrome')
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    processes = []
    client = None
    checks = 0
    try:
        with tempfile.TemporaryDirectory(
            prefix='cuju-page-challenges-', ignore_cleanup_errors=True
        ) as profile:
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(root / 'ci/mock_server.py'),
                        '--port',
                        str(options.port),
                        '--short',
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            page.wait_json(f'http://127.0.0.1:{options.port}/api/scenarios')
            processes.append(
                subprocess.Popen(
                    [
                        options.chrome,
                        '--headless=new',
                        '--mute-audio',
                        # The checks read the English page, whatever the language of the machine.
                        '--lang=en-US',
                        '--no-sandbox',
                        '--disable-background-networking',
                        '--proxy-server=http://127.0.0.1:9',
                        '--proxy-bypass-list=127.0.0.1',
                        '--no-first-run',
                        f'--remote-debugging-port={options.debug_port}',
                        f'--user-data-dir={profile}',
                        '--window-size=800,600',
                        'about:blank',
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env={**os.environ, 'XDG_CONFIG_HOME': profile, 'XDG_DATA_HOME': profile},
                )
            )
            debug = page.debugging_port(profile, options.debug_port)
            targets = page.wait_json(f'http://127.0.0.1:{debug}/json')
            target = next(item for item in targets if item['type'] == 'page')
            client = page.CDP(target['webSocketDebuggerUrl'])
            client.call('Runtime.enable')
            client.call('Page.enable')
            client.call(
                'Page.addScriptToEvaluateOnNewDocument',
                {
                    'source': """
                localStorage.setItem('cuju.muted', 'true');
                localStorage.setItem('cuju.quality', '"low"');
                localStorage.setItem('cuju.tips', '{"off": true}');
                if (localStorage.getItem('cuju.installOffer') === null) {
                    localStorage.setItem('cuju.installOffer', '{"dismissed": true}');
                }
                Element.prototype.requestPointerLock = function () {
                    throw new Error('Pointer capture refused by the page check.');
                };
            """
                },
            )
            client.call('Page.navigate', {'url': f'http://127.0.0.1:{options.port}/'})
            for _ in range(150):
                if client.evaluate('!!(window.cuju && window.cuju.menus)'):
                    break
                time.sleep(0.2)
            checks = card_checks(client)
            checks += page.challenge_checks(client)
            assert client.evaluate("localStorage.getItem('cuju.muted')") == 'true'
            assert not client.evaluate('!!document.pointerLockElement')
            assert not client.errors, client.errors
            print(f'PASS. {checks} challenge card and run checks. Chrome stayed muted.')
    except Exception as error:
        detail = json.dumps(client.errors)[:2000] if client else ''
        print(f'FAIL. {checks} checks passed. {error} {detail}', file=sys.stderr)
        return 1
    finally:
        if client:
            client.socket.close()
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    return 0


if __name__ == '__main__':
    sys.exit(main())
