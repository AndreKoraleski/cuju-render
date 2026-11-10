// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The presentation contract on the page, its version, its features, and the manifest as the page
// reads it once the server checked it, see _presentation.py. The section Team presentation
// packages of docs/presentation.md describes every part.

import { hash } from './values.js';

export const CONTRACT = '1.1';
export const MAJOR = 1;
export const MINOR = 1;

// The features this renderer implements, by the level of a package that needs them. A package
// that requires a feature of the worker level the renderer lacks runs without its worker, one
// of the manifest level draws in the stock look.
export const FEATURES = {
    'drivers.grf': 'manifest',
    'drivers.team': 'manifest',
    'drivers.worker': 'worker',
    lookahead: 'manifest',
    'lookahead.outcomes': 'manifest',
    'inference.pass/1': 'manifest',
    'inference.shot/1': 'manifest',
    'inference.header/1': 'manifest',
    'inference.volley/1': 'manifest',
    'inference.slide/1': 'manifest',
    'inference.save/1': 'manifest',
    'inference.goal/1': 'manifest',
    'inference.sprint/1': 'manifest',
    'inference.dribble/1': 'manifest',
    'clips.markers': 'manifest',
    'drivers.grf+layers': 'manifest',
    'bend.ball': 'manifest',
    'ik.fabrik': 'manifest',
    'shader.custom': 'manifest',
    'shader.sceneColor': 'manifest',
    'post.layer': 'manifest',
    'post.fullscreen': 'manifest',
    'geometry.worker': 'worker',
    'overlay.offscreen': 'worker',
    'audio.worklet': 'manifest',
    'audio.music': 'manifest',
    'camera.suggest': 'manifest',
    'time.suggest': 'manifest',
    'environment.sky': 'manifest',
    'environment.lightning': 'manifest',
    'fans.tifo': 'manifest',
};
// Features of the contract still to come, none since contract 1.1.
export const PLANNED = [];

const WORKER_ONLY = new Set(['drivers.worker', 'geometry.worker', 'overlay.offscreen']);

export const DRIVERS = ['grf', 'grf+layers', 'team', 'worker'];

// The semantic roles of clips.
export const ROLES = [
    'idle.calm', 'idle.alert', 'move', 'turn', 'brake', 'kick', 'pass.short', 'pass.long',
    'pass.high', 'shot', 'header', 'volley', 'slide', 'trip', 'catch', 'parry', 'dive.left',
    'dive.right', 'throwIn', 'restart.kickoff', 'restart.goal_kick', 'restart.free_kick',
    'restart.corner', 'restart.throw_in', 'restart.penalty', 'trap', 'deflect', 'celebration',
    'reaction.win', 'reaction.loss', 'lineup', 'salute', 'lament', 'recovery', 'podium',
];

// The role a missing role falls back to, in turn, until one has a clip.
export const FALLBACK = {
    'idle.alert': 'idle.calm', move: 'idle.calm', turn: 'move', brake: 'move',
    'pass.short': 'kick', 'pass.long': 'kick', 'pass.high': 'kick', shot: 'kick', header: 'kick',
    volley: 'shot', trap: 'kick', deflect: 'kick', parry: 'catch', throwIn: 'pass.short',
    'restart.kickoff': 'pass.short', 'restart.goal_kick': 'pass.long', 'restart.free_kick': 'pass.short',
    'restart.corner': 'pass.high', 'restart.throw_in': 'throwIn', 'restart.penalty': 'shot',
    'reaction.win': 'celebration', 'reaction.loss': 'lament', salute: 'reaction.win',
    recovery: 'idle.calm', podium: 'celebration',
};

// GRF's kinds of animation, as the action bytes of a frame store them, by the role of the clip
// that plays them. Ball control and movement belong to locomotion.
export const ACTION_ROLES = {
    3: 'trap', 4: 'pass.short', 5: 'pass.long', 6: 'pass.high', 7: 'header', 8: 'shot', 9: 'deflect',
    10: 'catch', 11: 'kick', 12: 'trip', 13: 'slide',
};
export const ACTION_ROLE_KINDS = new Set(Object.values(ACTION_ROLES).concat(['volley', 'throwIn', 'parry', 'dive.left', 'dive.right']));

// The semantic role of each still pose of the renderer's choreographies.
export const STILL_ROLES = {
    idle: 'idle.calm', idle_confident: 'idle.calm', idle_bounce: 'idle.alert', stand: 'idle.calm',
    breathe: 'idle.calm', clap: 'salute', applause: 'salute', applaud: 'salute', wave: 'salute',
    point: 'salute', salute: 'salute', bow: 'salute', dejected: 'lament', hands_on_head: 'lament',
    sad: 'lament', disappointed: 'lament', slump: 'lament', crouch: 'lament', kneel: 'lament',
    team_huddle: 'celebration', huddle: 'celebration', hug: 'celebration', embrace: 'celebration',
    arms_up: 'reaction.win', jump_fist: 'reaction.win', cheer: 'reaction.win', dance: 'celebration',
};

export function stillRole(still) {
    return STILL_ROLES[String(still || '')] || null;
}

