// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the shared picture sizes, the layout and safe areas of a picture of fixed size and the
// address and pacing of the clean feed, run from the repository root with
// `node tests/web/feed.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from a copy beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-feed-'));
for (const name of ['export/sizes.js', 'export/feed-params.js', 'export/feed.js', 'export/safe-frame.js', 'core/i18n.js']) {
    cpSync(fileURLToPath(new URL(`../../src/cuju/render/web/js/${name}`, import.meta.url)), join(folder, name));
}
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const load = (name) => import(pathToFileURL(join(folder, name)).href);
const sizes = await load('export/sizes.js');
const params = await load('export/feed-params.js');
const feed = await load('export/feed.js');

test('every preset and alias names its size, and other text is refused with what fits', () => {
    const expected = {
        '480p': [854, 480], '720p': [1280, 720], '1080p': [1920, 1080], '1440p': [2560, 1440], '4k': [3840, 2160],
        square: [1080, 1080], portrait: [1080, 1350], vertical: [1080, 1920],
    };
    assert.deepEqual(sizes.SIZE_PRESETS.map((p) => p.id), Object.keys(expected));
    for (const [id, [width, height]] of Object.entries(expected)) {
        assert.deepEqual(sizes.parseSize(id), { width, height }, id);
        assert.equal(sizes.sizeName(width, height), id);
    }
    assert.deepEqual(sizes.parseSize(' 2160P '), { width: 3840, height: 2160 });
    assert.deepEqual(sizes.parseSize('tall'), { width: 1080, height: 1920 });
    assert.deepEqual(sizes.parseSize('360p'), { width: 640, height: 360 });
    assert.deepEqual(sizes.parseSize('1000 x 1000'), { width: 1000, height: 1000 });
    assert.deepEqual(sizes.parseSize('2160x3840'), { width: 2160, height: 3840 });
    assert.equal(sizes.sizeName(1000, 1000), '1000x1000');
    for (const text of ['', 'big', '1280', '89x720', '3841x100', '3840x3840', '12.5x100', null]) {
        assert.throws(() => sizes.parseSize(text), RangeError, String(text));
    }
    assert.throws(() => sizes.parseSize('1281x720', { even: true }), /even/);
    assert.doesNotThrow(() => sizes.parseSize('1281x720'));
});

test('the layout keeps the shorter side at 720 and scales the graphics', () => {
    assert.deepEqual(sizes.layoutFor(1920, 1080), { width: 1280, height: 720, scale: 1.5 });
    assert.deepEqual(sizes.layoutFor(3840, 2160), { width: 1280, height: 720, scale: 3 });
    assert.deepEqual(sizes.layoutFor(1080, 1920), { width: 720, height: 1280, scale: 1.5 });
    assert.deepEqual(sizes.layoutFor(1080, 1080), { width: 720, height: 720, scale: 1.5 });
    assert.deepEqual(sizes.layoutFor(854, 480), { width: 854, height: 480, scale: 1 });
    const larger = sizes.layoutFor(1920, 1080, 1.5);
    assert.deepEqual([larger.width, larger.height, larger.scale], [853, 480, 2.25]);
    const smaller = sizes.layoutFor(1280, 720, 0.5);
    assert.deepEqual([smaller.width, smaller.height], [2560, 1440]);
    assert.equal(sizes.layoutFor(1280, 720, 9).scale, 2);
    assert.equal(sizes.parseGraphicsScale(''), 1);
    assert.equal(sizes.parseGraphicsScale('1.25'), 1.25);
    for (const text of ['0.4', '2.5', 'big']) {
        assert.throws(() => sizes.parseGraphicsScale(text), /from 0.5 to 2/);
    }
});

