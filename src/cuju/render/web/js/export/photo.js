// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Photo mode of the Watch page. It holds the match still, hands the view to a free camera with
// depth of field, film looks, a vignette and grain, draws frame guides over the picture and saves
// the picture as a PNG at the window's size or a chosen one. The page's own bars give way to a
// panel of its own, which a key hides, and a controller flies the camera too. Scripts reach it as
// window.cuju.photo, with open, close, set, camera, capture, save and state.

import * as THREE from 'three';
import { FullScreenQuad } from 'three/addons/postprocessing/Pass.js';
import { CAMERA_BOX, confine } from '../world/cameras.js';
import { OWN_KEYS } from '../core/comfort.js';
import { el, menuItem } from '../core/menu.js';
import {
    DEFAULTS, FOCUS_MAX, FOCUS_MIN, GUIDES, LOOKS, MAX_SIDE, MIN_SIDE, RANGES, RESOLUTIONS, captureFov, focusToSlider,
    guideGeometry, lookById, nextGuide, nextLook, normalizeSettings, photoFileName, readPad,
    resolveResolution, sliderToFocus,
} from './photo-core.js';
import { formatNumber, t } from '../core/i18n.js';
import { presetLabel } from './size-fields.js';

// Samples of the depth of field, on a spiral of the golden angle.
const SAMPLES = 48;
// The largest blur, as a share of the picture's height, so a photo of any size looks the same.
const MAX_BLUR = 0.02;
// Changes of moving grain per second, as on film.
const GRAIN_RATE = 24;
// Turning, rolling and zooming speeds of held keys, in radians and degrees per second.
const TURN = 1.2;
const ROLL = 30;
const ZOOM = 20;

// The name of a look in the language of the page.
const lookLabel = (id) => t(`photo.look.${lookById(id).id}`);
// A number as String writes it, with the decimal separator of the language.
const decimal = (v) => {
    const text = String(v);
    return /^-?\d+\.\d+$/.test(text) ? text.replace('.', formatNumber(0.5).charAt(1)) : text;
};

const VERTEX = /* glsl */`
varying vec2 vUv;
void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

// The picture as drawn, already toned and in display values, blurred by its depth around the
// focus distance, then graded and vignetted. The grain follows in a pass of its own, so grain
// that moves redraws only that pass.
const FRAGMENT = /* glsl */`
#include <packing>
#define SAMPLES ${SAMPLES}
uniform sampler2D tColor;
uniform sampler2D tDepth;
uniform vec2 resolution;
uniform float cameraNear;
uniform float cameraFar;
uniform float focus;
uniform float autoFocus;
uniform float aperture;
uniform float maxBlur;
uniform float exposure;
uniform float temperature;
uniform float tint;
uniform float contrast;
uniform float saturation;
uniform float fade;
uniform float mono;
uniform vec3 shadows;
uniform vec3 highlights;
uniform vec3 gain;
uniform float vignette;
varying vec2 vUv;

const vec3 LUMA = vec3(0.2126, 0.7152, 0.0722);

float distanceAt(vec2 uv) {
    return -perspectiveDepthToViewZ(texture2D(tDepth, uv).x, cameraNear, cameraFar);
}

// The blur of a point at distance z, from 0 to 1 of the largest.
float blurAt(float z, float f) {
    return clamp(abs(1.0 - f / max(z, 0.01)) * aperture * 2.0, 0.0, 1.0);
}

float focusDistance() {
    if (autoFocus < 0.5) {
        return focus;
    }
    float d = 0.4 * distanceAt(vec2(0.5));
    d += 0.15 * distanceAt(vec2(0.49, 0.5)) + 0.15 * distanceAt(vec2(0.51, 0.5));
    d += 0.15 * distanceAt(vec2(0.5, 0.49)) + 0.15 * distanceAt(vec2(0.5, 0.51));
    return clamp(d, ${FOCUS_MIN.toFixed(1)}, ${FOCUS_MAX.toFixed(1)});
}

vec3 depthOfField(vec2 uv) {
    vec3 color = texture2D(tColor, uv).rgb;
    if (aperture <= 0.0) {
        return color;
    }
    float f = focusDistance();
    float zc = distanceAt(uv);
    float cc = blurAt(zc, f) * maxBlur;
    float spacing = 0.5 * maxBlur / sqrt(float(SAMPLES));
    vec3 sum = color;
    float total = 1.0;
    for (int i = 0; i < SAMPLES; i++) {
        float r = sqrt((float(i) + 0.5) / float(SAMPLES)) * maxBlur;
        float a = float(i) * 2.39996323;
        vec2 suv = uv + vec2(cos(a), sin(a)) * r / resolution;
        vec3 sc = texture2D(tColor, suv).rgb;
        float zs = distanceAt(suv);
        float cs = blurAt(zs, f) * maxBlur;
        // A sharper point in front keeps its edge against the blurred background behind it.
        if (zs > zc) {
            cs = min(cs, cc * 2.0);
        }
        float m = smoothstep(r - spacing, r + spacing, cs);
        sum += mix(sum / total, sc, m);
        total += 1.0;
    }
    return sum / total;
}

vec3 grade(vec3 c) {
    c *= exp2(exposure);
    c *= vec3(1.0 + 0.12 * temperature - 0.03 * tint, 1.0 + 0.05 * tint, 1.0 - 0.12 * temperature - 0.03 * tint);
    float l = dot(c, LUMA);
    c = mix(vec3(l), c, saturation);
    c = max((c - 0.5) * contrast + 0.5, 0.0);
    l = clamp(dot(c, LUMA), 0.0, 1.0);
    c += shadows * (1.0 - l) * (1.0 - l) + highlights * l * l;
    c *= gain;
    c = mix(c, vec3(clamp(dot(c, LUMA), 0.0, 1.0)), mono);
    return fade + c * (1.0 - fade);
}

void main() {
    vec3 c = grade(depthOfField(vUv));
    float aspect = resolution.x / resolution.y;
    vec2 p = (vUv - 0.5) * vec2(aspect, 1.0);
    float d = length(p) / length(vec2(aspect, 1.0) * 0.5);
    c *= 1.0 - vignette * 0.85 * smoothstep(0.25, 1.05, d);
    gl_FragColor = vec4(clamp(c, 0.0, 1.0), 1.0);
}`;

// Film grain over the graded picture, stronger in the shadows.
const GRAIN = /* glsl */`
uniform sampler2D tGraded;
uniform float grain;
uniform float seed;
varying vec2 vUv;

