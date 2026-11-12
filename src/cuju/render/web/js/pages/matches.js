// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The Matches page, where two teams are picked for a match that plays on this computer, and the
// queue of requested matches with their progress, cancelling and watching.

import { api, controlLabel, uiLocale } from '../core/api.js';
import { formatNumber, serverText, t, tn } from '../core/i18n.js';
import { css, normalizeStyle } from '../players/kits.js';
import { Dropdown, el as h, enhanceSelect, menuItem } from '../core/menu.js';
import { icon, stateBadge, symbolOnly } from '../core/icons.js';
import { keptName, teamName } from '../core/names.js';
import { listedScenarios, scenarioName, scenarioText } from '../core/scenarios.js';
import { RANDOM, againOf, drawableTeams, drawnParts, fits, fittingScenarios, hiddenPart, requestOf, scenarioChoices, unfit, wasDrawn } from './draw.js';
import { filterScenarios, filterTeams, passesScenario, passesTeam, scenarioValue, shownTeams, teamValue, unknownTeams } from './queue-filters.js';

export { fits } from './draw.js';

const DEFAULT_SCENARIO = '11_vs_11_kaggle';
const FORMAT_NAMES = { '5v5': t('matches.format.5v5'), '11v11': t('matches.format.11v11') };
// The list of requested matches shows this many more rows each time Show more is pressed.
export const REQUEST_PAGE = 50;

// A small shirt in a team's kit, its pattern drawn with the same classes as the editor's.
export function kitShirt(team, side = 0, size = 'small') {
    const style = normalizeStyle(team, side);
    const k = style.kit;
    // The shirt is clipped to its outline, the wrapper draws an edge around it that shows a
    // white shirt on a white page.
    return h('span', { class: `kit-shirt ${size}`, 'aria-hidden': 'true' },
        h('span', {
            class: `kit-shirt-body p-${k.pattern}`,
            style: `--a:${css(k.primary)};--b:${css(k.secondary)};--c:${css(k.shorts)}`,
        }, style.badge ? h('b', { class: 'kit-badge' }, style.badge) : null));
}

// The state of a request, a failed one by the id of its message, or by its English text for an
// entry of a server that named no id.
function stateOf(r) {
    const id = typeof r.error_id === 'string' ? r.error_id : null;
    if (r.state === 'failed' && (id ? id === 'server.requests.cancelled' : r.error === 'cancelled')) {
        return 'cancelled';
    }
    // A restart of the server marks the requests that waited or played as interrupted.
    const interrupted = id ? id.startsWith('server.requests.interrupted')
        : typeof r.error === 'string' && r.error.startsWith('interrupted by a server restart');
    if (r.state === 'failed' && interrupted) {
        return 'interrupted';
    }
    return r.state;
}

const STATE_LABELS = {
    queued: t('matches.state.queued'), running: t('matches.state.running'), done: t('matches.state.done'),
    failed: t('matches.state.failed'), cancelled: t('matches.state.cancelled'), interrupted: t('matches.state.interrupted'),
};

// The players that a submission controls, one when its setting names none.
function controlledPlayers(team) {
    const players = team && team.control ? team.control.players : null;
    return Number.isInteger(players) && players > 0 ? players : 1;
}

