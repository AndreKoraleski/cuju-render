// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the loudness and peak safety of the renderer's sound, the meter against the test
// signals of EBU Tech 3341, the true peak, the limiter, the governor and the two AudioWorklet
// processors, run from the repository root with `node tests/web/loudness.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { performance } from 'node:perf_hooks';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from copies beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-loudness-'));
const inner = join(folder, 'presentation');
mkdirSync(inner);
for (const name of ['loudness', 'loudness-worklet']) {
    cpSync(fileURLToPath(new URL(`../../src/cuju/render/web/js/presentation/${name}.js`, import.meta.url)), join(inner, `${name}.js`));
}
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const load = (name) => import(pathToFileURL(join(inner, `${name}.js`)).href);
const L = await load('loudness');
const { Governor, Limiter, LoudnessMeter, TruePeak, dbToGain, gainToDb, kWeighting, measure, sanitize } = L;

// The AudioWorklet scope, enough of it to run the processors in Node.
const registered = {};
globalThis.sampleRate = 48000;
globalThis.AudioWorkletProcessor = class {
    constructor() {
        this.port = {
            messages: [],
            onmessage: null,
            postMessage(message) {
                this.messages.push(message);
            },
        };
    }
};
globalThis.registerProcessor = (name, processor) => {
    registered[name] = processor;
};
await load('loudness-worklet');

// The frames of each push cycle through these sizes, so every test also crosses the boundaries of
// the 25 ms parts and 100 ms hops at many places.
const PIECES = [3001, 4096, 128, 2203, 4799, 1];

const near = (actual, expected, tolerance, message) => {
    assert.ok(Math.abs(actual - expected) <= tolerance, `${message}, read ${actual}, expected ${expected} within ${tolerance}`);
};

// Plays a 1 kHz sine through a meter in pieces. Each segment is {seconds, levels} with one level in
// dBFS per channel, the peak level of the sine. After each piece the callback sees the meter and
// the time played.
function play(meter, segments, { sampleRate = 48000, frequency = 1000, after } = {}) {
    const channels = meter.channels;
    const buffers = [];
    for (let c = 0; c < channels; c += 1) buffers.push(new Float32Array(8192));
    const views = new Array(channels);
    let n = 0;
    let piece = 0;
    const w = (2 * Math.PI * frequency) / sampleRate;
    for (const { seconds, levels } of segments) {
        const gains = levels.map(dbToGain);
        const end = n + Math.round(seconds * sampleRate);
        while (n < end) {
            const count = Math.min(PIECES[piece % PIECES.length], end - n);
            piece += 1;
            for (let i = 0; i < count; i += 1) {
                const s = Math.sin(w * (n + i));
                for (let c = 0; c < channels; c += 1) buffers[c][i] = gains[c] * s;
            }
            for (let c = 0; c < channels; c += 1) views[c] = buffers[c].subarray(0, count);
            meter.push(views);
            n += count;
            if (after) after(meter, n / sampleRate);
        }
    }
    return meter;
}

const stereo = (seconds, db) => ({ seconds, levels: [db, db] });

test('the K weighting equals the published 48 kHz coefficients of BS.1770-4', () => {
    const [shelf, highPass] = kWeighting(48000);
    const published = [
        [1.53512485958697, -2.69169618940638, 1.19839281085285, -1.69065929318241, 0.73248077421585],
        [1, -2, 1, -1.99004745483398, 0.99007225036621],
    ];
    [shelf, highPass].forEach((f, i) => {
        assert.equal(f.a[0], 1);
        const got = [...f.b, f.a[1], f.a[2]];
        got.forEach((v, j) => near(v, published[i][j], 1e-6, `stage ${i + 1} coefficient ${j}`));
    });
    const slower = kWeighting(44100);
    assert.notEqual(slower[0].b[0], shelf.b[0], 'another rate derives other coefficients');
});

