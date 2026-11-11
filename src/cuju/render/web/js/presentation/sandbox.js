// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The bootstrap of the sandbox that runs a team's worker, section 15 of the contract. The server
// inlines this script into the page of its route /sandbox/presentation, which the renderer loads
// in an iframe with sandbox allow-scripts, so it runs in an opaque origin, without cookies,
// storage or access to the page. Its policy allows only this script, blob scripts and
// WebAssembly, and no connection at all, and its own sandbox directive keeps the origin opaque
// even when the route opens as a whole window.
//
// The bootstrap starts a worker only in an opaque origin, inside a frame, and only for a message
// of the page right above it whose origin is the route's own. A window that opens the route on its
// own, or a page of another site that frames it, starts nothing.
//
// The renderer posts the package's single file module as text with a MessagePort. The bootstrap
// turns the module into a blob, wraps it in a small script of its own and starts that as a worker,
// which imports the module and then talks to the renderer over the port alone. The worker checks
// that it reaches no network and no storage before the package's code runs and reports it in its
// first message.
//
// Before anything else the wrapper takes the GPU out of the worker's reach. Every OffscreenCanvas
// of the worker, the slots' own among them, offers the 2d context alone, a getContext that the
// package's code can neither replace nor redefine, navigator.gpu is gone and no nested worker
// starts, so a package reaches the GPU only through the shaders the renderer checks and compiles.
// The wrapper runs in a closure of its own, so the module sees none of its bindings, and it keeps
// the built in functions it calls later apart from the module, which may change their globals.

