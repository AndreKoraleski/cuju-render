// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The keyboard kit of the page. Every shortcut the page shows, in a message, a table of Help, a
// hint of the command palette or a tooltip, comes from here, so one change updates every place.
// A shortcut is a chord of key names, such as `Ctrl K` or `Shift + ?`, written in a message
// between backticks, and each key shows as a keycap, a kbd element with the legend that
// keyboards print on that key and the shape of that key, wide for Space, Enter, Shift and
// Backspace and square for the rest. A screen reader hears the full name of each key in the
// language of the page, such as Control K, from the language files.
//
// Keys whose keyboards print a word, such as Esc, Ctrl, Alt, Del, Home and End, the F keys,
// letters and digits, show that word. Keys that keyboards mark with a symbol, Space, Enter,
// Shift, Tab, Backspace and the arrows, show the symbol as an icon, drawn as an SVG element, so
// no font lacks it. Mac keyboards print the symbols of Command, Option and Control, so on a Mac
// those show as icons too, and the page's primary modifier, Mod, is Command there and Ctrl
// elsewhere, as the page's own shortcuts read either. Elsewhere Ctrl and Alt stay words, since
// PC and ABNT2 keyboards print them so and a symbol would read as a Mac key.
//
// The icons are those of Lucide 1.72.0, https://lucide.dev, under the ISC License, with the
// icons that came from Feather under the MIT License, read as shapes from vendor/lucide, each in
// a box of 24 by 24 and stroked with the color of the text.

import { messages, setCodeKind, t } from './i18n.js';
import { LUCIDE } from '../../vendor/lucide/icons.js';

const SVG = 'http://www.w3.org/2000/svg';
// The Lucide icon of each key that keyboards mark with a symbol.
const ICONS = {
    space: 'space',
    enter: 'corner-down-left',
    shift: 'arrow-big-up',
    backspace: 'delete',
    tab: 'arrow-right-to-line',
    command: 'command',
    option: 'option',
    control: 'chevron-up',
    left: 'arrow-left',
    right: 'arrow-right',
    up: 'arrow-up',
    down: 'arrow-down',
};

// Whether the page runs on a Mac, whose keyboards print the symbols of their modifiers.
export function isMac() {
    if (typeof navigator === 'undefined') {
        return false;
    }
    const platform = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || '';
    return /mac|iphone|ipad|ipod/i.test(platform);
}

// The keys by id, each with its legend as printed, its icon, its plain legend for a text without
// elements, its shape and the id of its name in the language files.
const KEYS = {
    ctrl: { legend: 'Ctrl', mac: { icon: 'control', text: '⌃' } },
    alt: { legend: 'Alt', mac: { icon: 'option', text: '⌥' } },
    meta: { legend: 'Win', mac: { icon: 'command', text: '⌘' } },
    shift: { icon: 'shift', text: '⇧', shape: 'wide' },
    space: { icon: 'space', shape: 'space' },
    enter: { icon: 'enter', text: '↵', shape: 'wide' },
    tab: { icon: 'tab', text: '⇥', shape: 'wide' },
    backspace: { icon: 'backspace', text: '⌫', shape: 'wide' },
    left: { icon: 'left', text: '←' },
    right: { icon: 'right', text: '→' },
    up: { icon: 'up', text: '↑' },
    down: { icon: 'down', text: '↓' },
    esc: { legend: 'Esc' },
    delete: { legend: 'Del' },
    insert: { legend: 'Ins' },
    home: { legend: 'Home' },
    end: { legend: 'End' },
    pageup: { legend: 'PgUp' },
    pagedown: { legend: 'PgDn' },
    capslock: { legend: 'Caps Lock', shape: 'wide' },
};

