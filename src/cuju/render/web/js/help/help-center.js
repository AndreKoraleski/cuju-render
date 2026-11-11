// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The learning part of the Help page and the ways into it. Help gains a part to learn by doing at
// its top, with the guided tour, the hands-on lessons and their progress, the shipped samples with
// one action to add or restore each, the diagnostic report and the installable page. The tour also
// starts from the first-run tip and from the command palette, which lists the lessons, the samples
// and the report as well. Scripts reach the parts as window.cuju.tour, cuju.tutorial,
// cuju.samples, cuju.doctor and cuju.install. Each part loads on its own, so a failure of one
// leaves the others and the page working.

import { GuidedTour } from './tour.js';
import { Lessons, loadCatalog } from './lessons.js';
import { doneCount, lessonAsk, lessonTitle } from './lessons-core.js';
import { HELP_TOPICS, paletteAction, searchWords } from './palette.js';
import { serverText, t, tOr, tn } from '../core/i18n.js';
import { icon, labelText, relabel, stateBadge, symbolOnly } from '../core/icons.js';

// The title and the description of a sample from the server, as the messages
// helpcenter.sample.<id>.title and .about, with the server's English for a sample without them.
function sampleTitle(entry) {
    return tOr(`helpcenter.sample.${entry.id}.title`, entry.title);
}

function sampleAbout(entry) {
    return tOr(`helpcenter.sample.${entry.id}.about`, entry.about);
}

// A team sample lives in the registry of the Teams page, not in the library of recordings.
function sampleState(entry) {
    const kind = entry.kind === 'team' ? 'teamState' : 'state';
    return tOr(`helpcenter.sample.${kind}.${entry.state}`, entry.state);
}

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
        throw new Error(t('helpcenter.error.unreachable', { origin: location.origin }));
    }
    const text = await res.text();
    let body = null;
    try {
        body = text ? JSON.parse(text) : null;
    } catch {
        body = null;
    }
    if (!res.ok) {
        throw new Error(body && body.error ? serverText(body) : t('helpcenter.error.status', { status: res.status }));
    }
    return body;
}

// The samples of the server, for window.cuju.samples and the Help page.
export const samplesApi = {
    list: () => call('GET', '/api/help/samples'),
    add: (names) => call('POST', '/api/help/samples', names ? { names } : {}),
};

function injectStyle() {
    if (document.getElementById('cuju-help-style')) {
        return;
    }
    const style = document.createElement('style');
    style.id = 'cuju-help-style';
    style.textContent = `
#help-learn, #help-samples { display: flex; flex-direction: column; gap: 8px; margin-bottom: 18px; }
.help-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.lesson-list, .sample-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 260px), 1fr)); }
.lesson-list li, .sample-list li { display: flex; flex-direction: column; gap: 4px; padding: 8px 10px;
    border: 1px solid var(--border); border-radius: 6px; }
.lesson-list li.done { border-style: dashed; }
.lesson-list .lesson-mark, .sample-list .sample-state { font-size: 12px; }
.lesson-list h3, .sample-list h3 { margin: 0; color: var(--text); font-size: 15px; font-variant: normal; letter-spacing: normal; }
.lesson-list p, .sample-list p { margin: 0; }
.tour { position: fixed; z-index: 60; width: min(380px, calc(100vw - 24px)); padding: 14px 16px;
    border: 1px solid var(--border); border-radius: 10px; background: var(--surface); color: var(--text);
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.45); transition: left 0.25s ease, top 0.25s ease; }
.tour[hidden], .tour-ring[hidden], .lesson-panel[hidden] { display: none; }
.tour h2 { margin: 2px 0 6px; font-size: 18px; }
.tour h2:focus { outline: none; }
.tour h2:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.tour-count, .lesson-count { margin: 0; font-size: 12px; opacity: 0.8; }
.tour-text { margin: 0 0 8px; }
.tour-offer { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 8px; }
.tour-offer[hidden], .lesson-offer[hidden] { display: none; }
.tour-actions, .lesson-actions { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.tour-keys { margin: 8px 0 0; }
.tour-ring { position: fixed; z-index: 59; pointer-events: none; border-radius: 8px;
    border: 3px solid var(--accent); box-shadow: 0 0 0 4px var(--scrim);
    transition: left 0.25s ease, top 0.25s ease, width 0.25s ease, height 0.25s ease; }
.tour.still, .tour-ring.still, :root.reduced-motion .tour, :root.reduced-motion .tour-ring { transition: none; }
.lesson-panel { position: fixed; z-index: 58; right: 12px; bottom: 12px; width: min(360px, calc(100vw - 24px));
    padding: 12px 14px; border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: 10px;
    background: var(--surface); color: var(--text);
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.4); display: flex; flex-direction: column; gap: 6px; }
.lesson-panel h2 { margin: 0; font-size: 16px; }
.lesson-panel h2:focus { outline: none; }
.lesson-panel h2:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.lesson-panel p { margin: 0; }
.lesson-offer { display: flex; flex-wrap: wrap; gap: 6px; }
.lesson-status { font-size: 13px; }
.lesson-panel.lesson-done { border-color: var(--accent); }
.lesson-panel.lesson-compact .lesson-ask, .lesson-panel.lesson-compact .lesson-offer { display: none; }
#app[data-page="watch"] .lesson-panel { bottom: 120px; }
#app.tv .lesson-panel { display: none; }
`;
    document.head.appendChild(style);
}

