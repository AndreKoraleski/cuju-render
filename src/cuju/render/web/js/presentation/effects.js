// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The effects a team package draws, section 8 of the contract. Particles, trails, decals on the
// pitch, lights and transient models, spawned by reflexes and workers on the team's own moments
// and drawn within the team's budgets.
//
// Particles live in one pool of points per effect of a team, simulated here and drawn by one
// small shader, so a burst costs no allocation. A trail is a ribbon that faces the camera, fed by
// a socket, the ball or the ball's future path. A decal lies on the pitch and fades. A team's pool
// lights are allocated once when its players are built, so three.js never recompiles a program
// when one turns on, and every further light becomes a local light that lights the team's own
// materials alone. Each light, each emissive and each pass of a team goes through the flash
// governor, and an effect on the line from the camera to the ball or to a player's torso fades to
// a quarter of its opacity.
//
// Effects spawned for an event are transient. They follow the event's seed, so a replay draws the
// same burst, and end at a new epoch. Effects on the ball follow it while the team holds the
// ball's custody, and otherwise stay where the ball was.

import * as THREE from 'three';
import { BALL_FLOAT, NODES_FLOAT, PLAYER_FLOATS, isCut } from '../recording/format.js';
import { OCCLUSION, occlusion } from './commands.js';
import { LOCAL_LIGHTS, shaderMaterial } from './shaders.js';
import { socketMatrix } from './stage.js';
import { clamp, hash } from './values.js';

export const MAX_INSTANCES = 64;
const tmpMatrix = new THREE.Matrix4();
const tmpVector = new THREE.Vector3();
const tmpQuat = new THREE.Quaternion();
const tmpScale = new THREE.Vector3();
const UP = new THREE.Vector3(0, 1, 0);

// A small generator of numbers from 0 to 1 by seed, mulberry32, the same on every machine.
export function random(seed) {
    let a = seed >>> 0;
    return () => {
        a = (a + 0x6D2B79F5) >>> 0;
        let t = a;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

const range = (r, rand, fallback) => {
    const v = Array.isArray(r) ? r : r == null ? fallback : [r, r];
    return v[0] + (v[1] - v[0]) * rand();
};
const pair = (v, fallback) => (Array.isArray(v) ? v : v == null ? fallback : [v, v]);
const rgb = (c) => new THREE.Color().setRGB(c[0] / 255, c[1] / 255, c[2] / 255, THREE.SRGBColorSpace);

// A colour of a manifest as a start and an end, from one colour or two, each three bytes.
export function colorPair(c, fallback) {
    if (!Array.isArray(c) || !c.length) {
        return fallback;
    }
    if (Array.isArray(c[0])) {
        return [c[0], c[1] || c[0]];
    }
    return [c, c];
}

function softDot() {
    const size = 64;
    const data = new Uint8Array(size * size * 4);
    for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
            const d = Math.hypot(x - size / 2 + 0.5, y - size / 2 + 0.5) / (size / 2);
            const a = Math.max(0, 1 - d) ** 2;
            data.set([255, 255, 255, Math.round(a * 255)], (y * size + x) * 4);
        }
    }
    const t = new THREE.DataTexture(data, size, size);
    t.needsUpdate = true;
    return t;
}
let DOT = null;
const dot = () => DOT || (DOT = softDot());

const POINTS_VERTEX = `
attribute float aT;
attribute float aSeed;
uniform vec2 uSize;
uniform float uScale;
varying float vT;
varying float vSeed;
void main() {
    vT = aT;
    vSeed = aSeed;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = aT > 1.0 ? 0.0 : mix(uSize.x, uSize.y, aT) * uScale / max(0.1, -mv.z);
    gl_Position = projectionMatrix * mv;
}`;
const POINTS_FRAGMENT = `
uniform sampler2D uMap;
uniform vec3 uColorA;
uniform vec3 uColorB;
uniform vec2 uOpacity;
uniform float uFade;
varying float vT;
varying float vSeed;
void main() {
    if (vT > 1.0) discard;
    vec4 tex = texture2D(uMap, gl_PointCoord);
    float a = tex.a * mix(uOpacity.x, uOpacity.y, vT) * uFade;
    if (a < 0.004) discard;
    gl_FragColor = vec4(mix(uColorA, uColorB, vT) * tex.rgb, a);
}`;

