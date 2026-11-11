// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The Export video dialog of the Watch page. It asks the server to draw a range of the open
// recording into an MP4 file with Chrome and ffmpeg, as `cuju render video` does, follows the
// export's progress and offers the file once it is ready. A server without Chrome or ffmpeg says
// what is missing and how to install it.

import { ARENA_LABELS } from '../world/arenas.js';
import { serverText, t } from '../core/i18n.js';
import { h } from '../teams/library.js';
import { teamName } from '../core/names.js';
import { sizeFields } from './size-fields.js';
import {
    VIDEO_CAMERAS, VIDEO_MAX_SECONDS, VIDEO_QUALITIES, VIDEO_RATES, checkRange, exportRequest,
    formatMoment, goalRange, progressText,
} from './video-range.js';

async function call(method, path, json) {
    const init = { method, cache: 'no-store', headers: {} };
    if (json !== undefined) {
        init.body = JSON.stringify(json);
        init.headers['Content-Type'] = 'application/json';
    }
    let res;
    try {
        res = await fetch(path, init);
    } catch {
        throw new Error(t('video.error.unreachable'));
    }
    const text = await res.text();
    let value = null;
    try {
        value = text ? JSON.parse(text) : null;
    } catch {
        value = null;
    }
    if (!res.ok) {
        const error = new Error((value && serverText(value)) || t('video.error.status', { status: res.status }));
        error.status = res.status;
        throw error;
    }
    return value;
}

const hourText = (hour) => {
    const whole = Math.floor(hour);
    return `${String(whole).padStart(2, '0')}:${String(Math.round((hour - whole) * 60)).padStart(2, '0')}`;
};

export class VideoExport {
    constructor(app) {
        this.app = app;
        this.entry = null;
        this.timer = null;
        this.dialog = h('dialog', { class: 'video-export', 'aria-labelledby': 'video-export-title' });
        document.getElementById('app').appendChild(this.dialog);
        this.dialog.addEventListener('close', () => this.stopPolling());
        this.button = document.getElementById('video-export-btn');
        if (this.button) {
            this.button.addEventListener('click', () => this.open());
        }
    }

    // The recording of the library that Watch shows, or null for a file, a live source or none.
    recording() {
        const source = this.app.source;
        return source && source.kind === 'match' && this.app.timeline ? source : null;
    }

    async open() {
        if (this.dialog.open) {
            return;
        }
        if (document.pointerLockElement) {
            document.exitPointerLock();
        }
        if (this.recording()) {
            this.app.act('pause');
        }
        this.render(null);
        this.dialog.showModal();
        const source = this.recording();
        if (!source) {
            return;
        }
        let status;
        try {
            status = await call('GET', '/api/video');
        } catch (err) {
            status = { available: false, missing: [err.status === 404 ? t('video.error.no_export') : err.message] };
        }
        if (!this.dialog.open) {
            return;
        }
        this.render(status);
        // An export of this recording that runs or finished in this server's lifetime shows again.
        try {
            const list = await call('GET', '/api/videos');
            const latest = (list || []).find((e) => e.match === source.id);
            if (latest && this.dialog.open) {
                this.follow(latest);
            }
        } catch {
            // The list is a convenience, the dialog works without it.
        }
    }

    close() {
        if (this.dialog.open) {
            this.dialog.close();
        }
    }

