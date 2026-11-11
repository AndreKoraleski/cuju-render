// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The clean feed, the Watch page as a picture of fixed size for a streaming program such as OBS.
// feed-boot.js has set the settings before the viewer started, and this module then follows the
// source of the address. It asks the server what the source names every few seconds, opens it,
// and moves on once the current match has finished, so a feed follows a live source through its
// restarts, the newest recording, the matches of a tournament or the request queue. A lost
// stream or server is asked for again until it answers. While nothing shows, the feed shows its
// background and a slate. Scripts read the feed's state through cuju.feed.state().

import { serverText, t } from '../core/i18n.js';
import { watchSafeArea } from './safe-frame.js';

// The pace of the questions to the server, the first after a failure and the longest.
const POLL_MS = 4000;
const RETRY_MAX_MS = 15000;
// A question to the server that has no answer this long counts as failed, so a busy server never
// holds the feed on its last picture.
const RESOLVE_TIMEOUT_MS = 10000;
// A finished match of a source that follows others holds its last picture this long before the
// slate covers it.
const HOLD_MS = 6000;
// The sources that follow others, every source but a single recording.
const FOLLOWING = new Set(['auto', 'live', 'latest', 'tournament', 'queue']);

const $ = (id) => document.getElementById(id);

// Returns the frame gate of a frame rate, which says for each animation frame whether to draw. The
// frames that it lets through keep an even pace, and a late frame resets the pace instead of
// drawing twice in a row.
export function frameGate(fps) {
    if (!(fps > 0)) {
        return null;
    }
    const period = 1000 / fps;
    let next = null;
    return (now) => {
        if (next === null) {
            next = now;
        }
        // A frame a little early still counts, as the display's own frames jitter.
        if (now < next - Math.min(4, period * 0.25)) {
            return false;
        }
        next += period;
        if (next < now - period) {
            next = now + period;
        }
        return true;
    };
}

// Whether two targets of the server name the same match or source.
export function sameTarget(a, b) {
    return !!a && !!b && a.kind === b.kind && a.id === b.id;
}

// What the feed does with a target that the server names, given what it shows. Returns open to
// open the target, retry to open the same one again, restart to play the recording again, slate
// to cover a finished match with the slate, or wait. Stalled says that the live stream shown has
// lost its connection, so a newer live source that the server names takes its place at once.
export function nextStep({ target, current, finished, following, loop, failed, heldFor, stalled = false }) {
    if (!target || target.kind === 'none') {
        if (!current) {
            return 'slate';
        }
        return finished && following && heldFor >= HOLD_MS ? 'slate' : 'wait';
    }
    if (sameTarget(target, current)) {
        if (!finished) {
            return 'wait';
        }
        if (current.kind === 'live') {
            return failed ? 'retry' : (following && heldFor >= HOLD_MS ? 'slate' : 'wait');
        }
        if (loop) {
            return 'restart';
        }
        return following && heldFor >= HOLD_MS ? 'slate' : 'wait';
    }
    const replaced = stalled && current.kind === 'live' && target.kind === 'live';
    return !current || finished || replaced ? 'open' : 'wait';
}

export class Feed {
    constructor(app, boot) {
        this.app = app;
        this.boot = boot;
        this.options = boot.options;
        this.current = null;
        this.opening = false;
        this.started = false;
        this.showEnded = false;
        this.finishedSince = 0;
        this.failures = 0;
        this.online = null;
        // The server's message in English for the state, and as the slate shows it.
        this.message = '';
        this.messageText = '';
        this.timer = null;
        this.root = $('app');
        this.root.classList.add('feed');
        this.safe = watchSafeArea(this.root, this.options.safe);
        this.buildSlate();
        // The feed stays on Watch. The fade to Home at the end of the show ends the match instead.
        const showPage = app.showPage.bind(app);
        app.showPage = (name) => {
            if (name === 'watch') {
                showPage('watch');
            } else if (name === 'home') {
                this.showEnded = true;
            }
        };
        if (app.page !== 'watch') {
            showPage('watch');
        }
        app.setTvMode(true, true);
        app.setCamera(this.options.camera);
        app.frameGate = frameGate(this.options.fps);
        // A feed with sound starts it at once, which OBS allows a page without a click.
        if (this.options.audio) {
            app.sound.unlock();
        }
        if (this.options.layer === 'graphics') {
            // The graphics alone, so the picture need not draw.
            app.view.render = () => {};
        }
        const canvas = app.view.renderer && app.view.renderer.domElement;
        if (canvas && canvas.addEventListener) {
            canvas.addEventListener('webglcontextlost', () => {
                this.boot.broken = 'The graphics context was lost.';
            });
        }
        this.heartbeat = setInterval(() => this.beat(), 1000);
        this.beat();
        this.poll();
    }

    get following() {
        return FOLLOWING.has(this.options.sourceParsed.kind);
    }

    buildSlate() {
        const slate = document.createElement('div');
        slate.id = 'feed-slate';
        slate.setAttribute('aria-live', 'polite');
        const logo = document.createElement('img');
        logo.src = 'assets/cuju-logo.svg';
        logo.alt = '';
        this.slateText = document.createElement('div');
        this.slateText.className = 'feed-slate-text';
        slate.append(logo, this.slateText);
        this.slate = slate;
        this.root.append(slate);
    }

    // Shows the slate, or the background alone when the address turns the slate off.
    setSlate(on, text = '') {
        this.root.classList.toggle('feed-idle', on);
        this.slate.classList.toggle('show', on && this.options.slate);
        this.slateText.textContent = text || t('feed.slate.next');
    }

