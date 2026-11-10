// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The event catalog of the team presentation contract, sections 4 and 5. It reads the frames of
// a store and names what happens in them, the authoritative events that frame fields state, the
// inferred game events that versioned rules derive from them, and the forecasts that let a
// package wind up before a contact.
//
// Every event has the same shape. Its id hashes the kind, the step and the players the frame
// bytes name, so it stays the same across epochs, replays and catalogs. Its step is the absolute
// frame index of the timeline, which a live ring keeps when it drops old frames, and its t is that
// index divided by the steps per second, the simulation time in seconds. A touch and the events
// read from a touch take the estimated contact moment as t instead, which lies inside the step
// before the flagged one. The lead is the event's t minus the drawn time, positive for a forecast,
// at or a little below zero when it occurs, and negative in a resync after a seek.
//
// An occur event carries what is known when it happens. An outcome that later frames settle, the
// fate of a pass, a shot, a save or a slide, and the scorer and assist of a goal, follows as a
// resolve of the same id with the next revision, at the step where the frames settle it.
//
// The module reads frames only and imports nothing but the recording format, so it runs in the
// page, in a worker and under Node alike.

import {
    ACTION, BALL_FLOAT, EPISODE_END, EPISODE_START, NODES_FLOAT, PLAYER_FLOATS, TOUCH, episodeBoundary,
    isCut,
} from '../recording/format.js';

// Seconds of simulation time that forecasts of contacts and of outcomes reach ahead of the drawn
// time. Outcomes wait so a package cannot tell the viewer of a goal long before it happens.
export const CONTACT_HORIZON = 2.5;
export const OUTCOME_HORIZON = 0.5;

// Kinds forecast over the whole contact horizon.
export const CONTACT_KINDS = Object.freeze([
    'touch', 'pass', 'shot', 'header', 'volley', 'slide', 'save', 'catch', 'deflection', 'restart.taken',
]);

// Kinds forecast only within the outcome horizon. Every resolve is held back the same way, which
// covers the outcome of a save, a shot, a pass and a slide and the enriched goal, since a resolve
// tells how a contact ends.
export const OUTCOME_KINDS = Object.freeze(['goal', 'woodwork', 'nearMiss', 'card']);

// Version of each inference rule. An inferred event names its rule and version in inference, so
// a package can pin the behaviour it was tested with.
export const RULES = Object.freeze({
    pass: 1, shot: 1, header: 1, volley: 1, slide: 1, catch: 1, deflection: 1, block: 1, save: 1,
    goal: 1, woodwork: 1, nearMiss: 1, sprint: 1, dribble: 1,
});

// The median number of steps from the start of an action to the touch it makes, per action kind.
// Measured on the two shipped samples, sample-11v11.cjr and sample-5v5.cjr, over every touch byte,
// by walking back from the touch step to the step where the player's action byte took its value
// and pooling the lags of both samples. The pooled counts were ballControl 433, trap 58, shortPass
// 67, longPass 15, highPass 32, shot 6, interfere 13, deflect 2 and trip 10. Shot has an even count
// whose middle values are 2 and 3. Header, catch, sliding and special never touched the ball in
// the samples and take DEFAULT_LAG, the pooled median of all touches.
export const ACTION_LAGS = Object.freeze({
    ballControl: 2, trap: 3, shortPass: 3, longPass: 3, highPass: 3, shot: 2.5, interfere: 1,
    deflect: 2, trip: 0,
});
export const DEFAULT_LAG = 2;

// GRF's pitch and goal, the goal lines at 55 meters either side of the centre, the touch lines
// at 36, the posts 3.66 meters either side of the middle of the goal line and the bar at 2.44.
const HALF_W = 55;
const HALF_H = 36;
const POST_Y = 3.66;
const BAR_Z = 2.44;

// Steps an analysis looks back for events that an earlier step settles, the longest being a
// dribble of fifteen seconds.
const BACK_SECONDS = 15;
// The most a player root moves in a step without a teleport of a restart, in meters per second.
const RUN_LIMIT = 15;
const SPRINT_SPEED = 6.5;
const SPRINT_STEPS = 5;

export const ACTION_NAMES = Object.freeze(Object.fromEntries(Object.entries(ACTION).map(([name, value]) => [value, name])));
const TOUCH_KINDS = [null, 'kick', 'intended', 'accidental'];
export const RESTART_NAMES = Object.freeze([null, 'kickoff', 'goal_kick', 'free_kick', 'corner', 'throw_in', 'penalty']);
const FOUL_TYPES = [null, 'foul', 'yellow', 'red'];

const PASSES = new Set([ACTION.shortPass, ACTION.longPass, ACTION.highPass]);
const PASS_TYPES = { [ACTION.shortPass]: 'short', [ACTION.longPass]: 'long', [ACTION.highPass]: 'high' };
const SAVES = new Set([ACTION.catch, ACTION.deflect, ACTION.interfere, ACTION.ballControl, ACTION.trap]);
const CATCHES = new Set([ACTION.catch, ACTION.ballControl, ACTION.trap]);
const QUIET_ACTIONS = new Set([ACTION.none, ACTION.movement]);
const CONTACT = new Set(CONTACT_KINDS);
const OUTCOME = new Set(OUTCOME_KINDS);

const stepsPerSecond = (store) => (store.header && store.header.steps_per_second) || 10;
const ball = (f) => [f.data[BALL_FLOAT], f.data[BALL_FLOAT + 1], f.data[BALL_FLOAT + 2]];
const root = (f, k) => {
    const o = NODES_FLOAT + k * PLAYER_FLOATS;
    return [f.data[o], f.data[o + 1], f.data[o + 2]];
};
const attackX = (team) => (team === 0 ? HALF_W : -HALF_W);
const scoreOf = (f, team) => (team === 0 ? f.scoreLeft : f.scoreRight);
const intentional = (touch) => touch === TOUCH.kicked || touch === TOUCH.nonKicked;
const round = (x, places = 3) => Math.round(x * 10 ** places) / 10 ** places;

// FNV 1a over the text, as eight hexadecimal digits.
function hash(text) {
    let h = 0x811c9dc5;
    for (let i = 0; i < text.length; i++) {
        h ^= text.charCodeAt(i);
        h = Math.imul(h, 0x01000193);
    }
    return (h >>> 0).toString(16).padStart(8, '0');
}

// The id of an event, from its kind, its step and the players the frame bytes name for it. Team
// events with no player name the team instead.
export function eventId(kind, step, key) {
    return `${kind}:${step}:${hash(`${kind}|${step}|${key.join(',')}`)}`;
}

function velocity(a, b, sps) {
    return [(b.data[BALL_FLOAT] - a.data[BALL_FLOAT]) * sps, (b.data[BALL_FLOAT + 1] - a.data[BALL_FLOAT + 1]) * sps,
        (b.data[BALL_FLOAT + 2] - a.data[BALL_FLOAT + 2]) * sps];
}

// The estimated contact moment of a touch flagged on step i, section 5.3. The ball is drawn as
// straight segments between the samples, and the engine flags the step whose interval holds the
// contact. The incoming segment from step i minus 2 to i minus 1 and the outgoing one from i to
// i plus 1 are extended over that interval, and the moment where they come closest is the
// contact, clamped to the interval. Without both segments, or with no bend between them, the
// contact is the sample of the interval where the drawn path bends most. Returns the time in
// seconds, the step and fraction of the interval it falls in, the point in the pitch frame and
// the method, intersection or sample.
export function contactEstimate(store, i) {
    const sps = stepsPerSecond(store);
    const c = store.get(i);
    if (!c) {
        return null;
    }
    const b = store.get(i - 1);
    if (!b || isCut(b, c)) {
        return { t: i / sps, step: i, fraction: 0, point: ball(c), method: 'sample' };
    }
    const a = store.get(i - 2);
    const d = store.get(i + 1);
    const joinedIn = a && !isCut(a, b);
    const joinedOut = d && !isCut(c, d);
    const pb = ball(b);
    const pc = ball(c);
    if (joinedIn && joinedOut) {
        const pa = ball(a);
        const pd = ball(d);
        const vin = [pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]];
        const vout = [pd[0] - pc[0], pd[1] - pc[1], pd[2] - pc[2]];
        // The incoming line at u is pb plus vin times u, the outgoing one pc plus vout times u
        // minus 1, so their gap is offset plus slope times u.
        const offset = [pb[0] - pc[0] + vout[0], pb[1] - pc[1] + vout[1], pb[2] - pc[2] + vout[2]];
        const slope = [vin[0] - vout[0], vin[1] - vout[1], vin[2] - vout[2]];
        const denom = slope[0] ** 2 + slope[1] ** 2 + slope[2] ** 2;
        if (denom > 1e-8) {
            const u = -(offset[0] * slope[0] + offset[1] * slope[1] + offset[2] * slope[2]) / denom;
            const fraction = Math.min(1, Math.max(0, u));
            const p = [0, 1, 2].map((n) => (pb[n] + vin[n] * fraction + pc[n] + vout[n] * (fraction - 1)) / 2);
            return result(i, fraction, p, 'intersection', sps);
        }
    }
    // The bend of the drawn path at each end of the interval, where both neighbours exist.
    const bendAt = (p, q, r) => Math.hypot(q[0] - p[0] - (r[0] - q[0]), q[1] - p[1] - (r[1] - q[1]), q[2] - p[2] - (r[2] - q[2]));
    const bendB = joinedIn ? bendAt(ball(a), pb, pc) : -1;
    const bendC = joinedOut ? bendAt(pb, pc, ball(d)) : -1;
    const fraction = bendB > bendC ? 0 : 1;
    return result(i, fraction, fraction ? pc : pb, 'sample', sps);
}

