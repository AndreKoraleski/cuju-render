// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The Tournaments page. A list of tournaments sits beside the open one, which shows its stages as
// brackets, tables and fixtures with results, the matches of people ready to play, and the trophy
// ceremony at the end. New tournament opens a wizard of five steps, the format, the entrants, the
// settings, every setting of every stage in the advanced editor, and a review of the draw.

import { api } from '../core/api.js';
import { kitShirt } from '../pages/matches.js';
import { el as h, icon } from '../core/menu.js';
import { listedScenarios, scenarioName, scenarioText } from '../core/scenarios.js';
import {
    DECIDED_NAMES, FORMAT_NAMES, SECTION_NAMES, SETTLE_NAMES, STATE_NAMES, TIEBREAK_NAMES,
    bracketLayout, fixtureMatches, fixtureState, isBracket, progressShare, sections, sideName,
    stageText, tiebreakText,
} from './tournament-layout.js';

const FORMATS = Object.keys(FORMAT_NAMES);
const TIEBREAKERS = Object.keys(TIEBREAK_NAMES);
const SETTLEMENTS = Object.keys(SETTLE_NAMES);
const STEPS = ['Format', 'Entrants', 'Settings', 'Stages', 'Review'];
const STATE_LABELS = { running: 'Running', stopped: 'Stopped', done: 'Finished', cancelled: 'Canceled' };
const KIND_NAMES = { team: 'Registered team', builtin: 'Built-in AI', person: 'Person' };

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
        const error = new Error(`Cannot reach the cuju server at ${location.origin}. Is it still running?`);
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
        const error = new Error((body && body.error) || `The server answered ${res.status}.`);
        error.status = res.status;
        throw error;
    }
    return body;
}

export const tournamentsApi = {
    list: () => call('GET', '/api/tournaments'),
    get: (id) => call('GET', `/api/tournaments/${encodeURIComponent(id)}`),
    presets: () => call('GET', '/api/tournaments/presets'),
    check: (config) => call('POST', '/api/tournaments/check', { config }),
    create: (config) => call('POST', '/api/tournaments', { config }),
    action: (id, action, body = {}) => call('POST', `/api/tournaments/${encodeURIComponent(id)}/${action}`, body),
    remove: (id) => call('DELETE', `/api/tournaments/${encodeURIComponent(id)}`),
    savePreset: (name, preset) => call('POST', `/api/tournaments/presets/${encodeURIComponent(name)}`, { preset }),
    removePreset: (name) => call('DELETE', `/api/tournaments/presets/${encodeURIComponent(name)}`),
};

function clone(value) {
    return JSON.parse(JSON.stringify(value));
}

// Every setting of a stage that the advanced editor shows, with the formats it applies to.
const ALL = null;
const KNOCKOUTS = ['knockout', 'double_elimination', 'ladder', 'king_of_the_hill', 'gauntlet'];
const TABLES = ['league', 'groups', 'swiss'];
const STAGE_FIELDS = [
    { key: 'name', label: 'Name', type: 'text', formats: ALL },
    { key: 'format', label: 'Format', type: 'select', options: FORMATS.map((f) => [f, FORMAT_NAMES[f]]), formats: ALL },
    { key: 'scenario', label: 'Scenario', type: 'scenario', empty: 'Chosen by the entrants', formats: ALL },
    { key: 'length', label: 'Match length in steps', type: 'optional', min: 50, max: 5000, step: 50, initial: 600, off: "The scenario's own", formats: ALL },
    { key: 'ability', label: 'Ability of built-in AI sides', type: 'optional', min: 0, max: 1, step: 0.05, initial: 0.5, off: "The scenario's own", formats: ALL, help: 'Applies to the built-in AI that plays beside a team or a person, and to built-in AI entrants without their own.' },
    { key: 'legs', label: 'Legs of each tie or meeting', type: 'number', min: 1, max: 10, formats: ALL },
    { key: 'final_legs', label: 'Legs of the final', type: 'optional', min: 1, max: 10, step: 1, initial: 1, off: 'As other ties', formats: ['knockout', 'double_elimination'] },
    { key: 'settle', label: 'A drawn tie is settled by', type: 'order', options: SETTLEMENTS, names: SETTLE_NAMES, formats: KNOCKOUTS },
    { key: 'replays', label: 'Replays at most', type: 'number', min: 1, max: 5, formats: KNOCKOUTS },
    { key: 'decider_scenario', label: 'Scenario of a deciding match', type: 'scenario', formats: KNOCKOUTS, help: 'Each side attacks from the left once, and the goals of both matches add up.' },
    { key: 'decider_length', label: 'Length of a deciding match', type: 'optional', min: 50, max: 5000, step: 50, initial: 400, off: "The scenario's own", formats: KNOCKOUTS },
    { key: 'draws', label: 'On a draw', type: 'select', options: [['holder', 'The holder keeps the place'], ['settle', 'Settle as a tie']], formats: ['ladder', 'king_of_the_hill', 'gauntlet'] },
    { key: 'points', label: 'Points for a win, draw and loss', type: 'points', formats: ALL },
    { key: 'tiebreakers', label: 'Tiebreakers after points', type: 'order', options: TIEBREAKERS, names: TIEBREAK_NAMES, formats: ALL },
    { key: 'bracket', label: 'An entrant count that is no power of two', type: 'select', options: [['byes', 'Byes for the top seeds'], ['play_in', 'A play-in round']], formats: ['knockout'] },
    { key: 'bracket_size', label: 'Bracket size', type: 'optional', min: 2, max: 512, step: 1, initial: 8, off: 'From the entrants', formats: ['knockout', 'double_elimination'] },
    { key: 'until', label: 'Play until this many remain', type: 'number', min: 1, max: 256, formats: ['knockout'] },
    { key: 'third_place', label: 'Third place match', type: 'check', formats: ['knockout'] },
    { key: 'grand_final_reset', label: 'A deciding match when the losers bracket wins the grand final', type: 'check', formats: ['double_elimination'] },
    { key: 'cycles', label: 'Times each pair meets, home and away in turn', type: 'number', min: 1, max: 10, formats: ['league', 'groups'] },
    { key: 'groups', label: 'Number of groups', type: 'optional', min: 1, max: 128, step: 1, initial: 4, off: 'From the group size', formats: ['groups'] },
    { key: 'group_size', label: 'Group size', type: 'number', min: 2, max: 256, formats: ['groups'] },
    { key: 'group_sizes', label: 'Sizes of each group', type: 'list', placeholder: 'For example 5, 4, 4', formats: ['groups'] },
    { key: 'pots', label: 'Pots of the draw', type: 'optional', min: 1, max: 256, step: 1, initial: 4, off: 'One entrant a group each', formats: ['groups'] },
    { key: 'qualifiers', label: 'Qualifiers of each group', type: 'list', placeholder: '2, or one count a group', single: true, formats: ['groups'] },
    { key: 'best_position', label: 'Best of this place also qualify', type: 'optional', min: 1, max: 64, step: 1, initial: 3, off: 'None', formats: ['groups'] },
    { key: 'best_count', label: 'How many of them', type: 'fill', formats: ['groups'] },
    { key: 'rounds', label: 'Rounds', type: 'optional', min: 1, max: 1000, step: 1, initial: 5, off: 'From the entrants', formats: ['swiss', 'ladder'] },
    { key: 'bye_points', label: 'A bye counts as', type: 'select', options: [['win', 'A win'], ['draw', 'A draw'], ['none', 'No points']], formats: ['swiss'] },
    { key: 'laps', label: 'Laps of challengers', type: 'number', min: 1, max: 10, formats: ['king_of_the_hill'] },
    { key: 'seeding', label: 'Seeding of those who arrive', type: 'select', options: [['standing', 'By the earlier stage'], ['random', 'Random from the seed'], ['rating', 'By rating']], formats: ALL, later: true },
    { key: 'advance', label: 'Entrants that advance', type: 'optional', min: 1, max: 256, step: 1, initial: 4, off: 'From the format', formats: ALL, notLast: true },
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
        name: 'Tournament', seed: '', seeding: 'random', concurrency: 1, forfeit_score: 3, preset: null,
        defaults: {}, stages: [{ format: 'knockout', name: 'Cup' }], entrants: [],
    };
}