test('gains, levels and sanitize', () => {
    near(dbToGain(-6), 0.501187, 1e-6, 'gain of -6 dB');
    near(gainToDb(0.5), -6.0206, 1e-4, 'level of a half');
    assert.equal(gainToDb(0), -Infinity);
    const a = Float32Array.from([1, NaN, -Infinity, 0.5, Infinity]);
    assert.equal(sanitize(a), 3);
    assert.deepEqual(Array.from(a), [1, 0, 0, 0.5, 0]);
    const silent = new LoudnessMeter(48000, 2);
    assert.equal(silent.momentary(), -Infinity);
    assert.equal(silent.shortTerm(), -Infinity);
    assert.equal(silent.integrated(), -Infinity);
    assert.equal(silent.truePeak(), -Infinity);
    silent.push([new Float32Array(48000), new Float32Array(48000)]);
    assert.equal(silent.momentary(), -Infinity, 'digital silence reads -Infinity');
});

test('Tech 3341 cases 1 and 2, a stereo sine at -23 and -33 dBFS', () => {
    for (const db of [-23, -33]) {
        const m = play(new LoudnessMeter(48000, 2), [stereo(20, db)]);
        near(m.momentary(), db, 0.1, `case at ${db} momentary`);
        near(m.shortTerm(), db, 0.1, `case at ${db} short-term`);
        near(m.integrated(), db, 0.1, `case at ${db} integrated`);
        near(m.maxMomentary(), db, 0.1, `case at ${db} largest momentary`);
        near(m.maxShortTerm(), db, 0.1, `case at ${db} largest short-term`);
    }
});

test('Tech 3341 cases 3, 4 and 5, the relative and absolute gates', () => {
    const cases = [
        [stereo(10, -36), stereo(60, -23), stereo(10, -36)],
        [stereo(10, -72), stereo(10, -36), stereo(60, -23), stereo(10, -36), stereo(10, -72)],
        [stereo(20, -26), stereo(20.1, -20), stereo(20, -26)],
    ];
    cases.forEach((segments, i) => near(play(new LoudnessMeter(48000, 2), segments).integrated(), -23, 0.1, `case ${i + 3}`));
});

// Tech 3341 case 6 plays the sine at -28 dBFS in the left and right channels, -24 dBFS in the
// centre and -30 dBFS in both surrounds. With the weights one, one, one, 1.41 and 1.41 the sum of
// the mean squares is 2 times 10 to the -2.8 plus 10 to the -2.4 plus 2.82 times 10 to the -3,
// which is the stereo -23 dBFS sum of 2 times 10 to the -2.3 less 0.02 dB, so the reading is
// -23.02 LUFS.
test('Tech 3341 case 6, five channels with their weights', () => {
    const m = play(new LoudnessMeter(48000, 5), [{ seconds: 20, levels: [-28, -28, -24, -30, -30] }]);
    near(m.integrated(), -23, 0.1, 'case 6');
    assert.deepEqual(Array.from(m.weights), [1, 1, 1, 1.41, 1.41]);
});

// Tech 3341 case 9 alternates 1.34 s at -20 dBFS and 1.66 s at -30 dBFS, so every window of 3 s
// holds one of each and reads 10 times the logarithm of 1.34 hundredths plus 1.66 thousandths over
// 3, against the 10 to the -2.3 of -23 dBFS, which is -22.99 LUFS.
test('Tech 3341 case 9, a constant short-term loudness after 3 s', () => {
    const segments = [];
    for (let i = 0; i < 4; i += 1) segments.push(stereo(1.34, -20), stereo(1.66, -30));
    let checked = 0;
    play(new LoudnessMeter(48000, 2), segments, {
        after(m, t) {
            if (t > 3.1) {
                near(m.shortTerm(), -23, 0.1, `short-term at ${t.toFixed(3)} s`);
                checked += 1;
            }
        },
    });
    assert.ok(checked > 100);
});