// One pool of particles of one effect of a team, simulated on the main thread.
class Cloud {
    constructor(spec, capacity, texture, shared) {
        this.spec = spec;
        this.capacity = Math.max(1, capacity);
        this.count = 0;
        const n = this.capacity;
        this.pos = new Float32Array(n * 3);
        this.vel = new Float32Array(n * 3);
        this.age = new Float32Array(n);
        this.life = new Float32Array(n);
        this.t = new Float32Array(n).fill(2);
        this.seed = new Float32Array(n);
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.BufferAttribute(this.pos, 3).setUsage(THREE.DynamicDrawUsage));
        g.setAttribute('aT', new THREE.BufferAttribute(this.t, 1).setUsage(THREE.DynamicDrawUsage));
        g.setAttribute('aSeed', new THREE.BufferAttribute(this.seed, 1));
        g.setDrawRange(0, 0);
        const colors = colorPair(spec.color, [[255, 236, 180], [255, 120, 40]]);
        const size = pair(spec.size, [0.12, 0.02]);
        const opacity = pair(spec.opacity, [1, 0]);
        const uniforms = {
            uMap: { value: texture || dot() }, uColorA: { value: rgb(colors[0]) }, uColorB: { value: rgb(colors[1]) },
            uSize: { value: new THREE.Vector2(size[0], size[1]) }, uOpacity: { value: new THREE.Vector2(opacity[0], opacity[1]) },
            uScale: { value: 600 }, uFade: { value: 1 },
        };
        this.material = new THREE.ShaderMaterial({
            uniforms, vertexShader: POINTS_VERTEX, fragmentShader: POINTS_FRAGMENT, transparent: true, depthWrite: false,
            blending: spec.blend === 'normal' ? THREE.NormalBlending : THREE.AdditiveBlending,
        });
        this.uniforms = uniforms;
        this.points = new THREE.Points(g, this.material);
        this.points.frustumCulled = false;
        this.points.renderOrder = 3;
        this.shared = shared;
    }

    // Emits n particles at a point of three's frame, along a direction with the effect's spread.
    emit(n, origin, direction, rand, limit) {
        const spec = this.spec;
        const spread = spec.spread ?? 0.6;
        for (let i = 0; i < n && this.count < this.capacity && limit() > 0; i++) {
            const j = this.count++;
            // A direction inside the cone about the given one.
            const theta = rand() * Math.PI * 2;
            const phi = Math.acos(1 - rand() * (1 - Math.cos(spread)));
            tmpVector.set(Math.sin(phi) * Math.cos(theta), Math.cos(phi), Math.sin(phi) * Math.sin(theta));
            tmpQuat.setFromUnitVectors(UP, direction);
            tmpVector.applyQuaternion(tmpQuat);
            const speed = range(spec.speed, rand, [1, 4]);
            this.pos.set([origin.x, origin.y, origin.z], j * 3);
            this.vel.set([tmpVector.x * speed, tmpVector.y * speed, tmpVector.z * speed], j * 3);
            this.age[j] = 0;
            this.life[j] = range(spec.life, rand, [0.4, 1.0]);
            this.seed[j] = rand();
            this.t[j] = 0;
        }
    }

    step(dt) {
        const g = this.spec.gravity ?? -4;
        const drag = Math.exp(-(this.spec.drag ?? 1) * dt);
        for (let j = 0; j < this.count; j++) {
            this.age[j] += dt;
            if (this.age[j] >= this.life[j]) {
                // The last particle takes the place of the one that died.
                const last = --this.count;
                this.pos.copyWithin(j * 3, last * 3, last * 3 + 3);
                this.vel.copyWithin(j * 3, last * 3, last * 3 + 3);
                this.age[j] = this.age[last];
                this.life[j] = this.life[last];
                this.seed[j] = this.seed[last];
                this.t[last] = 2;
                j--;
                continue;
            }
            const o = j * 3;
            this.vel[o] *= drag;
            this.vel[o + 1] = this.vel[o + 1] * drag + g * dt;
            this.vel[o + 2] *= drag;
            this.pos[o] += this.vel[o] * dt;
            this.pos[o + 1] = Math.max(0.02, this.pos[o + 1] + this.vel[o + 1] * dt);
            this.pos[o + 2] += this.vel[o + 2] * dt;
            this.t[j] = this.age[j] / this.life[j];
        }
        const geo = this.points.geometry;
        geo.attributes.position.needsUpdate = true;
        geo.attributes.aT.needsUpdate = true;
        geo.attributes.aSeed.needsUpdate = true;
        geo.setDrawRange(0, this.count);
    }

    center(out) {
        if (!this.count) {
            return null;
        }
        out.set(0, 0, 0);
        const n = Math.min(this.count, 16);
        for (let j = 0; j < n; j++) {
            out.x += this.pos[j * 3];
            out.y += this.pos[j * 3 + 1];
            out.z += this.pos[j * 3 + 2];
        }
        return out.multiplyScalar(1 / n);
    }

    dispose() {
        this.points.removeFromParent();
        this.points.geometry.dispose();
        this.material.dispose();
    }
}

