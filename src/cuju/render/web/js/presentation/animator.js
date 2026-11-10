// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Team driven animation, section 7 of the contract. A package whose driver is team draws its
// players from its own clips by semantic role instead of GRF's nodes. Where a player stands and
// faces always comes from the simulation, only the body's movement is the package's.
//
// Every weight and every clip time here is a function of the simulation and the ceremony
// clocks, so seeks, reverse play, slow motion and replays draw the same pose for the same moment.
// Locomotion is a blend space by speed whose phase follows the distance the player covered, so
// feet, wheels and rings advance exactly with the ground. Calm and alert idles, turns and brakes
// mix in by the turning rate and the deceleration. Actions are tracks whose contact marker meets
// the estimated contact with the ball, their wind-ups sped up to twice as fast when the warning
// is short. Each layer fades in and out over the blend time, so nothing pops, and a ceremony sits
// over an action, which sits over locomotion.

import { ACTION_ROLES, entries, pickClip, roleClips } from './contract.js';
import { contactClipTime, contactSchedule } from './tracks.js';
import { clamp } from './values.js';

export const BRAKE = 4;
export const TURN = 2.5;
// The share of a clip before its contact when the clip carries no marker.
export const DEFAULT_MARKER = 0.4;

// The role of the action clip that a touch event plays, from what the catalog knows of it.
export function actionRole(event, gameMode = 0) {
    const d = event.data || {};
    if (event.kind === 'restart.taken' && d.restart) {
        return `restart.${d.restart}`;
    }
    if (event.kind === 'save') {
        return d.style === 'catch' ? 'catch' : d.side === 'left' ? 'dive.left' : d.side === 'right' ? 'dive.right' : 'parry';
    }
    if (event.kind === 'pass') {
        return `pass.${d.type || 'short'}`;
    }
    if (['shot', 'header', 'volley', 'slide', 'catch'].includes(event.kind)) {
        return event.kind;
    }
    if (event.kind === 'deflection') {
        return 'deflect';
    }
    const role = ACTION_ROLES[d.action] || 'kick';
    return role.startsWith('pass') && gameMode === 5 ? 'throwIn' : role;
}

// The contact events that start an action clip, the more precise kinds before plain touches.
const PRIORITY = ['restart.taken', 'save', 'shot', 'volley', 'header', 'pass', 'slide', 'catch', 'deflection', 'touch'];

export function preferred(events) {
    let best = null;
    for (const e of events) {
        if (best === null || PRIORITY.indexOf(e.kind) < PRIORITY.indexOf(best.kind)) {
            best = e;
        }
    }
    return best;
}

export class Animator {
    // manifest, the normalized manifest, clipInfo, a function from a clip name to
    // {duration, marker} or null for a clip the model lacks, seed, the entity's seed.
    constructor(manifest, clipInfo, seed = 0) {
        this.manifest = manifest;
        this.clipInfo = clipInfo;
        this.seed = seed >>> 0;
        this.blend = Math.max(1e-3, Number(manifest.rig.blend) || 0.2);
        this.actions = new Map();
    }

    entry(role) {
        const e = pickClip(this.manifest, role, this.seed);
        return e && this.clipInfo(e.clip) ? e : null;
    }

    // The schedule of the action of a contact event, kept by event id, so a seek back finds the
    // same one. lead is the warning the renderer had, the event's lead when first seen.
    schedule(event, lead, gameMode = 0) {
        const id = event.id;
        if (this.actions.has(id)) {
            return this.actions.get(id);
        }
        const role = actionRole(event, gameMode);
        const entry = this.entry(role);
        if (!entry) {
            return null;
        }
        const info = this.clipInfo(entry.clip);
        const marker = info.marker != null ? info.marker : info.duration * DEFAULT_MARKER;
        const contactT = event.data && event.data.contactT != null ? event.data.contactT : event.t;
        const s = contactSchedule(marker, info.duration, contactT, lead);
        const action = { id, role, clip: entry.clip, marker, contactT, schedule: s, duration: info.duration, cancelledAt: null };
        this.actions.set(id, action);
        if (this.actions.size > 64) {
            this.actions.delete(this.actions.keys().next().value);
        }
        return action;
    }

    // Ends an action whose forecast was cancelled, fading over 0.15 s from simulation time sim.
    cancel(id, sim) {
        const a = this.actions.get(id);
        if (a && a.cancelledAt == null) {
            a.cancelledAt = sim;
        }
    }

