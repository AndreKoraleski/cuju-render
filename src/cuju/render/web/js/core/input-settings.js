// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The input settings of the Play page, kept in the browser. The keys of the keyboard, by the
// physical key so every layout plays the same, the dead zone of a controller's stick, and the
// device of each side when two people play. Nothing here touches the page, so the rules hold the
// same in a test.

export const STORAGE_KEY = 'cuju.input';

// Each binding presses the buttons of Gameplay Football, the ones outside GRF's 19 actions left
// out. The high pass key also slides when defending, as GRF reads one key for both.
export const BINDINGS = [
    { id: 'left', key: 'ArrowLeft', names: ['left'], label: 'Move left' },
    { id: 'right', key: 'ArrowRight', names: ['right'], label: 'Move right' },
    { id: 'up', key: 'ArrowUp', names: ['up'], label: 'Move up' },
    { id: 'down', key: 'ArrowDown', names: ['down'], label: 'Move down' },
    { id: 'short_pass', key: 'KeyS', names: ['short_pass'], label: 'Short pass' },
    { id: 'long_pass', key: 'KeyW', names: ['long_pass'], label: 'Long pass' },
    { id: 'high_pass', key: 'KeyA', names: ['high_pass', 'sliding'], label: 'High pass, or a sliding tackle when defending' },
    { id: 'shot', key: 'KeyD', names: ['shot'], label: 'Shot' },
    { id: 'sprint', key: 'KeyE', names: ['sprint'], label: 'Sprint while held' },
    { id: 'dribble', key: 'KeyC', names: ['dribble'], label: 'Dribble while held' },
];

// H, M and F keep Help, mute and fullscreen during a game, and Esc keeps the pause menu.
export const RESERVED = ['KeyH', 'KeyM', 'KeyF'];
const ALLOWED = /^(Arrow(Left|Right|Up|Down)|Key[A-Z]|Digit[0-9])$/;

// A stick counts as pushed along an axis past the dead zone. Half way is GRF's own gamepad
// player's reading and the default.
export const DEAD_ZONE = { min: 0.1, max: 0.8, step: 0.05, initial: 0.5 };

// The device of a side, chosen by the page or named, the keyboard or a controller by the slot the
// browser gives it.
export const DEVICES = ['auto', 'keyboard', 'pad0', 'pad1', 'pad2', 'pad3'];

// GRF's names of the actions of the v2 set, in order, as the engine took them.
export const ACTION_NAMES = [
    'idle', 'left', 'top left', 'top', 'top right', 'right', 'bottom right', 'bottom', 'bottom left',
    'long pass', 'high pass', 'short pass', 'shot', 'sprint', 'release direction', 'release sprint',
    'sliding', 'dribble', 'release dribble', 'built-in AI',
];

export function defaultSettings() {
    return {
        keys: Object.fromEntries(BINDINGS.map((binding) => [binding.id, binding.key])),
        deadZone: DEAD_ZONE.initial,
        devices: ['auto', 'auto'],
    };
}

// Why a key cannot take a binding, or null when it can. A key is an arrow, a letter or a digit,
// apart from the reserved ones, and belongs to one binding at a time.
export function keyProblem(settings, id, code) {
    if (RESERVED.includes(code)) {
        return 'reserved';
    }
    if (!ALLOWED.test(code)) {
        return 'invalid';
    }
    if (Object.entries(settings.keys).some(([other, used]) => other !== id && used === code)) {
        return 'taken';
    }
    return null;
}

export function keyMessage(problem) {
    return {
        reserved: 'H, M and F keep Help, mute and fullscreen. Choose another key.',
        invalid: 'Choose an arrow key, a letter or a digit.',
        taken: 'That key already has another action. Change that one first.',
    }[problem] || '';
}

// Whether two sides would share a named device, which each side keeps to itself.
export function devicesClash(devices) {
    return devices[0] !== 'auto' && devices[0] === devices[1];
}

// The settings from what storage held, each part checked on its own, so one damaged part keeps
// the defaults of that part alone.
export function normalize(stored) {
    const settings = defaultSettings();
    if (!stored || typeof stored !== 'object') {
        return settings;
    }
    const keys = stored.keys;
    if (keys && typeof keys === 'object') {
        const candidate = { ...settings.keys };
        for (const binding of BINDINGS) {
            if (typeof keys[binding.id] === 'string') {
                candidate[binding.id] = keys[binding.id];
            }
        }
        const codes = Object.values(candidate);
        const valid = BINDINGS.every((binding) => !keyProblem({ keys: candidate }, binding.id, candidate[binding.id]));
        if (valid && new Set(codes).size === codes.length) {
            settings.keys = candidate;
        }
    }
    const zone = Number(stored.deadZone);
    if (typeof stored.deadZone === 'number' && zone >= DEAD_ZONE.min && zone <= DEAD_ZONE.max) {
        settings.deadZone = zone;
    }
    const devices = stored.devices;
    if (Array.isArray(devices) && devices.length === 2 && devices.every((d) => DEVICES.includes(d)) && !devicesClash(devices)) {
        settings.devices = [devices[0], devices[1]];
    }
    return settings;
}

// Storage may be missing or refuse, in a private window or with blocked site data, and the
// defaults then serve.
export function loadSettings(storage = globalThis.localStorage) {
    try {
        return normalize(JSON.parse(storage.getItem(STORAGE_KEY) || 'null'));
    } catch {
        return defaultSettings();
    }
}

// Returns whether storage kept the settings. They hold for the visit either way.
export function saveSettings(settings, storage = globalThis.localStorage) {
    try {
        storage.setItem(STORAGE_KEY, JSON.stringify(settings));
        return true;
    } catch {
        return false;
    }
}

// The inputs of each physical key.
export function keyMap(settings) {
    const map = {};
    for (const binding of BINDINGS) {
        map[settings.keys[binding.id]] = binding.names;
    }
    return map;
}

// The name of a physical key as its keycap shows it.
export function keyLabel(code) {
    const arrows = { ArrowLeft: '←', ArrowRight: '→', ArrowUp: '↑', ArrowDown: '↓' };
    return arrows[code] || code.replace(/^Key|^Digit/, '');
}

// The directions of a stick, each axis past the dead zone, x to the right and y down.
export function stickDirections(x, y, deadZone) {
    const held = [];
    if (x < -deadZone) {
        held.push('left');
    } else if (x > deadZone) {
        held.push('right');
    }
    if (y < -deadZone) {
        held.push('up');
    } else if (y > deadZone) {
        held.push('down');
    }
    return held;
}

export function actionName(index) {
    return Number.isInteger(index) && ACTION_NAMES[index] ? ACTION_NAMES[index] : 'unknown';
}
