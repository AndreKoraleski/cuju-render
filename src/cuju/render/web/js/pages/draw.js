// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The choices of the Matches page for a match drawn at random, which side and scenario are drawn,
// the pool of teams a random side draws from, the scenarios that fit, and the requests of Play
// match, Retry and Repeat. The module touches no page, so the Node tests run it alone. The server
// draws the teams and the scenario from the seed of the request, src/cuju/render/_playing/draw.py.

// The word that stands for a team or a scenario drawn at random, as the server reads it.
export const RANDOM = 'random';

// Scenarios a team may play, by its format. The built-in AI plays any.
export function fits(team, scenario) {
    if (!team || team.kind === 'builtin' || !team.format) {
        return true;
    }
    if (scenario.startsWith('academy_')) return true;
    const name = scenario.replace(/^benchmark_full_game_/, '');
    return team.format === '5v5' ? name.startsWith('5_vs_5') : name.startsWith('11_vs_11');
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

// The teams that a side can draw for a scenario, or the side's own team in a list of one.
export function sideTeams(teams, unticked, id, scenario) {
    if (id === RANDOM) {
        return poolTeams(teams, unticked).filter((x) => fits(x, scenario));
    }
    const own = teams.find((x) => x.id === id);
    return own && fits(own, scenario) ? [own] : [];
}

// The scenarios that the two sides can play, those where each side has a team that fits.
export function fittingScenarios(scenarios, teams, unticked, left, right) {
    return scenarios.filter((sc) => sideTeams(teams, unticked, left, sc).length
        && sideTeams(teams, unticked, right, sc).length);
}

// The scenario list of the setup, Random scenario first when two or more fit, and the choice it
// keeps, the current one while it still fits, else the default, else 5 against 5, else the first.
export function scenarioChoices(scenarios, teams, unticked, left, right, current, preferred) {
    const ok = fittingScenarios(scenarios, teams, unticked, left, right);
    const listed = ok.length > 1 ? [RANDOM, ...ok] : ok;
    const keep = listed.includes(current) ? current
        : ok.includes(preferred) ? preferred
            : ok.includes('5_vs_5') ? '5_vs_5' : ok[0] || null;
    return { listed, keep };
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

// Whether a part of a request shows as Random, a part drawn at random while the match waits. The
// teams and the scenario drawn show once the match starts.
export function hiddenPart(r, part) {
    return r.state === 'queued' && drawnParts(r)[part];
}
