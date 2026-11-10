// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the voices of one-shot sounds, their fade on a seek and their limit, run from the
// repository root with `node tests/web/voices.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from copies beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-voices-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/broadcast/voices.js', import.meta.url)), join(folder, 'broadcast/voices.js'));
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const { MAX_VOICES, Voices } = await import(pathToFileURL(join(folder, 'broadcast/voices.js')).href);

// A stand-in for an AudioContext, its gains record where they ramp and whether they connect.
function fakeContext() {
    const param = (value) => ({
        value,
        ramps: [],
        cancelScheduledValues() {},
        setValueAtTime(v) {
            this.value = v;
        },
        linearRampToValueAtTime(v, t) {
            this.ramps.push([v, t]);
        },
    });
    const node = () => ({
        outs: [],
        connect(other) {
            this.outs.push(other);
            return other;
        },
        disconnect() {
            this.outs = [];
        },
    });
    return {
        currentTime: 10,
        createGain() {
            return { ...node(), gain: param(1) };
        },
        node,
        source(duration) {
            return { ...node(), buffer: { duration }, playbackRate: { value: 1 }, stopped: null, stop(t) {
                this.stopped = t;
            } };
        },
    };
}

test('a seek fades every voice and stops its sources, the beds stay', () => {
    const ctx = fakeContext();
    const voices = new Voices();
    const bed = ctx.node();
    // A bed routes outside any voice and comes back as it is.
    assert.equal(voices.tap(ctx, bed), bed);
    const src = ctx.source(2);
    let out = null;
    const got = voices.run(ctx, () => {
        out = voices.tap(ctx, src, src);
        return 'played';
    });
    assert.equal(got, 'played');
    assert.notEqual(out, src);
    assert.deepEqual(src.outs, [out]);
    assert.equal(voices.count(ctx.currentTime), 1);
    voices.stopAll(ctx);
    assert.equal(voices.count(ctx.currentTime), 0);
    assert.deepEqual(out.gain.ramps.at(-1)[0], 0);
    assert.ok(out.gain.ramps.at(-1)[1] <= ctx.currentTime + 0.1);
    assert.ok(src.stopped !== null && src.stopped <= ctx.currentTime + 0.2);
});

test('a sound that a voice puts off for later never plays after a seek', () => {
    const ctx = fakeContext();
    const voices = new Voices();
    let later = null;
    let runs = 0;
    voices.run(ctx, () => {
        voices.tap(ctx, ctx.node());
        later = voices.later(() => {
            runs++;
            // The sound put off joins its voice.
            assert.ok(voices.current);
        });
    });
    later();
    assert.equal(runs, 1);
    voices.stopAll(ctx);
    later();
    assert.equal(runs, 1);
    // Outside a voice a function stays as it is.
    const plain = () => 7;
    assert.equal(voices.later(plain), plain);
});

test('a burst keeps at most the limit of voices, the oldest end first', () => {
    const ctx = fakeContext();
    const voices = new Voices();
    const outs = [];
    for (let i = 0; i < MAX_VOICES + 5; i++) {
        voices.run(ctx, () => {
            const src = ctx.source(3);
            outs.push(voices.tap(ctx, src, src));
        });
        ctx.currentTime += 0.01;
    }
    assert.equal(voices.count(ctx.currentTime), MAX_VOICES);
    // The five oldest faded out, the newest still sound.
    for (let i = 0; i < 5; i++) {
        assert.equal(outs[i].gain.ramps.at(-1)[0], 0);
    }
    for (let i = 5; i < outs.length; i++) {
        assert.equal(outs[i].gain.ramps.length, 0);
    }
    // Voices that ended free their places without a fade.
    ctx.currentTime += 10;
    voices.run(ctx, () => voices.tap(ctx, ctx.node()));
    assert.equal(voices.count(ctx.currentTime), 1);
    assert.equal(outs.at(-1).gain.ramps.length, 0);
});

test('a call inside a voice joins it, and a voice that never sounds takes no place', () => {
    const ctx = fakeContext();
    const voices = new Voices();
    voices.run(ctx, () => {
        voices.tap(ctx, ctx.node());
        voices.run(ctx, () => voices.tap(ctx, ctx.node()));
    });
    voices.run(ctx, () => null);
    assert.equal(voices.count(ctx.currentTime), 1);
    assert.equal(voices.list[0].gains.length, 2);
});
