// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the search of a menu by typing, web/js/core/typeahead.js, run from the repository root
// with `node tests/web/typeahead.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const folder = mkdtempSync(join(tmpdir(), 'cuju-typeahead-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/core/typeahead.js', import.meta.url)), join(folder, 'core/typeahead.js'));
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const { fold, typedMatch } = await import(pathToFileURL(join(folder, 'core/typeahead.js')).href);

const labels = ['Every team', 'Single Eleven', "GRF's built-in AI", 'émile ärzte', 'Several Eleven',
    'Single Five', 'Équipe São Ñandú', 'Several Five'];

test('case and accents never matter', () => {
    assert.equal(fold('Équipe São Ñandú'), 'equipe sao nandu');
    assert.equal(fold('ÄRZTE'), 'arzte');
    // Typing e or E reaches every name that starts with an e, written with an accent or without.
    const reached = [];
    let at = 0;
    for (let k = 0; k < 3; k++) {
        at = typedMatch(labels, at, k % 2 ? 'E' : 'e');
        reached.push(labels[at]);
    }
    assert.deepEqual(reached, ['émile ärzte', 'Équipe São Ñandú', 'Every team']);
    assert.equal(labels[typedMatch(labels, 0, 'equ')], 'Équipe São Ñandú');
    assert.equal(labels[typedMatch(labels, 0, 'ÉQU')], 'Équipe São Ñandú');
});

test('letters typed together find a name by more than its first letter', () => {
    // The first letter goes to the first name with an s, the next ones narrow the word.
    assert.equal(labels[typedMatch(labels, 0, 's')], 'Single Eleven');
    assert.equal(labels[typedMatch(labels, 1, 'se')], 'Several Eleven');
    assert.equal(labels[typedMatch(labels, 4, 'sev')], 'Several Eleven');
    // A space belongs to the word, so two words of a name pick between Single Eleven and Five.
    assert.equal(labels[typedMatch(labels, 1, 'single f')], 'Single Five');
    assert.equal(labels[typedMatch(labels, 1, 'several f')], 'Several Five');
    // A word that no name starts with finds nothing, and the focus stays.
    assert.equal(typedMatch(labels, 1, 'sx'), -1);
    assert.equal(typedMatch([], 0, 's'), -1);
    assert.equal(typedMatch(labels, 0, ''), -1);
});

test('the same letter again moves on through the names that start with it', () => {
    assert.equal(labels[typedMatch(labels, 1, 'ss')], 'Several Eleven');
    assert.equal(labels[typedMatch(labels, 4, 'sss')], 'Single Five');
    assert.equal(labels[typedMatch(labels, 7, 'ssss')], 'Single Eleven');
    // From no item at all, the first name that starts with the letter.
    assert.equal(labels[typedMatch(labels, -1, 'g')], "GRF's built-in AI");
});
