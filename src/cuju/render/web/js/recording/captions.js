// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Text captions of the events of a match, short and plain, such as "Goal, number 9 for the
// Greens, 2 to 1", timed to the moments of moments.js. Every caption is a message id of the table
// captions.json with its values, so a translation replaces the table alone. The server writes
// the same cues as WebVTT with src/cuju/render/_moments/captions.py, by the same rules.
//
// The functions at the top touch nothing of the page, so they hold the same under Node. The
// overlay at the end shows the cues on Watch and Play, inside the safe areas, and reads each new
// cue to screen readers through a live region.

import { momentsOf } from './moments.js';

// Seconds a cue stays at most, at least, and how many show at once.
export const CUE_SECONDS = 4;
export const MIN_CUE_SECONDS = 1.5;
export const SHOWN = 3;
export const SIZES = Object.freeze(['small', 'medium', 'large']);
// Steps a growing live store holds back, so the moments of its newest steps settle first.
export const LIVE_HOLD_STEPS = 30;
// Steps the overlay reads in one drawing, so a long recording costs no visible pause.
export const CHUNK_STEPS = 400;

const RESTARTS = new Set(['corner', 'free_kick', 'penalty', 'throw_in', 'goal_kick']);

// The text of a message with its values put in place of the names in braces.
export function format(messages, id, params = {}) {
    const template = messages[id];
    if (typeof template !== 'string') {
        return id;
    }
    return template.replace(/\{([A-Za-z]+)\}/g, (whole, name) => (params[name] === undefined ? whole : String(params[name])));
}

// The names of the teams and the number and roster name of every player, from a header and the
// styles of its teams, which hold the rosters. A player without a roster entry wears 1 in goal
// and one more than the index of the team otherwise, as the kits do.
export function captionContext(header, styles = []) {
    const teams = [0, 1].map((side) => {
        const team = (header.teams || [])[side] || {};
        return typeof team.name === 'string' && team.name.trim() ? team.name.trim() : null;
    });
    const players = (header.players || []).map((p) => {
        const style = styles[p.team] || (((header.teams || [])[p.team] || {}).style) || {};
        const roster = Array.isArray(style.players) ? style.players[p.index] : null;
        const entry = roster && typeof roster === 'object' ? roster : null;
        let number = p.goalkeeper ? 1 : p.index + 1;
        if (entry) {
            number = Number.isInteger(entry.number) && entry.number >= 0 && entry.number <= 99 ? entry.number : p.index + 1;
        }
        const name = entry && typeof entry.name === 'string' ? entry.name.slice(0, 24).trim() : '';
        return { team: p.team, number, name };
    });
    return { teams, players };
}

function teamName(messages, context, side) {
    const name = context.teams[side];
    return name || format(messages, side === 0 ? 'caption.side.left' : 'caption.side.right');
}

function playerPhrase(messages, context, k) {
    const p = context.players[k];
    if (!p) {
        return null;
    }
    return p.name ? format(messages, 'caption.player.named', { number: p.number, name: p.name })
        : format(messages, 'caption.player', { number: p.number });
}

// The message id and values of the caption of a moment, or null for a moment without one,
// such as a pass or a change of possession.
export function captionOf(moment, context, messages) {
    const d = moment.data || {};
    const k = moment.player;
    const known = k != null && context.players[k] != null;
    const player = known ? playerPhrase(messages, context, k) : null;
    const team = moment.team != null ? teamName(messages, context, moment.team) : null;
    const of = known ? teamName(messages, context, context.players[k].team) : null;
    const score = Array.isArray(d.score) ? { left: d.score[0], right: d.score[1] } : {};
    switch (moment.kind) {
    case 'goal':
        if (d.ownGoal && known) {
            return { id: 'caption.goal.own', params: { player, otherTeam: of, ...score } };
        }
        if (known) {
            return { id: 'caption.goal', params: { player, team, ...score } };
        }
        return team ? { id: 'caption.goal.team', params: { team, ...score } } : null;
    case 'shot':
        return known ? { id: d.header ? 'caption.shot.header' : 'caption.shot', params: { player, team: of } } : null;
    case 'save':
    case 'block':
    case 'tackle':
    case 'foul':
    case 'offside':
        return known ? { id: `caption.${moment.kind}`, params: { player, team: of } } : null;
    case 'card': {
        if (!known) {
            return null;
        }
        const id = d.colour === 'red' ? (d.second ? 'caption.card.secondYellow' : 'caption.card.red') : 'caption.card.yellow';
        return { id, params: { player, team: of } };
    }
    case 'woodwork':
        return { id: d.part === 'bar' ? 'caption.woodwork.bar' : 'caption.woodwork.post', params: {} };
    case 'nearMiss':
        return { id: d.line === 'over' ? 'caption.nearMiss.over' : 'caption.nearMiss.wide', params: {} };
    case 'restart':
        return RESTARTS.has(d.restart) && team ? { id: `caption.restart.${d.restart}`, params: { team } } : null;
    case 'halftime':
        return { id: 'caption.halftime', params: score };
    case 'fulltime':
        return d.winner === 0 || d.winner === 1
            ? { id: 'caption.fulltime.win', params: { team: teamName(messages, context, d.winner), ...score } }
            : { id: 'caption.fulltime.draw', params: score };
    default:
        return null;
    }
}