function result(i, fraction, point, method, sps) {
    const at = i - 1 + fraction;
    const step = fraction >= 1 ? i : i - 1;
    return {
        t: at / sps,
        step,
        fraction: fraction >= 1 ? 0 : fraction,
        point: point.map((x) => round(x, 4)),
        method,
    };
}

// The analysis of one store, computed a step at a time and cached. A step's results depend on a
// bounded window of frames around it. When the window reached past the newest frame of a growing
// live store, the results are kept only until a newer frame arrives, then computed again, so a
// recording computes each step once and a live stream settles as its frames come in.
class Analysis {
    constructor(store) {
        this.store = store;
        this.header = store.header;
        this.players = store.header.players;
        this.n = this.players.length;
        this.sps = stepsPerSecond(store);
        this.back = BACK_SECONDS * this.sps;
        this.entries = new Map();
        this.due = new Map();
        this.shots = new Map();
        this.speeds = new Map();
        this.merged = new Map();
        this.missed = false;
    }

    // A frame of the store, noting a read past the newest frame.
    get(j) {
        if (j > this.store.last) {
            this.missed = true;
            return undefined;
        }
        return this.store.get(j);
    }

    prune() {
        if (this.entries.size < 4096) {
            return;
        }
        const floor = this.store.first - this.back - 64;
        for (const map of [this.entries, this.due, this.shots, this.speeds, this.merged]) {
            for (const key of map.keys()) {
                if (key < floor) {
                    map.delete(key);
                }
            }
        }
    }

    // A cached computation of step i in one of the maps, computed again once it is no longer
    // valid. Step results read the shots of earlier steps but never the results of other steps,
    // and shots read frames alone, so the computations never nest deeply.
    cached(map, i, compute) {
        const outer = this.missed;
        this.missed = false;
        const item = compute(i);
        item.complete = !this.missed;
        item.last = this.store.last;
        this.missed = outer || !item.complete;
        map.set(i, item);
        this.prune();
        return item;
    }

    // A valid cached item, noting that a result built on an unsettled one is unsettled too.
    hit(item) {
        if (item && (item.complete || item.last === this.store.last)) {
            if (!item.complete) {
                this.missed = true;
            }
            return true;
        }
        return false;
    }

    // The results of step i.
    at(i) {
        const item = this.entries.get(i);
        return this.hit(item) ? item : this.cached(this.entries, i, (j) => this.compute(j));
    }

    // The shots of step i, each with the shot event and how the shot ends.
    shotsAt(i) {
        const item = this.shots.get(i);
        return (this.hit(item) ? item : this.cached(this.shots, i, (j) => ({ list: this.findShots(j) }))).list;
    }

    // Every event of step i in the order the catalog sends them, frame events, inferred events,
    // then the resolves and deferred events that earlier steps settle there.
    eventsAt(i) {
        const item = this.merged.get(i);
        if (this.hit(item)) {
            return item.list;
        }
        return this.cached(this.merged, i, (j) => {
            const entry = this.at(j);
            return { list: entry.frame.concat(entry.inferred, this.dueAt(j)) };
        }).list;
    }

    // The resolves and deferred events that earlier steps settle at step i.
    dueAt(i) {
        const item = this.due.get(i);
        if (this.hit(item)) {
            return item.list;
        }
        return this.cached(this.due, i, (j) => {
            const list = [];
            for (let s = Math.max(this.store.first, j - this.back); s <= j; s++) {
                const later = this.at(s).later;
                for (let n = 0; n < later.length; n++) {
                    if (later[n].due === j) {
                        list.push(later[n].event);
                    }
                }
            }
            return { list };
        }).list;
    }

    event(kind, i, fields) {
        const key = fields.key || (fields.player != null && fields.player >= 0 ? [fields.player] : [`team${fields.team == null ? '' : fields.team}`]);
        const ev = {
            id: eventId(kind, i, key),
            kind,
            phase: 'occur',
            revision: 0,
            step: i,
            t: fields.t == null ? i / this.sps : fields.t,
            lead: 0,
        };
        if (fields.team != null && fields.team >= 0) {
            ev.team = fields.team;
        }
        if (fields.player != null && fields.player >= 0) {
            ev.player = fields.player;
        }
        const subjects = (fields.subjects || (ev.player != null ? [ev.player] : [])).filter((k) => k != null && k >= 0);
        if (subjects.length) {
            ev.subjects = subjects;
        }
        ev.provenance = fields.provenance || 'frame';
        if (fields.rule) {
            ev.inference = `${fields.rule}/${RULES[fields.rule]}`;
        }
        ev.data = Object.freeze(fields.data || {});
        return Object.freeze(ev);
    }

    // A resolve of an event, the same id with the next revision, settled at step due.
    resolve(ev, due, data, extra = {}) {
        return {
            due,
            event: Object.freeze({
                ...ev,
                ...extra,
                phase: 'resolve',
                revision: ev.revision + 1,
                data: Object.freeze({ ...ev.data, ...data, resolvedStep: due, resolvedT: due / this.sps }),
            }),
        };
    }

    compute(i) {
        const entry = { frame: [], inferred: [], later: [], touches: [] };
        const f = this.get(i);
        if (!f) {
            return entry;
        }
        const p = this.get(i - 1);
        const joined = !!p && !isCut(p, f);
        this.frameStep(i, f, p, joined, entry);
        this.inferStep(i, f, p, joined, entry);
        return entry;
    }

