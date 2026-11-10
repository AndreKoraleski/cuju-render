// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the 2D drawing of a match, run from the repository root with
// `node tests/web/pitch2d.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { gunzipSync } from 'node:zlib';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from a copy beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-pitch2d-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/', import.meta.url)), folder, { recursive: true });
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const load = (name) => import(pathToFileURL(join(folder, name)).href);
const pitch2d = await load('watch/pitch2d.js');
const { parseRecording } = await load('recording/format.js');
const {
    FULL_HALF_H, FULL_HALF_W, HALF_H, HALF_W, HEIGHT_LIFT, ballGeometry, drawPitch, drawScene,
    inkFor, pitchTransform, playerNumber, playerRadius, sceneFromFrames, teamPaint,
} = pitch2d;

// A copy, since a Buffer slices into its shared pool where a Uint8Array copies.
const sample = (name) => new Uint8Array(gunzipSync(readFileSync(new URL(`../../src/cuju/render/samples/${name}`, import.meta.url))));

// A context that records the calls the drawing makes, enough of CanvasRenderingContext2D for it.
function recorder() {
    const calls = [];
    const ctx = new Proxy({}, {
        get: (target, key) => (key in target ? target[key] : (...args) => calls.push([key, ...args])),
        set: (target, key, value) => {
            target[key] = value;
            return true;
        },
    });
    return { ctx, calls };
}

test('the pitch fills its box, centered, with one scale either way', () => {
    const t = pitchTransform(1200, 800);
    assert.equal(t.scale, Math.min(1200 / (2 * FULL_HALF_W), 800 / (2 * FULL_HALF_H)));
    assert.deepEqual([t.x(0), t.y(0)], [600, 400]);
    // The left goal lies left of the center, the engine's positive y towards the top.
    assert.ok(t.x(-HALF_W) < t.x(0) && t.x(HALF_W) > t.x(0));
    assert.ok(t.y(HALF_H) < t.y(0) && t.y(-HALF_H) > t.y(0));
    assert.equal(t.x(HALF_W) - t.x(0), t.y(-HALF_H) - t.y(0) + (HALF_W - HALF_H) * t.scale);
    // The grass reaches the edges of the limiting side and stays inside the other.
    const wide = pitchTransform(2000, 400);
    assert.equal(wide.y(FULL_HALF_H), 0);
    assert.equal(wide.y(-FULL_HALF_H), 400);
    assert.ok(wide.x(-FULL_HALF_W) > 0 && wide.x(FULL_HALF_W) < 2000);
    // Margins move the box, the top margin pushes the pitch down.
    const framed = pitchTransform(1200, 800, { top: 100, bottom: 50, side: 20 });
    assert.equal(framed.cy, 100 + (800 - 150) / 2);
    assert.ok(framed.y(FULL_HALF_H) >= 100 - 1e-9 && framed.y(-FULL_HALF_H) <= 750 + 1e-9);
    assert.ok(framed.x(-FULL_HALF_W) >= 20 - 1e-9 && framed.x(FULL_HALF_W) <= 1180 + 1e-9);
    // A box with no room draws nothing rather than a mirrored pitch.
    assert.equal(pitchTransform(10, 10, { top: 20 }).scale, 0);
});

test('the ball rises up the picture over a shadow that stays on the ground', () => {
    const t = pitchTransform(1200, 800);
    const ground = ballGeometry(t, 10, -5, 0);
    assert.equal(ground.ball.x, t.x(10));
    assert.equal(ground.ball.y, t.y(-5));
    assert.deepEqual([ground.shadow.x, ground.shadow.y], [t.x(10), t.y(-5)]);
    const high = ballGeometry(t, 10, -5, 4);
    assert.equal(high.shadow.y, ground.shadow.y);
    assert.equal(high.ball.y, ground.ball.y - 4 * HEIGHT_LIFT * t.scale);
    assert.ok(high.ball.r > ground.ball.r && high.shadow.r < ground.shadow.r);
    // A ball below the ground or very high stays within bounds.
    assert.equal(ballGeometry(t, 0, 0, -1).height, 0);
    assert.ok(ballGeometry(t, 0, 0, 500).height <= 12);
});

