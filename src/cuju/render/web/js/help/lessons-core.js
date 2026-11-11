// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The rules of the hands-on lessons. The catalog of lessons is web/lessons.json, which the page
// and the command `cuju render tutorial` both read. A lesson asks the person to do one thing and
// ends when the page's own state shows it done. The page takes a snapshot of its state a few times
// a second, and checkLesson compares it with the snapshot taken when the lesson began, keeping
// what it needs between two looks in a memory of the lesson. The browser keeps the lessons done.
// Nothing here touches the page, so the rules hold the same in a test. The page shows the title,
// the ask and the praise of a lesson as the messages lesson.<id>.title, .ask and .praise, whose
// English is the catalog's, and the catalog's own text stands in for a lesson without messages.

import { has, plainMarks, plainText, t, tn, tOr } from '../core/i18n.js';

export const LESSONS_KEY = 'cuju.lessons';

// The camera modes that follow one player.
export const FOLLOW_MODES = ['player', 'owner', 'fpp'];
// The camera modes that a person chooses, as the View menu lists them. The shows of the page move
// the camera through modes of their own, which no lesson counts.
export const CHOSEN_MODES = ['broadcast', 'tactical', 'goal', 'player', 'free', 'ball', 'owner', 'fpp'];
// Steps of a game that make 30 seconds of match time, at ten steps a second.
export const PLAYED_STEPS = 300;
// How far before and after a goal a seek lands to count as a jump to it, in seconds. N lands six
// seconds before the goal.
export const GOAL_BEFORE = 8;
export const GOAL_AFTER = 4;
// A move of the timeline between two looks that is this many seconds more than playing explains
// counts as a jump.
export const JUMP_SECONDS = 2;

// The stored progress, the lessons done with the time of each and the lesson under way, kept to
// the lessons of the catalog.
export function progressState(stored, ids) {
    const source = stored && typeof stored === 'object' ? stored : {};
    const known = new Set(ids);
    const done = {};
    if (source.done && typeof source.done === 'object' && !Array.isArray(source.done)) {
        for (const [id, when] of Object.entries(source.done)) {
            if (known.has(id) && typeof when === 'string') {
                done[id] = when;
            }
        }
    }
    const current = typeof source.current === 'string' && known.has(source.current) ? source.current : null;
    return { done, current };
}

// The progress once a lesson is done, which keeps the first time it was done.
export function markDone(progress, id, when, ids) {
    const clean = progressState(progress, ids);
    if (!ids.includes(id)) {
        return clean;
    }
    return { ...clean, done: { ...clean.done, [id]: clean.done[id] || when } };
}

// The first lesson not done after the given one, then from the start, or null when all are done.
export function nextLesson(progress, ids, after = null) {
    const clean = progressState(progress, ids);
    const from = after ? ids.indexOf(after) + 1 : 0;
    const order = [...ids.slice(from), ...ids.slice(0, from)];
    return order.find((id) => !(id in clean.done)) || null;
}

// How many lessons are done.
export function doneCount(progress, ids) {
    const clean = progressState(progress, ids);
    return ids.filter((id) => id in clean.done).length;
}

// Whether a lesson's need is there, a recording that plays or nothing.
export function needMet(lesson, snap) {
    if (!lesson || !lesson.needs) {
        return true;
    }
    if (lesson.needs === 'recording') {
        return !!(snap && snap.source);
    }
    return true;
}

// Whether the timeline moved by a jump between two looks, more than playing explains.
export function jumped(previous, snap) {
    if (!previous || !snap || !snap.source || !previous.source || previous.source.id !== snap.source.id) {
        return false;
    }
    if (typeof previous.t !== 'number' || typeof snap.t !== 'number' || !snap.sps) {
        return false;
    }
    const seconds = Math.max(0, (snap.at - previous.at) / 1000);
    const played = previous.playing ? Math.abs(previous.speed || 1) * seconds * snap.sps : 0;
    return Math.abs(snap.t - previous.t) > played + JUMP_SECONDS * snap.sps;
}

