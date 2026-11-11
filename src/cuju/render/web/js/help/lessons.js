// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The hands-on lessons. A small panel at the bottom of the window asks the person to do one thing,
// such as jumping to a goal or following a player, offers a sample first when the lesson needs a
// recording, and watches the page's own state a few times a second until the thing is done. The
// browser keeps the lessons done, Reset forgets them, and every lesson done is reported to the
// server, so `cuju render tutorial` sees the lessons that only a page can check. Those lessons are
// also watched while no panel shows, so a script that follows the steps of the tutorial reports
// them, and on load the page takes in the lessons that the server knows done. The panel is a
// region beside the page, so every control stays usable, and Esc closes it while it has the
// focus. Scripts reach it as window.cuju.tutorial.

import { LESSONS_KEY, checkLesson, doneCount, lessonAnnouncement, lessonAsk, lessonPraise, lessonTitle, markDone, needMet, nextLesson, progressState } from './lessons-core.js';
import { t } from '../core/i18n.js';

// The panel looks this often while a lesson is under way.
const LOOK_MS = 400;
// The teams of the registry are read this often while the lesson of a team is under way.
const TEAMS_MS = 3000;

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

export async function loadCatalog() {
    const res = await fetch('lessons.json', { cache: 'no-cache' });
    if (!res.ok) {
        throw new Error(t('lessons.loadFailed', { status: res.status }));
    }
    return (await res.json()).lessons;
}

