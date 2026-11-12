// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The parts of the Tournaments page for strict rules, the random entrant, the pre-flight check,
// more legs and the results. The wizard gains the switch of strict rules with their limits, the
// switch of the pre-flight, an adder of the random entrant and a pre-flight that runs from the
// review. A tournament shows its rules and its pre-flight in its head with the entrants that were
// left out, an Add legs control for a league or groups, and a Results section with the ratings
// and their intervals, the matrix of mean goal difference as a heat table and the files to save.
// tournament.js calls each part, so the page itself changes in a few places alone.

import { formatNumber, serverText, t } from '../core/i18n.js';
import { el as h } from '../core/menu.js';
import { icon } from '../core/icons.js';
import { spoilerFree } from '../core/spoilers.js';
import { jsonCall } from '../teams/team-check.js';
import { entrantName } from './tournament-layout.js';
import {
    RESULT_FILES, STRICT_DEFAULTS, STRICT_FLAGS, STRICT_FLAG_KEYS, STRICT_KEYS, STRICT_RANGES, STRICT_STEPS, STRICT_UNITS, analysisStamp, cellName,
    checkSides, entrantKey, fileAddress, folderText, intervalBar, intervalWords, legsRoom, limitNumber, limitsText,
    matrixCells, matrixOrder, methodText, playedText, preflightText, ratingScale, ratingText, ruleReason, sideText,
    signedMean, strictLimits, strictProblems, timingsText, warningTexts, withIncluded, withoutIncluded,
} from './tournament-results.js';

const enc = encodeURIComponent;

export const strictApi = {
    analysis: (id) => jsonCall('GET', `/api/tournaments/${enc(id)}/analysis`),
    preflight: (config) => jsonCall('POST', '/api/tournaments/preflight', { config }),
    addLegs: (id, legs) => jsonCall('POST', `/api/tournaments/${enc(id)}/legs`, { legs }),
};

// The symbol of an entrant's kind in the wizard, a letter for a person and the built-in AI and
// the dice for the random entrant.
export function kindGlyph(kind) {
    if (kind === 'random') {
        return icon('dice', 'icon text-symbol');
    }
    return kind === 'person' ? t('tournament.entrant.glyph.person') : t('tournament.entrant.glyph.builtin');
}

// The name of the random entrant as the server makes it.
export function randomName() {
    return t('server.tournament.label.random');
}

// The setup.

// Takes the strict rules, the pre-flight and the added entrants of a preset into a draft, and
// shows the added entrants in its list. Entrants that an earlier preset added leave the list
// unless this one adds them too.
export function applyPreset(draft, preset) {
    draft.strict = preset.strict ?? null;
    draft.preflight = !!preset.preflight;
    draft.include = JSON.parse(JSON.stringify(preset.include || []));
    const keys = new Set(draft.include.map(entrantKey));
    draft.entrants = draft.entrants.filter((entry) => !entry.included || keys.has(entrantKey(entry)));
    const before = draft.entrants.length;
    draft.entrants = withIncluded(draft.entrants, draft.include).slice(0, 256);
    for (const entry of draft.entrants.slice(before)) {
        entry.included = true;
    }
}

// Takes the strict rules, the pre-flight and the added entrants of a tournament run again into
// its draft, the added entrants marked as such in its list.
export function fromConfig(draft, config) {
    draft.strict = config.strict ?? null;
    draft.preflight = !!config.preflight;
    draft.include = JSON.parse(JSON.stringify(config.include || []));
    const keys = new Set(draft.include.map(entrantKey));
    for (const entry of draft.entrants) {
        if (keys.has(entrantKey(entry))) {
            entry.included = true;
        }
    }
}

// Drops an entrant of the list from the entrants a draft adds, so the server does not add it back.
export function removedEntrant(draft, entry) {
    draft.include = withoutIncluded(draft.include, entry);
}