    // Section 4.1, the events that frame fields state.
    frameStep(i, f, p, joined, entry) {
        const out = entry.frame;
        const header = this.header;
        const n = this.n;
        const score = [f.scoreLeft, f.scoreRight];
        if ((i === this.store.first && f.step === 0) || (p && episodeBoundary(p, f)) || (!p && (f.flags & EPISODE_START))) {
            out.push(this.event('episode.begin', i, { data: { episodeStep: f.step } }));
        }
        if (joined && header.second_half != null) {
            const threshold = header.second_half * 1800;
            if (p.timeMs < threshold && f.timeMs >= threshold) {
                out.push(this.event('halftime', i, { data: { score } }));
            }
        }
        if (joined && p.gameMode > 0 && f.gameMode === 0) {
            out.push(this.restartTaken(i, p.gameMode));
        }
        for (let k = 0; k < n; k++) {
            if (f.touches[k]) {
                const ev = this.touchEvent(i, k, f);
                out.push(ev);
                entry.touches.push(ev);
            }
        }
        if (joined) {
            for (let k = 0; k < n; k++) {
                const was = p.actions[k];
                const now = f.actions[k];
                if (was === now) {
                    continue;
                }
                const team = this.players[k].team;
                if (!QUIET_ACTIONS.has(was)) {
                    out.push(this.event('action.end', i, { player: k, team, data: { action: ACTION_NAMES[was] } }));
                }
                if (!QUIET_ACTIONS.has(now)) {
                    out.push(this.event('action.begin', i, {
                        player: k, team, data: { action: ACTION_NAMES[now], expectedContact: this.expectedContact(i, k, now) },
                    }));
                }
            }
            if (f.ownedPlayer !== p.ownedPlayer || f.ownedTeam !== p.ownedTeam) {
                out.push(this.event('possession', i, {
                    key: [p.ownedPlayer, f.ownedPlayer],
                    player: f.ownedPlayer,
                    team: f.ownedTeam,
                    subjects: [p.ownedPlayer, f.ownedPlayer],
                    data: {
                        from: p.ownedPlayer, to: f.ownedPlayer, fromTeam: p.ownedTeam, toTeam: f.ownedTeam,
                        teamChange: p.ownedTeam !== f.ownedTeam,
                    },
                }));
            }
            if (f.scoreLeft > p.scoreLeft || f.scoreRight > p.scoreRight) {
                const team = f.scoreLeft > p.scoreLeft ? 0 : 1;
                const bits = header.engine_scorer ? (f.flags >>> 8) & 31 : 0;
                const scorer = bits > 0 && bits <= n ? bits - 1 : -1;
                const data = { scoringTeam: team, score };
                if (scorer >= 0) {
                    data.scorer = scorer;
                }
                out.push(this.event('goal', i, { key: [`team${team}`], team, player: scorer, data }));
            }
            if (f.foul.type > 0 && (p.foul.type === 0 || p.foul.player !== f.foul.player || p.foul.type !== f.foul.type)) {
                const off = f.foul.player;
                const second = f.foul.type === 2 && off >= 0 && off < n && !!(p.playerFlags[off] & 2);
                out.push(this.event('foul', i, {
                    key: [off, f.foul.victim],
                    player: off,
                    team: off >= 0 && off < n ? this.players[off].team : -1,
                    subjects: [off, f.foul.victim],
                    data: { offender: off, victim: f.foul.victim, type: FOUL_TYPES[f.foul.type] || 'foul', second },
                }));
            }
            for (let k = 0; k < n; k++) {
                const was = p.playerFlags[k];
                const now = f.playerFlags[k];
                if (was === now) {
                    continue;
                }
                const team = this.players[k].team;
                if ((now & 4) && !(was & 4)) {
                    out.push(this.event('card', i, { player: k, team, data: { colour: 'red', player: k, second: !!(was & 2) } }));
                } else if ((now & 2) && !(was & 2)) {
                    out.push(this.event('card', i, { player: k, team, data: { colour: 'yellow', player: k, second: false } }));
                }
                if ((was & 1) && !(now & 1)) {
                    out.push(this.event('sentOff', i, { player: k, team, data: { player: k } }));
                } else if (!(was & 1) && (now & 1)) {
                    out.push(this.event('onPitch', i, { player: k, team, data: { player: k } }));
                }
                if ((was ^ now) & 8) {
                    out.push(this.event('control', i, { player: k, team, data: { player: k, controlled: !!(now & 8) } }));
                }
            }
            if (header.offside_called && (f.flags & 4) && !(p.flags & 4) && f.offside >= 0 && f.offside < n) {
                out.push(this.event('offside', i, { player: f.offside, team: this.players[f.offside].team, data: { player: f.offside } }));
            }
            if (f.gameMode > 0 && f.gameMode !== p.gameMode) {
                const taker = this.takerOf(i);
                out.push(this.event('restart.begin', i, {
                    key: [`mode${f.gameMode}`],
                    player: taker,
                    team: taker >= 0 ? this.players[taker].team : -1,
                    data: { restart: RESTART_NAMES[f.gameMode] || 'kickoff', mode: f.gameMode, taker },
                }));
            }
        }
        const next = this.get(i + 1);
        const flagged = !!(f.flags & EPISODE_END);
        if (flagged || (next && episodeBoundary(f, next))) {
            out.push(this.event('episode.end', i, { data: { episodeStep: f.step, flagged, score } }));
            if (flagged && header.full_match === true) {
                const winner = f.scoreLeft === f.scoreRight ? null : (f.scoreLeft > f.scoreRight ? 0 : 1);
                out.push(this.event('fulltime', i, { team: winner == null ? -1 : winner, data: { winner, draw: winner == null, score } }));
            }
        }
    }

    touchEvent(i, k, f) {
        const sps = this.sps;
        const a = this.get(i - 2);
        const b = this.get(i - 1);
        const d = this.get(i + 1);
        const joinedIn = a && b && !isCut(a, b) && !isCut(b, f);
        const joinedOut = d && !isCut(f, d);
        const contact = contactEstimate(this.store, i);
        const data = {
            kind: TOUCH_KINDS[f.touches[k]] || 'kick',
            action: ACTION_NAMES[f.actions[k]],
            ball: ball(f).map((x) => round(x, 4)),
            velocityIn: joinedIn ? velocity(a, b, sps).map((x) => round(x)) : null,
            velocityOut: joinedOut ? velocity(f, d, sps).map((x) => round(x)) : null,
            contactT: contact.t,
            contactPoint: contact.point,
        };
        return this.event('touch', i, { player: k, team: this.players[k].team, t: contact.t, data });
    }

    // The expected contact of an action that player k begins at step i, section 5.1. The first
    // touch by the player while the action lasts, within the contact horizon, is certain. Frames
    // that show the action end without a touch expect none. When the frames run out first, the
    // median lag of the action kind gives an estimate that is not certain.
    expectedContact(i, k, action) {
        const limit = i + Math.ceil(CONTACT_HORIZON * this.sps);
        let prev = this.get(i - 1);
        for (let j = i; j <= limit; j++) {
            const f = this.get(j);
            if (!f) {
                if (j > this.store.last) {
                    const name = ACTION_NAMES[action];
                    const lag = ACTION_LAGS[name] == null ? DEFAULT_LAG : ACTION_LAGS[name];
                    return { t: (i + lag) / this.sps, step: Math.round(i + lag), certain: false };
                }
                return null;
            }
            if (j > i && (isCut(prev, f) || f.actions[k] !== action)) {
                return null;
            }
            if (f.touches[k]) {
                const contact = contactEstimate(this.store, j);
                return { t: contact.t, step: j, certain: true };
            }
            prev = f;
        }
        return null;
    }

    // The player who takes the restart that begins at step i, the first owner or toucher after
    // it, as transition.js finds the taker.
    takerOf(i) {
        for (let j = i; j <= i + 25; j++) {
            const f = this.get(j);
            if (!f) {
                break;
            }
            if (f.ownedPlayer >= 0 && f.ownedPlayer < this.n) {
                return f.ownedPlayer;
            }
            for (let k = 0; k < this.n; k++) {
                if (f.touches[k]) {
                    return k;
                }
            }
        }
        return -1;
    }

    // Play resumes at step i, where the game mode returns to normal play. The taker is the first
    // player to touch the ball around that step, and the event takes the moment of that touch.
    restartTaken(i, mode) {
        let taker = -1;
        let at = -1;
        for (const j of [i, i - 1, i + 1, i + 2, i + 3]) {
            const f = this.get(j);
            if (!f) {
                continue;
            }
            for (let k = 0; k < this.n && taker < 0; k++) {
                if (f.touches[k]) {
                    taker = k;
                    at = j;
                }
            }
            if (taker >= 0) {
                break;
            }
        }
        const t = at >= 0 ? contactEstimate(this.store, at).t : i / this.sps;
        return this.event('restart.taken', i, {
            key: [`mode${mode}`],
            player: taker,
            team: taker >= 0 ? this.players[taker].team : -1,
            t,
            data: { restart: RESTART_NAMES[mode] || 'kickoff', mode, taker, touchStep: at >= 0 ? at : null },
        });
    }

    // Section 4.2, the version 1 inference rules.
    inferStep(i, f, p, joined, entry) {
        const n = this.n;
        for (const touch of entry.touches) {
            const k = touch.player;
            // A touch that lasts several steps with the same action is one, at its first step.
            if (joined && p.touches[k] && p.actions[k] === f.actions[k]) {
                continue;
            }
            this.inferTouch(i, k, f, touch, entry);
        }
        if (joined) {
            for (let k = 0; k < n; k++) {
                if (f.actions[k] === ACTION.sliding && p.actions[k] !== ACTION.sliding && (f.playerFlags[k] & 1)) {
                    this.inferSlide(i, k, entry);
                }
            }
        }
        this.inferSprints(i, entry);
        this.inferDribble(i, f, entry);
        if (this.ringsAt(i) && !this.ringsAt(i - 1)) {
            this.inferWoodwork(i, f, entry);
        }
        if (joined) {
            this.inferNearMiss(i, p, f, entry);
            const goal = entry.frame.find((ev) => ev.kind === 'goal');
            if (goal) {
                entry.later.push(this.enrichGoal(i, goal));
            }
        }
        // A save or block settles a shot of an earlier step, which only the step of the touch
        // can see, so the touches of this step look back for the shots they stop.
        for (const touch of entry.touches) {
            this.inferStop(i, touch, entry);
        }
    }