export class HelpCenter {
    constructor(app) {
        this.app = app;
        injectStyle();
        this.tour = new GuidedTour(app, { facts: () => this.facts(), ensure: (need) => this.ensure(need) });
        this.samples = [];
        this.lessons = null;
        this.buildHelp();
        this.bindTip();
        this.bindPalette();
        app.tour = this.tour.script();
        app.samples = {
            list: async () => (this.samples = await samplesApi.list()),
            add: async (names) => {
                const result = await samplesApi.add(names);
                this.samples = result.samples;
                this.renderSamples();
                return result;
            },
        };
        this.ready = Promise.allSettled([this.loadLessons(), this.refreshSamples(), this.loadParts()]);
    }

    // What the steps of the tour and the lessons need, as the page holds it now.
    facts() {
        const teams = this.app.library && Array.isArray(this.app.library.teams) ? this.app.library.teams : [];
        const listed = this.samples.find((entry) => entry.kind === 'team');
        return {
            recording: !!(this.app.source && !this.app.source.game),
            team: teams.some((team) => team.kind !== 'builtin') || !!(listed && listed.state === 'library'),
        };
    }

    // Adds the sample that a need asks for and shows it, a recording on Watch or a team on Teams.
    async ensure(need) {
        if (need === 'recording') {
            const result = await samplesApi.add(['sample-5v5']);
            this.samples = result.samples;
            this.renderSamples();
            await this.app.openMatch('sample-5v5');
            return;
        }
        if (need === 'team') {
            const result = await samplesApi.add(['starter-team']);
            this.samples = result.samples;
            this.renderSamples();
            if (this.app.library && typeof this.app.library.refresh === 'function') {
                await this.app.library.refresh();
            }
        }
    }

