// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the flash governor, its counter of general and red flashes, its envelopes and its
// backstop clamp, run from the repository root with `node tests/web/flash.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { performance } from 'node:perf_hooks';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's module
// loads from a copy beside a package file that names it a module.
const folder = mkdtempSync(join(tmpdir(), 'cuju-flash-'));
const inner = join(folder, 'presentation');
mkdirSync(inner);
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/presentation/flash.js', import.meta.url)), join(inner, 'flash.js'));
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const F = await import(pathToFileURL(join(inner, 'flash.js')).href);
const { Envelope, FlashCounter, FlashGovernor, SAFETY_FLASHES, linear, relativeLuminance } = F;

const W = 64;
const H = 36;
const BLACK = [0, 0, 0];
const WHITE = [255, 255, 255];
const RED = [255, 0, 0];
const PINK = [255, 128, 128];

// A frame of the grid in one colour, with a patch of another colour when given.
function frame(background, patch = null, colour = null) {
    const data = new Uint8ClampedArray(W * H * 4);
    for (let y = 0; y < H; y += 1) {
        for (let x = 0; x < W; x += 1) {
            const inside = patch && x >= patch.x && x < patch.x + patch.w && y >= patch.y && y < patch.y + patch.h;
            const c = inside ? colour : background;
            const p = (y * W + x) * 4;
            data[p] = c[0];
            data[p + 1] = c[1];
            data[p + 2] = c[2];
            data[p + 3] = 255;
        }
    }
    return data;
}

// The grey byte whose relative luminance is closest to the level.
function grey(level) {
    let best = 0;
    for (let c = 1; c < 256; c += 1) {
        if (Math.abs(relativeLuminance(c, c, c) - level) < Math.abs(relativeLuminance(best, best, best) - level)) best = c;
    }
    return [best, best, best];
}

