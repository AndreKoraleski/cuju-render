// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The words and numbers of strict rules, the pre-flight check and a tournament's results, kept
// apart from the page so that Node tests read them. The limits of strict rules mirror
// STRICT_DEFAULTS and STRICT_RANGES of the server's rules, and the keys of entrants mirror
// `entrant_key`, which tests/web/tournament_results.mjs holds equal to the Python source. The
// ratings read as a table with a bar for each interval on one scale, and the matrix of mean goal
// difference as a heat table whose cells each take a tone, up for the row and down for the
// column, and a level from 0 to 4 of how far the mean goes.

import { formatNumber, labelText, serverText, t } from '../core/i18n.js';

// The limits of strict rules with their defaults, the threads of a team's process, the seconds
// to load, of the first call, of each later call and of a reset, the milliseconds of the mean
// call, the megabytes of a team's folder and of its process's memory, and the seconds that all
// of a team's calls of a match may take together, as the server's rules give them.
export const STRICT_DEFAULTS = {
    threads: 1, load_seconds: 30, first_call_seconds: 10, call_seconds: 1, reset_seconds: 5, mean_call_ms: 20, folder_mb: 100,
    memory_mb: 2048, match_seconds: 120,
};
export const STRICT_RANGES = {
    threads: [1, 64], load_seconds: [1, 600], first_call_seconds: [0.1, 600], call_seconds: [0.01, 60],
    reset_seconds: [0.1, 600], mean_call_ms: [0.1, 10000], folder_mb: [1, 10000], memory_mb: [64, 65536],
    match_seconds: [1, 36000],
};
// The switches of strict rules with their defaults, as STRICT_FLAGS of the server's rules gives
// them. A frozen team plays from a read only copy of its folder and forfeits once its files
// change, a team sees the GPU only with `gpu`, and with `deterministic` the pre-flight refuses a
// team whose answers differ when the same steps play again, which is otherwise a warning.
export const STRICT_FLAGS = { frozen: true, gpu: false, deterministic: false };
export const STRICT_FLAG_KEYS = Object.keys(STRICT_FLAGS);
export const STRICT_KEYS = Object.keys(STRICT_DEFAULTS);
// The step of each limit's box, and the unit it reads in.
export const STRICT_STEPS = {
    threads: 1, load_seconds: 1, first_call_seconds: 0.1, call_seconds: 0.01, reset_seconds: 0.1, mean_call_ms: 0.1, folder_mb: 1,
    memory_mb: 1, match_seconds: 1,
};
export const STRICT_UNITS = {
    threads: 'threads', load_seconds: 's', first_call_seconds: 's', call_seconds: 's', reset_seconds: 's', mean_call_ms: 'ms', folder_mb: 'MB',
    memory_mb: 'MB', match_seconds: 's',
};

// The key of the random entrant, as RANDOM_KEY of the server's rules gives it.
export const RANDOM_KEY = 'random:uniform';

// The legs that a stage's meetings play at most, those it starts with and those added later, as
// MAX_LEGS and MAX_ADDED_LEGS of the server's rules give them.
export const MAX_LEGS = 10;
export const MAX_ADDED_LEGS = 90;
// The formats whose last stage takes more legs later.
export const LEG_FORMATS = ['league', 'groups'];

// The files of a tournament's results, in the order the server lists them.
export const RESULT_FILES = [
    'standings.csv', 'ratings.csv', 'ratings_method.json', 'pairwise_gd.csv', 'pairwise_counts.csv', 'matches.jsonl',
    'entrants.json', 'excluded.json',
];

// The rating of an entrant of the mean strength.
export const CENTRE = 1000;

// The limits of strict rules in full, or null for a tournament without them, as `check_strict`
// of the server's rules resolves `null`, `false`, `true` or an object of some limits.
export function strictLimits(value) {
    if (value === null || value === undefined || value === false) {
        return null;
    }
    const given = value === true || typeof value !== 'object' ? {} : value;
    const limits = { ...STRICT_DEFAULTS, ...STRICT_FLAGS };
    for (const key of STRICT_KEYS) {
        if (given[key] !== undefined && given[key] !== null && given[key] !== '') {
            limits[key] = Number(given[key]);
        }
    }
    for (const key of STRICT_FLAG_KEYS) {
        if (typeof given[key] === 'boolean') {
            limits[key] = given[key];
        }
    }
    return limits;
}

// The limits that lie outside their ranges, by key, which the server would refuse.
export function strictProblems(limits) {
    if (!limits) {
        return [];
    }
    return STRICT_KEYS.filter((key) => {
        const value = limits[key];
        const [lowest, highest] = STRICT_RANGES[key];
        return !Number.isFinite(value) || value < lowest || value > highest || (key === 'threads' && !Number.isInteger(value));
    });
}

