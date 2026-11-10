// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the retargeting of uploaded celebration clips onto GRF's nodes, run from the
// repository root with `node tests/web/retarget.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from copies beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-retarget-'));
for (const name of ['players/retarget.js', 'recording/format.js']) {
    cpSync(fileURLToPath(new URL(`../../src/cuju/render/web/js/${name}`, import.meta.url)), join(folder, name));
}
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const R = await import(pathToFileURL(join(folder, 'players/retarget.js')).href);
const { NODE_COUNT, NODE_PARENTS, PLAYER_FLOATS } = await import(pathToFileURL(join(folder, 'recording/format.js')).href);

const close = (a, b, eps = 1e-5) => Math.abs(a - b) <= eps;

// The same rotation, either sign of a quaternion.
function sameRotation(a, b, eps = 1e-5) {
    const dot = Math.abs(a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]);
    return close(dot, 1, eps);
}

function nodeRotation(nodes, n, o = 0) {
    return Array.from(nodes.subarray(o + n * 7 + 3, o + n * 7 + 7));
}

function nodePosition(nodes, n, o = 0) {
    return Array.from(nodes.subarray(o + n * 7, o + n * 7 + 3));
}

// A seeded source of numbers, so a failure repeats.
function random(seed) {
    let a = seed >>> 0;
    return () => {
        a = (a + 0x6d2b79f5) >>> 0;
        let t = a;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

function unitQuaternion(next) {
    const q = [next() - 0.5, next() - 0.5, next() - 0.5, next() - 0.5];
    const n = Math.hypot(...q);
    return q.map((v) => v / n);
}

// three.js's frame from the engine's, as players.js turns a node.
const threeRotation = (q) => [q[0], q[2], -q[1], q[3]];

// The rest pose of GRF's player by forward kinematics, positions only, rotations all identity.
function restPositions() {
    const out = [];
    for (let n = 0; n < NODE_COUNT; n++) {
        const p = NODE_PARENTS[n] < 0 ? [0, 0, 0] : out[NODE_PARENTS[n]];
        out.push(p.map((v, c) => v + R.REST_LOCAL[n][c]));
    }
    return out;
}

const identityRig = {
    corrections: Array.from({ length: NODE_COUNT }, (_, n) => (n > 0 ? [0, 0, 0, 1] : null)),
    heightRatio: 1,
    floor: 0,
};

test('a skeleton standing as GRF does gives the rest pose', () => {
    const bones = Array.from({ length: NODE_COUNT }, (_, n) => (n > 0 ? [0, 0, 0, 1] : null));
    const out = new Float32Array(PLAYER_FLOATS);
    R.nodesFromBones(bones, [0, R.REST_BODY_HEIGHT, 0], identityRig, [0, 0], out);
    const rest = restPositions();
    for (let n = 0; n < NODE_COUNT; n++) {
        assert.ok(nodePosition(out, n).every((v, c) => close(v, rest[n][c])), `position of node ${n}`);
        assert.ok(sameRotation(nodeRotation(out, n), [0, 0, 0, 1]), `rotation of node ${n}`);
    }
});

test('a node takes the bone rotation times the inverse of the correction, in the engine frame', () => {
    const next = random(7);
    for (let round = 0; round < 50; round++) {
        // The rotations GRF's nodes should end with, and corrections as a custom model has them.
        const wanted = Array.from({ length: NODE_COUNT }, () => unitQuaternion(next));
        const corrections = Array.from({ length: NODE_COUNT }, (_, n) => (n > 0 ? unitQuaternion(next) : null));
        // A custom model turns its bone by the node's rotation, in three's frame, times the
        // correction, and the clip's bone does the same.
        const bones = wanted.map((q, n) => (n > 0 ? R.multiply(threeRotation(q), corrections[n]) : null));
        const rig = { corrections, heightRatio: 1, floor: 0 };
        const out = new Float32Array(PLAYER_FLOATS);
        R.nodesFromBones(bones, [0, 1, 0], rig, [0, 0], out);
        for (let n = 1; n < NODE_COUNT; n++) {
            assert.ok(sameRotation(nodeRotation(out, n), wanted[n]), `node ${n} of round ${round}`);
        }
        // Every node below the pelvis hangs from its parent at GRF's bone length.
        for (let n = 2; n < NODE_COUNT; n++) {
            const p = NODE_PARENTS[n];
            const d = Math.hypot(...nodePosition(out, n).map((v, c) => v - nodePosition(out, p)[c]));
            assert.ok(close(d, Math.hypot(...R.REST_LOCAL[n]), 1e-5), `length of node ${n}`);
            const turned = R.rotate(nodeRotation(out, p), R.REST_LOCAL[n]);
            assert.ok(nodePosition(out, n).every((v, c) => close(v, nodePosition(out, p)[c] + turned[c], 1e-5)));
        }
    }
});

test('a node without a bone keeps its parent turn', () => {
    const turn = [Math.sin(0.4), 0, 0, Math.cos(0.4)];
    const bones = Array.from({ length: NODE_COUNT }, () => null);
    bones[1] = threeRotation(turn);
    const out = new Float32Array(PLAYER_FLOATS);
    R.nodesFromBones(bones, [0, R.REST_BODY_HEIGHT, 0], identityRig, [0, 0], out);
    for (let n = 1; n < NODE_COUNT; n++) {
        assert.ok(sameRotation(nodeRotation(out, n), turn), `node ${n}`);
    }
    assert.ok(sameRotation(nodeRotation(out, 0), [0, 0, 0, 1]));
});

test('the pelvis height follows the floor and the ratio of the heights', () => {
    const bones = Array.from({ length: NODE_COUNT }, () => null);
    const out = new Float32Array(PLAYER_FLOATS);
    // A skeleton half as tall, standing on a floor 0.1 above its origin.
    R.nodesFromBones(bones, [0.3, 0.1 + 0.48, -0.2], { ...identityRig, heightRatio: 0.5, floor: 0.1 }, [0.25, 0.5], out);
    assert.ok(close(out[7 + 2], 0.96));
    assert.deepEqual(nodePosition(out, 0), [0.25, 0.5, 0]);
    assert.ok(close(out[7], 0.25) && close(out[8], 0.5));
    // A crouch lowers the body, a jump raises it.
    R.nodesFromBones(bones, [0, 0.1 + 0.24, 0], { ...identityRig, heightRatio: 0.5, floor: 0.1 }, [0, 0], out);
    assert.ok(close(out[7 + 2], 0.48));
});

test('travel is taken out of a clip that walks, and sway stays within the limit', () => {
    // three's frame, so engine y is minus z.
    const walk = Array.from({ length: 31 }, (_, i) => [0, 1, i * 0.1]);
    for (const [x, y] of R.rootOffsets(walk)) {
        assert.ok(close(x, 0) && close(y, 0));
    }
    // A step aside and back stays as it is.
    const sway = Array.from({ length: 31 }, (_, i) => [0.2 * Math.sin((i / 30) * Math.PI), 1, 0]);
    R.rootOffsets(sway).forEach(([x, y], i) => {
        assert.ok(close(x, 0.2 * Math.sin((i / 30) * Math.PI)) && close(y, 0));
    });
    // A long run out and back is held to ROOT_LIMIT, along engine minus y for three's plus z.
    const out = Array.from({ length: 31 }, (_, i) => [0, 1, 4 * Math.sin((i / 30) * Math.PI)]);
    const offsets = R.rootOffsets(out);
    assert.ok(offsets.every(([x, y]) => Math.hypot(x, y) <= R.ROOT_LIMIT + 1e-9));
    assert.ok(close(offsets[15][1], -R.ROOT_LIMIT));
});

function sampleClip() {
    // A body that bobs and steps aside over one second, with the right arm turning.
    const samples = [];
    const count = R.FPS + 1;
    for (let i = 0; i < count; i++) {
        const u = i / (count - 1);
        const bones = Array.from({ length: NODE_COUNT }, () => null);
        bones[1] = [0, 0, 0, 1];
        const a = Math.PI * u;
        bones[6] = threeRotation([0, Math.sin(a / 2), 0, Math.cos(a / 2)]);
        samples.push({ bones, body: [0.3 * Math.sin(Math.PI * u), R.REST_BODY_HEIGHT + 0.1 * Math.sin(Math.PI * u), 0] });
    }
    return R.nodeClip(samples, identityRig, 1);
}

test('a clip of nodes loops, turns to its heading and keeps to the spot or the pitch', () => {
    const clip = sampleClip();
    assert.equal(clip.count, R.FPS + 1);
    assert.equal(clip.frames.length, clip.count * PLAYER_FLOATS);
    const a = new Float32Array(PLAYER_FLOATS);
    const b = new Float32Array(PLAYER_FLOATS);
    R.poseNodeClip(clip, 0.25, a);
    R.poseNodeClip(clip, 1.25, b);
    assert.ok(a.every((v, i) => close(v, b[i], 1e-5)), 'loops');
    // Between two samples the pose blends, at the sample it is the sample.
    R.poseNodeClip(clip, 0.5, a);
    assert.ok(a.every((v, i) => close(v, clip.frames[15 * PLAYER_FLOATS + i], 1e-5)));
    // Standing at 10, 5 and turned a quarter left, the step aside along engine x goes along y.
    R.poseNodeClip(clip, 0.5, b, 0, { x: 10, y: 5, heading: Math.PI / 2 });
    assert.ok(close(b[0], 10 - a[1], 1e-5) && close(b[1], 5 + a[0], 1e-5));
    assert.ok(close(b[7 + 2], a[7 + 2]));
    const yaw = [0, 0, Math.sin(Math.PI / 4), Math.cos(Math.PI / 4)];
    assert.ok(sameRotation(nodeRotation(b, 6), R.multiply(yaw, nodeRotation(a, 6))));
    // Pinned, the ground point stays on the spot.
    R.poseNodeClip(clip, 0.5, b, PLAYER_FLOATS * 0, { x: 3, y: 4, pin: true });
    assert.ok(close(b[0], 3) && close(b[1], 4));
    // At the touch line the step aside is held inside it.
    R.poseNodeClip(clip, 0.5, b, 0, { x: 55, y: 0, bounds: [55, 36] });
    assert.ok(b[0] <= 55 + 1e-6);
    // Written at an offset, the rest of the buffer stays as it was.
    const many = new Float32Array(3 * PLAYER_FLOATS).fill(9);
    R.poseNodeClip(clip, 0.5, many, PLAYER_FLOATS);
    assert.ok(many.subarray(0, PLAYER_FLOATS).every((v) => v === 9));
    assert.ok(many.subarray(2 * PLAYER_FLOATS).every((v) => v === 9));
});

test('loaded clips play by name until their team forgets them', () => {
    const clip = sampleClip();
    R.registerUpload('upload:victory.0 c1', clip, 'Victory');
    R.registerUpload('upload:victory.0 c2', clip, 'Other team');
    assert.ok(R.hasUpload('upload:victory.0 c1'));
    assert.equal(R.uploadLabel('upload:victory.0 c1'), 'Victory');
    assert.equal(R.uploadDuration('upload:victory.0 c1'), 1);
    assert.ok(!R.hasUpload('upload:victory.0'));
    assert.ok(!R.hasUpload(undefined));
    const out = new Float32Array(PLAYER_FLOATS);
    assert.equal(R.poseUpload('upload:victory.0 c1', 0.5, out, 0, {}), true);
    assert.equal(R.poseUpload('upload:missing.0 c1', 0.5, out, 0, {}), false);
    R.forgetUploads(' c1');
    assert.ok(!R.hasUpload('upload:victory.0 c1'));
    assert.ok(R.hasUpload('upload:victory.0 c2'));
});
