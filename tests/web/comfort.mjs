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
    assert.deepEqual(SOUND_CHANNELS, ['crowd', 'ambience', 'effects']);
    assert.deepEqual(soundLevels(undefined), { crowd: 1, ambience: 1, effects: 1 });
    assert.deepEqual(soundLevels('loud'), { crowd: 1, ambience: 1, effects: 1 });
    assert.deepEqual(soundLevels({ crowd: 0.25, ambience: 4, effects: -2 }),
        { crowd: 0.25, ambience: 1, effects: 0 });
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
