// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The parts of photo mode that need no page and no three.js, the film looks, the frame guides,
// the sizes of a saved photo, its file name, the checked settings and the reading of a
// controller. photo.js draws and steers with them, and tests/web/photo.mjs tests them.

import { SIZE_ALIASES, SIZE_PRESETS } from './sizes.js';

// A look grades the finished picture. Exposure is in stops, temperature and tint lean the white
// balance from minus one to one, contrast and saturation scale around their neutral value of one,
// fade lifts the blacks, mono turns the picture to black and white, shadows and highlights tint
// the dark and the bright parts, and gain scales each channel.
export const LOOKS = Object.freeze([
    look('natural', 'Natural', {}),
    look('warm', 'Warm', {
        exposure: 0.05, temperature: 0.45, tint: 0.05, contrast: 1.05, saturation: 1.08,
        highlights: [0.03, 0.015, -0.01],
    }),
    look('cold', 'Cold', {
        exposure: -0.03, temperature: -0.45, contrast: 1.06, saturation: 0.9,
        shadows: [-0.01, 0.01, 0.04],
    }),
    look('noir', 'Noir', {
        exposure: -0.05, contrast: 1.4, saturation: 0, mono: 1, gain: [1.04, 1.04, 1.04],
    }),
    look('vintage', 'Vintage', {
        temperature: 0.2, contrast: 0.9, saturation: 0.7, fade: 0.08,
        shadows: [0.02, 0.03, 0.01], highlights: [0.03, 0.02, -0.03], gain: [1.02, 0.99, 0.88],
    }),
    look('vivid', 'Vivid', {
        exposure: 0.05, contrast: 1.15, saturation: 1.4,
    }),
    look('matchday', 'Matchday', {
        exposure: 0.04, temperature: 0.1, contrast: 1.12, saturation: 1.2,
        shadows: [-0.02, 0.01, 0.035], highlights: [0.035, 0.015, -0.015],
    }),
]);

function look(id, label, values) {
    return Object.freeze({
        id,
        label,
        exposure: 0,
        temperature: 0,
        tint: 0,
        contrast: 1,
        saturation: 1,
        fade: 0,
        mono: 0,
        shadows: [0, 0, 0],
        highlights: [0, 0, 0],
        gain: [1, 1, 1],
        ...values,
    });
}

export function lookById(id) {
    return LOOKS.find((l) => l.id === id) || LOOKS[0];
}

// The look after or before the given one, round the list.
export function nextLook(id, step = 1) {
    const i = Math.max(0, LOOKS.findIndex((l) => l.id === id));
    return LOOKS[(((i + step) % LOOKS.length) + LOOKS.length) % LOOKS.length].id;
}

export const GUIDES = Object.freeze([
    { id: 'off', label: 'Off' },
    { id: 'thirds', label: 'Rule of thirds' },
    { id: 'golden', label: 'Golden ratio' },
    { id: 'center', label: 'Center cross' },
    { id: 'crop-16-9', label: 'Crop frame, 16 by 9' },
    { id: 'crop-4-5', label: 'Crop frame, 4 by 5' },
]);

export function nextGuide(id, step = 1) {
    const i = Math.max(0, GUIDES.findIndex((g) => g.id === id));
    return GUIDES[(((i + step) % GUIDES.length) + GUIDES.length) % GUIDES.length].id;
}

// The window's own size and the shared sizes of sizes.js, each named by its width and height.
export const RESOLUTIONS = Object.freeze([
    { id: 'window', label: 'Window size' },
    ...SIZE_PRESETS.map((p) => Object.freeze({ id: `${p.width}x${p.height}`, width: p.width, height: p.height, label: p.label, preset: p.id })),
]);

// The smallest and largest side of a saved photo.
export const MIN_SIDE = 16;
export const MAX_SIDE = 8192;

// The width and height of a photo for a choice of RESOLUTIONS, a string such as '1280x720', or
// an object with width and height. Window is the window's own size. A size out of range throws.
export function resolveResolution(choice, windowWidth, windowHeight, max = MAX_SIDE) {
    let width;
    let height;
    if (choice == null || choice === 'window') {
        width = Math.round(windowWidth);
        height = Math.round(windowHeight);
    } else if (typeof choice === 'object') {
        ({ width, height } = choice);
    } else {
        const named = String(choice).toLowerCase();
        const known = RESOLUTIONS.find((r) => r.id === choice || r.preset === (SIZE_ALIASES[named] || named));
        const m = String(choice).match(/^(\d+)\s*[x×]\s*(\d+)$/i);
        if (known) {
            ({ width, height } = known);
        } else if (m) {
            width = Number(m[1]);
            height = Number(m[2]);
        } else {
            throw new RangeError(`Unknown resolution ${JSON.stringify(choice)}, use window, a width and height, or one of ${RESOLUTIONS.map((r) => r.id).join(', ')}.`);
        }
    }
    const limit = Math.min(MAX_SIDE, Math.max(MIN_SIDE, Math.floor(max)));
    for (const [name, value] of [['width', width], ['height', height]]) {
        if (!Number.isInteger(value) || value < MIN_SIDE || value > limit) {
            throw new RangeError(`The ${name} of a photo is a whole number from ${MIN_SIDE} to ${limit}, not ${value}.`);
        }
    }
    return { width, height };
}