// Whether the timeline stands at a goal, from a little before it to a little after.
export function atGoal(snap) {
    if (!snap || !snap.source || !Array.isArray(snap.goals) || !snap.sps || typeof snap.t !== 'number') {
        return false;
    }
    return snap.goals.some((index) => snap.t >= index - GOAL_BEFORE * snap.sps && snap.t <= index + GOAL_AFTER * snap.sps);
}

// Whether a lesson is done, from the snapshot now, the one of the lesson's start and the memory of
// the lesson, which this function fills.
export function checkLesson(id, snap, base, memory = {}) {
    if (!snap) {
        return false;
    }
    switch (id) {
    case 'open_sample':
        return !!snap.source && (snap.source.kind === 'match' || snap.source.kind === 'file');
    case 'seek_goal': {
        // A replay and the show after the match seek on their own. A snapshot marked show, as
        // the watching in the background marks them, keeps their seeks out, from the first look
        // during the show to the first look after it.
        if (snap.show) {
            memory.inShow = true;
            memory.previous = null;
            return false;
        }
        // The timeline counts its jumps, so a jump counts even when the recording opened since
        // the last look. Jumps made before the lesson began stay out, and a recording opened
        // later counts from its start.
        const id = snap.source ? snap.source.id : null;
        if (!memory.seeks || memory.seeks.id !== id) {
            const before = !memory.seeks && base && base.source && base.source.id === id ? (base.jumps || 0) : 0;
            memory.seeks = { id, jumps: before };
        }
        if (memory.inShow) {
            memory.inShow = false;
            memory.seeks.jumps = snap.jumps || 0;
        }
        if (jumped(memory.previous, snap) || (snap.jumps || 0) > memory.seeks.jumps) {
            memory.jumps = (memory.jumps || 0) + 1;
        }
        memory.seeks.jumps = Math.max(memory.seeks.jumps, snap.jumps || 0);
        memory.previous = snap;
        return !!memory.jumps && atGoal(snap);
    }
    case 'switch_camera': {
        // The first chosen camera seen with the recording is the one to switch from.
        if (!snap.source || !CHOSEN_MODES.includes(snap.camera)) {
            return false;
        }
        if (memory.camera === undefined || memory.cameraSource !== snap.source.id) {
            memory.camera = snap.camera;
            memory.cameraSource = snap.source.id;
            return false;
        }
        return snap.camera !== memory.camera;
    }
    case 'follow_player':
        return !!snap.source && FOLLOW_MODES.includes(snap.camera);
    case 'play_game': {
        const game = snap.game;
        if (!game || !game.running || typeof game.step !== 'number') {
            return false;
        }
        if (memory.gameId !== game.id) {
            memory.gameId = game.id;
            memory.firstStep = game.step;
        }
        memory.firstStep = Math.min(memory.firstStep, game.step);
        return game.step - memory.firstStep >= PLAYED_STEPS;
    }
    case 'register_team':
        return (snap.teams || 0) > 0;
    case 'start_challenge':
        return !!snap.challenge;
    case 'make_photo':
        return !!snap.photo && (!base || snap.photo !== base.photo);
    default:
        return false;
    }
}

// The title, the ask and the praise of a lesson in the page's language.
export function lessonTitle(lesson) {
    return tOr(`lesson.${lesson.id}.title`, lesson.title);
}

export function lessonAsk(lesson) {
    return tOr(`lesson.${lesson.id}.ask`, lesson.ask);
}

export function lessonPraise(lesson) {
    return tOr(`lesson.${lesson.id}.praise`, lesson.praise);
}

// The ask and the praise as nodes, their marks as strong words, code and keycaps, for the page.
function markedOr(id, fallback) {
    return has(id) ? tn(id) : [plainMarks(plainText(fallback))];
}

export function lessonAskNodes(lesson) {
    return markedOr(`lesson.${lesson.id}.ask`, lesson.ask);
}

export function lessonPraiseNodes(lesson) {
    return markedOr(`lesson.${lesson.id}.praise`, lesson.praise);
}

// The words a screen reader hears when a lesson begins.
export function lessonAnnouncement(lesson, index, count) {
    return t('lessons.announce', { index: index + 1, count, title: lessonTitle(lesson), ask: lessonAsk(lesson) });
}
