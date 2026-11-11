// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The search of moments across the library, a panel of the Recordings page and entries of the
// command palette. A query goes to the server's index, `GET /api/search?q=`, in the small query
// language of the guide, such as `goal team:Greens after:60`, and the filters of the panel add
// their terms to it. A result opens Watch a few seconds before its moment.

import { formatDate } from '../core/api.js';
import { serverText, t } from '../core/i18n.js';
import { enhanceSelect } from '../core/menu.js';
import { composeQuery, looksLikeMoments as looksMoments } from '../recording/moments-query.js';

export { KIND_WORDS, composeQuery, looksLikeMoments } from '../recording/moments-query.js';

// The day a number of days before now, as the query language takes dates.
function daysAgo(days) {
    const d = new Date(Date.now() - days * 864e5);
    const pad = (x) => String(x).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// The choices of each filter, each a value of the query language with the message of its label,
// whose id ends in the value with its colons as dots, or in any for the empty value.
const choices = (group, values) => values.map((v) => [v, t(`moments.${group}.${v.replace(/:/g, '.') || 'any'}`)]);
const KIND_CHOICES = choices('kind', ['', 'goal', 'shot', 'save', 'block', 'pass', 'tackle', 'card', 'foul', 'offside',
    'set-piece', 'corner', 'free-kick', 'penalty', 'throw-in', 'possession', 'woodwork']);
const TIME_CHOICES = choices('time', ['', 'before:45', 'after:45', 'after:75', 'before:15']);
const SCORE_CHOICES = choices('score', ['', 'leading', 'level', 'trailing']);
const SOURCE_CHOICES = choices('source', ['', 'requested', 'game', 'tournament', 'challenge', 'recorder', 'live']);
const DATE_CHOICES = choices('date', ['', '0', '7', '30']);

function el(tag, attributes = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) {
        if (key.startsWith('on') && typeof value === 'function') {
            node.addEventListener(key.slice(2), value);
        } else if (value !== null && value !== undefined && value !== false) {
            node.setAttribute(key, value === true ? '' : value);
        }
    }
    node.append(...children.flat().filter((c) => c !== null && c !== undefined));
    return node;
}

async function fetchSearch(query, limit, signal = undefined) {
    const res = await fetch(`/api/search?q=${encodeURIComponent(query)}&limit=${limit}`, { cache: 'no-store', signal });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
        throw new Error(body.error ? serverText(body) : t('moments.serverStatus', { status: res.status }));
    }
    return body;
}

// Opens Watch a few seconds before a moment, seeking in place when its recording is open.
export function openMoment(app, result) {
    const tl = app.timeline;
    if (app.source && app.source.kind === 'match' && app.source.id === result.match && tl) {
        app.showPage('watch');
        if (app.director) {
            app.director.stop(false);
        }
        tl.seek(tl.first + result.seek * tl.sps);
        app.afterSeek();
        if (app.updatePlayUi) {
            app.updatePlayUi();
        }
        app.updateHash(true);
        return;
    }
    app.openMatch(result.match, result.seek);
}

export class MomentSearch {
    constructor(app) {
        this.app = app;
        this.text = '';
        this.filters = { kind: '', team: '', player: '', scenario: '', source: '', since: '', score: '', time: '' };
        this.date = '';
        this.open = false;
        this.results = null;
        this.error = null;
        this.token = 0;
        this.timer = null;
        this.palette = { query: null, results: [], busy: false };
    }

    // The query of the panel as it stands.
    query() {
        return composeQuery(this.text, { ...this.filters, since: this.date === '' ? '' : daysAgo(Number(this.date)) });
    }

    select(label, choices, value, pick) {
        const node = el('select', { 'aria-label': label }, choices.map(([v, t]) => el('option', { value: v }, t)));
        node.value = value;
        node.addEventListener('change', () => pick(node.value));
        queueMicrotask(() => enhanceSelect(node, { label, prefix: label }));
        return node;
    }