export class TournamentsPage {
    constructor(app) {
        this.app = app;
        this.root = document.getElementById('page-tournaments');
        this.list = [];
        this.teams = [];
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
        this.listHost = h('ul', { class: 'cup-list', 'aria-label': 'Tournaments' });
        this.mainHost = h('section', { class: 'cup-main', 'aria-live': 'polite', 'aria-busy': 'false' });
        const side = h('aside', { class: 'cup-side', 'aria-labelledby': 'cup-list-title' },
            h('header', { class: 'cup-side-head' },
                h('h2', { id: 'cup-list-title' }, 'Tournaments'),
                h('button', { type: 'button', class: 'btn primary', onclick: () => this.startWizard() }, 'New tournament')),
            this.listHost);
        this.root.replaceChildren(h('div', { class: 'cup-layout' }, side, this.mainHost));
    }

    render() {
        if (this.error) {
            this.built = false;
            this.root.replaceChildren(h('div', { class: 'page-pad' }, h('div', { class: 'notice error' },
                h('p', {}, this.error.message),
                h('p', { class: 'muted' }, 'Start the server with cuju render serve, then try again.'),
                h('button', { class: 'btn', type: 'button', onclick: () => this.refresh() }, 'Try again'))));
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
            this.listHost.replaceChildren(h('li', { class: 'muted pad' }, 'No tournaments yet.'));
            return;
        }
        this.listHost.replaceChildren(...this.list.map((t) => {
            const share = progressShare(t);
            const button = h('button', {
                type: 'button', class: `cup-item${t.id === this.openId && this.mode === 'view' ? ' active' : ''}`,
                'aria-current': t.id === this.openId && this.mode === 'view' ? 'true' : 'false',
                onclick: () => this.open(t.id),
            },
            h('span', { class: 'cup-item-name' }, t.name),
            h('span', { class: 'cup-item-meta' },
                h('span', { class: `state-pill ${t.state === 'running' ? 'running' : t.state === 'done' ? 'done' : 'failed'}` }, STATE_LABELS[t.state] || t.state),
                `${t.entrants} entrants, ${t.stages.map((s) => FORMAT_NAMES[s.format] || s.format).join(' then ')}`),
            t.champion ? h('span', { class: 'cup-item-champion' }, `Won by ${t.champion}`) : null,
            t.people_waiting ? h('span', { class: 'cup-item-people' }, `${t.people_waiting} ${t.people_waiting === 1 ? 'match waits' : 'matches wait'} for a person`) : null,
            t.state === 'running' ? h('span', { class: 'progress', 'aria-hidden': 'true' }, h('span', { class: 'bar', style: `width:${Math.round(share * 100)}%` })) : null);
            return h('li', {}, button);
        }));
    }

    renderEmpty() {
        this.mainHost.replaceChildren(h('div', { class: 'empty-state' },
            h('p', { class: 'empty-title' }, 'Tournaments of agents and people'),
            h('p', { class: 'muted' }, 'Choose a format, enter registered teams, the built-in AI and people, and the matches play here, each saved as a recording.'),
            h('button', { type: 'button', class: 'btn primary', onclick: () => this.startWizard() }, 'New tournament')));
    }

    // The wizard and the advanced editor.

    startWizard(config = null) {
        this.mode = 'wizard';
        this.openId = null;
        this.step = config ? 1 : 0;
        this.draft = config ? this.draftFrom(config) : newDraft();
        this.renderList();
        this.renderWizard();
    }

