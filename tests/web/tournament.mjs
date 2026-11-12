// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the bracket layout and the words of tournament tables, run from the repository root
// with `node tests/web/tournament.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from a copy beside a package file that names them modules. kits.js imports three for its
// textures, which a small stub stands in for, since the keepers it picks need no drawing.
const folder = mkdtempSync(join(tmpdir(), 'cuju-tournament-'));
for (const name of ['play/tournament-layout.js', 'core/i18n.js', 'players/kits.js']) {
    cpSync(fileURLToPath(new URL(`../../src/cuju/render/web/js/${name}`, import.meta.url)), join(folder, name));
}
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
mkdirSync(join(folder, 'node_modules', 'three'), { recursive: true });
writeFileSync(join(folder, 'node_modules', 'three', 'package.json'), '{"name": "three", "type": "module", "main": "index.js"}\n');
writeFileSync(join(folder, 'node_modules', 'three', 'index.js'),
    'export class Color {}\nexport class CanvasTexture {}\nexport const SRGBColorSpace = "srgb";\n');
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

// The labels that the server gives, as its rules make them, here written out by hand.
const label = (id, text, values = {}) => ({ id: `server.tournament.label.${id}`, text, values });
const semi = label('semi_final', 'Semi-final 1', { number: '1' });

test('Names and labels of the server show in the language of the page', async () => {
    const i18n = await import(pathToFileURL(join(folder, 'core/i18n.js')).href);
    const builtin = { name: 'Built-in AI 0.50', name_id: 'server.tournament.label.builtin_ability', name_values: { ability: '0.50' } };
    const twice = {
        name: 'Built-in AI 0.50 2', name_id: 'server.tournament.label.numbered',
        name_values: { name: label('builtin_ability', 'Built-in AI 0.50', { ability: '0.50' }), number: '2' },
    };
    const person = { name: 'Ana' };
    const from = { from: 'Winner of Semi-final 1', from_id: 'server.tournament.label.winner_of', from_values: { match: semi } };
    const table = { name: 'Group A', name_id: 'server.tournament.label.group', name_values: { group: 'A' } };
    const title = label('title', 'Spring cup, Semi-final 1, Built-in AI 0.50 against Ana', {
        tournament: 'Spring cup', match: semi, home: label('builtin_ability', 'Built-in AI 0.50', { ability: '0.50' }), away: 'Ana',
    });
    const note = {
        note: 'The game stopped, the policy of Reds failed, ValueError: no. Award the match to either side, or play it again.',
        note_id: 'server.tournament.note.failed',
        note_values: { error: { id: 'server.policy.failed', text: 'the policy of Reds failed, ValueError: no', values: { player: 'Reds', reason: 'ValueError: no' } } },
    };
    // English shows the server's own text.
    assert.equal(layout.entrantName(builtin), 'Built-in AI 0.50');
    assert.equal(layout.entrantName(twice), 'Built-in AI 0.50 2');
    assert.equal(layout.sideName(0, [person]), 'Ana');
    assert.equal(layout.sideName(from, []), 'Winner of Semi-final 1');
    assert.equal(layout.stageNameText('Group stage'), 'Group stage');
    assert.equal(layout.formatsText([{ format: 'groups' }, { format: 'knockout' }]), 'Groups then knockout');
    assert.equal(i18n.labelText(title), title.text);
    try {
        await i18n.setLanguage('pt');
        assert.equal(layout.entrantName(builtin), 'IA embutida 0,50');
        assert.equal(layout.entrantName(twice), 'IA embutida 0,50 2');
        assert.equal(layout.entrantName(person), 'Ana');
        assert.equal(layout.sideName(from, []), 'Vencedor de Semifinal 1');
        assert.equal(i18n.serverText(table, 'name'), 'Grupo A');
        assert.equal(i18n.labelText(title), 'Spring cup, Semifinal 1, IA embutida 0,50 x Ana');
        // The note and the failure inside it both read in Portuguese.
        const shown = i18n.serverText(note, 'note');
        assert.ok(shown.startsWith('O jogo parou, ') && shown.includes('W.O.'), shown);
        assert.ok(!/policy|failed|Award/.test(shown), shown);
        // A stage named by the server or a preset reads in Portuguese, a typed one as typed.
        assert.equal(layout.stageNameText('Group stage'), 'Fase de grupos');
        assert.equal(layout.stageNameText('Cup'), 'Copa');
        assert.equal(layout.stageNameText('Our final'), 'Our final');
        // A file of before, with the English text alone, keeps showing it.
        assert.equal(layout.entrantName({ name: 'Built-in AI 0.30' }), 'Built-in AI 0.30');
        assert.equal(layout.sideName({ from: 'Winner of Final' }, []), 'Winner of Final');
    } finally {
        await i18n.setLanguage('en');
    }
});