// The strict rules, the pre-flight and the added entrants of a draft, for its configuration and
// for a preset saved from it.
export function strictConfig(draft) {
    const out = {};
    if (draft.strict !== null && draft.strict !== undefined && draft.strict !== false) {
        out.strict = draft.strict;
    }
    if (draft.preflight) {
        out.preflight = true;
    }
    if (draft.include && draft.include.length) {
        out.include = draft.include;
    }
    return out;
}

// The adder of the random entrant, one player taking random actions, beside the built-in AI.
export function randomAdder(draft, add, toast) {
    return h('div', { class: 'cup-adder cup-adder-random' },
        h('span', { class: 'field' }, h('span', {}, t('tournament.entrants.random')),
            h('span', { class: 'muted small', id: 'cup-random-note' }, t('tournament.entrants.random.note'))),
        h('button', {
            type: 'button', class: 'btn', 'aria-label': t('tournament.entrants.random.add'), title: t('tournament.entrants.random.add'),
            'aria-describedby': 'cup-random-note', 'data-symbol': '', 'data-focus': 'add-random',
            onclick: () => {
                if (draft.entrants.some((entry) => entry.kind === 'random')) {
                    toast(t('tournament.entrants.random.in'));
                    return;
                }
                add({ kind: 'random' });
            },
        }, icon('plus')));
}

// The switch of strict rules with the box of each limit and its unit, and the switch of the
// pre-flight, for the settings of the wizard.
export function strictFields(draft) {
    const on = draft.strict !== null && draft.strict !== undefined && draft.strict !== false;
    const limits = strictLimits(on ? draft.strict : true);
    const box = h('input', { type: 'checkbox', role: 'switch', class: 'cup-strict-switch', checked: on, 'aria-describedby': 'cup-strict-note' });
    const boxes = {};
    const fields = STRICT_KEYS.map((key) => {
        const [lowest, highest] = STRICT_RANGES[key];
        const unit = STRICT_UNITS[key];
        const label = t(`tournament.strict.field.${key}`);
        const range = t('tournament.strict.range', { lowest: limitNumber(lowest), highest: limitNumber(highest) });
        const note = h('span', { class: 'muted small cup-strict-range', id: `cup-strict-${key}-range` }, range);
        const input = h('input', {
            type: 'number', min: String(lowest), max: String(highest), step: String(STRICT_STEPS[key]), value: String(limits[key]),
            disabled: !on, 'data-limit': key, 'aria-describedby': `cup-strict-${key}-range`,
            'aria-label': unit === 'threads' ? label : t('tournament.strict.field.label', { label, unit: t(`tournament.strict.unit.${unit}`) }),
        });
        boxes[key] = input;
        input.addEventListener('input', () => {
            const value = input.value.trim() === '' ? NaN : Number(input.value);
            const given = draft.strict && typeof draft.strict === 'object' ? { ...draft.strict } : strictLimits(true);
            given[key] = value;
            draft.strict = given;
            const bad = strictProblems(strictLimits(given)).includes(key);
            if (bad) {
                input.setAttribute('aria-invalid', 'true');
            } else {
                input.removeAttribute('aria-invalid');
            }
        });
        return h('label', { class: 'field small-field cup-strict-limit' }, h('span', {}, label),
            h('span', { class: 'cup-unit' }, input, unit === 'threads' ? null : h('span', { class: 'muted', 'aria-hidden': 'true' }, t(`tournament.strict.unitShort.${unit}`))),
            note);
    });
    // Each switch of the rules, such as frozen team folders, with what it does beside it.
    const flags = STRICT_FLAG_KEYS.map((key) => {
        const input = h('input', { type: 'checkbox', checked: !!limits[key], disabled: !on, 'data-flag': key, 'aria-describedby': `cup-strict-${key}-note` });
        boxes[key] = input;
        input.addEventListener('change', () => {
            const given = draft.strict && typeof draft.strict === 'object' ? { ...draft.strict } : strictLimits(true);
            given[key] = input.checked;
            draft.strict = given;
        });
        return h('div', { class: 'cup-strict-flag' }, h('label', { class: 'check' }, input, t(`tournament.strict.field.${key}`)),
            h('span', { class: 'muted small', id: `cup-strict-${key}-note` }, t(`tournament.strict.flagNote.${key}`)));
    });
    box.addEventListener('change', () => {
        draft.strict = box.checked ? strictLimits(true) : null;
        for (const key of STRICT_KEYS) {
            boxes[key].disabled = !box.checked;
            boxes[key].value = String(STRICT_DEFAULTS[key]);
            boxes[key].removeAttribute('aria-invalid');
        }
        for (const key of STRICT_FLAG_KEYS) {
            boxes[key].disabled = !box.checked;
            boxes[key].checked = STRICT_FLAGS[key];
        }
    });
    const pre = h('input', { type: 'checkbox', role: 'switch', class: 'cup-preflight-switch', checked: !!draft.preflight, 'aria-describedby': 'cup-preflight-note' });
    pre.addEventListener('change', () => {
        draft.preflight = pre.checked;
    });
    return h('fieldset', { class: 'cup-strict' },
        h('legend', {}, t('tournament.strict.title')),
        h('label', { class: 'check' }, box, t('tournament.strict.switch')),
        h('p', { class: 'muted small', id: 'cup-strict-note' }, t('tournament.strict.note')),
        h('div', { class: 'cup-strict-limits' }, fields),
        h('div', { class: 'cup-strict-flags' }, flags),
        h('label', { class: 'check' }, pre, t('tournament.preflight.switch')),
        h('p', { class: 'muted small', id: 'cup-preflight-note' }, t('tournament.preflight.note')));
}

