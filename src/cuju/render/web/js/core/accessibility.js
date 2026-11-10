// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The motion preference and the levels of the crowd, the ambience and the action sounds, in the
// settings panel and kept in the browser. Reduced motion plays the match without the cinematic
// sequences, camera flights, transitions, the ball trail and the turning of the editor preview.

import { h } from '../teams/library.js';
import { enhanceSelect } from './menu.js';
import { SOUND_CHANNELS, motionChoice, motionReduced, soundLevels } from './comfort.js';

const CHANNEL_LABELS = { crowd: 'Crowd', ambience: 'Ambience', effects: 'Action sounds' };

function load(key, fallback) {
    try {
        const v = localStorage.getItem(`cuju.${key}`);
        return v === null ? fallback : JSON.parse(v);
    } catch {
        return fallback;
    }
}

function save(key, value) {
    try {
        localStorage.setItem(`cuju.${key}`, JSON.stringify(value));
    } catch {
        // Storage can be unavailable, the setting then lasts for this visit only.
    }
}

export class AccessibilityControls {
    constructor(app) {
        this.app = app;
        this.system = window.matchMedia('(prefers-reduced-motion: reduce)');
        this.preference = motionChoice(load('motion', 'system'));
        const levels = soundLevels(load('soundLevels', {}));
        for (const name of SOUND_CHANNELS) {
            app.sound.setChannel(name, levels[name]);
        }
        this.motion = h('select', { id: 'motion', 'aria-label': 'Motion' },
            h('option', { value: 'system' }, 'Follow the system'),
            h('option', { value: 'reduce' }, 'Reduced'),
            h('option', { value: 'full' }, 'Full'));
        this.motion.value = this.preference;
        this.motion.addEventListener('change', () => {
            this.preference = motionChoice(this.motion.value);
            save('motion', this.preference);
            this.apply();
        });
        this.sliders = {};
        const rows = SOUND_CHANNELS.map((name) => {
            const input = h('input', { type: 'range', id: `level-${name}`, min: 0, max: 1, step: 0.05 });
            input.value = String(app.sound.levels[name]);
            input.addEventListener('input', () => {
                app.sound.setChannel(name, Number(input.value));
                save('soundLevels', app.sound.levels);
            });
            this.sliders[name] = input;
            return h('label', {}, `${CHANNEL_LABELS[name]} level`, input);
        });
        // The motion preference follows the theme, and the levels close the panel.
        const theme = document.getElementById('theme');
        const anchor = theme && theme.closest('label');
        const panel = document.getElementById('settings');
        const parts = [h('label', {}, 'Motion', this.motion),
            h('p', { class: 'muted small' }, 'Each level lowers its part of the sound under the volume.'), ...rows];
        if (anchor) {
            anchor.after(...parts);
        } else if (panel) {
            panel.append(...parts);
        }
        enhanceSelect(this.motion, { className: 'in-panel', align: 'right' });
        this.system.addEventListener('change', () => this.apply());
        this.apply();
    }

    apply() {
        const app = this.app;
        app.reducedMotion = motionReduced(this.preference, this.system.matches);
        document.documentElement.classList.toggle('reduced-motion', app.reducedMotion);
        document.documentElement.classList.toggle('full-motion', this.preference === 'full');
        app.cameras.reducedMotion = app.reducedMotion;
        app.ball.setTrail(app.settings.trail && !app.reducedMotion);
        if (!app.reducedMotion) {
            return;
        }
        // A sequence under way ends where it stands.
        if (app.director.running) {
            app.director.stop(false);
        }
        if (app.postMatch.running) {
            app.postMatch.end({ home: false, restore: false });
        }
        if (app.transition.active || app.transition.after) {
            app.transition.abort(false);
        }
        app.cameras.blend = null;
    }
}