    draftFrom(config) {
        const draft = newDraft();
        for (const key of ['name', 'seeding', 'concurrency', 'forfeit_score', 'preset']) {
            if (config[key] !== undefined) {
                draft[key] = config[key];
            }
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
            const entry = { kind: e.kind, name: e.name };
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
        const tabs = h('div', { class: 'cup-steps', role: 'tablist', 'aria-label': 'Steps of a new tournament' },
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
            h('button', { type: 'button', class: 'btn ghost', onclick: () => this.cancelWizard() }, 'Cancel'),
            h('span', { class: 'cup-nav-gap' }),
            this.step > 0 ? h('button', { type: 'button', class: 'btn', onclick: () => this.goStep(this.step - 1) }, 'Back') : null,
            this.step < STEPS.length - 1
                ? h('button', { type: 'button', class: 'btn primary', onclick: () => this.goStep(this.step + 1) }, 'Next')
                : h('button', { type: 'button', class: 'btn primary cup-start', onclick: (e) => this.create(e.currentTarget) }, icon('play'), 'Start tournament'));
        this.mainHost.replaceChildren(h('div', { class: 'cup-wizard' },
            h('header', { class: 'cup-head' }, h('h2', {}, 'New tournament'),
                h('p', { class: 'muted' }, 'Every step may be opened at any time, and Stages holds every setting of every stage.')),
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
            if (draft.name === 'Tournament' || Object.values(this.presets).some((p) => p.title === draft.name)) {
                draft.name = preset.title;
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
                h('span', { class: 'cup-preset-title' }, preset.title),
                h('span', { class: 'cup-preset-text muted small' }, preset.description || preset.stages.map(stageText).join(', then ')),
                h('span', { class: 'cup-preset-stages small' }, preset.stages.map((s) => FORMAT_NAMES[s.format] || s.format).join(' then '))),
                preset.shipped ? null : h('button', {
                    type: 'button', class: 'btn small ghost danger', 'aria-label': `Delete the preset ${preset.title}`,
                    onclick: async () => {
                        try {
                            await tournamentsApi.removePreset(name);
                            delete this.presets[name];
                            this.renderWizard();
                        } catch (err) {
                            this.app.hud.toast(err.message, 'error');
                        }
                    },
                }, 'Delete'));
        });
        return [
            h('p', { class: 'muted' }, 'Pick a format to start from. Every setting stays open to change in Settings and Stages.'),
            h('div', { class: 'cup-presets', role: 'radiogroup', 'aria-label': 'Formats' }, cards),
        ];
    }

    entrantsStep() {
        const d = this.draft;
        const teams = this.teams.filter((t) => t.kind !== 'builtin');
        const teamSelect = h('select', { 'aria-label': 'Registered team to add' },
            teams.length ? teams.map((t) => h('option', { value: t.id }, `${t.name}, ${t.format === '5v5' ? 'five' : 'eleven'} a side`)) : h('option', { value: '' }, 'No registered teams'));
        const ability = h('input', { type: 'number', min: '0', max: '1', step: '0.05', value: '0.5', 'aria-label': 'Ability of the built-in AI to add, from 0 to 1' });
        const person = h('input', { type: 'text', maxlength: '40', placeholder: 'Name', 'aria-label': 'Name of the person to add' });
        const add = (entry) => {
            if (d.entrants.length >= 256) {
                this.app.hud.toast('A tournament takes at most 256 entrants.', 'error');
                return;
            }
            d.entrants.push(entry);
            this.renderWizard();
        };
        const adders = h('div', { class: 'cup-adders' },
            h('div', { class: 'cup-adder' }, h('label', { class: 'field' }, 'Registered team', teamSelect),
                h('button', { type: 'button', class: 'btn', disabled: !teams.length, onclick: () => add({ kind: 'team', team: teamSelect.value }) }, 'Add team'),
                h('button', { type: 'button', class: 'btn ghost', disabled: !teams.length, onclick: () => {
                    const have = new Set(d.entrants.filter((e) => e.kind === 'team').map((e) => e.team));
                    teams.filter((t) => !have.has(t.id)).forEach((t) => d.entrants.push({ kind: 'team', team: t.id }));
                    this.renderWizard();
                } }, 'Add every team')),
            h('div', { class: 'cup-adder' }, h('label', { class: 'field' }, 'Built-in AI at an ability', ability),
                h('button', { type: 'button', class: 'btn', onclick: () => {
                    const value = Number(ability.value);
                    if (!(value >= 0 && value <= 1)) {
                        this.app.hud.toast('An ability lies from 0 to 1.', 'error');
                        return;
                    }
                    add({ kind: 'builtin', ability: Math.round(value * 10000) / 10000 });
                } }, 'Add built-in AI'),
                h('button', { type: 'button', class: 'btn ghost', onclick: () => {
                    [0.2, 0.4, 0.6, 0.8].forEach((v) => d.entrants.push({ kind: 'builtin', ability: v }));
                    this.renderWizard();
                } }, 'Add four of rising ability')),
            h('div', { class: 'cup-adder' }, h('label', { class: 'field' }, 'Person', person),
                h('button', { type: 'button', class: 'btn', onclick: () => {
                    const name = person.value.trim();
                    if (!name) {
                        this.app.hud.toast('A person enters by name.', 'error');
                        person.focus();
                        return;
                    }
                    add({ kind: 'person', name, teammates: 'builtin' });
                } }, 'Add person')));
        const rows = d.entrants.map((entry, index) => this.entrantRow(entry, index));
        return [
            h('p', { class: 'muted' }, `Entrants play in this order when the seeding is manual. ${d.entrants.length} of 2 to 256 entered.`),
            adders,
            d.entrants.length ? h('ol', { class: 'cup-entrants' }, rows) : h('p', { class: 'muted pad' }, 'No entrants yet.'),
        ];
    }