    // Whether the current target has finished, a recording that played to its end and its show,
    // or a live stream that ended or failed.
    finished() {
        const app = this.app;
        const cur = this.current;
        if (!cur) {
            return true;
        }
        const source = app.source;
        if (cur.kind === 'live') {
            if (source && source.kind === 'live' && source.id === cur.id) {
                return !!(source.live && (source.live.ended || source.live.failed));
            }
            return !app.pendingLive;
        }
        if (!source || source.id !== cur.id || !app.timeline) {
            return !this.opening;
        }
        if (this.showEnded) {
            return true;
        }
        const tl = app.timeline;
        return !tl.playing && tl.t >= tl.last - 0.5 && !app.director.running && !app.postMatch.running;
    }

    // Whether the live stream shown has lost its connection and tries to reconnect.
    liveStalled() {
        const source = this.app.source;
        if (this.current && this.current.kind === 'live' && source && source.kind === 'live' && source.id === this.current.id) {
            return !!(source.live && source.live.state === 'reconnecting');
        }
        return false;
    }

    liveFailed() {
        const source = this.app.source;
        if (this.current && source && source.kind === 'live' && source.id === this.current.id) {
            return !!(source.live && source.live.failed);
        }
        return true;
    }

    async resolve() {
        const abort = new AbortController();
        const timer = setTimeout(() => abort.abort(), RESOLVE_TIMEOUT_MS);
        let res;
        let body;
        try {
            res = await fetch(`/api/feed/resolve?source=${encodeURIComponent(this.options.source)}`, { cache: 'no-store', signal: abort.signal });
            body = await res.json().catch(() => null);
        } catch (err) {
            throw new Error(abort.signal.aborted ? t('feed.error.timeout') : err.message);
        } finally {
            clearTimeout(timer);
        }
        if (!res.ok || !body || typeof body !== 'object') {
            throw new Error((body && body.error && serverText(body)) || t('feed.error.status', { status: res.status }));
        }
        return body;
    }

    async poll() {
        clearTimeout(this.timer);
        let target = null;
        try {
            target = await this.resolve();
            this.online = true;
            this.failures = 0;
            this.message = target.message || '';
            this.messageText = serverText(target, 'message');
        } catch (err) {
            this.online = false;
            this.failures += 1;
            this.message = err.message;
            this.messageText = err.message;
        }
        if (this.online && !this.opening) {
            await this.consider(target);
        } else if (!this.online && !this.current) {
            this.setSlate(true, t('feed.slate.offline'));
        }
        const delay = this.online ? POLL_MS : Math.min(RETRY_MAX_MS, POLL_MS * 2 ** Math.min(3, this.failures - 1));
        this.timer = setTimeout(() => this.poll(), delay);
    }

    async consider(target) {
        const finished = this.finished();
        const now = performance.now();
        if (finished && !this.finishedSince) {
            this.finishedSince = now;
        } else if (!finished) {
            this.finishedSince = 0;
        }
        const step = nextStep({
            target,
            current: this.current,
            finished,
            following: this.following,
            loop: this.options.loop,
            failed: this.current && this.current.kind === 'live' ? this.liveFailed() : false,
            heldFor: this.finishedSince ? now - this.finishedSince : 0,
            stalled: this.liveStalled(),
        });
        if (step === 'open' || step === 'retry') {
            await this.open(target);
        } else if (step === 'restart') {
            this.restart();
        } else if (step === 'slate') {
            this.setSlate(true, target && target.kind !== 'none' ? '' : serverText(target, 'message'));
        }
    }

    async open(target) {
        const app = this.app;
        this.opening = true;
        this.showEnded = false;
        this.finishedSince = 0;
        this.current = { kind: target.kind, id: target.id, title: target.title || '' };
        try {
            if (target.kind === 'live') {
                app.openLive(target.id);
            } else {
                const at = this.started ? null : this.options.t;
                await app.openMatch(target.id, at);
            }
            this.started = true;
        } finally {
            this.opening = false;
        }
        app.setCamera(this.options.camera);
        this.beat();
    }

    // Plays the recording again from its start, as loop asks.
    restart() {
        const app = this.app;
        const tl = app.timeline;
        if (!tl) {
            return;
        }
        this.showEnded = false;
        this.finishedSince = 0;
        if (app.postMatch.running) {
            app.postMatch.end();
        }
        tl.seek(tl.first);
        app.afterSeek();
        tl.play(1);
        app.updatePlayUi();
        app.director.showLineups();
        this.beat();
    }

    // Marks the feed alive for its frame and keeps the slate in step with the picture.
    beat() {
        this.boot.alive = Date.now();
        this.boot.ready = true;
        const app = this.app;
        const showing = !!(this.current && app.source && app.source.id === this.current.id);
        if (showing && !(this.finishedSince && performance.now() - this.finishedSince >= HOLD_MS && this.following)) {
            this.setSlate(false);
        } else if (!this.current && this.online !== false) {
            this.setSlate(true, this.messageText);
        }
    }

    // The state of the feed, for scripts and agents.
    state() {
        const app = this.app;
        const tl = app.timeline;
        return {
            source: this.options.source,
            showing: this.current ? { ...this.current } : null,
            finished: this.finished(),
            online: this.online,
            message: this.message,
            slate: this.root.classList.contains('feed-idle'),
            playing: !!(tl && tl.playing),
            seconds: tl ? (tl.t - tl.first) / tl.sps : null,
            width: this.options.width,
            height: this.options.height,
            layout: { ...this.options.layout },
            view: { width: this.root.clientWidth, height: this.root.clientHeight },
            ratio: this.boot.ratio,
            safe: this.safe.margins ? { ...this.safe.margins } : null,
            fps: this.options.fps,
            muted: !!app.settings.muted,
            problems: [...this.boot.problems],
        };
    }
}

export function startFeed(app) {
    const feed = new Feed(app, window.cujuFeed);
    app.feed = feed;
    return feed;
}
