// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the choices of the Matches page for a match drawn at random, web/js/pages/draw.js,
// run from the repository root with `node tests/web/draw.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const folder = mkdtempSync(join(tmpdir(), 'cuju-draw-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/pages/draw.js', import.meta.url)), join(folder, 'pages/draw.js'));
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const draw = await import(pathToFileURL(join(folder, 'pages/draw.js')).href);
const { RANDOM } = draw;

const builtin = { id: 'builtin', kind: 'builtin' };
const five = { id: 't-five', kind: 'kaggle', format: '5v5' };
const other = { id: 't-other', kind: 'kaggle', format: '5v5' };
const eleven = { id: 't-eleven', kind: 'kaggle', format: '11v11' };
const teams = [builtin, five, other, eleven];
const scenarios = ['11_vs_11_kaggle', '5_vs_5', 'academy_corner', '1_vs_1_easy'];

test('the word of a random part is that of the server', () => {
    const source = readFileSync(new URL('../../src/cuju/render/_playing/draw.py', import.meta.url), 'utf8');
    assert.match(source, new RegExp(`^RANDOM = '${RANDOM}'$`, 'm'));
});

test('a random side draws from the ticked teams that fit the scenario', () => {
    const none = new Set();
    assert.deepEqual(draw.sideTeams(teams, none, RANDOM, '5_vs_5').map((x) => x.id), ['builtin', 't-five', 't-other']);
    assert.deepEqual(draw.sideTeams(teams, none, RANDOM, '11_vs_11_kaggle').map((x) => x.id), ['builtin', 't-eleven']);
    assert.deepEqual(draw.sideTeams(teams, new Set(['builtin', 't-other']), RANDOM, '5_vs_5').map((x) => x.id), ['t-five']);
    // A named side keeps its own team, while it fits.
    assert.deepEqual(draw.sideTeams(teams, none, 't-five', '5_vs_5'), [five]);
    assert.deepEqual(draw.sideTeams(teams, none, 't-five', '11_vs_11_kaggle'), []);
});

test('the scenario list holds what both sides can play, with Random scenario first', () => {
    const none = new Set();
    const both = draw.scenarioChoices(scenarios, teams, none, RANDOM, RANDOM, null, '11_vs_11_kaggle');
    assert.deepEqual(both.listed, [RANDOM, ...scenarios]);
    assert.equal(both.keep, '11_vs_11_kaggle');
    // Only 5 against 5 teams in the pool leave out the full match of 11.
    const small = draw.scenarioChoices(scenarios, teams, new Set(['builtin', 't-eleven']), RANDOM, RANDOM, '11_vs_11_kaggle', '11_vs_11_kaggle');
    assert.deepEqual(small.listed, [RANDOM, '5_vs_5', 'academy_corner']);
    assert.equal(small.keep, '5_vs_5');
    // A random scenario that the person chose stays chosen.
    assert.equal(draw.scenarioChoices(scenarios, teams, none, 't-five', RANDOM, RANDOM, '11_vs_11_kaggle').keep, RANDOM);
    // One fitting scenario offers no Random scenario, and an empty pool offers nothing.
    const one = draw.scenarioChoices(['5_vs_5', '11_vs_11_kaggle'], teams, none, 't-five', 't-other', RANDOM, '11_vs_11_kaggle');
    assert.deepEqual(one, { listed: ['5_vs_5'], keep: '5_vs_5' });
    const empty = draw.scenarioChoices(scenarios, teams, new Set(teams.map((x) => x.id)), RANDOM, 'builtin', null, '5_vs_5');
    assert.deepEqual(empty, { listed: [], keep: null });
});

test('Play match names the pool and same_team only when a side draws', () => {
    const state = { left: RANDOM, right: RANDOM, scenario: '5_vs_5', ability: [null, 0.4], unticked: new Set(), sameTeam: false };
    assert.deepEqual(draw.requestOf(state, teams, '7'), {
        left: RANDOM, right: RANDOM, scenario: '5_vs_5', seed: '7', ability: [null, 0.4], pool: null, same_team: false,
    });
    state.unticked = new Set(['builtin']);
    state.sameTeam = true;
    const picked = draw.requestOf(state, teams, null);
    assert.deepEqual(picked.pool, ['t-five', 't-other', 't-eleven']);
    assert.equal(picked.same_team, true);
    const fixed = draw.requestOf({ ...state, left: 't-five', right: 'builtin', scenario: RANDOM }, teams, null);
    assert.equal('pool' in fixed, false);
    assert.equal(fixed.scenario, RANDOM);
    assert.equal(draw.drawsAny(fixed), true);
    assert.equal(draw.drawsAny({ left: 'builtin', right: 'builtin', scenario: '5_vs_5' }), false);
});

test('Retry keeps the seed and the draw, Repeat of a drawn match leaves the seed to the server', () => {
    const r = {
        left: 't-five', right: 't-other', scenario: '5_vs_5', seed: 42, ability: [null, null], state: 'done',
        draw: { sides: [true, true], scenario: false, pool: ['t-five', 't-other'], same_team: false },
    };
    assert.deepEqual(draw.againOf(r, false), {
        left: RANDOM, right: RANDOM, scenario: '5_vs_5', seed: 42, ability: [null, null],
        pool: ['t-five', 't-other'], same_team: false,
    });
    assert.equal(draw.againOf(r, true).seed, null);
    const scenario = { ...r, left: 'builtin', draw: { sides: [false, false], scenario: true, pool: null, same_team: false } };
    assert.deepEqual(draw.againOf(scenario, false), { left: 'builtin', right: 't-other', scenario: RANDOM, seed: 42, ability: [null, null] });
    // A match without a draw repeats with its own seed, as it always has.
    const plain = { left: 'builtin', right: 'builtin', scenario: '5_vs_5', seed: 9, ability: [null, null] };
    assert.deepEqual(draw.againOf(plain, true), { ...plain });
    assert.equal(draw.wasDrawn(plain), false);
    assert.equal(draw.wasDrawn(r), true);
});

test('a drawn part shows as Random while the match waits and as drawn once it starts', () => {
    const r = { state: 'queued', draw: { sides: [true, false], scenario: true, pool: null, same_team: false } };
    assert.equal(draw.hiddenPart(r, 'left'), true);
    assert.equal(draw.hiddenPart(r, 'right'), false);
    assert.equal(draw.hiddenPart(r, 'scenario'), true);
    for (const state of ['running', 'done', 'failed']) {
        assert.equal(draw.hiddenPart({ ...r, state }, 'left'), false);
    }
    assert.deepEqual(draw.drawnParts({ ...r, state: 'done' }), { left: true, right: false, scenario: true });
    assert.deepEqual(draw.drawnParts({ draw: null }), { left: false, right: false, scenario: false });
    assert.deepEqual(draw.drawnParts({ draw: 'odd' }), { left: false, right: false, scenario: false });
});