// A ribbon that faces the camera, the last seconds of a moving point.
class Ribbon {
    constructor(spec, texture) {
        this.spec = spec;
        this.segments = clamp(Math.round(spec.segments || 32), 4, 64);
        this.length = spec.length || 0.6;
        this.samples = [];
        const n = this.segments;
        this.positions = new Float32Array(n * 2 * 3);
        this.colors = new Float32Array(n * 2 * 4);
        const index = [];
        for (let i = 0; i < n - 1; i++) {
            const a = i * 2;
            index.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
        }
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.BufferAttribute(this.positions, 3).setUsage(THREE.DynamicDrawUsage));
        g.setAttribute('color', new THREE.BufferAttribute(this.colors, 4).setUsage(THREE.DynamicDrawUsage));
        g.setIndex(index);
        g.setDrawRange(0, 0);
        this.material = new THREE.MeshBasicMaterial({
            vertexColors: true, transparent: true, depthWrite: false, side: THREE.DoubleSide, map: texture || null,
            blending: spec.blend === 'normal' ? THREE.NormalBlending : THREE.AdditiveBlending, toneMapped: false,
        });
        this.mesh = new THREE.Mesh(g, this.material);
        this.mesh.frustumCulled = false;
        this.mesh.renderOrder = 3;
        const c = colorPair(spec.color, [[255, 220, 150], [255, 90, 30]]);
        this.colorA = rgb(c[0]);
        this.colorB = rgb(c[1]);
        this.width = pair(spec.width, [0.25, 0]);
        this.opacity = pair(spec.opacity, [0.9, 0]);
    }

    // Adds a point at time now, or replaces the whole ribbon by a list of points with their times.
    sample(now, p) {
        const last = this.samples[this.samples.length - 1];
        if (!last || now - last.t > 1 / 120) {
            this.samples.push({ t: now, p: p.clone() });
        } else {
            last.p.copy(p);
        }
        while (this.samples.length > this.segments || (this.samples.length && now - this.samples[0].t > this.length)) {
            this.samples.shift();
        }
    }

    build(camera, fade, now) {
        const s = this.samples;
        const n = s.length;
        if (n < 2) {
            this.mesh.geometry.setDrawRange(0, 0);
            return;
        }
        for (let i = 0; i < n; i++) {
            const p = s[i].p;
            const q = s[Math.min(n - 1, i + 1)].p;
            const o = s[Math.max(0, i - 1)].p;
            const tangent = tmpVector.subVectors(q, o);
            if (tangent.lengthSq() < 1e-10) {
                tangent.set(1, 0, 0);
            }
            const view = new THREE.Vector3().subVectors(camera.position, p);
            const side = new THREE.Vector3().crossVectors(tangent, view).normalize();
            // u runs from 0 at the newest point to 1 at the oldest.
            const u = clamp((now - s[i].t) / this.length, 0, 1);
            const w = (this.width[0] + (this.width[1] - this.width[0]) * u) / 2;
            const a = (this.opacity[0] + (this.opacity[1] - this.opacity[0]) * u) * fade;
            const color = this.colorA.clone().lerp(this.colorB, u);
            this.positions.set([p.x + side.x * w, p.y + side.y * w, p.z + side.z * w, p.x - side.x * w, p.y - side.y * w, p.z - side.z * w], i * 6);
            this.colors.set([color.r, color.g, color.b, a, color.r, color.g, color.b, a], i * 8);
        }
        const g = this.mesh.geometry;
        g.attributes.position.needsUpdate = true;
        g.attributes.color.needsUpdate = true;
        g.setDrawRange(0, (n - 1) * 6);
    }

    dispose() {
        this.mesh.removeFromParent();
        this.mesh.geometry.dispose();
        this.material.dispose();
    }
}

let RING = null;
function ringTexture() {
    if (RING) {
        return RING;
    }
    const size = 128;
    const data = new Uint8Array(size * size * 4);
    for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
            const d = Math.hypot(x - size / 2 + 0.5, y - size / 2 + 0.5) / (size / 2);
            const a = d > 1 ? 0 : (1 - d) ** 0.6 * Math.min(1, (1 - d) * 6);
            data.set([255, 255, 255, Math.round(a * 255)], (y * size + x) * 4);
        }
    }
    RING = new THREE.DataTexture(data, size, size);
    RING.needsUpdate = true;
    return RING;
}

