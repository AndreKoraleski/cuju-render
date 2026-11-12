# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the team lists of the Matches page and the filters of its requests.

The module belongs to ci/page_check.py. The checks register teams in the mock server, one of
eleven, one with a long name and one whose name holds letters outside ASCII among those of five,
and request matches between them and the built-in AI. They then use the Team filter and the lists
of a new match by mouse and by keyboard, at the width of a desktop and of a phone. They see that a
team drawn for a waiting match stays out of the filters, that the filter lists the teams as the
lists of a new match do and finds a team by a typed word whatever its case and accents, that a menu
follows its button while the page scrolls, that a random side counts the teams it can draw, that
renamed, removed and new teams show the same in the filter and in the list, and that the team
cards and names fit a phone. They delete their teams at the end and leave the page as they found
it.
"""

UNTIL = """
    const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const until = async (test, ms = 10000) => {
        const end = performance.now() + ms;
        while (performance.now() < end) {
            const value = await test();
            if (value) {
                return value;
            }
            await wait(50);
        }
        return test();
    };
    const page = cuju.matches;
    const openItems = () => [...document.querySelectorAll('.dd-panel.open [role^="menuitem"]')];
    const label = (el) => el && (el.dataset.label || el.textContent);
    // The value of a team in the Team filter.
    const value = (team) => `team:${team.id}`;
