// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The 2D view of the Watch page. It draws the timeline's current moment on a 2D canvas over the
// stage in place of the 3D picture, so playback, seeking, speed and live sources go on exactly as
// in 3D. The presentations that need the 3D view, replays, celebrations, lineups, restart
// transitions and the show after the match, are skipped while it draws, and the goal graphic of
// the scoreboard stays. A browser without WebGL gets a view without a renderer and the 2D view
// alone, and a page whose 3D picture runs very slowly is offered the 2D view once.

import * as THREE from 'three';
import { drawPitch, drawScene, pitchTransform, playerNumber, sceneFromFrames, teamPaint } from './pitch2d.js';

// The settings of presentations that need the 3D view, read as off while the 2D view draws.
export const NEEDS_3D = ['replays', 'celebrations', 'lineups', 'transitions', 'decisionReplays', 'podium'];
// The 3D picture is very slow below this many frames a second, measured over SLOW_WINDOW seconds
// of playback.
export const SLOW_FPS = 12;
const SLOW_WINDOW = 5;

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
        // Storage can be unavailable, the setting then lasts for this visit only.
    }
}

// A renderer that draws nothing, for a browser without WebGL. It answers what the scene code asks
// of a renderer, so the page builds its scene as usual and the 2D view draws in its place.
function silentRenderer() {
    const canvas = document.createElement('canvas');
    return {
        domElement: canvas,
        capabilities: { isWebGL2: false, getMaxAnisotropy: () => 1 },
        shadowMap: { enabled: false },
        outputColorSpace: THREE.SRGBColorSpace,
        toneMapping: THREE.NoToneMapping,
        toneMappingExposure: 1,
        autoClear: true,
        setPixelRatio() {},
        getPixelRatio: () => 1,
        setSize() {},
        getSize: (v) => v.set(1, 1),
        getDrawingBufferSize: (v) => v.set(1, 1),
        setRenderTarget() {},
        getRenderTarget: () => null,
        setClearColor() {},
        getClearColor: (c) => c,
        getClearAlpha: () => 1,
        render() {},
        compile() {},
        dispose() {},
    };
}

// A View of scene.js without WebGL, its scene, camera and lights as the real one builds them, and
// a renderer that draws nothing. View is passed in so that this module needs no copy of it.
export function headlessView(container, View) {
    const view = Object.create(View.prototype);
    view.container = container;
    view.renderer = silentRenderer();
    container.appendChild(view.renderer.domElement);
    view.scene = new THREE.Scene();
    view.scene.fog = new THREE.FogExp2(0xbccbd9, 0.0012);
    view.camera = new THREE.PerspectiveCamera(30, 1, 0.1, 2500);
    view.sun = new THREE.DirectionalLight(0xfff1dc, 3.0);
    view.scene.add(view.sun, view.sun.target);
    view.hemi = new THREE.HemisphereLight(0xcfe3ff, 0x3a5a2a, 1.15);
    view.scene.add(view.hemi);
    view.quality = null;
    view.bloom = null;
    view.bloomStrength = 0.2;
    view.light = null;
    view.headless = true;
    view.setQuality = (name) => {
        view.quality = name;
    };
    view.render = () => {};
    view.resizeObserver = new ResizeObserver(() => view.resize());
    view.resizeObserver.observe(container);
    view.resize();
    return view;
}