// A small seeded random source, so the uneven frame times repeat.
function random(seed) {
    let s = seed >>> 0;
    return () => {
        s = (s + 0x6d2b79f5) >>> 0;
        let t = s;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

// Times of frames over the seconds, even at fps or uneven between 15 and 240 frames a second.
function times(seconds, { fps = 60, uneven = false, seed = 1 } = {}) {
    const out = [];
    if (!uneven) {
        for (let i = 0; i * (1 / fps) <= seconds + 1e-12; i += 1) out.push(i / fps);
        return out;
    }
    const next = random(seed);
    for (let t = 0; t <= seconds; t += Math.exp(Math.log(1 / 240) + next() * (Math.log(1 / 15) - Math.log(1 / 240)))) out.push(t);
    return out;
}

// Shows a frame that alternates between a and b at hz full cycles a second and gathers what the
// counter says. Steady counts are those after the first two seconds.
function alternate(a, b, hz, { seconds = 6, fps = 60, uneven = false, seed = 1 } = {}) {
    const counter = new FlashCounter(W, H);
    const stats = { general: 0, red: 0, steadyGeneralLow: Infinity, steadyRedLow: Infinity, thirdGeneral: null, thirdRed: null, transitions: 0 };
    for (const t of times(seconds, { fps, uneven, seed })) {
        const phase = Math.floor(t * hz * 2 + 1e-9) % 2;
        const r = counter.push(t, phase === 0 ? a : b);
        stats.general = Math.max(stats.general, r.general);
        stats.red = Math.max(stats.red, r.red);
        stats.transitions = Math.max(stats.transitions, r.transitions);
        if (t >= 2) {
            stats.steadyGeneralLow = Math.min(stats.steadyGeneralLow, r.general);
            stats.steadyRedLow = Math.min(stats.steadyRedLow, r.red);
        }
        if (stats.thirdGeneral === null && r.general >= 3) stats.thirdGeneral = t;
        if (stats.thirdRed === null && r.red >= 3) stats.thirdRed = t;
    }
    return stats;
}

test('the safety numbers name the WCAG thresholds', () => {
    assert.deepEqual({ ...SAFETY_FLASHES }, { perSecond: 3, areaFraction: 0.25, fieldDegrees: 10, fieldWidth: 1 / 3, fieldHeight: 1 / 3, version: 1 });
    const c = new FlashCounter(W, H);
    assert.equal(c.fieldCellsX, 21);
    assert.equal(c.fieldCellsY, 12);
    assert.equal(c.limit, 63, 'a quarter of a 21 by 12 field window');
    const tiny = new FlashCounter(2, 2);
    assert.equal(tiny.fieldCellsX, 1, 'a field window is at least one cell');
    assert.equal(tiny.fieldCellsY, 1);
});

test('relative luminance follows the WCAG formula', () => {
    assert.equal(relativeLuminance(255, 255, 255), 1);
    assert.equal(relativeLuminance(0, 0, 0), 0);
    assert.ok(Math.abs(relativeLuminance(128, 128, 128) - 0.21586) < 1e-4, 'mid grey');
    assert.ok(Math.abs(relativeLuminance(255, 0, 0) - 0.2126) < 1e-12, 'pure red');
    assert.ok(Math.abs(linear(10) - 10 / 255 / 12.92) < 1e-12, 'the linear part below the knee');
    assert.ok(Math.abs(F.redValue(255, 0, 0) - 320) < 1e-9);
    assert.ok(F.saturatedRed(255, 0, 0) && !F.saturatedRed(...PINK) && !F.saturatedRed(0, 0, 0));
});

test('full screen black and white counts its flashes', () => {
    const black = frame(BLACK);
    const white = frame(WHITE);
    const slow = alternate(black, white, 2);
    assert.equal(slow.general, 2, '2 Hz is two flashes a second');
    assert.equal(slow.steadyGeneralLow, 2, 'and stays two in every window');
    assert.equal(slow.red, 0, 'black and white hold no red');
    const fast = alternate(black, white, 5);
    assert.equal(fast.general, 5, '5 Hz is five flashes a second');
    assert.ok(fast.steadyGeneralLow >= 4);
    assert.ok(fast.thirdGeneral !== null && fast.thirdGeneral < 1, `the third flash at ${fast.thirdGeneral} s`);
    console.log(`# full screen, 2 Hz ${slow.general} flashes, 5 Hz ${fast.general} flashes, third flash at ${fast.thirdGeneral.toFixed(3)} s`);
});

test('only flashes over more than a quarter of a field window count', () => {
    const black = frame(BLACK);
    const at = (w, h) => alternate(black, frame(BLACK, { x: 30, y: 10, w, h }, WHITE), 5).general;
    assert.equal(at(6, 4), 0, 'a patch a tenth of the width and a tenth of the height');
    assert.equal(at(8, 7), 0, '56 cells, under a quarter of the 252 cells of a field window');
    assert.equal(at(8, 8), 5, '64 cells, over a quarter of a field window');
    assert.equal(at(23, 14), 5, 'a whole field window and a margin');
    assert.equal(at(18, 13), 5, 'a tenth of the screen area covers more than a quarter of a field');
    const split = frame(BLACK, { x: 0, y: 0, w: 4, h: 36 }, WHITE);
    for (let y = 0; y < H; y += 1) {
        for (let x = 40; x < 44; x += 1) split.fill(255, (y * W + x) * 4, (y * W + x) * 4 + 3);
    }
    assert.equal(alternate(black, split, 5).general, 0, 'two thin strips farther apart than a field');
    const rows = frame(BLACK);
    for (let p = 0; p < rows.length; p += 4) {
        if (Math.floor(p / 4 / W) % 2 === 0) rows.fill(255, p, p + 3);
    }
    assert.equal(alternate(black, rows, 5).general, 5, 'every other row flashing covers half of every field');
});

test('small changes and changes between bright levels count none', () => {
    const near = alternate(frame(grey(0.4)), frame(grey(0.45)), 5);
    assert.equal(near.general, 0, 'grey 0.4 to 0.45');
    const bright = [grey(0.82), WHITE];
    assert.ok(relativeLuminance(...bright[0]) > 0.8);
    assert.equal(alternate(frame(bright[0]), frame(bright[1]), 5).general, 0, 'the darker state above 0.8');
    assert.equal(alternate(frame(grey(0.79)), frame(grey(0.82)), 5).general, 0, 'a dark enough state, a small change');
    assert.equal(alternate(frame(grey(0.2)), frame(grey(0.9)), 5).general, 5, 'grey 0.2 to 0.9 flashes');
});

test('a saturated red counts red flashes and a pink does not', () => {
    const red = alternate(frame(BLACK), frame(RED), 5);
    assert.equal(red.red, 5, 'red against black at 5 Hz');
    assert.equal(red.general, 5, 'and it is a general flash too');
    assert.ok(red.thirdRed < 1);
    const pink = alternate(frame(BLACK), frame(PINK), 5);
    assert.equal(pink.red, 0, 'a desaturated pink is no red flash');
    assert.equal(pink.general, 5, 'though a general flash');
    const dull = alternate(frame([60, 0, 0]), frame([75, 0, 0]), 5);
    assert.equal(dull.red, 0, 'a red change of 20 or less');
    console.log(`# red against black ${red.red} red flashes, pink ${pink.red}`);
});

test('uneven frame times count the same flashes within one', () => {
    const black = frame(BLACK);
    const white = frame(WHITE);
    const red = frame(RED);
    const rows = [];
    for (const hz of [2, 3, 5]) {
        const even = alternate(black, white, hz, { seconds: 10 }).general;
        for (const fps of [15, 30, 144, 240]) {
            const got = alternate(black, white, hz, { seconds: 10, fps }).general;
            assert.ok(Math.abs(got - even) <= 1, `${hz} Hz at ${fps} fps counts ${got}, against ${even}`);
        }
        for (const seed of [1, 2, 3, 4, 5]) {
            const got = alternate(black, white, hz, { seconds: 10, uneven: true, seed });
            assert.ok(Math.abs(got.general - even) <= 1, `${hz} Hz uneven seed ${seed} counts ${got.general}, against ${even}`);
            rows.push(`${hz} Hz seed ${seed} ${got.general}`);
        }
        const r = alternate(black, red, hz, { seconds: 10, uneven: true, seed: 9 }).red;
        assert.ok(Math.abs(r - hz) <= 1, `${hz} Hz red uneven counts ${r}`);
    }
    console.log(`# uneven frame times, ${rows.join(', ')}`);
});

test('a slow fade is a transition and no flash', () => {
    const counter = new FlashCounter(W, H);
    const data = new Uint8ClampedArray(W * H * 4);
    let last = null;
    for (let i = 0; i <= 600; i += 1) {
        const t = i / 60;
        const level = Math.round(255 * (0.5 - 0.5 * Math.cos(t * Math.PI / 5)));
        for (let p = 0; p < data.length; p += 4) {
            const shade = Math.min(255, level + (p / 4) % W);
            data[p] = shade;
            data[p + 1] = shade;
            data[p + 2] = shade;
        }
        last = counter.push(t, data);
        assert.equal(last.general, 0);
    }
    assert.ok(last.generalTotal === 0, 'a five second fade up and down');
    counter.reset();
    assert.equal(counter.general, 0);
});

test('an Envelope lets through at most three rises a second', () => {
    const e = new Envelope();
    const rises = [];
    let previous = 0;
    let low = 0;
    let armed = true;
    let peak = 0;
    for (let i = 0; i <= 600; i += 1) {
        const t = i / 60;
        const asked = Math.floor(t * 20 + 1e-9) % 2 === 0 ? 1 : 0;
        const out = e.apply(t, asked);
        assert.ok(out <= asked + 1e-12, 'the envelope never raises a value');
        if (asked < previous) assert.equal(out, asked, 'a fall passes at once');
        if (out < previous) {
            if (peak - out >= 0.1) armed = true;
            if (armed) low = Math.min(low, out);
        }
        if (out > previous && armed && out - low >= 0.1) {
            rises.push(t);
            armed = false;
            peak = out;
            low = out;
        }
        previous = out;
    }
    for (const t of rises) {
        const inWindow = rises.filter((s) => s > t - 1 + 1e-6 && s <= t).length;
        assert.ok(inWindow <= 3, `${inWindow} rises in the second up to ${t}`);
    }
    assert.ok(rises.length >= 27 && rises.length <= 33, `${rises.length} rises over ten seconds`);
    console.log(`# envelope at 10 Hz, ${rises.length} rises over 10 s, most ${Math.max(...rises.map((t) => rises.filter((s) => s > t - 1 + 1e-6 && s <= t).length))} in a second`);

    const steady = new Envelope();
    assert.equal(steady.apply(0, 0.7), 0.7);
    assert.equal(steady.rises, 1, 'one rise, the light coming on');
    for (let i = 1; i <= 300; i += 1) assert.equal(steady.apply(i / 60, 0.7), 0.7, 'a steady value passes');
    assert.equal(steady.rises, 0, 'and no more');

    const ramp = new Envelope();
    for (let i = 0; i <= 180; i += 1) {
        const v = i / 180;
        assert.equal(ramp.apply(i / 60, v), v, 'a slow ramp passes unchanged');
    }
    assert.ok(ramp.rises <= 1, 'a slow ramp is one rise');

    const red = new Envelope();
    for (let i = 0; i < 6; i += 1) {
        red.apply(i * 0.1, 1, i % 2 === 0);
        red.apply(i * 0.1 + 0.05, 0, i % 2 === 0);
    }
    assert.equal(red.redRises, 3, 'red rises keep their own count');
    assert.equal(red.rises, 6);
    assert.equal(red.apply(0.6, 1, true), 0, 'a fourth red rise is held');
    assert.ok(red.held);
    assert.equal(red.apply(0.9, 1, true), 0, 'and stays held');
    assert.equal(red.apply(1.01, 1, true), 1, 'until the window frees a rise');
    const fall = new Envelope({ perSecond: 1 });
    assert.equal(fall.apply(0, 1), 1);
    assert.equal(fall.apply(0.1, 0), 0);
    assert.equal(fall.apply(0.2, 1), 0, 'a second rise in the second is held');
    assert.equal(fall.apply(0.3, 0.5), 0, 'a held channel stays');
    assert.equal(fall.apply(1, 0.5), 0.5, 'and rises once the window frees');
    assert.equal(fall.apply(1.1, 0.2), 0.2, 'falls pass at once');
});

test('a FlashGovernor clamps for a second after the third flash and returns smoothly', () => {
    const g = new FlashGovernor();
    assert.equal(g.envelope('home.light'), g.envelope('home.light', { rise: 0.5 }), 'one envelope per channel');
    const counter = new FlashCounter(W, H);
    const black = frame(BLACK);
    const white = frame(WHITE);
    let start = null;
    let t = 0;
    for (let i = 0; i <= 600; i += 1) {
        t = i / 60;
        const shown = start === null ? (Math.floor(t * 10 + 1e-9) % 2 === 0 ? black : white) : black;
        g.observe(t, counter.push(t, shown));
        if (start === null && g.clamped) start = t;
        else if (start === null) assert.equal(g.factor(t), 1, 'no clamp before the third flash');
        if (start !== null && t > start + 2) break;
    }
    assert.ok(start !== null && start < 1, `the clamp starts at ${start} s`);
    assert.equal(g.events.length, 1);
    assert.equal(g.events[0].kind, 'general');
    const until = g.events[0].until;
    assert.ok(until - start >= 1 - 1e-9 && until - start < 1.25, 'one second, at most held on by the last fall');
    assert.equal(g.factor(start), 0.25);
    assert.equal(g.factor(until - 0.01), 0.25);
    let previous = 0.25;
    for (let s = until; s <= until + 0.3; s += 0.01) {
        const f = g.factor(s);
        assert.ok(f >= previous - 1e-12 && f <= 1, 'the return rises smoothly');
        assert.ok(f - previous < 0.06, 'with no jump');
        previous = f;
    }
    assert.equal(g.factor(until + 0.31), 1);
    assert.ok(!g.clamped);
    g.observe(20, { general: 0, red: 3, generalTotal: 0, redTotal: 3 });
    assert.equal(g.events.length, 2);
    assert.equal(g.events[1].kind, 'red', 'red flashes clamp too');
    g.observe(20.1, { general: 0, red: 3, generalTotal: 0, redTotal: 3 });
    assert.equal(g.events[1].until, 21, 'no new flash, no longer clamp');
    for (let i = 0; i < 40; i += 1) g.observe(30 + i * 2, { general: 3, red: 0, generalTotal: 10 + i, redTotal: 3 });
    assert.equal(g.events.length, 32, 'the events keep the last 32');
    g.reset();
    assert.equal(g.events.length, 0);
    assert.equal(g.factor(100), 1);
});

test('a push of a 64 by 36 frame costs well under a millisecond', () => {
    const counter = new FlashCounter(W, H);
    const frames = [frame(BLACK), frame(WHITE), frame(RED), frame(BLACK)];
    const noise = new Uint8ClampedArray(W * H * 4);
    const next = random(7);
    for (let p = 0; p < noise.length; p += 1) noise[p] = Math.floor(next() * 256);
    frames.push(noise);
    for (let i = 0; i < 200; i += 1) counter.push(i / 60, frames[i % frames.length]);
    const result = counter.push(200 / 60, frames[0]);
    const count = 1000;
    const begin = performance.now();
    for (let i = 0; i < count; i += 1) {
        assert.equal(counter.push((201 + i) / 60, frames[i % frames.length]), result);
    }
    const each = (performance.now() - begin) / count;
    console.log(`# push cost ${(each * 1000).toFixed(1)} microseconds a frame over ${count} frames of 64 by 36`);
    assert.ok(each < 1, `${each} ms a push`);
});

// A slot's drawing of width by height pixels in one colour.
function drawing(colour, width = 96, height = 96) {
    const data = new Uint8ClampedArray(width * height * 4);
    for (let p = 0; p < data.length; p += 4) {
        data.set([...colour, 255], p);
    }
    return F.downsample(data, width, height);
}

test('a slot that flashes white and black or red at 30 Hz hides at its third flash and stays hidden', () => {
    for (const bright of [WHITE, RED]) {
        const guard = new F.SlotGuard();
        const frames = [drawing(bright), drawing(BLACK)];
        let hidden = null;
        let flashes = 0;
        for (let i = 0; i < 60; i += 1) {
            guard.draw(frames[i % 2]);
            if (!guard.show(i / 60, true) && hidden === null) {
                hidden = i / 60;
                flashes = Math.max(guard.counter.general, guard.counter.red);
            }
        }
        assert.ok(hidden !== null && hidden < 0.5, `hidden at ${hidden}`);
        assert.equal(flashes, SAFETY_FLASHES.perSecond, 'no fourth flash reaches the screen');
        assert.equal(guard.trips, 1);
        assert.equal(guard.show(hidden + F.SLOT_HOLD - 0.1, true), false, 'held for its seconds');
        guard.draw(drawing(BLACK));
        assert.equal(guard.show(hidden + F.SLOT_HOLD + 1.2, true), true, 'shows again after');
    }
});

test('a slot that stays steady, changes slowly or is shown and hidden once keeps showing', () => {
    const guard = new F.SlotGuard();
    for (let i = 0; i < 240; i += 1) {
        guard.draw(drawing([Math.round((i / 240) * 255), 200, 90]));
        assert.equal(guard.show(i / 60, i > 20), i > 20, `frame ${i}`);
    }
    assert.equal(guard.trips, 0);
    const unread = new F.SlotGuard();
    unread.draw(null);
    assert.equal(unread.show(0, true), false, 'a drawing the page cannot read never shows');
});

test('a slot reads a pattern finer than its cells by the mean of its light', () => {
    // Stripes one pixel wide, white and black, read as the mean of their light in every cell,
    // whichever stripes a cell would sample.
    const width = 96;
    const height = 96;
    const stripes = (phase) => {
        const data = new Uint8ClampedArray(width * height * 4);
        for (let y = 0; y < height; y += 1) {
            for (let x = 0; x < width; x += 1) {
                const v = (x + phase) % 2 ? 255 : 0;
                data.set([v, v, v, 255], (y * width + x) * 4);
            }
        }
        return F.downsample(data, width, height);
    };
    const a = stripes(0);
    const b = stripes(1);
    assert.deepEqual(a, b);
    const mean = relativeLuminance(a[0], a[1], a[2]);
    assert.ok(Math.abs(mean - 0.5) < 0.01, `mean ${mean}`);
    // A white square on black in a quarter of the slot fills the cells it covers.
    const data = new Uint8ClampedArray(width * height * 4);
    for (let y = 0; y < height / 2; y += 1) {
        for (let x = 0; x < width / 2; x += 1) data.set([255, 255, 255, 255], (y * width + x) * 4);
    }
    const out = F.downsample(data, width, height);
    assert.equal(out[0], 255);
    assert.equal(out[(15 * 16 + 15) * 4], 0);
});