// The pre-flights that a review ran, by draft, each with the configuration it checked, whether it
// still runs, and its answer or error.
const preflights = new WeakMap();

// The strict rules and the pre-flight of a draft for its review, and a button that runs the
// pre-flight now, which shows each team as passed or failed and those it would leave out.
export function strictReview(page) {
    const draft = page.draft;
    const limits = strictLimits(draft.strict);
    const teams = draft.entrants.filter((entry) => entry.kind === 'team').length;
    const host = h('div', { class: 'cup-preflight-result', role: 'status' });
    const button = h('button', {
        type: 'button', class: 'btn cup-preflight-run', 'data-focus': 'preflight-run', disabled: !teams,
        onclick: () => runPreflight(page, draft),
    }, icon('speed'), t('tournament.preflight.run'));
    const section = h('section', { class: 'cup-review-strict', 'aria-labelledby': 'cup-review-strict-title' },
        h('h3', { id: 'cup-review-strict-title' }, t('tournament.strict.title')),
        h('p', { class: 'small cup-review-limits' }, limits ? t('tournament.strict.summary', { limits: limitsText(limits) }) : t('tournament.strict.none')),
        draft.preflight ? h('p', { class: 'small' }, t('tournament.preflight.review')) : null,
        draft.entrants.some((entry) => entry.kind === 'random') ? h('p', { class: 'small muted' }, t('tournament.entrants.random.note')) : null,
        h('div', { class: 'row' }, button),
        teams ? null : h('p', { class: 'muted small' }, t('tournament.preflight.none')),
        host);
    drawPreflight(host, button, draft, page.config());
    return section;
}

async function runPreflight(page, draft) {
    const config = page.config();
    const stamp = JSON.stringify(config);
    const known = preflights.get(draft);
    if (known && known.busy) {
        return;
    }
    preflights.set(draft, { stamp, busy: true, teams: new Set(draft.entrants.filter((e) => e.kind === 'team').map((e) => e.team)).size });
    redrawPreflight(page, draft);
    let found;
    try {
        found = { stamp, report: await strictApi.preflight(config) };
    } catch (err) {
        found = { stamp, error: err.message };
    }
    preflights.set(draft, found);
    redrawPreflight(page, draft);
}

