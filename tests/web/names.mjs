// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the names and titles that the server makes, as web/js/core/names.js shows them in the
// language of the page, run from the repository root with `node tests/web/names.mjs`. The page
// loads as a Portuguese page, with the shipped languages in it.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const folder = mkdtempSync(join(tmpdir(), 'cuju-names-'));
for (const name of ['core/names.js', 'core/scenarios.js', 'core/i18n.js']) {
    cpSync(fileURLToPath(new URL(`../../src/cuju/render/web/js/${name}`, import.meta.url)), join(folder, name));
}
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const languages = new URL('../../src/cuju/render/web/languages/', import.meta.url);
const read = (code) => JSON.parse(readFileSync(new URL(`${code}.json`, languages), 'utf8'));
const shipped = { en: read('en'), pt: read('pt') };

// A Portuguese page, its stored choice pt, whose manifest link the runtime points at the language.
const manifest = { href: 'manifest.webmanifest', setAttribute(key, value) { this[key] = value; } };
globalThis.window = {};
globalThis.document = {
    documentElement: { lang: '', dir: '' },
    getElementById: (id) => (id === 'cuju-languages' ? { textContent: JSON.stringify(shipped) } : null),
    querySelector: (selector) => (selector === 'link[rel="manifest"]' ? manifest : null),
    querySelectorAll: () => [],
};
globalThis.localStorage = { getItem: (key) => (key === 'cuju.language' ? '"pt"' : null), setItem() {}, removeItem() {} };
globalThis.location = { search: '' };
Object.defineProperty(globalThis, 'navigator', { value: { languages: ['pt-BR'], language: 'pt-BR' }, configurable: true, writable: true });
globalThis.fetch = async () => ({ ok: false, status: 404, json: async () => ({}) });
const i18n = await import(pathToFileURL(join(folder, 'core/i18n.js')).href);
const names = await import(pathToFileURL(join(folder, 'core/names.js')).href);
const scenarios = await import(pathToFileURL(join(folder, 'core/scenarios.js')).href);
const pt = (id) => shipped.pt[id];
const label = (id, values = {}) => ({ id, text: shipped.en[id], values });

test('the page is Portuguese and its manifest asks for the language', () => {
    assert.equal(i18n.language().code, 'pt');
    assert.equal(manifest.href, 'manifest.webmanifest?lang=pt');
});

test('a team of the server shows its made name in the language, a given name as given', () => {
    const builtin = { id: 'builtin', name: "GRF's built-in AI", name_id: 'server.names.builtin', name_values: {} };
    assert.equal(names.teamName(builtin), pt('server.names.builtin'));
    assert.equal(names.teamName({ name: 'Rule bot' }), 'Rule bot');
    // A recording of before keeps its English text.
    assert.equal(names.teamName({ name: 'Left' }), 'Left');
    assert.equal(names.teamName({ name: 'Left', name_id: 'server.names.left', name_values: {} }), 'Esquerda');
    const you = label('server.names.person_with', { person: label('server.names.you'), team: 'Rule bot' });
    assert.equal(names.teamName({ name: 'You with Rule bot', name_id: you.id, name_values: you.values }), 'Você com Rule bot');
    assert.equal(names.teamName(null), '');
});

test('the teams of a summary show their labels and keep a given name', () => {
    const summary = { teams: ["GRF's built-in AI", 'Rex'], team_labels: [label('server.names.builtin'), null] };
    assert.deepEqual(names.summaryTeams(summary), [pt('server.names.builtin'), 'Rex']);
    assert.deepEqual(names.summaryTeams({ teams: ['Left', 'Right'] }), ['Left', 'Right']);
});

