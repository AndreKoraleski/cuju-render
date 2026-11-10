// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the page's live streams, run from the repository root with `node tests/web/live.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { gunzipSync } from 'node:zlib';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from a copy beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-live-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/', import.meta.url)), folder, { recursive: true });
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const load = (name) => import(pathToFileURL(join(folder, name)).href);
const { LiveSource, RECONNECT_ATTEMPTS, liveLimit } = await load('recording/live.js');
const { NODES_FLOAT, PLAYER_FLOATS, StreamParser, isCut, readSections, validateHeader } = await load('recording/format.js');
const { decodeFrames } = await load('recording/codec.js');

const sample = (name) => gunzipSync(readFileSync(new URL(`../../src/cuju/render/samples/${name}`, import.meta.url)));
const bytes = sample('sample-5v5.cjr');
const length = bytes.readUInt32LE(8);
// A live stream sends the header and frames of version 1, so the sample of version 2 decodes first.
const { keyframe_interval: interval, ...stored } = JSON.parse(bytes.subarray(12, 12 + length));
const header = { ...stored, version: 1, frame_count: null };
const coded = readSections(new Uint8Array(bytes), 12 + length).get('FRMS');
const frame = Buffer.from(decodeFrames(coded, header.players.length, stored.frame_count, interval), 0, header.frame_bytes);
const END = Buffer.alloc(8, 255);

// A numbered stream with the frames of the given serials, the end marker when ended is true.
function body(serials, ended = false, id = 'test:0') {
    const json = Buffer.from(JSON.stringify({ ...header, stream_sequence: 1, stream_id: id }));
    const head = Buffer.alloc(12);
    head.write('CUJREC1\n');
    head.writeUInt32LE(json.length, 8);
    const parts = [head, json];
    for (const serial of serials) {
        const prefix = Buffer.alloc(8);
        prefix.writeBigUInt64LE(BigInt(serial));
        // The step follows the serial, so only a gap or an episode makes a cut.
        const copy = Buffer.from(frame);
        copy.writeInt32LE(100 + serial, 0);
        copy.writeInt32LE(0, 28);
        parts.push(prefix, copy);
    }
    if (ended) {
        parts.push(END);
    }
    return Buffer.concat(parts);
}
const stream = (...args) => new Response(body(...args));

// A source that answers with each response in turn, an Error rejecting like a failed fetch.
function source(responses, extra = {}) {
    const calls = [];
    const errors = [];
    let ended = 0;
    let headers = 0;
    const live = new LiveSource('test', {
        open: async () => {
            calls.push(Date.now());
            const next = responses.shift();
            if (next instanceof Error) {
                throw next;
            }
            return typeof next === 'function' ? next() : next;
        },
        onHeader: () => headers++,
        onFrame: () => {},
        onEnd: () => ended++,
        onError: (error) => errors.push(error),
        ...extra,
    });
    return { live, calls, errors, count: () => ({ ended, headers }) };
}

// Waits out the delays of reconnection, which tests keep short.
async function run(live) {
    const realTimeout = globalThis.setTimeout;
    globalThis.setTimeout = (fn, delay, ...args) => realTimeout(fn, Math.min(delay, 1), ...args);
    try {
        await live.start();
    } finally {
        globalThis.setTimeout = realTimeout;
    }
}

test('unknown sequence formats fail before decoding frames', () => {
    assert.throws(() => validateHeader({ ...header, stream_sequence: 2 }), /does not read/);
});

test('the parser reads serials and stops at the end marker', () => {
    const frames = [];
    const parser = new StreamParser(() => {}, (f) => frames.push(f));
    const all = body([4, 5], true);
    // Chunks of seven bytes split every serial and frame.
    for (let i = 0; i < all.length; i += 7) {
        parser.push(all.subarray(i, i + 7));
    }
    assert.deepEqual(frames.map((f) => f.sequence), [4, 5]);
    assert.equal(parser.ended, true);
    assert.equal(frames[0].raw, undefined);
});

test('reconnect keeps history, deduplicates and marks missing frames', async () => {
    const { live, calls, errors, count } = source([stream([0, 1]), stream([1, 3], true)]);
    await run(live);
    assert.equal(calls.length, 2);
    assert.deepEqual(count(), { ended: 1, headers: 1 });
    assert.equal(live.store.size, 3);
    assert.equal(live.gaps, 1);
    assert.equal(isCut(live.store.get(0), live.store.get(1)), false);
    assert.equal(isCut(live.store.get(1), live.store.get(2)), true);
    assert.deepEqual(errors, []);
    assert.equal(live.state, 'ended');
});

test('the attempts to reconnect count each outage on its own', async () => {
    // Two outages of RECONNECT_ATTEMPTS failures each, with a successful reconnection between.
    const failures = () => Array.from({ length: RECONNECT_ATTEMPTS - 1 }, () => new Error('refused'));
    const { live, errors, count } = source([
        stream([0]), ...failures(), stream([0, 1]), ...failures(), stream([1, 2], true),
    ]);
    await run(live);
    assert.deepEqual(errors, []);
    assert.equal(count().ended, 1);
    assert.equal(live.store.size, 3);
    assert.equal(live.gaps, 0);
});