"""


def run(client, body):
    """Runs the body of an async function after the shared helpers and returns its value."""
    return client.evaluate(f'(async () => {{ {UNTIL} {body} }})()')


def press(client, key, code='', text=None):
    for kind in ('keyDown', 'keyUp'):
        event = {'type': kind, 'key': key, 'code': code}
        if text and kind == 'keyDown':
            event['text'] = text
        client.call('Input.dispatchKeyEvent', event)


def type_text(client, text):
    """Types the letters one by one, as a person types them within the pause of a search."""
    for letter in text:
        press(client, letter, '', letter)


def click(client, expression):
    """Clicks the middle of the start of an element with the mouse, after scrolling it into view."""
    x, y = client.evaluate(f"""
        (() => {{
            const el = {expression};
            el.scrollIntoView({{ block: 'nearest' }});
            const r = el.getBoundingClientRect();
            return [r.x + Math.min(r.width / 2, 40), r.y + r.height / 2];
        }})()
    """)
    for kind in ('mouseMoved', 'mousePressed', 'mouseReleased'):
        client.call(
            'Input.dispatchMouseEvent',
            {'type': kind, 'x': x, 'y': y, 'button': 'left', 'clickCount': 1},
        )


FILTER = 'cuju.matches.teamFilter.enhanced.button'


def setup(client):
    """Registers the teams, requests the matches, waits for them and opens the Matches page."""
    result = run(
        client,
        """
        const { api } = await import('./js/core/api.js');
        const source = 'def agent(obs):\\n    return [0]\\n';
        const add = (name, format) => api.uploadTeam(name, 'main.py', source, format);
        const teams = {
            five: await add('Filter Five', '5v5'),
            accent: await add('Équipe São Ñandú', '5v5'),
            long: await add(
                'The Extraordinarily Long Named Football Club of the Northern Valley', '5v5'),
            eleven: await add('Filter Eleven', '11v11'),
            three: await add('Filter Three', '5v5'),
            hidden: await add('Hidden Draw', '5v5'),
        };
        window.matchesCheck = { teams, poll: page.poll };
        const before = new Set((await api.requests()).map((r) => r.id));
        for (const [left, right, scenario] of [
            [teams.five.id, 'builtin', '5_vs_5'],
            [teams.accent.id, teams.long.id, '5_vs_5'],
            [teams.eleven.id, 'builtin', '11_vs_11_kaggle'],
        ]) {
            await api.requestMatch({ left, right, scenario, seed: 3 });
        }
        const done = await until(async () => {
            const list = (await api.requests()).filter((r) => !before.has(r.id));
            return list.length === 3 && list.every((r) => r.state === 'done');
        }, 120000);
        cuju.showPage('matches');
        await page.refresh();
        page.filters.team = 'all';
        page.renderQueue();
        return done || 'the requested matches did not finish';
    """,
    )
    assert result is True, f'Matches page setup {result}'


def filter_checks(client):
    """Uses the Team filter by mouse and by keyboard beside a waiting match drawn at random."""
    prepared = run(
        client,
        """
        const { teams } = window.matchesCheck;
        // The checks hold the list still, and the server names the drawn team and scenario of a
        // waiting match at once, as the mock does.
        page.poll = async () => {};
        const shown = page.requests.find((r) => r.left === teams.five.id);
        const draw = { sides: [true, false], scenario: true, pool: null, same_team: false };
        // A drawn match cancelled before it started keeps its draw unseen as well.
        page.requests = [{
            ...shown, id: 'r-filter-draw', state: 'queued', progress: 0, match: null,
            left: teams.hidden.id, right: teams.five.id, scenario: 'academy_corner', draw,
        }, {
            ...shown, id: 'r-filter-cancelled', state: 'failed', progress: 0, match: null,
            error: 'cancelled', error_id: 'server.requests.cancelled', started: null,
            left: teams.hidden.id, right: 'builtin', scenario: 'academy_corner', draw,
        }, ...page.requests];
        page.renderQueue();
        const cancelled = page.queueHost.querySelector('.req-card[data-id="r-filter-cancelled"]');
        return !!page.queueHost.querySelector('.req-card[data-id="r-filter-draw"]')
            && !!cancelled && cancelled.textContent.includes('Random team')
            && !cancelled.textContent.includes('Hidden Draw');
    """,
    )
    assert prepared, 'Waiting drawn match shows'
    click(client, FILTER)
    result = run(
        client,
        """
        const { teams } = window.matchesCheck;
        const items = openItems();
        const labels = items.map(label);
        const hints = Object.fromEntries(items.map((el) => [label(el),
            el.querySelector('.dd-hint') ? el.querySelector('.dd-hint').textContent : null]));
        // The order of the registry, the order of the team lists of a new match, and the teams
        // that earlier checks removed after them.
        const registry = page.teams.map((x) => x.name);
        const places = labels.slice(1).map((name) => registry.indexOf(name));
        const gone = places.indexOf(-1);
        const order = gone < 0 ? places : places.slice(0, gone);
        return {
            open: items.length > 1 && labels[0] === 'Every team',
            builtinFirst: labels[1] === 'GRF\\'s built-in AI',
            ordered: order.every((at, i) => i === 0 || at > order[i - 1])
                && (gone < 0 || places.slice(gone).every((at) => at < 0)),
            named: ['Filter Five', 'Équipe São Ñandú', 'Filter Eleven']
                .every((name) => labels.includes(name)),
            hidden: !labels.includes('Hidden Draw')
                && ![...page.teamFilter.options].some((o) => o.value === value(teams.hidden)),
            scenario: ![...page.scenarioFilter.options]
                .some((o) => o.value === 'scenario:academy_corner'),
            hint: hints['Filter Five'] === '5 against 5, submission, 1 player'
                && hints['Filter Eleven'] === '11 against 11, submission, 1 player',
            labels,
        };
    """,
    )
    labels = result.pop('labels')
    assert all(result.values()), f'Team filter lists {result} {labels}'
    # Typing in the menu that the mouse opened finds a team without its accents.
    type_text(client, 'equ')
    found = run(client, 'return label(document.activeElement);')
    assert found == 'Équipe São Ñandú', f'Typed equ in the Team filter {found}'
    press(client, 'Enter', 'Enter')
    result = run(
        client,
        """
        const { teams } = window.matchesCheck;
        const cards = [...page.queueHost.querySelectorAll('.req-card')];
        return {
            value: page.filters.team === value(teams.accent),
            closed: !document.querySelector('.dd-panel.open'),
            focus: document.activeElement === page.teamFilter.enhanced.button,
            cards: cards.length === 1 && cards[0].textContent.includes('Équipe São Ñandú'),
        };
    """,
    )
    assert all(result.values()), f'Team filter picks by keyboard {result}'
    # A team that a waiting match drew shows nothing of it, the waiting match stays with its named
    # side alone.
    result = run(
        client,
        """
        const { teams } = window.matchesCheck;
        page.teamFilter.value = value(teams.five);
        page.teamFilter.dispatchEvent(new Event('change'));
        const ids = [...page.queueHost.querySelectorAll('.req-card')].map((li) => li.dataset.id);
        const waiting = page.queueHost.querySelector('.req-card[data-id="r-filter-draw"]');
        return ids.includes('r-filter-draw') && waiting.textContent.includes('Random team')
            && !waiting.textContent.includes('Hidden Draw');
    """,
    )
    assert result is True, f'Waiting drawn match under the Team filter {result}'
    # By keyboard alone, with capitals, accents and a space in the typed word, and Escape.
    steps = []
    client.evaluate(f'{FILTER}.focus()')
    press(client, 'ArrowDown', 'ArrowDown')
    type_text(client, 'ÉQUIPE S')
    steps.append(run(client, 'return label(document.activeElement);'))
    client.evaluate('new Promise((resolve) => setTimeout(resolve, 800))')
    type_text(client, 'the ext')
    steps.append(run(client, 'return label(document.activeElement);'))
    press(client, 'Escape', 'Escape')
    steps.append(
        run(
            client,
            """
            return !document.querySelector('.dd-panel.open')
                && document.activeElement === page.teamFilter.enhanced.button
                && page.filters.team === value(window.matchesCheck.teams.five);
        """,
        )
    )
    press(client, 'ArrowDown', 'ArrowDown')
    type_text(client, 'the')
    press(client, 'Enter', 'Enter')
    steps.append(
        run(
            client,
            """
            const { teams } = window.matchesCheck;
            const picked = page.filters.team === value(teams.long);
            // The choice outlasts a redraw of the list and a reload of the page's data.
            page.renderQueue();
            await page.refresh();
            page.poll = async () => {};
            return picked && page.filters.team === value(teams.long)
                && page.teamFilter.enhanced.button.textContent.includes('The Extraordinarily');
        """,
        )
    )
    expected = [
        'Équipe São Ñandú',
        'The Extraordinarily Long Named Football Club of the Northern Valley',
        True,
        True,
    ]
    assert steps == expected, f'Team filter by keyboard {steps}'
    return 6


def menu_checks(client):
    """Counts the teams of a random side, and sees a menu follow its button as the page scrolls."""
    run(client, "page.state.unticked.clear(); page.state.right = 'builtin'; page.updateSetup();")
    click(client, 'cuju.matches.sides[0].button')
    click(client, "document.querySelector('.team-menu.open .dd-item')")
    click(client, 'cuju.matches.scenarioSelect.enhanced.button')
    type_text(client, '5 vs')
    press(client, 'Enter', 'Enter')
    result = run(
        client,
        """
        const s = page.state;
        // A side of five against the built-in AI draws one of the teams of five, and the built-in
        // AI only when no other team fits.
        const five = page.teams.filter((x) => x.kind !== 'builtin' && x.format === '5v5').length;
        const meta = page.sides[0].button.querySelector('.team-card-meta').textContent;
        return { random: s.left === 'random', scenario: s.scenario === '5_vs_5',
            count: meta === `Drawn from ${five} teams of the pool`,
            fewer: five < page.teams.length, meta };
    """,
    )
    meta = result.pop('meta')
    assert all(result.values()), f'Random side counts its teams {result} {meta}'
    run(client, "page.state.left = 'builtin'; page.updateSetup();")
    click(client, FILTER)
    result = run(
        client,
        """
        const button = page.teamFilter.enhanced.button;
        const panel = page.teamFilter.enhanced.panel;
        // The page scrolls in its own box, which a few requests leave short, so a tall box at its
        // end gives it room.
        const box = page.root;
        const room = document.createElement('div');
        room.style.height = '1500px';
        box.append(room);
        const beside = () => {
            const b = button.getBoundingClientRect();
            const p = panel.getBoundingClientRect();
            return panel.classList.contains('up') ? Math.abs(p.bottom - (b.top - 4)) < 2
                : Math.abs(p.top - (b.bottom + 4)) < 2;
        };
        // The panel slides into place as it opens.
        await wait(400);
        const first = beside();
        const top = button.getBoundingClientRect().top;
        box.scrollBy({ top: 120, behavior: 'instant' });
        await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const moved = Math.abs(button.getBoundingClientRect().top - top) > 20;
        const follows = beside();
        room.remove();
        return { open: panel.classList.contains('open'), first, moved, follows };
    """,
    )
    press(client, 'Escape', 'Escape')
    assert all(result.values()), f'Menu follows its button {result}'
    return 2


def phone_checks(client):
    """Checks the team cards, the lists and the names of requested matches at a phone's width."""
    client.call(
        'Emulation.setDeviceMetricsOverride',
        {'width': 390, 'height': 844, 'deviceScaleFactor': 1, 'mobile': True},
    )
    try:
        fits = run(
            client,
            """
            await wait(200);
            page.state.left = window.matchesCheck.teams.long.id;
            page.updateSetup();
            const box = page.root.querySelector('.match-setup').getBoundingClientRect();
            const card = page.sides[0].button;
            const meta = card.querySelector('.team-card-meta');
            // The line under the name says the format and the players plainly, in full, and the
            // whole control setting is the tooltip of the card.
            const plain = meta.textContent === '5 against 5, 1 player'
                && meta.scrollWidth <= meta.clientWidth + 1
                && card.title.startsWith('Submission, controls ');
            return plain && [...page.root.querySelectorAll('.side')].every((side) => {
                const r = side.getBoundingClientRect();
                return r.left >= box.left && r.right <= box.right;
            }) && document.documentElement.scrollWidth <= 390;
        """,
        )
        assert fits is True, 'Team cards fit a phone'
        click(client, 'cuju.matches.sides[0].button')
        result = run(
            client,
            """
            const panel = page.sides[0].dropdown.panel;
            const r = panel.getBoundingClientRect();
            return {
                open: panel.classList.contains('open'),
                inside: r.left >= 0 && r.right <= 390 && r.top >= 0 && r.bottom <= 844,
                noScroll: document.documentElement.scrollWidth <= 390,
            };
        """,
        )
        press(client, 'Escape', 'Escape')
        result['closed'] = run(
            client,
            """
            return !page.sides[0].dropdown.panel.classList.contains('open')
                && document.activeElement === page.sides[0].button;
        """,
        )
        assert all(result.values()), f'Team list on a phone {result}'
        run(
            client,
            """
            page.state.left = 'builtin';
            page.updateSetup();
            page.teamFilter.value = 'all';
            page.teamFilter.dispatchEvent(new Event('change'));
        """,
        )
        click(client, FILTER)
        # A name that the list cuts short shows whole as the tooltip of its item.
        cut = run(
            client,
            """
            const item = openItems().find((el) => label(el).startsWith('The Extraordinarily'));
            const name = item && item.querySelector('.dd-label');
            return !!item && name.scrollWidth > name.clientWidth && item.title === label(item);
        """,
        )
        assert cut is True, 'Cut name in the Team filter has a tooltip'
        type_text(client, 'équipe')
        press(client, 'Enter', 'Enter')
        result = run(
            client,
            """
            const { teams } = window.matchesCheck;
            const card = page.queueHost.querySelector('.req-card');
            const names = card ? [...card.querySelectorAll('.req-team-name')] : [];
            return { picked: page.filters.team === value(teams.accent),
                // The short name beside the long one keeps at least as much room as the long one.
                shared: names.length === 2 && names[0].clientWidth + 2 >= names[1].clientWidth,
                // The buttons go under the text, so the names keep the whole row.
                below: !!card && card.querySelector('.req-actions').getBoundingClientRect().top
                    >= card.querySelector('.req-main').getBoundingClientRect().bottom - 1,
                noScroll: document.documentElement.scrollWidth <= 390 };
        """,
        )
        assert all(result.values()), f'Team filter on a phone {result}'
    finally:
        client.call('Emulation.clearDeviceMetricsOverride')
    return 4