test('players keep their team sides at kick-off, as the 3D view places them', async () => {
    for (const name of ['sample-5v5.cjr', 'sample-11v11.cjr']) {
        const { header, frames } = await parseRecording(sample(name));
        const t = pitchTransform(1200, 800);
        const scene = sceneFromFrames(header, frames[0]);
        assert.equal(scene.players.length, header.players.length);
        // The kickers stand on the center line, every other player in the half of the team.
        for (const p of scene.players) {
            assert.ok(p.active);
            if (Math.abs(p.x) > 1) {
                assert.equal(t.x(p.x) < t.x(0) ? 0 : 1, p.team, `${name} player ${p.slot}`);
            }
        }
        // The goalkeepers stand in front of their own goals, the left team's at the left edge.
        for (const team of [0, 1]) {
            const keeper = scene.players.find((p) => p.team === team && p.goalkeeper);
            assert.ok(Math.abs(t.x(keeper.x) - t.x(team ? HALF_W : -HALF_W)) < 2 * t.scale);
        }
        // Blending halfway lands halfway between the frames.
        const a = frames[10];
        const b = frames[11];
        const half = sceneFromFrames(header, a, b, 0.5);
        const xa = sceneFromFrames(header, a).players[3].x;
        const xb = sceneFromFrames(header, b).players[3].x;
        assert.ok(Math.abs(half.players[3].x - (xa + xb) / 2) < 1e-4);
        assert.deepEqual(half.score, [a.scoreLeft, a.scoreRight]);
        assert.equal(half.clockMs, a.timeMs);
    }
});

test('the drawing draws every active player and the ball, numbers on large discs', async () => {
    const { header, frames } = await parseRecording(sample('sample-5v5.cjr'));
    const t = pitchTransform(1200, 800);
    const scene = sceneFromFrames(header, frames[0]);
    scene.players[2].active = false;
    const paint = teamPaint(header);
    const { ctx, calls } = recorder();
    const numbers = header.players.map((p) => playerNumber(null, p));
    drawScene(ctx, t, scene, paint, { numberOf: (p) => numbers[p.slot], scoreboard: '1  0 : 0  00:00' });
    const discs = calls.filter(([name, , , r]) => name === 'arc' && Math.abs(r - playerRadius(t)) < 1e-9);
    assert.equal(discs.length, header.players.length - 1);
    const texts = calls.filter(([name]) => name === 'fillText').map(([, text]) => text);
    assert.equal(texts.length, header.players.length);
    assert.ok(texts.includes('1  0 : 0  00:00'));
    assert.ok(calls.some(([name]) => name === 'ellipse'));
    // Small discs leave the numbers out.
    const small = recorder();
    drawScene(small.ctx, pitchTransform(160, 100), scene, paint, { numberOf: (p) => numbers[p.slot] });
    assert.equal(small.calls.filter(([name]) => name === 'fillText').length, 0);
    const pitch = recorder();
    drawPitch(pitch.ctx, t);
    // The halfway line, the circle, two boxes, two goal areas, two arcs and four corners at least.
    assert.ok(pitch.calls.filter(([name]) => name === 'stroke').length >= 16);
    assert.equal(pitch.calls.filter(([name]) => name === 'strokeRect').length, 3);
});

