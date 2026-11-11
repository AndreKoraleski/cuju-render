// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the teasers of the challenge cards, run from the repository root with
// `node tests/web/teasers.mjs`. A card shows its still, plays its teaser for the pointer, the
// keyboard focus or its play button, keeps still under reduced motion until asked, lets one card
// play at a time and falls back to its still or a drawing when files are missing.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the module loads from
// a copy beside a package file that names it a module.
const root = mkdtempSync(join(tmpdir(), 'cuju-teasers-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/play/teasers.js', import.meta.url)), join(root, 'teasers.js'));
writeFileSync(join(root, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(root, { recursive: true, force: true }));
const { TEASER_FOLDER, TeaserCards, loadTeasers, teaserFiles, teaserView } = await import(pathToFileURL(join(root, 'teasers.js')).href);

// A card that remembers what it was last told to show.
function card(id, { still = true, teaser = true } = {}) {
    return {
        id,
        still: still ? `${TEASER_FOLDER}${id}.webp` : null,
        teaser: teaser ? `${TEASER_FOLDER}${id}.mp4` : null,
        shown: [],
        show(view) {
            this.shown.push(view);
        },
        get last() {
            return this.shown[this.shown.length - 1];
        },
    };
}

test('a card shows its still until something asks it to play', () => {
    const cards = new TeaserCards();
    const corner = cards.add(card('corner'));
    assert.deepEqual(corner.last, { picture: 'still', button: true, playing: false });
});

test('the pointer and keyboard focus play the teaser, and leaving both stops it', () => {
    const cards = new TeaserCards();
    const corner = cards.add(card('corner'));
    cards.enter('corner', 'hover');
    assert.equal(corner.last.playing, true);
    cards.enter('corner', 'focus');
    cards.leave('corner', 'hover');
    assert.equal(corner.last.playing, true, 'the focus is still inside');
    cards.leave('corner', 'focus');
    assert.deepEqual(corner.last, { picture: 'still', button: true, playing: false });
    assert.equal(cards.current, null);
});

test('the play button starts and stops the teaser', () => {
    const cards = new TeaserCards();
    const corner = cards.add(card('corner'));
    assert.equal(cards.toggle('corner'), true);
    assert.equal(corner.last.playing, true);
    assert.equal(cards.toggle('corner'), false);
    assert.equal(corner.last.playing, false);
});

test('under reduced motion only the play button plays, and leaving stops it', () => {
    let reduced = true;
    const cards = new TeaserCards({ reduced: () => reduced });
    const corner = cards.add(card('corner'));
    cards.enter('corner', 'hover');
    cards.enter('corner', 'focus');
    assert.equal(corner.last.playing, false);
    assert.equal(corner.last.button, true);
    assert.equal(cards.toggle('corner'), true);
    cards.leave('corner', 'hover');
    assert.equal(corner.last.playing, true, 'the focus keeps the request');
    cards.leave('corner', 'focus');
    assert.equal(corner.last.playing, false);
    // A change of the setting to reduced motion stops a teaser that the pointer started.
    reduced = false;
    cards.enter('corner', 'hover');
    assert.equal(corner.last.playing, true);
    reduced = true;
    cards.refresh();
    assert.equal(corner.last.playing, false);
});

test('one teaser plays at a time', () => {
    const cards = new TeaserCards();
    const corner = cards.add(card('corner'));
    const duel = cards.add(card('one_on_one'));
    cards.enter('corner', 'focus');
    cards.enter('one_on_one', 'hover');
    assert.equal(duel.last.playing, true);
    assert.equal(corner.last.playing, false);
    assert.equal(cards.current, 'one_on_one');
    // The card that stopped forgets why it played, so it stays still once the other stops.
    cards.leave('one_on_one', 'hover');
    assert.equal(corner.last.playing, false);
    assert.equal(cards.current, null);
});

test('a card without a teaser keeps its still, and one without either is drawn', () => {
    const cards = new TeaserCards();
    const still = cards.add(card('corner', { teaser: false }));
    const bare = cards.add(card('empty_goal', { still: false, teaser: false }));
    cards.enter('corner', 'hover');
    assert.equal(cards.toggle('corner'), false);
    assert.deepEqual(still.last, { picture: 'still', button: false, playing: false });
    assert.deepEqual(bare.last, { picture: 'drawn', button: false, playing: false });
});

test('a teaser that fails to load leaves its card on the still', () => {
    const cards = new TeaserCards();
    const corner = cards.add(card('corner'));
    cards.enter('corner', 'hover');
    cards.fail('corner');
    assert.deepEqual(corner.last, { picture: 'still', button: false, playing: false });
    assert.equal(cards.current, null);
});

test('the view follows the reasons and the files', () => {
    assert.deepEqual(teaserView(), { picture: 'drawn', button: false, playing: false });
    assert.equal(teaserView({ still: true, teaser: true, reasons: ['focus'] }).playing, true);
    assert.equal(teaserView({ still: true, teaser: true, reduced: true, reasons: ['focus', 'hover'] }).playing, false);
    assert.equal(teaserView({ teaser: true, reduced: true, reasons: ['request'] }).playing, true);
});

test('the manifest names plain files of the folder alone', () => {
    const files = teaserFiles({ challenges: {
        corner: { teaser: 'corner.mp4', still: 'corner.webp' },
        duel: { teaser: '../secret.mp4', still: 'duel.webp' },
        bad: { teaser: 'bad.webm', still: 'https://example.com/bad.webp' },
        empty: null,
    } });
    assert.deepEqual(files, {
        corner: { teaser: `${TEASER_FOLDER}corner.mp4`, still: `${TEASER_FOLDER}corner.webp` },
        duel: { teaser: null, still: `${TEASER_FOLDER}duel.webp` },
    });
    assert.deepEqual(teaserFiles(null), {});
    assert.deepEqual(teaserFiles({ challenges: 'none' }), {});
});

test('a manifest that cannot be read gives no files, and the cards draw their pictures', async () => {
    const files = await loadTeasers(async () => ({ ok: false, json: async () => ({}) }));
    assert.deepEqual(files, {});
});