// A momentary counterpart of case 9 alternates 0.18 s at -20 dBFS and 0.22 s at -30 dBFS, so every
// window of 400 ms holds one of each and reads 10 times the logarithm of 1.8 thousandths plus 0.22
// thousandths over 0.4, against the 10 to the -2.3 of -23 dBFS, which is -22.97 LUFS. Each part is
// a whole number of cycles of the sine.
test('a constant momentary loudness after 400 ms', () => {
    const segments = [];
    for (let i = 0; i < 25; i += 1) segments.push(stereo(0.18, -20), stereo(0.22, -30));
    let checked = 0;
    play(new LoudnessMeter(48000, 2), segments, {
        after(m, t) {
            if (t > 0.5) {
                near(m.momentary(), -22.97, 0.1, `momentary at ${t.toFixed(3)} s`);
                checked += 1;
            }
        },
    });
    assert.ok(checked > 100);
});

test('case 1 at 44.1 kHz', () => {
    const m = play(new LoudnessMeter(44100, 2), [stereo(20, -23)], { sampleRate: 44100 });
    near(m.momentary(), -23, 0.1, 'momentary');
    near(m.shortTerm(), -23, 0.1, 'short-term');
    near(m.integrated(), -23, 0.1, 'integrated');
});

// A sine of a sample rate over n at a phase of phi degrees with its peak at the given level in
// dBTP, the true peak signals of Tech 3341 cases 15 to 19.
// The sine fades in and out over 20 ms, so the overshoot of a sudden start stays out of the reading.
function phasedSine(sampleRate, divisor, phase, db, seconds = 0.5, fade = 0.02) {
    const x = new Float32Array(Math.round(seconds * sampleRate));
    const a = dbToGain(db);
    const ramp = Math.round(fade * sampleRate);
    for (let i = 0; i < x.length; i += 1) {
        const edge = Math.min(i, x.length - 1 - i);
        const shape = edge < ramp ? 0.5 - 0.5 * Math.cos((Math.PI * edge) / ramp) : 1;
        x[i] = shape * a * Math.sin((2 * Math.PI * i) / divisor + (phase * Math.PI) / 180);
    }
    return x;
}

test('the true peak of the Tech 3341 signals', () => {
    const cases = [
        { name: 'case 15, fs/4 at 0 degrees', divisor: 4, phase: 0, db: -6, sample: -6 },
        { name: 'case 16, fs/4 at 45 degrees', divisor: 4, phase: 45, db: -6, sample: -9.01 },
        { name: 'case 17, fs/6 at 60 degrees', divisor: 6, phase: 60, db: -6, sample: -7.25 },
        { name: 'case 18, fs/8 at 67.5 degrees', divisor: 8, phase: 67.5, db: -6, sample: -6.69 },
        { name: 'case 19, fs/4 at 45 degrees and +3 dBTP', divisor: 4, phase: 45, db: 3, sample: -0.01 },
        { name: 'fs/4 at 45 degrees and 0 dBTP', divisor: 4, phase: 45, db: 0, sample: -3.01 },
    ];
    for (const { name, divisor, phase, db, sample } of cases) {
        for (const rate of [48000, 96000]) {
            const x = phasedSine(rate, divisor, phase, db);
            const tp = new TruePeak(rate, 2);
            let largest = 0;
            for (let o = 0; o < x.length; o += 1000) largest = Math.max(largest, tp.process([x.subarray(o, o + 1000), x.subarray(o, o + 1000)]));
            assert.equal(largest, tp.peak);
            if (rate === 48000 || divisor === 4) near(gainToDb(tp.peak), db, 0.1, `${name} at ${rate} Hz`);
            if (rate === 48000) {
                const read = measure(rate, [x, x]);
                near(read.samplePeak, sample, 0.02, `${name} sample peak`);
                near(read.truePeak, db, 0.1, `${name} by measure`);
            }
        }
    }
    const tp = new TruePeak(96000, 1);
    assert.equal(tp.factor, 2);
    assert.equal(new TruePeak(44100, 1).factor, 4);
});

