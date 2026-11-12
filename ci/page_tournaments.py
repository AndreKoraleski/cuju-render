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
                // Start waits while the review shows the refusal, which names why, and a press
                // leads to the refusal rather than to the server.
                const start = main().querySelector('.cup-start');
                const refusal = document.getElementById(start.getAttribute('aria-describedby'));
                const created = tournamentsApi.create;
                let asked = 0;
                tournamentsApi.create = async () => {
                    asked += 1;
                    throw new Error('refused');
                };
                press(start);
                tournamentsApi.create = created;
                all.held = start.getAttribute('aria-disabled') === 'true' && !!refusal
                    && refusal.contains(fix) && asked === 0 && active() === refusal;
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
                press(named('Move earlier: Goals scored, stage 2'));
                all.order = label(active()) === 'Use: Goals scored, stage 2';
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
                // The list takes the focus once it is read again, after the mode changes.
                await until(() => page.mode === 'empty'
                    && page.root.querySelector('.cup-side').contains(active()));
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


def clunky_checks(client):
    """Checks the presets kept and asked in place, the review, the editor of JSON, the orders,
    the sizes of teams, the announcements, the registry read again and the finished view."""
    result = client.evaluate(
        """
        (async () => {
            """
        + UNTIL
        + """
            const { api } = await import('./js/core/api.js');
            const { t } = await import('./js/core/i18n.js');
            const { tournamentsApi } = await import('./js/play/tournament.js');
            const spoilers = await import('./js/core/spoilers.js');
            const all = {};
            const made = [];
            const teams = [];
            const make = async (config) => {
                const entry = await tournamentsApi.create(config);
                made.push(entry.id);
                return entry;
            };
            const type = (input, text, kind = 'input') => {
                input.value = text;
                input.dispatchEvent(new Event(kind, { bubbles: true }));
            };
            const announced = () => page.announcer.textContent;
            try {
                // New tournament leaves the focus on the first step of the wizard.
                press(page.root.querySelector('.cup-side-head button'));
                await until(() => main().querySelector('[data-preset="round_robin"]'));
                all.wizardFocus = active().id === 'cup-step-0'
                    && !/null/.test(main().querySelector('.cup-step-panel').textContent);
                // The settings that the person sets stay when another preset leaves them free.
                const scenario = page.scenarios.find((name) => name.startsWith('academy'))
                    || page.scenarios[0];
                page.goStep(2);
                type(named(t('tournament.settings.seeding')), 'manual', 'change');
                type(named(t('tournament.settings.scenario')), scenario, 'change');
                press(named(t('tournament.optional.set.label',
                    { label: t('tournament.field.length') })));
                type(named(t('tournament.field.length')), '900');
                page.goStep(0);
                press(main().querySelector('[data-preset="round_robin"]'));
                all.kept = page.draft.seeding === 'manual'
                    && page.draft.defaults.scenario === scenario
                    && page.draft.defaults.length === 900 && !main().querySelector('.cup-replaced');
                // A preset that sets its own length says so, and Keep mine gives it back.
                press(main().querySelector('[data-preset="quick_cup"]'));
                const notice = main().querySelector('.cup-replaced');
                all.replaced = !!notice && /match length/.test(notice.textContent)
                    && page.draft.defaults.length === 600 && page.draft.seeding === 'manual';
                press(main().querySelector('[data-focus="keep-mine"]'));
                all.keepMine = page.draft.defaults.length === 900
                    && !main().querySelector('.cup-replaced')
                    && active().classList.contains('cup-preset-pick');
                all.keptSaid = await until(() => announced() === t('tournament.formatStep.kept'));
                // Deleting a preset of the person asks in place, and Escape keeps it.
                await tournamentsApi.savePreset('clunky_check', { title: 'Clunky check',
                    description: '', stages: [{ format: 'league', name: 'League' }] });
                page.presets = await tournamentsApi.presets();
                page.renderWizard();
                press(main().querySelector('[data-focus="delete-preset-clunky_check"]'));
                const asked = main().querySelector('.cup-presets .cup-confirm');
                all.deleteAsked = !!asked && active().dataset.answer === 'no';
                active().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape',
                    bubbles: true }));
                all.deleteKept = !main().querySelector('.cup-presets .cup-confirm')
                    && active().dataset.focus === 'delete-preset-clunky_check'
                    && 'clunky_check' in await tournamentsApi.presets();
                press(main().querySelector('[data-focus="delete-preset-clunky_check"]'));
                press(main().querySelector('.cup-presets .cup-confirm [data-answer="yes"]'));
                all.deleted = await until(() => !page.presets.clunky_check)
                    && !('clunky_check' in await tournamentsApi.presets());
                // Saving over a preset of the person asks first.
                await tournamentsApi.savePreset('clunky_over', { title: 'Old title',
                    description: '', stages: [{ format: 'league', name: 'League' }] });
                page.presets = await tournamentsApi.presets();
                // The review shows its check in place while it runs, and typing goes on.
                const check = tournamentsApi.check;
                let answer = null;
                tournamentsApi.check = (config) => new Promise((resolve) => {
                    answer = () => resolve(check(config));
                });
                page.goStep(4);
                const saveName = main().querySelector('.cup-preset-name');
                all.checking = !!main().querySelector('.cup-review .cup-checking')
                    && main().querySelector('.cup-review').getAttribute('aria-busy') === 'true';
                saveName.focus();
                type(saveName, 'clunky_over');
                await until(() => answer);
                answer();
                tournamentsApi.check = check;
                await until(() => !main().querySelector('.cup-checking'));
                all.typing = saveName.isConnected && saveName.value === 'clunky_over'
                    && active() === saveName;
                const title = saveName.closest('.row').querySelectorAll('input')[1];
                type(title, 'New title');
                press(main().querySelector('[data-focus="save-preset"]'));
                const over = main().querySelector('.cup-save .cup-confirm');
                all.saveAsked = !!over && /Old title/.test(over.textContent)
                    && active().dataset.answer === 'no'
                    && (await tournamentsApi.presets()).clunky_over.title === 'Old title';
                press(main().querySelector('.cup-save .cup-confirm [data-answer="yes"]'));
                all.saved = await until(() => page.presets.clunky_over
                    && page.presets.clunky_over.title === 'New title'
                    && active() && active().dataset.focus === 'save-preset');
                await tournamentsApi.removePreset('clunky_over');
                delete page.presets.clunky_over;
                // A mistake in the JSON names its line and column, and the caret goes there.
                page.goStep(3);
                main().querySelector('.cup-json-box').open = true;
                const json = main().querySelector('.cup-json');
                type(json, '{\\n  "stages": [\\n    { format: "league" }\\n  ]\\n}');
                press(named(t('tournament.json.apply')));
                const note = () => main().querySelector('.cup-json-note').textContent;
                all.json = note() === t('tournament.json.failed', { line: 3, column: 7 })
                    && active() === json && json.selectionStart === 22
                    && json.getAttribute('aria-invalid') === 'true';
                type(json, '[]');
                press(named(t('tournament.json.apply')));
                all.jsonShape = note() === t('tournament.json.expected');
                // An unchecked tiebreaker has no button to move it, and every name starts with a
                // capital, as the ways to settle a tie do.
                page.draft.stages = [{ format: 'league', name: 'League' }];
                page.goStep(3);
                const use = named('Use: Goal difference, stage 1');
                press(use);
                const row = named('Use: Goal difference, stage 1').closest('li');
                all.unchecked = !row.querySelector('input').checked && row.classList.contains('off')
                    && !row.querySelector('button')
                    && active().dataset.focus === 'use-goal_difference';
                all.capital = [...main().querySelectorAll('.cup-order li label')]
                    .every((node) => /^[A-Z]/.test(node.textContent.trim()));
                // The rows and the select of teams show the size of each team.
                teams.push(await api.uploadTeam('Size check', 'main.py',
                    new Blob(['def agent(obs):\\n    return [0]\\n']), '5v5'));
                page.teams = await api.teams();
                page.draft.entrants = [];
                page.goStep(1);
                const select = named(t('tournament.entrants.team.label'));
                const option = [...select.options].find((o) => o.value === teams[0].id);
                all.sizeOption = !!option
                    && option.textContent === 'Size check, 5v5, 1 controlled player';
                select.value = teams[0].id;
                press(named(t('tournament.entrants.team.add')));
                press(named(t('tournament.entrants.builtin.add')));
                all.sizeRow = main().querySelector('.cup-entrant-size')
                    ?.textContent === '5v5, 1 controlled player'
                    && page.mainHost.querySelector('.cup-adder select').value === teams[0].id;
                // The notes of names stay in place while empty, and a move is said.
                all.notes = [...main().querySelectorAll('.cup-name-note')]
                    .every((node) => getComputedStyle(node).display !== 'none');
                press(main().querySelector('.cup-entrants > li .cup-down'));
                all.moveSaid = await until(() => /^Moved Size check to place 2 of 2[.]$/.test(
                    announced()));
                // A team registered while the wizard is open joins the select once it is
                // focused.
                teams.push(await api.uploadTeam('Late check', 'main.py',
                    new Blob(['def agent(obs):\\n    return [0]\\n']), '11v11'));
                // A page without the focus of the system hears no focus event, so it is sent.
                const choose = named(t('tournament.entrants.team.label'));
                choose.focus();
                choose.dispatchEvent(new FocusEvent('focus'));
                all.late = await until(() => [...named(t('tournament.entrants.team.label'))
                    .options].some((o) => o.value === teams[1].id));
                page.cancelWizard();
                // A finished tournament reads as finished, with or without spoilers, and its
                // actions name themselves.
                const cup = await make({ name: 'Finish check', seed: 4, seeding: 'manual',
                    entrants: [{ kind: 'team', team: teams[1].id }, { kind: 'builtin',
                        ability: 0.8 }],
                    stages: [{ format: 'knockout', name: 'Cup', settle: ['lots'] }] });
                // The page has not seen the team yet, so it reads the registry again.
                page.teams = page.teams.filter((x) => x.id !== teams[1].id);
                page.teamsAsked = null;
                await page.open(cup.id);
                await until(() => page.current && page.current.state === 'done', 15000);
                await page.load(cup.id);
                all.teamRead = await until(() => page.teams.some((x) => x.id === teams[1].id)
                    && main().querySelector('.cup-fixture') && !main().querySelector('.cup-dot'));
                const played = () => main().querySelector('.cup-view-played').textContent;
                all.finished = played() === 'Finished, 1 match played';
                const words = (key) => main().querySelector(`[data-focus="${key}"]`)
                    ?.textContent.trim();
                all.words = words('act-ceremony') === t('tournament.view.ceremony')
                    && words('act-again') === t('tournament.view.again');
                spoilers.setSpoilerFree(cup.id, true);
                await page.load(cup.id);
                all.finishedQuiet = played() === 'Finished, 1 match played';
                // The score of predictions shows once, also beside what the person missed.
                const key = page.current.matches[0].key;
                spoilers.predict(cup.id, key, 'home');
                spoilers.markWatched(cup.id, key);
                page.session[cup.id] = [key];
                await page.load(cup.id);
                all.once = !!main().querySelector('.cup-caught-up')
                    && main().textContent.split('Predictions:').length === 2;
                spoilers.setSpoilerFree(cup.id, false);
                delete page.session[cup.id];
                // The main part redraws in silence, and the end of a match is said once.
                const quiet = await make({ name: 'Quiet check', seed: 9, seeding: 'manual',
                    entrants: [0.1, 0.3, 0.5, 0.7].map((ability) => ({ kind: 'builtin', ability })),
                    stages: [{ format: 'knockout', name: 'Cup', settle: ['lots'] }] });
                await page.open(quiet.id);
                page.announcer.textContent = '';
                await page.load(quiet.id);
                all.silent = !main().hasAttribute('aria-live')
                    && !main().closest('[aria-live]');
                all.resultSaid = await until(() => /^Final ended: .+ [0-9]+, .+ [0-9]+[.]$/.test(
                    announced()));
                page.announcer.textContent = '';
                await page.load(quiet.id);
                await wait(200);
                all.saidOnce = announced() === '';
                // A refusal of the server that stands alone starts with a capital.
                const open = await make({ name: 'Refusal check', seed: 2,
                    entrants: [{ kind: 'person', name: 'Ana' }, { kind: 'person', name: 'Bo' }],
                    stages: [{ format: 'knockout', name: 'Cup' }] });
                // The name of a tournament keeps the focus through the redraws of a poll.
                await page.open(open.id);
                page.renderView();
                all.titleFocus = active().tagName === 'H2' && main().contains(active());
                const refused = await tournamentsApi.remove(open.id).catch((err) => err);
                all.capitalRefusal = refused instanceof Error
                    && refused.message.startsWith('Expected a tournament that has ended');
                // A smaller zoom of the Brackets view shows the whole bracket smaller.
                const eight = await make({ name: 'Zoom check', seed: 3, seeding: 'manual',
                    entrants: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8].map((ability) => ({
                        kind: 'builtin', ability })),
                    stages: [{ format: 'knockout', name: 'Cup', settle: ['lots'] }] });
                await page.open(eight.id);
                await until(() => page.current && page.current.state === 'done', 15000);
                await page.openBrackets(eight.id);
                const width = () => main().querySelector('.cup-big .cup-bracket')
                    .getBoundingClientRect().width;
                page.zoom = 1;
                page.renderView();
                const full = width();
                page.zoom = 0.5;
                page.renderView();
                const half = width();
                all.zoom = half > 0 && half < full * 0.6;
                all.widths = [full, half];
                page.zoom = 1;
                page.closeBrackets();
                all.dialogs = dialogs.length === 0;
            } finally {
                cuju.hud.toast = toast;
                window.confirm = confirm;
                if (page.mode === 'wizard') {
                    page.cancelWizard();
                }
                for (const name of ['clunky_check', 'clunky_over']) {
                    await tournamentsApi.removePreset(name).catch(() => null);
                }
                for (const id of made) {
                    await tournamentsApi.action(id, 'cancel').catch(() => null);
                    await tournamentsApi.remove(id).catch(() => null);
                }
                for (const team of teams) {
                    await api.deleteTeam(team.id).catch(() => null);
                }
                page.mode = 'empty';
                page.openId = null;
                page.zoom = 1;
                await page.refresh();
            }
            const { widths, ...rest } = all;
            return Object.values(rest).every(Boolean) || JSON.stringify(all);
        })()
    """
    )
    assert result is True, f'Tournament presets, review, orders and finished view {result}'
    return 1


