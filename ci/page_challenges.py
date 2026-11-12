# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks the Challenges page, the ways to it, its cards, pictures, teasers and labels.

ci/page_check.py runs reach_checks, card_checks and bench_checks with the other checks of the
page. Run alone, this file starts the mock server and Chrome itself and runs these checks with the
checks of a challenge's run in ci/page_check.py.

The tab of the top bar, the item of the narrow page menu, the address, an old address of Play
that names a challenge, the command palette and the guided tour each open the Challenges page.

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


def reach_checks(client):
    """Checks that the tab, the page menu, Home, the address, an old address of Play, the palette
    and the tour each open the Challenges page, that Play holds no challenges, and that the page
    fits a phone."""
    checks = _run(
        client,
        """
        cuju.showPage('home');
        const tab = document.querySelector('.menu [data-page="challenges"]');
        tab.click();
        const section = document.getElementById('page-challenges');
        await wait(() => section.querySelector('.challenge-item'));
        const symbol = tab.querySelector('use').getAttribute('href');
        const others = [...document.querySelectorAll('.menu [data-page] use')]
            .filter((use) => use.getAttribute('href') === symbol).length;
        const all = {
            page: cuju.page === 'challenges', shown: !section.hidden,
            hash: location.hash === '#page=challenges' || location.hash,
            title: document.title === 'Challenges · Cuju' || document.title,
            current: tab.getAttribute('aria-current') === 'page',
            symbol: (symbol === '#i-challenges' && others === 1
                && !!document.getElementById('i-challenges')) || symbol,
            label: tab.textContent.trim() === 'Challenges' || tab.textContent,
            heading: (section.querySelector('h1') || {}).textContent === 'Challenges',
        };
        return Object.values(all).every((v) => v === true) || all;
        """,
        'The tab opens the Challenges page',
    )
    checks += _run(
        client,
        """
        cuju.showPage('home');
        document.querySelector('#page-menu [data-page="challenges"]').click();
        const menu = cuju.page === 'challenges'
            && document.getElementById('page-menu-label').textContent === 'Challenges';
        cuju.showPage('home');
        await wait(() => document.querySelector('.home-actions'));
        const hero = [...document.querySelectorAll('.home-actions button')]
            .find((b) => b.textContent.trim() === 'Challenges');
        hero.click();
        const home = cuju.page === 'challenges';
        cuju.showPage('home');
        location.hash = '#page=challenges';
        const address = !!(await wait(() => cuju.page === 'challenges'));
        // The old address of Play that names a challenge opens the page at that card.
        cuju.showPage('home');
        location.hash = '#page=play&challenge=corner';
        const start = () => document.querySelector(
            '.challenge-item[data-id="corner"] [data-action="start"]');
        const old = !!(await wait(() => cuju.page === 'challenges'
            && document.activeElement === start()));
        const rewritten = location.hash === '#page=challenges' || location.hash;
        cuju.showPage('play');
        await wait(() => document.querySelector('#page-play .play-setup'));
        const play = !document.querySelector('#page-play .challenges, #page-play .challenge-item');
        const all = { menu, home, address, old, rewritten, play };
        return Object.values(all).every((v) => v === true) || all;
        """,
        'The menu, Home and the addresses open the Challenges page',
    )
    checks += _run(
        client,
        """
        const pick = async (query, title) => {
            cuju.palette.open(query);
            const found = await wait(() => {
                cuju.palette.render();
                const index = cuju.palette.shown.findIndex((a) => a.title === title);
                return index >= 0 ? index + 1 : null;
            });
            if (!found) {
                cuju.palette.close(false);
                return null;
            }
            const action = cuju.palette.shown[found - 1];
            cuju.palette.run(found - 1);
            return action;
        };
        cuju.showPage('home');
        const page = await pick('go to challenges', 'Go to Challenges');
        const went = !!page && !!(await wait(() => cuju.page === 'challenges'));
        cuju.showPage('home');
        const one = await pick('challenge corner', 'Challenge, Corner');
        const start = () => document.querySelector(
            '.challenge-item[data-id="corner"] [data-action="start"]');
        const focused = !!one && one.group === 'Challenges'
            && !!(await wait(() => cuju.page === 'challenges'
                && document.activeElement === start()));
        const all = { went, focused };
        return Object.values(all).every((v) => v === true) || all;
        """,
        'The palette opens the Challenges page and a challenge',
    )
    checks += _run(
        client,
        """
        const { TOUR_STEPS } = await import('./js/help/tour-core.js');
        const index = TOUR_STEPS.findIndex((step) => step.id === 'challenges');
        cuju.showPage('home');
        await cuju.tour.start(index);
        const found = !!(await wait(() => cuju.tour.state().target));
        const board = document.querySelector(
            '#page-challenges .challenge-item [data-action="board"]');
        const tryIt = [...document.querySelectorAll('#tour .tour-actions button')]
            .find((b) => b.getAttribute('aria-label') === 'Try it');
        const shown = !!tryIt && !tryIt.hidden;
        tryIt.click();
        const opened = !!(await wait(() => board.getAttribute('aria-expanded') === 'true'));
        const all = { found, page: cuju.page === 'challenges', shown, opened,
            open: cuju.tour.state().open, matches: !cuju.play || !cuju.play.game };
        cuju.tour.leave();
        if (board.getAttribute('aria-expanded') === 'true') board.click();
        // The tour ends from its last step, so a later start begins at the first step again.
        await cuju.tour.start(TOUR_STEPS.length - 1);
        await cuju.tour.next();
        all.ended = cuju.tour.state().resumeAt === 0 && !cuju.tour.state().open;
        localStorage.removeItem('cuju.tour');
        return Object.values(all).every((v) => v === true) || all;
        """,
        'The tour points at the Challenges page and Try it opens a leaderboard',
    )
    # The top bar holds every tab beside its other controls, with their names on a wide screen and
    # their symbols alone between a wide screen and a phone.
    for width in (1440, 1321, 1320, 761):
        client.call(
            'Emulation.setDeviceMetricsOverride',
            {'width': width, 'height': 800, 'deviceScaleFactor': 1, 'mobile': False},
        )
        try:
            checks += _run(
                client,
                """
                await new Promise((resolve) => setTimeout(resolve, 300));
                const bar = document.getElementById('topbar');
                const tabs = [...document.querySelectorAll('.menu [data-page]')];
                const actions = document.querySelector('#topbar .top-actions')
                    .getBoundingClientRect().left;
                const shown = tabs.filter((tab) => tab.getClientRects().length > 0);
                const inside = innerWidth <= 760 || (shown.length === tabs.length
                    && shown.every((tab) => tab.getBoundingClientRect().right <= actions + 1));
                const all = { fits: bar.scrollWidth <= bar.clientWidth + 1
                    || [bar.scrollWidth, bar.clientWidth], inside };
                return Object.values(all).every((v) => v === true) || all;
                """,
                f'The top bar fits {width} pixels',
            )
        finally:
            client.call('Emulation.clearDeviceMetricsOverride')
    client.call(
        'Emulation.setDeviceMetricsOverride',
        {'width': 375, 'height': 740, 'deviceScaleFactor': 1, 'mobile': True},
    )
    try:
        checks += _run(
            client,
            """
            cuju.showPage('home');
            await new Promise((resolve) => setTimeout(resolve, 300));
            const button = document.getElementById('page-menu-btn');
            const menu = button.getClientRects().length > 0;
            document.querySelector('#page-menu [data-page="challenges"]').click();
            const section = document.getElementById('page-challenges');
            await wait(() => section.querySelector('.challenge-item'));
            await new Promise((resolve) => setTimeout(resolve, 300));
            const wide = [...section.querySelectorAll(
                '.challenges, .challenge-item, .challenge-list, .challenge-bench')]
                .filter((node) => node.getBoundingClientRect().right > innerWidth + 1).length;
            const all = { menu, page: cuju.page === 'challenges',
                fits: section.scrollWidth <= section.clientWidth + 1 || section.scrollWidth,
                wide: wide === 0 || wide };
            return Object.values(all).every((v) => v === true) || all;
            """,
            'The Challenges page fits a phone',
        )
    finally:
        client.call('Emulation.clearDeviceMetricsOverride')
    return checks