    inferTouch(i, k, f, touch, entry) {
        const team = this.players[k].team;
        const action = f.actions[k];
        const kind = f.touches[k];
        const base = { player: k, team, t: touch.t, provenance: 'inferred' };
        if (intentional(kind) && PASSES.has(action)) {
            const ev = this.event('pass', i, {
                ...base, rule: 'pass',
                data: { type: PASS_TYPES[action], target: this.passTarget(i, k, touch), outcome: 'pending', touch: touch.id },
            });
            entry.inferred.push(ev);
            const settled = this.followPass(i, k, team);
            if (settled) {
                entry.later.push(this.resolve(ev, settled.due, { outcome: settled.outcome, receiver: settled.receiver }));
            }
        }
        const shot = this.shotsAt(i).find((x) => x.k === k);
        const shoots = !!shot;
        if (shot) {
            entry.inferred.push(shot.event);
            if (shot.follow.due != null) {
                const follow = shot.follow;
                entry.later.push(this.resolve(shot.event, follow.due, {
                    onTarget: follow.onTarget, outcome: follow.outcome, woodwork: follow.woodwork,
                    keeper: follow.keeper ? follow.keeper.k : -1, stopper: follow.stopper,
                }));
            }
        }
        if (action === ACTION.header) {
            entry.inferred.push(this.event('header', i, {
                ...base, rule: 'header', data: { purpose: shoots ? 'shot' : this.headerPurpose(touch, team), touch: touch.id },
            }));
        }
        const cp = touch.data.contactPoint;
        const vin = touch.data.velocityIn;
        if (kind === TOUCH.kicked && action !== ACTION.header && cp[2] > 0.3 && vin && vin[2] < 0) {
            entry.inferred.push(this.event('volley', i, { ...base, rule: 'volley', data: { height: cp[2], touch: touch.id } }));
        }
        if (action === ACTION.catch) {
            entry.inferred.push(this.event('catch', i, { ...base, rule: 'catch', data: { goalkeeper: !!this.players[k].goalkeeper, touch: touch.id } }));
        }
        if (action === ACTION.deflect) {
            entry.inferred.push(this.event('deflection', i, { ...base, rule: 'deflection', data: { goalkeeper: !!this.players[k].goalkeeper, touch: touch.id } }));
        }
    }

    // The teammate nearest the line of the ball's flight, within 30 degrees of it, or -1.
    passTarget(i, k, touch) {
        const f = this.get(i);
        const v = touch.data.velocityOut || touch.data.velocityIn;
        if (!v) {
            return -1;
        }
        const speed = Math.hypot(v[0], v[1]);
        if (speed < 1) {
            return -1;
        }
        const dx = v[0] / speed;
        const dy = v[1] / speed;
        const from = touch.data.contactPoint;
        let best = -1;
        let bestScore = Math.tan(Math.PI / 6);
        for (let m = 0; m < this.n; m++) {
            if (m === k || this.players[m].team !== this.players[k].team || !(f.playerFlags[m] & 1)) {
                continue;
            }
            const r = root(f, m);
            const along = (r[0] - from[0]) * dx + (r[1] - from[1]) * dy;
            if (along <= 1) {
                continue;
            }
            const across = Math.abs((r[0] - from[0]) * dy - (r[1] - from[1]) * dx);
            const score = across / along;
            if (score < bestScore) {
                bestScore = score;
                best = m;
            }
        }
        return best;
    }

    // Follows a pass from step i to the next touch by another player within ten seconds. A
    // teammate's touch completes it, an opponent's intercepts it, and a stop of play first ends
    // it out when the ball left the pitch and stopped otherwise. Returns null when nothing
    // settles it.
    followPass(i, k, team) {
        let prev = this.get(i);
        for (let j = i + 1; j <= i + 10 * this.sps; j++) {
            const f = this.get(j);
            if (!f || isCut(prev, f)) {
                return f ? { due: j, outcome: 'stopped', receiver: -1 } : null;
            }
            for (let m = 0; m < this.n; m++) {
                if (f.touches[m] && m !== k) {
                    return { due: j, outcome: this.players[m].team === team ? 'complete' : 'intercepted', receiver: m };
                }
            }
            const stops = (f.gameMode !== 0 && prev.gameMode === 0) || (f.foul.type > 0 && prev.foul.type === 0)
                || f.scoreLeft !== prev.scoreLeft || f.scoreRight !== prev.scoreRight;
            if (stops) {
                const b = ball(prev);
                const out = Math.abs(b[0]) > HALF_W || Math.abs(b[1]) > HALF_H || Math.abs(ball(f)[0]) > HALF_W || Math.abs(ball(f)[1]) > HALF_H;
                return { due: j, outcome: out ? 'out' : 'stopped', receiver: -1 };
            }
            prev = f;
        }
        return null;
    }

    // Whether a header at step i sends the ball towards the opponent goal from within 30 meters,
    // the rule of analyse in show.js.
    headedAtGoal(i, team) {
        const a = this.get(i);
        const m = this.get(i + 1);
        const b = this.get(i + 2);
        if (!a || !m || !b || isCut(a, m) || isCut(m, b)) {
            return false;
        }
        const goalX = attackX(team);
        const vx = (b.data[BALL_FLOAT] - a.data[BALL_FLOAT]) * this.sps / 2;
        return Math.sign(vx) === Math.sign(goalX) && Math.abs(vx) > 3 && Math.abs(goalX - a.data[BALL_FLOAT]) < 30;
    }

    // A header that is no shot clears the ball from the third before its own goal, else passes it.
    headerPurpose(touch, team) {
        const own = -attackX(team);
        const v = touch.data.velocityOut;
        const near = Math.abs(own - touch.data.contactPoint[0]) < 2 * HALF_W / 3;
        const away = v && Math.sign(v[0]) === Math.sign(-own);
        return near && away ? 'clearance' : 'pass';
    }

    // The shots of step i, an intentional touch with the Shot action, or with the Header action
    // when the ball then flies at the goal, the rule of analyse in show.js.
    findShots(i) {
        const f = this.get(i);
        const p = this.get(i - 1);
        if (!f) {
            return [];
        }
        const joined = p && !isCut(p, f);
        const list = [];
        for (let k = 0; k < this.n; k++) {
            const kind = f.touches[k];
            const action = f.actions[k];
            if (!intentional(kind) || (joined && p.touches[k] && p.actions[k] === action)) {
                continue;
            }
            const team = this.players[k].team;
            if (action === ACTION.shot || (action === ACTION.header && this.headedAtGoal(i, team))) {
                list.push(this.makeShot(i, k, team, action, this.touchEvent(i, k, f)));
            }
        }
        return list;
    }

    makeShot(i, k, team, action, touch) {
        const base = { player: k, team, t: touch.t, provenance: 'inferred' };
        const goalX = attackX(team);
        const cp = touch.data.contactPoint;
        const dx = Math.abs(goalX - cp[0]);
        const distance = Math.hypot(dx, cp[1]);
        const angle = Math.atan2(Math.abs(cp[1]), dx) * 180 / Math.PI;
        // The angle the goal mouth fills seen from the ball.
        const left = Math.atan2(POST_Y - cp[1], dx);
        const right = Math.atan2(-POST_Y - cp[1], dx);
        const mouth = Math.abs(left - right);
        const v = touch.data.velocityOut;
        const speed = v ? Math.hypot(v[0], v[1], v[2]) : 0;
        // A rough chance of scoring in the manner of expected goals, from the angle of the mouth
        // and the distance, lower for headers.
        let quality = 1 / (1 + Math.exp(-(-1.1 + 1.6 * mouth - 0.1 * distance)));
        if (action === ACTION.header) {
            quality *= 0.6;
        }
        const ev = this.event('shot', i, {
            ...base, rule: 'shot',
            data: {
                distance: round(distance, 2), angle: round(angle, 1), speed: round(speed, 2), height: cp[2],
                quality: round(quality, 3), header: action === ACTION.header, onTarget: null, outcome: 'pending',
                touch: touch.id,
            },
        });
        return { i, k, team, event: ev, follow: this.followShot(i, k, team) };
    }