// Draws the answer of a pre-flight into the review that shows now, if the person is still there.
function redrawPreflight(page, draft) {
    if (page.mode !== 'wizard' || page.draft !== draft) {
        return;
    }
    const host = page.mainHost.querySelector('.cup-preflight-result');
    const button = page.mainHost.querySelector('.cup-preflight-run');
    if (host && button) {
        drawPreflight(host, button, draft, page.config());
    }
}

function drawPreflight(host, button, draft, config) {
    const run = preflights.get(draft);
    host.removeAttribute('aria-busy');
    button.removeAttribute('aria-disabled');
    if (!run) {
        host.replaceChildren();
        return;
    }
    if (run.busy) {
        host.setAttribute('aria-busy', 'true');
        button.setAttribute('aria-disabled', 'true');
        host.replaceChildren(h('p', { class: 'small' }, icon('running', 'icon text-symbol'), t('tournament.preflight.running', { count: run.teams })));
        return;
    }
    const stale = run.stamp !== JSON.stringify(config) ? h('p', { class: 'muted small' }, icon('warning', 'icon text-symbol'), t('tournament.preflight.stale')) : null;
    if (run.error) {
        host.replaceChildren(h('div', { class: 'notice error' }, h('p', {}, run.error)), stale);
        return;
    }
    const report = run.report;
    const excluded = report.excluded || [];
    host.replaceChildren(
        h('ul', { class: 'cup-checks symbol-list small' }, (report.checks || []).map(checkItem)),
        h('p', { class: 'small' }, excluded.length
            ? t('tournament.preflight.leftOut', { count: excluded.length, names: excluded.map((e) => serverText(e, 'name')).join(', ') })
            : t('tournament.preflight.allPass')),
        stale);
}

// A team's check as an item of a list, passed or failed with its reason, then each side it
// played with its timings, the size of its folder and its warnings. A check that a tournament
// keeps has no sides, so its timings follow its state.
export function checkItem(check) {
    const sides = checkSides(check);
    const timings = sides.length ? '' : timingsText(check.timings);
    const folder = folderText(check);
    const warnings = warningTexts(check);
    return h('li', { class: check.ok ? 'passed' : 'failed' },
        icon(check.ok ? 'done' : 'failed', 'icon text-symbol'),
        h('span', {}, h('strong', {}, serverText(check, 'name') || check.team), ', ',
            check.ok ? t('tournament.preflight.passed') : t('tournament.preflight.failed', { reason: ruleReason(check.rule) }),
            timings ? h('span', { class: 'muted' }, `, ${timings}`) : null,
            folder ? h('span', { class: 'muted' }, `, ${folder}`) : null),
        sides.length || warnings.length ? h('ul', { class: 'cup-check-sides symbol-list' },
            sides.map((side) => h('li', { class: side.skipped ? 'skipped' : side.ok ? 'passed' : 'failed' }, sideText(side))),
            warnings.map((text) => h('li', { class: 'warning' }, icon('warning', 'icon text-symbol'), text))) : null);
}

// The tournament view.

// The strict rules and the pre-flight of a tournament for its head, with the entrants that the
// pre-flight left out, their reasons and timings, and the checks of the other teams.
export function strictHead(cup) {
    const limits = cup.config && cup.config.strict ? strictLimits(cup.config.strict) : null;
    const state = cup.preflight ?? (cup.config && cup.config.preflight ? (cup.checks && cup.checks.length ? 'done' : 'waiting') : null);
    const excluded = cup.excluded || [];
    const checks = cup.checks || [];
    if (!limits && !state && !excluded.length) {
        return null;
    }
    const passed = checks.filter((check) => check.ok);
    return h('div', { class: 'cup-strict-head' },
        limits ? h('p', { class: 'small cup-strict-line' }, icon('clock', 'icon text-symbol'), t('tournament.strict.summary', { limits: limitsText(limits) })) : null,
        state ? h('p', { class: 'small cup-preflight-state' }, icon(state === 'done' ? 'done' : state === 'running' ? 'running' : 'waiting', 'icon text-symbol'),
            preflightText(state, cup.excluded_count ?? excluded.length)) : null,
        excluded.length ? h('section', { class: 'cup-excluded notice', 'aria-labelledby': 'cup-excluded-title' },
            h('h3', { id: 'cup-excluded-title' }, t('tournament.excluded.title')),
            h('ul', { class: 'symbol-list small' }, excluded.map((entry) => {
                const timings = timingsText(entry.timings);
                return h('li', {}, icon('failed', 'icon text-symbol'),
                    h('span', {}, h('strong', {}, serverText(entry, 'name')), ', ', serverText(entry, 'reason'),
                        timings ? h('span', { class: 'muted' }, `, ${timings}`) : null));
            }))) : null,
        passed.length ? checksBox(cup.id, passed) : null);
}

