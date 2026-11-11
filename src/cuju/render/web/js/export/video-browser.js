// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The video export of the browser itself, which needs nothing beyond the browser that shows the
// page. It opens the recording in a frame of its own at the layout of the picture's size, as the
// server's export opens it in Chrome, steps the frame's clocks by one frame at a time through the
// capture hook of capture.js, so a slow computer still draws every frame, draws the view and the
// page's graphics into a canvas of the picture's size, and encodes each frame with the browser's
// video encoder of WebCodecs into MP4 with H.264, or WebM with VP9 or VP8 where H.264 is missing.
// The file waits in memory, or on the browser's disk, until the page offers it as a download.

import { layoutFor } from './sizes.js';
import { DomPicture, readableHtmlPictures } from './dom-picture.js';
import { Mp4Writer } from './mp4-mux.js';
import { WebmWriter } from './webm-mux.js';
import {
    MAX_BYTES, SETTLE_MS, chooseEncoder, encoderCandidates, exportAddress, exportPlan, frameDuration, frameTime,
    videoFileName,
} from './video-plan.js';

// The page that draws has this long to open the recording, as the server's export allows.
const READY_MS = 120000;
// The encoder holds at most this many frames before the drawing waits for it.
const QUEUE = 6;
// The rule that hides the scoreboard and clock of an export without them, as _HOLD of video.py.
const HIDE_SCORE = '#scoreboard { display: none !important; }';

// An error of the export with the id of its message and the values of the message.
export class ExportError extends Error {
    constructor(id, values = {}, cause = undefined) {
        super(id);
        this.id = id;
        this.values = values;
        this.cause = cause;
    }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Whether this browser has the parts of WebCodecs that the export needs.
export function hasEncoder() {
    return typeof VideoEncoder === 'function' && typeof VideoFrame === 'function'
        && typeof VideoEncoder.isConfigSupported === 'function';
}

// What this browser can export, the container and codec of its best encoder at a size, or null
// with the reason. The reason is encoder when WebCodecs or every codec is missing, and pictures
// when the browser cannot read back a picture of the page's graphics.
export async function browserSupport(width = 1280, height = 720, fps = 30, quality = 'standard') {
    if (!hasEncoder()) {
        return { supported: false, reason: 'encoder' };
    }
    const chosen = await chooseEncoder(encoderCandidates(width, height, fps, quality), (config) => VideoEncoder.isConfigSupported(config));
    if (!chosen) {
        return { supported: false, reason: 'encoder' };
    }
    if (!(await readableHtmlPictures())) {
        return { supported: false, reason: 'pictures' };
    }
    return { supported: true, container: chosen.container, codec: chosen.config.codec };
}

// One export of a range of a recording of the library.
export class BrowserExport {
    // match is the recording's identifier and title its title, body the body of an export request
    // as exportRequest of video-range.js writes it, lang the language of the page and report a
    // function that takes each report of progress. container asks for mp4 or webm, and the best
    // encoder decides without it. A body with broadcast true keeps the team sheets, restarts,
    // celebrations and replays and draws until play reaches the end, at most maxFrames frames, and
    // maxBytes bounds the file.
    constructor({ match, title, body, lang, report, container = null, maxFrames = Infinity, maxBytes = MAX_BYTES }) {
        this.match = match;
        this.title = title;
        this.body = body;
        this.lang = lang;
        this.container = container;
        this.maxFrames = maxFrames;
        this.maxBytes = maxBytes;
        this.report = report || (() => {});
        this.cancelled = false;
        this.frame = null;
        this.host = null;
    }

    cancel() {
        this.cancelled = true;
    }

    check() {
        if (this.cancelled) {
            throw new ExportError('cancelled');
        }
    }

