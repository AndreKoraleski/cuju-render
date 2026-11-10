// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the shirt numbers on the backs of models other than GRF's, run from the repository
// root with `node tests/web/numbers.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from copies beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-numbers-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/players/number-patch.js', import.meta.url)), join(folder, 'players/number-patch.js'));
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const { backPatch, numberCell, numbersShown } = await import(pathToFileURL(join(folder, 'players/number-patch.js')).href);

// The vertices of a box torso, from x0 to x1 wide, y0 to y1 tall and z0 to z1 deep, on a grid.
function box(x0, x1, y0, y1, z0, z1, steps = 6) {
    const points = [];
    for (let i = 0; i <= steps; i++) {
        for (let j = 0; j <= steps; j++) {
            for (const z of [z0, z1]) {
                points.push(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * j / steps, z);
            }
        }
    }
    return points;
}

test('a torso holds its number on the upper back, behind the surface', () => {
    const patch = backPatch(box(-0.2, 0.2, 1.0, 1.5, -0.12, 0.1));
    assert.ok(patch);
    assert.ok(Math.abs(patch.x) < 1e-9);
    // The back faces minus z, and the patch floats just behind it.
    assert.ok(patch.z < -0.12 && patch.z > -0.13);
    // Upper back, the square inside the torso.
    assert.ok(patch.y > 1.25 && patch.y + patch.size / 2 <= 1.5 + 1e-9);
    assert.ok(patch.size >= 0.08 && patch.size <= 0.26);
    assert.ok(patch.size <= 0.6 * 0.4 + 1e-9);
});

test('a broad torso caps its number, and a hump below leaves it in place', () => {
    const points = box(-0.6, 0.6, 0, 1, -0.2, 0.2);
    // A pack low on the back reaches further back than the shoulders.
    points.push(...box(-0.1, 0.1, 0.05, 0.2, -0.5, -0.4, 2));
    const patch = backPatch(points);
    assert.equal(patch.size, 0.26);
    assert.ok(patch.z < -0.2 && patch.z > -0.21);
});

test('a torso too small or too thin holds no number', () => {
    assert.equal(backPatch([]), null);
    assert.equal(backPatch([0, 0, 0, 1, 1, 1]), null);
    assert.equal(backPatch(box(-0.04, 0.04, 1, 1.5, -0.1, 0.1)), null);
    assert.equal(backPatch(box(-0.2, 0.2, 1, 1.05, -0.1, 0.1)), null);
});

test('each number reads its own cell of the atlas', () => {
    assert.deepEqual(numberCell(0), [0, 0.9, 0.1, 1]);
    const [u0, v0, u1, v1] = numberCell(57);
    assert.ok(Math.abs(u0 - 0.7) < 1e-9 && Math.abs(u1 - 0.8) < 1e-9);
    assert.ok(Math.abs(v0 - 0.4) < 1e-9 && Math.abs(v1 - 0.5) < 1e-9);
    assert.deepEqual(numberCell(140), numberCell(99));
    assert.deepEqual(numberCell(-3), numberCell(0));
    assert.deepEqual(numberCell('x'), numberCell(0));
});

test('a team hides its numbers on the models it lists, GRF paints its own', () => {
    assert.equal(numbersShown({}, 'kaykit-knight'), true);
    assert.equal(numbersShown({ hidden_numbers: ['custom'] }, 'kaykit-knight'), true);
    assert.equal(numbersShown({ hidden_numbers: ['custom'] }, 'custom'), false);
    assert.equal(numbersShown({ hidden_numbers: [] }, 'grf'), false);
    assert.equal(numbersShown(null, 'custom'), true);
});
