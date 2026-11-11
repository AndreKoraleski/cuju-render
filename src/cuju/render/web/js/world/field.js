// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Field settings for grass, lines, nets, boards, crowd, time of day and weather. They live in this
// browser only, and travel as a JSON file with any images embedded as data URLs.

import { ARENAS } from './arenas.js';
import { PRESET_HOURS, WEATHER } from './sky.js';
import { t } from '../core/i18n.js';

const KEY = 'cuju.field';

export const MOWING = ['stripes', 'checkers', 'circles', 'none'];
export const BOARDS = ['sponsors', 'shipped', 'custom'];
// Named hours for the time of day, the slider takes any hour between.
export const TIMES = ['dawn', 'day', 'dusk', 'night'];
export const TIME_HOURS = PRESET_HOURS;
export const WEATHERS = Object.keys(WEATHER);
export const FIELD_VERSION = 2;
export const CROWDS = ['teams', 'custom', 'grf'];
// Boards are kept as data addresses in the browser's storage, which holds only a few megabytes.
export const MAX_BOARDS = 8;
// An exported field holds at most eight boards of well under a megabyte each.
export const MAX_IMPORT_BYTES = 8 * 1024 * 1024;

export const DEFAULT_FIELD = {
    version: FIELD_VERSION,
    grass: '#3f7f2c',
    mowing: 'stripes',
    stripeWidth: 5.5,
    lines: '#ffffff',
    net: '#ffffff',
    boards: 'sponsors',
    customBoards: [],
    crowd: 'teams',
    crowdColors: ['#d8d8d8', '#202428', '#b3262e', '#2a56b8', '#e0b33a', '#3c8a4a'],
    crowdDensity: 0.9,
    time: 15,
    weather: 'clear',
    weatherAmount: 0.75,
    wind: 0.2,
    arena: 'stadium',
};

export const PRESETS = {
    'Summer afternoon': {},
    'Autumn dusk': { grass: '#4a6e2a', time: 19, mowing: 'checkers', stripeWidth: 8, weather: 'overcast', weatherAmount: 0.5 },
    'Floodlit night': { grass: '#2f6a2a', time: 22, mowing: 'stripes', stripeWidth: 5.5 },
    'Rainy night': { grass: '#2f6a2a', time: 21.5, weather: 'rain', weatherAmount: 0.8, wind: 0.35 },
    'Winter snow': { grass: '#4a7a3a', time: 14, weather: 'snow', weatherAmount: 0.8, wind: 0.15, lines: '#2a56b8' },
    'Beach at sunset': { arena: 'beach', grass: '#4a8a34', time: 19.25, weather: 'clear', wind: 0.3 },
    'Rooftop by night': { arena: 'rooftop', grass: '#2f6a2a', time: 22.5, weather: 'clear', wind: 0.1 },
    'In orbit': { arena: 'space', grass: '#3b7a34', mowing: 'checkers', stripeWidth: 8, lines: '#bfefff', weather: 'clear' },
    'Training ground': {
        grass: '#5a8a3a', mowing: 'none', crowd: 'custom', crowdDensity: 0.08, boards: 'shipped',
    },
    'Circles and gold': {
        grass: '#3b7a34', mowing: 'circles', stripeWidth: 6, lines: '#fff4c4', net: '#f2c14e',
        crowd: 'custom', crowdColors: ['#f2c14e', '#1d1d1d', '#ffffff'], crowdDensity: 0.95,
    },
};

const isColor = (v) => typeof v === 'string' && /^#[0-9a-f]{6}$/i.test(v);
const isBoard = (b) => typeof b === 'string' && b.startsWith('data:image/');
const unit = (v, d) => (typeof v === 'number' && Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : d);

// The hour of a stored time, which older settings keep as a name.
export function fieldHour(time) {
    if (typeof time === 'string' && time in PRESET_HOURS) {
        return PRESET_HOURS[time];
    }
    return typeof time === 'number' && Number.isFinite(time) ? Math.min(24, Math.max(0, time)) : DEFAULT_FIELD.time;
}

// Fills and checks every field, unknown values fall back to the defaults.
export function cleanField(raw) {
    const r = raw && typeof raw === 'object' ? raw : {};
    const d = DEFAULT_FIELD;
    const width = Number(r.stripeWidth);
    const density = Number(r.crowdDensity);
    const colors = Array.isArray(r.crowdColors) ? r.crowdColors.filter(isColor).slice(0, 12) : [];
    return {
        version: FIELD_VERSION,
        grass: isColor(r.grass) ? r.grass : d.grass,
        mowing: MOWING.includes(r.mowing) ? r.mowing : d.mowing,
        stripeWidth: Number.isFinite(width) ? Math.min(20, Math.max(1, width)) : d.stripeWidth,
        lines: isColor(r.lines) ? r.lines : d.lines,
        net: isColor(r.net) ? r.net : d.net,
        boards: BOARDS.includes(r.boards) ? r.boards : d.boards,
        customBoards: Array.isArray(r.customBoards)
            ? r.customBoards.filter(isBoard).slice(0, MAX_BOARDS)
            : [],
        crowd: CROWDS.includes(r.crowd) ? r.crowd : d.crowd,
        crowdColors: colors.length ? colors : d.crowdColors.slice(),
        crowdDensity: Number.isFinite(density) ? Math.min(1, Math.max(0, density)) : d.crowdDensity,
        time: fieldHour(r.time),
        weather: WEATHERS.includes(r.weather) ? r.weather : d.weather,
        weatherAmount: unit(r.weatherAmount, d.weatherAmount),
        wind: unit(r.wind, d.wind),
        arena: ARENAS.includes(r.arena) ? r.arena : d.arena,
    };
}