(() => {
    const WRAPPER = `
(() => {
    const apply = Reflect.apply;
    const text = String;
    const own = Object.hasOwn;
    const locked = (value) => ({ value, writable: false, configurable: false, enumerable: false });
    // The built in functions the wrapper calls once the package's module runs, kept apart from it.
    const getContext = OffscreenCanvas.prototype.getContext;
    const toBitmap = OffscreenCanvas.prototype.transferToImageBitmap;
    const post = MessagePort.prototype.postMessage;
    const dataOf = Object.getOwnPropertyDescriptor(MessageEvent.prototype, 'data').get;
    const now = performance.now.bind(performance);
    Object.defineProperty(OffscreenCanvas.prototype, 'getContext', locked(function (kind, options) {
        const name = text(kind);
        return name === '2d' ? apply(getContext, this, [name, options]) : null;
    }));
    if (self.WorkerNavigator && 'gpu' in WorkerNavigator.prototype) { Object.defineProperty(WorkerNavigator.prototype, 'gpu', locked(undefined)); }
    for (const name of ['Worker', 'SharedWorker']) { if (name in self) { Object.defineProperty(self, name, locked(undefined)); } }
    let port = null;
    let probeUrl = null;
    self.onmessage = (e) => { if (e.data && e.data.type === 'port' && !port) { port = e.data.port; probeUrl = text(e.data.probe); self.onmessage = null; listen(); } };
    async function probe(url) {
        let network = 'blocked';
        try { await fetch(url, { cache: 'no-store' }); network = 'open'; } catch (error) { network = 'blocked'; }
        let storage = self.origin === 'null' ? 'blocked' : 'open';
        try { if (self.indexedDB) { self.indexedDB.open('cuju-probe'); storage = 'open'; } } catch (error) { /* refused */ }
        try { if (self.caches) { await self.caches.keys(); storage = 'open'; } } catch (error) { /* refused */ }
        return { network, storage };
    }
    let mod = null;
    let instanceId = null;
    // The canvases of the overlay slots a package declares, which its worker draws in, and their sizes.
    const SLOTS = { badge: [96, 96], lowerThird: [360, 90], sting: [320, 180], card: [200, 200], lineup: [384, 270] };
    let canvases = {};
    const reply = (message, transfer = []) => {
        try { apply(post, port, [message, transfer]); } catch (error) {
            apply(post, port, [{ type: 'error', instanceId, message: 'the reply could not be sent, ' + text(error && error.message || error).slice(0, 200) }]);
        }
    };
    function listen() { port.onmessage = async (e) => {
        const m = apply(dataOf, e, []) || {};
        try {
            if (m.type === 'hello') {
                instanceId = m.hello.instanceId;
                const sealed = await probe(probeUrl);
                if (sealed.network !== 'blocked' || sealed.storage !== 'blocked') {
                    reply({ type: 'ready', instanceId, ...sealed });
                    return;
                }
                canvases = {};
                if (typeof OffscreenCanvas === 'function') {
                    for (const slot of m.hello.slots || []) {
                        if (own(SLOTS, slot)) { canvases[slot] = new OffscreenCanvas(SLOTS[slot][0], SLOTS[slot][1]); }
                    }
                }
                mod = await import(__MODULE__);
                if (typeof mod.init === 'function') { await mod.init({ ...m.hello, canvases: { ...canvases } }); }
                reply({ type: 'ready', instanceId, ...sealed });
            } else if (m.type === 'frame' && mod) {
                const start = now();
                const out = (typeof mod.frame === 'function' ? await mod.frame(m.frame) : null) || {};
                const transfer = [];
                const overlays = [];
                for (const o of Array.isArray(out.overlays) ? out.overlays.slice(0, 8) : []) {
                    const slot = o ? text(o.slot) : '';
                    const op = o ? text(o.op) : '';
                    if (own(canvases, slot) && (op === 'show' || op === 'draw')) {
                        const bitmap = apply(toBitmap, canvases[slot], []);
                        transfer.push(bitmap);
                        overlays.push({ slot, op, bitmap });
                    } else {
                        overlays.push(o ? { slot, op } : null);
                    }
                }
                reply({ ...out, overlays, type: 'response', instanceId, epoch: m.frame.epoch, sourceFrameId: m.frame.frameId, ms: now() - start }, transfer);
            } else if (m.type === 'ping') {
                reply({ type: 'pong', instanceId, at: m.at });
            } else if (m.type === 'dispose') {
                if (mod && typeof mod.dispose === 'function') { await mod.dispose(); }
                self.close();
            }
        } catch (error) {
            reply({ type: 'error', instanceId, message: text(error && error.message || error).slice(0, 300) });
        }
    }; }
})();
`;
    let framed = false;
    try {
        framed = window.parent !== window;
    } catch (error) {
        framed = false;
    }
    if (self.origin !== 'null' || !framed) {
        return;
    }
    const own = new URL(location.href).origin;
    // The address the worker tries before the package runs, which the sandbox names itself.
    const probe = new URL('/api/presentation-probe', location.href).href;
    let worker = null;
    addEventListener('message', (e) => {
        if (e.source !== window.parent || e.origin !== own) {
            return;
        }
        const m = e.data || {};
        if (m.type === 'start' && e.ports[0] && !worker) {
            const port = e.ports[0];
            const moduleUrl = URL.createObjectURL(new Blob([String(m.module)], { type: 'text/javascript' }));
            const wrapper = WRAPPER.replace('__MODULE__', JSON.stringify(moduleUrl));
            const url = URL.createObjectURL(new Blob([wrapper], { type: 'text/javascript' }));
            try {
                // A classic worker, since an opaque origin starts no module worker from a blob, and
                // the package's module loads in it by a dynamic import.
                worker = new Worker(url, { name: String(m.name || 'cuju team worker').slice(0, 80) });
            } catch (error) {
                e.source.postMessage({ type: 'error', instanceId: m.instanceId, message: `no worker, ${error.message}` }, '*');
                return;
            }
            worker.onerror = (ev) => {
                ev.preventDefault();
                e.source.postMessage({ type: 'error', instanceId: m.instanceId, message: `the worker failed, ${ev.message || 'without a message'}` }, '*');
            };
            worker.postMessage({ type: 'port', port, probe }, [port]);
        } else if (m.type === 'stop' && worker) {
            worker.terminate();
            worker = null;
        }
    });
})();
