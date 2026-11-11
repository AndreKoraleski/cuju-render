// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The page of the command cuju render video, export.html, which src/cuju/render/_export/video.py
// opens in a headless Chrome, Edge or Chromium. It runs the browser's own export of
// video-browser.js, so the command needs no program beyond the browser, and the command follows
// it through window.cujuVideoExport over the debugging protocol. It asks what the browser can
// encode, starts one export, reads its state, cancels it and hands the finished file back in
// pieces of base64, so neither side holds the file twice in memory.

import { BrowserExport, hasEncoder } from './video-browser.js';
import { readableHtmlPictures } from './dom-picture.js';
import { chooseEncoder, encoderCandidates } from './video-plan.js';

let job = null;
let state = { state: 'idle' };
let result = null;

// The encoder of each container at a size, or null where the browser has none.
async function support(width, height, fps, quality) {
    const out = { mp4: null, webm: null, pictures: await readableHtmlPictures() };
    if (!hasEncoder()) {
        return out;
    }
    for (const container of ['mp4', 'webm']) {
        const chosen = await chooseEncoder(encoderCandidates(width, height, fps, quality, container), (config) => VideoEncoder.isConfigSupported(config));
        out[container] = chosen ? chosen.config.codec : null;
    }
    return out;
}

// Starts an export. options holds the recording's match and title, the body of the export, the
// container, the language and the limits of frames and bytes.
function start(options) {
    if (job) {
        throw new Error('An export runs already.');
    }
    result = null;
    state = { state: 'running', frame: 0, progress: 0 };
    const current = new BrowserExport({
        match: options.match,
        title: options.title,
        body: options.body,
        lang: options.lang,
        container: options.container,
        maxFrames: options.maxFrames,
        maxBytes: options.maxBytes,
        report: (entry) => {
            if (job === current) {
                state = { ...entry };
            }
        },
    });
    job = current;
    current.run().then((done) => {
        result = done;
        const { blob, ...facts } = done;
        state = { ...facts, state: 'done' };
    }, (error) => {
        state = error && error.id === 'cancelled'
            ? { state: 'cancelled' }
            : { state: 'failed', id: error && error.id, values: (error && error.values) || {}, message: String((error && error.message) || error) };
    }).finally(() => {
        job = null;
    });
    return true;
}

// The bytes of the finished file from start, at most length of them, as base64.
async function read(from, length) {
    if (!result) {
        return '';
    }
    const bytes = new Uint8Array(await result.blob.slice(from, from + length).arrayBuffer());
    let text = '';
    for (let i = 0; i < bytes.length; i += 32768) {
        text += String.fromCharCode(...bytes.subarray(i, i + 32768));
    }
    return btoa(text);
}

window.cujuVideoExport = {
    support,
    start,
    read,
    state: () => state,
    cancel: () => {
        if (job) {
            job.cancel();
        }
        return true;
    },
    clear: () => {
        result = null;
        return true;
    },
};
