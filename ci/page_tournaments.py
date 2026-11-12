# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the Tournaments page by keyboard and in place, for ci/page_check.py.

The wizard checks walk the steps as a person does, with a team of five a side that the check
registers on the mock and removes at the end. They hold the focus after every redraw, the numbers
of the entrants, the way to another scenario that a refusal offers, the presets as a group of radio
buttons, the names of the built-in AI, and the refusals that the page gives before asking the
server. The view checks play small tournaments of the mock, cancel and delete them by questions in
place, hold the trophy ceremony and open another match, reveal every result without spoilers, and
draw fixtures, kickoff cards and list rows of made up tournaments.
"""

UNTIL = """
    const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const until = async (test, ms = 10000) => {
        const end = performance.now() + ms;
        while (performance.now() < end) {
            const value = test();
            if (value) {
                return value;
            }
            await wait(50);
        }
        return test();
    };
    const page = cuju.tournaments;
    document.querySelector('[data-page="tournaments"]').click();
    await until(() => page.built);
    const main = () => page.mainHost;
    // A control by its accessible name, the label of a symbol or the text it shows.
    const named = (text, root = main()) => [...root.querySelectorAll('button, input, select')]
        .find((b) => (b.getAttribute('aria-label') || b.textContent).trim() === text);
    const active = () => document.activeElement;
    const label = (node) => (node
        && (node.getAttribute('aria-label') || node.textContent.trim())) || '';
    // Clicks a control as a person does, its focus first.
    const press = (node) => {
        if (node) {
            node.focus();
            node.click();
        }
    };
    const toasts = [];
    const toast = cuju.hud.toast.bind(cuju.hud);
    cuju.hud.toast = (text, ...rest) => {
        toasts.push(text);
        return toast(text, ...rest);
    };
    // A native dialog would block the page, so any that opens fails the check.
    const dialogs = [];
    const confirm = window.confirm;
    window.confirm = (text) => {
        dialogs.push(text);
        return false;
    };
