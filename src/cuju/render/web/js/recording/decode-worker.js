// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The worker that decodes a recording off the page's main thread. It unpacks the gzip and reads
// the frames of either version with the same reader as the page, format.js with codec.js, and
// hands the frames and the annotations back with their buffers moved rather than copied, so the
// page receives exactly the frames it would read itself.

import { FormatError, parseRecording } from './format.js';

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

// Decodes one request, { id, bytes }, into the reply and the buffers that it moves.
export async function decodeRequest({ id, bytes }) {
    try {
        const { header, frames, annotations } = await parseRecording(bytes);
        return { reply: { id, header, frames, annotations }, transfer: frameBuffers(frames) };
    } catch (err) {
        const message = err && err.message ? err.message : String(err);
        return { reply: { id, error: message, format: err instanceof FormatError }, transfer: [] };
    }
}

// Inside a worker, each message is a request. Node's tests import this file for its functions.
if (typeof self !== 'undefined' && typeof self.postMessage === 'function' && typeof document === 'undefined') {
    self.onmessage = async (event) => {
        const { reply, transfer } = await decodeRequest(event.data);
        self.postMessage(reply, transfer);
    };
}
