// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The safe area of a picture of fixed size, for the clean feed and the video export. The page
// marks the app as framed, with the margins of sizes.js as CSS variables and the shape of the
// picture as a class, so feed.css keeps the score, the banners and the captions inside the safe
// area at every size and shape. The margins follow the size of the view as it changes.

import { parseSafe, safeArea, shapeOf } from './sizes.js';

export const SHAPES = ['wide', 'square', 'tall'];

// Applies the safe area of mode to the app element and returns the margins in CSS pixels.
export function applySafeArea(app, mode, width, height) {
    const margins = safeArea(width, height, mode);
    for (const side of ['top', 'right', 'bottom', 'left']) {
        app.style.setProperty(`--safe-${side}`, `${margins[side]}px`);
    }
    const shape = shapeOf(width, height);
    app.classList.add('framed');
    for (const s of SHAPES) {
        app.classList.toggle(`shape-${s}`, s === shape);
    }
    app.dataset.safe = String(mode);
    return { ...margins, shape };
}

// Keeps the safe area of the app element in step with its size, and returns an object whose
// margins field holds the latest margins and whose stop ends the watch.
export function watchSafeArea(app, mode) {
    const state = { margins: null, mode };
    const update = () => {
        const width = app.clientWidth || window.innerWidth;
        const height = app.clientHeight || window.innerHeight;
        state.margins = applySafeArea(app, state.mode, width, height);
        state.width = width;
        state.height = height;
    };
    update();
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(update) : null;
    if (observer) {
        observer.observe(app);
    } else {
        window.addEventListener('resize', update);
    }
    state.update = update;
    state.stop = () => (observer ? observer.disconnect() : window.removeEventListener('resize', update));
    return state;
}

// The safe area that the query of an address names, as the video export gives it, auto when it
// names none or one out of place.
export function safeMode(search) {
    try {
        return parseSafe(new URLSearchParams(search).get('safe'));
    } catch {
        return 'auto';
    }
}
