// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Event tracks and ball custody, sections 5.4, 6 and 14 of the contract.
//
// A track is content bound to a span of one clock, a clip, a curve, a pose or an effect, with a
// seed. A track on the simulation clock is a pure function of simulation time, so seeks, reverse
// play, slow motion and replays show the same thing. The ledger keeps tracks by id across
// epochs, so after a seek back the renderer restores them itself, without waiting for a worker.

import { clamp } from './values.js';

export const MAX_TRACKS = 512;
export const CLOCKS = ['sim', 'ceremony', 'cosmetic'];
export const REPLAY = ['repeat', 'quiet', 'skip'];
export const KINDS = ['clip', 'curve', 'pose', 'effect'];

// A track as a manifest, the animator or a worker gives it, checked, or null.
export function checkTrack(t, entities) {
    if (!t || typeof t !== 'object' || !/^[A-Za-z0-9_.:-]{1,80}$/.test(String(t.id || ''))) {
        return null;
    }
    const entity = t.entity == null || t.entity === 'world' ? 'world' : String(t.entity);
    if (entity !== 'world' && entities && !entities.has(entity)) {
        return null;
    }
    const from = Number(t.from);
    const to = Number(t.to);
    if (!Number.isFinite(from) || !Number.isFinite(to) || to < from || to - from > 600) {
        return null;
    }
    const content = t.content && typeof t.content === 'object' ? t.content : null;
    if (!content || !KINDS.includes(content.kind)) {
        return null;
    }
    return {
        id: String(t.id),
        entity,
        event: t.event == null ? null : String(t.event),
        from,
        to,
        clock: CLOCKS.includes(t.clock) ? t.clock : 'sim',
        content,
        seed: Number(t.seed) >>> 0,
        replay: REPLAY.includes(t.replay) ? t.replay : 'repeat',
        rate: clamp(Number(t.rate ?? 1) || 1, 0.05, 8),
        source: t.source || 'manifest',
    };
}

export class Ledger {
    constructor() {
        this.tracks = new Map();
    }

    // Adds a track or replaces the one of the same id. Returns the track.
    put(track) {
        this.tracks.delete(track.id);
        this.tracks.set(track.id, track);
        while (this.tracks.size > MAX_TRACKS) {
            this.tracks.delete(this.tracks.keys().next().value);
        }
        return track;
    }

    get(id) {
        return this.tracks.get(id) || null;
    }

    remove(id) {
        return this.tracks.delete(id);
    }

    // Drops the tracks a source added, such as a worker that failed.
    dropSource(source) {
        for (const [id, t] of this.tracks) {
            if (t.source === source) {
                this.tracks.delete(id);
            }
        }
    }

    // The tracks live at the clocks given, each with its local time, the clock's time past its
    // start. While a replay plays, tracks marked skip stay out and those marked quiet come back
    // with quiet set.
    active(clocks, { replay = false, entity = null } = {}) {
        const out = [];
        for (const t of this.tracks.values()) {
            if (entity != null && t.entity !== entity) {
                continue;
            }
            if (replay && t.replay === 'skip') {
                continue;
            }
            const now = clocks.read(t.clock);
            if (now >= t.from && now <= t.to) {
                out.push({ track: t, local: now - t.from, quiet: replay && t.replay === 'quiet' });
            }
        }
        return out;
    }
}

// The schedule of an action clip whose contact marker meets the ball. marker is the time of the
// contact in the clip, length the clip's length, contactT the contact on the simulation clock and
// lead the simulation time left until it when the track starts. A wind-up longer than the lead
// plays up to twice as fast, past that the clip starts later and the animator blends into it.
// Returns {from, to, rate, offset}, so the clip's time at simulation time s is
// marker + (s - contactT) * rate before the contact and marker + (s - contactT) after it.
export function contactSchedule(marker, length, contactT, lead) {
    const windup = Math.max(0, marker);
    const room = Math.max(0, lead);
    let rate = 1;
    let start = windup;
    if (room < windup) {
        rate = Math.min(2, windup / Math.max(room, 1e-6));
        start = Math.min(windup, room * rate);
    }
    return { from: contactT - start / rate, to: contactT + Math.max(0, length - windup), rate, offset: windup - start };
}

// The time in an action clip at simulation time s, by its schedule.
export function contactClipTime(schedule, marker, contactT, s) {
    return s < contactT ? marker + (s - contactT) * schedule.rate : marker + (s - contactT);
}

const TOUCH_RANK = { kick: 3, intended: 2, accidental: 1 };
const ACTION_RANK = (action) => (action === 8 ? 3 : action >= 4 && action <= 6 ? 2 : 1);

// Ball custody. A team claims the ball on its own touch, and keeps it until the next touch by
// anyone, a change of game mode, an epoch change or MAX_CUSTODY seconds of simulation time.
export const MAX_CUSTODY = 6;

export class Custody {
    constructor() {
        this.holder = null;
    }

    // The winner of one step's touches, by the higher kind of touch, then the higher action, or
    // -1 when the teams tie or no team touched. touches are the touch events of the step.
    static winner(touches) {
        const best = [null, null];
        for (const t of touches) {
            if (t.team !== 0 && t.team !== 1) {
                continue;
            }
            const rank = [TOUCH_RANK[t.data && t.data.kind] || 0, ACTION_RANK(t.data && t.data.action)];
            const b = best[t.team];
            if (!b || rank[0] > b[0] || (rank[0] === b[0] && rank[1] > b[1])) {
                best[t.team] = rank;
            }
        }
        if (best[0] && best[1]) {
            const d = best[0][0] - best[1][0] || best[0][1] - best[1][1];
            return d > 0 ? 0 : d < 0 ? 1 : -1;
        }
        return best[0] ? 0 : best[1] ? 1 : -1;
    }

    // A claim of team on an event of its own touch, granted when the team wins the step. Returns
    // whether custody was granted.
    claim(team, event, touchesOfStep) {
        if (!event || event.team !== team || Custody.winner(touchesOfStep) !== team) {
            return false;
        }
        this.holder = { team, event: event.id, step: event.step, since: event.t };
        return true;
    }

    // Ends custody on the events of a drawing, a later touch, a restart or a reset, and after
    // MAX_CUSTODY seconds.
    observe(events, sim) {
        if (!this.holder) {
            return;
        }
        for (const e of events) {
            if (e.phase !== 'occur') {
                continue;
            }
            if ((e.kind === 'touch' && e.step > this.holder.step) || e.kind === 'restart.begin' || e.kind === 'reset') {
                this.holder = null;
                return;
            }
        }
        if (sim - this.holder.since > MAX_CUSTODY || sim < this.holder.since - 0.5) {
            this.holder = null;
        }
    }

    reset() {
        this.holder = null;
    }

    holds(team) {
        return !!this.holder && this.holder.team === team;
    }
}