export class FlatMode {
    // forced, the reason when the browser has no WebGL, so the 2D view is the only one.
    constructor(app, forced = null) {
        this.app = app;
        this.forced = forced;
        this.wanted = !!forced || !!load('view2d', false);
        this.stage = document.getElementById('stage');
        this.canvas = document.createElement('canvas');
        this.canvas.id = 'flat-view';
        this.canvas.setAttribute('aria-hidden', 'true');
        this.stage.appendChild(this.canvas);
        this.ctx = this.canvas.getContext('2d');
        this.pitch = null;
        this.paintKey = null;
        this.paint = null;
        this.numbers = null;
        this.told = new Set();
        // The measurement of the 3D picture's speed, frames and seconds of the current window.
        this.frames = 0;
        this.seconds = 0;
        this.lastNow = 0;
        this.suggested = false;
        this.prompt = this.buildPrompt();
        this.box = document.getElementById('view-2d');
        if (this.box) {
            this.box.checked = this.wanted;
            this.box.disabled = !!forced;
            this.box.addEventListener('change', () => this.set(this.box.checked));
        }
        this.sync();
        if (forced) {
            app.hud.toast('This browser cannot draw 3D, so Watch shows the 2D view.', 'info', 6000);
        }
    }

    // Whether the 2D view draws now, on the Watch page.
    get on() {
        return this.wanted && this.app.page === 'watch';
    }

    // The settings of the page as the presentations read them. While the 2D view draws, those that
    // need the 3D view read as off, and every write goes to the stored settings unchanged. The
    // field stored gives the stored settings themselves, for the panels that show them.
    gate(settings) {
        const off = new Set(NEEDS_3D);
        return new Proxy(settings, {
            get: (target, key, receiver) => {
                if (key === 'stored') {
                    return target;
                }
                return off.has(key) && this.on ? false : Reflect.get(target, key, receiver);
            },
        });
    }

    set(on, quiet = false) {
        if (this.forced) {
            on = true;
        }
        if (on === this.wanted) {
            this.sync();
            return;
        }
        this.wanted = !!on;
        save('view2d', this.wanted);
        if (this.wanted) {
            this.stopShows();
        }
        this.sync();
        this.app.cameras.jump();
        if (!quiet) {
            this.app.hud.toast(this.wanted ? 'The 2D view. Replays and shows wait for the 3D view.' : 'The 3D view.', 'info', 2500);
        }
    }

    toggle() {
        this.set(!this.wanted);
    }

    // Ends whatever presentation runs, since each takes the camera of the 3D view.
    stopShows() {
        const app = this.app;
        if (app.postMatch && app.postMatch.running) {
            app.postMatch.end({ home: false });
        }
        if (app.director && app.director.running) {
            app.director.stop(true);
        }
        if (app.transition && app.transition.active) {
            app.transition.abort(true);
        }
    }

    sync() {
        this.canvas.hidden = !this.wanted;
        document.getElementById('app').classList.toggle('flat-2d', this.wanted);
        if (this.box) {
            this.box.checked = this.wanted;
        }
        if (this.wanted) {
            this.prompt.hidden = true;
        }
    }

    // A replay or a show that needs the 3D view says once that it waits for it, and is skipped.
    blocks(kind) {
        if (!this.on) {
            return false;
        }
        if (!this.told.has(kind)) {
            this.told.add(kind);
            this.app.hud.toast('Replays need the 3D view, which the View menu turns back on.', 'info', 3500);
        }
        return true;
    }

    // The entry of the View menu, a check box, disabled without WebGL.
    menuItems(menuItem) {
        return [menuItem('2D view', {
            hint: this.forced ? 'This browser draws no 3D, so the 2D view is the only one' : 'A flat drawing from above, for slow or older computers',
            checked: this.wanted,
            check: true,
            disabled: !!this.forced,
            onSelect: () => this.toggle(),
        })];
    }

    // Draws the current moment when the 2D view is on, and returns whether it drew, so the caller
    // draws the 3D picture otherwise. The frames of the 3D picture on the Watch page are measured
    // for the offer of the 2D view.
    draw(page) {
        const now = performance.now();
        const dt = this.lastNow ? (now - this.lastNow) / 1000 : 0;
        this.lastNow = now;
        if (page !== 'watch' || !this.wanted) {
            if (page === 'watch') {
                this.measure(dt);
            }
            return false;
        }
        this.render();
        return true;
    }

