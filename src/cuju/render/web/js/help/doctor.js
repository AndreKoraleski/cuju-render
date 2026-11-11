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
import { formatList, formatNumber, serverText, t, tOr, tn } from '../core/i18n.js';

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

const yes = (value) => (value ? t('doctor.yes') : t('doctor.no'));

// A number with one decimal, in the language's way, without grouping, as the server writes it.
const oneDecimal = (value) => formatNumber(value, { minimumFractionDigits: 1, maximumFractionDigits: 1, useGrouping: false });

function size(bytes) {
    if (typeof bytes !== 'number' || !Number.isFinite(bytes)) {
        return t('doctor.unknown');
    }
    const units = ['bytes', 'KB', 'MB', 'GB'];
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit++;
    }
    return unit === 0 ? t('doctor.size.bytes', { count: value }) : `${oneDecimal(value)} ${units[unit]}`;
}

// The checks of the server by the words of their details. Each name is the message
// doctor.check.<key>.name, and a detail that one of the patterns matches is the message
// doctor.check.<key>.<variant>, with the named parts of the pattern as its values. Any other
// detail shows as the server wrote it.
const CHECKS = {
    'home folder': ['home_folder', [
        ['file', /^the home folder is a file$/],
        ['under', /^the home folder lies under a file$/],
        ['missing', /^the home folder is missing, the server makes it as it starts$/],
        ['readonly', /^the home folder is not writable$/],
        ['exists', /^(?<path>.+) exists$/],
    ]],
    writing: ['writing', [
        ['ok', /^the server can write its folder$/],
        ['fail', /^the server cannot write its folder, choose another with --home$/],
    ]],
    'disk space': ['disk_space', [
        ['unknown', /^unknown$/],
        ['low', /^(?<size>\d+\.\d) GB free, recordings may fail to save$/],
        ['free', /^(?<size>\d+\.\d) GB free$/],
    ]],
    samples: ['samples', [
        ['count', /^(?<count>\d+) sample recordings ship with the package$/],
    ]],
    'page files': ['page_files', [
        ['ok', /^the files of the page are in place$/],
        ['missing', /^the page is missing, install cuju again$/],
    ]],
    'server file': ['server_file', [
        ['stale', /^a stale server\.json names a server that does not answer, the next start replaces it$/],
        ['running', /^the server of the folder answers$/],
        ['none', /^no server runs$/],
    ]],
    'video export': ['video_export', [
        ['found', /^Chrome and ffmpeg are found$/],
    ]],
};

// The name of a check of the server in the page's language.
// The status line of a report. It names the checks that fail and those that warn, and says that
// every check passes only when none does either.
export function reportStatus(report) {
    const server = report && report.server;
    if (!server || server.error) {
        return t('doctor.status.noServer');
    }
    const checks = Array.isArray(server.checks) ? server.checks : [];
    const failed = checks.filter((check) => !check.ok);
    const warned = checks.filter((check) => check.ok && check.warning);
    if (!failed.length && !warned.length) {
        return t('doctor.status.passing');
    }
    const parts = [];
    if (failed.length) {
        parts.push(t('doctor.status.failing', { count: failed.length, names: formatList(failed.map(checkName)) }));
    }
    if (warned.length) {
        parts.push(t('doctor.status.warning', { count: warned.length, names: formatList(warned.map(checkName)) }));
    }
    return t('doctor.status.ready', { parts: parts.join(' ') });
}

export function checkName(check) {
    if (check.name_id) {
        return serverText(check, 'name');
    }
    const known = CHECKS[check.name];
    return known ? tOr(`doctor.check.${known[0]}.name`, check.name) : String(check.name ?? '');
}

// The detail of a check of the server in the page's language.
export function checkDetail(check) {
    if (check.detail_id) {
        return serverText(check, 'detail');
    }
    const detail = String(check.detail ?? '');
    const known = CHECKS[check.name];
    if (!known) {
        return detail;
    }
    for (const [variant, pattern] of known[1]) {
        const match = detail.match(pattern);
        if (match) {
            const values = { ...(match.groups || {}) };
            if (values.size !== undefined) {
                values.size = oneDecimal(Number(values.size));
            }
            if (values.count !== undefined) {
                values.count = Number(values.count);
            }
            return tOr(`doctor.check.${known[0]}.${variant}`, detail, values);
        }
    }
    return detail;
}