// The cues of moments, each with its start and end in seconds of the timeline, its message id
// and values, its text and the id of its moment, in the order of their starts. A cue lasts four
// seconds, or until the next cue starts, and at least a second and a half.
export function cuesOf(moments, context, messages) {
    const cues = [];
    for (const moment of moments) {
        const caption = captionOf(moment, context, messages);
        if (caption) {
            cues.push({
                start: moment.t, end: 0, id: caption.id, params: caption.params,
                text: format(messages, caption.id, caption.params), kind: moment.kind, moment: moment.id,
            });
        }
    }
    cues.sort((a, b) => a.start - b.start);
    timeCues(cues);
    return cues;
}

function timeCues(cues, from = 0) {
    for (let i = from; i < cues.length; i++) {
        const next = i + 1 < cues.length ? cues[i + 1].start : Infinity;
        cues[i].end = Math.max(cues[i].start + MIN_CUE_SECONDS, Math.min(cues[i].start + CUE_SECONDS, next));
    }
}

// A time of a WebVTT file, hours, minutes, seconds and milliseconds.
export function vttTime(seconds) {
    const ms = Math.floor(Math.max(0, seconds) * 1000 + 0.5);
    const pad = (x, n = 2) => String(x).padStart(n, '0');
    return `${pad(Math.floor(ms / 3600000))}:${pad(Math.floor(ms / 60000) % 60)}:${pad(Math.floor(ms / 1000) % 60)}.${pad(ms % 1000, 3)}`;
}

// The cues as a WebVTT file.
export function toVtt(cues) {
    const lines = ['WEBVTT', ''];
    cues.forEach((cue, i) => {
        lines.push(String(i + 1), `${vttTime(cue.start)} --> ${vttTime(cue.end)}`, cue.text, '');
    });
    return lines.join('\n');
}

// The cues that show at time now, the newest last, at most SHOWN of them.
export function activeCues(cues, now) {
    const out = [];
    for (const cue of cues) {
        if (cue.start > now) {
            break;
        }
        if (now < cue.end) {
            out.push(cue);
        }
    }
    return out.slice(-SHOWN);
}

// The cues whose start forward play crossed from then to now.
export function crossedCues(cues, then, now) {
    return cues.filter((cue) => cue.start > then && cue.start <= now);
}

// The cues of one store as it grows, every step of a recording, and for a live store the steps
// that have settled, extended as frames arrive. A track reads at most chunk steps at a time.
export class CueTrack {
    constructor(store, context, messages, live = false, chunk = Infinity) {
        this.store = store;
        this.context = context;
        this.messages = messages;
        this.live = live;
        this.done = store.first - 1;
        this.cues = [];
        this.extend(chunk);
    }

    // The last step whose moments have settled.
    get settled() {
        return this.live ? this.store.last - LIVE_HOLD_STEPS : this.store.last;
    }

    // Whether steps that have settled wait to be read.
    get pending() {
        return this.done < this.settled;
    }

    // Reads the moments of up to steps more of the steps that settled since the last call.
    extend(steps = Infinity) {
        const store = this.store;
        const from = Math.max(this.done + 1, store.first);
        const to = Math.min(this.settled, from + steps - 1);
        if (to < from) {
            return;
        }
        const added = cuesOf(momentsOf(store, from, to), this.context, this.messages);
        this.done = to;
        if (!added.length) {
            return;
        }
        this.cues.push(...added);
        this.cues.sort((a, b) => a.start - b.start);
        timeCues(this.cues);
    }
}

