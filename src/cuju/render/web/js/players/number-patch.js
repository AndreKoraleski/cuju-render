// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Where a shirt number sits on the back of a player model other than GRF's, measured from the
// torso of the model in GRF's rest pose. GRF's player wears its number on the back of the shirt,
// and the other models wear it there too, as a flat patch against the back, wherever the torso
// is wide and tall enough to hold one.

// The fewest torso vertices, and the narrowest and shortest torso in meters, that hold a number.
const MIN_POINTS = 12;
const MIN_WIDTH = 0.12;
const MIN_HEIGHT = 0.1;
// The side of the number's square, a share of the torso's width and height, between the bounds
// in meters. GRF's simple figure draws its number 0.17 meters wide.
const WIDTH_SHARE = 0.6;
const HEIGHT_SHARE = 0.55;
const MIN_SIZE = 0.08;
const MAX_SIZE = 0.26;
// How far up the torso the middle of the number sits, from its lowest point to its highest.
const HEIGHT_AT = 0.62;
// How far behind the back the patch floats, so the torso never covers it, in meters.
const LIFT = 0.006;

// The patch of a number on the back of a torso, from the torso's vertices in GRF's rest pose in
// three's frame, meters with the player facing plus z, so the back faces minus z. Points is a flat
// array of x, y and z. Returns the middle of the patch and the side of its square, or null when
// the torso is too small to hold a number.
export function backPatch(points) {
    const count = Math.floor(points.length / 3);
    if (count < MIN_POINTS) {
        return null;
    }
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (let i = 0; i < count; i++) {
        const x = points[3 * i], y = points[3 * i + 1];
        x0 = Math.min(x0, x);
        x1 = Math.max(x1, x);
        y0 = Math.min(y0, y);
        y1 = Math.max(y1, y);
    }
    const width = x1 - x0;
    const height = y1 - y0;
    if (!(width >= MIN_WIDTH && height >= MIN_HEIGHT)) {
        return null;
    }
    const size = Math.min(MAX_SIZE, WIDTH_SHARE * width, HEIGHT_SHARE * height);
    if (size < MIN_SIZE) {
        return null;
    }
    const x = (x0 + x1) / 2;
    const y = Math.min(y0 + HEIGHT_AT * height, y1 - size / 2);
    // The back under the patch alone decides its depth, so a hump lower down leaves it in place.
    let back = Infinity;
    for (let i = 0; i < count; i++) {
        if (Math.abs(points[3 * i] - x) <= size / 2 && Math.abs(points[3 * i + 1] - y) <= size / 2) {
            back = Math.min(back, points[3 * i + 2]);
        }
    }
    if (!Number.isFinite(back)) {
        return null;
    }
    return { x, y, z: back - LIFT, size };
}

// The corners of number n's cell in the atlas of numbers, 10 by 10 cells whose first row holds
// 0 to 9 at the top of the texture, as u0, v0, u1 and v1. A number outside 0 to 99 is clamped.
export function numberCell(n) {
    const k = Math.min(99, Math.max(0, Math.round(Number(n)) || 0));
    const col = k % 10;
    const row = Math.floor(k / 10);
    return [col / 10, (9 - row) / 10, (col + 1) / 10, (10 - row) / 10];
}

// Whether a team shows shirt numbers on a model, every model but GRF's, which paints its own,
// unless the team's style lists the model among hidden_numbers.
export function numbersShown(style, model) {
    if (!model || model === 'grf') {
        return false;
    }
    const hidden = style && Array.isArray(style.hidden_numbers) ? style.hidden_numbers : [];
    return !hidden.includes(model);
}