test('measure reads a decoded sample, a short one by its mean', () => {
    const x = phasedSine(48000, 48, 0, -20, 2, 0);
    const read = measure(48000, [x, x]);
    near(read.integrated, -20, 0.1, 'integrated');
    near(read.maxMomentary, -20, 0.1, 'largest momentary');
    near(read.maxShortTerm, -20 + 10 * Math.log10(2 / 3), 0.1, 'largest short-term of 2 s in a 3 s window');
    near(read.truePeak, -20, 0.05, 'true peak');
    near(read.samplePeak, -20, 0.01, 'sample peak');
    const short = phasedSine(48000, 48, 0, -20, 0.2, 0);
    near(measure(48000, [short, short]).integrated, -20, 0.15, 'a 200 ms cue');
    assert.equal(measure(48000, [new Float32Array(100)]).integrated, -Infinity);
});

// Runs a stereo signal through a limiter in quanta of 128 frames, with silence after it so the
// delay drains, and returns the output and the limiter.
function limit(signal, options = {}, inPlace = false) {
    const lim = new Limiter(48000, 2, options);
    const total = signal.length + lim.latency + 64;
    const left = new Float32Array(total);
    left.set(signal);
    const right = Float32Array.from(left, (v) => -v);
    const outLeft = inPlace ? left : new Float32Array(total);
    const outRight = inPlace ? right : new Float32Array(total);
    let deepest = 0;
    for (let o = 0; o < total; o += 128) {
        const e = Math.min(total, o + 128);
        lim.process([left.subarray(o, e), right.subarray(o, e)], [outLeft.subarray(o, e), outRight.subarray(o, e)]);
        assert.ok(lim.reduction >= 0);
        deepest = Math.max(deepest, lim.reduction);
    }
    const tp = new TruePeak(48000, 2);
    tp.process([outLeft, outRight]);
    tp.flush();
    return { out: outLeft, lim, truePeak: gainToDb(tp.peak), deepest };
}

function noise(seconds, rmsDb, seed = 7) {
    const x = new Float32Array(Math.round(seconds * 48000));
    let s = seed;
    const random = () => {
        s = (s * 1103515245 + 12345) % 2147483648;
        return (s + 1) / 2147483649;
    };
    const a = dbToGain(rmsDb);
    for (let i = 0; i < x.length; i += 1) x[i] = a * Math.sqrt(-2 * Math.log(random())) * Math.cos(2 * Math.PI * random());
    return x;
}

test('the limiter passes a quiet signal unchanged apart from its delay', () => {
    const x = phasedSine(48000, 48000 / 997, 0, -12, 1, 0);
    for (const inPlace of [false, true]) {
        const copy = Float32Array.from(x);
        const { out, lim, deepest } = limit(copy, {}, inPlace);
        assert.equal(lim.latency, 240);
        assert.equal(deepest, 0);
        for (let i = 0; i < x.length; i += 1) {
            if (out[i + lim.latency] !== x[i]) assert.fail(`frame ${i} changed, in place ${inPlace}`);
        }
        for (let i = 0; i < lim.latency; i += 1) assert.equal(out[i], 0);
    }
});

test('the limiter keeps the oversampled output under the ceiling', () => {
    const square = (period, seconds) => Float32Array.from({ length: Math.round(seconds * 48000) }, (_, i) => (Math.floor((2 * i) / period) % 2 ? -1 : 1));
    const spike = new Float32Array(4800);
    spike[1000] = 4;
    const cases = [
        { name: 'a 997 Hz sine at +6 dBFS', x: phasedSine(48000, 48000 / 997, 0, 6, 2, 0) },
        { name: 'a 15 kHz sine at +6 dBFS', x: phasedSine(48000, 3.2, 17, 6, 1, 0) },
        { name: 'a full scale 1 kHz square wave', x: square(48, 2) },
        { name: 'a full scale 8 kHz square wave', x: square(6, 1) },
        { name: 'white noise at +10 dBFS RMS', x: noise(2, 10) },
        { name: 'a single sample spike of 4.0', x: spike },
    ];
    for (const ceiling of [-1, -6]) {
        for (const { name, x } of cases) {
            const { truePeak, deepest } = limit(x, { ceiling });
            assert.ok(truePeak <= ceiling + 0.1, `${name} at ${ceiling} dBTP reads ${truePeak}`);
            assert.ok(truePeak >= ceiling - 0.5, `${name} at ${ceiling} dBTP stays near the ceiling, ${truePeak}`);
            assert.ok(deepest > 0, `${name} reduces`);
        }
    }
    const steady = limit(phasedSine(48000, 48000 / 997, 0, 6, 1, 0));
    near(steady.deepest, 7, 0.05, 'a +6 dBFS sine comes down by 7 dB to -1 dBTP');
});

