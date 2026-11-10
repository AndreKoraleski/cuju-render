// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The diagnostic report of the Help page. One action gathers what the browser can do, WebGL,
// WebGPU, the decode worker, the sound and the storage, with the page's version and settings,
// and asks the server for its own side, the versions, the home folder, the library and the recent
// errors, as `cuju render doctor` prints them. The report is text to copy into an issue or a file
// to save. It holds no personal path beyond the home folder, which the server writes from `~`, and
// no secret. Making it never plays a sound and never decodes a recording. Scripts reach it as
// window.cuju.doctor. reportText at the top of the file touches nothing of the page, so it holds
// the same in a test.

import { lastDecoder } from '../recording/decode.js';

function h(tag, attributes = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) {
        if (key.startsWith('on') && typeof value === 'function') {
            node.addEventListener(key.slice(2), value);
        } else if (value !== null && value !== undefined && value !== false) {
            node.setAttribute(key, value === true ? '' : value);
        }
    }
    node.append(...children.flat().filter((child) => child !== null && child !== undefined));
    return node;
}

const yes = (value) => (value ? 'yes' : 'no');

function size(bytes) {
    if (typeof bytes !== 'number' || !Number.isFinite(bytes)) {
        return 'unknown';
    }
    const units = ['bytes', 'KB', 'MB', 'GB'];
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit++;
    }
    return unit === 0 ? `${value} bytes` : `${value.toFixed(1)} ${units[unit]}`;
}

// The report as lines of text, the page's side first and then the server's.
export function reportText(report) {
    const page = report.page || {};
    const lines = [`cuju render diagnostic report, ${report.created || ''}`, ''];
    const section = (title, rows) => {
        lines.push(title);
        for (const [key, value] of rows) {
            lines.push(`  ${key}: ${value === null || value === undefined || value === '' ? 'unknown' : value}`);
        }
        lines.push('');
    };
    section('Page', [
        ['version', page.version], ['address', page.origin], ['page', page.page], ['drawing', page.drawing],
        ['reduced motion', yes(page.reducedMotion)], ['theme', page.theme], ['installed', page.standalone ? 'yes, as an app' : 'no'],
        ['service worker', page.serviceWorker],
    ]);
    const browser = report.browser || {};
    section('Browser', [
        ['name', browser.name], ['platform', browser.platform], ['mobile', yes(browser.mobile)],
        ['language', browser.language], ['screen', browser.screen], ['window', browser.window],
        ['pixel ratio', browser.pixelRatio], ['cores', browser.cores], ['storage', browser.storage],
    ]);
    const gl = report.webgl || {};
    section('Graphics', [
        ['WebGL', yes(gl.webgl1)], ['WebGL 2', yes(gl.webgl2)], ['renderer', gl.renderer],
        ['largest texture', gl.maxTexture], ['WebGPU', report.webgpu ? report.webgpu.state : 'unknown'],
    ]);
    const decode = report.decode || {};
    section('Decoding', [['worker', decode.worker], ['last recording read by', decode.last || 'none yet']]);
    const audio = report.audio || {};
    section('Sound', [
        ['muted', yes(audio.muted)], ['volume', audio.volume], ['audio context', audio.context],
    ]);
    const server = report.server;
    if (!server || server.error) {
        lines.push('Server', `  ${server && server.error ? server.error : 'not asked'}`, '');
        return lines.join('\n').trimEnd();
    }
    const versions = server.versions || {};
    section('Server versions', Object.entries(versions).map(([key, value]) => [key, value === null ? 'not installed' : value]));
    const home = server.home || {};
    section('Home folder', [
        ['path', home.path], ['exists', yes(home.exists)], ['writable', yes(home.writable)], ['free space', size(home.free_bytes)],
    ]);
    const folders = Object.entries(server.folders || {});
    if (folders.length) {
        section('Folders', folders.map(([name, entry]) => [name, `${entry.files} files, ${size(entry.bytes)}`]));
    }
    section('Library', Object.entries(server.library || {}).map(([key, value]) => [key.replaceAll('_', ' '), value]));
    lines.push('Checks');
    for (const check of server.checks || []) {
        lines.push(`  ${check.ok ? 'ok' : 'FAIL'}  ${check.name}, ${check.detail}`);
    }
    lines.push('', 'Recent warnings and errors');
    const errors = server.errors || [];
    if (!errors.length) {
        lines.push('  none');
    }
    for (const entry of errors) {
        lines.push(`  ${entry.at ? `${entry.at} ` : ''}${entry.level} ${entry.message}`);
    }
    return lines.join('\n').trimEnd();
}

