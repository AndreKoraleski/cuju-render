// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The layout of a tournament's brackets and the words of its tables, kept apart from the page so
// that Node tests read them. A bracket is a grid, one column for each round and as many rows as
// its widest round needs, and each tie spans the rows of the ties that feed it, so a later tie
// sits centred between its two earlier ones.

import { serverText, t, tOr } from '../core/i18n.js';

export const FORMAT_NAMES = {
    knockout: t('tournament.format.knockout'),
    double_elimination: t('tournament.format.double_elimination'),
    league: t('tournament.format.league'),
    groups: t('tournament.format.groups'),
    swiss: t('tournament.format.swiss'),
    ladder: t('tournament.format.ladder'),
    king_of_the_hill: t('tournament.format.king_of_the_hill'),
    gauntlet: t('tournament.format.gauntlet'),
};

export const TIEBREAK_NAMES = {
    goal_difference: t('tournament.tiebreak.goal_difference'),
    goals_for: t('tournament.tiebreak.goals_for'),
    goals_against: t('tournament.tiebreak.goals_against'),
    head_to_head: t('tournament.tiebreak.head_to_head'),
    wins: t('tournament.tiebreak.wins'),
    away_goals: t('tournament.tiebreak.away_goals'),
    fair_play: t('tournament.tiebreak.fair_play'),
    buchholz: t('tournament.tiebreak.buchholz'),
    lots: t('tournament.tiebreak.lots'),
};

// The format of each later stage in a list of stages, as it reads after the first.
const LATER_FORMAT_NAMES = {
    knockout: t('tournament.formatLater.knockout'),
    double_elimination: t('tournament.formatLater.double_elimination'),
    league: t('tournament.formatLater.league'),
    groups: t('tournament.formatLater.groups'),
    swiss: t('tournament.formatLater.swiss'),
    ladder: t('tournament.formatLater.ladder'),
    king_of_the_hill: t('tournament.formatLater.king_of_the_hill'),
    gauntlet: t('tournament.formatLater.gauntlet'),
};

// The formats of a list of stages in a phrase, such as Groups then knockout.
export function formatsText(stages) {
    return (stages || []).map((stage, index) => {
        const names = index === 0 ? FORMAT_NAMES : LATER_FORMAT_NAMES;
        return names[stage.format] || stage.format;
    }).join(t('tournament.formats.then'));
}

// The stage names that the server and its shipped presets give, by their English text, each
// with the message of its label. A stage that a draft holds by such a name shows it in the
// language of the page, and the server keeps the label when the name stays as it was.
export const STAGE_NAME_IDS = {
    Knockout: 'knockout',
    'Double elimination': 'double_elimination',
    League: 'league',
    Groups: 'groups',
    Swiss: 'swiss',
    Ladder: 'ladder',
    'King of the hill': 'king_of_the_hill',
    Gauntlet: 'gauntlet',
    'Group stage': 'group_stage',
    'Knockout stage': 'knockout_stage',
    'League phase': 'league_phase',
    Playoffs: 'playoffs',
    'Round robin': 'round_robin',
    Cup: 'cup',
    'Regular season': 'regular_season',
};

// The name of a stage of a draft in the language of the page, a name that a person typed as
// they typed it.
export function stageNameText(name) {
    const key = typeof name === 'string' && Object.prototype.hasOwnProperty.call(STAGE_NAME_IDS, name) ? STAGE_NAME_IDS[name] : null;
    return key ? tOr(`server.tournament.label.stage.${key}`, name) : (name || '');
}

// The name of an entrant, a name that the server made, such as Built-in AI 0.50, in the
// language of the page, and a name that a person gave as given.
export function entrantName(entrant) {
    return entrant ? serverText(entrant, 'name') : '';
}

// The longest name that a person gives an entrant, as the server takes it.
export const NAME_LONGEST = 40;

