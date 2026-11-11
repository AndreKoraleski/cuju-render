// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The Recordings page, a file explorer with a folder tree, a sortable table with search, filters
// and a selection of many rows, rename, move, details, and dragging recordings onto folders. A
// deleted recording goes to the Trash, which restores it or deletes it for good. The recordings of
// one run of a challenge show as one group row, which opens to the rows of its attempts.

import { api, formatBytes, formatDate } from '../core/api.js';
import { serverText, t, tn } from '../core/i18n.js';
import { h, listKeys } from '../teams/library.js';
import { Dropdown, enhanceSelect, menuHeading, menuItem } from '../core/menu.js';
import { recordingTitle, summaryTeams } from '../core/names.js';
import { groupRows, groupTotals, navigationRows } from './recording-groups.js';
import { scenarioName } from '../core/scenarios.js';

const FOLDERS_KEY = 'cuju.folders';
const COLUMNS = [
    { key: 'title' },
    { key: 'teams' },
    { key: 'score', numeric: true },
    { key: 'scenario' },
    { key: 'steps', numeric: true },
    { key: 'created' },
    { key: 'bytes', numeric: true },
].map((column) => ({ ...column, label: t(`recordings.column.${column.key}`) }));
// The choices of a select, each value with the message of its label, whose id is the prefix and
// the value with its colons as dots.
const choices = (prefix, values) => values.map((v) => [v, t(`${prefix}.${v.replace(/:/g, '.')}`)]);
const SORTS = choices('recordings.sort', ['created:-1', 'created:1', 'title:1', 'score:-1', 'teams:1', 'steps:-1', 'bytes:-1']);
const RANGES = choices('recordings.range', ['any', 'today', 'week', 'month', 'year']);
const SOURCES = Object.fromEntries(['requested_match', 'human_game', 'challenge', 'recorder', 'live', 'unknown']
    .map((key) => [key, t(`recordings.source.${key}`)]));
const RESULTS = choices('recordings.result', ['all', 'left', 'right', 'draw', 'unknown']);
const DEFAULT_FILTERS = { scenario: 'all', team: 'all', range: 'any', favorite: 'all', source: 'all', result: 'all' };
// The provenance fields in the order and with the names the details panel shows.
const PROVENANCE = ['source', 'cuju_version', 'seed', 'scenario', 'teams', 'humans', 'controls', 'agent_counts',
    'action_set', 'ability', 'late_steps', 'environment'].map((key) => [key, t(`recordings.provenance.${key}`)]);

// The teams of a recording joined, such as Greens against Blues.
function joinTeams(teams) {
    return teams.length ? teams.map((v) => (v == null ? '' : String(v))).reduce((left, right) => t('recordings.teams', { left, right })) : '';
}

// The values of the left and right side joined, such as person and built-in AI, and more in turn.
function joinSides(values) {
    return values.length ? values.reduce((left, right) => t('recordings.provenance.sides', { left, right })) : '';
}

function sourceOf(m) {
    const source = m.provenance && m.provenance.source;
    return typeof source === 'string' && source ? source : 'unknown';
}

// The result of a recording from its final score, unknown for a recording without one.
function resultOf(m) {
    if (!Array.isArray(m.score) || m.score.length !== 2) {
        return 'unknown';
    }
    const [a, b] = m.score;
    return a === b ? 'draw' : a > b ? 'left' : 'right';
}

function provenanceValue(key, value, provenance = {}) {
    if (key === 'source') {
        return SOURCES[value] || String(value);
    }
    if (key === 'scenario') {
        return scenarioName(value);
    }
    if (key === 'humans' && Array.isArray(value)) {
        // A side without a person is the built-in AI unless a registered team played it.
        const teams = Array.isArray(provenance.teams) ? provenance.teams : [];
        return joinSides(value.map((v, side) => t(v ? 'recordings.provenance.person'
            : teams[side] && teams[side] !== 'builtin' ? 'recordings.provenance.registered' : 'recordings.provenance.builtin')));
    }
    if (Array.isArray(value) && value.every((v) => v === null || typeof v !== 'object')) {
        return joinSides(value.map((v) => (v === null ? t('recordings.provenance.scenarioValue') : String(v))));
    }
    return typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value);
}

// The routes of the groups of recordings, which move or restore a whole run at once.
async function groupCall(method, path) {
    let res;
    try {
        res = await fetch(path, { method, cache: 'no-store' });
    } catch {
        throw new Error(t('api.unreachable', { origin: location.origin }));
    }
    const data = await res.json().catch(() => null);
    if (!res.ok) {
        throw new Error((data && data.error && serverText(data, 'error')) || t('api.status', { status: res.status, text: res.statusText }));
    }
    return data;
}

export const groupApi = {
    list: (id, trash = false) => groupCall('GET', `/api/${trash ? 'trash' : 'matches'}?group=${encodeURIComponent(id)}`),
    trash: (id) => groupCall('DELETE', `/api/groups/${encodeURIComponent(id)}`),
    restore: (id) => groupCall('POST', `/api/groups/${encodeURIComponent(id)}/restore`),
};

function loadFolders() {
    try {
        const v = JSON.parse(localStorage.getItem(FOLDERS_KEY) || '[]');
        return Array.isArray(v) ? v.filter((f) => typeof f === 'string') : [];
    } catch {
        return [];
    }
}

function saveFolders(list) {
    try {
        localStorage.setItem(FOLDERS_KEY, JSON.stringify(list));
    } catch {
        // Empty folders then last for this visit only.
    }
}

function cleanPath(path) {
    return path.split('/').map((p) => p.trim()).filter(Boolean).join('/');
}

