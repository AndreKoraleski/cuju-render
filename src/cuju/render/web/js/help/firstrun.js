// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// A friendlier first run. A short tip on each page points to the next thing to try, until it is
// dismissed, and the settings turn the tips off or bring them back. The main controls carry a
// line of help, which shows on keyboard focus, and on hover for a control without a title of its
// own. The empty Watch page also points to the demo and the samples. A tip takes the first corner
// of the window where it covers no control of the page and no notice. The browser keeps every
// dismissal, and the rules at the top of the file touch nothing of the page.

import { t, tm, tn } from '../core/i18n.js';
import { icon, symbolOnly } from '../core/icons.js';

export const TIPS_KEY = 'cuju.tips';

// The tip of each page, shown once until dismissed, the message firstrun.tip.<page>. The tip of
// Watch waits for a match.
export const TIPS = Object.fromEntries(['home', 'watch', 'recordings', 'matches', 'tournaments', 'teams', 'play', 'field']
    .map((page) => [page, t(`firstrun.tip.${page}`)]));

// The line of help of each main control by its id, the message firstrun.help.<id>.
export const HELP_TEXT = Object.fromEntries([
    'home-btn', 'open-palette', 'open-settings', 'fullscreen', 'match-menu-btn', 'view-menu-btn',
    'address-input', 'timeline', 'speed', 'mute', 'volume', 'live-env-index',
].map((id) => [id, t(`firstrun.help.${id}`)]));
// The line of help of each page's tab, the message firstrun.tab.<page> after the name of the page,
// since a tab of a middle-sized screen shows its symbol alone.
const TAB_HELP = Object.fromEntries(['watch', 'play', 'recordings', 'matches', 'tournaments', 'teams', 'field', 'help']
    .map((page) => [page, t('symbol.tip', { name: t(`html.nav.${page}`), text: t(`firstrun.tab.${page}`) })]));

// The corners a tip may take, in the order it tries them, the lower left first.
export const TIP_SPOTS = ['bottom-left', 'bottom-right', 'top-right', 'top-left'];

// The spot to take, given how many controls each spot would cover. The spot the tip holds stays
// while it covers nothing, else the first clear spot in order, else the one that covers least.
export function chooseSpot(current, covers) {
    const order = TIP_SPOTS.includes(current) ? [current, ...TIP_SPOTS.filter((spot) => spot !== current)] : TIP_SPOTS;
    let best = order[0];
    for (const spot of order) {
        const count = covers(spot);
        if (count === 0) {
            return spot;
        }
        if (count < covers(best)) {
            best = spot;
        }
    }
    return best;
}

// The controls of the page that a click or a press would reach.
const CONTROL = 'button, a[href], input, select, textarea, summary, [tabindex]:not([tabindex="-1"]), tbody tr, [role="row"], .challenge-item';

// The stored state of the tips, the pages whose tip was dismissed and whether tips are off.
export function tipState(stored) {
    const source = stored && typeof stored === 'object' ? stored : {};
    const dismissed = Array.isArray(source.dismissed) ? source.dismissed.filter((page) => page in TIPS) : [];
    return { dismissed: [...new Set(dismissed)], off: source.off === true };
}

// The tip that a page shows, or null when it has none, it was dismissed or tips are off.
export function tipFor(page, state) {
    const clean = tipState(state);
    return !clean.off && page in TIPS && !clean.dismissed.includes(page) ? TIPS[page] : null;
}

// The state after a page's tip is dismissed.
export function dismissTip(state, page) {
    const clean = tipState(state);
    return { ...clean, dismissed: clean.dismissed.includes(page) ? clean.dismissed : [...clean.dismissed, page] };
}

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
        return tipState(JSON.parse(localStorage.getItem(TIPS_KEY)));
    } catch {
        return tipState(null);
    }
}

export class FirstRun {
    constructor(app) {
        this.app = app;
        this.state = loadState();
        this.page = null;
        this.tip = h('aside', { id: 'tip', class: 'tip', 'aria-label': t('firstrun.tip.label'), hidden: true },
            this.tipText = h('p', { class: 'tip-text' }),
            h('div', { class: 'tip-actions' },
                h('button', { type: 'button', class: 'btn small', ...symbolOnly(t('firstrun.gotIt')), onclick: () => this.dismiss() }, icon('check')),
                h('button', { type: 'button', class: 'link small', onclick: () => this.setOff(true) }, t('firstrun.noMore'))));
        this.tooltip = h('div', { id: 'help-tip', class: 'help-tip', role: 'tooltip', hidden: true });
        // The tip comes right after the top bar in the order of the Tab key, before the page.
        const pages = document.getElementById('pages');
        if (pages) {
            pages.before(this.tip);
            pages.after(this.tooltip);
        } else {
            (document.getElementById('app') || document.body).append(this.tip, this.tooltip);
        }
        this.bindSetting();
        this.bindHelp();
        this.bindWatchEmpty();
        // The page in view decides the tip, at once on a change of page and a few times a second
        // for whatever else opens over it.
        const root = document.getElementById('app');
        if (root) {
            new MutationObserver(() => this.update()).observe(root, { attributes: true, attributeFilter: ['data-page', 'class'] });
        }
        setInterval(() => this.update(), 400);
        this.update();
    }

