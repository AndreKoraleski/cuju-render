// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The Tournaments page. A list of tournaments sits beside the open one, which shows its stages as
// brackets, tables and fixtures with results, the matches of people ready to play, and the trophy
// ceremony at the end. New tournament opens a wizard of five steps, the format, the entrants, the
// settings, every setting of every stage in the advanced editor, and a review of the draw.

import { api } from '../core/api.js';
import { formatList, formatNumber, serverText, t, tn, tOr } from '../core/i18n.js';
import { kitShirt } from '../pages/matches.js';
import { el as h } from '../core/menu.js';
import { icon, stateBadge, symbolOnly } from '../core/icons.js';
import { listedScenarios, scenarioName, scenarioText } from '../core/scenarios.js';
import {
    DECIDED_NAMES, FORMAT_NAMES, NAME_LONGEST, SECTION_NAMES, SETTLE_NAMES, STATE_NAMES, TIEBREAK_NAMES,
    againStages, bracketLayout, entrantName, fixtureMatches, fixtureState, formatsText, freeName, isBracket, isFinal, jsonErrorPlace,
    madeNames, nameKey, presetDraft, progressShare, sections, sentence, setSetting, shownAbility, sideName, stageNameText, stageText,
    tableCaption, tiebreakText, upNext,
} from './tournament-layout.js';
import {
    autoplay, markWatched, noteRecordings, predict, prediction, predictionScore, setAutoplay, setSpoilerFree,
    spoilerFree, watchedKeys,
} from '../core/spoilers.js';

const FORMATS = Object.keys(FORMAT_NAMES);
const TIEBREAKERS = Object.keys(TIEBREAK_NAMES);
const SETTLEMENTS = Object.keys(SETTLE_NAMES);
const STEPS = [t('tournament.step.format'), t('tournament.step.entrants'), t('tournament.step.settings'), t('tournament.step.stages'), t('tournament.step.review')];
const STATE_LABELS = { running: t('tournament.state.running'), stopped: t('tournament.state.stopped'), done: t('tournament.state.done'), cancelled: t('tournament.state.cancelled') };
const KIND_NAMES = { team: t('tournament.kind.team'), builtin: t('tournament.kind.builtin'), person: t('tournament.kind.person') };
// The name of a preset of the user, as the server's rule of identifiers takes it.
const PRESET_NAME = /^[a-z0-9][a-z0-9_-]{0,63}$/;
// The words between the formats of the stages in a list.
const COMMA_THEN = t('tournament.formats.commaThen');

// The title and description of a preset, those of a shipped one in the language of the page.
function presetTitle(name, preset) {
    return preset.shipped ? tOr(`tournament.preset.${name}.title`, preset.title) : preset.title;
}

function presetDescription(name, preset) {
    return preset.shipped ? tOr(`tournament.preset.${name}.description`, preset.description) : preset.description;
}

