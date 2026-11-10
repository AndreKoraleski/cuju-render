// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The fields of a picture size, shared by the Export video dialog and the Copy feed address
// dialog of the Watch page. A list holds the presets of sizes.js and Custom size, which shows a
// width and a height, and two lists set the scale and the safe area of the graphics.

import { h } from '../teams/library.js';
import { SIZE_PRESETS, checkSize, parseSafe } from './sizes.js';

// The scales of the graphics that the lists offer, the default first.
export const GRAPHICS_CHOICES = Object.freeze([
    { id: '1', label: 'As laid out' },
    { id: '0.75', label: 'Smaller, three quarters' },
    { id: '1.25', label: 'Larger, a quarter more' },
    { id: '1.5', label: 'Larger, half again' },
]);
export const SAFE_CHOICES = Object.freeze([
    { id: 'auto', label: 'Automatic, a margin of a twentieth' },
    { id: 'social', label: 'Clear of the buttons of short video apps' },
    { id: 'none', label: 'None, to the edges' },
]);

// Builds the fields with the given prefix of their identifiers and returns them with read, which
// returns the chosen width, height, scale and safe area, or throws a RangeError for a custom size
// out of range. Options are the size chosen first, limits for checkSize and whether to offer the
// scale and the safe area.
export function sizeFields(prefix, { value = '720p', limits = {}, graphics = true, safe = true } = {}) {
    const choice = h('select', { id: `${prefix}-size` },
        SIZE_PRESETS.map((p) => h('option', { value: p.id, selected: p.id === value }, p.label)),
        h('option', { value: 'custom' }, 'Custom size'));
    const side = (name, initial) => h('input', {
        id: `${prefix}-${name}`, type: 'number', min: String(limits.min || 90), max: String(limits.max || 3840),
        step: limits.even ? '2' : '1', value: String(initial), 'aria-label': `${name === 'width' ? 'Width' : 'Height'} in pixels`,
    });
    const width = side('width', 1280);
    const height = side('height', 720);
    const custom = h('span', { class: 'size-custom', hidden: true }, width, h('span', { 'aria-hidden': 'true' }, 'by'), height);
    const list = (id, entries) => h('select', { id: `${prefix}-${id}` }, entries.map((e) => h('option', { value: e.id }, e.label)));
    const scale = graphics ? list('scale', GRAPHICS_CHOICES) : null;
    const area = safe ? list('safe', SAFE_CHOICES) : null;
    choice.addEventListener('change', () => {
        custom.hidden = choice.value !== 'custom';
        const preset = SIZE_PRESETS.find((p) => p.id === choice.value);
        if (preset) {
            width.value = String(preset.width);
            height.value = String(preset.height);
        }
    });
    const field = (label, ...controls) => h('label', { class: 've-field' }, h('span', {}, label), ...controls);
    const fields = [field('Size', choice, custom)];
    if (scale) {
        fields.push(field('Graphics', scale));
    }
    if (area) {
        fields.push(field('Safe area', area));
    }
    const read = () => {
        let size;
        if (choice.value === 'custom') {
            size = checkSize(Number(width.value), Number(height.value), limits);
        } else {
            const preset = SIZE_PRESETS.find((p) => p.id === choice.value);
            size = checkSize(preset.width, preset.height, limits);
        }
        return {
            id: choice.value,
            width: size.width,
            height: size.height,
            scale: scale ? Number(scale.value) : 1,
            safe: area ? parseSafe(area.value) : 'auto',
        };
    };
    return { fields, read, choice, width, height, scale, area };
}