// The tournaments whose box of passed checks is open, so it stays open through the redraws.
const openChecks = new Set();

function checksBox(id, passed) {
    const box = h('details', { class: 'cup-checks-box small', open: openChecks.has(id) },
        h('summary', { 'data-focus': 'checks-box' }, t('tournament.checks.title', { count: passed.length })),
        h('ul', { class: 'cup-checks symbol-list' }, passed.map(checkItem)));
    box.addEventListener('toggle', () => {
        if (box.open) {
            openChecks.add(id);
        } else {
            openChecks.delete(id);
        }
    });
    return box;
}

// The control that adds legs to the last stage of a tournament, a league or groups, or null.
export function legsControl(page, cup) {
    const room = legsRoom(cup);
    if (!room) {
        return null;
    }
    const stages = cup.config.stages;
    const stage = serverText(stages[stages.length - 1], 'name');
    const input = h('input', { type: 'number', class: 'cup-legs-count', min: '1', max: String(room), step: '1', value: '1', 'data-focus': 'legs-count', 'aria-label': t('tournament.legs.label', { stage }) });
    const button = h('button', {
        type: 'button', class: 'btn ghost cup-legs-add', 'data-focus': 'legs-add',
        onclick: async () => {
            const legs = Number(input.value);
            if (!Number.isInteger(legs) || legs < 1 || legs > room) {
                input.setAttribute('aria-invalid', 'true');
                page.app.hud.toast(t('tournament.legs.range', { most: room }), 'error');
                input.focus();
                return;
            }
            button.disabled = true;
            page.focusAfter = 'legs-add';
            try {
                page.current = await strictApi.addLegs(cup.id, legs);
                page.app.hud.toast(t('tournament.legs.added', { count: legs }));
                await page.refresh();
            } catch (err) {
                page.app.hud.toast(err.message, 'error', 7000);
                button.disabled = false;
            }
        },
    }, icon('plus'), t('tournament.legs.add'));
    return h('span', { class: 'cup-legs row', role: 'group', 'aria-label': t('tournament.legs.group', { stage }) }, input, button);
}

// The results of a tournament, kept by page, one node that moves into each redraw of the view.
const views = new WeakMap();

// The Results section of a tournament's view, the same node at each redraw.
export function resultsSection(page, cup) {
    let view = views.get(page);
    if (!view) {
        view = new ResultsView(page);
        views.set(page, view);
    }
    return view.update(cup);
}

class ResultsView {
    constructor(page) {
        this.page = page;
        this.id = null;
        this.open = false;
        this.data = null;
        this.stamp = '';
        this.asked = '';
        this.error = null;
        this.drawn = '';
        this.toggle = h('button', {
            type: 'button', class: 'btn ghost cup-results-toggle', 'data-focus': 'results-toggle', 'aria-expanded': 'false', 'aria-controls': 'cup-results-body',
            onclick: () => {
                this.open = !this.open;
                this.update(this.cup);
            },
        }, icon('stats'), t('tournament.results.title'));
        this.body = h('div', { class: 'cup-results-body', id: 'cup-results-body' });
        this.node = h('section', { class: 'cup-results', 'aria-labelledby': 'cup-results-title' },
            h('h3', { id: 'cup-results-title' }, this.toggle), this.body);
    }