    // The layers of one moment, each {clip, time, weight, role} with weights summing to one, or an
    // empty list when no role has a clip. input holds sim, the simulation time, speed in metres per
    // second, distance, the metres the player covered since the match began, decel and turnRate
    // from the frames, alert, cosmetic, the cosmetic time, and overlay, {role, clip, time, weight}
    // of a ceremony, or null.
    layers(input) {
        const out = [];
        const overlay = input.overlay && input.overlay.weight > 0 && this.clipInfo(input.overlay.clip) ? input.overlay : null;
        const o = overlay ? clamp(overlay.weight, 0, 1) : 0;
        // The strongest action live at this moment of the simulation clock.
        let action = null;
        let a = 0;
        for (const act of this.actions.values()) {
            const s = act.schedule;
            const end = act.cancelledAt != null ? Math.min(s.to, act.cancelledAt + 0.15) : s.to;
            if (input.sim < s.from || input.sim > end) {
                continue;
            }
            const w = clamp(Math.min((input.sim - s.from) / this.blend + (s.offset > 0 ? 0.5 : 0), (end - input.sim) / (act.cancelledAt != null ? 0.15 : this.blend)), 0, 1);
            if (w > a) {
                a = w;
                action = act;
            }
        }
        const base = this.locomotion(input);
        const baseShare = (1 - o) * (1 - a);
        const sum = base.reduce((t, l) => t + l.weight, 0);
        for (const l of base) {
            if (sum > 0 && l.weight * baseShare > 1e-4) {
                out.push({ ...l, weight: (l.weight / sum) * baseShare });
            }
        }
        if (action && a > 0) {
            out.push({ clip: action.clip, role: action.role, weight: (1 - o) * a, time: clamp(contactClipTime(action.schedule, action.marker, action.contactT, input.sim), 0, action.duration) });
        }
        if (overlay) {
            out.push({ clip: overlay.clip, role: overlay.role, weight: o, time: overlay.time });
        }
        const total = out.reduce((t, l) => t + l.weight, 0);
        if (total <= 0) {
            return [];
        }
        for (const l of out) {
            l.weight /= total;
        }
        return out;
    }

    // Locomotion at one moment, unnormalized weights of the idles, moves, turns and brakes.
    locomotion(input) {
        const speed = Math.max(0, input.speed || 0);
        const moves = entries(this.manifest.clips.move).filter((m) => this.clipInfo(m.clip));
        const idle = (input.alert && this.entry('idle.alert')) || this.entry('idle.calm');
        const space = [];
        if (idle && !moves.some((m) => !(m.speed > 0))) {
            space.push({ clip: idle.clip, speed: 0, idle: true, role: input.alert ? 'idle.alert' : 'idle.calm' });
        }
        for (const m of moves) {
            space.push({ ...m, speed: m.speed || 0, role: 'move' });
        }
        if (!space.length) {
            const fallback = roleClips(this.manifest, 'move').find((m) => this.clipInfo(m.clip));
            if (!fallback) {
                return [];
            }
            space.push({ ...fallback, speed: 0, role: 'move' });
        }
        let lo = space[0];
        let hi = space[space.length - 1];
        for (let i = 0; i < space.length - 1; i++) {
            if (speed >= space[i].speed && speed <= space[i + 1].speed) {
                lo = space[i];
                hi = space[i + 1];
                break;
            }
        }
        const span = hi.speed - lo.speed;
        const u = span > 0 ? clamp((speed - lo.speed) / span, 0, 1) : (speed >= hi.speed ? 1 : 0);
        const out = [];
        const add = (m, w) => {
            if (w <= 0) {
                return;
            }
            const info = this.clipInfo(m.clip);
            let time;
            if (m.idle || !(m.speed > 0)) {
                time = (input.cosmetic || 0) * (m.rate || 1);
            } else {
                // The phase follows the ground covered, one cycle per stride.
                const stride = m.stride || m.speed * info.duration;
                time = ((((input.distance || 0) / stride) % 1) + 1) % 1 * info.duration;
            }
            out.push({ clip: m.clip, time, weight: w, role: m.role });
        };
        add(lo, lo === hi ? 1 : 1 - u);
        if (hi !== lo) {
            add(hi, u);
        }
        const brake = this.entry('brake');
        const bw = brake && this.manifest.clips.brake ? clamp((input.decel - BRAKE) / BRAKE, 0, 1) : 0;
        const turn = this.entry('turn');
        const tw = turn && this.manifest.clips.turn && speed < 2 ? clamp((Math.abs(input.turnRate || 0) - TURN) / TURN, 0, 1) : 0;
        for (const l of out) {
            l.weight *= (1 - bw) * (1 - tw);
        }
        if (bw > 0) {
            out.push({ clip: brake.clip, time: (input.sim || 0) % this.clipInfo(brake.clip).duration, weight: bw * (1 - tw), role: 'brake' });
        }
        if (tw > 0) {
            out.push({ clip: turn.clip, time: (input.cosmetic || 0) % this.clipInfo(turn.clip).duration, weight: tw, role: 'turn' });
        }
        return out;
    }

    // The weight each role plays at one moment, for the behaviours that read them.
    static roleWeights(layers) {
        const out = {};
        for (const l of layers) {
            out[`role:${l.role}`] = (out[`role:${l.role}`] || 0) + l.weight;
        }
        return out;
    }
}
