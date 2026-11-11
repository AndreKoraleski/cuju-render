// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The address of the clean feed, /feed with its query, read into checked options and written
// back. The page of the feed, the Copy feed address dialog and the tests read it here, and
// src/cuju/render/_export/feed.py reads and writes the same query for the server and the command
// line. A value out of place falls back to its default and names itself among the problems, so a
// feed always shows something.

import { DEFAULT_SIZE, layoutFor, parseGraphicsScale, parseSafe, parseSize, sizeName } from './sizes.js';

// The sources a feed follows. A recording plays one recording of the library, latest the newest
// recording, live the newest live source or one named by identifier or title, tournament the
// newest finished match of the newest or a named tournament, queue the newest finished request,
// and auto a live source while one streams and the newest recording otherwise.
export const FEED_SOURCES = Object.freeze(['auto', 'live', 'latest', 'tournament', 'queue', 'recording']);
export const FEED_CAMERAS = Object.freeze(['broadcast', 'tactical', 'goal', 'ball', 'owner']);
export const FEED_ARENAS = Object.freeze(['stadium', 'beach', 'rooftop', 'space', 'neon']);
export const FEED_HOURS = Object.freeze({ dawn: 6.5, day: 15, dusk: 19, night: 22 });
export const FEED_QUALITIES = Object.freeze(['low', 'medium', 'high']);
export const FEED_THEMES = Object.freeze(['dark', 'light']);
// Named backgrounds, the colors that keying in a streaming program knows, and transparent.
export const FEED_BACKGROUNDS = Object.freeze({
    transparent: 'transparent',
    black: '#000000',
    green: '#00b140',
    blue: '#0047bb',
    magenta: '#ff00ff',
    white: '#ffffff',
});
export const FEED_LAYERS = Object.freeze(['full', 'graphics']);
export const MAX_FEED_FPS = 60;

export const FEED_DEFAULTS = Object.freeze({
    source: 'auto',
    size: DEFAULT_SIZE,
    width: 1920,
    height: 1080,
    scale: 1,
    safe: 'auto',
    bg: 'black',
    audio: false,
    volume: 0.5,
    fps: 0,
    camera: 'broadcast',
    loop: false,
    broadcast: true,
    show: true,
    score: true,
    captions: false,
    layer: 'full',
    slate: true,
    quality: 'high',
    theme: 'dark',
    arena: null,
    time: null,
    t: null,
});

// The order of the keys in a written address, the source and the size first.
const ORDER = ['source', 'size', 'scale', 'safe', 'bg', 'layer', 'audio', 'volume', 'fps', 'camera', 'loop',
    'broadcast', 'show', 'score', 'captions', 'slate', 'quality', 'theme', 'arena', 'time', 't'];

// The rows of the server's list of feeds that name one live source or one tournament, as entries
// of the Follows list of the Copy feed address dialog, each with its label made a sentence.
export function namedSources(rows, taken = []) {
    return (Array.isArray(rows) ? rows : [])
        .filter((row) => row && typeof row.source === 'string' && /^(live|tournament):./.test(row.source)
            && !taken.includes(row.source))
        .map((row) => {
            // A row without a label shows its source as the address writes it.
            const label = row.label ? String(row.label) : '';
            return [row.source, label ? label.charAt(0).toUpperCase() + label.slice(1) : row.source];
        });
}

// The color scheme of the frame of /feed for a feed's theme, the scheme of the page inside it.
export function frameScheme(theme) {
    return theme === 'light' ? 'light' : 'dark';
}

// Returns what a source names, its kind and the identifier, title or tournament it picks.
export function parseSource(text) {
    const value = String(text ?? '').trim();
    if (!value) {
        return { kind: 'auto', id: '' };
    }
    const colon = value.indexOf(':');
    const head = (colon >= 0 ? value.slice(0, colon) : value).toLowerCase();
    const rest = colon >= 0 ? value.slice(colon + 1).trim() : '';
    if (FEED_SOURCES.includes(head)) {
        if (head === 'recording' && !rest) {
            throw new RangeError('A recording source names the identifier of a recording, as recording:m-20261106-105640-3a3f.');
        }
        if ((head === 'auto' || head === 'latest' || head === 'queue') && rest) {
            throw new RangeError(`The source ${head} takes nothing after it, not ${JSON.stringify(value)}.`);
        }
        return { kind: head, id: rest };
    }
    if (/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(value)) {
        return { kind: 'recording', id: value };
    }
    throw new RangeError(`A source is ${FEED_SOURCES.join(', ')}, a kind with a name after a colon such as live:Evaluation, or the identifier of a recording, not ${JSON.stringify(value)}.`);
}

// Writes a parsed source back as the address names it.
export function sourceText(source) {
    return source.id ? `${source.kind}:${source.id}` : source.kind;
}

