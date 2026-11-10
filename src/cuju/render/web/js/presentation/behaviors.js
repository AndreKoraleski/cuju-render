// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Persistent behaviours, section 7.5 of the contract. A package declares them once, in its
// manifest or from its worker, and the renderer evaluates them on the rendering thread every
// drawing against the entity's current anchors, so a late or skipped worker reply never causes a
// hold or a jump.
//
// Spins and oscillators integrate their phase, so a change of rate changes how fast they turn and
// never where they are. A spin may integrate over cosmetic time, over the distance the player
// covered, which seeks reproduce exactly, or both. A new epoch keeps every phase and restarts the
// estimates read from the simulation, the springs, gaze and banking. Under reduced motion the
// amplitudes of oscillators, springs and banking scale by the package's reducedMotion amplitude.

import { TAU, clamp, damp, dampAngle, evaluate, unit, wrap } from './values.js';

export const TYPES = ['spin', 'oscillate', 'spring', 'lookAt', 'bank', 'follow', 'curve', 'materialParam', 'audioParam', 'lightParam'];
export const CHANNELS = ['x', 'y', 'z', 'rotX', 'rotY', 'rotZ', 'scale'];
export const INPUTS = ['speed', 'accel', 'ballDistance', 'excitement', 'ceremony.amount', 'ballX.attack', 'alert'];
export const LOOK_TARGETS = ['ball', 'subject', 'camera'];
const ID = /^[A-Za-z0-9_.-]{1,40}$/;
const FADE = 0.3;

function checkCurve(value) {
    if (typeof value === 'number') {
        if (!Number.isFinite(value)) {
            throw new Error('expected a finite number');
        }
        return clamp(value, -1e4, 1e4);
    }
    if (!value || typeof value !== 'object') {
        throw new Error('expected a number or a curve of an input');
    }
    if (Array.isArray(value.sum)) {
        return { sum: value.sum.slice(0, 8).map(checkCurve) };
    }
    const input = String(value.input || '');
    if (!INPUTS.includes(input) && !/^jointSpeed:.{1,80}$/.test(input) && !/^role:[a-z.]{1,40}$/.test(input)) {
        throw new Error(`expected a known input, found ${input}`);
    }
    const out = { input };
    if (value.keys != null) {
        if (!Array.isArray(value.keys) || value.keys.length < 1 || value.keys.length > 32) {
            throw new Error('expected one to thirty two keys');
        }
        out.keys = value.keys.map((k) => [Number(k[0]) || 0, Number(k[1]) || 0]).sort((a, b) => a[0] - b[0]);
    }
    return out;
}

const vector = (v, d) => (Array.isArray(v) && v.length === 3 && v.every(Number.isFinite) && Math.hypot(...v) > 1e-9 ? v.slice() : d);
const num = (x, lo, hi, d) => (x != null && Number.isFinite(Number(x)) ? clamp(Number(x), lo, hi) : d);

