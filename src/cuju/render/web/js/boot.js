// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The first script of the page, a classic one, so it runs before the modules load. A module of the
// page that fails to load, as when a busy server refuses a connection, fails the whole graph of
// modules, which a browser does not load again by itself, and the page stays without its
// application. The page then reloads once after a moment, and once a minute at most, so a server
// that is gone leaves the page as it is rather than reloading it again and again.
(function () {
    const KEY = 'cuju.bootRetry';
    const SPACING_MS = 60000;
    window.addEventListener('error', (event) => {
        const node = event.target;
        if (!node || node.tagName !== 'SCRIPT' || node.type !== 'module' || window.cuju) {
            return;
        }
        try {
            const last = Number(sessionStorage.getItem(KEY)) || 0;
            if (Date.now() - last < SPACING_MS) {
                return;
            }
            sessionStorage.setItem(KEY, String(Date.now()));
        } catch {
            // Without storage the page cannot tell a second failure from the first, so it stays.
            return;
        }
        console.warn('a module of the page did not load, the page reloads');
        setTimeout(() => location.reload(), 1000);
    }, true);
}());

// Chrome and Edge offer to install the page once a page load, often before the modules load, so
// this script keeps the offer for the modules, which read it in window.cujuInstall and hear of each
// change through the event cuju-install. The page shows an offer of its own in place of the
// browser's small bar.
(function () {
    const held = window.cujuInstall || { prompt: null, installed: false };
    window.cujuInstall = held;
    const changed = () => window.dispatchEvent(new Event('cuju-install'));
    window.addEventListener('beforeinstallprompt', (event) => {
        event.preventDefault();
        held.prompt = event;
        changed();
    });
    window.addEventListener('appinstalled', () => {
        held.prompt = null;
        held.installed = true;
        changed();
    });
}());