test('the governor brings a loud cue to its short-term ceiling within its attack', () => {
    const g = new Governor(48000);
    const dt = 128 / 48000;
    let gain = 0;
    for (let t = 0; t < 5; t += dt) gain = g.update(-20, -20, dt);
    near(gain, 0, 1e-3, 'a bus at -20 LUFS sits under its ceilings');
    let previous = 0;
    let at = 0;
    for (; at < 1; at += dt) {
        gain = g.update(-10, -10, dt);
        assert.ok(gain <= previous + 1e-12, 'the gain falls without a step back');
        assert.ok(previous - gain < 1, 'the gain falls without a jump');
        previous = gain;
        if (Math.abs(at - 0.25) < dt / 2) assert.ok(gain > -8, 'still on its way at a quarter of the attack');
    }
    near(-10 + gain, -18, 0.1, 'short-term after the attack');
    near(g.reduction, 8, 0.1, 'reduction');
    for (let t = 0; t < 10; t += dt) gain = g.update(-30, -30, dt);
    assert.equal(g.penalized, false);
    near(gain, 0, 1e-3, 'the gain recovers with the release');
});

test('the governor leaves a quiet cue untouched and clamps a startle at once', () => {
    const g = new Governor(48000);
    const dt = 128 / 48000;
    for (let t = 0; t < 5; t += dt) assert.equal(g.update(-25, t < 0.1 ? -Infinity : -25, dt), 0);
    const s = new Governor(48000);
    for (let t = 0; t < 3; t += dt) s.update(-40, -40, dt);
    let rise = 0;
    let first = true;
    for (let t = 0; t < 0.1; t += dt) {
        rise += dt;
        const gain = s.update(-10, -40 + 10 * rise, dt);
        if (first) assert.ok(-10 + gain <= -40 + 18 + 0.01, `clamped at once, ${gain}`);
        first = false;
        assert.ok(-10 + gain <= -21.9, 'the startle stays clamped within its window');
    }
});

test('a sustained reduction latches the penalty, and the gain never goes over 0 dB', () => {
    const g = new Governor(48000);
    const dt = 128 / 48000;
    let t = 0;
    for (; t < 2; t += dt) g.update(-8, -8, dt);
    assert.equal(g.penalized, false);
    for (; t < 5; t += dt) g.update(-8, -8, dt);
    assert.equal(g.penalized, true);
    let gain = 0;
    for (; t < 20; t += dt) gain = g.update(-30, -30, dt);
    near(gain, -6, 1e-3, 'the penalty stays for the session');
    near(g.reduction, 6, 1e-3, 'reduction');
    g.reset();
    assert.equal(g.penalized, false);
    let seed = 3;
    const random = () => {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        return seed / 2147483648;
    };
    const odd = [-Infinity, NaN, null, undefined, Infinity];
    for (let i = 0; i < 20000; i += 1) {
        const m = random() < 0.05 ? odd[i % odd.length] : -60 + 70 * random();
        const st = random() < 0.05 ? odd[(i + 2) % odd.length] : -60 + 60 * random();
        const gainNow = g.update(m, st, random() < 0.01 ? NaN : 0.003 * random());
        assert.ok(gainNow <= 0 && Number.isFinite(gainNow), `gain ${gainNow}`);
    }
    // Short bursts that add up to about half a second in each 60 s leave the penalty off.
    const spread = new Governor(48000);
    for (let k = 0; k < 10; k += 1) {
        for (let u = 0; u < 0.25; u += dt) spread.update(-8, -8, dt);
        for (let u = 0; u < 30; u += dt) spread.update(-40, -40, dt);
    }
    assert.equal(spread.penalized, false);
});

