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
import { doneCount } from './lessons-core.js';
import { HELP_TOPICS } from './palette.js';

const STATES = { library: 'In the library', trash: 'In the Trash', missing: 'Not in the library' };

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
        throw new Error(`Cannot reach the cuju server at ${location.origin}. Is it still running?`);
    }
    const text = await res.text();
    let body = null;
    try {
        body = text ? JSON.parse(text) : null;
    } catch {
        body = null;
    }
    if (!res.ok) {
        throw new Error((body && body.error) || `The server answered ${res.status}.`);
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
.lesson-list h4, .sample-list h4 { margin: 0; font-size: 15px; }
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
        this.tourButton = h('button', { type: 'button', class: 'btn primary', onclick: () => this.tour.start() });
        this.tourAgain = h('button', { type: 'button', class: 'btn', onclick: () => this.tour.start(0) }, 'Start the tour again');
        this.lessonSummary = h('p', { class: 'muted', 'aria-live': 'polite' }, 'The lessons are loading.');
        this.lessonList = h('ol', { class: 'lesson-list', 'aria-label': 'Lessons' });
        this.continueButton = h('button', { type: 'button', class: 'btn primary', onclick: () => this.lessons && this.lessons.start() }, 'Start the lessons');
        this.resetButton = h('button', { type: 'button', class: 'btn', onclick: () => this.resetLessons() }, 'Reset the lessons');
        const learn = h('section', { id: 'help-learn', 'aria-labelledby': 'help-learn-title', tabindex: '-1' },
            h('h3', { id: 'help-learn-title' }, 'Learn by doing'),
            h('p', {}, 'The guided tour points at the main control of each page, one step at a time. The lessons ask you to do one thing each, such as jumping to a goal or registering a team, and notice when it is done.'),
            h('div', { class: 'help-row' }, this.tourButton, this.tourAgain),
            h('h3', { id: 'help-lessons' }, 'Lessons'),
            this.lessonSummary,
            this.lessonList,
            h('div', { class: 'help-row' }, this.continueButton, this.resetButton),
            h('p', { class: 'muted small' }, 'An agent learns the same lessons with ', h('code', {}, 'cuju render tutorial'),
                ', which prints each step and checks it from the server, and a script that drives this page uses ',
                h('code', {}, 'window.cuju.tutorial'), '.'));
        this.sampleList = h('ul', { class: 'sample-list', 'aria-label': 'Samples' });
        this.sampleNote = h('p', { class: 'muted small', 'aria-live': 'polite' });
        this.allButton = h('button', { type: 'button', class: 'btn', onclick: () => this.addSamples(null) }, 'Add or restore every sample');
        const samples = h('section', { id: 'help-samples', 'aria-labelledby': 'help-samples-title' },
            h('h3', { id: 'help-samples-title' }, 'Samples'),
            h('p', {}, 'cuju ships two recordings and a starter team. Each one can be added again, or brought back from the Trash, at any time.'),
            this.sampleList,
            h('div', { class: 'help-row' }, this.allButton),
            this.sampleNote);
        this.doctorHost = h('section', { id: 'help-doctor', 'aria-labelledby': 'help-doctor-title' });
        this.installHost = h('section', { id: 'help-install', 'aria-labelledby': 'help-install-title' });
        const header = card.querySelector('header');
        (header || card.firstChild).after(learn, samples, this.doctorHost, this.installHost);
        for (const topic of [
            ['help-learn-title', 'Guided tour', 'tour walkthrough start learn tutorial'],
            ['help-lessons', 'Lessons', 'tutorial hands on learn practice'],
            ['help-samples-title', 'Samples', 'sample recording starter team restore'],
            ['help-doctor-title', 'Diagnostic report', 'doctor report diagnostics webgl versions problem'],
            ['help-install-title', 'Install the app', 'install app pwa offline'],
        ]) {
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
                }
            }).observe(page, { attributes: true, attributeFilter: ['hidden'] });
        }
    }

    renderTour() {
        if (!this.tourButton) {
            return;
        }
        const at = this.tour.resumeAt;
        this.tourButton.textContent = at > 0 ? `Resume the tour at step ${at + 1}` : 'Take the guided tour';
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
        this.lessonSummary.textContent = `${done} of ${lessons.ids.length} lessons done.`;
        this.continueButton.textContent = done === 0 ? 'Start the lessons' : (done === lessons.ids.length ? 'Practice again' : 'Continue the lessons');
        this.resetButton.disabled = done === 0;
        this.lessonList.replaceChildren(...lessons.lessons.map((lesson) => {
            const finished = lesson.id in lessons.progress.done;
            return h('li', { class: finished ? 'done' : null, 'data-lesson': lesson.id },
                h('span', { class: 'lesson-mark' }, finished ? 'Done' : 'To do'),
                h('h4', {}, lesson.title),
                h('p', { class: 'muted small' }, lesson.ask),
                h('div', {}, h('button', { type: 'button', class: 'btn small', 'aria-label': `Start the lesson ${lesson.title}`, onclick: () => lessons.start(lesson.id) }, finished ? 'Again' : 'Start')));
        }));
    }

    async resetLessons() {
        if (this.lessons) {
            await this.lessons.reset();
            this.app.hud?.toast('The lessons are reset.', 'info', 2500);
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
            this.sampleNote.textContent = `${this.sampleError} The command cuju render sample adds the samples too.`;
            this.allButton.disabled = true;
            return;
        }
        this.allButton.disabled = this.samples.every((entry) => entry.state === 'library');
        this.sampleList.replaceChildren(...this.samples.map((entry) => {
            const action = entry.state === 'library'
                ? h('button', { type: 'button', class: 'btn small', 'aria-label': `Open ${entry.title}`, onclick: () => this.openSample(entry) }, 'Open')
                : h('button', { type: 'button', class: 'btn small', 'aria-label': `${entry.state === 'trash' ? 'Restore' : 'Add'} ${entry.title}`, onclick: () => this.addSamples([entry.id]) }, entry.state === 'trash' ? 'Restore' : 'Add');
            return h('li', { 'data-sample': entry.id },
                h('span', { class: 'sample-state' }, STATES[entry.state] || entry.state),
                h('h4', {}, entry.title),
                h('p', { class: 'muted small' }, entry.about),
                h('div', {}, action));
        }));
    }

    async addSamples(names) {
        this.sampleNote.textContent = 'Adding the samples.';
        try {
            const result = await samplesApi.add(names);
            this.samples = result.samples;
            this.sampleError = null;
            const words = result.changes.map((change) => {
                const entry = this.samples.find((item) => item.id === change.id);
                return `${change.change} ${entry ? entry.title : change.id}`;
            });
            this.sampleNote.textContent = words.length ? `${words.join(', ')}.`.replace(/^./, (c) => c.toUpperCase()) : 'The library already holds those samples.';
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
        const button = h('button', { type: 'button', class: 'btn small', onclick: () => this.tour.start() }, 'Take the tour');
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
        const add = (title, run, keywords) => list.push({ group: 'Help', title, run, keywords, hint: '' });
        const at = this.tour.resumeAt;
        add(at > 0 ? `Resume the guided tour at step ${at + 1}` : 'Take the guided tour', () => this.tour.start(), 'tour walkthrough learn start help');
        if (this.lessons) {
            const next = this.lessons.state().next;
            add(next ? 'Continue the lessons' : 'Practice the lessons again', () => this.lessons.start(), 'tutorial lesson learn practice hands on');
            for (const lesson of this.lessons.lessons) {
                add(`Lesson, ${lesson.title}`, () => this.lessons.start(lesson.id), 'tutorial lesson learn');
            }
        }
        add('Add or restore the samples', () => this.addSamples(null), 'sample recording starter team restore trash');
        add('Make the diagnostic report', () => this.openPart('doctor'), 'doctor report diagnostics problem bug webgl');
        add('Install the app', () => this.openPart('install'), 'install app pwa offline');
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