// The report as lines of text, the page's side first and then the server's.
export function reportText(report) {
    const page = report.page || {};
    const lines = [t('doctor.report.head', { created: report.created || '' }), ''];
    // Each section's title is the message doctor.section.<key>, and each row's name the message
    // doctor.row.<key>, unless the row names a package, a folder or a count of the server.
    const row = (key, value) => [t(`doctor.row.${key}`), value];
    const section = (key, rows) => {
        lines.push(t(`doctor.section.${key}`));
        for (const [name, value] of rows) {
            lines.push(`  ${name}: ${value === null || value === undefined || value === '' ? t('doctor.unknown') : value}`);
        }
        lines.push('');
    };
    section('page', [
        row('version', page.version), row('address', page.origin), row('page', page.page), row('drawing', page.drawing),
        row('reducedMotion', yes(page.reducedMotion)), row('theme', page.theme), row('installed', page.standalone ? t('doctor.installed.app') : t('doctor.no')),
        row('serviceWorker', page.serviceWorker),
    ]);
    const browser = report.browser || {};
    section('browser', [
        row('name', browser.name), row('platform', browser.platform), row('mobile', yes(browser.mobile)),
        row('language', browser.language), row('screen', browser.screen), row('window', browser.window),
        row('pixelRatio', browser.pixelRatio), row('cores', browser.cores), row('storage', browser.storage),
    ]);
    const gl = report.webgl || {};
    section('graphics', [
        ['WebGL', yes(gl.webgl1)], ['WebGL 2', yes(gl.webgl2)], row('renderer', gl.renderer),
        row('largestTexture', gl.maxTexture), ['WebGPU', report.webgpu ? report.webgpu.state : t('doctor.unknown')],
    ]);
    const decode = report.decode || {};
    section('decoding', [row('worker', decode.worker), row('lastDecoder', decode.last || t('doctor.noneYet'))]);
    const audio = report.audio || {};
    section('sound', [
        row('muted', yes(audio.muted)), row('volume', audio.volume), row('audioContext', audio.context),
    ]);
    const server = report.server;
    if (!server || server.error) {
        lines.push(t('doctor.section.server'), `  ${server && server.error ? server.error : t('doctor.server.notAsked')}`, '');
        return lines.join('\n').trimEnd();
    }
    const versions = server.versions || {};
    section('versions', Object.entries(versions).map(([key, value]) => [key, value === null ? t('doctor.notInstalled') : value]));
    const home = server.home || {};
    section('home', [
        row('path', home.path), row('exists', yes(home.exists)), row('writable', yes(home.writable)), row('freeSpace', size(home.free_bytes)),
    ]);
    const folders = Object.entries(server.folders || {});
    if (folders.length) {
        section('folders', folders.map(([name, entry]) => [name, t('doctor.folder', { count: entry.files, size: size(entry.bytes) })]));
    }
    section('library', Object.entries(server.library || {}).map(([key, value]) => [tOr(`doctor.library.${key}`, key.replaceAll('_', ' ')), value]));
    lines.push(t('doctor.section.checks'));
    for (const check of server.checks || []) {
        lines.push(`  ${!check.ok ? t('doctor.check.fail') : check.warning ? t('doctor.check.warn') : t('doctor.check.ok')}  ${checkName(check)}, ${checkDetail(check)}`);
    }
    lines.push('', t('doctor.section.errors'));
    const errors = server.errors || [];
    if (!errors.length) {
        lines.push(`  ${t('doctor.none')}`);
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
        screen: t('doctor.by', { width: screen.width, height: screen.height }),
        window: t('doctor.by', { width: window.innerWidth, height: window.innerHeight }),
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
        return { state: t('doctor.webgpu.none') };
    }
    try {
        const adapter = await Promise.race([
            navigator.gpu.requestAdapter(),
            new Promise((resolve) => setTimeout(() => resolve('late'), 2000)),
        ]);
        if (adapter === 'late') {
            return { state: t('doctor.webgpu.late') };
        }
        if (!adapter) {
            return { state: t('doctor.webgpu.noAdapter') };
        }
        const info = adapter.info || {};
        const named = [info.vendor, info.architecture].filter(Boolean).join(' ');
        return { state: named ? t('doctor.webgpu.named', { adapter: named }) : t('doctor.webgpu.available') };
    } catch (err) {
        return { state: t('doctor.webgpu.failed', { error: err.message }) };
    }
}