// A number of a limit in the numbers of the language, with as many decimals as it needs.
export function limitNumber(value) {
    return formatNumber(Number(value), { maximumFractionDigits: 2 });
}

// One limit of strict rules in words, such as each later call within 1 s.
export function limitText(key, value) {
    const number = limitNumber(value);
    return key === 'threads' ? t('tournament.strict.limit.threads', { count: Number(value), value: number }) : t(`tournament.strict.limit.${key}`, { value: number });
}

// Every limit of strict rules in words, in the order of the rules.
export function limitsText(limits) {
    if (!limits) {
        return '';
    }
    const flags = STRICT_FLAG_KEYS.map((key) => t(`tournament.strict.flag.${key}.${(limits[key] ?? STRICT_FLAGS[key]) ? 'on' : 'off'}`));
    return [...STRICT_KEYS.map((key) => limitText(key, limits[key])), ...flags].join(', ');
}

// The key of an entrant as given, as `entrant_key` of the server's rules gives it, the team of a
// team, the built-in AI at its ability, RANDOM_KEY for the random entrant, a person by name.
export function entrantKey(raw) {
    const kind = (raw && raw.kind) || 'team';
    if (kind === 'team') {
        return String(raw.team);
    }
    if (kind === 'builtin') {
        const ability = raw.ability;
        const number = typeof ability === 'number' && Number.isFinite(ability);
        return `builtin:${number ? ability.toFixed(2) : 'scenario'}`;
    }
    if (kind === 'random') {
        return RANDOM_KEY;
    }
    return typeof raw.name === 'string' ? `person:${raw.name.trim().split(/\s+/).filter(Boolean).join(' ')}` : null;
}

// The entrants with each of `include` whose key none of them holds, as `with_included` of the
// server's rules adds them.
export function withIncluded(entrants, include) {
    const keys = new Set(entrants.map(entrantKey));
    const added = [];
    for (const raw of include || []) {
        const key = entrantKey(raw);
        if (!keys.has(key)) {
            keys.add(key);
            added.push({ ...raw });
        }
    }
    return [...entrants, ...added];
}

// The entrants that a tournament adds, without the one of the same key as a removed entrant, so
// the server does not add it back.
export function withoutIncluded(include, removed) {
    const key = entrantKey(removed);
    return (include || []).filter((raw) => entrantKey(raw) !== key);
}

// The legs that the last stage of a tournament may still take, or 0 when it takes none, a stage
// other than a league or groups, or a canceled tournament.
export function legsRoom(cup) {
    const stages = cup && cup.config && cup.config.stages;
    const last = stages && stages[stages.length - 1];
    if (!last || !LEG_FORMATS.includes(last.format) || cup.state === 'cancelled') {
        return 0;
    }
    return Math.max(0, MAX_LEGS + MAX_ADDED_LEGS - (last.legs || 1) - (last.added_legs || 0));
}

// The ratings, best first, the higher rating first and the lower index on a tie.
export function orderedRatings(ratings) {
    return [...(ratings || [])].sort((a, b) => b.rating - a.rating || a.entrant - b.entrant);
}

// The scale of the interval bars, from a little below the lowest end to a little above the
// highest, at least 100 points wide, rounded out to tens.
export function ratingScale(ratings) {
    const rows = ratings || [];
    if (!rows.length) {
        return { low: CENTRE - 50, high: CENTRE + 50 };
    }
    let low = Math.min(...rows.map((row) => row.low));
    let high = Math.max(...rows.map((row) => row.high));
    if (high - low < 100) {
        const middle = (high + low) / 2;
        low = middle - 50;
        high = middle + 50;
    }
    const pad = (high - low) * 0.05;
    return { low: Math.floor((low - pad) / 10) * 10, high: Math.ceil((high + pad) / 10) * 10 };
}

// Where the bar of a rating's interval sits on the scale, in percent of the width, its left end,
// its width, the mark of the rating itself and the line of the centre, null off the scale.
export function intervalBar(row, scale) {
    const span = scale.high - scale.low || 1;
    const at = (value) => Math.max(0, Math.min(100, ((value - scale.low) / span) * 100));
    const left = at(row.low);
    const round = (value) => Math.round(value * 100) / 100;
    return {
        left: round(left),
        width: round(Math.max(0, at(row.high) - left)),
        mark: round(at(row.rating)),
        centre: CENTRE >= scale.low && CENTRE <= scale.high ? round(at(CENTRE)) : null,
    };
}

// A rating in whole points, in the numbers of the language.
export function ratingText(value) {
    return formatNumber(Math.round(Number(value)));
}