    render(status) {
        const d = this.dialog;
        d.replaceChildren();
        const head = h('div', { class: 've-head' },
            h('h2', { id: 'video-export-title' }, t('video.title')),
            h('button', { class: 'icon-btn', type: 'button', 'aria-label': t('video.close'), title: t('video.close.title'), onclick: () => this.close() }, '×'));
        d.append(head);
        const source = this.recording();
        if (!source) {
            d.append(h('p', {}, t('video.no_recording')),
                h('div', { class: 've-actions' }, h('button', { class: 'btn', type: 'button', onclick: () => this.close() }, t('video.close'))));
            return;
        }
        if (!status) {
            d.append(h('p', { class: 'muted' }, t('video.asking')));
            return;
        }
        if (!status.available) {
            d.append(h('p', {}, t('video.unavailable')),
                h('ul', { class: 've-missing' }, (status.missing || []).map((m) => h('li', {}, m))),
                h('p', { class: 'muted' }, t('video.unavailable.restart')),
                h('div', { class: 've-actions' }, h('button', { class: 'btn', type: 'button', onclick: () => this.close() }, t('video.close'))));
            return;
        }
        const tl = this.app.timeline;
        const annotated = !!(tl.store.annotations && tl.store.annotations.size > 0);
        const now = (tl.t - tl.first) / tl.sps;
        const duration = (tl.last - tl.first) / tl.sps;
        this.duration = duration;
        const start = h('input', { id: 've-start', type: 'text', inputmode: 'decimal', value: formatMoment(now), 'aria-describedby': 've-range-note' });
        const end = h('input', { id: 've-end', type: 'text', inputmode: 'decimal', value: formatMoment(Math.min(duration, now + 15)), 'aria-describedby': 've-range-note' });
        const here = () => formatMoment((this.app.timeline.t - this.app.timeline.first) / this.app.timeline.sps);
        const goals = (tl.store.goals || []).map((g, i) => {
            const at = (g.index - tl.first) / tl.sps;
            const team = teamName(source.header.teams[g.team]) || t(g.team ? 'video.goal.right' : 'video.goal.left');
            return { at, label: t('video.goal.option', { number: i + 1, moment: formatMoment(at), team }) };
        });
        const goal = h('select', { id: 've-goal', 'aria-label': t('video.goal.label') },
            h('option', { value: '' }, goals.length ? t('video.goal.around') : t('video.goal.none')),
            goals.map((g, i) => h('option', { value: String(i) }, g.label)));
        goal.disabled = !goals.length;
        goal.addEventListener('change', () => {
            const g = goals[Number(goal.value)];
            if (g) {
                const range = goalRange(g.at, duration);
                start.value = formatMoment(range.start);
                end.value = formatMoment(range.end);
            }
        });
        const select = (id, label, options, value) => h('label', { class: 've-field' }, h('span', {}, label),
            h('select', { id }, options.map((o) => h('option', { value: o.id, selected: o.id === value }, o.label))));
        const camera = VIDEO_CAMERAS.some((c) => c.id === this.app.cameras.mode) ? this.app.cameras.mode : 'broadcast';
        const field = this.app.field || {};
        const arena = ARENA_LABELS[field.arena] || ARENA_LABELS.stadium;
        const hour = typeof field.time === 'number' ? hourText(field.time) : '15:00';
        this.note = h('p', { id: 've-range-note', class: 've-note', role: 'status', 'aria-live': 'polite' },
            t('video.range.note', { end: formatMoment(duration), count: VIDEO_MAX_SECONDS / 60 }));
        this.progress = h('progress', { max: '1', value: '0', hidden: true, 'aria-label': t('video.progress.label') });
        this.status = h('p', { class: 've-status', role: 'status', 'aria-live': 'polite' });
        this.exportButton = h('button', { class: 'btn primary', type: 'button', onclick: () => this.start() }, t('video.export'));
        this.cancelButton = h('button', { class: 'btn', type: 'button', hidden: true, onclick: () => this.cancel() }, t('video.cancel'));
        this.download = h('a', { class: 'btn primary', hidden: true }, t('video.download'));
        this.sizes = sizeFields('ve', { value: '720p', limits: { even: true } });
        d.append(
            h('div', { class: 've-range' },
                // A label of the field alone, so the button beside it stays out of its name.
                h('div', { class: 've-field' }, h('span', {}, h('label', { for: 've-start' }, t('video.start'))), start,
                    h('button', { class: 'btn small', type: 'button', onclick: () => { start.value = here(); } }, t('video.start.here'))),
                h('div', { class: 've-field' }, h('span', {}, h('label', { for: 've-end' }, t('video.end'))), end,
                    h('button', { class: 'btn small', type: 'button', onclick: () => { end.value = here(); } }, t('video.end.here'))),
                h('label', { class: 've-field' }, h('span', {}, t('video.goal')), goal)),
            this.note,
            h('div', { class: 've-grid' },
                ...this.sizes.fields,
                h('label', { class: 've-field' }, h('span', {}, t('video.fps')),
                    h('select', { id: 've-fps' }, VIDEO_RATES.map((r) => h('option', { value: String(r), selected: r === 30 }, t('video.fps.option', { rate: r }))))),
                select('ve-quality', t('video.quality'), VIDEO_QUALITIES, 'standard'),
                select('ve-camera', t('video.camera'), VIDEO_CAMERAS, camera),
                h('label', { class: 'check' }, h('input', { id: 've-score', type: 'checkbox', checked: true }), t('video.score')),
                // The labels and the box of the annotations, off by default as in a clean picture,
                // offered for a recording that has them.
                annotated ? h('label', { class: 'check' }, h('input', { id: 've-annotations', type: 'checkbox' }), t('video.annotations')) : null),
            h('p', { class: 'muted small' }, t('video.look', { arena, hour })),
            this.progress,
            this.status,
            h('div', { class: 've-actions' }, this.exportButton, this.cancelButton, this.download,
                h('button', { class: 'btn', type: 'button', onclick: () => this.close() }, t('video.close'))));
        this.inputs = { start, end };
        start.focus();
    }

