// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The shared things a team borrows on its own moments, section 10 of the contract. Camera and
// time suggestions, environment moments of the sky, the floodlights, the fog, lightning and a tifo
// in the team's own stand, and the overlay slots a worker draws in.
//
// Each is a suggestion that the renderer weighs, by the limits L1 to L6. A suggestion counts only
// for the team's own events. The camera follows one only in the broadcast camera or in the team's
// own celebration, never while the viewer uses the transport, and in open play only to tighten the
// framing for at most 1.5 seconds. A time suggestion freezes for at most 0.3 seconds or slows to no
// less than a quarter for at most 1.5 seconds, once per team in 30 seconds, on recordings and
// replays and on a live stream only with a second of buffer left. An environment moment lasts at
// most 6 seconds, one at a time with 20 seconds between a team's moments, and fades in and out over
// at least 0.3 seconds through the flash governor. Reduced motion and the viewer's setting refuse
// camera and time suggestions. Overlay slots never cover the score, the clock or the banners,
// and each slot counts the flashes of what it shows and hides for a while once it reaches the
// limit of the flash governor, since its drawing sits beside the picture the backstop reads.

import * as THREE from 'three';
import { SLOT_GRID, SlotGuard, downsample } from './flash.js';
import { clamp } from './values.js';

export const CAMERA_PLAY_SECONDS = 1.5;
export const CAMERA_SECONDS = 4;
export const TIME_COOLDOWN = 30;
export const MOMENT_SECONDS = 6;
export const MOMENT_COOLDOWN = 20;
export const MOMENT_FADE = 0.3;
export const SLOTS = ['badge', 'lowerThird', 'sting', 'card', 'lineup'];
// The fields of view of the shots, as a share of the framing they tighten.
const SHOTS = { closeup: 0.55, orbit: 0.75, low: 0.8, behindBall: 0.85, path: 0.9 };
// Where each slot sits, by the side of its team, in the stage's own frame.
const SLOT_STYLES = {
    badge: (side) => `top:58px;${side ? 'right' : 'left'}:16px;width:96px;height:96px`,
    lowerThird: (side) => `bottom:96px;${side ? 'right' : 'left'}:24px;width:360px;height:90px`,
    sting: () => 'top:50%;left:50%;width:320px;height:180px;transform:translate(-50%,-50%)',
    card: (side) => `top:30%;${side ? 'right' : 'left'}:24px;width:200px;height:200px`,
    lineup: (side) => `top:20%;${side ? 'right' : 'left'}:8%;width:30%;height:50%`,
};

export class Moments {
    constructor(presentation) {
        this.presentation = presentation;
        this.camera = null;
        this.time = null;
        this.environment = null;
        this.lastTime = [-Infinity, -Infinity];
        this.lastMoment = [-Infinity, -Infinity];
        this.refused = [];
        this.accepted = { camera: 0, time: 0, environment: 0, overlays: 0 };
        this.slots = new Map();
        // The viewer's settings, which turn the team's camera and time suggestions off.
        this.settings = { camera: true, time: true };
        try {
            this.settings.camera = localStorage.getItem('cuju.teamCamera') !== 'false';
            this.settings.time = localStorage.getItem('cuju.teamTime') !== 'false';
        } catch {
            // Storage can be unavailable, the settings then keep their defaults.
        }
    }

    refuse(kind, why) {
        this.refused.push(`${kind}: ${why}`);
        this.refused = this.refused.slice(-12);
        return false;
    }

    // The event a suggestion answers, which must be the team's own.
    own(pkg, id) {
        const p = this.presentation;
        const step = Number(String(id || '').split(':')[1]);
        const events = Number.isFinite(step) && p.catalog ? p.catalog.eventsAt(step) : [];
        const hit = events.find((e) => e.id === id) || p.recent.get(id) || null;
        return hit && hit.team === pkg.side ? hit : null;
    }

    // The viewer uses the transport while a key or a click of the timeline is less than two
    // seconds old.
    transportBusy() {
        const app = this.presentation.app;
        return performance.now() - (app.lastTransport || -Infinity) < 2000;
    }