    // Opens the page that draws, in a frame at the layout of the picture's size, and waits until it
    // has opened the recording.
    async openPage(layout) {
        const host = document.createElement('div');
        host.className = 've-drawing';
        host.setAttribute('aria-hidden', 'true');
        // The frame stays in the page, behind everything and unseen, so it keeps drawing.
        host.style.cssText = `position:fixed;left:0;top:0;width:${layout.width}px;height:${layout.height}px;`
            + 'overflow:hidden;opacity:0;pointer-events:none;z-index:-1;contain:strict;';
        const frame = document.createElement('iframe');
        frame.setAttribute('tabindex', '-1');
        frame.inert = true;
        frame.style.cssText = `border:0;width:${layout.width}px;height:${layout.height}px;display:block;color-scheme:dark;`;
        frame.src = exportAddress(this.body, { ratio: layout.scale, lang: this.lang, match: this.match });
        host.append(frame);
        document.body.append(host);
        this.host = host;
        this.frame = frame;
        const end = performance.now() + READY_MS;
        while (performance.now() < end) {
            this.check();
            let state = null;
            try {
                state = this.pageState();
            } catch {
                state = null;
            }
            if (state && state.fatal) {
                throw new ExportError('video.browser.error.page', { error: state.fatal });
            }
            if (state && state.ready) {
                return frame.contentWindow;
            }
            await sleep(200);
        }
        throw new ExportError('video.browser.error.timeout', { seconds: READY_MS / 1000 });
    }

    // Whether the page that draws has opened the recording and loaded what it draws, as _READY of
    // video.py asks it.
    pageState() {
        const win = this.frame.contentWindow;
        const doc = win && win.document;
        if (!doc) {
            return null;
        }
        const fatal = doc.getElementById('fatal');
        if (fatal && !fatal.hidden && fatal.textContent) {
            return { fatal: fatal.textContent };
        }
        const app = win.cuju;
        const loading = doc.getElementById('loading');
        return {
            ready: !!(win.cujuCapture && app && app.source && app.source.id === this.match && app.timeline
                && app.players && app.assets && (app.assets.manifest || app.assets.error) && loading && loading.hidden),
        };
    }

    // Holds the page at the first frame of the warm-up with the camera of the export, as _HOLD of
    // video.py does, and hides the scoreboard when the export leaves it out.
    hold(win, at) {
        const app = win.cuju;
        if (app.director.lineup && (this.body.broadcast !== true || at > 0)) {
            app.director.closeLineups(false);
        }
        // A short recording may play to its end while the page loads, so the card and the show
        // of its end go before the first frame is held.
        clearTimeout(app.fullTimeTimer);
        if (app.postMatch && app.postMatch.running) {
            app.postMatch.end();
        }
        if (app.transition && app.transition.title) {
            app.transition.title.hide();
        }
        app.endCard = false;
        app.timeline.pause();
        app.setCamera(this.body.camera);
        const tl = app.timeline;
        tl.seek(tl.first + at * tl.sps);
        app.afterSeek();
        if (app.cameras.jump) {
            app.cameras.jump();
        }
        if (this.body.score === false) {
            const style = win.document.createElement('style');
            style.textContent = HIDE_SCORE;
            win.document.head.append(style);
        }
    }

    // Seeks the held frame again, freezes the page's clocks and plays the match from there, as
    // _PLAY of video.py does.
    play(win, at) {
        const app = win.cuju;
        const tl = app.timeline;
        tl.pause();
        tl.seek(tl.first + at * tl.sps);
        app.afterSeek();
        if (app.cameras.jump) {
            app.cameras.jump();
        }
        win.cujuCapture.start();
        app.lastTime = win.performance.now();
        if (!app.director.lineup) {
            tl.play(1);
        }
    }

