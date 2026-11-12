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

// The ability that the built-in AI plays with on an entrant's side in a stage, the entrant's own,
// else the stage's, else the tournament's standard, and null for the scenario's own, as
// `match_ability` of the server's rules gives it.
export function matchAbility(entrant, stage, standard) {
    for (const value of [entrant && entrant.ability, stage && stage.ability, standard]) {
        if (value !== null && value !== undefined) {
            return value;
        }
    }
    return null;
}

// The ability that shows beside an entrant's name, its own where it differs from the standard,
// or null, and null too for a built-in AI whose made name already holds it, as `shown_ability`
// of the server's rules gives it.
export function shownAbility(entrant, standard) {
    const own = entrant ? entrant.ability : null;
    if (own === null || own === undefined || own === (standard ?? null)) {
        return null;
    }
    if (entrant.kind === 'builtin' && entrant.name_id !== null && entrant.name_id !== undefined) {
        return null;
    }
    return own;
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

// The name of each entrant of a list, as `_name_entrants` of the server's rules gives them, from
// the name each shows of its own and whether a person gave it. A given name stays as given, and
// a made one, such as Built-in AI 0.50, takes the first free number from 2 that no given name and
// no earlier made name holds, in the words of `numbered`.
export function madeNames(bases, numbered = (name, number) => t('server.tournament.label.numbered', { name, number })) {
    const names = new Set(bases.filter((base) => base.own).map((base) => nameKey(base.name)));
    return bases.map((base) => {
        if (base.own) {
            return base.name;
        }
        let name = base.name;
        for (let number = 2; names.has(nameKey(name)); number++) {
            name = numbered(base.name, number);
        }
        names.add(nameKey(name));
        return name;
    });
}

// The settings of a stage that the rules work out from the count of its entrants, which a
// tournament run again with other entrants works out anew.
const COUNTED = ['bracket_size', 'advance', 'rounds', 'groups', 'group_sizes', 'pots', 'best_count'];

// The stages of a tournament to run again, those its maker gave when the tournament keeps them,
// else its resolved stages with only the settings of `keys`, and without those that follow from
// the count of entrants, so another count of entrants works them out anew.
export function againStages(config, keys, fallback = []) {
    const given = config && config.given && Array.isArray(config.given.stages) ? config.given.stages : null;
    const stages = given || (config && config.stages) || fallback;
    return JSON.parse(JSON.stringify(stages)).map((stage) => {
        if (given) {
            return stage;
        }
        const own = {};
        for (const [key, value] of Object.entries(stage)) {
            if (keys.includes(key) && !COUNTED.includes(key)) {
                own[key] = value;
            }
        }
        return own;
    });
}

// A message as a sentence of its own, its first letter a capital. The server's refusals start
// small, since most of them continue a sentence of the page, so one that stands alone takes the
// capital here.
export function sentence(text) {
    const value = String(text ?? '');
    return value.replace(/^\p{Ll}/u, (letter) => letter.toLocaleUpperCase());
}

// The line and column of a mistake in a text of JSON, both counted from 1, from the message of
// the browser's JSON.parse, which names them, as Chrome and Firefox do, or names the position of
// the character, else null.
export function jsonErrorPlace(text, error) {
    const message = String((error && error.message) || '');
    const named = /line (\d+) column (\d+)/i.exec(message);
    if (named) {
        return { line: Number(named[1]), column: Number(named[2]) };
    }
    const at = /position (\d+)/i.exec(message);
    if (!at) {
        return null;
    }
    const before = String(text).slice(0, Number(at[1])).split('\n');
    return { line: before.length, column: before.at(-1).length + 1 };
}

// The settings that a person sets by hand in the wizard, at the top of the draft or among its
// defaults, which a preset chosen afterwards keeps where the preset leaves them free.
export const OWN_SETTINGS = ['seeding', 'concurrency', 'forfeit_score', 'ability', 'defaults.scenario', 'defaults.length'];

// The value of each setting of OWN_SETTINGS in a draft that sets none of them.
const DRAFT_SETTINGS = { seeding: 'random', concurrency: 1, forfeit_score: 3, ability: null };

// Whether a preset sets a setting of OWN_SETTINGS itself. A seeding at random and an ability left
// to the scenario are the defaults, so a preset that names them leaves the person's choice free.
function presetSets(preset, key) {
    if (key.startsWith('defaults.')) {
        const name = key.slice('defaults.'.length);
        return !!preset.defaults && preset.defaults[name] !== undefined && preset.defaults[name] !== null;
    }
    if (key === 'seeding') {
        return typeof preset.seeding === 'string' && preset.seeding !== 'random';
    }
    if (key === 'ability') {
        return preset.ability !== undefined && preset.ability !== null;
    }
    return preset[key] !== undefined && preset[key] !== null;
}

function settingOf(source, key) {
    if (key.startsWith('defaults.')) {
        return source.defaults ? source.defaults[key.slice('defaults.'.length)] : undefined;
    }
    return source[key];
}

// The format part of a draft once a person chooses `preset`, its seeding, matches at once, score
// of an award, standard ability and defaults, with the stages of the preset. A setting that the
// person set, by the keys of `own`, stays where the preset leaves it free, and gives way where
// the preset sets another value, which `replaced` lists with the person's value, so the page
// offers to keep it. Any other setting comes from the preset, else from a new draft.
export function presetDraft(draft, preset, own) {
    const values = { defaults: JSON.parse(JSON.stringify(preset.defaults || {})), stages: JSON.parse(JSON.stringify(preset.stages || [])) };
    for (const key of Object.keys(DRAFT_SETTINGS)) {
        values[key] = presetSets(preset, key) ? preset[key] : DRAFT_SETTINGS[key];
    }
    const replaced = [];
    for (const key of OWN_SETTINGS) {
        const mine = settingOf(draft, key);
        if (!own.has(key) || mine === undefined) {
            continue;
        }
        const theirs = settingOf(values, key);
        if (presetSets(preset, key) && JSON.stringify(theirs) !== JSON.stringify(mine)) {
            replaced.push({ key, mine, theirs });
        } else {
            setSetting(values, key, mine);
        }
    }
    return { values, replaced };
}

// Sets a setting of OWN_SETTINGS in a draft or in the values of presetDraft, a default of null
// or undefined by leaving it out.
export function setSetting(target, key, value) {
    if (!key.startsWith('defaults.')) {
        target[key] = value;
        return;
    }
    const name = key.slice('defaults.'.length);
    target.defaults = target.defaults || {};
    if (value === null || value === undefined) {
        delete target.defaults[name];
    } else {
        target.defaults[name] = value;
    }
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

// The caption of a stage's table, which names how it is ordered. A ladder orders by place on the
// ladder and a king of the hill by the king first and then by ties won, while the tables of the
// other formats order by points and then by their tiebreakers.
export function tableCaption(format, tiebreakers) {
    if (format === 'ladder') {
        return t('tournament.table.caption.ladder');
    }
    if (format === 'king_of_the_hill') {
        return t('tournament.table.caption.king');
    }
    const order = (tiebreakers || []).map((name) => TIEBREAK_NAMES[name] || name).join(t('tournament.formats.commaThen'));
    return t('tournament.table.caption', { order });
}

// The share of a tournament played, from 0 to 1, of the matches that the server expects the whole
// tournament to play, or of those scheduled so far when it expects fewer or names none, so the
// share keeps from falling back each time a round is drawn.
export function progressShare(entry) {
    if (!entry) {
        return 0;
    }
    if (entry.state === 'done') {
        return 1;
    }
    const total = Math.max(entry.scheduled || 0, Number(entry.expected) || 0);
    return total ? Math.min(1, entry.played / total) : 0;
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

// The state of a fixture for the page, from the states of its matches. A fixture of a canceled
// tournament that has not ended never plays, and says so.
export function fixtureState(fixture, matches, canceled = false) {
    if (fixture.state === 'done') {
        return 'done';
    }
    if (canceled) {
        return 'cancelled';
    }
    if (fixture.state === 'waiting') {
        return 'waiting';
    }
    const states = fixtureMatches(fixture, matches).map((m) => m.state);
    for (const state of ['running', 'playing', 'failed', 'person', 'unseen', 'ready']) {
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
    unseen: t('tournament.fixtureState.unseen'),
    cancelled: t('tournament.fixtureState.cancelled'),
};

// The labels of the matches that end a tournament or a bracket, which a card announces as such.
const FINAL_LABELS = ['server.tournament.label.final', 'server.tournament.label.grand_final', 'server.tournament.label.grand_final_reset'];

// Whether a match is a final, a leg of one or a grand final, by the label that the rules gave it.
export function isFinal(match) {
    let label = match ? { id: match.label_id, values: match.label_values } : null;
    for (let depth = 0; label && depth < 4; depth++) {
        if (FINAL_LABELS.includes(label.id)) {
            return true;
        }
        label = label.values && typeof label.values.match === 'object' ? label.values.match : null;
    }
    return false;
}

// The matches that come next for a person, those played and waiting to be watched first, in the
// order to watch them, then those still to play while the tournament runs or stopped, at most
// `count`. A tournament that ended or was canceled has no match still to play.
export function upNext(entry, count = 4) {
    if (!entry || !Array.isArray(entry.matches)) {
        return [];
    }
    const unseen = (entry.spoilers && entry.spoilers.unseen) || [];
    const byKey = new Map(entry.matches.map((m) => [m.key, m]));
    const watch = unseen.map((key) => byKey.get(key)).filter(Boolean);
    const open = entry.state === undefined || entry.state === 'running' || entry.state === 'stopped';
    const play = open ? entry.matches.filter((m) => !m.result && m.state !== 'unseen' && typeof m.home === 'number' && typeof m.away === 'number') : [];
    return [...watch, ...play].slice(0, count);
}
