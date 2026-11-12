// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The Home page, the first page of the viewer, laid out as a landing page. A wide opening band
// carries the logo as the name, a line on what the viewer does and the ways into its pages. Below
// it the page runs down in bands, the live sources and the newest recordings with a way into each,
// or a first run guide while the library is empty, then what the viewer does, the keys of the
// Watch page, a note on what cuju is with links to the project, and the version. Every text from
// the server goes into the page as text, never as markup.

import { api, formatDate } from '../core/api.js';
import { el as h } from '../core/menu.js';
import { recordingTitle, summaryTeams } from '../core/names.js';
import { scenarioName } from '../core/scenarios.js';
import { t, tn } from '../core/i18n.js';
import { icon, reicon, relabel, symbolOnly } from '../core/icons.js';
import { chord } from '../core/keys.js';

const REFRESH_MS = 8000;
const LATEST = 5;
const SVG_NS = 'http://www.w3.org/2000/svg';

// Each link names its messages, home.links.<key>.label and .hint.
const LINKS = [
    ['repository', 'https://github.com/AndreKoraleski/cuju'],
    ['documentation', 'https://github.com/AndreKoraleski/cuju/tree/main/docs'],
    ['rendering', 'https://github.com/AndreKoraleski/cuju/blob/main/docs/rendering.md'],
    ['issues', 'https://github.com/AndreKoraleski/cuju/issues'],
    ['changelog', 'https://github.com/AndreKoraleski/cuju/blob/main/CHANGELOG.md'],
    ['pypi', 'https://pypi.org/project/cuju/'],
];
const NOTICE_URL = 'https://github.com/AndreKoraleski/cuju/blob/main/NOTICE';

// What the viewer does, each with the symbol of the page that shows it and its messages
// home.feature.<name>.title and .text, whose placeholder {code} is the code of the part.
const FEATURES = [
    ['camera', 'video'],
    ['replay', 'replay'],
    ['shirt', 'shirt'],
    ['live', 'live', 'CUJU_RENDER=on'],
    ['podium', 'podium'],
    ['field', 'field'],
];

// Each key group lists its rows, each row its keys, where a key is a chord such as `Shift R`
// that the keyboard kit draws, and `to` joins a range. The group's name is the message
// home.keys.<group>.title and each row's text home.keys.<group>.<row>.
const KEYS = [
    ['cameras', [
        [['V'], 'cycle'],
        [['B'], 'ball'],
        [['P'], 'owner'],
        [['1', 'to', '0'], 'players'],
        [['G'], 'goalkeeper'],
        [['W', 'A', 'S', 'D'], 'fly'],
        [['Q', 'E'], 'height'],
    ]],
    ['playback', [
        [['Space'], 'play'],
        [['J', 'K', 'L'], 'shuttle'],
        [['Left', 'Right'], 'step'],
        [['N'], 'next'],
    ]],
    ['replays', [
        [['R'], 'last'],
        [['Shift R'], 'angles'],
        [['Enter'], 'skip'],
        [['Esc'], 'end'],
    ]],
    ['screen', [
        [['T'], 'tv'],
        [['F'], 'fullscreen'],
        [['M'], 'mute'],
        [['H'], 'shortcuts'],
    ]],
];

function createdMs(m) {
    if (typeof m.created === 'number') {
        return m.created < 1e12 ? m.created * 1000 : m.created;
    }
    return Date.parse(m.created) || 0;
}

// An element of an SVG drawing, with its attributes and children.
function svg(tag, attrs = {}, ...children) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) {
        node.setAttribute(k, String(v));
    }
    node.append(...children);
    return node;
}

