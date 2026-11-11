// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the touch controls, run from the repository root with `node tests/web/touch.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from copies beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-touch-'));
for (const name of ['play/touch.js', 'core/input-settings.js', 'core/i18n.js']) {
    cpSync(fileURLToPath(new URL(`../../src/cuju/render/web/js/${name}`, import.meta.url)), join(folder, name));
}
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const touch = await import(pathToFileURL(join(folder, 'play/touch.js')).href);
const { BINDINGS } = await import(pathToFileURL(join(folder, 'core/input-settings.js')).href);
const { TOUCH_BUTTONS, stickNames, swipeFrame, touchChoice, touchShown } = touch;

test('the buttons press the inputs that the keys of play press', () => {
    const keys = Object.fromEntries(BINDINGS.map((binding) => [binding.id, binding.names]));
    assert.deepEqual(TOUCH_BUTTONS.map((button) => button.id).sort(),
        ['dribble', 'high_pass', 'long_pass', 'short_pass', 'shot', 'sprint']);
    for (const button of TOUCH_BUTTONS) {
        assert.deepEqual(button.names, keys[button.id], button.id);
    }
});

test('the stick holds a direction on each axis past its dead zone', () => {
    assert.deepEqual(stickNames(0, 0, 70), []);
    assert.deepEqual(stickNames(20, -20, 70), []);
    assert.deepEqual(stickNames(70, 0, 70), ['right']);
    assert.deepEqual(stickNames(-70, 0, 70), ['left']);
    assert.deepEqual(stickNames(0, -70, 70), ['up']);
    assert.deepEqual(stickNames(0, 70, 70), ['down']);
    assert.deepEqual(stickNames(50, 50, 70), ['right', 'down']);
    assert.deepEqual(stickNames(-50, -50, 70), ['left', 'up']);
    assert.deepEqual(stickNames(30, 0, 70, 0.4), ['right']);
});

test('the pad shows as chosen, and by itself once a touch screen is used', () => {
    assert.equal(touchChoice('on'), 'on');
    assert.equal(touchChoice('sometimes'), 'auto');
    assert.equal(touchShown('auto', false), false);
    assert.equal(touchShown('auto', true), true);
    assert.equal(touchShown('on', false), true);
    assert.equal(touchShown('off', true), false);
    assert.equal(touchShown(null, true), true);
});

test('a swipe moves through the match from where it stands', () => {
    assert.equal(swipeFrame(100, 0, 500, 0, 1000), 100);
    assert.equal(swipeFrame(100, 250, 500, 0, 1000), 600);
    assert.equal(swipeFrame(100, -250, 500, 0, 1000), 0);
    assert.equal(swipeFrame(900, 500, 500, 0, 1000), 1000);
    assert.equal(swipeFrame(10, 50, 0, 10, 20), 20);
});