"""


def wizard_checks(client):
    """Checks the focus, the numbers, the refusals and the presets of the wizard."""
    result = client.evaluate(
        """
        (async () => {
            """
        + UNTIL
        + """
            const { api } = await import('./js/core/api.js');
            const { tournamentsApi } = await import('./js/play/tournament.js');
            const five = await api.uploadTeam('Five check', 'main.py',
                new Blob(['def agent(obs):\\n    return [0]\\n']), '5v5');
            const all = {};
            try {
                page.root.querySelector('.cup-side-head button').click();
                await until(() => main().querySelector('[data-preset="round_robin"]'));
                // The presets are radio buttons with one stop of the Tab key, and an arrow chooses.
                const picks = [...main().querySelectorAll('.cup-preset-pick')];
                all.oneStop = picks.filter((b) => b.tabIndex === 0).length === 1;
                picks[0].focus();
                picks[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight',
                    bubbles: true }));
                const second = picks[1].dataset.preset;
                all.arrows = page.draft.preset === second
                    && active().dataset.preset === second && active().tabIndex === 0;
                // A saved preset keeps its forfeit score when the wizard starts from it.
                await tournamentsApi.savePreset('check_forfeit', { title: 'Forfeit check',
                    description: '', seeding: 'random', concurrency: 1, forfeit_score: 5,
                    ability: null, defaults: {}, stages: [{ format: 'league', name: 'League' }] });
                page.presets = await tournamentsApi.presets();
                page.renderWizard();
                main().querySelector('[data-preset="check_forfeit"]').click();
                all.forfeit = page.draft.forfeit_score === 5;
                await tournamentsApi.removePreset('check_forfeit');
                delete page.presets.check_forfeit;
                page.draft.forfeit_score = 3;
                page.renderWizard();
                main().querySelector('[data-preset="round_robin"]').click();
                // Next leaves the focus on the tab of the step it opens.
                press(named('Next'));
                all.next = page.step === 1 && active().id === 'cup-step-1';
                // An empty ability adds nobody, and says why.
                const box = () => main().querySelector('.cup-adder input[type="number"]');
                box().value = '';
                press(named('Add built-in AI'));
                all.empty = page.draft.entrants.length === 0
                    && toasts.at(-1) === 'An ability lies from 0 to 1.';
                // The built-in AI at the same ability shows the number the server gives it.
                box().value = '0.5';
                press(named('Add built-in AI'));
                all.adder = label(active()) === 'Add built-in AI';
                box().value = '0.5';
                press(named('Add built-in AI'));
                await wait(0);
                const names = [...main().querySelectorAll('.cup-entrant-name input')]
                    .map((input) => input.placeholder);
                all.numbered = names.join('|') === 'Built-in AI 0.50|Built-in AI 0.50 2'
                    && /enters as Built-in AI 0.50 2/.test(toasts.at(-1));
                // The rows show their numbers.
                const marker = getComputedStyle(main().querySelector('.cup-entrants > li'),
                    '::before').content;
                all.number = /counter|"1"/.test(marker);
                // Enter in the name of a person adds the person, and the focus stays there.
                const person = named('Name of the person to add');
                person.focus();
                person.value = 'Ana';
                person.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                all.person = page.draft.entrants.at(-1).name === 'Ana'
                    && label(active()) === 'Name of the person to add';
                // Add every team adds the team once, and then says every team is in.
                press(main().querySelector('[data-focus="add-all"]'));
                const count = page.draft.entrants.length;
                press(main().querySelector('[data-focus="add-all"]'));
                all.every = count === 4 && page.draft.entrants.length === 4
                    && toasts.at(-1) === 'Every registered team has entered already.'
                    && active().dataset.focus === 'add-all';
                // Moving the last entrant to the top keeps the focus on a button that works.
                for (let i = 3; i > 0; i--) {
                    press(main().querySelectorAll('.cup-entrants > li')[i].querySelector(
                        '.cup-up'));
                }
                all.moved = page.draft.entrants[0].kind === 'team'
                    && active().classList.contains('cup-down') && !active().disabled;
                // Removing the last entrant gives the focus to the one before it.
                press(main().querySelectorAll('.cup-entrants > li')[3].querySelector(
                    '.cup-remove'));
                all.removed = page.draft.entrants.length === 3
                    && label(active()) === 'Remove entrant 3';
                // A stage of eleven a side refuses the team of five, and the review leads to the
                // stage's scenario.
                page.draft.defaults = { scenario: '11_vs_11_kaggle' };
                page.goStep(4);
                const fix = await until(() => main().querySelector('.cup-fix-scenario'), 8000);
                all.offer = !!fix && /stage 1/.test(fix.textContent);
                if (fix) {
                    fix.click();
                    all.scenario = page.step === 3
                        && label(active()).startsWith('Scenario, stage 1');
                }
                // A scenario of the deciding matches leads to that field.
                page.draft.defaults = {};
                page.draft.stages = [{ format: 'knockout', name: 'Cup' }];
                const check = tournamentsApi.check;
                tournamentsApi.check = async () => {
                    const error = new Error('Five check cannot play a deciding match');
                    error.id = 'server.tournament.cannot_play_decider';
                    error.values = { stage: 1 };
                    throw error;
                };
                page.goStep(4);
                const decider = await until(() => main().querySelector('.cup-fix-scenario'), 8000);
                tournamentsApi.check = check;
                all.decider = !!decider && /deciding matches of stage 1/.test(decider.textContent);
                if (decider) {
                    decider.click();
                    all.deciderField = label(active()) === 'Scenario of a deciding match, stage 1';
                }
                // The stage buttons name their stage, and the boxes of a setting read as typed.
                page.goStep(3);
                all.labels = !!named('Remove stage 1') && !!named('Move stage 1 later')
                    && !!named('Set: Ability of built-in AI sides, stage 1');
                // Adding a stage focuses its name, and its format select keeps the focus.
                press(named('Add a stage'));
                all.added = page.draft.stages.length === 2 && label(active()) === 'Name, stage 2';
                const format = named('Format, stage 2');
                format.focus();
                format.value = 'league';
                format.dispatchEvent(new Event('change'));
                all.format = label(active()) === 'Format, stage 2'
                    && page.draft.stages[1].format === 'league';
                // A later stage names standing as its default seeding.
                const seeding = named('Seeding of those who arrive, stage 2');
                all.seeding = !!seeding
                    && seeding.options[0].textContent === 'By the earlier stage, the default'
                    && seeding.options[1].textContent === 'Random from the seed';
                // A tiebreaker moved to the top keeps the focus on its box.
                press(named('Move earlier: goals scored, stage 2'));
                all.order = label(active()) === 'Use: goals scored, stage 2';
                // Moving and removing a stage keep the focus on a working button.
                press(named('Move stage 2 earlier'));
                all.stageMoved = label(active()) === 'Move stage 1 later';
                press(named('Remove stage 1'));
                all.stageRemoved = page.draft.stages.length === 1 && main().contains(active())
                    && !active().disabled;
                // The editor of JSON stays open, with the focus on its button.
                main().querySelector('.cup-json-box').open = true;
                await wait(50);
                press(named('Use this JSON'));
                all.json = main().querySelector('.cup-json-box').open
                    && label(active()) === 'Use this JSON';
                // A preset without a name is refused on the page, with the focus on the name.
                page.goStep(4);
                press(await until(() => named('Save preset')));
                const name = main().querySelector('.cup-preset-name');
                all.presetName = active() === name && name.getAttribute('aria-invalid') === 'true'
                    && /small letters/.test(toasts.at(-1));
                all.dialogs = dialogs.length === 0;
            } finally {
                cuju.hud.toast = toast;
                window.confirm = confirm;
                page.cancelWizard();
                await api.deleteTeam(five.id);
            }
            return Object.values(all).every(Boolean) || JSON.stringify(all);
        })()
    """
    )
    assert result is True, f'Tournament wizard by keyboard {result}'
    return 1


def phone_checks(client):
    """Checks that the ability of an entrant shows its placeholder at the width of a phone."""
    client.call(
        'Emulation.setDeviceMetricsOverride',
        {'width': 390, 'height': 844, 'deviceScaleFactor': 1, 'mobile': True},
    )
    try:
        result = client.evaluate(
            """
            (async () => {
                """
            + UNTIL
            + """
                const all = {};
                try {
                    page.startWizard();
                    page.draft.ability = 0.8;
                    page.draft.entrants = [{ kind: 'builtin', ability: null }, { kind: 'person',
                        name: 'Ana', teammates: 'builtin' }];
                    page.goStep(1);
                    await wait(100);
                    const boxes = [...main().querySelectorAll('.cup-entrant-ability')];
                    // The box is wide enough for its placeholder, such as Standard, 0.80.
                    const probe = document.createElement('span');
                    probe.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap';
                    probe.style.font = getComputedStyle(boxes[0]).font;
                    probe.textContent = boxes[0].placeholder;
                    document.body.append(probe);
                    const wanted = probe.offsetWidth;
                    probe.remove();
                    all.wide = boxes.length === 2 && boxes.every((b) => b.clientWidth >= wanted);
                    all.noScroll = document.documentElement.scrollWidth <= 390;
                    all.sizes = boxes.map((b) => b.clientWidth).concat(wanted);
                    // The offer of another scenario wraps its words within the review.
                    const { tournamentsApi } = await import('./js/play/tournament.js');
                    const check = tournamentsApi.check;
                    tournamentsApi.check = async () => {
                        const error = new Error('Five check cannot play a deciding match');
                        error.id = 'server.tournament.cannot_play_decider';
                        error.values = { stage: 1 };
                        throw error;
                    };
                    page.goStep(4);
                    const fix = await until(() => main().querySelector('.cup-fix-scenario'), 8000);
                    tournamentsApi.check = check;
                    const notice = fix && fix.closest('.notice');
                    all.fixFits = !!fix && fix.scrollWidth <= fix.clientWidth + 1
                        && fix.getBoundingClientRect().right
                            <= notice.getBoundingClientRect().right;
                } finally {
                    cuju.hud.toast = toast;
                    window.confirm = confirm;
                    page.cancelWizard();
                }
                const { sizes, ...rest } = all;
                return Object.values(rest).every(Boolean) || JSON.stringify(all);
            })()
        """
        )
    finally:
        client.call('Emulation.clearDeviceMetricsOverride')
    assert result is True, f'Tournament entrants at the width of a phone {result}'
    return 1


def view_checks(client):
    """Checks the questions in place, the focus after actions, the ceremony and made up views."""
    result = client.evaluate(
        """
        (async () => {
            """
        + UNTIL
        + """
            const { tournamentsApi } = await import('./js/play/tournament.js');
            const spoilers = await import('./js/core/spoilers.js');
            const all = {};
            const made = [];
            const make = async (config) => {
                const entry = await tournamentsApi.create(config);
                made.push(entry.id);
                return entry;
            };
            try {
                // Two people meet in a final, so its card waits in Up next, in the away kit of
                // the right side, since both play with the built-in AI.
                const people = await make({ name: 'People check', seed: 2, seeding: 'manual',
                    entrants: [{ kind: 'person', name: 'Ana' }, { kind: 'person', name: 'Bo' }],
                    stages: [{ format: 'knockout', name: 'Cup' }] });
                await page.open(people.id);
                const card = await until(() => main().querySelector('.cup-kickoff'));
                all.final = !!card && card.querySelector('.cup-kickoff-label').textContent.trim(
                    ) === 'Final';
                all.away = !!card && card.querySelectorAll(
                    '.cup-kickoff-side')[1].classList.contains('away');
                // Cancel asks in place, Escape keeps it running with the focus on Cancel.
                press(named('Cancel tournament'));
                const asked = main().querySelector('.cup-actions .cup-confirm');
                all.asked = !!asked && label(active()) === 'Keep it running';
                active().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape',
                    bubbles: true }));
                all.kept = !main().querySelector('.cup-actions .cup-confirm')
                    && label(active()) === 'Cancel tournament' && page.current.state === 'running';
                press(named('Cancel tournament'));
                press(main().querySelector('[data-focus="ask-yes-cancel"]'));
                await until(() => page.current.state === 'cancelled');
                await wait(100);
                // A canceled tournament lists nothing to play and says so, with the focus kept.
                all.canceled = page.current.state === 'cancelled'
                    && !main().querySelector('.cup-up-next')
                    && !!main().querySelector('.cup-canceled')
                    && /Not played, canceled/.test(main().querySelector(
                        '.cup-stage-view').textContent);
                all.cancelFocus = main().contains(active()) && active() !== main();
                page.list = await tournamentsApi.list();
                page.renderList();
                all.noPeople = !page.listHost.querySelector('.cup-item.active .cup-item-people');
                // Delete asks in place too, and gives the focus to the list.
                press(main().querySelector('[data-focus="act-delete"]'));
                all.deleteAsked = !!main().querySelector('.cup-actions .cup-confirm');
                press(main().querySelector('[data-focus="ask-yes-delete"]'));
                await until(() => page.mode === 'empty');
                made.splice(made.indexOf(people.id), 1);
                all.deleted = page.mode === 'empty'
                    && page.root.querySelector('.cup-side').contains(active());
                // The trophy ceremony leaves with its match when another one opens.
                const cup = await make({ name: 'Ceremony check', seed: 4,
                    entrants: [{ kind: 'builtin', ability: 0.2 }, { kind: 'builtin',
                        ability: 0.8 }],
                    stages: [{ format: 'knockout', name: 'Cup' }] });
                await page.open(cup.id);
                await until(() => page.current && page.current.state === 'done', 15000);
                await page.load(cup.id);
                await page.ceremony();
                const shown = await until(() => cuju.podium.showing, 8000);
                const other = page.current.matches.find((m) => m.result && m.result.match);
                await cuju.openMatch(other.result.match);
                all.ceremony = !!shown && !cuju.podium.showing;
                cuju.director.stop(true);
                cuju.timeline.pause();
                cuju.showPage('tournaments');
                // Reveal all joins the summary of what the person missed.
                const many = await make({ name: 'Reveal check', seed: 5, seeding: 'manual',
                    entrants: [0.1, 0.3, 0.5, 0.7].map((ability) => ({ kind: 'builtin', ability })),
                    stages: [{ format: 'knockout', name: 'Cup' }] });
                await page.open(many.id);
                await until(() => page.current && page.current.state === 'done', 15000);
                spoilers.setSpoilerFree(many.id, true);
                await page.load(many.id);
                const first = await until(() => main().querySelector(
                    '[data-focus^="unseen-reveal-"]'));
                const key = first.dataset.focus.slice('unseen-reveal-'.length);
                press(first);
                await until(() => !main().querySelector(`[data-focus="unseen-reveal-${CSS.escape(
                    key)}"]`));
                all.revealFocus = main().contains(active()) && active() !== main();
                press(main().querySelector('[data-focus="reveal-all"]'));
                press(main().querySelector('[data-focus="reveal-yes"]'));
                const summary = await until(() => main().querySelector('.cup-caught-up'));
                all.summary = !!summary && summary.querySelectorAll('li').length === 3;
                spoilers.setSpoilerFree(many.id, false);
                // A stopped tournament says in the list why it stopped.
                const failing = await make({ name: 'Stopped check', seed: 6, seeding: 'manual',
                    entrants: [{ kind: 'builtin', ability: 0.1, name: 'Failing bot' },
                        { kind: 'builtin', ability: 0.4 }],
                    stages: [{ format: 'knockout', name: 'Cup' }] });
                await page.open(failing.id);
                await until(() => page.current && page.current.state === 'stopped', 15000);
                page.list = await tournamentsApi.list();
                page.renderList();
                const row = [...page.listHost.querySelectorAll('.cup-item')].find((
                    b) => /Stopped check/.test(b.textContent));
                all.failed = !!row && /1 failed match waits for an award or Resume/.test(
                    row.textContent);
                // An award confirmed keeps the focus in the tournament.
                press(main().querySelector('.cup-failed [data-focus^="award-"]'));
                press(main().querySelector('.cup-failed .cup-confirm .btn.primary'));
                await until(() => page.current.state !== 'stopped');
                await wait(100);
                all.awardFocus = main().contains(active()) && active() !== main();
                // A tie decided by lots after a replay reads in the order things happened, and
                // the score of deciding matches says how the tie was decided once.
                page.current.config.entrants = [{ name: 'Rex', team: 'a', color: [200, 0, 0],
                    secondary: [255, 255, 255] },
                    { name: 'Max', team: 'b', color: [0, 0, 200], secondary: [255, 255, 255] }];
                page.matchMap = new Map();
                const meta = (f) => page.fixture({ id: 'x', label: null, matches: [],
                    state: 'done', home: 0, away: 1, winner: 1, ...f })
                    .querySelector('.cup-fixture-meta').textContent;
                all.lots = meta({ score: [0, 0], replay: [0, 0], decided_by: 'lots' })
                    === 'replay 0 to 0, by lots';
                all.deciders = meta({ score: [1, 1], decider: [1, 0], decided_by: 'decider' })
                    === 'deciding matches 1 to 0';
                // A tie of two byes holds an empty place in its bracket.
                const bracket = page.bracket({ name: 'losers', rounds: [{ name: 'Losers round 1',
                    fixtures: [
                    { id: 'l1', home: null, away: null, matches: [], state: 'done' },
                    { id: 'l2', home: 0, away: null, matches: [], state: 'done', winner: 0 }] }] });
                all.byes = bracket.querySelectorAll('.cup-fixture').length === 1
                    && bracket.querySelectorAll('.cup-bracket-cell.empty').length === 1;
                all.dialogs = dialogs.length === 0;
            } finally {
                cuju.hud.toast = toast;
                window.confirm = confirm;
                for (const id of made) {
                    await tournamentsApi.action(id, 'cancel').catch(() => null);
                    await tournamentsApi.remove(id).catch(() => null);
                }
                page.mode = 'empty';
                page.openId = null;
                await page.refresh();
            }
            return Object.values(all).every(Boolean) || JSON.stringify(all);
        })()
    """
    )
    assert result is True, f'Tournament actions in place {result}'
    return 1