// An ability in the numbers of the language, with two decimals.
function abilityText(value) {
    return formatNumber(Number(value), { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// The ability beside an entrant's name where it differs from the standard, or null, with the
// symbol of the built-in AI before it, since the ability steers the players the built-in AI controls.
function abilityBadge(entrant, standard) {
    const own = shownAbility(entrant, standard);
    if (own === null) {
        return null;
    }
    return h('span', { class: 'cup-ability small muted', title: t('tournament.entrant.shownAbility.title') },
        icon('robot', 'icon text-symbol'), t('tournament.entrant.shownAbility', { ability: abilityText(own) }));
}

// The words of an entrant's own ability for a label that a screen reader reads, or an empty text.
function abilityWords(entrant, standard) {
    const own = shownAbility(entrant, standard);
    return own === null ? '' : t('tournament.entrant.shownAbility', { ability: abilityText(own) });
}

// The standard ability of a tournament in words, its value or the scenario's own.
function standardText(standard) {
    return standard === null || standard === undefined ? t('tournament.view.ability.scenario') : t('tournament.view.ability', { ability: abilityText(standard) });
}

// The size of a team and the players it controls, such as 5v5, 2 controlled players.
function teamSize(team) {
    const players = (team && team.control && team.control.players) || 1;
    return t('tournament.team.size', { format: team.format, count: players });
}

// A team with its size, for a list or a select.
function teamOption(team) {
    return t('tournament.entrants.team.option', { name: team.name, size: teamSize(team) });
}

// A request to the server, which throws an error with the server's reason.
async function call(method, path, json) {
    let res;
    try {
        res = await fetch(path, {
            method,
            cache: 'no-store',
            headers: json === undefined ? {} : { 'Content-Type': 'application/json' },
            body: json === undefined ? undefined : JSON.stringify(json),
        });
    } catch {
        const error = new Error(t('api.unreachable', { origin: location.origin }));
        error.status = 0;
        throw error;
    }
    const text = await res.text();
    let body = null;
    try {
        body = text ? JSON.parse(text) : null;
    } catch {
        body = null;
    }
    if (!res.ok) {
        // A refusal of the server starts small, as it continues a sentence elsewhere, and the
        // page shows it as a sentence of its own.
        const error = new Error(sentence((body && body.error && serverText(body, 'error')) || t('tournament.api.status', { status: res.status })));
        error.status = res.status;
        // The message of a refusal and its values, so the page can lead to the setting it names.
        error.id = (body && body.error_id) || null;
        error.values = (body && body.error_values) || {};
        throw error;
    }
    return body;
}

export const tournamentsApi = {
    list: () => call('GET', '/api/tournaments'),
    get: (id) => call('GET', `/api/tournaments/${encodeURIComponent(id)}`),
    presets: () => call('GET', '/api/tournaments/presets'),
    ratings: () => call('GET', '/api/tournaments/ratings'),
    check: (config) => call('POST', '/api/tournaments/check', { config }),
    // A tournament as a person sees it who has watched only the matches of `watched`.
    spoilers: (id, watched) => call('POST', `/api/tournaments/${encodeURIComponent(id)}/spoilers`, { watched }),
    create: (config) => call('POST', '/api/tournaments', { config }),
    action: (id, action, body = {}) => call('POST', `/api/tournaments/${encodeURIComponent(id)}/${action}`, body),
    remove: (id) => call('DELETE', `/api/tournaments/${encodeURIComponent(id)}`),
    savePreset: (name, preset) => call('POST', `/api/tournaments/presets/${encodeURIComponent(name)}`, { preset }),
    removePreset: (name) => call('DELETE', `/api/tournaments/presets/${encodeURIComponent(name)}`),
};

function ratingKey(entry) {
    if (entry.kind === 'team') {
        return entry.team;
    }
    if (entry.kind === 'builtin') {
        return `builtin:${entry.ability == null ? 'scenario' : Number(entry.ability).toFixed(2)}`;
    }
    return `person:${entry.name || ''}`;
}

function clone(value) {
    return JSON.parse(JSON.stringify(value));
}

// A team in its away kit, its shirt and shorts colors swapped with its trim, as the right side of
// a match wears it against the same team, so two entrants of one team look apart in a fixture.
function awayTeam(team) {
    const kit = (team.style && team.style.kit) || {};
    const primary = kit.primary || team.color;
    const secondary = kit.secondary || team.secondary;
    if (!primary || !secondary) {
        return team;
    }
    const swapped = { ...kit, primary: secondary, secondary: primary, shorts: kit.socks || primary, socks: kit.shorts || secondary };
    return { ...team, color: secondary, secondary: primary, style: { ...(team.style || {}), kit: swapped } };
}

// Every setting of a stage that the advanced editor shows, with the formats it applies to.
const ALL = null;
const KNOCKOUTS = ['knockout', 'double_elimination', 'ladder', 'king_of_the_hill', 'gauntlet'];
const TABLES = ['league', 'groups', 'swiss'];
const OFF_SCENARIO = t('tournament.off.scenario');
const OFF_ENTRANTS = t('tournament.off.entrants');
const BY_ENTRANTS = t('tournament.scenario.byEntrants');
const RANDOM_SEEDING = t('tournament.seeding.random');
// The seeding of a later stage, whose default is the standing of the stage before it.
const LATER_SEEDING = [['standing', t('tournament.field.seeding.standing')], ['random', t('tournament.field.seeding.random')], ['rating', t('tournament.field.seeding.rating')]];
const STAGE_FIELDS = [
    { key: 'name', label: t('tournament.field.name'), type: 'text', formats: ALL },
    { key: 'format', label: t('tournament.field.format'), type: 'select', options: FORMATS.map((f) => [f, FORMAT_NAMES[f]]), formats: ALL },
    { key: 'scenario', label: t('tournament.field.scenario'), type: 'scenario', empty: BY_ENTRANTS, formats: ALL },
    { key: 'length', label: t('tournament.field.length'), type: 'optional', min: 50, max: 5000, step: 50, initial: 600, off: OFF_SCENARIO, formats: ALL },
    { key: 'ability', label: t('tournament.field.ability'), type: 'optional', min: 0, max: 1, step: 0.05, initial: 0.5, off: OFF_SCENARIO, formats: ALL, help: t('tournament.field.ability.help') },
    { key: 'legs', label: t('tournament.field.legs'), type: 'number', min: 1, max: 10, formats: ALL },
    { key: 'final_legs', label: t('tournament.field.final_legs'), type: 'optional', min: 1, max: 10, step: 1, initial: 1, off: t('tournament.off.otherTies'), formats: ['knockout', 'double_elimination'] },
    { key: 'settle', label: t('tournament.field.settle'), type: 'order', options: SETTLEMENTS, names: SETTLE_NAMES, formats: KNOCKOUTS },
    { key: 'replays', label: t('tournament.field.replays'), type: 'number', min: 1, max: 5, formats: KNOCKOUTS },
    { key: 'decider_scenario', label: t('tournament.field.decider_scenario'), type: 'scenario', formats: KNOCKOUTS, help: t('tournament.field.decider_scenario.help') },
    { key: 'decider_length', label: t('tournament.field.decider_length'), type: 'optional', min: 50, max: 5000, step: 50, initial: 400, off: OFF_SCENARIO, formats: KNOCKOUTS },
    { key: 'draws', label: t('tournament.field.draws'), type: 'select', options: [['holder', t('tournament.field.draws.holder')], ['settle', t('tournament.field.draws.settle')]], formats: ['ladder', 'king_of_the_hill', 'gauntlet'] },
    { key: 'points', label: t('tournament.field.points'), type: 'points', formats: [...TABLES, 'ladder', 'king_of_the_hill'] },
    { key: 'tiebreakers', label: t('tournament.field.tiebreakers'), type: 'order', options: TIEBREAKERS, names: TIEBREAK_NAMES, formats: TABLES },
    { key: 'bracket', label: t('tournament.field.bracket'), type: 'select', options: [['byes', t('tournament.field.bracket.byes')], ['play_in', t('tournament.field.bracket.play_in')]], formats: ['knockout'] },
    { key: 'bracket_size', label: t('tournament.field.bracket_size'), type: 'optional', min: 2, max: 512, step: 1, initial: 8, off: OFF_ENTRANTS, formats: ['knockout', 'double_elimination'] },
    { key: 'until', label: t('tournament.field.until'), type: 'number', min: 1, max: 256, formats: ['knockout'] },
    { key: 'third_place', label: t('tournament.field.third_place'), type: 'check', formats: ['knockout'] },
    { key: 'grand_final_reset', label: t('tournament.field.grand_final_reset'), type: 'check', formats: ['double_elimination'] },
    { key: 'cycles', label: t('tournament.field.cycles'), type: 'number', min: 1, max: 10, formats: ['league', 'groups'] },
    { key: 'groups', label: t('tournament.field.groups'), type: 'optional', min: 1, max: 128, step: 1, initial: 4, off: t('tournament.off.groupSize'), formats: ['groups'] },
    { key: 'group_size', label: t('tournament.field.group_size'), type: 'number', min: 2, max: 256, formats: ['groups'] },
    { key: 'group_sizes', label: t('tournament.field.group_sizes'), type: 'list', placeholder: t('tournament.field.group_sizes.placeholder'), formats: ['groups'] },
    { key: 'pots', label: t('tournament.field.pots'), type: 'optional', min: 1, max: 256, step: 1, initial: 4, off: t('tournament.off.pots'), formats: ['groups'] },
    { key: 'qualifiers', label: t('tournament.field.qualifiers'), type: 'list', placeholder: t('tournament.field.qualifiers.placeholder'), single: true, formats: ['groups'] },
    { key: 'best_position', label: t('tournament.field.best_position'), type: 'optional', min: 1, max: 64, step: 1, initial: 3, off: t('tournament.off.none'), formats: ['groups'] },
    { key: 'best_count', label: t('tournament.field.best_count'), type: 'fill', formats: ['groups'] },
    { key: 'rounds', label: t('tournament.field.rounds'), type: 'optional', min: 1, max: 1000, step: 1, initial: 5, off: OFF_ENTRANTS, formats: ['swiss', 'ladder'] },
    { key: 'bye_points', label: t('tournament.field.bye_points'), type: 'select', options: [['win', t('tournament.field.bye_points.win')], ['draw', t('tournament.field.bye_points.draw')], ['none', t('tournament.field.bye_points.none')]], formats: ['swiss'] },
    { key: 'laps', label: t('tournament.field.laps'), type: 'number', min: 1, max: 10, formats: ['king_of_the_hill'] },
    { key: 'seeding', label: t('tournament.field.seeding'), type: 'select', options: LATER_SEEDING, formats: ALL, later: true },
    { key: 'advance', label: t('tournament.field.advance'), type: 'optional', min: 1, max: 256, step: 1, initial: 4, off: t('tournament.off.format'), formats: ALL, notLast: true },
];
const STAGE_DEFAULTS = {
    format: 'knockout', name: '', scenario: null, length: null, ability: null, legs: 1, final_legs: null,
    settle: ['replay', 'lots'], replays: 1, decider_scenario: 'academy_run_to_score_with_keeper', decider_length: null,
    points: { win: 3, draw: 1, loss: 0 }, tiebreakers: ['goal_difference', 'goals_for', 'head_to_head', 'wins', 'fair_play', 'lots'],
    seeding: 'standing', bracket: 'byes', bracket_size: null, until: 1, third_place: false, grand_final_reset: true,
    cycles: 1, groups: null, group_size: 4, group_sizes: null, pots: null, qualifiers: 2, best_position: null, best_count: 0,
    rounds: null, laps: 1, bye_points: 'win', draws: null, advance: null,
};

function newDraft() {
    return {
        name: '', seed: '', seeding: 'random', concurrency: 1, forfeit_score: 3, ability: null, preset: null,
        defaults: {}, stages: [{ format: 'knockout', name: 'Cup' }], entrants: [],
        // The settings of OWN_SETTINGS that the person set by hand.
        own: new Set(),
    };
}

export class TournamentsPage {
    constructor(app) {
        this.app = app;
        this.root = document.getElementById('page-tournaments');
        this.list = [];
        this.teams = [];
        this.ratings = {};
        this.scenarios = [];
        this.presets = {};
        this.current = null;
        this.openId = null;
        this.mode = 'empty';
        this.draft = null;
        this.step = 0;
        this.stageTab = 0;
        this.error = null;
        this.built = false;
        this.token = 0;
        this.announced = new Set();
        // The award that waits for its confirmation, by where it shows, its match and its side.
        this.awarding = null;
        this.primed = false;
        // The match that plays on Watch for a tournament without spoilers, the matches watched
        // in this visit by tournament, the zoom of the Brackets view and the card between matches.
        this.watching = null;
        this.session = {};
        this.zoom = 1;
        this.intermission = null;
        this.revealing = false;
        document.addEventListener('cuju:recording-ended', (e) => this.recordingEnded(e.detail || {}));
        // A person who comes back to the page from another window may have registered a team
        // there, so the teams are read again.
        window.addEventListener('focus', () => {
            if (this.visible && this.built) {
                this.refreshTeams();
            }
        });
        setInterval(() => this.poll(), 1500);
    }

    // Says a change in the polite region of the page, which stays in place and empty between
    // messages, so a screen reader hears each one, the same text again too.
    announce(text) {
        if (!this.announcer) {
            return;
        }
        this.announcer.textContent = '';
        setTimeout(() => {
            this.announcer.textContent = text;
        }, 50);
    }

    // Reads the registry again, and redraws the part that shows teams when it changed, the
    // entrants step of the wizard or the open tournament.
    async refreshTeams() {
        const teams = await api.teams().catch(() => null);
        if (!teams || JSON.stringify(teams) === JSON.stringify(this.teams)) {
            return;
        }
        this.teams = teams;
        if (this.mode === 'wizard' && this.step === 1) {
            this.renderWizard();
        } else if ((this.mode === 'view' || this.mode === 'brackets') && this.current) {
            this.renderView();
        }
    }

    get visible() {
        return !!this.root && !this.root.hidden;
    }

    async refresh() {
        const token = ++this.token;
        try {
            const [list, teams, scenarios, presets] = await Promise.all([
                tournamentsApi.list(), api.teams().catch(() => []), api.scenarios().catch(() => []), tournamentsApi.presets().catch(() => ({})),
            ]);
            if (token !== this.token) {
                return;
            }
            this.list = list;
            this.teams = teams;
            this.scenarios = listedScenarios(scenarios);
            this.presets = presets;
            this.error = null;
        } catch (err) {
            if (token !== this.token) {
                return;
            }
            this.error = err;
        }
        this.render();
        if ((this.mode === 'view' || this.mode === 'brackets') && this.openId) {
            await this.load(this.openId);
        }
    }

    build() {
        this.built = true;
        this.listHost = h('ul', { class: 'cup-list', 'aria-label': t('tournament.list.label') });
        // The main part redraws as a tournament plays, so it stays silent, and the announcer
        // below says the changes worth hearing.
        this.mainHost = h('section', { class: 'cup-main', 'aria-busy': 'false' });
        const side = h('aside', { class: 'cup-side', 'aria-labelledby': 'cup-list-title' },
            h('header', { class: 'cup-side-head' },
                h('h1', { id: 'cup-list-title' }, t('tournament.list.title')),
                h('button', { type: 'button', class: 'btn primary', onclick: () => this.startWizard() }, icon('plus'), t('tournament.new'))),
            this.listHost);
        this.announcer = h('p', { class: 'sr-only', role: 'status', 'aria-live': 'polite' });
        this.root.replaceChildren(h('div', { class: 'cup-layout' }, side, this.mainHost), this.announcer);
    }

    render() {
        if (this.error) {
            this.built = false;
            this.root.replaceChildren(h('div', { class: 'page-pad' }, h('div', { class: 'notice error' },
                h('p', {}, this.error.message),
                h('p', { class: 'muted' }, tn('tournament.offline.hint')),
                h('button', { class: 'btn', type: 'button', ...symbolOnly(t('tournament.offline.retry')), onclick: () => this.refresh() }, icon('refresh')))));
            return;
        }
        if (!this.built) {
            this.build();
        }
        this.renderList();
        if (this.mode === 'empty') {
            this.renderEmpty();
        } else if (this.mode === 'wizard' && !this.mainHost.querySelector('.cup-wizard')) {
            this.renderWizard();
        }
    }

    renderList() {
        if (!this.list.length) {
            this.listHost.replaceChildren(h('li', { class: 'muted pad' }, t('tournament.list.empty')));
            return;
        }
        this.listHost.replaceChildren(...this.list.map((cup) => {
            const share = progressShare(cup);
            const shown = cup.id === this.openId && (this.mode === 'view' || this.mode === 'brackets');
            const button = h('button', {
                type: 'button', class: `cup-item${shown ? ' active' : ''}`,
                'aria-current': shown ? 'true' : 'false',
                onclick: () => this.open(cup.id),
            },
            h('span', { class: 'cup-item-name' }, serverText(cup, 'name')),
            h('span', { class: 'cup-item-meta' },
                stateBadge(cup.state, STATE_LABELS[cup.state] || cup.state, `state-pill ${cup.state === 'running' ? 'running' : cup.state === 'done' ? 'done' : 'failed'}`),
                t('tournament.list.meta', { count: cup.entrants, formats: formatsText(cup.stages) })),
            cup.champion && !spoilerFree(cup.id) ? h('span', { class: 'cup-item-champion' }, t('tournament.list.champion', { name: serverText(cup, 'champion') })) : null,
            spoilerFree(cup.id) ? h('span', { class: 'cup-item-spoilers small muted' }, icon('eye', 'icon text-symbol'), t('tournament.spoilers.listed')) : null,
            // People wait only for a tournament that runs or stopped, never one that ended.
            cup.people_waiting && ['running', 'stopped'].includes(cup.state) ? h('span', { class: 'cup-item-people' }, t('tournament.list.people', { count: cup.people_waiting })) : null,
            // A stopped tournament says why, the failed matches that wait for an award or Resume.
            cup.state === 'stopped' && cup.failed ? h('span', { class: 'cup-item-failed small' }, icon('warning', 'icon text-symbol'), t('tournament.list.failed', { count: cup.failed })) : null,
            cup.state === 'running' ? h('span', { class: 'progress', 'aria-hidden': 'true' }, h('span', { class: 'bar', style: `width:${Math.round(share * 100)}%` })) : null);
            return h('li', {}, button);
        }));
    }

    renderEmpty() {
        this.mainHost.replaceChildren(h('div', { class: 'empty-state' },
            h('p', { class: 'empty-title' }, t('tournament.empty.title')),
            h('p', { class: 'muted' }, tn('tournament.empty.text')),
            h('button', { type: 'button', class: 'btn primary', onclick: () => this.startWizard() }, icon('plus'), t('tournament.new'))));
    }

    // The wizard and the advanced editor.

    startWizard(config = null) {
        this.mode = 'wizard';
        this.root.querySelector('.cup-layout')?.classList.remove('brackets');
        this.openId = null;
        this.step = config ? 1 : 0;
        this.draft = config ? this.draftFrom(config) : newDraft();
        this.replaced = null;
        this.renderList();
        this.renderWizard();
        // The focus goes to the tab of the step that opens, so a keyboard starts in the wizard.
        document.getElementById(`cup-step-${this.step}`)?.focus();
        this.refreshEntrants();
    }

    // Reads the registry and the ratings again, and redraws the entrants step when they changed.
    async refreshEntrants() {
        const draft = this.draft;
        const [teams, ratings] = await Promise.all([
            api.teams().catch(() => null), tournamentsApi.ratings().catch(() => null),
        ]);
        if (this.mode !== 'wizard' || this.draft !== draft) {
            return;
        }
        const changed = (teams && JSON.stringify(teams) !== JSON.stringify(this.teams))
            || (ratings && JSON.stringify(ratings) !== JSON.stringify(this.ratings));
        this.teams = teams || this.teams;
        this.ratings = ratings || this.ratings;
        if (changed && this.step === 1) {
            this.renderWizard();
        }
    }

    draftFrom(config) {
        const draft = newDraft();
        for (const key of ['name', 'seeding', 'concurrency', 'forfeit_score', 'ability', 'preset']) {
            if (config[key] !== undefined) {
                draft[key] = config[key];
            }
        }
        // A name that the server made, such as Tournament, stays the server's, so the new
        // tournament takes it in any language, while a name a person gave carries over.
        if (config.name_id) {
            draft.name = '';
        }
        draft.stages = againStages(config, Object.keys(STAGE_DEFAULTS), draft.stages);
        draft.defaults = clone((config.given && config.given.defaults) || {});
        draft.entrants = (config.entrants || []).map((e) => {
            const entry = { kind: e.kind, name: e.name_id ? undefined : e.name, ability: e.ability ?? null };
            if (e.kind === 'team') {
                entry.team = e.team;
                // A team that entered under its own name enters again under it, as a team just
                // added does, so its row shows the name as the one it takes, not as one typed.
                const team = this.teams.find((x) => x.id === e.team);
                if (team && e.name === team.name) {
                    entry.name = undefined;
                }
            } else if (e.kind === 'person') {
                entry.teammates = e.team || 'builtin';
            }
            if (e.rated) {
                entry.rating = e.rating;
            }
            return entry;
        });
        return draft;
    }

    renderWizard() {
        const tabs = h('div', { class: 'cup-steps', role: 'tablist', 'aria-label': t('tournament.wizard.steps') },
            STEPS.map((name, index) => h('button', {
                type: 'button', role: 'tab', id: `cup-step-${index}`, class: `cup-step${index === this.step ? ' active' : ''}`,
                'aria-selected': index === this.step ? 'true' : 'false', tabindex: index === this.step ? '0' : '-1',
                'aria-controls': 'cup-step-panel',
                onclick: () => this.goStep(index),
                onkeydown: (e) => this.stepKeys(e, index),
            }, h('span', { class: 'cup-step-number' }, String(index + 1)), name)));
        const panel = h('div', { class: 'cup-step-panel', id: 'cup-step-panel', role: 'tabpanel', 'aria-labelledby': `cup-step-${this.step}` });
        const body = [this.formatStep, this.entrantsStep, this.settingsStep, this.stagesStep, this.reviewStep][this.step].call(this);
        panel.append(...[body].flat().filter(Boolean));
        const nav = h('div', { class: 'cup-nav' },
            h('button', { type: 'button', class: 'btn ghost', ...symbolOnly(t('tournament.wizard.cancel')), onclick: () => this.cancelWizard() }, icon('close')),
            h('span', { class: 'cup-nav-gap' }),
            this.step > 0 ? h('button', { type: 'button', class: 'btn', ...symbolOnly(t('tournament.wizard.back')), onclick: () => this.goStep(this.step - 1, true) }, icon('back')) : null,
            this.step < STEPS.length - 1
                ? h('button', { type: 'button', class: 'btn primary', ...symbolOnly(t('tournament.wizard.next')), onclick: () => this.goStep(this.step + 1, true) }, icon('next'))
                : h('button', { type: 'button', class: 'btn primary cup-start', onclick: (e) => this.create(e.currentTarget) }, icon('play'), t('tournament.wizard.start')));
        const memo = this.focusMemo();
        this.mainHost.replaceChildren(h('div', { class: 'cup-wizard' },
            h('header', { class: 'cup-head' }, h('h2', {}, t('tournament.new')),
                h('p', { class: 'muted' }, tn('tournament.wizard.text'))),
            tabs, panel, nav));
        this.restoreFocus(memo);
    }

    // What the focused control of the main part is, by its id, its focus key or its accessible
    // name, so the same control takes the focus again once the part is drawn anew.
    focusMemo() {
        const node = document.activeElement;
        if (!node || node === this.mainHost || !this.mainHost.contains(node)) {
            return null;
        }
        return { id: node.id || null, focus: node.dataset.focus || null, label: node.getAttribute('aria-label') };
    }

    // Focuses the control that `memo` names, or the tab of the current step when it is gone or
    // can no longer be used, so the focus never falls back to the start of the page.
    restoreFocus(memo) {
        if (!memo) {
            return;
        }
        const usable = (node) => node && !node.disabled && node.isConnected;
        const all = [...this.mainHost.querySelectorAll('button, input, select, textarea, [tabindex]')];
        const found = (memo.id && document.getElementById(memo.id))
            || (memo.focus && all.find((node) => node.dataset.focus === memo.focus))
            || (memo.label && all.find((node) => node.getAttribute('aria-label') === memo.label));
        const target = usable(found) ? found : document.getElementById(`cup-step-${this.step}`);
        target?.focus();
    }

    stepKeys(e, index) {
        const moves = { ArrowRight: 1, ArrowLeft: -1, Home: -index, End: STEPS.length - 1 - index };
        if (e.key in moves) {
            e.preventDefault();
            const next = Math.max(0, Math.min(STEPS.length - 1, index + moves[e.key]));
            this.goStep(next);
            document.getElementById(`cup-step-${next}`)?.focus();
        }
    }

    // Opens the Stages step at the scenario of a stage, for a person to choose another.
    focusStageScenario(index, decider = false) {
        this.goStep(3);
        const field = t(decider ? 'tournament.field.decider_scenario' : 'tournament.field.scenario');
        const label = t('tournament.stage.fieldLabel', { label: field, number: index + 1 });
        const stage = this.mainHost.querySelectorAll('.cup-stage')[index];
        const control = stage && [...stage.querySelectorAll('select, button, input')]
            .find((node) => (node.getAttribute('aria-label') || '').startsWith(label));
        stage?.scrollIntoView({ block: 'center' });
        control?.focus();
    }

    // Opens a step, and with `focusTab` or from a tab focuses the tab of the step, as Next and Back
    // do, so a screen reader names the step that opened.
    goStep(index, focusTab = false) {
        this.step = index;
        const fromTab = document.activeElement && document.activeElement.classList.contains('cup-step');
        this.renderWizard();
        if (focusTab || fromTab) {
            document.getElementById(`cup-step-${index}`)?.focus();
        }
    }

    cancelWizard() {
        this.mode = this.openId ? 'view' : 'empty';
        this.draft = null;
        this.render();
        if (this.mode === 'view') {
            this.renderView();
        }
    }

    formatStep() {
        const entries = Object.entries(this.presets);
        // A preset gives its format and stages, and the settings that the person set by hand stay
        // where it leaves them free. Where it sets its own, a notice names them and offers the
        // person's back.
        const choose = (name) => {
            const preset = this.presets[name];
            const draft = this.draft;
            const { values, replaced } = presetDraft(draft, preset, draft.own);
            Object.assign(draft, values);
            draft.preset = name;
            this.replaced = replaced.length ? { name, items: replaced } : null;
            if (!draft.name || Object.entries(this.presets).some(([key, p]) => presetTitle(key, p) === draft.name)) {
                draft.name = presetTitle(name, preset);
            }
            this.renderWizard();
            this.mainHost.querySelector(`[data-preset="${name}"]`)?.focus();
        };
        // The presets are a group of radio buttons with one stop of the Tab key, the chosen one or
        // else the first, and the arrow keys choose the next or the previous, Home and End the ends.
        const names = entries.map(([name]) => name);
        const stop = names.includes(this.draft.preset) ? this.draft.preset : names[0];
        const keys = (e, index) => {
            const moves = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1, Home: -index, End: names.length - 1 - index };
            if (e.key in moves && !e.altKey && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                const next = e.key === 'Home' || e.key === 'End' ? index + moves[e.key] : (index + moves[e.key] + names.length) % names.length;
                choose(names[next]);
            }
        };
        const cards = entries.map(([name, preset], index) => {
            const on = this.draft.preset === name;
            return h('div', { class: `cup-preset${on ? ' active' : ''}` },
                h('button', {
                    type: 'button', class: 'cup-preset-pick', role: 'radio', 'aria-checked': on ? 'true' : 'false', 'data-preset': name,
                    tabindex: name === stop ? '0' : '-1',
                    onclick: () => choose(name),
                    onkeydown: (e) => keys(e, index),
                },
                h('span', { class: 'cup-preset-title' }, presetTitle(name, preset)),
                h('span', { class: 'cup-preset-text muted small' }, presetDescription(name, preset) || preset.stages.map(stageText).join(COMMA_THEN)),
                h('span', { class: 'cup-preset-stages small' }, formatsText(preset.stages))),
                preset.shipped ? null : this.deletePresetButton(name, preset));
        });
        return [
            h('p', { class: 'muted' }, tn('tournament.formatStep.intro')),
            this.draft.own.size ? h('p', { class: 'muted small' }, t('tournament.formatStep.kept.note')) : null,
            this.replacedNotice(),
            h('div', { class: 'cup-presets', role: 'radiogroup', 'aria-label': t('tournament.formatStep.label') }, cards),
        ];
    }

    // The notice of the settings of the person that the chosen preset set in their place, with
    // Keep mine, which gives them back, and the preset's own, which closes the notice.
    replacedNotice() {
        const replaced = this.replaced;
        if (!replaced || replaced.name !== this.draft.preset || !this.presets[replaced.name]) {
            return null;
        }
        const title = presetTitle(replaced.name, this.presets[replaced.name]);
        const settings = formatList(replaced.items.map((item) => t(`tournament.setting.${item.key}`)));
        const pick = () => this.mainHost.querySelector('.cup-preset-pick[tabindex="0"]')?.focus();
        return h('div', { class: 'notice cup-replaced', role: 'status' },
            h('p', {}, icon('info', 'icon text-symbol'), t('tournament.formatStep.replaced', { title, settings })),
            h('div', { class: 'row' },
                h('button', { type: 'button', class: 'btn small primary', 'data-focus': 'keep-mine', onclick: () => {
                    for (const item of replaced.items) {
                        setSetting(this.draft, item.key, item.mine);
                    }
                    this.replaced = null;
                    this.renderWizard();
                    pick();
                    this.announce(t('tournament.formatStep.kept'));
                } }, icon('undo'), t('tournament.formatStep.keep')),
                h('button', { type: 'button', class: 'btn small ghost', 'data-focus': 'use-preset', onclick: () => {
                    this.replaced = null;
                    this.renderWizard();
                    pick();
                } }, icon('check'), t('tournament.formatStep.usePreset'))));
    }

    // The button that deletes a preset of the person, which asks first in place of the button, as
    // Award and Delete of a tournament do. Escape or Keep it leaves the preset, and the focus
    // returns to the button.
    deletePresetButton(name, preset) {
        const title = preset.title;
        const button = h('button', {
            type: 'button', class: 'btn small ghost danger', 'data-focus': `delete-preset-${name}`,
            'aria-label': t('tournament.formatStep.delete.label', { title }),
        }, icon('trash'), t('tournament.formatStep.delete'));
        button.addEventListener('click', () => {
            const back = () => {
                ask.replaceWith(button);
                button.focus();
            };
            const ask = this.confirmGroup(t('tournament.formatStep.delete.confirm', { title }),
                [icon('trash'), t('tournament.formatStep.delete')], t('tournament.formatStep.delete.no'), async () => {
                    try {
                        await tournamentsApi.removePreset(name);
                        delete this.presets[name];
                        // A draft made from the deleted preset no longer names it.
                        if (this.draft.preset === name) {
                            this.draft.preset = null;
                        }
                        this.renderWizard();
                        this.mainHost.querySelector('.cup-preset-pick[tabindex="0"]')?.focus();
                        this.announce(t('tournament.formatStep.deleted', { title }));
                    } catch (err) {
                        back();
                        this.app.hud.toast(err.message, 'error');
                    }
                }, back, true);
            button.replaceWith(ask);
            ask.querySelector('[data-answer="no"]').focus();
        });
        return button;
    }

    // A question in place of a button, with its yes and no, as the questions of a tournament
    // show it. Escape answers no.
    confirmGroup(question, yes, no, onYes, onNo, danger = false) {
        return h('span', {
            class: 'cup-confirm', role: 'group', 'aria-label': question,
            onkeydown: (e) => {
                if (e.key === 'Escape') {
                    e.preventDefault();
                    e.stopPropagation();
                    onNo();
                }
            },
        },
        h('span', { class: 'small' }, question),
        h('button', { type: 'button', class: `btn small primary${danger ? ' danger' : ''}`, 'data-answer': 'yes', onclick: (e) => {
            e.currentTarget.disabled = true;
            onYes();
        } }, ...[yes].flat()),
        h('button', { type: 'button', class: 'btn small ghost', 'data-answer': 'no', onclick: onNo }, icon('close'), no));
    }

    entrantsStep() {
        const d = this.draft;
        const teams = this.teams.filter((x) => x.kind !== 'builtin');
        const teamSelect = h('select', { 'aria-label': t('tournament.entrants.team.label') },
            teams.length ? teams.map((x) => h('option', { value: x.id }, teamOption(x))) : h('option', { value: '' }, t('tournament.entrants.team.none')));
        // A team registered elsewhere since the step opened joins the list once the person comes
        // to choose a team.
        teamSelect.addEventListener('focus', () => this.refreshEntrants());
        const ability = h('input', { type: 'number', min: '0', max: '1', step: '0.05', value: '0.5', 'aria-label': t('tournament.entrants.builtin.label') });
        const person = h('input', { type: 'text', maxlength: '40', placeholder: t('tournament.entrants.name'), 'aria-label': t('tournament.entrants.person.label') });
        const add = (entry) => {
            if (d.entrants.length >= 256) {
                this.app.hud.toast(t('tournament.entrants.full'), 'error');
                return false;
            }
            d.entrants.push(entry);
            this.renderWizard();
            return true;
        };
        // A team whose name an entrant already shows, as when it enters again, enters under the
        // first free name, such as Rex 2, which its row then lets a person change.
        // The select keeps the team added last, so the next one is a step away.
        if (teams.some((x) => x.id === this.lastTeam)) {
            teamSelect.value = this.lastTeam;
        }
        teamSelect.addEventListener('change', () => {
            this.lastTeam = teamSelect.value;
        });
        const addTeam = (id) => {
            this.lastTeam = id;
            const team = teams.find((x) => x.id === id);
            const entry = { kind: 'team', team: id };
            const taken = this.takenNames();
            if (team && taken.has(nameKey(team.name))) {
                entry.name = freeName(team.name, taken);
            }
            if (add(entry) && entry.name) {
                this.app.hud.toast(t('tournament.entrants.renamed', { team: team.name, name: entry.name }), 'info', 6000, 'edit');
                this.mainHost.querySelector('.cup-entrants > li:last-child .cup-entrant-name input')?.focus();
            }
        };
        const adders = h('div', { class: 'cup-adders' },
            h('div', { class: 'cup-adder' }, h('label', { class: 'field' }, t('tournament.entrants.team'), teamSelect),
                h('button', { type: 'button', class: 'btn', disabled: !teams.length, ...symbolOnly(t('tournament.entrants.team.add')), onclick: () => addTeam(teamSelect.value) }, icon('plus')),
                h('button', { type: 'button', class: 'btn ghost', 'data-focus': 'add-all', disabled: !teams.length, onclick: () => {
                    const have = new Set(d.entrants.filter((e) => e.kind === 'team').map((e) => e.team));
                    const missing = teams.filter((team) => !have.has(team.id));
                    if (!missing.length) {
                        this.app.hud.toast(t('tournament.entrants.team.allIn'), 'info');
                        return;
                    }
                    // The list stops at the most entrants a tournament takes, and says so.
                    const room = 256 - d.entrants.length;
                    for (const x of missing.slice(0, Math.max(0, room))) {
                        const taken = this.takenNames();
                        d.entrants.push(taken.has(nameKey(x.name)) ? { kind: 'team', team: x.id, name: freeName(x.name, taken) } : { kind: 'team', team: x.id });
                    }
                    if (missing.length > room) {
                        this.app.hud.toast(t('tournament.entrants.full'), 'error');
                    }
                    this.renderWizard();
                } }, icon('plus'), t('tournament.entrants.team.addAll'))),
            h('div', { class: 'cup-adder' }, h('label', { class: 'field' }, t('tournament.entrants.builtin'), ability),
                h('button', { type: 'button', class: 'btn', ...symbolOnly(t('tournament.entrants.builtin.add')), onclick: () => {
                    // An empty box reads as no ability at all, never as 0.
                    const value = ability.value.trim() === '' ? NaN : Number(ability.value);
                    if (!(value >= 0 && value <= 1)) {
                        this.app.hud.toast(t('tournament.entrants.builtin.range'), 'error');
                        ability.focus();
                        return;
                    }
                    const entry = { kind: 'builtin', ability: Math.round(value * 10000) / 10000 };
                    const base = this.shownName(entry);
                    if (add(entry)) {
                        // The built-in AI at an ability that an entrant already shows enters under
                        // the next number, which the server gives it, as a team entered again does.
                        const made = this.madeNames().at(-1);
                        if (made !== base) {
                            this.app.hud.toast(t('tournament.entrants.renamed', { team: base, name: made }), 'info', 6000, 'edit');
                            this.mainHost.querySelector('.cup-entrants > li:last-child .cup-entrant-name input')?.focus();
                        }
                    }
                } }, icon('plus'))),
            h('div', { class: 'cup-adder' }, h('label', { class: 'field' }, t('tournament.entrants.person'), person),
                h('button', { type: 'button', class: 'btn cup-add-person', ...symbolOnly(t('tournament.entrants.person.add')), onclick: () => {
                    const name = person.value.trim();
                    if (!name) {
                        this.app.hud.toast(t('tournament.entrants.person.noName'), 'error');
                        person.focus();
                        return;
                    }
                    if (this.takenNames().has(nameKey(name))) {
                        this.app.hud.toast(t('tournament.entrants.person.taken', { name }), 'error', 6000, 'warning');
                        person.focus();
                        return;
                    }
                    add({ kind: 'person', name, teammates: 'builtin' });
                } }, icon('plus'))));
        // Enter in the name of a person adds the person, as the button beside it does.
        person.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.isComposing) {
                e.preventDefault();
                adders.querySelector('.cup-add-person')?.click();
            }
        });
        const rows = d.entrants.map((entry, index) => this.entrantRow(entry, index));
        queueMicrotask(() => this.markNames());
        // The draw is random from the tournament seed, unless the person sets the bracket by hand,
        // which seeds the entrants in the order of this list, the first as seed 1.
        const manual = h('input', { type: 'checkbox', class: 'cup-manual', checked: d.seeding === 'manual' });
        const drawNote = h('span', { class: 'muted small cup-draw-note', id: 'cup-draw-note' });
        const showDraw = () => {
            drawNote.textContent = t(d.seeding === 'manual' ? 'tournament.entrants.draw.manual' : d.seeding === 'rating' ? 'tournament.entrants.draw.rating' : 'tournament.entrants.draw.random');
        };
        manual.setAttribute('aria-describedby', 'cup-draw-note');
        manual.addEventListener('change', () => {
            d.seeding = manual.checked ? 'manual' : 'random';
            d.own.add('seeding');
            showDraw();
        });
        showDraw();
        return [
            h('p', { class: 'muted' }, tn('tournament.entrants.intro', { count: d.entrants.length })),
            h('div', { class: 'cup-draw' }, h('label', { class: 'check' }, manual, t('tournament.entrants.draw.byHand')), drawNote),
            adders,
            d.entrants.length ? h('ol', { class: 'cup-entrants' }, rows) : h('p', { class: 'muted pad' }, t('tournament.entrants.empty')),
        ];
    }

    entrantRow(entry, index) {
        const d = this.draft;
        const team = entry.kind === 'team' ? this.teams.find((x) => x.id === entry.team) : null;
        const fallback = entry.kind === 'team' ? (team ? team.name : entry.team)
            : entry.kind === 'builtin' ? (entry.ability == null ? t('tournament.entrant.builtin') : t('tournament.entrant.builtinAt', { ability: abilityText(entry.ability) })) : '';
        const number = index + 1;
        const noteId = `cup-name-note-${index}`;
        const name = h('input', { type: 'text', maxlength: String(NAME_LONGEST), value: entry.name || '', placeholder: fallback || t('tournament.entrants.name'), 'aria-label': t('tournament.entrant.name.label', { number }), 'aria-describedby': noteId });
        name.addEventListener('input', () => {
            entry.name = name.value.trim() || undefined;
            this.markNames();
        });
        const note = h('span', { class: 'cup-name-note small', id: noteId, role: 'status' });
        const held = this.ratings[ratingKey(entry)];
        const rating = h('input', {
            type: 'number', min: '0', max: '10000', step: '1', value: entry.rating ?? '', placeholder: String(Math.round(held ? held.rating : 1500)),
            title: t('tournament.entrant.rating.title'), 'aria-label': t('tournament.entrant.rating.label', { number }),
        });
        rating.addEventListener('input', () => {
            entry.rating = rating.value === '' ? undefined : Number(rating.value);
        });
        const extra = [];
        // Every entrant may carry an ability, which the built-in AI players of its side play with.
        // Left empty, it follows the stage's or the standard, which the placeholder names.
        const followed = d.ability === null || d.ability === undefined ? t('tournament.entrant.ability.placeholder')
            : t('tournament.entrant.ability.standard', { ability: abilityText(d.ability) });
        const ability = h('input', {
            type: 'number', class: 'cup-entrant-ability', min: '0', max: '1', step: '0.05', value: entry.ability ?? '', placeholder: followed,
            title: t('tournament.entrant.ability.title'), 'aria-label': t('tournament.entrant.ability.label', { number }),
        });
        ability.addEventListener('input', () => {
            entry.ability = ability.value === '' ? null : Number(ability.value);
            // The made name of the built-in AI holds its ability, so the names follow it.
            if (entry.kind === 'builtin') {
                this.markNames();
            }
        });
        const abilityField = h('label', { class: 'field small-field' }, t('tournament.entrant.ability'), ability);
        if (entry.kind === 'person') {
            const dynamic = this.teams.filter((x) => x.kind !== 'builtin' && x.control && x.control.assignment === 'dynamic');
            const mates = h('select', { 'aria-label': t('tournament.entrant.teammates.label', { number }) },
                h('option', { value: 'builtin' }, t('tournament.entrant.builtin')), dynamic.map((x) => h('option', { value: x.id }, teamOption(x))));
            mates.value = entry.teammates || 'builtin';
            mates.addEventListener('change', () => {
                entry.teammates = mates.value;
            });
            extra.push(h('label', { class: 'field small-field' }, t('tournament.entrant.teammates'), mates));
        } else {
            extra.push(h('span', { class: 'cup-entrant-extra', 'aria-hidden': 'true' }));
        }
        extra.push(abilityField);
        const move = (by) => {
            const to = index + by;
            if (to < 0 || to >= d.entrants.length) {
                return;
            }
            [d.entrants[index], d.entrants[to]] = [d.entrants[to], d.entrants[index]];
            this.renderWizard();
            // The moved entrant keeps the focus on the button that moved it, or on the other one
            // once it reaches either end of the list, and its new place is said.
            const row = this.mainHost.querySelectorAll('.cup-entrants > li')[to];
            const buttons = row ? [row.querySelector(by < 0 ? '.cup-up' : '.cup-down'), row.querySelector(by < 0 ? '.cup-down' : '.cup-up')] : [];
            buttons.find((button) => button && !button.disabled)?.focus();
            this.announce(t('tournament.moved', { name: this.madeNames()[to] || '', place: to + 1, total: d.entrants.length }));
        };
        return h('li', { class: 'cup-entrant' },
            team ? kitShirt(team, 0) : h('span', { class: `cup-kind ${entry.kind}`, 'aria-hidden': 'true' }, entry.kind === 'person' ? t('tournament.entrant.glyph.person') : t('tournament.entrant.glyph.builtin')),
            // The shirt marks a team, so its row names the team, with its kind for a screen
            // reader alone, and its size under the name.
            h('span', { class: 'cup-entrant-kind small muted' }, team ? [h('span', { class: 'sr-only' }, `${KIND_NAMES.team}, `), team.name] : KIND_NAMES[entry.kind],
                team ? h('span', { class: 'cup-entrant-size' }, teamSize(team)) : null),
            h('span', { class: 'cup-entrant-name' }, h('label', { class: 'field' }, h('span', {}, icon('edit', 'icon text-symbol'), t('tournament.entrants.name')), name), note), ...extra,
            h('label', { class: 'field small-field' }, t('tournament.entrant.rating'), rating),
            h('span', { class: 'cup-entrant-actions' },
                h('button', { type: 'button', class: 'btn small ghost cup-up', ...symbolOnly(t('tournament.entrant.up.label', { number })), disabled: index === 0, onclick: () => move(-1) }, icon('up')),
                h('button', { type: 'button', class: 'btn small ghost cup-down', ...symbolOnly(t('tournament.entrant.down.label', { number })), disabled: index === d.entrants.length - 1, onclick: () => move(1) }, icon('down')),
                h('button', { type: 'button', class: 'btn small ghost danger cup-remove', ...symbolOnly(t('tournament.entrant.remove.label', { number })), onclick: () => {
                    d.entrants.splice(index, 1);
                    this.renderWizard();
                    // The focus moves to the entrant that takes the place, else the one before it,
                    // else to the first way to add an entrant.
                    const rows = this.mainHost.querySelectorAll('.cup-entrants > li');
                    const row = rows[Math.min(index, rows.length - 1)];
                    (row ? row.querySelector('.cup-remove') : this.mainHost.querySelector('.cup-adder select, .cup-adder input'))?.focus();
                } }, icon('close'))));
    }

    // The name that an entrant of the draft shows, the one a person gave, else its team's or
    // its kind's.
    shownName(entry) {
        if (entry.name) {
            return entry.name;
        }
        if (entry.kind === 'team') {
            const team = this.teams.find((x) => x.id === entry.team);
            return team ? team.name : entry.team;
        }
        if (entry.kind === 'builtin') {
            return entry.ability == null ? t('tournament.entrant.builtin') : t('tournament.entrant.builtinAt', { ability: abilityText(entry.ability) });
        }
        return '';
    }

    // The name that each entrant of the draft takes, the one a person gave, else the one the
    // server makes from its team or kind, numbered from 2 when an entrant already holds it.
    madeNames() {
        return madeNames(this.draft.entrants.map((e) => ({ name: this.shownName(e), own: !!e.name })));
    }

    // The keys of the names that the entrants of the draft show.
    takenNames() {
        return new Set(this.draft.entrants.map((e) => nameKey(this.shownName(e))).filter(Boolean));
    }

    // The entrant whose name the given name of entrant `index` repeats, or -1. A given name
    // repeats no other given name, which the server refuses, nor the name an earlier entrant takes
    // from its team or kind, which the server would number in its place.
    nameClash(index) {
        const entries = this.draft.entrants;
        const own = entries[index];
        if (!own || !own.name) {
            return -1;
        }
        const key = nameKey(own.name);
        return entries.findIndex((e, j) => j !== index && (e.name || j < index) && nameKey(this.shownName(e)) === key);
    }

    // Each entrant whose given name repeats another, with the entrant it repeats.
    nameClashes() {
        return this.draft.entrants.map((entry, index) => ({ index, other: this.nameClash(index), name: entry.name }))
            .filter((clash) => clash.other >= 0);
    }

    // Marks each name of the entrants step that repeats another, with the reason beside it.
    markNames() {
        if (!this.draft || this.mode !== 'wizard') {
            return;
        }
        const made = this.madeNames();
        this.mainHost.querySelectorAll('.cup-entrants > li').forEach((row, index) => {
            const input = row.querySelector('.cup-entrant-name input');
            const note = row.querySelector('.cup-name-note');
            if (!input || !note) {
                return;
            }
            // A field left empty shows the name that the entrant takes, as the server makes it.
            if (made[index] && input.placeholder !== made[index]) {
                input.placeholder = made[index];
            }
            const other = this.nameClash(index);
            const text = other >= 0 ? t('tournament.entrant.name.taken', { name: this.draft.entrants[index].name, other: other + 1 }) : '';
            if (other >= 0) {
                input.setAttribute('aria-invalid', 'true');
            } else {
                input.removeAttribute('aria-invalid');
            }
            // A name that repeats another shows the symbol of a warning before its reason.
            if (note.textContent !== text) {
                note.replaceChildren(...(text ? [icon('warning', 'icon text-symbol'), text] : []));
            }
        });
    }

    settingsStep() {
        const d = this.draft;
        const name = h('input', { type: 'text', maxlength: '80', value: d.name, placeholder: t('server.tournament.label.tournament'), 'aria-label': t('tournament.settings.name.label') });
        name.addEventListener('input', () => {
            d.name = name.value;
        });
        const seed = h('input', { type: 'text', inputmode: 'numeric', value: d.seed, placeholder: t('tournament.settings.seed.placeholder'), 'aria-label': t('tournament.settings.seed.label') });
        seed.addEventListener('input', () => {
            d.seed = seed.value.trim();
        });
        // Each setting that the person sets here is theirs, which a preset chosen afterwards
        // keeps where it leaves the setting free.
        const seeding = this.select([['random', RANDOM_SEEDING], ['manual', t('tournament.seeding.manual')], ['rating', t('tournament.seeding.rating')]], d.seeding, t('tournament.settings.seeding'), (v) => {
            d.seeding = v;
            d.own.add('seeding');
        });
        const concurrency = h('input', { type: 'number', min: '1', max: '8', step: '1', value: String(d.concurrency), 'aria-label': t('tournament.settings.concurrency.label') });
        concurrency.addEventListener('input', () => {
            d.concurrency = Number(concurrency.value);
            d.own.add('concurrency');
        });
        const forfeit = h('input', { type: 'number', min: '1', max: '10', step: '1', value: String(d.forfeit_score), 'aria-label': t('tournament.settings.forfeit.label') });
        forfeit.addEventListener('input', () => {
            d.forfeit_score = Number(forfeit.value);
            d.own.add('forfeit_score');
        });
        const scenario = this.scenarioSelect(d.defaults.scenario ?? null, t('tournament.settings.scenario'), BY_ENTRANTS, (v) => {
            setSetting(d, 'defaults.scenario', v);
            d.own.add('defaults.scenario');
        });
        const length = this.optionalNumber({ key: 'length', min: 50, max: 5000, step: 50, initial: 600, off: OFF_SCENARIO, label: t('tournament.field.length') }, d.defaults.length ?? null, (v) => {
            setSetting(d, 'defaults.length', v);
            d.own.add('defaults.length');
        });
        const defaults = d.defaults;
        return h('div', { class: 'cup-form' },
            h('label', { class: 'field' }, t('tournament.settings.name'), name),
            h('label', { class: 'field' }, t('tournament.settings.seed'),
                h('span', { class: 'row' }, seed, h('button', { type: 'button', class: 'btn ghost', ...symbolOnly(t('tournament.settings.seed.draw')), onclick: () => {
                    seed.value = String(crypto.getRandomValues(new Uint32Array(1))[0]);
                    d.seed = seed.value;
                } }, icon('dice')))),
            h('p', { class: 'muted small' }, tn('tournament.settings.seed.note')),
            h('label', { class: 'field' }, t('tournament.settings.seeding'), seeding),
            h('div', { class: 'field' }, h('span', {}, t('tournament.settings.scenario')), scenario, h('span', { class: 'muted small' }, scenarioText(defaults.scenario || ''))),
            h('div', { class: 'field' }, h('span', {}, t('tournament.settings.length')), length),
            this.standardControl(),
            h('label', { class: 'field' }, t('tournament.settings.concurrency'), concurrency),
            h('label', { class: 'field' }, t('tournament.settings.forfeit'), forfeit),
            h('p', { class: 'muted small' }, tn('tournament.settings.note')));
    }

    select(options, value, label, onChange) {
        const select = h('select', { 'aria-label': label }, options.map(([v, text]) => h('option', { value: v }, text)));
        select.value = value;
        select.addEventListener('change', () => onChange(select.value));
        return select;
    }

    scenarioSelect(value, label, empty, onChange) {
        const options = [...(empty ? [['', empty]] : []), ...this.scenarios.map((s) => [s, scenarioName(s)])];
        if (value && !this.scenarios.includes(value)) {
            options.push([value, scenarioName(value)]);
        }
        const select = this.select(options, value ?? '', label, (v) => onChange(v === '' ? null : v));
        return select;
    }

    // The standard ability of the tournament, which every entrant and stage that sets none plays
    // with, a slider with its value beside it and a box that sets it. Left clear, the scenario's
    // own ability plays, as the value beside the slider says.
    standardControl() {
        const d = this.draft;
        const label = t('tournament.settings.ability');
        const on = d.ability !== null && d.ability !== undefined;
        const box = h('input', { type: 'checkbox', class: 'cup-standard-set', checked: on, 'aria-label': t('tournament.optional.set.label', { label }) });
        const range = h('input', { type: 'range', class: 'cup-standard-range', min: '0', max: '1', step: '0.05', value: String(on ? d.ability : 0.5), disabled: !on, 'aria-label': label });
        const shown = h('output', { class: 'ability-value' });
        const show = () => {
            shown.textContent = box.checked ? abilityText(d.ability) : OFF_SCENARIO;
            range.setAttribute('aria-valuetext', shown.textContent);
        };
        const sync = () => {
            range.disabled = !box.checked;
            d.ability = box.checked ? Math.round(Number(range.value) * 10000) / 10000 : null;
            d.own.add('ability');
            show();
        };
        box.addEventListener('change', sync);
        range.addEventListener('input', sync);
        show();
        return h('div', { class: 'field cup-standard' }, h('span', {}, label),
            h('span', { class: 'cup-optional ability' }, h('label', { class: 'check' }, box, t('tournament.optional.set')), range, shown),
            h('span', { class: 'muted small' }, t('tournament.settings.ability.help')));
    }

    // A number that may be left to its default, a box that turns it on and the number itself.
    optionalNumber(field, value, onChange) {
        const on = value !== null && value !== undefined;
        const box = h('input', { type: 'checkbox', checked: on, 'aria-label': t('tournament.optional.set.label', { label: field.label }) });
        const input = h('input', {
            type: 'number', min: String(field.min), max: String(field.max), step: String(field.step || 1),
            value: String(on ? value : field.initial), disabled: !on, 'aria-label': field.label,
        });
        const shown = h('span', { class: 'muted small' }, on ? '' : field.off);
        const sync = () => {
            input.disabled = !box.checked;
            shown.textContent = box.checked ? '' : field.off;
            onChange(box.checked ? Number(input.value) : null);
        };
        box.addEventListener('change', sync);
        input.addEventListener('input', sync);
        return h('span', { class: 'cup-optional' }, h('label', { class: 'check' }, box, t('tournament.optional.set')), input, shown);
    }

    stagesStep() {
        const d = this.draft;
        const stages = d.stages.map((stage, index) => this.stageCard(stage, index));
        const json = h('textarea', { class: 'cup-json', rows: '14', spellcheck: 'false', 'aria-label': t('tournament.json.label') },
            JSON.stringify({ ability: d.ability ?? null, defaults: d.defaults, stages: d.stages }, null, 2));
        // The note of a mistake stays in place and empty until there is one, so a screen reader
        // hears it.
        const applied = h('p', { class: 'small cup-json-note', id: 'cup-json-note', role: 'status' });
        json.setAttribute('aria-describedby', 'cup-json-note');
        json.addEventListener('input', () => {
            json.removeAttribute('aria-invalid');
            applied.replaceChildren();
        });
        const refuse = (text, at = null) => {
            json.setAttribute('aria-invalid', 'true');
            applied.replaceChildren(icon('warning', 'icon text-symbol'), text);
            // The caret goes to the mistake, so the person fixes it where it is.
            if (at !== null) {
                json.focus();
                json.setSelectionRange(at, at);
            }
        };
        const apply = h('button', { type: 'button', class: 'btn', ...symbolOnly(t('tournament.json.apply')), onclick: () => {
            let value;
            try {
                value = JSON.parse(json.value);
            } catch (err) {
                const place = jsonErrorPlace(json.value, err);
                if (!place) {
                    refuse(t('tournament.json.unreadable'));
                    return;
                }
                const lines = json.value.split('\n');
                const at = lines.slice(0, place.line - 1).reduce((sum, line) => sum + line.length + 1, 0) + place.column - 1;
                refuse(t('tournament.json.failed', place), Math.min(at, json.value.length));
                return;
            }
            if (!value || typeof value !== 'object' || !Array.isArray(value.stages)) {
                refuse(t('tournament.json.expected'));
                return;
            }
            d.stages = value.stages;
            d.defaults = value.defaults && typeof value.defaults === 'object' ? value.defaults : {};
            d.ability = value.ability ?? null;
            this.renderWizard();
            this.app.hud.toast(t('tournament.json.applied'));
        } }, icon('check'));
        // The editor of JSON stays open through the redraws that applying it makes.
        const jsonBox = h('details', { class: 'cup-json-box', open: !!this.jsonOpen }, h('summary', {}, t('tournament.json.edit')), json, h('div', { class: 'row' }, apply), applied);
        jsonBox.addEventListener('toggle', () => {
            this.jsonOpen = jsonBox.open;
        });
        return [
            h('p', { class: 'muted' }, tn('tournament.stages.intro')),
            h('div', { class: 'cup-form' }, this.standardControl()),
            h('div', { class: 'cup-stages' }, stages),
            h('button', { type: 'button', class: 'btn', 'data-focus': 'add-stage', disabled: d.stages.length >= 8, ...symbolOnly(t('tournament.stages.add')), onclick: () => {
                d.stages.push({ format: 'knockout', name: '' });
                this.renderWizard();
                // The new stage opens at its first field, its name.
                [...this.mainHost.querySelectorAll('.cup-stage')].at(-1)?.querySelector('input, select')?.focus();
            } }, icon('plus')),
            jsonBox,
        ];
    }

    stageCard(stage, index) {
        const d = this.draft;
        const last = index === d.stages.length - 1;
        const format = stage.format || 'knockout';
        const merged = { ...STAGE_DEFAULTS, ...d.defaults, ...stage };
        const rows = STAGE_FIELDS.filter((f) => (!f.formats || f.formats.includes(format))
            && !(f.later && index === 0) && !(f.notLast && last))
            .map((field) => this.stageField(stage, merged, field, index));
        // A stage that moves keeps the focus on the button that moved it, or on the other one at
        // either end, and a removed stage gives it to the stage that takes its place.
        const focusStage = (at, ...kinds) => {
            const card = this.mainHost.querySelectorAll('.cup-stage')[at];
            kinds.map((kind) => card && card.querySelector(`[data-stage="${kind}"]`))
                .find((button) => button && !button.disabled)?.focus();
        };
        const move = (by) => {
            const to = index + by;
            [d.stages[index], d.stages[to]] = [d.stages[to], d.stages[index]];
            this.renderWizard();
            focusStage(to, by < 0 ? 'earlier' : 'later', by < 0 ? 'later' : 'earlier');
            const moved = d.stages[to];
            const name = stageNameText(moved.name) || FORMAT_NAMES[moved.format] || moved.format;
            this.announce(t('tournament.moved', { name, place: to + 1, total: d.stages.length }));
        };
        const number = index + 1;
        return h('fieldset', { class: 'cup-stage' },
            h('legend', {}, t('tournament.stage.legend', { number: index + 1, format: FORMAT_NAMES[format] || format })),
            h('div', { class: 'cup-stage-fields' }, rows),
            h('div', { class: 'row' },
                h('button', { type: 'button', class: 'btn small ghost', 'data-stage': 'earlier', disabled: index === 0, ...symbolOnly(t('tournament.stage.earlier', { number })), onclick: () => move(-1) }, icon('up')),
                h('button', { type: 'button', class: 'btn small ghost', 'data-stage': 'later', disabled: last, ...symbolOnly(t('tournament.stage.later', { number })), onclick: () => move(1) }, icon('down')),
                h('button', { type: 'button', class: 'btn small ghost danger', 'data-stage': 'remove', disabled: d.stages.length === 1, ...symbolOnly(t('tournament.stage.remove', { number })), onclick: () => {
                    d.stages.splice(index, 1);
                    this.renderWizard();
                    const count = this.mainHost.querySelectorAll('.cup-stage').length;
                    focusStage(Math.min(index, count - 1), 'remove', 'earlier', 'later');
                    if (!this.mainHost.contains(document.activeElement)) {
                        this.mainHost.querySelector('[data-focus="add-stage"]')?.focus();
                    }
                } }, icon('close'))));
    }

    stageField(stage, merged, field, index) {
        const set = (value) => {
            stage[field.key] = value;
        };
        const label = t('tournament.stage.fieldLabel', { label: field.label, number: index + 1 });
        let control;
        const value = merged[field.key];
        if (field.type === 'text') {
            // A name that the server or a preset gives shows in the language of the page, and
            // stays the server's until a person types another.
            const format = FORMAT_NAMES[merged.format] || merged.format;
            control = h('input', { type: 'text', maxlength: '60', value: stageNameText(value), placeholder: format, 'aria-label': label });
            control.addEventListener('input', () => set(control.value));
        } else if (field.type === 'select') {
            const options = field.key === 'draws' && value === null
                ? field.options : field.options;
            const shown = value ?? (field.key === 'draws' ? (merged.format === 'gauntlet' ? 'settle' : 'holder') : '');
            control = this.select(options, shown, label, (v) => {
                set(v);
                if (field.key === 'format') {
                    this.renderWizard();
                }
            });
        } else if (field.type === 'scenario') {
            control = this.scenarioSelect(value, label, field.empty || null, set);
        } else if (field.type === 'number') {
            control = h('input', { type: 'number', min: String(field.min), max: String(field.max), step: '1', value: String(value), 'aria-label': label });
            control.addEventListener('input', () => set(Number(control.value)));
        } else if (field.type === 'optional') {
            // A stage that sets no ability follows the standard, where the tournament has one.
            const standard = field.key === 'ability' ? this.draft.ability : null;
            const off = standard === null || standard === undefined ? field.off : t('tournament.off.standard', { ability: abilityText(standard) });
            control = this.optionalNumber({ ...field, label, off }, value, set);
        } else if (field.type === 'check') {
            control = h('input', { type: 'checkbox', checked: !!value, 'aria-label': label });
            control.addEventListener('change', () => set(control.checked));
            control = h('label', { class: 'check' }, control, t('tournament.stage.on'));
        } else if (field.type === 'points') {
            const points = { ...value };
            control = h('span', { class: 'cup-points' }, ['win', 'draw', 'loss'].map((name) => {
                const input = h('input', { type: 'number', min: '-100', max: '100', step: '1', value: String(points[name]), 'aria-label': t(`tournament.points.${name}.label`, { number: index + 1 }) });
                input.addEventListener('input', () => {
                    points[name] = Number(input.value);
                    set({ ...points });
                });
                return h('label', { class: 'field small-field' }, t(`tournament.points.${name}`), input);
            }));
        } else if (field.type === 'list') {
            const text = Array.isArray(value) ? value.join(', ') : value ?? '';
            control = h('input', { type: 'text', value: String(text), placeholder: field.placeholder, 'aria-label': label });
            control.addEventListener('input', () => {
                const parts = control.value.split(/[\s,]+/).filter(Boolean).map(Number);
                if (!control.value.trim()) {
                    set(field.single ? 2 : null);
                } else if (field.single && parts.length === 1) {
                    set(parts[0]);
                } else {
                    set(parts);
                }
            });
        } else if (field.type === 'fill') {
            const fill = value === 'fill';
            const box = h('input', { type: 'checkbox', checked: fill, 'aria-label': t('tournament.stage.fill.label', { number: index + 1 }) });
            const input = h('input', { type: 'number', min: '0', max: '128', step: '1', value: fill ? '0' : String(value || 0), disabled: fill, 'aria-label': label });
            const sync = () => {
                input.disabled = box.checked;
                set(box.checked ? 'fill' : Number(input.value));
            };
            box.addEventListener('change', sync);
            input.addEventListener('input', sync);
            control = h('span', { class: 'cup-optional' }, input, h('label', { class: 'check' }, box, t('tournament.stage.fill')));
        } else if (field.type === 'order') {
            control = this.orderControl(field, value, set, label, index + 1);
        }
        return h('div', { class: 'field cup-field' }, h('span', { class: 'cup-field-label' }, field.label), control,
            field.help ? h('span', { class: 'muted small' }, field.help) : null);
    }

    // An ordered choice, such as the tiebreakers, each option on or off with buttons to move it.
    orderControl(field, value, set, label, number) {
        const chosen = (value || []).filter((v) => field.options.includes(v));
        // Lots always decide last, so they stay at the end of the list.
        const order = [...chosen, ...field.options.filter((v) => !chosen.includes(v))].filter((v) => v !== 'lots');
        if (field.options.includes('lots')) {
            order.push('lots');
        }
        const list = h('ol', { class: 'cup-order', 'aria-label': label });
        // The names of tiebreakers continue sentences elsewhere, so they start small, and a list
        // shows each as a name of its own, as the ways to settle a tie read.
        const shown = (name) => sentence(field.names[name]);
        const draw = (focus = null) => {
            list.replaceChildren(...order.map((name, i) => {
                const on = chosen.includes(name);
                const box = h('input', { type: 'checkbox', checked: on || name === 'lots', disabled: name === 'lots', 'data-focus': `use-${name}`, 'aria-label': t('tournament.order.use.label', { name: shown(name), number }) });
                // The items in use stay first, in their order, so the list reads as the order of
                // play, an item taken into use joining the end of them and one left out leaving.
                box.addEventListener('change', () => {
                    order.splice(order.indexOf(name), 1);
                    if (box.checked) {
                        chosen.push(name);
                    } else {
                        chosen.splice(chosen.indexOf(name), 1);
                    }
                    const last = order.reduce((end, item, at) => (chosen.includes(item) ? at + 1 : end), 0);
                    order.splice(last, 0, name);
                    commit();
                    draw(`use-${name}`);
                });
                // An item out of use takes no place in the order, so it has no button to move it.
                const up = !on || name === 'lots' ? null : h('button', { type: 'button', class: 'btn small ghost', disabled: i === 0, ...symbolOnly(t('tournament.order.earlier.label', { name: shown(name), number })), onclick: () => {
                    [order[i - 1], order[i]] = [order[i], order[i - 1]];
                    commit();
                    // At the top of the list the button no longer moves it, so its box takes the focus.
                    draw(i - 1 === 0 ? `use-${name}` : `up-${name}`);
                    const now = order.filter((item) => chosen.includes(item) || item === 'lots');
                    this.announce(t('tournament.moved', { name: shown(name), place: now.indexOf(name) + 1, total: now.length }));
                } }, icon('up'));
                if (up) {
                    up.dataset.focus = `up-${name}`;
                }
                return h('li', { class: on || name === 'lots' ? '' : 'off' }, h('label', { class: 'check' }, box, shown(name)), up);
            }));
            if (focus) {
                list.querySelector(`[data-focus="${focus}"]`)?.focus();
            }
        };
        const commit = () => {
            const list = order.filter((name) => chosen.includes(name) || name === 'lots');
            set(list);
        };
        draw();
        return list;
    }

    reviewStep() {
        // The check runs on the server while the person may type the name of a preset below, and
        // its place shows that it runs until the answer takes it.
        const host = h('div', { class: 'cup-review', 'aria-busy': 'true' },
            h('p', { class: 'muted cup-checking', role: 'status' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), t('tournament.review.checking')));
        const saveName = h('input', { type: 'text', class: 'cup-preset-name', maxlength: '64', placeholder: t('tournament.review.presetName.placeholder'), pattern: PRESET_NAME.source, 'aria-label': t('tournament.review.presetName.label') });
        const saveTitle = h('input', { type: 'text', maxlength: '60', placeholder: t('tournament.review.presetTitle.placeholder'), value: this.draft.name, 'aria-label': t('tournament.review.presetTitle.label') });
        const saveButton = h('button', { type: 'button', class: 'btn', 'data-focus': 'save-preset', ...symbolOnly(t('tournament.review.save')), onclick: () => {
            // A name that the server cannot take is refused here, with its rule and the focus on
            // the name.
            const name = saveName.value.trim();
            if (!PRESET_NAME.test(name)) {
                saveName.setAttribute('aria-invalid', 'true');
                this.app.hud.toast(t('tournament.review.presetName.rule'), 'error', 7000);
                saveName.focus();
                return;
            }
            saveName.removeAttribute('aria-invalid');
            const own = this.presets[name];
            if (!own || own.shipped) {
                this.savePreset(name, saveTitle.value.trim());
                return;
            }
            // A preset of the person by that name is replaced only once the person says so, in
            // place of the button, as a delete asks.
            const back = () => {
                ask.replaceWith(saveButton);
                saveButton.focus();
            };
            const ask = this.confirmGroup(t('tournament.review.replace.confirm', { title: own.title }),
                [icon('save'), t('tournament.review.replace')], t('tournament.review.replace.no'), async () => {
                    await this.savePreset(name, saveTitle.value.trim());
                    back();
                }, back);
            saveButton.replaceWith(ask);
            ask.querySelector('[data-answer="no"]').focus();
        } }, icon('save'));
        const save = h('div', { class: 'cup-save' },
            h('h3', {}, t('tournament.review.save.title')),
            h('div', { class: 'row' },
                h('label', { class: 'field' }, t('tournament.review.presetName'), saveName),
                h('label', { class: 'field' }, t('tournament.review.presetTitle.placeholder'), saveTitle),
                saveButton));
        const clashes = this.nameClashes();
        if (clashes.length) {
            // Two entrants that share a name go back to the entrants step, before any check.
            host.setAttribute('aria-busy', 'false');
            host.replaceChildren(h('div', { class: 'notice error', role: 'alert' },
                h('ul', { class: 'symbol-list' }, clashes.map((clash) => h('li', {}, icon('warning', 'icon text-symbol'), t('tournament.review.nameTaken', { number: clash.index + 1, name: clash.name, other: clash.other + 1 })))),
                h('p', { class: 'muted small' }, t('tournament.review.names'))));
            queueMicrotask(() => this.holdStart(host.firstElementChild));
        } else {
            this.check(host);
        }
        return [host, save];
    }

    config() {
        const d = this.draft;
        const config = {
            seeding: d.seeding, concurrency: d.concurrency,
            forfeit_score: d.forfeit_score, defaults: d.defaults, stages: d.stages,
            entrants: d.entrants.map((e) => {
                const entry = { kind: e.kind };
                for (const key of ['team', 'name', 'rating', 'teammates', 'ability']) {
                    if (e[key] !== undefined && e[key] !== null && e[key] !== '') {
                        entry[key] = e[key];
                    }
                }
                return entry;
            }),
        };
        // A tournament left without a name takes the server's, which reads in any language.
        if ((d.name || '').trim()) {
            config.name = d.name.trim();
        }
        if (d.seed !== '' && d.seed !== null && d.seed !== undefined) {
            config.seed = /^\d+$/.test(String(d.seed)) ? Number(d.seed) : d.seed;
        }
        if (d.preset) {
            config.preset = d.preset;
        }
        if (d.ability !== null && d.ability !== undefined) {
            config.ability = d.ability;
        }
        return config;
    }

    async check(host) {
        try {
            const preview = await tournamentsApi.check(this.config());
            host.setAttribute('aria-busy', 'false');
            const entrants = preview.config.entrants;
            const standard = preview.config.ability ?? null;
            const parts = [h('p', {}, t('tournament.review.summary', {
                entrants: t('tournament.count.entrants', { count: entrants.length }), seed: preview.config.seed,
                matches: t('tournament.review.matches', { count: preview.matches }),
            })), h('p', { class: 'muted small cup-review-ability' }, standardText(standard))];
            const own = entrants.filter((e) => shownAbility(e, standard) !== null);
            if (own.length) {
                parts.push(h('ul', { class: 'cup-review-abilities small' }, own.map((e) => h('li', {}, entrantName(e), ' ', abilityBadge(e, standard)))));
            }
            this.draft.seed = String(preview.config.seed);
            preview.stages.forEach((stage, index) => {
                const settings = preview.config.stages[index];
                parts.push(h('section', { class: 'cup-review-stage' },
                    h('h3', {}, t('tournament.review.stage', { number: index + 1, name: serverText(settings, 'name') })),
                    h('p', { class: 'muted small' }, [
                        stageText(settings), t('tournament.count.entrants', { count: settings.entrants }),
                        index < preview.stages.length - 1 ? t('tournament.review.advance', { count: settings.advance }) : null,
                        scenarioName(settings.scenario), settings.length ? t('tournament.count.steps', { count: settings.length }) : null,
                        settings.ability != null ? t('tournament.stage.ability', { ability: abilityText(settings.ability) }) : null,
                    ].filter(Boolean).join(', ')),
                    stage.tables && stage.tables.length && settings.format === 'groups'
                        ? h('div', { class: 'cup-review-groups' }, stage.tables.map((table) => h('div', {},
                            h('h4', {}, serverText(table, 'name')), h('ul', {}, table.rows.map((row) => h('li', {}, entrantName(entrants[row.entrant])))))))
                        : null,
                    stage.rounds && stage.rounds.length && settings.format !== 'groups'
                        ? h('div', {}, h('h4', {}, serverText(stage.rounds[0], 'name')), h('ul', { class: 'cup-review-draw' },
                            stage.rounds[0].fixtures.slice(0, 32).map((f) => h('li', {}, t('tournament.versus', { home: sideName(f.home, entrants), away: sideName(f.away, entrants) })))))
                        : null));
            });
            host.replaceChildren(...parts);
        } catch (err) {
            host.setAttribute('aria-busy', 'false');
            // A scenario that an entrant cannot play names its stage, so a button leads straight to
            // that stage's scenario.
            // A scenario of the deciding matches leads to that field of the stage instead.
            const decider = err.id === 'server.tournament.cannot_play_decider';
            // Teams of both sizes are told a scenario that fits them, which the button leads to as well.
            const stage = ['server.tournament.cannot_play', 'server.tournament.mixed_sizes'].includes(err.id) || decider ? Number(err.values?.stage) : NaN;
            const fix = Number.isInteger(stage) && stage >= 1 && stage <= this.draft.stages.length
                ? h('button', { type: 'button', class: 'btn cup-fix-scenario', onclick: () => this.focusStageScenario(stage - 1, decider) },
                    icon('edit'), t(decider ? 'tournament.review.fixDecider' : 'tournament.review.fixScenario', { number: stage }))
                : null;
            host.replaceChildren(h('div', { class: 'notice error', role: 'alert' }, h('p', {}, err.message),
                h('p', { class: 'muted small' }, tn('tournament.review.failed')), fix));
            if (host.isConnected) {
                this.holdStart(host.firstElementChild);
            }
        }
    }

    // Holds Start tournament while the review shows a refusal, the refusal as its description,
    // so a person who reaches the button hears why it waits, and a press leads to the refusal.
    holdStart(refusal) {
        const start = this.mainHost.querySelector('.cup-start');
        if (!start || !refusal) {
            return;
        }
        refusal.id = 'cup-review-refusal';
        refusal.tabIndex = -1;
        start.setAttribute('aria-disabled', 'true');
        start.setAttribute('aria-describedby', refusal.id);
    }

    async savePreset(name, title) {
        const d = this.draft;
        try {
            const saved = await tournamentsApi.savePreset(name, {
                title: title || d.name || name, description: '', seeding: d.seeding, concurrency: d.concurrency,
                forfeit_score: d.forfeit_score, ability: d.ability ?? null, defaults: d.defaults, stages: d.stages,
            });
            this.presets[name] = saved;
            this.app.hud.toast(t('tournament.review.saved', { title: saved.title }));
        } catch (err) {
            this.app.hud.toast(err.message, 'error', 7000);
        }
    }

    async create(button) {
        if (button.getAttribute('aria-disabled') === 'true') {
            document.getElementById('cup-review-refusal')?.focus();
            return;
        }
        if (this.nameClashes().length) {
            this.app.hud.toast(t('tournament.review.names'), 'error', 7000);
            return;
        }
        button.disabled = true;
        try {
            const entry = await tournamentsApi.create(this.config());
            this.app.hud.toast(t('tournament.started', { name: serverText(entry, 'name') }));
            this.draft = null;
            this.list = await tournamentsApi.list();
            await this.open(entry.id);
        } catch (err) {
            this.app.hud.toast(err.message, 'error', 8000);
            button.disabled = false;
        }
    }

    // A tournament.

    async open(id) {
        this.mode = 'view';
        this.root.querySelector('.cup-layout')?.classList.remove('brackets');
        this.openId = id;
        this.awarding = null;
        this.asking = null;
        this.stageTab = null;
        this.renderList();
        this.mainHost.setAttribute('aria-busy', 'true');
        await this.load(id);
        this.mainHost.setAttribute('aria-busy', 'false');
        this.mainHost.querySelector('h2')?.focus();
    }

    async load(id) {
        try {
            const entry = await this.fetchCup(id);
            if (this.openId !== id) {
                return;
            }
            const before = this.current && this.current.id === id ? this.current : null;
            this.current = entry;
            this.renderView();
            this.announceChanges(before, entry);
            // A team registered since the page read the registry would show as a dot of its
            // color, so the registry is read again once for the teams it lacks.
            const missing = [...new Set(entry.config.entrants.map((e) => e.team).filter((team) => team && !this.teams.some((x) => x.id === team)))].join('|');
            if (missing && missing !== this.teamsAsked) {
                this.teamsAsked = missing;
                this.refreshTeams();
            }
        } catch (err) {
            if (err.status === 404) {
                this.mode = 'empty';
                this.openId = null;
                this.current = null;
                this.refresh();
            } else {
                this.app.hud.toast(err.message, 'error');
            }
        }
    }

    // Says what changed in the open tournament since it was last read, the results of matches
    // that ended and a stop. A result that waits to be watched without spoilers has none yet,
    // and the end of a tournament has a toast of its own.
    announceChanges(before, entry) {
        if (!before || !this.announcer) {
            return;
        }
        const entrants = entry.config.entrants;
        const old = new Map(before.matches.map((m) => [m.key, m]));
        const said = entry.matches.filter((m) => m.result && Array.isArray(m.result.score)
            && !(old.get(m.key) && old.get(m.key).result)).map((m) => t('tournament.announce.result', {
            label: serverText(m, 'label'), home: entrantName(entrants[m.home]), away: entrantName(entrants[m.away]),
            left: m.result.score[0], right: m.result.score[1],
        }));
        // Many results at once, as Reveal all shows them, are said as their count.
        if (said.length > 3) {
            said.splice(0, said.length, t('tournament.announce.results', { count: said.length }));
        }
        if (entry.state === 'stopped' && before.state !== 'stopped') {
            said.push(t('tournament.announce.stopped', { name: serverText(entry, 'name') }));
        }
        if (said.length) {
            this.announce(said.join(' '));
        }
    }

    // A tournament in full, or as the person sees it who watches it without spoilers, whose
    // unwatched recordings the lists of the page then leave out.
    async fetchCup(id) {
        if (!spoilerFree(id)) {
            return tournamentsApi.get(id);
        }
        const entry = await tournamentsApi.spoilers(id, watchedKeys(id));
        const recordings = {};
        for (const m of entry.matches || []) {
            if (m.unseen && m.unseen.match) {
                recordings[m.key] = m.unseen.match;
            }
        }
        noteRecordings(id, recordings);
        return entry;
    }

    renderView() {
        const cup = this.current;
        if (cup && this.mode === 'brackets') {
            this.renderBrackets();
            return;
        }
        if (!cup || this.mode !== 'view') {
            return;
        }
        this.root.querySelector('.cup-layout')?.classList.remove('brackets');
        const entrants = cup.config.entrants;
        this.matchMap = new Map(cup.matches.map((m) => [m.key, m]));
        if (this.stageTab === null || this.stageTab >= cup.stages_view.length) {
            const playing = cup.stages_view.findIndex((s) => s.state !== 'done');
            this.stageTab = playing >= 0 ? playing : cup.stages_view.length - 1;
        }
        const share = progressShare(cup);
        const actions = [];
        // Each action shows its words beside its symbol, so the actions of a tournament read
        // at a glance on any screen.
        if (cup.state === 'running') {
            // Canceling cannot be undone, so it asks first in place of the button.
            actions.push(this.askButton('cancel',
                h('button', { type: 'button', class: 'btn ghost danger' }, icon('stop'), t('tournament.view.cancel')),
                t('tournament.view.cancel.confirm', { name: serverText(cup, 'name') }), t('tournament.view.cancel'), t('tournament.view.cancel.no'),
                () => this.act('cancel', t('tournament.view.cancelled'))));
        }
        if (cup.state === 'stopped') {
            actions.push(h('button', { type: 'button', class: 'btn primary', 'data-focus': 'act-resume', onclick: () => this.act('resume', t('tournament.view.resumed')) }, icon('play'), t('tournament.view.resume')));
        }
        // Without spoilers, the ceremony waits until the person has watched the champion win.
        if (cup.state === 'done' && cup.champion_index !== null && cup.champion_index !== undefined) {
            actions.push(h('button', { type: 'button', class: 'btn primary', 'data-focus': 'act-ceremony', onclick: () => this.ceremony() }, icon('trophy'), t('tournament.view.ceremony')));
        }
        actions.push(h('button', { type: 'button', class: 'btn ghost', 'data-focus': 'act-brackets', onclick: () => this.openBrackets(cup.id) }, icon('grid'), t('tournament.brackets.open')));
        actions.push(h('button', { type: 'button', class: 'btn ghost', 'data-focus': 'act-again', onclick: () => {
            const config = clone(cup.config);
            this.startWizard(config);
            this.draft.seed = '';
        } }, icon('replay'), t('tournament.view.again')));
        if (cup.state !== 'running') {
            actions.push(this.askButton('delete',
                h('button', { type: 'button', class: 'btn ghost danger' }, icon('trash'), t('tournament.view.delete')),
                t('tournament.delete.confirm', { name: serverText(cup, 'name') }), t('tournament.view.delete'), t('tournament.forfeit.no'),
                () => this.remove()));
        }
        const head = h('header', { class: 'cup-head' },
            h('h2', { tabindex: '-1', 'data-focus': 'cup-title' }, serverText(cup, 'name')),
            h('p', { class: 'cup-meta' },
                stateBadge(cup.state, STATE_LABELS[cup.state] || cup.state, `state-pill ${cup.state === 'running' ? 'running' : cup.state === 'done' ? 'done' : 'failed'}`),
                h('span', {}, t('tournament.count.entrants', { count: entrants.length })),
                h('span', {}, t('tournament.view.seed', { seed: cup.seed })),
                h('span', { class: 'cup-view-ability' }, standardText(cup.config.ability ?? null)),
                // A tournament that ended reads as finished, its schedule played in full.
                h('span', { class: 'cup-view-played' }, cup.state === 'done' ? t('tournament.view.finished', { count: cup.played })
                    : t('tournament.view.played', { count: cup.played, total: cup.scheduled })),
                cup.running ? h('span', {}, t('tournament.view.running', { count: cup.running })) : null),
            cup.state === 'running' ? h('div', { class: 'progress', role: 'progressbar', 'aria-label': t('tournament.view.progress.label'), 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round(share * 100)) },
                h('div', { class: 'bar', style: `width:${Math.round(share * 100)}%` })) : null,
            cup.champion ? h('p', { class: 'cup-champion' }, h('span', {}, t('tournament.view.champion', { name: serverText(cup, 'champion') }))) : null,
            cup.state === 'cancelled' ? h('p', { class: 'notice cup-canceled' }, icon('close', 'icon text-symbol'), t('tournament.view.canceledNote')) : null,
            cup.error ? h('div', { class: 'notice error', role: 'alert' }, h('p', {}, sentence(serverText(cup, 'error'))), this.failedAwards(cup)) : null,
            cup.persistence_error ? h('div', { class: 'notice error' }, h('p', {}, sentence(serverText(cup, 'persistence_error')))) : null,
            cup.owner ? h('p', { class: 'muted small' }, t('tournament.view.owner', { owner: cup.owner })) : null,
            h('div', { class: 'row cup-actions' }, actions),
            this.spoilerBar(cup));
        const open = ['running', 'stopped'].includes(cup.state);
        const people = open ? cup.matches.filter((m) => ['person', 'playing'].includes(m.state)) : [];
        const peopleBox = people.length ? h('section', { class: 'cup-people', 'aria-labelledby': 'cup-people-title' },
            h('h3', { id: 'cup-people-title' }, t('tournament.people.title')),
            cup.state === 'stopped' ? h('p', { class: 'muted small' }, t('tournament.people.resume')) : null,
            h('ul', {}, people.map((m) => h('li', {},
                h('span', {}, t('tournament.people.match', { label: serverText(m, 'label'), home: entrantName(entrants[m.home]), away: entrantName(entrants[m.away]), scenario: scenarioName(m.scenario) })),
                m.note ? h('span', { class: 'muted small' }, serverText(m, 'note')) : null,
                m.state === 'playing' ? h('span', { class: 'muted small' }, t('tournament.people.playing'))
                    : h('span', { class: 'row' },
                        h('button', { type: 'button', class: 'btn small primary', 'data-focus': `people-${m.key}`, disabled: cup.state !== 'running', onclick: () => this.playMatch(m) }, icon('play'), t('tournament.play')),
                        this.forfeitButton(m, 'home'), this.forfeitButton(m, 'away')))))) : null;
        const tabs = h('div', { class: 'cup-tabs', role: 'tablist', 'aria-label': t('tournament.view.stages.label') }, cup.stages_view.map((stage, index) => h('button', {
            type: 'button', role: 'tab', id: `cup-tab-${index}`, 'aria-selected': index === this.stageTab ? 'true' : 'false',
            tabindex: index === this.stageTab ? '0' : '-1', class: `cup-tab${index === this.stageTab ? ' active' : ''}`, 'aria-controls': 'cup-stage-panel',
            onclick: () => {
                this.stageTab = index;
                this.renderView();
                document.getElementById(`cup-tab-${index}`)?.focus();
            },
            onkeydown: (e) => {
                const by = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
                if (by) {
                    e.preventDefault();
                    this.stageTab = (index + by + cup.stages_view.length) % cup.stages_view.length;
                    this.renderView();
                    document.getElementById(`cup-tab-${this.stageTab}`)?.focus();
                }
            },
        }, serverText(stage, 'name'), h('span', { class: 'muted small' }, ` ${FORMAT_NAMES[stage.format] || stage.format}`))));
        const stage = cup.stages_view[this.stageTab];
        const panel = h('div', { class: 'cup-stage-view', id: 'cup-stage-panel', role: 'tabpanel', 'aria-labelledby': `cup-tab-${this.stageTab}` },
            this.stageView(stage, cup.config.stages[this.stageTab]));
        const ranking = cup.ranking ? h('section', { class: 'cup-ranking', 'aria-labelledby': 'cup-ranking-title' },
            h('h3', { id: 'cup-ranking-title' }, t('tournament.view.ranking')),
            h('ol', {}, cup.ranking.map((e) => h('li', {}, entrantName(entrants[e]))))) : null;
        const focused = document.activeElement && this.mainHost.contains(document.activeElement) ? document.activeElement : null;
        // An action that took the focus with it, such as a confirmed award, names where it was.
        const focusKey = focused ? (focused.id || focused.dataset.focus || null) : this.focusAfter || null;
        const byId = !!focused && focusKey === focused.id;
        this.focusAfter = null;
        const scroll = this.mainHost.scrollTop;
        this.mainHost.replaceChildren(h('div', { class: 'cup-view' }, head, this.caughtUp(cup), peopleBox, this.upNextBox(cup), tabs, panel, ranking));
        this.mainHost.scrollTop = scroll;
        if (focusKey) {
            this.refocus(focusKey, byId);
        }
    }

    // A button of the tournament that asks first, as an award does, the question with its yes and
    // no in place of the button, through the page's refreshes until either answer. Escape or no
    // leaves everything as it was, and the focus returns to the button.
    askButton(name, button, question, yes, no, onYes) {
        const focus = (key) => this.mainHost.querySelector(`[data-focus="${CSS.escape(key)}"]`)?.focus();
        if (this.asking !== name) {
            button.dataset.focus = `act-${name}`;
            button.addEventListener('click', () => {
                this.asking = name;
                this.renderView();
                focus(`ask-no-${name}`);
            });
            return button;
        }
        const cancel = () => {
            this.asking = null;
            this.renderView();
            focus(`act-${name}`);
        };
        return h('span', {
            class: 'cup-confirm', role: 'group', 'aria-label': question,
            onkeydown: (e) => {
                if (e.key === 'Escape') {
                    e.preventDefault();
                    e.stopPropagation();
                    cancel();
                }
            },
        },
        h('span', { class: 'small' }, question),
        h('button', { type: 'button', class: 'btn small primary danger', 'data-focus': `ask-yes-${name}`, onclick: (e) => {
            e.currentTarget.disabled = true;
            this.asking = null;
            this.focusAfter = `ask-yes-${name}`;
            onYes();
        } }, yes),
        h('button', { type: 'button', class: 'btn small ghost', 'data-focus': `ask-no-${name}`, onclick: cancel }, icon('close'), no));
    }

    // Focuses the control of `key` again once the tournament is drawn anew, or when it is gone or
    // can no longer be used, as after an award, a reveal or a change of state, a control that
    // takes its place, else the name of the tournament, so the focus never falls to the page.
    refocus(key, byId = false) {
        const find = (name) => {
            const node = this.mainHost.querySelector(`[data-focus="${CSS.escape(name)}"]`);
            return node && !node.disabled ? node : null;
        };
        const usable = byId ? document.getElementById(key) : find(key);
        if (usable && !usable.disabled) {
            usable.focus();
            return;
        }
        const match = /^(?:unseen-watch|unseen-reveal)-(.+)$/.exec(key);
        const instead = {
            'act-resume': ['act-cancel', 'act-delete'], 'act-cancel': ['act-delete', 'act-resume'],
            'ask-yes-cancel': ['act-delete', 'act-resume'], 'ask-no-cancel': ['act-cancel'],
            'zoom-out': ['zoom-in'], 'zoom-in': ['zoom-out'], 'watch-next': ['reveal-all'],
        }[key] || (match ? [`watch-${match[1]}`, 'watch-next'] : []);
        const award = /^award-yes-(fixture|notice)-/.exec(key);
        const next = award ? [...this.mainHost.querySelectorAll(`[data-focus^="award-${award[1]}-"]`)].find((node) => !node.disabled) : null;
        const found = next || [...instead, 'watch-next'].map(find).find(Boolean);
        (found || this.mainHost.querySelector('h2'))?.focus();
    }

    // The awards of the failed matches, for the notice of a stopped tournament.
    failedAwards(cup) {
        if (cup.state !== 'stopped') {
            return null;
        }
        const failed = cup.matches.filter((m) => m.state === 'failed');
        if (!failed.length) {
            return null;
        }
        const entrants = cup.config.entrants;
        return h('ul', { class: 'cup-failed' }, failed.map((m) => h('li', {},
            h('span', {}, t('tournament.failed.match', { label: serverText(m, 'label'), home: entrantName(entrants[m.home]), away: entrantName(entrants[m.away]) })),
            h('span', { class: 'row' }, this.forfeitButton(m, 'home', 'notice'), this.forfeitButton(m, 'away', 'notice')))));
    }

    // The button that awards a match to one side, which asks first in a confirm step of its own,
    // the question with Award and Cancel in place of the button. Escape or Cancel leaves the
    // match as it was, and the step stays through the page's refreshes until either answer.
    forfeitButton(match, side, where = 'fixture') {
        const entrants = this.current.config.entrants;
        const winner = entrantName(entrants[side === 'home' ? match.home : match.away]);
        const id = `${where}-${match.key}-${side}`;
        const label = serverText(match, 'label');
        const focus = (key) => this.mainHost.querySelector(`[data-focus="${CSS.escape(key)}"]`)?.focus();
        if (this.awarding !== id) {
            return h('button', { type: 'button', class: 'btn small ghost', 'data-focus': `award-${id}`, onclick: () => {
                this.awarding = id;
                this.renderView();
                focus(`award-no-${id}`);
            } }, icon('flag'), t('tournament.forfeit', { name: winner }));
        }
        const cancel = () => {
            this.awarding = null;
            this.renderView();
            focus(`award-${id}`);
        };
        const question = t('tournament.forfeit.confirm', { label, name: winner, goals: this.current.config.forfeit_score });
        return h('span', {
            class: 'cup-confirm', role: 'group', 'aria-label': question,
            onkeydown: (e) => {
                if (e.key === 'Escape') {
                    e.preventDefault();
                    e.stopPropagation();
                    cancel();
                }
            },
        },
        h('span', { class: 'small' }, question),
        h('button', { type: 'button', class: 'btn small primary', 'data-focus': `award-yes-${id}`, onclick: async (e) => {
            e.currentTarget.disabled = true;
            this.focusAfter = `award-yes-${id}`;
            try {
                this.current = await tournamentsApi.action(this.current.id, 'forfeit', { key: match.key, winner: side });
                this.awarding = null;
                this.app.hud.toast(t('tournament.forfeit.done', { label, name: winner }));
                this.renderView();
            } catch (err) {
                this.awarding = null;
                this.renderView();
                this.app.hud.toast(err.message, 'error', 7000);
            }
        } }, icon('flag'), t('tournament.forfeit.yes')),
        h('button', { type: 'button', class: 'btn small ghost', 'data-focus': `award-no-${id}`, ...symbolOnly(t('tournament.forfeit.no')), onclick: cancel }, icon('close')));
    }

    stageView(stage, settings) {
        const entrants = this.current.config.entrants;
        const parts = [h('p', { class: 'muted small' }, [
            stageText(settings), scenarioName(settings.scenario), settings.length ? t('tournament.count.steps', { count: settings.length }) : null,
            settings.ability != null ? t('tournament.stage.ability', { ability: abilityText(settings.ability) }) : null,
            stage.state === 'waiting' && this.current.state !== 'cancelled' ? t('tournament.stage.waiting') : null,
            stage.state !== 'done' && this.current.state === 'cancelled' ? t('tournament.stage.cancelled') : null,
        ].filter(Boolean).join(', '))];
        if (stage.state === 'waiting') {
            return parts;
        }
        if (isBracket(stage)) {
            parts.push(...sections(stage).map((section) => this.bracket(section)));
        }
        for (const table of stage.tables || []) {
            parts.push(this.table(table, stage, settings));
        }
        if (!isBracket(stage)) {
            parts.push(h('section', { class: 'cup-fixtures', 'aria-label': t('tournament.fixtures') },
                h('h3', {}, t('tournament.fixtures')),
                stage.rounds.map((round) => h('div', { class: 'cup-round' },
                    h('h4', {}, this.roundTitle(round, entrants)),
                    h('ul', {}, round.fixtures.map((f) => h('li', {}, this.fixture(f))))))));
        }
        return parts;
    }

    // The title of a round, with the entrant who has a bye or holds the hill.
    roundTitle(round, entrants) {
        let title = serverText(round, 'name');
        if (round.bye != null) {
            title = t('tournament.round.bye', { round: title, name: entrantName(entrants[round.bye]) });
        }
        if (round.king != null) {
            title = t('tournament.round.king', { round: title, name: entrantName(entrants[round.king]) });
        }
        return title;
    }

    bracket(section) {
        const layout = bracketLayout(section.rounds);
        const byId = new Map(section.rounds.flatMap((r) => r.fixtures).map((f) => [f.id, f]));
        const roundOf = new Map(section.rounds.flatMap((r) => r.fixtures.map((f) => [f.id, r.name])));
        const grid = h('div', {
            class: 'cup-bracket', role: 'list',
            // The width of a round's column comes from the style, wide in the Brackets view, so its zoom
            // scales the whole bracket.
            style: `grid-template-columns: repeat(${layout.columns}, var(--cup-column)); grid-template-rows: auto repeat(${layout.rows}, minmax(32px, auto));`,
        });
        const name = SECTION_NAMES[section.name] || section.name;
        const titled = !(section.rounds.length === 1 && serverText(section.rounds[0], 'name') === name);
        section.rounds.forEach((round, column) => {
            if (titled) {
                grid.append(h('div', { class: 'cup-bracket-round', role: 'presentation', style: `grid-column:${column + 1}; grid-row:1` }, serverText(round, 'name')));
            }
        });
        layout.cells.flat().forEach((cell) => {
            const fixture = byId.get(cell.id);
            const place = `grid-column:${cell.column}; grid-row:${cell.rowStart + 1} / ${cell.rowEnd + 1}`;
            // A tie of two byes plays nothing and holds its place in the grid empty.
            if (fixture.home == null && fixture.away == null) {
                grid.append(h('div', { class: 'cup-bracket-cell empty', 'aria-hidden': 'true', style: place }));
                return;
            }
            grid.append(h('div', { class: 'cup-bracket-cell', role: 'listitem', style: place }, this.fixture(fixture, true, roundOf.get(cell.id))));
        });
        return h('section', { class: 'cup-bracket-section', 'aria-label': name },
            h('h3', {}, name), h('div', { class: 'cup-bracket-scroll', tabindex: '0', 'aria-label': t('tournament.bracket.scroll.label', { name }) }, grid));
    }

    fixture(f, compact = false, round = null) {
        const cup = this.current;
        const entrants = cup.config.entrants;
        const state = fixtureState(f, this.matchMap, cup.state === 'cancelled');
        const matches = fixtureMatches(f, this.matchMap);
        // Two entrants of one team meet with the away side in its away kit, as in the match.
        const same = typeof f.home === 'number' && typeof f.away === 'number' && entrants[f.home].team === entrants[f.away].team;
        const standard = cup.config.ability ?? null;
        // A side's name for a screen reader, with its own ability where it differs from the standard.
        const spokenSide = (value) => [sideName(value, entrants), typeof value === 'number' ? abilityWords(entrants[value], standard) : ''].filter(Boolean).join(', ');
        const side = (value, index) => {
            const known = typeof value === 'number';
            const won = f.winner !== null && f.winner !== undefined && f.winner === value && known;
            const team = known ? this.teams.find((x) => x.id === entrants[value].team) : null;
            const away = same && index === 1;
            const dot = known ? (away ? entrants[value].secondary : entrants[value].color) : null;
            return h('span', { class: `cup-side-name${won ? ' won' : ''}${known ? '' : ' unknown'}` },
                known && team ? kitShirt(away ? awayTeam(team) : team, index) : known ? h('span', { class: 'cup-dot', style: `background: rgb(${dot.join(',')})`, 'aria-hidden': 'true' }) : null,
                h('span', {}, sideName(value, entrants)),
                known ? abilityBadge(entrants[value], standard) : null,
                f.score ? h('b', { class: 'cup-goals' }, String(f.score[index])) : null);
        };
        const running = matches.find((m) => m.state === 'running');
        // How a tie was decided, left out where the score of its replay or deciding matches
        // already says so, after those scores, in the order things happened.
        const told = (f.decided_by === 'replay' && f.replay) || (f.decided_by === 'decider' && f.decider);
        const decided = !told && f.decided_by && DECIDED_NAMES[f.decided_by] ? DECIDED_NAMES[f.decided_by] : '';
        const watch = matches.filter((m) => m.result && m.result.match);
        const unseen = matches.filter((m) => m.state === 'unseen');
        // A failed match waits for an award to either side, or a retry by Resume.
        const failed = matches.find((m) => m.state === 'failed');
        const label = f.label ? serverText(f, 'label') : '';
        // A replay and the deciding matches have scores of their own beside the tie's.
        const extra = [f.replay ? t('tournament.fixture.replay', { left: f.replay[0], right: f.replay[1] }) : null,
            f.decider ? t('tournament.fixture.decider', { left: f.decider[0], right: f.decider[1] }) : null];
        const winner = typeof f.winner === 'number' && f.state === 'done' ? t('tournament.fixture.wonBy', { name: sideName(f.winner, entrants) }) : null;
        const spoken = [label, t('tournament.fixture.versus', { home: spokenSide(f.home), away: spokenSide(f.away) }),
            f.score ? t('tournament.fixture.score', { left: f.score[0], right: f.score[1] }) : null, ...extra, decided, winner, state !== 'done' ? STATE_NAMES[state] || state : null];
        return h('div', { class: `cup-fixture state-${state}`, 'aria-label': spoken.filter(Boolean).join(', ') },
            compact && label && f.label !== round ? h('span', { class: 'cup-fixture-label small muted' }, label) : null,
            side(f.home, 0), side(f.away, 1),
            h('span', { class: 'cup-fixture-meta small muted' },
                [...extra, decided, state !== 'done' ? STATE_NAMES[state] : null,
                    running ? t('tournament.fixture.percent', { pct: Math.round((running.progress || 0) * 100) }) : null,
                    f.group ? t('tournament.fixture.group', { group: f.group }) : null,
                    matches.some((m) => m.result && m.result.forfeit) ? t('tournament.fixture.awarded') : null,
                    failed && failed.error ? serverText(failed, 'error') : null].filter(Boolean).join(', ')),
            watch.length ? h('span', { class: 'cup-watch row' }, watch.map((m, i) => h('button', {
                type: 'button', class: 'btn small ghost', 'data-focus': `watch-${m.key}`,
                ...symbolOnly(t('tournament.watch.label', { label: serverText(m, 'label'), home: entrantName(entrants[m.home]), away: entrantName(entrants[m.away]) })),
                onclick: () => this.app.openMatchInWatch(m.result.match),
            }, icon('watch'), watch.length > 1 ? formatNumber(i + 1) : null))) : null,
            // Each match gives a pair of buttons, so the pairs flatten into one row.
            unseen.length ? h('span', { class: 'cup-unseen row' }, unseen.flatMap((m) => this.unseenButtons(m))) : null,
            failed ? h('span', { class: 'row' }, this.forfeitButton(failed, 'home'), this.forfeitButton(failed, 'away')) : null,
            matches.some((m) => m.state === 'person') ? h('button', { type: 'button', class: 'btn small primary', 'data-focus': `play-${f.id}`, disabled: cup.state !== 'running', ...symbolOnly(t('tournament.play')), onclick: () => this.playMatch(matches.find((m) => m.state === 'person')) }, icon('play')) : null);
    }

    table(table, stage, settings) {
        const entrants = this.current.config.entrants;
        const swiss = stage.format === 'swiss';
        const king = stage.format === 'king_of_the_hill';
        const head = ['place', 'entrant', 'played', 'won', 'drawn', 'lost', 'for', 'against', 'difference', 'points'].map((name) => t(`tournament.table.${name}`));
        if (swiss) {
            head.push(t('tournament.table.buchholz'), t('tournament.table.byes'));
        }
        if (king) {
            head.push(t('tournament.table.titles'));
        }
        const notes = [];
        const rows = table.rows.map((row, index) => {
            const next = table.rows[index + 1];
            const reason = tiebreakText(row, next, entrants);
            if (reason) {
                notes.push(h('li', {}, t('tournament.table.note', { name: entrantName(entrants[row.entrant]), reason })));
            }
            const qualified = index < table.qualify || row.best;
            const cells = [row.position, entrantName(entrants[row.entrant]), row.played, row.won, row.drawn, row.lost, row.for, row.against, row.difference, row.points];
            if (swiss) {
                cells.push(row.buchholz, row.byes);
            }
            if (king) {
                cells.push(row.titles);
            }
            return h('tr', { class: qualified && stage.index < this.current.config.stages.length - 1 ? 'qualified' : '' },
                cells.map((value, i) => (i === 1 ? h('th', { scope: 'row' }, String(value), abilityBadge(entrants[row.entrant], this.current.config.ability ?? null), row.best ? h('span', { class: 'muted small' }, t('tournament.table.best')) : null) : h('td', {}, String(value)))));
        });
        const name = serverText(table, 'name');
        return h('section', { class: 'cup-table' },
            h('h3', {}, name),
            h('div', { class: 'cup-table-scroll', tabindex: '0', 'aria-label': t('tournament.table.scroll.label', { name }) },
                h('table', {}, h('caption', { class: 'muted small' }, tableCaption(stage.format, settings.tiebreakers)),
                    h('thead', {}, h('tr', {}, head.map((name) => h('th', { scope: 'col' }, name)))),
                    h('tbody', {}, rows))),
            notes.length ? h('ul', { class: 'cup-tiebreaks small' }, notes) : null);
    }

    async act(action, message) {
        try {
            await tournamentsApi.action(this.current.id, action);
            this.app.hud.toast(message);
            await this.refresh();
        } catch (err) {
            this.app.hud.toast(err.message, 'error', 7000);
        }
    }

    // Deletes the open tournament, once its question has been answered, and gives the focus to
    // the list of tournaments.
    async remove() {
        const cup = this.current;
        try {
            await tournamentsApi.remove(cup.id);
            this.mode = 'empty';
            this.openId = null;
            this.current = null;
            await this.refresh();
            (this.listHost.querySelector('.cup-item') || this.root.querySelector('.cup-side-head button'))?.focus();
        } catch (err) {
            this.renderView();
            this.app.hud.toast(err.message, 'error');
        }
    }

    async playMatch(match) {
        const cup = this.current;
        const app = this.app;
        try {
            const entry = await tournamentsApi.action(cup.id, 'play', { key: match.key });
            const { PlayPage } = await import('./play.js');
            app.play = app.play || new PlayPage(app);
            const id = cup.id;
            app.play.begin(entry, match.persons, {
                label: t('tournament.play.label', { name: serverText(cup, 'name'), label: serverText(match, 'label') }),
                back: () => {
                    app.showPage('tournaments');
                    this.open(id);
                },
            });
            app.showPage('play');
        } catch (err) {
            app.hud.toast(err.status === 409 ? t('tournament.play.busy') : err.message, 'error', 7000);
        }
    }

    // The trophy ceremony, the podium and confetti of the show after a match, in the colors of the
    // champion, over the last match the champion played that has a recording.
    async ceremony() {
        const cup = this.current;
        const app = this.app;
        const champion = cup.champion_index;
        const played = cup.matches.filter((m) => m.result && m.result.match && !m.decider && (m.home === champion || m.away === champion));
        const last = played[played.length - 1];
        if (!last) {
            app.hud.toast(t('tournament.ceremony.none', { champion: serverText(cup, 'champion'), name: serverText(cup, 'name') }), 'info', 7000);
            return;
        }
        // A game of the Play page may still be the source, ended, quit or stopped, and its
        // scoreboard and live state would show while the recording loads, so they hide at once.
        const ended = app.source && app.source.live ? app.source : null;
        if (ended) {
            app.hud.hide();
            document.getElementById('app')?.classList.add('no-source');
        }
        await app.openMatch(last.result.match);
        if (ended && app.source === ended) {
            document.getElementById('app')?.classList.remove('no-source');
        }
        if (!app.timeline || !app.source) {
            return;
        }
        if (app.director.running) {
            app.director.stop(false);
        }
        app.timeline.seek(app.timeline.last);
        app.timeline.pause();
        if (typeof app.afterSeek === 'function') {
            app.afterSeek();
        }
        const runnerUp = cup.ranking && cup.ranking.length > 1 ? entrantName(cup.config.entrants[cup.ranking[1]]) : null;
        app.podium.show(null, {
            team: last.home === champion ? 0 : 1,
            title: serverText(cup, 'champion'),
            subtitle: runnerUp ? t('tournament.ceremony.subtitle.runnerUp', { name: serverText(cup, 'name'), runnerUp }) : t('tournament.ceremony.subtitle', { name: serverText(cup, 'name') }),
        });
    }

    // Watching without spoilers.

    // The switch of a tournament without spoilers and, while it is on, Watch next, the count of
    // the matches to watch, Reveal all, the autoplay of the next match and the predictions.
    spoilerBar(cup) {
        const on = spoilerFree(cup.id);
        const box = h('input', { type: 'checkbox', class: 'cup-spoiler-switch', role: 'switch', checked: on, 'aria-describedby': 'cup-spoiler-note' });
        box.addEventListener('change', async () => {
            setSpoilerFree(cup.id, box.checked);
            this.revealing = false;
            this.renderList();
            await this.load(cup.id);
            this.mainHost.querySelector('.cup-spoiler-switch')?.focus();
        });
        const parts = [h('label', { class: 'check' }, box, t('tournament.spoilers.switch'))];
        const spoilers = cup.spoilers || null;
        if (!on || !spoilers) {
            parts.push(h('span', { class: 'muted small', id: 'cup-spoiler-note' }, t('tournament.spoilers.note')));
            return h('div', { class: 'cup-spoilers', role: 'group', 'aria-label': t('tournament.spoilers.label') }, parts);
        }
        const next = spoilers.unseen.length ? this.matchMap.get(spoilers.unseen[0]) : null;
        parts.push(h('span', { class: 'small', id: 'cup-spoiler-note', role: 'status' },
            spoilers.hidden ? t('tournament.spoilers.hidden', { count: spoilers.hidden }) : t('tournament.spoilers.none')));
        if (next) {
            parts.push(h('button', { type: 'button', class: 'btn primary cup-watch-next', 'data-focus': 'watch-next', onclick: () => this.watchMatch(cup.id, next) }, icon('watch'), t('tournament.spoilers.next')));
        }
        const auto = h('input', { type: 'checkbox', class: 'cup-autoplay', checked: autoplay(cup.id) });
        auto.addEventListener('change', () => setAutoplay(cup.id, auto.checked));
        parts.push(h('label', { class: 'check small' }, auto, t('tournament.spoilers.autoplay')));
        if (spoilers.hidden) {
            parts.push(this.revealAllButton(cup));
        }
        const score = predictionScore(cup.id, cup.matches);
        if (score.scored) {
            parts.push(h('span', { class: 'small cup-prediction-score' }, icon('star', 'icon text-symbol'), t('tournament.predictions.score', { right: score.right, total: score.scored })));
        }
        return h('div', { class: 'cup-spoilers on', role: 'group', 'aria-label': t('tournament.spoilers.label') }, parts);
    }

    // Reveal all, which asks first in place of the button, as an award does.
    revealAllButton(cup) {
        if (!this.revealing) {
            return h('button', { type: 'button', class: 'btn small ghost', 'data-focus': 'reveal-all', onclick: () => {
                this.revealing = true;
                this.renderView();
                this.mainHost.querySelector('[data-focus="reveal-no"]')?.focus();
            } }, icon('eye'), t('tournament.spoilers.revealAll'));
        }
        const cancel = () => {
            this.revealing = false;
            this.renderView();
            this.mainHost.querySelector('[data-focus="reveal-all"]')?.focus();
        };
        const question = t('tournament.spoilers.revealAll.confirm', { count: cup.spoilers.hidden });
        return h('span', {
            class: 'cup-confirm', role: 'group', 'aria-label': question,
            onkeydown: (e) => {
                if (e.key === 'Escape') {
                    e.preventDefault();
                    e.stopPropagation();
                    cancel();
                }
            },
        }, h('span', { class: 'small' }, question),
        h('button', { type: 'button', class: 'btn small primary', 'data-focus': 'reveal-yes', onclick: async () => {
            this.revealing = false;
            // The matches revealed here join those watched in this visit, so the summary of what
            // the person missed lists them too.
            const seen = new Set(watchedKeys(cup.id));
            const fresh = (cup.spoilers.played || []).filter((key) => !seen.has(key));
            (this.session[cup.id] = this.session[cup.id] || []).push(...fresh);
            markWatched(cup.id, ...(cup.spoilers.played || []));
            await this.load(cup.id);
            this.app.hud.toast(t('tournament.spoilers.revealed.all'));
            this.mainHost.querySelector('.cup-spoiler-switch')?.focus();
        } }, icon('eye'), t('tournament.spoilers.revealAll.yes')),
        h('button', { type: 'button', class: 'btn small ghost', 'data-focus': 'reveal-no', ...symbolOnly(t('tournament.forfeit.no')), onclick: cancel }, icon('close')));
    }

    // Watch and Reveal for a played match that the person has not watched yet.
    unseenButtons(match) {
        const cup = this.current;
        const entrants = cup.config.entrants;
        const names = { label: serverText(match, 'label'), home: entrantName(entrants[match.home]), away: entrantName(entrants[match.away]) };
        return [
            match.unseen && match.unseen.match ? h('button', {
                type: 'button', class: 'btn small primary', 'data-focus': `unseen-watch-${match.key}`,
                ...symbolOnly(t('tournament.spoilers.watch.label', names)),
                onclick: () => this.watchMatch(cup.id, match),
            }, icon('watch')) : null,
            h('button', {
                type: 'button', class: 'btn small ghost', 'data-focus': `unseen-reveal-${match.key}`,
                ...symbolOnly(t('tournament.spoilers.reveal.label', names)),
                onclick: () => this.reveal(cup.id, match.key),
            }, icon('eye')),
        ];
    }

    // Watch next of a tournament from anywhere, as the palette offers it.
    async watchNextOf(id) {
        let entry;
        try {
            entry = await this.fetchCup(id);
        } catch (err) {
            this.app.hud.toast(err.message, 'error');
            return;
        }
        const key = entry.spoilers && entry.spoilers.unseen[0];
        const next = key ? entry.matches.find((m) => m.key === key) : null;
        if (next) {
            this.watchMatch(id, next);
        } else {
            this.app.hud.toast(t('tournament.spoilers.caughtUp.toast', { name: serverText(entry, 'name') }), 'info', 6000);
        }
    }

    // Marks a match watched on purpose and shows its result.
    async reveal(id, key) {
        markWatched(id, key);
        (this.session[id] = this.session[id] || []).push(key);
        await this.load(id);
        this.app.hud.toast(t('tournament.spoilers.revealed'));
    }

    // Plays a match that waits to be watched on Watch, which marks it watched at its end. A match
    // awarded without a recording reveals at once.
    watchMatch(id, match) {
        this.closeIntermission();
        if (!match || !match.unseen) {
            return;
        }
        if (!match.unseen.match) {
            this.reveal(id, match.key);
            return;
        }
        this.watching = { id, key: match.key, recording: match.unseen.match };
        this.app.openMatchInWatch(match.unseen.match);
    }

    // A recording that played to its end marks its match watched, when it is the one that Watch
    // next opened or a match of a tournament without spoilers, and shows the card of what follows.
    async recordingEnded(detail) {
        const cup = detail.provenance && detail.provenance.tournament;
        let id = null;
        let key = null;
        if (this.watching && detail.id === this.watching.recording) {
            ({ id, key } = this.watching);
        } else if (cup && typeof cup.id === 'string' && typeof cup.key === 'string' && spoilerFree(cup.id)) {
            ({ id, key } = cup);
        }
        this.watching = null;
        if (!id || !spoilerFree(id) || watchedKeys(id).includes(key)) {
            return;
        }
        markWatched(id, key);
        (this.session[id] = this.session[id] || []).push(key);
        let entry;
        try {
            entry = await this.fetchCup(id);
        } catch {
            return;
        }
        if (this.openId === id) {
            this.current = entry;
            this.renderView();
        }
        const next = entry.spoilers && entry.spoilers.unseen.length
            ? entry.matches.find((m) => m.key === entry.spoilers.unseen[0]) : null;
        if (next) {
            this.showIntermission(entry, next, autoplay(id));
        } else if (entry.spoilers && !entry.spoilers.hidden) {
            this.app.hud.toast(t('tournament.spoilers.caughtUp.toast', { name: serverText(entry, 'name') }), 'info', 6000);
        }
    }

    // The card between two matches on Watch, which names only who plays next, the final with a
    // card of its own, and with autoplay counts down to it. Play now, Escape and Cancel answer it.
    showIntermission(entry, next, counting) {
        this.closeIntermission();
        const host = document.getElementById('page-watch');
        if (!host || this.app.page !== 'watch') {
            return;
        }
        if (typeof this.app.releasePointer === 'function') {
            this.app.releasePointer();
        }
        const entrants = entry.config.entrants;
        const final = isFinal(next);
        const id = entry.id;
        // A timer reads its count when asked, so a screen reader is not told every second.
        const left = h('span', { class: 'cup-count small', role: 'timer' });
        let seconds = 10;
        const tick = () => {
            left.textContent = counting ? t('tournament.intermission.count', { count: seconds }) : '';
        };
        const play = h('button', { type: 'button', class: 'btn primary', onclick: () => this.watchMatch(id, next) }, icon('play'), t('tournament.intermission.play'));
        const card = h('section', {
            class: `cup-intermission${final ? ' final' : ''}`, 'aria-labelledby': 'cup-intermission-title',
            onkeydown: (e) => {
                if (e.key === 'Escape') {
                    e.preventDefault();
                    e.stopPropagation();
                    this.closeIntermission();
                }
            },
        },
        h('h2', { id: 'cup-intermission-title' }, final ? icon('trophy', 'icon text-symbol') : null,
            final ? t('tournament.intermission.final') : t('tournament.intermission.next')),
        h('p', { class: 'cup-intermission-stage small muted' }, `${serverText(entry, 'name')}, ${serverText(next, 'label')}`),
        h('p', { class: 'cup-intermission-sides' },
            this.kickoffSide(entrants[next.home], 0), h('span', { class: 'cup-versus' }, t('tournament.intermission.versus')), this.kickoffSide(entrants[next.away], 1, entrants[next.home])),
        left,
        h('div', { class: 'row' }, play,
            h('button', { type: 'button', class: 'btn ghost', onclick: () => this.closeIntermission() }, icon('close'), t('tournament.intermission.cancel'))));
        tick();
        const before = document.activeElement;
        host.append(card);
        this.intermission = { card, timer: null, before };
        if (counting) {
            this.intermission.timer = setInterval(() => {
                // A person who left Watch keeps the next match from starting there.
                if (this.app.page !== 'watch') {
                    this.closeIntermission();
                    return;
                }
                seconds -= 1;
                tick();
                if (seconds <= 0) {
                    this.watchMatch(id, next);
                }
            }, 1000);
        }
        play.focus({ preventScroll: true });
    }

    // Closes the card between matches. A card that held the focus gives it back to where it was
    // before the card opened, else to the play button of Watch.
    closeIntermission() {
        if (!this.intermission) {
            return;
        }
        const { card, timer, before } = this.intermission;
        const held = card.contains(document.activeElement);
        clearInterval(timer);
        card.remove();
        this.intermission = null;
        if (held) {
            const back = before && before.isConnected && before !== document.body ? before : document.getElementById('btn-play');
            back?.focus({ preventScroll: true });
        }
    }

    // A side of a kickoff card, the kit of its team or a mark of its color, and its name. Two
    // entrants of one team meet with the away side in its away kit, as in the match.
    kickoffSide(entrant, index, other = null) {
        const team = entrant ? this.teams.find((x) => x.id === entrant.team) : null;
        const away = index === 1 && !!entrant && !!other && entrant.team === other.team;
        const color = (away ? entrant && entrant.secondary : entrant && entrant.color) || [128, 128, 128];
        return h('span', { class: `cup-kickoff-side${away ? ' away' : ''}` },
            team ? kitShirt(away ? awayTeam(team) : team, index) : entrant ? h('span', { class: 'cup-dot', style: `background: rgb(${color.join(',')})`, 'aria-hidden': 'true' }) : null,
            h('span', {}, entrantName(entrant)));
    }

    // The next matches of the tournament as kickoff cards, those to watch first, each naming who
    // plays, the final with a card of its own, and the prediction of its result.
    upNextBox(cup) {
        const next = upNext(cup, 4);
        if (!next.length) {
            return null;
        }
        const entrants = cup.config.entrants;
        const cards = next.map((m) => {
            const final = isFinal(m);
            const pick = prediction(cup.id, m.key);
            const choose = (side, words) => h('button', {
                type: 'button', class: `btn small${pick === side ? ' primary' : ' ghost'}`, 'aria-pressed': pick === side ? 'true' : 'false',
                'data-focus': `predict-${m.key}-${side}`,
                onclick: () => {
                    predict(cup.id, m.key, pick === side ? null : side);
                    this.renderView();
                },
            }, words);
            return h('li', { class: `cup-kickoff${final ? ' final' : ''}` },
                // The label of a final names it already, beside the symbol of the trophy.
                h('p', { class: 'cup-kickoff-label small muted' }, final ? icon('trophy', 'icon text-symbol') : null, serverText(m, 'label')),
                h('p', { class: 'cup-kickoff-sides' }, this.kickoffSide(entrants[m.home], 0), h('span', { class: 'cup-versus' }, t('tournament.intermission.versus')), this.kickoffSide(entrants[m.away], 1, entrants[m.home])),
                h('p', { class: 'small muted' }, STATE_NAMES[m.state] || ''),
                h('div', { class: 'cup-predict row', role: 'group', 'aria-label': t('tournament.predictions.label', { label: serverText(m, 'label') }) },
                    choose('home', entrantName(entrants[m.home])), choose('draw', t('tournament.predictions.draw')), choose('away', entrantName(entrants[m.away]))),
                m.state === 'unseen' ? h('span', { class: 'row' }, this.unseenButtons(m)) : null);
        });
        return h('section', { class: 'cup-up-next', 'aria-labelledby': 'cup-up-next-title' },
            h('h3', { id: 'cup-up-next-title' }, t('tournament.upNext.title')),
            h('ol', { class: 'cup-kickoffs' }, cards));
    }

    // Once the person has watched every played match, the results of those watched in this visit,
    // what they missed. The score of the predictions shows once, in the bar of spoilers above.
    caughtUp(cup) {
        const watchedNow = this.session[cup.id] || [];
        if (!spoilerFree(cup.id) || !cup.spoilers || cup.spoilers.hidden || !watchedNow.length) {
            return null;
        }
        const entrants = cup.config.entrants;
        const results = watchedNow.map((key) => this.matchMap.get(key)).filter((m) => m && m.result && Array.isArray(m.result.score));
        return h('section', { class: 'cup-caught-up notice', 'aria-labelledby': 'cup-caught-up-title' },
            h('h3', { id: 'cup-caught-up-title' }, icon('done', 'icon text-symbol'), t('tournament.caughtUp.title')),
            h('ul', {}, results.map((m) => h('li', {}, t('tournament.caughtUp.result', {
                label: serverText(m, 'label'), home: entrantName(entrants[m.home]), away: entrantName(entrants[m.away]), left: m.result.score[0], right: m.result.score[1],
            })))),
            h('button', { type: 'button', class: 'btn small ghost', 'data-focus': 'caught-up-close', onclick: () => {
                delete this.session[cup.id];
                this.renderView();
            } }, icon('close'), t('tournament.caughtUp.close')));
    }

    // The Brackets view.

    // Opens the brackets, groups and tables of a tournament large, in a view of their own.
    async openBrackets(id) {
        this.mode = 'brackets';
        this.openId = id;
        this.stageTab = null;
        this.renderList();
        await this.load(id);
        this.mainHost.querySelector('h2')?.focus();
    }

    closeBrackets() {
        this.mode = 'view';
        this.root.querySelector('.cup-layout')?.classList.remove('brackets');
        this.renderList();
        this.renderView();
        this.mainHost.querySelector('[data-focus="act-brackets"]')?.focus();
    }

    renderBrackets() {
        const cup = this.current;
        this.matchMap = new Map(cup.matches.map((m) => [m.key, m]));
        if (this.stageTab === null || this.stageTab >= cup.stages_view.length) {
            const playing = cup.stages_view.findIndex((s) => s.state !== 'done');
            this.stageTab = playing >= 0 ? playing : cup.stages_view.length - 1;
        }
        this.root.querySelector('.cup-layout')?.classList.add('brackets');
        const zoomTo = (value) => {
            this.zoom = Math.max(0.5, Math.min(2, Math.round(value * 10) / 10));
            this.renderView();
        };
        const tabs = h('div', { class: 'cup-tabs', role: 'tablist', 'aria-label': t('tournament.view.stages.label') }, cup.stages_view.map((stage, index) => h('button', {
            type: 'button', role: 'tab', id: `cup-tab-${index}`, 'aria-selected': index === this.stageTab ? 'true' : 'false',
            tabindex: index === this.stageTab ? '0' : '-1', class: `cup-tab${index === this.stageTab ? ' active' : ''}`, 'aria-controls': 'cup-stage-panel',
            onclick: () => {
                this.stageTab = index;
                this.renderView();
                document.getElementById(`cup-tab-${index}`)?.focus();
            },
            onkeydown: (e) => {
                const by = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
                if (by) {
                    e.preventDefault();
                    this.stageTab = (index + by + cup.stages_view.length) % cup.stages_view.length;
                    this.renderView();
                    document.getElementById(`cup-tab-${this.stageTab}`)?.focus();
                }
            },
        }, serverText(stage, 'name'))));
        const stage = cup.stages_view[this.stageTab];
        const zoom = h('div', { class: 'cup-zoom row', role: 'group', 'aria-label': t('tournament.brackets.zoom.label') },
            h('button', { type: 'button', class: 'btn small ghost', 'data-focus': 'zoom-out', disabled: this.zoom <= 0.5, ...symbolOnly(t('tournament.brackets.zoom.out')), onclick: () => zoomTo(this.zoom - 0.1) }, icon('minus')),
            h('output', { class: 'small', 'aria-live': 'polite' }, t('tournament.brackets.zoom.value', { percent: Math.round(this.zoom * 100) })),
            h('button', { type: 'button', class: 'btn small ghost', 'data-focus': 'zoom-in', disabled: this.zoom >= 2, ...symbolOnly(t('tournament.brackets.zoom.in')), onclick: () => zoomTo(this.zoom + 0.1) }, icon('plus')),
            h('button', { type: 'button', class: 'btn small ghost', 'data-focus': 'zoom-reset', ...symbolOnly(t('tournament.brackets.zoom.reset')), onclick: () => zoomTo(1) }, icon('reset')));
        const head = h('header', { class: 'cup-head cup-brackets-head' },
            h('h2', { tabindex: '-1', 'data-focus': 'cup-title' }, t('tournament.brackets.title', { name: serverText(cup, 'name') })),
            h('div', { class: 'row' },
                h('button', { type: 'button', class: 'btn ghost', 'data-focus': 'brackets-back', onclick: () => this.closeBrackets() }, icon('back'), t('tournament.brackets.back')),
                zoom,
                spoilerFree(cup.id) && cup.spoilers && cup.spoilers.unseen.length
                    ? h('button', { type: 'button', class: 'btn primary cup-watch-next', 'data-focus': 'watch-next', onclick: () => this.watchMatch(cup.id, this.matchMap.get(cup.spoilers.unseen[0])) }, icon('watch'), t('tournament.spoilers.next'))
                    : null),
            spoilerFree(cup.id) ? h('p', { class: 'muted small' }, icon('eye', 'icon text-symbol'), t('tournament.spoilers.listed')) : null);
        const panel = h('div', { class: 'cup-stage-view cup-big', id: 'cup-stage-panel', role: 'tabpanel', 'aria-labelledby': `cup-tab-${this.stageTab}`, style: `--cup-zoom: ${this.zoom}` },
            this.stageView(stage, cup.config.stages[this.stageTab]));
        const focused = document.activeElement && this.mainHost.contains(document.activeElement) ? document.activeElement : null;
        // An action that took the focus with it, such as a confirmed award, names where it was.
        const focusKey = focused ? (focused.id || focused.dataset.focus || null) : this.focusAfter || null;
        const byId = !!focused && focusKey === focused.id;
        this.focusAfter = null;
        const scroll = this.mainHost.scrollTop;
        this.mainHost.replaceChildren(h('div', { class: 'cup-view cup-brackets' }, head, tabs, panel));
        this.mainHost.scrollTop = scroll;
        if (focusKey) {
            this.refocus(focusKey, byId);
        }
    }

    // Live progress, and a notice when a match of a person is ready.
    async poll() {
        if (document.hidden || document.body.classList.contains('offline')) {
            return;
        }
        const busy = this.list.some((cup) => cup.state === 'running');
        if (!this.visible && (!busy || !this.primed)) {
            if (!this.primed) {
                this.primed = true;
                try {
                    this.list = await tournamentsApi.list();
                } catch {
                    // The server is away, the next poll tries again.
                }
            }
            return;
        }
        let list;
        try {
            list = await tournamentsApi.list();
        } catch {
            return;
        }
        for (const cup of list) {
            const key = `${cup.id}|${cup.people_waiting}`;
            if (cup.people_waiting && cup.state === 'running' && !this.announced.has(key)) {
                this.announced.add(key);
                this.app.hud.toast(t(this.visible ? 'tournament.toast.person' : 'tournament.toast.person.away', { name: serverText(cup, 'name') }), 'info', 6000);
            }
            const old = this.list.find((x) => x.id === cup.id);
            if (old && old.state !== 'done' && cup.state === 'done' && !spoilerFree(cup.id)) {
                this.app.hud.toast(t('tournament.toast.won', { name: serverText(cup, 'name'), champion: serverText(cup, 'champion') }), 'info', 7000);
            }
        }
        const changed = JSON.stringify(list) !== JSON.stringify(this.list);
        this.list = list;
        if (!this.visible || !this.built) {
            return;
        }
        if (changed) {
            this.renderList();
        }
        if ((this.mode === 'view' || this.mode === 'brackets') && this.openId) {
            const summary = list.find((cup) => cup.id === this.openId);
            if (summary && (changed || summary.running) && !this.mainHost.contains(document.activeElement?.closest('input, select, textarea'))) {
                await this.load(this.openId);
            }
        }
    }
}