// The names a message or a binding may give a key, by the id of the key. Mod is the page's
// primary modifier.
const ALIASES = {
    ctrl: 'ctrl', control: 'ctrl', alt: 'alt', option: 'alt', opt: 'alt', meta: 'meta', cmd: 'meta', command: 'meta',
    win: 'meta', super: 'meta', shift: 'shift', space: 'space', spacebar: 'space', ' ': 'space', enter: 'enter',
    return: 'enter', tab: 'tab', backspace: 'backspace', esc: 'esc', escape: 'esc', del: 'delete', delete: 'delete',
    ins: 'insert', insert: 'insert', home: 'home', end: 'end', pgup: 'pageup', pageup: 'pageup', pgdn: 'pagedown',
    pagedown: 'pagedown', capslock: 'capslock', left: 'left', arrowleft: 'left', '←': 'left', right: 'right',
    arrowright: 'right', '→': 'right', up: 'up', arrowup: 'up', '↑': 'up', down: 'down', arrowdown: 'down',
    '↓': 'down',
};

// The signs of the codes of KeyboardEvent, by code, as a US layout prints them.
const CODE_SIGNS = {
    BracketLeft: '[', BracketRight: ']', Comma: ',', Period: '.', Slash: '/', Backslash: '\\', Semicolon: ';',
    Quote: "'", Minus: '-', Equal: '=', Backquote: '`', NumpadAdd: '+', NumpadSubtract: '-', NumpadMultiply: '*',
    NumpadDivide: '/', NumpadDecimal: '.', NumpadEnter: 'enter',
};

// The id of a key from one of its names, the key or the code of a KeyboardEvent, a function
// key, or a single printed character, else null.
export function keyId(name) {
    const raw = String(name);
    const lower = raw.toLowerCase();
    const code = /^(?:Key([A-Z])|Digit(\d)|Numpad(\d))$/.exec(raw);
    if (code) {
        return code[1] || code[2] || code[3];
    }
    if (Object.prototype.hasOwnProperty.call(CODE_SIGNS, raw)) {
        return CODE_SIGNS[raw] === 'enter' ? 'enter' : CODE_SIGNS[raw];
    }
    const side = /^(Shift|Control|Alt|Meta|OS)(Left|Right)$/.exec(raw);
    if (side) {
        return { Shift: 'shift', Control: 'ctrl', Alt: 'alt', Meta: 'meta', OS: 'meta' }[side[1]];
    }
    if (lower === 'mod') {
        return isMac() ? 'meta' : 'ctrl';
    }
    if (Object.prototype.hasOwnProperty.call(ALIASES, lower)) {
        return ALIASES[lower];
    }
    if (/^f([1-9]|1[0-9]|2[0-4])$/i.test(raw)) {
        return raw.toUpperCase();
    }
    // A key that prints one character, a letter, a digit or a sign, such as ?, [ or +.
    if ([...raw].length === 1 && /\S/.test(raw)) {
        return raw.length === 1 && /[a-z]/.test(raw) ? raw.toUpperCase() : raw;
    }
    return null;
}

// The keys of a chord, such as Ctrl K, Ctrl+K or Shift + ?, as ids, or null for any text that is
// not a chord, such as a command.
export function chordKeys(text) {
    const raw = String(text).trim();
    if (!raw) {
        return null;
    }
    if (keyId(raw)) {
        return [keyId(raw)];
    }
    // Keys part by spaces or by a plus, and a plus at the end is the plus key itself.
    const tokens = raw.split(/\s*\+\s*(?=\S)|\s+/).filter(Boolean);
    const ids = tokens.map(keyId);
    return ids.length > 1 && ids.every(Boolean) ? ids : null;
}

function info(id) {
    const key = KEYS[id];
    if (!key) {
        return { legend: id, text: id, shape: 'square' };
    }
    const own = isMac() && key.mac ? { ...key, ...key.mac, legend: undefined } : key;
    return { legend: own.legend, icon: own.icon, text: own.text || own.legend, shape: own.shape || 'square' };
}

// The full name of a key in the language of the page, such as Control for Ctrl.
export function keyName(id) {
    if (!KEYS[id]) {
        return id;
    }
    return t(`keys.name.${id === 'meta' && isMac() ? 'command' : id === 'alt' && isMac() ? 'option' : id}`);
}