    // Whether the ball, flying from a to b over one step, would cross the goal line at goalX between
    // the posts and under the bar within two seconds, the rule of show.js.
    headsInGoal(a, b, goalX, margin) {
        const sps = this.sps;
        const vx = (b.data[BALL_FLOAT] - a.data[BALL_FLOAT]) * sps;
        if (Math.sign(vx) !== Math.sign(goalX) || Math.abs(vx) < 1) {
            return false;
        }
        const t = (goalX - b.data[BALL_FLOAT]) / vx;
        if (t < 0 || t > 2) {
            return false;
        }
        const y = b.data[BALL_FLOAT + 1] + (b.data[BALL_FLOAT + 1] - a.data[BALL_FLOAT + 1]) * sps * t;
        const z = b.data[BALL_FLOAT + 2] + (b.data[BALL_FLOAT + 2] - a.data[BALL_FLOAT + 2]) * sps * t - 4.9 * t * t;
        return Math.abs(y) < POST_Y + margin && z < BAR_Z + margin;
    }

    // Follows a shot from step i, as followShot in show.js does, until the ball crosses the goal
    // line, another player touches it, play stops or four seconds pass. The outcome is goal,
    // saved, woodwork, blocked, redirected, wide, over, stopped or none, and due is the step that
    // settles it.
    followShot(i, k, team) {
        const goalX = attackX(team);
        const end = i + 4 * this.sps;
        const out = { onTarget: false, outcome: 'none', due: null, keeper: null, stopper: -1, woodwork: false };
        let prev = this.get(i);
        for (let j = i + 1; j <= end; j++) {
            const f = this.get(j);
            if (!f || isCut(prev, f)) {
                if (f) {
                    Object.assign(out, { outcome: out.woodwork ? 'woodwork' : 'stopped', due: j });
                }
                return out;
            }
            if (this.ringsAt(j)) {
                out.woodwork = true;
            }
            if (scoreOf(f, team) > scoreOf(prev, team)) {
                return Object.assign(out, { onTarget: true, outcome: 'goal', due: j });
            }
            const x0 = prev.data[BALL_FLOAT];
            const x1 = f.data[BALL_FLOAT];
            if (Math.abs(x1) >= HALF_W && Math.sign(x1) === Math.sign(goalX) && Math.abs(x0) < HALF_W) {
                const w = (Math.abs(goalX) - Math.abs(x0)) / Math.max(1e-6, Math.abs(x1 - x0));
                const y = prev.data[BALL_FLOAT + 1] + (f.data[BALL_FLOAT + 1] - prev.data[BALL_FLOAT + 1]) * w;
                const z = prev.data[BALL_FLOAT + 2] + (f.data[BALL_FLOAT + 2] - prev.data[BALL_FLOAT + 2]) * w;
                out.onTarget = Math.abs(y) < POST_Y && z < BAR_Z;
                // A ball over the line between the posts goes in a step or two later.
                for (let g = j; g <= j + 3; g++) {
                    const gf = this.get(g);
                    if (gf && scoreOf(gf, team) > scoreOf(prev, team)) {
                        return Object.assign(out, { onTarget: true, outcome: 'goal', due: g });
                    }
                }
                const missed = Math.abs(y) >= POST_Y ? 'wide' : 'over';
                return Object.assign(out, { outcome: out.woodwork ? 'woodwork' : missed, due: j });
            }
            for (let m = 0; m < this.n; m++) {
                if (!f.touches[m] || (m === k && prev.touches[m] && prev.actions[m] === f.actions[m])) {
                    continue;
                }
                const pl = this.players[m];
                if (pl.goalkeeper && pl.team !== team) {
                    const a = this.get(Math.max(i, j - 2));
                    const b = j - 1 > i ? prev : f;
                    out.onTarget = this.headsInGoal(a, b, goalX, 0.5);
                    out.keeper = { i: j, k: m, action: f.actions[m], heading: out.onTarget };
                    const after = this.afterKeeper(j, m, team);
                    if (after.goal >= 0) {
                        return Object.assign(out, { onTarget: true, outcome: 'goal', due: after.goal });
                    }
                    const saved = out.onTarget && j - i <= 2 * this.sps && SAVES.has(f.actions[m]);
                    return Object.assign(out, { outcome: saved ? 'saved' : (out.woodwork ? 'woodwork' : 'keeper'), due: saved ? after.due : j, stopper: m });
                }
                const blocked = pl.team !== team ? 'blocked' : 'redirected';
                return Object.assign(out, { outcome: out.woodwork ? 'woodwork' : blocked, due: j, stopper: m });
            }
            if (f.gameMode !== 0 && prev.gameMode === 0) {
                return Object.assign(out, { outcome: out.woodwork ? 'woodwork' : 'stopped', due: j });
            }
            prev = f;
        }
        if (this.get(end)) {
            Object.assign(out, { outcome: out.woodwork ? 'woodwork' : 'none', due: end });
        }
        return out;
    }

    // What follows a keeper's touch at step i, the step of a goal by the shooting team before
    // anyone else touches the ball within three seconds, or -1, and the step that settles it.
    afterKeeper(i, keeper, team) {
        const before = scoreOf(this.get(i - 1) || this.get(i), team);
        let prev = this.get(i);
        const end = i + 3 * this.sps;
        for (let j = i + 1; j <= end; j++) {
            const f = this.get(j);
            if (!f || isCut(prev, f)) {
                return { goal: -1, due: f ? j : i };
            }
            if (scoreOf(f, team) > before) {
                return { goal: j, due: j };
            }
            for (let m = 0; m < this.n; m++) {
                if (f.touches[m] && m !== keeper) {
                    return { goal: -1, due: j };
                }
            }
            prev = f;
        }
        return { goal: -1, due: end };
    }

    // The touches of step i that stop a shot of an earlier step, a save by the defending keeper
    // or a block by a defending outfield player.
    inferStop(i, touch, entry) {
        const k = touch.player;
        for (let s = i - 1; s >= Math.max(this.store.first, i - 4 * this.sps); s--) {
            for (const shot of this.shotsAt(s)) {
                const follow = shot.follow;
                if (follow.keeper && follow.keeper.i === i && follow.keeper.k === k) {
                    if (follow.keeper.heading && SAVES.has(follow.keeper.action) && i - s <= 2 * this.sps) {
                        entry.inferred.push(this.saveEvent(i, k, shot, touch, entry));
                    }
                    return;
                }
                if (follow.stopper === k && follow.outcome === 'blocked' && follow.due === i) {
                    entry.inferred.push(this.event('block', i, {
                        player: k, team: this.players[k].team, t: touch.t, provenance: 'inferred', rule: 'block',
                        subjects: [k, shot.k], data: { shot: shot.event.id, shooter: shot.k, touch: touch.id },
                    }));
                    return;
                }
            }
        }
    }

    // A save, the defending keeper's touch of a shot heading in within two seconds. The touch is
    // a contact and is forecast, so whether the ball stays out follows as a resolve.
    saveEvent(i, k, shot, touch, entry) {
        const f = this.get(i);
        const before = this.get(shot.i) || f;
        const team = this.players[k].team;
        const from = root(before, k);
        const cp = touch.data.contactPoint;
        const dive = cp[1] - from[1];
        // The keeper faces the way his team attacks, and his left is plus y when that is plus x.
        const facing = team === 0 ? 1 : -1;
        const ev = this.event('save', i, {
            player: k, team, t: touch.t, provenance: 'inferred', rule: 'save', subjects: [k, shot.k],
            data: {
                style: CATCHES.has(f.actions[k]) ? 'catch' : 'parry', dive: round(Math.abs(dive), 2),
                side: Math.abs(dive) < 0.3 ? 'centre' : (dive * facing > 0 ? 'left' : 'right'),
                shot: shot.event.id, shooter: shot.k, saved: 'pending', touch: touch.id,
            },
        });
        const after = this.afterKeeper(i, k, shot.team);
        entry.later.push(this.resolve(ev, after.due, { saved: after.goal < 0 }));
        return ev;
    }

