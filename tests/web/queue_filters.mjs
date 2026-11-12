// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the Team and Scenario filters of the list of requested matches on the Matches page,
// web/js/pages/queue-filters.js, run from the repository root with `node tests/web/queue_filters.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const folder = mkdtempSync(join(tmpdir(), 'cuju-queue-filters-'));
for (const name of ['draw.js', 'queue-filters.js']) {
    cpSync(fileURLToPath(new URL(`../../src/cuju/render/web/js/pages/${name}`, import.meta.url)), join(folder, 'pages', name));
}
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const filters = await import(pathToFileURL(join(folder, 'pages/queue-filters.js')).href);

const noDraw = null;
const both = { sides: [true, true], scenario: true, pool: null, same_team: false };
const left = { sides: [true, false], scenario: false, pool: null, same_team: false };
// The server names the teams and the scenario that a request drew as soon as it queues it.
const requests = [
    { id: 'r-4', state: 'queued', left: 't-accent', right: 't-eleven', scenario: 'academy_corner', draw: both },
    { id: 'r-3', state: 'queued', left: 't-five', right: 'builtin', scenario: '5_vs_5', draw: left },
    { id: 'r-2', state: 'done', left: 't-five', right: 'builtin', scenario: 'academy_corner', draw: left },
    { id: 'r-1', state: 'failed', left: 't-long', right: 't-five', scenario: '11_vs_11_kaggle', draw: noDraw },
];
const ids = (list) => list.map((r) => r.id);
// The registry lists the built-in AI first and then the teams from the newest.
const registry = ['builtin', 't-accent', 't-long', 't-eleven', 't-five'].map((id) => ({ id }));

test('a part drawn at random stays out of the filters while its match waits', () => {
    // The drawn teams of the waiting requests appear in the filter only by the requests that show them.
    assert.deepEqual(filters.filterTeams(requests, registry), ['builtin', 't-long', 't-five']);
    assert.deepEqual(filters.filterScenarios(requests), ['11_vs_11_kaggle', '5_vs_5', 'academy_corner']);
    assert.deepEqual(ids(requests.filter((r) => filters.passesTeam(r, filters.teamValue('t-accent')))), []);
    assert.deepEqual(ids(requests.filter((r) => filters.passesTeam(r, filters.teamValue('t-five')))), ['r-2', 'r-1']);
    assert.deepEqual(ids(requests.filter((r) => filters.passesTeam(r, filters.teamValue('builtin')))), ['r-3', 'r-2']);
    assert.deepEqual(ids(requests.filter((r) => filters.passesScenario(r, filters.scenarioValue('academy_corner')))), ['r-2']);
    assert.deepEqual(ids(requests.filter((r) => filters.passesTeam(r, 'all') && filters.passesScenario(r, 'all'))), ids(requests));
    // Once the match starts, the drawn teams and scenario show and filter as any other.
    const started = requests.map((r) => ({ ...r, state: 'running' }));
    assert.deepEqual(ids(started.filter((r) => filters.passesTeam(r, filters.teamValue('t-accent')))), ['r-4']);
    assert.deepEqual(ids(started.filter((r) => filters.passesScenario(r, filters.scenarioValue('academy_corner')))), ['r-4', 'r-2']);
    assert.deepEqual(filters.shownTeams(requests[1]), [null, 'builtin']);
    assert.equal(filters.shownScenario(requests[0]), null);
});

test('the Team filter lists its teams as the team lists of a new match do', () => {
    // The order of the registry, whatever the order of the requests, and the same after a new one.
    assert.deepEqual(filters.filterTeams(requests.slice(2), registry), ['builtin', 't-long', 't-five']);
    const newer = [{ id: 'r-5', state: 'done', left: 't-five', right: 't-long', scenario: '5_vs_5', draw: noDraw }, ...requests.slice(2)];
    assert.deepEqual(filters.filterTeams(newer, registry), ['builtin', 't-long', 't-five']);
    // A team that the registry no longer holds comes last, and a team without requests stays out.
    assert.deepEqual(filters.filterTeams(requests.slice(2), registry.filter((x) => x.id !== 't-long')), ['builtin', 't-five', 't-long']);
    assert.deepEqual(filters.filterTeams([], registry), []);
});

test('the teams that requests name and the registry lacks, which the page then loads', () => {
    assert.deepEqual(filters.unknownTeams(requests, registry), []);
    // A team drawn for a waiting match counts too, as its name shows once the match starts.
    assert.deepEqual(filters.unknownTeams(requests, registry.filter((x) => x.id !== 't-accent' && x.id !== 't-long')), ['t-accent', 't-long']);
    assert.deepEqual(filters.unknownTeams([], []), []);
});

test('a team or a scenario named all never reads as every one', () => {
    const odd = [
        { id: 'r-a', state: 'done', left: 'all', right: 'builtin', scenario: 'all', draw: noDraw },
        { id: 'r-b', state: 'done', left: 't-five', right: 'builtin', scenario: '5_vs_5', draw: noDraw },
    ];
    assert.notEqual(filters.teamValue('all'), filters.ALL);
    assert.notEqual(filters.scenarioValue('all'), filters.ALL);
    assert.deepEqual(ids(odd.filter((r) => filters.passesTeam(r, filters.teamValue('all')))), ['r-a']);
    assert.deepEqual(ids(odd.filter((r) => filters.passesScenario(r, filters.scenarioValue('all')))), ['r-a']);
    assert.deepEqual(ids(odd.filter((r) => filters.passesTeam(r, filters.ALL))), ['r-a', 'r-b']);
});
