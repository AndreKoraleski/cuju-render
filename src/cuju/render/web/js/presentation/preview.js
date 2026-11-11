// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The preview of a team package, a panel over the match view for authors. It opens with
// `preview=left` or `preview=right` in the page's address, on that side, as `cuju render pack
// preview` opens it, with `preview=1` on the side whose package loads, or from
// `cuju.presentation.preview.open()`. Buttons send events of the package's own team at once, so
// each reflex and each effect plays on demand, and meters show the team's budgets, the flash
// governor, the loudness of the master and of each team bus, and the worker's log. The panel
// reads what `cuju.presentation.status()` gives, which an agent may read the same way.

import { formatNumber, has, t } from '../core/i18n.js';
import { h } from '../teams/library.js';

export const EVENTS = ['touch', 'pass', 'shot', 'header', 'save', 'slide', 'goal', 'celebration.begin', 'winner.reveal', 'mvp.reveal', 'halftime'];
const KINDS = ['particles', 'lights', 'localLights', 'shaders', 'voices', 'worklets', 'drawCalls', 'triangles', 'textureBytes', 'geometryBytes', 'audioBytes'];

// The side that the value of preview= in the page's address names, left or right, or null for
// the side whose package loads, as `preview=1` asks.
export function previewSide(value) {
    const v = String(value || '').toLowerCase();
    return v === 'left' ? 0 : v === 'right' ? 1 : null;
}

// A number in the page's language with a fixed count of decimals.
const fixed = (x, digits) => formatNumber(Number(x) || 0, { minimumFractionDigits: digits, maximumFractionDigits: digits });
const db = (x) => (x == null || !Number.isFinite(x) ? t('presentation.preview.none') : fixed(x, 1));
const count = (x) => formatNumber(Math.round(Number(x) || 0));

// A word of the contract, a level, a worker's status, a rung or a budget, in the page's
// language, the contract's own name for one the language lacks.
function word(group, value) {
    const key = `presentation.preview.${group}.${value == null ? 'none' : value}`;
    return has(key) ? t(key) : String(value);
}

