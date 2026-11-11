// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the words of the challenges on the Play page, the value of a run with the seconds its
// attempts took to score in all and the person's name, which a default name of any language leaves
// unset, run from the repository root with `node tests/web/challenges.mjs`.
// The page loads as an English page, with the shipped languages in it.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from a copy of the whole folder beside a package file that names them modules. The icons
// that core/icons.js reads come along in vendor/lucide, beside the folder as in the page.
const root = mkdtempSync(join(tmpdir(), 'cuju-challenges-'));
const folder = join(root, 'js');
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js', import.meta.url)), folder, { recursive: true });
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/vendor/lucide', import.meta.url)), join(root, 'vendor', 'lucide'), { recursive: true });
writeFileSync(join(root, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(root, { recursive: true, force: true }));
const languages = new URL('../../src/cuju/render/web/languages/', import.meta.url);
// English ships with the page, and the Portuguese draft waits in translations/.
const read = (code) => JSON.parse(readFileSync(code === 'en' ? new URL(`${code}.json`, languages) : new URL(`../../translations/${code}.json`, import.meta.url), 'utf8'));
const shipped = { en: read('en'), pt: read('pt') };

// menu.js listens on the window and the document for its menus, which the tests never open.
globalThis.window = { addEventListener() {} };
globalThis.MutationObserver = class { observe() {} };
globalThis.document = {
    documentElement: { lang: '', dir: '' },
    getElementById: (id) => (id === 'cuju-languages' ? { textContent: JSON.stringify(shipped) } : null),
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener() {},
};
globalThis.localStorage = { getItem: (key) => (key === 'cuju.language' ? '"en"' : null), setItem() {}, removeItem() {} };
globalThis.location = { search: '' };
Object.defineProperty(globalThis, 'navigator', { value: { languages: ['en-US'], language: 'en-US' }, configurable: true, writable: true });
globalThis.fetch = async () => ({ ok: false, status: 404, json: async () => ({}) });
const { runText, typedName } = await import(pathToFileURL(join(folder, 'play/challenges.js')).href);

const corner = { id: 'corner', measure: 'scored', attempts: 5 };
const margin = { id: 'one_on_one', measure: 'margin', attempts: 5 };

test('a run names the seconds its counting attempts took to score in all', () => {
    assert.equal(runText(corner, { value: 4, seconds: 7.1 }, 'challenges.outcome.value'), '4 of 5, scored in 7.1 seconds in all.');
    assert.equal(runText(margin, { value: 2, seconds: 3 }, 'challenges.outcome.value'), '+2 goals, scored in 3 seconds in all.');
    assert.equal(runText(corner, { value: 5, seconds: 6.2 }, 'challenges.item.best', { rank: '1' }), 'Your best, 5 of 5, scored in 6.2 seconds in all, rank 1.');
});

test('a run in which no attempt counted names no seconds', () => {
    assert.equal(runText(corner, { value: 0, seconds: 0 }, 'challenges.outcome.value'), '0 of 5, no goal counted.');
    assert.equal(runText(corner, { value: 0, seconds: 0 }, 'challenges.outcome.best', { rank: 2 }), 'Personal best 0 of 5, rank 2.');
    assert.equal(runText(corner, { value: 0, seconds: 0 }, 'challenges.item.best', { rank: '3' }), 'Your best, 0 of 5, rank 3.');
    assert.equal(runText(margin, { value: -1, seconds: 0 }, 'challenges.outcome.value'), '-1 goal, no goal counted.');
});

test('Portuguese holds every form of the run in its own words', () => {
    for (const id of ['challenges.outcome.value', 'challenges.item.best', 'challenges.outcome.best']) {
        for (const form of Object.values(shipped.pt[id])) {
            assert.match(form, /segundos? no total/, id);
        }
        assert.ok(typeof shipped.pt[`${id}.none`] === 'string', id);
    }
});

test('a default name of any language counts as no name, and a typed one stays', () => {
    const known = new Set(['Player', 'Jogador']);
    assert.equal(typedName('  Ana  ', known), 'Ana');
    assert.equal(typedName('Jogador', known), '');
    assert.equal(typedName(' Player ', known), '');
    // The page's own default counts as none before the server named the others.
    assert.equal(typedName('Player', new Set()), '');
    assert.equal(typedName('Jogador', new Set()), 'Jogador');
    assert.equal(typedName('', known), '');
    assert.equal(typedName(null, known), '');
    assert.equal(typedName('x'.repeat(50), known), 'x'.repeat(40));
});
