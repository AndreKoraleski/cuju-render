// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the words and numbers of strict rules, the pre-flight check and a tournament's
// results, the ratings with their interval bars and the heat table of mean goal difference, run
// from the repository root with `node tests/web/tournament_results.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// The page's modules load from a copy beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-tournament-results-'));
for (const name of ['play/tournament-results.js', 'core/i18n.js']) {
    cpSync(fileURLToPath(new URL(`../../src/cuju/render/web/js/${name}`, import.meta.url)), join(folder, name));
}
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const results = await import(pathToFileURL(join(folder, 'play/tournament-results.js')).href);

const source = (path) => readFileSync(new URL(`../../src/cuju/render/${path}`, import.meta.url), 'utf8');
const english = JSON.parse(source('web/languages/en.json'));

// The text of a Python dictionary or tuple of the rules, from its name to its closing bracket.
function pythonBlock(text, name) {
    const start = text.indexOf(`${name}`);
    assert.ok(start >= 0, name);
    const open = text.indexOf('=', start) + 1;
    const close = { '{': '}', '(': ')' }[text.slice(open).trim()[0]];
    return text.slice(open, text.indexOf(`\n${close}`, open) + 2);
}

test('The limits of strict rules and the legs mirror the server\'s rules', () => {
    const rules = source('_tournaments/tournament.py');
    const defaults = Object.fromEntries([...pythonBlock(rules, 'STRICT_DEFAULTS: dict').matchAll(/'(\w+)': ([\d.]+)/g)]
        .map(([, key, value]) => [key, Number(value)]));
    assert.deepEqual(defaults, results.STRICT_DEFAULTS);
    const ranges = Object.fromEntries([...pythonBlock(rules, 'STRICT_RANGES: dict').matchAll(/'(\w+)': \(([\d.]+), ([\d.]+)\)/g)]
        .map(([, key, low, high]) => [key, [Number(low), Number(high)]]));
    assert.deepEqual(ranges, results.STRICT_RANGES);
    assert.equal(/^RANDOM_KEY = '([^']+)'$/m.exec(rules)[1], results.RANDOM_KEY);
    assert.equal(Number(/^MAX_LEGS = (\d+)$/m.exec(rules)[1]), results.MAX_LEGS);
    assert.equal(Number(/^MAX_ADDED_LEGS = (\d+)$/m.exec(rules)[1]), results.MAX_ADDED_LEGS);
    const files = [...pythonBlock(source('_tournaments/results.py'), 'FILES =').matchAll(/'([\w.]+)'/g)].map((m) => m[1]);
    assert.deepEqual(files, results.RESULT_FILES);
    for (const key of results.STRICT_KEYS) {
        assert.ok(results.STRICT_STEPS[key] > 0 && results.STRICT_UNITS[key], key);
    }
});

test('Strict rules resolve as the server resolves them, and a limit off its range is found', () => {
    assert.equal(results.strictLimits(null), null);
    assert.equal(results.strictLimits(false), null);
    assert.deepEqual(results.strictLimits(true), results.STRICT_DEFAULTS);
    assert.deepEqual(results.strictLimits({ call_seconds: 0.5, threads: '2' }), { ...results.STRICT_DEFAULTS, call_seconds: 0.5, threads: 2 });
    assert.deepEqual(results.strictProblems(results.strictLimits(true)), []);
    assert.deepEqual(results.strictProblems({ ...results.STRICT_DEFAULTS, threads: 1.5, mean_call_ms: 0, load_seconds: NaN }),
        ['threads', 'load_seconds', 'mean_call_ms']);
    assert.equal(results.limitsText(results.strictLimits(true)),
        '1 thread for each team, loading within 30 s, the first action call within 10 s, each later call within 1 s, a reset within 5 s, a mean call of at most 20 ms, a team folder of at most 100 MB');
    assert.equal(results.limitText('threads', 4), '4 threads for each team');
    assert.equal(results.limitText('call_seconds', 0.25), 'each later call within 0.25 s');
    assert.equal(results.limitText('mean_call_ms', 10000), 'a mean call of at most 10,000 ms');
});