function createdMs(m) {
    return typeof m.created === 'number' ? (m.created < 1e12 ? m.created * 1000 : m.created) : Date.parse(m.created) || 0;
}

// Sort keys, a score by its total of goals and then by its margin.
function sortValue(m, key) {
    switch (key) {
    case 'teams':
        return summaryTeams(m).join(' ').toLowerCase();
    case 'title':
        return (recordingTitle(m) || m.id || '').toLowerCase();
    case 'score': {
        const [a, b] = m.score || [0, 0];
        return (a + b) * 1000 + Math.abs(a - b);
    }
    case 'created':
        return createdMs(m);
    case 'steps':
    case 'bytes':
        return Number(m[key]) || 0;
    default:
        return String(m[key] || '').toLowerCase();
    }
}

function inRange(m, range) {
    if (range === 'any') {
        return true;
    }
    const t = createdMs(m);
    const now = new Date();
    if (range === 'today') {
        return t >= new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    }
    if (range === 'week') {
        return t >= now.getTime() - 7 * 864e5;
    }
    if (range === 'month') {
        return t >= now.getTime() - 30 * 864e5;
    }
    return t >= new Date(now.getFullYear(), 0, 1).getTime();
}

export class RecordingsPage {
    constructor(app) {
        this.app = app;
        this.root = document.getElementById('page-recordings');
        this.list = [];
        // The folder shown, empty for every recording.
        this.folder = '';
        this.selected = new Set();
        this.anchor = null;
        this.sortKey = 'created';
        this.sortDir = -1;
        this.query = '';
        this.filters = { ...DEFAULT_FILTERS };
        this.extraFolders = loadFolders();
        this.error = null;
        // Whether the page shows the Trash instead of the library.
        this.trash = false;
        // The recording whose details are open, or null.
        this.editing = null;
        // The groups shown open, by identifier.
        this.open = new Set();
        // The rows that the keyboard walks, groups and recordings in the order of the table.
        this.nav = [];
    }

    async refresh() {
        try {
            this.list = await (this.trash ? api.trash() : api.matches());
            this.error = null;
        } catch (err) {
            this.error = err;
        }
        const ids = new Set(this.list.map((m) => m.id));
        if (this.editing && !ids.has(this.editing)) {
            this.editing = null;
        }
        this.selected = new Set([...this.selected].filter((id) => ids.has(id)));
        if (this.folder && !this.folders().includes(this.folder)) {
            this.folder = '';
        }
        this.render();
    }

    folders() {
        const all = new Set(['']);
        const add = (path) => {
            const parts = cleanPath(path || '').split('/').filter(Boolean);
            for (let i = 1; i <= parts.length; i++) {
                all.add(parts.slice(0, i).join('/'));
            }
        };
        for (const m of this.list) {
            add(m.folder);
        }
        for (const f of this.extraFolders) {
            add(f);
        }
        return [...all].sort((a, b) => a.localeCompare(b));
    }

    inFolder(m, path) {
        const f = cleanPath(m.folder || '');
        return !path || f === path || f.startsWith(`${path}/`);
    }

    visible() {
        const q = this.query.trim().toLowerCase();
        const f = this.filters;
        let rows = this.list.filter((m) => {
            if (q) {
                const group = m.group ? [m.group.title, serverText(m.group, 'title')] : [];
                const text = [m.title, recordingTitle(m), ...(m.teams || []), ...summaryTeams(m), ...(m.tags || []), m.notes, m.scenario, scenarioName(m.scenario), m.folder, ...group].join(' ').toLowerCase();
                if (!text.includes(q)) {
                    return false;
                }
            } else if (!this.inFolder(m, this.folder)) {
                return false;
            }
            if (f.scenario !== 'all' && m.scenario !== f.scenario) {
                return false;
            }
            if (f.team !== 'all' && !(m.teams || []).includes(f.team)) {
                return false;
            }
            if (f.favorite === 'yes' && !m.favorite) {
                return false;
            }
            if (f.source !== 'all' && sourceOf(m) !== f.source) {
                return false;
            }
            if (f.result !== 'all' && resultOf(m) !== f.result) {
                return false;
            }
            return inRange(m, f.range);
        });
        rows = rows.slice().sort((a, b) => {
            const x = sortValue(a, this.sortKey);
            const y = sortValue(b, this.sortKey);
            return (x < y ? -1 : x > y ? 1 : 0) * this.sortDir;
        });
        return rows;
    }

    // A select of the toolbar, made a dropdown, whose change runs pick.
    filterSelect(label, prefix, entries, value, pick, align = 'left') {
        const el = h('select', { 'aria-label': label }, entries.map(([v, t]) => h('option', { value: v }, t)));
        el.value = entries.some(([v]) => v === value) ? value : entries[0][0];
        el.addEventListener('change', () => pick(el.value));
        queueMicrotask(() => enhanceSelect(el, { label, prefix, align }));
        return el;
    }