// The markings of a football pitch of 105 by 68 meters in tenths of a meter, drawn behind the
// opening band as a quiet backdrop.
function pitchArt() {
    const line = (d) => svg('path', { d });
    const spot = (cx) => svg('circle', { class: 'spot', cx, cy: 340, r: 4 });
    const drawing = svg('svg', { class: 'home-pitch', viewBox: '-40 -20 1130 720', 'aria-hidden': 'true', focusable: 'false' },
        line('M0 0H1050V680H0Z'),
        line('M525 0V680'),
        svg('circle', { cx: 525, cy: 340, r: 91.5 }),
        line('M0 138.5H165V541.5H0'),
        line('M1050 138.5H885V541.5H1050'),
        line('M0 248.4H55V431.6H0'),
        line('M1050 248.4H995V431.6H1050'),
        line('M165 266.9A91.5 91.5 0 0 1 165 413.1'),
        line('M885 266.9A91.5 91.5 0 0 0 885 413.1'),
        line('M10 0A10 10 0 0 1 0 10'),
        line('M1040 0A10 10 0 0 0 1050 10'),
        line('M0 670A10 10 0 0 1 10 680'),
        line('M1050 670A10 10 0 0 0 1040 680'),
        line('M0 303.4H-20V376.6H0'),
        line('M1050 303.4H1070V376.6H1050'),
        spot(110), spot(525), spot(940),
        svg('circle', { class: 'ball', cx: 760, cy: 250, r: 7 }));
    return h('div', { class: 'home-pitch-frame', 'aria-hidden': 'true' }, drawing);
}

// The head of a band, a heading with an optional line above it and an optional control at its right.
function bandHead(id, title, { eyebrow, aside, level = 'h2' } = {}) {
    return h('div', { class: 'home-head' },
        h('div', { class: 'home-head-text' },
            eyebrow ? h('p', { class: 'home-eyebrow' }, eyebrow) : null,
            h(level, { id, class: 'home-h2' }, title)),
        aside || null);
}

// A command to copy, with a button that puts it on the clipboard.
function command(text) {
    const button = h('button', { type: 'button', class: 'btn small ghost home-copy', ...symbolOnly(t('home.copy.label', { command: text })) }, icon('copy'));
    // The button names what it did for a moment, its check mark showing the copy.
    const tell = (label, symbol) => {
        relabel(button, label);
        reicon(button, symbol);
    };
    button.addEventListener('click', async () => {
        try {
            await navigator.clipboard.writeText(text);
            tell(t('home.copy.done'), 'check');
        } catch {
            // Without the clipboard the text is selected, so a key press copies it.
            const range = document.createRange();
            range.selectNodeContents(code);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
            tell(t('home.copy.selected'), 'check');
        }
        setTimeout(() => {
            tell(t('home.copy.label', { command: text }), 'copy');
        }, 1600);
    });
    const code = h('code', {}, text);
    return h('div', { class: 'home-command' }, code, button);
}

function keyChord(keys) {
    return keys.flatMap((k, i) => {
        const node = k === 'to' ? h('span', { class: 'home-key-word' }, t('home.keys.to')) : chord(k);
        return i ? [' ', node] : [node];
    });
}

// The bare mark in both grays, the light one for the dark theme and the dark one for the light
// theme, of which style.css shows the one that suits the theme in force. Home is the page's own
// surface, so the mark stands on it without its tile.
function themedMark(className, alt, side) {
    return [['cuju-mark.svg', 'mark-for-dark'], ['cuju-mark-light.svg', 'mark-for-light']].map(([file, theme]) => h('img', {
        class: `${className} ${theme}`, src: `assets/${file}`, alt, width: side, height: side,
    }));
}

function newTab(label) {
    return [label, h('span', { class: 'sr-only' }, t('home.newtab'))];
}

export class HomePage {
    constructor(app) {
        this.app = app;
        this.root = document.getElementById('page-home');
        this.timer = null;
        this.token = 0;
        this.shown = false;
        this.signature = null;
        this.build();
        // A file chosen from this page plays on the Watch page.
        const input = document.getElementById('file-input');
        if (input) {
            input.addEventListener('change', () => {
                if (this.app.page === 'home' && this.pickedFile) {
                    this.app.showPage('watch');
                }
                this.pickedFile = false;
            });
        }
        document.addEventListener('visibilitychange', () => {
            if (this.shown && !document.hidden) {
                this.refresh();
            }
        });
        this.loadVersion();
    }

    show() {
        this.shown = true;
        // The montage's poster loads once Home shows, so a page opened on a match skips it.
        for (const video of this.root.querySelectorAll('video[data-poster]:not([poster])')) {
            video.poster = video.dataset.poster;
        }
        clearInterval(this.timer);
        this.timer = setInterval(() => {
            if (!document.hidden) {
                this.refresh();
            }
        }, REFRESH_MS);
        this.refresh();
    }

