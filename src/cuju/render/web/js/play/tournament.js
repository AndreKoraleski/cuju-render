// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The Tournaments page. A list of tournaments sits beside the open one, which shows its stages as
// brackets, tables and fixtures with results, the matches of people ready to play, and the trophy
// ceremony at the end. New tournament opens a wizard of five steps, the format, the entrants, the
// settings, every setting of every stage in the advanced editor, and a review of the draw.

import { api } from '../core/api.js';
import { formatNumber, serverText, t, tOr } from '../core/i18n.js';
import { kitShirt } from '../pages/matches.js';
import { el as h, icon } from '../core/menu.js';
import { listedScenarios, scenarioName, scenarioText } from '../core/scenarios.js';
import {
    DECIDED_NAMES, FORMAT_NAMES, SECTION_NAMES, SETTLE_NAMES, STATE_NAMES, TIEBREAK_NAMES,
    bracketLayout, entrantName, fixtureMatches, fixtureState, formatsText, isBracket, progressShare,
    sections, sideName, stageNameText, stageText, tiebreakText,
} from './tournament-layout.js';

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
        name: '', seed: '', seeding: 'random', concurrency: 1, forfeit_score: 3, preset: null,
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
        if (this.mode === 'view' && this.openId) {
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
                h('button', { type: 'button', class: 'btn primary', onclick: () => this.startWizard() }, t('tournament.new'))),
            this.listHost);
        this.root.replaceChildren(h('div', { class: 'cup-layout' }, side, this.mainHost));
    }

    render() {
        if (this.error) {
            this.built = false;
            this.root.replaceChildren(h('div', { class: 'page-pad' }, h('div', { class: 'notice error' },
                h('p', {}, this.error.message),
                h('p', { class: 'muted' }, t('tournament.offline.hint')),
                h('button', { class: 'btn', type: 'button', onclick: () => this.refresh() }, t('tournament.offline.retry')))));
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
            const button = h('button', {
                type: 'button', class: `cup-item${cup.id === this.openId && this.mode === 'view' ? ' active' : ''}`,
                'aria-current': cup.id === this.openId && this.mode === 'view' ? 'true' : 'false',
                onclick: () => this.open(cup.id),
            },
            h('span', { class: 'cup-item-name' }, serverText(cup, 'name')),
            h('span', { class: 'cup-item-meta' },
                h('span', { class: `state-pill ${cup.state === 'running' ? 'running' : cup.state === 'done' ? 'done' : 'failed'}` }, STATE_LABELS[cup.state] || cup.state),
                t('tournament.list.meta', { count: cup.entrants, formats: formatsText(cup.stages) })),
            cup.champion ? h('span', { class: 'cup-item-champion' }, t('tournament.list.champion', { name: serverText(cup, 'champion') })) : null,
            cup.people_waiting ? h('span', { class: 'cup-item-people' }, t('tournament.list.people', { count: cup.people_waiting })) : null,
            cup.state === 'running' ? h('span', { class: 'progress', 'aria-hidden': 'true' }, h('span', { class: 'bar', style: `width:${Math.round(share * 100)}%` })) : null);
            return h('li', {}, button);
        }));
    }

    renderEmpty() {
        this.mainHost.replaceChildren(h('div', { class: 'empty-state' },
            h('p', { class: 'empty-title' }, t('tournament.empty.title')),
            h('p', { class: 'muted' }, t('tournament.empty.text')),
            h('button', { type: 'button', class: 'btn primary', onclick: () => this.startWizard() }, t('tournament.new'))));
    }

    // The wizard and the advanced editor.

    startWizard(config = null) {
        this.mode = 'wizard';
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
        for (const key of ['name', 'seeding', 'concurrency', 'forfeit_score', 'preset']) {
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
            const entry = { kind: e.kind, name: e.name_id ? undefined : e.name };
            if (e.kind === 'team') {
                entry.team = e.team;
            } else if (e.kind === 'builtin') {
                entry.ability = e.ability;
            } else {
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
            h('button', { type: 'button', class: 'btn ghost', onclick: () => this.cancelWizard() }, t('tournament.wizard.cancel')),
            h('span', { class: 'cup-nav-gap' }),
            this.step > 0 ? h('button', { type: 'button', class: 'btn', onclick: () => this.goStep(this.step - 1) }, t('tournament.wizard.back')) : null,
            this.step < STEPS.length - 1
                ? h('button', { type: 'button', class: 'btn primary', onclick: () => this.goStep(this.step + 1) }, t('tournament.wizard.next'))
                : h('button', { type: 'button', class: 'btn primary cup-start', onclick: (e) => this.create(e.currentTarget) }, icon('play'), t('tournament.wizard.start')));
        this.mainHost.replaceChildren(h('div', { class: 'cup-wizard' },
            h('header', { class: 'cup-head' }, h('h2', {}, t('tournament.new')),
                h('p', { class: 'muted' }, t('tournament.wizard.text'))),
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
                }, t('tournament.formatStep.delete')));
        });
        return [
            h('p', { class: 'muted' }, t('tournament.formatStep.intro')),
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
                return;
            }
            d.entrants.push(entry);
            this.renderWizard();
        };
        const adders = h('div', { class: 'cup-adders' },
            h('div', { class: 'cup-adder' }, h('label', { class: 'field' }, t('tournament.entrants.team'), teamSelect),
                h('button', { type: 'button', class: 'btn', disabled: !teams.length, onclick: () => add({ kind: 'team', team: teamSelect.value }) }, t('tournament.entrants.team.add')),
                h('button', { type: 'button', class: 'btn ghost', disabled: !teams.length, onclick: () => {
                    const have = new Set(d.entrants.filter((e) => e.kind === 'team').map((e) => e.team));
                    teams.filter((x) => !have.has(x.id)).forEach((x) => d.entrants.push({ kind: 'team', team: x.id }));
                    this.renderWizard();
                } }, t('tournament.entrants.team.addAll'))),
            h('div', { class: 'cup-adder' }, h('label', { class: 'field' }, t('tournament.entrants.builtin'), ability),
                h('button', { type: 'button', class: 'btn', onclick: () => {
                    const value = Number(ability.value);
                    if (!(value >= 0 && value <= 1)) {
                        this.app.hud.toast(t('tournament.entrants.builtin.range'), 'error');
                        return;
                    }
                    add({ kind: 'builtin', ability: Math.round(value * 10000) / 10000 });
                } }, t('tournament.entrants.builtin.add')),
                h('button', { type: 'button', class: 'btn ghost', onclick: () => {
                    [0.2, 0.4, 0.6, 0.8].forEach((v) => d.entrants.push({ kind: 'builtin', ability: v }));
                    this.renderWizard();
                } }, t('tournament.entrants.builtin.addFour'))),
            h('div', { class: 'cup-adder' }, h('label', { class: 'field' }, t('tournament.entrants.person'), person),
                h('button', { type: 'button', class: 'btn', onclick: () => {
                    const name = person.value.trim();
                    if (!name) {
                        this.app.hud.toast(t('tournament.entrants.person.noName'), 'error');
                        person.focus();
                        return;
                    }
                    add({ kind: 'person', name, teammates: 'builtin' });
                } }, t('tournament.entrants.person.add'))));
        const rows = d.entrants.map((entry, index) => this.entrantRow(entry, index));
        return [
            h('p', { class: 'muted' }, t('tournament.entrants.intro', { count: d.entrants.length })),
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
        const name = h('input', { type: 'text', maxlength: '40', value: entry.name || '', placeholder: fallback || t('tournament.entrants.name'), 'aria-label': t('tournament.entrant.name.label', { number }) });
        name.addEventListener('input', () => {
            entry.name = name.value.trim() || undefined;
        });
        const held = this.ratings[ratingKey(entry)];
        const rating = h('input', {
            type: 'number', min: '0', max: '10000', step: '1', value: entry.rating ?? '', placeholder: String(Math.round(held ? held.rating : 1500)),
            title: t('tournament.entrant.rating.title'), 'aria-label': t('tournament.entrant.rating.label', { number }),
        });
        rating.addEventListener('input', () => {
            entry.rating = rating.value === '' ? undefined : Number(rating.value);
        });
        const extra = [];
        if (entry.kind === 'builtin') {
            const ability = h('input', { type: 'number', min: '0', max: '1', step: '0.05', value: entry.ability ?? '', placeholder: t('tournament.entrant.ability.placeholder'), 'aria-label': t('tournament.entrant.ability.label', { number }) });
            ability.addEventListener('input', () => {
                entry.ability = ability.value === '' ? null : Number(ability.value);
            });
            extra.push(h('label', { class: 'field small-field' }, t('tournament.entrant.ability'), ability));
        } else if (entry.kind === 'person') {
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
            h('label', { class: 'field' }, t('tournament.entrants.name'), name), ...extra,
            h('label', { class: 'field small-field' }, t('tournament.entrant.rating'), rating),
            h('span', { class: 'cup-entrant-actions' },
                h('button', { type: 'button', class: 'btn small ghost cup-up', 'aria-label': t('tournament.entrant.up.label', { number }), disabled: index === 0, onclick: () => move(-1) }, t('tournament.entrant.up')),
                h('button', { type: 'button', class: 'btn small ghost cup-down', 'aria-label': t('tournament.entrant.down.label', { number }), disabled: index === d.entrants.length - 1, onclick: () => move(1) }, t('tournament.entrant.down')),
                h('button', { type: 'button', class: 'btn small ghost danger', 'aria-label': t('tournament.entrant.remove.label', { number }), onclick: () => {
                    d.entrants.splice(index, 1);
                    this.renderWizard();
                } }, t('tournament.entrant.remove'))));
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
        const ability = this.optionalNumber({ key: 'ability', min: 0, max: 1, step: 0.05, initial: 0.5, off: OFF_SCENARIO, label: t('tournament.field.ability') }, defaults.ability ?? null, (v) => {
            if (v === null) {
                delete defaults.ability;
            } else {
                defaults.ability = v;
            }
        });
        return h('div', { class: 'cup-form' },
            h('label', { class: 'field' }, t('tournament.settings.name'), name),
            h('label', { class: 'field' }, t('tournament.settings.seed'),
                h('span', { class: 'row' }, seed, h('button', { type: 'button', class: 'btn ghost', onclick: () => {
                    seed.value = String(crypto.getRandomValues(new Uint32Array(1))[0]);
                    d.seed = seed.value;
                } }, t('tournament.settings.seed.draw')))),
            h('p', { class: 'muted small' }, t('tournament.settings.seed.note')),
            h('label', { class: 'field' }, t('tournament.settings.seeding'), seeding),
            h('div', { class: 'field' }, h('span', {}, t('tournament.settings.scenario')), scenario, h('span', { class: 'muted small' }, scenarioText(defaults.scenario || ''))),
            h('div', { class: 'field' }, h('span', {}, t('tournament.settings.length')), length),
            h('div', { class: 'field' }, h('span', {}, t('tournament.field.ability')), ability),
            h('label', { class: 'field' }, t('tournament.settings.concurrency'), concurrency),
            h('label', { class: 'field' }, t('tournament.settings.forfeit'), forfeit),
            h('p', { class: 'muted small' }, t('tournament.settings.note')));
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
            JSON.stringify({ defaults: d.defaults, stages: d.stages }, null, 2));
        const applied = h('p', { class: 'muted small', role: 'status' });
        const apply = h('button', { type: 'button', class: 'btn', onclick: () => {
            try {
                const value = JSON.parse(json.value);
                if (!value || !Array.isArray(value.stages)) {
                    throw new Error(t('tournament.json.expected'));
                }
                d.stages = value.stages;
                d.defaults = value.defaults || {};
                this.renderWizard();
                this.app.hud.toast(t('tournament.json.applied'));
            } catch (err) {
                applied.textContent = t('tournament.json.failed', { reason: err.message });
            }
        } }, t('tournament.json.apply'));
        return [
            h('p', { class: 'muted' }, t('tournament.stages.intro')),
            h('div', { class: 'cup-stages' }, stages),
            h('button', { type: 'button', class: 'btn', disabled: d.stages.length >= 8, onclick: () => {
                d.stages.push({ format: 'knockout', name: '' });
                this.renderWizard();
            } }, t('tournament.stages.add')),
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
                h('button', { type: 'button', class: 'btn small ghost', disabled: index === 0, onclick: () => move(-1) }, t('tournament.stage.earlier')),
                h('button', { type: 'button', class: 'btn small ghost', disabled: last, onclick: () => move(1) }, t('tournament.stage.later')),
                h('button', { type: 'button', class: 'btn small ghost danger', disabled: d.stages.length === 1, onclick: () => {
                    d.stages.splice(index, 1);
                    this.renderWizard();
                } }, t('tournament.stage.remove'))));
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
            control = this.optionalNumber({ ...field, label }, value, set);
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
                const up = name === 'lots' ? null : h('button', { type: 'button', class: 'btn small ghost', disabled: i === 0, 'aria-label': t('tournament.order.earlier.label', { name: field.names[name] }), onclick: () => {
                    [order[i - 1], order[i]] = [order[i], order[i - 1]];
                    commit();
                    draw(`up-${name}`);
                } }, t('tournament.order.earlier'));
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
            h('div', { class: 'row' }, saveName, saveTitle, h('button', { type: 'button', class: 'btn', onclick: () => this.savePreset(saveName.value.trim(), saveTitle.value.trim()) }, t('tournament.review.save'))));
        this.check(host);
        return [host, save];
    }

    config() {
        const d = this.draft;
        const config = {
            seeding: d.seeding, concurrency: d.concurrency,
            forfeit_score: d.forfeit_score, defaults: d.defaults, stages: d.stages,
            entrants: d.entrants.map((e) => {
                const entry = { kind: e.kind };
                for (const key of ['team', 'name', 'rating', 'teammates']) {
                    if (e[key] !== undefined && e[key] !== null && e[key] !== '') {
                        entry[key] = e[key];
                    }
                }
                if (e.kind === 'builtin') {
                    entry.ability = e.ability ?? null;
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
        return config;
    }

    async check(host) {
        try {
            const preview = await tournamentsApi.check(this.config());
            host.setAttribute('aria-busy', 'false');
            const entrants = preview.config.entrants;
            const parts = [h('p', {}, t('tournament.review.summary', {
                entrants: t('tournament.count.entrants', { count: entrants.length }), seed: preview.config.seed,
                matches: t('tournament.review.matches', { count: preview.matches }),
            }))];
            this.draft.seed = String(preview.config.seed);
            preview.stages.forEach((stage, index) => {
                const settings = preview.config.stages[index];
                parts.push(h('section', { class: 'cup-review-stage' },
                    h('h3', {}, t('tournament.review.stage', { number: index + 1, name: serverText(settings, 'name') })),
                    h('p', { class: 'muted small' }, [
                        stageText(settings), t('tournament.count.entrants', { count: settings.entrants }),
                        index < preview.stages.length - 1 ? t('tournament.review.advance', { count: settings.advance }) : null,
                        scenarioName(settings.scenario), settings.length ? t('tournament.count.steps', { count: settings.length }) : null,
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
                h('p', { class: 'muted small' }, t('tournament.review.failed'))));
        }
    }

    async savePreset(name, title) {
        const d = this.draft;
        try {
            const saved = await tournamentsApi.savePreset(name, {
                title: title || d.name || name, description: '', seeding: d.seeding, concurrency: d.concurrency,
                forfeit_score: d.forfeit_score, defaults: d.defaults, stages: d.stages,
            });
            this.presets[name] = saved;
            this.app.hud.toast(t('tournament.review.saved', { title: saved.title }));
        } catch (err) {
            this.app.hud.toast(err.message, 'error', 7000);
        }
    }

    async create(button) {
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
            const entry = await tournamentsApi.get(id);
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

    renderView() {
        const cup = this.current;
        if (!cup || this.mode !== 'view') {
            return;
        }
        const entrants = cup.config.entrants;
        this.matchMap = new Map(cup.matches.map((m) => [m.key, m]));
        if (this.stageTab === null || this.stageTab >= cup.stages_view.length) {
            const playing = cup.stages_view.findIndex((s) => s.state !== 'done');
            this.stageTab = playing >= 0 ? playing : cup.stages_view.length - 1;
        }
        const share = progressShare(cup);
        const actions = [];
        if (cup.state === 'running') {
            actions.push(h('button', { type: 'button', class: 'btn ghost danger', 'data-focus': 'act-cancel', onclick: () => this.act('cancel', t('tournament.view.cancelled')) }, t('tournament.view.cancel')));
        }
        if (cup.state === 'stopped') {
            actions.push(h('button', { type: 'button', class: 'btn primary', 'data-focus': 'act-resume', onclick: () => this.act('resume', t('tournament.view.resumed')) }, t('tournament.view.resume')));
        }
        if (cup.state === 'done') {
            actions.push(h('button', { type: 'button', class: 'btn primary', 'data-focus': 'act-ceremony', onclick: () => this.ceremony() }, t('tournament.view.ceremony')));
        }
        actions.push(h('button', { type: 'button', class: 'btn ghost', onclick: () => {
            const config = clone(cup.config);
            this.startWizard(config);
            this.draft.seed = '';
        } }, t('tournament.view.again')));
        if (cup.state !== 'running') {
            actions.push(h('button', { type: 'button', class: 'btn ghost danger', 'data-focus': 'act-delete', onclick: () => this.remove() }, t('tournament.view.delete')));
        }
        const head = h('header', { class: 'cup-head' },
            h('h2', { tabindex: '-1' }, serverText(cup, 'name')),
            h('p', { class: 'cup-meta' },
                h('span', { class: `state-pill ${cup.state === 'running' ? 'running' : cup.state === 'done' ? 'done' : 'failed'}` }, STATE_LABELS[cup.state] || cup.state),
                h('span', {}, t('tournament.count.entrants', { count: entrants.length })),
                h('span', {}, t('tournament.view.seed', { seed: cup.seed })),
                h('span', {}, t('tournament.view.played', { played: cup.played, count: cup.scheduled })),
                cup.running ? h('span', {}, t('tournament.view.running', { count: cup.running })) : null),
            cup.state === 'running' ? h('div', { class: 'progress', role: 'progressbar', 'aria-label': t('tournament.view.progress.label'), 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round(share * 100)) },
                h('div', { class: 'bar', style: `width:${Math.round(share * 100)}%` })) : null,
            cup.champion ? h('p', { class: 'cup-champion' }, h('span', {}, t('tournament.view.champion', { name: serverText(cup, 'champion') }))) : null,
            cup.error ? h('div', { class: 'notice error', role: 'alert' }, h('p', {}, serverText(cup, 'error')), this.failedAwards(cup)) : null,
            cup.persistence_error ? h('div', { class: 'notice error' }, h('p', {}, serverText(cup, 'persistence_error'))) : null,
            cup.owner ? h('p', { class: 'muted small' }, t('tournament.view.owner', { owner: cup.owner })) : null,
            h('div', { class: 'row cup-actions' }, actions));
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
        const focusKey = focused ? (focused.id || focused.dataset.focus || null) : null;
        const byId = focusKey && focused.id === focusKey;
        const scroll = this.mainHost.scrollTop;
        this.mainHost.replaceChildren(h('div', { class: 'cup-view' }, head, peopleBox, tabs, panel, ranking));
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
            } }, t('tournament.forfeit', { name: winner }));
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
        } }, t('tournament.forfeit.yes')),
        h('button', { type: 'button', class: 'btn small ghost', 'data-focus': `award-no-${id}`, onclick: cancel }, t('tournament.forfeit.no')));
    }

    stageView(stage, settings) {
        const entrants = this.current.config.entrants;
        const parts = [h('p', { class: 'muted small' }, [
            stageText(settings), scenarioName(settings.scenario), settings.length ? t('tournament.count.steps', { count: settings.length }) : null,
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
        const side = (value, index) => {
            const known = typeof value === 'number';
            const won = f.winner !== null && f.winner !== undefined && f.winner === value && known;
            const team = known ? this.teams.find((x) => x.id === entrants[value].team) : null;
            return h('span', { class: `cup-side-name${won ? ' won' : ''}${known ? '' : ' unknown'}` },
                known && team ? kitShirt(team, index) : known ? h('span', { class: 'cup-dot', style: `background: rgb(${entrants[value].color.join(',')})`, 'aria-hidden': 'true' }) : null,
                h('span', {}, sideName(value, entrants)),
                f.score ? h('b', { class: 'cup-goals' }, String(f.score[index])) : null);
        };
        const running = matches.find((m) => m.state === 'running');
        const decided = f.decided_by && DECIDED_NAMES[f.decided_by] ? DECIDED_NAMES[f.decided_by] : '';
        const watch = matches.filter((m) => m.result && m.result.match);
        // A failed match waits for an award to either side, or a retry by Resume.
        const failed = matches.find((m) => m.state === 'failed');
        const label = f.label ? serverText(f, 'label') : '';
        // A replay and the deciding matches have scores of their own beside the tie's.
        const extra = [f.replay ? t('tournament.fixture.replay', { left: f.replay[0], right: f.replay[1] }) : null,
            f.decider ? t('tournament.fixture.decider', { left: f.decider[0], right: f.decider[1] }) : null];
        const winner = typeof f.winner === 'number' && f.state === 'done' ? t('tournament.fixture.wonBy', { name: sideName(f.winner, entrants) }) : null;
        const spoken = [label, t('tournament.fixture.versus', { home: sideName(f.home, entrants), away: sideName(f.away, entrants) }),
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
                type: 'button', class: 'btn small ghost', 'data-focus': `watch-${m.key}`, 'aria-label': t('tournament.watch.label', { label: serverText(m, 'label'), home: entrantName(entrants[m.home]), away: entrantName(entrants[m.away]) }),
                onclick: () => this.app.openMatchInWatch(m.result.match),
            }, icon('play'), watch.length > 1 ? t('tournament.watch.number', { number: i + 1 }) : t('tournament.watch')))) : null,
            failed ? h('span', { class: 'row' }, this.forfeitButton(failed, 'home'), this.forfeitButton(failed, 'away')) : null,
            matches.some((m) => m.state === 'person') ? h('button', { type: 'button', class: 'btn small primary', 'data-focus': `play-${f.id}`, disabled: cup.state !== 'running', onclick: () => this.playMatch(matches.find((m) => m.state === 'person')) }, t('tournament.play')) : null);
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
                cells.map((value, i) => (i === 1 ? h('th', { scope: 'row' }, String(value), row.best ? h('span', { class: 'muted small' }, t('tournament.table.best')) : null) : h('td', {}, String(value)))));
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
            if (old && old.state !== 'done' && cup.state === 'done') {
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
        if (this.mode === 'view' && this.openId) {
            const summary = list.find((cup) => cup.id === this.openId);
            if (summary && (changed || summary.running) && !this.mainHost.contains(document.activeElement?.closest('input, select, textarea'))) {
                await this.load(this.openId);
            }
        }
    }
}