def pool_checks(client):
    """Marks the teams of the pool that cannot play the chosen scenario and counts the rest."""
    result = run(
        client,
        """
        const { teams } = window.matchesCheck;
        await until(() => page.formations);
        // A team that controls three players, as the registry would hold it.
        const three = page.team(teams.three.id);
        three.control = { players: 3, assignment: 'dynamic', selection: [], goalkeeper: 'scenario',
            action_set: 'default' };
        const s = page.state;
        s.unticked.clear();
        s.left = 'builtin';
        s.right = 'random';
        page.updateSetup();
        page.scenarioSelect.value = 'academy_3_vs_1_with_keeper';
        page.scenarioSelect.dispatchEvent(new Event('change'));
        const row = (team) => page.pool.list.querySelector(`[data-id="${team.id}"]`);
        const meta = () => page.sides[1].button.querySelector('.team-card-meta').textContent;
        // The right side of the drill holds two players, too few for a team of three.
        const fits = [...page.pool.list.querySelectorAll('.draw-pool-team')]
            .filter((el) => !el.classList.contains('unfit') && el.dataset.id !== 'builtin');
        const all = {
            three: row(teams.three).classList.contains('unfit')
                && row(teams.three).title.includes('controllable players'),
            count: meta() === `Drawn from ${fits.length} teams of the pool`,
        };
        // A full match of five leaves out the team of eleven, said in words.
        page.scenarioSelect.value = '5_vs_5';
        page.scenarioSelect.dispatchEvent(new Event('change'));
        all.eleven = row(teams.eleven).classList.contains('unfit')
            && row(teams.eleven).title.includes('11 against 11')
            && !row(teams.three).classList.contains('unfit');
        const shown = { meta: meta(), title: row(teams.three).title };
        s.right = 'builtin';
        page.updateSetup();
        return Object.values(all).every(Boolean) || JSON.stringify({ ...all, ...shown });
    """,
    )
    assert result is True, f'Pool of the draw marks the teams that cannot play {result}'
    return 1


