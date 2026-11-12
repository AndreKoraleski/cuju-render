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
    // Only 5 against 5 teams in the pool leave out the full match of 11, and a scenario that is no
    // full match takes a team of either format, as the server does.
    const small = draw.scenarioChoices(scenarios, teams, new Set(['builtin', 't-eleven']), RANDOM, RANDOM, '11_vs_11_kaggle', '11_vs_11_kaggle');
    assert.deepEqual(small.listed, [RANDOM, '5_vs_5', 'academy_corner', '1_vs_1_easy']);
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
        assert.equal(draw.hiddenPart({ ...r, state, started: 1.5 }, 'left'), false);
    }
    // A match cancelled or interrupted before it started keeps its draw unseen, as while it waited.
    assert.equal(draw.hiddenPart({ ...r, state: 'failed', started: null }, 'left'), true);
    assert.equal(draw.hiddenPart({ ...r, state: 'failed', started: null }, 'scenario'), true);
    assert.equal(draw.hiddenPart({ ...r, state: 'failed', started: null }, 'right'), false);
    assert.deepEqual(draw.drawnParts({ ...r, state: 'done' }), { left: true, right: false, scenario: true });
    assert.deepEqual(draw.drawnParts({ draw: null }), { left: false, right: false, scenario: false });
    assert.deepEqual(draw.drawnParts({ draw: 'odd' }), { left: false, right: false, scenario: false });
});

test('a random side counts the teams it can draw, not every team of the pool', () => {
    const none = new Set();
    const state = { left: RANDOM, right: 'builtin', scenario: '5_vs_5', sameTeam: false };
    // A match of five a side leaves out the team of eleven, and the built-in AI that plays the
    // other side while other teams fit.
    assert.deepEqual(draw.drawableTeams(teams, none, state, 0, scenarios).map((x) => x.id), ['t-five', 't-other']);
    assert.deepEqual(draw.drawableTeams(teams, none, { ...state, sameTeam: true }, 0, scenarios).map((x) => x.id), ['builtin', 't-five', 't-other']);
    assert.deepEqual(draw.drawableTeams(teams, none, { ...state, scenario: '11_vs_11_kaggle' }, 0, scenarios).map((x) => x.id), ['t-eleven']);
    // A random scenario lets every team of the pool play some scenario, and leaves out the team of
    // the other side, since another team fits every scenario.
    assert.deepEqual(draw.drawableTeams(teams, none, { ...state, scenario: RANDOM }, 0, scenarios).map((x) => x.id), ['t-five', 't-other', 't-eleven']);
    // The unticked teams stay out, and a pool of the other side's team alone plays it again.
    assert.deepEqual(draw.drawableTeams(teams, new Set(['t-five', 't-other']), state, 0, scenarios).map((x) => x.id), ['builtin']);
    // The right side counts alike, and two random sides take different teams.
    const both = { left: RANDOM, right: RANDOM, scenario: '5_vs_5', sameTeam: false };
    assert.deepEqual(draw.drawableTeams(teams, new Set(['builtin', 't-other']), both, 1, scenarios).map((x) => x.id), ['t-five']);
    assert.deepEqual(draw.drawableTeams(teams, none, both, 1, scenarios).map((x) => x.id), ['builtin', 't-five', 't-other']);
    // No scenario that fits draws nothing.
    assert.deepEqual(draw.drawableTeams(teams, none, { ...state, scenario: null }, 0, scenarios), []);
});

const shared = JSON.parse(readFileSync(new URL('../support/control_fits.json', import.meta.url), 'utf8'));

test('a team fits a side by its format and control as the server checks it', () => {
    // tests/test_teams.py checks the server's rule with the same cases.
    for (const c of shared.formats) {
        assert.equal(draw.fits({ id: 't', kind: 'kaggle', format: c.format }, c.scenario), c.fits, c.scenario);
    }
    for (const c of shared.controls) {
        const formation = c.formation.map(([role, controllable]) => ({ role, controllable }));
        assert.deepEqual(draw.controlFault(c.control, formation), c.fault, JSON.stringify(c.control));
    }
});

test('the players of a drill decide which side a team can draw', () => {
    // The drill of three against one with a keeper gives four players to the left side and two
    // to the right, so a team that controls three plays the left side alone.
    const player = (role) => ({ role, controllable: true });
    const sides = { academy_3_vs_1_with_keeper: [[player(0), player(5), player(5), player(5)], [player(0), player(1)]] };
    const three = { id: 't-three', kind: 'kaggle', format: '5v5', control: { players: 3, assignment: 'dynamic', selection: [], goalkeeper: 'scenario' } };
    const pool = [builtin, five, three];
    const none = new Set();
    assert.equal(draw.fits(three, 'academy_3_vs_1_with_keeper', 0, sides), true);
    assert.deepEqual(draw.unfit(three, 'academy_3_vs_1_with_keeper', 1, sides), { id: 'server.teams.control.too_few', values: { count: 2 } });
    const state = { left: 'builtin', right: RANDOM, scenario: 'academy_3_vs_1_with_keeper', sameTeam: false };
    assert.deepEqual(draw.drawableTeams(pool, none, state, 1, [], sides).map((x) => x.id), ['t-five']);
    assert.deepEqual(draw.drawableTeams(pool, none, { ...state, left: RANDOM, right: 'builtin' }, 0, [], sides).map((x) => x.id), ['t-five', 't-three']);
    // A scenario whose players the page lacks checks the format alone.
    assert.equal(draw.fits(three, 'academy_3_vs_1_with_keeper', 1, null), true);
    assert.deepEqual(draw.unfit({ ...five, format: '5v5' }, '11_vs_11_kaggle'), { id: 'matches.draw.unfit.format', values: { format: '5v5' } });
});