test('a title of the server shows in the language, nested labels and values included', () => {
    const against = label('server.names.against', { left: label('server.names.you'), right: label('server.names.builtin') });
    const entry = { title: "You against GRF's built-in AI", title_id: against.id, title_values: against.values };
    assert.equal(names.recordingTitle(entry), `Você contra ${pt('server.names.builtin')}`);
    const scenario = { kind: 'scenario', name: '5_vs_5', text: '5_vs_5' };
    const recorder = { title: '5_vs_5, environment 2', title_id: 'server.names.recorder', title_values: { scenario, environment: '2' }, scenario: '5_vs_5' };
    assert.ok(!names.recordingTitle(recorder).includes('5_vs_5'), names.recordingTitle(recorder));
    assert.ok(names.recordingTitle(recorder).endsWith(', ambiente 2'));
    const challenge = { kind: 'challenge', name: 'empty_goal_close', text: 'Empty goal from close range' };
    const attempt = label('server.names.challenge_attempt', { challenge, attempt: '5', competitor: label('server.names.python_policy') });
    const title = names.recordingTitle({ title: 'x', title_id: attempt.id, title_values: attempt.values });
    assert.equal(title, `${pt('challenge.empty_goal_close.title')}, tentativa 5, ${pt('server.names.python_policy')}`);
    assert.equal(names.recordingTitle({ title: 'Demo, the built-in AI against itself', title_id: 'server.names.demo', title_values: {} }), pt('server.names.demo'));
});

test('a shipped sample shows its title in the language while it keeps the one it ships with', () => {
    assert.equal(names.recordingTitle({ id: 'sample-5v5', title: 'Sample match, 5 vs 5' }), pt('server.names.sample_5v5'));
    assert.equal(names.recordingTitle({ title: 'Sample match, 11 vs 11' }, 'sample-11v11'), pt('server.names.sample_11v11'));
    assert.equal(names.recordingTitle({ id: 'sample-5v5', title: 'My sample' }), 'My sample');
});

test('a title of before keeps its text with its scenario in words', () => {
    assert.equal(names.recordingTitle({ title: 'My match', scenario: '5_vs_5' }), 'My match');
    assert.ok(!names.recordingTitle({ title: '5_vs_5, environment 0', scenario: '5_vs_5' }).startsWith('5_vs_5'));
    assert.equal(names.recordingTitle(null), '');
});

// An object that throws when made text, as JSON with a key toString makes one.
const hostile = () => JSON.parse('{"toString": 1, "valueOf": 2}');

test('a title, scenario or team of a malformed file shows as text and never throws', () => {
    const cases = [[5, '5'], [[1], ''], [{}, ''], [true, 'true'], [{ text: 1 }, ''], [null, ''], [hostile(), ''], [[hostile()], '']];
    for (const [title, shown] of cases) {
        assert.equal(names.recordingTitle({ id: 'm-x', title, scenario: '' }), shown, JSON.stringify(title));
        assert.equal(names.recordingTitle({ id: 'm-x', title, scenario: hostile() }), shown);
        assert.equal(names.recordingTitle({ id: 'm-x', title, title_id: 'server.names.demo', title_values: hostile() }), shown);
        assert.equal(scenarios.titleText(title, [5]), shown);
    }
    for (const scenario of [5, [], {}, hostile(), null]) {
        assert.equal(typeof scenarios.scenarioName(scenario), 'string');
    }
    assert.equal(scenarios.scenarioName(5), '5');
    assert.equal(scenarios.scenarioName({}), '');
    const summary = { teams: [5, hostile(), null, 'Rex'], team_labels: [null, { id: 'server.names.builtin', text: hostile() }, 7, null] };
    assert.deepEqual(names.summaryTeams(summary), ['5', pt('server.names.builtin'), '', 'Rex']);
    assert.deepEqual(names.summaryTeams({ teams: hostile(), team_labels: 5 }), []);
    assert.deepEqual(names.textList([1, 'a', hostile(), null]), ['1', 'a', '', '']);
    assert.deepEqual(names.textList(hostile()), []);
    assert.equal(names.teamName({ name: 'Rex', name_id: hostile(), name_values: hostile() }), 'Rex');
    assert.equal(names.teamName({ name: hostile() }), '');
    const scenario = { kind: 'scenario', name: hostile(), text: hostile() };
    assert.equal(typeof names.recordingTitle({ title: 'x', title_id: 'server.names.recorder', title_values: { scenario, environment: hostile() } }), 'string');
});

