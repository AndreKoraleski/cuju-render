# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks the page's structure and keyboard paths, the tour that leaves the focus free, the values
of the timeline, the single keys on a focused button, the skip link and the page titles.

ci/page_check.py runs a11y_checks with the other checks of the page.
"""

WAIT = """
    const wait = async (test, tries = 100) => {
        for (let i = 0; i < tries; i++) {
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
"""


def _run(client, body, name):
    result = client.evaluate(f'(async () => {{ {WAIT} {body} }})()')
    assert result is True, f'{name} {result}'
    return 1


def _key(client, key, code, shift=False):
    for kind in ('keyDown', 'keyUp'):
        event = {'type': kind, 'key': key, 'code': code, 'modifiers': 8 if shift else 0}
        if kind == 'keyDown' and (len(key) == 1 or key == 'Enter'):
            event['text'] = '\r' if key == 'Enter' else key
            event['windowsVirtualKeyCode'] = 13 if key == 'Enter' else ord(key.upper())
        client.call('Input.dispatchKeyEvent', event)


def a11y_checks(client):
    """Runs every check of this file and returns how many passed."""
    count = 0
    # The tour's card leaves the focus free, so Try it reaches its control from the keyboard.
    count += _run(
        client,
        """
        localStorage.removeItem('cuju.tour');
        await cuju.tour.start(9);
        await wait(() => cuju.tour.state().target);
        const card = document.getElementById('tour');
        window.__tryIt = [...card.querySelectorAll('.tour-actions button')]
            .find((b) => b.getAttribute('aria-label') === 'Try it');
        window.__tryIt.focus();
        const free = card.getAttribute('aria-modal') === 'false';
        return (free && document.activeElement === window.__tryIt)
            || JSON.stringify({ modal: card.getAttribute('aria-modal'),
                focus: document.activeElement.textContent });
        """,
        'The tour card stays non-modal',
    )
    _key(client, 'Enter', 'Enter')
    count += _run(
        client,
        """
        // Try it on the Settings step opens the panel, and the focus moves into it.
        const panel = document.getElementById('settings');
        const moved = await wait(() => panel.classList.contains('open')
            && panel.contains(document.activeElement), 20);
        delete window.__tryIt;
        return !!moved || JSON.stringify({ open: panel.classList.contains('open'),
            focus: document.activeElement.id || document.activeElement.textContent });
        """,
        'Try it opens the control and moves the focus into it',
    )
    _key(client, 'Escape', 'Escape')
    count += _run(
        client,
        """
        const panel = document.getElementById('settings');
        const closed = await wait(() => !panel.classList.contains('open'), 20);
        const all = { closed: !!closed, tour: cuju.tour.state().open,
            focus: document.activeElement === document.getElementById('open-settings') };
        cuju.tour.leave();
        return Object.values(all).every(Boolean) || JSON.stringify(all);
        """,
        'Esc closes what Try it opened and keeps the tour',
    )
    # The timeline says its value as a slider does.
    count += _run(
        client,
        """
        await cuju.samples.add(['sample-5v5']);
        await cuju.openMatch('sample-5v5');
        cuju.director.stop(true);
        cuju.act('pause');
        cuju.timeline.seek(cuju.timeline.first + 83 * cuju.timeline.sps);
        const bar = document.getElementById('timeline');
        const text = await wait(() => /^1:23 of \\d+:\\d\\d$/
            .test(bar.getAttribute('aria-valuetext')) && bar.getAttribute('aria-valuetext'));
        const all = {
            text, now: bar.getAttribute('aria-valuenow') === '83',
            min: bar.getAttribute('aria-valuemin') === '0',
            max: Number(bar.getAttribute('aria-valuemax')) > 83,
            title: document.title.endsWith(' · Cuju') && document.title !== 'Watch · Cuju',
        };
        return Object.values(all).every(Boolean) || JSON.stringify(all);
        """,
        'The timeline values',
    )
    # A single key on a focused button or link reaches the page, Enter stays with the button.
    client.evaluate("""
        cuju.showPage('recordings');
        document.querySelector('.menu [data-page="play"]').focus();
    """)
    _key(client, 'h', 'KeyH')
    count += _run(
        client,
        """
        const help = await wait(() => cuju.page === 'help', 20);
        cuju.showPage('recordings');
        document.querySelector('.menu [data-page="teams"]').focus();
        return !!help || JSON.stringify({ page: cuju.page });
        """,
        'H on a focused button opens Help',
    )
    _key(client, '?', 'Slash', shift=True)
    count += _run(
        client,
        """
        const help = await wait(() => cuju.page === 'help', 20);
        cuju.showPage('watch');
        cuju.act('pause');
        document.getElementById('btn-pause').focus();
        window.__tv = cuju.tvMode;
        return !!help || JSON.stringify({ page: cuju.page });
        """,
        'The question mark on a focused button opens Help',
    )
    _key(client, 't', 'KeyT')
    count += _run(
        client,
        """
        const toggled = await wait(() => cuju.tvMode !== window.__tv, 20);
        cuju.setTvMode(window.__tv);
        delete window.__tv;
        cuju.act('pause');
        document.getElementById('btn-play').focus();
        return !!toggled || JSON.stringify({ tv: cuju.tvMode });
        """,
        'T on a focused button of Watch toggles broadcast mode',
    )
    _key(client, 'Enter', 'Enter')
    count += _run(
        client,
        """
        // Enter clicks the button once, and the keys of Watch leave it to the button.
        const playing = await wait(() => cuju.timeline.playing, 20);
        cuju.act('pause');
        const all = { playing: !!playing, page: cuju.page === 'watch',
            muted: localStorage.getItem('cuju.muted') === 'true' };
        return Object.values(all).every(Boolean) || JSON.stringify(all);
        """,
        'Enter on a focused button stays with the button',
    )
    # The skip link keeps the address of the page and moves the focus into it.
    count += _run(
        client,
        """
        cuju.showPage('recordings');
        await wait(() => location.hash === '#page=recordings');
        const skip = document.querySelector('.skip-link');
        skip.focus();
        skip.click();
        const pages = document.getElementById('pages');
        const all = {
            hash: location.hash === '#page=recordings', focus: document.activeElement === pages,
            label: pages.getAttribute('aria-label') === 'Recordings',
            title: document.title === 'Recordings · Cuju',
            heading: document.getElementById('page-name').textContent === 'Recordings'
                && !document.getElementById('page-name').hidden,
        };
        cuju.showPage('help');
        all.help = document.title === 'Help · Cuju';
        cuju.showPage('home');
        all.home = document.title === 'Cuju' && document.getElementById('page-name').hidden
            && !!document.querySelector('#page-home h1');
        return Object.values(all).every(Boolean) || JSON.stringify(all);
        """,
        'The skip link, titles and headings',
    )
    # A page lesson done without its panel, as the steps of cuju render tutorial do, is reported.
    count += _run(
        client,
        """
        await cuju.tutorial.reset();
        cuju.showPage('watch');
        const before = cuju.tutorial.state().done.includes('make_photo');
        await wait(() => cuju.photo);
        cuju.photo.open();
        await cuju.photo.capture({ width: 64, height: 36 });
        cuju.photo.close();
        const done = await wait(() => cuju.tutorial.state().done.includes('make_photo'));
        const server = await wait(async () => (await (await fetch('/api/help/tutorial')).json())
            .page.includes('make_photo'));
        const all = { before: !before, done: !!done, server: !!server,
            panel: document.getElementById('lesson-panel').hidden };
        await cuju.tutorial.reset();
        return Object.values(all).every(Boolean) || JSON.stringify(all);
        """,
        'A page lesson done without its panel',
    )
    return count