    suggestCamera(pkg, c) {
        const p = this.presentation;
        const app = p.app;
        if (!this.settings.camera || app.reducedMotion) {
            return this.refuse('camera', 'the viewer turned team cameras off or reduces motion');
        }
        const event = this.own(pkg, c.event);
        if (!event) {
            return this.refuse('camera', 'not the team’s own event');
        }
        const director = app.director;
        const celebration = director && director.cel && director.cel.goal && director.cel.goal.team === pkg.side;
        const mode = app.cameras ? app.cameras.mode : null;
        if (!(mode === 'broadcast' && !(director && director.running)) && !(mode === 'scripted' && celebration)) {
            return this.refuse('camera', 'the camera is the viewer’s or the director’s');
        }
        if (this.transportBusy()) {
            return this.refuse('camera', 'the viewer uses the transport');
        }
        if (this.camera && this.camera.priority > (c.priority ?? 1)) {
            return this.refuse('camera', 'a stronger suggestion runs');
        }
        const seconds = Math.min(c.duration ?? 2, celebration ? CAMERA_SECONDS : CAMERA_PLAY_SECONDS);
        const now = p.clocks.cosmetic;
        this.camera = { pkg, shot: c.shot, subject: c.subject || (event.player != null ? `p${event.player}` : 'ball'), from: now, to: now + seconds, priority: c.priority ?? 1, fov: SHOTS[c.shot] || 0.8 };
        this.accepted.camera += 1;
        return true;
    }

    // The point a camera suggestion frames, in three's frame, or null.
    subjectPoint(subject, out = new THREE.Vector3()) {
        const p = this.presentation;
        if (subject === 'ball' || !subject) {
            return p.app.ball ? out.copy(p.app.ball.mesh.position) : null;
        }
        if (/^p\d+$/.test(subject) && p.players && p.app.pose) {
            return p.players.position(p.app.pose, Number(subject.slice(1)), out).setY(1.1);
        }
        return null;
    }

    // What the camera takes of a running suggestion this drawing, a target to lean toward and a
    // share of the field of view, or null. The cameras call it as they finish a shot.
    cameraAdjust() {
        const s = this.camera;
        if (!s) {
            return null;
        }
        const now = this.presentation.clocks.cosmetic;
        if (now > s.to || this.transportBusy() || this.presentation.app.reducedMotion) {
            this.camera = null;
            return null;
        }
        const k = Math.min(1, (now - s.from) / 0.4, (s.to - now) / 0.4);
        const target = this.subjectPoint(s.subject);
        return target ? { target, amount: clamp(k, 0, 1) * 0.6, fov: 1 + (s.fov - 1) * clamp(k, 0, 1) } : null;
    }

    suggestTime(pkg, c) {
        const p = this.presentation;
        const app = p.app;
        const tl = app.timeline;
        if (!this.settings.time || app.reducedMotion) {
            return this.refuse('time', 'the viewer turned team time off or reduces motion');
        }
        if (!this.own(pkg, c.event)) {
            return this.refuse('time', 'not the team’s own event');
        }
        const now = p.clocks.cosmetic;
        if (now - this.lastTime[pkg.side] < TIME_COOLDOWN || this.time) {
            return this.refuse('time', 'one time suggestion per team in 30 seconds');
        }
        if (!tl || !tl.playing || tl.direction < 0 || tl.speed !== 1 || this.transportBusy()) {
            return this.refuse('time', 'the viewer’s transport is not at plain play');
        }
        const freeze = clamp(c.freeze || 0, 0, 0.3);
        const slow = c.slow ? { speed: clamp(c.slow.speed, 0.25, 1), seconds: clamp(c.slow.seconds, 0, 1.5) } : null;
        const cost = freeze + (slow ? slow.seconds * (1 - slow.speed) : 0);
        if (tl.live && tl.behindLive - cost < 1) {
            return this.refuse('time', 'a live stream needs a second of buffer after it');
        }
        const event = this.own(pkg, c.event);
        const at = c.at === 'contact' && event.data && event.data.contactT != null ? event.data.contactT : event.t + (typeof c.at === 'number' ? c.at : 0);
        this.time = { pkg, at, freeze, slow, started: null };
        this.lastTime[pkg.side] = now;
        this.accepted.time += 1;
        return true;
    }

    // The share of real time the timeline plays this drawing, 1 without a time suggestion. The
    // page multiplies its step of play by it.
    timeScale(dt) {
        const t = this.time;
        if (!t) {
            return 1;
        }
        const p = this.presentation;
        const tl = p.app.timeline;
        if (!tl || !tl.playing || tl.direction < 0 || this.transportBusy() || p.app.reducedMotion) {
            this.time = null;
            return 1;
        }
        if (t.started == null) {
            if (p.clocks.sim + 1e-6 < t.at) {
                return 1;
            }
            t.started = p.clocks.cosmetic;
        }
        const age = p.clocks.cosmetic - t.started;
        if (age < t.freeze) {
            return 0;
        }
        if (t.slow && age < t.freeze + t.slow.seconds) {
            return t.slow.speed;
        }
        this.time = null;
        return 1;
    }