    buildHelp() {
        const card = document.querySelector('#help .help-card');
        if (!card) {
            return;
        }
        this.tourButton = h('button', { type: 'button', class: 'btn primary', onclick: () => this.tour.start() }, icon('play'), labelText(''));
        this.tourAgain = h('button', { type: 'button', class: 'btn', ...symbolOnly(t('helpcenter.tour.again')), onclick: () => this.tour.start(0) }, icon('replay'));
        this.lessonSummary = h('p', { class: 'muted', 'aria-live': 'polite' }, t('helpcenter.lessons.loading'));
        this.lessonList = h('ol', { class: 'lesson-list', 'aria-label': t('helpcenter.lessons.list') });
        this.continueButton = h('button', { type: 'button', class: 'btn primary', onclick: () => this.lessons && this.lessons.start() }, icon('play'), labelText(t('helpcenter.lessons.start')));
        this.resetButton = h('button', { type: 'button', class: 'btn', ...symbolOnly(t('helpcenter.lessons.reset')), onclick: () => this.resetLessons() }, icon('reset'));
        const learn = h('section', { id: 'help-learn', 'aria-labelledby': 'help-learn-title', tabindex: '-1' },
            h('h2', { id: 'help-learn-title' }, t('helpcenter.learn.title')),
            h('p', {}, t('helpcenter.learn.text')),
            h('div', { class: 'help-row' }, this.tourButton, this.tourAgain),
            h('h2', { id: 'help-lessons' }, t('helpcenter.lessons.title')),
            this.lessonSummary,
            this.lessonList,
            h('div', { class: 'help-row' }, this.continueButton, this.resetButton),
            h('p', { class: 'muted small' }, tn('helpcenter.lessons.agent', {
                command: h('code', {}, 'cuju render tutorial'), script: h('code', {}, 'window.cuju.tutorial'),
            })));
        this.sampleList = h('ul', { class: 'sample-list', 'aria-label': t('helpcenter.samples.list') });
        this.sampleNote = h('p', { class: 'muted small', 'aria-live': 'polite' });
        this.allButton = h('button', { type: 'button', class: 'btn', onclick: () => this.addSamples(null) }, icon('plus'), t('helpcenter.samples.all'));
        const samples = h('section', { id: 'help-samples', 'aria-labelledby': 'help-samples-title' },
            h('h2', { id: 'help-samples-title' }, t('helpcenter.samples.title')),
            h('p', {}, t('helpcenter.samples.text')),
            this.sampleList,
            h('div', { class: 'help-row' }, this.allButton),
            this.sampleNote);
        this.doctorHost = h('section', { id: 'help-doctor', 'aria-labelledby': 'help-doctor-title' });
        this.installHost = h('section', { id: 'help-install', 'aria-labelledby': 'help-install-title' });
        const header = card.querySelector('header');
        (header || card.firstChild).after(learn, samples, this.doctorHost, this.installHost);
        // Each topic's title and words are the messages helpcenter.topic.<key>.title and .words.
        for (const topic of [
            ['help-learn-title', 'tour', 'tour walkthrough start learn tutorial'],
            ['help-lessons', 'lessons', 'tutorial hands on learn practice'],
            ['help-samples-title', 'samples', 'sample recording starter team restore'],
            ['help-doctor-title', 'doctor', 'doctor report diagnostics webgl versions problem'],
            ['help-install-title', 'install', 'install app pwa offline'],
        ].map(([id, key, words]) => [id, t(`helpcenter.topic.${key}.title`), searchWords(`helpcenter.topic.${key}.words`, words)])) {
            if (!HELP_TOPICS.some((entry) => entry[0] === topic[0])) {
                HELP_TOPICS.push(topic);
            }
        }
        this.renderTour();
        const page = document.getElementById('page-help');
        if (page) {
            new MutationObserver(() => {
                if (!page.hidden) {
                    this.renderTour();
                    this.refreshSamples();
                    // A lesson that the command line or another page finished while Help was
                    // away shows as done each time Help shows.
                    this.lessons?.sync().then(() => this.renderLessons());
                }
            }).observe(page, { attributes: true, attributeFilter: ['hidden'] });
        }
    }

    renderTour() {
        if (!this.tourButton) {
            return;
        }
        const at = this.tour.resumeAt;
        relabel(this.tourButton, at > 0 ? t('helpcenter.tour.resume', { index: at + 1 }) : t('helpcenter.tour.take'));
        this.tourAgain.hidden = at === 0;
    }