// Whether a contract version is one this renderer serves, of its major and a minor up to its own.
export function supports(version) {
    const m = /^(\d+)\.(\d+)$/.exec(String(version || ''));
    return !!m && Number(m[1]) === MAJOR && Number(m[2]) <= MINOR;
}

// The level a package runs at, given the features it requires, worker, manifest or stock, and the
// required and preferred features this renderer lacks.
export function level(manifest) {
    const missing = (manifest.requires || []).filter((f) => !(f in FEATURES));
    const lacking = (manifest.prefers || []).filter((f) => !(f in FEATURES));
    // A missing feature that only a worker uses drops the worker, any other drops the package.
    const at = !missing.length ? 'worker' : missing.every((f) => WORKER_ONLY.has(f)) ? 'manifest' : 'stock';
    return { level: at, missing, lacking };
}

const DEFAULT_RIG = { driver: {}, sockets: {}, bounds: null, rootMotion: 'ignore', joints: null, attachments: {}, ik: {}, layers: [] };

// A manifest with every part filled, or null for one this renderer cannot serve.
export function normalize(manifest) {
    if (!manifest || typeof manifest !== 'object' || !supports(manifest.contract)) {
        return null;
    }
    const rig = { ...DEFAULT_RIG, ...(manifest.rig || {}) };
    if (typeof rig.driver === 'string') {
        rig.driver = { outfield: rig.driver, goalkeeper: rig.driver };
    }
    return {
        ...manifest,
        requires: manifest.requires || [],
        prefers: manifest.prefers || [],
        models: manifest.models || {},
        rig,
        clips: manifest.clips || {},
        behaviours: Array.isArray(manifest.behaviours) ? manifest.behaviours : [],
        materials: manifest.materials || {},
        effects: manifest.effects || {},
        audio: manifest.audio || {},
        reflexes: Array.isArray(manifest.reflexes) ? manifest.reflexes : [],
        worker: manifest.worker || null,
        reducedMotion: { amplitude: 0.3, ...(manifest.reducedMotion || {}) },
        quality: manifest.quality || {},
        lights: manifest.lights || {},
        post: manifest.post || {},
        overlays: manifest.overlays || {},
    };
}

// The role of a player on the pitch, goalkeeper or outfield.
export function roleOf(player) {
    return player.goalkeeper ? 'goalkeeper' : 'outfield';
}

// The driver that moves a player, grf unless the manifest names another for his role.
export function driverOf(manifest, player) {
    const d = manifest.rig.driver[roleOf(player)];
    return DRIVERS.includes(d) ? d : 'grf';
}

// The model file a player draws, by shirt number first, then by role, or null for the team's
// own model.
export function modelOf(manifest, player) {
    const m = manifest.models;
    const byNumber = m.byNumber && m.byNumber[String(player.number)];
    return byNumber || m[roleOf(player)] || m.outfield || null;
}

// Whether a selector picks a player, by role, shirt number or roster index, all given keys
// matching.
export function selects(when, player) {
    if (!when) {
        return true;
    }
    if (when.role && when.role !== roleOf(player)) {
        return false;
    }
    if (when.number != null && ![].concat(when.number).includes(player.number)) {
        return false;
    }
    if (when.index != null && ![].concat(when.index).includes(player.index)) {
        return false;
    }
    return true;
}

// The seed base of a match, the same for every viewer of the same recording.
export function seedBase(header) {
    const p = (header && header.provenance) || {};
    if (p.seed != null) {
        return hash(`seed:${p.seed}`);
    }
    return hash(JSON.stringify([header && header.scenario, header && header.title, header && header.teams && header.teams.map((t) => t && t.name)]));
}

// A seed of an entity and a key that holds no epoch, so replays and seeks reuse it.
export function seed(base, side, entity, key = '') {
    return hash(`${base}:${side}:${entity}:${key}`);
}

// The clip entries of a role, following the fallback chain. Each entry is
// {clip, speed, stride, rate, loop}.
export function roleClips(manifest, role) {
    const clips = (manifest && manifest.clips) || {};
    const seen = new Set();
    for (let r = role; r && !seen.has(r); r = FALLBACK[r]) {
        seen.add(r);
        const entry = clips[r];
        const list = entries(entry);
        if (list.length) {
            return list;
        }
    }
    return [];
}

// The entries of a clip declaration, a name, a list of names or descriptions, or for move a
// space of clips by speed.
export function entries(entry) {
    if (!entry) {
        return [];
    }
    if (typeof entry === 'string') {
        return [{ clip: entry }];
    }
    if (Array.isArray(entry)) {
        return entry.map((e) => (typeof e === 'string' ? { clip: e } : e)).filter((e) => e && e.clip);
    }
    if (entry.space === 'speed' && Array.isArray(entry.clips)) {
        return entry.clips.map((c) => (Array.isArray(c) ? { clip: c[0], speed: Number(c[1]) || 0, stride: c[2] } : c))
            .filter((e) => e && e.clip).sort((a, b) => (a.speed || 0) - (b.speed || 0));
    }
    return entry.clip ? [entry] : [];
}

// One clip of a role for an entity, the variant its seed picks, or null.
export function pickClip(manifest, role, entitySeed = 0) {
    const list = roleClips(manifest, role);
    if (!list.length) {
        return null;
    }
    return role === 'move' ? list[0] : list[(entitySeed >>> 0) % list.length];
}
