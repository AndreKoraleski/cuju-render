// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the framing of the automatic cameras at every shape of picture, run from the
// repository root with `node tests/web/framing.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const folder = mkdtempSync(join(tmpdir(), 'cuju-framing-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/world/framing.js', import.meta.url)), join(folder, 'world/framing.js'));
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const framing = await import(pathToFileURL(join(folder, 'world/framing.js')).href);

// The half sizes of the ground that the tactical camera keeps in the picture, as pitch.js has
// them, and the half length and width of the pitch inside the lines.
const FULL_HALF_W = 60;
const FULL_HALF_H = 40;
const HALF_W = 55;
const HALF_H = 36;
const ASPECTS = { wide: 21 / 9, hd: 16 / 9, tv: 4 / 3, square: 1, portrait: 4 / 5, tall: 9 / 16 };

test('a picture as wide as 16 by 9 or wider keeps every field of view exactly', () => {
    for (const fov of [26, 30, 34, 40, 46, 60]) {
        assert.equal(framing.aspectFov(fov, 16 / 9), fov);
        assert.equal(framing.aspectFov(fov, 21 / 9), fov);
        assert.equal(framing.aspectFov(fov, 32 / 9), fov);
    }
    assert.equal(framing.leadScale(16 / 9), 1);
    assert.equal(framing.trackRate(21 / 9), 1);
    assert.equal(framing.narrowShare(16 / 9), 0);
    assert.equal(framing.aspectFov(30, 0), 30);
    assert.equal(framing.aspectFov(30, Number.NaN), 30);
});

test('a narrower picture widens the field of view steadily, up to the clamp', () => {
    for (const fov of [30, 46]) {
        let last = fov;
        for (const aspect of [16 / 9, 4 / 3, 1, 4 / 5, 9 / 16, 0.4]) {
            const wide = framing.aspectFov(fov, aspect);
            assert.ok(wide >= last - 1e-12, `${fov} at ${aspect}`);
            assert.ok(wide <= Math.max(fov, framing.MAX_FOV) + 1e-9, `${fov} at ${aspect}`);
            last = wide;
        }
    }
    // At 9 by 16 the vertical view takes the horizontal view of 16 by 9.
    const across = (fov) => 2 * Math.atan(Math.tan((fov * Math.PI) / 360) * (16 / 9)) * (180 / Math.PI);
    assert.ok(Math.abs(framing.aspectFov(30, 9 / 16) - across(30)) < 1e-9);
    assert.ok(framing.leadScale(9 / 16) < framing.leadScale(1) && framing.leadScale(1) < 1);
    assert.ok(framing.trackRate(9 / 16) > 1);
    assert.equal(framing.narrowShare(9 / 16), 1);
    assert.ok(framing.narrowShare(1) > 0 && framing.narrowShare(1) < 1);
});

// The broadcast camera as framedUpdate places it for a target on the ground, without its zoom.
function broadcast(tx, tz, aspect) {
    const x = Math.max(-HALF_W + 4, Math.min(HALF_W - 4, tx));
    const z = Math.max(-26, Math.min(26, tz));
    const tall = framing.narrowShare(aspect);
    return { pos: { x: x * 0.8, y: 20 + tall * 3, z: 63 - tall * 6 }, target: { x, y: 0, z: z * 0.75 }, fov: 26 - Math.max(0, Math.abs(x) - 30) * 0.08 };
}

test('the broadcast camera keeps the ball inside the picture at every shape, with its lead', () => {
    for (const [name, aspect] of Object.entries(ASPECTS)) {
        const share = framing.leadScale(aspect);
        for (let bx = -50; bx <= 50; bx += 10) {
            for (let bz = -30; bz <= 30; bz += 10) {
                for (const [lx, lz] of [[0, 0], [9, 0], [-9, 0], [6, 6], [-6, -6]]) {
                    const cam = broadcast(bx + lx * share, bz + lz * share, aspect);
                    const fov = framing.aspectFov(cam.fov, aspect);
                    const ball = { x: bx, y: 0.11, z: -bz };
                    // The engine's y is the picture's minus z, so the ball lies at minus bz.
                    const seen = framing.inFrame(cam.pos, { ...cam.target, z: -cam.target.z }, fov, aspect, ball, 0.08);
                    assert.ok(seen, `${name} ball ${bx}, ${bz} lead ${lx}, ${lz}`);
                }
            }
        }
    }
});

// The tactical camera as framedUpdate places it, its height fitting the ground to the picture.
function tactical(aspect, bx) {
    const halfFov = (17 * Math.PI) / 180;
    const wide = Math.max(0.5, aspect);
    const need = Math.max((FULL_HALF_W + 2) / wide, FULL_HALF_H + 2);
    const height = need / Math.tan(halfFov);
    const room = Math.max(0, need * wide - FULL_HALF_W - 2);
    const drift = Math.max(-room, Math.min(room, bx * 0.15));
    return { pos: { x: drift, y: height, z: 6 }, target: { x: drift, y: 0, z: 0 }, fov: 34 };
}

test('the tactical camera keeps the whole pitch in the picture at every shape', () => {
    for (const [name, aspect] of Object.entries(ASPECTS)) {
        for (const bx of [-50, 0, 50]) {
            const cam = tactical(aspect, bx);
            for (const x of [-HALF_W, HALF_W]) {
                for (const z of [-HALF_H, HALF_H]) {
                    assert.ok(framing.inFrame(cam.pos, cam.target, cam.fov, aspect, { x, y: 0, z }), `${name} ball ${bx} corner ${x}, ${z}`);
                }
            }
        }
    }
});

test('a turn between two points keeps the distance and height of the target', () => {
    const pos = { x: 0, y: 5, z: 0 };
    const target = { x: 10, y: 1, z: 0 };
    const out = framing.turnBetween(pos, { ...target }, { x: 10, y: 0, z: 0 }, { x: 0, y: 0, z: 10 }, 1);
    assert.ok(Math.abs(Math.hypot(out.x, out.z) - 10) < 1e-9);
    assert.equal(out.y, 1);
    assert.ok(Math.abs(out.x - out.z) < 1e-9);
    assert.deepEqual(framing.turnBetween(pos, { ...target }, target, target, 0), target);
    assert.equal(framing.project(pos, pos, 30, 1, target), null);
    const ahead = framing.project({ x: 0, y: 0, z: 10 }, { x: 0, y: 0, z: 0 }, 30, 16 / 9, { x: 0, y: 0, z: 0 });
    assert.ok(Math.abs(ahead.x) < 1e-12 && Math.abs(ahead.y) < 1e-12 && Math.abs(ahead.depth - 10) < 1e-12);
});