def refill_checks(client):
    """Keeps an open Team filter open and its focus in place while new requests come in."""
    client.evaluate(f'{FILTER}.focus()')
    press(client, 'ArrowDown', 'ArrowDown')
    press(client, 'ArrowDown', 'ArrowDown')
    result = run(
        client,
        """
        const { teams } = window.matchesCheck;
        const before = document.activeElement.dataset.value;
        const shown = page.requests.find((r) => r.left === teams.five.id);
        // A poll brings a request of a team that the list did not show.
        page.requests = [{ ...shown, id: 'r-matches-refill', left: teams.three.id },
            ...page.requests];
        page.renderQueue();
        await wait(50);
        const panel = page.teamFilter.enhanced.panel;
        return {
            open: panel.classList.contains('open'),
            focus: panel.contains(document.activeElement)
                && document.activeElement.dataset.value === before,
            added: openItems().some((el) => el.dataset.value === value(teams.three)),
        };
    """,
    )
    press(client, 'Escape', 'Escape')
    assert all(result.values()), f'Open Team filter refills in place {result}'
    return 1


def rebuild_checks(client):
    """Builds the page again after an error and sees one list for each side."""
    result = run(
        client,
        """
        const count = () => document.querySelectorAll('#app > .team-menu').length;
        const before = count();
        page.error = new Error('The server is away.');
        page.render();
        page.error = null;
        page.render();
        page.render();
        return (before === 2 && count() === 2) || JSON.stringify({ before, after: count() });
    """,
    )
    assert result is True, f'Team lists after a rebuild {result}'
    return 1


