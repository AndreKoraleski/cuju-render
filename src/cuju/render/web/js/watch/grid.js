// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The grid of environments of a live source. A panel over the Watch page shows a page of the
// batch's environments as small 2D views, each with its score, its clock and its index, which the
// source refreshes at a modest pace while the panel is open. A click or Enter on a tile shows that
// environment in the main view, through the switch of environments, and the arrow keys move
// between the tiles.

import { api } from '../core/api.js';
import { t, tn } from '../core/i18n.js';
import { drawPitch, drawScene, formatClock, pitchTransform, teamPaint } from './pitch2d.js';

// The sizes of the grid, square numbers of tiles up to the most that a request may ask for.
export const GRID_SIZES = [4, 9, 16, 25, 36, 49, 64];
// The page asks the source for its tiles this often, the source reads states at its own pace.
export const POLL_MS = 1000;

export function gridColumns(size) {
    return Math.max(1, Math.ceil(Math.sqrt(size)));
}

// The sizes worth offering for a batch of count environments, every size below the count and the
// first that holds them all.
export function gridSizes(count) {
    const sizes = [];
    for (const size of GRID_SIZES) {
        sizes.push(size);
        if (size >= count) {
            break;
        }
    }
    return sizes;
}

// The index that a key moves the focus to among count tiles in rows of columns, the same index at
// an edge, and -1 for a key that moves nothing.
export function moveIndex(index, key, columns, count) {
    switch (key) {
    case 'ArrowLeft':
        return Math.max(0, index - 1);
    case 'ArrowRight':
        return Math.min(count - 1, index + 1);
    case 'ArrowUp':
        return index - columns >= 0 ? index - columns : index;
    case 'ArrowDown':
        return index + columns < count ? index + columns : index;
    case 'Home':
        return 0;
    case 'End':
        return count - 1;
    default:
        return -1;
    }
}

// The scene of a tile of the source, in the form that sceneFromFrames gives a frame.
export function sceneFromTile(tile) {
    return {
        players: tile.teams.map((team, i) => ({
            slot: i,
            x: tile.players[2 * i],
            y: tile.players[2 * i + 1],
            team,
            index: i,
            goalkeeper: false,
            active: !!tile.active[i],
            controlled: false,
            owner: false,
        })),
        ball: tile.ball,
        score: tile.score,
        clockMs: tile.clock,
        step: tile.step,
        mode: tile.mode,
    };
}

// What the tile of an environment shows after an answer of the source. A tile that the source
// answered with shows as it is. When the source answered none, the last tile it gave for the
// environment stays and is marked as refreshing, and without one the environment waits for its
// first picture. The label names what the tile shows, for screen readers.
export function tileState(environment, answered, held) {
    const tile = answered || held || null;
    if (!tile) {
        return { tile: null, refreshing: false, label: t('grid.tile.waiting.label', { environment }) };
    }
    const refreshing = !answered;
    const clock = formatClock(tile.clock);
    const label = t('grid.tile.label', { environment, left: tile.score[0], right: tile.score[1], clock });
    return { tile, refreshing, clock, label: refreshing ? t('grid.tile.label.refreshing', { label }) : label };
}

function load(key, fallback) {
    try {
        const v = localStorage.getItem(`cuju.${key}`);
        return v === null ? fallback : JSON.parse(v);
    } catch {
        return fallback;
    }
}

function save(key, value) {
    try {
        localStorage.setItem(`cuju.${key}`, JSON.stringify(value));
    } catch {
        // Storage can be unavailable, the size then lasts for this visit only.
    }
}

function el(tag, attributes = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) {
        if (key === 'class') {
            node.className = value;
        } else if (key === 'text') {
            node.textContent = value;
        } else {
            node.setAttribute(key, value);
        }
    }
    node.append(...children);
    return node;
}