export class Lessons {
    // helpers holds ensure(need), which adds a sample and resolves once it is there, and
    // onChange(), which redraws the list of the Help page.
    constructor(app, lessons, helpers) {
        this.app = app;
        this.lessons = lessons;
        this.ids = lessons.map((lesson) => lesson.id);
        this.helpers = helpers;
        this.progress = this.read();
        this.active = null;
        this.base = null;
        this.memory = {};
        this.teamCount = null;
        this.count = h('p', { class: 'lesson-count' });
        this.title = h('h2', { id: 'lesson-title', tabindex: '-1' });
        this.ask = h('p', { class: 'lesson-ask' });
        this.offerButton = h('button', { type: 'button', class: 'btn small', onclick: () => this.fillNeed() });
        this.goButton = h('button', { type: 'button', class: 'btn small', onclick: () => this.goThere() });
        this.offer = h('div', { class: 'lesson-offer' }, this.offerButton, this.goButton);
        this.status = h('p', { class: 'lesson-status', role: 'status', 'aria-live': 'polite' });
        this.nextButton = h('button', { type: 'button', class: 'btn primary small', onclick: () => this.advance() }, t('lessons.skip'));
        this.panel = h('aside', { id: 'lesson-panel', class: 'lesson-panel', role: 'region', 'aria-labelledby': 'lesson-title', hidden: true },
            this.count, this.title, this.ask, this.offer, this.status,
            h('div', { class: 'lesson-actions' }, this.nextButton,
                h('button', { type: 'button', class: 'btn small', onclick: () => this.stop(true) }, t('lessons.close'))));
        this.panel.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                this.stop(true);
            }
        });
        (document.getElementById('app') || document.body).append(this.panel);
        // The lessons that only a page can check are watched all the time, so a person or a
        // script that does one without starting it, as the steps of `cuju render tutorial` do,
        // still reports it.
        this.watched = lessons.filter((lesson) => lesson.agent && lesson.agent.check === 'page').map((lesson) => lesson.id);
        this.background = {};
        this.watchTimer = setInterval(() => this.watch(), LOOK_MS);
        this.synced = this.sync();
    }

    // Takes in the lessons that the server knows done, those other pages reported and those whose
    // checks of the library hold, so a fresh browser shows the progress the server has.
    async sync() {
        try {
            const res = await fetch('/api/help/tutorial', { cache: 'no-store' });
            if (!res.ok) {
                return this.state();
            }
            const server = await res.json();
            const done = (server.lessons || []).filter((entry) => entry.done && !(entry.id in this.progress.done));
            if (done.length) {
                const when = new Date().toISOString();
                for (const entry of done) {
                    this.progress = markDone(this.progress, entry.id, when, this.ids);
                }
                this.save();
                if (this.active) {
                    this.nextButton.textContent = this.nextLabel(this.active);
                }
            }
        } catch {
            // The server is away, the browser keeps what it has.
        }
        return this.state();
    }

    // One look for the lessons of the page that are not done and not under way.
    watch() {
        if (document.hidden) {
            return;
        }
        const waiting = this.watched.filter((id) => !(id in this.progress.done) && !(this.active && this.active.id === id));
        if (!waiting.length) {
            return;
        }
        // Watched in the background, the seeks of a replay or of the show after the match stay
        // out, so watching a match with its replays leaves Jump to a goal open.
        const app = this.app;
        const snap = { ...this.snapshot(), show: !!((app.director && app.director.active) || (app.postMatch && app.postMatch.running)) };
        for (const id of waiting) {
            const entry = this.background[id] || (this.background[id] = { base: snap, memory: {} });
            if ((entry.base.source && entry.base.source.id) !== (snap.source && snap.source.id)) {
                entry.base = snap;
            }
            // A lesson counts once its check turns true, so a state that already holds when the
            // watching begins, such as a followed player at a reset, stays out.
            if (!checkLesson(id, snap, entry.base, entry.memory)) {
                entry.ready = true;
            } else if (entry.ready) {
                delete this.background[id];
                this.progress = markDone(this.progress, id, new Date().toISOString(), this.ids);
                this.save();
                this.report([id]);
            }
        }
    }

    read() {
        try {
            return progressState(JSON.parse(localStorage.getItem(LESSONS_KEY)), this.ids);
        } catch {
            return progressState(null, this.ids);
        }
    }

    save() {
        try {
            localStorage.setItem(LESSONS_KEY, JSON.stringify(this.progress));
        } catch {
            // Storage can be unavailable, the lessons then last for this visit only.
        }
        this.helpers.onChange();
    }

    lesson(id) {
        return this.lessons.find((lesson) => lesson.id === id) || null;
    }

    get isOpen() {
        return !this.panel.hidden;
    }

    // What the page holds now, for the checks of lessons-core.js.
    snapshot() {
        const app = this.app;
        const tl = app.timeline;
        const source = app.source && !app.source.game ? { kind: app.source.kind, id: app.source.id } : null;
        const play = app.play;
        const game = play && play.game;
        let running = null;
        if (game && game.started && !game.ended && game.source && game.source.store) {
            const store = game.source.store;
            const frame = store.get(store.last);
            running = { id: game.id, running: !game.paused, step: frame && typeof frame.step === 'number' ? frame.step : null };
        }
        let challenge = false;
        try {
            const state = play && play.challenges && play.challenges.state();
            challenge = !!(state && (state.run || (state.jobs && state.jobs.length)));
        } catch {
            challenge = false;
        }
        const capture = app.photo && app.photo.lastCapture;
        return {
            at: performance.now(),
            page: app.page,
            source,
            t: source && tl ? tl.t : null,
            sps: source && tl ? tl.sps : null,
            playing: !!(source && tl && tl.playing),
            jumps: source && tl ? tl.jumps || 0 : 0,
            speed: tl ? tl.direction * tl.speed : 1,
            goals: source && tl && tl.store ? tl.store.goals.map((goal) => goal.index) : [],
            camera: app.cameras ? app.cameras.mode : null,
            game: running,
            teams: this.teamCount,
            challenge,
            photo: capture ? JSON.stringify(capture) : null,
        };
    }

    // Begins a lesson, by default the next one not done, on its page.
    start(id = null) {
        const lesson = this.lesson(id || this.progress.current || nextLesson(this.progress, this.ids) || this.ids[0]);
        if (!lesson) {
            return this.state();
        }
        this.active = lesson;
        this.progress = { ...this.progress, current: lesson.id };
        this.save();
        this.memory = {};
        this.teamCount = null;
        this.base = null;
        const index = this.ids.indexOf(lesson.id);
        this.count.textContent = t('lessons.count', { index: index + 1, count: this.ids.length });
        this.title.textContent = lessonTitle(lesson);
        this.ask.textContent = lessonAsk(lesson);
        this.panel.hidden = false;
        this.panel.classList.remove('lesson-done');
        if (this.app.page !== lesson.page && !(lesson.page === 'watch' && this.app.page === 'watch')) {
            this.app.showPage(lesson.page);
        }
        const done = lesson.id in this.progress.done;
        this.status.textContent = done ? t('lessons.doneBefore') : lessonAnnouncement(lesson, index, this.ids.length);
        this.nextButton.textContent = this.nextLabel(lesson);
        this.updateOffer();
        this.title.focus({ preventScroll: true });
        clearInterval(this.timer);
        this.timer = setInterval(() => this.look(), LOOK_MS);
        this.look();
        return this.state();
    }

    nextLabel(lesson) {
        const after = nextLesson(this.progress, this.ids, lesson.id);
        if (lesson.id in this.progress.done) {
            return after ? t('lessons.next') : t('lessons.finish');
        }
        return t('lessons.skip');
    }

    updateOffer() {
        const lesson = this.active;
        if (!lesson) {
            return;
        }
        const snap = this.snapshot();
        const missing = !needMet(lesson, snap);
        const team = lesson.id === 'register_team' && !(lesson.id in this.progress.done);
        this.offerButton.hidden = !(missing || team);
        this.offerButton.textContent = team ? t('lessons.offer.team') : t('lessons.offer.recording');
        this.offerButton.disabled = false;
        const away = this.app.page !== lesson.page;
        this.goButton.hidden = !away;
        this.goButton.textContent = t('lessons.go', { page: t(`palette.page.${lesson.page}`) });
        this.offer.hidden = this.offerButton.hidden && this.goButton.hidden;
    }

    async fillNeed() {
        const lesson = this.active;
        if (!lesson) {
            return;
        }
        this.offerButton.disabled = true;
        this.status.textContent = t('lessons.adding');
        try {
            await this.helpers.ensure(lesson.id === 'register_team' ? 'team' : 'recording');
            this.status.textContent = lesson.id === 'register_team' ? t('lessons.added.team') : t('lessons.added.recording');
        } catch (err) {
            this.status.textContent = t('lessons.addFailed', { error: err.message });
        }
        this.offerButton.disabled = false;
        const focused = document.activeElement === this.offerButton || document.activeElement === document.body;
        this.updateOffer();
        // The offer hides once its sample is there, so the focus goes on to the next button of
        // the panel rather than to the page.
        if (focused && this.isOpen && this.offerButton.hidden) {
            (this.goButton.hidden ? this.nextButton : this.goButton).focus({ preventScroll: true });
        }
    }

    goThere() {
        if (this.active) {
            this.app.showPage(this.active.page);
            this.updateOffer();
        }
    }

    async readTeams() {
        if (this.teamsBusy || (this.teamsAt && performance.now() - this.teamsAt < TEAMS_MS)) {
            return;
        }
        this.teamsBusy = true;
        try {
            const { api } = await import('../core/api.js');
            const teams = await api.teams();
            this.teamCount = teams.filter((team) => team.kind !== 'builtin').length;
        } catch {
            // The server is away, the lesson waits for it.
        } finally {
            this.teamsAt = performance.now();
            this.teamsBusy = false;
        }
    }

    // One look at the page, which ends the lesson once its check holds.
    look() {
        const lesson = this.active;
        if (!lesson || !this.isOpen) {
            return;
        }
        if (lesson.id === 'register_team') {
            this.readTeams();
        }
        const snap = this.snapshot();
        // A lesson compares with the page as it stood when the lesson began, or when the recording
        // that it shows changed.
        if (!this.base || (this.base.source && this.base.source.id) !== (snap.source && snap.source.id)) {
            this.base = snap;
        }
        this.panel.classList.toggle('lesson-compact', !!snap.game && this.app.page === 'play');
        this.updateOffer();
        if (lesson.id === 'play_game' && snap.game && !this.memory.reported) {
            const step = snap.game.step - (this.memory.firstStep ?? snap.game.step);
            if (step > 0 && step < 300) {
                const seconds = Math.floor(step / 10);
                if (seconds !== this.memory.shownSeconds && seconds % 5 === 0) {
                    this.memory.shownSeconds = seconds;
                    this.status.textContent = t('lessons.played', { count: seconds });
                }
            }
        }
        if (!checkLesson(lesson.id, snap, this.base, this.memory) || this.memory.reported) {
            return;
        }
        this.memory.reported = true;
        this.complete(lesson);
    }

    complete(lesson) {
        this.progress = markDone(this.progress, lesson.id, new Date().toISOString(), this.ids);
        this.save();
        this.panel.classList.add('lesson-done');
        this.status.textContent = t('lessons.done', { praise: lessonPraise(lesson) });
        this.nextButton.textContent = this.nextLabel(lesson);
        this.report([lesson.id]);
        if (this.onDone) {
            this.onDone(lesson.id);
        }
    }

    async report(ids) {
        try {
            await fetch('/api/help/tutorial', {
                method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ done: ids }),
            });
        } catch {
            // The server is away, the browser keeps the lesson all the same.
        }
    }

    // The next lesson not done, or the end of the tutorial.
    advance() {
        const lesson = this.active;
        const after = lesson ? nextLesson(this.progress, this.ids, lesson.id) : nextLesson(this.progress, this.ids);
        if (!after || after === (lesson && lesson.id)) {
            this.stop(false);
            this.progress = { ...this.progress, current: null };
            this.save();
            const all = doneCount(this.progress, this.ids) === this.ids.length;
            this.app.hud?.toast(all ? t('lessons.allDone') : t('lessons.stopped'), 'info', 4000);
            return this.state();
        }
        return this.start(after);
    }

    // Closes the panel, and with focus gives the focus back to the page.
    stop(focus = false) {
        clearInterval(this.timer);
        this.timer = null;
        const inside = this.panel.contains(document.activeElement);
        this.panel.hidden = true;
        this.active = null;
        if (focus || inside) {
            document.getElementById('pages')?.focus({ preventScroll: true });
        }
        return this.state();
    }

    // Forgets every lesson done, in the browser and on the server.
    async reset() {
        this.stop(false);
        this.progress = progressState(null, this.ids);
        this.background = {};
        this.save();
        // The page lessons take their starting point at once, so a step that follows the reset
        // before the next look still counts.
        this.watch();
        try {
            await fetch('/api/help/tutorial', {
                method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reset: true }),
            });
        } catch {
            // The server is away, the browser has forgotten the lessons all the same.
        }
        return this.state();
    }

    state() {
        return {
            active: this.active ? this.active.id : null,
            done: Object.keys(this.progress.done).filter((id) => this.ids.includes(id)),
            next: nextLesson(this.progress, this.ids),
            count: this.ids.length,
        };
    }

    // The functions of window.cuju.tutorial.
    script() {
        return {
            lessons: () => this.lessons.map((lesson) => ({ id: lesson.id, title: lesson.title, page: lesson.page, ask: lesson.ask, needs: lesson.needs || null, done: lesson.id in this.progress.done })),
            start: (id) => this.start(id || null),
            stop: () => this.stop(false),
            next: () => this.advance(),
            check: () => {
                this.look();
                return this.state();
            },
            reset: () => this.reset(),
            state: () => this.state(),
            snapshot: () => this.snapshot(),
        };
    }
}