test('the safe area keeps a margin on every side, more for a tall picture and for social apps', () => {
    assert.deepEqual(sizes.safeArea(1280, 720), { top: 36, right: 64, bottom: 36, left: 64 });
    assert.deepEqual(sizes.safeArea(720, 1280), { top: 76.8, right: 36, bottom: 102.4, left: 36 });
    assert.deepEqual(sizes.safeArea(720, 720, 'none'), { top: 0, right: 0, bottom: 0, left: 0 });
    assert.deepEqual(sizes.safeArea(1000, 500, 10), { top: 50, right: 100, bottom: 50, left: 100 });
    const social = sizes.safeArea(720, 1280, 'social');
    assert.ok(social.bottom > social.top && social.right > social.left, JSON.stringify(social));
    for (const [w, h] of [[1280, 720], [720, 720], [720, 900], [720, 1280], [2560, 720]]) {
        for (const mode of ['auto', 'social', 0, 25]) {
            const m = sizes.safeArea(w, h, mode);
            assert.ok(m.left + m.right < w * 0.6 && m.top + m.bottom < h * 0.6, `${w}x${h} ${mode}`);
        }
    }
    assert.equal(sizes.shapeOf(1280, 720), 'wide');
    assert.equal(sizes.shapeOf(720, 720), 'square');
    assert.equal(sizes.shapeOf(1080, 1350), 'tall');
    assert.equal(sizes.shapeOf(720, 1280), 'tall');
    assert.equal(sizes.parseSafe(''), 'auto');
    assert.equal(sizes.parseSafe('Social'), 'social');
    assert.equal(sizes.parseSafe('7.5%'), 7.5);
    for (const text of ['wide', '-1', '30']) {
        assert.throws(() => sizes.parseSafe(text), /safe area/);
    }
});

test('a feed address reads into options, with defaults in place of values out of place', () => {
    const plain = params.parseFeed('');
    assert.deepEqual(plain.problems, []);
    assert.equal(plain.options.source, 'auto');
    assert.deepEqual([plain.options.width, plain.options.height, plain.options.size], [1920, 1080, '1080p']);
    assert.deepEqual(plain.options.layout, { width: 1280, height: 720, scale: 1.5 });
    assert.equal(plain.options.background, '#000000');
    assert.equal(plain.options.audio, false);
    const tall = params.parseFeed('?source=live:Evaluation&size=vertical&scale=1.25&safe=social&bg=transparent&audio&volume=0.3&fps=30&camera=ball&loop=1&broadcast=0&time=dusk&arena=neon');
    assert.deepEqual(tall.problems, []);
    const o = tall.options;
    assert.deepEqual(o.sourceParsed, { kind: 'live', id: 'Evaluation' });
    assert.deepEqual([o.width, o.height, o.scale, o.safe, o.background], [1080, 1920, 1.25, 'social', 'transparent']);
    assert.deepEqual([o.audio, o.volume, o.fps, o.camera, o.loop, o.broadcast, o.time, o.arena], [true, 0.3, 30, 'ball', true, false, 19, 'neon']);
    const sized = params.parseFeed('size=720p&w=1000&h=1000');
    assert.deepEqual([sized.options.width, sized.options.height, sized.options.size], [1000, 1000, '1000x1000']);
    const wrong = params.parseFeed('source=../x&size=huge&scale=7&bg=chartreuse&fps=61&camera=free&volume=2&audio=maybe');
    assert.equal(wrong.problems.length, 8);
    assert.equal(wrong.options.source, 'auto');
    assert.deepEqual([wrong.options.width, wrong.options.scale, wrong.options.bg, wrong.options.fps], [1920, 1, 'black', 0]);
    assert.equal(params.parseFeed('bg=1a2b3c').options.background, '#1a2b3c');
    assert.equal(params.parseFeed('bg=%23abc').options.background, '#aabbcc');
    assert.deepEqual(params.parseSource('m-20261106-105640-3a3f'), { kind: 'recording', id: 'm-20261106-105640-3a3f' });
    assert.deepEqual(params.parseSource('Tournament:t-1'), { kind: 'tournament', id: 't-1' });
    for (const text of ['recording:', 'queue:x', 'a b', '../up']) {
        assert.throws(() => params.parseSource(text), RangeError, text);
    }
});

test('a written address names the source, the size and the options that differ from the defaults', () => {
    assert.equal(params.feedQuery({}), 'source=auto&size=1080p');
    assert.equal(params.feedQuery({ source: 'live:Evaluation', width: 1080, height: 1920, bg: 'transparent', audio: true, fps: 30 }),
        'source=live:Evaluation&size=vertical&bg=transparent&audio=1&fps=30');
    assert.equal(params.feedAddress('http://127.0.0.1:8780/', { source: 'queue', size: '4k', scale: 0.75, safe: 'none', loop: true }),
        'http://127.0.0.1:8780/feed?source=queue&size=4k&scale=0.75&safe=none&loop=1');
    const round = params.parseFeed(params.feedQuery({ source: 'tournament:t-1', width: 1000, height: 1000, safe: 5, time: 19 }));
    assert.deepEqual(round.problems, []);
    assert.deepEqual([round.options.source, round.options.size, round.options.safe, round.options.time], ['tournament:t-1', '1000x1000', 5, 19]);
});