    entrantRow(entry, index) {
        const d = this.draft;
        const team = entry.kind === 'team' ? this.teams.find((t) => t.id === entry.team) : null;
        const fallback = entry.kind === 'team' ? (team ? team.name : entry.team)
            : entry.kind === 'builtin' ? (entry.ability == null ? 'Built-in AI' : `Built-in AI ${Number(entry.ability).toFixed(2)}`) : '';
        const name = h('input', { type: 'text', maxlength: '40', value: entry.name || '', placeholder: fallback || 'Name', 'aria-label': `Name of entrant ${index + 1}` });
        name.addEventListener('input', () => {
            entry.name = name.value.trim() || undefined;
        });
        const rating = h('input', { type: 'number', min: '0', max: '10000', step: '1', value: entry.rating ?? '', placeholder: 'From earlier tournaments', 'aria-label': `Rating of entrant ${index + 1}` });
        rating.addEventListener('input', () => {
            entry.rating = rating.value === '' ? undefined : Number(rating.value);
        });
        const extra = [];
        if (entry.kind === 'builtin') {
            const ability = h('input', { type: 'number', min: '0', max: '1', step: '0.05', value: entry.ability ?? '', placeholder: "Scenario's", 'aria-label': `Ability of entrant ${index + 1}` });
            ability.addEventListener('input', () => {
                entry.ability = ability.value === '' ? null : Number(ability.value);
            });
            extra.push(h('label', { class: 'field small-field' }, 'Ability', ability));
        } else if (entry.kind === 'person') {
            const dynamic = this.teams.filter((t) => t.kind !== 'builtin' && t.control && t.control.assignment === 'dynamic');
            const mates = h('select', { 'aria-label': `Teammates of entrant ${index + 1}` },
                h('option', { value: 'builtin' }, 'Built-in AI'), dynamic.map((t) => h('option', { value: t.id }, t.name)));
            mates.value = entry.teammates || 'builtin';
            mates.addEventListener('change', () => {
                entry.teammates = mates.value;
            });
            extra.push(h('label', { class: 'field small-field' }, 'Teammates', mates));
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
            team ? kitShirt(team, 0) : h('span', { class: `cup-kind ${entry.kind}`, 'aria-hidden': 'true' }, entry.kind === 'person' ? 'P' : 'AI'),
            h('span', { class: 'cup-entrant-kind small muted' }, KIND_NAMES[entry.kind]),
            h('label', { class: 'field' }, 'Name', name), ...extra,
            h('label', { class: 'field small-field' }, 'Rating', rating),
            h('span', { class: 'cup-entrant-actions' },
                h('button', { type: 'button', class: 'btn small ghost cup-up', 'aria-label': `Move entrant ${index + 1} up`, disabled: index === 0, onclick: () => move(-1) }, 'Up'),
                h('button', { type: 'button', class: 'btn small ghost cup-down', 'aria-label': `Move entrant ${index + 1} down`, disabled: index === d.entrants.length - 1, onclick: () => move(1) }, 'Down'),
                h('button', { type: 'button', class: 'btn small ghost danger', 'aria-label': `Remove entrant ${index + 1}`, onclick: () => {
                    d.entrants.splice(index, 1);
                    this.renderWizard();
                } }, 'Remove')));
    }

    settingsStep() {
        const d = this.draft;
        const name = h('input', { type: 'text', maxlength: '80', value: d.name, 'aria-label': 'Name of the tournament' });
        name.addEventListener('input', () => {
            d.name = name.value;
        });
        const seed = h('input', { type: 'text', inputmode: 'numeric', value: d.seed, placeholder: 'Random', 'aria-label': 'Tournament seed' });
        seed.addEventListener('input', () => {
            d.seed = seed.value.trim();
        });
        const seeding = this.select([['random', 'Random from the seed'], ['manual', 'Manual, in the order of Entrants'], ['rating', 'By rating, from earlier tournaments or set by hand']], d.seeding, 'Seeding', (v) => {
            d.seeding = v;
        });
        const concurrency = h('input', { type: 'number', min: '1', max: '8', step: '1', value: String(d.concurrency), 'aria-label': 'Matches of agents at once' });
        concurrency.addEventListener('input', () => {
            d.concurrency = Number(concurrency.value);
        });
        const forfeit = h('input', { type: 'number', min: '1', max: '10', step: '1', value: String(d.forfeit_score), 'aria-label': 'Goals of an awarded match' });
        forfeit.addEventListener('input', () => {
            d.forfeit_score = Number(forfeit.value);
        });
        const defaults = d.defaults;
        const scenario = this.scenarioSelect(defaults.scenario ?? null, 'Scenario of every stage', 'Chosen by the entrants', (v) => {
            if (v === null) {
                delete defaults.scenario;
            } else {
                defaults.scenario = v;
            }
        });
        const length = this.optionalNumber({ key: 'length', min: 50, max: 5000, step: 50, initial: 600, off: "The scenario's own", label: 'Match length in steps' }, defaults.length ?? null, (v) => {
            if (v === null) {
                delete defaults.length;
            } else {
                defaults.length = v;
            }
        });
        const ability = this.optionalNumber({ key: 'ability', min: 0, max: 1, step: 0.05, initial: 0.5, off: "The scenario's own", label: 'Ability of built-in AI sides' }, defaults.ability ?? null, (v) => {
            if (v === null) {
                delete defaults.ability;
            } else {
                defaults.ability = v;
            }
        });
        return h('div', { class: 'cup-form' },
            h('label', { class: 'field' }, 'Name', name),
            h('label', { class: 'field' }, 'Tournament seed, empty for a random one',
                h('span', { class: 'row' }, seed, h('button', { type: 'button', class: 'btn ghost', onclick: () => {
                    seed.value = String(crypto.getRandomValues(new Uint32Array(1))[0]);
                    d.seed = seed.value;
                } }, 'Draw'))),
            h('p', { class: 'muted small' }, 'The same settings and seed give the same draw and the same seed for every match.'),
            h('label', { class: 'field' }, 'Seeding', seeding),
            h('div', { class: 'field' }, h('span', {}, 'Scenario of every stage'), scenario, h('span', { class: 'muted small' }, scenarioText(defaults.scenario || ''))),
            h('div', { class: 'field' }, h('span', {}, 'Match length in steps, ten a second'), length),
            h('div', { class: 'field' }, h('span', {}, 'Ability of built-in AI sides'), ability),
            h('label', { class: 'field' }, 'Matches of agents at once, each in a process of its own', concurrency),
            h('label', { class: 'field' }, 'Goals of a match awarded by forfeit', forfeit),
            h('p', { class: 'muted small' }, 'Stages holds every setting of each stage, and a stage setting overrides these.'));
    }