    hide() {
        this.shown = false;
        clearInterval(this.timer);
        this.timer = null;
        // An answer that arrives after the page is left is dropped.
        this.token++;
    }

    build() {
        // The live sources and the recordings, or the guide or the offline note in their place.
        this.status = h('div', { class: 'home-status', 'aria-live': 'polite' },
            h('p', { class: 'muted home-checking' }, t('home.status.asking')));
        this.root.replaceChildren(h('div', { class: 'home' },
            this.hero(),
            h('div', { class: 'home-band home-now' }, h('div', { class: 'home-wrap' }, this.status)),
            this.reelBand(),
            this.featuresBand(),
            this.keysBand(),
            this.footBand()));
    }

    // The opening band, the logo as the name, the line beneath it and the ways into the pages.
    hero() {
        const go = (page) => () => this.app.showPage(page);
        this.glanceLive = h('span', { class: 'home-glance-item live' });
        this.glanceRecordings = h('button', { type: 'button', class: 'home-glance-item link', onclick: go('recordings') });
        // A glance at what the server holds, shown once both counts are known.
        this.glance = h('p', { class: 'home-glance', hidden: true }, this.glanceLive, this.glanceRecordings);
        return h('header', { class: 'home-hero' },
            pitchArt(),
            h('div', { class: 'home-wrap home-hero-inner' },
                h('p', { class: 'home-eyebrow' }, t('home.hero.eyebrow')),
                h('h1', { class: 'home-title' },
                    themedMark('home-wordmark', t('structure.name'), '408')),
                h('p', { class: 'home-tagline' }, t('home.hero.tagline')),
                h('p', { class: 'home-lede' }, t('home.hero.lede')),
                h('nav', { class: 'home-actions', 'aria-label': t('home.hero.pages') },
                    h('button', { type: 'button', class: 'btn primary home-cta', onclick: go('watch') }, icon('watch'), t('home.hero.watch')),
                    h('button', { type: 'button', class: 'btn', onclick: go('play') }, icon('gamepad'), t('home.hero.play')),
                    h('button', { type: 'button', class: 'btn', onclick: go('challenges') }, icon('challenges'), t('home.hero.challenges')),
                    h('button', { type: 'button', class: 'btn', onclick: go('matches') }, icon('matches'), t('home.hero.matches')),
                    h('button', { type: 'button', class: 'btn', onclick: go('teams') }, icon('shirt'), t('home.hero.teams')),
                    h('button', { type: 'button', class: 'btn', onclick: go('field') }, icon('field'), t('home.hero.field'))),
                this.glance));
    }

    // A montage of the viewer, muted until the viewer turns the sound on, and played from its controls.
    reelBand() {
        const video = h('video', {
            class: 'home-reel-video', src: 'assets/promo.mp4', 'data-poster': 'assets/promo-poster.jpg',
            controls: true, muted: true, playsinline: true, preload: 'none', width: '1280', height: '720',
            'aria-label': t('home.reel.label'),
        });
        video.muted = true;
        return h('section', { class: 'home-band home-reel', 'aria-labelledby': 'home-reel-title' },
            h('div', { class: 'home-wrap' },
                bandHead('home-reel-title', t('home.reel.title'), { eyebrow: t('home.reel.eyebrow') }),
                video));
    }

    featuresBand() {
        const items = FEATURES.map(([name, symbol, code]) => h('li', { class: 'home-feature' },
            icon(symbol, 'home-icon'),
            h('h3', {}, t(`home.feature.${name}.title`)),
            h('p', {}, ...tn(`home.feature.${name}.text`, code ? { code: h('code', {}, code) } : {}))));
        return h('section', { class: 'home-band home-features', 'aria-labelledby': 'home-features-title' },
            h('div', { class: 'home-wrap' },
                bandHead('home-features-title', t('home.features.title'), { eyebrow: t('home.features.eyebrow') }),
                h('ul', { class: 'home-feature-list' }, ...items)));
    }

