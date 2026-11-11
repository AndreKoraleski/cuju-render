// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The start of the page as a clean feed, active only when the address carries the query parameter
// feed, as the frame of /feed gives it. It runs before main.js, so the viewer starts with the
// feed's own settings. The settings live in memory for the visit, so a feed never changes the
// settings that the browser keeps for the page, and the same address always looks the same. The
// pointer stays free, keys and controllers reach nothing, and the page opens on Watch.

import { parseFeed } from './export/feed-params.js';

const params = new URLSearchParams(location.search);

// Settings in memory, with the interface of localStorage.
export class MemoryStorage {
    constructor(entries) {
        this.map = new Map(entries);
    }

    get length() {
        return this.map.size;
    }

    key(index) {
        return [...this.map.keys()][index] ?? null;
    }

    getItem(key) {
        return this.map.has(String(key)) ? this.map.get(String(key)) : null;
    }

    setItem(key, value) {
        this.map.set(String(key), String(value));
    }

    removeItem(key) {
        this.map.delete(String(key));
    }

    clear() {
        this.map.clear();
    }
}

// The stored settings that give the feed its look, from its checked options.
export function feedSettings(options) {
    const broadcast = options.broadcast;
    const remembered = ['broadcast', 'tactical', 'goal'].includes(options.camera) ? options.camera : 'broadcast';
    const settings = {
        muted: !options.audio,
        volume: options.volume,
        quality: options.quality,
        theme: options.theme,
        tvMode: true,
        idleReturn: false,
        pointerLock: false,
        camera: remembered,
        lineups: broadcast,
        celebrations: broadcast,
        replays: broadcast,
        decisionReplays: broadcast,
        transitions: broadcast,
        podium: broadcast && options.show,
        tips: { off: true },
        playerLabels: false,
        clickFollow: false,
        view2dDeclined: true,
        touchControls: 'off',
        annotations: { players: false, actions: false, text: false },
        captions: options.captions,
    };
    const field = {};
    if (options.arena) {
        field.arena = options.arena;
    }
    if (options.time != null) {
        field.time = options.time;
    }
    if (Object.keys(field).length) {
        settings.field = field;
    }
    return settings;
}

function boot() {
    const { options, problems } = parseFeed(params);
    const settings = feedSettings(options);
    const storage = new MemoryStorage(Object.entries(settings).map(([key, value]) => [`cuju.${key}`, JSON.stringify(value)]));
    try {
        Object.defineProperty(window, 'localStorage', { configurable: true, get: () => storage });
    } catch {
        // A browser that keeps its storage fixed runs the feed on the stored settings.
    }
    // The frame of /feed scales the page up to the picture, so the drawing takes the picture's
    // own pixels rather than those of the layout.
    let ratio = Math.min(8, Math.max(0.25, Number(params.get('ratio')) || window.devicePixelRatio || 1));
    try {
        Object.defineProperty(window, 'devicePixelRatio', { configurable: true, get: () => ratio });
    } catch {
        // The drawing then takes the window's own ratio.
    }
    Element.prototype.requestPointerLock = function () {
        return Promise.reject(new Error('The pointer stays free in a feed.'));
    };
    Object.defineProperty(navigator, 'getGamepads', { configurable: true, value: () => [] });
    // Keys reach nothing, a feed shows the match on its own.
    for (const type of ['keydown', 'keyup', 'keypress']) {
        window.addEventListener(type, (e) => {
            e.stopImmediatePropagation();
            e.preventDefault();
        }, true);
    }
    window.addEventListener('contextmenu', (e) => e.preventDefault(), true);
    history.replaceState(null, '', `${location.pathname}${location.search}#page=watch`);
    const root = document.documentElement;
    root.classList.add('cuju-feed');
    root.dataset.feedLayer = options.layer;
    root.dataset.feedBackground = options.background === 'transparent' ? 'transparent' : 'solid';
    root.style.setProperty('--feed-background', options.background);
    if (!options.score) {
        root.classList.add('feed-no-score');
    }
    window.cujuFeed = {
        options,
        problems,
        ready: false,
        broken: null,
        alive: Date.now(),
        get ratio() {
            return ratio;
        },
        // The frame calls this when the window changes size, and the page then draws anew.
        setRatio(value) {
            const next = Math.min(8, Math.max(0.25, Number(value) || 1));
            if (next !== ratio) {
                ratio = next;
                const app = window.cuju;
                if (app && app.view && app.settings) {
                    app.view.setQuality(app.settings.quality);
                }
            }
        },
    };
    for (const problem of problems) {
        console.warn(`cuju feed: ${problem}`);
    }
}

if (params.has('feed')) {
    boot();
}
