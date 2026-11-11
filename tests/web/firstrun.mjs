// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the tips of the first run, run from the repository root with
// `node tests/web/firstrun.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's module
// loads from a copy beside a package file that names it a module.
const folder = mkdtempSync(join(tmpdir(), 'cuju-firstrun-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/help/firstrun.js', import.meta.url)), join(folder, 'help/firstrun.js'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/core/i18n.js', import.meta.url)), join(folder, 'core/i18n.js'));
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const { HELP_TEXT, TIPS, TIP_SPOTS, chooseSpot, dismissTip, tipFor, tipState } = await import(pathToFileURL(join(folder, 'help/firstrun.js')).href);

test('every page but Help has a short tip, and every control a short line of help', () => {
    assert.deepEqual(Object.keys(TIPS).sort(), ['field', 'home', 'matches', 'play', 'recordings', 'teams', 'tournaments', 'watch']);
    for (const text of [...Object.values(TIPS), ...Object.values(HELP_TEXT)]) {
        assert.ok(text.length <= 90, text);
        assert.ok(!/[;:()!]/.test(text), text);
    }
});

test('a dismissed tip stays away, and tips that are off show nowhere', () => {
    assert.equal(tipFor('home', null), TIPS.home);
    assert.equal(tipFor('help', null), null);
    const after = dismissTip(null, 'home');
    assert.equal(tipFor('home', after), null);
    assert.equal(tipFor('teams', after), TIPS.teams);
    assert.deepEqual(dismissTip(after, 'home'), after);
    assert.equal(tipFor('teams', { ...after, off: true }), null);
});

test('a stored state keeps only what it should', () => {
    assert.deepEqual(tipState(null), { dismissed: [], off: false });
    assert.deepEqual(tipState({ dismissed: ['home', 'home', 'nowhere', 3], off: 'yes' }), { dismissed: ['home'], off: false });
    assert.deepEqual(tipState({ dismissed: 'home', off: true }), { dismissed: [], off: true });
});

test('a tip keeps a clear corner, else takes the first clear one, else the one that covers least', () => {
    assert.equal(TIP_SPOTS[0], 'bottom-left');
    const covers = (counts) => (spot) => counts[spot] ?? 0;
    assert.equal(chooseSpot(undefined, covers({})), 'bottom-left');
    assert.equal(chooseSpot('top-right', covers({})), 'top-right');
    assert.equal(chooseSpot('bottom-left', covers({ 'bottom-left': 3 })), 'bottom-right');
    assert.equal(chooseSpot('bottom-left', covers({ 'bottom-left': 3, 'bottom-right': 1, 'top-right': 2, 'top-left': 4 })), 'bottom-right');
    assert.equal(chooseSpot('top-left', covers({ 'top-left': 2, 'bottom-left': 1, 'bottom-right': 1, 'top-right': 1 })), 'bottom-left');
});