    async loadLessons() {
        const catalog = await loadCatalog();
        this.lessons = new Lessons(this.app, catalog, {
            ensure: (need) => this.ensure(need),
            onChange: () => this.renderLessons(),
        });
        this.app.tutorial = this.lessons.script();
        this.renderLessons();
    }

    renderLessons() {
        const lessons = this.lessons;
        if (!lessons || !this.lessonList) {
            return;
        }
        const done = doneCount(lessons.progress, lessons.ids);
        this.lessonSummary.textContent = t('helpcenter.lessons.summary', { done, count: lessons.ids.length });
        relabel(this.continueButton, done === 0 ? t('helpcenter.lessons.start') : (done === lessons.ids.length ? t('helpcenter.lessons.again') : t('helpcenter.lessons.continue')));
        this.resetButton.disabled = done === 0;
        this.lessonList.replaceChildren(...lessons.lessons.map((lesson) => {
            const finished = lesson.id in lessons.progress.done;
            return h('li', { class: finished ? 'done' : null, 'data-lesson': lesson.id },
                stateBadge(finished ? 'done' : 'todo', finished ? t('helpcenter.lesson.done') : t('helpcenter.lesson.todo'), 'lesson-mark'),
                h('h3', {}, lessonTitle(lesson)),
                h('p', { class: 'muted small' }, lessonAsk(lesson)),
                h('div', {}, h('button', { type: 'button', class: 'btn small', ...symbolOnly(t('helpcenter.lesson.start.label', { title: lessonTitle(lesson) })), onclick: () => lessons.start(lesson.id) }, icon(finished ? 'replay' : 'play'))));
        }));
    }

    async resetLessons() {
        if (this.lessons) {
            await this.lessons.reset();
            this.app.hud?.toast(t('helpcenter.lessons.resetDone'), 'info', 2500);
        }
    }

    async refreshSamples() {
        try {
            this.samples = await samplesApi.list();
            this.sampleError = null;
        } catch (err) {
            this.sampleError = err.message;
        }
        this.renderSamples();
    }

    renderSamples() {
        if (!this.sampleList) {
            return;
        }
        if (this.sampleError && !this.samples.length) {
            this.sampleList.replaceChildren();
            this.sampleNote.textContent = t('helpcenter.samples.offline', { error: this.sampleError });
            this.allButton.disabled = true;
            return;
        }
        this.allButton.disabled = this.samples.every((entry) => entry.state === 'library');
        this.sampleList.replaceChildren(...this.samples.map((entry) => {
            const action = entry.state === 'library'
                ? h('button', { type: 'button', class: 'btn small', ...symbolOnly(t('helpcenter.samples.open.label', { title: sampleTitle(entry) })), onclick: () => this.openSample(entry) }, icon('play'))
                : h('button', {
                    type: 'button', class: 'btn small',
                    ...symbolOnly(t(entry.state === 'trash' ? 'helpcenter.samples.restore.label' : 'helpcenter.samples.add.label', { title: sampleTitle(entry) })),
                    onclick: () => this.addSamples([entry.id]),
                }, icon(entry.state === 'trash' ? 'reset' : 'plus'));
            return h('li', { 'data-sample': entry.id },
                h('span', { class: 'sample-state' }, sampleState(entry)),
                h('h3', {}, sampleTitle(entry)),
                h('p', { class: 'muted small' }, sampleAbout(entry)),
                h('div', {}, action));
        }));
    }

    async addSamples(names) {
        this.sampleNote.textContent = t('helpcenter.samples.adding');
        try {
            const result = await samplesApi.add(names);
            this.samples = result.samples;
            this.sampleError = null;
            const words = result.changes.map((change) => {
                const entry = this.samples.find((item) => item.id === change.id);
                const title = entry ? sampleTitle(entry) : change.id;
                return tOr(`helpcenter.samples.change.${change.change}`, `${change.change} {title}`, { title });
            });
            this.sampleNote.textContent = words.length
                ? t('helpcenter.samples.changes', { list: words.join(', ') }).replace(/^./, (c) => c.toUpperCase())
                : t('helpcenter.samples.held');
            if (this.app.library && typeof this.app.library.refresh === 'function' && result.changes.some((change) => change.id === 'starter-team')) {
                this.app.library.refresh();
            }
        } catch (err) {
            this.sampleNote.textContent = err.message;
        }
        this.renderSamples();
    }