    render() {
        const app = this.app;
        const ratio = Math.min(2, window.devicePixelRatio || 1);
        const w = Math.max(1, this.stage.clientWidth);
        const h = Math.max(1, this.stage.clientHeight);
        if (this.canvas.width !== Math.round(w * ratio) || this.canvas.height !== Math.round(h * ratio)) {
            this.canvas.width = Math.round(w * ratio);
            this.canvas.height = Math.round(h * ratio);
            this.pitch = null;
        }
        const ctx = this.ctx;
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        const room = Math.min(96, h * 0.16);
        const t = pitchTransform(w, h, { top: room, bottom: room, side: 16 });
        // The pitch is drawn once for each size and copied on every frame.
        if (!this.pitch) {
            this.pitch = document.createElement('canvas');
            this.pitch.width = this.canvas.width;
            this.pitch.height = this.canvas.height;
            const p = this.pitch.getContext('2d');
            p.setTransform(ratio, 0, 0, ratio, 0, 0);
            drawPitch(p, t);
        }
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.drawImage(this.pitch, 0, 0);
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        const tl = app.timeline;
        const source = app.source;
        if (!tl || !source || tl.store.size === 0) {
            return;
        }
        const s = tl.sample();
        if (!s.a) {
            return;
        }
        if (this.paintKey !== app.styles || !this.paint || this.paintHeader !== source.header) {
            this.paintKey = app.styles;
            this.paintHeader = source.header;
            this.paint = teamPaint(source.header, app.styles);
            this.numbers = source.header.players.map((p) => playerNumber(app.styles, p));
        }
        const scene = sceneFromFrames(source.header, s.a, s.b, s.w);
        drawScene(ctx, t, scene, this.paint, { numberOf: (p) => this.numbers[p.slot] });
    }

    // The frame rate of the 3D picture while a match plays, in windows of SLOW_WINDOW seconds. A
    // window below SLOW_FPS offers the 2D view, once for each visit and never after it was declined.
    measure(dt) {
        const app = this.app;
        const playing = app.timeline && app.timeline.playing && !document.hidden;
        if (!playing || dt <= 0 || dt > 1) {
            this.frames = 0;
            this.seconds = 0;
            return;
        }
        this.frames++;
        this.seconds += dt;
        if (this.seconds >= SLOW_WINDOW) {
            const fps = this.frames / this.seconds;
            this.frames = 0;
            this.seconds = 0;
            if (fps < SLOW_FPS) {
                this.suggest(fps);
            }
        }
    }

    suggest(fps) {
        if (this.suggested || this.wanted || load('view2dDeclined', false)) {
            return;
        }
        this.suggested = true;
        this.prompt.querySelector('.flat-suggest-text').textContent =
            `The 3D picture draws ${Math.max(1, Math.round(fps))} frames a second here. The 2D view plays the same match from above and needs much less.`;
        this.prompt.hidden = false;
    }

    buildPrompt() {
        const card = document.createElement('div');
        card.id = 'flat-suggest';
        card.className = 'flat-suggest';
        card.setAttribute('role', 'region');
        card.setAttribute('aria-label', 'Offer of the 2D view');
        card.setAttribute('aria-live', 'polite');
        card.dataset.prompt = '';
        card.hidden = true;
        const text = document.createElement('p');
        text.className = 'flat-suggest-text';
        const yes = document.createElement('button');
        yes.type = 'button';
        yes.className = 'btn small';
        yes.textContent = 'Use the 2D view';
        yes.addEventListener('click', () => {
            card.hidden = true;
            this.set(true);
        });
        const no = document.createElement('button');
        no.type = 'button';
        no.className = 'btn small';
        no.textContent = 'Keep 3D';
        no.addEventListener('click', () => {
            card.hidden = true;
            save('view2dDeclined', true);
        });
        const row = document.createElement('div');
        row.className = 'flat-suggest-actions';
        row.append(yes, no);
        card.append(text, row);
        document.getElementById('watch').appendChild(card);
        return card;
    }
}
