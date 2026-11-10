// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Commands and reflexes, the plumbing that effects, lights, shaders, post, sound, music,
// environment moments, camera and time suggestions and overlay slots plug into. This module
// checks every command a reflex or a worker sends and hands it to the handler registered for its
// kind. The core registers handlers for what it draws itself, clips, behaviours, custody and one
// sound, and the renderer's later work registers the rest through register, without touching the
// contract's other modules. A command without a handler is counted and dropped.

import { clamp } from './values.js';

// The renderer's safety rules, versioned and owned by the renderer, never by a package. The
// sound and flash handlers apply them. Loudness follows ITU-R BS.1770 and EBU Tech 3341 meters,
// EBU R 128 targets and R 128 s1 for short cues, and ITU-T H.870 as relative safeguards. Flashes
// follow WCAG 2.3.1 and ITU-R BT.1702.
export const SAFETY = Object.freeze({
    version: 2,
    loudness: Object.freeze({
        integrated: -23, truePeak: -1, shortTermAboveTarget: 5, momentaryWindow: 0.4, shortTermWindow: 3,
        teamShortTerm: -18, teamMomentary: -14, teamTruePeak: -6, startleRise: 18, startleWindow: 0.1,
        sustainedDb: 6, sustainedSeconds: 3, sustainedWithin: 60, penaltyDb: 6,
    }),
    flashes: Object.freeze({ perSecond: 3, areaFraction: 0.25, fieldDegrees: 10, fieldWidth: 1 / 3, fieldHeight: 1 / 3, red: true }),
});

export const OCCLUSION = Object.freeze({ floor: 0.25, fadeIn: 0.15, recover: 0.3 });
export const ATTACH = ['ball', 'path', 'world', 'self'];
export const CLASSES = ['moment', 'action', 'bed'];
export const BUSES = ['effects', 'fans', 'music', 'voice'];
export const SHOTS = ['closeup', 'orbit', 'low', 'behindBall', 'path'];
export const SLOTS = ['badge', 'lowerThird', 'sting', 'card', 'lineup'];
export const CLAIMS = ['ball', 'goal', 'sky', 'floodlights', 'fans'];
export const REPLAY = ['repeat', 'quiet', 'skip'];
// The kinds of command and the actions a reflex may hold.
export const KINDS = ['effects', 'audio', 'camera', 'time', 'overlays', 'claims', 'resources', 'environment', 'materials'];
export const ACTIONS = ['audio', 'effect', 'clip', 'behaviour', 'claim', 'camera', 'time', 'overlay', 'environment', 'music'];

const ID = /^[A-Za-z0-9_.:-]{1,80}$/;
const num = (x, lo, hi, d) => (x != null && Number.isFinite(Number(x)) ? clamp(Number(x), lo, hi) : d);

const handlers = new Map();
export const dropped = {};

// Registers the handler of a kind of command, a function (command, context) returning whether it
// took the command. A later registration replaces an earlier one.
export function register(kind, handler) {
    if (!KINDS.includes(kind)) {
        throw new Error(`no command kind ${kind}`);
    }
    handlers.set(kind, handler);
}

export function handlerOf(kind) {
    return handlers.get(kind) || null;
}

// Hands a checked command to its handler, counting what no handler takes.
export function dispatch(kind, command, context) {
    const h = handlers.get(kind);
    const taken = h ? !!h(command, context) : false;
    if (!taken) {
        dropped[kind] = (dropped[kind] || 0) + 1;
    }
    return taken;
}

// Where a command's time falls, the contact of its event, the event itself or an offset of it in
// seconds, or an audio time.
function checkAt(at) {
    if (at == null || at === 'occur' || at === 'contact') {
        return { mode: at || 'occur', offset: 0 };
    }
    if (typeof at === 'object') {
        if (at.audio != null) {
            return { mode: 'audio', time: num(at.audio, 0, 1e9, 0) };
        }
        return {
            mode: at.event === 'contact' ? 'contact' : 'occur', event: at.event == null ? null : String(at.event),
            offset: num(at.offset, -10, 10, 0), quantize: ['beat', 'bar'].includes(at.quantize) ? at.quantize : null,
        };
    }
    return { mode: 'occur', offset: num(at, -10, 10, 0) };
}