// The browser's name and platform, from the client hints where the browser has them.
function browserFacts() {
    const data = navigator.userAgentData;
    const brands = data && Array.isArray(data.brands)
        ? data.brands.filter((brand) => !/not.?a.?brand/i.test(brand.brand)).map((brand) => `${brand.brand} ${brand.version}`).join(', ')
        : '';
    return {
        name: brands || navigator.userAgent,
        platform: (data && data.platform) || navigator.platform || '',
        mobile: !!(data && data.mobile),
        language: navigator.language || '',
        screen: `${screen.width} by ${screen.height}`,
        window: `${window.innerWidth} by ${window.innerHeight}`,
        pixelRatio: Math.round((window.devicePixelRatio || 1) * 100) / 100,
        cores: navigator.hardwareConcurrency || null,
        storage: null,
    };
}

function webglFacts() {
    const facts = { webgl1: false, webgl2: false, renderer: null, maxTexture: null };
    for (const kind of ['webgl2', 'webgl']) {
        let gl = null;
        try {
            gl = document.createElement('canvas').getContext(kind);
        } catch {
            gl = null;
        }
        if (!gl) {
            continue;
        }
        facts[kind === 'webgl2' ? 'webgl2' : 'webgl1'] = true;
        if (!facts.renderer) {
            const info = gl.getExtension('WEBGL_debug_renderer_info');
            facts.renderer = info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
            facts.maxTexture = gl.getParameter(gl.MAX_TEXTURE_SIZE);
        }
        gl.getExtension('WEBGL_lose_context')?.loseContext();
    }
    if (facts.webgl2) {
        facts.webgl1 = true;
    }
    return facts;
}

async function webgpuFacts() {
    if (!navigator.gpu || typeof navigator.gpu.requestAdapter !== 'function') {
        return { state: 'not offered by this browser' };
    }
    try {
        const adapter = await Promise.race([
            navigator.gpu.requestAdapter(),
            new Promise((resolve) => setTimeout(() => resolve('late'), 2000)),
        ]);
        if (adapter === 'late') {
            return { state: 'offered, the adapter did not answer in time' };
        }
        if (!adapter) {
            return { state: 'offered, no adapter found' };
        }
        const info = adapter.info || {};
        const named = [info.vendor, info.architecture].filter(Boolean).join(' ');
        return { state: `available${named ? `, ${named}` : ''}` };
    } catch (err) {
        return { state: `offered, ${err.message}` };
    }
}

// Starts the decode worker and sends it three bytes, which it answers with a format error, so the
// worker shows it runs without reading a recording.
function workerFacts() {
    if (typeof Worker !== 'function') {
        return Promise.resolve('workers are not offered, recordings decode on the page');
    }
    return new Promise((resolve) => {
        let worker;
        const timer = setTimeout(() => {
            worker?.terminate();
            resolve('the worker did not answer in time, recordings decode on the page');
        }, 3000);
        try {
            worker = new Worker(new URL('../recording/decode-worker.js', import.meta.url), { type: 'module' });
        } catch (err) {
            clearTimeout(timer);
            resolve(`the worker did not start, ${err.message}`);
            return;
        }
        worker.onmessage = (event) => {
            clearTimeout(timer);
            worker.terminate();
            resolve(event.data && event.data.format ? 'runs' : 'answers in an unexpected way');
        };
        worker.onerror = (event) => {
            clearTimeout(timer);
            worker.terminate();
            event.preventDefault?.();
            resolve(`the worker failed, ${(event && event.message) || 'it did not load'}`);
        };
        worker.postMessage({ id: -1, bytes: new Uint8Array([1, 2, 3]) });
    });
}

async function getJson(path) {
    const res = await fetch(path, { cache: 'no-store' });
    if (!res.ok) {
        throw new Error(`the server answered ${res.status}`);
    }
    return res.json();
}

export class DoctorSection {
    constructor(app, host) {
        this.app = app;
        this.host = host;
        this.report = null;
        this.makeButton = h('button', { type: 'button', class: 'btn primary', onclick: () => this.make() }, 'Make the report');
        this.copyButton = h('button', { type: 'button', class: 'btn', disabled: true, onclick: () => this.copy() }, 'Copy');
        this.saveButton = h('button', { type: 'button', class: 'btn', disabled: true, onclick: () => this.save() }, 'Save as a file');
        this.status = h('p', { class: 'muted small', role: 'status', 'aria-live': 'polite' });
        this.output = h('textarea', {
            id: 'doctor-text', class: 'doctor-text', readonly: true, rows: '14', spellcheck: 'false', hidden: true,
            'aria-label': 'Diagnostic report',
        });
        host.replaceChildren(
            h('h3', { id: 'help-doctor-title' }, 'Diagnostic report'),
            h('p', {}, 'The report gathers the versions, the browser, WebGL and WebGPU, the decode worker, the sound, the home folder, the library and the recent errors of the server, to copy into an issue. It names no folder beyond the home folder of the renderer and holds no secret. The command ', h('code', {}, 'cuju render doctor'), ' prints the server side too.'),
            h('div', { class: 'help-row' }, this.makeButton, this.copyButton, this.saveButton),
            this.status,
            this.output);
        if (!document.getElementById('cuju-doctor-style')) {
            const style = document.createElement('style');
            style.id = 'cuju-doctor-style';
            style.textContent = `
#help-doctor { display: flex; flex-direction: column; gap: 8px; margin-bottom: 18px; }
.doctor-text { width: 100%; box-sizing: border-box; font-family: ui-monospace, Consolas, monospace; font-size: 12px;
    background: var(--surface-2); color: var(--text); border: 1px solid var(--border); padding: 8px; resize: vertical; }
.doctor-text[hidden] { display: none; }
`;
            document.head.appendChild(style);
        }
    }