// The effects of one team, its clouds, ribbons, decals, lights and models.
class TeamEffects {
    constructor(system, pkg) {
        this.system = system;
        this.pkg = pkg;
        this.side = pkg.side;
        this.group = new THREE.Group();
        this.group.name = `team effects ${pkg.side}`;
        this.clouds = new Map();
        this.instances = new Map();
        this.decals = [];
        this.pool = [];
        this.local = [];
        this.textures = new Map();
        this.particles = 0;
    }

    texture(file) {
        if (!file) {
            return null;
        }
        if (!this.textures.has(file)) {
            const t = new THREE.Texture();
            this.textures.set(file, t);
            this.system.presentation.fetchFile(this.pkg, file).then((data) => createImageBitmap(new Blob([data]))).then((bitmap) => {
                t.image = bitmap;
                t.colorSpace = THREE.SRGBColorSpace;
                t.needsUpdate = true;
                this.pkg.budget.take({ textureBytes: bitmap.width * bitmap.height * 4 });
            }).catch((err) => this.pkg.errors.push(`texture ${file} not used, ${err.message || err}`));
        }
        return this.textures.get(file);
    }

    // The team's pool lights, allocated once, as many as the budget of its quality holds.
    allocate(count) {
        while (this.pool.length < count) {
            const light = new THREE.PointLight(0xffffff, 0, 6, 2);
            light.castShadow = false;
            light.userData.free = true;
            this.pool.push(light);
            this.group.add(light);
        }
    }

    cloud(name, spec) {
        let cloud = this.clouds.get(name);
        if (!cloud) {
            const limits = this.pkg.budget.limits;
            const rungs = this.pkg.budget.past('fewerParticles') ? 0.5 : 1;
            const capacity = Math.min(Math.floor(limits.particles * rungs), Math.ceil((spec.count || 0) + (spec.rate || 0) * pair(spec.life, [0.4, 1])[1] * 1.2) + 8);
            cloud = new Cloud(spec, capacity, this.texture(spec.texture), this.system.shared(this.side));
            if (spec.shader && this.system.presentation.shaderSource(this.pkg, spec.shader)) {
                const custom = this.system.presentation.customMaterial(this.pkg, spec.shader, { blending: spec.blend || 'additive' });
                if (custom) {
                    Object.assign(custom.uniforms, cloud.uniforms);
                    cloud.points.material = custom;
                }
            }
            this.clouds.set(name, cloud);
            this.group.add(cloud.points);
        }
        return cloud;
    }

    dispose() {
        for (const c of this.clouds.values()) {
            c.dispose();
        }
        for (const i of this.instances.values()) {
            this.system.end(this, i, true);
        }
        for (const d of this.decals) {
            d.mesh.removeFromParent();
            d.mesh.material.dispose();
        }
        for (const t of this.textures.values()) {
            t.dispose();
        }
        this.group.removeFromParent();
    }
}

export class Effects {
    constructor(presentation) {
        this.presentation = presentation;
        this.teams = [null, null];
        this.scene = null;
        this.uniforms = [null, null];
        this.spawned = 0;
        this.refused = 0;
    }

    shared(side) {
        return this.presentation.sharedUniforms(side);
    }

    // Builds the effects of the packages on screen once the page built its players.
    attach(scene, packages) {
        this.dispose();
        this.scene = scene;
        for (const pkg of packages) {
            if (!pkg) {
                continue;
            }
            const team = new TeamEffects(this, pkg);
            this.teams[pkg.side] = team;
            scene.add(team.group);
            const m = pkg.manifest;
            const wantsPool = Object.values(m.lights || {}).some((l) => l.kind === 'pool')
                || Object.values(m.effects || {}).some((e) => e.type === 'light');
            if (wantsPool && !pkg.budget.past('localLights')) {
                team.allocate(pkg.budget.limits.lights);
            }
        }
    }

