// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The annotations of a recording or a live stream, as the section Annotations of
// docs/rendering.md describes them. A record belongs to a frame, the frame's index in a recording
// or its serial in a live stream, and to one player of the header or to the whole match. It holds
// named numbers v, a text t, the chosen action a and the likely actions k, each a pair of an
// action and its probability. Nothing here touches the page, so the tests read it in Node.

import { ACTION_NAMES } from '../core/input-settings.js';

// The named numbers that a label over a player shows at most.
export const LABEL_VALUES = 4;

function valid(record) {
    return !!record && typeof record === 'object' && Number.isInteger(record.f) && record.f >= 0;
}

// A series of numbers over the frames, one name of one player or of the whole match.
export function seriesKey(name, player) {
    return `${Number.isInteger(player) ? player : -1}:${name}`;
}

export class Annotations {
    constructor(records = []) {
        // The records of each frame, the whole match's and each player's.
        this.frames = new Map();
        this.series = new Map();
        this.count = 0;
        // Grows with every change, so a view redraws what it drew from an older version.
        this.version = 0;
        this.add(records);
    }

    get size() {
        return this.count;
    }

    // Adds records, each in place of an earlier record of its frame and player.
    add(records) {
        for (const record of Array.isArray(records) ? records : []) {
            if (!valid(record)) {
                continue;
            }
            let entry = this.frames.get(record.f);
            if (!entry) {
                entry = { match: null, players: new Map() };
                this.frames.set(record.f, entry);
            }
            const player = Number.isInteger(record.p) && record.p >= 0 ? record.p : -1;
            const had = player < 0 ? entry.match : entry.players.get(player);
            if (!had) {
                this.count++;
            }
            if (player < 0) {
                entry.match = record;
            } else {
                entry.players.set(player, record);
            }
            const values = record.v && typeof record.v === 'object' ? record.v : {};
            for (const [name, value] of Object.entries(values)) {
                if (typeof value !== 'number' || !Number.isFinite(value)) {
                    continue;
                }
                const key = seriesKey(name, player);
                let series = this.series.get(key);
                if (!series) {
                    series = { key, name, player, points: new Map() };
                    this.series.set(key, series);
                }
                series.points.set(record.f, value);
            }
        }
        this.version++;
    }

    // The records of a frame, or null.
    at(frame) {
        return this.frames.get(frame) || null;
    }

    // Drops the frames before a frame, as a live store drops its oldest frames.
    prune(first) {
        let dropped = false;
        for (const [frame, entry] of this.frames) {
            if (frame < first) {
                this.count -= (entry.match ? 1 : 0) + entry.players.size;
                this.frames.delete(frame);
                dropped = true;
            }
        }
        if (dropped) {
            for (const series of this.series.values()) {
                for (const frame of series.points.keys()) {
                    if (frame < first) {
                        series.points.delete(frame);
                    }
                }
            }
            this.version++;
        }
    }

    // Every series, those of the whole match first, then by player and by name.
    list() {
        return [...this.series.values()].sort((a, b) => a.player - b.player || a.name.localeCompare(b.name));
    }

    // The points of a series, pairs of frame and value in the order of the frames.
    points(key) {
        const series = this.series.get(key);
        return series ? [...series.points].sort((a, b) => a[0] - b[0]) : [];
    }
}

// A number with three significant digits at most, and whole numbers as they are.
export function formatValue(value) {
    if (Number.isInteger(value)) {
        return String(value);
    }
    const text = Number(value).toPrecision(3);
    return String(Number(text));
}

// The name of an action of GRF's action set, with a capital.
export function actionLabel(action) {
    const name = Number.isInteger(action) && ACTION_NAMES[action] ? ACTION_NAMES[action] : `action ${action}`;
    return name[0].toUpperCase() + name.slice(1);
}

// The lines that show a record, its numbers, its action and the likely actions, and its text,
// each null when the record has none. Values lists at most LABEL_VALUES names.
export function noteLines(record) {
    if (!record) {
        return { values: null, action: null, text: null };
    }
    const values = Object.entries(record.v || {}).filter(([, value]) => typeof value === 'number')
        .slice(0, LABEL_VALUES).map(([name, value]) => `${name} ${formatValue(value)}`);
    const likely = Array.isArray(record.k) ? record.k.filter((pair) => Array.isArray(pair) && pair.length === 2) : [];
    const parts = likely.map(([action, probability]) => `${actionLabel(action)} ${Math.round(probability * 100)}%`);
    let action = parts.join(', ');
    if (Number.isInteger(record.a)) {
        action = [`${actionLabel(record.a)} chosen`, ...(action ? [action] : [])].join(', ');
    }
    return {
        values: values.length ? values.join(', ') : null,
        action: action || null,
        text: typeof record.t === 'string' && record.t ? record.t : null,
    };
}

// The path of a series over the frames from first to last, in a box of width by height with y
// growing down, scaled from the series' smallest to its largest value. A frame without a value
// breaks the line when the gap between two points is wider than gap frames.
export function seriesPath(points, first, last, width, height, gap = 10) {
    const shown = points.filter(([frame]) => frame >= first && frame <= last);
    if (!shown.length) {
        return { path: '', min: null, max: null };
    }
    let min = Infinity;
    let max = -Infinity;
    for (const [, value] of shown) {
        min = Math.min(min, value);
        max = Math.max(max, value);
    }
    const span = Math.max(1, last - first);
    const range = max - min;
    const x = (frame) => ((frame - first) / span) * width;
    const y = (value) => (range > 0 ? (1 - (value - min) / range) * height : height / 2);
    let path = '';
    let previous = null;
    for (const [frame, value] of shown) {
        const move = previous === null || frame - previous > gap;
        path += `${move ? 'M' : 'L'}${x(frame).toFixed(1)} ${y(value).toFixed(1)}`;
        previous = frame;
    }
    return { path, min, max };
}
