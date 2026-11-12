// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The choices of the Matches page for a match drawn at random, which side and scenario are drawn,
// the pool of teams a random side draws from, the scenarios that fit, and the requests of Play
// match, Retry and Repeat. The module touches no page, so the Node tests run it alone. The server
// draws the teams and the scenario from the seed of the request, src/cuju/render/_playing/draw.py.

// The word that stands for a team or a scenario drawn at random, as the server reads it.
export const RANDOM = 'random';

// The players a side of each format holds, and the roles of GRF by number, as
// src/cuju/render/_registry/teams.py names them.
const FORMAT_SIZES = { '5v5': 5, '11v11': 11 };
const ROLES = ['GK', 'CB', 'LB', 'RB', 'DM', 'CM', 'LM', 'RM', 'AM', 'CF'];

// The players a side of a full match holds, 5 or 11, or null for any other scenario.
function scenarioSize(scenario) {
    const name = scenario.replace(/^benchmark_full_game_/, '');
    return name.startsWith('5_vs_5') ? 5 : name.startsWith('11_vs_11') ? 11 : null;
}

// Why a control setting cannot play a side, as a message and its values, or null when it can,
// the rule of selected_players in src/cuju/render/_registry/teams.py. The formation lists each
// player of the side by its role, 0 for the goalkeeper, and whether a team can control it.
export function controlFault(control, formation) {
    const c = { players: 1, assignment: 'dynamic', selection: [], goalkeeper: 'scenario', ...(control || {}) };
    const available = formation.flatMap((p, i) => (p.controllable ? [i] : []));
    if (c.players > available.length) {
        return { id: 'server.teams.control.too_few', values: { count: available.length } };
    }
    const keeper = formation.flatMap((p, i) => (p.role === 0 ? [i] : []));
    const freeKeeper = keeper.some((i) => available.includes(i));
    if (c.assignment === 'dynamic') {
        return c.goalkeeper === 'agent' && !freeKeeper ? { id: 'server.teams.control.goalkeeper_uncontrollable', values: {} } : null;
    }
    const selected = [];
    for (const item of c.selection) {
        const candidates = Number.isInteger(item) ? [item] : available.filter((i) => formation[i].role === ROLES.indexOf(item));
        const found = candidates.find((i) => available.includes(i) && !selected.includes(i));
        if (found === undefined) {
            return { id: 'server.teams.control.select_player', values: { player: String(item) } };
        }
        selected.push(found);
    }
    const ownsKeeper = selected.some((i) => keeper.includes(i));
    const fault = c.goalkeeper === 'builtin' && !freeKeeper ? 'goalkeeper_builtin'
        : c.goalkeeper === 'agent' && !ownsKeeper ? 'goalkeeper_selected'
            : c.goalkeeper !== 'agent' && ownsKeeper ? 'goalkeeper_outside'
                : c.goalkeeper === 'scenario' && freeKeeper ? 'goalkeeper_scenario' : null;
    return fault ? { id: `server.teams.control.${fault}`, values: {} } : null;
}

// Why a team cannot play a side of a scenario, or null when it can, as the server checks it
// before it queues a match. A team of the other format cannot play a full match of the wrong
// size, the message matches.draw.unfit.format, and with the players of the scenario's sides,
// which the server lists at /api/scenarios/sides, the team's control must fit the side. The
// built-in AI plays any side, and a scenario whose players the page lacks checks the format alone.
export function unfit(team, scenario, side = 0, sides = null) {
    if (!team || team.kind === 'builtin' || !team.format || !scenario) {
        return null;
    }
    const size = scenarioSize(scenario);
    if (size !== null && FORMAT_SIZES[team.format] && size !== FORMAT_SIZES[team.format]) {
        return { id: 'matches.draw.unfit.format', values: { format: team.format } };
    }
    const formation = sides && Array.isArray(sides[scenario]) ? sides[scenario][side] : null;
    return Array.isArray(formation) ? controlFault(team.control, formation) : null;
}

// Whether a team can play a side of a scenario.
export function fits(team, scenario, side = 0, sides = null) {
    return unfit(team, scenario, side, sides) === null;
}

// The teams of the pool, every team of the registry but those the person unticked.
export function poolTeams(teams, unticked) {
    return teams.filter((x) => !unticked.has(x.id));
}

// The pool as a request names it, null for every team, so a team added later joins the draw.
export function poolOf(teams, unticked) {
    const kept = poolTeams(teams, unticked).map((x) => x.id);
    return kept.length === teams.length ? null : kept;
}

