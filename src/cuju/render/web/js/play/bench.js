// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The benchmark of models in the Challenges section of Play. A person picks one or several
// registered teams and several or all challenges, and the server plays every pair as a full
// headless run, as Run headless does, in a process of its own and by the challenges' own rules and
// seeds. The view follows the job and draws a table of models by challenges, each cell with its
// value and medal, and each model's medals, score and place, which the server counts, and exports
// the benchmark as JSON and its table as CSV. benchCsv writes the same CSV as csv_text of
// bench.py, and the two share their cases in tests/support/bench_table.json.

import { formatNumber, serverText, t, tn } from '../core/i18n.js';
import { el as h } from '../core/menu.js';
import { STATE_ICONS, icon, symbolOnly } from '../core/icons.js';
import { teamName } from '../core/names.js';
import { medalMark } from './medals.js';

// A benchmark is followed this often while it waits or plays.
const POLL_MS = 1000;
const LIVE = ['queued', 'running'];

async function call(method, path, json) {
    const init = { method, cache: 'no-store', headers: {} };
    if (json !== undefined) {
        init.body = JSON.stringify(json);
        init.headers['Content-Type'] = 'application/json';
    }
    let res;
    try {
        res = await fetch(path, init);
    } catch {
        throw new Error(t('api.unreachable', { origin: location.origin }));
    }
    const text = await res.text();
    let data = null;
    try {
        data = text ? JSON.parse(text) : null;
    } catch {
        data = null;
    }
    if (!res.ok) {
        const error = new Error((data && data.error && serverText(data, 'error')) || t('challenges.api.status', { status: res.status }));
        error.status = res.status;
        throw error;
    }
    return data;
}

const enc = encodeURIComponent;

// The client of the server's benchmark routes.
export const benchApi = {
    start: (teams, challenges = null, keep = false, workers = null) => call('POST', '/api/challenges/benches', {
        teams, ...(challenges ? { challenges } : {}), keep_recordings: !!keep, ...(workers == null ? {} : { workers }),
    }),
    list: () => call('GET', '/api/challenges/benches'),
    get: (id) => call('GET', `/api/challenges/benches/${enc(id)}`),
    cancel: (id) => call('DELETE', `/api/challenges/benches/${enc(id)}`),
    csvUrl: (id) => `/api/challenges/benches/${enc(id)}/table.csv`,
};

// The cell of a model and a challenge in a benchmark, or null.
export function benchCell(job, team, challenge) {
    return (job.cells || []).find((cell) => cell.team === team && cell.challenge === challenge) || null;
}

// The table of a benchmark, its columns, the challenges in the order of the benchmark, and its rows,
// the models in the order they were chosen, each with its cells, medals, score and place.
export function benchTable(job) {
    const rows = (job.rows || []).map((row) => ({
        ...row,
        cells: job.challenges.map((challenge) => benchCell(job, row.team, challenge)),
    }));
    return { columns: job.challenges.slice(), rows };
}

