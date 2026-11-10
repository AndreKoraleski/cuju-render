// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Small numeric helpers of the presentation contract, with no dependency on three.js, so Node
// tests load them as they are.

export const TAU = Math.PI * 2;

export function clamp(x, lo, hi) {
    return x < lo ? lo : x > hi ? hi : x;
}

// Moves a toward b at an exponential rate per second, the same for any step.
export function damp(a, b, rate, dt) {
    return a + (b - a) * -Math.expm1(-rate * Math.max(0, dt));
}

// An angle wrapped into minus pi to pi.
export function wrap(angle) {
    return Math.atan2(Math.sin(angle), Math.cos(angle));
}

// Moves angle a toward b along the short way, at an exponential rate and at most maxSpeed radians
// per second.
export function dampAngle(a, b, rate, dt, maxSpeed = Infinity) {
    const delta = wrap(b - a) * -Math.expm1(-rate * Math.max(0, dt));
    const limit = maxSpeed * Math.max(0, dt);
    return wrap(a + clamp(delta, -limit, limit));
}

// A piecewise linear curve of rising points, held flat past both ends.
export function curve(points, x) {
    if (!points || !points.length) {
        return 0;
    }
    if (x <= points[0][0]) {
        return points[0][1];
    }
    for (let i = 1; i < points.length; i++) {
        const [x1, y1] = points[i];
        if (x <= x1) {
            const [x0, y0] = points[i - 1];
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0);
        }
    }
    return points[points.length - 1][1];
}

// A curve of the contract, a plain number, or the value of one input of the entity read through
// rising keys, held flat past both ends, or a sum of curves. An input the entity lacks reads 0.
export function evaluate(value, inputs) {
    if (typeof value === 'number') {
        return value;
    }
    if (!value || typeof value !== 'object') {
        return 0;
    }
    if (Array.isArray(value.sum)) {
        return value.sum.reduce((total, part) => total + evaluate(part, inputs), 0);
    }
    const x = Number(inputs && inputs[value.input]) || 0;
    return value.keys ? curve(value.keys, x) : x;
}

// A 32 bit hash of a string, FNV-1a, for seeds that stay the same on every machine.
export function hash(text) {
    let h = 0x811c9dc5;
    const s = String(text);
    for (let i = 0; i < s.length; i++) {
        h = Math.imul(h ^ s.charCodeAt(i), 16777619);
    }
    return h >>> 0;
}

// A number from 0 to 1 that a seed and a name always give.
export function unit(seed, name = '') {
    let x = hash(`${seed}:${name}`);
    x = Math.imul(x ^ (x >>> 16), 0x45d9f3b);
    x = Math.imul(x ^ (x >>> 16), 0x45d9f3b);
    return ((x ^ (x >>> 16)) >>> 0) / 4294967296;
}