    render() {
        const tree = this.renderTree();
        const search = h('input', { type: 'search', placeholder: t('recordings.search.placeholder'), value: this.query, class: 'search', 'aria-label': t('recordings.search.label') });
        search.addEventListener('input', () => {
            this.query = search.value;
            this.renderTree(true);
            this.renderTable();
        });
        const scenarios = [...new Set(this.list.map((m) => m.scenario).filter(Boolean))].sort();
        // The filter keeps the English name of a team, which the summaries hold, and shows it in the
        // page's language.
        const shownTeams = new Map(this.list.flatMap((m) => (m.teams || []).map((name, i) => [name, summaryTeams(m)[i]])));
        const teams = [...shownTeams.keys()].sort((a, b) => shownTeams.get(a).localeCompare(shownTeams.get(b)));
        const folderNames = this.folders();
        const sources = [...new Set(this.list.map(sourceOf))].sort();
        if (!sources.includes(this.filters.source)) {
            this.filters.source = 'all';
        }
        const filters = h('div', { class: 'filter-bar' },
            this.filterSelect(t('recordings.filter.view'), t('recordings.filter.view'), [['library', t('recordings.view.library')], ['trash', t('recordings.view.trash')]], this.trash ? 'trash' : 'library', (v) => {
                this.trash = v === 'trash';
                this.selected.clear();
                this.editing = null;
                this.refresh();
            }),
            this.filterSelect(t('recordings.filter.folder'), t('recordings.filter.folder'), folderNames.map((p) => [p, p || t('recordings.folder.any')]), this.folder, (v) => {
                this.folder = v;
                this.query = '';
                this.selected.clear();
                this.render();
            }),
            this.filterSelect(t('recordings.filter.scenario'), t('recordings.filter.scenario'), [['all', t('recordings.scenario.any')], ...scenarios.map((s) => [s, scenarioName(s)])], this.filters.scenario, (v) => {
                this.filters.scenario = v;
                this.renderTable();
            }),
            this.filterSelect(t('recordings.filter.team'), t('recordings.filter.team'), [['all', t('recordings.team.any')], ...teams.map((name) => [name, shownTeams.get(name)])], this.filters.team, (v) => {
                this.filters.team = v;
                this.renderTable();
            }),
            this.filterSelect(t('recordings.filter.date'), t('recordings.filter.date'), RANGES, this.filters.range, (v) => {
                this.filters.range = v;
                this.renderTable();
            }),
            this.filterSelect(t('recordings.filter.favorites'), t('recordings.filter.show'), [['all', t('recordings.favorite.all')], ['yes', t('recordings.favorite.yes')]], this.filters.favorite, (v) => {
                this.filters.favorite = v;
                this.renderTable();
            }),
            this.filterSelect(t('recordings.filter.source'), t('recordings.filter.source'), [['all', t('recordings.source.any')], ...sources.map((v) => [v, SOURCES[v] || v])], this.filters.source, (v) => {
                this.filters.source = v;
                this.renderTable();
            }),
            this.filterSelect(t('recordings.filter.result'), t('recordings.filter.result'), RESULTS, this.filters.result, (v) => {
                this.filters.result = v;
                this.renderTable();
            }),
            this.sortSelectEl = this.filterSelect(t('recordings.filter.sort'), t('recordings.filter.sort'), SORTS, `${this.sortKey}:${this.sortDir}`, (v) => {
                const [key, dir] = v.split(':');
                this.sortKey = key;
                this.sortDir = Number(dir);
                this.renderTable();
            }, 'right'));
        this.moveBtn = h('button', { type: 'button', class: 'btn', disabled: true }, t('recordings.action.move'), h('span', { class: 'dd-caret', 'aria-hidden': 'true' }));
        const movePanel = h('div', { role: 'menu', class: 'move-menu', 'aria-label': t('recordings.move.menu') });
        this.moveDropdown = new Dropdown(this.moveBtn, movePanel, { onOpen: () => this.fillMove(movePanel) });
        const actions = h('div', { class: 'toolbar actions' },
            this.countLabel = h('span', { class: 'muted small selection-count' }),
            h('span', { class: 'spacer' }),
            h('button', { class: 'btn', type: 'button', disabled: true, 'data-act': 'open', onclick: () => this.openSelected() }, t('recordings.action.open')),
            h('button', { class: 'btn', type: 'button', disabled: true, 'data-act': 'rename', onclick: () => this.renameSelected() }, t('recordings.action.rename')),
            h('button', { class: 'btn', type: 'button', disabled: true, 'data-act': 'details', 'aria-expanded': 'false', onclick: () => this.toggleDetails() }, t('recordings.action.details')),
            h('span', { class: 'dd-wrap' }, this.moveBtn, movePanel),
            h('button', { class: 'btn', type: 'button', disabled: true, hidden: !this.trash, 'data-act': 'restore', onclick: () => this.restoreSelected() }, t('recordings.action.restore')),
            h('button', { class: 'btn danger', type: 'button', disabled: true, 'data-act': 'delete', onclick: () => this.deleteSelected() }, t(this.trash ? 'recordings.action.purge' : 'recordings.action.trash')),
            h('button', { class: 'btn ghost', type: 'button', title: t(this.trash ? 'recordings.action.refresh.trash' : 'recordings.action.refresh.library'), onclick: () => this.refresh() }, t('recordings.action.refresh')));
        this.detailsHost = h('div', { class: 'details-host' });
        // The search of moments across every recording, a panel above the table.
        this.momentsHost = h('div', { class: 'moments-host' });
        const momentsToggle = this.app.moments && !this.trash
            ? this.app.moments.mount(this.momentsHost, scenarios.map((s) => [s, scenarioName(s)]), teams) : null;
        this.tableHost = h('div', { class: 'table-host' });
        this.treeHost = h('div', { class: 'tree-host' }, tree);
        this.root.replaceChildren(h('div', { class: 'explorer' },
            h('aside', { class: 'folders', 'aria-label': t('recordings.folders') },
                h('div', { class: 'pane-head' }, h('span', { class: 'label' }, t('recordings.folders')),
                    h('button', { class: 'btn small', type: 'button', onclick: () => this.newFolder() }, t('recordings.folder.new'))),
                this.treeHost),
            h('div', { class: 'files' }, h('div', { class: 'toolbar' }, search, filters, momentsToggle), this.momentsHost, actions, this.detailsHost, this.tableHost)));
        this.renderTable();
        this.renderDetails();
    }

