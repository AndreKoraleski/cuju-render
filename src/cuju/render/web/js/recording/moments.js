// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The moments of a match, the events that a search finds and captions read, taken from the event
// catalog of the team presentation contract. A moment is one event of the catalog of a kind
// worth finding, with the data of its last resolve merged in, so a shot knows how it ended and a
// goal knows its scorer and assist. The server's index of the library, src/cuju/render/
// _events.py, builds the same moments from the same rules, with the same ids, steps and times,
// and a test holds the two to each other on the shipped samples.
//
// The module reads frames only, so it runs in the page, in a worker and under Node alike.

import { isCut } from './format.js';
import { stepEvents } from '../presentation/catalog.js';

// The version of the moments. The server's index rebuilds every recording when it changes.
export const MOMENTS_VERSION = 1;

// The kinds of moments, in the order a step lists them.
export const MOMENT_KINDS = Object.freeze([
    'goal', 'shot', 'save', 'block', 'woodwork', 'nearMiss', 'pass', 'tackle', 'foul', 'card',
    'offside', 'restart', 'possession', 'halftime', 'fulltime',
]);

// The catalog kind each moment comes from, where the names differ.
const FROM_CATALOG = { slide: 'tackle', 'restart.begin': 'restart' };

// The fields of the data that each kind keeps, in this order, the rest of the catalog's data
// being for presentation packages.
export const MOMENT_DATA = Object.freeze({
    goal: ['scoringTeam', 'score', 'scorer', 'assist', 'ownGoal', 'certain', 'passes', 'solo', 'lastAction', 'distance'],
    shot: ['distance', 'angle', 'quality', 'header', 'onTarget', 'outcome', 'keeper', 'stopper'],
    save: ['style', 'side', 'shooter', 'saved'],
    block: ['shooter'],
    woodwork: ['part', 'goalSide', 'shooter'],
    nearMiss: ['line', 'margin', 'goalSide', 'shooter'],
    pass: ['type', 'outcome', 'receiver'],
    tackle: ['won', 'touched'],
    foul: ['offender', 'victim', 'type'],
    card: ['colour', 'second'],
    offside: [],
    restart: ['restart', 'taker'],
    possession: ['from', 'to', 'fromTeam', 'toTeam'],
    halftime: ['score'],
    fulltime: ['winner', 'draw', 'score'],
});

// Steps after the last step of a range that a scan reads for the resolves of its events, the
// longest being a pass followed for ten seconds and a save settled three seconds after a shot of
// four seconds.
const RESOLVE_STEPS = 150;

function pick(kind, data) {
    const out = {};
    for (const key of MOMENT_DATA[kind]) {
        if (data[key] !== undefined) {
            out[key] = data[key];
        }
    }
    return out;
}

// The team that last owned the ball before step i, walking back within the same episode while
// the frames join, and its player, or nulls.
function lastOwner(store, i) {
    let next = store.get(i);
    for (let j = i - 1; j >= store.first; j--) {
        const f = store.get(j);
        if (!f || isCut(f, next)) {
            return null;
        }
        if (f.ownedTeam >= 0) {
            return { team: f.ownedTeam, player: f.ownedPlayer };
        }
        next = f;
    }
    return null;
}

// The moment of a catalog event, or null for an event that makes none. A possession event makes
// one only when the ball goes to the other team from the team that last owned it, so a loose
// ball that its owners win back is no change.
function momentOf(store, ev) {
    if (ev.phase !== 'occur') {
        return null;
    }
    const kind = FROM_CATALOG[ev.kind] || ev.kind;
    if (!MOMENT_DATA[kind]) {
        return null;
    }
    let data = ev.data;
    if (kind === 'possession') {
        if (!(data.toTeam >= 0) || data.fromTeam === data.toTeam) {
            return null;
        }
        const before = data.fromTeam >= 0 ? { team: data.fromTeam, player: data.from } : lastOwner(store, ev.step);
        if (!before || before.team === data.toTeam) {
            return null;
        }
        data = { from: before.player, to: data.to, fromTeam: before.team, toTeam: data.toTeam };
    }
    const moment = { id: ev.id, kind, step: ev.step, t: ev.t };
    if (ev.team != null) {
        moment.team = ev.team;
    }
    if (ev.player != null) {
        moment.player = ev.player;
    }
    moment.data = pick(kind, data);
    return moment;
}

// The moments whose events occur at the steps from to to of a store, in the order of their steps
// and of the catalog within a step, each with the data of the last resolve of its event that the
// store settles.
export function momentsOf(store, from = store.first, to = store.last) {
    const first = Math.max(store.first, from);
    const last = Math.min(store.last, to);
    const out = [];
    const byId = new Map();
    for (let i = first; i <= last; i++) {
        for (const ev of stepEvents(store, i)) {
            const moment = momentOf(store, ev);
            if (moment) {
                out.push(moment);
                byId.set(moment.id, moment);
            }
        }
    }
    const end = Math.min(store.last, last + RESOLVE_STEPS);
    for (let i = first; i <= end; i++) {
        for (const ev of stepEvents(store, i)) {
            if (ev.phase !== 'resolve') {
                continue;
            }
            const moment = byId.get(ev.id);
            if (!moment) {
                continue;
            }
            const resolved = pick(moment.kind, ev.data);
            Object.assign(moment.data, resolved);
            // The enriched goal names the scorer it found.
            if (ev.player != null) {
                moment.player = ev.player;
            }
        }
    }
    return out;
}
