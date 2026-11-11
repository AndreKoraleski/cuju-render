// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The state of the offer to install the page as an app, shared by the offer on Home and the
// Install the app part of Help. Chrome and Edge fire beforeinstallprompt once a page load, often
// before the modules of the page load, so js/boot.js keeps the event in window.cujuInstall and
// says each change with the event cuju-install on the window. The browser keeps a dismissal of the
// offer, and the rules at the top of the file touch nothing of the page.

export const OFFER_KEY = 'cuju.installOffer';
// The page loads that pass before the offer shows, so a first visit stays with its first tips.
export const QUIET_VISITS = 1;
const MOST_VISITS = 1000;

// The stored state of the offer, whether it was dismissed and how many times the page loaded.
export function offerState(stored) {
    const source = stored && typeof stored === 'object' ? stored : {};
    const visits = Number.isInteger(source.visits) && source.visits > 0 ? Math.min(source.visits, MOST_VISITS) : 0;
    return { dismissed: source.dismissed === true, visits };
}

// The state after one more load of the page.
export function countVisit(state) {
    const clean = offerState(state);
    return { ...clean, visits: Math.min(clean.visits + 1, MOST_VISITS) };
}

// The state after the person turns the offer down, which keeps it away for good.
export function dismissOffer(state) {
    return { ...offerState(state), dismissed: true };
}

// Whether the offer shows on Home. It needs the browser's own offer, a page that is no installed
// app, a visit after the first, no dismissal, the Home page and nothing open over it.
export function offerShown({ state, prompt, installed, page, busy }) {
    const clean = offerState(state);
    return !!prompt && !installed && !clean.dismissed && clean.visits > QUIET_VISITS && page === 'home' && !busy;
}

// The way this browser installs a page as an app. browser, it fires beforeinstallprompt, as
// Chrome, Edge and other Chromium browsers do. safari, Safari on a Mac, whose File menu adds the
// page to the Dock. command, any other browser, for which cuju render app --install makes the app.
export function installRoute({ hasEvent, userAgent = '', vendor = '' }) {
    if (hasEvent) {
        return 'browser';
    }
    const apple = /Apple/.test(vendor) && /Safari\//.test(userAgent) && !/(Chrome|CriOS|FxiOS|Edg)\//.test(userAgent);
    if (apple && /Macintosh/.test(userAgent)) {
        return 'safari';
    }
    return 'command';
}

// Whether the page runs as an app, an installed page, a page added to the Dock or the window of
// cuju render app through the system's web view.
export function runsAsApp(win = globalThis) {
    const media = (query) => !!(win.matchMedia && win.matchMedia(query).matches);
    return media('(display-mode: standalone)') || media('(display-mode: window-controls-overlay)')
        || media('(display-mode: minimal-ui)') || win.navigator?.standalone === true || !!win.pywebview;
}

// What boot.js keeps, the browser's offer and whether the page was installed during this visit.
function held() {
    const win = globalThis.window;
    if (win && !win.cujuInstall) {
        win.cujuInstall = { prompt: null, installed: false };
    }
    return win ? win.cujuInstall : { prompt: null, installed: false };
}

export function heldPrompt() {
    return held().prompt;
}

export function installedNow() {
    return held().installed || runsAsApp();
}

// Calls fn on each change of the offer or of the install.
export function onInstallChange(fn) {
    globalThis.window?.addEventListener('cuju-install', fn);
}

function changed() {
    const win = globalThis.window;
    if (win && typeof win.dispatchEvent === 'function' && typeof Event === 'function') {
        win.dispatchEvent(new Event('cuju-install'));
    }
}

// Shows the browser's offer, which it gives once, and returns the person's answer, accepted or
// dismissed, or unavailable when the browser holds no offer.
export async function promptInstall() {
    const keep = held();
    const prompt = keep.prompt;
    if (!prompt) {
        return { outcome: 'unavailable' };
    }
    keep.prompt = null;
    changed();
    await prompt.prompt();
    const choice = await prompt.userChoice;
    return { outcome: choice && choice.outcome === 'accepted' ? 'accepted' : 'dismissed' };
}