    keysBand() {
        const groups = KEYS.map(([name, rows]) => h('div', { class: 'home-keys-group' },
            h('h3', {}, t(`home.keys.${name}.title`)),
            h('dl', {}, ...rows.flatMap(([keys, row]) => [h('dt', {}, ...keyChord(keys)), h('dd', {}, tn(`home.keys.${name}.${row}`))]))));
        const all = h('button', { type: 'button', class: 'btn ghost', onclick: () => {
            const btn = document.getElementById('open-help');
            if (btn) {
                btn.click();
            }
        } }, icon('keyboard'), ...tn('home.keys.all'));
        return h('section', { class: 'home-band home-keys', 'aria-labelledby': 'home-keys-title' },
            h('div', { class: 'home-wrap' },
                bandHead('home-keys-title', t('home.keys.title'), { eyebrow: t('home.keys.eyebrow'), aside: all }),
                h('div', { class: 'home-keys-grid' }, ...groups)));
    }

    // The foot of the page, what cuju is with its credits, the links and the version.
    footBand() {
        this.version = h('span', { class: 'home-version', hidden: true });
        const links = LINKS.map(([key, href]) => h('li', {},
            h('a', { href, target: '_blank', rel: 'noopener noreferrer', class: 'home-link' },
                h('span', { class: 'home-link-label' }, ...newTab(t(`home.links.${key}.label`))),
                h('span', { class: 'home-link-hint' }, t(`home.links.${key}.hint`)))));
        const notice = h('a', { href: NOTICE_URL, target: '_blank', rel: 'noopener noreferrer' }, ...newTab('NOTICE'));
        const about = h('section', { class: 'home-about', 'aria-labelledby': 'home-about-title' },
            bandHead('home-about-title', t('home.about.title')),
            h('p', {}, tn('home.about.runs')),
            h('p', {}, tn('home.about.watch')),
            h('p', {}, h('a', { href: 'https://en.wikipedia.org/wiki/Cuju', target: '_blank', rel: 'noopener noreferrer' },
                ...newTab(t('home.about.name')))),
            h('p', { class: 'home-credits' }, ...tn('home.about.credits', { notice })));
        const linkList = h('section', { class: 'home-links', 'aria-labelledby': 'home-links-title' },
            bandHead('home-links-title', t('home.links.title')),
            h('ul', { class: 'home-link-list' }, ...links));
        return h('footer', { class: 'home-band home-foot' },
            h('div', { class: 'home-wrap' },
                h('div', { class: 'home-foot-grid' }, about, linkList),
                h('div', { class: 'home-colophon' },
                    themedMark('home-colophon-logo', '', '22'),
                    h('span', {}, t('home.license')),
                    this.version)));
    }

    // The installed version, shown only when the client of the server offers it.
    async loadVersion() {
        if (typeof api.info !== 'function') {
            return;
        }
        try {
            const info = await api.info();
            if (info && typeof info.version === 'string' && info.version) {
                this.version.textContent = t('home.version', { version: info.version });
                this.version.hidden = false;
            }
        } catch {
            // An older server has no version to show, the line stays hidden.
        }
    }

    async refresh() {
        const token = ++this.token;
        const [live, matches] = await Promise.allSettled([api.live(), api.matches()]);
        if (token !== this.token) {
            return;
        }
        const failed = [live, matches].filter((r) => r.status === 'rejected').map((r) => r.reason);
        const offline = failed.some((err) => !err || !err.status);
        if (this.app.library && typeof this.app.library.setOffline === 'function') {
            this.app.library.setOffline(offline);
        }
        const state = {
            offline,
            live: live.status === 'fulfilled' && Array.isArray(live.value) ? live.value : null,
            liveError: live.status === 'rejected' ? String(live.reason && live.reason.message || live.reason) : null,
            matches: matches.status === 'fulfilled' && Array.isArray(matches.value) ? matches.value : null,
            matchesError: matches.status === 'rejected' ? String(matches.reason && matches.reason.message || matches.reason) : null,
        };
        // The same answer leaves the page as it is, so the focus and the hover stay put.
        const signature = JSON.stringify(state);
        if (signature === this.signature) {
            return;
        }
        this.signature = signature;
        this.renderStatus(state);
    }

