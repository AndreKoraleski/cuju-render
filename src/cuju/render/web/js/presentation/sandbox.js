// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The bootstrap of the sandbox that runs a team's worker, section 15 of the contract. The server
// inlines this script into the page of its route /sandbox/presentation, which the renderer loads
// in an iframe with sandbox allow-scripts, so it runs in an opaque origin, without cookies,
// storage or access to the page. Its policy allows only this script, blob scripts and
// WebAssembly, and no connection at all.
//
// The renderer posts the package's single file module as text with a MessagePort. The bootstrap
// turns the module into a blob, wraps it in a small script of its own and starts that as a worker,
// which imports the module and then talks to the renderer over the port alone. The worker checks
// that it reaches no network and no storage before the package's code runs and reports it in its
// first message.

(() => {
    const WRAPPER = `
let port = null;
self.onmessage = (e) => { if (e.data && e.data.type === 'port' && !port) { port = e.data.port; listen(); } };
async function probe(url) {
    let network = 'blocked';
    try { await fetch(url, { cache: 'no-store' }); network = 'open'; } catch (error) { network = 'blocked'; }
    let storage = 'blocked';
    try { if (self.indexedDB) { self.indexedDB.open('cuju-probe'); storage = 'open'; } } catch (error) { storage = 'blocked'; }
    return { network, storage };
}
let mod = null;
let instanceId = null;
// The canvases of the overlay slots a package declares, which its worker draws in, and their sizes.
const SLOTS = { badge: [96, 96], lowerThird: [360, 90], sting: [320, 180], card: [200, 200], lineup: [384, 270] };
let canvases = {};
const reply = (message, transfer = []) => {
    try { port.postMessage(message, transfer); } catch (error) {
        port.postMessage({ type: 'error', instanceId, message: 'the reply could not be sent, ' + String(error && error.message || error).slice(0, 200) });
    }
};
function listen() { port.onmessage = async (e) => {
    const m = e.data || {};
    try {
        if (m.type === 'hello') {
            instanceId = m.hello.instanceId;
            const sealed = await probe(m.probe);
            if (sealed.network !== 'blocked') {
                reply({ type: 'ready', instanceId, ...sealed });
                return;
            }
            canvases = {};
            if (typeof OffscreenCanvas === 'function') {
                for (const slot of m.hello.slots || []) {
                    if (SLOTS[slot]) { canvases[slot] = new OffscreenCanvas(SLOTS[slot][0], SLOTS[slot][1]); }
                }
            }
            mod = await import(__MODULE__);
            if (typeof mod.init === 'function') { await mod.init({ ...m.hello, canvases }); }
            reply({ type: 'ready', instanceId, ...sealed });
        } else if (m.type === 'frame' && mod) {
            const start = performance.now();
            const out = (typeof mod.frame === 'function' ? await mod.frame(m.frame) : null) || {};
            const transfer = [];
            if (Array.isArray(out.overlays)) {
                out.overlays = out.overlays.slice(0, 8).map((o) => {
                    const canvas = o && canvases[o.slot];
                    if (canvas && (o.op === 'show' || o.op === 'draw')) {
                        const bitmap = canvas.transferToImageBitmap();
                        transfer.push(bitmap);
                        return { slot: o.slot, op: o.op, bitmap };
                    }
                    return o && { slot: o.slot, op: o.op };
                });
            }
            reply({ ...out, type: 'response', instanceId, epoch: m.frame.epoch, sourceFrameId: m.frame.frameId, ms: performance.now() - start }, transfer);
        } else if (m.type === 'ping') {
            reply({ type: 'pong', instanceId, at: m.at });
        } else if (m.type === 'dispose') {
            if (mod && typeof mod.dispose === 'function') { await mod.dispose(); }
            self.close();
        }
    } catch (error) {
        reply({ type: 'error', instanceId, message: String(error && error.message || error).slice(0, 300) });
    }
}; }
`;
    let worker = null;
    addEventListener('message', (e) => {
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
            worker.postMessage({ type: 'port', port }, [port]);
        } else if (m.type === 'stop' && worker) {
            worker.terminate();
            worker = null;
        }
    });
})();