// The teams that a side, 0 on the left, can draw for a scenario, or the side's own team in a list
// of one. `sides` holds the players of the scenarios' sides, as `unfit` reads them.
export function sideTeams(teams, unticked, id, scenario, side = 0, sides = null) {
    if (id === RANDOM) {
        return poolTeams(teams, unticked).filter((x) => fits(x, scenario, side, sides));
    }
    const own = teams.find((x) => x.id === id);
    return own && fits(own, scenario, side, sides) ? [own] : [];
}

// The scenarios that the two sides can play, those where each side has a team that fits.
export function fittingScenarios(scenarios, teams, unticked, left, right, sides = null) {
    return scenarios.filter((sc) => sideTeams(teams, unticked, left, sc, 0, sides).length
        && sideTeams(teams, unticked, right, sc, 1, sides).length);
}

// The scenario list of the setup, Random scenario first when two or more fit, and the choice it
// keeps, the current one while it still fits, else the default, else 5 against 5, else the first.
export function scenarioChoices(scenarios, teams, unticked, left, right, current, preferred, sides = null) {
    const ok = fittingScenarios(scenarios, teams, unticked, left, right, sides);
    const listed = ok.length > 1 ? [RANDOM, ...ok] : ok;
    const keep = listed.includes(current) ? current
        : ok.includes(preferred) ? preferred
            : ok.includes('5_vs_5') ? '5_vs_5' : ok[0] || null;
    return { listed, keep };
}

// The teams that a random side can draw, in the order of the registry, those of the pool that can
// play the side in the chosen scenario, or in a scenario that both sides can play when the
// scenario is random. The two sides take different teams whenever another team fits, unless a
// team may meet itself, as the server draws, src/cuju/render/_playing/draw.py.
export function drawableTeams(teams, unticked, state, side, scenarios, sides = null) {
    const names = state.scenario === RANDOM
        ? fittingScenarios(scenarios.filter((sc) => sc !== RANDOM), teams, unticked, state.left, state.right, sides)
        : [state.scenario];
    const found = new Set();
    for (const sc of names.filter(Boolean)) {
        const lefts = sideTeams(teams, unticked, state.left, sc, 0, sides);
        const rights = sideTeams(teams, unticked, state.right, sc, 1, sides);
        const every = lefts.flatMap((l) => rights.map((r) => [l.id, r.id]));
        const pairs = state.sameTeam ? every : every.filter(([l, r]) => l !== r);
        (pairs.length ? pairs : every).forEach((pair) => found.add(pair[side]));
    }
    return teams.filter((x) => found.has(x.id));
}

// Whether the setup draws anything, a side or the scenario.
export function drawsAny(state) {
    return state.left === RANDOM || state.right === RANDOM || state.scenario === RANDOM;
}

// The request of Play match, which names the pool and whether a team may meet itself only when a
// side draws.
export function requestOf(state, teams, seed) {
    const spec = {
        left: state.left, right: state.right, scenario: state.scenario, seed,
        ability: state.ability.slice(),
    };
    if (state.left === RANDOM || state.right === RANDOM) {
        spec.pool = poolOf(teams, state.unticked);
        spec.same_team = !!state.sameTeam;
    }
    return spec;
}

// The parts of a request that were drawn at random, by its draw, none for a request without.
export function drawnParts(r) {
    const d = r && r.draw && typeof r.draw === 'object' ? r.draw : null;
    const sides = d && Array.isArray(d.sides) ? d.sides : [];
    return { left: sides[0] === true, right: sides[1] === true, scenario: !!(d && d.scenario === true) };
}

// Whether a request draws anything at random.
export function wasDrawn(r) {
    const parts = drawnParts(r);
    return parts.left || parts.right || parts.scenario;
}

// The request of Retry or Repeat. Retry keeps the seed, so it draws the same teams and scenario
// again. Repeat of a match drawn at random leaves the seed to the server, which draws anew, and
// Repeat of any other match keeps its seed, as it always has.
export function againOf(r, repeat) {
    const parts = drawnParts(r);
    const spec = {
        left: parts.left ? RANDOM : r.left, right: parts.right ? RANDOM : r.right,
        scenario: parts.scenario ? RANDOM : r.scenario,
        seed: repeat && wasDrawn(r) ? null : r.seed, ability: r.ability,
    };
    if (parts.left || parts.right) {
        spec.pool = Array.isArray(r.draw.pool) ? r.draw.pool.slice() : null;
        spec.same_team = r.draw.same_team === true;
    }
    return spec;
}

// Whether a part of a request shows as Random, a part drawn at random of a match that has not
// started, one that waits or one that was cancelled or interrupted before it started. The teams
// and the scenario drawn show once the match starts.
export function hiddenPart(r, part) {
    const unstarted = r.state === 'queued' || (r.state === 'failed' && typeof r.started !== 'number');
    return unstarted && drawnParts(r)[part];
}