// A chord as text without elements, the legends joined by spaces, such as Ctrl K or ⇧ ?, and
// Space by its name, for a title, a notification or a canvas.
export function chordText(text) {
    const ids = chordKeys(text);
    if (!ids) {
        return String(text);
    }
    return ids.map((id) => (id === 'space' ? keyName(id) : info(id).text)).join(' ');
}

// A chord as its full names, such as Control K, for a screen reader.
export function chordName(text) {
    const ids = chordKeys(text);
    return ids ? ids.map(keyName).join(' ') : String(text);
}

function icon(name) {
    const svg = document.createElementNS(SVG, 'svg');
    for (const [k, v] of Object.entries({
        viewBox: '0 0 24 24', width: '1em', height: '1em', fill: 'none', stroke: 'currentColor', 'stroke-width': '2',
        'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', focusable: 'false',
    })) {
        svg.setAttribute(k, v);
    }
    for (const [tag, attributes] of LUCIDE[ICONS[name]] || []) {
        const shape = document.createElementNS(SVG, tag);
        for (const [k, v] of Object.entries(attributes)) {
            shape.setAttribute(k, v);
        }
        svg.append(shape);
    }
    return svg;
}

// One keycap, a kbd element with the legend or the icon of the key and the shape of the key.
export function keycap(id) {
    const key = info(id);
    const node = document.createElement('kbd');
    node.className = `keycap keycap-${key.shape}`;
    if (key.icon) {
        node.append(icon(key.icon));
    } else {
        node.textContent = key.legend;
    }
    return node;
}

// A chord as keycaps inside a kbd element, which a screen reader reads by the full names of the
// keys, or a code element for a text that is no chord.
export function chord(text) {
    const ids = chordKeys(text);
    if (!ids) {
        const code = document.createElement('code');
        code.textContent = String(text);
        return code;
    }
    const node = document.createElement('kbd');
    node.className = 'chord';
    const name = document.createElement('span');
    name.className = 'sr-only';
    name.textContent = ids.map(keyName).join(' ');
    const caps = document.createElement('span');
    caps.className = 'chord-keys';
    caps.setAttribute('aria-hidden', 'true');
    caps.append(...ids.map(keycap));
    node.append(name, caps);
    return node;
}

// Draws every plain kbd element under root as keycaps, the key named by its data-key or its
// text, such as the shortcuts of the static markup. A kbd that names no key stays as it is.
export function upgradeKeys(root = typeof document === 'undefined' ? null : document) {
    if (!root || !root.querySelectorAll) {
        return;
    }
    for (const node of root.querySelectorAll('kbd:not(.keycap):not(.chord)')) {
        if (node.closest('.chord')) {
            continue;
        }
        const text = node.dataset.key || node.textContent;
        if (chordKeys(text)) {
            node.replaceWith(chord(text));
        }
    }
}

// The attributes that static markup translates, as i18n.js reads them from data-i18n-<attribute>.
const ATTRIBUTES = ['title', 'aria-label', 'placeholder', 'alt', 'aria-description', 'aria-roledescription', 'label'];

// i18n.js translates the static markup as it loads, before this module tells it how to show a
// shortcut, so the shortcuts in those texts came out as code and the attributes named their keys
// as the messages write them. Here they take their keycaps and their legends, once.
export function upgradeStatic(root = typeof document === 'undefined' ? null : document) {
    if (!root || !root.querySelectorAll) {
        return;
    }
    for (const node of root.querySelectorAll('[data-i18n] code')) {
        if (chordKeys(node.textContent)) {
            node.replaceWith(chord(node.textContent));
        }
    }
    const raw = messages();
    for (const name of ATTRIBUTES) {
        for (const node of root.querySelectorAll(`[data-i18n-${name}]`)) {
            const id = node.getAttribute(`data-i18n-${name}`);
            if (typeof raw[id] === 'string' && raw[id].includes('`')) {
                node.setAttribute(name, t(id));
            }
        }
    }
    upgradeKeys(root);
}

// Messages show code that names a chord as keycaps, and as its legends in plain text.
setCodeKind({ text: chordText, node: chord });
upgradeStatic();