test('Entrant keys follow the server, so an added entrant enters once and leaves when removed', () => {
    assert.equal(results.entrantKey({ kind: 'team', team: 't-1' }), 't-1');
    assert.equal(results.entrantKey({ team: 't-2' }), 't-2');
    assert.equal(results.entrantKey({ kind: 'builtin' }), 'builtin:scenario');
    assert.equal(results.entrantKey({ kind: 'builtin', ability: 0.5 }), 'builtin:0.50');
    assert.equal(results.entrantKey({ kind: 'random', ability: 0.3 }), 'random:uniform');
    assert.equal(results.entrantKey({ kind: 'person', name: '  Ana   Lu ' }), 'person:Ana Lu');
    const include = [{ kind: 'random' }, { kind: 'builtin' }];
    const listed = results.withIncluded([{ kind: 'team', team: 't-1' }, { kind: 'builtin' }], include);
    assert.deepEqual(listed.map(results.entrantKey), ['t-1', 'builtin:scenario', 'random:uniform']);
    assert.deepEqual(results.withoutIncluded(include, { kind: 'builtin', ability: null }), [{ kind: 'random' }]);
    assert.deepEqual(results.withoutIncluded(include, { kind: 'builtin', ability: 0.5 }), include);
});

test('Ratings come best first, the lower index first on a tie', () => {
    const rows = [
        { entrant: 2, rating: 990, low: 900, high: 1080, matches: 4 },
        { entrant: 0, rating: 1010, low: 950, high: 1070, matches: 4 },
        { entrant: 1, rating: 990, low: 940, high: 1040, matches: 4 },
    ];
    assert.deepEqual(results.orderedRatings(rows).map((row) => row.entrant), [0, 1, 2]);
    assert.deepEqual(rows.map((row) => row.entrant), [2, 0, 1], 'the ratings given stay as they were');
    assert.equal(results.ratingText(1234.56), '1,235');
    assert.equal(results.intervalWords(rows[1]), 'Rating 1,010, from 950 to 1,070');
});

test('The interval bars share one scale, wide enough, each mark inside its bar', () => {
    const rows = [
        { entrant: 0, rating: 1200, low: 1100, high: 1300, matches: 10 },
        { entrant: 1, rating: 1000, low: 950, high: 1050, matches: 10 },
        { entrant: 2, rating: 800, low: 650, high: 870, matches: 10 },
    ];
    const scale = results.ratingScale(rows);
    assert.ok(scale.low <= 650 && scale.high >= 1300, JSON.stringify(scale));
    assert.equal(scale.low % 10, 0);
    assert.equal(scale.high % 10, 0);
    for (const row of rows) {
        const bar = results.intervalBar(row, scale);
        assert.ok(bar.left >= 0 && bar.width > 0 && bar.left + bar.width <= 100, JSON.stringify(bar));
        assert.ok(bar.mark >= bar.left && bar.mark <= bar.left + bar.width, JSON.stringify(bar));
        assert.ok(bar.centre > 0 && bar.centre < 100);
    }
    const [best, , worst] = rows.map((row) => results.intervalBar(row, scale));
    assert.ok(best.left > worst.left + worst.width, 'intervals apart on the scale stay apart');
    // Ratings all at the centre still draw on a scale of 100 points.
    const flat = results.ratingScale([{ entrant: 0, rating: 1000, low: 1000, high: 1000, matches: 0 }]);
    assert.ok(flat.high - flat.low >= 100);
    assert.deepEqual(results.intervalBar({ rating: 1000, low: 1000, high: 1000 }, flat), { left: 50, width: 0, mark: 50, centre: 50 });
    assert.deepEqual(results.ratingScale([]), { low: 950, high: 1050 });
    // A value off the scale stays at its edge.
    assert.equal(results.intervalBar({ rating: 2000, low: 1900, high: 2100 }, { low: 900, high: 1100 }).left, 100);
});

