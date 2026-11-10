// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The range and settings of a video export, as the Export video dialog of the Watch page reads
// them and the server's endpoint POST /api/matches/{id}/video takes them.

import { SIZE_PRESETS, checkSize, parseGraphicsScale, parseSafe } from './sizes.js';

// The sizes, frame rates, qualities and cameras that the server accepts from the page. The sizes
// are the shared presets of sizes.js, and a custom size takes any even width and height within
// their limits.
export const VIDEO_SIZES = SIZE_PRESETS;
export const VIDEO_RATES = [24, 25, 30, 50, 60];
export const VIDEO_QUALITIES = [
    { id: 'draft', label: 'Draft' },
    { id: 'standard', label: 'Standard' },
    { id: 'high', label: 'High' },
];
export const VIDEO_CAMERAS = [
    { id: 'broadcast', label: 'Broadcast' },
    { id: 'tactical', label: 'Tactical' },
    { id: 'goal', label: 'Behind the goal' },
    { id: 'ball', label: 'Follow the ball' },
    { id: 'owner', label: 'Follow the player on the ball' },
];
// The longest export that the page asks for, in seconds, as the server's default limit.
export const VIDEO_MAX_SECONDS = 600;
// A goal's range runs from this long before the goal to this long after it.
export const GOAL_BEFORE = 8;
export const GOAL_AFTER = 4;

// Reads a moment typed as seconds, such as 75 or 75.5, or as minutes and seconds, such as 1:15.
// Returns the seconds, or null for text that names no moment.
export function parseMoment(text) {
    const value = String(text ?? '').trim();
    let m = value.match(/^(\d+(?:\.\d+)?)$/);
    if (m) {
        return Number(m[1]);
    }
    m = value.match(/^(\d+):(\d{1,2}(?:\.\d+)?)$/);
    if (m && Number(m[2]) < 60) {
        return Number(m[1]) * 60 + Number(m[2]);
    }
    return null;
}

// Writes seconds as minutes and seconds with a tenth, such as 1:05.3, or 1:05 for whole seconds.
export function formatMoment(seconds) {
    const tenths = Math.max(0, Math.round(seconds * 10));
    const whole = Math.floor(tenths / 10);
    const text = `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
    return tenths % 10 ? `${text}.${tenths % 10}` : text;
}

// The range around a goal at the given seconds, kept within a recording of duration seconds.
export function goalRange(at, duration) {
    return { start: Math.max(0, at - GOAL_BEFORE), end: Math.min(duration, at + GOAL_AFTER) };
}

// Checks a range typed in the dialog against a recording of duration seconds. Returns the start
// and end in seconds, or an error to show.
export function checkRange(startText, endText, duration) {
    const start = parseMoment(startText);
    const end = parseMoment(endText);
    if (start == null || end == null) {
        return { error: 'Type the start and end as seconds, such as 75, or minutes and seconds, such as 1:15.' };
    }
    if (start >= duration) {
        return { error: `The start lies past the end of the recording, at ${formatMoment(duration)}.` };
    }
    const last = Math.min(end, duration);
    if (last <= start) {
        return { error: 'The end comes after the start.' };
    }
    if (last - start > VIDEO_MAX_SECONDS) {
        return { error: `A video runs at most ${VIDEO_MAX_SECONDS / 60} minutes, so choose a shorter range.` };
    }
    return { start, end: last };
}

// The body of an export request, from a checked range and the choices of the dialog. The arena
// and time of day come from the field settings of the page.
export function exportRequest(range, choices, field) {
    const size = videoSize(choices.size);
    const body = {
        start: Math.round(range.start * 1000) / 1000,
        end: Math.round(range.end * 1000) / 1000,
        camera: VIDEO_CAMERAS.some((c) => c.id === choices.camera) ? choices.camera : 'broadcast',
        width: size.width,
        height: size.height,
        fps: VIDEO_RATES.includes(Number(choices.fps)) ? Number(choices.fps) : 30,
        quality: VIDEO_QUALITIES.some((q) => q.id === choices.quality) ? choices.quality : 'standard',
        score: choices.score !== false,
    };
    const graphics = graphicsScale(choices.scale);
    if (graphics !== 1) {
        body.scale = graphics;
    }
    const safe = safeChoice(choices.safe);
    if (safe !== 'auto') {
        body.safe = safe;
    }
    if (field && typeof field.arena === 'string') {
        body.arena = field.arena;
    }
    if (field && typeof field.time === 'number' && Number.isFinite(field.time)) {
        body.time = Math.min(24, Math.max(0, field.time));
    }
    return body;
}

// The size of a choice, a preset's identifier or a width and height, which a video needs even.
// Anything else falls back to 720p.
export function videoSize(choice) {
    const preset = VIDEO_SIZES.find((s) => s.id === choice);
    if (preset) {
        return preset;
    }
    if (choice && typeof choice === 'object') {
        try {
            return checkSize(choice.width, choice.height, { even: true });
        } catch {
            // A size out of range falls back below.
        }
    }
    return VIDEO_SIZES.find((s) => s.id === '720p');
}

function graphicsScale(value) {
    try {
        return parseGraphicsScale(value);
    } catch {
        return 1;
    }
}

function safeChoice(value) {
    try {
        return parseSafe(value);
    } catch {
        return 'auto';
    }
}

// The line of progress of an export entry from the server.
export function progressText(entry) {
    if (!entry) {
        return '';
    }
    if (entry.state === 'done') {
        const mb = entry.bytes ? `, ${(entry.bytes / 1e6).toFixed(1)} MB` : '';
        return `The video is ready${mb}.`;
    }
    if (entry.state === 'failed') {
        return `The export failed. ${entry.error || ''}`.trim();
    }
    if (entry.state === 'cancelled') {
        return 'The export was cancelled.';
    }
    if (!entry.frame) {
        return 'Starting Chrome and opening the recording.';
    }
    if (entry.progress >= 1) {
        return 'Finishing the file.';
    }
    return `Drawing frame ${entry.frame} of ${entry.frames}, ${Math.round(entry.progress * 100)} percent.`;
}
