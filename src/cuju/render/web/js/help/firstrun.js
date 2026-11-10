// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// A friendlier first run. A short tip on each page points to the next thing to try, until it is
// dismissed, and the settings turn the tips off or bring them back. The main controls carry a
// line of help, which shows on keyboard focus, and on hover for a control without a title of its
// own. The empty Watch page also points to the demo and the samples. The browser keeps every
// dismissal, and the rules at the top of the file touch nothing of the page.

export const TIPS_KEY = 'cuju.tips';

// The tip of each page, shown once until dismissed. The tip of Watch waits for a match.
export const TIPS = {
    home: 'Ctrl K opens the command palette, which reaches every page, recording and setting.',
    watch: 'V cycles the cameras, R replays the last goal, and the Match menu lists the goals.',
    recordings: 'Details keeps a favorite mark, tags and notes on the selected recording.',
    matches: 'An agent added on the Teams page joins the team lists here.',
    teams: 'Choose a team to dress it, with a kit, a model, celebrations, sounds and sponsors.',
    play: 'A controller plays too, and Input settings change the keys and the dead zone.',
    field: 'A preset sets the arena, the grass, the hour and the weather at once.',
};

// The line of help of each main control.
export const HELP_TEXT = {
    'home-btn': 'Home, the way into every page',
    'open-palette': 'Search every page, recording and setting, Ctrl K',
    'open-settings': 'Presets, presentation, sound levels, motion and theme',
    fullscreen: 'Fill the screen, F',
    'match-menu-btn': 'Open a recording, a live source or a goal of the match',
    'view-menu-btn': 'Camera, time of day, weather, arena, quality and theme',
    'address-input': 'The id of a live source or a recording, then Enter',
    timeline: 'Seek with a click or a drag, the arrows step 5 seconds',
    speed: 'Playback speed, the Up and Down arrows change it',
    mute: 'Sound starts muted, M turns it on and off',
    volume: 'Volume of every sound of the page',
    'live-env-index': 'Show another environment of the batch',
};
const TAB_HELP = {
    watch: 'Watch a recording or a live source',
    play: 'Play a game against the built-in AI',
    recordings: 'The library of saved matches',
    matches: 'Request a match between two teams',
    teams: 'Add agents and dress their teams',
    field: 'The arena, the grass, the sky and the crowd',
    help: 'Keys, controls and guides',
};

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
        this.tip = h('aside', { id: 'tip', class: 'tip', 'aria-label': 'Tip', hidden: true },
            this.tipText = h('p', { class: 'tip-text' }),
            h('div', { class: 'tip-actions' },
                h('button', { type: 'button', class: 'btn small', onclick: () => this.dismiss() }, 'Got it'),
                h('button', { type: 'button', class: 'link small', onclick: () => this.setOff(true) }, 'No more tips')));
        this.tooltip = h('div', { id: 'help-tip', class: 'help-tip', role: 'tooltip', hidden: true });
        (document.getElementById('app') || document.body).append(this.tip, this.tooltip);
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
        const busy = app.tvMode || game || (page === 'watch' && !app.source)
            || [...document.querySelectorAll('dialog[open], [role="dialog"], .dd-panel.open')].some(shown);
        const show = !!text && !busy && performance.now() - this.since > 1200;
        if (this.tip.dataset.page !== page) {
            this.tip.hidden = true;
        }
        if (show && this.tipText.textContent !== `Tip. ${text}`) {
            this.tipText.textContent = `Tip. ${text}`;
        }
        if (this.tip.hidden === show) {
            this.tip.hidden = !show;
            this.tip.dataset.page = page;
        }
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
        help.after(h('label', { class: 'check' }, this.box, ' Tips for new visitors, on again brings back every tip'));
    }

    // The line of help of a control shows on keyboard focus, and on hover when the control has no
    // title for the browser to show. Esc, a click, a key or leaving the control hides it.
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
        const target = (node) => (node instanceof Element ? node.closest('[data-help]') : null);
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
        this.hideHelp();
        this.helpFor = node;
        this.tooltip.textContent = node.dataset.help;
        this.tooltip.hidden = false;
        const own = node.getAttribute('aria-describedby') || '';
        if (!own.split(' ').includes('help-tip')) {
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
        empty.insertBefore(h('p', { class: 'muted small watch-next' },
            'New here? The command ', h('code', {}, 'cuju render demo'), ' streams a live match, and ',
            h('button', { type: 'button', class: 'link', onclick: () => this.openSample() }, 'a sample match'),
            ' opens at once.'), offline);
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
        app.hud.toast('The library holds no recording yet. The command cuju render sample adds the samples.', 'info', 5000);
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