test('The matrix follows the ratings, with each cell its mean, matches, tone and level', () => {
    const matrix = { mean: [[null, -3, 0.04], [3, null, null], [-0.04, null, null]], matches: [[0, 2, 1], [2, 0, 0], [1, 0, 0]] };
    const ratings = [{ entrant: 1, rating: 1200 }, { entrant: 0, rating: 900 }, { entrant: 2, rating: 900 }];
    const order = results.matrixOrder(ratings, 3);
    assert.deepEqual(order, [1, 0, 2]);
    assert.deepEqual(results.matrixOrder([], 2), [0, 1]);
    assert.equal(results.matrixExtent(matrix), 3);
    assert.equal(results.matrixExtent({ mean: [[null]], matches: [[0]] }), 1);
    const rows = results.matrixCells(matrix, order);
    assert.deepEqual(rows.map((row) => row.entrant), [1, 0, 2]);
    const cell = (row, column) => rows.find((r) => r.entrant === row).cells.find((c) => c.column === column);
    assert.deepEqual(cell(1, 1), { row: 1, column: 1, mean: null, matches: 0, self: true, tone: 'self', level: 0 });
    assert.deepEqual(cell(1, 0), { row: 1, column: 0, mean: 3, matches: 2, self: false, tone: 'up', level: 4 });
    assert.deepEqual(cell(0, 1), { row: 0, column: 1, mean: -3, matches: 2, self: false, tone: 'down', level: 4 });
    assert.equal(cell(0, 2).tone, 'even');
    assert.equal(cell(1, 2).tone, 'none');
    assert.deepEqual([0.2, 0.75, 0.76, 1.5, 2.3, 3, 9].map((mean) => results.heatLevel(mean, 3).level), [1, 1, 2, 2, 4, 4, 4]);
    assert.deepEqual(results.heatLevel(-1.6, 3), { tone: 'down', level: 3 });
    assert.deepEqual(results.heatLevel(undefined, 3), { tone: 'none', level: 0 });
});

test('Each cell of the matrix has a name that reads the pair, the mean and the matches', () => {
    assert.equal(results.cellName('Rex', 'Bot', { mean: 1.2, matches: 10 }), 'Rex against Bot, mean goal difference plus 1.2 over 10 matches');
    assert.equal(results.cellName('Rex', 'Bot', { mean: -0.5, matches: 1 }), 'Rex against Bot, mean goal difference minus 0.5 over 1 match');
    assert.equal(results.cellName('Rex', 'Bot', { mean: 0.04, matches: 4 }), 'Rex against Bot, mean goal difference 0.0 over 4 matches');
    assert.equal(results.cellName('Rex', 'Bot', { mean: null, matches: 0 }), 'Rex against Bot, not met yet');
    assert.equal(results.cellName('Rex', 'Rex', { self: true }), 'Rex against itself');
    assert.equal(results.signedMean(1.24), '+1.2');
    assert.equal(results.signedMean(-0.46), '-0.5');
    assert.equal(results.signedMean(-0.04), '0.0');
    assert.equal(results.signedMean(3), '+3.0');
});

test('Timings read in milliseconds and seconds, those missing left out', () => {
    assert.equal(results.msText(4.234), '4.2 ms');
    assert.equal(results.msText(1234.5), '1,235 ms');
    assert.equal(results.msText(null), null);
    assert.equal(results.secondsText(1.256), '1.26 s');
    assert.equal(results.secondsText(30), '30 s');
    assert.equal(results.timingsText({
        load_seconds: 0.5, reset_seconds: null, calls: 50, first_ms: 120, mean_ms: 4.5, max_ms: 9, mean_after_first_ms: 2.25,
    }), 'loaded in 0.5 s, 50 calls, first call 120 ms, mean call after the first 2.3 ms, longest call 9 ms');
    assert.equal(results.timingsText({ calls: 1, mean_ms: 3 }), '1 call, mean call 3 ms');
    assert.equal(results.timingsText({ calls: 0, load_seconds: null }), '');
    assert.equal(results.timingsText(null), '');
});

test('A forfeit by rule reads its reason in the page\'s language and the score at that moment', () => {
    const rule = {
        side: 'away', kind: 'timeout', reason: 'kept English', reason_id: 'server.strict.call_time',
        reason_values: { player: 'Slow', call: '12', count: '1' }, step: 11, at: [1, 0],
    };
    assert.equal(results.ruleReason(rule), 'Slow did not answer action call 12 within 1 second');
    assert.equal(results.ruleText(rule), 'forfeit at 1 to 0, Slow did not answer action call 12 within 1 second');
    assert.equal(results.ruleText({ reason: 'plain' }), 'forfeit at 0 to 0, plain');
    const played = { result: { score: [2, 1], forfeit: false } };
    assert.equal(results.forfeitWords([played]), null);
    assert.equal(results.forfeitWords([played, { result: { score: [3, 0], forfeit: true } }]), 'awarded');
    assert.equal(results.forfeitWords([{ result: { score: [3, 0], forfeit: true, rule } }]), results.ruleText(rule));
    assert.equal(results.forfeitWords([]), null);
});