    renderStatus(state) {
        const known = !state.offline && state.live && state.matches;
        this.glance.hidden = !known;
        if (known) {
            const on = state.live.length > 0;
            this.glanceLive.classList.toggle('on', on);
            this.glanceLive.replaceChildren(
                h('i', { class: 'home-live-dot', 'aria-hidden': 'true' }),
                on ? t('home.glance.live', { count: state.live.length }) : t('home.glance.none'));
            this.glanceRecordings.textContent = t('home.glance.recordings', { count: state.matches.length });
        }
        // The focus returns to the same control after a redraw.
        const active = document.activeElement;
        const focusKey = active && this.status.contains(active) ? active.dataset.focusKey : null;
        let parts;
        if (state.offline) {
            parts = [this.offlineBlock()];
        } else if (state.live && state.matches && !state.live.length && !state.matches.length) {
            parts = [this.firstRunBlock()];
        } else {
            parts = [this.liveBlock(state), this.recordingsBlock(state)];
        }
        this.status.replaceChildren(...parts);
        if (focusKey) {
            const again = this.status.querySelector(`[data-focus-key="${CSS.escape(focusKey)}"]`);
            if (again) {
                again.focus();
            }
        }
    }

    openFile() {
        const input = document.getElementById('file-input');
        if (input) {
            this.pickedFile = true;
            input.click();
        }
    }

    offlineBlock() {
        return h('section', { class: 'home-block home-wide home-offline', 'aria-labelledby': 'home-offline-title' },
            bandHead('home-offline-title', t('home.offline.title')),
            h('div', { class: 'home-prose' },
                h('p', {}, tn('home.offline.text')),
                command('cuju render serve --open'),
                h('div', { class: 'home-row' },
                    h('button', { type: 'button', class: 'btn primary', 'data-focus-key': 'open-file', onclick: () => this.openFile() }, icon('folder'), t('home.openFile')),
                    h('button', { type: 'button', class: 'btn', 'data-focus-key': 'retry', ...symbolOnly(t('home.offline.retry')), onclick: () => this.refresh() }, icon('refresh')))));
    }

    firstRunBlock() {
        const step = (n, title, text, ...extra) => h('li', { class: 'home-step' },
            h('span', { class: 'home-step-n', 'aria-hidden': 'true' }, String(n)),
            h('h3', {}, title),
            h('p', {}, text),
            ...extra);
        return h('section', { class: 'home-block home-wide home-first', 'aria-labelledby': 'home-first-title' },
            bandHead('home-first-title', t('home.first.title'), { eyebrow: t('home.first.eyebrow') }),
            h('p', { class: 'home-intro' }, t('home.first.intro')),
            h('ol', { class: 'home-steps' },
                step(1, t('home.first.serve.title'), tn('home.first.serve.text'),
                    command('cuju render serve --open')),
                step(2, t('home.first.stream.title'), tn('home.first.stream.text'),
                    command('CUJU_RENDER=on python train.py')),
                step(3, t('home.first.record.title'), tn('home.first.record.text', { code: h('code', {}, 'cuju.render.Recorder') }),
                    h('div', { class: 'home-row' },
                        h('button', { type: 'button', class: 'btn', 'data-focus-key': 'first-matches', onclick: () => this.app.showPage('matches') }, icon('matches'), t('home.requestMatch')),
                        h('button', { type: 'button', class: 'btn ghost', 'data-focus-key': 'first-file', onclick: () => this.openFile() }, icon('folder'), t('home.openFile'))))));
    }

