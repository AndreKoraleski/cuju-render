// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Decodes a recording in a Web Worker, so the page keeps drawing and loading while the frames are
// unpacked and read. Where a worker cannot start, the page reads the recording itself with the
// same reader, so a recording opens either way with the same frames. A worker that started and
// then failed on a recording leaves it unopened, since the page would only fail on it again.
//
// A worker could not start when making it throws, when it reports an error before it said it
// started, or when its reader did not load.

import { FormatError, parseRecording } from './format.js';

// How the last recording was decoded, 'worker' or 'page', for the page's checks.
export let lastDecoder = null;

let nextId = 0;

function startWorker() {
    return new Worker(new URL('./decode-worker.js', import.meta.url), { type: 'module' });
}

// Decodes in a worker made by makeWorker, resolving with the recording or rejecting with the
// worker's own error. A format error keeps its class and takes its message again from its id, in
// the page's language, and a worker that could not start rejects with `unavailable`, so the
// caller falls back to the page.
function inWorker(bytes, makeWorker) {
    return new Promise((resolve, reject) => {
        let worker;
        try {
            worker = makeWorker();
        } catch (err) {
            reject(Object.assign(new Error(`The decoder did not start, ${err && err.message}`), { unavailable: true }));
            return;
        }
        const id = ++nextId;
        let started = false;
        const done = () => worker.terminate();
        worker.onmessage = (event) => {
            const data = event.data || {};
            if (data.id !== id) {
                return;
            }
            if (data.started) {
                started = true;
                return;
            }
            done();
            if (data.error) {
                reject(data.format ? new FormatError(data.messageId, data.messageValues) : Object.assign(new Error(data.error), { unavailable: !!data.unavailable }));
            } else {
                resolve({ header: data.header, frames: data.frames, annotations: data.annotations || null });
            }
        };
        worker.onerror = (event) => {
            done();
            if (event && typeof event.preventDefault === 'function') {
                event.preventDefault();
            }
            reject(Object.assign(new Error(`The decoder failed, ${(event && event.message) || 'it did not load'}`), { unavailable: !started }));
        };
        worker.onmessageerror = worker.onerror;
        // The worker receives a copy, so the bytes stay whole for the page if it must read them.
        worker.postMessage({ id, bytes });
    });
}

// Decodes a recording, compressed or not, into its header, frames and annotations.
// options.makeWorker replaces the worker, null reads on the page alone.
export async function decodeRecording(input, options = {}) {
    const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
    const makeWorker = options.makeWorker !== undefined
        ? options.makeWorker
        : (typeof Worker === 'function' ? startWorker : null);
    if (makeWorker) {
        try {
            const rec = await inWorker(bytes, makeWorker);
            lastDecoder = 'worker';
            return rec;
        } catch (err) {
            if (!err.unavailable) {
                throw err;
            }
            console.warn('decoding on the page instead', err.message);
        }
    }
    // Reading on the page blocks it for a moment, so its loading message paints first.
    if (typeof requestAnimationFrame === 'function') {
        await new Promise((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)));
    }
    const rec = await parseRecording(bytes);
    lastDecoder = 'page';
    return rec;
}