test('team colors come from the kits, numbers from the roster', () => {
    const header = { teams: [{ color: [250, 250, 250] }, { color: [10, 10, 60], secondary: [200, 0, 0] }] };
    const plain = teamPaint(header);
    assert.equal(plain[0].fill, 'rgb(250, 250, 250)');
    assert.equal(plain[0].ink, inkFor([250, 250, 250]));
    assert.equal(plain[0].ink, '#111111');
    assert.equal(plain[1].ink, '#ffffff');
    assert.equal(plain[1].edge, 'rgb(200, 0, 0)');
    const styles = [
        { kit: { primary: [1, 2, 3], secondary: [4, 5, 6] }, goalkeeper: { primary: [7, 8, 9] }, players: [{ number: 23 }] },
        { kit: { primary: [9, 9, 9], secondary: [0, 0, 0] }, goalkeeper: { primary: [250, 250, 0] } },
    ];
    const kits = teamPaint(header, styles);
    assert.equal(kits[0].fill, 'rgb(1, 2, 3)');
    assert.equal(kits[0].keeper, 'rgb(7, 8, 9)');
    assert.equal(kits[1].keeperInk, '#111111');
    assert.equal(playerNumber(styles, { team: 0, index: 0, goalkeeper: true }), '23');
    assert.equal(playerNumber(styles, { team: 1, index: 0, goalkeeper: true }), '1');
    assert.equal(playerNumber(null, { team: 1, index: 4, goalkeeper: false }), '5');
});

test('the grid moves the focus by rows and columns and offers square sizes', async () => {
    const { GRID_SIZES, gridColumns, gridSizes, moveIndex, sceneFromTile } = await load('watch/grid.js');
    assert.deepEqual(GRID_SIZES.map(gridColumns), [2, 3, 4, 5, 6, 7, 8]);
    assert.deepEqual(gridSizes(3), [4]);
    assert.deepEqual(gridSizes(12), [4, 9, 16]);
    assert.deepEqual(gridSizes(4096), GRID_SIZES);
    // Nine tiles in rows of three, seven of them shown on the last page.
    assert.equal(moveIndex(0, 'ArrowRight', 3, 9), 1);
    assert.equal(moveIndex(2, 'ArrowRight', 3, 9), 3);
    assert.equal(moveIndex(8, 'ArrowRight', 3, 9), 8);
    assert.equal(moveIndex(0, 'ArrowLeft', 3, 9), 0);
    assert.equal(moveIndex(4, 'ArrowUp', 3, 9), 1);
    assert.equal(moveIndex(1, 'ArrowUp', 3, 9), 1);
    assert.equal(moveIndex(4, 'ArrowDown', 3, 7), 4);
    assert.equal(moveIndex(3, 'ArrowDown', 3, 7), 6);
    assert.equal(moveIndex(5, 'Home', 3, 7), 0);
    assert.equal(moveIndex(0, 'End', 3, 7), 6);
    assert.equal(moveIndex(0, 'Enter', 3, 7), -1);
    // A tile of the source draws as a scene, its players by team at their positions.
    const tile = {
        environment: 4, step: 9, score: [1, 0], clock: 61000, mode: 0, ball: [1, 2, 0.5],
        teams: [0, 1], players: [-20, 3, 30, -4], active: [1, 0],
    };
    const scene = sceneFromTile(tile);
    assert.deepEqual(scene.players.map((p) => [p.x, p.y, p.team, p.active]), [[-20, 3, 0, true], [30, -4, 1, false]]);
    assert.deepEqual([scene.score, scene.clockMs, scene.ball], [[1, 0], 61000, [1, 2, 0.5]]);
    const t = pitchTransform(320, 200);
    const { ctx, calls } = recorder();
    drawScene(ctx, t, scene, teamPaint(null), { numbers: false, scoreboard: '4   1 : 0   01:01' });
    assert.equal(calls.filter(([name, , , r]) => name === 'arc' && Math.abs(r - playerRadius(t)) < 1e-9).length, 1);
    assert.ok(calls.some(([name, text]) => name === 'fillText' && text === '4   1 : 0   01:01'));
    // A tile without a picture yet draws its strip alone, without a ball.
    const empty = recorder();
    drawScene(empty.ctx, t, { players: [], ball: null }, [], { scoreboard: '4   waiting' });
    assert.ok(!empty.calls.some(([name]) => name === 'ellipse'));
});
