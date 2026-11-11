// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the medal items of the challenges, run from the repository root with
// `node tests/web/medals.mjs`. The items follow medal_items of challenges.py on the cases that
// tests/support/medal_items.json shares with the Python tests, read in English, and draw each
// metal in a color that keeps the contrast of level AA on every surface of both themes.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// The page's modules load from a copy of the whole folder beside a package file that names them
// modules, with the icons of vendor/lucide beside it as in the page.
const root = mkdtempSync(join(tmpdir(), 'cuju-medals-'));
const folder = join(root, 'js');
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js', import.meta.url)), folder, { recursive: true });
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/vendor/lucide', import.meta.url)), join(root, 'vendor', 'lucide'), { recursive: true });
writeFileSync(join(root, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(root, { recursive: true, force: true }));
const english = JSON.parse(readFileSync(new URL('../../src/cuju/render/web/languages/en.json', import.meta.url), 'utf8'));
const cases = JSON.parse(readFileSync(new URL('../support/medal_items.json', import.meta.url), 'utf8'));
const style = readFileSync(new URL('../../src/cuju/render/web/style.css', import.meta.url), 'utf8');

globalThis.window = { addEventListener() {} };
globalThis.MutationObserver = class { observe() {} };
globalThis.document = {
    documentElement: { lang: '', dir: '' },
    getElementById: (id) => (id === 'cuju-languages' ? { textContent: JSON.stringify({ en: english }) } : null),
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener() {},
};
globalThis.localStorage = { getItem: (key) => (key === 'cuju.language' ? '"en"' : null), setItem() {}, removeItem() {} };
globalThis.location = { search: '' };
Object.defineProperty(globalThis, 'navigator', { value: { languages: ['en-US'], language: 'en-US' }, configurable: true, writable: true });
globalThis.fetch = async () => ({ ok: false, status: 404, json: async () => ({}) });
const { METALS, MEDAL_ORDER, itemText, medalItems, medalOf, medalStyle } = await import(pathToFileURL(join(folder, 'play/medals.js')).href);

test('the items follow medal_items of the server, gold first, one mark at most', () => {
    for (const { challenge, value, items } of cases) {
        assert.deepEqual(medalItems(challenge, value), items, `${challenge.id} ${value}`);
        assert.deepEqual(items.map((item) => item.medal), MEDAL_ORDER);
        assert.ok(items.filter((item) => item.reached).length <= 1);
        if (value != null) {
            const won = medalOf(challenge, value);
            assert.equal((items.find((item) => item.reached) || { medal: null }).medal, won);
        }
    }
});

test('each item says its medal and its target in plain words and numbers', () => {
    const find = (id) => cases.find((item) => item.challenge.id === id).challenge;
    const words = (id) => medalItems(find(id)).map((item) => itemText(find(id), item));
    assert.deepEqual(words('one_on_one'), ['Gold, 6 goals or more ahead', 'Silver, 3 goals or more ahead', 'Bronze, 1 goal or more ahead']);
    assert.deepEqual(words('corner'), ['Gold, a goal in 4 attempts or more', 'Silver, a goal in 2 attempts or more', 'Bronze, a goal in 1 attempt or more']);
    assert.deepEqual(words('empty_goal_close'), [
        'Gold, a goal within 3 seconds in all 5 attempts',
        'Silver, a goal within 3 seconds in 4 attempts or more',
        'Bronze, a goal within 3 seconds in 3 attempts or more',
    ]);
    assert.equal(words('run_to_score')[0], 'Gold, a goal within 6.5 seconds in all 5 attempts');
});

// The relative luminance and contrast ratio of the Web Content Accessibility Guidelines.
const channel = (value) => {
    const c = value / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};
const luminance = (hex) => {
    const n = parseInt(hex.slice(1), 16);
    return 0.2126 * channel(n >> 16) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
};
const contrast = (a, b) => {
    const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (high + 0.05) / (low + 0.05);
};

test('every metal keeps a contrast of 4.5 to 1 on every surface of both themes', () => {
    const surfaces = (block) => ['bg', 'surface', 'surface-2'].map((name) => block.match(new RegExp(`--${name}: (#[0-9a-f]{6});`))[1]);
    const dark = surfaces(style.slice(style.indexOf(':root {'), style.indexOf('@media (prefers-color-scheme: light)')));
    const light = surfaces(style.slice(style.indexOf(':root[data-theme="light"] {')));
    for (const [medal, colors] of Object.entries(METALS)) {
        for (const surface of dark) {
            assert.ok(contrast(colors.dark, surface) >= 4.5, `${medal} on ${surface}`);
        }
        for (const surface of light) {
            assert.ok(contrast(colors.light, surface) >= 4.5, `${medal} on ${surface}`);
        }
    }
    const css = medalStyle();
    assert.match(css, /prefers-color-scheme: light/);
    assert.match(css, /:root\[data-theme="light"\]/);
    assert.ok(Object.values(METALS).every((colors) => css.includes(colors.dark) && css.includes(colors.light)));
});