def card_checks(client):
    """Checks the cards' pictures and names, then their teasers by pointer, focus and button."""
    checks = _run(
        client,
        """
        cuju.showPage('challenges');
        await wait(() => document.querySelectorAll('.challenge-item .challenge-media').length === 3
            && Object.keys(cuju.challengesPage.teaserFiles || {}).length);
        const ids = ['empty_goal_close', 'corner', 'one_on_one'];
        const text = (id, selector) => card(id).querySelector(selector).textContent;
        const named = ids.every((id) => {
            const heading = document.getElementById(card(id).getAttribute('aria-labelledby'));
            return heading && heading.textContent === text(id, 'h2')
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
                && b.getAttribute('aria-label') === `Play the preview of ${text(id, 'h2')}`;
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
        await cuju.challengesPage.show();
        const back = !!(await wait(() => card('corner').querySelector('img.challenge-still')));
        document.activeElement.blur();
        const kept = localStorage.getItem('cuju.muted') === 'true';
        return (drawn && muted && back && kept) || { drawn, muted, back, kept };
        """,
        'Card fallback and sound',
    )
    return checks


def bench_checks(client):
    """Checks the medal items of the cards, the board and the end card, and a benchmark of a test
    team and the built-in AI on one challenge, its progress, its table and its CSV."""
    checks = _run(
        client,
        """
        cuju.showPage('challenges');
        const panel = cuju.challengesPage;
        // A default name of another language, stored before, gives way to the page's own default.
        localStorage.setItem('cuju.challengeName', 'Jogador');
        panel.nameField.value = 'Jogador';
        panel.namesRead = false;
        await panel.show();
        const unnamed = panel.nameField.value === '' && panel.nameField.placeholder === 'Player'
            && localStorage.getItem('cuju.challengeName') === null
            && panel.personName() === 'Player';
        // The person of the run that the checks of page_check.py played.
        const person = (await cuju.challenges.board('one_on_one'))
            .find((entry) => entry.kind === 'person');
        panel.nameField.value = person ? person.name : 'Page check';
        await panel.show();
        await wait(() => card('empty_goal_close')
            && card('empty_goal_close').querySelector('.medal-items'));
        // The card's own items, apart from those of the line of a headless run on the card.
        const items = (id) => [...card(id).querySelectorAll(':scope > .medal-items .medal-item')];
        const words = items('empty_goal_close').map((li) => li.textContent.trim());
        const ordered = ['empty_goal_close', 'corner', 'one_on_one'].every((id) =>
            items(id).map((li) => li.dataset.medal).join() === 'gold,silver,bronze');
        const listed = card('one_on_one').querySelector('.medal-items')
            .getAttribute('aria-label') === 'Medals of One on one';
        const color = (id, medal) => getComputedStyle(card(id)
            .querySelector(`.medal-item.${medal} > svg`)).color;
        const metals = new Set(['gold', 'silver', 'bronze'].map((m) => color('corner', m)));
        const text = getComputedStyle(card('corner')).color;
        // The person's best run of One on one marks the item of its medal, and the headless run
        // of the built-in AI marks the item it reached on the line of the run.
        const mine = panel.find('one_on_one').board.mine;
        const reached = items('one_on_one').filter((li) => li.classList.contains('reached'));
        const marked = mine && mine.medal
            ? reached.length === 1 && reached[0].dataset.medal === mine.medal
                && /Your best/.test(reached[0].textContent)
            : reached.length === 0;
        const job = [...card('one_on_one')
            .querySelectorAll('.challenge-job .medal-item.reached')];
        const best = marked && !!mine && job.length === 1 && job[0].dataset.medal === 'silver'
            && /Reached/.test(job[0].textContent)
            && items('corner').every((li) => !li.classList.contains('reached'));
        const toggle = card('one_on_one').querySelector('[data-action="board"]');
        if (toggle.getAttribute('aria-expanded') !== 'true') toggle.click();
        const marks = await wait(() => card('one_on_one')
            .querySelectorAll('.challenge-board .medal-mark').length);
        const all = {
            words: words.join('|') === 'Gold, a goal within 3 seconds in all 5 attempts'
                + '|Silver, a goal within 3 seconds in 4 attempts or more'
                + '|Bronze, a goal within 3 seconds in 3 attempts or more' || words.join('|'),
            ordered, listed, colored: (metals.size === 3 && !metals.has(text)) || [...metals],
            best: best || { mine, job: job.map((li) => li.textContent) }, marks: !!marks, unnamed,
        };
        toggle.click();
        return Object.values(all).every((v) => v === true) || all;
        """,
        'Medal items',
    )
    checks += _run(
        client,
        """
        const { api } = await import('./js/core/api.js');
        const panel = cuju.challengesPage;
        const source = 'def agent(obs):\\n    return [12]\\n';
        const team = await api.uploadTeam('Bench bot', 'main.py', source, '11v11');
        try {
            await panel.show(await api.teams());
            const view = document.querySelector('.challenge-bench');
            const box = (name, value) =>
                view.querySelector(`input[name="${name}"][value="${value}"]`);
            box('bench-team', 'builtin').checked = true;
            box('bench-team', team.id).checked = true;
            const every = view.querySelector('.bench-all');
            every.checked = false;
            every.dispatchEvent(new Event('change', { bubbles: true }));
            box('bench-challenge', 'one_on_one').checked = true;
            view.querySelector('[data-action="bench"]').click();
            const done = await wait(() => panel.bench.job && panel.bench.job.state === 'done'
                && /finished/.test(view.querySelector('.bench-status').textContent), 20000);
            const rows = [...view.querySelectorAll('.bench-table tbody tr')];
            const cells = rows.map((row) => row.querySelector('td[data-challenge="one_on_one"]'));
            const job = panel.bench.job;
            const csv = cuju.challenges.benchCsv().trim().split('\\n');
            const all = {
                done: !!done,
                chosen: job && job.challenges.join() === 'one_on_one'
                    && job.teams.join() === `builtin,${team.id}`,
                rows: rows.map((row) => row.dataset.team).join() === `builtin,${team.id}`,
                cells: cells.every((cell) => cell && cell.dataset.state === 'done'
                    && !!cell.querySelector('.medal-mark')),
                named: !!rows[1] && rows[1].querySelector('th').textContent === 'Bench bot',
                progress: view.querySelector('.bench-progress').value === 1,
                csv: (csv.length === 3 && csv[0].startsWith('model,team,one_on_one value')
                    && csv[2].startsWith(`Bench bot,${team.id},`)) || csv,
                exports: !view.querySelector('.bench-exports').hidden,
                board: (await cuju.challenges.board('one_on_one'))
                    .some((entry) => entry.team === team.id && entry.kind === 'agent'),
            };
            return Object.values(all).every((v) => v === true) || all;
        } finally {
            await api.deleteTeam(team.id);
            await panel.show(await api.teams());
        }
        """,
        'Benchmark of a test team',
    )
    return checks


