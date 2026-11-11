// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The comfort rules of the page, the motion preference with the fades and still shots of reduced
// motion, the levels of the three sound channels that the page keeps in the browser, the controls
// that keep their own keys and the open panels that take a captured pointer back.

// Follow the system, always reduce, or always move in full.
export const MOTION_CHOICES = ['system', 'reduce', 'full'];

// The channels under the master volume. Each level runs from 0 to 1 and starts at 1, or 0.8 for
// the music of team packages, so a level only ever turns its channel down.
export const SOUND_CHANNELS = ['crowd', 'ambience', 'effects', 'music'];
export const SOUND_DEFAULTS = { music: 0.8 };

// The stored motion preference, or system for anything else.
export function motionChoice(value) {
    return MOTION_CHOICES.includes(value) ? value : 'system';
}

// Whether the page reduces motion, for a preference and the system's own setting.
export function motionReduced(choice, systemReduces) {
    const chosen = motionChoice(choice);
    return chosen === 'reduce' || (chosen === 'system' && !!systemReduces);
}

// The cover of the fade that takes the place of a wipe under reduced motion, at the progress p of
// the wipe from 0 to 1. It rises over the first three tenths, covers the view fully from 0.3 to
// 0.7, where the wipe covers it and the cut happens, and clears over the last three tenths.
export function fadeCover(p) {
    if (!(p > 0 && p < 1)) {
        return 0;
    }
    const smooth = (x) => {
        const u = Math.max(0, Math.min(1, x));
        return u * u * (3 - 2 * u);
    };
    return Math.min(smooth(p / 0.3), 1 - smooth((p - 0.7) / 0.3));
}

// The least time in seconds that a still shot holds before its subject may cut it, and the part
// of the half frame its subject may leave the middle by before then.
export const STILL_HOLD = 1;
export const STILL_EDGE = 0.7;

// Whether a still shot under reduced motion cuts to a new framing, because the subject it wants
// to see left the frame, moved far nearer or farther, or after the shortest hold neared the edge.
// The view holds the position and target of the still, its vertical field of view in degrees,
// and the seconds it has held. Points are objects with x, y and z, with y up.
export function stillCut(view, want, aspect = 16 / 9, held = Infinity) {
    const fx = view.target.x - view.pos.x;
    const fy = view.target.y - view.pos.y;
    const fz = view.target.z - view.pos.z;
    const length = Math.hypot(fx, fy, fz);
    if (!(length > 1e-6)) {
        return true;
    }
    const f = [fx / length, fy / length, fz / length];
    // The right of the view is level, and straight down looks along the x axis.
    const flat = Math.hypot(f[0], f[2]);
    const r = flat > 1e-6 ? [-f[2] / flat, 0, f[0] / flat] : [1, 0, 0];
    const u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]];
    const d = [want.x - view.pos.x, want.y - view.pos.y, want.z - view.pos.z];
    const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    const depth = dot(d, f);
    if (!(depth > 0.1)) {
        return true;
    }
    const tanV = Math.tan(((view.fov || 40) * Math.PI) / 360);
    const tanH = tanV * Math.max(0.5, aspect || 16 / 9);
    const edge = Math.max(Math.abs(dot(d, r) / depth) / tanH, Math.abs(dot(d, u) / depth) / tanV);
    const near = depth / length;
    if (edge > 1 || near < 0.5 || near > 2) {
        return true;
    }
    return held >= STILL_HOLD && edge > STILL_EDGE;
}

// A channel level within 0 and 1, and 1 for anything that is not a number.
export function soundLevel(value, fallback = 1) {
    const level = typeof value === 'number' ? value : Number.NaN;
    return Number.isFinite(level) ? Math.max(0, Math.min(1, level)) : fallback;
}

// The levels of every channel from a stored object, each kept within 0 and 1.
export function soundLevels(stored) {
    const source = stored && typeof stored === 'object' ? stored : {};
    return Object.fromEntries(SOUND_CHANNELS.map((name) => [name, soundLevel(source[name], SOUND_DEFAULTS[name] ?? 1)]));
}

// Controls that keep their keys, so Space or a letter on one of them acts on that control alone.
export const OWN_KEYS = [
    'button', 'a[href]', 'summary', '[role="button"]', '[role="link"]', '[role^="menuitem"]',
    '[role="slider"]', '[role="checkbox"]', '[role="radio"]', '[role="switch"]', '[role="tab"]',
    '[role="option"]', '[role="treeitem"]', '[role="spinbutton"]',
].join(', ');

// Buttons and links act on Enter and Space alone, so a letter or a question mark pressed on one
// still reaches the single key shortcuts of the page, such as H, M and F. A button inside a
// dialog, a menu or a list keeps every key, as do the other controls of OWN_KEYS.
const PLAIN = 'button, a[href], [role="button"], [role="link"]';
const PLAIN_ROLES = [null, 'button', 'link'];
const HOLDERS = 'dialog, [role="dialog"], [role="alertdialog"], [role="menu"], [role="menubar"], '
    + '[role="listbox"], [role="tablist"], [role="tree"], [role="grid"], .dd-panel';

// Whether a control keeps a key to itself, the control being the closest element of OWN_KEYS
// around the key's target, or null. Esc always goes on to the page.
export function keepsKey(control, key, modifiers = {}) {
    if (!control || key === 'Escape') {
        return false;
    }
    const plain = control.matches(PLAIN) && PLAIN_ROLES.includes(control.getAttribute('role'));
    const letter = /^[a-z?]$/i.test(key) && !modifiers.ctrlKey && !modifiers.metaKey && !modifiers.altKey;
    return !(plain && letter && !control.closest(HOLDERS));
}

// Whatever opens over the page and asks for a click or a key. A dialog, an open details element,
// a menu, a popover or a list of a dropdown, the panel of a button that shows as expanded, the
// team editor, the lineups, the cards after the match and any element marked with data-prompt.
// Each counts only while it shows.
export const POINTER_PANELS = [
    'dialog[open]', 'details[open]', '[role="dialog"]', '[role="alertdialog"]', '[aria-modal="true"]',
    '[role="menu"]', '.dd-panel.open', 'button[aria-expanded="true"]', '#team-editor:not([hidden])',
    '#lineups', '.post-card', '#victory', '#spotlight', '[data-prompt]',
].join(', ');

// The first panel of the page that shows and wants the pointer, or null.
export function openPanel(root = document) {
    for (const node of root.querySelectorAll(POINTER_PANELS)) {
        if (node.getClientRects().length > 0) {
            return node;
        }
    }
    return null;
}
