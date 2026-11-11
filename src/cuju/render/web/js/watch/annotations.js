// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The overlay of annotations on the Watch page. The numbers, the chosen and likely actions and the
// text of each player show under the player, the whole match's in a box over the controls, and
// chosen series as lines on the timeline. The Annotations panel picks what shows. A recording or
// stream without annotations keeps the overlay and its button hidden.

import * as THREE from 'three';
import { t } from '../core/i18n.js';
import { h } from '../teams/library.js';
import { Dropdown } from '../core/menu.js';
import { icon, symbolOnly } from '../core/icons.js';
import { labelHeight, labelTop, noteLines, seriesPath } from '../recording/annotation-data.js';

const SVG = 'http://www.w3.org/2000/svg';
// The colors of the lines, by the position of a series in the panel.
const COLORS = 4;
// The series that a recording opens with, the first ones in the panel.
const FIRST_SERIES = 1;

function load() {
    try {
        const stored = JSON.parse(localStorage.getItem('cuju.annotations'));
        return stored && typeof stored === 'object' ? stored : {};
    } catch {
        return {};
    }
}

function save(options) {
    try {
        localStorage.setItem('cuju.annotations', JSON.stringify(options));
    } catch {
        // Storage can be unavailable, the choice then lasts for this visit only.
    }
}

export class AnnotationOverlay {
    constructor(app) {
        this.app = app;
        this.store = null;
        this.data = null;
        this.chosen = new Set();
        this.listed = -1;
        this.drawn = '';
        this.placed = 0;
        const stored = load();
        this.options = Object.fromEntries(['players', 'actions', 'text'].map((key) => [key, stored[key] !== false]));
        this.button = h('button', { type: 'button', class: 'icon-btn', id: 'annotations-button', ...symbolOnly(t('annotations.button'), t('annotations.button.title')), hidden: true }, icon('layers'));
        this.list = h('div', { class: 'annotation-series', role: 'group', 'aria-labelledby': 'annotation-series-title' });
        const check = (key, text) => {
            const input = h('input', { type: 'checkbox', id: `annotation-${key}` });
            input.checked = this.options[key];
            input.addEventListener('change', () => {
                this.options[key] = input.checked;
                save(this.options);
                this.placed = 0;
            });
            return h('label', { class: 'check' }, input, ` ${text}`);
        };
        this.panel = h('div', { id: 'annotations-panel', class: 'popover', role: 'dialog', 'aria-label': t('annotations.title') },
            h('h3', { class: 'panel-title' }, t('annotations.title')),
            check('players', t('annotations.players')),
            check('actions', t('annotations.actions')),
            check('text', t('annotations.text')),
            h('p', { id: 'annotation-series-title' }, t('annotations.series.title')),
            this.list);
        document.body.append(this.panel);
        const row = document.querySelector('#controls .button-row');
        if (row) {
            row.append(h('div', { class: 'group annotations-group' }, this.button));
        }
        this.menu = new Dropdown(this.button, this.panel, { align: 'right' });
        this.layer = h('div', { class: 'annotation-labels', 'aria-hidden': 'true', hidden: true });
        document.body.append(this.layer);
        this.foot = new THREE.Vector3();
        this.matchBox = h('div', { class: 'annotation-match', hidden: true });
        const controls = document.getElementById('controls');
        if (controls) {
            controls.before(this.matchBox);
        }
        this.svg = document.createElementNS(SVG, 'svg');
        this.svg.setAttribute('class', 'timeline-series');
        this.svg.setAttribute('viewBox', '0 0 1000 100');
        this.svg.setAttribute('preserveAspectRatio', 'none');
        this.svg.setAttribute('aria-hidden', 'true');
        const timeline = document.getElementById('timeline');
        if (timeline) {
            timeline.append(this.svg);
        }
    }

    // Whether the overlay shows, a store with annotations on the Watch page.
    get active() {
        return !!this.data;
    }

    // Follows the timeline's store, called on every frame of the page. The labels move about ten
    // times a second, and the lines redraw when the annotations or the frames change.
    update() {
        const app = this.app;
        const store = app.timeline ? app.timeline.store : null;
        const data = store && store.annotations && store.annotations.size > 0 ? store.annotations : null;
        if (store !== this.store || data !== this.data) {
            const fresh = store !== this.store;
            this.store = store;
            this.data = data;
            this.button.hidden = !data;
            if (!data) {
                this.menu.close(false);
            }
            if (fresh) {
                this.chosen = new Set(data ? data.list().slice(0, FIRST_SERIES).map((s) => s.key) : []);
                this.listed = -1;
                this.drawn = '';
            }
        }
        app.playerTools.wanted = !!data && Object.values(this.options).some(Boolean);
        if (!data) {
            this.hide();
            return;
        }
        if (data.series.size !== this.listed) {
            this.fill();
        }
        this.draw();
        const now = performance.now();
        if (now - this.placed >= 100) {
            this.placed = now;
            this.place();
        }
    }