// The part of a view of the given size that a photo of another shape shows, centered. A narrower
// photo keeps the height of the view and a wider one keeps its width.
export function captureRegion(viewWidth, viewHeight, outWidth, outHeight) {
    return fitAspect({ x: 0, y: 0, width: viewWidth, height: viewHeight }, outWidth / outHeight);
}

// The vertical field of view in degrees of a photo of another shape, so it shows exactly the
// region of captureRegion.
export function captureFov(fov, viewAspect, outAspect) {
    if (!(outAspect > viewAspect)) {
        return fov;
    }
    const half = Math.tan((fov * Math.PI) / 360) * (viewAspect / outAspect);
    return (Math.atan(half) * 360) / Math.PI;
}

// The largest rectangle of the given aspect inside a rectangle, centered in it.
export function fitAspect(rect, aspect) {
    if (rect.width / rect.height > aspect) {
        const width = rect.height * aspect;
        return { x: rect.x + (rect.width - width) / 2, y: rect.y, width, height: rect.height };
    }
    const height = rect.width / aspect;
    return { x: rect.x, y: rect.y + (rect.height - height) / 2, width: rect.width, height };
}

const GOLDEN = (Math.sqrt(5) - 1) / 2;

// The lines of a guide over a view of the given size, each [x1, y1, x2, y2] in pixels, and the
// frame, the part of the view that a saved photo or a crop frame keeps, or null when that is the
// whole view. Output is the size of the photo, or null for the window's size.
export function guideGeometry(kind, width, height, output = null) {
    const region = output ? captureRegion(width, height, output.width, output.height) : { x: 0, y: 0, width, height };
    let frame = region;
    if (kind === 'crop-16-9' || kind === 'crop-4-5') {
        frame = fitAspect(region, kind === 'crop-16-9' ? 16 / 9 : 4 / 5);
    }
    const lines = [];
    const cut = (fractions) => {
        for (const f of fractions) {
            const x = frame.x + f * frame.width;
            const y = frame.y + f * frame.height;
            lines.push([x, frame.y, x, frame.y + frame.height]);
            lines.push([frame.x, y, frame.x + frame.width, y]);
        }
    };
    if (kind === 'thirds') {
        cut([1 / 3, 2 / 3]);
    } else if (kind === 'golden') {
        cut([1 - GOLDEN, GOLDEN]);
    } else if (kind === 'center') {
        const cx = frame.x + frame.width / 2;
        const cy = frame.y + frame.height / 2;
        const arm = Math.min(frame.width, frame.height) * 0.05;
        lines.push([cx - arm, cy, cx + arm, cy], [cx, cy - arm, cx, cy + arm]);
    }
    const whole = frame.width >= width - 0.5 && frame.height >= height - 0.5;
    return { kind, lines, frame: whole ? null : frame };
}

// The name of a saved photo, from the recording or source and the frame shown.
export function photoFileName(recording, frame) {
    const slug = String(recording ?? '').toLowerCase().replace(/[^a-z0-9._-]+/g, '-')
        .replace(/-{2,}/g, '-').replace(/^[-.]+|[-.]+$/g, '').slice(0, 64).replace(/[-.]+$/, '') || 'view';
    const part = Number.isInteger(frame) && frame >= 0 ? `-${frame}` : '';
    return `cuju-photo-${slug}${part}.png`;
}

// The focus distance in meters and its slider, from 0 to 1000 on a logarithmic scale.
export const FOCUS_MIN = 0.5;
export const FOCUS_MAX = 300;

export function focusToSlider(meters) {
    const m = Math.min(FOCUS_MAX, Math.max(FOCUS_MIN, meters));
    return Math.round((1000 * Math.log(m / FOCUS_MIN)) / Math.log(FOCUS_MAX / FOCUS_MIN));
}

export function sliderToFocus(value) {
    const v = Math.min(1000, Math.max(0, Number(value) || 0));
    return Math.round(FOCUS_MIN * Math.pow(FOCUS_MAX / FOCUS_MIN, v / 1000) * 10) / 10;
}

