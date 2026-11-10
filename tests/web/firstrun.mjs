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
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const { HELP_TEXT, TIPS, dismissTip, tipFor, tipState } = await import(pathToFileURL(join(folder, 'help/firstrun.js')).href);

test('every page but Help has a short tip, and every control a short line of help', () => {
    assert.deepEqual(Object.keys(TIPS).sort(), ['field', 'home', 'matches', 'play', 'recordings', 'teams', 'watch']);
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