    // The details of the recording being edited, its favorite mark, tags, notes and provenance.
    renderDetails(focus = false) {
        if (!this.detailsHost) {
            return;
        }
        const m = this.editing && this.list.find((x) => x.id === this.editing);
        const button = this.root.querySelector('.actions [data-act="details"]');
        if (button) {
            button.setAttribute('aria-expanded', m ? 'true' : 'false');
        }
        if (!m || this.trash) {
            this.detailsHost.replaceChildren();
            return;
        }
        const favorite = h('input', { type: 'checkbox', checked: !!m.favorite });
        const tags = h('input', { type: 'text', value: (m.tags || []).join(', '), maxlength: 1000 });
        const notes = h('textarea', { rows: 4, maxlength: 10000 });
        notes.value = m.notes || '';
        const provenance = m.provenance || {};
        const known = PROVENANCE.filter(([key]) => provenance[key] !== undefined && provenance[key] !== null);
        const extra = Object.keys(provenance).filter((key) => !PROVENANCE.some(([k]) => k === key));
        const rows = [...known, ...extra.map((key) => [key, key.replaceAll('_', ' ')])].flatMap(([key, label]) => [
            h('dt', {}, label), h('dd', {}, provenanceValue(key, provenance[key], provenance))]);
        const save = h('button', { class: 'btn primary', type: 'submit' }, t('recordings.details.save'));
        const close = () => {
            this.editing = null;
            this.renderDetails();
            const again = this.root.querySelector('.actions [data-act="details"]');
            if (again && !again.disabled) {
                again.focus();
            }
        };
        const form = h('form', { class: 'recording-details', 'aria-label': t('recordings.details.label', { title: recordingTitle(m) || m.id }) },
            h('h3', {}, recordingTitle(m) || m.id),
            h('label', { class: 'check' }, favorite, t('recordings.details.favorite')),
            h('label', { class: 'field' }, t('recordings.details.tags'), tags),
            h('label', { class: 'field' }, t('recordings.details.notes'), notes),
            h('div', { class: 'provenance' },
                h('h4', {}, t('recordings.details.provenance')),
                rows.length ? h('dl', {}, rows) : h('p', { class: 'muted small' }, t('recordings.details.noProvenance')),
                h('p', { class: 'muted small' }, t('recordings.details.provenanceNote'))),
            h('div', { class: 'toolbar' }, save,
                h('button', { class: 'btn', type: 'button', onclick: close }, t('recordings.details.close'))));
        form.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                close();
            }
        });
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            save.disabled = true;
            try {
                await api.patchMatch(m.id, {
                    favorite: favorite.checked,
                    tags: [...new Set(tags.value.split(',').map((t) => t.trim()).filter(Boolean))],
                    notes: notes.value,
                });
                this.app.hud.toast(t('recordings.details.saved'));
                await this.refresh();
                const again = this.detailsHost.querySelector('input[type="checkbox"]');
                if (again) {
                    again.focus();
                }
            } catch (err) {
                this.app.hud.toast(err.message, 'error', 7000);
                save.disabled = false;
            }
        });
        this.detailsHost.replaceChildren(form);
        if (focus) {
            favorite.focus();
        }
    }

    toggleDetails() {
        const [id] = this.selected;
        if (this.trash || this.selected.size !== 1 || !id) {
            return;
        }
        this.editing = this.editing === id ? null : id;
        this.renderDetails(true);
    }

    fillMove(panel) {
        const ids = [...this.selected];
        const current = new Set(ids.map((id) => cleanPath((this.list.find((m) => m.id === id) || {}).folder || '')));
        panel.replaceChildren(menuHeading(t('recordings.move.heading', { count: ids.length })),
            ...this.folders().map((path) => menuItem(path ? path.split('/').pop() : t('recordings.move.top'), {
                hint: path.includes('/') ? path : null,
                className: `depth-${Math.min(4, path ? path.split('/').length - 1 : 0)}`,
                checked: current.size === 1 && current.has(path),
                onSelect: () => this.move(ids, path),
            })),
            menuItem(t('recordings.folder.new'), { hint: t('recordings.move.newHint'), onSelect: () => {
                const path = this.askFolder();
                if (path) {
                    this.move(ids, path);
                }
            } }));
    }

    renderTree(only = false) {
        const folders = this.folders();
        const items = folders.map((path) => {
            const depth = path ? path.split('/').length : 0;
            const name = path ? path.split('/').pop() : t('recordings.folder.all');
            const count = path ? this.list.filter((m) => this.inFolder(m, path)).length : this.list.length;
            const active = path === this.folder && !this.query;
            const open = () => {
                this.folder = path;
                this.query = '';
                this.selected.clear();
                this.render();
                const again = this.root.querySelector(`.folder[data-path="${CSS.escape(path)}"]`);
                if (again) {
                    again.focus();
                }
            };
            const row = h('li', {
                class: `folder${active ? ' active' : ''}`,
                style: `padding-left:${8 + depth * 14}px`,
                tabindex: '0',
                role: 'treeitem',
                'aria-selected': active ? 'true' : 'false',
                'data-path': path,
                onclick: open,
                onkeydown: (e) => {
                    if ((e.key === 'Enter' || e.key === ' ') && e.target === row) {
                        e.preventDefault();
                        open();
                    } else if (e.key === 'F2' && path) {
                        e.preventDefault();
                        this.renameFolder(path);
                    }
                },
            }, h('span', { class: 'folder-icon', 'aria-hidden': 'true' }), h('span', { class: 'folder-name' }, name), h('span', { class: 'count' }, String(count)),
            path ? h('span', { class: 'folder-actions' },
                h('button', { type: 'button', class: 'link', title: t('recordings.folder.rename.title'), onclick: (e) => { e.stopPropagation(); this.renameFolder(path); } }, t('recordings.folder.rename')),
                h('button', { type: 'button', class: 'link danger', title: t('recordings.folder.delete.title'), onclick: (e) => { e.stopPropagation(); this.deleteFolder(path); } }, t('recordings.folder.delete'))) : null);
            row.addEventListener('dragover', (e) => {
                if (e.dataTransfer.types.includes('application/x-cuju-matches')) {
                    e.preventDefault();
                    row.classList.add('drop');
                }
            });
            row.addEventListener('dragleave', () => row.classList.remove('drop'));
            row.addEventListener('drop', (e) => {
                e.preventDefault();
                row.classList.remove('drop');
                let ids;
                try {
                    ids = JSON.parse(e.dataTransfer.getData('application/x-cuju-matches') || '[]');
                } catch {
                    return;
                }
                if (Array.isArray(ids) && ids.length) {
                    this.move(ids.filter((id) => typeof id === 'string'), path);
                }
            });
            return row;
        });
        const tree = h('ul', { class: 'tree', role: 'tree', 'aria-label': t('recordings.folders') }, items);
        listKeys(tree, '.folder');
        if (only && this.treeHost) {
            this.treeHost.replaceChildren(tree);
        }
        return tree;
    }

    renderTable() {
        if (!this.tableHost) {
            return;
        }
        if (this.error) {
            this.tableHost.replaceChildren(h('div', { class: 'notice error' }, h('p', {}, this.error.message),
                h('p', { class: 'muted' }, t('recordings.error.hint')),
                h('button', { class: 'btn', type: 'button', onclick: () => this.refresh() }, t('recordings.error.retry'))));
            this.updateActions();
            return;
        }
        const active = document.activeElement;
        const focusedKey = active && active.closest && active.closest('tr[data-key]') ? active.closest('tr[data-key]').dataset.key : null;
        const onToggle = !!(active && active.classList && active.classList.contains('group-toggle'));
        const rows = this.visible();
        this.rows = rows;
        const head = h('tr', {}, COLUMNS.map((c) => {
            const sorted = this.sortKey === c.key;
            const sortBy = () => {
                if (sorted) {
                    this.sortDir = -this.sortDir;
                } else {
                    this.sortKey = c.key;
                    this.sortDir = c.numeric || c.key === 'created' ? -1 : 1;
                }
                if (this.sortSelectEl && SORTS.some(([v]) => v === `${this.sortKey}:${this.sortDir}`)) {
                    this.sortSelectEl.value = `${this.sortKey}:${this.sortDir}`;
                }
                this.renderTable();
            };
            return h('th', {
                class: `${c.numeric ? 'num' : ''}${sorted ? ' sorted' : ''}`,
                'aria-sort': sorted ? (this.sortDir > 0 ? 'ascending' : 'descending') : 'none',
                tabindex: '0',
                onclick: sortBy,
                onkeydown: (e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        sortBy();
                    }
                },
                title: t(`recordings.column.${c.key}.sort`),
            }, c.label, sorted ? (this.sortDir > 0 ? ' ▲' : ' ▼') : '');
        }));
        const showFolder = !!this.query || !this.folder || rows.some((m) => cleanPath(m.folder || '') !== this.folder);
        const items = groupRows(rows);
        this.nav = navigationRows(items, this.open);
        const body = [];
        for (const item of items) {
            if (item.kind === 'recording') {
                body.push(this.recordingRow(item.recording, showFolder));
                continue;
            }
            body.push(this.groupRow(item));
            for (const member of item.members) {
                body.push(this.recordingRow(member, showFolder, item.id));
            }
        }
        const table = h('table', { class: 'grid', 'aria-label': t(this.trash ? 'recordings.table.trash' : 'recordings.table.library'), 'aria-multiselectable': 'true' }, h('thead', {}, head), h('tbody', {}, body));
        const filtered = Object.entries(DEFAULT_FILTERS).some(([key, value]) => this.filters[key] !== value);
        const empty = rows.length ? null : this.trash && !this.list.length ? h('div', { class: 'empty-state' },
            h('p', { class: 'empty-title' }, t('recordings.empty.trash.title')),
            h('p', { class: 'muted' }, t('recordings.empty.trash.text')))
            : h('div', { class: 'empty-state' },
                h('p', { class: 'empty-title' }, t(this.query || filtered ? 'recordings.empty.filtered.title' : this.list.length ? 'recordings.empty.folder.title' : 'recordings.empty.none.title')),
                h('p', { class: 'muted' }, this.query || filtered ? t('recordings.empty.filtered.text')
                    : this.list.length ? t('recordings.empty.folder.text')
                        : tn('recordings.empty.none.text', { sample: h('code', {}, 'cuju render sample'), recorder: h('code', {}, 'cuju.render.Recorder') })),
                !this.list.length ? h('div', { class: 'empty-actions' },
                    h('button', { type: 'button', class: 'btn primary', onclick: () => this.app.showPage('matches') }, t('recordings.empty.none.match')),
                    h('button', { type: 'button', class: 'btn', onclick: () => this.app.palette?.helpTopic('help-start') }, t('recordings.empty.none.help'))) : null);
        this.tableHost.replaceChildren(table, ...(empty ? [empty] : []));
        if (focusedKey) {
            const again = this.tableHost.querySelector(`tr[data-key="${CSS.escape(focusedKey)}"]`);
            const target = again && onToggle ? again.querySelector('.group-toggle') : again;
            if (target && !again.hidden) {
                target.focus({ preventScroll: true });
            }
        }
        this.updateActions();
    }

    // The row of one recording, inside a group when `parent` names it, hidden while it is closed.
    recordingRow(m, showFolder, parent = null) {
        const tr = h('tr', {
            id: `recording-row-${m.id}`,
            class: `${this.selected.has(m.id) ? 'selected' : ''}${parent ? ' group-member' : ''}`,
            hidden: !!parent && !this.open.has(parent),
            draggable: this.trash ? 'false' : 'true',
            tabindex: '0',
            'aria-selected': this.selected.has(m.id) ? 'true' : 'false',
            'data-id': m.id,
            'data-key': m.id,
            'data-group': parent,
        },
        h('td', { class: 'title-cell' },
            m.favorite ? h('span', { class: 'favorite-mark', role: 'img', 'aria-label': t('recordings.favorite'), title: t('recordings.favorite') }, '★') : null,
            h('span', { class: 'ellipsis' }, recordingTitle(m) || m.id),
            showFolder && m.folder ? h('span', { class: 'folder-tag' }, m.folder) : null,
            ...(m.tags || []).slice(0, 3).map((tag) => h('span', { class: 'folder-tag tag' }, tag))),
        h('td', { class: 'wrap' }, joinTeams(summaryTeams(m))),
        h('td', { class: 'num' }, m.score ? t('recordings.score', { left: m.score[0], right: m.score[1] }) : ''),
        h('td', { class: 'wrap' }, scenarioName(m.scenario)),
        h('td', { class: 'num' }, m.steps != null ? String(m.steps) : ''),
        h('td', {}, formatDate(m.created)),
        h('td', { class: 'num' }, formatBytes(m.bytes)));
        tr.addEventListener('click', (e) => this.select(this.nav.findIndex((r) => r.key === m.id), e));
        tr.addEventListener('dblclick', () => this.openSelected(m.id));
        tr.addEventListener('keydown', (e) => this.rowKey(e, this.nav.findIndex((r) => r.key === m.id)));
        this.dragRows(tr, [m.id]);
        return tr;
    }

    // The row of a group, a disclosure button that names the challenge and the competitor, the
    // run's result and the count of its recordings, with the totals of its members.
    groupRow(item) {
        const ids = item.members.map((m) => m.id);
        const key = `group:${item.id}`;
        const open = this.open.has(item.id);
        const selected = ids.every((id) => this.selected.has(id));
        const totals = groupTotals(item.members);
        const title = serverText(item.group, 'title') || item.id;
        const result = serverText(item.group, 'result');
        const count = ids.length;
        const toggle = h('button', {
            type: 'button',
            class: 'group-toggle',
            'aria-expanded': open ? 'true' : 'false',
            'aria-controls': ids.map((id) => `recording-row-${id}`).join(' '),
            'aria-label': t('recordings.group.label', { title, result, count }),
            onclick: (e) => {
                e.stopPropagation();
                this.toggleGroup(item.id);
            },
        }, h('span', { class: 'group-caret', 'aria-hidden': 'true' }), h('span', { class: 'ellipsis' }, title));
        const first = item.members[0];
        const tr = h('tr', {
            class: `group-row${selected ? ' selected' : ''}`,
            draggable: this.trash ? 'false' : 'true',
            tabindex: '0',
            'aria-selected': selected ? 'true' : 'false',
            'data-key': key,
            'data-group': item.id,
        },
        h('td', { class: 'title-cell' }, toggle,
            result ? h('span', { class: 'group-result muted small' }, result) : null,
            h('span', { class: 'folder-tag' }, t('recordings.group.count', { count }))),
        h('td', { class: 'wrap' }, joinTeams(summaryTeams(first))),
        h('td', { class: 'num' }, ''),
        h('td', { class: 'wrap' }, scenarioName(first.scenario)),
        h('td', { class: 'num' }, String(totals.steps)),
        h('td', {}, totals.created ? formatDate(totals.created) : ''),
        h('td', { class: 'num' }, formatBytes(totals.bytes)));
        tr.addEventListener('click', (e) => this.select(this.nav.findIndex((r) => r.key === key), e));
        tr.addEventListener('dblclick', () => this.toggleGroup(item.id));
        tr.addEventListener('keydown', (e) => this.rowKey(e, this.nav.findIndex((r) => r.key === key)));
        this.dragRows(tr, ids);
        return tr;
    }

    // Dragging a row drags the selection, or the row's recordings when it is not selected.
    dragRows(tr, ids) {
        tr.addEventListener('dragstart', (e) => {
            if (this.trash) {
                e.preventDefault();
                return;
            }
            if (!ids.every((id) => this.selected.has(id))) {
                this.selected = new Set(ids);
                this.renderTable();
            }
            e.dataTransfer.setData('application/x-cuju-matches', JSON.stringify([...this.selected]));
            e.dataTransfer.effectAllowed = 'move';
        });
    }

    // Opens or closes a group, and keeps the focus where it was.
    toggleGroup(id, open = !this.open.has(id)) {
        if (open) {
            this.open.add(id);
        } else {
            this.open.delete(id);
        }
        this.renderTable();
    }

    // The groups whose recordings of the view are all among `ids`, each with those recordings.
    wholeGroups(ids) {
        const chosen = new Set(ids);
        return groupRows(this.list)
            .filter((item) => item.kind === 'group' && item.members.every((m) => chosen.has(m.id)))
            .map((item) => ({ id: item.id, ids: item.members.map((m) => m.id) }));
    }

    updateActions() {
        const count = this.selected.size;
        const q = (act) => this.root.querySelector(`.actions [data-act="${act}"]`);
        if (!q('open')) {
            return;
        }
        q('open').disabled = count !== 1 || this.trash;
        q('rename').disabled = count !== 1 || this.trash;
        q('details').disabled = count !== 1 || this.trash;
        q('restore').disabled = count === 0 || !this.trash;
        q('delete').disabled = count === 0;
        const verb = this.trash ? 'recordings.action.purge' : 'recordings.action.trash';
        q('delete').textContent = count > 1 ? t(`${verb}.count`, { count }) : t(verb);
        this.moveBtn.disabled = count === 0 || this.trash;
        const shown = this.rows ? this.rows.length : 0;
        // The total counts every recording of the view, the library or the Trash, on disk.
        const total = this.list.reduce((sum, m) => sum + (Number(m.bytes) || 0), 0);
        const where = this.trash ? 'trash' : 'library';
        this.countLabel.textContent = count ? t(`recordings.count.selected.${where}`, { count, shown, size: formatBytes(total) })
            : t(`recordings.count.${where}`, { count: shown, size: formatBytes(total) });
    }

    // Arrows move through the rows and select, with Shift they extend, Enter opens, Delete deletes
    // and F2 renames. On a group, Enter and the right and left arrows open and close it, and the
    // left arrow on a row of a group goes back to the group.
    rowKey(e, i) {
        if (e.target !== e.currentTarget) {
            return;
        }
        const entry = this.nav[i];
        if (!entry) {
            return;
        }
        const go = (j) => {
            j = Math.max(0, Math.min(this.nav.length - 1, j));
            const key = this.nav[j].key;
            this.select(j, { shiftKey: e.shiftKey, ctrlKey: false, metaKey: false });
            const tr = this.tableHost.querySelector(`tr[data-key="${CSS.escape(key)}"]`);
            if (tr) {
                tr.focus();
            }
        };
        if (e.key === 'ArrowDown') {
            go(i + 1);
        } else if (e.key === 'ArrowUp') {
            go(i - 1);
        } else if (e.key === 'Home') {
            go(0);
        } else if (e.key === 'End') {
            go(this.nav.length - 1);
        } else if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft') && entry.group) {
            this.toggleGroup(entry.group.id, e.key === 'ArrowRight');
        } else if (e.key === 'ArrowLeft' && entry.parent) {
            go(this.nav.findIndex((r) => r.key === `group:${entry.parent}`));
        } else if (e.key === 'Enter') {
            if (entry.group) {
                this.toggleGroup(entry.group.id);
            } else {
                this.openSelected(entry.recording.id);
            }
        } else if (e.key === ' ') {
            this.select(i, { shiftKey: false, ctrlKey: true, metaKey: false });
        } else if (e.key === 'Delete') {
            if (!entry.ids.every((id) => this.selected.has(id))) {
                this.selected = new Set(entry.ids);
            }
            this.deleteSelected();
        } else if (e.key === 'F2') {
            if (this.trash || !entry.recording) {
                return;
            }
            this.selected = new Set([entry.recording.id]);
            this.renameSelected();
        } else {
            return;
        }
        e.preventDefault();
    }

    // Click selects one row, Ctrl or Cmd toggles, Shift selects the range from the last click. A
    // group's row selects every recording of the group.
    select(index, e) {
        const entry = this.nav[index];
        if (!entry) {
            return;
        }
        if (e.shiftKey && this.anchor != null) {
            const a = Math.min(this.anchor, index);
            const b = Math.max(this.anchor, index);
            if (!(e.ctrlKey || e.metaKey)) {
                this.selected.clear();
            }
            for (let i = a; i <= b && i < this.nav.length; i++) {
                for (const id of this.nav[i].ids) {
                    this.selected.add(id);
                }
            }
        } else if (e.ctrlKey || e.metaKey) {
            const all = entry.ids.every((id) => this.selected.has(id));
            for (const id of entry.ids) {
                if (all) {
                    this.selected.delete(id);
                } else {
                    this.selected.add(id);
                }
            }
            this.anchor = index;
        } else {
            this.selected = new Set(entry.ids);
            this.anchor = index;
        }
        this.renderTable();
    }

    // A recording of the Trash opens only after Restore.
    openSelected(id = [...this.selected][0]) {
        if (id && !this.trash) {
            this.app.openMatchInWatch(id);
        }
    }

    async renameSelected() {
        if (this.trash) {
            return;
        }
        const [id] = this.selected;
        const m = this.list.find((x) => x.id === id);
        if (!m) {
            return;
        }
        const shown = recordingTitle(m) || m.title || '';
        const title = prompt(t('recordings.rename.prompt'), shown);
        if (title == null || !title.trim() || title.trim() === shown || title.trim() === m.title) {
            return;
        }
        try {
            await api.patchMatch(id, { title: title.trim() });
        } catch (err) {
            this.app.hud.toast(err.message, 'error');
        }
        this.refresh();
    }

    async deleteSelected() {
        const ids = [...this.selected];
        if (!ids.length) {
            return;
        }
        const question = ids.length === 1
            ? t('recordings.purge.confirmOne', { title: recordingTitle(this.list.find((m) => m.id === ids[0])) || ids[0] })
            : t('recordings.purge.confirm', { count: ids.length });
        // Moving to the Trash can be undone, so only a permanent deletion asks first.
        if (this.trash && !confirm(question)) {
            return;
        }
        const failed = [];
        // A whole group moves to the Trash in one step.
        const groups = this.trash ? [] : this.wholeGroups(ids);
        const grouped = new Set(groups.flatMap((group) => group.ids));
        for (const group of groups) {
            try {
                await groupApi.trash(group.id);
            } catch (err) {
                failed.push(...group.ids.map(() => err.message));
            }
        }
        for (const id of ids.filter((x) => !grouped.has(x))) {
            try {
                await (this.trash ? api.purgeMatch(id) : api.deleteMatch(id));
            } catch (err) {
                failed.push(err.message);
            }
        }
        const done = ids.length - failed.length;
        if (failed.length) {
            this.app.hud.toast(t(this.trash ? 'recordings.purge.failed' : 'recordings.trash.failed', { count: failed.length, reason: failed[0] }), 'error', 7000);
        } else if (this.trash) {
            this.app.hud.toast(t('recordings.purge.done', { count: done }));
        } else {
            this.app.hud.toast(t('recordings.trash.done', { count: done }));
        }
        this.selected.clear();
        this.refresh();
    }

    async restoreSelected() {
        const ids = [...this.selected];
        if (!this.trash || !ids.length) {
            return;
        }
        const failed = [];
        // A whole group of the Trash comes back in one step, and any recording on its own.
        const groups = this.wholeGroups(ids);
        const grouped = new Set(groups.flatMap((group) => group.ids));
        for (const group of groups) {
            try {
                await groupApi.restore(group.id);
            } catch (err) {
                failed.push(...group.ids.map(() => err.message));
            }
        }
        for (const id of ids.filter((x) => !grouped.has(x))) {
            try {
                await api.restoreMatch(id);
            } catch (err) {
                failed.push(err.message);
            }
        }
        const done = ids.length - failed.length;
        if (failed.length) {
            this.app.hud.toast(t('recordings.restore.failed', { count: failed.length, reason: failed[0] }), 'error', 7000);
        } else {
            this.app.hud.toast(t('recordings.restore.done', { count: done }));
        }
        this.selected.clear();
        this.refresh();
    }

    async move(ids, folder) {
        if (this.trash) {
            return;
        }
        let failed = 0;
        for (const id of ids) {
            try {
                await api.patchMatch(id, { folder });
            } catch {
                failed++;
            }
        }
        if (failed < ids.length) {
            this.extraFolders = this.extraFolders.filter((f) => !(folder === f || folder.startsWith(`${f}/`)));
            saveFolders(this.extraFolders);
        }
        if (failed) {
            this.app.hud.toast(t('recordings.move.failed', { count: failed, total: ids.length }), 'error');
        } else {
            this.app.hud.toast(folder ? t('recordings.move.done', { count: ids.length, folder }) : t('recordings.move.doneTop', { count: ids.length }));
        }
        this.selected.clear();
        this.refresh();
    }

    // Asks for a new folder's name and keeps it, returning its path or null.
    askFolder() {
        const name = prompt(t('recordings.folder.new.prompt'), '');
        const clean = cleanPath(name || '').replace(/\//g, ' ');
        if (!clean) {
            return null;
        }
        const path = this.folder ? `${this.folder}/${clean}` : clean;
        if (!this.extraFolders.includes(path)) {
            this.extraFolders.push(path);
            saveFolders(this.extraFolders);
        }
        return path;
    }

    newFolder() {
        if (this.askFolder()) {
            this.render();
        }
    }

    // Renames a folder on the server first, and changes the view only for what the server took.
    async renameFolder(path) {
        const name = prompt(t('recordings.folder.rename.prompt'), path.split('/').pop());
        const clean = cleanPath(name || '').replace(/\//g, ' ');
        if (!clean || clean === path.split('/').pop()) {
            return;
        }
        const target = [...path.split('/').slice(0, -1), clean].join('/');
        const inside = this.list.filter((m) => this.inFolder(m, path) && cleanPath(m.folder || ''));
        let failed = 0;
        let error = '';
        for (const m of inside) {
            const f = cleanPath(m.folder || '');
            try {
                await api.patchMatch(m.id, { folder: target + f.slice(path.length) });
            } catch (err) {
                failed++;
                error = err.message;
            }
        }
        if (failed) {
            this.app.hud.toast(t('recordings.folder.rename.failed', { count: failed, total: inside.length, reason: error }), 'error', 7000);
            await this.refresh();
            return;
        }
        this.extraFolders = this.extraFolders.map((f) => (f === path || f.startsWith(`${path}/`) ? target + f.slice(path.length) : f));
        saveFolders(this.extraFolders);
        if (this.folder === path || this.folder.startsWith(`${path}/`)) {
            this.folder = target + this.folder.slice(path.length);
        }
        this.app.hud.toast(t('recordings.folder.rename.done', { name: clean }));
        this.refresh();
    }

    async deleteFolder(path) {
        const inside = this.list.filter((m) => cleanPath(m.folder || '') && this.inFolder(m, path));
        const parent = path.split('/').slice(0, -1).join('/');
        const question = parent ? t('recordings.folder.delete.confirm', { path, count: inside.length, parent })
            : t('recordings.folder.delete.confirmTop', { path, count: inside.length });
        if (inside.length && !confirm(question)) {
            return;
        }
        let failed = 0;
        for (const m of inside) {
            try {
                await api.patchMatch(m.id, { folder: parent });
            } catch (err) {
                failed++;
                this.app.hud.toast(err.message, 'error');
            }
        }
        if (failed) {
            this.refresh();
            return;
        }
        this.extraFolders = this.extraFolders.filter((f) => !(f === path || f.startsWith(`${path}/`)));
        saveFolders(this.extraFolders);
        if (this.folder === path || this.folder.startsWith(`${path}/`)) {
            this.folder = parent;
        }
        this.refresh();
    }
}
