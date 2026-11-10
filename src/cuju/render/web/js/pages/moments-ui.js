// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The search of moments across the library, a panel of the Recordings page and entries of the
// command palette. A query goes to the server's index, `GET /api/search?q=`, in the small query
// language of the guide, such as `goal team:Greens after:60`, and the filters of the panel add
// their terms to it. A result opens Watch a few seconds before its moment.

import { formatDate } from '../core/api.js';
import { enhanceSelect } from '../core/menu.js';
import { composeQuery, looksLikeMoments as looksMoments } from '../recording/moments-query.js';

export { KIND_WORDS, composeQuery, looksLikeMoments } from '../recording/moments-query.js';

// The day a number of days before now, as the query language takes dates.
function daysAgo(days) {
    const d = new Date(Date.now() - days * 864e5);
    const pad = (x) => String(x).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const KIND_CHOICES = [
    ['', 'Every kind'], ['goal', 'Goals'], ['shot', 'Shots'], ['save', 'Saves'], ['block', 'Blocks'],
    ['pass', 'Passes'], ['tackle', 'Tackles'], ['card', 'Cards'], ['foul', 'Fouls'], ['offside', 'Offsides'],
    ['set-piece', 'Set pieces'], ['corner', 'Corners'], ['free-kick', 'Free kicks'], ['penalty', 'Penalties'],
    ['throw-in', 'Throw ins'], ['possession', 'Changes of possession'], ['woodwork', 'Woodwork'],
];
const TIME_CHOICES = [
    ['', 'Any time'], ['before:45', 'First half'], ['after:45', 'Second half'], ['after:75', 'Last 15 minutes'],
    ['before:15', 'First 15 minutes'],
];
const SCORE_CHOICES = [['', 'Any score'], ['leading', 'Leading'], ['level', 'Level'], ['trailing', 'Trailing']];
const SOURCE_CHOICES = [
    ['', 'Every source'], ['requested', 'Requested matches'], ['game', 'Played games'], ['tournament', 'Tournaments'],
    ['challenge', 'Challenges'], ['recorder', 'Recorders'], ['live', 'Live sources'],
];
const DATE_CHOICES = [['', 'Any date'], ['0', 'Today'], ['7', 'Last 7 days'], ['30', 'Last 30 days']];

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
        throw new Error(body.error || `The server answered ${res.status}.`);
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
        }, 'Search moments');
        this.input = el('input', {
            type: 'search', id: 'moments-query', class: 'search', value: this.text, spellcheck: 'false',
            'aria-label': 'Search moments', placeholder: 'Moments, such as goal team:Greens after:60',
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
            'aria-label': 'Player number or name', placeholder: 'Player number or name', spellcheck: 'false',
        });
        player.addEventListener('input', () => {
            this.filters.player = player.value;
            this.schedule();
        });
        const filters = el('div', { class: 'filter-bar moments-filters' },
            this.select('Kind', KIND_CHOICES, this.filters.kind, pick('kind')),
            this.select('Team', [['', 'Either team'], ['left', 'Left team'], ['right', 'Right team'],
                ...teams.map((t) => [t, t])], this.filters.team, pick('team')),
            player,
            this.select('Time', TIME_CHOICES, this.filters.time, pick('time')),
            this.select('Score', SCORE_CHOICES, this.filters.score, pick('score')),
            this.select('Scenario', [['', 'Every scenario'], ...scenarios.map(([v, t]) => [v, t])], this.filters.scenario, pick('scenario')),
            this.select('Source', SOURCE_CHOICES, this.filters.source, pick('source')),
            this.select('Date', DATE_CHOICES, this.date, (v) => {
                this.date = v;
                this.run();
            }));
        this.status = el('p', { class: 'muted small moments-status', role: 'status', 'aria-live': 'polite' });
        this.list = el('ul', { class: 'moments-list', id: 'moments-results', 'aria-label': 'Moments found' });
        this.list.addEventListener('keydown', (e) => this.onListKey(e));
        this.panel = el('section', { id: 'moments-panel', class: 'moments-panel', 'aria-label': 'Search moments', hidden: !this.open },
            el('div', { class: 'toolbar' }, this.input, filters),
            el('p', { id: 'moments-help', class: 'muted small' },
                'Words name kinds, such as goal, shot, save, pass, tackle, card, corner or penalty. Filters such as team:, player:, after:, before:, score: and source: narrow them, and a minus sign excludes.'),
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
                this.status.textContent = 'Type a kind such as goal or corner, or choose a filter';
            }
            return;
        }
        if (this.status) {
            this.status.textContent = 'Searching';
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
        this.status.textContent = found.total === 0 ? `No moments found in ${found.recordings} recordings`
            : `${found.total} ${found.total === 1 ? 'moment' : 'moments'} in ${found.recordings} recordings${shown < found.total ? `, the first ${shown} shown` : ''}`;
        this.list.replaceChildren(...found.results.map((r) => el('li', {
            class: 'moment-row', tabindex: '-1', role: 'button', 'data-match': r.match, 'data-kind': r.kind,
            'aria-label': `${r.text}, minute ${r.minute}, ${r.title}`,
            onclick: () => openMoment(this.app, r),
        }, el('span', { class: 'moment-minute' }, r.minute),
        el('span', { class: 'moment-text' }, r.text),
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
        const keywords = `${text} moment search find`;
        const list = [{
            group: 'Moments', title: `Search moments, ${text}`, keywords, hint: 'Recordings',
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
                group: 'Moments', title: `${r.minute}  ${r.text}`, keywords, hint: r.title,
                run: () => openMoment(this.app, r),
            });
        }
        return list;
    }
}
