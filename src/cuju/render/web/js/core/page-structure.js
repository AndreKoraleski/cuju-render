// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The structure of the page for a screen reader and the browser. Each page has a title of its own
// in the window, such as Help · Cuju, and Watch takes the title of the recording that plays. The
// main region takes the name of the page in view, a heading names each page that lacks one of its
// own, and a change of page is said aloud. A page whose own visible title is its h1, as Teams,
// Tournaments and Help have, keeps that heading alone, so every page has one h1 and the headings
// below it descend a level at a time. The skip link moves the focus into the page and leaves
// the address as it stands. The names at the top of the file touch nothing of the page, so they
// hold the same in a test. Each name is the message structure.page.<page>.

import { t } from './i18n.js';

// The pages in the order of the top bar, each opened by the address #page=<page>.
export const PAGES = ['home', 'watch', 'play', 'challenges', 'recordings', 'matches', 'tournaments', 'teams', 'field', 'help'];

export const PAGE_NAMES = Object.fromEntries(PAGES.map((page) => [page, t(`structure.page.${page}`)]));

// The name of a page as the page shows it.
export function pageName(page) {
    return PAGE_NAMES[page] || (page ? `${page[0].toUpperCase()}${page.slice(1)}` : '');
}

// The title of the window on a page. Home is Cuju alone, Watch names the recording that plays,
// and every other page names itself.
export function pageTitle(page, watchTitle = null) {
    if (!page || page === 'home') {
        return t('structure.name');
    }
    if (page === 'watch' && watchTitle) {
        return t('structure.title', { title: watchTitle });
    }
    return t('structure.title', { title: pageName(page) });
}

export class PageStructure {
    constructor(app) {
        this.app = app;
        this.watchTitle = null;
        this.main = document.getElementById('pages');
        // One heading for the page in view, kept for a screen reader. A page with an h1 of its
        // own keeps that one, and the heading stays away there.
        this.heading = document.createElement('h1');
        this.heading.id = 'page-name';
        this.heading.className = 'sr-only';
        this.live = document.createElement('p');
        this.live.className = 'sr-only';
        this.live.setAttribute('aria-live', 'polite');
        this.live.id = 'page-live';
        if (this.main) {
            this.main.prepend(this.heading);
            this.main.after(this.live);
            // Pages build their parts as they show, so the heading looks again when they change.
            let queued = false;
            new MutationObserver(() => {
                if (!queued) {
                    queued = true;
                    requestAnimationFrame(() => {
                        queued = false;
                        this.placeHeading();
                    });
                }
            }).observe(this.main, { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden'] });
        }
        const skip = document.querySelector('.skip-link');
        if (skip) {
            skip.addEventListener('click', (e) => {
                e.preventDefault();
                this.main?.focus();
            });
        }
        this.update(app.page, false);
    }

    // The title of the recording that plays on Watch, or null without one.
    setWatchTitle(title) {
        this.watchTitle = title || null;
        document.title = pageTitle(this.app.page, this.watchTitle);
    }

    // Shows the heading of the page in view unless the page shows an h1 of its own.
    placeHeading() {
        const section = document.getElementById(`page-${this.app.page}`);
        const own = section && [...section.querySelectorAll('h1')].some((node) => node.getClientRects().length > 0);
        const hidden = this.app.page === 'home' || !!own;
        if (this.heading.hidden !== hidden) {
            this.heading.hidden = hidden;
        }
    }

    // Names the page in view. With say, the change is also said aloud, unless the focus moved
    // into the page, where the name of the main region already says it.
    update(page, say = true) {
        const name = pageName(page);
        document.title = pageTitle(page, this.watchTitle);
        this.heading.textContent = name;
        this.placeHeading();
        if (this.main) {
            this.main.setAttribute('aria-label', name);
        }
        if (say && !(this.main && this.main.contains(document.activeElement))) {
            // A fresh text each time, so the same page named twice is read twice.
            this.live.textContent = '';
            setTimeout(() => {
                this.live.textContent = t('structure.live', { name });
            }, 50);
        }
    }
}