// Returns the CSS color of a background, a name of FEED_BACKGROUNDS or a hex color.
export function parseBackground(text) {
    const value = String(text ?? '').trim().toLowerCase();
    if (value in FEED_BACKGROUNDS) {
        return FEED_BACKGROUNDS[value];
    }
    const hex = value.replace(/^#/, '');
    if (/^([0-9a-f]{3}|[0-9a-f]{6})$/.test(hex)) {
        const full = hex.length === 3 ? [...hex].map((c) => c + c).join('') : hex;
        return `#${full}`;
    }
    throw new RangeError(`A background is ${Object.keys(FEED_BACKGROUNDS).join(', ')} or a hex color such as 1a1a1a, not ${JSON.stringify(String(text ?? ''))}.`);
}

function parseFlag(text, name) {
    const value = String(text ?? '').trim().toLowerCase();
    if (['1', 'true', 'yes', 'on', ''].includes(value)) {
        return true;
    }
    if (['0', 'false', 'no', 'off'].includes(value)) {
        return false;
    }
    throw new RangeError(`The option ${name} is 1 or 0, not ${JSON.stringify(String(text))}.`);
}

function parseNumber(text, name, low, high) {
    const value = Number(String(text ?? '').trim());
    if (String(text ?? '').trim() === '' || !Number.isFinite(value) || value < low || value > high) {
        throw new RangeError(`The option ${name} is a number from ${low} to ${high}, not ${JSON.stringify(String(text))}.`);
    }
    return value;
}

function parseChoice(text, name, choices) {
    const value = String(text ?? '').trim().toLowerCase();
    if (!choices.includes(value)) {
        throw new RangeError(`The option ${name} is one of ${choices.join(', ')}, not ${JSON.stringify(String(text))}.`);
    }
    return value;
}

function parseHour(text) {
    const value = String(text ?? '').trim().toLowerCase();
    if (value in FEED_HOURS) {
        return FEED_HOURS[value];
    }
    return parseNumber(value, 'time', 0, 24);
}

// Reads the query of a feed's address, a string or URLSearchParams, into options and problems.
// The size comes from size, or from w and h together, which win over it.
export function parseFeed(query) {
    const params = query instanceof URLSearchParams ? query : new URLSearchParams(String(query ?? '').replace(/^\?/, ''));
    const options = { ...FEED_DEFAULTS };
    const problems = [];
    const read = (key, parse) => {
        if (!params.has(key)) {
            return;
        }
        try {
            options[key] = parse(params.get(key));
        } catch (err) {
            problems.push(err.message);
        }
    };
    try {
        options.sourceParsed = parseSource(params.get('source'));
    } catch (err) {
        problems.push(err.message);
        options.sourceParsed = parseSource('auto');
    }
    options.source = sourceText(options.sourceParsed);
    let size = parseSize(DEFAULT_SIZE);
    if (params.has('size')) {
        try {
            size = parseSize(params.get('size'));
        } catch (err) {
            problems.push(err.message);
        }
    }
    const w = params.get('w') ?? params.get('width');
    const h = params.get('h') ?? params.get('height');
    if (w != null || h != null) {
        try {
            size = parseSize(`${w ?? size.width}x${h ?? size.height}`);
        } catch (err) {
            problems.push(err.message);
        }
    }
    options.width = size.width;
    options.height = size.height;
    options.size = sizeName(size.width, size.height);
    read('scale', parseGraphicsScale);
    read('safe', parseSafe);
    if (params.has('bg') || params.has('background')) {
        try {
            const given = params.get('bg') ?? params.get('background');
            parseBackground(given);
            options.bg = String(given).trim().toLowerCase().replace(/^#/, '');
        } catch (err) {
            problems.push(err.message);
        }
    }
    read('layer', (v) => parseChoice(v, 'layer', FEED_LAYERS));
    for (const key of ['audio', 'loop', 'broadcast', 'show', 'score', 'captions', 'slate']) {
        read(key, (v) => parseFlag(v, key));
    }
    read('volume', (v) => parseNumber(v, 'volume', 0, 1));
    read('fps', (v) => {
        const fps = parseNumber(v, 'fps', 0, MAX_FEED_FPS);
        if (!Number.isInteger(fps)) {
            throw new RangeError(`The option fps is a whole number from 0 to ${MAX_FEED_FPS}, not ${JSON.stringify(String(v))}.`);
        }
        return fps;
    });
    read('camera', (v) => parseChoice(v, 'camera', FEED_CAMERAS));
    read('quality', (v) => parseChoice(v, 'quality', FEED_QUALITIES));
    read('theme', (v) => parseChoice(v, 'theme', FEED_THEMES));
    read('arena', (v) => parseChoice(v, 'arena', FEED_ARENAS));
    read('time', parseHour);
    read('t', (v) => parseNumber(v, 't', 0, 1e6));
    options.background = parseBackground(options.bg);
    options.layout = layoutFor(options.width, options.height, options.scale);
    return { options, problems };
}

function written(key, value) {
    if (typeof value === 'boolean') {
        return value ? '1' : '0';
    }
    return String(value);
}

// Writes the query of a feed's address for options, the source and the size always and every
// other option that differs from its default. Takes the options of parseFeed or a partial set.
export function feedQuery(given = {}) {
    const options = { ...FEED_DEFAULTS, ...given };
    if (given.width != null && given.height != null && given.size == null) {
        options.size = sizeName(given.width, given.height);
    }
    const params = new URLSearchParams();
    for (const key of ORDER) {
        const value = options[key];
        if (key !== 'source' && key !== 'size' && (value === FEED_DEFAULTS[key] || value == null)) {
            continue;
        }
        params.set(key, written(key, value));
    }
    return params.toString().replace(/%3A/g, ':');
}

// Returns the whole address of a feed on the server at base, such as http://127.0.0.1:8780/.
export function feedAddress(base, options = {}) {
    const root = String(base || '').replace(/\/+$/, '');
    return `${root}/feed?${feedQuery(options)}`;
}