    hide() {
        this.layer.hidden = true;
        this.matchBox.hidden = true;
        if (this.svg.childElementCount) {
            this.svg.replaceChildren();
        }
        this.drawn = '';
    }

    // The panel's list of series, a check box for each with the color of its line.
    fill() {
        const app = this.app;
        const series = this.data.list();
        this.listed = this.data.series.size;
        if (!series.length) {
            this.list.replaceChildren(h('p', { class: 'muted small' }, t('annotations.series.none')));
            return;
        }
        this.list.replaceChildren(...series.map((s, i) => {
            const input = h('input', { type: 'checkbox', 'data-series': s.key });
            input.checked = this.chosen.has(s.key);
            input.addEventListener('change', () => {
                if (input.checked) {
                    this.chosen.add(s.key);
                } else {
                    this.chosen.delete(s.key);
                }
                this.drawn = '';
            });
            const owner = s.player >= 0 ? app.playerLabel(s.player) : t('annotations.series.match');
            return h('label', { class: 'check' }, input, h('i', { class: `series-swatch series-${i % COLORS}` }), ` ${t('annotations.series.item', { name: s.name, owner })}`);
        }));
    }

    // The key of a frame, its serial in a live stream and its index in a recording.
    key(index) {
        const frame = this.store.get(index);
        return frame && frame.sequence !== undefined ? frame.sequence : index;
    }

    // Draws the chosen series over the timeline, from its first frame to its last.
    draw() {
        const store = this.store;
        const first = store.first;
        const last = Math.max(first, store.last);
        const state = `${this.data.version}:${first}:${last}:${[...this.chosen].join(',')}`;
        if (state === this.drawn) {
            return;
        }
        this.drawn = state;
        // A live stream keys its frames by serial, which a map turns back into positions.
        let position = (frame) => frame;
        if (store.size && store.get(first).sequence !== undefined) {
            const positions = new Map();
            for (let i = first; i <= last; i++) {
                const frame = store.get(i);
                if (frame) {
                    positions.set(frame.sequence, i);
                }
            }
            position = (frame) => positions.get(frame);
        }
        const series = this.data.list();
        const paths = [];
        series.forEach((s, i) => {
            if (!this.chosen.has(s.key)) {
                return;
            }
            const points = this.data.points(s.key).map(([frame, value]) => [position(frame), value])
                .filter(([at]) => at !== undefined);
            const { path } = seriesPath(points, first, last, 1000, 100);
            if (path) {
                const node = document.createElementNS(SVG, 'path');
                node.setAttribute('d', path);
                node.setAttribute('class', `series-${i % COLORS}`);
                node.setAttribute('vector-effect', 'non-scaling-stroke');
                node.dataset.series = s.key;
                paths.push(node);
            }
        });
        this.svg.replaceChildren(...paths);
    }

    // The height of a player's feet on the screen, from the pose of the frame shown.
    feetY(index, rect) {
        const app = this.app;
        const world = app.players.position(app.pose, index, this.foot).setY(0);
        const screen = world.project(app.view.camera);
        return rect.top + (1 - screen.y) * rect.height / 2;
    }

    // Places the labels under the players in view and fills the box of the whole match.
    place() {
        const app = this.app;
        const covered = app.page !== 'watch' || app.director.running || app.postMatch.running || app.transition.active;
        const entry = covered || !app.timeline ? null : this.data.at(this.key(app.timeline.index));
        const lines = (record) => {
            const shown = noteLines(record);
            return [
                this.options.players ? shown.values : null,
                this.options.actions ? shown.action : null,
                this.options.text ? shown.text : null,
            ].filter(Boolean);
        };
        const match = entry ? lines(entry.match) : [];
        this.matchBox.hidden = !match.length;
        this.matchBox.replaceChildren(...match.map((line) => h('div', {}, line)));
        const nodes = [];
        if (entry && entry.players.size) {
            const used = [];
            const rect = app.view.renderer.domElement.getBoundingClientRect();
            const controls = document.getElementById('controls');
            const edge = controls && controls.getBoundingClientRect().height ? controls.getBoundingClientRect().top - 8 : rect.bottom;
            for (const point of app.playerTools.points.slice().sort((a, b) => a.depth - b.depth)) {
                const record = entry.players.get(point.index);
                const shown = record ? lines(record) : [];
                if (!shown.length) {
                    continue;
                }
                // The label hangs under the player's feet, so it leaves the player in view.
                const top = labelTop(point.y, this.feetY(point.index, rect), shown.length, edge);
                const height = labelHeight(shown.length);
                if (used.some((other) => Math.abs(other.x - point.x) < 120 && top < other.top + other.height && other.top < top + height)) {
                    continue;
                }
                used.push({ x: point.x, top, height });
                const label = h('span', { 'data-player': String(point.index) }, ...shown.map((line) => h('b', {}, line)));
                label.style.left = `${Math.max(rect.left + 90, Math.min(rect.right - 90, point.x))}px`;
                label.style.top = `${top}px`;
                nodes.push(label);
            }
        }
        this.layer.replaceChildren(...nodes);
        this.layer.hidden = !nodes.length;
    }
}