    // A slide that player k begins at step i. Whether it wins the ball follows as a resolve, by
    // the rule of wonBall in show.js from the slide's first touch of the ball.
    inferSlide(i, k, entry) {
        const team = this.players[k].team;
        const ev = this.event('slide', i, { player: k, team, provenance: 'inferred', rule: 'slide', data: { won: 'pending' } });
        entry.inferred.push(ev);
        let prev = this.get(i);
        let touched = -1;
        let ended = -1;
        for (let j = i; j <= i + 3 * this.sps; j++) {
            const f = this.get(j);
            if (!f || (j > i && isCut(prev, f))) {
                ended = f ? j : -1;
                break;
            }
            if (f.touches[k]) {
                touched = j;
                break;
            }
            if (f.actions[k] !== ACTION.sliding) {
                ended = j;
                break;
            }
            prev = f;
        }
        if (touched < 0) {
            if (ended >= 0) {
                entry.later.push(this.resolve(ev, ended, { won: false, touched: false }));
            }
            return;
        }
        prev = this.get(touched);
        for (let j = touched; j <= touched + 3 * this.sps; j++) {
            const f = this.get(j);
            if (!f) {
                return;
            }
            if (j > touched && isCut(prev, f)) {
                entry.later.push(this.resolve(ev, j, { won: false, touched: true }));
                return;
            }
            let won = null;
            if (j > touched && f.ownedTeam >= 0) {
                won = f.ownedTeam === team;
            } else if (j > touched) {
                for (let m = 0; m < this.n && won == null; m++) {
                    if (f.touches[m] && m !== k) {
                        won = this.players[m].team === team;
                    }
                }
            }
            if (won != null) {
                entry.later.push(this.resolve(ev, j, { won, touched: true }));
                return;
            }
            prev = f;
        }
        entry.later.push(this.resolve(ev, touched + 3 * this.sps, { won: false, touched: true }));
    }

    // The horizontal speed of player k's root over the step into i, zero across a cut and for a
    // move faster than a run, which is a restart's teleport.
    speedAt(i, k) {
        const item = this.speeds.get(i);
        if (this.hit(item)) {
            return item.list[k];
        }
        return this.cached(this.speeds, i, (j) => {
            const list = new Float32Array(this.n);
            const a = this.get(j - 1);
            const b = this.get(j);
            if (a && b && !isCut(a, b)) {
                for (let m = 0; m < this.n; m++) {
                    const o = NODES_FLOAT + m * PLAYER_FLOATS;
                    const v = (b.playerFlags[m] & 1) ? Math.hypot(b.data[o] - a.data[o], b.data[o + 1] - a.data[o + 1]) * this.sps : 0;
                    list[m] = v > RUN_LIMIT ? 0 : v;
                }
            }
            return { list };
        }).list[k];
    }

    // A sprint is a run of at least half a second with the root faster than 6.5 meters per second.
    // It begins on the first step of the run and ends on the first step after it.
    inferSprints(i, entry) {
        for (let k = 0; k < this.n; k++) {
            const team = this.players[k].team;
            const here = this.speedAt(i, k);
            const before = this.speedAt(i - 1, k);
            if (here > SPRINT_SPEED && before <= SPRINT_SPEED) {
                let run = true;
                for (let j = i + 1; j < i + SPRINT_STEPS && run; j++) {
                    run = this.speedAt(j, k) > SPRINT_SPEED;
                }
                if (run) {
                    entry.inferred.push(this.event('sprint.begin', i, {
                        player: k, team, provenance: 'inferred', rule: 'sprint', data: { speed: round(here, 2) },
                    }));
                }
            } else if (here <= SPRINT_SPEED && before > SPRINT_SPEED) {
                let run = true;
                for (let j = i - 2; j >= i - SPRINT_STEPS && run; j--) {
                    run = this.speedAt(j, k) > SPRINT_SPEED;
                }
                if (run) {
                    entry.inferred.push(this.event('sprint.end', i, {
                        player: k, team, provenance: 'inferred', rule: 'sprint', data: { speed: round(here, 2) },
                    }));
                }
            }
        }
    }

    // A dribble is a run of at least three touches by one player, none by anyone else, each within
    // a second and a half of the last, in open play, that carries the ball at least five meters.
    // It begins at its first touch and ends at its last, which this step defers to.
    inferDribble(i, f, entry) {
        const gap = Math.round(1.5 * this.sps);
        for (let k = 0; k < this.n; k++) {
            if (!f.touches[k] || f.gameMode !== 0) {
                continue;
            }
            // Only the first touch of a run starts one, so a touch by the same player shortly
            // before, with nobody else in between, rules this step out.
            let continues = false;
            let prev = f;
            for (let j = i - 1; j >= i - gap; j--) {
                const g = this.get(j);
                if (!g || isCut(g, prev) || g.gameMode !== 0) {
                    break;
                }
                let other = false;
                for (let m = 0; m < this.n; m++) {
                    if (g.touches[m]) {
                        if (m === k) {
                            continues = true;
                        } else {
                            other = true;
                        }
                    }
                }
                if (continues || other) {
                    break;
                }
                prev = g;
            }
            if (continues) {
                continue;
            }
            const run = [i];
            prev = f;
            let quiet = 0;
            for (let j = i + 1; j <= i + BACK_SECONDS * this.sps; j++) {
                const g = this.get(j);
                if (!g || isCut(prev, g) || g.gameMode !== 0) {
                    break;
                }
                let other = false;
                for (let m = 0; m < this.n; m++) {
                    if (g.touches[m] && m !== k) {
                        other = true;
                    }
                }
                if (other) {
                    break;
                }
                if (g.touches[k]) {
                    // A touch held over several steps counts once.
                    if (!prev.touches[k]) {
                        run.push(j);
                    }
                    quiet = 0;
                } else if (++quiet > gap) {
                    break;
                }
                prev = g;
            }
            if (run.length < 3) {
                continue;
            }
            const last = run[run.length - 1];
            const b0 = ball(f);
            const b1 = ball(this.get(last));
            const distance = Math.hypot(b1[0] - b0[0], b1[1] - b0[1]);
            if (distance < 5) {
                continue;
            }
            const team = this.players[k].team;
            const beaten = this.beaten(i, last, k, team);
            const data = { touches: run.length, distance: round(distance, 2), beaten, endStep: last };
            const begin = this.event('dribble.begin', i, { player: k, team, provenance: 'inferred', rule: 'dribble', data });
            entry.inferred.push(begin);
            entry.later.push({
                due: last,
                event: this.event('dribble.end', last, {
                    player: k, team, provenance: 'inferred', rule: 'dribble', data: { ...data, beginStep: i, begin: begin.id },
                }),
            });
        }
    }

    // Opponents a dribbler passes within two meters, ahead of him along his attack at some step of
    // the dribble and behind him at its end.
    beaten(from, to, k, team) {
        const sign = team === 0 ? 1 : -1;
        const end = this.get(to);
        const me = root(end, k);
        const out = [];
        for (let m = 0; m < this.n; m++) {
            if (this.players[m].team === team || !(end.playerFlags[m] & 1)) {
                continue;
            }
            const them = root(end, m);
            if ((them[0] - me[0]) * sign >= 0) {
                continue;
            }
            for (let j = from; j <= to; j++) {
                const g = this.get(j);
                const a = root(g, k);
                const b = root(g, m);
                if (Math.hypot(b[0] - a[0], b[1] - a[1]) < 2 && (b[0] - a[0]) * sign > 0) {
                    out.push(m);
                    break;
                }
            }
        }
        return out;
    }

    // Whether the ball rings off the frame of a goal at the sample of step i, a sharp change of
    // its horizontal velocity near a post or the bar with no player touching it, the rule of
    // detectKick in main.js.
    ringsAt(i) {
        const a = this.get(i - 1);
        const b = this.get(i);
        const c = this.get(i + 1);
        if (!a || !b || !c || isCut(a, b) || isCut(b, c)) {
            return false;
        }
        for (let m = 0; m < this.n; m++) {
            if (b.touches[m] || c.touches[m]) {
                return false;
            }
        }
        const sps = this.sps;
        const v1x = (b.data[BALL_FLOAT] - a.data[BALL_FLOAT]) * sps;
        const v1y = (b.data[BALL_FLOAT + 1] - a.data[BALL_FLOAT + 1]) * sps;
        const v2x = (c.data[BALL_FLOAT] - b.data[BALL_FLOAT]) * sps;
        const v2y = (c.data[BALL_FLOAT + 1] - b.data[BALL_FLOAT + 1]) * sps;
        const jump = Math.hypot(v2x - v1x, v2y - v1y);
        const bx = Math.abs(b.data[BALL_FLOAT]);
        const by = Math.abs(b.data[BALL_FLOAT + 1]);
        const bz = b.data[BALL_FLOAT + 2];
        const nearPost = Math.abs(bx - HALF_W) < 0.6 && bz < 2.7 && (Math.abs(by - 3.7) < 0.6 || (by < 3.9 && bz > 2.1));
        return jump > 4.5 && nearPost;
    }

    // The last player to touch the ball before step i within four seconds, or -1.
    lastToucher(i) {
        for (let j = i; j >= Math.max(this.store.first, i - 4 * this.sps); j--) {
            const f = this.get(j);
            if (!f) {
                break;
            }
            for (let m = 0; m < this.n; m++) {
                if (f.touches[m]) {
                    return m;
                }
            }
        }
        return -1;
    }

