// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The reach of a figure and the drawn ball, sections 5.3 and 7.2 of the contract, with the checks
// of the geometry a worker builds. The parts here are plain arithmetic with no three.js, so Node
// tests load them as they are.
//
// bend.ball bends the drawn path of the ball through the estimated contact of each touch. The
// renderer draws the ball as straight segments between the samples of the frames, and the engine
// flags the step whose interval holds the contact, so the drawn ball passes the contact point at
// the contact time, and the foot, the ball and the sound meet. It changes the drawing alone.
//
// ik.fabrik reaches a chain of bones toward the drawn ball over a short window around the
// contact of an action, by FABRIK, forward and backward passes that keep each bone's length. The
// rig adapts to the ball, the ball never moves to the rig.
//
// geometry.worker buffers come from the sandbox as plain arrays or typed arrays, checked here for
// their lengths, values and bounds, and counted.

export const MAX_VERTICES = 65536;
export const MAX_EXTENT = 100;

// The drawn ball between samples pb and pc of an interval, at the share w of it, bent through the
// contact point at the share u. Points are arrays of three numbers. Returns a new point.
export function bendBall(pb, pc, point, u, w) {
    if (!(u > 0 && u < 1)) {
        return [0, 1, 2].map((i) => pb[i] + (pc[i] - pb[i]) * w);
    }
    if (w <= u) {
        const k = w / u;
        return [0, 1, 2].map((i) => pb[i] + (point[i] - pb[i]) * k);
    }
    const k = (w - u) / (1 - u);
    return [0, 1, 2].map((i) => point[i] + (pc[i] - point[i]) * k);
}

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const len = (a) => Math.hypot(a[0], a[1], a[2]);
const along = (from, to, d) => {
    const v = sub(to, from);
    const l = len(v) || 1;
    return [from[0] + (v[0] / l) * d, from[1] + (v[1] / l) * d, from[2] + (v[2] / l) * d];
};

// FABRIK on the joints of a chain, each an array of three numbers from the root to the tip, toward
// a target. The root stays where it is and every bone keeps its length. A target out of reach
// stretches the chain straight toward it. Returns new joints.
export function fabrik(joints, target, iterations = 8, tolerance = 1e-3) {
    const n = joints.length;
    const lengths = [];
    for (let i = 0; i < n - 1; i++) {
        lengths.push(len(sub(joints[i + 1], joints[i])));
    }
    const total = lengths.reduce((a, b) => a + b, 0);
    const root = joints[0].slice();
    const out = joints.map((j) => j.slice());
    if (len(sub(target, root)) >= total) {
        for (let i = 1; i < n; i++) {
            out[i] = along(out[i - 1], target, lengths[i - 1]);
        }
        return out;
    }
    for (let k = 0; k < iterations; k++) {
        out[n - 1] = target.slice();
        for (let i = n - 2; i >= 0; i--) {
            out[i] = along(out[i + 1], out[i], lengths[i]);
        }
        out[0] = root.slice();
        for (let i = 1; i < n; i++) {
            out[i] = along(out[i - 1], out[i], lengths[i - 1]);
        }
        if (len(sub(out[n - 1], target)) < tolerance) {
            break;
        }
    }
    return out;
}

// The weight of a reach at simulation time sim, for an action whose contact is at contactT, over
// a window of seconds before and after it, a smooth rise and fall.
export function reachWeight(sim, contactT, window) {
    if (!(window > 0)) {
        return 0;
    }
    const x = Math.abs(sim - contactT) / window;
    if (x >= 1) {
        return 0;
    }
    const u = 1 - x;
    return u * u * (3 - 2 * u);
}

function numbers(value, name, size, maximum) {
    const array = ArrayBuffer.isView(value) ? value : Array.isArray(value) ? Float32Array.from(value) : null;
    if (!array || array.length % size !== 0 || array.length / size > maximum) {
        throw new Error(`expected ${name} as groups of ${size} numbers, at most ${maximum} of them`);
    }
    const out = Float32Array.from(array);
    for (const x of out) {
        if (!Number.isFinite(x)) {
            throw new Error(`expected finite ${name}`);
        }
    }
    return out;
}

// Checks one geometry a worker sends and returns it with typed arrays and its cost, or throws.
// positions, normals, uvs and colors are numbers in groups of 3, 3, 2 and 3 or 4, indices whole
// numbers inside the vertex count.
export function checkGeometry(c) {
    if (!c || typeof c !== 'object' || !/^[A-Za-z0-9_.:-]{1,80}$/.test(String(c.id || ''))) {
        throw new Error('expected a geometry with an id');
    }
    const positions = numbers(c.positions, 'positions', 3, MAX_VERTICES);
    const count = positions.length / 3;
    if (!count) {
        throw new Error('expected at least one vertex');
    }
    for (const x of positions) {
        if (Math.abs(x) > MAX_EXTENT) {
            throw new Error(`expected positions within ${MAX_EXTENT} metres`);
        }
    }
    const out = { id: String(c.id), positions, count };
    for (const [name, size] of [['normals', 3], ['uvs', 2]]) {
        if (c[name] != null) {
            out[name] = numbers(c[name], name, size, MAX_VERTICES);
            if (out[name].length / size !== count) {
                throw new Error(`expected ${name} for every vertex`);
            }
        }
    }
    if (c.colors != null) {
        const size = c.colors.length === count * 4 ? 4 : 3;
        out.colors = numbers(c.colors, 'colors', size, MAX_VERTICES);
        out.colorSize = size;
        if (out.colors.length / size !== count) {
            throw new Error('expected colors for every vertex');
        }
    }
    if (c.indices != null) {
        const source = ArrayBuffer.isView(c.indices) || Array.isArray(c.indices) ? c.indices : null;
        if (!source || source.length % 3 !== 0 || source.length > MAX_VERTICES * 6) {
            throw new Error('expected indices in triangles');
        }
        const indices = count > 65535 ? Uint32Array.from(source) : Uint16Array.from(source);
        for (let i = 0; i < source.length; i++) {
            if (!(Number.isInteger(source[i]) && source[i] >= 0 && source[i] < count)) {
                throw new Error('expected indices of the vertices');
            }
        }
        out.indices = indices;
    }
    out.triangles = out.indices ? out.indices.length / 3 : Math.floor(count / 3);
    out.bytes = positions.byteLength + (out.normals ? out.normals.byteLength : 0) + (out.uvs ? out.uvs.byteLength : 0)
        + (out.colors ? out.colors.byteLength : 0) + (out.indices ? out.indices.byteLength : 0);
    return out;
}
