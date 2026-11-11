// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The host of one team's worker, section 15 of the contract. Each instance gets its own sandbox,
// an iframe of the route /sandbox/presentation with sandbox allow-scripts, so its opaque origin
// shares nothing with the page or another team. The host hands the package's single file module
// to it as text with a MessagePort, and from then on talks to the worker over that port alone.
// In developer mode, for a trusted local folder that the renderer's home names, the module runs on
// the page itself with direct access instead, which the page marks.
//
// The host sends one Frame at a time and coalesces the drawings in between, their events
// accumulated by the caller. A reply later than LATE_MS is used and counted late. A worker that
// throws, refuses its sandbox or stays silent for SILENT_MS is ended, the page fades what it drove
// back to the manifest's own look, and the host starts it once more. A second failure leaves the
// team without its worker.
//
// Silence is counted in the time the page draws, each drawing adding at most SILENT_STEP_MS, so
// a page that stalls while it loads models and compiles programs never charges its own stall to
// the worker. Before its first answer a worker has FIRST_SILENT_MS.
//
// A reply of the sandbox holds plain data alone, objects, arrays, typed arrays and primitives, so
// its size in JSON is its size, and its only bitmaps sit in at most MAXIMUM_OVERLAYS overlays, each
// at the size of its slot. A reply of anything else ends the worker as a failure.

import { FIRST_SILENT_MS, LATE_MS, SILENT_MS } from './budget.js';
import { SLOT_SIZES } from './commands.js';
import { MAXIMUM_REPLY } from './protocol.js';

export const SANDBOX_ROUTE = '/sandbox/presentation';
export const RESTARTS = 1;
export const RESTART_DELAY_MS = 1000;
// A worker counts as silent once SILENT_MS passed and the page drew this many times since, so a
// page that draws a frame in seconds, a slow machine or a headless browser, waits for the reply
// its own slowness held back.
export const SILENT_DRAWINGS = 3;
// The most one drawing adds to the silence of a worker, in milliseconds.
export const SILENT_STEP_MS = 100;
// The most overlays a reply carries, the most parts of plain data it holds and how deep they nest.
export const MAXIMUM_OVERLAYS = 8;
export const MAXIMUM_PARTS = 100000;
export const MAXIMUM_NESTING = 64;

const isBitmap = (value) => typeof ImageBitmap !== 'undefined' && value instanceof ImageBitmap;

// Why a reply of the sandbox may not pass, or null when it may. Every bitmap sits in an overlay of
// a slot at that slot's size, at most MAXIMUM_OVERLAYS of them, and everything else is plain data.
export function replyProblem(m) {
    const bitmaps = new Set();
    if (m.overlays !== undefined) {
        if (!Array.isArray(m.overlays) || m.overlays.length > MAXIMUM_OVERLAYS) {
            return `overlays beyond a list of ${MAXIMUM_OVERLAYS}`;
        }
        for (const o of m.overlays) {
            const bitmap = o && typeof o === 'object' ? o.bitmap : undefined;
            if (bitmap === undefined || bitmap === null) {
                continue;
            }
            const size = typeof o.slot === 'string' && Object.hasOwn(SLOT_SIZES, o.slot) ? SLOT_SIZES[o.slot] : null;
            if (!isBitmap(bitmap) || !size || bitmap.width !== size[0] || bitmap.height !== size[1]) {
                const shape = isBitmap(bitmap) ? `a bitmap of ${bitmap.width} by ${bitmap.height} pixels` : 'something else';
                return `${shape} for the slot ${String(o.slot).slice(0, 40)}`;
            }
            bitmaps.add(bitmap);
        }
    }
    const stack = [[m, 0]];
    let parts = 0;
    while (stack.length) {
        const [value, depth] = stack.pop();
        if (value === null || typeof value !== 'object' || bitmaps.has(value)) {
            continue;
        }
        if (++parts > MAXIMUM_PARTS || depth > MAXIMUM_NESTING) {
            return 'more parts than a reply holds';
        }
        if (ArrayBuffer.isView(value) && !(value instanceof DataView)) {
            continue;
        }
        const proto = Object.getPrototypeOf(value);
        if (!Array.isArray(value) && proto !== Object.prototype && proto !== null) {
            return `${isBitmap(value) ? 'a bitmap outside its slot' : 'an object other than plain data'}`;
        }
        for (const key of Object.keys(value)) {
            stack.push([value[key], depth + 1]);
        }
    }
    return null;
}

