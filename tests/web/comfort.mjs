// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the motion preference, the sound levels and the pointer rule of the page, run from the
// repository root with `node tests/web/comfort.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's module
// loads from a copy beside a package file that names it a module.
const folder = mkdtempSync(join(tmpdir(), 'cuju-comfort-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/core/comfort.js', import.meta.url)), join(folder, 'core/comfort.js'));
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const comfort = await import(pathToFileURL(join(folder, 'core/comfort.js')).href);
const {
    MOTION_CHOICES, SOUND_CHANNELS, motionChoice, motionReduced, soundLevel, soundLevels,
} = comfort;

test('the motion preference follows the system unless set', () => {
    assert.deepEqual(MOTION_CHOICES, ['system', 'reduce', 'full']);
    for (const stored of [undefined, null, '', 'fast', 1, {}]) {
        assert.equal(motionChoice(stored), 'system');
    }
    assert.equal(motionReduced('system', true), true);
    assert.equal(motionReduced('system', false), false);
    assert.equal(motionReduced('reduce', false), true);
    assert.equal(motionReduced('full', true), false);
    assert.equal(motionReduced('unknown', true), true);
});

test('sound levels only turn their channels down', () => {
    assert.deepEqual(SOUND_CHANNELS, ['crowd', 'ambience', 'effects', 'music']);
    assert.deepEqual(soundLevels(undefined), { crowd: 1, ambience: 1, effects: 1, music: 0.8 });
    assert.deepEqual(soundLevels('loud'), { crowd: 1, ambience: 1, effects: 1, music: 0.8 });
    assert.deepEqual(soundLevels({ crowd: 0.25, ambience: 4, effects: -2, music: 2 }),
        { crowd: 0.25, ambience: 1, effects: 0, music: 1 });
    for (const value of [Number.NaN, Infinity, '0.5', null, true]) {
        assert.equal(soundLevel(value), 1);
    }
    assert.equal(soundLevel(0), 0);
});

test('open panels take the pointer back only while they show', () => {
    const { OWN_KEYS, POINTER_PANELS, openPanel } = comfort;
    const panels = ['details[open]', 'dialog[open]', '[role="menu"]', 'button[aria-expanded="true"]'];
    for (const selector of panels) {
        assert.ok(POINTER_PANELS.split(', ').includes(selector), selector);
    }
    assert.ok(OWN_KEYS.split(', ').includes('summary'));
    const node = (shows) => ({ getClientRects: () => (shows ? [{}] : []) });
    const root = (nodes) => ({
        querySelectorAll(selector) {
            assert.equal(selector, POINTER_PANELS);
            return nodes;
        },
    });
    const shown = node(true);
    assert.equal(openPanel(root([node(false), shown])), shown);
    assert.equal(openPanel(root([node(false)])), null);
    assert.equal(openPanel(root([])), null);
});

test('reduced motion fades where a wipe would sweep, fully covered around the cut', () => {
    const { fadeCover } = comfort;
    for (const p of [null, undefined, Number.NaN, -1, 0, 1, 2]) {
        assert.equal(fadeCover(p), 0);
    }
    for (const p of [0.3, 0.4, 0.5, 0.6, 0.7]) {
        assert.equal(fadeCover(p), 1);
    }
    assert.ok(fadeCover(0.05) > 0 && fadeCover(0.05) < fadeCover(0.15) && fadeCover(0.15) < 1);
    assert.ok(fadeCover(0.95) > 0 && fadeCover(0.95) < fadeCover(0.85) && fadeCover(0.85) < 1);
    assert.ok(Math.abs(fadeCover(0.1) - fadeCover(0.9)) < 1e-12);
});

test('a still shot holds while its subject stays in frame and cuts when it leaves', () => {
    const { STILL_EDGE, STILL_HOLD, stillCut } = comfort;
    const v = (x, y, z) => ({ x, y, z });
    // Ten meters back, looking along minus z at the subject.
    const view = { pos: v(0, 0, 10), target: v(0, 0, 0), fov: 40 };
    const tanV = Math.tan((20 * Math.PI) / 180);
    assert.equal(stillCut(view, v(0, 0, 0), 16 / 9, 0), false);
    assert.equal(stillCut(view, v(0, 0, 0), 16 / 9, 60), false);
    // Within the middle of the frame the shot holds however long it runs.
    const inner = 10 * tanV * 16 / 9 * (STILL_EDGE - 0.1);
    assert.equal(stillCut(view, v(inner, 0, 0), 16 / 9, 60), false);
    assert.equal(stillCut(view, v(-inner, 0, 0), 16 / 9, 60), false);
    // Near the edge it holds for the shortest hold, then cuts.
    const edge = 10 * tanV * 16 / 9 * (STILL_EDGE + 0.1);
    assert.equal(stillCut(view, v(edge, 0, 0), 16 / 9, STILL_HOLD / 2), false);
    assert.equal(stillCut(view, v(edge, 0, 0), 16 / 9, STILL_HOLD), true);
    // The vertical edge is nearer than the horizontal one.
    assert.equal(stillCut(view, v(0, 10 * tanV * 1.05, 0), 16 / 9, 0), true);
    assert.equal(stillCut(view, v(10 * tanV * 1.05, 0, 0), 16 / 9, 0), false);
    // Out of the frame, behind the camera, or far nearer or farther, it cuts at once.
    assert.equal(stillCut(view, v(10 * tanV * 16 / 9 * 1.05, 0, 0), 16 / 9, 0), true);
    assert.equal(stillCut(view, v(0, 0, 20), 16 / 9, 0), true);
    assert.equal(stillCut(view, v(0, 0, 6), 16 / 9, 0), true);
    assert.equal(stillCut(view, v(0, 0, -15), 16 / 9, 0), true);
    // A view straight down and a view of no length.
    const down = { pos: v(0, 30, 0), target: v(0, 0, 0), fov: 40 };
    assert.equal(stillCut(down, v(2, 0, 2), 16 / 9, 60), false);
    assert.equal(stillCut({ pos: v(1, 1, 1), target: v(1, 1, 1), fov: 40 }, v(0, 0, 0)), true);
});
