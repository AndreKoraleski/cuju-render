// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The worker that decodes a recording off the page's main thread. It unpacks the gzip and reads
// the frames of either version with the same reader as the page, format.js with codec.js, and
// hands the frames and the annotations back with their buffers moved rather than copied, so the
// page receives exactly the frames it would read itself.

// The reader loads on the first request. It reads the language files as it loads, so a static
// import would hold the worker's message handler back until then, and a request that arrives
// first would be lost.
let reader = null;
const format = () => (reader = reader || import('./format.js'));

// Every buffer that the frames hold, once each, which the reply moves to the page.
export function frameBuffers(frames) {
    const seen = new Set();
    const visit = (value) => {
        if (ArrayBuffer.isView(value)) {
            seen.add(value.buffer);
        } else if (value && typeof value === 'object') {
            for (const item of Object.values(value)) {
                visit(item);
            }
        }
    };
    for (const frame of frames) {
        visit(frame);
    }
    return [...seen];
}

// Decodes one request, { id, bytes }, into the reply and the buffers that it moves. A format
// error also sends the id and the values of its message, so the page shows it in its language.
// A reader that does not load replies with `unavailable`, and once it has loaded, `started`, when
// given, receives the id before the recording is read, so the page tells a worker that could not
// start from one that failed on the recording.
export async function decodeRequest({ id, bytes }, started = null) {
    let reader;
    try {
        reader = await format();
    } catch (err) {
        return { reply: { id, error: err && err.message ? err.message : String(err), unavailable: true }, transfer: [] };
    }
    const { FormatError, parseRecording } = reader;
    if (started) {
        started(id);
    }
    try {
        const { header, frames, annotations } = await parseRecording(bytes);
        return { reply: { id, header, frames, annotations }, transfer: frameBuffers(frames) };
    } catch (err) {
        const message = err && err.message ? err.message : String(err);
        const format = err instanceof FormatError;
        const reply = { id, error: message, format };
        if (format) {
            reply.messageId = err.messageId;
            reply.messageValues = err.messageValues;
        }
        return { reply, transfer: [] };
    }
}

// Inside a worker, each message is a request. Node's tests import this file for its functions.
if (typeof self !== 'undefined' && typeof self.postMessage === 'function' && typeof document === 'undefined') {
    self.onmessage = async (event) => {
        const { reply, transfer } = await decodeRequest(event.data, (id) => self.postMessage({ id, started: true }));
        self.postMessage(reply, transfer);
    };
}