def recordings_checks(client):
    """Searches the recordings without the accents of a team's name."""
    result = run(
        client,
        """
        cuju.showPage('recordings');
        const recordings = cuju.recordings;
        // The library as it is now, with the matches of these checks, and none of the filters
        // that earlier checks chose.
        const filters = recordings.filters;
        recordings.filters = Object.fromEntries(Object.keys(filters)
            .map((key) => [key, key === 'range' ? 'any' : 'all']));
        recordings.trash = false;
        await recordings.refresh();
        const search = document.querySelector('#page-recordings input.search');
        search.value = 'EQUIPE SAO';
        search.dispatchEvent(new Event('input', { bubbles: true }));
        const found = recordings.visible()
            .some((m) => (m.title || '').includes('Équipe São Ñandú'));
        search.value = '';
        search.dispatchEvent(new Event('input', { bubbles: true }));
        recordings.filters = filters;
        cuju.showPage('matches');
        await page.refresh();
        page.poll = async () => {};
        return found || JSON.stringify({ count: recordings.list.length,
            titles: recordings.list.slice(0, 5).map((m) => m.title) });
    """,
    )
    assert result is True, f'Recordings search ignores accents {result}'
    return 1


def registry_checks(client):
    """Renames and removes teams and sees the filter and the list name them alike."""
    result = run(
        client,
        """
        const { api } = await import('./js/core/api.js');
        const { teams } = window.matchesCheck;
        page.teamFilter.value = value(teams.five);
        page.teamFilter.dispatchEvent(new Event('change'));
        // The Teams page tells the app of a change, as here.
        await api.updateTeam(teams.five.id, { name: 'Filter Five Renamed' });
        cuju.teamsChanged();
        const names = () => [...page.queueHost.querySelectorAll('.req-team-name')]
            .map((x) => x.textContent);
        const renamed = await until(() => names().includes('Filter Five Renamed'));
        const all = {
            renamed: !!renamed && !names().includes('Filter Five'),
            kept: page.filters.team === value(teams.five),
            filter: page.teamFilter.enhanced.button.textContent.includes('Filter Five Renamed'),
        };
        await api.deleteTeam(teams.accent.id);
        page.teamFilter.value = value(teams.accent);
        page.teamFilter.dispatchEvent(new Event('change'));
        cuju.teamsChanged();
        // A removed team shows the name that its requests kept, marked as removed.
        const gone = 'Équipe São Ñandú (removed)';
        const removed = await until(() => names().includes(gone));
        const option = [...page.teamFilter.options].find((o) => o.value === value(teams.accent));
        all.removed = !!removed && !names().includes('Équipe São Ñandú');
        all.option = !!option && option.textContent === gone
            && option.dataset.hint === teams.accent.id;
        // A request of before, which kept no names, shows Removed team alone.
        const older = { ...page.requests.find((r) => r.left === teams.accent.id),
            id: 'r-matches-older', left: 't-matches-older', team_names: undefined };
        all.older = page.requestCard(older).querySelector('.req-team-name').textContent
            === 'Removed team';
        // A removed team comes after every team of the registry.
        const kinds = [...page.teamFilter.options].slice(1)
            .map((o) => !!page.team(o.value.slice('team:'.length)));
        all.last = kinds.indexOf(false) >= 0 && !kinds.slice(kinds.indexOf(false)).includes(true);
        return Object.values(all).every(Boolean) || JSON.stringify({ ...all, names: names() });
    """,
    )
    assert result is True, f'Renamed and removed teams {result}'
    return 2


