// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The picture sizes of the page, shared by the clean feed, the Export video dialog and photo
// mode, with the layout that keeps the graphics in proportion at every size and the safe areas
// that keep the score, the banners and the captions inside the picture at every shape. The module
// src/cuju/render/_export/sizes.py holds the same presets and rules for the server and the command
// line, and a test keeps the two equal.

// The named sizes, each with an identifier that the feed's address and the commands accept.
export const SIZE_PRESETS = Object.freeze([
    Object.freeze({ id: '480p', width: 854, height: 480, label: '480p, 854 by 480' }),
    Object.freeze({ id: '720p', width: 1280, height: 720, label: '720p, 1280 by 720' }),
    Object.freeze({ id: '1080p', width: 1920, height: 1080, label: '1080p, 1920 by 1080' }),
    Object.freeze({ id: '1440p', width: 2560, height: 1440, label: '1440p, 2560 by 1440' }),
    Object.freeze({ id: '4k', width: 3840, height: 2160, label: '4K, 3840 by 2160' }),
    Object.freeze({ id: 'square', width: 1080, height: 1080, label: 'Square, 1080 by 1080' }),
    Object.freeze({ id: 'portrait', width: 1080, height: 1350, label: 'Portrait, 1080 by 1350' }),
    Object.freeze({ id: 'vertical', width: 1080, height: 1920, label: 'Vertical, 1080 by 1920' }),
]);

// Other names of sizes, each naming a preset or a size of its own.
export const SIZE_ALIASES = Object.freeze({
    '360p': '640x360',
    '2160p': '4k',
    uhd: '4k',
    hd: '720p',
    fhd: '1080p',
    tall: 'vertical',
});

// The size that a feed takes when its address names none.
export const DEFAULT_SIZE = '1080p';

// The smallest and largest side of a picture, and its largest area, that of 4K.
export const MIN_SIDE = 90;
export const MAX_SIDE = 3840;
export const MAX_AREA = 3840 * 2160;

// The page lays out with its shorter side at this many CSS pixels, so the graphics keep their
// proportion at every size, and a smaller picture lays out at its own size.
export const LAYOUT_SHORT = 720;

// The scale of the graphics, which makes them larger or smaller than the layout gives them.
export const MIN_GRAPHICS = 0.5;
export const MAX_GRAPHICS = 2;

// The safe areas. Auto keeps a margin of a twentieth of the picture on every side, and a tall
// picture keeps more at its top and bottom. Social keeps clear of the buttons and captions that
// apps of short videos lay over a tall picture. A number is a percentage of each side.
export const SAFE_MODES = Object.freeze(['auto', 'none', 'social']);
export const MAX_SAFE_PERCENT = 25;

const SIZE_TEXT = /^(\d{1,5})\s*[x×]\s*(\d{1,5})$/i;

// Returns the preset of a width and height, or null.
export function presetOf(width, height) {
    return SIZE_PRESETS.find((p) => p.width === width && p.height === height) || null;
}

// Returns the name of a size, the preset's identifier or the width and height as 1280x720.
export function sizeName(width, height) {
    const preset = presetOf(width, height);
    return preset ? preset.id : `${width}x${height}`;
}

// Checks a width and height, whole numbers within the sides and the area, and even when asked.
// Throws a RangeError that says what fits.
export function checkSize(width, height, { min = MIN_SIDE, max = MAX_SIDE, area = MAX_AREA, even = false } = {}) {
    for (const [name, value] of [['width', width], ['height', height]]) {
        if (!Number.isInteger(value) || value < min || value > max) {
            throw new RangeError(`The ${name} is a whole number from ${min} to ${max}, not ${value}.`);
        }
        if (even && value % 2) {
            throw new RangeError(`The ${name} is an even number for the video encoder, not ${value}.`);
        }
    }
    if (width * height > area) {
        throw new RangeError(`A picture holds at most ${area} pixels, as 3840 by 2160 does, not ${width} by ${height}.`);
    }
    return { width, height };
}