    // Builds the panel into a host of the Recordings page.
    mount(host, scenarios = [], teams = []) {
        this.host = host;
        this.toggle = el('button', {
            type: 'button', class: 'btn', id: 'moments-toggle', 'aria-expanded': this.open ? 'true' : 'false',
            'aria-controls': 'moments-panel', onclick: () => this.setOpen(!this.open),
        }, t('moments.toggle'));
        this.input = el('input', {
            type: 'search', id: 'moments-query', class: 'search', value: this.text, spellcheck: 'false',
            'aria-label': t('moments.query.label'), placeholder: t('moments.query.placeholder'),
            'aria-describedby': 'moments-help',
        });
        this.input.addEventListener('input', () => {
            this.text = this.input.value;
            this.schedule();
        });
        this.input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this.run();
            } else if (e.key === 'ArrowDown' && this.list && this.list.firstElementChild) {
                e.preventDefault();
                this.list.firstElementChild.focus();
            }
        });
        const pick = (key) => (value) => {
            this.filters[key] = value;
            this.run();
        };
        const player = el('input', {
            type: 'text', id: 'moments-player', class: 'small-input', value: this.filters.player,
            'aria-label': t('moments.player'), placeholder: t('moments.player'), spellcheck: 'false',
        });
        player.addEventListener('input', () => {
            this.filters.player = player.value;
            this.schedule();
        });
        const filters = el('div', { class: 'filter-bar moments-filters' },
            this.select(t('moments.filter.kind'), KIND_CHOICES, this.filters.kind, pick('kind')),
            this.select(t('moments.filter.team'), [['', t('moments.team.any')], ['left', t('moments.team.left')],
                ['right', t('moments.team.right')], ...teams.map((name) => [name, name])], this.filters.team, pick('team')),
            player,
            this.select(t('moments.filter.time'), TIME_CHOICES, this.filters.time, pick('time')),
            this.select(t('moments.filter.score'), SCORE_CHOICES, this.filters.score, pick('score')),
            this.select(t('moments.filter.scenario'), [['', t('moments.scenario.any')], ...scenarios.map(([v, name]) => [v, name])],
                this.filters.scenario, pick('scenario')),
            this.select(t('moments.filter.source'), SOURCE_CHOICES, this.filters.source, pick('source')),
            this.select(t('moments.filter.date'), DATE_CHOICES, this.date, (v) => {
                this.date = v;
                this.run();
            }));
        this.status = el('p', { class: 'muted small moments-status', role: 'status', 'aria-live': 'polite' });
        this.list = el('ul', { class: 'moments-list', id: 'moments-results', 'aria-label': t('moments.results') });
        this.list.addEventListener('keydown', (e) => this.onListKey(e));
        this.panel = el('section', { id: 'moments-panel', class: 'moments-panel', 'aria-label': t('moments.panel'), hidden: !this.open },
            el('div', { class: 'toolbar' }, this.input, filters),
            el('p', { id: 'moments-help', class: 'muted small' },
                t('moments.help')),
            this.status, this.list);
        host.replaceChildren(this.panel);
        this.renderResults();
        return this.toggle;
    }

    setOpen(open, focus = true) {
        this.open = !!open;
        if (this.panel) {
            this.panel.hidden = !this.open;
        }
        if (this.toggle) {
            this.toggle.setAttribute('aria-expanded', this.open ? 'true' : 'false');
        }
        if (this.open) {
            this.run();
            if (focus && this.input) {
                this.input.focus();
            }
        }
    }

    // Shows the panel with a query, from the palette or the Match menu.
    show(text) {
        this.text = text;
        this.app.showPage('recordings');
        const apply = () => {
            if (this.input) {
                this.input.value = text;
            }
            this.setOpen(true);
        };
        if (this.panel && this.panel.isConnected) {
            apply();
        } else {
            setTimeout(apply, 0);
        }
    }

    schedule() {
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.run(), 250);
    }

    async run() {
        clearTimeout(this.timer);
        if (!this.open) {
            return;
        }
        const token = ++this.token;
        const query = this.query();
        // An empty query names every moment of the library, so the panel waits for a word or a
        // filter and lists nothing until then.
        if (!query.trim()) {
            this.results = null;
            this.error = null;
            this.renderResults();
            if (this.status) {
                this.status.textContent = t('moments.status.empty');
            }
            return;
        }
        if (this.status) {
            this.status.textContent = t('moments.status.searching');
        }
        // A newer query cancels the request of an older one, which frees its connection.
        if (this.request) {
            this.request.abort();
        }
        const request = (this.request = new AbortController());
        try {
            const found = await fetchSearch(query, 200, request.signal);
            if (token !== this.token) {
                return;
            }
            this.results = found;
            this.error = null;
        } catch (err) {
            if (token !== this.token) {
                return;
            }
            this.results = null;
            this.error = err.message;
        }
        this.renderResults();
    }

    renderResults() {
        if (!this.list) {
            return;
        }
        if (this.error) {
            this.status.textContent = this.error;
            this.list.replaceChildren();
            return;
        }
        const found = this.results;
        if (!found) {
            this.status.textContent = '';
            this.list.replaceChildren();
            return;
        }
        const shown = found.results.length;
        const recordings = t('moments.status.recordings', { count: found.recordings });
        this.status.textContent = found.total === 0 ? t('moments.status.none', { recordings })
            : t(shown < found.total ? 'moments.status.foundFirst' : 'moments.status.found', { count: found.total, recordings, shown });
        this.list.replaceChildren(...found.results.map((r) => el('li', {
            class: 'moment-row', tabindex: '-1', role: 'button', 'data-match': r.match, 'data-kind': r.kind,
            'aria-label': t('moments.result', { text: serverText(r, 'text'), minute: r.minute, title: r.title }),
            onclick: () => openMoment(this.app, r),
        }, el('span', { class: 'moment-minute' }, r.minute),
        el('span', { class: 'moment-text' }, serverText(r, 'text')),
        el('span', { class: 'moment-match muted small' }, [r.title, formatDate(r.created)].filter(Boolean).join(', ')))));
        const first = this.list.firstElementChild;
        if (first) {
            first.tabIndex = 0;
        }
    }

    onListKey(e) {
        const row = e.target.closest('.moment-row');
        if (!row) {
            return;
        }
        const rows = [...this.list.children];
        const at = rows.indexOf(row);
        const go = (i) => {
            const next = rows[Math.max(0, Math.min(rows.length - 1, i))];
            for (const r of rows) {
                r.tabIndex = -1;
            }
            next.tabIndex = 0;
            next.focus();
        };
        if (e.key === 'ArrowDown') {
            go(at + 1);
        } else if (e.key === 'ArrowUp') {
            if (at === 0) {
                this.input.focus();
            } else {
                go(at - 1);
            }
        } else if (e.key === 'Home') {
            go(0);
        } else if (e.key === 'End') {
            go(rows.length - 1);
        } else if (e.key === 'Enter' || e.key === ' ') {
            row.click();
        } else {
            return;
        }
        e.preventDefault();
    }

    // The entries of the palette for a typed line, the moments found for it, best first, and one
    // that opens the panel with it. The search runs in the background, and refresh draws the
    // palette again when it answers.
    paletteActions(query, refresh) {
        if (!looksMoments(query)) {
            return [];
        }
        const text = query.trim();
        const keywords = `${text} ${t('moments.palette.keywords')}`;
        const list = [{
            group: t('moments.palette.group'), title: t('moments.palette.search', { query: text }), keywords, hint: t('moments.palette.hint'),
            run: () => this.show(text),
        }];
        const state = this.palette;
        if (state.query !== text) {
            state.query = text;
            state.results = [];
            clearTimeout(state.timer);
            state.timer = setTimeout(() => {
                fetchSearch(text, 8).then((found) => {
                    if (state.query === text) {
                        state.results = found.results;
                        refresh();
                    }
                }).catch(() => {});
            }, 200);
        }
        for (const r of state.results) {
            list.push({
                group: t('moments.palette.group'), title: `${r.minute}  ${serverText(r, 'text')}`, keywords, hint: r.title,
                run: () => openMoment(this.app, r),
            });
        }
        return list;
    }
}