test('a title or a name shows a message only of those that recordings carry', () => {
    for (const id of ['format.error.magic', 'home.recordings.title', 'server.origin', 'server.namesx.demo', 'constructor', '__proto__']) {
        assert.equal(names.recordingTitle({ title: 'Mine', title_id: id, title_values: {} }), 'Mine', id);
        assert.equal(names.teamName({ name: 'Rex', name_id: id, name_values: {} }), 'Rex', id);
        assert.deepEqual(names.summaryTeams({ teams: ['Rex'], team_labels: [{ id, text: 'Rex', values: {} }] }), ['Rex']);
    }
    // A label inside the values that names another message shows its English text.
    const against = label('server.names.against', { left: { id: 'format.error.magic', text: 'Lefty', values: {} }, right: label('server.names.you') });
    assert.equal(names.recordingTitle({ title: 'Lefty against You', title_id: against.id, title_values: against.values }), 'Lefty contra Você');
    // The labels of tournaments show in the language.
    const title = label('server.tournament.label.title', {
        tournament: 'Spring cup', match: label('server.tournament.label.final'), home: 'Rex',
        away: label('server.tournament.label.builtin_ability', { ability: '0.80' }),
    });
    assert.equal(names.recordingTitle({ title: 'x', title_id: title.id, title_values: title.values }),
        `Spring cup, ${pt('server.tournament.label.final')}, Rex x ${pt('server.tournament.label.builtin_ability').replace('{ability}', '0,80')}`);
    assert.equal(names.teamName({ name: 'Built-in AI', name_id: 'server.tournament.label.builtin', name_values: {} }), pt('server.tournament.label.builtin'));
});

test('labels nested beyond their depth show their text, however deep', () => {
    let deep = { text: 'a', id: 'server.names.you', values: {} };
    for (let i = 0; i < 200000; i++) {
        deep = { text: 'a', id: 'server.names.against', values: { left: deep, right: 'b' } };
    }
    assert.equal(typeof names.recordingTitle({ title: 'x', title_id: 'server.names.against', title_values: { left: deep, right: 'b' } }), 'string');
    assert.equal(typeof names.teamName({ name: 'x', name_id: 'server.names.person_with', name_values: { person: deep, team: 'b' } }), 'string');
    assert.equal(names.recordingTitle({ title: 'x', title_id: 'nope', title_values: { v: deep } }), 'x');
    // A title of tournament labels a few levels deep shows in full.
    const leg = label('server.tournament.label.leg', { match: label('server.tournament.label.decider', { match: label('server.tournament.label.final') }), number: '2' });
    const person = label('server.names.person_with', { person: label('server.names.you'), team: label('server.names.builtin') });
    const title = label('server.tournament.label.title', { tournament: 'Cup', match: leg, home: person, away: 'Rex' });
    const shown = names.recordingTitle({ title: 'x', title_id: title.id, title_values: title.values });
    assert.ok(shown.startsWith('Cup, ') && shown.endsWith(' x Rex') && shown.includes(pt('server.names.builtin')), shown);
});

test('the summaries of the library list with their fields of the wrong kinds made plain', () => {
    const odd = hostile();
    const list = names.summaryList([
        { id: 'a', title: odd, scenario: 5, notes: odd, folder: [], teams: odd, tags: [odd, 'x'], team_labels: 5,
            score: [1, odd], created: odd, steps: 'x', bytes: NaN, provenance: 5, group: [1], extra: odd },
        { id: 'b', title: 'Fine', teams: ['L', 'R'], team_labels: [null, label('server.names.you')], score: [2, 1], created: 5 },
        null, 5, { title: 'no id' }, { id: 7 },
    ]);
    assert.deepEqual(list.map((m) => m.id), ['a', 'b']);
    const [a, b] = list;
    assert.equal(a.title, '');
    assert.equal(a.scenario, '5');
    assert.equal(a.notes, '');
    assert.equal(a.folder, '');
    assert.deepEqual(a.teams, []);
    assert.deepEqual(a.tags, ['', 'x']);
    assert.equal(a.team_labels, null);
    for (const key of ['score', 'created', 'bytes', 'provenance', 'group']) {
        assert.ok(!(key in a), key);
    }
    assert.equal(a.steps, 'x');
    assert.equal(a.extra, odd);
    assert.equal(names.recordingTitle(a) || a.id, 'a');
    assert.deepEqual(names.summaryTeams(b), ['L', pt('server.names.you')]);
    assert.deepEqual(b.score, [2, 1]);
    assert.deepEqual(names.summaryList({ length: 1, 0: { id: 'x' } }), []);
});