test('The pre-flight, more legs and the stamp of the analysis follow the tournament', () => {
    assert.equal(results.preflightText(null), null);
    assert.equal(results.preflightText('waiting'), 'Pre-flight check waiting to start');
    assert.equal(results.preflightText('running'), 'Pre-flight check running');
    assert.equal(results.preflightText('done', 0), 'Pre-flight check passed by every team');
    assert.equal(results.preflightText('done', 1), 'Pre-flight check done, 1 team left out');
    assert.equal(results.preflightText('done', 2), 'Pre-flight check done, 2 teams left out');
    const league = (state, stage) => ({ state, config: { stages: [{ format: 'knockout', legs: 1 }, stage] } });
    assert.equal(results.legsRoom(league('done', { format: 'league', legs: 10 })), 90);
    assert.equal(results.legsRoom(league('running', { format: 'groups', legs: 2, added_legs: 5 })), 93);
    assert.equal(results.legsRoom(league('done', { format: 'league', legs: 10, added_legs: 90 })), 0);
    assert.equal(results.legsRoom(league('cancelled', { format: 'league', legs: 1 })), 0);
    assert.equal(results.legsRoom(league('done', { format: 'swiss', legs: 1 })), 0);
    assert.equal(results.legsRoom(null), 0);
    assert.equal(results.fileAddress('cup 1', 'standings.csv'), '/api/tournaments/cup%201/files/standings.csv');
    const cup = { id: 'a', played: 3, scheduled: 6, excluded_count: 1 };
    assert.notEqual(results.analysisStamp(cup), results.analysisStamp({ ...cup, played: 4 }));
    assert.equal(results.analysisStamp(cup), results.analysisStamp({ ...cup }));
});

test('A check reads each side it played, the size of the folder and its warnings', () => {
    const timings = { load_seconds: 0.5, reset_seconds: 0.1, calls: 50, first_ms: 40, mean_ms: 3, max_ms: 12, mean_after_first_ms: 2.5 };
    const rule = { reason: 'kept', reason_id: 'server.strict.invalid_range', reason_values: { player: 'Rex', reason: 'action 25' }, detail: 'range' };
    const report = {
        ok: false, rule, timings, folder_mb: 0.42,
        sides: { left: { ok: true, rule: null, timings }, right: { ok: false, rule, timings: { calls: 3 } } },
        warnings: [{ id: 'server.strict.warning_action', text: 'kept', values: { player: 'Rex', action: '5', share: '95' } }],
    };
    const sides = results.checkSides(report);
    assert.deepEqual(sides.map((side) => side.side), ['left', 'right']);
    assert.equal(results.sideText(sides[0]),
        'Left side passed, loaded in 0.5 s, reset in 0.1 s, 50 calls, first call 40 ms, mean call after the first 2.5 ms, longest call 12 ms');
    assert.equal(results.sideText(sides[1]), 'Right side failed, Rex answered an action outside its action set, action 25, 3 calls');
    assert.deepEqual(results.warningTexts(report), ['Rex answered the action 5 in 95% of its actions.']);
    assert.equal(results.folderText(report), 'folder of 0.42 MB');
    assert.equal(results.folderText({ folder_mb: 12.4 }), 'folder of 12 MB');
    assert.equal(results.folderText({}), null);
    // The right side stays unplayed once the left failed, and a check a tournament keeps has no sides.
    const left = results.checkSides({ sides: { left: { ok: false, rule, timings: {} } } });
    assert.equal(results.sideText(left[1]), 'Right side left unplayed after the left side failed');
    assert.deepEqual(results.checkSides({ ok: true, timings }), []);
    assert.deepEqual(results.warningTexts({}), []);
});

