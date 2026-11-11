// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of watching a tournament without spoilers, web/js/core/spoilers.js, which keeps what a
// person has watched in the browser and hides the outcomes of the rest from the lists of
// recordings, run from the repository root with `node tests/web/spoilers.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const folder = mkdtempSync(join(tmpdir(), 'cuju-spoilers-'));
for (const name of ['core/spoilers.js', 'core/i18n.js', 'play/tournament-layout.js']) {
    cpSync(fileURLToPath(new URL(`../../src/cuju/render/web/js/${name}`, import.meta.url)), join(folder, name));
}
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const english = JSON.parse(readFileSync(new URL('../../src/cuju/render/web/languages/en.json', import.meta.url), 'utf8'));

// An English page whose store a test reads and empties.
const stored = new Map();
globalThis.window = {};
globalThis.document = {
    documentElement: { lang: '', dir: '' },
    getElementById: (id) => (id === 'cuju-languages' ? { textContent: JSON.stringify({ en: english }) } : null),
    querySelector: () => null,
    querySelectorAll: () => [],
};
globalThis.localStorage = {
    getItem: (key) => (stored.has(key) ? stored.get(key) : null),
    setItem: (key, value) => stored.set(key, String(value)),
    removeItem: (key) => stored.delete(key),
};
globalThis.location = { search: '' };
Object.defineProperty(globalThis, 'navigator', { value: { languages: ['en'], language: 'en' }, configurable: true, writable: true });
globalThis.fetch = async () => ({ ok: false, status: 404, json: async () => ({}) });
const spoilers = await import(pathToFileURL(join(folder, 'core/spoilers.js')).href);
const layout = await import(pathToFileURL(join(folder, 'play/tournament-layout.js')).href);

function fresh() {
    stored.clear();
    spoilers.reloadSpoilers();
}

const summary = (key, extra = {}) => ({
    id: `m-${key}`, title: 'Spring cup, Final, Rex against Max', title_id: 'server.names.tournament',
    teams: ['Rex', 'Max'], team_labels: [null, null], score: [2, 1], scenario: '5_vs_5',
    provenance: { source: 'requested_match', tournament: { id: 'cup-1', key, name: 'Spring cup' } },
    ...extra,
});

test('A tournament hides its outcomes only while it is on, and the browser remembers it', () => {
    fresh();
    assert.equal(spoilers.spoilerFree('cup-1'), false);
    assert.equal(spoilers.hideSummary(summary('0/f/1')).score[0], 2);
    spoilers.setSpoilerFree('cup-1', true);
    // Another visit reads the same state from the store.
    spoilers.reloadSpoilers();
    assert.equal(spoilers.spoilerFree('cup-1'), true);
    assert.equal(spoilers.spoilerFree('cup-2'), false);
    assert.deepEqual(JSON.parse(stored.get('cuju.spoilers'))['cup-1'].watched, []);
});

test('An unwatched recording loses its score, teams and title, and a watched one keeps them', () => {
    fresh();
    spoilers.setSpoilerFree('cup-1', true);
    const hidden = spoilers.hideSummary(summary('0/f/1'));
    assert.equal(hidden.score, null);
    assert.deepEqual(hidden.teams, []);
    assert.equal(hidden.title, 'Spring cup, a match not watched yet');
    assert.equal(hidden.title_id, undefined);
    assert.equal(hidden.spoiler, true);
    // The provenance keeps the tournament and the key, and drops the names of the sides.
    assert.deepEqual(Object.keys(hidden.provenance.tournament).filter((k) => hidden.provenance.tournament[k] !== undefined), ['id', 'key', 'name']);
    spoilers.markWatched('cup-1', '0/f/1');
    assert.deepEqual(spoilers.hideSummary(summary('0/f/1')).score, [2, 1]);
    // A recording of another tournament or of no tournament stays as it is.
    assert.deepEqual(spoilers.hideSummary({ ...summary('x'), provenance: {} }).score, [2, 1]);
    assert.equal(spoilers.hidesOutcome({ tournament: { id: 'cup-1', key: '0/w4-1/1' } }), true);
    assert.equal(spoilers.hidesOutcome({ tournament: { id: 'cup-1', key: '0/f/1' } }), false);
    assert.equal(spoilers.hidesOutcome(null), false);
});

