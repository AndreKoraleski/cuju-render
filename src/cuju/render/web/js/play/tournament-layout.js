// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The layout of a tournament's brackets and the words of its tables, kept apart from the page so
// that Node tests read them. A bracket is a grid, one column for each round and as many rows as
// its widest round needs, and each tie spans the rows of the ties that feed it, so a later tie
// sits centred between its two earlier ones.

export const FORMAT_NAMES = {
    knockout: 'Knockout',
    double_elimination: 'Double elimination',
    league: 'League',
    groups: 'Groups',
    swiss: 'Swiss system',
    ladder: 'Ladder',
    king_of_the_hill: 'King of the hill',
    gauntlet: 'Gauntlet',
};

export const TIEBREAK_NAMES = {
    goal_difference: 'goal difference',
    goals_for: 'goals scored',
    goals_against: 'fewer goals conceded',
    head_to_head: 'the matches between them',
    wins: 'wins',
    away_goals: 'away goals',
    fair_play: 'fair play',
    buchholz: 'Buchholz, the points of the opponents met',
    lots: 'lots drawn from the tournament seed',
};

export const SETTLE_NAMES = {
    away_goals: 'Away goals',
    replay: 'A replay',
    decider: 'A deciding match',
    lots: 'Lots from the seed',
};

export const DECIDED_NAMES = {
    score: '',
    aggregate: 'on aggregate',
    'away goals': 'on away goals',
    replay: 'after a replay',
    decider: 'after a deciding match',
    lots: 'by lots',
    holder: 'holds on a draw',
    bye: '',
};

// The sections of a bracket in the order the page draws them.
const SECTIONS = ['play_in', 'main', 'winners', 'losers', 'final', 'third'];

export const SECTION_NAMES = {
    play_in: 'Play-in round',
    main: 'Bracket',
    winners: 'Winners bracket',
    losers: 'Losers bracket',
    final: 'Grand final',
    third: 'Third place',
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

// The name of a side of a fixture, an entrant, a bye or the tie it comes from.
export function sideName(side, entrants) {
    if (side === null || side === undefined) {
        return 'Bye';
    }
    if (typeof side === 'object') {
        return side.from || 'To be decided';
    }
    return entrants[side] ? entrants[side].name : `Entrant ${side + 1}`;
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
        return `Level with ${other} on every tiebreaker, placed above by ${name}`;
    }
    return `Level on points with ${other}, placed above on ${name}`;
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
        parts.push(`${stage.group_sizes.length} groups`);
    }
    if (stage.format === 'swiss' && stage.rounds) {
        parts.push(`${stage.rounds} rounds`);
    }
    if ((stage.format === 'knockout' || stage.format === 'double_elimination') && stage.legs > 1) {
        parts.push(`${stage.legs} legs`);
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
    done: 'Played',
    waiting: 'Waiting for earlier results',
    running: 'Playing',
    playing: 'A person is playing',
    failed: 'Failed',
    person: 'Ready for a person',
    ready: 'In the queue',
};