// An ability in the numbers of the language, with two decimals.
function abilityText(value) {
    return formatNumber(Number(value), { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// The time a request was made, its saved time, or for an older entry the time in its identifier,
// r-YYYYMMDD-HHMMSS-xxxx.
function requestTime(r) {
    if (typeof r.created === 'number' && Number.isFinite(r.created)) {
        return new Date(r.created * 1000);
    }
    const m = /^r-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/.exec(r.id || '');
    return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]) : null;
}

// The seconds a request played, from its start to its end or to now while it plays.
function playedSeconds(r) {
    if (typeof r.started !== 'number') {
        return null;
    }
    const end = typeof r.finished === 'number' ? r.finished : Date.now() / 1000;
    return Math.max(0, Math.floor(end - r.started));
}

export class MatchesPage {
    constructor(app) {
        this.app = app;
        this.root = document.getElementById('page-matches');
        this.setTeams([]);
        this.scenarios = [];
        // The players of the scenarios' sides, which the server sends once and the page reads to
        // tell the teams that can play a side, null until they come.
        this.formations = null;
        this.requests = [];
        this.seen = new Set();
        // The teams that requests named and the registry did not hold when the page looked.
        this.looked = new Set();
        this.primed = false;
        // A side or the scenario may be Random, which the server draws from the seed, a side from
        // the teams of the pool, every team but those unticked.
        this.state = {
            left: null, right: 'builtin', scenario: null, seed: '', ability: [null, null],
            unticked: new Set(), sameTeam: false,
        };
        this.filters = { status: 'all', team: 'all', scenario: 'all', date: 'any', sort: 'newest' };
        this.limit = REQUEST_PAGE;
        this.error = null;
        this.token = 0;
        this.built = false;
        setInterval(() => this.poll(), 1500);
    }

    get visible() {
        return !this.root.hidden;
    }

    async refresh() {
        const token = ++this.token;
        if (!this.formations && !this.loadingFormations) {
            // The players come apart from the rest, so a slow first answer holds up nothing.
            this.loadingFormations = api.scenarioSides().then((sides) => {
                this.formations = sides && typeof sides === 'object' ? sides : null;
                this.updateSetup();
            }).catch(() => null).finally(() => {
                this.loadingFormations = null;
            });
        }
        try {
            const [teams, scenarios, requests] = await Promise.all([
                api.teams(), api.scenarios().catch(() => []), api.requests().catch(() => []),
            ]);
            if (token !== this.token) {
                return;
            }
            this.setTeams(teams);
            const listed = listedScenarios(scenarios);
            this.scenarios = listed.length ? listed : [DEFAULT_SCENARIO];
            this.requests = requests;
            this.error = null;
        } catch (err) {
            if (token !== this.token) {
                return;
            }
            this.error = err;
        }
        this.render();
    }

    // The registry, and a count of its changes, so the cards of the list redraw when a team is
    // renamed, restyled or removed.
    setTeams(teams) {
        const text = JSON.stringify(teams);
        if (text !== this.teamsText) {
            this.teamsText = text;
            this.teamsVersion = (this.teamsVersion || 0) + 1;
        }
        this.teams = teams;
    }

    team(id) {
        return this.teams.find((x) => x.id === id) || null;
    }

    // The name of a team of the registry, or for a team that the registry no longer holds the name
    // that a request kept, marked as removed, that of `kept` or else of the newest request that
    // shows the team, or Removed team alone for a request of before that kept none.
    teamName(id, kept = null) {
        if (id === RANDOM) {
            return t('matches.team.random');
        }
        const x = this.team(id);
        if (x) {
            return teamName(x);
        }
        const name = keptName(kept) || this.keptName(id);
        return name ? t('matches.team.removed.named', { name }) : t('matches.team.removed');
    }

    // The name that the newest request showing a team kept for it, or the empty text.
    keptName(id) {
        for (const r of this.requests) {
            const names = Array.isArray(r.team_names) ? r.team_names : [];
            const at = shownTeams(r).indexOf(id);
            const name = at >= 0 ? keptName(names[at]) : '';
            if (name) {
                return name;
            }
        }
        return '';
    }

    // The second line of a team in the team lists and the Team filter, its kind and format, or
    // the identifier of a team that the registry no longer holds.
    teamHint(id) {
        const x = this.team(id);
        if (!x) {
            return id;
        }
        return x.kind === 'builtin' ? t('matches.team.builtin.hint')
            : FORMAT_NAMES[x.format] ? t('matches.team.submission.hint', { format: FORMAT_NAMES[x.format], count: controlledPlayers(x) }) : t('matches.team.submission');
    }

    render() {
        if (this.error) {
            this.built = false;
            this.root.replaceChildren(h('div', { class: 'page-pad' }, h('div', { class: 'notice error' },
                h('p', {}, this.error.message),
                h('p', { class: 'muted' }, tn('matches.offline.hint')),
                h('button', { class: 'btn', type: 'button', ...symbolOnly(t('matches.offline.retry')), onclick: () => this.refresh() }, icon('refresh')))));
            return;
        }
        const s = this.state;
        if (s.left !== RANDOM && !this.team(s.left)) {
            s.left = (this.teams.find((x) => x.kind !== 'builtin') || this.teams[0] || {}).id || null;
        }
        if (s.right !== RANDOM && !this.team(s.right)) {
            s.right = (this.teams.find((x) => x.kind === 'builtin') || this.teams[0] || {}).id || null;
        }
        if (!this.built) {
            this.build();
        }
        this.updateSetup();
        this.renderQueue();
    }

    // The page is built once, later refreshes update its parts in place.
    build() {
        this.built = true;
        // A page built again, as after an error, takes away the lists of the sides it built before.
        for (const side of this.sides || []) {
            side.dropdown.close(false);
            side.dropdown.panel.remove();
        }
        this.sides = [0, 1].map((side) => this.sidePicker(side));
        this.scenarioSelect = h('select', { 'aria-label': t('matches.setup.scenario') });
        this.scenarioSelect.addEventListener('change', () => {
            this.state.scenario = this.scenarioSelect.value;
            // The cards of random sides count the teams that the scenario lets them draw.
            this.updateSetup();
        });
        this.scenarioText = h('p', { class: 'scenario-text muted small', 'aria-live': 'polite' });
        this.seedInput = h('input', { type: 'number', min: '0', step: '1', placeholder: t('matches.setup.seed.placeholder'), value: this.state.seed, 'aria-label': t('matches.setup.seed.label') });
        this.seedInput.addEventListener('input', () => {
            this.state.seed = this.seedInput.value;
        });
        this.clash = h('div', { class: 'clash', role: 'alert', hidden: true });
        this.pool = this.buildPool();
        this.playButton = h('button', { type: 'button', class: 'btn primary play-btn', onclick: () => this.play() },
            icon('play'), t('matches.setup.play'));
        this.queueHost = h('div', { class: 'queue-list' });
        this.filterBar = this.buildFilters();
        const setup = h('section', { class: 'match-setup', 'aria-labelledby': 'setup-title' },
            h('header', { class: 'setup-head' },
                h('h2', { id: 'setup-title' }, t('matches.setup.title')),
                h('p', { class: 'muted' }, tn('matches.setup.text'))),
            h('div', { class: 'versus' }, this.sides[0].root, h('div', { class: 'vs', 'aria-hidden': 'true' }, t('matches.versus')), this.sides[1].root),
            this.pool.root,
            h('div', { class: 'setup-row' },
                h('label', { class: 'field' }, t('matches.setup.scenario'), this.scenarioSelect),
                h('label', { class: 'field seed-field' }, t('matches.setup.seed'),
                    h('span', { class: 'row' }, this.seedInput,
                        h('button', { type: 'button', class: 'btn ghost', ...symbolOnly(t('matches.setup.draw'), t('matches.setup.draw.title')), onclick: () => this.drawSeed() }, icon('dice'))))),
            this.scenarioText,
            this.clash,
            h('div', { class: 'play-row' }, this.playButton));
        const queue = h('section', { class: 'match-queue', 'aria-labelledby': 'queue-title' },
            h('header', { class: 'queue-head' }, h('h2', { id: 'queue-title' }, t('matches.queue.title')), this.filterBar),
            this.queueHost);
        this.root.replaceChildren(h('div', { class: 'matches-layout' }, setup, queue));
        enhanceSelect(this.scenarioSelect, { label: t('matches.setup.scenario'), className: 'wide' });
    }

    // The short text of the chosen scenario under the list.
    describeScenario() {
        const sc = this.state.scenario || '';
        this.scenarioText.textContent = sc === RANDOM ? t('matches.setup.scenario.random.text') : scenarioText(sc);
    }

    // The pool of the draw, a box to tick for each team that a random side may draw, and whether a
    // team may meet itself. It shows while a side is Random.
    buildPool() {
        const list = h('div', { class: 'draw-pool-list' });
        const same = h('input', { type: 'checkbox' });
        same.addEventListener('change', () => {
            this.state.sameTeam = same.checked;
            this.updateSetup();
        });
        const root = h('fieldset', { class: 'draw-pool', hidden: true },
            h('legend', {}, t('matches.draw.title')),
            h('p', { class: 'muted small' }, tn('matches.draw.text')),
            list,
            h('label', { class: 'check' }, same, t('matches.draw.sameTeam')));
        return { root, list, same, key: '' };
    }

    // Why a team of the pool cannot be drawn in the chosen scenario, by any random side, or the
    // empty text when it can. A random scenario asks for a scenario that both sides can play.
    poolFault(x, scenario) {
        const s = this.state;
        const random = [0, 1].filter((side) => [s.left, s.right][side] === RANDOM);
        if (!scenario || scenario === RANDOM) {
            const fitting = fittingScenarios(this.scenarios, this.teams, new Set(), s.left, s.right, this.formations);
            return fitting.some((sc) => random.some((side) => fits(x, sc, side, this.formations))) ? '' : t('matches.draw.unfit.none');
        }
        const faults = random.map((side) => unfit(x, scenario, side, this.formations));
        const fault = faults.every(Boolean) ? faults[0] : null;
        if (!fault) {
            return '';
        }
        return fault.id === 'matches.draw.unfit.format'
            ? t('matches.draw.unfit.format', { format: FORMAT_NAMES[fault.values.format] || fault.values.format })
            : t('matches.draw.unfit.control', { reason: t(fault.id, fault.values) });
    }

    // Fills the boxes of the pool when the registry changes, and ticks them as the state says, so
    // a box keeps its focus while the person ticks it. A team that cannot be drawn in the chosen
    // scenario shows faded, with the reason as its tooltip and for a screen reader.
    fillPool(scenario = this.state.scenario) {
        const pool = this.pool;
        const key = this.teams.map((x) => `${x.id}|${teamName(x)}`).join('\n');
        if (key !== pool.key) {
            pool.key = key;
            pool.list.replaceChildren(...this.teams.map((x, i) => {
                const box = h('input', { type: 'checkbox', value: x.id });
                box.addEventListener('change', () => {
                    if (box.checked) {
                        this.state.unticked.delete(x.id);
                    } else {
                        this.state.unticked.add(x.id);
                    }
                    this.updateSetup();
                });
                return h('label', { class: 'check draw-pool-team', 'data-id': x.id }, box, kitShirt(x, i % 2), h('span', {}, teamName(x)),
                    h('span', { class: 'sr-only draw-pool-fault' }));
            }));
        }
        for (const row of pool.list.querySelectorAll('.draw-pool-team')) {
            const x = this.team(row.dataset.id);
            const fault = x ? this.poolFault(x, scenario) : '';
            row.classList.toggle('unfit', !!fault);
            row.title = fault;
            row.querySelector('.draw-pool-fault').textContent = fault ? `, ${fault}` : '';
        }
        for (const box of pool.list.querySelectorAll('input')) {
            box.checked = !this.state.unticked.has(box.value);
        }
        pool.same.checked = this.state.sameTeam;
    }

    // One side of the match, a large card of the chosen team that opens a list of every team.
    sidePicker(side) {
        const teamLabel = t(side ? 'matches.side.right.team' : 'matches.side.left.team');
        const button = h('button', { type: 'button', class: 'team-card', 'aria-label': teamLabel });
        const panel = h('div', { role: 'menu', class: 'team-menu', 'aria-label': teamLabel });
        document.getElementById('app').appendChild(panel);
        const fill = () => {
            const current = side ? this.state.right : this.state.left;
            const random = menuItem(t('matches.team.random'), {
                checked: current === RANDOM,
                hint: t('matches.team.random.hint'),
                icon: icon('dice'),
                onSelect: () => {
                    this.state[side ? 'right' : 'left'] = RANDOM;
                    this.updateSetup();
                },
            });
            panel.replaceChildren(random, ...this.teams.map((x, i) => menuItem(teamName(x), {
                checked: x.id === current,
                hint: this.teamHint(x.id),
                icon: kitShirt(x, i % 2),
                onSelect: () => {
                    this.state[side ? 'right' : 'left'] = x.id;
                    this.updateSetup();
                },
            })));
        };
        const dropdown = new Dropdown(button, panel, { onOpen: fill, align: side ? 'right' : 'left' });
        // The ability of the built-in AI on this side, GRF's team difficulty, which steers every
        // player the built-in AI controls. Left alone it is the scenario's own.
        const name = side ? 'right' : 'left';
        const own = h('input', { type: 'checkbox', 'aria-label': t(`matches.side.${name}.ability.set`) });
        const range = h('input', {
            type: 'range', min: '0', max: '1', step: '0.05', value: '0.5', disabled: true,
            'aria-label': t(`matches.side.${name}.ability.range`),
        });
        const shown = h('output', { class: 'ability-value' }, t('matches.ability.scenario'));
        const sync = () => {
            const value = own.checked ? Number(range.value) : null;
            this.state.ability[side] = value;
            range.disabled = !own.checked;
            shown.textContent = value === null ? t('matches.ability.scenario') : abilityText(value);
        };
        own.addEventListener('change', sync);
        range.addEventListener('input', sync);
        const ability = h('div', { class: 'ability', title: t('matches.ability.title') },
            h('label', { class: 'check' }, own, t('matches.ability')), range, shown);
        const root = h('div', { class: `side side-${side ? 'right' : 'left'}` },
            h('div', { class: 'side-label' }, t(`matches.side.${name}`)), button, ability);
        return { root, button, dropdown };
    }

    updateSetup() {
        if (!this.built) {
            return;
        }
        const s = this.state;
        const { listed, keep } = scenarioChoices(this.scenarios, this.teams, s.unticked, s.left, s.right, s.scenario, DEFAULT_SCENARIO, this.formations);
        [s.left, s.right].forEach((id, side) => {
            const x = this.team(id);
            const card = this.sides[side].button;
            card.title = '';
            if (id === RANDOM) {
                card.replaceChildren(
                    h('span', { class: 'kit-shirt large team-card-random', 'aria-hidden': 'true' }, icon('dice')),
                    h('span', { class: 'team-card-text' },
                        h('span', { class: 'team-card-name' }, t('matches.team.random')),
                        h('span', { class: 'team-card-meta' }, t('matches.team.random.meta', { count: drawableTeams(this.teams, s.unticked, { ...s, scenario: keep }, side, this.scenarios, this.formations).length }))),
                    h('span', { class: 'dd-caret', 'aria-hidden': 'true' }));
                return;
            }
            if (!x) {
                card.replaceChildren(h('span', { class: 'team-card-empty' }, t('matches.team.none')));
                return;
            }
            // A submission shows its format and the players it controls, and its whole control
            // setting as the tooltip of the card.
            const builtin = x.kind === 'builtin';
            card.title = builtin ? '' : t('matches.team.submission.title', { control: controlLabel(x.control, x.format) });
            card.replaceChildren(
                kitShirt(x, side, 'large'),
                h('span', { class: 'team-card-text' },
                    h('span', { class: 'team-card-name' }, teamName(x)),
                    h('span', { class: 'team-card-meta' }, builtin ? t('matches.team.builtin.meta') : t('matches.team.submission.meta', { format: FORMAT_NAMES[x.format] || x.format, count: controlledPlayers(x) }))),
                h('span', { class: 'dd-caret', 'aria-hidden': 'true' }));
        });
        const random = [s.left, s.right].includes(RANDOM);
        const l = s.left === RANDOM ? null : this.team(s.left);
        const r = s.right === RANDOM ? null : this.team(s.right);
        const chosen = (l || s.left === RANDOM) && (r || s.right === RANDOM);
        const clash = l && r && l.kind !== 'builtin' && r.kind !== 'builtin' && l.format && r.format && l.format !== r.format;
        if (clash) {
            this.clash.replaceChildren(...tn('matches.setup.clash'));
        } else if (!chosen) {
            this.clash.replaceChildren(t('matches.setup.noTeams'));
        }
        this.clash.hidden = !clash && !!chosen;
        this.pool.root.hidden = !random;
        if (random) {
            this.fillPool(keep);
        }
        const name = (sc) => (sc === RANDOM ? t('matches.setup.scenario.random') : scenarioName(sc));
        this.scenarioSelect.replaceChildren(...(listed.length ? listed : [t('matches.setup.noScenario')]).map((sc) =>
            h('option', { value: listed.length ? sc : '' }, listed.length ? name(sc) : sc)));
        this.scenarioSelect.value = keep || '';
        this.scenarioSelect.disabled = !listed.length;
        s.scenario = keep || null;
        this.describeScenario();
        this.playButton.disabled = !listed.length || !chosen;
    }

    drawSeed() {
        const v = crypto.getRandomValues(new Uint32Array(1))[0];
        this.seedInput.value = String(v);
        this.state.seed = this.seedInput.value;
    }

    async play() {
        const s = this.state;
        const text = this.seedInput.value.trim();
        if (text !== '' && !/^\d+$/.test(text)) {
            this.app.hud.toast(t('matches.setup.seed.invalid'), 'error');
            return;
        }
        this.playButton.disabled = true;
        try {
            await api.requestMatch(requestOf(s, this.teams, text === '' ? null : text));
            this.app.hud.toast(t('matches.toast.queued', { left: this.teamName(s.left), right: this.teamName(s.right) }));
            this.playButton.classList.remove('kicked');
            void this.playButton.offsetWidth;
            this.playButton.classList.add('kicked');
            this.requests = await api.requests();
            this.renderQueue();
        } catch (err) {
            this.app.hud.toast(err.message, 'error', 7000);
        } finally {
            this.updateSetup();
        }
    }

    buildFilters() {
        const select = (key, label, options) => {
            const el = h('select', { 'aria-label': label }, options.map(([v, text]) => h('option', { value: v }, text)));
            el.value = this.filters[key];
            el.addEventListener('change', () => {
                this.filters[key] = el.value;
                this.renderQueue();
            });
            return el;
        };
        this.statusFilter = select('status', t('matches.filter.status'), [['all', t('matches.filter.status.all')], ['active', t('matches.filter.status.active')], ['done', STATE_LABELS.done], ['failed', STATE_LABELS.failed], ['cancelled', STATE_LABELS.cancelled], ['interrupted', STATE_LABELS.interrupted]]);
        this.teamFilter = select('team', t('matches.filter.team'), [['all', t('matches.filter.team.all')]]);
        this.scenarioFilter = select('scenario', t('matches.filter.scenario'), [['all', t('matches.filter.scenario.all')]]);
        this.dateFilter = select('date', t('matches.filter.date'), [['any', t('matches.filter.date.any')], ['hour', t('matches.filter.date.hour')], ['today', t('matches.filter.date.today')], ['week', t('matches.filter.date.week')]]);
        this.sortSelect = select('sort', t('matches.filter.sort'), [['newest', t('matches.filter.sort.newest')], ['oldest', t('matches.filter.sort.oldest')]]);
        const bar = h('div', { class: 'filter-bar' }, this.statusFilter, this.teamFilter, this.scenarioFilter, this.dateFilter, this.sortSelect);
        queueMicrotask(() => {
            enhanceSelect(this.statusFilter, { label: t('matches.filter.status'), icon: 'filter' });
            enhanceSelect(this.teamFilter, { label: t('matches.filter.team'), icon: 'shirt' });
            enhanceSelect(this.scenarioFilter, { label: t('matches.filter.scenario'), icon: 'field' });
            enhanceSelect(this.dateFilter, { label: t('matches.filter.date'), icon: 'calendar' });
            enhanceSelect(this.sortSelect, { label: t('matches.filter.sort'), icon: 'sort', align: 'right' });
        });
        return bar;
    }

    // The team and scenario filters list what the requests show, as queue-filters.js describes.
    refillFilters() {
        const fill = (select, key, all, entries) => {
            const keep = this.filters[key];
            const want = [['all', all], ...entries];
            const now = [...select.options].map((o) => `${o.value}|${o.textContent}|${o.dataset.hint || ''}`).join('\n');
            if (now !== want.map(([v, text, hint]) => `${v}|${text}|${hint || ''}`).join('\n')) {
                select.replaceChildren(...want.map(([v, text, hint]) => h('option', { value: v, 'data-hint': hint || null }, text)));
            }
            this.filters[key] = want.some(([v]) => v === keep) ? keep : 'all';
            select.value = this.filters[key];
        };
        fill(this.teamFilter, 'team', t('matches.filter.team.all'), filterTeams(this.requests, this.teams).map((id) => [teamValue(id), this.teamName(id), this.teamHint(id)]));
        fill(this.scenarioFilter, 'scenario', t('matches.filter.scenario.all'), filterScenarios(this.requests).map((s) => [scenarioValue(s), scenarioName(s)]));
    }

    renderQueue() {
        if (!this.built) {
            return;
        }
        this.refillFilters();
        const f = this.filters;
        let rows = this.requests.filter((r) => {
            const st = stateOf(r);
            if (f.status === 'active' && st !== 'queued' && st !== 'running') {
                return false;
            }
            if (f.status !== 'all' && f.status !== 'active' && st !== f.status) {
                return false;
            }
            if (!passesTeam(r, f.team)) {
                return false;
            }
            if (f.date !== 'any') {
                const when = requestTime(r);
                const now = new Date();
                const from = f.date === 'hour' ? now.getTime() - 36e5
                    : f.date === 'today' ? new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
                        : now.getTime() - 7 * 864e5;
                if (!when || when.getTime() < from) {
                    return false;
                }
            }
            return passesScenario(r, f.scenario);
        });
        // The server lists the requests newest first.
        if (f.sort === 'oldest') {
            rows = rows.slice().reverse();
        }
        if (!this.requests.length) {
            this.queueHost.replaceChildren(h('div', { class: 'empty-state' },
                h('p', { class: 'empty-title' }, t('matches.queue.empty.title')),
                h('p', { class: 'muted' }, tn('matches.queue.empty.text'))));
            return;
        }
        if (!rows.length) {
            this.queueHost.replaceChildren(h('p', { class: 'muted pad' }, t('matches.queue.filtered')));
            return;
        }
        const more = rows.length - this.limit;
        rows = rows.slice(0, this.limit);
        // Rows are kept by request, so a progress bar moves smoothly instead of being redrawn.
        const old = new Map([...this.queueHost.querySelectorAll('.req-card')].map((el) => [el.dataset.id, el]));
        const list = this.queueHost.querySelector('.req-cards') || h('ul', { class: 'req-cards' });
        const items = rows.map((r) => {
            const key = `${r.id}|${stateOf(r)}|${r.match || ''}|${r.error || ''}|${r.persistence_error || ''}|${this.teamsVersion}`;
            let li = old.get(r.id);
            if (!li || li.dataset.key !== key) {
                li = this.requestCard(r);
                li.dataset.key = key;
            }
            const played = li.querySelector('.req-played');
            const seconds = playedSeconds(r);
            if (played && seconds !== null) {
                played.textContent = t('matches.request.played', { count: seconds });
            }
            const bar = li.querySelector('.progress .bar');
            if (bar) {
                const pct = Math.round((r.progress || 0) * 100);
                bar.style.width = `${pct}%`;
                const label = li.querySelector('.pct');
                if (label) {
                    label.textContent = t('matches.request.percent', { pct });
                }
            }
            return li;
        });
        list.replaceChildren(...items);
        if (list.parentNode !== this.queueHost) {
            this.queueHost.replaceChildren(list);
        }
        this.showMore(more);
    }

    // The button under the list that shows the next rows, kept in place while it has focus.
    showMore(more) {
        let button = this.queueHost.querySelector('.req-more');
        if (more <= 0) {
            if (button && button === document.activeElement) {
                // The last rows take the focus of the button that showed them.
                this.queueHost.querySelector('.req-card:last-child button')?.focus();
            }
            button?.remove();
            return;
        }
        if (!button) {
            button = h('button', { type: 'button', class: 'btn small ghost req-more', onclick: () => {
                this.limit += REQUEST_PAGE;
                this.renderQueue();
            } });
            this.queueHost.appendChild(button);
        }
        button.textContent = t('matches.queue.more', { shown: Math.min(more, REQUEST_PAGE), count: more });
    }

    requestCard(r) {
        const st = stateOf(r);
        const when = requestTime(r);
        const parts = drawnParts(r);
        // A part drawn at random shows as Random while the match waits, and as what was drawn,
        // with a mark, once it starts.
        const drawnMark = () => h('span', { class: 'req-drawn', title: t('matches.request.drawn') },
            icon('dice'), h('span', { class: 'sr-only' }, t('matches.request.drawn')));
        const side = (id, i) => {
            const part = i ? 'right' : 'left';
            if (hiddenPart(r, part)) {
                return h('span', { class: 'req-team req-random' }, icon('dice'), h('span', { class: 'req-team-name' }, t('matches.team.random')));
            }
            const x = this.team(id);
            const kept = Array.isArray(r.team_names) ? r.team_names[i] : null;
            return h('span', { class: 'req-team' }, x ? kitShirt(x, i) : null, h('span', { class: 'req-team-name', title: x ? null : id }, this.teamName(id, kept)),
                parts[part] ? drawnMark() : null);
        };
        const scenario = hiddenPart(r, 'scenario') ? h('span', {}, t('matches.setup.scenario.random'))
            : h('span', {}, scenarioName(r.scenario), parts.scenario ? drawnMark() : null);
        const actions = [];
        if (st === 'queued' || st === 'running') {
            actions.push(h('button', { type: 'button', class: 'btn small ghost danger', ...symbolOnly(t('matches.request.cancel')), onclick: () => this.cancel(r) }, icon('close')));
        }
        if (st === 'done' && r.match) {
            actions.push(h('button', { type: 'button', class: 'btn small primary', onclick: () => this.app.openMatchInWatch(r.match) },
                icon('play'), t('matches.request.watch')));
        }
        if (st !== 'queued' && st !== 'running') {
            // Retry and Repeat queue a new request with the same seed, teams, scenario and ability.
            // A match drawn at random repeats with a new seed, which draws again.
            const again = st === 'done' ? 'repeat' : 'retry';
            const title = wasDrawn(r) ? `matches.request.${again}.draw.title` : `matches.request.${again}.title`;
            actions.push(h('button', { type: 'button', class: 'btn small', ...symbolOnly(t(`matches.request.${again}`), t(title, { seed: r.seed })),
                onclick: (event) => this.again(r, event.currentTarget, again === 'repeat') }, icon(again === 'repeat' ? 'replay' : 'refresh')));
        }
        const li = h('li', { class: `req-card state-${st}`, 'data-id': r.id },
            h('div', { class: 'req-main' },
                h('div', { class: 'req-teams' }, side(r.left, 0), h('span', { class: 'req-vs' }, t('matches.versus')), side(r.right, 1)),
                h('div', { class: 'req-meta' },
                    stateBadge(st, STATE_LABELS[st] || st),
                    scenario,
                    r.seed != null ? h('span', {}, t('matches.request.seed', { seed: r.seed })) : null,
                    Array.isArray(r.ability) && r.ability.some((v) => v !== null)
                        ? h('span', {}, t('matches.request.ability', Object.fromEntries(['left', 'right'].map((key, i) => [key, r.ability[i] === null ? t('matches.request.ability.scenario') : abilityText(r.ability[i])]))))
                        : null,
                    when ? h('span', {}, new Intl.DateTimeFormat(uiLocale(), { timeStyle: 'short', dateStyle: 'medium' }).format(when)) : null,
                    h('span', { class: 'req-played' })),
                st === 'queued' || st === 'running'
                    ? h('div', { class: 'req-progress' },
                        h('div', { class: `progress${st === 'queued' ? ' waiting' : ''}` }, h('div', { class: 'bar' })),
                        h('span', { class: 'pct muted small' }, st === 'queued' ? t('matches.request.queued') : ''))
                    : null,
                (st === 'failed' || st === 'interrupted') && r.error ? h('div', { class: 'error-text' }, serverText(r, 'error')) : null,
                r.persistence_error ? h('div', { class: 'error-text' }, serverText(r, 'persistence_error')) : null),
            h('div', { class: 'req-actions' }, actions));
        if (st === 'queued') {
            li.querySelector('.pct').classList.remove('pct');
        }
        return li;
    }

    async again(r, button, repeat = false) {
        button.disabled = true;
        try {
            const spec = againOf(r, repeat);
            await api.requestMatch(spec);
            const names = { left: this.teamName(spec.left), right: this.teamName(spec.right) };
            this.app.hud.toast(spec.seed == null ? t('matches.toast.queued', names) : t('matches.toast.queuedSeed', { ...names, seed: r.seed }));
            this.requests = await api.requests();
            this.renderQueue();
        } catch (err) {
            this.app.hud.toast(err.message, 'error', 7000);
            button.disabled = false;
        }
    }

    async cancel(r) {
        try {
            await api.cancelRequest(r.id);
            this.seen.add(r.id);
            this.app.hud.toast(t('matches.toast.cancelled'));
        } catch (err) {
            this.app.hud.toast(err.status === 404 ? t('matches.toast.ended') : err.message, 'error');
        }
        try {
            this.requests = await api.requests();
        } catch {
            // The next poll tries again.
        }
        this.renderQueue();
    }

    // Watches the queue in the background and tells when a match is ready or failed.
    async poll() {
        if (document.hidden || document.body.classList.contains('offline')) {
            return;
        }
        const active = this.requests.some((r) => r.state === 'queued' || r.state === 'running');
        if (!active && this.primed && !this.visible) {
            // Nothing runs, a slower check is enough while the page is elsewhere.
            this.idleTicks = (this.idleTicks || 0) + 1;
            if (this.idleTicks % 6) {
                return;
            }
        }
        let list;
        try {
            list = await api.requests();
        } catch {
            return;
        }
        // A request may name a team added since the page loaded the registry, from the command
        // line or another tab, and the page then loads the registry again, once for each such
        // team, so a team that was removed is not looked up on every check.
        const before = this.teamsVersion;
        const unknown = unknownTeams(list, this.teams).filter((id) => !this.looked.has(id));
        if (unknown.length) {
            try {
                this.setTeams(await api.teams());
                unknown.forEach((id) => this.looked.add(id));
            } catch {
                // The next check tries again.
            }
        }
        for (const r of list) {
            const st = stateOf(r);
            if ((st === 'done' || st === 'failed' || st === 'cancelled') && !this.seen.has(r.id)) {
                this.seen.add(r.id);
                if (this.primed && st === 'done') {
                    this.app.hud.toast(t(this.visible ? 'matches.toast.ready' : 'matches.toast.ready.away', { left: this.teamName(r.left), right: this.teamName(r.right) }), 'info', 6000);
                } else if (this.primed && st === 'failed') {
                    this.app.hud.toast(t('matches.toast.failed', { error: r.error ? serverText(r, 'error') : '' }), 'error', 7000);
                }
            }
        }
        this.primed = true;
        const changed = JSON.stringify(list) !== JSON.stringify(this.requests);
        this.requests = list;
        if (this.teamsVersion !== before && this.visible) {
            this.render();
        } else if (changed && this.visible) {
            this.renderQueue();
        }
    }
}