def new_team_checks(client):
    """Registers a team behind the page's back and sees a request of it show the team's name."""
    result = run(
        client,
        """
        const { api } = await import('./js/core/api.js');
        const check = window.matchesCheck;
        page.poll = check.poll;
        page.teamFilter.value = 'all';
        page.teamFilter.dispatchEvent(new Event('change'));
        // Another tab or the command line registers a team and requests a match of it.
        const source = 'def agent(obs):\\n    return [0]\\n';
        const late = await api.uploadTeam('Late Arrivals', 'main.py', source, '5v5');
        check.teams.late = late;
        const r = await api.requestMatch(
            { left: late.id, right: 'builtin', scenario: '5_vs_5', seed: 4 });
        const card = () => page.queueHost.querySelector(`.req-card[data-id="${r.id}"]`);
        const named = await until(() => card() && card().textContent.includes('Late Arrivals'));
        const option = [...page.teamFilter.options].find((o) => o.value === value(late));
        return (!!named && !!option && option.textContent === 'Late Arrivals')
            || JSON.stringify({ card: card() && card().textContent,
                option: option && option.textContent });
    """,
    )
    assert result is True, f'Request of a new team {result}'
    return 1


def cleanup(client):
    run(
        client,
        """
        const { api } = await import('./js/core/api.js');
        const check = window.matchesCheck;
        if (!check) {
            return;
        }
        page.poll = check.poll;
        for (const team of Object.values(check.teams)) {
            await api.deleteTeam(team.id).catch(() => null);
        }
        page.state.left = 'builtin';
        page.state.right = 'builtin';
        page.state.unticked.clear();
        page.filters.team = 'all';
        delete window.matchesCheck;
        await page.refresh();
    """,
    )


def check_matches(client):
    """Runs every check of the Matches page and returns their count."""
    try:
        setup(client)
        checks = filter_checks(client)
        checks += menu_checks(client)
        checks += pool_checks(client)
        checks += refill_checks(client)
        checks += rebuild_checks(client)
        checks += recordings_checks(client)
        checks += phone_checks(client)
        checks += registry_checks(client)
        checks += new_team_checks(client)
    finally:
        cleanup(client)
    return checks