float hash(vec2 p) {
    vec3 q = fract(vec3(p.xyx) * 0.1031);
    q += dot(q, q.yzx + 33.33);
    return fract((q.x + q.y) * q.z);
}

void main() {
    vec3 c = texture2D(tGraded, vUv).rgb;
    float l = clamp(dot(c, vec3(0.2126, 0.7152, 0.0722)), 0.0, 1.0);
    float n = hash(gl_FragCoord.xy + seed * 61.7) + hash(gl_FragCoord.xy * 1.37 + seed * 17.3) - 1.0;
    c += n * grain * 0.14 * (0.35 + 0.65 * (1.0 - l));
    gl_FragColor = vec4(clamp(c, 0.0, 1.0), 1.0);
}`;

const STYLE = `
html.cuju-photo #topbar,
html.cuju-photo #watch > :not(#stage):not(.photo-ui),
html.cuju-photo .player-labels { display: none !important; }
.photo-guides { position: absolute; inset: 0; z-index: 4; width: 100%; height: 100%; pointer-events: none; }
.photo-guides .shade { fill: rgba(0, 0, 0, 0.45); fill-rule: evenodd; }
.photo-guides line, .photo-guides rect { fill: none; vector-effect: non-scaling-stroke; }
.photo-guides .halo { stroke: rgba(0, 0, 0, 0.5); stroke-width: 3; }
.photo-guides .ink { stroke: rgba(255, 255, 255, 0.85); stroke-width: 1; }
#photo-panel { position: absolute; top: 12px; right: 12px; z-index: 8; width: 300px;
    max-height: calc(100% - 24px); overflow: auto; padding: 12px 14px; border: 1px solid var(--border);
    background: var(--overlay); color: var(--text); font-size: 13px; }
#photo-panel[hidden] { display: none; }
#photo-panel:focus { outline: none; }
#photo-panel h2 { margin: 0 0 8px; font-size: 16px; font-weight: normal; }
#photo-panel .photo-row { display: grid; grid-template-columns: 1fr auto; align-items: center;
    gap: 2px 8px; margin: 6px 0; }
