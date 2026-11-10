// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the presets of the settings panel, run from the repository root with
// `node tests/web/presets.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's module
// loads from a copy beside a package file that names it a module.
const folder = mkdtempSync(join(tmpdir(), 'cuju-presets-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/watch/presets.js', import.meta.url)), join(folder, 'watch/presets.js'));
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const {
    PRESETS, PRESET_NAMES, PRESET_SETTINGS, cleanCustom, presetOf, presetValues, switchPreset,
} = await import(pathToFileURL(join(folder, 'watch/presets.js')).href);

const KEYS = ['lineups', 'celebrations', 'replays', 'decisionReplays', 'transitions', 'podium'];
const MINE = { lineups: false, celebrations: true, replays: true, decisionReplays: false, transitions: true, podium: false };

test('the presets cover the six parts of the presentation', () => {
    assert.deepEqual(PRESET_SETTINGS.map(([key]) => key), KEYS);
    assert.deepEqual(PRESET_NAMES.map(([name]) => name), ['quick', 'broadcast', 'custom']);
    assert.ok(KEYS.every((key) => PRESETS.quick[key] === false && PRESETS.broadcast[key] === true));
});

test('the values name their preset, and every other mix is custom', () => {
    assert.equal(presetOf(PRESETS.quick), 'quick');
    assert.equal(presetOf(PRESETS.broadcast), 'broadcast');
    assert.equal(presetOf(MINE), 'custom');
    // A setting the page has not stored yet is on, as its default is.
    assert.equal(presetOf({}), 'broadcast');
    assert.equal(presetOf(null), 'broadcast');
    assert.deepEqual(presetValues({ replays: false, other: 1 }), { ...PRESETS.broadcast, replays: false });
});

test('a stored custom mix is kept only when whole', () => {
    assert.deepEqual(cleanCustom(MINE), MINE);
    for (const stored of [null, 'quick', 3, {}, { ...MINE, podium: 'no' }, { lineups: true }]) {
        assert.equal(cleanCustom(stored), null);
    }
});

test('a preset keeps the custom mix it leaves, and Custom brings it back', () => {
    const quick = switchPreset('quick', MINE, null);
    assert.deepEqual(quick.values, PRESETS.quick);
    assert.deepEqual(quick.custom, MINE);
    const broadcast = switchPreset('broadcast', quick.values, quick.custom);
    assert.deepEqual(broadcast.values, PRESETS.broadcast);
    assert.deepEqual(broadcast.custom, MINE);
    const back = switchPreset('custom', broadcast.values, broadcast.custom);
    assert.deepEqual(back.values, MINE);
    assert.deepEqual(back.custom, MINE);
    // The preset's values are a copy, which a later change never reaches.
    back.values.podium = true;
    assert.equal(MINE.podium, false);
    assert.equal(switchPreset('quick', PRESETS.broadcast, null).values.podium, false);
});

test('Custom without a kept mix leaves the values as they are', () => {
    assert.deepEqual(switchPreset('custom', PRESETS.quick, null), { values: PRESETS.quick, custom: null });
    // A preset chosen over another preset keeps the custom mix that the store holds.
    assert.deepEqual(switchPreset('broadcast', PRESETS.quick, MINE).custom, MINE);
});