// A behaviour as a manifest or a worker gives it, checked and filled. Throws for an unknown type
// or a malformed part. id names it for later updates, when picks the players it applies to.
export function checkBehaviour(spec, index = 0) {
    if (!spec || typeof spec !== 'object' || !TYPES.includes(spec.type)) {
        throw new Error('expected a behaviour of a known type');
    }
    const id = spec.id == null ? `${spec.type}${index}` : String(spec.id);
    if (!ID.test(id)) {
        throw new Error('expected an id of letters, digits, dots, dashes and underscores');
    }
    const out = { id, type: spec.type, weight: checkCurve(spec.weight ?? 1) };
    if (spec.when) {
        out.when = spec.when;
    }
    if (spec.node != null) {
        out.node = String(spec.node).slice(0, 80);
    }
    if (spec.attachment != null) {
        out.attachment = String(spec.attachment).slice(0, 40);
    }
    out.seed = ['number', 'index'].includes(spec.seed) ? spec.seed : num(spec.seed, 0, 2 ** 31, 'entity');
    const channel = () => {
        const c = spec.channel || 'y';
        if (!CHANNELS.includes(c)) {
            throw new Error(`expected a channel among ${CHANNELS.join(', ')}`);
        }
        return c;
    };
    switch (spec.type) {
    case 'spin':
        out.axis = vector(spec.axis, [0, 1, 0]);
        out.rate = checkCurve(spec.rate ?? 1);
        out.phaseFrom = ['cosmetic', 'distance', 'both'].includes(spec.phaseFrom) ? spec.phaseFrom : 'cosmetic';
        out.perMetre = num(spec.perMetre, -100, 100, 0);
        if (spec.clip != null) {
            out.clip = String(spec.clip).slice(0, 80);
            out.period = num(spec.period, 0.001, 1e6, null);
        } else if (out.node == null && out.attachment == null) {
            throw new Error('expected the node, the attachment or the clip a spin turns');
        }
        break;
    case 'oscillate':
        out.channel = channel();
        out.amp = checkCurve(spec.amp ?? 0);
        out.freq = checkCurve(spec.freq ?? 1);
        out.offset = checkCurve(spec.offset ?? 0);
        break;
    case 'spring':
        out.channel = channel();
        out.goal = checkCurve(spec.goal ?? 0);
        out.stiffness = num(spec.stiffness, 0.1, 1e4, 40);
        out.damping = num(spec.damping, 0, 1e3, 12);
        out.mass = num(spec.mass, 0.01, 100, 1);
        out.limit = num(spec.limit, 0, 100, 10);
        break;
    case 'lookAt':
        if (out.node == null) {
            throw new Error('expected the node that looks');
        }
        out.target = LOOK_TARGETS.includes(spec.target) || /^p\d+$/.test(String(spec.target)) ? spec.target : 'ball';
        out.rate = num(spec.rate, 0.1, 100, 12);
        out.slew = num(spec.slew, 0.1, 100, 10);
        out.pitchLimit = num(spec.pitchLimit, 0, 1.6, 0.8);
        out.yawLimit = num(spec.yawLimit, 0, Math.PI, Math.PI);
        out.descendants = !!spec.descendants;
        out.forward = vector(spec.forward, null);
        break;
    case 'bank':
        out.gain = checkCurve(spec.gain ?? 0.01);
        out.limit = num(spec.limit, 0, 1.6, 0.3);
        out.rate = num(spec.rate, 0.1, 100, 6);
        break;
    case 'follow':
        if (out.node == null) {
            throw new Error('expected the node that follows');
        }
        out.target = LOOK_TARGETS.includes(spec.target) ? spec.target : 'ball';
        out.smoothing = num(spec.smoothing, 0.01, 100, 4);
        out.limit = num(spec.limit, 0, 10, 0.5);
        break;
    case 'curve': {
        out.channel = channel();
        const keys = Array.isArray(spec.keys) ? spec.keys.slice(0, 64) : [];
        if (keys.length < 2) {
            throw new Error('expected two keys or more');
        }
        out.keys = keys.map((k) => [Number(k[0]) || 0, Number(k[1]) || 0]).sort((a, b) => a[0] - b[0]);
        out.clock = ['sim', 'cosmetic', 'ceremony'].includes(spec.clock) ? spec.clock : 'cosmetic';
        out.loop = spec.loop !== false;
        break;
    }
    case 'materialParam':
        out.material = String(spec.material || '*').slice(0, 80);
        out.uniform = String(spec.uniform || '').slice(0, 80);
        if (!out.uniform) {
            throw new Error('expected the uniform a material parameter drives');
        }
        out.value = checkCurve(spec.value ?? 0);
        break;
    case 'lightParam':
        out.light = String(spec.light || '').slice(0, 40);
        out.param = ['intensity', 'distance'].includes(spec.param) ? spec.param : 'intensity';
        if (!out.light) {
            throw new Error('expected the light a light parameter drives');
        }
        out.value = checkCurve(spec.value ?? 0);
        break;
    case 'audioParam':
        out.processor = String(spec.processor || '').slice(0, 80);
        out.param = String(spec.param || '').slice(0, 80);
        if (!out.processor || !out.param) {
            throw new Error('expected the processor and the parameter an audio parameter drives');
        }
        out.value = checkCurve(spec.value ?? 0);
        break;
    default:
        break;
    }
    return out;
}

// The outputs of one entity's behaviours for one drawing, summed by channel.
export function emptyOutputs() {
    return {
        root: { x: 0, y: 0, z: 0, rotX: 0, rotY: 0, rotZ: 0, scale: 0 },
        nodes: new Map(),
        clipTime: new Map(),
        looks: [],
        follows: [],
        materials: [],
        audio: [],
        attachments: new Map(),
        lights: [],
    };
}

function nodeOut(out, node) {
    let entry = out.nodes.get(node);
    if (!entry) {
        entry = { x: 0, y: 0, z: 0, rotX: 0, rotY: 0, rotZ: 0, scale: 0, spins: [] };
        out.nodes.set(node, entry);
    }
    return entry;
}

function write(out, node, channel, value, attachment = null) {
    (attachment != null ? attachmentOut(out, attachment) : node == null ? out.root : nodeOut(out, node))[channel] += value;
}

// The offset of an attachment in its socket frame, which the channel behaviours naming it move.
function attachmentOut(out, name) {
    let entry = out.attachments.get(name);
    if (!entry) {
        entry = { x: 0, y: 0, z: 0, rotX: 0, rotY: 0, rotZ: 0, scale: 0, spins: [] };
        out.attachments.set(name, entry);
    }
    return entry;
}