    select(options, value, label, onChange) {
        const select = h('select', { 'aria-label': label }, options.map(([v, t]) => h('option', { value: v }, t)));
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
        const box = h('input', { type: 'checkbox', checked: on, 'aria-label': `Set ${field.label.toLowerCase()}` });
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
        return h('span', { class: 'cup-optional' }, h('label', { class: 'check' }, box, 'Set'), input, shown);
    }

    stagesStep() {
        const d = this.draft;
        const stages = d.stages.map((stage, index) => this.stageCard(stage, index));
        const json = h('textarea', { class: 'cup-json', rows: '14', spellcheck: 'false', 'aria-label': 'The stages and defaults as JSON' },
            JSON.stringify({ defaults: d.defaults, stages: d.stages }, null, 2));
        const applied = h('p', { class: 'muted small', role: 'status' });
        const apply = h('button', { type: 'button', class: 'btn', onclick: () => {
            try {
                const value = JSON.parse(json.value);
                if (!value || !Array.isArray(value.stages)) {
                    throw new Error('expected an object with a list of stages');
                }
                d.stages = value.stages;
                d.defaults = value.defaults || {};
                this.renderWizard();
                this.app.hud.toast('The stages follow the JSON.');
            } catch (err) {
                applied.textContent = `The JSON could not be used, ${err.message}`;
            }
        } }, 'Use this JSON');
        return [
            h('p', { class: 'muted' }, 'Each stage seeds the next, which takes those who advance. A setting left alone takes the tournament default or the format default.'),
            h('div', { class: 'cup-stages' }, stages),
            h('button', { type: 'button', class: 'btn', disabled: d.stages.length >= 8, onclick: () => {
                d.stages.push({ format: 'knockout', name: `Stage ${d.stages.length + 1}` });
                this.renderWizard();
            } }, 'Add a stage'),
            h('details', { class: 'cup-json-box' }, h('summary', {}, 'Edit as JSON'), json, h('div', { class: 'row' }, apply), applied),
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
            h('legend', {}, `Stage ${index + 1}, ${FORMAT_NAMES[format] || format}`),
            h('div', { class: 'cup-stage-fields' }, rows),
            h('div', { class: 'row' },
                h('button', { type: 'button', class: 'btn small ghost', disabled: index === 0, onclick: () => move(-1) }, 'Move earlier'),
                h('button', { type: 'button', class: 'btn small ghost', disabled: last, onclick: () => move(1) }, 'Move later'),
                h('button', { type: 'button', class: 'btn small ghost danger', disabled: d.stages.length === 1, onclick: () => {
                    d.stages.splice(index, 1);
                    this.renderWizard();
                } }, 'Remove stage')));
    }