    // A command of kind effects, from a reflex or a worker. Returns whether it was taken.
    command(pkg, c, event = null) {
        const team = pkg && this.teams[pkg.side];
        if (!team || pkg.budget.past('stock')) {
            return false;
        }
        if (c.op === 'stop') {
            const inst = team.instances.get(c.id);
            if (inst) {
                inst.stopAt = this.presentation.clocks.cosmetic;
                inst.fadeOut = c.fadeOut;
            }
            return !!inst;
        }
        if (c.op === 'update') {
            const inst = team.instances.get(c.id);
            if (inst) {
                Object.assign(inst.params, c.params || {});
            }
            return !!inst;
        }
        const name = c.effect || c.kind;
        const spec = (pkg.manifest.effects || {})[name];
        if (!spec) {
            return false;
        }
        if (spec.type === 'post') {
            return this.presentation.post.spawn(pkg, spec, c, event);
        }
        if (team.instances.size >= Math.min(MAX_INSTANCES, pkg.budget.limits.effects || MAX_INSTANCES)) {
            this.refused += 1;
            return false;
        }
        const clocks = this.presentation.clocks;
        const seed = hash(`${c.id}:${event ? event.id : ''}`);
        const contact = event && event.data && event.data.contactT != null ? event.data.contactT : event ? event.t : clocks.sim;
        const at = c.at && c.at.mode === 'contact' ? contact + (c.at.offset || 0) : (event ? event.t : clocks.sim) + ((c.at && c.at.offset) || 0);
        const inst = {
            id: c.id, name, spec, attach: c.attach, event, params: { ...(c.params || {}) }, rand: random(seed), seed,
            startSim: at, born: null, stopAt: null, fadeOut: 0.5, fade: 1, occlusion: 1, quiet: !!c.quiet,
            duration: spec.duration ?? (spec.type === 'particles' && !spec.rate ? 0 : spec.type === 'light' ? 0.6 : 1.2),
            point: null, ribbon: null, light: null, object: null,
        };
        team.instances.set(c.id, inst);
        this.spawned += 1;
        return true;
    }

    // Where an effect is now in three's frame, with the frame of its socket, or null.
    resolve(team, inst, out, frame = null) {
        const p = this.presentation;
        const a = inst.attach || { to: 'self' };
        if (a.to === 'ball' || a.to === 'path') {
            const ball = p.app.ball ? p.app.ball.mesh.position : null;
            if (!ball) {
                return null;
            }
            // A team that holds the ball's custody draws on the ball, any other where the ball was.
            if (p.custody.holds(team.side) || !inst.point) {
                inst.point = ball.clone();
            }
            return out.copy(inst.point);
        }
        if (a.to === 'world') {
            const pos = inst.params.position;
            if (Array.isArray(pos) && pos.length === 3) {
                return out.set(Number(pos[0]) || 0, Number(pos[2]) || 0, -(Number(pos[1]) || 0));
            }
            const cp = inst.event && inst.event.data && inst.event.data.contactPoint;
            if (cp) {
                return out.set(cp[0], cp[2], -cp[1]);
            }
            const ball = p.app.ball ? p.app.ball.mesh.position : null;
            return ball ? out.copy(inst.point || (inst.point = ball.clone())) : null;
        }
        const id = a.to === 'entity' && a.entity ? a.entity : inst.event && inst.event.player != null ? `p${inst.event.player}` : null;
        let entity = id ? p.entities.get(id) : null;
        if (!entity || entity.pkg !== team.pkg) {
            entity = [...p.entities.values()].find((e) => e.pkg === team.pkg && e.visible) || null;
        }
        if (!entity || !entity.visible) {
            return null;
        }
        const socket = a.socket && entity.pkg.manifest.rig.sockets[a.socket];
        const entry = p.players && p.players.rigged ? p.players.rigged.byK.get(entity.k) : null;
        if (socket && entry) {
            socketMatrix(entry.rig, entry.instance, socket, entity.cosmetic, tmpMatrix);
        } else {
            tmpMatrix.copy(entity.cosmetic);
            if (!socket) {
                tmpMatrix.multiply(new THREE.Matrix4().makeTranslation(0, ((entity.bounds() || {}).height || 1.8) * 0.5, 0));
            }
        }
        if (frame) {
            frame.copy(tmpMatrix);
        }
        return out.setFromMatrixPosition(tmpMatrix);
    }

    // The ball's drawn path from now for seconds ahead, from the frames, in three's frame.
    path(seconds, count) {
        const tl = this.presentation.app.timeline;
        const store = tl.store;
        const sps = tl.sps || 10;
        const out = [];
        for (let i = 0; i < count; i++) {
            const t = tl.t + (seconds * sps * i) / Math.max(1, count - 1);
            const j = Math.floor(t);
            const a = store.get(j);
            const b = store.get(j + 1);
            if (!a) {
                break;
            }
            const w = b && !isCut(a, b) ? t - j : 0;
            const d = (k) => a.data[BALL_FLOAT + k] + ((b && w ? b.data[BALL_FLOAT + k] : a.data[BALL_FLOAT + k]) - a.data[BALL_FLOAT + k]) * w;
            out.push({ t: i / Math.max(1, count - 1), p: new THREE.Vector3(d(0), d(2), -d(1)) });
        }
        return out;
    }