    liveBlock(state) {
        const list = state.live || [];
        const count = list.length
            ? h('span', { class: 'home-live-count' }, h('i', { class: 'home-live-dot', 'aria-hidden': 'true' }), t('home.live.count', { count: list.length }))
            : null;
        let body;
        if (state.liveError) {
            body = h('p', { class: 'home-empty error-text' }, t('home.live.error', { error: state.liveError }));
        } else if (!list.length) {
            body = h('p', { class: 'home-empty muted' }, ...tn('home.live.empty', { code: h('code', {}, 'CUJU_RENDER=on') }));
        } else {
            body = h('ul', { class: 'home-list' }, ...list.map((s) => {
                const meta = [scenarioName(s.scenario), Number.isFinite(s.environment) ? t('home.live.environment', { index: s.environment }) : null].filter(Boolean);
                return h('li', { class: 'home-item live' },
                    h('div', { class: 'home-item-main' },
                        h('p', { class: 'home-item-title' }, recordingTitle(s) || s.id),
                        h('p', { class: 'home-item-meta' }, ...meta.map((m) => h('span', {}, m)))),
                    h('button', {
                        type: 'button',
                        class: 'btn small primary',
                        'data-focus-key': `live:${s.id}`,
                        ...symbolOnly(t('home.live.watch.label', { title: recordingTitle(s) || s.id })),
                        onclick: () => this.app.openLive(s.id),
                    }, icon('play')));
            }));
        }
        return h('section', { class: 'home-block home-live', 'aria-labelledby': 'home-live-title' },
            bandHead('home-live-title', t('home.live.title'), { aside: count }), body);
    }

    recordingsBlock(state) {
        const all = (state.matches || []).slice().sort((a, b) => createdMs(b) - createdMs(a));
        const latest = all.slice(0, LATEST);
        const more = h('button', {
            type: 'button',
            class: 'link home-more',
            'data-focus-key': 'all-recordings',
            onclick: () => this.app.showPage('recordings'),
        }, all.length > LATEST ? t('home.recordings.all', { count: all.length }) : t('home.recordings.open'));
        let body;
        if (state.matchesError) {
            body = h('p', { class: 'home-empty error-text' }, t('home.recordings.error', { error: state.matchesError }));
        } else if (!latest.length) {
            body = h('div', { class: 'home-empty' },
                h('p', { class: 'muted' }, ...tn('home.recordings.empty', { code: h('code', {}, 'cuju.render.Recorder') })),
                h('div', { class: 'home-row' },
                    h('button', { type: 'button', class: 'btn', 'data-focus-key': 'rec-matches', onclick: () => this.app.showPage('matches') }, icon('matches'), t('home.requestMatch'))));
        } else {
            body = h('ul', { class: 'home-list' }, ...latest.map((m) => this.recordingItem(m)));
        }
        return h('section', { class: 'home-block home-recordings', 'aria-labelledby': 'home-rec-title' },
            bandHead('home-rec-title', t('home.recordings.title'), { aside: more }), body);
    }

    recordingItem(m) {
        const teams = summaryTeams(m);
        const score = Array.isArray(m.score) ? m.score : null;
        const board = teams.length === 2
            ? h('p', { class: 'home-board' },
                h('span', { class: 'home-board-team left' }, teams[0]),
                h('span', { class: 'home-score' },
                    h('span', { 'aria-hidden': 'true' }, score ? String(score[0]) : '-'),
                    h('span', { 'aria-hidden': 'true' }, score ? String(score[1]) : '-'),
                    h('span', { class: 'sr-only' }, ` ${score ? t('home.score', { left: score[0], right: score[1] }) : t('home.score.none')} `)),
                h('span', { class: 'home-board-team right' }, teams[1]))
            : null;
        const date = formatDate(m.created);
        const meta = [scenarioName(m.scenario), date].filter(Boolean);
        const title = recordingTitle(m) || m.id;
        // A title that only names the two teams says what the scoreboard below it says.
        const english = Array.isArray(m.teams) ? `${m.teams[0]} against ${m.teams[1]}` : null;
        const plain = board && (m.title_id === 'server.names.against' || (!m.title_id && m.title === english));
        return h('li', { class: 'home-item' },
            h('div', { class: 'home-item-main' },
                plain ? null : h('p', { class: 'home-item-title' }, title),
                board,
                h('p', { class: 'home-item-meta' }, ...meta.map((x) => h('span', {}, x)))),
            h('button', {
                type: 'button',
                class: 'btn small',
                'data-focus-key': `rec:${m.id}`,
                ...symbolOnly(t('home.recordings.play.label', { title })),
                onclick: () => this.app.openMatchInWatch(m.id),
            }, icon('play')));
    }
}
