// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The fields of a picture size, shared by the Export video dialog and the Copy feed address
// dialog of the Watch page. A list holds the presets of sizes.js and Custom size, which shows a
// width and a height, and two lists set the scale and the safe area of the graphics.

import { t } from '../core/i18n.js';
import { h } from '../teams/library.js';
import { MAX_AREA, MAX_SIDE, MIN_SIDE, SIZE_PRESETS, checkSize, parseSafe } from './sizes.js';

// The scales of the graphics that the lists offer, the default first.
export const GRAPHICS_CHOICES = Object.freeze([
    { id: '1', label: t('size-fields.graphics.1') },
    { id: '0.75', label: t('size-fields.graphics.0_75') },
    { id: '1.25', label: t('size-fields.graphics.1_25') },
    { id: '1.5', label: t('size-fields.graphics.1_5') },
]);
export const SAFE_CHOICES = Object.freeze([
    { id: 'auto', label: t('size-fields.safe.auto') },
    { id: 'social', label: t('size-fields.safe.social') },
    { id: 'none', label: t('size-fields.safe.none') },
]);

// The name of a preset in the language of the page. sizes.js keeps its English labels, the
// server and the tests read it alone.
export function presetLabel(preset) {
    return t(`size-fields.preset.${preset.id}`);
}

// Checks a size as checkSize does, with its refusal in the language of the page.
function checkShown(width, height, limits) {
    try {
        return checkSize(width, height, limits);
    } catch (err) {
        const { min = MIN_SIDE, max = MAX_SIDE, area = MAX_AREA, even = false } = limits;
        for (const [name, value] of [['width', width], ['height', height]]) {
            if (!Number.isInteger(value) || value < min || value > max) {
                throw new RangeError(t(`size-fields.error.${name}.range`, { min, max, value }));
            }
            if (even && value % 2) {
                throw new RangeError(t(`size-fields.error.${name}.even`, { value }));
            }
        }
        if (width * height > area) {
            throw new RangeError(t('size-fields.error.area', { area, width, height }));
        }
        throw err;
    }
}

// Builds the fields with the given prefix of their identifiers and returns them with read, which
// returns the chosen width, height, scale and safe area, or throws a RangeError for a custom size
// out of range. Options are the size chosen first, limits for checkSize and whether to offer the
// scale and the safe area.
export function sizeFields(prefix, { value = '720p', limits = {}, graphics = true, safe = true } = {}) {
    const choice = h('select', { id: `${prefix}-size` },
        SIZE_PRESETS.map((p) => h('option', { value: p.id, selected: p.id === value }, presetLabel(p))),
        h('option', { value: 'custom' }, t('size-fields.custom')));
    const side = (name, initial) => h('input', {
        id: `${prefix}-${name}`, type: 'number', min: String(limits.min || 90), max: String(limits.max || 3840),
        step: limits.even ? '2' : '1', value: String(initial), 'aria-label': t(`size-fields.${name === 'width' ? 'width' : 'height'}`),
    });
    const width = side('width', 1280);
    const height = side('height', 720);
    const custom = h('span', { class: 'size-custom', hidden: true }, width, h('span', { 'aria-hidden': 'true' }, t('size-fields.by')), height);
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
    const fields = [field(t('size-fields.size'), choice, custom)];
    if (scale) {
        fields.push(field(t('size-fields.graphics'), scale));
    }
    if (area) {
        fields.push(field(t('size-fields.safe'), area));
    }
    const read = () => {
        let size;
        if (choice.value === 'custom') {
            size = checkShown(Number(width.value), Number(height.value), limits);
        } else {
            const preset = SIZE_PRESETS.find((p) => p.id === choice.value);
            size = checkShown(preset.width, preset.height, limits);
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
