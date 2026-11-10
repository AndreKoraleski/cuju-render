// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The frame of the clean feed, the page at /feed. It lays the Watch page out at the size that
// keeps the graphics in proportion, as layoutFor of sizes.js gives it, and scales the frame up to
// the picture, so a feed of 1920 by 1080 shows the graphics as the page shows them at 1280 by
// 720, and a vertical feed lays out 720 wide. A window of another size than the picture fits the
// picture inside it, centered. The page inside draws at the picture's own pixels, and a page
// that stops answering, fails to load or loses its graphics context loads again.

import { parseFeed } from './export/feed-params.js';

// A page that has not started this long after it loaded, or has not answered this long, loads
// again. The check pauses while the window is hidden.
const START_MS = 20000;
const SILENT_MS = 30000;
const CHECK_MS = 5000;

const frame = document.getElementById('feed-frame');
const query = location.search.replace(/^\?/, '');
const { options } = parseFeed(query);
document.documentElement.style.background = options.background;
document.body.style.background = options.background;

// Places the frame and returns the ratio of the picture's pixels to the layout's.
function place() {
    const { width, height, layout } = options;
    const vw = window.innerWidth || width;
    const vh = window.innerHeight || height;
    const fit = Math.min(vw / width, vh / height) || 1;
    const sx = (width * fit) / layout.width;
    const sy = (height * fit) / layout.height;
    frame.style.width = `${layout.width}px`;
    frame.style.height = `${layout.height}px`;
    frame.style.transform = `translate(${(vw - width * fit) / 2}px, ${(vh - height * fit) / 2}px) scale(${sx}, ${sy})`;
    return Math.max(sx, sy) * (window.devicePixelRatio || 1);
}

let ratio = place();
let loadedAt = performance.now();

function load() {
    loadedAt = performance.now();
    frame.src = `./?feed=1${query ? `&${query}` : ''}&ratio=${ratio.toFixed(4)}#page=watch`;
}

function inner() {
    try {
        return frame.contentWindow && frame.contentWindow.cujuFeed;
    } catch {
        // A page of the browser's own, such as an error page, is out of reach.
        return null;
    }
}

frame.addEventListener('load', () => {
    loadedAt = performance.now();
});

window.addEventListener('resize', () => {
    ratio = place();
    const feed = inner();
    if (feed) {
        feed.setRatio(ratio);
    }
});

setInterval(() => {
    if (document.hidden) {
        return;
    }
    const feed = inner();
    const now = performance.now();
    const stale = feed
        ? !!feed.broken || (feed.ready && Date.now() - feed.alive > SILENT_MS) || (!feed.ready && now - loadedAt > START_MS)
        : now - loadedAt > START_MS;
    if (stale) {
        load();
    }
}, CHECK_MS);

// Scripts that hold this window reach the feed's state here as well.
window.cujuFeedFrame = {
    options,
    get ratio() {
        return ratio;
    },
    state: () => {
        const app = frame.contentWindow && frame.contentWindow.cuju;
        return app && app.feed ? app.feed.state() : null;
    },
    reload: load,
};

load();