    inferWoodwork(i, f, entry) {
        const b = ball(f);
        const side = Math.sign(b[0]) || 1;
        const by = Math.abs(b[1]);
        // Seen by the side that attacks this goal, which faces plus x when side is plus.
        const part = by < 3.9 && b[2] > 2.1 ? 'bar' : (b[1] * side > 0 ? 'leftPost' : 'rightPost');
        const shooter = this.lastToucher(i);
        const team = shooter >= 0 ? this.players[shooter].team : (side > 0 ? 0 : 1);
        entry.inferred.push(this.event('woodwork', i, {
            key: [`side${side}`], player: shooter, team, provenance: 'inferred', rule: 'woodwork',
            data: { part, goalSide: side, shooter, point: b.map((x) => round(x, 3)) },
        }));
    }

    // A ball crossing the goal line just wide of a post or just over the bar, the rule of nearMiss
    // in main.js, with the margin by which it missed.
    inferNearMiss(i, a, b, entry) {
        const ax = Math.abs(a.data[BALL_FLOAT]);
        const bx = Math.abs(b.data[BALL_FLOAT]);
        const speed = Math.abs(b.data[BALL_FLOAT] - a.data[BALL_FLOAT]) * this.sps;
        if (ax > HALF_W || bx <= HALF_W || speed < 8 || speed > 60 || Math.sign(a.data[BALL_FLOAT]) !== Math.sign(b.data[BALL_FLOAT])) {
            return;
        }
        const w = (HALF_W - ax) / Math.max(1e-6, bx - ax);
        const y = Math.abs(a.data[BALL_FLOAT + 1] + (b.data[BALL_FLOAT + 1] - a.data[BALL_FLOAT + 1]) * w);
        const z = a.data[BALL_FLOAT + 2] + (b.data[BALL_FLOAT + 2] - a.data[BALL_FLOAT + 2]) * w;
        const wide = y > 3.9 && y < 7 && z < 3.5;
        const over = y <= 3.9 && z > 2.6 && z < 4.5;
        if (!wide && !over) {
            return;
        }
        const side = Math.sign(b.data[BALL_FLOAT]);
        const shooter = this.lastToucher(i);
        const team = shooter >= 0 ? this.players[shooter].team : (side > 0 ? 0 : 1);
        entry.inferred.push(this.event('nearMiss', i, {
            key: [`side${side}`], player: shooter, team, provenance: 'inferred', rule: 'nearMiss',
            data: {
                line: wide ? 'wide' : 'over', margin: round(wide ? y - POST_Y : z - BAR_Z, 2), goalSide: side, shooter,
            },
        }));
    }

    // The touches that start a run of the same player and action, as touchEvents in show.js lists
    // them, between steps from and to.
    touchStarts(from, to) {
        const list = [];
        let prev = null;
        for (let i = from; i <= to; i++) {
            const f = this.get(i);
            if (!f) {
                prev = null;
                continue;
            }
            const joined = prev && !isCut(prev, f);
            for (let k = 0; k < this.n; k++) {
                const touch = f.touches[k];
                if (!touch || (joined && prev.touches[k] && prev.actions[k] === f.actions[k])) {
                    continue;
                }
                list.push({ i, k, team: this.players[k].team, action: f.actions[k], touch });
            }
            prev = f;
        }
        return list;
    }

    // The enriched goal of step i, a resolve of the frame's goal with the scorer, the assist and
    // the manner of the goal, by the rule of attribute in show.js. The scorer the engine names
    // wins when the recording carries it.
    enrichGoal(i, goal) {
        const team = goal.team;
        const sps = this.sps;
        const from = Math.max(this.store.first, i - 20 * sps);
        const events = this.touchStarts(from, i);
        let scorer = -1;
        let at = -1;
        for (let s = i - 1; s >= Math.max(this.store.first, i - 8 * sps) && at < 0; s--) {
            for (const shot of this.shotsAt(s)) {
                if (shot.follow.outcome === 'goal' && shot.follow.due === i) {
                    scorer = shot.k;
                    at = events.findIndex((e) => e.i === shot.i && e.k === shot.k);
                }
            }
        }
        if (scorer < 0) {
            let last = events.length - 1;
            while (last >= 0 && events[last].touch === TOUCH.accidental) {
                last--;
            }
            if (last >= 0 && events[last].i >= i - 15 * sps) {
                at = last;
                for (let e = last; e >= 0 && events[e].i === events[last].i; e--) {
                    if (events[e].team === team && events[e].touch !== TOUCH.accidental) {
                        at = e;
                        break;
                    }
                }
                scorer = events[at].k;
            }
        }
        if (scorer < 0) {
            for (let j = i - 1; j >= from; j--) {
                const f = this.get(j);
                if (f && f.ownedPlayer >= 0 && f.ownedPlayer < this.n) {
                    scorer = f.ownedPlayer;
                    break;
                }
            }
        }
        const certain = goal.data.scorer != null;
        if (certain) {
            scorer = goal.data.scorer;
            at = events.findLastIndex((e) => e.k === scorer);
        }
        const ownGoal = scorer >= 0 && this.players[scorer].team !== team;
        let assist = -1;
        let passes = 0;
        let solo = false;
        if (scorer >= 0 && !ownGoal && at >= 0) {
            const t0 = events[at].i;
            for (let e = at - 1; e >= 0 && events[e].i >= t0 - 10 * sps; e--) {
                const ev = events[e];
                if (ev.k === scorer) {
                    continue;
                }
                if (ev.team !== team) {
                    if (ev.touch === TOUCH.accidental) {
                        continue;
                    }
                    break;
                }
                assist = ev.k;
                break;
            }
            for (let e = at - 1; e >= 0; e--) {
                const ev = events[e];
                if (ev.team !== team && ev.touch !== TOUCH.accidental) {
                    break;
                }
                if (ev.team === team && intentional(ev.touch) && PASSES.has(ev.action)) {
                    passes++;
                }
            }
            let own = 0;
            for (let e = at - 1; e >= 0 && events[e].k === scorer && events[e].i >= t0 - BACK_SECONDS * sps; e--) {
                own++;
            }
            solo = own >= 2;
        }
        const data = { scorer, assist, ownGoal, certain, passes, solo };
        if (at >= 0) {
            const e = events[at];
            const touch = this.touchEvent(e.i, e.k, this.get(e.i));
            const cp = touch.data.contactPoint;
            const v = touch.data.velocityOut;
            const vin = touch.data.velocityIn;
            const distance = Math.hypot(attackX(team) - cp[0], cp[1]);
            const speed = v ? Math.hypot(v[0], v[1], v[2]) : 0;
            let lastAction = ACTION_NAMES[e.action];
            if (e.action === ACTION.header) {
                lastAction = 'header';
            } else if (e.touch === TOUCH.kicked && cp[2] > 0.3 && vin && vin[2] < 0) {
                lastAction = 'volley';
            } else if (e.action === ACTION.shot) {
                lastAction = 'shot';
            }
            Object.assign(data, {
                lastAction, distance: round(distance, 2), speed: round(speed, 2), screamer: speed >= 25 && distance >= 20,
                touchStep: e.i,
            });
        }
        const extra = { provenance: 'inferred', inference: `goal/${RULES.goal}` };
        if (scorer >= 0) {
            extra.player = scorer;
            extra.subjects = assist >= 0 ? [scorer, assist] : [scorer];
        }
        return this.resolve(goal, i, data, extra);
    }
}

const analyses = new WeakMap();

function analysisOf(store) {
    let a = analyses.get(store);
    if (!a) {
        a = new Analysis(store);
        analyses.set(store, a);
    }
    return a;
}

// Every authoritative event of step i, read from frame fields, with provenance frame and phase
// occur, section 4.1.
export function frameEvents(store, i) {
    return analysisOf(store).at(i).frame.slice();
}

// Every inferred event of step i by the version 1 rules of section 4.2, followed by the resolves
// and deferred ends that earlier steps settle at step i. A resolve keeps the step and t of the
// event it refines and names the step that settles it in data.resolvedStep.
export function inferredEvents(store, i) {
    const a = analysisOf(store);
    return a.at(i).inferred.concat(a.dueAt(i));
}

// Events of step i in the order the catalog sends them, frame events, then inferred ones, then
// resolves.
export function stepEvents(store, i) {
    return analysisOf(store).eventsAt(i).slice();
}

