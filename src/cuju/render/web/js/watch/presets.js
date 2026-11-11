// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// One-click presets of the presentation at the top of the settings panel. Quick look turns off
// the lineups, the celebrations, the replays after goals, the decision replays, the restart
// transitions and the show after the match, for a researcher who checks a match, and Full
// broadcast turns them all on. Any other mix is Custom, which the browser keeps, so a person who
// tries a preset and comes back to Custom finds their own choices again. The rules at the top of
// the file touch nothing of the page, so they hold the same in a test.

import { t } from '../core/i18n.js';

// Each setting of a preset, its key in the page's settings and the box of the settings panel.
export const PRESET_SETTINGS = [
    ['lineups', 'lineups-on'],
    ['celebrations', 'celebrations-on'],
    ['replays', 'replays'],
    ['decisionReplays', 'decision-replays'],
    ['transitions', 'restart-transitions'],
    ['podium', 'podium-on'],
];
const KEYS = PRESET_SETTINGS.map(([key]) => key);
export const PRESETS = {
    quick: Object.fromEntries(KEYS.map((key) => [key, false])),
    broadcast: Object.fromEntries(KEYS.map((key) => [key, true])),
};
// Each preset with its name in the page's language, the message presets.<name>.
export const PRESET_NAMES = ['quick', 'broadcast', 'custom'].map((name) => [name, t(`presets.${name}`)]);
export const CUSTOM_KEY = 'cuju.presetCustom';

// The values of the preset settings, each true unless it is false, as the page's defaults are.
export function presetValues(settings) {
    const source = settings && typeof settings === 'object' ? settings : {};
    return Object.fromEntries(KEYS.map((key) => [key, source[key] !== false]));
}

// The preset that the values make, or custom for any other mix.
export function presetOf(settings) {
    const values = presetValues(settings);
    for (const name of ['quick', 'broadcast']) {
        if (KEYS.every((key) => values[key] === PRESETS[name][key])) {
            return name;
        }
    }
    return 'custom';
}

// A stored custom mix, or null when the store holds nothing of the kind.
export function cleanCustom(stored) {
    if (!stored || typeof stored !== 'object' || !KEYS.every((key) => typeof stored[key] === 'boolean')) {
        return null;
    }
    return presetValues(stored);
}

// The values that a preset brings and the custom mix kept from then on. Leaving a custom mix keeps
// it, and Custom brings back the kept mix, or the current values when none was kept.
export function switchPreset(name, current, custom) {
    const now = presetValues(current);
    const kept = presetOf(now) === 'custom' ? now : cleanCustom(custom);
    if (name === 'quick' || name === 'broadcast') {
        return { values: { ...PRESETS[name] }, custom: kept };
    }
    return { values: kept ? { ...kept } : now, custom: kept };
}

function loadCustom() {
    try {
        return cleanCustom(JSON.parse(localStorage.getItem(CUSTOM_KEY)));
    } catch {
        return null;
    }
}

function saveCustom(values) {
    try {
        localStorage.setItem(CUSTOM_KEY, JSON.stringify(values));
    } catch {
        // Storage can be unavailable, the custom mix then lasts for this visit only.
    }
}

export class SettingsPresets {
    constructor(app) {
        this.app = app;
        this.custom = loadCustom();
        const panel = document.getElementById('settings');
        if (!panel) {
            return;
        }
        this.buttons = PRESET_NAMES.map(([name, label]) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'preset-btn';
            button.dataset.preset = name;
            button.setAttribute('role', 'radio');
            button.textContent = label;
            button.addEventListener('click', () => this.apply(name));
            button.addEventListener('keydown', (e) => this.onKey(e, name));
            return button;
        });
        this.group = document.createElement('div');
        this.group.id = 'presets';
        this.group.className = 'presets';
        this.group.setAttribute('role', 'radiogroup');
        this.group.setAttribute('aria-label', t('presets.label'));
        this.group.append(...this.buttons);
        const note = document.createElement('p');
        note.className = 'muted small preset-note';
        note.textContent = t('presets.note');
        const title = panel.querySelector('.panel-title');
        (title || panel.firstChild).after(this.group, note);
        // A change of any one box makes a mix of its own, which Custom keeps.
        for (const [, id] of PRESET_SETTINGS) {
            document.getElementById(id)?.addEventListener('change', () => this.applying || this.sync(true));
        }
        this.sync(true);
    }

    // The values of the preset settings, those that a game on Play holds back while it shows.
    current() {
        const settings = (this.app.play && this.app.play.saved) || this.app.settings;
        // The 2D view reads some of them as off while it draws, the stored values are the preset's.
        return presetValues(settings.stored || settings);
    }

    get name() {
        return presetOf(this.current());
    }

    // The presets to offer, every one but the one in force, and Custom once there is a mix to keep.
    choices() {
        const name = this.name;
        return PRESET_NAMES.filter(([choice]) => choice !== name && (choice !== 'custom' || this.custom));
    }

    apply(name) {
        if (name === 'custom' && !this.custom) {
            return;
        }
        const { values, custom } = switchPreset(name, this.current(), this.custom);
        this.custom = custom;
        if (custom) {
            saveCustom(custom);
        }
        // A game on Play holds these settings back and restores them when it ends, so the
        // restored values follow the preset.
        const held = this.app.play && this.app.play.saved;
        // The boxes change one at a time, and the mixes on the way are no mix of the person's.
        this.applying = true;
        try {
            for (const [key, id] of PRESET_SETTINGS) {
                const box = document.getElementById(id);
                if (box && box.checked !== values[key]) {
                    box.checked = values[key];
                    box.dispatchEvent(new Event('change', { bubbles: true }));
                }
                if (held) {
                    held[key] = values[key];
                }
            }
        } finally {
            this.applying = false;
        }
        this.sync(false);
        this.app.hud.toast(t('presets.toast', { name: PRESET_NAMES.find(([n]) => n === name)[1] }), 'info', 1500);
    }

    // Marks the preset in force, and keeps a custom mix when keep is set.
    sync(keep) {
        const values = this.current();
        const name = presetOf(values);
        if (keep && name === 'custom') {
            this.custom = values;
            saveCustom(values);
        }
        for (const button of this.buttons || []) {
            const on = button.dataset.preset === name;
            button.setAttribute('aria-checked', on ? 'true' : 'false');
            button.tabIndex = on ? 0 : -1;
            const off = button.dataset.preset === 'custom' && !this.custom;
            button.setAttribute('aria-disabled', off ? 'true' : 'false');
            button.title = off ? t('presets.customOff') : '';
        }
    }

    // The arrows move through the presets and choose one, as in any group of radio buttons.
    onKey(e, name) {
        const order = PRESET_NAMES.map(([n]) => n).filter((n) => n !== 'custom' || this.custom);
        const i = order.indexOf(name);
        const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
        if (!step || i < 0) {
            return;
        }
        e.preventDefault();
        e.stopPropagation();
        const next = order[(i + step + order.length) % order.length];
        this.apply(next);
        this.buttons.find((b) => b.dataset.preset === next).focus();
    }
}