// The spaces between the words of a name, those that Python's split takes.
const SPACES = /[\t-\r\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/;

// The words of a name with one space between them, as the server's rules trim it.
function trimmed(name) {
    return String(name ?? '').split(SPACES).filter(Boolean).join(' ');
}

// What two entrant names share when they read as one, trimmed and without case, as `name_key`
// of the server's rules gives it. Each character is lowered, raised and lowered again, which
// folds such letters as the German sharp s, one by one as Python does it.
export function nameKey(name) {
    return Array.from(trimmed(name), (c) => c.toLowerCase().toUpperCase().toLowerCase()).join('');
}

// The name itself, or the name with the first number from 2 whose key no entrant holds, kept to
// the longest name an entrant takes, as `free_name` of the server's rules gives it.
export function freeName(base, taken, longest = NAME_LONGEST) {
    const cut = (text, most) => Array.from(text).slice(0, Math.max(0, most)).join('').trimEnd();
    const clean = cut(trimmed(base), longest ?? Infinity);
    let name = clean;
    for (let number = 2; taken.has(nameKey(name)); number++) {
        const suffix = ` ${number}`;
        name = `${longest == null ? clean : cut(clean, longest - suffix.length)}${suffix}`;
    }
    return name;
}

export const SETTLE_NAMES = {
    away_goals: t('tournament.settle.away_goals'),
    replay: t('tournament.settle.replay'),
    decider: t('tournament.settle.decider'),
    lots: t('tournament.settle.lots'),
};

export const DECIDED_NAMES = {
    score: '',
    aggregate: t('tournament.decided.aggregate'),
    'away goals': t('tournament.decided.away_goals'),
    replay: t('tournament.decided.replay'),
    decider: t('tournament.decided.decider'),
    lots: t('tournament.decided.lots'),
    holder: t('tournament.decided.holder'),
    bye: '',
};

// The sections of a bracket in the order the page draws them.
const SECTIONS = ['play_in', 'main', 'winners', 'losers', 'final', 'third'];

export const SECTION_NAMES = {
    play_in: t('tournament.section.play_in'),
    main: t('tournament.section.main'),
    winners: t('tournament.section.winners'),
    losers: t('tournament.section.losers'),
    final: t('tournament.section.final'),
    third: t('tournament.section.third'),
};

// Whether a stage draws as a bracket.
export function isBracket(stage) {
    return stage.format === 'knockout' || stage.format === 'double_elimination';
}

// The rounds of a bracket stage grouped by section, each section with its rounds in order.
export function sections(stage) {
    const by = new Map();
    for (const round of stage.rounds || []) {
        const name = round.section || (round.fixtures[0] && round.fixtures[0].section) || 'main';
        if (!by.has(name)) {
            by.set(name, []);
        }
        by.get(name).push(round);
    }
    return SECTIONS.filter((name) => by.has(name)).map((name) => ({ name, rounds: by.get(name) }));
}

// The grid of a section, each tie with its column and the rows it spans, counted from 1.
// A round of k ties in a section whose widest round holds `widest` ties spans 2 * widest / k rows
// a tie, so equal rounds stay level and halving rounds centre between their feeders.
export function bracketLayout(rounds) {
    const widest = Math.max(1, ...rounds.map((round) => round.fixtures.length));
    const rows = widest * 2;
    const cells = rounds.map((round, column) => {
        const count = Math.max(1, round.fixtures.length);
        const span = rows / count;
        return round.fixtures.map((fixture, index) => {
            const start = Math.round(index * span) + 1;
            const end = Math.round((index + 1) * span) + 1;
            return { id: fixture.id, column: column + 1, rowStart: start, rowEnd: end };
        });
    });
    return { columns: rounds.length, rows, cells };
}

// The name of a side of a fixture, an entrant, a bye or the tie it comes from, whose words the
// server gives.
export function sideName(side, entrants) {
    if (side === null || side === undefined) {
        return t('tournament.side.bye');
    }
    if (typeof side === 'object') {
        return side.from ? serverText(side, 'from') : t('tournament.side.undecided');
    }
    return entrants[side] ? entrantName(entrants[side]) : t('tournament.side.entrant', { number: side + 1 });
}

// Why a row stands above the next one in a table, in words, or an empty text when its points
// already put it there.
export function tiebreakText(row, next, entrants) {
    if (!row || !next || !row.tiebreak) {
        return '';
    }
    const name = TIEBREAK_NAMES[row.tiebreak] || row.tiebreak;
    const other = sideName(next.entrant, entrants);
    if (row.tiebreak === 'lots') {
        return t('tournament.tiebreakText.lots', { other, name });
    }
    return t('tournament.tiebreakText.points', { other, name });
}

// The share of a tournament played, from 0 to 1, by the matches scheduled so far.
export function progressShare(entry) {
    if (!entry || !entry.scheduled) {
        return entry && entry.state === 'done' ? 1 : 0;
    }
    return entry.state === 'done' ? 1 : Math.min(1, entry.played / entry.scheduled);
}

// A short description of a stage's format for a list, such as Groups of 4 then 2 advance.
export function stageText(stage) {
    const name = FORMAT_NAMES[stage.format] || stage.format;
    const parts = [name];
    if (stage.format === 'groups' && stage.group_sizes) {
        parts.push(t('tournament.stageText.groups', { count: stage.group_sizes.length }));
    }
    if (stage.format === 'swiss' && stage.rounds) {
        parts.push(t('tournament.stageText.rounds', { count: stage.rounds }));
    }
    if ((stage.format === 'knockout' || stage.format === 'double_elimination') && stage.legs > 1) {
        parts.push(t('tournament.stageText.legs', { count: stage.legs }));
    }
    return parts.join(', ');
}

// The matches of a fixture with their entries, in the order of the fixture.
export function fixtureMatches(fixture, matches) {
    return (fixture.matches || []).map((key) => matches.get(key)).filter(Boolean);
}

// The state of a fixture for the page, from the states of its matches.
export function fixtureState(fixture, matches) {
    if (fixture.state === 'done') {
        return 'done';
    }
    if (fixture.state === 'waiting') {
        return 'waiting';
    }
    const states = fixtureMatches(fixture, matches).map((m) => m.state);
    for (const state of ['running', 'playing', 'failed', 'person', 'ready']) {
        if (states.includes(state)) {
            return state;
        }
    }
    return 'waiting';
}

export const STATE_NAMES = {
    done: t('tournament.fixtureState.done'),
    waiting: t('tournament.fixtureState.waiting'),
    running: t('tournament.fixtureState.running'),
    playing: t('tournament.fixtureState.playing'),
    failed: t('tournament.fixtureState.failed'),
    person: t('tournament.fixtureState.person'),
    ready: t('tournament.fixtureState.ready'),
};