export class ModuleHost {
    // options: source, the module's text, or url for developer mode, instanceId, hello, the Hello
    // message, developer, context, what a developer module's init also receives, document, where
    // the sandbox iframe goes, onResponse(message), onStatus(status, detail).
    constructor(options) {
        this.options = options;
        this.status = 'starting';
        this.inFlight = null;
        this.restarts = 0;
        this.failures = [];
        this.late = 0;
        this.answered = 0;
        this.disposed = false;
        this.sealed = null;
        this.frame = null;
        this.port = null;
        this.module = null;
        this.start();
    }

    get ready() {
        return this.status === 'ready';
    }

    // The detail is the English reason of a failure, and label the same reason as a message of
    // the language files, presentation.reason.<name>, which the page shows in its language.
    setStatus(status, detail = '', label = null) {
        this.status = status;
        if (this.options.onStatus) {
            this.options.onStatus(status, detail, label);
        }
    }

    // Fails with a reason of the language files, its English text first.
    failWith(name, text, values = {}, final = false) {
        this.fail(text, final, { id: `presentation.reason.${name}`, text, values });
    }

    start() {
        const o = this.options;
        this.inFlight = null;
        this.lastHeard = performance.now();
        this.lastWants = null;
        this.startWait = 0;
        if (o.developer) {
            import(o.url).then(async (mod) => {
                this.module = mod;
                if (typeof mod.init === 'function') {
                    await mod.init({ ...o.hello, developer: o.context || null });
                }
                if (!this.disposed) {
                    this.setStatus('ready', 'developer');
                }
            }).catch((err) => this.failWith('moduleLoad', `the module did not load, ${err.message || err}`, { error: String(err.message || err) }));
            return;
        }
        const doc = o.document || globalThis.document;
        const frame = doc.createElement('iframe');
        frame.setAttribute('sandbox', 'allow-scripts');
        frame.setAttribute('aria-hidden', 'true');
        frame.setAttribute('tabindex', '-1');
        frame.title = 'Team presentation sandbox';
        frame.style.cssText = 'position:absolute;width:0;height:0;border:0;visibility:hidden';
        frame.src = SANDBOX_ROUTE;
        this.frame = frame;
        this.onWindowMessage = (e) => {
            if (e.source === frame.contentWindow && e.data && e.data.instanceId === o.instanceId && e.data.type === 'error') {
                const known = e.data.reason === 'noWorker' || e.data.reason === 'workerFailed';
                if (known) {
                    this.failWith(e.data.reason, String(e.data.message), { error: String(e.data.error ?? '') });
                } else {
                    this.fail(e.data.message);
                }
            }
        };
        globalThis.addEventListener('message', this.onWindowMessage);
        frame.addEventListener('load', () => {
            if (this.disposed || this.frame !== frame) {
                return;
            }
            const channel = new MessageChannel();
            this.port = channel.port1;
            this.port.onmessage = (e) => this.receive(e.data);
            frame.contentWindow.postMessage({ type: 'start', module: o.source, instanceId: o.instanceId, name: `cuju team ${o.instanceId}` }, '*', [channel.port2]);
            this.port.postMessage({ type: 'hello', hello: o.hello });
        }, { once: true });
        doc.body.appendChild(frame);
    }

    receive(m) {
        if (this.disposed || !m || m.instanceId !== this.options.instanceId) {
            return;
        }
        this.lastHeard = performance.now();
        if (m.type === 'ready') {
            this.sealed = { network: m.network, storage: m.storage };
            if (m.network !== 'blocked' || m.storage !== 'blocked') {
                this.failWith('reached', 'the sandbox could reach the network or storage, the worker stays off', {}, true);
                return;
            }
            this.setStatus('ready', 'sandbox');
        } else if (m.type === 'error') {
            this.failWith('threw', `the worker threw, ${m.message}`, { error: String(m.message) });
        } else if (m.type === 'response') {
            this.answer(m);
        }
    }

