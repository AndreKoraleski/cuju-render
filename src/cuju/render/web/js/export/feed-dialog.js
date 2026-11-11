// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The Copy feed address dialog of the Watch page. It writes the address of a clean feed, the page
// at /feed that a browser source of OBS or another streaming program shows, from what the feed
// follows, its size, the scale and safe area of its graphics, its background, whether it shows
// the graphics alone, its camera, its sound and its frame rate, and copies the address or opens
// the feed in a new tab. The server's live sources and tournaments join the sources it follows.

import { h } from '../teams/library.js';
import { feedAddress, namedSources } from './feed-params.js';
import { serverText, t } from '../core/i18n.js';
import { sizeFields } from './size-fields.js';
import { VIDEO_CAMERAS } from './video-range.js';

// The sources that the dialog offers beside the open match.
const FOLLOW = [
    ['auto', t('feed.dialog.follow.auto')],
    ['live', t('feed.dialog.follow.live')],
    ['latest', t('feed.dialog.follow.latest')],
    ['tournament', t('feed.dialog.follow.tournament')],
    ['queue', t('feed.dialog.follow.queue')],
];
const BACKGROUNDS = [
    ['black', t('feed.dialog.background.black')],
    ['transparent', t('feed.dialog.background.transparent')],
    ['green', t('feed.dialog.background.green')],
];
const RATES = [
    ['0', t('feed.dialog.rate.display')],
    ['30', t('feed.dialog.rate.option', { rate: 30 })],
    ['60', t('feed.dialog.rate.option', { rate: 60 })],
];

// The source of the open match, a recording of the library or a live source of this server.
export function openSource(source) {
    if (!source || source.game) {
        return null;
    }
    if (source.kind === 'match') {
        return { value: `recording:${source.id}`, label: t('feed.dialog.follow.this_recording') };
    }
    if (source.kind === 'live' && source.live && !source.live.url) {
        return { value: `live:${source.id}`, label: t('feed.dialog.follow.this_live') };
    }
    return null;
}

export class FeedDialog {
    constructor(app) {
        this.app = app;
        this.dialog = h('dialog', { class: 'feed-address', 'aria-labelledby': 'feed-address-title' });
        document.getElementById('app').appendChild(this.dialog);
        this.dialog.addEventListener('input', () => this.update());
        this.dialog.addEventListener('change', () => this.update());
    }

    open() {
        if (this.dialog.open) {
            return;
        }
        if (document.pointerLockElement) {
            document.exitPointerLock();
        }
        this.render();
        this.dialog.showModal();
        this.update();
        this.addNamed();
    }

    // Adds the live sources and tournaments of the server to the Follows list once it answers.
    async addNamed() {
        let rows;
        try {
            const res = await fetch('/api/feed', { cache: 'no-store' });
            rows = res.ok ? await res.json() : [];
        } catch {
            return;
        }
        if (!this.dialog.open) {
            return;
        }
        const taken = [...this.source.options].map((o) => o.value);
        // A row's label shows in the page's language when the server names its message.
        const shown = (Array.isArray(rows) ? rows : []).map((row) => (row && row.label_id ? { ...row, label: serverText(row, 'label') } : row));
        this.source.append(...namedSources(shown, taken).map(([value, label]) => h('option', { value }, label)));
    }

    close() {
        if (this.dialog.open) {
            this.dialog.close();
        }
    }

    render() {
        const d = this.dialog;
        const own = openSource(this.app.source);
        const choices = [...(own ? [[own.value, own.label]] : []), ...FOLLOW];
        const select = (id, entries) => h('select', { id }, entries.map(([value, label]) => h('option', { value }, label)));
        this.source = select('fa-source', choices);
        this.sizes = sizeFields('fa', { value: '1080p' });
        this.background = select('fa-bg', BACKGROUNDS);
        this.fps = select('fa-fps', RATES);
        this.camera = select('fa-camera', VIDEO_CAMERAS.map((c) => [c.id, c.label]));
        this.graphicsOnly = h('input', { id: 'fa-layer', type: 'checkbox' });
        this.audio = h('input', { id: 'fa-audio', type: 'checkbox' });
        this.loop = h('input', { id: 'fa-loop', type: 'checkbox' });
        this.captions = h('input', { id: 'fa-captions', type: 'checkbox' });
        this.output = h('input', { id: 'fa-url', type: 'text', readonly: true, spellcheck: 'false', 'aria-label': t('feed.dialog.address') });
        this.note = h('p', { class: 've-note', role: 'status', 'aria-live': 'polite' });
        this.openLink = h('a', { class: 'btn', target: '_blank', rel: 'noopener' }, t('feed.dialog.open'));
        const field = (label, control) => h('label', { class: 've-field' }, h('span', {}, label), control);
        d.replaceChildren(
            h('div', { class: 've-head' },
                h('h2', { id: 'feed-address-title' }, t('feed.dialog.title')),
                h('button', { class: 'icon-btn', type: 'button', 'aria-label': t('feed.dialog.close'), title: t('feed.dialog.close.title'), onclick: () => this.close() }, '×')),
            h('p', { class: 'muted small' }, t('feed.dialog.intro')),
            h('div', { class: 've-grid' },
                field(t('feed.dialog.follows'), this.source),
                ...this.sizes.fields,
                field(t('feed.dialog.background'), this.background),
                field(t('feed.dialog.rate'), this.fps),
                field(t('feed.dialog.camera'), this.camera),
                h('label', { class: 'check' }, this.graphicsOnly, t('feed.dialog.graphicsOnly')),
                h('label', { class: 'check' }, this.audio, t('feed.dialog.audio')),
                h('label', { class: 'check' }, this.loop, t('feed.dialog.loop')),
                h('label', { class: 'check' }, this.captions, t('feed.dialog.captions'))),
            this.output,
            this.note,
            h('div', { class: 've-actions' },
                h('button', { class: 'btn primary', type: 'button', onclick: () => this.copy() }, t('feed.dialog.copy')),
                this.openLink,
                h('button', { class: 'btn', type: 'button', onclick: () => this.close() }, t('feed.dialog.close'))));
    }

    // The feed's options from the fields, or null with the problem shown.
    options() {
        let size;
        try {
            size = this.sizes.read();
        } catch (err) {
            this.note.textContent = err.message;
            this.note.classList.add('error');
            return null;
        }
        this.note.classList.remove('error');
        this.note.textContent = t('feed.dialog.size_note', { width: size.width, height: size.height });
        return {
            source: this.source.value,
            width: size.width,
            height: size.height,
            scale: size.scale,
            safe: size.safe,
            bg: this.background.value,
            fps: Number(this.fps.value),
            camera: this.camera.value,
            layer: this.graphicsOnly.checked ? 'graphics' : 'full',
            audio: this.audio.checked,
            loop: this.loop.checked,
            captions: this.captions.checked,
        };
    }

    address() {
        const options = this.options();
        return options ? feedAddress(`${location.origin}${location.pathname.replace(/[^/]*$/, '')}`, options) : '';
    }

    update() {
        const url = this.address();
        this.output.value = url;
        this.openLink.href = url || '#';
        this.openLink.toggleAttribute('aria-disabled', !url);
    }

    async copy() {
        const url = this.address();
        if (!url) {
            return;
        }
        try {
            await navigator.clipboard.writeText(url);
            this.note.textContent = t('feed.dialog.copied');
        } catch {
            this.output.focus();
            this.output.select();
            this.note.textContent = t('feed.dialog.copy_by_hand');
        }
    }
}