    // Brings the section up to date with the tournament, asking for the analysis again while the
    // results show and the tournament's played matches changed.
    update(cup) {
        this.cup = cup;
        if (cup.id !== this.id) {
            // Another tournament opens with its Results closed, so no ratings of the one before
            // stay in view, and its own load only once asked for.
            this.id = cup.id;
            this.open = false;
            this.data = null;
            this.stamp = '';
            this.asked = '';
            this.error = null;
            this.drawn = '';
            this.body.setAttribute('aria-busy', 'false');
        }
        this.toggle.setAttribute('aria-expanded', this.open ? 'true' : 'false');
        this.body.hidden = !this.open;
        const hidden = spoilerFree(cup.id);
        const stamp = analysisStamp(cup);
        if (this.open && !hidden && cup.played && stamp !== this.asked) {
            this.fetch(cup, stamp);
        }
        const drawn = JSON.stringify([this.open, hidden, cup.played > 0, this.stamp, !!this.error, this.asked === stamp]);
        if (drawn !== this.drawn) {
            this.drawn = drawn;
            this.draw(cup, hidden);
        }
        // A box that scrolls keeps its place as the section moves into the next redraw.
        const kept = [...this.body.querySelectorAll('[data-scroll]')].map((node) => [node, node.scrollLeft, node.scrollTop]);
        queueMicrotask(() => kept.forEach(([node, left, top]) => {
            node.scrollLeft = left;
            node.scrollTop = top;
        }));
        return this.node;
    }

    async fetch(cup, stamp) {
        this.asked = stamp;
        this.body.setAttribute('aria-busy', 'true');
        try {
            const found = await strictApi.analysis(cup.id);
            if (this.id !== cup.id) {
                return;
            }
            this.data = found;
            this.stamp = stamp;
            this.error = null;
        } catch (err) {
            if (this.id !== cup.id) {
                return;
            }
            this.error = err.message;
        }
        this.body.setAttribute('aria-busy', 'false');
        this.update(this.cup);
    }

    draw(cup, hidden) {
        if (!this.open) {
            this.body.replaceChildren();
            return;
        }
        if (hidden) {
            this.body.replaceChildren(h('p', { class: 'muted small' }, icon('eye', 'icon text-symbol'), t('tournament.results.spoilers')));
            return;
        }
        if (!cup.played) {
            this.body.replaceChildren(h('p', { class: 'muted small' }, t('tournament.results.none')));
            return;
        }
        if (this.error) {
            this.body.replaceChildren(h('div', { class: 'notice error' }, h('p', {}, this.error)));
            return;
        }
        if (!this.data) {
            this.body.replaceChildren(h('p', { class: 'muted small' }, t('tournament.results.loading')));
            return;
        }
        const entrants = cup.config.entrants;
        this.body.replaceChildren(
            h('div', { class: 'cup-results-summary small' }, h('p', {}, playedText(this.data)), h('p', { class: 'muted' }, methodText(this.data))),
            ratingsTable(this.data, entrants), matrixTable(this.data, entrants), filesList(cup));
    }
}