// A field of the CSV, in quotes when it holds a comma, a quote or a line break, as Python's csv
// module writes it.
function csvField(value) {
    const text = value == null ? '' : String(value);
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

// The table as CSV, one row for each model, with the identifiers of the challenges and medals, the
// English name of each model and its score with one decimal, as csv_text of bench.py writes it.
export function benchCsv(job) {
    const header = ['model', 'team'];
    for (const id of job.challenges) {
        header.push(`${id} value`, `${id} medal`);
    }
    header.push('gold', 'silver', 'bronze', 'score', 'place');
    const lines = [header];
    for (const row of benchTable(job).rows) {
        const line = [row.name, row.team];
        for (const cell of row.cells) {
            const done = !!cell && cell.state === 'done';
            line.push(done ? String(cell.value) : '', done && cell.medal ? cell.medal : '');
        }
        line.push(row.gold, row.silver, row.bronze, Number(row.score).toFixed(1), row.place);
        lines.push(line);
    }
    return lines.map((line) => line.map(csvField).join(',')).join('\n') + '\n';
}

// The benchmark as JSON, as the server answers it.
export function benchJson(job) {
    return `${JSON.stringify(job, null, 1)}\n`;
}

// The share of the attempts played, from 0 to 1.
export function benchProgress(job) {
    return typeof job.progress === 'number' && Number.isFinite(job.progress) ? Math.max(0, Math.min(1, job.progress)) : 0;
}

export class BenchPanel {
    // `panel` is the ChallengesPanel, which holds the catalog, the teams and the words of values.
    constructor(panel, words) {
        this.panel = panel;
        this.words = words;
        this.job = null;
        this.polling = false;
        this.root = null;
    }

    element() {
        this.teamBox = h('fieldset', { class: 'bench-choice bench-teams' });
        this.challengeBox = h('fieldset', { class: 'bench-choice bench-challenges' });
        // All challenges follows the challenges chosen one by one.
        this.challengeBox.addEventListener('change', (event) => {
            const all = this.challengeBox.querySelector('.bench-all');
            if (all && event.target.name === 'bench-challenge') {
                all.checked = [...this.challengeBox.querySelectorAll('input[name="bench-challenge"]')].every((input) => input.checked);
            }
        });
        this.keepBox = h('input', { type: 'checkbox', class: 'bench-keep' });
        this.startButton = h('button', { type: 'button', class: 'btn primary', 'data-action': 'bench', onclick: () => this.startFromPage() },
            icon('stats'), t('challenges.bench.start'));
        this.progressBar = h('progress', { class: 'bench-progress', max: '1', value: '0', 'aria-label': t('challenges.bench.progress') });
        this.statusText = h('span', {});
        this.cancelButton = h('button', { type: 'button', class: 'btn small', 'data-action': 'bench-cancel', hidden: true, ...symbolOnly(t('challenges.bench.cancel')),
            onclick: () => this.cancel() }, icon('stop'));
        this.status = h('div', { class: 'bench-status', role: 'status', 'aria-live': 'polite', hidden: true }, this.progressBar, this.statusText, this.cancelButton);
        this.tableBox = h('div', { class: 'bench-table' });
        this.exports = h('div', { class: 'challenge-actions bench-exports', hidden: true },
            h('button', { type: 'button', class: 'btn small', 'data-action': 'bench-json', onclick: () => this.download('json') }, icon('download'), t('challenges.bench.json')),
            h('button', { type: 'button', class: 'btn small', 'data-action': 'bench-csv', onclick: () => this.download('csv') }, icon('download'), t('challenges.bench.csv')));
        this.root = h('section', { class: 'challenge-bench', 'aria-labelledby': 'challenge-bench-title' },
            h('h3', { id: 'challenge-bench-title' }, t('challenges.bench.title')),
            h('p', { class: 'muted' }, ...tn('challenges.bench.text')),
            h('div', { class: 'bench-choices' }, this.teamBox, this.challengeBox),
            h('label', { class: 'check' }, this.keepBox, t('challenges.bench.keep')),
            h('div', { class: 'challenge-actions' }, this.startButton),
            this.status, this.tableBox, this.exports);
        this.renderChoices();
        return this.root;
    }

    // The teams and challenges to choose, keeping what was chosen before.
    renderChoices() {
        if (!this.root) {
            return;
        }
        const checked = (box) => new Set([...box.querySelectorAll('input:checked')].map((input) => input.value));
        const teams = checked(this.teamBox);
        const challenges = checked(this.challengeBox);
        const fresh = !this.teamBox.querySelector('input');
        const option = (name, value, text, on) => h('label', { class: 'check' },
            h('input', { type: 'checkbox', name, value, checked: on }), text);
        this.teamBox.replaceChildren(h('legend', {}, t('challenges.bench.models')),
            ...this.panel.teams.map((team) => option('bench-team', team.id,
                team.kind === 'builtin' ? t('challenges.team.builtin') : teamName(team), teams.has(team.id))));
        const all = h('input', { type: 'checkbox', class: 'bench-all', checked: fresh || challenges.size === this.panel.catalog.length });
        all.addEventListener('change', () => this.challengeBox.querySelectorAll('input[name="bench-challenge"]').forEach((input) => {
            input.checked = all.checked;
        }));
        this.challengeBox.replaceChildren(h('legend', {}, t('challenges.bench.challenges')),
            h('label', { class: 'check' }, all, t('challenges.bench.all')),
            ...this.panel.catalog.map((c) => option('bench-challenge', c.id, this.words.title(c), fresh || challenges.has(c.id))));
    }

    chosen(name) {
        return [...this.root.querySelectorAll(`input[name="${name}"]:checked`)].map((input) => input.value);
    }

    async startFromPage() {
        const teams = this.chosen('bench-team');
        const challenges = this.chosen('bench-challenge');
        if (!teams.length || !challenges.length) {
            this.showStatus(t(teams.length ? 'challenges.bench.noChallenge' : 'challenges.bench.noModel'), true);
            return null;
        }
        const every = challenges.length === this.panel.catalog.length;
        return this.start(teams, every ? null : challenges, this.keepBox.checked);
    }

    // Starts a benchmark on the server and follows it.
    async start(teams, challenges = null, keep = false, workers = null) {
        let job;
        try {
            job = await benchApi.start(teams, challenges, keep, workers);
        } catch (err) {
            this.showStatus(err.message, true);
            throw err;
        }
        this.job = job;
        this.render();
        this.follow();
        return job;
    }

    follow() {
        if (this.polling || !this.job) {
            return;
        }
        this.polling = true;
        const tick = async () => {
            try {
                const before = this.job.state;
                this.job = await benchApi.get(this.job.id);
                this.render();
                if (before !== this.job.state && !LIVE.includes(this.job.state)) {
                    // The runs reached the leaderboards, so the cards show them.
                    this.panel.boards.clear();
                    this.panel.show();
                }
            } catch {
                // The next refresh of the page tries again.
            }
            if (this.job && LIVE.includes(this.job.state)) {
                setTimeout(tick, POLL_MS);
            } else {
                this.polling = false;
            }
        };
        tick();
    }

    async cancel() {
        if (!this.job) {
            return;
        }
        try {
            await benchApi.cancel(this.job.id);
        } catch (err) {
            this.showStatus(err.message, true);
        }
        this.polling = false;
        this.follow();
    }

    showStatus(text, error = false) {
        this.status.hidden = false;
        this.progressBar.hidden = true;
        this.cancelButton.hidden = true;
        this.statusText.className = error ? 'error-text' : '';
        this.statusText.textContent = text;
    }

    render() {
        const job = this.job;
        if (!this.root || !job) {
            return;
        }
        const live = LIVE.includes(job.state);
        const share = benchProgress(job);
        const runs = job.cells.filter((cell) => cell.state !== 'skipped');
        const ended = runs.filter((cell) => !LIVE.includes(cell.state)).length;
        this.status.hidden = false;
        this.progressBar.hidden = false;
        this.progressBar.value = share;
        this.cancelButton.hidden = !live;
        this.statusText.className = job.state === 'failed' ? 'error-text' : '';
        const values = { done: ended, total: runs.length, percent: formatNumber(share, { style: 'percent', maximumFractionDigits: 0 }) };
        if (job.state === 'queued') {
            this.statusText.textContent = t('challenges.bench.queued');
        } else if (live) {
            this.statusText.textContent = t('challenges.bench.running', values);
        } else if (job.state === 'done') {
            this.statusText.textContent = t('challenges.bench.done', values);
        } else {
            this.statusText.textContent = t('challenges.bench.stopped', { reason: job.error ? serverText(job, 'error') : t('challenges.job.noResult') });
        }
        this.tableBox.replaceChildren(this.table(job));
        this.exports.hidden = false;
    }

    // The words of a cell, its value and medal once played, or its state.
    cellNodes(c, cell) {
        if (!cell) {
            return [];
        }
        if (cell.state === 'done') {
            const parts = [h('span', { class: 'bench-value' }, this.words.value(c, cell.value)), ' ', medalMark(cell.medal, t('challenges.board.noMedal'))];
            if (cell.failed_attempts) {
                parts.push(h('span', { class: 'muted small bench-failed' }, t('challenges.bench.failedAttempts', { count: cell.failed_attempts })));
            }
            return parts;
        }
        const label = t(`challenges.bench.state.${cell.state}`);
        const reason = cell.error ? serverText(cell, 'error') : '';
        return [h('span', { class: `bench-state ${cell.state}` }, icon(STATE_ICONS[cell.state] || 'info'), label),
            reason ? h('span', { class: 'muted small bench-reason' }, reason) : null].filter(Boolean);
    }

    table(job) {
        const { columns, rows } = benchTable(job);
        const specs = columns.map((id) => this.panel.find(id) || { id, title: id, measure: 'scored', attempts: 0, targets: [0, 0, 0] });
        const head = h('tr', {},
            h('th', { scope: 'col' }, t('challenges.bench.model')),
            ...specs.map((c) => h('th', { scope: 'col', 'data-challenge': c.id }, this.words.title(c))),
            ...['gold', 'silver', 'bronze'].map((medal) => h('th', { scope: 'col', class: 'num' }, medalMark(medal))),
            h('th', { scope: 'col', class: 'num' }, t('challenges.bench.score')),
            h('th', { scope: 'col', class: 'num' }, t('challenges.bench.place')));
        const body = rows.map((row) => h('tr', { 'data-team': row.team },
            h('th', { scope: 'row' }, teamName(row)),
            ...row.cells.map((cell, index) => h('td', { 'data-challenge': columns[index], 'data-state': cell ? cell.state : '' }, ...this.cellNodes(specs[index], cell))),
            h('td', { class: 'num' }, String(row.gold)),
            h('td', { class: 'num' }, String(row.silver)),
            h('td', { class: 'num' }, String(row.bronze)),
            h('td', { class: 'num bench-score' }, formatNumber(Number(row.score), { minimumFractionDigits: 1, maximumFractionDigits: 1 })),
            h('td', { class: 'num' }, String(row.place))));
        return h('table', {}, h('caption', {}, t('challenges.bench.caption')), h('thead', {}, head), h('tbody', {}, body));
    }

    // Saves the benchmark as JSON or its table as CSV, a file named after the benchmark.
    download(kind) {
        if (!this.job) {
            return;
        }
        const text = kind === 'csv' ? benchCsv(this.job) : benchJson(this.job);
        const blob = new Blob([text], { type: kind === 'csv' ? 'text/csv' : 'application/json' });
        const link = h('a', { href: URL.createObjectURL(blob), download: `${this.job.id}.${kind}` });
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 0);
    }
}