// Feeds a processor quanta of 128 frames made by a function of the frame and channel.
function run(processor, seconds, channels, value) {
    const frames = 128;
    const output = [];
    for (let c = 0; c < Math.max(1, channels); c += 1) output.push(new Float32Array(frames));
    const input = [];
    for (let c = 0; c < channels; c += 1) input.push(new Float32Array(frames));
    const total = Math.round((seconds * 48000) / frames);
    for (let q = 0; q < total; q += 1) {
        for (let c = 0; c < channels; c += 1) for (let i = 0; i < frames; i += 1) input[c][i] = value(q * frames + i, c);
        assert.equal(processor.process(channels > 0 ? [input] : [[]], [output], {}), true);
    }
    return output;
}

test('cuju-loudness passes its input, meters it and watches for a runaway', () => {
    const Processor = registered['cuju-loudness'];
    const p = new Processor({ processorOptions: {} });
    const sine = (n) => dbToGain(-23) * Math.sin((2 * Math.PI * 1000 * n) / 48000);
    const out = run(p, 4, 2, sine);
    near(out[0][5], sine(4 * 48000 - 128 + 5), 1e-7, 'the input passes unchanged');
    const meters = p.port.messages.filter((m) => m.type === 'meter');
    assert.ok(meters.length >= 39 && meters.length <= 40, `a meter message every 100 ms, ${meters.length}`);
    const last = meters[meters.length - 1];
    assert.deepEqual(Object.keys(last), ['type', 'momentary', 'shortTerm', 'integrated', 'truePeak', 'reduction', 'penalized', 'nonFinite']);
    near(last.momentary, -23, 0.1, 'momentary');
    near(last.shortTerm, -23, 0.1, 'short-term');
    near(last.integrated, -23, 0.1, 'integrated');
    near(last.truePeak, -23, 0.1, 'true peak');
    assert.equal(last.reduction, 0);
    p.port.onmessage({ data: { type: 'reset' } });
    p.port.messages.length = 0;
    run(p, 0.2, 2, () => 0);
    assert.equal(p.port.messages[0].momentary, null, 'silence reads null');
    assert.equal(p.port.messages[0].truePeak, null);
    const bad = run(p, 1.2, 2, (n) => (n % 2 ? NaN : 0.01));
    assert.ok(bad[0].every(Number.isFinite), 'samples that are not finite become zero');
    assert.ok(p.port.messages.some((m) => m.type === 'meter' && m.nonFinite > 0));
    assert.deepEqual(p.port.messages.filter((m) => m.type === 'runaway'), [{ type: 'runaway', reason: 'nonFinite' }]);
    const dc = new Processor({ processorOptions: {} });
    run(dc, 0.8, 2, () => 0.2);
    assert.equal(dc.port.messages.filter((m) => m.type === 'runaway').length, 0, 'a short offset is no runaway');
    run(dc, 0.8, 2, () => 0.2);
    assert.deepEqual(dc.port.messages.filter((m) => m.type === 'runaway'), [{ type: 'runaway', reason: 'dc' }]);
    const empty = new Processor({ processorOptions: {} });
    const silent = run(empty, 0.2, 0, () => 1);
    assert.ok(silent[0].every((v) => v === 0), 'a missing input is silence');
    const mono = new Processor({ processorOptions: { channels: 2 } });
    run(mono, 3, 1, sine);
    assert.equal(mono.channels, 1, 'the meters follow the input channel count');
});