test('the frame gate keeps an even pace below the display and recovers from a stall', () => {
    assert.equal(feed.frameGate(0), null);
    const gate = feed.frameGate(30);
    const drawn = [];
    for (let i = 0; i <= 60; i++) {
        const t = i * (1000 / 60) + (i % 3 === 0 ? 0.6 : -0.4);
        if (gate(t)) {
            drawn.push(i);
        }
    }
    assert.equal(drawn.length, 31);
    assert.ok(drawn.every((v, i) => v === i * 2), drawn.join(' '));
    assert.equal(gate(5000), true);
    assert.equal(gate(5010), false);
    assert.equal(gate(5034), true);
    const all = feed.frameGate(60);
    let count = 0;
    for (let i = 0; i < 120; i++) {
        count += all(i * (1000 / 60)) ? 1 : 0;
    }
    assert.equal(count, 120);
});

test('the feed opens, waits, retries, restarts and rests on the slate as its source asks', () => {
    const step = (o) => feed.nextStep({ following: true, loop: false, failed: false, heldFor: 0, finished: false, ...o });
    const match = { kind: 'match', id: 'm-1' };
    const other = { kind: 'match', id: 'm-2' };
    const live = { kind: 'live', id: 'live-1' };
    const none = { kind: 'none', id: '' };
    assert.equal(step({ target: none, current: null }), 'slate');
    assert.equal(step({ target: match, current: null }), 'open');
    assert.equal(step({ target: match, current: match }), 'wait');
    assert.equal(step({ target: other, current: match }), 'wait');
    assert.equal(step({ target: other, current: match, finished: true }), 'open');
    assert.equal(step({ target: match, current: match, finished: true, loop: true }), 'restart');
    assert.equal(step({ target: match, current: match, finished: true, heldFor: 1000 }), 'wait');
    assert.equal(step({ target: match, current: match, finished: true, heldFor: 7000 }), 'slate');
    assert.equal(step({ target: match, current: match, finished: true, heldFor: 7000, following: false }), 'wait');
    assert.equal(step({ target: live, current: live, finished: true, failed: true }), 'retry');
    assert.equal(step({ target: live, current: live, finished: true, failed: false, heldFor: 7000 }), 'slate');
    assert.equal(step({ target: none, current: live, finished: true, heldFor: 7000 }), 'slate');
    assert.equal(step({ target: none, current: live, finished: false }), 'wait');
    assert.equal(step({ target: { kind: 'live', id: 'live-2' }, current: live, finished: true }), 'open');
    assert.equal(feed.sameTarget(match, { ...match, title: 'x' }), true);
    assert.equal(feed.sameTarget(match, live), false);
});

test('the frame of a feed takes the color scheme of its page', () => {
    assert.equal(params.frameScheme('dark'), 'dark');
    assert.equal(params.frameScheme('light'), 'light');
    assert.equal(params.frameScheme(undefined), 'dark');
    assert.equal(params.frameScheme(params.parseFeed('?theme=light').options.theme), 'light');
});

test('the Copy feed address dialog offers each live source and tournament of the server', () => {
    const rows = [
        { source: 'auto', label: 'a live source while one streams' },
        { source: 'live', label: 'the newest live source' },
        { source: 'live:Evaluation', label: 'the live source Evaluation' },
        { source: 'tournament:cup-1', label: 'the matches of the tournament Cup' },
        { source: 'recording:m-1', label: 'a recording' },
    ];
    assert.deepEqual(params.namedSources(rows, ['auto', 'live:Evaluation']), [
        ['tournament:cup-1', 'The matches of the tournament Cup'],
    ]);
    assert.deepEqual(params.namedSources(rows).map(([source]) => source), ['live:Evaluation', 'tournament:cup-1']);
    assert.deepEqual(params.namedSources(null), []);
    assert.deepEqual(params.namedSources([{ source: 'live:live-1' }]), [['live:live-1', 'live:live-1']]);
});

test('a newer live source replaces a stream that lost its connection', () => {
    const step = (o) => feed.nextStep({ following: true, loop: false, failed: false, heldFor: 0, finished: false, ...o });
    const live = { kind: 'live', id: 'live-1' };
    const newer = { kind: 'live', id: 'live-2' };
    assert.equal(step({ target: newer, current: live }), 'wait');
    assert.equal(step({ target: newer, current: live, stalled: true }), 'open');
    // The stream that reconnects stays while the server names it still.
    assert.equal(step({ target: live, current: live, stalled: true }), 'wait');
    assert.equal(step({ target: { kind: 'match', id: 'm-1' }, current: live, stalled: true }), 'wait');
});
