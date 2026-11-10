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

import { LATE_MS, SILENT_MS } from './budget.js';
import { MAXIMUM_REPLY } from './protocol.js';

export const SANDBOX_ROUTE = '/sandbox/presentation';
export const RESTARTS = 1;
export const RESTART_DELAY_MS = 1000;
// A worker counts as silent once SILENT_MS passed and the page drew this many times since, so a
// page that draws a frame in seconds, a slow machine or a headless browser, waits for the reply
// its own slowness held back.
export const SILENT_DRAWINGS = 3;

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

    setStatus(status, detail = '') {
        this.status = status;
        if (this.options.onStatus) {
            this.options.onStatus(status, detail);
        }
    }

    start() {
        const o = this.options;
        this.inFlight = null;
        this.lastHeard = performance.now();
        if (o.developer) {
            import(o.url).then(async (mod) => {
                this.module = mod;
                if (typeof mod.init === 'function') {
                    await mod.init({ ...o.hello, developer: o.context || null });
                }
                if (!this.disposed) {
                    this.setStatus('ready', 'developer');
                }
            }).catch((err) => this.fail(`the module did not load, ${err.message || err}`));
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
                this.fail(e.data.message);
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
            this.port.postMessage({ type: 'hello', hello: o.hello, probe: new URL('/api/presentation-probe', globalThis.location.href).href });
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
            if (m.network !== 'blocked') {
                this.fail('the sandbox could reach the network, the worker stays off', true);
                return;
            }
            this.setStatus('ready', 'sandbox');
        } else if (m.type === 'error') {
            this.fail(`the worker threw, ${m.message}`);
        } else if (m.type === 'response') {
            this.answer(m);
        }
    }

    answer(m) {
        const sent = this.inFlight;
        this.inFlight = null;
        let size = 0;
        try {
            size = JSON.stringify(m).length;
        } catch {
            size = Infinity;
        }
        if (size > MAXIMUM_REPLY) {
            this.fail('the worker answered with too much');
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

    // Whether a Frame may go now, ready with nothing outstanding. A worker silent for SILENT_MS
    // fails.
    wants(now = performance.now()) {
        if (this.status !== 'ready') {
            if (this.status === 'starting' && now - this.lastHeard > SILENT_MS * 5) {
                this.fail('the sandbox did not start');
            }
            return false;
        }
        if (this.inFlight) {
            if (now - this.inFlight.at > SILENT_MS) {
                this.inFlight.waits = (this.inFlight.waits || 0) + 1;
                if (this.inFlight.waits >= SILENT_DRAWINGS) {
                    this.fail(`the worker stayed silent for ${SILENT_MS / 1000} s`);
                }
            }
            return false;
        }
        return true;
    }

    send(frame, now = performance.now()) {
        this.inFlight = { at: now, frameId: frame.frameId };
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
        }).catch((err) => this.fail(`the module threw, ${err.message || err}`));
    }

    fail(reason, final = false) {
        if (this.disposed || this.status === 'failed' || this.status === 'restarting') {
            return;
        }
        this.failures.push(reason);
        this.stopSandbox();
        const again = !final && this.restarts < RESTARTS;
        this.setStatus(again ? 'restarting' : 'failed', reason);
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