// The ratings, best first, each with its interval as a bar on one scale.
export function ratingsTable(data, entrants) {
    const rows = data.ratings || [];
    const scale = ratingScale(rows);
    const head = ['rank', 'entrant', 'rating', 'interval', 'low', 'high', 'matches'].map((name) => h('th', { scope: 'col' }, t(`tournament.results.column.${name}`)));
    const body = rows.map((row, index) => {
        const bar = intervalBar(row, scale);
        return h('tr', {},
            h('td', {}, formatNumber(index + 1)),
            h('th', { scope: 'row' }, entrantName(entrants[row.entrant])),
            h('td', {}, ratingText(row.rating)),
            h('td', { class: 'cup-interval-cell' }, h('span', { class: 'cup-interval', role: 'img', 'aria-label': intervalWords(row) },
                bar.centre === null ? null : h('span', { class: 'cup-interval-centre', style: `left:${bar.centre}%` }),
                h('span', { class: 'cup-interval-range', style: `left:${bar.left}%; width:${bar.width}%` }),
                h('span', { class: 'cup-interval-mark', style: `left:${bar.mark}%` }))),
            h('td', {}, ratingText(row.low)),
            h('td', {}, ratingText(row.high)),
            h('td', {}, formatNumber(row.matches)));
    });
    return h('section', { class: 'cup-ratings', 'aria-labelledby': 'cup-ratings-title' },
        h('h4', { id: 'cup-ratings-title' }, t('tournament.results.ratings')),
        h('div', { class: 'cup-ratings-scroll', tabindex: '0', 'data-scroll': '', 'data-focus': 'results-ratings', role: 'region', 'aria-label': t('tournament.results.ratings.scroll') },
            h('table', {}, h('caption', { class: 'muted small' }, t('tournament.results.ratings.caption', { count: data.resamples ?? 0 })),
                h('thead', {}, h('tr', {}, head)), h('tbody', {}, body))));
}

// The matrix of mean goal difference, row against column, as a heat table whose first column
// stays in place while the rest scrolls inside its own box.
export function matrixTable(data, entrants) {
    const order = matrixOrder(data.ratings, entrants.length);
    const rows = matrixCells(data.matrix, order);
    const names = entrants.map((entrant) => entrantName(entrant));
    const head = h('tr', {}, h('td', { class: 'cup-matrix-corner small muted' }, t('tournament.results.matrix.corner')),
        order.map((index) => h('th', { scope: 'col' }, names[index])));
    const body = rows.map((row) => h('tr', {},
        h('th', { scope: 'row' }, names[row.entrant]),
        row.cells.map((cell) => {
            const name = cellName(names[cell.row], names[cell.column], cell);
            return h('td', { class: `cup-heat heat-${cell.tone}${cell.level ? ` heat-${cell.tone}-${cell.level}` : ''}`, 'aria-label': name, title: name },
                cell.self || cell.tone === 'none' ? h('span', { class: 'muted', 'aria-hidden': 'true' }, t('tournament.results.cell.empty'))
                    : [h('span', { class: 'cup-heat-mean', 'aria-hidden': 'true' }, signedMean(cell.mean)),
                        h('span', { class: 'cup-heat-count small', 'aria-hidden': 'true' }, formatNumber(cell.matches))]);
        })));
    return h('section', { class: 'cup-matrix', 'aria-labelledby': 'cup-matrix-title' },
        h('h4', { id: 'cup-matrix-title' }, t('tournament.results.matrix')),
        h('div', { class: 'cup-matrix-scroll', tabindex: '0', 'data-scroll': '', 'data-focus': 'results-matrix', role: 'region', 'aria-label': t('tournament.results.matrix.scroll') },
            h('table', {}, h('caption', { class: 'muted small' }, t('tournament.results.matrix.caption')),
                h('thead', {}, head), h('tbody', {}, body))),
        h('p', { class: 'cup-heat-legend small muted' },
            h('span', { class: 'cup-heat-swatch heat-up-4', 'aria-hidden': 'true' }), t('tournament.results.legend.up'),
            h('span', { class: 'cup-heat-swatch heat-down-4', 'aria-hidden': 'true' }), t('tournament.results.legend.down')));
}

// The files of a tournament's results, each a link that saves it.
function filesList(cup) {
    return h('section', { class: 'cup-files', 'aria-labelledby': 'cup-files-title' },
        h('h4', { id: 'cup-files-title' }, t('tournament.results.files')),
        h('p', { class: 'muted small' }, t('tournament.results.files.note')),
        h('ul', { class: 'cup-file-list row' }, RESULT_FILES.map((name) => h('li', {},
            h('a', {
                class: 'btn small ghost', href: fileAddress(cup.id, name), download: `${cup.id}-${name}`, 'data-focus': `results-file-${name}`,
                'aria-label': t('tournament.results.file', { name }),
            }, icon('download'), name)))));
}