let tableLoad = null;

// The table of messages of the page, read once from captions.json beside it.
export function loadMessages(url = 'captions.json') {
    if (!tableLoad) {
        tableLoad = fetch(url).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`captions.json ${r.status}`))))
            .then((table) => table.messages || {});
    }
    return tableLoad;
}

function load(key, fallback) {
    try {
        const v = localStorage.getItem(`cuju.${key}`);
        return v === null ? fallback : JSON.parse(v);
    } catch {
        return fallback;
    }
}

function save(key, value) {
    try {
        localStorage.setItem(`cuju.${key}`, JSON.stringify(value));
    } catch {
        // Storage can be unavailable, the setting then lasts for this visit only.
    }
}

// The captions over the view of Watch and Play. The setting turns them on or off and picks a
// size, and the browser keeps both. Each new cue that forward play reaches goes to a live
// region, so a screen reader reads it once, and the cues of the moment show above the controls.
export class CaptionsOverlay {
    constructor(app) {
        this.app = app;
        this.enabled = load('captions', false) === true;
        this.size = SIZES.includes(load('captionSize', 'medium')) ? load('captionSize', 'medium') : 'medium';
        this.messages = null;
        this.track = null;
        this.store = null;
        this.last = null;
        this.seekedTo = null;
        this.shown = '';
        this.spoken = { track: null, ids: new Set() };
        this.box = document.createElement('div');
        this.box.className = 'captions';
        this.box.id = 'captions';
        this.box.hidden = true;
        this.box.setAttribute('aria-hidden', 'true');
        this.live = document.createElement('div');
        this.live.className = 'sr-only';
        this.live.id = 'captions-live';
        this.live.setAttribute('aria-live', 'polite');
        this.live.setAttribute('role', 'log');
        this.live.setAttribute('aria-label', 'Captions');
        this.applySize();
        this.addSettings();
        loadMessages().then((messages) => {
            this.messages = messages;
        }).catch(() => {
            this.messages = null;
        });
    }

    addSettings() {
        const anchor = document.getElementById('labels-on') || document.getElementById('trail');
        const label = anchor && anchor.closest('label');
        if (!label) {
            return;
        }
        const check = document.createElement('input');
        check.type = 'checkbox';
        check.id = 'captions-on';
        check.checked = this.enabled;
        check.addEventListener('change', () => this.setEnabled(check.checked));
        const row = document.createElement('label');
        row.className = 'check';
        row.append(check, ' Captions of the events of the match');
        const size = document.createElement('select');
        size.id = 'captions-size';
        for (const [value, text] of [['small', 'Small'], ['medium', 'Medium'], ['large', 'Large']]) {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = text;
            size.append(option);
        }
        size.value = this.size;
        size.addEventListener('change', () => this.setSize(size.value));
        const sizeRow = document.createElement('label');
        sizeRow.append('Size of the captions ', size);
        label.after(row, sizeRow);
        this.check = check;
        this.select = size;
    }

    setEnabled(on) {
        this.enabled = !!on;
        save('captions', this.enabled);
        if (this.check) {
            this.check.checked = this.enabled;
        }
        this.last = null;
        this.render([]);
    }

    setSize(size) {
        this.size = SIZES.includes(size) ? size : 'medium';
        save('captionSize', this.size);
        if (this.select) {
            this.select.value = this.size;
        }
        this.applySize();
    }

    applySize() {
        this.box.dataset.size = this.size;
    }

    // The cues of the open source, made when a source opens or its teams change.
    trackFor(timeline) {
        const app = this.app;
        if (!this.messages || !timeline || !app.source || !app.source.header) {
            return null;
        }
        const styles = app.styles || [];
        const key = `${app.source.id || ''}:${styles.length}`;
        if (!this.track || this.store !== timeline.store || this.key !== key) {
            this.store = timeline.store;
            this.key = key;
            this.track = new CueTrack(timeline.store, captionContext(app.source.header, styles), this.messages,
                !!timeline.live, CHUNK_STEPS);
        } else if (this.track.pending) {
            this.track.extend(CHUNK_STEPS);
        }
        return this.track;
    }