// The words of a rating's interval bar, for a screen reader.
export function intervalWords(row) {
    return t('tournament.results.interval', { rating: ratingText(row.rating), low: ratingText(row.low), high: ratingText(row.high) });
}

// The order of the entrants in the matrix, those rated best first, then any left unrated.
export function matrixOrder(ratings, count) {
    const order = orderedRatings(ratings).map((row) => row.entrant).filter((index) => index >= 0 && index < count);
    for (let index = 0; index < count; index++) {
        if (!order.includes(index)) {
            order.push(index);
        }
    }
    return order;
}

// The largest mean goal difference of the matrix, at least 1, which the darkest tone stands for.
export function matrixExtent(matrix) {
    let most = 0;
    for (const row of (matrix && matrix.mean) || []) {
        for (const value of row) {
            if (typeof value === 'number' && Number.isFinite(value)) {
                most = Math.max(most, Math.abs(value));
            }
        }
    }
    return Math.max(1, most);
}

// The tone and level of a cell, `self` on the diagonal, `none` for a pair that has not met,
// `even` for a mean that rounds to 0, else `up` where the row scores more and `down` where the
// column does, at a level from 1 to 4 of the mean over the extent.
export function heatLevel(mean, extent, self = false) {
    if (self) {
        return { tone: 'self', level: 0 };
    }
    if (typeof mean !== 'number' || !Number.isFinite(mean)) {
        return { tone: 'none', level: 0 };
    }
    if (Math.round(mean * 10) === 0) {
        return { tone: 'even', level: 0 };
    }
    const share = Math.min(1, Math.abs(mean) / (extent || 1));
    return { tone: mean > 0 ? 'up' : 'down', level: Math.max(1, Math.ceil(share * 4)) };
}

// A mean goal difference with its sign and one decimal, a plus sign above 0 and a minus sign
// below it.
export function signedMean(mean) {
    const rounded = Math.round(mean * 10) / 10;
    return formatNumber(rounded === 0 ? 0 : rounded, { minimumFractionDigits: 1, maximumFractionDigits: 1, signDisplay: 'exceptZero' });
}

// The accessible name of a cell, such as Rex against Bot, mean goal difference plus 1.2 over 10
// matches.
export function cellName(rowName, columnName, cell) {
    const names = { row: rowName, column: columnName };
    if (cell.self) {
        return t('tournament.results.cell.self', names);
    }
    if (typeof cell.mean !== 'number' || !cell.matches) {
        return t('tournament.results.cell.none', names);
    }
    const tone = heatLevel(cell.mean, 1).tone;
    const mean = formatNumber(Math.abs(Math.round(cell.mean * 10) / 10), { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    return t(`tournament.results.cell.${tone}`, { ...names, mean, count: cell.matches });
}

// The rows of the matrix in the order given, each with its entrant and its cells, each cell with
// its row, column, mean, matches, whether it is the diagonal, its tone and level.
export function matrixCells(matrix, order) {
    const extent = matrixExtent(matrix);
    return order.map((row) => ({
        entrant: row,
        cells: order.map((column) => {
            const self = row === column;
            const mean = self ? null : (matrix.mean[row] || [])[column] ?? null;
            const matches = self ? 0 : (matrix.matches[row] || [])[column] || 0;
            return { row, column, mean, matches, self, ...heatLevel(mean, extent, self) };
        }),
    }));
}

// A time in milliseconds in words, such as 4.2 ms, with a decimal below 100, or null.
export function msText(value) {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
        return null;
    }
    return t('tournament.timing.ms', { value: formatNumber(value, { maximumFractionDigits: value < 100 ? 1 : 0 }) });
}

// A time in seconds in words, such as 1.25 s, or null.
export function secondsText(value) {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
        return null;
    }
    return t('tournament.timing.seconds', { value: formatNumber(value, { maximumFractionDigits: value < 10 ? 2 : 1 }) });
}

// The timings of a team's check or a side's match in words, those it has, in order.
export function timingParts(timings) {
    if (!timings || typeof timings !== 'object') {
        return [];
    }
    const parts = [];
    const add = (id, text) => {
        if (text) {
            parts.push(t(id, { time: text }));
        }
    };
    add('tournament.timing.load', secondsText(timings.load_seconds));
    add('tournament.timing.reset', secondsText(timings.reset_seconds));
    if (typeof timings.calls === 'number' && timings.calls > 0) {
        parts.push(t('tournament.timing.calls', { count: timings.calls, value: formatNumber(timings.calls) }));
    }
    add('tournament.timing.first', msText(timings.first_ms));
    // The mean that the limit holds leaves out the first call, which loads what a policy needs.
    if (typeof timings.mean_after_first_ms === 'number') {
        add('tournament.timing.meanAfter', msText(timings.mean_after_first_ms));
    } else {
        add('tournament.timing.mean', msText(timings.mean_ms));
    }
    add('tournament.timing.max', msText(timings.max_ms));
    if (typeof timings.memory_mb === 'number' && Number.isFinite(timings.memory_mb)) {
        parts.push(t('tournament.timing.memory', { value: formatNumber(timings.memory_mb, { maximumFractionDigits: timings.memory_mb < 10 ? 1 : 0 }) }));
    }
    return parts;
}