    openSample(entry) {
        if (entry.kind === 'recording') {
            this.app.openMatchInWatch(entry.target);
        } else {
            this.app.showPage('teams');
        }
    }

    // A button of the first-run tip starts the tour.
    bindTip() {
        const actions = this.app.firstRun && this.app.firstRun.tip && this.app.firstRun.tip.querySelector('.tip-actions');
        if (!actions) {
            return;
        }
        const button = h('button', { type: 'button', class: 'btn small', onclick: () => this.tour.start() }, t('helpcenter.tip.tour'));
        // Got it stays the first button of the tip.
        if (actions.firstElementChild) {
            actions.firstElementChild.after(button);
        } else {
            actions.append(button);
        }
    }

    // The command palette lists the tour, the lessons, the samples and the report.
    bindPalette() {
        const palette = this.app.palette;
        if (!palette || typeof palette.actions !== 'function') {
            return;
        }
        const own = palette.actions.bind(palette);
        palette.actions = () => [...own(), ...this.actions()];
    }

    actions() {
        const list = [];
        // The words of each action are its English words and the message helpcenter.words.<key>.
        const add = (title, run, key, keywords) => list.push(paletteAction('Help', title, run, searchWords(`helpcenter.words.${key}`, keywords)));
        const at = this.tour.resumeAt;
        add(at > 0 ? t('helpcenter.action.resume', { index: at + 1 }) : t('helpcenter.tour.take'), () => this.tour.start(), 'tour', 'tour walkthrough learn start help');
        if (this.lessons) {
            const next = this.lessons.state().next;
            add(next ? t('helpcenter.lessons.continue') : t('helpcenter.action.practice'), () => this.lessons.start(), 'lessons', 'tutorial lesson learn practice hands on');
            for (const lesson of this.lessons.lessons) {
                add(t('helpcenter.action.lesson', { title: lessonTitle(lesson) }), () => this.lessons.start(lesson.id), 'lesson', 'tutorial lesson learn');
            }
        }
        add(t('helpcenter.action.samples'), () => this.addSamples(null), 'samples', 'sample recording starter team restore trash');
        add(t('helpcenter.action.doctor'), () => this.openPart('doctor'), 'doctor', 'doctor report diagnostics problem bug webgl');
        add(t('helpcenter.action.install'), () => this.openPart('install'), 'install', 'install app pwa offline');
        return list;
    }

    // Shows a part of the Help page, and makes the report when asked for it.
    openPart(name) {
        const id = name === 'doctor' ? 'help-doctor-title' : 'help-install-title';
        if (this.app.palette) {
            this.app.palette.helpTopic(id);
        } else {
            this.app.showPage('help');
        }
        if (name === 'doctor' && this.doctor && typeof this.doctor.gather === 'function') {
            this.doctor.gather().catch(() => {});
        }
    }

    // The diagnostic report and the installable page, each its own module.
    async loadParts() {
        const parts = [
            ['./doctor.js', 'DoctorSection', this.doctorHost, 'doctor'],
            ['./pwa.js', 'AppInstall', this.installHost, 'install'],
        ];
        await Promise.allSettled(parts.map(async ([path, name, host, key]) => {
            if (!host) {
                return;
            }
            try {
                const module = await import(path);
                const part = new module[name](this.app, host);
                this[key] = part.script();
                this.app[key] = this[key];
            } catch (err) {
                console.warn(`${key} not loaded`, err);
                host.hidden = true;
            }
        }));
    }
}