export const DEFAULTS = Object.freeze({
    look: 'natural',
    vignette: 0.2,
    grain: 0.05,
    focus: 'auto',
    aperture: 0.15,
    fov: 40,
    roll: 0,
    guide: 'off',
    resolution: 'window',
});

// The ranges of the numeric settings, field of view and roll in degrees.
export const RANGES = Object.freeze({
    vignette: [0, 1],
    grain: [0, 1],
    aperture: [0, 1],
    fov: [10, 100],
    roll: [-90, 90],
});

// The settings after a change, each value checked. An unknown name or a value out of place
// throws with a message that says what fits, so a script learns its mistake.
export function normalizeSettings(current, patch) {
    const next = { ...DEFAULTS, ...current };
    if (patch == null) {
        return next;
    }
    if (typeof patch !== 'object') {
        throw new TypeError('Photo settings are an object, such as { look: \'noir\', vignette: 0.4 }.');
    }
    for (const [key, value] of Object.entries(patch)) {
        if (key === 'look') {
            if (!LOOKS.some((l) => l.id === value)) {
                throw new RangeError(`Unknown look ${JSON.stringify(value)}, use one of ${LOOKS.map((l) => l.id).join(', ')}.`);
            }
            next.look = value;
        } else if (key === 'guide') {
            if (!GUIDES.some((g) => g.id === value)) {
                throw new RangeError(`Unknown guide ${JSON.stringify(value)}, use one of ${GUIDES.map((g) => g.id).join(', ')}.`);
            }
            next.guide = value;
        } else if (key === 'focus') {
            if (value === 'auto' || value === null) {
                next.focus = 'auto';
            } else if (typeof value === 'number' && Number.isFinite(value)) {
                next.focus = Math.min(FOCUS_MAX, Math.max(FOCUS_MIN, value));
            } else {
                throw new RangeError(`The focus is 'auto' or a distance in meters from ${FOCUS_MIN} to ${FOCUS_MAX}.`);
            }
        } else if (key === 'resolution') {
            const size = resolveResolution(value, 1920, 1080);
            // A preset's name keeps the identifier of its width and height, as the panel lists it.
            const listed = RESOLUTIONS.find((r) => r.width === size.width && r.height === size.height);
            next.resolution = typeof value === 'object' ? { width: value.width, height: value.height }
                : typeof value === 'string' && value !== 'window' && listed ? listed.id : value;
        } else if (key in RANGES) {
            const [lo, hi] = RANGES[key];
            if (typeof value !== 'number' || !Number.isFinite(value)) {
                throw new RangeError(`The ${key} is a number from ${lo} to ${hi}.`);
            }
            next[key] = Math.min(hi, Math.max(lo, value));
        } else {
            throw new RangeError(`Unknown photo setting ${JSON.stringify(key)}, use ${Object.keys(DEFAULTS).join(', ')}.`);
        }
    }
    return next;
}

// The buttons of a controller with the standard mapping that photo mode uses, by index.
export const PAD_BUTTONS = Object.freeze({
    0: 'save', 1: 'leave', 2: 'interface', 3: 'guide', 4: 'previousLook', 5: 'nextLook',
});

function stick(x, y, deadzone) {
    const length = Math.hypot(x, y);
    if (!(length > deadzone)) {
        return [0, 0];
    }
    const scale = Math.min(1, (length - deadzone) / (1 - deadzone)) / length;
    return [x * scale, y * scale];
}

const buttonValue = (b) => (typeof b === 'number' ? b : (b ? (b.pressed ? Math.max(0.5, b.value || 1) : b.value || 0) : 0));

// What a controller asks for, from its axes and buttons and the buttons held at the last poll.
// Move and look are the sticks past the dead zone, rise is the right trigger less the left one,
// zoom and roll are the vertical and horizontal pad, and pressed names the buttons of PAD_BUTTONS
// pressed since the last poll.
export function readPad(pad, before = [], deadzone = 0.15) {
    const axes = (pad && pad.axes) || [];
    const raw = (pad && pad.buttons) || [];
    const value = (i) => buttonValue(raw[i]);
    const buttons = raw.map((b, i) => value(i) > 0.5);
    const pressed = Object.entries(PAD_BUTTONS)
        .filter(([i]) => buttons[i] && !before[i]).map(([, name]) => name);
    return {
        move: stick(axes[0] || 0, axes[1] || 0, deadzone),
        look: stick(axes[2] || 0, axes[3] || 0, deadzone),
        rise: value(7) - value(6),
        zoom: (buttons[13] ? 1 : 0) - (buttons[12] ? 1 : 0),
        roll: (buttons[15] ? 1 : 0) - (buttons[14] ? 1 : 0),
        pressed,
        buttons,
    };
}
