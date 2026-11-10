// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The Recordings page, a file explorer with a folder tree, a sortable table with search, filters
// and a selection of many rows, rename, move, details, and dragging recordings onto folders. A
// deleted recording goes to the Trash, which restores it or deletes it for good.

import { api, formatBytes, formatDate } from '../core/api.js';
import { h, listKeys } from '../teams/library.js';
import { Dropdown, enhanceSelect, menuHeading, menuItem } from '../core/menu.js';
import { scenarioName, titleText } from '../core/scenarios.js';

const FOLDERS_KEY = 'cuju.folders';
const COLUMNS = [
    { key: 'title', label: 'Title' },
    { key: 'teams', label: 'Teams' },
    { key: 'score', label: 'Score', numeric: true },
    { key: 'scenario', label: 'Scenario' },
    { key: 'steps', label: 'Steps', numeric: true },
    { key: 'created', label: 'Date' },
    { key: 'bytes', label: 'Size', numeric: true },
];
const SORTS = [
    ['created:-1', 'Newest first'], ['created:1', 'Oldest first'], ['title:1', 'Title, A to Z'],
    ['score:-1', 'Most goals'], ['teams:1', 'Teams, A to Z'], ['steps:-1', 'Longest'], ['bytes:-1', 'Largest'],
];
const RANGES = [['any', 'Any date'], ['today', 'Today'], ['week', 'Last 7 days'], ['month', 'Last 30 days'], ['year', 'This year']];
const SOURCES = { requested_match: 'Requested match', human_game: 'Played game', challenge: 'Challenge', recorder: 'Recorder', live: 'Live source', unknown: 'Unknown source' };
const RESULTS = [['all', 'Every result'], ['left', 'Left won'], ['right', 'Right won'], ['draw', 'Draw'], ['unknown', 'Unknown result']];
const DEFAULT_FILTERS = { scenario: 'all', team: 'all', range: 'any', favorite: 'all', source: 'all', result: 'all' };
// The provenance fields in the order and with the names the details panel shows.
const PROVENANCE = [
    ['source', 'Source'], ['cuju_version', 'cuju version'], ['seed', 'Seed'], ['scenario', 'Scenario'],
    ['teams', 'Teams'], ['humans', 'People on the left and right'], ['controls', 'Controls'],
    ['agent_counts', 'Agents on the left and right'], ['action_set', 'Action set'], ['ability', 'Ability'],
    ['late_steps', 'Steps the built-in AI played for a late team'], ['environment', 'Environment'],
];

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
        return value.map((v, side) => (v ? 'person' : teams[side] && teams[side] !== 'builtin' ? 'registered team' : 'built-in AI')).join(' and ');
    }
    if (Array.isArray(value) && value.every((v) => v === null || typeof v !== 'object')) {
        return value.map((v) => (v === null ? "scenario's" : String(v))).join(' and ');
    }
    return typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value);
}

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
        return (m.teams || []).join(' ').toLowerCase();
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
                const text = [m.title, titleText(m.title, m.scenario), ...(m.teams || []), ...(m.tags || []), m.notes, m.scenario, scenarioName(m.scenario), m.folder].join(' ').toLowerCase();
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
        const search = h('input', { type: 'search', placeholder: 'Search every recording', value: this.query, class: 'search', 'aria-label': 'Search recordings' });
        search.addEventListener('input', () => {
            this.query = search.value;
            this.renderTree(true);
            this.renderTable();
        });
        const scenarios = [...new Set(this.list.map((m) => m.scenario).filter(Boolean))].sort();
        const teams = [...new Set(this.list.flatMap((m) => m.teams || []))].sort((a, b) => a.localeCompare(b));
        const folderNames = this.folders();
        const sources = [...new Set(this.list.map(sourceOf))].sort();
        if (!sources.includes(this.filters.source)) {
            this.filters.source = 'all';
        }
        const filters = h('div', { class: 'filter-bar' },
            this.filterSelect('View', 'View', [['library', 'Library'], ['trash', 'Trash']], this.trash ? 'trash' : 'library', (v) => {
                this.trash = v === 'trash';
                this.selected.clear();
                this.editing = null;
                this.refresh();
            }),
            this.filterSelect('Folder', 'Folder', folderNames.map((p) => [p, p || 'Every folder']), this.folder, (v) => {
                this.folder = v;
                this.query = '';
                this.selected.clear();
                this.render();
            }),
            this.filterSelect('Scenario', 'Scenario', [['all', 'Every scenario'], ...scenarios.map((s) => [s, scenarioName(s)])], this.filters.scenario, (v) => {
                this.filters.scenario = v;
                this.renderTable();
            }),
            this.filterSelect('Team', 'Team', [['all', 'Every team'], ...teams.map((t) => [t, t])], this.filters.team, (v) => {
                this.filters.team = v;
                this.renderTable();
            }),
            this.filterSelect('Date', 'Date', RANGES, this.filters.range, (v) => {
                this.filters.range = v;
                this.renderTable();
            }),
            this.filterSelect('Favorites', 'Show', [['all', 'Every recording'], ['yes', 'Favorites']], this.filters.favorite, (v) => {
                this.filters.favorite = v;
                this.renderTable();
            }),
            this.filterSelect('Source', 'Source', [['all', 'Every source'], ...sources.map((v) => [v, SOURCES[v] || v])], this.filters.source, (v) => {
                this.filters.source = v;
                this.renderTable();
            }),
            this.filterSelect('Result', 'Result', RESULTS, this.filters.result, (v) => {
                this.filters.result = v;
                this.renderTable();
            }),
            this.sortSelectEl = this.filterSelect('Sort', 'Sort', SORTS, `${this.sortKey}:${this.sortDir}`, (v) => {
                const [key, dir] = v.split(':');
                this.sortKey = key;
                this.sortDir = Number(dir);
                this.renderTable();
            }, 'right'));
        this.moveBtn = h('button', { type: 'button', class: 'btn', disabled: true }, 'Move to', h('span', { class: 'dd-caret', 'aria-hidden': 'true' }));
        const movePanel = h('div', { role: 'menu', class: 'move-menu', 'aria-label': 'Move to folder' });
        this.moveDropdown = new Dropdown(this.moveBtn, movePanel, { onOpen: () => this.fillMove(movePanel) });
        const actions = h('div', { class: 'toolbar actions' },
            this.countLabel = h('span', { class: 'muted small selection-count' }),
            h('span', { class: 'spacer' }),
            h('button', { class: 'btn', type: 'button', disabled: true, 'data-act': 'open', onclick: () => this.openSelected() }, 'Open'),
            h('button', { class: 'btn', type: 'button', disabled: true, 'data-act': 'rename', onclick: () => this.renameSelected() }, 'Rename'),
            h('button', { class: 'btn', type: 'button', disabled: true, 'data-act': 'details', 'aria-expanded': 'false', onclick: () => this.toggleDetails() }, 'Details'),
            h('span', { class: 'dd-wrap' }, this.moveBtn, movePanel),
            h('button', { class: 'btn', type: 'button', disabled: true, hidden: !this.trash, 'data-act': 'restore', onclick: () => this.restoreSelected() }, 'Restore'),
            h('button', { class: 'btn danger', type: 'button', disabled: true, 'data-act': 'delete', onclick: () => this.deleteSelected() }, this.trash ? 'Delete permanently' : 'Move to Trash'),
            h('button', { class: 'btn ghost', type: 'button', title: this.trash ? 'Read the Trash again' : 'Read the library again', onclick: () => this.refresh() }, 'Refresh'));
        this.detailsHost = h('div', { class: 'details-host' });
        // The search of moments across every recording, a panel above the table.
        this.momentsHost = h('div', { class: 'moments-host' });
        const momentsToggle = this.app.moments && !this.trash
            ? this.app.moments.mount(this.momentsHost, scenarios.map((s) => [s, scenarioName(s)]), teams) : null;
        this.tableHost = h('div', { class: 'table-host' });
        this.treeHost = h('div', { class: 'tree-host' }, tree);
        this.root.replaceChildren(h('div', { class: 'explorer' },
            h('aside', { class: 'folders', 'aria-label': 'Folders' },
                h('div', { class: 'pane-head' }, h('span', { class: 'label' }, 'Folders'),
                    h('button', { class: 'btn small', type: 'button', onclick: () => this.newFolder() }, 'New folder')),
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
        const save = h('button', { class: 'btn primary', type: 'submit' }, 'Save details');
        const close = () => {
            this.editing = null;
            this.renderDetails();
            const again = this.root.querySelector('.actions [data-act="details"]');
            if (again && !again.disabled) {
                again.focus();
            }
        };
        const form = h('form', { class: 'recording-details', 'aria-label': `Details of ${titleText(m.title, m.scenario) || m.id}` },
            h('h3', {}, titleText(m.title, m.scenario) || m.id),
            h('label', { class: 'check' }, favorite, 'Favorite'),
            h('label', { class: 'field' }, 'Tags, separated by commas, up to twenty of forty characters each', tags),
            h('label', { class: 'field' }, 'Notes, up to ten thousand characters', notes),
            h('div', { class: 'provenance' },
                h('h4', {}, 'Provenance'),
                rows.length ? h('dl', {}, rows) : h('p', { class: 'muted small' }, 'This recording names no provenance.'),
                h('p', { class: 'muted small' }, 'A field that is missing is unknown. A team identifier names a team of this computer, whose files may have changed since the match.')),
            h('div', { class: 'toolbar' }, save,
                h('button', { class: 'btn', type: 'button', onclick: close }, 'Close')));
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
                this.app.hud.toast('Details saved.');
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
        panel.replaceChildren(menuHeading(`Move ${ids.length === 1 ? 'the recording' : `${ids.length} recordings`} to`),
            ...this.folders().map((path) => menuItem(path ? path.split('/').pop() : 'No folder, the top level', {
                hint: path.includes('/') ? path : null,
                className: `depth-${Math.min(4, path ? path.split('/').length - 1 : 0)}`,
                checked: current.size === 1 && current.has(path),
                onSelect: () => this.move(ids, path),
            })),
            menuItem('New folder', { hint: 'Make one and move there', onSelect: () => {
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
            const name = path ? path.split('/').pop() : 'All recordings';
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
                h('button', { type: 'button', class: 'link', title: 'Rename folder', onclick: (e) => { e.stopPropagation(); this.renameFolder(path); } }, 'Rename'),
                h('button', { type: 'button', class: 'link danger', title: 'Delete folder', onclick: (e) => { e.stopPropagation(); this.deleteFolder(path); } }, 'Delete')) : null);
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
        const tree = h('ul', { class: 'tree', role: 'tree', 'aria-label': 'Folders' }, items);
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
                h('p', { class: 'muted' }, 'Start the server with cuju render serve, then refresh. Dropping a .cjr file on the Watch page still works.'),
                h('button', { class: 'btn', type: 'button', onclick: () => this.refresh() }, 'Try again')));
            this.updateActions();
            return;
        }
        const focusedId = document.activeElement && document.activeElement.closest && document.activeElement.closest('tr[data-id]')
            ? document.activeElement.closest('tr[data-id]').dataset.id : null;
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
                title: c.key === 'score' ? 'Sort by goals in all, then by the margin' : `Sort by ${c.label.toLowerCase()}`,
            }, c.label, sorted ? (this.sortDir > 0 ? ' ▲' : ' ▼') : '');
        }));
        const showFolder = !!this.query || !this.folder || rows.some((m) => cleanPath(m.folder || '') !== this.folder);
        const body = rows.map((m, i) => {
            const tr = h('tr', {
                class: this.selected.has(m.id) ? 'selected' : '',
                draggable: this.trash ? 'false' : 'true',
                tabindex: '0',
                'aria-selected': this.selected.has(m.id) ? 'true' : 'false',
                'data-id': m.id,
            },
            h('td', { class: 'title-cell' },
                m.favorite ? h('span', { class: 'favorite-mark', role: 'img', 'aria-label': 'Favorite', title: 'Favorite' }, '★') : null,
                h('span', { class: 'ellipsis' }, titleText(m.title, m.scenario) || m.id),
                showFolder && m.folder ? h('span', { class: 'folder-tag' }, m.folder) : null,
                ...(m.tags || []).slice(0, 3).map((tag) => h('span', { class: 'folder-tag tag' }, tag))),
            h('td', {}, (m.teams || []).join(' against ')),
            h('td', { class: 'num' }, m.score ? `${m.score[0]} to ${m.score[1]}` : ''),
            h('td', {}, scenarioName(m.scenario)),
            h('td', { class: 'num' }, m.steps != null ? String(m.steps) : ''),
            h('td', {}, formatDate(m.created)),
            h('td', { class: 'num' }, formatBytes(m.bytes)));
            tr.addEventListener('click', (e) => this.select(m.id, i, e));
            tr.addEventListener('dblclick', () => this.openSelected(m.id));
            tr.addEventListener('keydown', (e) => this.rowKey(e, m, i));
            tr.addEventListener('dragstart', (e) => {
                if (this.trash) {
                    e.preventDefault();
                    return;
                }
                if (!this.selected.has(m.id)) {
                    this.selected = new Set([m.id]);
                    this.renderTable();
                }
                e.dataTransfer.setData('application/x-cuju-matches', JSON.stringify([...this.selected]));
                e.dataTransfer.effectAllowed = 'move';
            });
            return tr;
        });
        const table = h('table', { class: 'grid', 'aria-label': this.trash ? 'Recordings in the Trash' : 'Recordings', 'aria-multiselectable': 'true' }, h('thead', {}, head), h('tbody', {}, body));
        const filtered = Object.entries(DEFAULT_FILTERS).some(([key, value]) => this.filters[key] !== value);
        const empty = rows.length ? null : this.trash && !this.list.length ? h('div', { class: 'empty-state' },
            h('p', { class: 'empty-title' }, 'The Trash is empty'),
            h('p', { class: 'muted' }, 'Move to Trash on a recording of the library brings it here, where Restore returns it.'))
            : h('div', { class: 'empty-state' },
                h('p', { class: 'empty-title' }, this.query || filtered ? 'Nothing matches' : this.list.length ? 'This folder is empty' : 'No recordings yet'),
                h('p', { class: 'muted' }, this.query || filtered ? 'Change the search or the filters above.'
                    : this.list.length ? 'Drag recordings onto a folder, or select some and use Move to.'
                        : ['The command ', h('code', {}, 'cuju render sample'), ' brings back the two sample matches, ',
                            h('code', {}, 'cuju.render.Recorder'), ' records the matches of a script, and a match requested on Matches lands here.']),
                !this.list.length ? h('div', { class: 'empty-actions' },
                    h('button', { type: 'button', class: 'btn primary', onclick: () => this.app.showPage('matches') }, 'Play a match'),
                    h('button', { type: 'button', class: 'btn', onclick: () => this.app.palette?.helpTopic('help-start') }, 'How to record')) : null);
        this.tableHost.replaceChildren(table, ...(empty ? [empty] : []));
        if (focusedId) {
            const again = this.tableHost.querySelector(`tr[data-id="${CSS.escape(focusedId)}"]`);
            if (again) {
                again.focus({ preventScroll: true });
            }
        }
        this.updateActions();
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
        const verb = this.trash ? 'Delete permanently' : 'Move to Trash';
        q('delete').textContent = count > 1 ? `${verb}, ${count}` : verb;
        this.moveBtn.disabled = count === 0 || this.trash;
        const shown = this.rows ? this.rows.length : 0;
        // The total counts every recording of the view, the library or the Trash, on disk.
        const total = this.list.reduce((sum, m) => sum + (Number(m.bytes) || 0), 0);
        const where = this.trash ? 'in the Trash' : 'in the library';
        const counted = count ? `${count} of ${shown} selected` : `${shown} ${shown === 1 ? 'recording' : 'recordings'}`;
        this.countLabel.textContent = `${counted}, ${formatBytes(total)} ${where}`;
    }

    // Arrows move through the rows and select, with Shift they extend, Enter opens, Delete deletes
    // and F2 renames.
    rowKey(e, m, i) {
        if (e.target !== e.currentTarget) {
            return;
        }
        const go = (j) => {
            j = Math.max(0, Math.min(this.rows.length - 1, j));
            const id = this.rows[j].id;
            this.select(id, j, { shiftKey: e.shiftKey, ctrlKey: false, metaKey: false });
            const tr = this.tableHost.querySelector(`tr[data-id="${CSS.escape(id)}"]`);
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
            go(this.rows.length - 1);
        } else if (e.key === 'Enter') {
            this.openSelected(m.id);
        } else if (e.key === ' ') {
            this.select(m.id, i, { shiftKey: false, ctrlKey: true, metaKey: false });
        } else if (e.key === 'Delete') {
            if (!this.selected.has(m.id)) {
                this.selected = new Set([m.id]);
            }
            this.deleteSelected();
        } else if (e.key === 'F2') {
            if (this.trash) {
                return;
            }
            this.selected = new Set([m.id]);
            this.renameSelected();
        } else {
            return;
        }
        e.preventDefault();
    }

    // Click selects one, Ctrl or Cmd toggles, Shift selects the range from the last click.
    select(id, index, e) {
        if (e.shiftKey && this.anchor != null) {
            const a = Math.min(this.anchor, index);
            const b = Math.max(this.anchor, index);
            if (!(e.ctrlKey || e.metaKey)) {
                this.selected.clear();
            }
            for (let i = a; i <= b; i++) {
                this.selected.add(this.rows[i].id);
            }
        } else if (e.ctrlKey || e.metaKey) {
            if (this.selected.has(id)) {
                this.selected.delete(id);
            } else {
                this.selected.add(id);
            }
            this.anchor = index;
        } else {
            this.selected = new Set([id]);
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
        const title = prompt('New title for this recording', m.title || '');
        if (title == null || !title.trim() || title.trim() === m.title) {
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
        const what = ids.length === 1 ? `"${(this.list.find((m) => m.id === ids[0]) || {}).title || ids[0]}"` : `${ids.length} recordings`;
        // Moving to the Trash can be undone, so only a permanent deletion asks first.
        if (this.trash && !confirm(`Delete ${what} permanently? The files leave the disk, and this cannot be undone.`)) {
            return;
        }
        const failed = [];
        for (const id of ids) {
            try {
                await (this.trash ? api.purgeMatch(id) : api.deleteMatch(id));
            } catch (err) {
                failed.push(err.message);
            }
        }
        const done = ids.length - failed.length;
        if (failed.length) {
            this.app.hud.toast(`${failed.length} could not be ${this.trash ? 'deleted' : 'moved to the Trash'}. ${failed[0]}`, 'error', 7000);
        } else if (this.trash) {
            this.app.hud.toast(done === 1 ? 'Recording deleted permanently.' : `${done} recordings deleted permanently.`);
        } else {
            this.app.hud.toast(done === 1 ? 'Recording moved to the Trash. Restore it from the Trash view.' : `${done} recordings moved to the Trash. Restore them from the Trash view.`);
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
        for (const id of ids) {
            try {
                await api.restoreMatch(id);
            } catch (err) {
                failed.push(err.message);
            }
        }
        const done = ids.length - failed.length;
        if (failed.length) {
            this.app.hud.toast(`${failed.length} could not be restored. ${failed[0]}`, 'error', 7000);
        } else {
            this.app.hud.toast(done === 1 ? 'Recording restored to the library.' : `${done} recordings restored to the library.`);
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
            this.app.hud.toast(`${failed} of ${ids.length} recordings could not be moved.`, 'error');
        } else {
            this.app.hud.toast(`${ids.length === 1 ? 'Recording' : `${ids.length} recordings`} moved to ${folder || 'the top level'}.`);
        }
        this.selected.clear();
        this.refresh();
    }

    // Asks for a new folder's name and keeps it, returning its path or null.
    askFolder() {
        const name = prompt('Name of the new folder', '');
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
        const name = prompt('New name for this folder', path.split('/').pop());
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
            this.app.hud.toast(`${failed} of ${inside.length} recordings could not be moved, the folder keeps its name. ${error}`, 'error', 7000);
            await this.refresh();
            return;
        }
        this.extraFolders = this.extraFolders.map((f) => (f === path || f.startsWith(`${path}/`) ? target + f.slice(path.length) : f));
        saveFolders(this.extraFolders);
        if (this.folder === path || this.folder.startsWith(`${path}/`)) {
            this.folder = target + this.folder.slice(path.length);
        }
        this.app.hud.toast(`Folder renamed to ${clean}.`);
        this.refresh();
    }

    async deleteFolder(path) {
        const inside = this.list.filter((m) => cleanPath(m.folder || '') && this.inFolder(m, path));
        const parent = path.split('/').slice(0, -1).join('/');
        if (inside.length && !confirm(`Delete the folder "${path}"? Its ${inside.length} recordings move to ${parent || 'the top level'}, none is deleted.`)) {
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