    choices() {
        const value = (id) => this.dialog.querySelector(`#${id}`).value;
        const size = this.sizes.read();
        return {
            size: { width: size.width, height: size.height },
            scale: size.scale,
            safe: size.safe,
            fps: Number(value('ve-fps')),
            quality: value('ve-quality'),
            camera: value('ve-camera'),
            score: this.dialog.querySelector('#ve-score').checked,
            annotations: !!(this.dialog.querySelector('#ve-annotations') || {}).checked,
        };
    }

    async start() {
        const source = this.recording();
        if (!source || !this.inputs) {
            return;
        }
        const range = checkRange(this.inputs.start.value, this.inputs.end.value, this.duration);
        if (range.error) {
            this.note.textContent = range.error;
            this.note.classList.add('error');
            return;
        }
        let choices;
        try {
            choices = this.choices();
        } catch (err) {
            this.note.textContent = err.message;
            this.note.classList.add('error');
            return;
        }
        this.note.classList.remove('error');
        this.exportButton.disabled = true;
        try {
            const entry = await call('POST', `/api/matches/${encodeURIComponent(source.id)}/video`, exportRequest(range, choices, this.app.field));
            this.follow(entry);
        } catch (err) {
            this.exportButton.disabled = false;
            this.status.textContent = err.status === 409 ? `${err.message}.` : t('video.error.start', { error: err.message });
        }
    }

    async cancel() {
        if (!this.entry) {
            return;
        }
        this.cancelButton.disabled = true;
        try {
            await call('DELETE', `/api/videos/${encodeURIComponent(this.entry.id)}`);
        } catch (err) {
            this.status.textContent = err.message;
        }
    }

    // Shows an export entry and asks for it again while it runs.
    follow(entry) {
        this.entry = entry;
        if (!this.status) {
            return;
        }
        const running = entry.state === 'running';
        this.progress.hidden = entry.state !== 'running' && entry.state !== 'done';
        this.progress.value = entry.state === 'done' ? 1 : entry.progress || 0;
        this.status.textContent = progressText(entry);
        this.exportButton.disabled = running;
        this.exportButton.textContent = entry.state === 'done' ? t('video.export.again') : t('video.export');
        this.cancelButton.hidden = !running;
        this.cancelButton.disabled = false;
        this.download.hidden = entry.state !== 'done';
        if (entry.state === 'done') {
            this.download.href = `/api/videos/${encodeURIComponent(entry.id)}/file`;
            this.download.setAttribute('download', entry.filename || 'match.mp4');
        }
        this.stopPolling();
        if (running && this.dialog.open) {
            this.timer = setTimeout(async () => {
                try {
                    const next = await call('GET', `/api/videos/${encodeURIComponent(entry.id)}`);
                    if (this.dialog.open && this.entry && this.entry.id === entry.id) {
                        this.follow(next);
                    }
                } catch (err) {
                    this.status.textContent = err.status === 404 ? t('video.error.gone') : err.message;
                    this.exportButton.disabled = false;
                    this.cancelButton.hidden = true;
                }
            }, 700);
        }
    }

    stopPolling() {
        clearTimeout(this.timer);
        this.timer = null;
    }
}