    save() {
        try {
            localStorage.setItem(TIPS_KEY, JSON.stringify(this.state));
        } catch {
            // Storage can be unavailable, dismissals then last for this visit only.
        }
    }

    // The page's tip, once the page has shown for a moment, and none over broadcast mode, a game,
    // a dialog, a menu or the palette.
    update() {
        const app = this.app;
        const page = app.page;
        if (page !== this.page) {
            this.page = page;
            this.since = performance.now();
        }
        const text = tipFor(page, this.state);
        const shown = (node) => node.getClientRects().length > 0;
        // A game on Play keeps the picture clear, so its tip waits on the setup card.
        const game = page === 'play' && app.play && app.play.stage && !app.play.stage.hidden;
        const busy = app.tvMode || game || (page === 'watch' && !app.source) || !!(app.photo && app.photo.isOpen)
            || [...document.querySelectorAll('dialog[open], [role="dialog"], .dd-panel.open')].some(shown);
        const show = !!text && !busy && performance.now() - this.since > 1200;
        if (this.tip.dataset.page !== page) {
            this.tip.hidden = true;
        }
        // The tip shows with its marks, its words in bold and its shortcuts as keycaps.
        if (show && this.tipText.dataset.tip !== page) {
            this.tipText.dataset.tip = page;
            this.tipText.replaceChildren(...tn('firstrun.tip.line', { text: tm(`firstrun.tip.${page}`) }));
        }
        if (this.tip.hidden === show) {
            this.tip.hidden = !show;
            this.tip.dataset.page = page;
        }
        if (show) {
            this.place();
        }
    }

    // Moves the tip to a corner where it covers no control and no notice that shows.
    place() {
        const tip = this.tip;
        const toast = document.getElementById('toast');
        const counts = {};
        const covers = (spot) => {
            if (!(spot in counts)) {
                tip.dataset.spot = spot;
                counts[spot] = this.covered(tip.getBoundingClientRect(), toast);
            }
            return counts[spot];
        };
        const spot = chooseSpot(tip.dataset.spot, covers);
        tip.dataset.spot = spot;
    }

    // How many controls of the page lie under a box, a notice that shows counting as one.
    covered(box, toast) {
        if (!box.width) {
            return 0;
        }
        const found = new Set();
        const pages = document.getElementById('pages');
        for (let x = box.left + 6; x < box.right; x += Math.max(20, (box.width - 12) / 6)) {
            for (let y = box.top + 6; y < box.bottom; y += Math.max(14, (box.height - 12) / 4)) {
                for (const node of document.elementsFromPoint(x, y)) {
                    const control = node.closest(CONTROL);
                    if (control && !this.tip.contains(control) && (!pages || pages.contains(control))) {
                        found.add(control);
                    }
                }
            }
        }
        // A region that holds the whole tip, such as a scrolling list, is no control under it.
        const holds = (node) => {
            const r = node.getBoundingClientRect();
            return r.left <= box.left && r.right >= box.right && r.top <= box.top && r.bottom >= box.bottom;
        };
        let count = [...found].filter((node) => !holds(node)).length;
        if (toast && toast.classList.contains('show') && toast.textContent) {
            const t = toast.getBoundingClientRect();
            if (t.left < box.right && t.right > box.left && t.top < box.bottom && t.bottom > box.top) {
                count += 1;
            }
        }
        return count;
    }

    dismiss() {
        const focused = this.tip.contains(document.activeElement);
        this.state = dismissTip(this.state, this.tip.dataset.page || this.app.page);
        this.save();
        this.tip.hidden = true;
        if (focused) {
            document.getElementById('pages')?.focus({ preventScroll: true });
        }
        this.update();
    }

    setOff(off) {
        const focused = this.tip.contains(document.activeElement);
        // Turning the tips on again brings back every tip.
        this.state = off ? { ...this.state, off: true } : { dismissed: [], off: false };
        this.save();
        if (this.box) {
            this.box.checked = !off;
        }
        this.tip.hidden = true;
        if (focused) {
            document.getElementById('pages')?.focus({ preventScroll: true });
        }
        this.update();
    }

    // A box of the settings panel turns the tips off and on.
    bindSetting() {
        const anchor = document.getElementById('saved-style')?.closest('label');
        if (!anchor) {
            return;
        }
        this.box = h('input', { type: 'checkbox', id: 'tips-on' });
        this.box.checked = !this.state.off;
        this.box.addEventListener('change', () => this.setOff(!this.box.checked));
        const help = anchor.nextElementSibling && anchor.nextElementSibling.matches('p') ? anchor.nextElementSibling : anchor;
        help.after(h('label', { class: 'check' }, this.box, ` ${t('firstrun.setting')}`));
    }