// The behaviours of one entity, those of its package and those its worker set, each with its
// state. seeds holds the entity's seeds, entity, number and index.
export class BehaviourSet {
    constructor(seeds = {}) {
        this.seeds = { entity: 0, number: 0, index: 0, ...seeds };
        this.items = new Map();
    }

    seedOf(spec) {
        return typeof spec.seed === 'number' ? spec.seed : this.seeds[spec.seed] || 0;
    }

    // Sets a behaviour, or replaces the description of a running one of the same id, which keeps
    // its state, so its phase goes on. source is manifest or worker.
    set(spec, source = 'manifest') {
        const old = this.items.get(spec.id);
        if (old) {
            old.spec = spec;
            old.source = source;
            old.stopping = false;
            return old;
        }
        const s = this.seedOf(spec);
        // Spins and oscillators of different entities start at phases their seeds give.
        const phase = spec.type === 'oscillate' ? unit(s, spec.id) * TAU
            : spec.type === 'spin' ? unit(s, spec.id) * (spec.clip ? (spec.period || 1) : TAU) : 0;
        const item = { spec, source, state: { phase, value: 0, velocity: 0, yaw: 0, pitch: 0, roll: 0, pos: null, ready: false }, fade: 0, stopping: false, fadeOut: FADE };
        this.items.set(spec.id, item);
        return item;
    }

    // Merges new parts into a running behaviour.
    update(id, patch) {
        const item = this.items.get(id);
        if (!item) {
            return false;
        }
        try {
            item.spec = checkBehaviour({ ...item.spec, ...patch, id, type: item.spec.type });
        } catch {
            return false;
        }
        return true;
    }

    stop(id, fadeOut = FADE) {
        const item = this.items.get(id);
        if (item) {
            item.stopping = true;
            item.fadeOut = Math.max(1e-3, fadeOut);
        }
    }

    // Fades out every behaviour a source set, as a worker that failed hands its part back.
    stopSource(source, fadeOut = 0.5) {
        for (const [id, item] of this.items) {
            if (item.source === source) {
                this.stop(id, fadeOut);
            }
        }
    }

    // A new epoch keeps phases and restarts the estimates of the simulation.
    reset() {
        for (const item of this.items.values()) {
            item.state.ready = false;
            item.state.velocity = 0;
        }
    }

    // Evaluates every behaviour for one drawing. ctx holds dt, the cosmetic step, distance, the
    // metres covered since the last drawing, negative in reverse, inputs by name, velocity,
    // {forward, lateral} in metres per second, looks, a function from a target name to its yaw
    // and pitch relative to the facing or null, follow, a function from a target name to its
    // offset from the entity in the root frame or null, clocks, a Clocks, and reducedMotion, the
    // amplitude factor while the viewer asks for reduced motion or 1.
    evaluate(ctx, out = emptyOutputs()) {
        const dt = Math.max(0, ctx.dt || 0);
        const calm = ctx.reducedMotion == null ? 1 : ctx.reducedMotion;
        for (const [id, item] of this.items) {
            const want = item.stopping ? 0 : 1;
            const rate = want > item.fade ? 1 / FADE : 1 / (item.stopping ? item.fadeOut : FADE);
            item.fade = want > item.fade ? Math.min(want, item.fade + rate * dt) : Math.max(want, item.fade - rate * dt);
            if (item.stopping && item.fade <= 0) {
                this.items.delete(id);
                continue;
            }
            const weight = clamp(evaluate(item.spec.weight, ctx.inputs), 0, 1) * item.fade;
            this.step(item, ctx, dt, out, weight, calm);
        }
        return out;
    }

