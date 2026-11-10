// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the Play page's input settings, run from the repository root with
// `node tests/web/input.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's module
// loads from a copy beside a package file that names it a module.
const folder = mkdtempSync(join(tmpdir(), 'cuju-input-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/core/input-settings.js', import.meta.url)), join(folder, 'core/input-settings.js'));
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const {
    ACTION_NAMES, BINDINGS, STORAGE_KEY, actionName, defaultSettings, devicesClash, keyLabel, keyMap,
    keyProblem, loadSettings, normalize, saveSettings, stickDirections,
} = await import(pathToFileURL(join(folder, 'core/input-settings.js')).href);

// A storage that keeps its items, or throws on every call, as a private window may.
function memory() {
    const items = new Map();
    return { getItem: (key) => items.get(key) ?? null, setItem: (key, value) => items.set(key, String(value)), items };
}
const broken = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };

test('the defaults are the layout of Gameplay Football', () => {
    const settings = defaultSettings();
    const map = keyMap(settings);
    assert.deepEqual(map.KeyA, ['high_pass', 'sliding']);
    assert.deepEqual(map.ArrowLeft, ['left']);
    assert.deepEqual(map.KeyE, ['sprint']);
    assert.equal(Object.keys(map).length, BINDINGS.length);
    assert.equal(settings.deadZone, 0.5);
    assert.deepEqual(settings.devices, ['auto', 'auto']);
});

test('a key is refused when reserved, unknown or taken', () => {
    const settings = defaultSettings();
    for (const code of ['KeyH', 'KeyM', 'KeyF']) {
        assert.equal(keyProblem(settings, 'shot', code), 'reserved');
    }
    for (const code of ['Escape', 'Tab', 'Space', 'ShiftLeft', 'Enter', 'F5']) {
        assert.equal(keyProblem(settings, 'shot', code), 'invalid');
    }
    assert.equal(keyProblem(settings, 'shot', 'KeyW'), 'taken');
    assert.equal(keyProblem(settings, 'shot', 'KeyD'), null);
    assert.equal(keyProblem(settings, 'shot', 'KeyX'), null);
    assert.equal(keyProblem(settings, 'shot', 'Digit7'), null);
});

test('stored settings keep each valid part and drop a damaged one', () => {
    const storage = memory();
    const settings = defaultSettings();
    settings.keys.shot = 'KeyX';
    settings.deadZone = 0.25;
    settings.devices = ['pad1', 'keyboard'];
    assert.equal(saveSettings(settings, storage), true);
    assert.deepEqual(loadSettings(storage), settings);
    // Duplicate, reserved and unknown keys, a dead zone out of range and a shared device fall back.
    const damaged = (changes) => normalize({ ...JSON.parse(storage.getItem(STORAGE_KEY)), ...changes });
    assert.deepEqual(damaged({ keys: { ...settings.keys, shot: 'KeyW' } }).keys, defaultSettings().keys);
    assert.deepEqual(damaged({ keys: { ...settings.keys, shot: 'KeyH' } }).keys, defaultSettings().keys);
    assert.deepEqual(damaged({ keys: { ...settings.keys, shot: 'Space' } }).keys, defaultSettings().keys);
    assert.equal(damaged({ deadZone: 0.95 }).deadZone, 0.5);
    assert.equal(damaged({ deadZone: '0.3' }).deadZone, 0.5);
    assert.equal(damaged({ deadZone: 0.3 }).keys.shot, 'KeyX');
    assert.deepEqual(damaged({ devices: ['pad0', 'pad0'] }).devices, ['auto', 'auto']);
    assert.deepEqual(damaged({ devices: ['auto', 'auto'] }).devices, ['auto', 'auto']);
    assert.deepEqual(damaged({ devices: ['mouse', 'auto'] }).devices, ['auto', 'auto']);
    assert.deepEqual(normalize('nonsense'), defaultSettings());
    storage.setItem(STORAGE_KEY, '{not json');
    assert.deepEqual(loadSettings(storage), defaultSettings());
});

test('storage that refuses leaves the defaults and reports the failed save', () => {
    assert.deepEqual(loadSettings(broken), defaultSettings());
    assert.equal(saveSettings(defaultSettings(), broken), false);
});

test('the stick counts past the dead zone on each axis', () => {
    assert.deepEqual(stickDirections(0.4, -0.4, 0.5), []);
    assert.deepEqual(stickDirections(0.4, -0.4, 0.3), ['right', 'up']);
    assert.deepEqual(stickDirections(-0.9, 0.6, 0.5), ['left', 'down']);
    assert.deepEqual(stickDirections(0.5, 0, 0.5), []);
});

test('devices, labels and the names of the engine actions', () => {
    assert.equal(devicesClash(['keyboard', 'keyboard']), true);
    assert.equal(devicesClash(['auto', 'auto']), false);
    assert.equal(devicesClash(['pad0', 'pad1']), false);
    assert.equal(keyLabel('KeyQ'), 'Q');
    assert.equal(keyLabel('Digit3'), '3');
    assert.equal(keyLabel('ArrowUp'), '↑');
    assert.equal(ACTION_NAMES.length, 20);
    assert.equal(actionName(13), 'sprint');
    assert.equal(actionName(19), 'built-in AI');
    assert.equal(actionName(42), 'unknown');
});
