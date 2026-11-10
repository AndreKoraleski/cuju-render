// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The comfort rules of the page, the motion preference and the levels of the three sound channels
// that the page keeps in the browser, the controls that keep their own keys and the open panels
// that take a captured pointer back.

// Follow the system, always reduce, or always move in full.
export const MOTION_CHOICES = ['system', 'reduce', 'full'];

// The channels under the master volume. Each level runs from 0 to 1 and starts at 1, so a level
// only ever turns its channel down.
export const SOUND_CHANNELS = ['crowd', 'ambience', 'effects'];

// The stored motion preference, or system for anything else.
export function motionChoice(value) {
    return MOTION_CHOICES.includes(value) ? value : 'system';
}

// Whether the page reduces motion, for a preference and the system's own setting.
export function motionReduced(choice, systemReduces) {
    const chosen = motionChoice(choice);
    return chosen === 'reduce' || (chosen === 'system' && !!systemReduces);
}

// A channel level within 0 and 1, and 1 for anything that is not a number.
export function soundLevel(value) {
    const level = typeof value === 'number' ? value : Number.NaN;
    return Number.isFinite(level) ? Math.max(0, Math.min(1, level)) : 1;
}

// The levels of every channel from a stored object, each kept within 0 and 1.
export function soundLevels(stored) {
    const source = stored && typeof stored === 'object' ? stored : {};
    return Object.fromEntries(SOUND_CHANNELS.map((name) => [name, soundLevel(source[name])]));
}

// Controls that keep their keys, so Space or a letter on one of them acts on that control alone.
export const OWN_KEYS = [
    'button', 'a[href]', 'summary', '[role="button"]', '[role="link"]', '[role^="menuitem"]',
    '[role="slider"]', '[role="checkbox"]', '[role="radio"]', '[role="switch"]', '[role="tab"]',
    '[role="option"]', '[role="treeitem"]', '[role="spinbutton"]',
].join(', ');

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
