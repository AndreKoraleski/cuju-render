// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the end of a recording and of the episode that statistics describe, run from the
// repository root with `node tests/web/episodes.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from a copy beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-episodes-'));
for (const name of ['recording/episodes.js', 'recording/format.js', 'recording/codec.js', 'core/i18n.js']) {
    cpSync(fileURLToPath(new URL(`../../src/cuju/render/web/js/${name}`, import.meta.url)), join(folder, name));
}
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const { fullMatch, summaryRange } = await import(pathToFileURL(join(folder, 'recording/episodes.js')).href);

// A store of frames with the given steps and flags, starting at index `first`.
function store(frames, first = 0) {
    const items = frames.map(([step, flags = 0]) => ({ step, flags }));
    return { first, last: first + items.length - 1, get: (i) => items[i - first] };
}

test('Full time needs a header that names a full match', () => {
    assert.equal(fullMatch({ full_match: true }), true);
    assert.equal(fullMatch({ full_match: false }), false);
    // A recording without timing fields ends its episode as End of episode.
    assert.equal(fullMatch({}), false);
    assert.equal(fullMatch(null), false);
});

test('a live source without a completed episode describes the current one', () => {
    assert.deepEqual(summaryRange(store([[1], [2], [3], [4]], 10)), { first: 10, last: 13 });
});

test('automatic resets choose the latest completed episode by its start flag', () => {
    // The step that ends an episode shows the next kick off with flag 2.
    const frames = store([[5], [6], [7], [0, 2], [1], [2], [3], [0, 2], [1], [2]], 20);
    assert.deepEqual(summaryRange(frames), { first: 23, last: 26 });
});

test('an end flag closes an episode without automatic resets', () => {
    const ended = store([[1], [2], [3, 1], [0], [1], [2]]);
    assert.deepEqual(summaryRange(ended), { first: 0, last: 2 });
    // A source whose last frame ends an episode describes that episode.
    const last = store([[7], [8, 1], [0], [1], [2, 1]]);
    assert.deepEqual(summaryRange(last), { first: 2, last: 4 });
});

test('a completed episode of one frame leaves the current one', () => {
    const frames = store([[9], [0, 2], [1], [2]]);
    assert.deepEqual(summaryRange(frames), { first: 1, last: 3 });
});
