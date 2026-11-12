// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The command palette, a searchable list of everything the page does. Ctrl K, or the button in
// the top bar, opens it on any page, except while a text field has the focus, which keeps its own
// keys. Typing narrows the list by fuzzy matching, the arrows move through it, Enter runs the
// chosen action and Esc closes it, and focus then returns to where it was. The actions reach every
// page, the newest recordings and the live sources, a game in each scenario, a requested match,
// the settings, the choices of the View menu, the players of the open match and the help topics.
// The matching at the top of the file touches nothing of the page, so it holds the same in a test.
// The titles and groups show in the page's language, and every action stays findable by its
// English words too, as searchWords puts them beside the words of the language.

import { recordingTitle, summaryTeams } from '../core/names.js';
import { listedScenarios, scenarioName } from '../core/scenarios.js';
import { language, serverText, storedLanguage, t, tOr } from '../core/i18n.js';
import { spoilerFree } from '../core/spoilers.js';
import { chord } from '../core/keys.js';
import { PAGES } from '../core/page-structure.js';

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

// The words an action is found by, its English words, with the words of the message id in the
// page's language beside them when they differ, so a query in either language finds it.
export function searchWords(id, english = '') {
    const own = id ? tOr(id, english) : english;
    return own && own !== english ? `${english} ${own}`.trim() : english;
}

// The languages the palette offers, each usable language other than the one shown, then
// following the browser while a language is chosen. A choice whose code is null follows the
// browser.
export function languageChoices(languages, shown, chosen = null) {
    const list = (Array.isArray(languages) ? languages : [])
        .filter((entry) => entry && entry.code && entry.usable !== false && entry.code !== (chosen || shown))
        .map((entry) => ({ code: entry.code, name: entry.name || entry.code }));
    if (chosen) {
        list.push({ code: null, name: null });
    }
    return list;
}

// The groups of the list by their English names, each the message palette.group.<key>.
const GROUPS = {
    Pages: 'pages', Live: 'live', Recordings: 'recordings', Matches: 'matches', Play: 'play',
    Challenges: 'challenges', Teams: 'teams', Tournaments: 'tournaments', Follow: 'follow', Settings: 'settings', View: 'view', Help: 'help',
};

// The keys of the Watch page that choose a camera, which its actions show.
const CAMERA_KEYS = { ball: 'B', owner: 'P' };

// An action of the list. The group shows in the page's language, and its English name joins the
// words when the two differ, so English queries keep finding the group. keys names the shortcut
// that does the same on its page, such as `T`, which the list shows as keycaps.
export function paletteAction(group, title, run, keywords = '', hint = '', keys = '') {
    const key = GROUPS[group];
    const shown = key ? t(`palette.group.${key}`) : group;
    const words = shown !== group ? `${keywords} ${group}`.trim() : keywords;
    return { group: shown, title, run, keywords: words, hint, keys };
}

// The help topics, each a heading of the Help page, with its title and its words to find it by,
// the messages palette.topic.<key>.title and .words.
export const HELP_TOPICS = [
    ['help-keyboard', 'keyboard', 'tab focus keys navigation'],
    ['help-start', 'start', 'first steps record watch live'],
    ['help-pages', 'pages', 'home teams field'],
    ['help-teams', 'teams', 'agent submission kaggle main.py idle'],
    ['help-play', 'play', 'keys controller gamepad touch'],
    ['help-playback', 'playback', 'pause seek speed goal replay'],
    ['help-cameras', 'cameras', 'broadcast tactical follow free'],
    ['help-view', 'view', 'broadcast mode fullscreen mute'],
].map(([id, key, words]) => [id, t(`palette.topic.${key}.title`), searchWords(`palette.topic.${key}.words`, words)]);