export class EnvironmentGrid {
    constructor(app) {
        this.app = app;
        this.open = false;
        this.timer = null;
        this.tiles = [];
        // The last tile that the source gave for each environment, while the grid shows its source.
        this.held = new Map();
        this.first = 0;
        this.size = load('gridSize', 9);
        this.sourceId = null;
        this.count = 1;
        this.focusIndex = 0;
        this.opener = null;
        this.build();
        this.button = document.getElementById('live-grid');
        if (this.button) {
            this.button.addEventListener('click', () => this.show());
        }
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && this.open) {
                this.poll();
            }
        });
    }

    build() {
        this.title = el('h3', { class: 'panel-title', id: 'env-grid-title', text: t('grid.title') });
        this.sizeSelect = el('select', { id: 'env-grid-size', 'aria-label': t('grid.size.label') });
        this.sizeSelect.addEventListener('change', () => {
            this.size = Number(this.sizeSelect.value);
            save('gridSize', this.size);
            this.first = Math.floor(this.current() / this.size) * this.size;
            this.layout(true);
        });
        this.previous = el('button', { type: 'button', class: 'btn small', text: t('grid.previous') });
        this.previous.addEventListener('click', () => this.page(-1));
        this.next = el('button', { type: 'button', class: 'btn small', text: t('grid.next') });
        this.next.addEventListener('click', () => this.page(1));
        const close = el('button', { type: 'button', class: 'btn small', text: t('grid.close') });
        close.addEventListener('click', () => this.hide());
        this.range = el('span', { class: 'env-grid-range muted' });
        this.status = el('p', { class: 'env-grid-status muted small', role: 'status' });
        this.body = el('div', { class: 'env-grid-tiles', role: 'group', 'aria-label': t('grid.tiles.label') });
        this.body.addEventListener('keydown', (e) => this.onKey(e));
        const head = el('div', { class: 'env-grid-head' }, this.title, this.range,
            el('label', { class: 'env-grid-size' }, el('span', { text: t('grid.size') }), this.sizeSelect),
            this.previous, this.next, close);
        this.panel = el('div', { id: 'env-grid', role: 'dialog', 'aria-labelledby': 'env-grid-title', 'data-prompt': '' },
            head, this.status, this.body);
        this.panel.hidden = true;
        this.panel.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                this.hide();
            }
        });
        document.getElementById('watch').appendChild(this.panel);
    }

    // The live source that the grid can show, one of this server with several environments.
    eligible() {
        const source = this.app.source;
        const live = source && source.kind === 'live' ? source.live : null;
        return !!live && !source.game && !live.url && (source.header.environment_count || 1) > 1;
    }

    // The entry of the View menu, for a live source with several environments alone.
    menuItems(menuItem) {
        if (!this.eligible()) {
            return [];
        }
        return [menuItem(t('grid.menu'), {
            hint: t('grid.menu.hint', { count: this.app.source.header.environment_count }),
            onSelect: () => setTimeout(() => this.show(), 0),
        })];
    }

    // The Grid button beside the live controls, shown for a source with several environments.
    update() {
        if (this.button) {
            this.button.hidden = !this.eligible();
        }
        if (this.open && this.app.source && this.app.source.id !== this.sourceId) {
            this.hide();
        }
    }

    current() {
        const header = this.app.source && this.app.source.header;
        return (header && header.provenance && header.provenance.environment) || 0;
    }

    show() {
        if (!this.eligible()) {
            this.app.hud.toast(t('grid.ineligible'), 'info');
            return;
        }
        const source = this.app.source;
        if (source.id !== this.sourceId) {
            this.held = new Map();
        }
        this.sourceId = source.id;
        this.count = source.header.environment_count;
        const sizes = gridSizes(this.count);
        if (!sizes.includes(this.size)) {
            this.size = sizes.find((s) => s >= Math.min(9, this.count)) || sizes.at(-1);
        }
        this.sizeSelect.replaceChildren(...sizes.map((s) => el('option', { value: String(s), text: String(s) })));
        this.sizeSelect.value = String(this.size);
        this.first = Math.floor(this.current() / this.size) * this.size;
        this.opener = document.activeElement;
        this.app.releasePointer();
        this.open = true;
        this.panel.hidden = false;
        this.status.textContent = t('grid.asking');
        this.layout(true);
    }

    // Closes the panel, and gives the focus back to its opener unless the page changed.
    hide(restore = true) {
        if (!this.open) {
            return;
        }
        this.open = false;
        this.panel.hidden = true;
        clearTimeout(this.timer);
        this.timer = null;
        const back = this.opener && this.opener.isConnected && this.opener.getClientRects().length ? this.opener : document.getElementById('stage');
        if (restore) {
            back.focus();
        }
    }

    page(direction) {
        const first = this.first + direction * this.size;
        if (first < 0 || first >= this.count) {
            return;
        }
        this.first = first;
        this.layout(true);
    }

    // Builds the tiles of the current page and asks for their pictures, focusing one when asked.
    layout(focus) {
        const shown = Math.min(this.size, this.count - this.first);
        const columns = gridColumns(this.size);
        this.body.style.gridTemplateColumns = `repeat(${columns}, minmax(0, 1fr))`;
        this.body.style.gridTemplateRows = `repeat(${Math.ceil(this.size / columns)}, minmax(0, 1fr))`;
        const current = this.current();
        this.tiles = [];
        for (let i = 0; i < shown; i++) {
            const environment = this.first + i;
            const canvas = el('canvas', { 'aria-hidden': 'true' });
            const tile = el('button', {
                type: 'button',
                class: 'env-tile',
                tabindex: '-1',
                'data-environment': String(environment),
            }, canvas, el('span', { class: 'env-tile-label', text: `${environment}` }));
            if (environment === current) {
                tile.setAttribute('aria-current', 'true');
            }
            tile.addEventListener('click', () => this.choose(environment));
            tile.addEventListener('focus', () => {
                this.focusIndex = i;
                for (const other of this.tiles) {
                    other.tabIndex = other === tile ? 0 : -1;
                }
            });
            this.tiles.push(tile);
        }
        this.body.replaceChildren(...this.tiles);
        this.range.textContent = t('grid.range', { first: this.first, last: this.first + shown - 1, count: this.count });
        this.previous.disabled = this.first === 0;
        this.next.disabled = this.first + this.size >= this.count;
        const start = current >= this.first && current < this.first + shown ? current - this.first : 0;
        this.focusIndex = start;
        if (this.tiles[start]) {
            this.tiles[start].tabIndex = 0;
            if (focus) {
                this.tiles[start].focus();
            }
        }
        // A tile read before shows at once, refreshing until the source answers for it.
        for (const tile of this.tiles) {
            this.drawTile(tile, null);
        }
        clearTimeout(this.timer);
        this.poll();
    }

    onKey(e) {
        if (e.key === 'PageUp' || e.key === 'PageDown') {
            e.preventDefault();
            e.stopPropagation();
            this.page(e.key === 'PageUp' ? -1 : 1);
            return;
        }
        const next = moveIndex(this.focusIndex, e.key, gridColumns(this.size), this.tiles.length);
        if (next < 0) {
            return;
        }
        e.preventDefault();
        e.stopPropagation();
        this.tiles[next].focus();
    }

    // Asks the source for the tiles of the page, then again after POLL_MS while the grid is open,
    // the page shows and the source is the one the grid belongs to.
    async poll() {
        clearTimeout(this.timer);
        this.timer = null;
        if (this.open && (!this.eligible() || this.app.source.id !== this.sourceId)) {
            this.hide();
            return;
        }
        if (!this.open || document.hidden || this.app.page !== 'watch') {
            if (this.app.page !== 'watch') {
                this.hide(false);
            }
            return;
        }
        const id = this.sourceId;
        const first = this.first;
        const size = this.size;
        try {
            const document_ = await api.liveGrid(id, first, size);
            if (!this.open || id !== this.sourceId || first !== this.first || size !== this.size) {
                return;
            }
            const waiting = document_.tiles.filter((tile) => !tile).length;
            this.status.replaceChildren(...(waiting
                ? [t('grid.status.waiting', { count: waiting, total: document_.tiles.length })]
                : tn('grid.status.ready')));
            document_.tiles.forEach((tile, i) => {
                if (tile) {
                    this.held.set(first + i, tile);
                }
                if (this.tiles[i]) {
                    this.drawTile(this.tiles[i], tile);
                }
            });
        } catch (err) {
            if (!this.open || id !== this.sourceId) {
                return;
            }
            this.status.textContent = err.status === 404
                ? t('grid.error.unavailable', { error: err.message })
                : t('grid.error.retry', { error: err.message });
            if (err.status === 404) {
                return;
            }
        }
        if (this.open) {
            this.timer = setTimeout(() => this.poll(), POLL_MS);
        }
    }

    // Draws the tile of an answer, or the last tile of its environment, which then shows dimmed
    // and marked as refreshing, or the wait for a first picture.
    drawTile(node, answered) {
        const canvas = node.querySelector('canvas');
        const ratio = Math.min(2, window.devicePixelRatio || 1);
        const w = Math.max(40, canvas.clientWidth || 160);
        const h = Math.max(30, canvas.clientHeight || 110);
        if (canvas.width !== Math.round(w * ratio) || canvas.height !== Math.round(h * ratio)) {
            canvas.width = Math.round(w * ratio);
            canvas.height = Math.round(h * ratio);
        }
        const ctx = canvas.getContext('2d');
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        const strip = Math.max(10, Math.min(16, Math.round(h * 0.09))) + 8;
        const transform = pitchTransform(w, h, { top: strip, side: 2, bottom: 2 });
        drawPitch(ctx, transform);
        const environment = Number(node.dataset.environment);
        const { tile, refreshing, clock, label } = tileState(environment, answered, this.held.get(environment));
        node.setAttribute('aria-label', label);
        node.toggleAttribute('data-refreshing', refreshing);
        if (!tile) {
            delete node.dataset.step;
            drawScene(ctx, transform, { players: [], ball: null }, [], { scoreboard: t('grid.tile.waiting', { environment }) });
            return;
        }
        const header = this.app.source && this.app.source.header;
        const paint = teamPaint(header, this.app.styles);
        const scoreboard = `${environment}   ${tile.score[0]} : ${tile.score[1]}   ${clock}`;
        if (refreshing) {
            ctx.globalAlpha = 0.45;
            drawScene(ctx, transform, sceneFromTile(tile), paint, { numbers: false });
            ctx.globalAlpha = 1;
            drawScene(ctx, transform, { players: [], ball: null }, paint, { scoreboard: t('grid.tile.refreshing', { scoreboard }) });
        } else {
            drawScene(ctx, transform, sceneFromTile(tile), paint, { numbers: false, scoreboard });
        }
        node.dataset.step = String(tile.step);
    }

    // Shows an environment in the main view, through the switch of the live source.
    choose(environment) {
        const current = this.current();
        this.hide();
        if (environment === current) {
            return;
        }
        const input = document.getElementById('live-env-index');
        input.value = String(environment);
        this.app.switchEnvironment();
    }
}
