// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The command palette, a searchable list of everything the page does. Ctrl K, or the button in
// the top bar, opens it on any page, except while a text field has the focus, which keeps its own
// keys. Typing narrows the list by fuzzy matching, the arrows move through it, Enter runs the
// chosen action and Esc closes it, and focus then returns to where it was. The actions reach every
// page, the newest recordings and the live sources, a game in each scenario, a requested match,
// the settings, the choices of the View menu, the players of the open match and the help topics.
// The matching at the top of the file touches nothing of the page, so it holds the same in a test.

import { listedScenarios, scenarioName, titleText } from '../core/scenarios.js';

// The most entries the list shows at once.
export const LIMIT = 60;

// Lower case without accents, so a query matches whatever way a name is written.
export function fold(text) {
    return String(text ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
}

// How well one word of a query matches a text, or null when its letters do not all appear in
// order. Each letter found scores one, a letter right after the last one found three more, a
// letter that starts a word of the text five more, and a word that the query starts eight more.
export function matchScore(query, text) {
    const q = fold(query).trim();
    const t = fold(text);
    if (!q) {
        return 0;
    }
    let score = 0;
    let from = 0;
    let last = -2;
    for (const letter of q) {
        const at = t.indexOf(letter, from);
        if (at < 0) {
            return null;
        }
        score += 1;
        if (at === last + 1) {
            score += 3;
        }
        if (at === 0 || /[^a-z0-9]/.test(t[at - 1])) {
            score += 5;
        }
        last = at;
        from = at + 1;
    }
    if (new RegExp(`(^|[^a-z0-9])${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`).test(t)) {
        score += 8;
    }
    return score;
}

// The actions that match a query, best first, each with its score. Every word of the query must
// match the title or the keywords of an action, and a word found in the title counts more. Equal
// scores keep the order of the list, so an empty query shows the list as it stands.
export function rankActions(query, actions, limit = LIMIT) {
    const words = fold(query).split(/\s+/).filter(Boolean);
    const ranked = [];
    actions.forEach((action, order) => {
        let total = 0;
        for (const word of words) {
            const inTitle = matchScore(word, action.title);
            const inWords = matchScore(word, `${action.group || ''} ${action.keywords || ''} ${action.hint || ''}`);
            const best = Math.max(inTitle === null ? -1 : inTitle * 2, inWords === null ? -1 : inWords);
            if (best < 0) {
                return;
            }
            total += best;
        }
        ranked.push({ action, score: total, order });
    });
    ranked.sort((a, b) => b.score - a.score || a.order - b.order);
    return ranked.slice(0, limit).map((entry) => ({ ...entry.action, score: entry.score }));
}

// The help topics, each a heading of the Help page.
export const HELP_TOPICS = [
    ['help-keyboard', 'Keyboard', 'tab focus keys navigation'],
    ['help-start', 'Getting started', 'first steps record watch live'],
    ['help-pages', 'Pages', 'home teams field'],
    ['help-teams', 'Making a team', 'agent submission kaggle main.py idle'],
    ['help-play', 'Play controls', 'keys controller gamepad touch'],
    ['help-playback', 'Playback keys', 'pause seek speed goal replay'],
    ['help-cameras', 'Camera keys', 'broadcast tactical follow free'],
    ['help-view', 'View keys', 'broadcast mode fullscreen mute'],
];

const PAGES = [
    ['home', 'Home'], ['watch', 'Watch'], ['play', 'Play'], ['recordings', 'Recordings'],
    ['matches', 'Matches'], ['tournaments', 'Tournaments'], ['teams', 'Teams'], ['field', 'Field'], ['help', 'Help'],
];
const TIMES = [['dawn', 'Dawn', 6.5], ['day', 'Day', 15], ['dusk', 'Dusk', 19], ['night', 'Night', 22]];

function h(tag, attributes = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) {
        if (value !== null && value !== undefined && value !== false) {
            node.setAttribute(key, value === true ? '' : value);
        }
    }
    node.append(...children.flat().filter((child) => child !== null && child !== undefined));
    return node;
}

// Whether keys typed at a node go into text, which the palette never takes them from.
function typing(node) {
    if (!(node instanceof Element)) {
        return false;
    }
    if (node.closest('textarea, select, [contenteditable=""], [contenteditable="true"]')) {
        return true;
    }
    const input = node.closest('input');
    return !!input && !['checkbox', 'radio', 'range', 'button', 'submit', 'reset', 'color', 'file'].includes(input.type);
}