// The anchor of an effect, the team's own socket, its entity, the ball, its path or the world.
function checkAttach(attach, own) {
    if (attach == null) {
        return { to: 'self' };
    }
    if (typeof attach === 'string') {
        if (ATTACH.includes(attach)) {
            return { to: attach };
        }
        if (/^socket:[A-Za-z0-9_]{1,40}$/.test(attach)) {
            return { to: 'self', socket: attach.slice(7) };
        }
        return null;
    }
    if (typeof attach === 'object') {
        const entity = attach.entity == null ? null : String(attach.entity);
        // A team addresses its own entities alone, the opponent's are never targets.
        if (entity !== null && !own.has(entity)) {
            return null;
        }
        return { to: 'entity', entity, socket: attach.socket ? String(attach.socket).slice(0, 40) : null };
    }
    return null;
}

// An effect command, spawn, update or stop, or null.
export function checkEffect(c, own) {
    if (!c || !ID.test(String(c.id || ''))) {
        return null;
    }
    const op = c.op || 'spawn';
    if (!['spawn', 'update', 'stop'].includes(op)) {
        return null;
    }
    if (op === 'stop') {
        return { op, id: String(c.id), fadeOut: num(c.fadeOut, 0, 10, 0.5) };
    }
    const attach = checkAttach(c.attach, own);
    if (!attach || typeof c.kind !== 'string' || c.kind.length > 40) {
        return null;
    }
    return { op, id: String(c.id), kind: c.kind, attach, at: checkAt(c.at), params: c.params && typeof c.params === 'object' ? c.params : {} };
}

// An audio command, play, param, stop or music, or null.
export function checkAudio(c, own) {
    if (!c || !['play', 'param', 'stop', 'music'].includes(c.op || 'play')) {
        return null;
    }
    const out = {
        op: c.op || 'play', id: c.id == null ? null : String(c.id).slice(0, 80), cue: c.cue == null ? null : String(c.cue).slice(0, 80),
        node: c.node == null ? null : String(c.node).slice(0, 80), at: checkAt(c.at),
        class: CLASSES.includes(c.class) ? c.class : 'action', bus: BUSES.includes(c.bus) ? c.bus : 'effects',
        // A package may only lower its sounds, the renderer's governor sets the ceiling.
        gain: num(c.gain, 0, 1, 1), rate: num(c.rate, 0.25, 4, 1),
        param: c.param == null ? null : String(c.param).slice(0, 40), value: num(c.value, -1e6, 1e6, 0),
        stems: Array.isArray(c.stems) ? c.stems.slice(0, 16).map((x) => Number(x) | 0) : 'all', fade: num(c.fade, 0, 10, 1),
    };
    if (c.attach != null) {
        out.attach = checkAttach(c.attach, own);
        if (!out.attach) {
            return null;
        }
    }
    return out;
}

export function checkClaim(c) {
    return c && CLAIMS.includes(c.target) && c.event != null ? { target: c.target, event: String(c.event) } : null;
}

export function checkCamera(c) {
    if (!c || !SHOTS.includes(c.shot) || c.event == null) {
        return null;
    }
    return { event: String(c.event), shot: c.shot, subject: c.subject == null ? null : String(c.subject), duration: num(c.duration, 0, 4, 2), priority: num(c.priority, 0, 10, 1), path: Array.isArray(c.path) ? c.path.slice(0, 32) : null };
}

export function checkTime(c) {
    if (!c || c.event == null) {
        return null;
    }
    const slow = c.slow && typeof c.slow === 'object' ? { speed: num(c.slow.speed, 0.25, 1, 0.5), seconds: num(c.slow.seconds, 0, 1.5, 0) } : null;
    return { event: String(c.event), at: c.at === 'contact' ? 'contact' : num(c.at, -5, 5, 0), freeze: num(c.freeze, 0, 0.3, 0), slow };
}

export function checkOverlay(c) {
    return c && SLOTS.includes(c.slot) && ['show', 'hide', 'draw'].includes(c.op || 'show') ? { slot: c.slot, op: c.op || 'show' } : null;
}

export function checkResource(c, files) {
    if (!c || !['load', 'geometry', 'texture', 'dispose'].includes(c.op) || !ID.test(String(c.id || ''))) {
        return null;
    }
    if (c.op === 'load' && !files.has(String(c.file || ''))) {
        return null;
    }
    return { ...c, id: String(c.id) };
}

// The reflexes of a manifest that an event fires for the team on side. where.team is self, the
// default, opponent or any, where.player a header index or a list, where.role goalkeeper or
// outfield. A reflex whose replay policy is skip stays out of replays.
export function reflexesFor(manifest, event, side, players = null) {
    const out = [];
    for (const r of (manifest && manifest.reflexes) || []) {
        if (r.on !== event.kind || (r.phase || 'occur') !== event.phase) {
            continue;
        }
        const w = r.where || {};
        const team = w.team || 'self';
        if (team === 'self' && event.team !== side) {
            continue;
        }
        if (team === 'opponent' && event.team !== 1 - side) {
            continue;
        }
        if (w.player != null && ![].concat(w.player).includes(event.player)) {
            continue;
        }
        if (w.role && players && event.player != null) {
            const p = players[event.player];
            if (!p || (w.role === 'goalkeeper') !== !!p.goalkeeper) {
                continue;
            }
        }
        out.push(r);
    }
    return out;
}