    stageField(stage, merged, field, index) {
        const set = (value) => {
            stage[field.key] = value;
        };
        const label = `${field.label}, stage ${index + 1}`;
        let control;
        const value = merged[field.key];
        if (field.type === 'text') {
            control = h('input', { type: 'text', maxlength: '60', value: value || '', 'aria-label': label });
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
            control = h('label', { class: 'check' }, control, 'On');
        } else if (field.type === 'points') {
            const points = { ...value };
            control = h('span', { class: 'cup-points' }, ['win', 'draw', 'loss'].map((name) => {
                const input = h('input', { type: 'number', min: '-100', max: '100', step: '1', value: String(points[name]), 'aria-label': `Points for a ${name}, stage ${index + 1}` });
                input.addEventListener('input', () => {
                    points[name] = Number(input.value);
                    set({ ...points });
                });
                return h('label', { class: 'field small-field' }, name[0].toUpperCase() + name.slice(1), input);
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
            const box = h('input', { type: 'checkbox', checked: fill, 'aria-label': `Enough to fill a bracket, stage ${index + 1}` });
            const input = h('input', { type: 'number', min: '0', max: '128', step: '1', value: fill ? '0' : String(value || 0), disabled: fill, 'aria-label': label });
            const sync = () => {
                input.disabled = box.checked;
                set(box.checked ? 'fill' : Number(input.value));
            };
            box.addEventListener('change', sync);
            input.addEventListener('input', sync);
            control = h('span', { class: 'cup-optional' }, input, h('label', { class: 'check' }, box, 'Enough to fill a bracket'));
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
                const box = h('input', { type: 'checkbox', checked: on || name === 'lots', disabled: name === 'lots', 'aria-label': `Use ${field.names[name]}` });
                box.addEventListener('change', () => {
                    if (box.checked) {
                        chosen.push(name);
                    } else {
                        chosen.splice(chosen.indexOf(name), 1);
                    }
                    commit();
                });
                const up = name === 'lots' ? null : h('button', { type: 'button', class: 'btn small ghost', disabled: i === 0, 'aria-label': `Move ${field.names[name]} earlier`, onclick: () => {
                    [order[i - 1], order[i]] = [order[i], order[i - 1]];
                    commit();
                    draw(`up-${name}`);
                } }, 'Earlier');
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
        const host = h('div', { class: 'cup-review', 'aria-busy': 'true' }, h('p', { class: 'muted' }, 'Checking the tournament.'));
        const saveName = h('input', { type: 'text', placeholder: 'my_format', pattern: '[a-z0-9][a-z0-9_-]*', 'aria-label': 'Name of the preset, small letters, digits, dashes and underscores' });
        const saveTitle = h('input', { type: 'text', maxlength: '60', placeholder: 'Title', value: this.draft.name, 'aria-label': 'Title of the preset' });
        const save = h('div', { class: 'cup-save' },
            h('h3', {}, 'Save the format as a preset'),
            h('div', { class: 'row' }, saveName, saveTitle, h('button', { type: 'button', class: 'btn', onclick: () => this.savePreset(saveName.value.trim(), saveTitle.value.trim()) }, 'Save preset')));
        this.check(host);
        return [host, save];
    }

    config() {
        const d = this.draft;
        const config = {
            name: (d.name || '').trim() || 'Tournament', seeding: d.seeding, concurrency: d.concurrency,
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
            const parts = [h('p', {}, `${entrants.length} entrants, seed ${preview.config.seed}, ${preview.matches} matches known before any result.`)];
            this.draft.seed = String(preview.config.seed);
            preview.stages.forEach((stage, index) => {
                const settings = preview.config.stages[index];
                parts.push(h('section', { class: 'cup-review-stage' },
                    h('h3', {}, `${index + 1}. ${settings.name}`),
                    h('p', { class: 'muted small' }, [
                        stageText(settings), `${settings.entrants} entrants`, index < preview.stages.length - 1 ? `${settings.advance} advance` : null,
                        scenarioName(settings.scenario), settings.length ? `${settings.length} steps a match` : null,
                    ].filter(Boolean).join(', ')),
                    stage.tables && stage.tables.length && settings.format === 'groups'
                        ? h('div', { class: 'cup-review-groups' }, stage.tables.map((table) => h('div', {},
                            h('h4', {}, table.name), h('ul', {}, table.rows.map((row) => h('li', {}, entrants[row.entrant].name))))))
                        : null,
                    stage.rounds && stage.rounds.length && settings.format !== 'groups'
                        ? h('div', {}, h('h4', {}, stage.rounds[0].name), h('ul', { class: 'cup-review-draw' },
                            stage.rounds[0].fixtures.slice(0, 32).map((f) => h('li', {}, `${sideName(f.home, entrants)} against ${sideName(f.away, entrants)}`))))
                        : null));
            });
            host.replaceChildren(...parts);
        } catch (err) {
            host.setAttribute('aria-busy', 'false');
            host.replaceChildren(h('div', { class: 'notice error', role: 'alert' }, h('p', {}, err.message),
                h('p', { class: 'muted small' }, 'Change the setting that the message names, in Entrants, Settings or Stages.')));
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
            this.app.hud.toast(`Saved the preset ${saved.title}.`);
        } catch (err) {
            this.app.hud.toast(err.message, 'error', 7000);
        }
    }

    async create(button) {
        button.disabled = true;
        try {
            const entry = await tournamentsApi.create(this.config());
            this.app.hud.toast(`${entry.name} has started.`);
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
        const t = this.current;
        if (!t || this.mode !== 'view') {
            return;
        }
        const entrants = t.config.entrants;
        this.matchMap = new Map(t.matches.map((m) => [m.key, m]));
        if (this.stageTab === null || this.stageTab >= t.stages_view.length) {
            const playing = t.stages_view.findIndex((s) => s.state !== 'done');
            this.stageTab = playing >= 0 ? playing : t.stages_view.length - 1;
        }
        const share = progressShare(t);
        const actions = [];
        if (t.state === 'running') {
            actions.push(h('button', { type: 'button', class: 'btn ghost danger', 'data-focus': 'act-cancel', onclick: () => this.act('cancel', 'The tournament is canceled.') }, 'Cancel tournament'));
        }
        if (t.state === 'stopped') {
            actions.push(h('button', { type: 'button', class: 'btn primary', 'data-focus': 'act-resume', onclick: () => this.act('resume', 'The tournament runs again.') }, 'Resume'));
        }
        if (t.state === 'done') {
            actions.push(h('button', { type: 'button', class: 'btn primary', 'data-focus': 'act-ceremony', onclick: () => this.ceremony() }, 'Trophy ceremony'));
        }
        actions.push(h('button', { type: 'button', class: 'btn ghost', onclick: () => {
            const config = clone(t.config);
            this.startWizard(config);
            this.draft.seed = '';
        } }, 'Run again'));
        if (t.state !== 'running') {
            actions.push(h('button', { type: 'button', class: 'btn ghost danger', 'data-focus': 'act-delete', onclick: () => this.remove() }, 'Delete'));
        }
        const head = h('header', { class: 'cup-head' },
            h('h2', { tabindex: '-1' }, t.name),
            h('p', { class: 'cup-meta' },
                h('span', { class: `state-pill ${t.state === 'running' ? 'running' : t.state === 'done' ? 'done' : 'failed'}` }, STATE_LABELS[t.state] || t.state),
                h('span', {}, `${entrants.length} entrants`),
                h('span', {}, `seed ${t.seed}`),
                h('span', {}, `${t.played} of ${t.scheduled} scheduled matches played`),
                t.running ? h('span', {}, `${t.running} playing now`) : null),
            t.state === 'running' ? h('div', { class: 'progress', role: 'progressbar', 'aria-label': 'Matches played', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round(share * 100)) },
                h('div', { class: 'bar', style: `width:${Math.round(share * 100)}%` })) : null,
            t.champion ? h('p', { class: 'cup-champion' }, h('span', {}, `Champion, ${t.champion}`)) : null,
            t.error ? h('div', { class: 'notice error', role: 'alert' }, h('p', {}, t.error)) : null,
            t.persistence_error ? h('div', { class: 'notice error' }, h('p', {}, t.persistence_error)) : null,
            t.owner ? h('p', { class: 'muted small' }, `Another process, ${t.owner}, runs this tournament, so this page follows it.`) : null,
            h('div', { class: 'row cup-actions' }, actions));
        const people = t.matches.filter((m) => ['person', 'playing'].includes(m.state));
        const peopleBox = people.length ? h('section', { class: 'cup-people', 'aria-labelledby': 'cup-people-title' },
            h('h3', { id: 'cup-people-title' }, 'Matches for people'),
            h('ul', {}, people.map((m) => h('li', {},
                h('span', {}, `${m.label}, ${entrants[m.home].name} against ${entrants[m.away].name}, ${scenarioName(m.scenario)}`),
                m.note ? h('span', { class: 'muted small' }, m.note) : null,
                m.state === 'playing' ? h('span', { class: 'muted small' }, 'Playing on the Play page.')
                    : h('span', { class: 'row' },
                        h('button', { type: 'button', class: 'btn small primary', 'data-focus': `people-${m.key}`, onclick: () => this.playMatch(m) }, icon('play'), 'Play now'),
                        this.forfeitButton(m, 'home'), this.forfeitButton(m, 'away')))))) : null;
        const tabs = h('div', { class: 'cup-tabs', role: 'tablist', 'aria-label': 'Stages' }, t.stages_view.map((stage, index) => h('button', {
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
                    this.stageTab = (index + by + t.stages_view.length) % t.stages_view.length;
                    this.renderView();
                    document.getElementById(`cup-tab-${this.stageTab}`)?.focus();
                }
            },
        }, `${stage.name}`, h('span', { class: 'muted small' }, ` ${FORMAT_NAMES[stage.format] || stage.format}`))));
        const stage = t.stages_view[this.stageTab];
        const panel = h('div', { class: 'cup-stage-view', id: 'cup-stage-panel', role: 'tabpanel', 'aria-labelledby': `cup-tab-${this.stageTab}` },
            this.stageView(stage, t.config.stages[this.stageTab]));
        const ranking = t.ranking ? h('section', { class: 'cup-ranking', 'aria-labelledby': 'cup-ranking-title' },
            h('h3', { id: 'cup-ranking-title' }, 'Final ranking'),
            h('ol', {}, t.ranking.map((e) => h('li', {}, entrants[e].name)))) : null;
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

    forfeitButton(match, side) {
        const entrants = this.current.config.entrants;
        const winner = entrants[side === 'home' ? match.home : match.away].name;
        return h('button', { type: 'button', class: 'btn small ghost', 'data-focus': `award-${match.key}-${side}`, onclick: async () => {
            try {
                this.current = await tournamentsApi.action(this.current.id, 'forfeit', { key: match.key, winner: side });
                this.app.hud.toast(`${match.label} is awarded to ${winner}.`);
                this.renderView();
            } catch (err) {
                this.app.hud.toast(err.message, 'error', 7000);
            }
        } }, `Award to ${winner}`);
    }

    stageView(stage, settings) {
        const entrants = this.current.config.entrants;
        const parts = [h('p', { class: 'muted small' }, [
            stageText(settings), scenarioName(settings.scenario), settings.length ? `${settings.length} steps a match` : null,
            stage.state === 'waiting' ? 'Waiting for the stage before it' : null,
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
            parts.push(h('section', { class: 'cup-fixtures', 'aria-label': 'Fixtures and results' },
                h('h3', {}, 'Fixtures and results'),
                stage.rounds.map((round) => h('div', { class: 'cup-round' },
                    h('h4', {}, round.name + (round.bye != null ? `, bye for ${entrants[round.bye].name}` : '') + (round.king != null ? `, king ${entrants[round.king].name}` : '')),
                    h('ul', {}, round.fixtures.map((f) => h('li', {}, this.fixture(f))))))));
        }
        return parts;
    }

    bracket(section) {
        const layout = bracketLayout(section.rounds);
        const byId = new Map(section.rounds.flatMap((r) => r.fixtures).map((f) => [f.id, f]));
        const grid = h('div', {
            class: 'cup-bracket', role: 'list',
            style: `grid-template-columns: repeat(${layout.columns}, minmax(190px, 1fr)); grid-template-rows: auto repeat(${layout.rows}, minmax(32px, auto));`,
        });
        section.rounds.forEach((round, column) => {
            grid.append(h('div', { class: 'cup-bracket-round', role: 'presentation', style: `grid-column:${column + 1}; grid-row:1` }, round.name));
        });
        layout.cells.flat().forEach((cell) => {
            const box = h('div', { class: 'cup-bracket-cell', role: 'listitem', style: `grid-column:${cell.column}; grid-row:${cell.rowStart + 1} / ${cell.rowEnd + 1}` },
                this.fixture(byId.get(cell.id), true));
            grid.append(box);
        });
        return h('section', { class: 'cup-bracket-section', 'aria-label': SECTION_NAMES[section.name] || section.name },
            h('h3', {}, SECTION_NAMES[section.name] || section.name), h('div', { class: 'cup-bracket-scroll', tabindex: '0', 'aria-label': `${SECTION_NAMES[section.name] || section.name}, scrolls sideways` }, grid));
    }

    fixture(f, compact = false) {
        const t = this.current;
        const entrants = t.config.entrants;
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
        const label = f.label || '';
        return h('div', { class: `cup-fixture state-${state}`, 'aria-label': `${label} ${sideName(f.home, entrants)} against ${sideName(f.away, entrants)}, ${STATE_NAMES[state] || state}` },
            compact && label ? h('span', { class: 'cup-fixture-label small muted' }, label) : null,
            side(f.home, 0), side(f.away, 1),
            h('span', { class: 'cup-fixture-meta small muted' },
                [decided, state !== 'done' ? STATE_NAMES[state] : null,
                    running ? `${Math.round((running.progress || 0) * 100)} percent` : null,
                    f.group ? `Group ${f.group}` : null,
                    matches.some((m) => m.result && m.result.forfeit) ? 'awarded' : null,
                    matches.find((m) => m.state === 'failed')?.error || null].filter(Boolean).join(', ')),
            watch.length ? h('span', { class: 'cup-watch row' }, watch.map((m, i) => h('button', {
                type: 'button', class: 'btn small ghost', 'data-focus': `watch-${m.key}`, 'aria-label': `Watch ${m.label}, ${entrants[m.home].name} against ${entrants[m.away].name}`,
                onclick: () => this.app.openMatchInWatch(m.result.match),
            }, icon('play'), watch.length > 1 ? `Watch ${i + 1}` : 'Watch'))) : null,
            matches.some((m) => m.state === 'person') ? h('button', { type: 'button', class: 'btn small primary', 'data-focus': `play-${f.id}`, onclick: () => this.playMatch(matches.find((m) => m.state === 'person')) }, 'Play now') : null);
    }

    table(table, stage, settings) {
        const entrants = this.current.config.entrants;
        const swiss = stage.format === 'swiss';
        const king = stage.format === 'king_of_the_hill';
        const head = ['Place', 'Entrant', 'Played', 'Won', 'Drawn', 'Lost', 'For', 'Against', 'Difference', 'Points'];
        if (swiss) {
            head.push('Buchholz');
        }
        if (king) {
            head.push('Ties won');
        }
        const notes = [];
        const rows = table.rows.map((row, index) => {
            const next = table.rows[index + 1];
            const reason = tiebreakText(row, next, entrants);
            if (reason) {
                notes.push(h('li', {}, `${entrants[row.entrant].name}. ${reason}.`));
            }
            const qualified = index < table.qualify || row.best;
            const cells = [row.position, entrants[row.entrant].name, row.played, row.won, row.drawn, row.lost, row.for, row.against, row.difference, row.points];
            if (swiss) {
                cells.push(row.buchholz);
            }
            if (king) {
                cells.push(row.titles);
            }
            return h('tr', { class: qualified && stage.index < this.current.config.stages.length - 1 ? 'qualified' : '' },
                cells.map((value, i) => (i === 1 ? h('th', { scope: 'row' }, String(value), row.best ? h('span', { class: 'muted small' }, ', best of its place') : null) : h('td', {}, String(value)))));
        });
        const ordered = settings.tiebreakers.map((name) => TIEBREAK_NAMES[name]).join(', then ');
        return h('section', { class: 'cup-table' },
            h('h3', {}, table.name),
            h('div', { class: 'cup-table-scroll', tabindex: '0', 'aria-label': `${table.name} table, scrolls sideways` },
                h('table', {}, h('caption', { class: 'muted small' }, `Ordered by points, then ${ordered}.`),
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
        const t = this.current;
        if (!window.confirm(`Delete ${t.name}? Its recordings stay in Recordings.`)) {
            return;
        }
        try {
            await tournamentsApi.remove(t.id);
            this.mode = 'empty';
            this.openId = null;
            this.current = null;
            await this.refresh();
        } catch (err) {
            this.app.hud.toast(err.message, 'error');
        }
    }

    async playMatch(match) {
        const t = this.current;
        const app = this.app;
        try {
            const entry = await tournamentsApi.action(t.id, 'play', { key: match.key });
            const { PlayPage } = await import('./play.js');
            app.play = app.play || new PlayPage(app);
            const id = t.id;
            app.play.begin(entry, match.persons, {
                label: `${t.name}, ${match.label}`,
                back: () => {
                    app.showPage('tournaments');
                    this.open(id);
                },
            });
            app.showPage('play');
        } catch (err) {
            app.hud.toast(err.status === 409 ? 'A game is already playing. Quit it first.' : err.message, 'error', 7000);
        }
    }

    // The trophy ceremony, the podium and confetti of the show after a match, in the colors of the
    // champion, over the last match the champion played that has a recording.
    async ceremony() {
        const t = this.current;
        const app = this.app;
        const champion = t.champion_index;
        const played = t.matches.filter((m) => m.result && m.result.match && !m.decider && (m.home === champion || m.away === champion));
        const last = played[played.length - 1];
        if (!last) {
            app.hud.toast(`${t.champion} won ${t.name}, with no recording of a match to hold the ceremony in.`, 'info', 7000);
            return;
        }
        await app.openMatch(last.result.match);
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
        const runnerUp = t.ranking && t.ranking.length > 1 ? t.config.entrants[t.ranking[1]].name : null;
        app.podium.show(null, {
            team: last.home === champion ? 0 : 1,
            title: t.champion,
            subtitle: `Champions of ${t.name}${runnerUp ? `, ahead of ${runnerUp}` : ''}`,
        });
    }

    // Live progress, and a notice when a match of a person is ready.
    async poll() {
        if (document.hidden || document.body.classList.contains('offline')) {
            return;
        }
        const busy = this.list.some((t) => t.state === 'running');
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
        for (const t of list) {
            const key = `${t.id}|${t.people_waiting}`;
            if (t.people_waiting && !this.announced.has(key)) {
                this.announced.add(key);
                this.app.hud.toast(`${t.name} has a match ready for a person${this.visible ? '.' : ', open it from Tournaments.'}`, 'info', 6000);
            }
            const old = this.list.find((x) => x.id === t.id);
            if (old && old.state !== 'done' && t.state === 'done') {
                this.app.hud.toast(`${t.name} is won by ${t.champion}.`, 'info', 7000);
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
            const summary = list.find((t) => t.id === this.openId);
            if (summary && (changed || summary.running) && !this.mainHost.contains(document.activeElement?.closest('input, select, textarea'))) {
                await this.load(this.openId);
            }
        }
    }
}