export class Preview {
    constructor(app) {
        this.app = app;
        this.panel = null;
        this.side = 0;
        // Whether the side follows the package the page loads, until the viewer picks one.
        this.auto = true;
        this.timer = null;
        const check = () => {
            const raw = location.hash.replace(/^#/, '');
            const value = new URLSearchParams(raw).get('preview');
            if (value && !this.panel) {
                this.open(previewSide(value));
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
        this.auto = side == null;
        if (side == null) {
            side = p.packages[0] ? 0 : p.packages[1] ? 1 : 0;
        }
        this.side = side;
        if (this.panel) {
            return;
        }
        const buttons = EVENTS.map((kind) => {
            const b = h('button', { type: 'button', class: 'bar-btn', 'data-event': kind }, word('event', kind));
            b.addEventListener('click', () => this.inject(kind));
            return b;
        });
        const close = h('button', { type: 'button', class: 'bar-btn', 'aria-label': t('presentation.preview.closeLabel') }, t('presentation.preview.close'));
        close.addEventListener('click', () => this.close());
        const sideButton = h('button', { type: 'button', class: 'bar-btn' }, t('presentation.preview.otherSide'));
        sideButton.addEventListener('click', () => {
            this.side = 1 - this.side;
            this.auto = false;
            this.render();
        });
        this.body = h('div', { class: 'preview-body' });
        this.panel = h('section', { id: 'presentation-preview', 'aria-label': t('presentation.preview.label'), class: 'panel',
            style: 'position:fixed;right:12px;top:64px;width:340px;max-height:80vh;overflow:auto;z-index:40;padding:10px;font-size:12px;background:var(--panel-bg, rgba(16,20,28,0.92));color:var(--text, #eee);border-radius:8px' },
        h('h2', { style: 'font-size:14px;margin:0 0 6px' }, t('presentation.preview.heading')),
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

    // Moves the panel below the offer of the 2D view while the offer shows, which sits in the
    // same corner of the view.
    avoidOffer() {
        const offer = document.getElementById('flat-suggest');
        const top = offer && !offer.hidden ? Math.round(offer.getBoundingClientRect().bottom) + 8 : 64;
        this.panel.style.top = `${Math.max(64, top)}px`;
    }

    // The panel's figures, from the presentation's status.
    render() {
        if (!this.panel) {
            return;
        }
        const s = this.app.presentation.status();
        // A panel opened before the packages loaded follows the side that has one.
        if (this.auto && !s.packages[this.side] && s.packages[1 - this.side]) {
            this.side = 1 - this.side;
        }
        this.avoidOffer();
        const pkg = s.packages[this.side];
        const lines = [];
        if (!pkg) {
            lines.push([t('presentation.preview.package'), t('presentation.preview.noPackage', { side: word('side', this.side ? 'right' : 'left') })]);
        } else {
            lines.push([t('presentation.preview.package'), t('presentation.preview.packageLine', {
                name: pkg.name || pkg.team, level: word('level', pkg.level), status: word('status', pkg.status), rung: word('rung', pkg.budget.level),
            })]);
            lines.push([t('presentation.preview.mainThread'), t('presentation.preview.ofMs', { used: fixed(pkg.budget.mainMs || 0, 2), limit: fixed(pkg.budget.limits.mainMs, 2) })]);
            for (const k of KINDS) {
                if (pkg.budget.limits[k] != null) {
                    lines.push([word('kind', k), t('presentation.preview.of', { used: count(pkg.budget.used[k]), limit: count(pkg.budget.limits[k]) })]);
                }
            }
        }
        const none = t('presentation.preview.none');
        const fx = s.effects[this.side];
        if (fx) {
            lines.push([t('presentation.preview.effects'), t('presentation.preview.effectsLine', {
                instances: count(fx.instances), particles: count(fx.particles), decals: count(fx.decals), lit: count(fx.poolLit), lights: count(fx.poolLights), local: count(fx.localLights),
            })]);
        }
        lines.push([t('presentation.preview.flashes'), t(s.flash.clamped ? 'presentation.preview.flashesClamped' : 'presentation.preview.flashesLine', {
            general: count(s.flash.counts.general), red: count(s.flash.counts.red), factor: fixed(s.flash.factor, 2),
        })]);
        const m = s.audio.master;
        lines.push([t('presentation.preview.master'), m ? t('presentation.preview.masterLine', {
            momentary: db(m.momentary), shortTerm: db(m.shortTerm), integrated: db(m.integrated), truePeak: db(m.truePeak),
        }) : t('presentation.preview.notMetered')]);
        const bus = s.audio.teams[this.side];
        if (bus) {
            const e = bus.meters.effects;
            lines.push([t('presentation.preview.bus'), e ? t(bus.penalized ? 'presentation.preview.busPenalized' : 'presentation.preview.busLine', {
                momentary: db(e.momentary), shortTerm: db(e.shortTerm), down: db(e.reduction),
            }) : t('presentation.preview.quiet')]);
            lines.push([t('presentation.preview.voices'), t('presentation.preview.voicesLine', {
                voices: count(bus.voices), music: bus.music.join(', ') || none, processors: bus.processors.join(', ') || none,
            })]);
        }
        lines.push([t('presentation.preview.moments'), t('presentation.preview.momentsLine', {
            camera: count(s.moments.accepted.camera), time: count(s.moments.accepted.time), environment: count(s.moments.accepted.environment),
        })]);
        if (s.moments.refused.length) {
            lines.push([t('presentation.preview.refused'), s.moments.refused.slice(-3).join(', ')]);
        }
        lines.push([t('presentation.preview.passes'), t('presentation.preview.passesLine', {
            layers: s.post.layers.filter(Boolean).join(', ') || t('presentation.preview.noLayer'), moments: count(s.post.moments.length), drawn: count(s.post.drawn),
        })]);
        if (pkg) {
            lines.push([t('presentation.preview.log'), (pkg.log || []).slice(-5).join(', ') || t('presentation.preview.empty')]);
            if (pkg.errors.length) {
                lines.push([t('presentation.preview.errors'), pkg.errors.slice(-3).join(', ')]);
            }
        }
        this.body.replaceChildren(...lines.map(([k, v]) => h('div', { class: 'preview-line' }, h('strong', {}, `${k} `), v)));
    }
}