    step(item, ctx, dt, out, weight, calm) {
        const spec = item.spec;
        const s = item.state;
        const inputs = ctx.inputs || {};
        switch (spec.type) {
        case 'spin': {
            const rate = evaluate(spec.rate, inputs);
            const covered = ctx.distance || 0;
            if (spec.phaseFrom === 'distance') {
                s.phase += rate * covered;
            } else {
                s.phase += rate * dt + (spec.phaseFrom === 'both' ? spec.perMetre * covered : 0);
            }
            if (spec.clip) {
                const period = spec.period || 0;
                if (period > 0) {
                    s.phase = ((s.phase % period) + period) % period;
                }
                // A clip's time is no amount to fade, a faded spin leaves the clip to its role.
                if (weight > 0) {
                    out.clipTime.set(spec.clip, s.phase);
                }
            } else {
                s.phase %= TAU * 1e6;
                (spec.attachment != null ? attachmentOut(out, spec.attachment) : nodeOut(out, spec.node)).spins.push({ axis: spec.axis, angle: s.phase * weight });
            }
            break;
        }
        case 'oscillate': {
            s.phase = (s.phase + TAU * evaluate(spec.freq, inputs) * dt) % (TAU * 1e6);
            const v = evaluate(spec.offset, inputs) + evaluate(spec.amp, inputs) * calm * Math.sin(s.phase);
            write(out, spec.node, spec.channel, v * weight, spec.attachment);
            break;
        }
        case 'bank': {
            const v = ctx.velocity || { forward: 0, lateral: 0 };
            const gain = evaluate(spec.gain, inputs) * calm;
            const roll = clamp(-gain * v.lateral, -spec.limit, spec.limit);
            const pitch = clamp(gain * v.forward, -spec.limit, spec.limit);
            if (!s.ready) {
                s.roll = roll;
                s.pitch = pitch;
                s.ready = true;
            }
            s.roll = damp(s.roll, roll, spec.rate, dt);
            s.pitch = damp(s.pitch, pitch, spec.rate, dt);
            write(out, spec.node, 'rotZ', s.roll * weight);
            write(out, spec.node, 'rotX', s.pitch * weight);
            break;
        }
        case 'lookAt': {
            const look = ctx.looks ? ctx.looks(spec.target) : null;
            const yaw = look ? clamp(look.yaw, -spec.yawLimit, spec.yawLimit) : 0;
            const pitch = look ? clamp(look.pitch, -spec.pitchLimit, spec.pitchLimit) : 0;
            if (!s.ready) {
                s.yaw = yaw;
                s.pitch = pitch;
                s.ready = true;
            }
            s.yaw = dampAngle(s.yaw, yaw, spec.rate, dt, spec.slew);
            s.pitch = dampAngle(s.pitch, pitch, spec.rate, dt, spec.slew);
            out.looks.push({ node: spec.node, yaw: s.yaw, pitch: s.pitch, weight: look ? weight : 0, descendants: spec.descendants, forward: spec.forward });
            break;
        }
        case 'follow': {
            const goal = ctx.follow ? ctx.follow(spec.target) : null;
            const target = goal ? goal.map((c) => clamp(c, -spec.limit, spec.limit)) : [0, 0, 0];
            if (!s.ready || !s.pos) {
                s.pos = target.slice();
                s.ready = true;
            }
            for (let i = 0; i < 3; i++) {
                s.pos[i] = damp(s.pos[i], target[i], spec.smoothing, dt);
            }
            out.follows.push({ node: spec.node, offset: s.pos.map((c) => c * weight) });
            break;
        }
        case 'spring': {
            const goal = evaluate(spec.goal, inputs);
            if (!s.ready) {
                s.value = goal;
                s.velocity = 0;
                s.ready = true;
            }
            // Semi implicit Euler in steps of at most 10 ms keeps a stiff spring stable.
            for (let left = dt; left > 1e-9; left -= 0.01) {
                const h = Math.min(0.01, left);
                s.velocity += ((spec.stiffness * (goal - s.value) - spec.damping * s.velocity) / spec.mass) * h;
                s.value += s.velocity * h;
            }
            s.value = clamp(s.value, -spec.limit, spec.limit);
            write(out, spec.node, spec.channel, s.value * weight * calm, spec.attachment);
            break;
        }
        case 'curve': {
            const keys = spec.keys;
            const first = keys[0][0];
            const last = keys[keys.length - 1][0];
            let t = ctx.clocks ? ctx.clocks.read(spec.clock) : 0;
            if (spec.loop && last > first) {
                t = first + ((((t - first) % (last - first)) + (last - first)) % (last - first));
            }
            write(out, spec.node, spec.channel, curveAt(keys, t) * weight, spec.attachment);
            break;
        }
        case 'materialParam':
            out.materials.push({ material: spec.material, uniform: spec.uniform, value: evaluate(spec.value, inputs), weight, attachment: spec.attachment || null });
            break;
        case 'lightParam':
            out.lights.push({ light: spec.light, param: spec.param, value: evaluate(spec.value, inputs), weight });
            break;
        case 'audioParam':
            out.audio.push({ processor: spec.processor, param: spec.param, value: evaluate(spec.value, inputs), weight });
            break;
        default:
            break;
        }
    }
}

function curveAt(keys, t) {
    if (t <= keys[0][0]) {
        return keys[0][1];
    }
    for (let i = 1; i < keys.length; i++) {
        if (t <= keys[i][0]) {
            const [t0, v0] = keys[i - 1];
            const [t1, v1] = keys[i];
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0);
        }
    }
    return keys[keys.length - 1][1];
}

export { wrap };