    // Moves every effect on by one drawing, after the players and the ball are drawn.
    update(dt) {
        const p = this.presentation;
        const camera = p.app.view ? p.app.view.camera : null;
        if (!camera || !this.scene) {
            return;
        }
        const clocks = p.clocks;
        const now = clocks.cosmetic;
        const sim = clocks.sim;
        const forward = p.app.timeline && p.app.timeline.playing && p.app.timeline.direction > 0;
        const governor = p.flashFactor();
        const motion = p.app.reducedMotion ? 0.5 : 1;
        const targets = this.targets(camera);
        for (const team of this.teams) {
            if (!team) {
                continue;
            }
            // What each team's effects cost counts against its own budget.
            const started = performance.now();
            const pkg = team.pkg;
            const scale = (p.app.view.renderer.domElement.height || 800) / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2));
            team.particles = 0;
            for (const cloud of team.clouds.values()) {
                team.particles += cloud.count;
            }
            const limit = () => Math.floor(pkg.budget.limits.particles * (pkg.budget.past('fewerParticles') ? 0.5 : 1) * motion) - team.particles;
            for (const inst of team.instances.values()) {
                // An effect waits for its time on the simulation clock, the contact of its event.
                if (inst.born == null) {
                    if (sim + 1e-6 < inst.startSim && inst.startSim - sim < 3) {
                        continue;
                    }
                    inst.born = now;
                }
                const age = now - inst.born;
                const ending = inst.stopAt != null || (inst.duration > 0 && age > inst.duration);
                if (ending && inst.stopAt == null) {
                    inst.stopAt = now;
                }
                const out = inst.stopAt != null ? clamp(1 - (now - inst.stopAt) / Math.max(0.05, inst.fadeOut), 0, 1) : 1;
                const pos = this.resolve(team, inst, new THREE.Vector3(), tmpMatrix);
                const want = pos && !p.relaxed() ? occlusion([pos.x, pos.y, pos.z], [camera.position.x, camera.position.y, camera.position.z], targets) : 1;
                const rate = want < inst.occlusion ? (1 - OCCLUSION.floor) / OCCLUSION.fadeIn : (1 - OCCLUSION.floor) / OCCLUSION.recover;
                inst.occlusion = want < inst.occlusion ? Math.max(want, inst.occlusion - rate * dt) : Math.min(want, inst.occlusion + rate * dt);
                inst.fade = out * inst.occlusion;
                this.step(team, inst, pos, dt, now, age, governor, forward, limit, camera, scale);
                if (inst.stopAt != null && out <= 0 && !(inst.cloud && inst.cloud.count)) {
                    this.end(team, inst);
                }
            }
            for (const cloud of team.clouds.values()) {
                cloud.uniforms.uScale.value = scale;
                cloud.step(dt);
            }
            this.stepDecals(team, now);
            this.stepLights(team, now, governor);
            team.spent = performance.now() - started;
        }
    }

    // The points an effect must leave clear, the ball and the torso of every player on screen.
    targets(camera) {
        const p = this.presentation;
        const out = [];
        const ball = p.app.ball ? p.app.ball.mesh.position : null;
        if (ball) {
            out.push([ball.x, ball.y, ball.z]);
        }
        if (p.players && p.app.pose) {
            const n = p.header ? p.header.players.length : 0;
            for (let k = 0; k < n; k++) {
                if (p.players.visible && !p.players.visible[k]) {
                    continue;
                }
                const v = p.players.position(p.app.pose, k, tmpVector);
                out.push([v.x, 1.2, v.z]);
            }
        }
        return out;
    }

    step(team, inst, pos, dt, now, age, governor, forward, limit, camera, scale) {
        const spec = inst.spec;
        if (spec.type === 'particles') {
            const cloud = team.cloud(inst.name, spec);
            inst.cloud = cloud;
            cloud.uniforms.uFade.value = inst.fade * governor;
            if (!pos || inst.stopAt != null) {
                return;
            }
            const direction = new THREE.Vector3(...(spec.direction || [0, 1, 0]));
            if (inst.attach && inst.attach.socket) {
                tmpMatrix.decompose(tmpVector, tmpQuat, tmpScale);
                direction.applyQuaternion(tmpQuat);
            }
            direction.normalize();
            // Bursts and streams emit in forward play alone, so reverse play leaves no new sparks.
            if (!inst.burst) {
                inst.burst = true;
                if (forward || inst.event == null) {
                    cloud.emit(Math.round(spec.count ?? 24), pos, direction, inst.rand, limit);
                }
            }
            if (spec.rate && forward) {
                inst.carry = (inst.carry || 0) + spec.rate * dt;
                const n = Math.floor(inst.carry);
                inst.carry -= n;
                cloud.emit(n, pos, direction, inst.rand, limit);
            }
        } else if (spec.type === 'trail') {
            if (!inst.ribbon) {
                inst.ribbon = new Ribbon(spec, team.texture(spec.texture));
                team.group.add(inst.ribbon.mesh);
            }
            const r = inst.ribbon;
            r.material.opacity = 1;
            if (inst.attach && inst.attach.to === 'path') {
                // The ghost of the path ahead, the exact samples of the frames.
                r.samples = this.path(r.length, r.segments).map((s) => ({ t: now - s.t * r.length, p: s.p }));
            } else if (pos && inst.stopAt == null) {
                r.sample(now, pos);
            }
            r.build(camera, inst.fade * governor, now);
        } else if (spec.type === 'decal') {
            if (!inst.placed && pos) {
                inst.placed = true;
                this.decal(team, spec, pos, inst.rand);
            }
            inst.stopAt = inst.stopAt ?? now;
        } else if (spec.type === 'light') {
            const attack = spec.attack ?? 0.05;
            const release = spec.release ?? 0.3;
            const life = inst.duration;
            const env = Math.min(1, age / Math.max(1e-3, attack)) * (life > 0 && age > life ? clamp(1 - (age - life) / release, 0, 1) : 1);
            inst.lightLevel = (spec.intensity ?? 4) * env * (inst.stopAt != null ? inst.fade : inst.occlusion);
            inst.lightPos = pos ? pos.clone() : null;
            if (inst.stopAt != null && env <= 0) {
                inst.fade = 0;
            }
        } else if (spec.type === 'mesh') {
            if (!inst.object) {
                const source = team.pkg.effectScenes && team.pkg.effectScenes.get(spec.file);
                if (!source) {
                    return;
                }
                inst.object = source.clone(true);
                inst.object.traverse((o) => {
                    if (o.isMesh) {
                        o.material = o.material.clone();
                        o.material.transparent = true;
                        o.castShadow = false;
                    }
                });
                team.group.add(inst.object);
            }
            if (pos) {
                inst.object.position.copy(pos);
            }
            const s = spec.scale ?? 1;
            inst.object.scale.setScalar(s);
            inst.object.rotation.y = (spec.spin || 0) * age;
            inst.object.traverse((o) => {
                if (o.isMesh) {
                    o.material.opacity = inst.fade * governor;
                }
            });
        }
    }

    decal(team, spec, pos, rand) {
        const limit = team.pkg.budget.limits.decals || 64;
        while (team.decals.length >= limit) {
            const old = team.decals.shift();
            old.mesh.removeFromParent();
            old.mesh.material.dispose();
        }
        const size = spec.size ?? 1;
        const color = spec.color ? rgb(colorPair(spec.color)[0]) : new THREE.Color(0.1, 0.08, 0.06);
        const material = new THREE.MeshBasicMaterial({
            map: team.texture(spec.texture) || ringTexture(), color, transparent: true, depthWrite: false,
            polygonOffset: true, polygonOffsetFactor: -2, blending: spec.blend === 'additive' ? THREE.AdditiveBlending : THREE.NormalBlending,
        });
        const mesh = new THREE.Mesh(team.system.decalGeometry || (team.system.decalGeometry = new THREE.PlaneGeometry(1, 1)), material);
        mesh.rotation.x = -Math.PI / 2;
        mesh.rotation.z = spec.rotation === 'random' || spec.rotation == null ? rand() * Math.PI * 2 : THREE.MathUtils.degToRad(spec.rotation);
        mesh.scale.set(size, size, 1);
        mesh.position.set(pos.x, 0.014, pos.z);
        mesh.renderOrder = 1;
        team.group.add(mesh);
        const opacity = Math.min(0.7, pair(spec.opacity, [0.6, 0.6])[0]);
        const half = spec.life === 'half';
        team.decals.push({ mesh, born: this.presentation.clocks.cosmetic, life: half ? Infinity : spec.life ?? 8, fade: spec.fade ?? 1, opacity, half });
    }

    stepDecals(team, now) {
        team.decals = team.decals.filter((d) => {
            const age = now - d.born;
            const left = d.life - age;
            const k = Math.min(1, age / 0.25) * clamp(left / d.fade, 0, 1);
            d.mesh.material.opacity = d.opacity * k;
            if (left <= 0) {
                d.mesh.removeFromParent();
                d.mesh.material.dispose();
                return false;
            }
            return true;
        });
    }

    // Halftime clears the decals that last until it.
    halftime() {
        for (const team of this.teams) {
            if (team) {
                for (const d of team.decals) {
                    if (d.half) {
                        d.life = this.presentation.clocks.cosmetic - d.born + d.fade;
                    }
                }
            }
        }
    }

    // The lights of a team on this drawing, the effects of type light and the lights of the
    // manifest, the strongest first into the pool, the rest local. Every intensity goes through
    // the flash governor.
    stepLights(team, now, governor) {
        const p = this.presentation;
        const wanted = [];
        for (const inst of team.instances.values()) {
            if (inst.spec.type === 'light' && inst.lightPos && inst.lightLevel > 0) {
                wanted.push({ id: `fx:${inst.id}`, pos: inst.lightPos, color: colorPair(inst.spec.color, [[255, 200, 120]])[0], intensity: inst.lightLevel, distance: inst.spec.distance ?? 6, decay: inst.spec.decay ?? 2, kind: 'pool' });
            }
        }
        for (const l of p.manifestLights(team.pkg)) {
            wanted.push(l);
        }
        const time = p.clocks.cosmetic;
        for (const w of wanted) {
            const env = p.flash.envelope(`${team.side}:${w.id}`);
            w.level = env.apply(time, w.intensity / 50, isRed(w.color)) * 50 * governor;
        }
        wanted.sort((a, b) => (b.kind === 'pool') - (a.kind === 'pool') || b.level - a.level);
        const free = team.pool.slice();
        const local = [];
        for (const w of wanted) {
            const light = w.kind === 'pool' ? free.shift() : null;
            if (light) {
                light.position.copy(w.pos);
                light.color.setRGB(w.color[0] / 255, w.color[1] / 255, w.color[2] / 255, THREE.SRGBColorSpace);
                light.intensity = w.level;
                light.distance = w.distance;
                light.decay = w.decay;
            } else if (local.length < LOCAL_LIGHTS) {
                local.push(w);
            }
        }
        for (const light of free) {
            light.intensity = 0;
        }
        team.localCount = local.length;
        team.poolCount = team.pool.length - free.length;
        p.setLocalLights(team.side, local);
    }

    end(team, inst, quiet = false) {
        if (inst.ribbon) {
            inst.ribbon.dispose();
        }
        if (inst.object) {
            inst.object.removeFromParent();
            inst.object.traverse((o) => {
                if (o.isMesh) {
                    o.material.dispose();
                }
            });
        }
        team.instances.delete(inst.id);
        if (!quiet) {
            team.ended = (team.ended || 0) + 1;
        }
    }

    // A new epoch ends every transient effect at once.
    endTransient() {
        for (const team of this.teams) {
            if (!team) {
                continue;
            }
            for (const inst of [...team.instances.values()]) {
                if (inst.event) {
                    this.end(team, inst, true);
                }
            }
            for (const cloud of team.clouds.values()) {
                cloud.count = 0;
                cloud.t.fill(2);
                cloud.step(0);
            }
        }
    }

    // The degrade ladder of a team, its pool lights handed to local lights at that rung.
    degrade(pkg) {
        const team = this.teams[pkg.side];
        if (team && pkg.budget.past('localLights')) {
            for (const light of team.pool) {
                light.intensity = 0;
            }
            team.pool.length = 0;
        }
    }

    // What the effects of each team hold now, for status and the preview.
    snapshot() {
        return this.teams.map((t) => (t ? {
            instances: t.instances.size, particles: t.particles, clouds: t.clouds.size, decals: t.decals.length,
            poolLights: t.pool.length, poolLit: t.poolCount || 0, localLights: t.localCount || 0,
            kinds: [...t.instances.values()].map((i) => i.spec.type),
        } : null));
    }

    dispose() {
        for (const t of this.teams) {
            if (t) {
                t.dispose();
            }
        }
        this.teams = [null, null];
    }
}

// Whether a colour is a saturated red, which the flash rules count apart.
export function isRed(c) {
    const [r, g, b] = c.map((x) => (x / 255) ** 2.2);
    return r + g + b > 0 && r / (r + g + b) >= 0.8;
}

export { NODES_FLOAT, PLAYER_FLOATS, shaderMaterial };