#photo-panel .photo-row > :is(input[type="range"], select) { grid-column: 1 / -1; width: 100%; }
#photo-panel .photo-size { grid-template-columns: 1fr auto 1fr; }
#photo-panel .photo-size[hidden] { display: none; }
#photo-panel .photo-size input { width: 100%; min-width: 0; }
#photo-panel output { color: var(--muted); font-variant-numeric: tabular-nums; }
#photo-panel .photo-check { display: flex; align-items: center; gap: 6px; margin: 6px 0; }
#photo-panel .photo-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
#photo-panel .photo-keys { margin: 10px 0 0; color: var(--muted); line-height: 1.5; }
#photo-panel .photo-status { min-height: 1.4em; margin: 6px 0 0; color: var(--muted); }
@media (max-width: 600px) {
    #photo-panel { top: auto; bottom: 8px; left: 8px; right: 8px; width: auto; max-height: 45%; }
}`;

function injectStyle() {
    if (document.getElementById('cuju-photo-style')) {
        return;
    }
    const style = document.createElement('style');
    style.id = 'cuju-photo-style';
    style.textContent = STYLE;
    document.head.appendChild(style);
}

const SVG = 'http://www.w3.org/2000/svg';

function svg(tag, attrs = {}) {
    const node = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) {
        node.setAttribute(k, String(v));
    }
    return node;
}

function vector(value, name) {
    if (Array.isArray(value) && value.length === 3 && value.every(Number.isFinite)) {
        return new THREE.Vector3(value[0], value[1], value[2]);
    }
    if (value && [value.x, value.y, value.z].every(Number.isFinite)) {
        return new THREE.Vector3(value.x, value.y, value.z);
    }
    throw new TypeError(`The camera ${name} is [x, y, z] or { x, y, z } in meters, y up.`);
}

const round = (v, digits = 3) => Math.round(v * 10 ** digits) / 10 ** digits;

// Keys that a focused control of the panel uses itself.
const CONTROL_KEYS = new Set(['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown', ' ', 'Enter', 'Tab']);
// Keys the Watch page keeps in photo mode, fullscreen and mute.
const PAGE_KEYS = new Set(['f', 'm']);

export class PhotoMode {
    constructor(app) {
        this.app = app;
        this.isOpen = false;
        this.settings = { ...DEFAULTS };
        this.hidden = false;
        this.held = new Set();
        this.padButtons = [];
        this.saving = false;
        this.saved = null;
        this.lastCapture = null;
        this.seed = 0;
        this.looks = LOOKS.map((l) => l.id);
        this.guides = GUIDES.map((g) => g.id);
        this.resolutions = RESOLUTIONS.map((r) => r.id);
        injectStyle();
        this.buildMenuItem();
        window.addEventListener('keydown', (e) => this.onKey(e), true);
        window.addEventListener('keyup', (e) => this.onKeyUp(e), true);
        window.addEventListener('blur', () => {
            this.held.clear();
            this.shift = false;
        });
        // A click on the picture skips a show on the Watch page, which photo mode holds still.
        const stage = document.getElementById('stage');
        if (stage) {
            stage.addEventListener('click', (e) => {
                if (this.isOpen) {
                    e.stopImmediatePropagation();
                }
            }, true);
        }
    }

    // The entry of the View menu, which a fill of the menu leaves alone.
    buildMenuItem() {
        const host = document.getElementById('view-photo');
        if (!host) {
            return;
        }
        host.replaceChildren(menuItem(t('photo.title'), {
            kbd: 'O', hint: t('photo.menu.hint'),
            onSelect: () => {
                this.open();
                setTimeout(() => this.panel && !this.panel.hidden && this.panel.focus(), 0);
            },
        }));
    }

    // Opening and leaving.

    open() {
        if (this.isOpen) {
            return this.state();
        }
        const app = this.app;
        if (app.page !== 'watch') {
            app.showPage('watch');
        }
        this.snapshot();
        const tl = app.timeline;
        if (tl) {
            tl.pause();
        }
        app.userPaused = true;
        if (app.sound && typeof app.sound.setActive === 'function') {
            app.sound.setActive(false);
        }
        const rig = app.cameras;
        const cam = app.view.camera;
        this.settings = normalizeSettings(this.settings, {
            fov: THREE.MathUtils.clamp(cam.fov, ...RANGES.fov), roll: 0,
        });
        this.picking = app.playerTools ? app.playerTools.picking : false;
        if (app.playerTools) {
            app.playerTools.picking = false;
        }
        rig.setMode('free');
        // The photo starts from the view as it stands, without a glide.
        rig.blend = null;
        rig.flight = null;
        rig.freeFov = this.settings.fov;
        rig.rawFov = this.settings.fov;
        rig.releaseAll();
        this.held.clear();
        this.padButtons = this.readPads().buttons;
        this.isOpen = true;
        this.buildUi();
        document.documentElement.classList.add('cuju-photo');
        this.setHidden(false);
        this.syncPanel();
        this.drawGuides();
        this.place();
        return this.state();
    }

    close() {
        if (!this.isOpen) {
            return this.state();
        }
        this.isOpen = false;
        if (document.pointerLockElement) {
            document.exitPointerLock();
        }
        document.documentElement.classList.remove('cuju-photo');
        this.held.clear();
        this.app.cameras.releaseAll();
        if (this.app.playerTools) {
            this.app.playerTools.picking = this.picking;
        }
        this.restore();
        // Focus inside the panel goes back to the page with it.
        if (this.panel && this.panel.contains(document.activeElement)) {
            document.activeElement.blur();
        }
        this.destroyUi();
        this.freePasses();
        return this.state();
    }

    toggle() {
        return this.isOpen ? this.close() : this.open();
    }

    // The camera, the springs of the framed shots, the free camera and playback as they were.
    snapshot() {
        const app = this.app;
        const rig = app.cameras;
        const cam = app.view.camera;
        const spring = (s) => ({ x: Array.from(s.x), v: Array.from(s.v) });
        const tl = app.timeline;
        this.saved = {
            mode: rig.mode,
            position: cam.position.clone(),
            quaternion: cam.quaternion.clone(),
            fov: cam.fov,
            near: cam.near,
            target: rig.target.clone(),
            rawPos: rig.rawPos.clone(),
            rawQuat: rig.rawQuat.clone(),
            rawFov: rig.rawFov,
            shotPos: spring(rig.shotPos),
            shotTarget: spring(rig.shotTarget),
            shotFov: spring(rig.shotFov),
            followSpring: spring(rig.followSpring),
            offset: rig.offset.clone(),
            freePos: rig.freePos.clone(),
            yaw: rig.yaw,
            pitch: rig.pitch,
            viewYaw: rig.viewYaw,
            viewPitch: rig.viewPitch,
            freeFov: rig.freeFov,
            speed: rig.speed,
            fppPos: rig.fppPos.clone(),
            fppQuat: rig.fppQuat.clone(),
            rigFov: rig.fov,
            timeline: tl,
            playing: tl ? tl.playing : false,
            following: tl ? tl.following : false,
            direction: tl ? tl.direction : 1,
            speedOfPlay: tl ? tl.speed : 1,
            userPaused: app.userPaused,
        };
    }

    restore() {
        const s = this.saved;
        if (!s) {
            return;
        }
        this.saved = null;
        const app = this.app;
        const rig = app.cameras;
        const cam = app.view.camera;
        const set = (spring, saved) => {
            spring.x.set(saved.x);
            spring.v.set(saved.v);
        };
        // The camera goes back first, so a mode that starts from the camera starts from its view.
        cam.position.copy(s.position);
        cam.quaternion.copy(s.quaternion);
        cam.fov = s.fov;
        cam.near = s.near;
        cam.updateProjectionMatrix();
        rig.target.copy(s.target);
        rig.freePos.copy(s.freePos);
        rig.setMode(s.mode);
        rig.blend = null;
        rig.shotCut = false;
        rig.flight = null;
        set(rig.shotPos, s.shotPos);
        set(rig.shotTarget, s.shotTarget);
        set(rig.shotFov, s.shotFov);
        set(rig.followSpring, s.followSpring);
        rig.offset.copy(s.offset);
        rig.freePos.copy(s.freePos);
        rig.freeVel.set(0, 0, 0);
        rig.yaw = s.yaw;
        rig.pitch = s.pitch;
        rig.viewYaw = s.viewYaw;
        rig.viewPitch = s.viewPitch;
        rig.freeFov = s.freeFov;
        rig.speed = s.speed;
        rig.fppPos.copy(s.fppPos);
        rig.fppQuat.copy(s.fppQuat);
        rig.fov = s.rigFov;
        rig.rawPos.copy(s.rawPos);
        rig.rawQuat.copy(s.rawQuat);
        rig.rawFov = s.rawFov;
        rig.camVel.set(0, 0, 0);
        rig.lastCamPos.copy(s.position);
        rig.idle = 0;
        const tl = app.timeline;
        if (tl && tl === s.timeline) {
            tl.direction = s.direction;
            tl.speed = s.speedOfPlay;
            if (s.following) {
                tl.following = true;
                tl.playing = true;
            } else if (s.playing) {
                tl.playing = true;
            }
        }
        app.userPaused = s.userPaused;
    }

    // The frame loop of photo mode, in place of the page's own while it is open. Returns false
    // when the page left the Watch page and photo mode closed.
    frame(dt) {
        const app = this.app;
        if (app.page !== 'watch') {
            this.close();
            return false;
        }
        const rig = app.cameras;
        if (rig.mode !== 'free') {
            rig.setMode('free');
            rig.blend = null;
        }
        // Grain moves at the pace of film, and holds still under reduced motion.
        this.grainClock = (this.grainClock || 0) + dt;
        if (!app.reducedMotion && this.settings.grain > 0 && this.grainClock >= 1 / GRAIN_RATE) {
            this.grainClock = 0;
            this.seed = (this.seed + 1) % 1000;
        }
        this.pollPad(dt);
        this.steer(dt);
        rig.idleSeconds = 0;
        rig.freeFov = this.settings.fov;
        rig.update(dt, app.ball.mesh.position, app.players, app.pose || { players: 1 }, app.view.aspect, null);
        this.roll();
        this.draw();
        return true;
    }

    // Held arrows turn, Z and X roll, minus and plus zoom.
    steer(dt) {
        if (!this.held.size) {
            return;
        }
        const rig = this.app.cameras;
        const fast = this.shift ? 3 : 1;
        const turn = TURN * fast * dt;
        const yaw = (this.held.has('ArrowLeft') ? 1 : 0) - (this.held.has('ArrowRight') ? 1 : 0);
        const pitch = (this.held.has('ArrowUp') ? 1 : 0) - (this.held.has('ArrowDown') ? 1 : 0);
        if (yaw || pitch) {
            rig.touch();
            rig.yaw += yaw * turn;
            rig.pitch = THREE.MathUtils.clamp(rig.pitch + pitch * turn, -CAMERA_BOX.pitchLimit, CAMERA_BOX.pitchLimit);
        }
        const roll = (this.held.has('x') ? 1 : 0) - (this.held.has('z') ? 1 : 0);
        const zoom = (this.held.has('-') ? 1 : 0) - (this.held.has('+') ? 1 : 0);
        if (roll || zoom) {
            this.update({
                roll: this.settings.roll + roll * ROLL * fast * dt,
                fov: this.settings.fov + zoom * ZOOM * fast * dt,
            });
        }
    }

    roll() {
        if (this.settings.roll) {
            this.app.view.camera.rotateZ(THREE.MathUtils.degToRad(this.settings.roll));
        }
    }

    // Sets the camera from the free camera at once, as it settles, for a capture right after a
    // change from a script.
    place() {
        const rig = this.app.cameras;
        const cam = this.app.view.camera;
        rig.rawPos.copy(rig.freePos);
        rig.rawQuat.setFromEuler(new THREE.Euler(rig.viewPitch, rig.viewYaw, 0, 'YXZ'));
        rig.rawFov = this.settings.fov;
        cam.position.copy(rig.rawPos);
        cam.quaternion.copy(rig.rawQuat);
        cam.fov = this.settings.fov;
        cam.updateProjectionMatrix();
        rig.target.copy(rig.rawPos).addScaledVector(new THREE.Vector3(0, 0, -1).applyQuaternion(rig.rawQuat), 20);
        this.roll();
    }

    // Drawing.

    ensurePasses(width, height) {
        if (!this.material) {
            const uniforms = {
                tColor: { value: null },
                tDepth: { value: null },
                resolution: { value: new THREE.Vector2(1, 1) },
                cameraNear: { value: 0.1 },
                cameraFar: { value: 2500 },
                focus: { value: 30 },
                autoFocus: { value: 1 },
                aperture: { value: 0 },
                maxBlur: { value: 10 },
                vignette: { value: 0 },
            };
            for (const name of ['exposure', 'temperature', 'tint', 'contrast', 'saturation', 'fade', 'mono']) {
                uniforms[name] = { value: 0 };
            }
            for (const name of ['shadows', 'highlights', 'gain']) {
                uniforms[name] = { value: new THREE.Vector3() };
            }
            this.material = new THREE.ShaderMaterial({
                vertexShader: VERTEX, fragmentShader: FRAGMENT, uniforms, depthTest: false, depthWrite: false,
            });
            this.grainMaterial = new THREE.ShaderMaterial({
                vertexShader: VERTEX,
                fragmentShader: GRAIN,
                depthTest: false,
                depthWrite: false,
                uniforms: { tGraded: { value: null }, grain: { value: 0 }, seed: { value: 0 } },
            });
            this.quad = new FullScreenQuad(this.material);
        }
        if (!this.colorTexture || this.colorTexture.image.width !== width || this.colorTexture.image.height !== height) {
            if (this.colorTexture) {
                this.colorTexture.dispose();
            }
            this.colorTexture = new THREE.FramebufferTexture(width, height);
        }
        if (!this.gradeTarget || this.gradeTarget.width !== width || this.gradeTarget.height !== height) {
            if (this.gradeTarget) {
                this.gradeTarget.dispose();
            }
            this.gradeTarget = new THREE.WebGLRenderTarget(width, height, { depthBuffer: false });
        }
        // The depth needs no more than half the size, the blur hides its edges.
        const dw = Math.max(1, Math.ceil(width / 2));
        const dh = Math.max(1, Math.ceil(height / 2));
        if (!this.depthTarget || this.depthTarget.width !== dw || this.depthTarget.height !== dh) {
            if (this.depthTarget) {
                this.depthTarget.depthTexture.dispose();
                this.depthTarget.dispose();
            }
            const depthTexture = new THREE.DepthTexture(dw, dh);
            depthTexture.type = THREE.UnsignedIntType;
            this.depthTarget = new THREE.WebGLRenderTarget(dw, dh, { depthTexture, depthBuffer: true });
        }
    }

    // What the picture depends on besides the settings, the camera and the size, so a still view
    // with still grain draws nothing new.
    pictureKey(width, height) {
        const cam = this.app.view.camera;
        cam.updateMatrixWorld();
        const parts = [width, height, cam.fov, cam.aspect, cam.near];
        for (const v of cam.matrixWorld.elements) {
            parts.push(Math.round(v * 1e5));
        }
        return parts.join(',');
    }

    // Draws the photo onto the canvas at the size of its drawing buffer. The scene and the blur
    // draw again only when the camera, the size or a setting changed, and the grain only when it
    // moved. Force draws everything.
    draw(force = false) {
        const r = this.app.view.renderer;
        const size = r.getDrawingBufferSize(new THREE.Vector2());
        const key = this.pictureKey(size.x, size.y);
        const grain = `${this.settings.grain},${this.seed}`;
        if (force || this.dirty || key !== this.drawnKey || !this.material) {
            this.renderScene(size.x, size.y);
            this.drawnKey = key;
            this.dirty = false;
        } else if (grain === this.drawnGrain) {
            return;
        }
        this.drawnGrain = grain;
        const g = this.grainMaterial;
        g.uniforms.tGraded.value = this.gradeTarget.texture;
        g.uniforms.grain.value = this.settings.grain;
        g.uniforms.seed.value = this.seed;
        this.quad.material = g;
        r.setRenderTarget(null);
        this.quad.render(r);
    }

    // The scene as the page draws it, its depth, and the blur, the grade and the vignette into a
    // target of their own.
    renderScene(width, height) {
        const view = this.app.view;
        const r = view.renderer;
        const cam = view.camera;
        view.render();
        this.ensurePasses(width, height);
        r.setRenderTarget(null);
        r.copyFramebufferToTexture(this.colorTexture);
        const s = this.settings;
        if (s.aperture > 0) {
            // The scene once more, small, for its depth, with the sun's shadow left as it was.
            const shadows = r.shadowMap.autoUpdate;
            r.shadowMap.autoUpdate = false;
            r.setRenderTarget(this.depthTarget);
            r.clear();
            r.render(view.scene, cam);
            r.shadowMap.autoUpdate = shadows;
        }
        const u = this.material.uniforms;
        const L = lookById(s.look);
        u.tColor.value = this.colorTexture;
        u.tDepth.value = this.depthTarget.depthTexture;
        u.resolution.value.set(width, height);
        u.cameraNear.value = cam.near;
        u.cameraFar.value = cam.far;
        u.autoFocus.value = s.focus === 'auto' ? 1 : 0;
        u.focus.value = s.focus === 'auto' ? 30 : s.focus;
        u.aperture.value = s.aperture;
        u.maxBlur.value = MAX_BLUR * height;
        for (const name of ['exposure', 'temperature', 'tint', 'contrast', 'saturation', 'fade', 'mono']) {
            u[name].value = L[name];
        }
        for (const name of ['shadows', 'highlights', 'gain']) {
            u[name].value.fromArray(L[name]);
        }
        u.vignette.value = s.vignette;
        this.quad.material = this.material;
        r.setRenderTarget(this.gradeTarget);
        this.quad.render(r);
        r.setRenderTarget(null);
    }

    freePasses() {
        if (this.quad) {
            this.quad.dispose();
            this.quad = null;
        }
        for (const name of ['material', 'grainMaterial', 'gradeTarget']) {
            if (this[name]) {
                this[name].dispose();
                this[name] = null;
            }
        }
        this.drawnKey = null;
        this.drawnGrain = null;
        if (this.colorTexture) {
            this.colorTexture.dispose();
            this.colorTexture = null;
        }
        if (this.depthTarget) {
            this.depthTarget.depthTexture.dispose();
            this.depthTarget.dispose();
            this.depthTarget = null;
        }
    }

    // The size of the picture in device pixels, the size a photo at Window size has.
    windowSize() {
        const canvas = this.app.view.renderer.domElement;
        const ratio = window.devicePixelRatio || 1;
        return {
            width: Math.max(16, Math.round(canvas.clientWidth * ratio)),
            height: Math.max(16, Math.round(canvas.clientHeight * ratio)),
        };
    }

    maxSide() {
        const gl = this.app.view.renderer.getContext();
        const dims = gl.getParameter(gl.MAX_VIEWPORT_DIMS);
        return Math.min(gl.getParameter(gl.MAX_RENDERBUFFER_SIZE), gl.getParameter(gl.MAX_TEXTURE_SIZE), dims[0], dims[1]);
    }

    // Draws the photo at its size off the view and returns its pixels as a canvas. The drawing
    // buffer takes the photo's size for one draw, inside one task, so the window never shows it.
    renderPhoto(width, height) {
        const app = this.app;
        const view = app.view;
        const r = view.renderer;
        const cam = view.camera;
        const gl = r.getContext();
        const ratio = r.getPixelRatio();
        const viewAspect = cam.aspect;
        const fov = this.settings.fov;
        let pixels = null;
        try {
            this.place();
            r.setPixelRatio(1);
            r.setSize(width, height, false);
            if (gl.drawingBufferWidth !== width || gl.drawingBufferHeight !== height) {
                throw new RangeError(t('photo.error.device', { width: gl.drawingBufferWidth, height: gl.drawingBufferHeight }));
            }
            cam.aspect = width / height;
            cam.fov = captureFov(fov, viewAspect, width / height);
            cam.updateProjectionMatrix();
            if (view.bloom) {
                view.bloom.setSize(width, height);
                if (view.frame) {
                    view.frame.dispose();
                }
                view.frame = new THREE.FramebufferTexture(width, height);
            }
            this.draw(true);
            pixels = new Uint8Array(width * height * 4);
            gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
        } finally {
            r.setPixelRatio(ratio);
            cam.fov = fov;
            view.resize();
            this.place();
            this.draw(true);
        }
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        const image = ctx.createImageData(width, height);
        const row = width * 4;
        for (let y = 0; y < height; y++) {
            image.data.set(pixels.subarray((height - 1 - y) * row, (height - y) * row), y * row);
        }
        for (let i = 3; i < image.data.length; i += 4) {
            image.data[i] = 255;
        }
        ctx.putImageData(image, 0, 0);
        return canvas;
    }

    // The photo as a PNG. Options are width and height, or resolution, as for set, as, 'dataURL'
    // by default or 'blob', and download, true to save the file as well.
    async capture(options = {}) {
        if (!this.isOpen) {
            throw new Error('Photo mode is closed. Open it first with cuju.photo.open().');
        }
        const o = options || {};
        const choice = o.width != null || o.height != null ? { width: o.width, height: o.height } : (o.resolution ?? this.settings.resolution);
        const win = this.windowSize();
        const { width, height } = resolveResolution(choice, win.width, win.height, this.maxSide());
        const canvas = this.renderPhoto(width, height);
        const blob = await new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error(t('photo.error.encode')))), 'image/png'));
        const name = this.fileName();
        this.lastCapture = { width, height, name, bytes: blob.size };
        if (o.download) {
            this.download(blob, name);
        }
        if (o.as === 'blob') {
            return blob;
        }
        return await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(reader.error);
            reader.readAsDataURL(blob);
        });
    }

    // Saves the photo through a download link, at the chosen resolution.
    async save(options = {}) {
        if (this.saving) {
            return null;
        }
        this.saving = true;
        this.status(t('photo.status.saving'));
        try {
            await this.capture({ ...options, as: 'blob', download: true });
            const c = this.lastCapture;
            this.status(t('photo.status.saved', { name: c.name, width: c.width, height: c.height }));
            return { ...c };
        } catch (err) {
            this.status(t('photo.status.failed', { reason: err.message }));
            throw err;
        } finally {
            this.saving = false;
        }
    }

    download(blob, name) {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = name;
        link.hidden = true;
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
    }

    fileName() {
        const app = this.app;
        const source = app.source;
        const id = source ? (source.id || (source.live && source.live.id) || source.kind) : null;
        const frame = app.timeline && source ? app.timeline.index : null;
        return photoFileName(id, frame);
    }

    // Settings.

    // Changes settings, each checked. Returns the state.
    set(patch) {
        this.update(patch, true);
        return this.state();
    }

    // Changes settings. A script's change is strict, a number out of range throws, and the keys,
    // the controller and the panel hold theirs to the range.
    update(patch, strict = false) {
        this.settings = normalizeSettings(this.settings, patch, { strict });
        this.dirty = true;
        if (this.isOpen) {
            this.syncPanel();
            this.drawGuides();
        }
    }

    // Sets the camera from a script, at once. Takes position, target, fov and roll, any of them,
    // and returns the camera.
    camera(view) {
        if (!this.isOpen) {
            throw new Error('Photo mode is closed. Open it first with cuju.photo.open().');
        }
        const rig = this.app.cameras;
        if (view && typeof view === 'object') {
            const position = view.position != null ? vector(view.position, 'position') : null;
            const target = view.target != null ? vector(view.target, 'target') : null;
            const patch = {};
            if (view.fov != null) {
                patch.fov = view.fov;
            }
            if (view.roll != null) {
                patch.roll = view.roll;
            }
            this.update(patch);
            rig.touch();
            rig.blend = null;
            rig.flight = null;
            rig.freeVel.set(0, 0, 0);
            if (position) {
                rig.freePos.copy(confine(position));
            }
            if (target) {
                const dir = new THREE.Vector3().subVectors(target, rig.freePos);
                if (dir.lengthSq() > 1e-8) {
                    rig.yaw = Math.atan2(-dir.x, -dir.z);
                    rig.pitch = THREE.MathUtils.clamp(Math.atan2(dir.y, Math.hypot(dir.x, dir.z)), -CAMERA_BOX.pitchLimit, CAMERA_BOX.pitchLimit);
                }
            }
            rig.viewYaw = rig.yaw;
            rig.viewPitch = rig.pitch;
            this.place();
        }
        return this.cameraState();
    }

    cameraState() {
        const rig = this.app.cameras;
        const forward = new THREE.Vector3(0, 0, -1).applyEuler(new THREE.Euler(rig.viewPitch, rig.viewYaw, 0, 'YXZ'));
        const p = rig.freePos;
        return {
            position: [round(p.x), round(p.y), round(p.z)],
            target: [round(p.x + forward.x * 20), round(p.y + forward.y * 20), round(p.z + forward.z * 20)],
            fov: round(this.settings.fov, 2),
            roll: round(this.settings.roll, 2),
        };
    }

    // Everything a script needs to know.
    state() {
        const s = this.settings;
        return {
            open: this.isOpen,
            interface: this.isOpen && !this.hidden,
            look: s.look,
            vignette: s.vignette,
            grain: s.grain,
            focus: s.focus,
            aperture: s.aperture,
            fov: round(s.fov, 2),
            roll: round(s.roll, 2),
            guide: s.guide,
            resolution: s.resolution,
            windowSize: this.isOpen ? this.windowSize() : null,
            camera: this.isOpen ? this.cameraState() : null,
            lastCapture: this.lastCapture ? { ...this.lastCapture } : null,
            looks: this.looks.slice(),
            guides: this.guides.slice(),
            resolutions: this.resolutions.slice(),
        };
    }

    // Hides or shows the panel, true hides it. Showing it gives the pointer back.
    hideInterface(hidden = true) {
        if (this.isOpen) {
            this.setHidden(!!hidden);
        }
        return this.state();
    }

    setHidden(hidden) {
        this.hidden = hidden;
        if (!this.panel) {
            return;
        }
        this.panel.hidden = hidden;
        if (hidden) {
            this.panel.removeAttribute('data-prompt');
            if (this.panel.contains(document.activeElement)) {
                document.activeElement.blur();
            }
            this.app.hud.toast(t('photo.hidden'), 'info', 1800);
        } else {
            // A panel that asks for the pointer frees it, as every panel of the page does.
            this.panel.setAttribute('data-prompt', '');
            if (document.pointerLockElement) {
                document.exitPointerLock();
            }
        }
    }

    status(text) {
        if (this.statusLine) {
            this.statusLine.textContent = text;
        }
    }

    // Keys.

    onKey(e) {
        const app = this.app;
        this.shift = e.shiftKey;
        if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) {
            return;
        }
        const lower = e.key.length === 1 ? e.key.toLowerCase() : e.key;
        const field = e.target.closest && e.target.closest('input:not([type="range"]):not([type="checkbox"]), select, textarea, [contenteditable]');
        if (!this.isOpen) {
            if (lower === 'o' && app.page === 'watch' && !field && !document.querySelector('dialog[open]')
                && !(e.target.closest && e.target.closest(OWN_KEYS))) {
                e.preventDefault();
                e.stopPropagation();
                this.open();
            }
            return;
        }
        if (app.page !== 'watch') {
            return;
        }
        if (e.key === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            if (this.hidden) {
                this.setHidden(false);
            } else {
                this.close();
            }
            return;
        }
        const control = e.target.closest && e.target.closest('#photo-panel input, #photo-panel select, #photo-panel button');
        if (field || (control && CONTROL_KEYS.has(e.key))) {
            return;
        }
        if (e.key === 'Tab' || PAGE_KEYS.has(lower) || e.key === 'Shift') {
            return;
        }
        const s = this.settings;
        const step = e.shiftKey ? -1 : 1;
        let handled = true;
        if ('wasdqec'.includes(lower) && lower.length === 1) {
            app.cameras.press(lower, true, e.shiftKey);
        } else if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) {
            this.held.add(e.key);
        } else if (lower === 'z' || lower === 'x') {
            this.held.add(lower);
        } else if (e.key === '-' || e.key === '_') {
            this.held.add('-');
        } else if (e.key === '+' || e.key === '=') {
            this.held.add('+');
        } else if (e.code === 'BracketLeft' || e.code === 'BracketRight') {
            const sign = e.code === 'BracketLeft' ? -1 : 1;
            if (e.shiftKey) {
                this.update({ aperture: Math.round((s.aperture + sign * 0.05) * 100) / 100 });
            } else {
                const from = s.focus === 'auto' ? this.focusGuess() : s.focus;
                this.update({ focus: Math.round(from * (sign > 0 ? 1.1 : 1 / 1.1) * 10) / 10 });
            }
        } else if (lower === 'r') {
            this.update({ roll: 0, fov: DEFAULTS.fov, focus: 'auto' });
        } else if (lower === 'l') {
            this.update({ look: nextLook(s.look, step) });
            app.hud.toast(lookLabel(this.settings.look), 'info', 1000);
        } else if (lower === 'g') {
            this.update({ guide: nextGuide(s.guide, step) });
        } else if (lower === 'u') {
            this.setHidden(!this.hidden);
        } else if (lower === 'p') {
            if (!e.repeat) {
                this.save().catch((err) => console.warn('photo not saved', err));
            }
        } else if (lower === 'o') {
            this.close();
        } else {
            // The Watch page's other keys rest while photo mode holds the moment.
            handled = e.key.length === 1 || ['Home', 'End', 'Enter', 'PageUp', 'PageDown', 'Backspace', 'Delete'].includes(e.key);
        }
        if (handled) {
            e.preventDefault();
            e.stopPropagation();
        }
    }

    onKeyUp(e) {
        this.shift = e.shiftKey;
        const lower = e.key.length === 1 ? e.key.toLowerCase() : e.key;
        this.held.delete(e.key);
        this.held.delete(lower);
        if (e.key === '_') {
            this.held.delete('-');
        } else if (e.key === '=') {
            this.held.delete('+');
        }
    }

    // A focus distance to start a change from while focus follows the center, the distance
    // along the view to the ground, or 30 meters for a view at the sky.
    focusGuess() {
        const cam = this.app.view.camera;
        const dir = new THREE.Vector3(0, 0, -1).applyQuaternion(cam.quaternion);
        if (dir.y < -1e-3 && cam.position.y > 0) {
            return THREE.MathUtils.clamp(cam.position.y / -dir.y, FOCUS_MIN, FOCUS_MAX);
        }
        return 30;
    }

    // Controllers.

    readPads() {
        let list = [];
        try {
            list = navigator.getGamepads ? Array.from(navigator.getGamepads() || []) : [];
        } catch {
            list = [];
        }
        const pad = list.find((p) => p && p.connected && p.mapping === 'standard') || list.find((p) => p && p.connected);
        return pad ? readPad(pad, this.padButtons) : { move: [0, 0], look: [0, 0], rise: 0, zoom: 0, roll: 0, pressed: [], buttons: [] };
    }

    // The left stick flies, the right one turns, the triggers lower and raise, the pad zooms and
    // rolls, the shoulders change the look, the lower face button saves, the right one leaves,
    // the left one hides the interface and the upper one changes the guide.
    pollPad(dt) {
        const p = this.readPads();
        this.padButtons = p.buttons;
        const rig = this.app.cameras;
        const [mx, my] = p.move;
        const [lx, ly] = p.look;
        if (mx || my || p.rise) {
            rig.touch();
            const forward = new THREE.Vector3(-Math.sin(rig.yaw), 0, -Math.cos(rig.yaw));
            const right = new THREE.Vector3(-forward.z, 0, forward.x);
            const move = forward.multiplyScalar(-my).addScaledVector(right, mx);
            move.y += p.rise;
            rig.freePos.addScaledVector(move, rig.speed * dt);
            confine(rig.freePos);
        }
        if (lx || ly) {
            rig.touch();
            rig.yaw -= lx * 2.2 * dt;
            rig.pitch = THREE.MathUtils.clamp(rig.pitch - ly * 1.6 * dt, -CAMERA_BOX.pitchLimit, CAMERA_BOX.pitchLimit);
        }
        if (p.zoom || p.roll) {
            this.update({ fov: this.settings.fov + p.zoom * ZOOM * dt, roll: this.settings.roll + p.roll * ROLL * dt });
        }
        for (const name of p.pressed) {
            if (name === 'save') {
                this.save().catch((err) => console.warn('photo not saved', err));
            } else if (name === 'leave') {
                this.close();
                return;
            } else if (name === 'nextLook' || name === 'previousLook') {
                this.update({ look: nextLook(this.settings.look, name === 'nextLook' ? 1 : -1) });
                this.app.hud.toast(lookLabel(this.settings.look), 'info', 1000);
            } else if (name === 'interface') {
                this.setHidden(!this.hidden);
            } else if (name === 'guide') {
                this.update({ guide: nextGuide(this.settings.guide) });
            }
        }
    }

    // The panel and the guides.

    buildUi() {
        const watch = document.getElementById('watch');
        if (!watch || this.panel) {
            return;
        }
        this.guideLayer = svg('svg', { class: 'photo-guides photo-ui', 'aria-hidden': 'true' });
        const select = (id, entries, label) => el('select', { id }, entries.map((e) => el('option', { value: e.id }, label(e))));
        const range = (id, min, max, stepValue) => el('input', { id, type: 'range', min, max, step: stepValue });
        const row = (label, id, control) => el('div', { class: 'photo-row' },
            el('label', { for: id }, label), el('output', { for: id, id: `${id}-value` }), control);
        this.controls = {
            look: select('photo-look', LOOKS, (e) => lookLabel(e.id)),
            vignette: range('photo-vignette', 0, 1, 0.01),
            grain: range('photo-grain', 0, 1, 0.01),
            auto: el('input', { id: 'photo-autofocus', type: 'checkbox' }),
            focus: range('photo-focus', 0, 1000, 1),
            aperture: range('photo-aperture', 0, 1, 0.01),
            fov: range('photo-fov', RANGES.fov[0], RANGES.fov[1], 0.5),
            roll: range('photo-roll', RANGES.roll[0], RANGES.roll[1], 0.5),
            guide: select('photo-guide', GUIDES, (e) => t(`photo.guide.${e.id}`)),
            resolution: select('photo-resolution', [...RESOLUTIONS, { id: 'custom', label: t('photo.resolution.custom') }],
                (e) => (e.id === 'window' ? t('photo.resolution.window') : e.preset ? presetLabel({ id: e.preset }) : e.label)),
            width: el('input', { id: 'photo-width', type: 'number', min: '16', max: '8192', step: '1', value: '1920', 'aria-label': t('photo.width') }),
            height: el('input', { id: 'photo-height', type: 'number', min: '16', max: '8192', step: '1', value: '1080', 'aria-label': t('photo.height') }),
        };
        const c = this.controls;
        this.statusLine = el('p', { class: 'photo-status', role: 'status' });
        const button = (text, title, action, cls = 'btn small') => el('button', { type: 'button', class: cls, title, onclick: action }, text);
        this.panel = el('aside', { id: 'photo-panel', class: 'photo-ui', 'aria-label': t('photo.title'), tabindex: '-1' },
            el('h2', {}, t('photo.title')),
            row(t('photo.look'), 'photo-look', c.look),
            row(t('photo.vignette'), 'photo-vignette', c.vignette),
            row(t('photo.grain'), 'photo-grain', c.grain),
            el('label', { class: 'photo-check' }, c.auto, t('photo.autofocus')),
            row(t('photo.focus'), 'photo-focus', c.focus),
            row(t('photo.aperture'), 'photo-aperture', c.aperture),
            row(t('photo.fov'), 'photo-fov', c.fov),
            row(t('photo.roll'), 'photo-roll', c.roll),
            row(t('photo.guide'), 'photo-guide', c.guide),
            row(t('photo.resolution'), 'photo-resolution', c.resolution),
            el('div', { class: 'photo-row photo-size', hidden: true }, c.width, el('span', { 'aria-hidden': 'true' }, t('photo.by')), c.height),
            el('div', { class: 'photo-actions' },
                button(t('photo.save'), t('photo.save.title'), () => this.save().catch((err) => console.warn('photo not saved', err)), 'btn small primary'),
                button(t('photo.hide'), t('photo.hide.title'), () => this.setHidden(true)),
                button(t('photo.leave'), t('photo.leave.title'), () => this.close())),
            this.statusLine,
            el('p', { class: 'photo-keys' }, t('photo.keys')));
        const on = (control, event, read) => control.addEventListener(event, () => {
            try {
                this.update(read());
            } catch (err) {
                this.status(err.message);
            }
        });
        on(c.look, 'change', () => ({ look: c.look.value }));
        on(c.vignette, 'input', () => ({ vignette: Number(c.vignette.value) }));
        on(c.grain, 'input', () => ({ grain: Number(c.grain.value) }));
        on(c.auto, 'change', () => ({ focus: c.auto.checked ? 'auto' : this.focusGuess() }));
        on(c.focus, 'input', () => ({ focus: sliderToFocus(c.focus.value) }));
        on(c.aperture, 'input', () => ({ aperture: Number(c.aperture.value) }));
        on(c.fov, 'input', () => ({ fov: Number(c.fov.value) }));
        on(c.roll, 'input', () => ({ roll: Number(c.roll.value) }));
        on(c.guide, 'change', () => ({ guide: c.guide.value }));
        const custom = () => {
            const size = { width: Number(c.width.value), height: Number(c.height.value) };
            // The checks of photo-core.js, here with the message in the language of the page.
            for (const side of ['width', 'height']) {
                const v = size[side];
                if (!Number.isInteger(v) || v < MIN_SIDE || v > MAX_SIDE) {
                    throw new RangeError(t(`photo.error.${side}`, { min: MIN_SIDE, max: MAX_SIDE, value: String(v) }));
                }
            }
            return { resolution: size };
        };
        on(c.resolution, 'change', () => (c.resolution.value === 'custom' ? custom() : { resolution: c.resolution.value }));
        on(c.width, 'change', custom);
        on(c.height, 'change', custom);
        watch.append(this.guideLayer, this.panel);
        this.resizeObserver = new ResizeObserver(() => this.drawGuides());
        this.resizeObserver.observe(document.getElementById('stage'));
    }

    destroyUi() {
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
            this.resizeObserver = null;
        }
        for (const node of [this.panel, this.guideLayer]) {
            if (node) {
                node.remove();
            }
        }
        this.panel = null;
        this.guideLayer = null;
        this.controls = null;
        this.statusLine = null;
    }

    syncPanel() {
        const c = this.controls;
        if (!c) {
            return;
        }
        const s = this.settings;
        const show = (control, text) => {
            const out = document.getElementById(`${control.id}-value`);
            if (out) {
                out.textContent = text;
            }
        };
        const value = (control, v) => {
            if (document.activeElement !== control || control.type !== 'range') {
                control.value = String(v);
            }
        };
        value(c.look, s.look);
        value(c.vignette, s.vignette);
        show(c.vignette, t('photo.value.percent', { value: Math.round(s.vignette * 100) }));
        value(c.grain, s.grain);
        show(c.grain, t('photo.value.percent', { value: Math.round(s.grain * 100) }));
        c.auto.checked = s.focus === 'auto';
        value(c.focus, focusToSlider(s.focus === 'auto' ? this.focusGuess() : s.focus));
        show(c.focus, s.focus === 'auto' ? t('photo.value.center') : t('photo.value.meters', { value: decimal(s.focus) }));
        value(c.aperture, s.aperture);
        show(c.aperture, t('photo.value.percent', { value: Math.round(s.aperture * 100) }));
        value(c.fov, Math.round(s.fov * 2) / 2);
        show(c.fov, t('photo.value.degrees', { value: Math.round(s.fov) }));
        value(c.roll, Math.round(s.roll * 2) / 2);
        show(c.roll, t('photo.value.degrees', { value: Math.round(s.roll) }));
        value(c.guide, s.guide);
        const known = typeof s.resolution === 'string' && RESOLUTIONS.some((r) => r.id === s.resolution);
        value(c.resolution, known ? s.resolution : 'custom');
        c.width.parentElement.hidden = known;
        if (!known && s.resolution && typeof s.resolution === 'object') {
            value(c.width, s.resolution.width);
            value(c.height, s.resolution.height);
        }
        show(c.resolution, '');
    }

    // The guides and the frame of a photo of another shape, over the picture and never in it.
    drawGuides() {
        const layer = this.guideLayer;
        if (!layer) {
            return;
        }
        const canvas = this.app.view.renderer.domElement;
        const w = canvas.clientWidth || 1;
        const h = canvas.clientHeight || 1;
        let output = null;
        try {
            const win = this.windowSize();
            const size = resolveResolution(this.settings.resolution, win.width, win.height);
            output = this.settings.resolution === 'window' ? null : size;
        } catch {
            output = null;
        }
        const g = guideGeometry(this.settings.guide, w, h, output);
        layer.setAttribute('viewBox', `0 0 ${w} ${h}`);
        const nodes = [];
        if (g.frame) {
            const f = g.frame;
            nodes.push(svg('path', { class: 'shade', d: `M0 0H${w}V${h}H0Z M${f.x} ${f.y}V${f.y + f.height}H${f.x + f.width}V${f.y}Z` }));
            for (const cls of ['halo', 'ink']) {
                nodes.push(svg('rect', { class: cls, x: f.x, y: f.y, width: f.width, height: f.height }));
            }
        }
        for (const cls of ['halo', 'ink']) {
            for (const [x1, y1, x2, y2] of g.lines) {
                nodes.push(svg('line', { class: cls, x1, y1, x2, y2 }));
            }
        }
        layer.replaceChildren(...nodes);
        layer.dataset.guide = g.kind;
        layer.dataset.lines = String(g.lines.length);
    }
}
