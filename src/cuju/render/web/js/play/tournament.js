// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The Tournaments page. A list of tournaments sits beside the open one, which shows its stages as
// brackets, tables and fixtures with results, the matches of people ready to play, and the trophy
// ceremony at the end. New tournament opens a wizard of five steps, the format, the entrants, the
// settings, every setting of every stage in the advanced editor, and a review of the draw.

import { api } from '../core/api.js';
import { formatNumber, serverText, t, tn, tOr } from '../core/i18n.js';
import { kitShirt } from '../pages/matches.js';
import { el as h } from '../core/menu.js';
import { icon, stateBadge, symbolOnly } from '../core/icons.js';
import { listedScenarios, scenarioName, scenarioText } from '../core/scenarios.js';
import {
    DECIDED_NAMES, FORMAT_NAMES, NAME_LONGEST, SECTION_NAMES, SETTLE_NAMES, STATE_NAMES, TIEBREAK_NAMES,
    bracketLayout, entrantName, fixtureMatches, fixtureState, formatsText, freeName, isBracket, isFinal, nameKey,
    progressShare, sections, shownAbility, sideName, stageNameText, stageText, tiebreakText, upNext,
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
        const error = new Error((body && body.error && serverText(body, 'error')) || t('tournament.api.status', { status: res.status }));
        error.status = res.status;
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
    { key: 'seeding', label: t('tournament.field.seeding'), type: 'select', options: [['standing', t('tournament.field.seeding.standing')], ['random', RANDOM_SEEDING], ['rating', t('tournament.field.seeding.rating')]], formats: ALL, later: true },
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
        setInterval(() => this.poll(), 1500);
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
        this.mainHost = h('section', { class: 'cup-main', 'aria-live': 'polite', 'aria-busy': 'false' });
        const side = h('aside', { class: 'cup-side', 'aria-labelledby': 'cup-list-title' },
            h('header', { class: 'cup-side-head' },
                h('h1', { id: 'cup-list-title' }, t('tournament.list.title')),
                h('button', { type: 'button', class: 'btn primary', onclick: () => this.startWizard() }, icon('plus'), t('tournament.new'))),
            this.listHost);
        this.root.replaceChildren(h('div', { class: 'cup-layout' }, side, this.mainHost));
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
            cup.people_waiting ? h('span', { class: 'cup-item-people' }, t('tournament.list.people', { count: cup.people_waiting })) : null,
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
        this.renderList();
        this.renderWizard();
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
        draft.stages = clone(config.stages || draft.stages).map((stage) => {
            const own = {};
            for (const [key, value] of Object.entries(stage)) {
                if (key in STAGE_DEFAULTS) {
                    own[key] = value;
                }
            }
            return own;
        });
        draft.entrants = (config.entrants || []).map((e) => {
            const entry = { kind: e.kind, name: e.name_id ? undefined : e.name, ability: e.ability ?? null };
            if (e.kind === 'team') {
                entry.team = e.team;
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
        panel.append(...[body].flat());
        const nav = h('div', { class: 'cup-nav' },
            h('button', { type: 'button', class: 'btn ghost', ...symbolOnly(t('tournament.wizard.cancel')), onclick: () => this.cancelWizard() }, icon('close')),
            h('span', { class: 'cup-nav-gap' }),
            this.step > 0 ? h('button', { type: 'button', class: 'btn', ...symbolOnly(t('tournament.wizard.back')), onclick: () => this.goStep(this.step - 1) }, icon('back')) : null,
            this.step < STEPS.length - 1
                ? h('button', { type: 'button', class: 'btn primary', ...symbolOnly(t('tournament.wizard.next')), onclick: () => this.goStep(this.step + 1) }, icon('next'))
                : h('button', { type: 'button', class: 'btn primary cup-start', onclick: (e) => this.create(e.currentTarget) }, icon('play'), t('tournament.wizard.start')));
        this.mainHost.replaceChildren(h('div', { class: 'cup-wizard' },
            h('header', { class: 'cup-head' }, h('h2', {}, t('tournament.new')),
                h('p', { class: 'muted' }, tn('tournament.wizard.text'))),
            tabs, panel, nav));
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

    goStep(index) {
        this.step = index;
        const focusTab = document.activeElement && document.activeElement.classList.contains('cup-step');
        this.renderWizard();
        if (focusTab) {
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
        const choose = (name) => {
            const preset = this.presets[name];
            const draft = this.draft;
            draft.preset = name;
            draft.seeding = preset.seeding || 'random';
            draft.defaults = clone(preset.defaults || {});
            draft.stages = clone(preset.stages);
            if (preset.concurrency) {
                draft.concurrency = preset.concurrency;
            }
            if ('ability' in preset) {
                draft.ability = preset.ability ?? null;
            }
            if (!draft.name || Object.entries(this.presets).some(([key, p]) => presetTitle(key, p) === draft.name)) {
                draft.name = presetTitle(name, preset);
            }
            this.renderWizard();
            this.mainHost.querySelector(`[data-preset="${name}"]`)?.focus();
        };
        const cards = entries.map(([name, preset]) => {
            const on = this.draft.preset === name;
            return h('div', { class: `cup-preset${on ? ' active' : ''}` },
                h('button', {
                    type: 'button', class: 'cup-preset-pick', role: 'radio', 'aria-checked': on ? 'true' : 'false', 'data-preset': name,
                    onclick: () => choose(name),
                },
                h('span', { class: 'cup-preset-title' }, presetTitle(name, preset)),
                h('span', { class: 'cup-preset-text muted small' }, presetDescription(name, preset) || preset.stages.map(stageText).join(COMMA_THEN)),
                h('span', { class: 'cup-preset-stages small' }, formatsText(preset.stages))),
                preset.shipped ? null : h('button', {
                    type: 'button', class: 'btn small ghost danger', 'aria-label': t('tournament.formatStep.delete.label', { title: preset.title }),
                    onclick: async () => {
                        try {
                            await tournamentsApi.removePreset(name);
                            delete this.presets[name];
                            this.renderWizard();
                        } catch (err) {
                            this.app.hud.toast(err.message, 'error');
                        }
                    },
                }, icon('trash'), t('tournament.formatStep.delete')));
        });
        return [
            h('p', { class: 'muted' }, tn('tournament.formatStep.intro')),
            h('div', { class: 'cup-presets', role: 'radiogroup', 'aria-label': t('tournament.formatStep.label') }, cards),
        ];
    }

    entrantsStep() {
        const d = this.draft;
        const teams = this.teams.filter((x) => x.kind !== 'builtin');
        const teamSelect = h('select', { 'aria-label': t('tournament.entrants.team.label') },
            teams.length ? teams.map((x) => h('option', { value: x.id }, t(x.format === '5v5' ? 'tournament.entrants.team.five' : 'tournament.entrants.team.eleven', { name: x.name }))) : h('option', { value: '' }, t('tournament.entrants.team.none')));
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
        const addTeam = (id) => {
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
                h('button', { type: 'button', class: 'btn ghost', disabled: !teams.length, onclick: () => {
                    const have = new Set(d.entrants.filter((e) => e.kind === 'team').map((e) => e.team));
                    for (const x of teams.filter((team) => !have.has(team.id))) {
                        const taken = this.takenNames();
                        d.entrants.push(taken.has(nameKey(x.name)) ? { kind: 'team', team: x.id, name: freeName(x.name, taken) } : { kind: 'team', team: x.id });
                    }
                    this.renderWizard();
                } }, icon('plus'), t('tournament.entrants.team.addAll'))),
            h('div', { class: 'cup-adder' }, h('label', { class: 'field' }, t('tournament.entrants.builtin'), ability),
                h('button', { type: 'button', class: 'btn', ...symbolOnly(t('tournament.entrants.builtin.add')), onclick: () => {
                    const value = Number(ability.value);
                    if (!(value >= 0 && value <= 1)) {
                        this.app.hud.toast(t('tournament.entrants.builtin.range'), 'error');
                        return;
                    }
                    add({ kind: 'builtin', ability: Math.round(value * 10000) / 10000 });
                } }, icon('plus')),
                h('button', { type: 'button', class: 'btn ghost', onclick: () => {
                    [0.2, 0.4, 0.6, 0.8].forEach((v) => d.entrants.push({ kind: 'builtin', ability: v }));
                    this.renderWizard();
                } }, icon('plus'), t('tournament.entrants.builtin.addFour'))),
            h('div', { class: 'cup-adder' }, h('label', { class: 'field' }, t('tournament.entrants.person'), person),
                h('button', { type: 'button', class: 'btn', ...symbolOnly(t('tournament.entrants.person.add')), onclick: () => {
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
        });
        const abilityField = h('label', { class: 'field small-field' }, t('tournament.entrant.ability'), ability);
        if (entry.kind === 'person') {
            const dynamic = this.teams.filter((x) => x.kind !== 'builtin' && x.control && x.control.assignment === 'dynamic');
            const mates = h('select', { 'aria-label': t('tournament.entrant.teammates.label', { number }) },
                h('option', { value: 'builtin' }, t('tournament.entrant.builtin')), dynamic.map((x) => h('option', { value: x.id }, x.name)));
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
            this.mainHost.querySelectorAll('.cup-entrants > li')[to]?.querySelector(by < 0 ? '.cup-up' : '.cup-down')?.focus();
        };
        return h('li', { class: 'cup-entrant' },
            team ? kitShirt(team, 0) : h('span', { class: `cup-kind ${entry.kind}`, 'aria-hidden': 'true' }, entry.kind === 'person' ? t('tournament.entrant.glyph.person') : t('tournament.entrant.glyph.builtin')),
            h('span', { class: 'cup-entrant-kind small muted' }, team ? t('tournament.entrant.teamKind', { kind: KIND_NAMES.team, name: team.name }) : KIND_NAMES[entry.kind]),
            h('span', { class: 'cup-entrant-name' }, h('label', { class: 'field' }, h('span', {}, icon('edit', 'icon text-symbol'), t('tournament.entrants.name')), name), note), ...extra,
            h('label', { class: 'field small-field' }, t('tournament.entrant.rating'), rating),
            h('span', { class: 'cup-entrant-actions' },
                h('button', { type: 'button', class: 'btn small ghost cup-up', ...symbolOnly(t('tournament.entrant.up.label', { number })), disabled: index === 0, onclick: () => move(-1) }, icon('up')),
                h('button', { type: 'button', class: 'btn small ghost cup-down', ...symbolOnly(t('tournament.entrant.down.label', { number })), disabled: index === d.entrants.length - 1, onclick: () => move(1) }, icon('down')),
                h('button', { type: 'button', class: 'btn small ghost danger', ...symbolOnly(t('tournament.entrant.remove.label', { number })), onclick: () => {
                    d.entrants.splice(index, 1);
                    this.renderWizard();
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
        this.mainHost.querySelectorAll('.cup-entrants > li').forEach((row, index) => {
            const input = row.querySelector('.cup-entrant-name input');
            const note = row.querySelector('.cup-name-note');
            if (!input || !note) {
                return;
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
        const seeding = this.select([['random', RANDOM_SEEDING], ['manual', t('tournament.seeding.manual')], ['rating', t('tournament.seeding.rating')]], d.seeding, t('tournament.settings.seeding'), (v) => {
            d.seeding = v;
        });
        const concurrency = h('input', { type: 'number', min: '1', max: '8', step: '1', value: String(d.concurrency), 'aria-label': t('tournament.settings.concurrency.label') });
        concurrency.addEventListener('input', () => {
            d.concurrency = Number(concurrency.value);
        });
        const forfeit = h('input', { type: 'number', min: '1', max: '10', step: '1', value: String(d.forfeit_score), 'aria-label': t('tournament.settings.forfeit.label') });
        forfeit.addEventListener('input', () => {
            d.forfeit_score = Number(forfeit.value);
        });
        const defaults = d.defaults;
        const scenario = this.scenarioSelect(defaults.scenario ?? null, t('tournament.settings.scenario'), BY_ENTRANTS, (v) => {
            if (v === null) {
                delete defaults.scenario;
            } else {
                defaults.scenario = v;
            }
        });
        const length = this.optionalNumber({ key: 'length', min: 50, max: 5000, step: 50, initial: 600, off: OFF_SCENARIO, label: t('tournament.field.length') }, defaults.length ?? null, (v) => {
            if (v === null) {
                delete defaults.length;
            } else {
                defaults.length = v;
            }
        });
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
        const box = h('input', { type: 'checkbox', class: 'cup-standard-set', checked: on, 'aria-label': t('tournament.optional.set.label', { label: label.toLowerCase() }) });
        const range = h('input', { type: 'range', class: 'cup-standard-range', min: '0', max: '1', step: '0.05', value: String(on ? d.ability : 0.5), disabled: !on, 'aria-label': label });
        const shown = h('output', { class: 'ability-value' });
        const show = () => {
            shown.textContent = box.checked ? abilityText(d.ability) : OFF_SCENARIO;
            range.setAttribute('aria-valuetext', shown.textContent);
        };
        const sync = () => {
            range.disabled = !box.checked;
            d.ability = box.checked ? Math.round(Number(range.value) * 10000) / 10000 : null;
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
        const box = h('input', { type: 'checkbox', checked: on, 'aria-label': t('tournament.optional.set.label', { label: field.label.toLowerCase() }) });
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
        const applied = h('p', { class: 'muted small', role: 'status' });
        const apply = h('button', { type: 'button', class: 'btn', ...symbolOnly(t('tournament.json.apply')), onclick: () => {
            try {
                const value = JSON.parse(json.value);
                if (!value || !Array.isArray(value.stages)) {
                    throw new Error(t('tournament.json.expected'));
                }
                d.stages = value.stages;
                d.defaults = value.defaults || {};
                d.ability = value.ability ?? null;
                this.renderWizard();
                this.app.hud.toast(t('tournament.json.applied'));
            } catch (err) {
                applied.textContent = t('tournament.json.failed', { reason: err.message });
            }
        } }, icon('check'));
        return [
            h('p', { class: 'muted' }, tn('tournament.stages.intro')),
            h('div', { class: 'cup-form' }, this.standardControl()),
            h('div', { class: 'cup-stages' }, stages),
            h('button', { type: 'button', class: 'btn', disabled: d.stages.length >= 8, ...symbolOnly(t('tournament.stages.add')), onclick: () => {
                d.stages.push({ format: 'knockout', name: '' });
                this.renderWizard();
            } }, icon('plus')),
            h('details', { class: 'cup-json-box' }, h('summary', {}, t('tournament.json.edit')), json, h('div', { class: 'row' }, apply), applied),
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
        const move = (by) => {
            const to = index + by;
            [d.stages[index], d.stages[to]] = [d.stages[to], d.stages[index]];
            this.renderWizard();
        };
        return h('fieldset', { class: 'cup-stage' },
            h('legend', {}, t('tournament.stage.legend', { number: index + 1, format: FORMAT_NAMES[format] || format })),
            h('div', { class: 'cup-stage-fields' }, rows),
            h('div', { class: 'row' },
                h('button', { type: 'button', class: 'btn small ghost', disabled: index === 0, ...symbolOnly(t('tournament.stage.earlier')), onclick: () => move(-1) }, icon('up')),
                h('button', { type: 'button', class: 'btn small ghost', disabled: last, ...symbolOnly(t('tournament.stage.later')), onclick: () => move(1) }, icon('down')),
                h('button', { type: 'button', class: 'btn small ghost danger', disabled: d.stages.length === 1, ...symbolOnly(t('tournament.stage.remove')), onclick: () => {
                    d.stages.splice(index, 1);
                    this.renderWizard();
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
            control = this.orderControl(field, value, set, label);
        }
        return h('div', { class: 'field cup-field' }, h('span', { class: 'cup-field-label' }, field.label), control,
            field.help ? h('span', { class: 'muted small' }, field.help) : null);
    }

    // An ordered choice, such as the tiebreakers, each option on or off with buttons to move it.
    orderControl(field, value, set, label) {
        const chosen = (value || []).filter((v) => field.options.includes(v));
        // Lots always decide last, so they stay at the end of the list.
        const order = [...chosen, ...field.options.filter((v) => !chosen.includes(v))].filter((v) => v !== 'lots');
        if (field.options.includes('lots')) {
            order.push('lots');
        }
        const list = h('ol', { class: 'cup-order', 'aria-label': label });
        const draw = (focus = null) => {
            list.replaceChildren(...order.map((name, i) => {
                const on = chosen.includes(name);
                const box = h('input', { type: 'checkbox', checked: on || name === 'lots', disabled: name === 'lots', 'aria-label': t('tournament.order.use.label', { name: field.names[name] }) });
                box.addEventListener('change', () => {
                    if (box.checked) {
                        chosen.push(name);
                    } else {
                        chosen.splice(chosen.indexOf(name), 1);
                    }
                    commit();
                });
                const up = name === 'lots' ? null : h('button', { type: 'button', class: 'btn small ghost', disabled: i === 0, ...symbolOnly(t('tournament.order.earlier.label', { name: field.names[name] })), onclick: () => {
                    [order[i - 1], order[i]] = [order[i], order[i - 1]];
                    commit();
                    draw(`up-${name}`);
                } }, icon('up'));
                if (up) {
                    up.dataset.focus = `up-${name}`;
                }
                return h('li', { class: on ? '' : 'off' }, h('label', { class: 'check' }, box, field.names[name]), up);
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
        const host = h('div', { class: 'cup-review', 'aria-busy': 'true' }, h('p', { class: 'muted' }, t('tournament.review.checking')));
        const saveName = h('input', { type: 'text', placeholder: t('tournament.review.presetName.placeholder'), pattern: '[a-z0-9][a-z0-9_-]*', 'aria-label': t('tournament.review.presetName.label') });
        const saveTitle = h('input', { type: 'text', maxlength: '60', placeholder: t('tournament.review.presetTitle.placeholder'), value: this.draft.name, 'aria-label': t('tournament.review.presetTitle.label') });
        const save = h('div', { class: 'cup-save' },
            h('h3', {}, t('tournament.review.save.title')),
            h('div', { class: 'row' }, saveName, saveTitle, h('button', { type: 'button', class: 'btn', ...symbolOnly(t('tournament.review.save')), onclick: () => this.savePreset(saveName.value.trim(), saveTitle.value.trim()) }, icon('save'))));
        const clashes = this.nameClashes();
        if (clashes.length) {
            // Two entrants that share a name go back to the entrants step, before any check.
            host.setAttribute('aria-busy', 'false');
            host.replaceChildren(h('div', { class: 'notice error', role: 'alert' },
                h('ul', { class: 'symbol-list' }, clashes.map((clash) => h('li', {}, icon('warning', 'icon text-symbol'), t('tournament.review.nameTaken', { number: clash.index + 1, name: clash.name, other: clash.other + 1 })))),
                h('p', { class: 'muted small' }, t('tournament.review.names'))));
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
            host.replaceChildren(h('div', { class: 'notice error', role: 'alert' }, h('p', {}, err.message),
                h('p', { class: 'muted small' }, tn('tournament.review.failed'))));
        }
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
            this.current = entry;
            this.renderView();
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
        if (cup.state === 'running') {
            actions.push(h('button', { type: 'button', class: 'btn ghost danger', 'data-focus': 'act-cancel', ...symbolOnly(t('tournament.view.cancel')), onclick: () => this.act('cancel', t('tournament.view.cancelled')) }, icon('stop')));
        }
        if (cup.state === 'stopped') {
            actions.push(h('button', { type: 'button', class: 'btn primary', 'data-focus': 'act-resume', ...symbolOnly(t('tournament.view.resume')), onclick: () => this.act('resume', t('tournament.view.resumed')) }, icon('play')));
        }
        // Without spoilers, the ceremony waits until the person has watched the champion win.
        if (cup.state === 'done' && cup.champion_index !== null && cup.champion_index !== undefined) {
            actions.push(h('button', { type: 'button', class: 'btn primary', 'data-focus': 'act-ceremony', ...symbolOnly(t('tournament.view.ceremony')), onclick: () => this.ceremony() }, icon('trophy')));
        }
        actions.push(h('button', { type: 'button', class: 'btn ghost', 'data-focus': 'act-brackets', onclick: () => this.openBrackets(cup.id) }, icon('grid'), t('tournament.brackets.open')));
        actions.push(h('button', { type: 'button', class: 'btn ghost', ...symbolOnly(t('tournament.view.again')), onclick: () => {
            const config = clone(cup.config);
            this.startWizard(config);
            this.draft.seed = '';
        } }, icon('replay')));
        if (cup.state !== 'running') {
            actions.push(h('button', { type: 'button', class: 'btn ghost danger', 'data-focus': 'act-delete', onclick: () => this.remove() }, icon('trash'), t('tournament.view.delete')));
        }
        const head = h('header', { class: 'cup-head' },
            h('h2', { tabindex: '-1' }, serverText(cup, 'name')),
            h('p', { class: 'cup-meta' },
                stateBadge(cup.state, STATE_LABELS[cup.state] || cup.state, `state-pill ${cup.state === 'running' ? 'running' : cup.state === 'done' ? 'done' : 'failed'}`),
                h('span', {}, t('tournament.count.entrants', { count: entrants.length })),
                h('span', {}, t('tournament.view.seed', { seed: cup.seed })),
                h('span', { class: 'cup-view-ability' }, standardText(cup.config.ability ?? null)),
                h('span', {}, t('tournament.view.played', { count: cup.played, total: cup.scheduled })),
                cup.running ? h('span', {}, t('tournament.view.running', { count: cup.running })) : null),
            cup.state === 'running' ? h('div', { class: 'progress', role: 'progressbar', 'aria-label': t('tournament.view.progress.label'), 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round(share * 100)) },
                h('div', { class: 'bar', style: `width:${Math.round(share * 100)}%` })) : null,
            cup.champion ? h('p', { class: 'cup-champion' }, h('span', {}, t('tournament.view.champion', { name: serverText(cup, 'champion') }))) : null,
            cup.error ? h('div', { class: 'notice error', role: 'alert' }, h('p', {}, serverText(cup, 'error')), this.failedAwards(cup)) : null,
            cup.persistence_error ? h('div', { class: 'notice error' }, h('p', {}, serverText(cup, 'persistence_error'))) : null,
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
                        h('button', { type: 'button', class: 'btn small primary', 'data-focus': `people-${m.key}`, disabled: cup.state !== 'running', ...symbolOnly(t('tournament.play')), onclick: () => this.playMatch(m) }, icon('play')),
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
        const focusKey = focused ? (focused.id || focused.dataset.focus || null) : null;
        const byId = focusKey && focused.id === focusKey;
        const scroll = this.mainHost.scrollTop;
        this.mainHost.replaceChildren(h('div', { class: 'cup-view' }, head, this.caughtUp(cup), peopleBox, this.upNextBox(cup), tabs, panel, ranking));
        this.mainHost.scrollTop = scroll;
        if (focusKey) {
            (byId ? document.getElementById(focusKey) : this.mainHost.querySelector(`[data-focus="${CSS.escape(focusKey)}"]`))?.focus();
        }
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
            stage.state === 'waiting' ? t('tournament.stage.waiting') : null,
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
            style: `grid-template-columns: repeat(${layout.columns}, minmax(190px, 1fr)); grid-template-rows: auto repeat(${layout.rows}, minmax(32px, auto));`,
        });
        const name = SECTION_NAMES[section.name] || section.name;
        const titled = !(section.rounds.length === 1 && serverText(section.rounds[0], 'name') === name);
        section.rounds.forEach((round, column) => {
            if (titled) {
                grid.append(h('div', { class: 'cup-bracket-round', role: 'presentation', style: `grid-column:${column + 1}; grid-row:1` }, serverText(round, 'name')));
            }
        });
        layout.cells.flat().forEach((cell) => {
            const box = h('div', { class: 'cup-bracket-cell', role: 'listitem', style: `grid-column:${cell.column}; grid-row:${cell.rowStart + 1} / ${cell.rowEnd + 1}` },
                this.fixture(byId.get(cell.id), true, roundOf.get(cell.id)));
            grid.append(box);
        });
        return h('section', { class: 'cup-bracket-section', 'aria-label': name },
            h('h3', {}, name), h('div', { class: 'cup-bracket-scroll', tabindex: '0', 'aria-label': t('tournament.bracket.scroll.label', { name }) }, grid));
    }

    fixture(f, compact = false, round = null) {
        const cup = this.current;
        const entrants = cup.config.entrants;
        const state = fixtureState(f, this.matchMap);
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
        const decided = f.decided_by && DECIDED_NAMES[f.decided_by] ? DECIDED_NAMES[f.decided_by] : '';
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
            f.score ? t('tournament.fixture.score', { left: f.score[0], right: f.score[1] }) : null, ...extra, winner, decided, state !== 'done' ? STATE_NAMES[state] || state : null];
        return h('div', { class: `cup-fixture state-${state}`, 'aria-label': spoken.filter(Boolean).join(', ') },
            compact && label && f.label !== round ? h('span', { class: 'cup-fixture-label small muted' }, label) : null,
            side(f.home, 0), side(f.away, 1),
            h('span', { class: 'cup-fixture-meta small muted' },
                [decided, ...extra, state !== 'done' ? STATE_NAMES[state] : null,
                    running ? t('tournament.fixture.percent', { pct: Math.round((running.progress || 0) * 100) }) : null,
                    f.group ? t('tournament.fixture.group', { group: f.group }) : null,
                    matches.some((m) => m.result && m.result.forfeit) ? t('tournament.fixture.awarded') : null,
                    failed && failed.error ? serverText(failed, 'error') : null].filter(Boolean).join(', ')),
            watch.length ? h('span', { class: 'cup-watch row' }, watch.map((m, i) => h('button', {
                type: 'button', class: 'btn small ghost', 'data-focus': `watch-${m.key}`,
                ...symbolOnly(t('tournament.watch.label', { label: serverText(m, 'label'), home: entrantName(entrants[m.home]), away: entrantName(entrants[m.away]) })),
                onclick: () => this.app.openMatchInWatch(m.result.match),
            }, icon('watch'), watch.length > 1 ? formatNumber(i + 1) : null))) : null,
            unseen.length ? h('span', { class: 'cup-unseen row' }, unseen.map((m) => this.unseenButtons(m))) : null,
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
        const ordered = settings.tiebreakers.map((name) => TIEBREAK_NAMES[name]).join(COMMA_THEN);
        const name = serverText(table, 'name');
        return h('section', { class: 'cup-table' },
            h('h3', {}, name),
            h('div', { class: 'cup-table-scroll', tabindex: '0', 'aria-label': t('tournament.table.scroll.label', { name }) },
                h('table', {}, h('caption', { class: 'muted small' }, t('tournament.table.caption', { order: ordered })),
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

    async remove() {
        const cup = this.current;
        if (!window.confirm(t('tournament.delete.confirm', { name: serverText(cup, 'name') }))) {
            return;
        }
        try {
            await tournamentsApi.remove(cup.id);
            this.mode = 'empty';
            this.openId = null;
            this.current = null;
            await this.refresh();
        } catch (err) {
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
        const left = h('span', { class: 'cup-count small', role: 'status' });
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
            this.kickoffSide(entrants[next.home], 0), h('span', { class: 'cup-versus' }, t('tournament.intermission.versus')), this.kickoffSide(entrants[next.away], 1)),
        left,
        h('div', { class: 'row' }, play,
            h('button', { type: 'button', class: 'btn ghost', onclick: () => this.closeIntermission() }, icon('close'), t('tournament.intermission.cancel'))));
        tick();
        host.append(card);
        this.intermission = { card, timer: null };
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

    closeIntermission() {
        if (!this.intermission) {
            return;
        }
        clearInterval(this.intermission.timer);
        this.intermission.card.remove();
        this.intermission = null;
    }

    // A side of a kickoff card, the kit of its team or a mark of its color, and its name.
    kickoffSide(entrant, index) {
        const team = entrant ? this.teams.find((x) => x.id === entrant.team) : null;
        return h('span', { class: 'cup-kickoff-side' },
            team ? kitShirt(team, index) : entrant ? h('span', { class: 'cup-dot', style: `background: rgb(${(entrant.color || [128, 128, 128]).join(',')})`, 'aria-hidden': 'true' }) : null,
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
                h('p', { class: 'cup-kickoff-label small muted' }, final ? icon('trophy', 'icon text-symbol') : null,
                    final ? t('tournament.upNext.final', { label: serverText(m, 'label') }) : serverText(m, 'label')),
                h('p', { class: 'cup-kickoff-sides' }, this.kickoffSide(entrants[m.home], 0), h('span', { class: 'cup-versus' }, t('tournament.intermission.versus')), this.kickoffSide(entrants[m.away], 1)),
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
    // what they missed, with the predictions they got right.
    caughtUp(cup) {
        const watchedNow = this.session[cup.id] || [];
        if (!spoilerFree(cup.id) || !cup.spoilers || cup.spoilers.hidden || !watchedNow.length) {
            return null;
        }
        const entrants = cup.config.entrants;
        const results = watchedNow.map((key) => this.matchMap.get(key)).filter((m) => m && m.result && Array.isArray(m.result.score));
        const score = predictionScore(cup.id, results);
        return h('section', { class: 'cup-caught-up notice', 'aria-labelledby': 'cup-caught-up-title' },
            h('h3', { id: 'cup-caught-up-title' }, icon('done', 'icon text-symbol'), t('tournament.caughtUp.title')),
            h('ul', {}, results.map((m) => h('li', {}, t('tournament.caughtUp.result', {
                label: serverText(m, 'label'), home: entrantName(entrants[m.home]), away: entrantName(entrants[m.away]), left: m.result.score[0], right: m.result.score[1],
            })))),
            score.scored ? h('p', { class: 'small' }, t('tournament.predictions.score', { right: score.right, total: score.scored })) : null,
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
            h('h2', { tabindex: '-1' }, t('tournament.brackets.title', { name: serverText(cup, 'name') })),
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
        const focusKey = focused ? (focused.id || focused.dataset.focus || null) : null;
        const byId = focusKey && focused.id === focusKey;
        const scroll = this.mainHost.scrollTop;
        this.mainHost.replaceChildren(h('div', { class: 'cup-view cup-brackets' }, head, tabs, panel));
        this.mainHost.scrollTop = scroll;
        if (focusKey) {
            (byId ? document.getElementById(focusKey) : this.mainHost.querySelector(`[data-focus="${CSS.escape(focusKey)}"]`))?.focus();
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
            if (cup.people_waiting && !this.announced.has(key)) {
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