// The timings in one line.
export function timingsText(timings) {
    return timingParts(timings).join(', ');
}

// The reason that a rule gives, translated where the server names its message.
export function ruleReason(rule) {
    return rule ? serverText(rule, 'reason') : '';
}

// A match that a side forfeited by breaking a rule, in words, with the score at that moment.
export function ruleText(rule) {
    const at = Array.isArray(rule.at) ? rule.at : [0, 0];
    return t('tournament.rule.forfeit', { left: at[0], right: at[1], reason: ruleReason(rule) });
}

// How the matches of a fixture were forfeited, a rule broken with its reason and the score at
// that moment, or an award by hand, or null when every match was played out.
export function forfeitWords(matches) {
    const ruled = (matches || []).filter((m) => m && m.result && m.result.rule);
    if (ruled.length) {
        return ruled.map((m) => ruleText(m.result.rule)).join(', ');
    }
    return (matches || []).some((m) => m && m.result && m.result.forfeit) ? t('tournament.fixture.awarded') : null;
}

// The state of a tournament's pre-flight check in words, or null for one without it.
export function preflightText(state, excluded = 0) {
    if (!state) {
        return null;
    }
    if (state === 'done') {
        return excluded ? t('tournament.preflight.state.excluded', { count: excluded }) : t('tournament.preflight.state.done');
    }
    return t(state === 'running' ? 'tournament.preflight.state.running' : 'tournament.preflight.state.waiting');
}

// The address of a file of a tournament's results.
export function fileAddress(id, name) {
    return `/api/tournaments/${encodeURIComponent(id)}/files/${encodeURIComponent(name)}`;
}

// What the analysis of a tournament follows, so the page asks for it again once it changes.
export function analysisStamp(cup) {
    return cup ? `${cup.id}|${cup.played}|${cup.scheduled}|${cup.excluded_count ?? (cup.excluded || []).length}` : '';
}

// The sides of a team's check in order, the left and the right, each with whether it passed, the
// rule it broke and its timings. A side that the check left unplayed, the right after the left
// failed, comes as null, and a check without sides, as a tournament keeps it, has none.
export function checkSides(report) {
    const sides = report && report.sides;
    if (!sides || typeof sides !== 'object') {
        return [];
    }
    return ['left', 'right'].map((side) => (sides[side] ? { side, ...sides[side] } : { side, skipped: true }));
}

// A side of a team's check in words, passed or failed with its reason, then its timings.
export function sideText(side) {
    const name = t(`tournament.check.side.${side.side}`);
    if (side.skipped) {
        return t('tournament.check.skipped', { side: name });
    }
    const state = side.ok ? t('tournament.check.passed', { side: name }) : t('tournament.check.failed', { side: name, reason: ruleReason(side.rule) });
    const timings = timingsText(side.timings);
    return timings ? `${state}, ${timings}` : state;
}

// The warnings of a team's check in the language of the page, each a label of the server.
export function warningTexts(report) {
    return ((report && report.warnings) || []).map((warning) => labelText(warning)).filter(Boolean);
}

// The size of a team's folder in words, or null.
export function folderText(report) {
    const size = report && report.folder_mb;
    return typeof size === 'number' && Number.isFinite(size)
        ? t('tournament.check.folder', { value: formatNumber(size, { maximumFractionDigits: size < 1 ? 2 : size < 10 ? 1 : 0 }) }) : null;
}

// How many matches the ratings rest on and how many of them ended early, in words.
export function playedText(found) {
    const played = (found && found.played) || 0;
    const early = (found && found.cut_short) || 0;
    const parts = [t('tournament.results.played', { count: played })];
    if (played) {
        parts.push(early ? t('tournament.results.cutShort', { count: early }) : t('tournament.results.fullTime'));
    }
    return parts.join(' ');
}

// How the ratings are made, the virtual draws of the prior and the resamples of the bootstrap.
export function methodText(found) {
    const method = (found && found.method) || {};
    const prior = method.prior || {};
    const bootstrap = method.bootstrap || {};
    return t('tournament.results.method', {
        count: prior.virtual_draws ?? 1,
        resamples: formatNumber(bootstrap.resamples ?? (found && found.resamples) ?? 0),
        seed: bootstrap.tournament_seed ?? '',
    });
}