// How far from its step the t of an event can lie, up to two steps before it for a restart taken
// by a touch in the step before the game mode returns to play, and up to three steps after it for
// a restart taken late.
const BEFORE_STEPS = 2;
const AFTER_STEPS = 3;

// When a resolve is sent, the time of the step that settles it.
const sendTime = (ev) => (ev.phase === 'resolve' ? ev.data.resolvedT : ev.t);

// The catalog of one store for one viewer. Each drawing passes the drawn time, and update
// returns the events that drawing brings, forecasts within the horizons, occurs as forward play
// crosses them, and cancels when play turns back, speeds up or jumps. Steps are analysed once and
// cached, and forecasts scan each step once per epoch as the horizon reaches it.
export class Catalog {
    constructor(store, options = {}) {
        this.store = store;
        this.analysis = analysisOf(store);
        this.sps = stepsPerSecond(store);
        this.fullLookahead = !!options.fullLookahead;
        this.live = !!options.live;
        this.epoch = 0;
        this.last = null;
        this.mode = null;
        this.resetReason = null;
        this.pending = new Map();
        this.sent = new Set();
        this.frontier = null;
        this.queue = [];
    }

    // The events of step i, frame events, inferred events and resolves, frozen and shared.
    eventsAt(i) {
        if (i < this.store.first || i > this.store.last) {
            return [];
        }
        return this.analysis.eventsAt(i);
    }

    newEpoch() {
        this.epoch += 1;
        this.pending.clear();
        this.sent.clear();
        this.frontier = null;
        this.queue = [];
    }

    // Cancels of the forecasts that have not occurred, at drawn time now in seconds.
    cancelPending(now) {
        const out = [];
        for (const ev of this.pending.values()) {
            out.push({ ...ev, phase: 'cancel', lead: ev.t - now });
        }
        this.pending.clear();
        return out;
    }

    // Starts a new epoch for a reason, a seek, a cut, a source switch, and returns the cancels of
    // the forecasts still pending. The next drawing starts afresh, and window gives the events a
    // resync needs.
    reset(reason = 'seek') {
        const now = this.last == null ? 0 : this.last / this.sps;
        const out = this.cancelPending(now);
        this.newEpoch();
        this.last = null;
        this.resetReason = reason;
        return out;
    }

    // The horizon of contact forecasts in seconds, shorter on a live source by what is buffered.
    contactHorizon(t, ahead) {
        if (!this.live) {
            return CONTACT_HORIZON;
        }
        const buffered = ahead == null ? Math.max(0, (this.store.last - t) / this.sps) : ahead;
        return Math.max(0, Math.min(CONTACT_HORIZON, buffered - 0.2));
    }

    // The events of one drawing at timeline index t. Forward play at a speed up to 2.5 forecasts
    // and crosses events. Entering reverse or a faster speed cancels the forecasts not yet
    // occurred and sends nothing more until forward play returns in a new epoch. A jump further
    // than play covers in one drawing of dt seconds is a seek, which cancels, starts a new epoch
    // and resyncs with the events of window.
    update({ t, playing = true, direction = 1, speed = 1, ahead = null, dt = 0 } = {}) {
        const sps = this.sps;
        const now = t / sps;
        const out = [];
        const mode = direction < 0 ? 'reverse' : (speed > 2.5 ? 'fast' : 'forward');
        if (this.mode != null && mode !== this.mode) {
            if (this.mode === 'forward') {
                out.push(...this.cancelPending(now));
            }
            this.newEpoch();
            this.last = null;
            this.resetReason = mode === 'forward' ? 'resume' : (mode === 'reverse' ? 'reverse' : 'speed');
        }
        this.mode = mode;
        if (mode !== 'forward') {
            this.last = t;
            return out;
        }
        const prev = this.last;
        this.last = t;
        if (prev != null) {
            const steps = t - prev;
            const leap = Math.max(6, Math.ceil(dt * speed * sps) + 2);
            if (steps < 0 || steps > leap) {
                out.push(...this.cancelPending(now));
                this.newEpoch();
                this.resetReason = 'seek';
                for (const ev of this.window(t)) {
                    this.sent.add(`${ev.phase}:${ev.id}`);
                    out.push(ev);
                }
            } else if (steps > 0 && playing !== false) {
                out.push(...this.cross(prev / sps, now));
            } else if (steps > 0) {
                // Frames stepped while paused pass their events silently, so their forecasts are
                // no longer pending.
                for (const [id, ev] of this.pending) {
                    if (ev.t <= now) {
                        this.pending.delete(id);
                        this.sent.add(`occur:${id}`);
                    }
                }
            }
        }
        out.push(...this.forecast(t, now, ahead));
        return out;
    }

    // The occurs of the events whose t forward play passed, from just after then to now, and the
    // resolves settled in that time, in the order of their times.
    cross(then, now) {
        const sps = this.sps;
        const list = [];
        const from = Math.max(this.store.first, Math.floor(then * sps) - AFTER_STEPS);
        const to = Math.min(this.store.last, Math.floor(now * sps) + BEFORE_STEPS);
        for (let s = from; s <= to; s++) {
            for (const ev of this.eventsAt(s)) {
                const at = sendTime(ev);
                if (at > then && at <= now) {
                    list.push(ev);
                }
            }
        }
        list.sort((a, b) => sendTime(a) - sendTime(b));
        const out = [];
        for (const ev of list) {
            const key = `${ev.phase}:${ev.id}`;
            if (this.sent.has(key)) {
                continue;
            }
            this.sent.add(key);
            this.pending.delete(ev.id);
            out.push({ ...ev, lead: ev.t - now });
        }
        return out;
    }

    // Forecasts of contacts within the contact horizon and of outcomes within the outcome horizon,
    // or the contact horizon with full look ahead, each once per epoch. Resolves count as outcomes
    // and are sent once their settling step is that close. Each step is scanned once per epoch,
    // and what it holds for later waits in a short queue until its horizon reaches it.
    forecast(t, now, ahead) {
        const sps = this.sps;
        const contact = this.contactHorizon(t, ahead);
        const outcome = this.fullLookahead ? contact : Math.min(OUTCOME_HORIZON, contact);
        const to = Math.min(this.store.last, Math.floor((now + contact) * sps) + BEFORE_STEPS);
        let s = this.frontier == null ? Math.max(this.store.first, Math.floor(t) - AFTER_STEPS) : this.frontier + 1;
        for (; s <= to; s++) {
            for (const ev of this.eventsAt(s)) {
                if (ev.phase === 'resolve' || CONTACT.has(ev.kind) || OUTCOME.has(ev.kind)) {
                    this.queue.push(ev);
                }
            }
            this.frontier = s;
        }
        if (!this.queue.length) {
            return [];
        }
        const out = [];
        const keep = [];
        for (const ev of this.queue) {
            const resolve = ev.phase === 'resolve';
            const lead = sendTime(ev) - now;
            const key = `${resolve ? 'resolve' : 'forecast'}:${ev.id}`;
            if (lead <= 0 || this.sent.has(key) || this.sent.has(`occur:${ev.id}`)) {
                continue;
            }
            const reach = resolve || !CONTACT.has(ev.kind) ? outcome : contact;
            if (lead > reach) {
                keep.push(ev);
                continue;
            }
            this.sent.add(key);
            if (resolve) {
                out.push({ ...ev, lead: ev.t - now });
            } else {
                const forecast = { ...ev, phase: 'forecast', lead };
                this.pending.set(ev.id, forecast);
                out.push(forecast);
            }
        }
        this.queue = keep;
        out.sort((a, b) => a.t - b.t);
        return out;
    }

    // The occur events whose t lies in the span seconds up to timeline index t, with their
    // negative leads, followed by the resolves of them settled by then, for the resync after a
    // seek of section 5.4. It changes nothing in the catalog.
    window(t, span = 3) {
        const sps = this.sps;
        const now = t / sps;
        const from = Math.max(this.store.first, Math.floor((now - span) * sps) - AFTER_STEPS);
        const to = Math.min(this.store.last, Math.floor(t) + BEFORE_STEPS);
        const occurs = [];
        const resolves = [];
        for (let s = from; s <= to; s++) {
            for (const ev of this.eventsAt(s)) {
                if (ev.t < now - span || ev.t > now) {
                    continue;
                }
                if (ev.phase !== 'resolve') {
                    occurs.push({ ...ev, lead: ev.t - now });
                } else if (ev.data.resolvedT <= now) {
                    resolves.push({ ...ev, lead: ev.t - now });
                }
            }
        }
        occurs.sort((a, b) => a.t - b.t);
        return occurs.concat(resolves);
    }
}