    // Everything the report holds, the page's side and the server's.
    async gather() {
        const app = this.app;
        const report = { created: new Date().toISOString().slice(0, 19), page: {}, browser: browserFacts() };
        let version = null;
        try {
            version = (await getJson('/api/info')).version;
        } catch {
            version = null;
        }
        const worker = navigator.serviceWorker && navigator.serviceWorker.controller;
        const theme = document.getElementById('theme');
        report.page = {
            version,
            origin: location.origin,
            page: app.page,
            drawing: app.noWebGL ? '2D view, WebGL did not start' : (app.flat && app.flat.wanted ? '2D view' : '3D'),
            reducedMotion: !!app.reducedMotion,
            theme: theme ? theme.value : null,
            standalone: !!(window.matchMedia && window.matchMedia('(display-mode: standalone)').matches),
            serviceWorker: worker ? `controls the page, ${new URL(worker.scriptURL).pathname}${new URL(worker.scriptURL).search}` : 'none',
        };
        report.webgl = webglFacts();
        const [gpu, decoder, estimate] = await Promise.all([
            webgpuFacts(),
            workerFacts(),
            navigator.storage && navigator.storage.estimate ? navigator.storage.estimate().catch(() => null) : Promise.resolve(null),
        ]);
        report.webgpu = gpu;
        report.decode = { worker: decoder, last: lastDecoder };
        if (estimate && typeof estimate.usage === 'number') {
            report.browser.storage = `${size(estimate.usage)} of ${size(estimate.quota)}`;
        }
        const sound = app.sound;
        report.audio = {
            muted: !!(app.settings && app.settings.muted),
            volume: app.settings ? app.settings.volume : null,
            context: sound && sound.ctx ? sound.ctx.state : 'not started, the page starts it on Watch or Play',
        };
        try {
            report.server = await getJson('/api/help/doctor');
        } catch (err) {
            report.server = { error: `The server did not answer, ${err.message}. Start it with cuju render.` };
        }
        this.report = report;
        return report;
    }

    async make() {
        this.makeButton.disabled = true;
        this.status.textContent = 'Making the report.';
        try {
            const report = await this.gather();
            this.output.value = reportText(report);
            this.output.hidden = false;
            this.copyButton.disabled = false;
            this.saveButton.disabled = false;
            const failed = report.server && Array.isArray(report.server.checks) ? report.server.checks.filter((check) => !check.ok).length : 0;
            this.status.textContent = report.server && report.server.error
                ? 'The report is ready, without the server, which did not answer.'
                : `The report is ready, ${failed ? `${failed} ${failed === 1 ? 'check fails' : 'checks fail'}` : 'every check passes'}.`;
            return report;
        } catch (err) {
            this.status.textContent = `The report failed, ${err.message}`;
            throw err;
        } finally {
            this.makeButton.disabled = false;
        }
    }

    async text() {
        if (!this.report) {
            await this.make();
        }
        return reportText(this.report);
    }

    async copy() {
        const text = await this.text();
        try {
            await navigator.clipboard.writeText(text);
            this.status.textContent = 'The report is copied.';
            return true;
        } catch {
            // Without the clipboard, the text is selected for the person to copy.
            this.output.hidden = false;
            this.output.focus();
            this.output.select();
            this.status.textContent = 'The report is selected, Ctrl C copies it.';
            return false;
        }
    }

    async save() {
        const text = await this.text();
        const name = `cuju-report-${new Date().toISOString().slice(0, 10)}.txt`;
        const url = URL.createObjectURL(new Blob([`${text}\n`], { type: 'text/plain' }));
        const link = h('a', { href: url, download: name, hidden: true });
        document.body.append(link);
        this.lastSave = { name, bytes: text.length + 1 };
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        this.status.textContent = `The report is saved as ${name}.`;
        return name;
    }

    // The functions of window.cuju.doctor.
    script() {
        return {
            gather: () => this.make(),
            text: () => this.text(),
            copy: () => this.copy(),
            save: () => this.save(),
        };
    }
}
