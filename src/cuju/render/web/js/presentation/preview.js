// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The preview of a team package, a panel over the match view for authors. It opens with
// `preview=1` in the page's address, as `cuju render pack preview` opens it, or from
// `cuju.presentation.preview.open()`. Buttons send events of the package's own team at once, so
// each reflex and each effect plays on demand, and meters show the team's budgets, the flash
// governor, the loudness of the master and of each team bus, and the worker's log. The panel
// reads what `cuju.presentation.status()` gives, which an agent may read the same way.

import { h } from '../teams/library.js';

export const EVENTS = ['touch', 'pass', 'shot', 'header', 'save', 'slide', 'goal', 'celebration.begin', 'winner.reveal', 'mvp.reveal', 'halftime'];
const KINDS = ['particles', 'lights', 'localLights', 'shaders', 'voices', 'worklets', 'drawCalls', 'triangles', 'textureBytes', 'geometryBytes', 'audioBytes'];

const db = (x) => (x == null || !Number.isFinite(x) ? 'none' : `${x.toFixed(1)}`);

export class Preview {
    constructor(app) {
        this.app = app;
        this.panel = null;
        this.side = 0;
        this.timer = null;
        const check = () => {
            const raw = location.hash.replace(/^#/, '');
            if (new URLSearchParams(raw).get('preview') && !this.panel) {
                this.open();
            }
        };
        addEventListener('hashchange', check);
        check();
    }

    // Sends an event of the team on side, at once, to its reflexes and its worker.
    inject(kind) {
        return this.app.presentation.inject(this.side, kind);
    }

    open(side = null) {
        const p = this.app.presentation;
        if (side == null) {
            side = p.packages[0] ? 0 : p.packages[1] ? 1 : 0;
        }
        this.side = side;
        if (this.panel) {
            return;
        }
        const buttons = EVENTS.map((kind) => {
            const b = h('button', { type: 'button', class: 'bar-btn', 'data-event': kind }, kind);
            b.addEventListener('click', () => this.inject(kind));
            return b;
        });
        const close = h('button', { type: 'button', class: 'bar-btn', 'aria-label': 'Close the preview' }, 'Close');
        close.addEventListener('click', () => this.close());
        const sideButton = h('button', { type: 'button', class: 'bar-btn' }, 'Other side');
        sideButton.addEventListener('click', () => {
            this.side = 1 - this.side;
            this.render();
        });
        this.body = h('div', { class: 'preview-body' });
        this.panel = h('section', { id: 'presentation-preview', 'aria-label': 'Preview of the team package', class: 'panel',
            style: 'position:fixed;right:12px;top:64px;width:340px;max-height:80vh;overflow:auto;z-index:40;padding:10px;font-size:12px;background:var(--panel-bg, rgba(16,20,28,0.92));color:var(--text, #eee);border-radius:8px' },
        h('h2', { style: 'font-size:14px;margin:0 0 6px' }, 'Package preview'),
        h('div', { class: 'preview-events', style: 'display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px' }, ...buttons),
        h('div', { style: 'display:flex;gap:4px;margin-bottom:8px' }, sideButton, close),
        this.body);
        document.body.appendChild(this.panel);
        this.timer = setInterval(() => this.render(), 250);
        this.render();
    }

    close() {
        clearInterval(this.timer);
        if (this.panel) {
            this.panel.remove();
        }
        this.panel = null;
    }

    // The panel's figures, from the presentation's status.
    render() {
        if (!this.panel) {
            return;
        }
        const s = this.app.presentation.status();
        const pkg = s.packages[this.side];
        const lines = [];
        if (!pkg) {
            lines.push(['Package', `none on side ${this.side}`]);
        } else {
            lines.push(['Package', `${pkg.name || pkg.team}, ${pkg.level}, ${pkg.status}, rung ${pkg.budget.level}`]);
            lines.push(['Main thread p95', `${(pkg.budget.p95 || 0).toFixed(2)} of ${pkg.budget.limits.mainMs} ms`]);
            for (const k of KINDS) {
                if (pkg.budget.limits[k] != null) {
                    lines.push([k, `${Math.round(pkg.budget.used[k] || 0)} of ${pkg.budget.limits[k]}`]);
                }
            }
        }
        const fx = s.effects[this.side];
        if (fx) {
            lines.push(['Effects', `${fx.instances} live, ${fx.particles} particles, ${fx.decals} decals, ${fx.poolLit} of ${fx.poolLights} pool lights, ${fx.localLights} local`]);
        }
        lines.push(['Flashes in a second', `${s.flash.counts.general} general, ${s.flash.counts.red} red, factor ${s.flash.factor.toFixed(2)}${s.flash.clamped ? ', clamped' : ''}`]);
        const m = s.audio.master;
        lines.push(['Master', m ? `M ${db(m.momentary)}, S ${db(m.shortTerm)}, I ${db(m.integrated)} LUFS, TP ${db(m.truePeak)} dBTP` : 'not metered, sound off']);
        const bus = s.audio.teams[this.side];
        if (bus) {
            const e = bus.meters.effects;
            lines.push(['Team bus', e ? `M ${db(e.momentary)}, S ${db(e.shortTerm)} LUFS, down ${db(e.reduction)} dB${bus.penalized ? ', penalized' : ''}` : 'quiet']);
            lines.push(['Voices', `${bus.voices}, music ${bus.music.join(', ') || 'none'}, processors ${bus.processors.join(', ') || 'none'}`]);
        }
        lines.push(['Moments', `${s.moments.accepted.camera} camera, ${s.moments.accepted.time} time, ${s.moments.accepted.environment} environment`]);
        if (s.moments.refused.length) {
            lines.push(['Refused', s.moments.refused.slice(-3).join(', ')]);
        }
        lines.push(['Passes', `${s.post.layers.filter(Boolean).join(', ') || 'no layer'}, ${s.post.moments.length} moments, ${s.post.drawn} drawn`]);
        if (pkg) {
            lines.push(['Worker log', (pkg.log || []).slice(-3).join(', ') || 'empty']);
            if (pkg.errors.length) {
                lines.push(['Errors', pkg.errors.slice(-3).join(', ')]);
            }
        }
        this.body.replaceChildren(...lines.map(([k, v]) => h('div', { class: 'preview-line' }, h('strong', {}, `${k} `), v)));
    }
}