    // An environment moment of a reflex or a worker, the sky, the floodlights, the fog, lightning
    // or a tifo, each needing its feature.
    moment(pkg, c) {
        const p = this.presentation;
        const event = this.own(pkg, c.event);
        if (!event) {
            return this.refuse('environment', 'not the team’s own event');
        }
        const now = p.clocks.cosmetic;
        if (this.environment || now - this.lastMoment[pkg.side] < MOMENT_COOLDOWN) {
            return this.refuse('environment', 'one moment at a time, 20 seconds apart for a team');
        }
        const has = (f) => p.hasFeature(pkg, f);
        const m = { pkg, from: now, to: now + clamp(c.duration ?? 4, MOMENT_FADE * 2, MOMENT_SECONDS), base: null, parts: {} };
        if (has('environment.sky')) {
            for (const key of ['sky', 'floodlights', 'fog']) {
                if (c[key]) {
                    m.parts[key] = { color: c[key].color || c[key].tint || [255, 255, 255], amount: clamp(c[key].amount ?? c[key].level ?? 1, 0, 1.5) };
                }
            }
        }
        if (has('environment.lightning') && c.lightning) {
            m.parts.lightning = { target: c.lightning.target || 'goal', event, done: false };
        }
        if (has('fans.tifo') && c.tifo) {
            m.parts.tifo = { file: c.tifo };
        }
        if (!Object.keys(m.parts).length) {
            return this.refuse('environment', 'the package lists none of the features of its parts');
        }
        this.environment = m;
        this.lastMoment[pkg.side] = now;
        this.accepted.environment += 1;
        this.capture(m);
        return true;
    }

    // The renderer's own values a moment changes, kept to give back when it ends.
    capture(m) {
        const app = this.presentation.app;
        const sky = app.environment && app.environment.sky ? app.environment.sky.material.uniforms : null;
        const flood = app.stadium && app.stadium.floodlights ? app.stadium.floodlights : null;
        m.base = {
            tint: sky && sky.uTint ? sky.uTint.value.clone() : null,
            flood: flood ? flood.lights.map((l) => ({ color: l.color.clone(), intensity: l.intensity })) : null,
            fog: app.view && app.view.scene.fog ? app.view.scene.fog.color.clone() : null,
            hemi: app.view && app.view.hemi ? app.view.hemi.intensity : null,
        };
    }

    // Moves the moment on by one drawing, faded and governed, and gives the renderer's values
    // back as it ends.
    update() {
        const m = this.environment;
        const p = this.presentation;
        if (!m) {
            return;
        }
        const app = p.app;
        const now = p.clocks.cosmetic;
        const k = clamp(Math.min((now - m.from) / MOMENT_FADE, (m.to - now) / MOMENT_FADE), 0, 1);
        const env = p.flash.envelope(`${m.pkg.side}:environment`);
        const level = env.apply(now, k) * p.flashFactor();
        const color = (c) => new THREE.Color().setRGB(c[0] / 255, c[1] / 255, c[2] / 255, THREE.SRGBColorSpace);
        const sky = app.environment && app.environment.sky ? app.environment.sky.material.uniforms : null;
        if (m.parts.sky && sky && sky.uTint && m.base.tint) {
            sky.uTint.value.copy(m.base.tint).lerp(color(m.parts.sky.color), Math.min(1, m.parts.sky.amount) * level);
        }
        const flood = app.stadium && app.stadium.floodlights;
        if (m.parts.floodlights && flood && m.base.flood) {
            flood.lights.forEach((l, i) => {
                l.color.copy(m.base.flood[i].color).lerp(color(m.parts.floodlights.color), level);
                l.intensity = m.base.flood[i].intensity * (1 + (m.parts.floodlights.amount - 1) * level);
            });
        }
        if (m.parts.fog && app.view.scene.fog && m.base.fog) {
            app.view.scene.fog.color.copy(m.base.fog).lerp(color(m.parts.fog.color), Math.min(1, m.parts.fog.amount) * level);
        }
        if (m.parts.lightning) {
            this.lightning(m, now);
        }
        if (m.parts.tifo) {
            this.tifo(m, level);
        }
        if (now >= m.to) {
            this.restore(m);
            this.environment = null;
        }
    }

