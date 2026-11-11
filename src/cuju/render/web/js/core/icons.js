// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The symbols of the page, the Lucide icons that vendor/lucide/icons.js holds, each a list of
// shapes in a box of 24 by 24 stroked in the color of the text, so every symbol follows the theme.
// The module fills the sprite of the page, an svg element of index.html, as it loads, and a
// control draws a symbol through a use element that points into the sprite.
//
// A control that shows its symbol alone keeps its name. symbolOnly gives it the name as its
// accessible name and as its tooltip, which the browser shows on hover and the page shows on
// keyboard focus, so the name reads the same to every person.

import { LUCIDE } from '../../vendor/lucide/icons.js';

const SVG_NS = 'http://www.w3.org/2000/svg';

// The symbols of the page by the name the page gives them, each the Lucide icon it draws.
// ci/make_icons.py copies the icons named here.
export const SYMBOLS = {
    // Playback.
    play: 'play', pause: 'pause', 'frame-back': 'step-back', 'frame-forward': 'step-forward',
    restart: 'skip-back', goal: 'goal', volume: 'volume-2', muted: 'volume-x', stop: 'square',
    replay: 'repeat',
    // The top bar and the pages.
    fullscreen: 'maximize', search: 'search', settings: 'settings', keyboard: 'keyboard',
    home: 'house', watch: 'tv', gamepad: 'gamepad-2', archive: 'archive', matches: 'swords',
    trophy: 'trophy', shirt: 'shirt', field: 'land-plot', help: 'circle-question-mark',
    // Actions.
    close: 'x', back: 'arrow-left', next: 'arrow-right', previous: 'chevron-left', forward: 'chevron-right',
    up: 'chevron-up', down: 'chevron-down', plus: 'plus', minus: 'minus', check: 'check',
    refresh: 'refresh-cw', reset: 'rotate-ccw', undo: 'undo-2', redo: 'redo-2', trash: 'trash-2',
    edit: 'pencil', info: 'info', folder: 'folder', 'folder-plus': 'folder-plus', 'folder-move': 'folder-input',
    file: 'file', copy: 'copy', download: 'download', upload: 'upload', film: 'film', camera: 'camera',
    eye: 'eye', list: 'list', grid: 'layout-grid', live: 'radio', dice: 'dices', save: 'save',
    star: 'star', flag: 'flag', exit: 'log-out', robot: 'bot', sparkle: 'sparkles', more: 'ellipsis',
    layers: 'layers', link: 'link', podium: 'medal', video: 'video', user: 'user', crosshair: 'crosshair',
    monitor: 'monitor', stats: 'chart-column', palette: 'palette', languages: 'languages', external: 'external-link',
    // States.
    clock: 'clock', running: 'loader', alert: 'triangle-alert', waiting: 'hourglass', done: 'circle-check',
    failed: 'circle-x', warning: 'circle-alert',
    // The drawing tools of the painter.
    cursor: 'mouse-pointer-2', brush: 'brush', eraser: 'eraser', square: 'square', circle: 'circle',
    triangle: 'triangle', line: 'slash', text: 'type', image: 'image', 'bring-forward': 'bring-to-front',
    'send-backward': 'send-to-back', clear: 'square-x',
    // Time of day, weather and mowing.
    sun: 'sun', dawn: 'sunrise', dusk: 'sunset', moon: 'moon', cloud: 'cloud', rain: 'cloud-rain',
    storm: 'cloud-lightning', snow: 'cloud-snow', fog: 'haze', stripes: 'columns-3', checkers: 'grid-3x3',
    circles: 'circle-dot', plain: 'ban',
};

// Fills the sprite of the page with every symbol it lacks, making the sprite when the page has none.
export function installIcons(doc = typeof document === 'undefined' ? null : document) {
    if (!doc || !doc.body) {
        return null;
    }
    let sprite = doc.getElementById('icons');
    if (!sprite) {
        sprite = doc.createElementNS(SVG_NS, 'svg');
        sprite.id = 'icons';
        sprite.setAttribute('width', '0');
        sprite.setAttribute('height', '0');
        sprite.setAttribute('aria-hidden', 'true');
        sprite.style.position = 'absolute';
        doc.body.prepend(sprite);
    }
    for (const [name, lucide] of Object.entries(SYMBOLS)) {
        const shapes = LUCIDE[lucide];
        if (!shapes || doc.getElementById(`i-${name}`)) {
            continue;
        }
        const symbol = doc.createElementNS(SVG_NS, 'symbol');
        symbol.id = `i-${name}`;
        symbol.setAttribute('viewBox', '0 0 24 24');
        for (const [tag, attributes] of shapes) {
            const shape = doc.createElementNS(SVG_NS, tag);
            for (const [key, value] of Object.entries(attributes)) {
                shape.setAttribute(key, value);
            }
            if (!attributes.fill) {
                shape.setAttribute('fill', 'none');
            }
            shape.setAttribute('stroke', 'currentColor');
            shape.setAttribute('stroke-width', '2');
            shape.setAttribute('stroke-linecap', 'round');
            shape.setAttribute('stroke-linejoin', 'round');
            symbol.append(shape);
        }
        sprite.append(symbol);
    }
    return sprite;
}

// A symbol of the sprite, hidden from screen readers, since the control around it carries the name.
export function icon(name, className = 'icon') {
    const node = document.createElementNS(SVG_NS, 'svg');
    node.setAttribute('class', className);
    node.setAttribute('aria-hidden', 'true');
    node.setAttribute('focusable', 'false');
    const use = document.createElementNS(SVG_NS, 'use');
    use.setAttribute('href', `#i-${name}`);
    node.append(use);
    return node;
}

// The symbol of each state of a request, a match, a tournament or a source.
export const STATE_ICONS = {
    queued: 'clock', waiting: 'waiting', running: 'running', live: 'live', done: 'done', failed: 'failed',
    todo: 'circle', error: 'alert', cancelled: 'close', interrupted: 'pause', stopped: 'pause', paused: 'pause', person: 'gamepad',
};

// A badge of a state that shows its symbol alone, the name of the state as its accessible name and
// its tooltip.
export function stateBadge(state, label, className = `state-pill ${state}`) {
    const node = document.createElement('span');
    node.className = className;
    node.setAttribute('role', 'img');
    node.setAttribute('aria-label', label);
    node.title = label;
    node.setAttribute('data-symbol', '');
    node.dataset.state = state;
    node.append(icon(STATE_ICONS[state] || 'info'));
    return node;
}

// The attributes of a control that shows its symbol alone, its name as the accessible name and as
// the tooltip. The tooltip may say more than the name, such as the key of the control.
export function symbolOnly(label, tip = label) {
    return { 'aria-label': label, title: tip, 'data-symbol': '' };
}

// The text of a control beside its symbol, in a span that relabel finds again.
export function labelText(text) {
    const node = document.createElement('span');
    node.className = 'btn-label';
    node.textContent = text;
    return node;
}

// Gives a control another symbol of the sprite.
export function reicon(button, name) {
    button.querySelector('svg.icon use')?.setAttribute('href', `#i-${name}`);
}

// Gives a control with a symbol a new name. A symbol alone takes it as its accessible name and its
// tooltip, a symbol with text takes it as the text beside the symbol.
export function relabel(button, text, tip = text) {
    if (button.hasAttribute('data-symbol')) {
        button.setAttribute('aria-label', text);
        button.title = tip;
        return;
    }
    const label = button.querySelector('.btn-label');
    if (label) {
        label.textContent = text;
    } else {
        button.textContent = text;
    }
}

installIcons();