    // Runs the export and returns the file and what it holds.
    async run() {
        const { width, height, fps, quality } = this.body;
        const plan = exportPlan(this.body.start, this.body.end, fps);
        const chosen = await chooseEncoder(encoderCandidates(width, height, fps, quality, this.container), (config) => VideoEncoder.isConfigSupported(config));
        if (!chosen) {
            throw new ExportError('video.browser.error.codec', { container: this.container || '' });
        }
        const broadcast = this.body.broadcast === true;
        const total = broadcast ? this.maxFrames : plan.frames;
        const summary = { start: this.body.start, end: this.body.end, frames: plan.frames, width, height, fps };
        this.report({ state: 'running', frame: 0, progress: 0, ...summary });
        const layout = layoutFor(width, height, this.body.scale ?? 1);
        let encoder = null;
        try {
            const win = await this.openPage(layout);
            this.hold(win, plan.warmFrom);
            await sleep(SETTLE_MS);
            this.check();
            this.play(win, plan.warmFrom);
            const capture = win.cujuCapture;
            for (let i = 0; i < plan.warmFrames; i++) {
                capture.step(plan.step);
            }
            const writer = chosen.container === 'mp4'
                ? new Mp4Writer({ width, height, fps })
                : new WebmWriter({ width, height, fps, codec: chosen.config.codec });
            let failure = null;
            encoder = new VideoEncoder({
                output: (chunk, metadata) => {
                    const data = new Uint8Array(chunk.byteLength);
                    chunk.copyTo(data);
                    const description = metadata && metadata.decoderConfig && metadata.decoderConfig.description;
                    writer.add(data, { timestamp: chunk.timestamp, duration: chunk.duration ?? 0, key: chunk.type === 'key', description });
                },
                error: (error) => {
                    failure = error;
                },
            });
            encoder.configure(chosen.config);
            const canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;
            const context = canvas.getContext('2d', { alpha: false });
            context.imageSmoothingQuality = 'high';
            const view = win.cuju.view.renderer.domElement;
            const graphics = new DomPicture(win, view, layout.width, layout.height);
            const sx = width / layout.width;
            const sy = height / layout.height;
            let reported = 0;
            let written = 0;
            const tl = win.cuju.timeline;
            for (let i = 0; i < total; i++) {
                this.check();
                if (failure) {
                    throw new ExportError('video.browser.error.encoder', { error: String(failure.message || failure) }, failure);
                }
                capture.step(i === 0 ? 0 : plan.step);
                const position = (tl.t - tl.first) / tl.sps;
                if (broadcast && i >= 1 && position >= this.body.end) {
                    break;
                }
                // The view is read at once after it is drawn, before the browser shows and clears
                // it, and the graphics of the page follow over it.
                context.fillStyle = '#000';
                context.fillRect(0, 0, width, height);
                const rect = view.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    context.drawImage(view, rect.left * sx, rect.top * sy, rect.width * sx, rect.height * sy);
                }
                await graphics.draw(context, width, height);
                const picture = new VideoFrame(canvas, { timestamp: frameTime(i, fps), duration: frameDuration(i, fps) });
                encoder.encode(picture, { keyFrame: i % plan.keyEvery === 0 });
                picture.close();
                while (encoder.encodeQueueSize > QUEUE && !failure) {
                    await sleep(4);
                }
                written = i + 1;
                if (writer.bytes > this.maxBytes) {
                    throw new ExportError('video.browser.error.size', { mb: Math.round(this.maxBytes / 1048576) });
                }
                const now = performance.now();
                if (now - reported >= 250 || written === total) {
                    reported = now;
                    const share = broadcast ? (position - this.body.start) / Math.max(1e-9, this.body.end - this.body.start) : written / total;
                    this.report({ state: 'running', frame: written, progress: Math.min(1, Math.max(0, share)), position, ...summary });
                }
            }
            const limited = broadcast && written >= total;
            this.report({ state: 'running', frame: written, progress: 1, limited, ...summary });
            await encoder.flush();
            if (failure) {
                throw new ExportError('video.browser.error.encoder', { error: String(failure.message || failure) }, failure);
            }
            encoder.close();
            encoder = null;
            const blob = writer.finish();
            const filename = videoFileName(this.title, this.body.start, this.body.end, chosen.container);
            return {
                ...summary, frames: written, limited, state: 'done', blob, bytes: blob.size, filename,
                container: chosen.container, codec: chosen.config.codec,
            };
        } finally {
            if (encoder && encoder.state !== 'closed') {
                try {
                    encoder.close();
                } catch {
                    // An encoder that failed is closed already.
                }
            }
            this.close();
        }
    }

    // Removes the page that draws.
    close() {
        if (this.host) {
            this.host.remove();
            this.host = null;
            this.frame = null;
        }
    }
}