// Returns the width and height that a size names, a preset such as 1080p, an alias such as
// 2160p, or a width and height such as 1280x720. Throws a RangeError for anything else.
export function parseSize(text, limits = {}) {
    let value = String(text ?? '').trim().toLowerCase();
    value = SIZE_ALIASES[value] || value;
    const preset = SIZE_PRESETS.find((p) => p.id === value);
    if (preset) {
        return checkSize(preset.width, preset.height, limits);
    }
    const m = value.match(SIZE_TEXT);
    if (!m) {
        throw new RangeError(`A size is a width and height such as 1280x720, or one of ${SIZE_PRESETS.map((p) => p.id).join(', ')}, not ${JSON.stringify(String(text ?? ''))}.`);
    }
    return checkSize(Number(m[1]), Number(m[2]), limits);
}

// Returns the scale of the graphics that a text names, from MIN_GRAPHICS to MAX_GRAPHICS.
export function parseGraphicsScale(text) {
    if (text == null || text === '') {
        return 1;
    }
    const value = Number(text);
    if (!Number.isFinite(value) || value < MIN_GRAPHICS || value > MAX_GRAPHICS) {
        throw new RangeError(`The scale of the graphics is a number from ${MIN_GRAPHICS} to ${MAX_GRAPHICS}, not ${JSON.stringify(String(text))}.`);
    }
    return value;
}

// Returns the size in CSS pixels that the page lays out at for a picture, and the scale from
// those pixels to the picture's own. The shorter side lays out at LAYOUT_SHORT, or at its own
// size when it is smaller, and the scale of the graphics shrinks or grows the layout around them.
export function layoutFor(width, height, graphics = 1) {
    const g = Math.min(MAX_GRAPHICS, Math.max(MIN_GRAPHICS, Number(graphics) || 1));
    const scale = Math.max(1, Math.min(width, height) / LAYOUT_SHORT) * g;
    return {
        width: Math.max(1, Math.round(width / scale)),
        height: Math.max(1, Math.round(height / scale)),
        scale,
    };
}

// Returns the safe area mode that a text names, auto, none, social or a percentage. Throws a
// RangeError for anything else.
export function parseSafe(text) {
    const value = String(text ?? '').trim().toLowerCase();
    if (!value) {
        return 'auto';
    }
    if (SAFE_MODES.includes(value)) {
        return value;
    }
    const percent = Number(value.replace(/%$/, ''));
    if (value !== '' && Number.isFinite(percent) && percent >= 0 && percent <= MAX_SAFE_PERCENT) {
        return percent;
    }
    throw new RangeError(`A safe area is auto, none, social or a percentage from 0 to ${MAX_SAFE_PERCENT}, not ${JSON.stringify(String(text))}.`);
}

// Returns the margins of the safe area of a picture of the given size, in the same unit, for a
// mode of parseSafe. A wide picture keeps a twentieth of each side, a tall one a little more at
// its top and bottom, where a phone holds its own bars. Social keeps clear of the buttons along
// the right and the captions along the bottom of the apps of short videos.
export function safeArea(width, height, mode = 'auto') {
    const w = Math.max(0, width);
    const h = Math.max(0, height);
    const round = (v) => Math.round(v * 10) / 10;
    if (mode === 'none') {
        return { top: 0, right: 0, bottom: 0, left: 0 };
    }
    if (typeof mode === 'number') {
        const f = Math.min(MAX_SAFE_PERCENT, Math.max(0, mode)) / 100;
        return { top: round(h * f), right: round(w * f), bottom: round(h * f), left: round(w * f) };
    }
    const tall = shapeOf(w, h) === 'tall';
    if (mode === 'social') {
        return tall
            ? { top: round(h * 0.12), right: round(w * 0.14), bottom: round(h * 0.22), left: round(w * 0.06) }
            : { top: round(h * 0.08), right: round(w * 0.08), bottom: round(h * 0.14), left: round(w * 0.08) };
    }
    return tall
        ? { top: round(h * 0.06), right: round(w * 0.05), bottom: round(h * 0.08), left: round(w * 0.05) }
        : { top: round(h * 0.05), right: round(w * 0.05), bottom: round(h * 0.05), left: round(w * 0.05) };
}

// The shape of a picture, for rules that differ between them.
export function shapeOf(width, height) {
    const aspect = width / Math.max(1, height);
    if (aspect < 0.85) {
        return 'tall';
    }
    if (aspect < 1.25) {
        return 'square';
    }
    return 'wide';
}