export function loadField() {
    try {
        return cleanField(JSON.parse(localStorage.getItem(KEY) || '{}'));
    } catch {
        return cleanField({});
    }
}

// Returns an error message when the browser refuses to store the settings.
export function saveField(field) {
    try {
        localStorage.setItem(KEY, JSON.stringify(field));
        return null;
    } catch (err) {
        return t('field.store.failed', { reason: err.name === 'QuotaExceededError' ? t('field.store.tooLarge') : err.message });
    }
}

export function presetField(name) {
    return cleanField({ ...DEFAULT_FIELD, ...(PRESETS[name] || {}) });
}

export function exportField(field) {
    const blob = new Blob([JSON.stringify(field, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'cuju-field.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

// What each setting of an export must hold. A file with a wrong value is refused whole, so an
// import never half applies.
const CHECKS = {
    version: (v) => Number.isInteger(v) && v >= 1 && v <= FIELD_VERSION,
    grass: isColor,
    lines: isColor,
    net: isColor,
    mowing: (v) => MOWING.includes(v),
    stripeWidth: (v) => typeof v === 'number' && v >= 1 && v <= 20,
    boards: (v) => BOARDS.includes(v),
    customBoards: (v) => Array.isArray(v) && v.every(isBoard),
    crowd: (v) => CROWDS.includes(v),
    crowdColors: (v) => Array.isArray(v) && v.length > 0 && v.every(isColor),
    crowdDensity: (v) => typeof v === 'number' && v >= 0 && v <= 1,
    time: (v) => (typeof v === 'string' && v in PRESET_HOURS) || (typeof v === 'number' && v >= 0 && v <= 24),
    weather: (v) => WEATHERS.includes(v),
    weatherAmount: (v) => typeof v === 'number' && v >= 0 && v <= 1,
    wind: (v) => typeof v === 'number' && v >= 0 && v <= 1,
    arena: (v) => ARENAS.includes(v),
};
// The names of the settings in the messages of a refused import, the keys stay English.
const NAMES = {
    grass: t('field.setting.grass'), lines: t('field.setting.lines'), net: t('field.setting.net'),
    mowing: t('field.setting.mowing'), stripeWidth: t('field.setting.stripeWidth'), boards: t('field.setting.boards'),
    customBoards: t('field.setting.customBoards'), crowd: t('field.setting.crowd'), crowdColors: t('field.setting.crowdColors'),
    crowdDensity: t('field.setting.crowdDensity'), time: t('field.setting.time'), weather: t('field.setting.weather'),
    weatherAmount: t('field.setting.weatherAmount'), wind: t('field.setting.wind'), arena: t('field.setting.arena'),
    version: t('field.setting.version'),
};

// Checks a parsed export against the current field. Returns the field to apply and notes for
// the user, or throws with the reason the file is refused. Settings the file leaves out keep
// their current values, so a file without boards keeps the boards already drawn.
export function validateImport(raw, current) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
        throw new Error(t('field.import.notExport'));
    }
    const known = Object.keys(raw).filter((k) => k in CHECKS);
    if (!('version' in raw) || known.length < 2) {
        throw new Error(t('field.import.noSettings'));
    }
    if (typeof raw.version === 'number' && raw.version > FIELD_VERSION) {
        throw new Error(t('field.import.newer'));
    }
    const bad = known.filter((k) => !CHECKS[k](raw[k]));
    if (bad.length) {
        const list = bad.map((k) => NAMES[k] || k).join(', ');
        throw new Error(t('field.import.damaged', { count: bad.length, settings: list }));
    }
    const notes = [];
    const merged = { ...current };
    for (const k of known) {
        merged[k] = raw[k];
    }
    if (Array.isArray(raw.customBoards) && raw.customBoards.length > MAX_BOARDS) {
        const left = raw.customBoards.length - MAX_BOARDS;
        notes.push(t('field.import.boardsLeft', { count: left, total: raw.customBoards.length, max: MAX_BOARDS }));
    }
    const unknown = Object.keys(raw).filter((k) => !(k in CHECKS));
    if (unknown.length) {
        const names = unknown.slice(0, 4).join(', ');
        notes.push(unknown.length > 4 ? t('field.import.unknownMore', { names }) : t('field.import.unknown', { count: unknown.length, names }));
    }
    return { field: cleanField(merged), notes };
}

export async function importField(file, current = DEFAULT_FIELD) {
    if (file.size > MAX_IMPORT_BYTES) {
        throw new Error(t('field.import.tooLarge', { size: Math.ceil(file.size / 1024 / 1024), max: MAX_IMPORT_BYTES / 1024 / 1024 }));
    }
    const text = await file.text();
    let raw;
    try {
        raw = JSON.parse(text);
    } catch {
        throw new Error(t('field.import.notJson'));
    }
    return validateImport(raw, current);
}

export async function loadImages(dataUrls) {
    const out = [];
    for (const url of dataUrls) {
        try {
            out.push(await createImageBitmap(await (await fetch(url)).blob()));
        } catch {
            // A broken image is skipped.
        }
    }
    return out;
}
