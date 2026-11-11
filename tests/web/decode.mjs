// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the decoder of recordings in a Web Worker, which must hand the page the very frames
// that the page's own reader makes, run from the repository root with
// `node tests/web/decode.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { Worker } from 'node:worker_threads';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from a copy beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-decode-'));
for (const name of ['recording/format.js', 'recording/codec.js', 'recording/decode.js', 'recording/decode-worker.js', 'core/i18n.js']) {
    cpSync(fileURLToPath(new URL(`../../src/cuju/render/web/js/${name}`, import.meta.url)), join(folder, name));
}
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
// A worker of Node with the globals of a browser's worker, self, postMessage and onmessage.
writeFileSync(join(folder, 'boot.js'), `
import { parentPort } from 'node:worker_threads';
globalThis.self = globalThis;
globalThis.postMessage = (message, transfer) => parentPort.postMessage(message, transfer);
await import('./recording/decode-worker.js');
parentPort.on('message', (data) => self.onmessage({ data }));
`);
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const url = (name) => pathToFileURL(join(folder, name)).href;
const { FormatError, parseRecording } = await import(url('recording/format.js'));
const decoder = await import(url('recording/decode.js'));
const { frameBuffers } = await import(url('recording/decode-worker.js'));

// The browser's Worker, made of a worker of Node.
function nodeWorker() {
    const worker = new Worker(new URL(url('boot.js')));
    return {
        postMessage: (message) => worker.postMessage(message),
        terminate: () => worker.terminate(),
        set onmessage(listener) {
            worker.on('message', (data) => listener({ data }));
        },
        set onerror(listener) {
            worker.on('error', (err) => listener({ message: err.message }));
        },
        set onmessageerror(listener) {
            worker.on('messageerror', (err) => listener({ message: String(err) }));
        },
    };
}

// A worker that fails to load its script, as an old browser's module worker does.
function brokenWorker() {
    const worker = { postMessage: () => setTimeout(() => worker.onerror({ message: 'no modules' }), 0), terminate() {} };
    return worker;
}

const sample = (name) => new Uint8Array(readFileSync(fileURLToPath(new URL(`../../src/cuju/render/samples/${name}.cjr`, import.meta.url))));
// The page's own reading of each sample, made once.
const read = new Map();
const pageRead = (name) => {
    if (!read.has(name)) {
        read.set(name, parseRecording(sample(name)));
    }
    return read.get(name);
};

// Compares two decoded recordings field by field, typed arrays by their bytes.
function assertSame(actual, expected) {
    assert.deepEqual(actual.header, expected.header);
    assert.equal(actual.frames.length, expected.frames.length);
    for (let i = 0; i < expected.frames.length; i++) {
        const a = actual.frames[i];
        const b = expected.frames[i];
        assert.deepEqual(Object.keys(a).sort(), Object.keys(b).sort());
        for (const key of Object.keys(b)) {
            if (ArrayBuffer.isView(b[key])) {
                assert.equal(a[key].constructor, b[key].constructor, `frame ${i} ${key}`);
                assert.ok(Buffer.from(a[key].buffer, a[key].byteOffset, a[key].byteLength)
                    .equals(Buffer.from(b[key].buffer, b[key].byteOffset, b[key].byteLength)), `frame ${i} ${key}`);
            } else {
                assert.deepEqual(a[key], b[key], `frame ${i} ${key}`);
            }
        }
    }
}

for (const name of ['sample-5v5', 'sample-11v11']) {
    test(`the worker decodes ${name} into the page's frames`, async () => {
        const bytes = sample(name);
        const expected = await pageRead(name);
        assert.ok(expected.frames.length > 100);
        const actual = await decoder.decodeRecording(bytes, { makeWorker: nodeWorker });
        assert.equal(decoder.lastDecoder, 'worker');
        assertSame(actual, expected);
        // The worker sent a copy, the page keeps its bytes whole.
        assert.equal(bytes.byteLength, sample(name).byteLength);
    });
}

test('every frame buffer moves to the page', async () => {
    const { frames } = await pageRead('sample-5v5');
    const buffers = frameBuffers(frames);
    assert.equal(new Set(buffers).size, buffers.length);
    for (const frame of frames.slice(0, 50)) {
        for (const value of Object.values(frame)) {
            if (ArrayBuffer.isView(value)) {
                assert.ok(buffers.includes(value.buffer));
            }
        }
    }
});

test('the page reads the recording itself when the worker cannot help', async () => {
    const bytes = sample('sample-5v5');
    const expected = await pageRead('sample-5v5');
    const thrown = () => {
        throw new Error('workers are off');
    };
    const warn = console.warn;
    console.warn = () => {};
    try {
        for (const makeWorker of [thrown, brokenWorker, null]) {
            const actual = await decoder.decodeRecording(bytes, { makeWorker });
            assert.equal(decoder.lastDecoder, 'page');
            assertSame(actual, expected);
        }
    } finally {
        console.warn = warn;
    }
});

test('a recording that the worker refuses keeps its message', async () => {
    const bytes = new TextEncoder().encode('This is no recording at all.');
    await assert.rejects(decoder.decodeRecording(bytes, { makeWorker: nodeWorker }), (err) => {
        assert.ok(err instanceof FormatError);
        assert.match(err.message, /not a cuju recording/);
        return true;
    });
});