def model_checks(client):
    """Checks Play it yourself and Run a model on a card, a model's run on the card with its
    progress, Cancel run, result and medal items, its board entry marked as a model, and the
    ways to the benchmark and the achievements at the top of the page."""
    checks = _run(
        client,
        """
        cuju.showPage('challenges');
        await wait(() => card('corner') && card('corner').querySelector('[data-action="model"]'));
        const own = card('corner').querySelector('[data-action="start"]');
        const button = card('corner').querySelector('[data-action="model"]');
        const part = card('corner').querySelector('.challenge-model');
        const closed = button.getAttribute('aria-expanded') === 'false' && part.hidden
            && button.getAttribute('aria-controls') === part.id;
        button.click();
        const select = part.querySelector('select[data-role="team"]');
        const opened = button.getAttribute('aria-expanded') === 'true' && !part.hidden
            && document.activeElement === select;
        const models = [...select.options].map((option) => option.value);
        const attempts = [...part.querySelectorAll('select[data-role="attempts"] option')]
            .map((option) => option.textContent).join('|');
        const all = {
            own: (own.textContent.trim() === 'Play it yourself'
                && own.getAttribute('aria-label') === 'Play it yourself, Corner'
                && !!own.querySelector('svg use')) || own.outerHTML.slice(0, 160),
            model: (button.textContent.trim() === 'Run a model'
                && button.getAttribute('aria-label') === 'Run a model, Corner'
                && !!button.querySelector('svg use')) || button.outerHTML.slice(0, 160),
            closed, opened, builtin: models[0] === 'builtin' || models.join(),
            attempts: attempts === 'Full run, 5 attempts|Practice, one attempt' || attempts,
            named: part.getAttribute('role') === 'group'
                && document.getElementById(part.getAttribute('aria-labelledby')).textContent
                    === 'Run a model',
        };
        return Object.values(all).every((v) => v === true) || all;
        """,
        'Play it yourself and Run a model on a card',
    )
    checks += _run(
        client,
        """
        const part = card('corner').querySelector('.challenge-model');
        part.querySelector('select[data-role="team"]').value = 'builtin';
        part.querySelector('select[data-role="attempts"]').value = 'full';
        part.querySelector('[data-action="headless"]').click();
        const line = () => card('corner').querySelector('.challenge-job');
        const running = !!(await wait(() => !line().hidden
            && line().querySelector('progress.bench-progress')
            && line().querySelector('button[aria-label="Cancel run"]')));
        const done = !!(await wait(() => /finished Corner/.test(line().innerText), 20000));
        const medals = !!line().querySelector('.medal-items');
        const others = [...document.querySelectorAll('.challenge-item:not([data-id="corner"]) '
            + '.challenge-job')].every((other) => !/Corner/.test(other.innerText));
        const toggle = card('corner').querySelector('[data-action="board"]');
        if (toggle.getAttribute('aria-expanded') !== 'true') toggle.click();
        const marked = !!(await wait(() => [...card('corner')
            .querySelectorAll('.challenge-board tr.agent .challenge-kind')]
            .some((mark) => mark.classList.contains('agent'))));
        toggle.click();
        const all = { running, done, medals, others, marked };
        return Object.values(all).every((v) => v === true) || all;
        """,
        'A model runs on its card and reaches the board as a model',
    )
    checks += _run(
        client,
        """
        const part = card('corner').querySelector('.challenge-model');
        part.querySelector('[data-action="headless"]').click();
        const line = () => card('corner').querySelector('.challenge-job');
        const cancel = await wait(() => line().querySelector('button[aria-label="Cancel run"]'));
        if (cancel) cancel.click();
        const stopped = !!(await wait(() => !line().querySelector('progress.bench-progress')
            && /stopped|finished/.test(line().innerText)));
        const button = card('corner').querySelector('[data-action="model"]');
        button.click();
        const shut = part.hidden && button.getAttribute('aria-expanded') === 'false';
        const all = { cancel: !!cancel, stopped, shut };
        return Object.values(all).every((v) => v === true) || all;
        """,
        'Cancel run stops a model on its card',
    )
    checks += _run(
        client,
        """
        const go = (action) => document.querySelector(`[data-action="${action}"]`);
        const bench = go('jump-bench');
        bench.click();
        const toBench = document.activeElement === document.getElementById('challenge-bench-title');
        go('jump-achievements').click();
        const toAchievements = document.activeElement
            === document.getElementById('achievements-title');
        const all = {
            label: bench.textContent.trim() === 'Benchmark several models' || bench.textContent,
            toBench, toAchievements,
        };
        return Object.values(all).every((v) => v === true) || all;
        """,
        'The top of the page leads to the benchmark and the achievements',
    )
    # A team that played with players out says so on the line of its run and on the board.
    checks += _run(
        client,
        """
        const panel = cuju.challengesPage;
        const c = panel.find('corner');
        const done = panel.jobs.find((job) => job.challenge === 'corner' && job.result);
        const job = { ...done, id: 'out', state: 'done',
            result: { ...done.result, playing: [1, 4] } };
        panel.jobs = [job, ...panel.jobs];
        panel.renderJob();
        const line = card('corner').querySelector('.challenge-job').innerText;
        const board = document.createElement('div');
        panel.fillBoard(c, board, [{ rank: 1, kind: 'agent', name: 'Four', team: 'four',
            value: 3, seconds: 4, medal: 'bronze', time: 1, playing: [1, 4] }]);
        panel.jobs = panel.jobs.filter((entry) => entry.id !== 'out');
        panel.renderJob();
        const words = 'Played with 1 of its 4 players, the others out.';
        const all = { line: line.includes(words) || line,
            board: board.querySelector('.challenge-playing').textContent === words };
        return Object.values(all).every((v) => v === true) || all;
        """,
        'A run with players out says so',
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
            checks = reach_checks(client)
            checks += card_checks(client)
            checks += page.challenge_checks(client)
            checks += bench_checks(client)
            checks += model_checks(client)
            assert client.evaluate("localStorage.getItem('cuju.muted')") == 'true'
            assert not client.evaluate('!!document.pointerLockElement')
            assert not client.errors, client.errors
            print(f'PASS. {checks} challenge, medal and benchmark checks. Chrome stayed muted.')
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
