// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The Matches page, where two teams are picked for a match that plays on this computer, and the
// queue of requested matches with their progress, cancelling and watching.

import { api, controlLabel, uiLocale } from '../core/api.js';
import { formatNumber, serverText, t } from '../core/i18n.js';
import { css, normalizeStyle } from '../players/kits.js';
import { Dropdown, el as h, enhanceSelect, icon, menuItem } from '../core/menu.js';
import { teamName } from '../core/names.js';
import { listedScenarios, scenarioName, scenarioText } from '../core/scenarios.js';

const DEFAULT_SCENARIO = '11_vs_11_kaggle';
const FORMAT_NAMES = { '5v5': t('matches.format.5v5'), '11v11': t('matches.format.11v11') };
// The list of requested matches shows this many more rows each time Show more is pressed.
export const REQUEST_PAGE = 50;

// Scenarios a team may play, by its format. The built-in AI plays any.
export function fits(team, scenario) {
    if (!team || team.kind === 'builtin' || !team.format) {
        return true;
    }
    if (scenario.startsWith('academy_')) return true;
    const name = scenario.replace(/^benchmark_full_game_/, '');
    return team.format === '5v5' ? name.startsWith('5_vs_5') : name.startsWith('11_vs_11');
}

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

function stateOf(r) {
    if (r.state === 'failed' && r.error === 'cancelled') {
        return 'cancelled';
    }
    // A restart of the server marks the requests that waited or played as interrupted.
    if (r.state === 'failed' && typeof r.error === 'string' && r.error.startsWith('interrupted by a server restart')) {
        return 'interrupted';
    }
    return r.state;
}

