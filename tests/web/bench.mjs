// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the table of a benchmark of models, run from the repository root with
// `node tests/web/bench.mjs`. The table, its CSV and its progress follow bench.py on the case that
// tests/support/bench_table.json shares with the Python tests.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = mkdtempSync(join(tmpdir(), 'cuju-bench-'));
const folder = join(root, 'js');
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js', import.meta.url)), folder, { recursive: true });
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/vendor/lucide', import.meta.url)), join(root, 'vendor', 'lucide'), { recursive: true });
writeFileSync(join(root, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(root, { recursive: true, force: true }));
const english = JSON.parse(readFileSync(new URL('../../src/cuju/render/web/languages/en.json', import.meta.url), 'utf8'));
const shared = JSON.parse(readFileSync(new URL('../support/bench_table.json', import.meta.url), 'utf8'));

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
const { benchApi, benchCell, benchCsv, benchJson, benchProgress, benchTable, playingText } = await import(pathToFileURL(join(folder, 'play/bench.js')).href);

const job = shared.document;

test('the table lists the models as chosen, each with a cell for every challenge', () => {
    const { columns, rows } = benchTable(job);
    assert.deepEqual(columns, ['empty_goal_close', 'one_on_one']);
    assert.deepEqual(rows.map((row) => row.team), job.models.map((model) => model.team));
    assert.deepEqual(rows.map((row) => row.cells.map((cell) => cell.state)), [['done', 'done'], ['done', 'done'], ['failed', 'skipped']]);
    assert.deepEqual(rows.map((row) => [row.gold, row.silver, row.bronze, row.score, row.place]), [[1, 1, 0, 75, 1], [0, 2, 0, 73.3, 2], [0, 0, 0, 0, 3]]);
    assert.equal(benchCell(job, 'builtin', 'one_on_one').value, 4);
    assert.equal(benchCell(job, 'builtin', 'corner'), null);
});

test('the CSV equals the one the server writes, with quoted names and one decimal of score', () => {
    assert.equal(benchCsv(job), shared.csv);
    const lines = benchCsv(job).trim().split('\n');
    assert.equal(lines[0], 'model,team,empty_goal_close value,empty_goal_close medal,one_on_one value,one_on_one medal,gold,silver,bronze,score,place');
    assert.match(lines[1], /^"Striker, ""the bold""",/);
    assert.match(lines[3], /,,,,,0,0,0,0\.0,3$/);
});

test('the JSON is the benchmark as the server answers it, and the progress stays within 0 and 1', () => {
    assert.deepEqual(JSON.parse(benchJson(job)), job);
    assert.equal(benchProgress(job), 1);
    assert.equal(benchProgress({ progress: 1.5 }), 1);
    assert.equal(benchProgress({ progress: null }), 0);
    assert.equal(benchApi.csvUrl('b-20261111-120000-abcd'), '/api/challenges/benches/b-20261111-120000-abcd/table.csv');
});

test('a running benchmark shows the cells it has played and leaves the others empty', () => {
    const running = structuredClone(job);
    running.cells[1].state = 'running';
    running.cells[1].value = null;
    const lines = benchCsv(running).trim().split('\n');
    assert.match(lines[1], /,5,gold,,,/);
});

test('a run with players out says how many of its players played', () => {
    // A team of four that played the one on one played with one player, the others out, and the
    // board, the line of the run and the cell of a benchmark all say so in the same words.
    assert.equal(playingText([1, 4]), 'Played with 1 of its 4 players, the others out.');
    assert.equal(playingText([2, 3]), 'Played with 2 of its 3 players, the others out.');
});