def phone_view_checks(client):
    """Checks the actions, the bracket that scrolls sideways and the ceremony card below the
    podium at the width of a phone."""
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
                const { tournamentsApi } = await import('./js/play/tournament.js');
                const all = {};
                let id = null;
                try {
                    const cup = await tournamentsApi.create({ name: 'Phone check', seed: 3,
                        seeding: 'manual',
                        entrants: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8].map((ability) => ({
                            kind: 'builtin', ability })),
                        stages: [{ format: 'knockout', name: 'Cup', settle: ['lots'] }] });
                    id = cup.id;
                    await page.open(id);
                    await until(() => page.current && page.current.state === 'done', 15000);
                    await page.load(id);
                    // The actions keep their words within the width of the phone.
                    all.actions = [...main().querySelectorAll('.cup-actions .btn')]
                        .every((b) => b.getBoundingClientRect().right <= 390);
                    await page.openBrackets(id);
                    const scroll = main().querySelector('.cup-big .cup-bracket-scroll');
                    all.sideways = !!scroll && scroll.scrollWidth > scroll.clientWidth
                        && document.documentElement.scrollWidth <= 390;
                    page.closeBrackets();
                    // The card of the ceremony sits low, so the podium shows above it.
                    await page.ceremony();
                    await until(() => cuju.podium.showing, 8000);
                    const card = document.getElementById('victory').getBoundingClientRect();
                    all.ceremony = card.top >= innerHeight * 0.45 && card.bottom <= innerHeight
                        && card.left >= 0 && card.right <= 390;
                    all.size = [card.top, card.bottom, innerHeight];
                    cuju.postMatch.end();
                    cuju.showPage('tournaments');
                } finally {
                    cuju.hud.toast = toast;
                    window.confirm = confirm;
                    if (id) {
                        await tournamentsApi.remove(id).catch(() => null);
                    }
                    page.mode = 'empty';
                    page.openId = null;
                    await page.refresh();
                }
                const { size, ...rest } = all;
                return Object.values(rest).every(Boolean) || JSON.stringify(all);
            })()
        """
        )
    finally:
        client.call('Emulation.clearDeviceMetricsOverride')
    assert result is True, f'Tournament views at the width of a phone {result}'
    return 1


def desktop_checks(client):
    """Checks that the kind of each entrant reads on one line at the width of a desktop."""
    client.call(
        'Emulation.setDeviceMetricsOverride',
        {'width': 1280, 'height': 800, 'deviceScaleFactor': 1, 'mobile': False},
    )
    try:
        result = client.evaluate(
            """
            (async () => {
                """
            + UNTIL
            + """
                const { api } = await import('./js/core/api.js');
                const all = {};
                const teams = [];
                try {
                    for (const name of ['Several five', 'Single eleven']) {
                        teams.push(await api.uploadTeam(name, 'main.py',
                            new Blob(['def agent(obs):\\n    return [0]\\n']), '5v5'));
                    }
                    page.startWizard();
                    page.teams = await api.teams();
                    page.draft.entrants = [...teams.map((team) => ({ kind: 'team',
                        team: team.id })),
                        { kind: 'builtin', ability: 0.5 }, { kind: 'person', name: 'Ana',
                            teammates: 'builtin' }];
                    page.goStep(1);
                    await wait(100);
                    // The words that a row shows of its kind, and the size of a team under
                    // them, are one line each.
                    const lines = (node) => {
                        const range = document.createRange();
                        range.selectNodeContents(node);
                        return new Set([...range.getClientRects()].map((r) => Math.round(r.top)))
                            .size;
                    };
                    const kinds = [...main().querySelectorAll('.cup-entrant-kind')];
                    const shown = (kind) => [...kind.childNodes].filter((node) => node.nodeType
                        === Node.TEXT_NODE || node.classList.contains('cup-entrant-size'));
                    all.lines = kinds.map((kind) => shown(kind).map(lines));
                    all.oneLine = kinds.length === 4 && kinds.every((kind) => shown(kind)
                        .every((node) => lines(node) === 1));
                    all.noScroll = document.documentElement.scrollWidth <= 1280;
                } finally {
                    page.cancelWizard();
                    for (const team of teams) {
                        await api.deleteTeam(team.id).catch(() => null);
                    }
                }
                const { lines, ...rest } = all;
                return Object.values(rest).every(Boolean) || JSON.stringify(all);
            })()
        """
        )
    finally:
        client.call('Emulation.clearDeviceMetricsOverride')
    assert result is True, f'Tournament entrants at the width of a desktop {result}'
    return 1