// Starts the decode worker and sends it three bytes, which it answers with a format error, so the
// worker shows it runs without reading a recording.
function workerFacts() {
    if (typeof Worker !== 'function') {
        return Promise.resolve(t('doctor.worker.none'));
    }
    return new Promise((resolve) => {
        let worker;
        const timer = setTimeout(() => {
            worker?.terminate();
            resolve(t('doctor.worker.late'));
        }, 3000);
        try {
            worker = new Worker(new URL('../recording/decode-worker.js', import.meta.url), { type: 'module' });
        } catch (err) {
            clearTimeout(timer);
            resolve(t('doctor.worker.start', { error: err.message }));
            return;
        }
        worker.onmessage = (event) => {
            clearTimeout(timer);
            worker.terminate();
            resolve(event.data && event.data.format ? t('doctor.worker.runs') : t('doctor.worker.odd'));
        };
        worker.onerror = (event) => {
            clearTimeout(timer);
            worker.terminate();
            event.preventDefault?.();
            resolve(t('doctor.worker.failed', { error: (event && event.message) || t('doctor.worker.notLoaded') }));
        };
        worker.postMessage({ id: -1, bytes: new Uint8Array([1, 2, 3]) });
    });
}

async function getJson(path) {
    const res = await fetch(path, { cache: 'no-store' });
    if (!res.ok) {
        throw new Error(t('doctor.error.status', { status: res.status }));
    }
    return res.json();
}

export class DoctorSection {
    constructor(app, host) {
        this.app = app;
        this.host = host;
        this.report = null;
        this.makeButton = h('button', { type: 'button', class: 'btn primary', onclick: () => this.make() }, t('doctor.make'));
        this.copyButton = h('button', { type: 'button', class: 'btn', disabled: true, onclick: () => this.copy() }, t('doctor.copy'));
        this.saveButton = h('button', { type: 'button', class: 'btn', disabled: true, onclick: () => this.save() }, t('doctor.save'));
        this.status = h('p', { class: 'muted small', role: 'status', 'aria-live': 'polite' });
        this.output = h('textarea', {
            id: 'doctor-text', class: 'doctor-text', readonly: true, rows: '14', spellcheck: 'false', hidden: true,
            'aria-label': t('doctor.title'),
        });
        host.replaceChildren(
            h('h2', { id: 'help-doctor-title' }, t('doctor.title')),
            h('p', {}, tn('doctor.text', { command: h('code', {}, 'cuju render doctor') })),
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
            drawing: app.noWebGL ? t('doctor.drawing.noWebGL') : (app.flat && app.flat.wanted ? t('doctor.drawing.flat') : '3D'),
            reducedMotion: !!app.reducedMotion,
            theme: theme ? theme.value : null,
            standalone: !!(window.matchMedia && window.matchMedia('(display-mode: standalone)').matches),
            serviceWorker: worker ? t('doctor.serviceWorker', { path: `${new URL(worker.scriptURL).pathname}${new URL(worker.scriptURL).search}` }) : t('doctor.none'),
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
            report.browser.storage = t('doctor.storage', { used: size(estimate.usage), quota: size(estimate.quota) });
        }
        const sound = app.sound;
        report.audio = {
            muted: !!(app.settings && app.settings.muted),
            volume: app.settings ? app.settings.volume : null,
            context: sound && sound.ctx ? sound.ctx.state : t('doctor.audio.notStarted'),
        };
        try {
            report.server = await getJson('/api/help/doctor');
        } catch (err) {
            report.server = { error: t('doctor.server.failed', { error: err.message }) };
        }
        this.report = report;
        return report;
    }

    async make() {
        this.makeButton.disabled = true;
        this.status.textContent = t('doctor.status.making');
        try {
            const report = await this.gather();
            this.output.value = reportText(report);
            this.output.hidden = false;
            this.copyButton.disabled = false;
            this.saveButton.disabled = false;
            this.status.textContent = reportStatus(report);
            return report;
        } catch (err) {
            this.status.textContent = t('doctor.status.failed', { error: err.message });
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
            this.status.textContent = t('doctor.status.copied');
            return true;
        } catch {
            // Without the clipboard, the text is selected for the person to copy.
            this.output.hidden = false;
            this.output.focus();
            this.output.select();
            this.status.textContent = t('doctor.status.selected');
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
        this.status.textContent = t('doctor.status.saved', { name });
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