test('Every stage name of the page has a message in English and in the Portuguese draft', async () => {
    const { readFileSync } = await import('node:fs');
    for (const code of ['en', 'pt']) {
        const place = code === 'en' ? `../../src/cuju/render/web/languages/${code}.json` : `../../translations/${code}.json`;
        const file = JSON.parse(readFileSync(new URL(place, import.meta.url), 'utf8'));
        for (const key of Object.values(layout.STAGE_NAME_IDS)) {
            assert.equal(typeof file[`server.tournament.label.stage.${key}`], 'string', `${code} ${key}`);
        }
        for (const format of Object.keys(layout.FORMAT_NAMES)) {
            assert.equal(typeof file[`tournament.formatLater.${format}`], 'string', `${code} ${format}`);
        }
    }
    const english = JSON.parse(readFileSync(new URL('../../src/cuju/render/web/languages/en.json', import.meta.url), 'utf8'));
    for (const [name, key] of Object.entries(layout.STAGE_NAME_IDS)) {
        assert.equal(english[`server.tournament.label.stage.${key}`], name);
    }
    // The section of the third place match agrees with the name of its round.
    assert.equal(english['tournament.section.third'], english['server.tournament.label.third_place']);
});

test('Entrant names compare and number as the server\'s rules do', () => {
    // The same cases hold the server's name_key and free_name, in tests/test_tournament.py.
    const cases = JSON.parse(readFileSync(new URL('../support/entrant_names.json', import.meta.url), 'utf8'));
    for (const [name, key] of cases.keys) {
        assert.equal(layout.nameKey(name), key, JSON.stringify(name));
    }
    for (const [base, taken, longest, name] of cases.free) {
        assert.equal(layout.freeName(base, new Set(taken.map(layout.nameKey)), longest), name, JSON.stringify(base));
    }
    assert.equal(layout.NAME_LONGEST, 40);
});

test('Abilities follow the entrant, the stage and the standard as the server\'s rules do', () => {
    // The same cases hold the server's match_ability and shown_ability, in tests/test_tournament.py.
    const cases = JSON.parse(readFileSync(new URL('../support/entrant_abilities.json', import.meta.url), 'utf8'));
    for (const [entrant, stage, standard, ability] of cases.match) {
        assert.equal(layout.matchAbility(entrant, stage, standard), ability, JSON.stringify([entrant, stage, standard]));
    }
    for (const [entrant, standard, ability] of cases.shown) {
        assert.equal(layout.shownAbility(entrant, standard), ability, JSON.stringify([entrant, standard]));
    }
});

test('A team that plays itself keeps its keepers apart', async () => {
    const kits = await import(pathToFileURL(join(folder, 'players/kits.js')).href);
    const team = { id: 'rex', style: { kit: { primary: [200, 20, 20], secondary: [250, 250, 250] }, goalkeeper: { primary: [20, 200, 20] } } };
    const styles = [kits.normalizeStyle(team, 0), kits.normalizeStyle(team, 1)];
    kits.separateKeepers(styles, [team, team]);
    assert.ok(styles[1].away, 'the right side wears its away kit');
    assert.notDeepEqual(styles[1].goalkeeper.primary, styles[0].goalkeeper.primary);
    // Two teams that chose the same keeper keep their own choice.
    const other = { ...team, id: 'max' };
    const kept = [kits.normalizeStyle(team, 0), kits.normalizeStyle(other, 1)];
    kits.separateKeepers(kept, [team, other]);
    assert.deepEqual(kept[1].goalkeeper.primary, kept[0].goalkeeper.primary);
});