test('cuju-loudness with govern brings a loud bus down smoothly', () => {
    const Processor = registered['cuju-loudness'];
    const p = new Processor({ processorOptions: { govern: true, shortTermCeiling: -18, momentaryCeiling: -14 } });
    const sine = (n) => dbToGain(-14) * Math.sin((2 * Math.PI * 1000 * n) / 48000);
    let largestStep = 0;
    let previous = 0;
    const frames = 128;
    const input = [new Float32Array(frames), new Float32Array(frames)];
    const output = [new Float32Array(frames), new Float32Array(frames)];
    for (let q = 0; q < (8 * 48000) / frames; q += 1) {
        for (let i = 0; i < frames; i += 1) input[0][i] = input[1][i] = sine(q * frames + i);
        p.process([input], [output], {});
        for (let i = 0; i < frames; i += 1) {
            const gain = input[0][i] === 0 ? null : output[0][i] / input[0][i];
            if (gain !== null && Math.abs(input[0][i]) > 0.05) {
                if (previous) largestStep = Math.max(largestStep, Math.abs(gain - previous));
                previous = gain;
            }
        }
    }
    const last = p.port.messages.filter((m) => m.type === 'meter').pop();
    near(last.shortTerm, -18, 0.3, 'the output short-term sits at its ceiling');
    near(last.reduction, 4, 0.3, 'reduction');
    assert.equal(last.penalized, false);
    assert.ok(largestStep < 0.01, `the gain moves smoothly, largest step ${largestStep}`);
});

test('cuju-limiter limits and reports', () => {
    const Processor = registered['cuju-limiter'];
    const p = new Processor({ processorOptions: {} });
    run(p, 1, 2, (n, c) => (c ? -1 : 1) * dbToGain(6) * Math.sin((2 * Math.PI * 997 * n) / 48000));
    const reports = p.port.messages.filter((m) => m.type === 'limiter');
    assert.ok(reports.length >= 9);
    const last = reports[reports.length - 1];
    assert.deepEqual(Object.keys(last), ['type', 'reduction', 'truePeak']);
    assert.ok(last.truePeak <= -0.9, `true peak ${last.truePeak}`);
    near(last.reduction, 7, 0.1, 'reduction');
    const low = new Processor({ processorOptions: { ceiling: -6 } });
    run(low, 0.5, 2, (n) => Math.sin((2 * Math.PI * 440 * n) / 48000));
    assert.ok(low.port.messages.pop().truePeak <= -5.9);
    const empty = new Processor({ processorOptions: {} });
    const silent = run(empty, 0.2, 0, () => 1);
    assert.ok(silent[0].every((v) => v === 0), 'a missing input is silence');
});

test('the meter and the limiter are cheap', (t) => {
    const seconds = 10;
    const frames = 128;
    const x = noise(seconds, -20, 11);
    const meter = new LoudnessMeter(48000, 2);
    const lim = new Limiter(48000, 2);
    const out = [new Float32Array(frames), new Float32Array(frames)];
    const time = (fn) => {
        const start = performance.now();
        for (let o = 0; o < x.length; o += frames) fn(x.subarray(o, o + frames));
        return (performance.now() - start) / seconds;
    };
    time((q) => meter.push([q, q]));
    meter.reset();
    const meterCost = time((q) => {
        meter.push([q, q]);
        meter.momentary();
        meter.shortTerm();
    });
    const limiterCost = time((q) => lim.process([q, q], out));
    const loud = noise(seconds, 6, 13);
    const start = performance.now();
    for (let o = 0; o < loud.length; o += frames) lim.process([loud.subarray(o, o + frames), loud.subarray(o, o + frames)], out);
    const limitingCost = (performance.now() - start) / seconds;
    const report = `per second of stereo audio at 48 kHz, meter ${meterCost.toFixed(2)} ms, limiter ${limiterCost.toFixed(2)} ms, limiter while limiting ${limitingCost.toFixed(2)} ms`;
    t.diagnostic(report);
    console.log(report);
    assert.ok(meterCost < 200 && limiterCost < 200, report);
});
