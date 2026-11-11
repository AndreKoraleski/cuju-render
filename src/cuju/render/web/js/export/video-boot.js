// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The start of the page that draws a video export of the browser, active only when the address
// carries the query parameters capture and export, as video-browser.js opens it in a frame of its
// own. It runs before main.js, so the viewer starts with the settings of the export, which
// exportSettings of video-plan.js gives and the parameter export carries. The settings live in
// memory, so an export never changes the settings that the browser keeps for the page. The
// drawing takes the pixels of the picture through the parameter ratio, the pointer stays free and
// keys and controllers reach nothing.

import { MemoryStorage } from '../feed-boot.js';

const params = new URLSearchParams(location.search);

// The settings of the parameter export, a JSON object of the stored settings, or null.
export function readSettings(text) {
    try {
        const value = JSON.parse(text);
        return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
    } catch {
        return null;
    }
}

function boot() {
    const settings = readSettings(params.get('export')) || {};
    const storage = new MemoryStorage(Object.entries(settings).map(([key, value]) => [`cuju.${key}`, JSON.stringify(value)]));
    try {
        Object.defineProperty(window, 'localStorage', { configurable: true, get: () => storage });
    } catch {
        // A browser that keeps its storage fixed draws on the stored settings.
    }
    const ratio = Math.min(8, Math.max(0.25, Number(params.get('ratio')) || 1));
    try {
        Object.defineProperty(window, 'devicePixelRatio', { configurable: true, get: () => ratio });
    } catch {
        // The drawing then takes the window's own ratio.
    }
    Element.prototype.requestPointerLock = function () {
        return Promise.reject(new Error('The pointer stays free while exporting.'));
    };
    Object.defineProperty(navigator, 'getGamepads', { configurable: true, value: () => [] });
    for (const type of ['keydown', 'keyup', 'keypress']) {
        window.addEventListener(type, (e) => {
            e.stopImmediatePropagation();
            e.preventDefault();
        }, true);
    }
    window.cujuExport = { ratio };
}

if (params.has('capture') && params.has('export')) {
    boot();
}