    answer(m) {
        const sent = this.inFlight;
        this.inFlight = null;
        const problem = this.port ? replyProblem(m) : null;
        if (problem) {
            for (const o of Array.isArray(m.overlays) ? m.overlays : []) {
                if (o && isBitmap(o.bitmap)) {
                    o.bitmap.close();
                }
            }
            this.failWith('answer', `the worker answered with ${problem}`, { problem });
            return;
        }
        let size = 0;
        try {
            size = JSON.stringify(m).length;
        } catch {
            size = Infinity;
        }
        if (size > MAXIMUM_REPLY) {
            this.failWith('tooMuch', 'the worker answered with too much');
            return;
        }
        this.answered += 1;
        if (sent) {
            m.roundTrip = performance.now() - sent.at;
            if (m.roundTrip > LATE_MS) {
                this.late += 1;
            }
        }
        this.options.onResponse(m);
    }

    // Whether a Frame may go now, ready with nothing outstanding, called once a drawing. A worker
    // silent for SILENT_MS of drawing time, FIRST_SILENT_MS before its first answer, fails.
    wants(now = performance.now()) {
        const step = this.lastWants == null ? 0 : Math.min(SILENT_STEP_MS, Math.max(0, now - this.lastWants));
        this.lastWants = now;
        if (this.status !== 'ready') {
            this.startWait = this.status === 'starting' ? this.startWait + step : 0;
            if (this.status === 'starting' && this.startWait > FIRST_SILENT_MS * 2) {
                this.failWith('noStart', 'the sandbox did not start');
            }
            return false;
        }
        if (this.inFlight) {
            const limit = this.answered ? SILENT_MS : FIRST_SILENT_MS;
            this.inFlight.waited += step;
            if (this.inFlight.waited > limit) {
                this.inFlight.waits = (this.inFlight.waits || 0) + 1;
                if (this.inFlight.waits >= SILENT_DRAWINGS) {
                    this.failWith('silent', `the worker stayed silent for ${limit / 1000} s`, { seconds: limit / 1000 });
                }
            }
            return false;
        }
        return true;
    }

    send(frame, now = performance.now()) {
        this.inFlight = { at: now, frameId: frame.frameId, waited: 0 };
        if (this.port) {
            this.port.postMessage({ type: 'frame', frame });
            return;
        }
        // Developer mode calls the module on the page, still one Frame at a time.
        const mod = this.module;
        const start = performance.now();
        Promise.resolve().then(() => (mod && typeof mod.frame === 'function' ? mod.frame(frame) : null)).then((out) => {
            if (!this.disposed && this.inFlight && this.inFlight.frameId === frame.frameId) {
                this.answer({ ...(out || {}), type: 'response', instanceId: this.options.instanceId, epoch: frame.epoch, sourceFrameId: frame.frameId, ms: performance.now() - start });
            }
        }).catch((err) => this.failWith('moduleThrew', `the module threw, ${err.message || err}`, { error: String(err.message || err) }));
    }

    fail(reason, final = false, label = null) {
        if (this.disposed || this.status === 'failed' || this.status === 'restarting') {
            return;
        }
        this.failures.push(reason);
        this.stopSandbox();
        const again = !final && this.restarts < RESTARTS;
        this.setStatus(again ? 'restarting' : 'failed', reason, label);
        if (again) {
            this.restarts += 1;
            this.timer = setTimeout(() => {
                if (!this.disposed) {
                    this.setStatus('starting');
                    this.start();
                }
            }, RESTART_DELAY_MS);
        }
    }

    stopSandbox() {
        this.inFlight = null;
        if (this.port) {
            try {
                this.port.postMessage({ type: 'dispose' });
            } catch {
                // A port already closed needs no notice.
            }
            this.port.close();
            this.port = null;
        }
        if (this.frame) {
            this.frame.remove();
            this.frame = null;
        }
        if (this.onWindowMessage) {
            globalThis.removeEventListener('message', this.onWindowMessage);
            this.onWindowMessage = null;
        }
        this.module = null;
    }

    dispose() {
        if (this.disposed) {
            return;
        }
        this.disposed = true;
        clearTimeout(this.timer);
        this.stopSandbox();
        this.setStatus('disposed');
    }
}