test('an outage ends after its attempts with the last reason', async () => {
    const outage = Array.from({ length: RECONNECT_ATTEMPTS }, () => new Error('refused'));
    const { live, calls, errors } = source([stream([0]), ...outage]);
    await run(live);
    assert.equal(calls.length, 1 + RECONNECT_ATTEMPTS);
    assert.equal(errors.length, 1);
    assert.match(errors[0].message, /3 attempts to reconnect failed, cannot reach the live stream, refused\.$/);
    assert.equal(live.state, 'failed');
});

test('the delays of reconnection double and stay bounded', async () => {
    const delays = [];
    const realTimeout = globalThis.setTimeout;
    globalThis.setTimeout = (fn, delay, ...args) => {
        if (delay >= 1000) {
            delays.push(delay);
        }
        return realTimeout(fn, 0, ...args);
    };
    const outage = Array.from({ length: RECONNECT_ATTEMPTS }, () => new Error('refused'));
    const { live } = source([stream([0]), ...outage]);
    try {
        await live.start();
    } finally {
        globalThis.setTimeout = realTimeout;
    }
    assert.deepEqual(delays, [1000, 2000, 4000]);
});

test('a source that has stopped ends reconnection at once', async () => {
    const { live, calls, errors } = source([stream([0]), new Response('gone', { status: 404 })]);
    await run(live);
    assert.equal(calls.length, 2);
    assert.match(errors[0].message, /answered 404/);
});

test('stop cancels backoff without reconnecting', async () => {
    const { live, calls, errors } = source([stream([0]), stream([1])]);
    const running = live.start();
    await new Promise((resolve) => setTimeout(resolve, 30));
    live.stop();
    await running;
    assert.equal(calls.length, 1);
    assert.deepEqual(errors, []);
});

test('a source can end before its first frame', async () => {
    const { live, errors, count } = source([new Response(END)]);
    await run(live);
    assert.deepEqual(count(), { ended: 1, headers: 0 });
    assert.equal(live.store, null);
    assert.deepEqual(errors, []);
});

test('a stream that closes before its header ends, as a game that ends early does', async () => {
    const { live, calls, errors, count } = source([new Response(new Uint8Array(0))]);
    await run(live);
    assert.equal(calls.length, 1);
    assert.equal(count().ended, 1);
    assert.deepEqual(errors, []);
});

test('a stream without serials ends when it closes, as in 0.2.0', async () => {
    const { live, calls, count } = source([new Response(bytes)]);
    await run(live);
    assert.equal(calls.length, 1);
    assert.equal(count().ended, 1);
    assert.equal(live.resumable, false);
});

test('a first connection that fails reports it at once', async () => {
    const { live, calls, errors } = source([new Error('refused')]);
    await run(live);
    assert.equal(calls.length, 1);
    assert.match(errors[0].message, /^Cannot reach the live stream, refused\.$/);
});

test('a stream on another server names CORS when it cannot be reached', async () => {
    const realFetch = globalThis.fetch;
    globalThis.fetch = async () => {
        throw new TypeError('Failed to fetch');
    };
    const errors = [];
    try {
        const live = new LiveSource('http://elsewhere.example/api/live/x/stream', {
            onHeader: assert.fail, onFrame: assert.fail, onEnd: assert.fail, onError: (e) => errors.push(e),
        });
        await live.start();
    } finally {
        globalThis.fetch = realFetch;
    }
    assert.match(errors[0].message, /Failed to fetch\. A stream on another server must allow this page, through CORS\.$/);
});

test('a switched source ends the stream rather than mixing two', async () => {
    const { live, errors, count } = source([stream([0]), stream([0], false, 'test:1')]);
    await run(live);
    assert.equal(live.store.size, 1);
    assert.deepEqual(errors, []);
    assert.equal(count().ended, 1);
});

test('the state of the connection reaches onState', async () => {
    const states = [];
    const { live } = source([stream([0]), new Error('refused'), stream([0, 1], true)], {
        onState: (state) => states.push(state),
    });
    await run(live);
    assert.deepEqual(states, ['connecting', 'connected', 'reconnecting', 'connected', 'ended']);
});

test('the live memory budget keeps 15 minutes of eleven a side within 80 MiB', () => {
    const big = sample('sample-11v11.cjr');
    const head = JSON.parse(big.subarray(12, 12 + big.readUInt32LE(8)));
    assert.equal(head.players.length, 22);
    const limit = liveLimit(head);
    assert.ok(limit >= 15 * 60 * head.steps_per_second, `${limit} frames`);
    // A decoded frame keeps its floats, three bytes per player and its fields, no raw bytes.
    const decoded = (NODES_FLOAT + 22 * PLAYER_FLOATS) * 4 + 3 * 22 + 160;
    assert.ok(limit * decoded <= 80 * 1024 * 1024);
});