const STATE_LABELS = {
    queued: t('matches.state.queued'), running: t('matches.state.running'), done: t('matches.state.done'),
    failed: t('matches.state.failed'), cancelled: t('matches.state.cancelled'), interrupted: t('matches.state.interrupted'),
};

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
        this.teams = [];
        this.scenarios = [];
        this.requests = [];
        this.seen = new Set();
        this.primed = false;
        this.state = { left: null, right: 'builtin', scenario: null, seed: '', ability: [null, null] };
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
        try {
            const [teams, scenarios, requests] = await Promise.all([
                api.teams(), api.scenarios().catch(() => []), api.requests().catch(() => []),
            ]);
            if (token !== this.token) {
                return;
            }
            this.teams = teams;
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

    team(id) {
        return this.teams.find((x) => x.id === id) || null;
    }

    teamName(id) {
        const x = this.team(id);
        return x ? teamName(x) : id;
    }

    render() {
        if (this.error) {
            this.built = false;
            this.root.replaceChildren(h('div', { class: 'page-pad' }, h('div', { class: 'notice error' },
                h('p', {}, this.error.message),
                h('p', { class: 'muted' }, t('matches.offline.hint')),
                h('button', { class: 'btn', type: 'button', onclick: () => this.refresh() }, t('matches.offline.retry')))));
            return;
        }
        const s = this.state;
        if (!this.team(s.left)) {
            s.left = (this.teams.find((x) => x.kind !== 'builtin') || this.teams[0] || {}).id || null;
        }
        if (!this.team(s.right)) {
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
        this.sides = [0, 1].map((side) => this.sidePicker(side));
        this.scenarioSelect = h('select', { 'aria-label': t('matches.setup.scenario') });
        this.scenarioSelect.addEventListener('change', () => {
            this.state.scenario = this.scenarioSelect.value;
            this.describeScenario();
        });
        this.scenarioText = h('p', { class: 'scenario-text muted small', 'aria-live': 'polite' });
        this.seedInput = h('input', { type: 'number', min: '0', step: '1', placeholder: t('matches.setup.seed.placeholder'), value: this.state.seed, 'aria-label': t('matches.setup.seed.label') });
        this.seedInput.addEventListener('input', () => {
            this.state.seed = this.seedInput.value;
        });
        this.clash = h('div', { class: 'clash', role: 'alert', hidden: true });
        this.playButton = h('button', { type: 'button', class: 'btn primary play-btn', onclick: () => this.play() },
            icon('play'), t('matches.setup.play'));
        this.queueHost = h('div', { class: 'queue-list' });
        this.filterBar = this.buildFilters();
        const setup = h('section', { class: 'match-setup', 'aria-labelledby': 'setup-title' },
            h('header', { class: 'setup-head' },
                h('h2', { id: 'setup-title' }, t('matches.setup.title')),
                h('p', { class: 'muted' }, t('matches.setup.text'))),
            h('div', { class: 'versus' }, this.sides[0].root, h('div', { class: 'vs', 'aria-hidden': 'true' }, t('matches.versus')), this.sides[1].root),
            h('div', { class: 'setup-row' },
                h('label', { class: 'field' }, t('matches.setup.scenario'), this.scenarioSelect),
                h('label', { class: 'field seed-field' }, t('matches.setup.seed'),
                    h('span', { class: 'row' }, this.seedInput,
                        h('button', { type: 'button', class: 'btn ghost', title: t('matches.setup.draw.title'), onclick: () => this.drawSeed() }, t('matches.setup.draw'))))),
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
        this.scenarioText.textContent = scenarioText(this.state.scenario || '');
    }

    // One side of the match, a large card of the chosen team that opens a list of every team.
    sidePicker(side) {
        const teamLabel = t(side ? 'matches.side.right.team' : 'matches.side.left.team');
        const button = h('button', { type: 'button', class: 'team-card', 'aria-label': teamLabel });
        const panel = h('div', { role: 'menu', class: 'team-menu', 'aria-label': teamLabel });
        document.getElementById('app').appendChild(panel);
        const fill = () => {
            const current = side ? this.state.right : this.state.left;
            panel.replaceChildren(...this.teams.map((x, i) => menuItem(teamName(x), {
                checked: x.id === current,
                hint: x.kind === 'builtin' ? t('matches.team.builtin.hint')
                    : FORMAT_NAMES[x.format] ? t('matches.team.submission.hint', { format: FORMAT_NAMES[x.format] }) : t('matches.team.submission'),
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
        [s.left, s.right].forEach((id, side) => {
            const x = this.team(id);
            const card = this.sides[side].button;
            if (!x) {
                card.replaceChildren(h('span', { class: 'team-card-empty' }, t('matches.team.none')));
                return;
            }
            card.replaceChildren(
                kitShirt(x, side, 'large'),
                h('span', { class: 'team-card-text' },
                    h('span', { class: 'team-card-name' }, teamName(x)),
                    h('span', { class: 'team-card-meta' }, x.kind === 'builtin' ? t('matches.team.builtin.meta') : t('matches.team.submission.meta', { format: FORMAT_NAMES[x.format] || x.format, control: controlLabel(x.control, x.format) }))),
                h('span', { class: 'dd-caret', 'aria-hidden': 'true' }));
        });
        const l = this.team(s.left);
        const r = this.team(s.right);
        const clash = l && r && l.kind !== 'builtin' && r.kind !== 'builtin' && l.format && r.format && l.format !== r.format;
        let ok = this.scenarios.filter((sc) => fits(l, sc) && fits(r, sc));
        if (clash) {
            ok = ok.filter((sc) => sc.startsWith('academy_'));
            this.clash.replaceChildren(t('matches.setup.clash'));
        } else if (!l || !r) {
            this.clash.replaceChildren(t('matches.setup.noTeams'));
        }
        this.clash.hidden = !clash && !!(l && r);
        const keep = ok.includes(s.scenario) ? s.scenario
            : ok.includes(DEFAULT_SCENARIO) ? DEFAULT_SCENARIO
                : ok.includes('5_vs_5') ? '5_vs_5' : ok[0];
        this.scenarioSelect.replaceChildren(...(ok.length ? ok : [t('matches.setup.noScenario')]).map((sc) =>
            h('option', { value: ok.length ? sc : '' }, ok.length ? scenarioName(sc) : sc)));
        this.scenarioSelect.value = keep || '';
        this.scenarioSelect.disabled = !ok.length;
        s.scenario = keep || null;
        this.describeScenario();
        this.playButton.disabled = !ok.length || !l || !r;
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
            await api.requestMatch({ left: s.left, right: s.right, scenario: s.scenario, seed: text === '' ? null : text, ability: s.ability.slice() });
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
            enhanceSelect(this.statusFilter, { label: t('matches.filter.status'), prefix: t('matches.filter.status.prefix') });
            enhanceSelect(this.teamFilter, { label: t('matches.filter.team'), prefix: t('matches.filter.team') });
            enhanceSelect(this.scenarioFilter, { label: t('matches.filter.scenario'), prefix: t('matches.filter.scenario') });
            enhanceSelect(this.dateFilter, { label: t('matches.filter.date'), prefix: t('matches.filter.date') });
            enhanceSelect(this.sortSelect, { label: t('matches.filter.sort'), prefix: t('matches.filter.sort'), align: 'right' });
        });
        return bar;
    }

    // The team and scenario filters list what the requests hold.
    refillFilters() {
        const ids = [...new Set(this.requests.flatMap((r) => [r.left, r.right]))];
        const scenarios = [...new Set(this.requests.map((r) => r.scenario))].sort();
        const fill = (select, key, all, entries) => {
            const keep = this.filters[key];
            const want = [['all', all], ...entries];
            const now = [...select.options].map((o) => `${o.value}|${o.textContent}`).join('\n');
            if (now !== want.map(([v, text]) => `${v}|${text}`).join('\n')) {
                select.replaceChildren(...want.map(([v, text]) => h('option', { value: v }, text)));
            }
            this.filters[key] = want.some(([v]) => v === keep) ? keep : 'all';
            select.value = this.filters[key];
        };
        fill(this.teamFilter, 'team', t('matches.filter.team.all'), ids.map((id) => [id, this.teamName(id)]));
        fill(this.scenarioFilter, 'scenario', t('matches.filter.scenario.all'), scenarios.map((s) => [s, scenarioName(s)]));
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
            if (f.team !== 'all' && r.left !== f.team && r.right !== f.team) {
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
            return f.scenario === 'all' || r.scenario === f.scenario;
        });
        // The server lists the requests newest first.
        if (f.sort === 'oldest') {
            rows = rows.slice().reverse();
        }
        if (!this.requests.length) {
            this.queueHost.replaceChildren(h('div', { class: 'empty-state' },
                h('p', { class: 'empty-title' }, t('matches.queue.empty.title')),
                h('p', { class: 'muted' }, t('matches.queue.empty.text'))));
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
            const key = `${r.id}|${stateOf(r)}|${r.match || ''}|${r.error || ''}|${r.persistence_error || ''}`;
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
        const side = (id, i) => {
            const x = this.team(id);
            return h('span', { class: 'req-team' }, x ? kitShirt(x, i) : null, h('span', { class: 'req-team-name' }, this.teamName(id)));
        };
        const actions = [];
        if (st === 'queued' || st === 'running') {
            actions.push(h('button', { type: 'button', class: 'btn small ghost danger', onclick: () => this.cancel(r) }, t('matches.request.cancel')));
        }
        if (st === 'done' && r.match) {
            actions.push(h('button', { type: 'button', class: 'btn small primary', onclick: () => this.app.openMatchInWatch(r.match) },
                icon('play'), t('matches.request.watch')));
        }
        if (st !== 'queued' && st !== 'running') {
            // Retry and Repeat queue a new request with the same seed, teams, scenario and ability.
            const again = st === 'done' ? 'repeat' : 'retry';
            actions.push(h('button', { type: 'button', class: 'btn small', title: t(`matches.request.${again}.title`, { seed: r.seed }),
                onclick: (event) => this.again(r, event.currentTarget) }, t(`matches.request.${again}`)));
        }
        const li = h('li', { class: `req-card state-${st}`, 'data-id': r.id },
            h('div', { class: 'req-main' },
                h('div', { class: 'req-teams' }, side(r.left, 0), h('span', { class: 'req-vs' }, t('matches.versus')), side(r.right, 1)),
                h('div', { class: 'req-meta' },
                    h('span', { class: `state-pill ${st}` }, STATE_LABELS[st] || st),
                    h('span', {}, scenarioName(r.scenario)),
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

    async again(r, button) {
        button.disabled = true;
        try {
            await api.requestMatch({ left: r.left, right: r.right, scenario: r.scenario, seed: r.seed, ability: r.ability });
            this.app.hud.toast(t('matches.toast.queuedSeed', { left: this.teamName(r.left), right: this.teamName(r.right), seed: r.seed }));
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
        if (changed && this.visible) {
            this.renderQueue();
        }
    }
}
