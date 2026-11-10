// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the bracket layout and the words of tournament tables, run from the repository root
// with `node tests/web/tournament.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's module
// loads from a copy beside a package file that names it a module.
const folder = mkdtempSync(join(tmpdir(), 'cuju-tournament-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/play/tournament-layout.js', import.meta.url)), join(folder, 'play/tournament-layout.js'));
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const layout = await import(pathToFileURL(join(folder, 'play/tournament-layout.js')).href);

function rounds(...counts) {
    return counts.map((count, r) => ({
        name: `Round ${r + 1}`,
        fixtures: Array.from({ length: count }, (_, i) => ({ id: `${r}-${i}` })),
    }));
}

test('Each tie of a halving bracket sits centred between the two that feed it', () => {
    const grid = layout.bracketLayout(rounds(8, 4, 2, 1));
    assert.equal(grid.columns, 4);
    assert.equal(grid.rows, 16);
    const [first, second, third, final] = grid.cells;
    assert.deepEqual(first.map((c) => [c.rowStart, c.rowEnd]), [[1, 3], [3, 5], [5, 7], [7, 9], [9, 11], [11, 13], [13, 15], [15, 17]]);
    for (let r = 1; r < grid.cells.length; r++) {
        grid.cells[r].forEach((cell, i) => {
            const feeders = grid.cells[r - 1].slice(2 * i, 2 * i + 2);
            assert.equal(cell.rowStart, feeders[0].rowStart);
            assert.equal(cell.rowEnd, feeders[1].rowEnd);
            assert.equal(cell.column, r + 1);
        });
    }
    assert.deepEqual([second.length, third.length, final.length], [4, 2, 1]);
    assert.deepEqual([final[0].rowStart, final[0].rowEnd], [1, 17]);
});

test('Rounds of equal size in a losers bracket stay level', () => {
    const grid = layout.bracketLayout(rounds(2, 2, 1, 1));
    assert.deepEqual(grid.cells[0].map((c) => c.rowStart), grid.cells[1].map((c) => c.rowStart));
    assert.deepEqual(grid.cells[2].map((c) => [c.rowStart, c.rowEnd]), [[1, 5]]);
    assert.deepEqual(grid.cells[3].map((c) => [c.rowStart, c.rowEnd]), [[1, 5]]);
});

test('Cells never overlap within a column and cover the grid', () => {
    for (const counts of [[1], [2, 1], [4, 2, 1], [3, 2, 1], [16, 8, 4, 2, 1], [5, 3, 1]]) {
        const grid = layout.bracketLayout(rounds(...counts));
        for (const column of grid.cells) {
            for (let i = 1; i < column.length; i++) {
                assert.ok(column[i].rowStart >= column[i - 1].rowEnd, `overlap in ${counts}`);
            }
            assert.equal(column[0].rowStart, 1);
            assert.equal(column[column.length - 1].rowEnd, grid.rows + 1);
        }
    }
});

test('Sections come in the order of play, from the round or its fixtures', () => {
    const stage = {
        format: 'double_elimination',
        rounds: [
            { name: 'Winners round 1', section: 'winners', fixtures: [{ id: 'a' }] },
            { name: 'Losers round 1', section: 'losers', fixtures: [{ id: 'b' }] },
            { name: 'Grand final', section: 'final', fixtures: [{ id: 'c' }] },
            { name: 'Winners final', section: 'winners', fixtures: [{ id: 'd' }] },
        ],
    };
    const parts = layout.sections(stage);
    assert.deepEqual(parts.map((p) => p.name), ['winners', 'losers', 'final']);
    assert.deepEqual(parts[0].rounds.map((r) => r.name), ['Winners round 1', 'Winners final']);
    const knockout = layout.sections({ format: 'knockout', rounds: [
        { name: 'Play-in round', section: 'play_in', fixtures: [] },
        { name: 'Final', section: 'main', fixtures: [] },
        { name: 'Third place match', section: 'third', fixtures: [] },
    ] });
    assert.deepEqual(knockout.map((p) => p.name), ['play_in', 'main', 'third']);
    assert.ok(layout.isBracket({ format: 'knockout' }) && !layout.isBracket({ format: 'swiss' }));
});

test('Sides name an entrant, a bye or the tie they come from', () => {
    const entrants = [{ name: 'Reds' }, { name: 'Blues' }];
    assert.equal(layout.sideName(1, entrants), 'Blues');
    assert.equal(layout.sideName(null, entrants), 'Bye');
    assert.equal(layout.sideName({ from: 'Winner of Semi-final 1' }, entrants), 'Winner of Semi-final 1');
});

test('A tiebreak explains why a row stands above the next', () => {
    const entrants = [{ name: 'Reds' }, { name: 'Blues' }, { name: 'Golds' }];
    const rows = [
        { entrant: 0, tiebreak: 'goal_difference' },
        { entrant: 1, tiebreak: null },
        { entrant: 2, tiebreak: 'lots' },
    ];
    assert.equal(layout.tiebreakText(rows[0], rows[1], entrants), 'Level on points with Blues, placed above on goal difference');
    assert.equal(layout.tiebreakText(rows[1], rows[2], entrants), '');
    assert.match(layout.tiebreakText(rows[2], { entrant: 0 }, entrants), /^Level with Reds on every tiebreaker/);
    assert.equal(layout.tiebreakText(rows[2], undefined, entrants), '');
    for (const name of ['goal_difference', 'goals_for', 'goals_against', 'head_to_head', 'wins', 'away_goals', 'fair_play', 'buchholz', 'lots']) {
        assert.ok(layout.TIEBREAK_NAMES[name]);
    }
});

test('Fixture states follow their matches, and progress follows the schedule', () => {
    const matches = new Map([
        ['a', { key: 'a', state: 'done' }],
        ['b', { key: 'b', state: 'running' }],
        ['c', { key: 'c', state: 'person' }],
    ]);
    assert.equal(layout.fixtureState({ state: 'ready', matches: ['a', 'b'] }, matches), 'running');
    assert.equal(layout.fixtureState({ state: 'ready', matches: ['a', 'c'] }, matches), 'person');
    assert.equal(layout.fixtureState({ state: 'done', matches: ['a'] }, matches), 'done');
    assert.equal(layout.fixtureState({ state: 'waiting', matches: [] }, matches), 'waiting');
    assert.equal(layout.progressShare({ state: 'running', played: 3, scheduled: 12 }), 0.25);
    assert.equal(layout.progressShare({ state: 'done', played: 3, scheduled: 4 }), 1);
    assert.equal(layout.stageText({ format: 'groups', group_sizes: [4, 4, 3] }), 'Groups, 3 groups');
});