export class CommandPalette {
    constructor(app, { CAMERA_MODES = [], api = null } = {}) {
        this.app = app;
        this.cameraModes = CAMERA_MODES;
        this.api = api;
        this.live = [];
        this.recent = [];
        this.scenarios = [];
        this.shown = [];
        this.active = 0;
        this.returnTo = null;
        this.input = h('input', {
            id: 'palette-input', type: 'text', role: 'combobox', autocomplete: 'off', spellcheck: 'false',
            'aria-expanded': 'true', 'aria-controls': 'palette-list', 'aria-autocomplete': 'list',
            'aria-label': 'Search actions', placeholder: 'Type to search, Enter runs, Esc closes',
        });
        this.list = h('ul', { id: 'palette-list', role: 'listbox', 'aria-label': 'Actions' });
        this.count = h('p', { class: 'palette-count', 'aria-live': 'polite' });
        this.root = h('div', { id: 'palette', role: 'dialog', 'aria-label': 'Command palette', hidden: true },
            h('div', { class: 'palette-box' }, this.input, this.list, this.count));
        (document.getElementById('app') || document.body).append(this.root);
        this.input.addEventListener('input', () => this.render());
        this.input.addEventListener('keydown', (e) => this.onKey(e));
        this.root.addEventListener('pointerdown', (e) => {
            if (e.target === this.root) {
                e.preventDefault();
                this.close(true);
            }
        });
        this.list.addEventListener('click', (e) => {
            const item = e.target.closest('[role="option"]');
            if (item) {
                this.run(Number(item.dataset.index));
            }
        });
        this.list.addEventListener('pointermove', (e) => {
            const item = e.target.closest('[role="option"]');
            if (item && Number(item.dataset.index) !== this.active) {
                this.select(Number(item.dataset.index));
            }
        });
        // Ctrl K opens the palette everywhere but in text, early, before the keys of a page.
        window.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.code === 'KeyK'
                && !e.repeat && (e.target === this.input || !typing(e.target)) && !e.defaultPrevented) {
                e.preventDefault();
                e.stopImmediatePropagation();
                this.toggle();
            }
        }, true);
        const button = document.getElementById('open-palette');
        if (button) {
            button.addEventListener('click', () => this.toggle());
        }
    }

    get isOpen() {
        return !this.root.hidden;
    }

    toggle() {
        if (this.isOpen) {
            this.close(true);
        } else {
            this.open();
        }
    }

    open(query = '') {
        if (this.isOpen) {
            return;
        }
        // The palette needs the mouse and the keys, so a captured pointer goes free.
        if (document.pointerLockElement) {
            document.exitPointerLock();
        }
        const active = document.activeElement;
        this.returnTo = active && active !== document.body ? active : null;
        if (this.app.menus) {
            for (const menu of Object.values(this.app.menus)) {
                if (menu && menu.isOpen && typeof menu.close === 'function') {
                    menu.close(false);
                }
            }
        }
        this.root.hidden = false;
        document.getElementById('app')?.classList.remove('idle');
        this.input.value = query;
        this.input.focus();
        this.render();
        this.refresh();
    }

    // Closes the palette, and with restore gives the focus back to where it was.
    close(restore) {
        if (!this.isOpen) {
            return;
        }
        this.root.hidden = true;
        this.input.removeAttribute('aria-activedescendant');
        const back = this.returnTo;
        this.returnTo = null;
        if (restore && back && back.isConnected && back.getClientRects().length && !back.closest('[hidden], [inert]')) {
            back.focus({ preventScroll: true });
        } else if (restore && document.activeElement === this.input) {
            this.input.blur();
        }
    }

    // The live sources, the newest recordings and the scenarios, read anew on each opening.
    refresh() {
        const api = this.api;
        if (!api) {
            return;
        }
        const token = (this.token = (this.token || 0) + 1);
        const done = () => {
            if (token === this.token && this.isOpen) {
                this.render(true);
            }
        };
        api.live().then((list) => {
            this.live = Array.isArray(list) ? list : [];
            done();
        }).catch(() => {});
        api.matches().then((list) => {
            const when = (m) => (typeof m.created === 'number' ? m.created * 1000 : Date.parse(m.created) || 0);
            this.recent = (Array.isArray(list) ? list : []).slice().sort((a, b) => when(b) - when(a)).slice(0, 8);
            done();
        }).catch(() => {});
        if (!this.scenarios.length) {
            api.scenarios().then((list) => {
                this.scenarios = listedScenarios(Array.isArray(list) ? list : []);
                done();
            }).catch(() => {});
        }
    }

    // Every action as the page stands, each with a title, a group, words to find it by, a hint and
    // what it does.
    actions() {
        const app = this.app;
        const list = [];
        const add = (group, title, run, keywords = '', hint = '') => list.push({ group, title, run, keywords, hint });
        const watch = () => {
            if (app.page !== 'watch') {
                app.showPage('watch');
            }
        };
        for (const [page, label] of PAGES) {
            if (page !== app.page) {
                add('Pages', `Go to ${label}`, () => app.showPage(page), `page open ${page}`);
            }
        }
        for (const s of this.live) {
            add('Live', `Watch live, ${titleText(s.title, s.scenario) || s.id}`, () => {
                watch();
                app.openLive(s.id);
            }, `source stream ${s.id}`, scenarioName(s.scenario));
        }
        for (const m of this.recent) {
            add('Recordings', `Open ${titleText(m.title, m.scenario) || m.id}`, () => app.openMatchInWatch(m.id),
                `recording match ${m.id} ${(m.teams || []).join(' ')}`, scenarioName(m.scenario));
        }
        add('Matches', 'Request a match', () => {
            app.showPage('matches');
            setTimeout(() => document.querySelector('#page-matches select, #page-matches button')?.focus(), 0);
        }, 'new play teams queue');
        for (const name of this.scenarios) {
            add('Play', `Play a game, ${scenarioName(name)}`, () => this.playScenario(name), 'scenario game start person');
        }
        const players = app.source && app.source.header ? app.source.header.players : [];
        players.forEach((player, k) => {
            let label = '';
            try {
                label = app.playerLabel(k);
            } catch {
                label = `Player ${player.index + 1}`;
            }
            add('Follow', `Follow ${label.replace(/\s+/g, ' ')}`, () => {
                watch();
                app.cameras.followIndex = k;
                app.setCamera('player');
                app.announcePlayer();
            }, 'player camera number name chase');
        });
        const muted = !!(app.settings && app.settings.muted);
        add('Settings', muted ? 'Unmute' : 'Mute', () => app.setMuted(!muted), 'sound volume audio');
        add('Settings', app.tvMode ? 'Leave broadcast mode' : 'Broadcast mode', () => {
            watch();
            app.setTvMode(!app.tvMode);
        }, 'tv television picture alone');
        const labels = document.getElementById('labels-on');
        if (labels) {
            add('Settings', labels.checked ? 'Hide player labels' : 'Show player labels', () => labels.click(), 'names numbers');
        }
        const motion = document.getElementById('motion');
        if (motion) {
            for (const [value, title] of [['reduce', 'Reduced motion'], ['full', 'Full motion'], ['system', 'Motion follows the system']]) {
                if (motion.value !== value) {
                    add('Settings', title, () => this.choose(motion, value), 'animation accessibility');
                }
            }
        }
        const theme = document.getElementById('theme');
        if (theme) {
            for (const [value, title] of [['dark', 'Dark theme'], ['light', 'Light theme'], ['system', 'Theme follows the system']]) {
                if (theme.value !== value) {
                    add('Settings', title, () => this.choose(theme, value), 'colors appearance mode');
                }
            }
        }
        if (app.presets) {
            for (const [name, title] of app.presets.choices()) {
                add('Settings', `${title} preset`, () => app.presets.apply(name), 'presentation replays celebrations show');
            }
        }
        add('Settings', 'Open the settings', () => app.menus && app.menus.settings && app.menus.settings.open(true), 'preferences options');
        for (const mode of this.cameraModes) {
            add('View', `Camera, ${mode.label}`, () => {
                watch();
                app.setCamera(mode.id);
            }, `camera view ${mode.id}`);
        }
        const field = app.fieldPage;
        if (field) {
            const rerender = () => field.root && !field.root.hidden;
            for (const item of document.querySelectorAll('#view-environment [data-arena]')) {
                add('View', `Arena, ${item.textContent.trim()}`, () => field.change({ arena: item.dataset.arena }, rerender()), 'stadium ground place');
            }
            for (const [, title, hour] of TIMES) {
                add('View', `Time of day, ${title}`, () => field.change({ time: hour }, rerender()), 'hour sky light sun');
            }
            for (const item of document.querySelectorAll('#view-environment [data-weather]')) {
                add('View', `Weather, ${item.textContent.trim()}`, () => field.change({ weather: item.dataset.weather }, rerender()), 'rain snow sky');
            }
        }
        add('View', document.fullscreenElement ? 'Leave fullscreen' : 'Fullscreen', () => app.toggleFullscreen(), 'screen');
        for (const [id, title, keywords] of HELP_TOPICS) {
            add('Help', `Help, ${title}`, () => this.helpTopic(id), `help guide ${keywords}`);
        }
        add('Help', 'The full guide', () => window.open('https://github.com/AndreKoraleski/cuju/blob/main/docs/rendering.md', '_blank', 'noopener'), 'documentation docs manual');
        return list;
    }

    // Sets a select of the settings as a person would, so its own handlers save and apply it.
    choose(select, value) {
        select.value = value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
    }

    playScenario(name) {
        const app = this.app;
        const play = app.play;
        if (play && play.setup) {
            play.setup.scenario = name;
            if (app.page === 'play' && play.scenarioSelect && play.scenarioSelect.value !== name) {
                this.choose(play.scenarioSelect, name);
            }
        }
        app.showPage('play');
        if (!play && app.play) {
            // The page builds on its first visit and reads the scenario of its setup once the
            // list of scenarios arrives.
            app.play.setup.scenario = name;
        }
        setTimeout(() => app.play && app.play.startButton && !app.play.setupView.hidden && app.play.startButton.focus(), 0);
    }

    helpTopic(id) {
        this.app.showPage('help');
        const heading = document.getElementById(id);
        if (heading) {
            heading.tabIndex = -1;
            heading.scrollIntoView({ block: 'start' });
            heading.focus({ preventScroll: true });
        }
    }

    render(keep = false) {
        const chosen = keep ? this.shown[this.active] : null;
        this.shown = rankActions(this.input.value, this.actions());
        const again = chosen ? this.shown.findIndex((a) => a.title === chosen.title && a.group === chosen.group) : -1;
        this.active = again >= 0 ? again : 0;
        this.list.replaceChildren(...this.shown.map((action, index) => h('li', {
            id: `palette-item-${index}`, role: 'option', 'data-index': String(index),
            'aria-selected': index === this.active ? 'true' : 'false',
        }, h('span', { class: 'palette-title' }, action.title),
        h('span', { class: 'palette-group' }, action.hint ? `${action.group}, ${action.hint}` : action.group))));
        this.count.textContent = this.shown.length ? `${this.shown.length} ${this.shown.length === 1 ? 'action' : 'actions'}` : 'Nothing matches';
        this.select(this.active);
    }

    select(index) {
        const items = this.list.children;
        if (!items.length) {
            this.input.removeAttribute('aria-activedescendant');
            return;
        }
        this.active = Math.max(0, Math.min(items.length - 1, index));
        for (const item of items) {
            item.setAttribute('aria-selected', Number(item.dataset.index) === this.active ? 'true' : 'false');
        }
        const item = items[this.active];
        this.input.setAttribute('aria-activedescendant', item.id);
        item.scrollIntoView({ block: 'nearest' });
    }

    run(index) {
        const action = this.shown[index];
        if (!action) {
            return;
        }
        this.close(true);
        try {
            action.run();
        } catch (err) {
            this.app.hud.toast(`That action failed, ${err.message}`, 'error');
        }
    }

    onKey(e) {
        const page = Math.max(1, Math.floor(this.list.clientHeight / 40));
        const moves = {
            ArrowDown: this.active + 1, ArrowUp: this.active - 1, PageDown: this.active + page,
            PageUp: this.active - page,
        };
        if (e.key in moves) {
            const count = this.shown.length;
            let next = moves[e.key];
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                next = count ? (next + count) % count : 0;
            }
            this.select(next);
        } else if ((e.key === 'Home' || e.key === 'End') && e.ctrlKey) {
            this.select(e.key === 'Home' ? 0 : this.shown.length - 1);
        } else if (e.key === 'Enter') {
            this.run(this.active);
        } else if (e.key === 'Escape') {
            this.close(true);
        } else if (e.key === 'Tab') {
            // The palette holds a field alone, so Tab stays in it.
        } else {
            return;
        }
        e.preventDefault();
        e.stopPropagation();
    }
}