// The times of day, each named by the message palette.time.<key>.
const TIMES = [['dawn', 6.5], ['day', 15], ['dusk', 19], ['night', 22]];

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
        this.challenges = [];
        this.cups = [];
        this.shown = [];
        this.active = 0;
        this.returnTo = null;
        this.input = h('input', {
            id: 'palette-input', type: 'text', role: 'combobox', autocomplete: 'off', spellcheck: 'false',
            'aria-expanded': 'true', 'aria-controls': 'palette-list', 'aria-autocomplete': 'list',
            'aria-label': t('palette.search'), placeholder: t('palette.placeholder'),
        });
        this.list = h('ul', { id: 'palette-list', role: 'listbox', 'aria-label': t('palette.list') });
        this.count = h('p', { class: 'palette-count', 'aria-live': 'polite' });
        this.root = h('div', { id: 'palette', role: 'dialog', 'aria-label': t('palette.label'), hidden: true },
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
        import('../play/tournament.js').then((m) => m.tournamentsApi.list()).then((list) => {
            this.cups = Array.isArray(list) ? list.slice(0, 8) : [];
            done();
        }).catch(() => {});
        import('../play/challenges.js').then((m) => m.challengeApi.list()).then((list) => {
            this.challenges = Array.isArray(list) ? list : [];
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
        const add = (group, title, run, keywords = '', hint = '', keys = '') => list.push(paletteAction(group, title, run, keywords, hint, keys));
        if (app.moments) {
            list.push(...app.moments.paletteActions(this.input.value, () => this.isOpen && this.render(true)));
        }
        const watch = () => {
            if (app.page !== 'watch') {
                app.showPage('watch');
            }
        };
        // The pages, each named by the message palette.page.<page>.
        for (const page of PAGES) {
            if (page !== app.page) {
                add('Pages', t('palette.go', { page: t(`palette.page.${page}`) }), () => app.showPage(page),
                    `${searchWords('palette.words.page', 'page open')} ${page}`, '', page === 'help' ? 'H' : '');
            }
        }
        for (const s of this.live) {
            add('Live', t('palette.live', { title: recordingTitle(s) || s.id }), () => {
                watch();
                app.openLive(s.id);
            }, `${searchWords('palette.words.live', 'source stream')} ${s.id}`, scenarioName(s.scenario));
        }
        for (const m of this.recent) {
            add('Recordings', t('palette.open', { title: recordingTitle(m) || m.id }), () => app.openMatchInWatch(m.id),
                `${searchWords('palette.words.recording', 'recording match')} ${m.id} ${[...(m.teams || []), ...summaryTeams(m)].join(' ')}`, scenarioName(m.scenario));
        }
        // The Brackets view of each recent tournament, and Watch next of one without spoilers.
        for (const cup of this.cups) {
            const name = serverText(cup, 'name');
            add('Tournaments', t('palette.brackets', { name }), () => {
                app.showPage('tournaments');
                app.tournaments.openBrackets(cup.id);
            }, `${searchWords('palette.words.brackets', 'bracket tournament table groups draw big')} ${name}`);
            if (spoilerFree(cup.id)) {
                add('Tournaments', t('palette.watchNext', { name }), () => app.tournaments.watchNextOf(cup.id),
                    `${searchWords('palette.words.watchNext', 'tournament spoilers next match watch')} ${name}`);
            }
        }
        add('Matches', t('palette.request'), () => {
            app.showPage('matches');
            setTimeout(() => document.querySelector('#page-matches select, #page-matches button')?.focus(), 0);
        }, searchWords('palette.words.request', 'new play teams queue'));
        for (const name of this.scenarios) {
            add('Play', t('palette.play', { scenario: scenarioName(name) }), () => this.playScenario(name),
                searchWords('palette.words.play', 'scenario game start person'));
        }
        add('Challenges', t('palette.challenges'), () => this.showChallenge(null),
            searchWords('palette.words.challenges', 'challenge drill medal leaderboard achievement'));
        for (const c of this.challenges) {
            add('Challenges', t('palette.challenge', { title: tOr(`challenge.${c.id}.title`, c.title) }), () => this.showChallenge(c.id),
                `${searchWords('palette.words.challenge', 'challenge drill medal leaderboard')} ${c.id}`, scenarioName(c.scenario));
        }
        const editing = !!(app.editor && app.editor.isOpen && app.editor.team);
        add('Teams', editing ? t('palette.surprise.look') : t('palette.surprise.team'), () => {
            app.showPage('teams');
            if (editing && typeof app.surprise === 'function') {
                app.surprise({ apply: true });
            }
            setTimeout(() => document.querySelector(editing ? '#team-editor .surprise-go' : '#teams-side .surprise-go')?.focus(), 0);
        }, searchWords('palette.words.surprise', 'surprise random generate kit name colors seed team'));
        const players = app.source && app.source.header ? app.source.header.players : [];
        players.forEach((player, k) => {
            let label = '';
            try {
                label = app.playerLabel(k);
            } catch {
                label = t('palette.player', { number: player.index + 1 });
            }
            add('Follow', t('palette.follow', { player: label.replace(/\s+/g, ' ') }), () => {
                watch();
                app.cameras.followIndex = k;
                app.setCamera('player');
                app.announcePlayer();
            }, searchWords('palette.words.follow', 'player camera number name chase'));
        });
        const muted = !!(app.settings && app.settings.muted);
        add('Settings', muted ? t('palette.unmute') : t('palette.mute'), () => app.setMuted(!muted), searchWords('palette.words.mute', 'sound volume audio'), '', 'M');
        add('Settings', app.tvMode ? t('palette.tv.leave') : t('palette.tv'), () => {
            watch();
            app.setTvMode(!app.tvMode);
        }, searchWords('palette.words.tv', 'tv television picture alone'), '', 'T');
        if (app.captions) {
            add('Settings', app.captions.enabled ? t('palette.captions.off') : t('palette.captions.on'),
                () => app.captions.setEnabled(!app.captions.enabled), searchWords('palette.words.captions', 'subtitles text events accessibility'));
        }
        if (app.feedDialog) {
            add('View', t('palette.feed'), () => {
                watch();
                app.feedDialog.open();
            }, searchWords('palette.words.feed', 'obs stream streaming browser source clean feed url size vertical'));
        }
        const labels = document.getElementById('labels-on');
        if (labels) {
            add('Settings', labels.checked ? t('palette.labels.hide') : t('palette.labels.show'), () => labels.click(), searchWords('palette.words.labels', 'names numbers'));
        }
        const motion = document.getElementById('motion');
        if (motion) {
            for (const value of ['reduce', 'full', 'system']) {
                if (motion.value !== value) {
                    add('Settings', t(`palette.motion.${value}`), () => this.choose(motion, value), searchWords('palette.words.motion', 'animation accessibility'));
                }
            }
        }
        const theme = document.getElementById('theme');
        if (theme) {
            for (const value of ['dark', 'light', 'system']) {
                if (theme.value !== value) {
                    add('Settings', t(`palette.theme.${value}`), () => this.choose(theme, value), searchWords('palette.words.theme', 'colors appearance mode'));
                }
            }
        }
        if (app.language && typeof app.language.list === 'function') {
            const words = searchWords('palette.words.language', 'language translation locale');
            for (const choice of languageChoices(app.language.list(), language().code, storedLanguage())) {
                add('Settings', choice.code ? t('palette.language', { name: choice.name }) : t('palette.language.follow'),
                    () => app.language.choose(choice.code).catch(() => {}), `${words} ${choice.code || ''} ${choice.name || ''}`.trim());
            }
        }
        if (app.presets) {
            for (const [name, title] of app.presets.choices()) {
                add('Settings', t('palette.preset', { name: title }), () => app.presets.apply(name), searchWords('palette.words.preset', 'presentation replays celebrations show'));
            }
        }
        add('Settings', t('palette.settings'), () => app.menus && app.menus.settings && app.menus.settings.open(true), searchWords('palette.words.settings', 'preferences options'));
        for (const mode of this.cameraModes) {
            add('View', t('palette.camera', { camera: mode.label }), () => {
                watch();
                app.setCamera(mode.id);
            }, `${searchWords('palette.words.camera', 'camera view')} ${mode.id}`, '', CAMERA_KEYS[mode.id] || '');
        }
        const field = app.fieldPage;
        if (field) {
            const rerender = () => field.root && !field.root.hidden;
            for (const item of document.querySelectorAll('#view-environment [data-arena]')) {
                add('View', t('palette.arena', { arena: item.textContent.trim() }), () => field.change({ arena: item.dataset.arena }, rerender()), searchWords('palette.words.arena', 'stadium ground place'));
            }
            for (const [key, hour] of TIMES) {
                add('View', t('palette.time', { time: t(`palette.time.${key}`) }), () => field.change({ time: hour }, rerender()), searchWords('palette.words.time', 'hour sky light sun'));
            }
            for (const item of document.querySelectorAll('#view-environment [data-weather]')) {
                add('View', t('palette.weather', { weather: item.textContent.trim() }), () => field.change({ weather: item.dataset.weather }, rerender()), searchWords('palette.words.weather', 'rain snow sky'));
            }
        }
        if (app.photo) {
            add('View', t('palette.photo'), () => {
                watch();
                app.photo.open();
            }, searchWords('palette.words.photo', 'photo picture screenshot capture still image'), '', 'O');
        }
        add('View', document.fullscreenElement ? t('palette.fullscreen.leave') : t('palette.fullscreen'), () => app.toggleFullscreen(), searchWords('palette.words.fullscreen', 'screen'), '', 'F');
        for (const [id, title, keywords] of HELP_TOPICS) {
            add('Help', t('palette.help', { topic: title }), () => this.helpTopic(id), `${searchWords('palette.words.help', 'help guide')} ${keywords}`);
        }
        add('Help', t('palette.guide'), () => window.open('https://github.com/AndreKoraleski/cuju-render/blob/main/docs/rendering.md', '_blank', 'noopener'), searchWords('palette.words.guide', 'documentation docs manual'));
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

    // Shows the Challenges page, and with an identifier moves the focus to Play it yourself of
    // that challenge once the list has it, else to the heading of the page.
    async showChallenge(id) {
        this.app.showPage('challenges');
        return this.app.challengesPage ? this.app.challengesPage.focusCard(id) : false;
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
        h('span', { class: 'palette-group' }, action.hint ? t('palette.groupHint', { group: action.group, hint: action.hint }) : action.group),
        action.keys ? h('span', { class: 'palette-keys' }, chord(action.keys)) : null)));
        this.count.textContent = this.shown.length ? t('palette.count', { count: this.shown.length }) : t('palette.none');
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
            this.app.hud.toast(t('palette.failed', { error: err.message }), 'error');
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