test('A recording known by its identifier alone stays hidden until its match is watched', () => {
    fresh();
    spoilers.setSpoilerFree('cup-1', true);
    spoilers.noteRecordings('cup-1', { '0/w4-1/1': 'm-semi' });
    assert.equal(spoilers.hiddenRecording('m-semi'), true);
    assert.equal(spoilers.hiddenRecording('m-other'), false);
    spoilers.markWatched('cup-1', '0/w4-1/1');
    assert.equal(spoilers.hiddenRecording('m-semi'), false);
    spoilers.setSpoilerFree('cup-1', false);
    spoilers.noteRecordings('cup-1', { '0/w4-2/1': 'm-two' });
    assert.equal(spoilers.hiddenRecording('m-two'), false);
});

test('Predictions score against the results that show', () => {
    fresh();
    spoilers.predict('cup-1', 'a', 'home');
    spoilers.predict('cup-1', 'b', 'draw');
    spoilers.predict('cup-1', 'c', 'away');
    spoilers.predict('cup-1', 'd', 'nonsense');
    assert.equal(spoilers.prediction('cup-1', 'a'), 'home');
    assert.equal(spoilers.prediction('cup-1', 'd'), null);
    const matches = [
        { key: 'a', result: { score: [2, 0] } },
        { key: 'b', result: { score: [0, 1] } },
        { key: 'c', result: null, state: 'unseen' },
    ];
    assert.deepEqual(spoilers.predictionScore('cup-1', matches), { right: 1, scored: 2 });
    assert.deepEqual([[1, 0], [1, 1], [0, 3], null].map(spoilers.outcome), ['home', 'draw', 'away', null]);
    spoilers.predict('cup-1', 'a', null);
    assert.equal(spoilers.prediction('cup-1', 'a'), null);
});

test('A store that cannot be read starts empty and the page works on', () => {
    fresh();
    stored.set('cuju.spoilers', '{not json');
    spoilers.reloadSpoilers();
    assert.equal(spoilers.spoilerFree('cup-1'), false);
    spoilers.setSpoilerFree('cup-1', true);
    assert.equal(JSON.parse(stored.get('cuju.spoilers'))['cup-1'].on, true);
    assert.equal(spoilers.autoplay('cup-1'), false);
    spoilers.setAutoplay('cup-1', true);
    assert.equal(spoilers.autoplay('cup-1'), true);
});

test('A fixture waits to be watched, the final reads as one, and Up next lists what to watch first', () => {
    const matches = new Map([['a', { key: 'a', state: 'unseen' }], ['b', { key: 'b', state: 'ready' }]]);
    assert.equal(layout.fixtureState({ state: 'ready', matches: ['a', 'b'] }, matches), 'unseen');
    assert.equal(typeof layout.STATE_NAMES.unseen, 'string');
    assert.equal(layout.isFinal({ label_id: 'server.tournament.label.final' }), true);
    assert.equal(layout.isFinal({ label_id: 'server.tournament.label.leg', label_values: { match: { id: 'server.tournament.label.grand_final', values: {} }, number: 1 } }), true);
    assert.equal(layout.isFinal({ label_id: 'server.tournament.label.semi_final', label_values: { number: 1 } }), false);
    const entry = {
        spoilers: { unseen: ['s2', 's1'] },
        matches: [
            { key: 's1', home: 0, away: 3, state: 'unseen', result: null },
            { key: 's2', home: 1, away: 2, state: 'unseen', result: null },
            { key: 'f', home: 0, away: 1, state: 'ready', result: null },
            { key: 'x', home: 0, away: 2, state: 'done', result: { score: [1, 0] } },
        ],
    };
    assert.deepEqual(layout.upNext(entry).map((m) => m.key), ['s2', 's1', 'f']);
    assert.deepEqual(layout.upNext(entry, 1).map((m) => m.key), ['s2']);
    assert.deepEqual(layout.upNext(null), []);
});