// The actions of a reflex, each checked, with the event it answers. Returns a list of
// {kind, command} for dispatch, the clip, behaviour and claim actions the core runs itself.
export function reflexActions(reflex, event, own) {
    const out = [];
    for (const a of reflex.do || []) {
        const replay = REPLAY.includes(a.replay) ? a.replay : 'repeat';
        if (event.replay && replay === 'skip') {
            continue;
        }
        const quiet = !!event.replay && replay === 'quiet';
        if (a.audio != null) {
            const c = checkAudio({ op: 'play', cue: a.audio, at: a.at, class: a.class, bus: a.bus, gain: a.gain, attach: a.attach }, own);
            if (c) {
                out.push({ kind: 'audio', command: { ...c, gain: quiet ? c.gain * 0.5 : c.gain, event: event.id } });
            }
        }
        if (a.effect != null) {
            const c = checkEffect({ op: 'spawn', id: `${a.effect}:${event.id}`, kind: String(a.effect), attach: a.attach, at: a.at, params: a.params }, own);
            if (c) {
                out.push({ kind: 'effects', command: { ...c, effect: String(a.effect), event: event.id, quiet } });
            }
        }
        if (a.claim != null && CLAIMS.includes(a.claim)) {
            out.push({ kind: 'claim', command: { target: a.claim, event: event.id } });
        }
        if (a.clip != null) {
            out.push({ kind: 'clip', command: { role: String(a.clip), on: a.on === 'team' ? 'team' : 'subject', event: event.id } });
        }
        if (a.behaviour != null && typeof a.behaviour === 'object') {
            out.push({ kind: 'behaviour', command: { spec: a.behaviour, on: a.on === 'team' ? 'team' : 'subject' } });
        }
        if (a.camera != null) {
            const c = checkCamera({ ...a.camera, event: event.id });
            if (c) {
                out.push({ kind: 'camera', command: c });
            }
        }
        if (a.overlay != null) {
            const c = checkOverlay({ slot: a.overlay, op: a.op });
            if (c) {
                out.push({ kind: 'overlays', command: c });
            }
        }
        if (a.environment != null && typeof a.environment === 'object') {
            out.push({ kind: 'environment', command: { ...a.environment, event: event.id } });
        }
        if (a.time != null && typeof a.time === 'object') {
            const c = checkTime({ ...a.time, event: event.id, at: a.at });
            if (c) {
                out.push({ kind: 'time', command: c });
            }
        }
        if (a.music != null) {
            const c = checkAudio({ op: a.stop ? 'stop' : 'music', id: String(a.music), gain: a.gain, at: a.at }, own);
            if (c) {
                out.push({ kind: 'audio', command: { ...c, stems: Array.isArray(a.stems) ? a.stems.slice(0, 16).map((x) => Number(x) | 0) : 'all', fade: num(a.fade, 0, 10, 1), event: event.id } });
            }
        }
    }
    return out;
}

// The occlusion fade of section 10.4. An effect of a team fades to the floor where it sits on the
// line from the camera to the ball or a player's torso. Points are [x, y, z], clearance the radius
// in metres kept clear. Returns the factor its opacity takes, from OCCLUSION.floor to 1.
export function occlusion(effect, camera, targets, clearance = 0.6) {
    let factor = 1;
    for (const t of targets) {
        const d = [t[0] - camera[0], t[1] - camera[1], t[2] - camera[2]];
        const length2 = d[0] * d[0] + d[1] * d[1] + d[2] * d[2];
        if (length2 < 1e-9) {
            continue;
        }
        const u = ((effect[0] - camera[0]) * d[0] + (effect[1] - camera[1]) * d[1] + (effect[2] - camera[2]) * d[2]) / length2;
        if (u <= 0 || u >= 1) {
            continue;
        }
        const gap = Math.hypot(camera[0] + d[0] * u - effect[0], camera[1] + d[1] * u - effect[1], camera[2] + d[2] * u - effect[2]);
        factor = Math.min(factor, clamp((gap - clearance * 0.5) / (clearance * 0.5), 0, 1));
    }
    return OCCLUSION.floor + (1 - OCCLUSION.floor) * factor;
}
