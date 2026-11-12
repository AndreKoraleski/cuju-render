// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The check of a registered team under strict rules, on its card of the Teams page. The team
// loads in a process of its own and plays a few steps against the built-in AI within the default
// limits of strict rules, and the card says whether it passed, the rule it broke otherwise and its
// timings. The checks outlive the redraws of the list, so a check that runs keeps its card busy
// and its answer reaches the card that shows the team then.

import { serverText, t } from '../core/i18n.js';
import { el as h } from '../core/menu.js';
import { icon } from '../core/icons.js';
import { teamName } from '../core/names.js';
import { checkSides, folderText, ruleReason, sideText, timingsText, warningTexts } from '../play/tournament-results.js';

// A request to the server that answers JSON, which throws an error with the server's reason.
export async function jsonCall(method, path, json) {
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
        error.id = (body && body.error_id) || null;
        error.values = (body && body.error_values) || {};
        throw error;
    }
    return body;
}

// The checks by team, each busy, its report or its error, and the card that shows each team now.
const checks = new Map();
const cards = new Map();

// Fills the part of a card that holds the check of its team. A check that runs keeps its button,
// which says so and takes no click, so the focus stays on it until the answer.
function draw(node, team) {
    const check = checks.get(team.id) || null;
    const busy = !!check && check.busy;
    const button = h('button', {
        type: 'button', class: 'btn small ghost team-check-run', 'aria-disabled': busy ? 'true' : 'false',
        'aria-label': t('tournament.teamCheck.label', { name: teamName(team) }),
        onclick: (e) => {
            e.stopPropagation();
            run(team);
        },
    }, icon(busy ? 'running' : 'speed'), t(busy ? 'tournament.teamCheck.busy' : 'tournament.teamCheck.button'));
    const status = h('div', { class: 'team-check-status small', role: 'status', 'aria-busy': busy ? 'true' : 'false' });
    if (busy) {
        status.append(t('tournament.teamCheck.running'));
    } else if (check && check.error) {
        status.classList.add('failed');
        status.append(icon('failed', 'icon text-symbol'), check.error);
    } else if (check && check.report) {
        // The check plays the team on the left and then on the right, each side with its timings,
        // and names the size of its folder and any warning, which never fails the check.
        const report = check.report;
        const sides = checkSides(report);
        const timings = sides.length ? '' : timingsText(report.timings);
        const folder = folderText(report);
        const warnings = warningTexts(report);
        status.classList.add(report.ok ? 'passed' : 'failed');
        status.append(...[icon(report.ok ? 'done' : 'failed', 'icon text-symbol'),
            report.ok ? t('tournament.teamCheck.passed') : t('tournament.teamCheck.failed', { reason: ruleReason(report.rule) }),
            timings ? h('span', { class: 'muted team-check-timings' }, `, ${timings}`) : null,
            folder ? h('span', { class: 'muted' }, `, ${folder}`) : null,
            sides.length || warnings.length ? h('ul', { class: 'team-check-sides symbol-list' },
                sides.map((side) => h('li', { class: side.skipped ? 'skipped muted' : side.ok ? 'passed' : 'failed' }, sideText(side))),
                warnings.map((text) => h('li', { class: 'warning' }, icon('warning', 'icon text-symbol'), text))) : null].filter(Boolean));
    }
    node.replaceChildren(button, status);
}

// Runs the check of a team, once at a time, and draws its answer on the team's card.
async function run(team) {
    if (checks.get(team.id)?.busy) {
        return;
    }
    checks.set(team.id, { busy: true });
    redraw(team);
    let found;
    try {
        found = { report: await jsonCall('POST', `/api/teams/${encodeURIComponent(team.id)}/preflight`, {}) };
    } catch (err) {
        found = { error: err.message };
    }
    checks.set(team.id, found);
    redraw(team);
}

// Draws the card that shows a team now, and keeps the focus on its button when it held it.
function redraw(team) {
    const node = cards.get(team.id);
    if (!node || !node.isConnected) {
        return;
    }
    const had = node.contains(document.activeElement);
    draw(node, team);
    if (had) {
        node.querySelector('.team-check-run')?.focus();
    }
}

// The check of a team for its card, a button and the line of its answer.
export function teamCheck(team) {
    const node = h('div', { class: 'team-check', 'data-team': team.id });
    cards.set(team.id, node);
    draw(node, team);
    return node;
}
