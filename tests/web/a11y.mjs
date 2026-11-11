// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the page's structure, the keys that controls keep and the names of scenarios with
// agents, run from the repository root with `node tests/web/a11y.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from copies beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-a11y-'));
for (const name of ['core/comfort.js', 'core/page-structure.js', 'core/scenarios.js', 'core/i18n.js']) {
    cpSync(fileURLToPath(new URL(`../../src/cuju/render/web/js/${name}`, import.meta.url)), join(folder, name));
}
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const load = (name) => import(pathToFileURL(join(folder, name)).href);
const { keepsKey } = await load('core/comfort.js');
const { pageName, pageTitle } = await load('core/page-structure.js');
const { scenarioName, titleText } = await load('core/scenarios.js');

// A control with a tag, a role and the selectors of its ancestors, enough for matches and closest.
function control(tag, role = null, inside = []) {
    const own = (selector) => selector.split(',').map((part) => part.trim()).some((part) => {
        const [, name, attribute] = /^([a-z]*)(\[.*\])?$/.exec(part.replace(/:not\(.*\)/, '')) || [];
        if (name && name !== tag) {
            return false;
        }
        if (!attribute) {
            return !!name;
        }
        if (attribute === '[href]') {
            return tag === 'a';
        }
        const wanted = /\[role="([^"]+)"\]/.exec(attribute);
        return !!wanted && wanted[1] === role;
    });
    return {
        matches: own,
        getAttribute: (name) => (name === 'role' ? role : null),
        closest: (selector) => (inside.some((outer) => selector.split(',').map((part) => part.trim()).includes(outer)) ? {} : null),
    };
}

test('buttons and links pass letters and the question mark on, and keep Enter and Space', () => {
    const button = control('button');
    for (const key of ['h', 'H', '?', 'm', 'F']) {
        assert.equal(keepsKey(button, key), false, key);
    }
    for (const key of ['Enter', ' ', 'ArrowLeft', '1']) {
        assert.equal(keepsKey(button, key), true, key);
    }
    assert.equal(keepsKey(control('a'), 'h'), false);
    assert.equal(keepsKey(button, 'h', { ctrlKey: true }), true);
    assert.equal(keepsKey(button, 'Escape'), false);
    assert.equal(keepsKey(null, 'h'), false);
});

test('menus, tabs, sliders and controls inside a dialog keep their letters', () => {
    assert.equal(keepsKey(control('button', 'menuitem'), 'h'), true);
    assert.equal(keepsKey(control('button', 'tab'), 'h'), true);
    assert.equal(keepsKey(control('div', 'slider'), 'h'), true);
    assert.equal(keepsKey(control('button', null, ['[role="dialog"]']), 'h'), true);
    assert.equal(keepsKey(control('button', null, ['[role="menu"]']), 'm'), true);
});

test('each page has a title of its own, and Watch names its recording', () => {
    assert.equal(pageTitle('home'), 'Cuju');
    assert.equal(pageTitle('help'), 'Help · Cuju');
    assert.equal(pageTitle('recordings', 'Sample match'), 'Recordings · Cuju');
    assert.equal(pageTitle('watch', 'Sample match'), 'Sample match · Cuju');
    assert.equal(pageTitle('watch'), 'Watch · Cuju');
    assert.equal(pageName('tournaments'), 'Tournaments');
});

test('scenario names read the agents of each side in words', () => {
    assert.equal(scenarioName('5_vs_5_l0_r0'), '5 vs 5');
    assert.equal(scenarioName('11_vs_11_kaggle_l0_r0'), '11 vs 11, Kaggle');
    assert.equal(scenarioName('5_vs_5_l4_r0'), '5 vs 5, 4 agents on the left');
    assert.equal(scenarioName('5_vs_5_l0_r1'), '5 vs 5, 1 agent on the right');
    assert.equal(scenarioName('5_vs_5_l4_r4'), '5 vs 5, 4 agents a side');
    assert.equal(scenarioName('11_vs_11_stochastic_l2_r1'), '11 vs 11, 2 agents on the left and 1 on the right');
    assert.equal(scenarioName('my_scenario_l0_r0'), 'My scenario');
    assert.equal(titleText('5_vs_5_l0_r0, seed 3', '5_vs_5_l0_r0'), '5 vs 5, seed 3');
    assert.equal(titleText('11_vs_11_kaggle_l0_r0'), '11 vs 11, Kaggle');
});