test('Progress counts the matches the server expects, so it never falls back as rounds are drawn', () => {
    // A Swiss of six schedules three matches a round, and the server expects nine in all.
    const first = layout.progressShare({ state: 'running', played: 2, scheduled: 3, expected: 9 });
    const second = layout.progressShare({ state: 'running', played: 3, scheduled: 6, expected: 9 });
    assert.ok(second >= first, [first, second]);
    assert.equal(second, 3 / 9);
    // A replay beyond what the server expected counts in the schedule instead.
    assert.equal(layout.progressShare({ state: 'running', played: 9, scheduled: 10, expected: 9 }), 0.9);
    assert.equal(layout.progressShare({ state: 'running', played: 0, scheduled: 0 }), 0);
});

test('A canceled tournament has nothing to play next and reads its open fixtures as canceled', () => {
    const matches = [
        { key: 'a', home: 0, away: 1, state: 'done', result: { score: [1, 0] } },
        { key: 'b', home: 2, away: 3, state: 'ready', result: null },
    ];
    assert.deepEqual(layout.upNext({ state: 'running', matches }).map((m) => m.key), ['b']);
    assert.deepEqual(layout.upNext({ state: 'cancelled', matches }), []);
    assert.deepEqual(layout.upNext({ state: 'done', matches }), []);
    // A match that waits to be watched still comes up after the end.
    const unseen = [{ ...matches[0], state: 'unseen', result: null }, matches[1]];
    assert.deepEqual(layout.upNext({ state: 'cancelled', matches: unseen, spoilers: { unseen: ['a'] } }).map((m) => m.key), ['a']);
    const map = new Map(matches.map((m) => [m.key, m]));
    assert.equal(layout.fixtureState({ state: 'ready', matches: ['b'] }, map, true), 'cancelled');
    assert.equal(layout.fixtureState({ state: 'done', matches: ['a'] }, map, true), 'done');
    assert.equal(layout.STATE_NAMES.cancelled, 'Not played, canceled');
});

test('A ladder and a king of the hill name their own order in the caption of their tables', () => {
    const tiebreakers = ['goal_difference', 'lots'];
    assert.equal(layout.tableCaption('league', tiebreakers), 'Ordered by points, then goal difference, then lots drawn from the tournament seed.');
    assert.equal(layout.tableCaption('ladder', tiebreakers), 'Ordered by place on the ladder.');
    assert.equal(layout.tableCaption('king_of_the_hill', tiebreakers), 'The king first, then by ties won.');
});

test('Made names number from 2 around the given names, as the server names entrants', () => {
    const names = layout.madeNames([
        { name: 'Built-in AI 0.50', own: false },
        { name: 'Built-in AI 0.50', own: false },
        { name: 'Rex 2', own: true },
        { name: 'Rex', own: false },
        { name: 'Rex', own: false },
    ]);
    assert.deepEqual(names, ['Built-in AI 0.50', 'Built-in AI 0.50 2', 'Rex 2', 'Rex', 'Rex 3']);
});

test('Run again takes the stages as given, else drops the settings that the count of entrants made', () => {
    const keys = ['format', 'name', 'bracket_size', 'advance', 'rounds', 'legs'];
    const resolved = { format: 'knockout', name: 'Cup', bracket_size: 4, advance: 1, rounds: 2, legs: 2, entrants: 4 };
    assert.deepEqual(layout.againStages({ stages: [resolved] }, keys), [{ format: 'knockout', name: 'Cup', legs: 2 }]);
    const given = [{ format: 'knockout', name: 'Cup', legs: 2 }];
    const again = layout.againStages({ stages: [resolved], given: { stages: given, defaults: {} } }, keys);
    assert.deepEqual(again, given);
    assert.notEqual(again[0], given[0], 'the draft holds a copy');
});