    // One bolt from the sky to the team's target, a single rise of light that the governor counts.
    lightning(m, now) {
        const p = this.presentation;
        const app = p.app;
        const part = m.parts.lightning;
        if (!part.bolt) {
            const side = m.pkg.side;
            const target = part.target === 'ball' && app.ball ? app.ball.mesh.position.clone()
                : Array.isArray(part.target) ? new THREE.Vector3(part.target[0], part.target[2], -part.target[1])
                    // The goal the team attacks, its crossbar.
                    : new THREE.Vector3(side === 0 ? 52.5 : -52.5, 2.44, 0);
            const points = [];
            const rand = mulberry(m.from * 1000);
            const top = target.clone().add(new THREE.Vector3((rand() - 0.5) * 20, 70, (rand() - 0.5) * 20));
            for (let i = 0; i <= 16; i++) {
                const u = i / 16;
                const q = top.clone().lerp(target, u);
                if (i > 0 && i < 16) {
                    q.x += (rand() - 0.5) * 4 * (1 - u * 0.5);
                    q.z += (rand() - 0.5) * 4 * (1 - u * 0.5);
                }
                points.push(q);
            }
            const geometry = new THREE.BufferGeometry().setFromPoints(points);
            part.bolt = new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: 0xe8efff, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, fog: false }));
            part.bolt.frustumCulled = false;
            app.view.scene.add(part.bolt);
            part.at = now;
        }
        const age = now - part.at;
        // One rise and one fall of light, never a strobe.
        const env = p.flash.envelope(`${m.pkg.side}:lightning`);
        const flash = env.apply(now, age < 0.08 ? 1 : Math.max(0, 1 - (age - 0.08) / 0.4)) * p.flashFactor();
        part.bolt.material.opacity = flash;
        if (app.view.hemi && m.base.hemi != null) {
            app.view.hemi.intensity = m.base.hemi * (1 + 0.8 * flash);
        }
        if (age > 0.6 && !part.done) {
            part.done = true;
            part.bolt.removeFromParent();
            part.bolt.geometry.dispose();
            part.bolt.material.dispose();
            if (app.view.hemi && m.base.hemi != null) {
                app.view.hemi.intensity = m.base.hemi;
            }
        }
    }

    // A tifo, an image of the package, raised in the stand behind the goal the team defends.
    tifo(m, level) {
        const p = this.presentation;
        const part = m.parts.tifo;
        if (!part.mesh) {
            const texture = new THREE.Texture();
            const material = new THREE.MeshBasicMaterial({ map: texture, transparent: true, opacity: 0, side: THREE.DoubleSide, fog: true });
            part.mesh = new THREE.Mesh(new THREE.PlaneGeometry(34, 11), material);
            // Team 0 defends negative x, its fans stand behind that goal.
            const x = m.pkg.side === 0 ? -62 : 62;
            part.mesh.position.set(x, 9, 0);
            part.mesh.rotation.y = m.pkg.side === 0 ? Math.PI / 2 : -Math.PI / 2;
            p.app.view.scene.add(part.mesh);
            p.fetchFile(m.pkg, part.file).then((data) => createImageBitmap(new Blob([data]))).then((bitmap) => {
                texture.image = bitmap;
                texture.colorSpace = THREE.SRGBColorSpace;
                texture.needsUpdate = true;
                part.ready = true;
            }).catch((err) => m.pkg.errors.push(`tifo ${part.file} not shown, ${err.message || err}`));
        }
        part.mesh.material.opacity = part.ready ? 0.95 * level : 0;
        part.mesh.position.y = 4 + 5 * level;
    }

    restore(m) {
        const app = this.presentation.app;
        const sky = app.environment && app.environment.sky ? app.environment.sky.material.uniforms : null;
        if (m.parts.sky && sky && m.base.tint) {
            sky.uTint.value.copy(m.base.tint);
        }
        const flood = app.stadium && app.stadium.floodlights;
        if (m.parts.floodlights && flood && m.base.flood) {
            flood.lights.forEach((l, i) => {
                l.color.copy(m.base.flood[i].color);
                l.intensity = m.base.flood[i].intensity;
            });
        }
        if (m.parts.fog && app.view.scene.fog && m.base.fog) {
            app.view.scene.fog.color.copy(m.base.fog);
        }
        if (m.parts.lightning && m.parts.lightning.bolt && !m.parts.lightning.done) {
            m.parts.lightning.bolt.removeFromParent();
        }
        if (m.parts.tifo && m.parts.tifo.mesh) {
            m.parts.tifo.mesh.removeFromParent();
            m.parts.tifo.mesh.geometry.dispose();
            m.parts.tifo.mesh.material.map.dispose();
            m.parts.tifo.mesh.material.dispose();
        }
    }

    // A new epoch or another match ends what runs.
    end() {
        if (this.environment) {
            this.restore(this.environment);
            this.environment = null;
        }
        this.camera = null;
        this.time = null;
    }

    // The overlay slots of a package, a canvas each, which the worker's bitmaps fill.
    slot(pkg, name) {
        const key = `${pkg.side}:${name}`;
        let s = this.slots.get(key);
        if (!s) {
            const stage = document.getElementById('stage');
            if (!stage) {
                return null;
            }
            const canvas = document.createElement('canvas');
            canvas.className = 'team-overlay';
            canvas.dataset.slot = name;
            canvas.dataset.team = String(pkg.side);
            canvas.setAttribute('aria-hidden', 'true');
            canvas.style.cssText = `position:absolute;pointer-events:none;z-index:2;${SLOT_STYLES[name](pkg.side)}`;
            canvas.hidden = true;
            stage.appendChild(canvas);
            s = { canvas, context: canvas.getContext('bitmaprenderer'), shown: false, until: Infinity, pkg, name, guard: new SlotGuard(), trips: 0 };
            this.slots.set(key, s);
        }
        return s;
    }

    // Whether a slot may show now, by the windows of section 10.2.
    window(pkg, name) {
        const p = this.presentation;
        const director = p.app.director;
        if (name === 'badge') {
            return true;
        }
        if (name === 'lineup') {
            return !!(director && director.lineup);
        }
        if (name === 'lowerThird' || name === 'sting') {
            return !!(director && director.cel && director.cel.goal && director.cel.goal.team === pkg.side)
                || (p.recentOwn(pkg, ['goal', 'winner.reveal'], name === 'sting' ? 0.72 : 5));
        }
        if (name === 'card') {
            return p.recentOwn(pkg, ['mvp.reveal', 'winner.reveal'], 8);
        }
        return false;
    }

    // An overlay command of a worker, with the bitmap the sandbox drew when it draws.
    overlay(pkg, c, bitmap = null) {
        if (!(pkg.manifest.overlays && pkg.manifest.overlays[c.slot])) {
            return this.refuse('overlay', `the package declares no slot ${c.slot}`);
        }
        const s = this.slot(pkg, c.slot);
        if (!s) {
            return false;
        }
        if (bitmap && s.context) {
            s.guard.draw(this.measure(bitmap));
            s.canvas.width = bitmap.width;
            s.canvas.height = bitmap.height;
            s.context.transferFromImageBitmap(bitmap);
        }
        if (c.op === 'hide') {
            s.shown = false;
        } else {
            s.shown = true;
        }
        this.accepted.overlays += 1;
        return true;
    }

    // A drawing of a worker as the guard of its slot reads it, over black, or null when the page
    // cannot read it.
    measure(bitmap) {
        try {
            const canvas = this.sampler || (this.sampler = document.createElement('canvas'));
            canvas.width = bitmap.width;
            canvas.height = bitmap.height;
            const g = this.samplerContext || (this.samplerContext = canvas.getContext('2d', { willReadFrequently: true }));
            g.fillStyle = '#000';
            g.fillRect(0, 0, bitmap.width, bitmap.height);
            g.drawImage(bitmap, 0, 0);
            return downsample(g.getImageData(0, 0, bitmap.width, bitmap.height).data, bitmap.width, bitmap.height, SLOT_GRID);
        } catch {
            return null;
        }
    }

    // Shows each slot only inside its window, hidden on other pages and in the 2D view, and hides
    // for a while a slot whose drawings flash past the limit.
    updateSlots() {
        const p = this.presentation;
        const onStage = p.app.page === 'watch' || p.app.page === 'play';
        const now = p.clocks.cosmetic;
        for (const s of this.slots.values()) {
            const wanted = onStage && s.shown && this.window(s.pkg, s.name);
            s.canvas.hidden = !s.guard.show(now, wanted);
            if (s.guard.trips !== s.trips) {
                s.trips = s.guard.trips;
                this.refuse('overlay', `the slot ${s.name} flashed past the limit and hides for ${s.guard.hold} s`);
            }
        }
    }

    disposeSlots() {
        for (const s of this.slots.values()) {
            s.canvas.remove();
        }
        this.slots.clear();
    }

    snapshot() {
        return {
            camera: this.camera ? { shot: this.camera.shot, subject: this.camera.subject } : null,
            time: this.time ? { freeze: this.time.freeze, slow: this.time.slow, started: this.time.started != null } : null,
            environment: this.environment ? Object.keys(this.environment.parts) : null,
            accepted: { ...this.accepted }, refused: this.refused.slice(), settings: { ...this.settings },
            slots: [...this.slots.values()].map((s) => ({ team: s.pkg.side, slot: s.name, shown: !s.canvas.hidden, trips: s.guard.trips })),
        };
    }
}

function mulberry(seed) {
    let a = Math.floor(seed) >>> 0;
    return () => {
        a = (a + 0x6D2B79F5) >>> 0;
        let t = a;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}