test('The results say how many matches ended early, the prior and the resamples', () => {
    const method = { prior: { virtual_draws: 1 }, bootstrap: { resamples: 200, tournament_seed: 7 } };
    assert.equal(results.playedText({ played: 12, cut_short: 3 }), 'The ratings rest on 12 played matches. 3 matches among them ended early, by a forfeit or before full time.');
    assert.equal(results.playedText({ played: 1, cut_short: 1 }), 'The ratings rest on 1 played match. 1 match among them ended early, by a forfeit or before full time.');
    assert.equal(results.playedText({ played: 4, cut_short: 0 }), 'The ratings rest on 4 played matches. Every one of them ran to full time.');
    assert.equal(results.methodText({ method, resamples: 200 }),
        'Each entrant also plays 1 virtual draw against an entrant of a fixed strength, which keeps every rating finite, and the intervals come from 200 resamples of the played matches, drawn from the tournament seed 7.');
});

// The relative luminance and contrast of colors, as WCAG defines them.
function luminance(hex) {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
        .map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contrast = (a, b) => {
    const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (high + 0.05) / (low + 0.05);
};

test('Every tone of the heat table keeps its text readable in both themes', () => {
    const style = source('web/style.css');
    const block = (opening) => style.split(opening)[1].split('}')[0];
    const tokens = (text) => Object.fromEntries([...text.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6});/g)].map((m) => [m[1], m[2]]));
    const dark = tokens(block(':root {'));
    const light = tokens(block(':root[data-theme="light"] {'));
    const heats = [...style.matchAll(/--(heat-(?:up|down)-\d):\s*(#[0-9a-f]{6});/g)];
    assert.equal(heats.length, 24, 'eight tones in the dark theme, the light one by the system and by choice');
    const sets = [heats.slice(0, 8), heats.slice(8, 16), heats.slice(16, 24)].map((list) => Object.fromEntries(list.map((m) => [m[1], m[2]])));
    assert.deepEqual(sets[1], sets[2], 'the light theme reads the same by the system and by choice');
    for (const [colors, text, name] of [[sets[0], dark.text, 'dark'], [sets[2], light.text, 'light']]) {
        assert.equal(Object.keys(colors).length, 8, name);
        for (const [tone, color] of Object.entries(colors)) {
            assert.ok(contrast(color, text) >= 4.5, `${name} ${tone} ${color} against ${text}: ${contrast(color, text).toFixed(2)}`);
        }
        // Each step stands further from the page than the one before, so the heat reads in order.
        for (const side of ['up', 'down']) {
            const steps = [1, 2, 3, 4].map((level) => contrast(colors[`heat-${side}-${level}`], text));
            assert.ok(steps.every((value, i) => i === 0 || value < steps[i - 1]), `${name} ${side} ${steps}`);
        }
    }
    for (const level of [1, 2, 3, 4]) {
        for (const side of ['up', 'down']) {
            assert.ok(style.includes(`.heat-${side}-${level} { background: var(--heat-${side}-${level}); }`), `${side} ${level}`);
        }
    }
});

test('Every message that the strict and results parts name is in English', () => {
    const files = ['play/tournament-results.js', 'play/tournament-strict.js', 'teams/team-check.js'];
    const ids = new Set();
    for (const file of files) {
        const text = source(`web/js/${file}`);
        for (const match of text.matchAll(/'((?:tournament|server)\.[A-Za-z0-9_.]+)'/g)) {
            ids.add(match[1]);
        }
        // A message named from a key, such as the field of each limit, takes every key.
        for (const [, prefix, name] of text.matchAll(/`((?:tournament)\.[A-Za-z0-9_.]+)\.\$\{(\w+)\}`/g)) {
            const keys = {
                key: results.STRICT_KEYS, tone: ['up', 'down', 'even'], unit: ['s', 'ms'],
                name: ['rank', 'entrant', 'rating', 'interval', 'low', 'high', 'matches'],
            }[name];
            assert.ok(keys, `${file} ${prefix}`);
            for (const key of keys) {
                ids.add(`${prefix}.${key}`);
            }
        }
    }
    ids.add('tournament.strict.field.threads');
    const missing = [...ids].filter((id) => !(id in english) && !/\.$/.test(id));
    assert.deepEqual(missing, []);
});
