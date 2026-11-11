// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The offer to install the page as an app, a small card on Home. It shows once the browser holds
// its own offer, from the second visit on, while the page is no installed app and nothing opens
// over Home, such as the tour, a lesson, a dialog or broadcast mode. Install shows the browser's
// offer, and Not now, or a No in the browser's offer, keeps the card away in this browser for good.
// The Install the app part of Help keeps the install within reach afterwards. Scripts reach the
// card as window.cuju.installOffer.

import { t } from '../core/i18n.js';
import {
    OFFER_KEY, countVisit, dismissOffer, heldPrompt, installedNow, offerShown, offerState,
    onInstallChange, promptInstall,
} from './install-state.js';

function h(tag, attributes = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) {
        if (key.startsWith('on') && typeof value === 'function') {
            node.addEventListener(key.slice(2), value);
        } else if (value !== null && value !== undefined && value !== false) {
            node.setAttribute(key, value === true ? '' : value);
        }
    }
    node.append(...children.flat().filter((child) => child !== null && child !== undefined));
    return node;
}

function loadState() {
    try {
        return offerState(JSON.parse(localStorage.getItem(OFFER_KEY)));
    } catch {
        return offerState(null);
    }
}

function injectStyle() {
    if (document.getElementById('install-offer-style')) {
        return;
    }
    const style = document.createElement('style');
    style.id = 'install-offer-style';
    style.textContent = `
.install-offer { margin: 16px auto 0; padding: 0 16px; max-width: 1120px; box-sizing: border-box; }
.install-offer[hidden] { display: none; }
.install-offer-card { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; justify-content: space-between;
    padding: 12px 14px; border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: 10px;
    background: var(--surface); color: var(--text); }
.install-offer-text { flex: 1 1 280px; min-width: 0; }
.install-offer h2 { margin: 0 0 2px; font-size: 16px; }
.install-offer p { margin: 0; }
.install-offer-actions { display: flex; flex-wrap: wrap; gap: 6px; }
#app.tv .install-offer { display: none; }
`;
    document.head.appendChild(style);
}

export class InstallOffer {
    constructor(app) {
        this.app = app;
        this.state = countVisit(loadState());
        this.save();
        injectStyle();
        this.installButton = h('button', { type: 'button', class: 'btn primary small', onclick: () => this.install() }, t('installOffer.install'));
        this.laterButton = h('button', { type: 'button', class: 'btn small', onclick: () => this.dismiss() }, t('installOffer.later'));
        this.card = h('aside', { id: 'install-offer', class: 'install-offer', 'aria-labelledby': 'install-offer-title', hidden: true },
            h('div', { class: 'install-offer-card' },
                h('div', { class: 'install-offer-text' },
                    h('h2', { id: 'install-offer-title' }, t('installOffer.title')),
                    h('p', {}, t('installOffer.text')),
                    h('p', { class: 'muted small' }, t('installOffer.later.note'))),
                h('div', { class: 'install-offer-actions' }, this.installButton, this.laterButton)));
        this.attach();
        onInstallChange(() => this.update());
        const root = document.getElementById('app');
        if (root) {
            new MutationObserver(() => this.update()).observe(root, { attributes: true, attributeFilter: ['data-page', 'class'] });
        }
        if (window.matchMedia) {
            window.matchMedia('(display-mode: standalone)').addEventListener?.('change', () => this.update());
        }
        // The tour, a lesson and the dialogs open without a change of page, so a slow look follows them.
        this.timer = setInterval(() => this.update(), 1000);
        this.update();
    }

    // The card sits on Home below its opening band, or at the top of Home before that band exists.
    attach() {
        const home = document.getElementById('page-home');
        if (!home || home.contains(this.card)) {
            return;
        }
        const hero = home.querySelector('.home-hero');
        if (hero) {
            hero.after(this.card);
        } else {
            home.prepend(this.card);
        }
    }

    save() {
        try {
            localStorage.setItem(OFFER_KEY, JSON.stringify(this.state));
        } catch {
            // Storage can be unavailable, a dismissal then lasts for this visit only.
        }
    }

    // Whether something opens over Home, which the card then leaves alone.
    busy() {
        const shown = (node) => node.getClientRects().length > 0;
        return !!this.app.tvMode || !!(this.app.photo && this.app.photo.isOpen)
            || [...document.querySelectorAll('dialog[open], [role="dialog"], .dd-panel.open, .lesson-panel')].some(shown);
    }

    shown() {
        return offerShown({
            state: this.state, prompt: heldPrompt(), installed: installedNow(), page: this.app.page, busy: this.busy(),
        });
    }

    update() {
        this.attach();
        const show = this.shown();
        if (this.card.hidden === show) {
            // Focus inside a card that goes moves to the page, so the keyboard keeps its place.
            if (!show && this.card.contains(document.activeElement)) {
                document.getElementById('pages')?.focus({ preventScroll: true });
            }
            this.card.hidden = !show;
        }
    }

    async install() {
        const { outcome } = await promptInstall();
        // A No in the browser's own offer counts as Not now.
        if (outcome === 'dismissed') {
            this.state = dismissOffer(this.state);
            this.save();
        }
        this.update();
        return { outcome };
    }

    dismiss() {
        this.state = dismissOffer(this.state);
        this.save();
        this.update();
    }

    // The functions of window.cuju.installOffer.
    script() {
        return {
            state: () => ({ ...offerState(this.state), shown: !this.card.hidden, prompt: !!heldPrompt(), installed: installedNow() }),
            install: () => this.install(),
            dismiss: () => this.dismiss(),
        };
    }
}
