// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The messages between the renderer and a team's worker, section 11 of the contract.
//
// The renderer sends a Hello once, then a Frame on every drawing while no reply is outstanding,
// with the state of the drawings in between coalesced and their events accumulated, never
// dropped. The worker answers each Frame with a Response that names the Frame's instance, epoch
// and frame id. A reply of another instance or an older epoch is dropped, and every command in a
// reply is checked and held to its ranges before it takes effect.

import { checkBehaviour } from './behaviors.js';
import {
    checkAudio, checkCamera, checkClaim, checkEffect, checkOverlay, checkResource, checkTime,
} from './commands.js';
import { CONTRACT } from './contract.js';
import { checkTrack } from './tracks.js';
import { clamp } from './values.js';

// The most commands of each kind one reply may carry, and the largest reply in characters.
export const MAXIMUM_COMMANDS = 64;
export const MAXIMUM_REPLY = 512 * 1024;
// The lines of a worker's log that the page keeps, the newest last.
export const LOG_LINES = 50;

// The log of a worker with the lines of a new reply added, the oldest dropped past max.
export function appendLog(log, lines, max = LOG_LINES) {
    const out = (log || []).concat(lines || []);
    return out.length > max ? out.slice(out.length - max) : out;
}

const round = (x) => Math.round(x * 1e4) / 1e4;
const roundAll = (v) => (Array.isArray(v) ? v.map(round) : v);

// The Hello of an instance, section 11.2.
export function helloMessage(h) {
    return {
        type: 'hello',
        contract: CONTRACT,
        features: h.features,
        lacking: h.lacking || [],
        limits: h.limits,
        quality: h.quality,
        reducedMotion: !!h.reducedMotion,
        instanceId: h.instanceId,
        team: h.team,
        attack: h.attack,
        roster: h.roster,
        header: h.header,
        seedBase: h.seedBase,
        slots: h.slots || [],
    };
}

// A Frame of the protocol, section 11.3, from the renderer's snapshot of one drawing.
export function frameMessage(s) {
    return {
        type: 'frame',
        instanceId: s.instanceId,
        epoch: s.epoch,
        frameId: s.frameId,
        reset: s.reset || null,
        clocks: s.clocks,
        playback: s.playback,
        quality: s.quality,
        reducedMotion: !!s.reducedMotion,
        audible: !!s.audible,
        players: s.players.map((p) => ({
            ...p,
            root: roundAll(p.root),
            facing: round(p.facing),
            velocity: roundAll(p.velocity),
            speed: round(p.speed),
            distance: round(p.distance),
        })),
        ball: s.ball ? { ...s.ball, pos: roundAll(s.ball.pos), velocity: roundAll(s.ball.velocity) } : null,
        game: s.game,
        events: s.events,
        camera: s.camera,
    };
}

function list(value) {
    return Array.isArray(value) ? value.slice(0, MAXIMUM_COMMANDS) : [];
}

// Checks a reply against what the renderer expects. expect holds instanceId, epoch, own, the set
// of the team's own entity ids, envelope, a function from an entity id to its conservative bounds,
// and files, the set of the package's files. Returns {ok, reason, response} with every command
// checked, or ok false with the reason, stale, foreign or malformed.
export function checkResponse(message, expect) {
    if (!message || typeof message !== 'object' || message.type !== 'response') {
        return { ok: false, reason: 'malformed' };
    }
    if (message.instanceId !== expect.instanceId) {
        return { ok: false, reason: 'foreign' };
    }
    if (message.epoch !== expect.epoch) {
        return { ok: false, reason: 'stale' };
    }
    const own = expect.own;
    const r = {
        instanceId: message.instanceId, epoch: message.epoch, sourceFrameId: Number(message.sourceFrameId) || 0,
        ms: clamp(Number(message.ms) || 0, 0, 1e6), resources: [], behaviours: [], tracks: [], effects: [],
        claims: [], audio: [], camera: null, time: null, overlays: [], bounds: [], log: [], rejected: 0,
    };
    const keep = (target, value) => {
        if (value) {
            target.push(value);
        } else {
            r.rejected++;
        }
    };
    for (const c of list(message.resources)) {
        keep(r.resources, checkResource(c, expect.files));
    }
    for (const b of list(message.behaviours)) {
        const op = b && (b.op || 'set');
        const entity = b && b.entity != null ? String(b.entity) : null;
        if (!b || !['set', 'update', 'stop'].includes(op) || (entity !== null && !own.has(entity))) {
            r.rejected++;
            continue;
        }
        try {
            if (op === 'set') {
                r.behaviours.push({ op, entity, behaviour: checkBehaviour({ ...b.behaviour, id: b.id ?? (b.behaviour && b.behaviour.id) }) });
            } else if (op === 'update') {
                r.behaviours.push({ op, entity, id: String(b.id), patch: { ...(b.behaviour || {}) } });
            } else {
                r.behaviours.push({ op, entity, id: String(b.id), fadeOut: clamp(Number(b.fadeOut ?? 0.3) || 0, 0, 10) });
            }
        } catch {
            r.rejected++;
        }
    }
    for (const t of list(message.tracks)) {
        keep(r.tracks, checkTrack({ ...t, source: 'worker' }, own));
    }
    for (const e of list(message.effects)) {
        keep(r.effects, checkEffect(e, own));
    }
    for (const c of list(message.claims)) {
        keep(r.claims, checkClaim(c));
    }
    for (const a of list(message.audio)) {
        keep(r.audio, checkAudio(a, own));
    }
    for (const o of list(message.overlays)) {
        keep(r.overlays, checkOverlay(o));
    }
    if (message.camera != null) {
        r.camera = checkCamera(message.camera);
        r.rejected += r.camera ? 0 : 1;
    }
    if (message.time != null) {
        r.time = checkTime(message.time);
        r.rejected += r.time ? 0 : 1;
    }
    for (const b of list(message.bounds)) {
        const entity = b && String(b.entity);
        const envelope = own.has(entity) && expect.envelope ? expect.envelope(entity) : null;
        const current = b && b.current;
        if (!envelope || !current) {
            r.rejected++;
            continue;
        }
        // Current bounds lie inside the conservative envelope, which framing may always trust.
        r.bounds.push({ entity, current: { radius: clamp(Number(current.radius) || 0, 0.05, envelope.radius), height: clamp(Number(current.height) || 0, 0.2, envelope.height) } });
    }
    for (const line of list(message.log)) {
        r.log.push(String(line).slice(0, 300));
    }
    return { ok: true, response: r };
}