    // The line of help of a control shows on keyboard focus, and on hover when the control has no
    // title for the browser to show. A control that shows its symbol alone shows its title the same
    // way on keyboard focus, so its name reads by keyboard as it does by mouse. Esc, a click, a key
    // or leaving the control hides it.
    bindHelp() {
        for (const [id, text] of Object.entries(HELP_TEXT)) {
            document.getElementById(id)?.setAttribute('data-help', text);
        }
        for (const button of document.querySelectorAll('#topbar .menu [data-page]')) {
            if (TAB_HELP[button.dataset.page]) {
                button.dataset.help = TAB_HELP[button.dataset.page];
            }
        }
        let timer = null;
        const target = (node) => (node instanceof Element ? node.closest('[data-help], [data-symbol], .icon-btn[title], .text-btn[title]') : null);
        document.addEventListener('focusin', (e) => {
            const node = target(e.target);
            if (node && node.matches(':focus-visible')) {
                this.showHelp(node);
            } else {
                this.hideHelp();
            }
        });
        document.addEventListener('focusout', () => this.hideHelp());
        document.addEventListener('pointerover', (e) => {
            const node = target(e.target);
            clearTimeout(timer);
            if (node && e.pointerType === 'mouse' && !node.title) {
                timer = setTimeout(() => this.showHelp(node), 600);
            }
        });
        document.addEventListener('pointerout', (e) => {
            if (target(e.target) === this.helpFor) {
                clearTimeout(timer);
                this.hideHelp();
            }
        });
        document.addEventListener('pointerdown', () => {
            clearTimeout(timer);
            this.hideHelp();
        }, true);
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !this.tooltip.hidden) {
                this.hideHelp();
            }
        }, true);
    }

    showHelp(node) {
        const rect = node.getBoundingClientRect();
        if (!rect.width || this.app.tvMode) {
            return;
        }
        const text = node.dataset.help || node.title || node.getAttribute('aria-label') || '';
        if (!text) {
            return;
        }
        this.hideHelp();
        this.helpFor = node;
        this.tooltip.textContent = text;
        this.tooltip.hidden = false;
        const own = node.getAttribute('aria-describedby') || '';
        // A tooltip that only repeats the name of its control adds nothing for a screen reader.
        if (text !== node.getAttribute('aria-label') && !own.split(' ').includes('help-tip')) {
            node.setAttribute('aria-describedby', `${own} help-tip`.trim());
        }
        const box = this.tooltip.getBoundingClientRect();
        const below = rect.bottom + 6 + box.height < window.innerHeight;
        const left = Math.max(8, Math.min(window.innerWidth - box.width - 8, rect.left + rect.width / 2 - box.width / 2));
        this.tooltip.style.left = `${left}px`;
        this.tooltip.style.top = `${below ? rect.bottom + 6 : rect.top - box.height - 6}px`;
    }

    hideHelp() {
        const node = this.helpFor;
        this.helpFor = null;
        this.tooltip.hidden = true;
        if (node) {
            const rest = (node.getAttribute('aria-describedby') || '').split(' ').filter((id) => id && id !== 'help-tip');
            if (rest.length) {
                node.setAttribute('aria-describedby', rest.join(' '));
            } else {
                node.removeAttribute('aria-describedby');
            }
        }
    }

    // The empty Watch page offers the demo and the samples as the next step.
    bindWatchEmpty() {
        const empty = document.getElementById('watch-empty');
        if (!empty) {
            return;
        }
        const offline = empty.querySelector('.offline-note');
        empty.insertBefore(h('p', { class: 'muted small watch-next' }, tn('firstrun.watch.next', {
            command: h('code', {}, 'cuju render demo'),
            sample: h('button', { type: 'button', class: 'link', onclick: () => this.openSample() }, t('firstrun.watch.sample')),
        })), offline);
    }

    async openSample() {
        const app = this.app;
        try {
            const { api } = await import('../core/api.js');
            const list = await api.matches();
            const sample = list.find((m) => m.id === 'sample-5v5') || list.find((m) => m.id === 'sample-11v11') || list[0];
            if (sample) {
                app.openMatchInWatch(sample.id);
                return;
            }
        } catch {
            // The Recordings page says what is wrong with the library.
        }
        app.hud.toast(t('firstrun.noRecording'), 'info', 5000);
        app.showPage('recordings');
    }

    // Shows the Making a team topic of the Help page.
    helpTopic(id) {
        if (this.app.palette) {
            this.app.palette.helpTopic(id);
        } else {
            this.app.showPage('help');
        }
    }
}