    // The cues of the open recording, every settled step read, for Save captions.
    cues() {
        const track = this.trackFor(this.app.timeline);
        if (!track) {
            return [];
        }
        track.extend();
        return track.cues;
    }

    // Saves the cues of the open recording as a WebVTT file, named after the recording, and
    // returns its text. With save false it only returns the text.
    download({ save = true } = {}) {
        const app = this.app;
        const cues = this.cues();
        if (!this.messages || !app.source) {
            if (app.hud) {
                app.hud.toast('The captions are not ready yet', 'error');
            }
            return null;
        }
        const text = toVtt(cues);
        if (!save) {
            return text;
        }
        const name = `${String(app.source.id || 'recording').replace(/[^A-Za-z0-9_.-]+/g, '-')}.vtt`;
        const url = URL.createObjectURL(new Blob([text], { type: 'text/vtt' }));
        const link = document.createElement('a');
        link.href = url;
        link.download = name;
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        if (app.hud) {
            app.hud.toast(`Saved ${cues.length} captions as ${name}`);
        }
        return text;
    }

    // Shows the cues of the drawn time and sends the new ones to the live region, on each frame.
    update() {
        const app = this.app;
        const hud = document.getElementById('hud');
        if (hud && hud.parentNode && this.box.parentNode !== hud.parentNode) {
            hud.parentNode.insertBefore(this.box, hud.nextSibling);
            hud.parentNode.insertBefore(this.live, this.box.nextSibling);
        }
        const tl = app.timeline;
        const onStage = app.page === 'watch' || app.page === 'play';
        if (!this.enabled || !onStage || !tl || !tl.store || tl.store.size === 0) {
            this.last = null;
            this.render([]);
            return;
        }
        const track = this.trackFor(tl);
        if (!track) {
            return;
        }
        const now = tl.t / tl.sps;
        if (this.seekedTo != null) {
            // A seek counts the cues of the moment it lands on as read, and play from there reads
            // the next ones, also when the first frame after it already passed their start.
            this.spoken = { track, ids: new Set(activeCues(track.cues, this.seekedTo).map((cue) => cue.moment)) };
            this.last = this.seekedTo;
            this.seekedTo = null;
        }
        const then = this.last;
        const wall = performance.now() / 1000;
        const elapsed = this.lastWall == null ? 0 : wall - this.lastWall;
        this.last = now;
        this.lastWall = wall;
        const active = activeCues(track.cues, now);
        // Forward play reads each cue it reaches once, also one whose steps settled a moment
        // after the view passed its start, and a seek, a reverse or a pause reads none. Play moves
        // the view by the time that passed at its speed, so a slow page that draws seldom still
        // plays forward, and only a jump beyond that is a seek.
        const reach = Math.max(2, elapsed * Math.max(1, tl.speed || 1) + 0.5);
        const forward = then != null && tl.playing && tl.direction > 0 && now >= then && now - then < reach;
        if (this.spoken.track !== track || (!forward && then != null && Math.abs(now - then) > 0.5)) {
            // After a seek the cues ahead are read again when play reaches them.
            this.spoken = { track, ids: new Set(active.map((cue) => cue.moment)) };
        }
        for (const cue of active) {
            if (!this.spoken.ids.has(cue.moment)) {
                this.spoken.ids.add(cue.moment);
                if (forward) {
                    this.announce(cue.text);
                }
            }
        }
        this.render(active);
    }

    // Called by the page after every seek, with the timeline already at its new place.
    seeked() {
        const tl = this.app.timeline;
        this.seekedTo = tl ? tl.t / tl.sps : null;
        this.lastWall = performance.now() / 1000;
    }

    announce(text) {
        const line = document.createElement('p');
        line.textContent = text;
        this.live.append(line);
        while (this.live.childElementCount > 3) {
            this.live.firstElementChild.remove();
        }
    }

    render(cues) {
        const text = cues.map((cue) => cue.text).join('\n');
        if (text === this.shown) {
            return;
        }
        this.shown = text;
        this.box.replaceChildren(...cues.map((cue) => {
            const line = document.createElement('span');
            line.className = 'caption-line';
            line.textContent = cue.text;
            return line;
        }));
        this.box.hidden = !cues.length;
    }
}
