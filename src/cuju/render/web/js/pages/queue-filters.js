// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The Team and Scenario filters of the list of requested matches on the Matches page, what they
// offer and which requests they keep. A part drawn at random stays out of them while its match
// waits, as the list shows it as Random, so no filter tells what the draw picked before the match
// starts. The module touches no page, so the Node tests run it alone.

import { hiddenPart } from './draw.js';

// The teams of a request that the list shows by name, null for a side that shows as Random.
export function shownTeams(r) {
    return [hiddenPart(r, 'left') ? null : r.left, hiddenPart(r, 'right') ? null : r.right];
}

// The scenario of a request that the list shows by name, null while it shows as Random.
export function shownScenario(r) {
    return hiddenPart(r, 'scenario') ? null : r.scenario;
}

// The teams that the Team filter offers, those the list shows by name. They come in the order of
// the registry, the order of the team lists of a new match, so they keep their places as requests
// come and go, and a team that the registry no longer holds comes after them.
export function filterTeams(requests, teams) {
    const named = new Set(requests.flatMap(shownTeams).filter((id) => typeof id === 'string'));
    const known = new Set(teams.map((x) => x.id));
    return [...teams.map((x) => x.id).filter((id) => named.has(id)), ...[...named].filter((id) => !known.has(id))];
}

// The scenarios that the Scenario filter offers, those the list shows by name, in order.
export function filterScenarios(requests) {
    return [...new Set(requests.map(shownScenario).filter((sc) => typeof sc === 'string'))].sort();
}

// The values of the filters, Every team and Every scenario as ALL, and each team or scenario
// after a prefix, so a team or a scenario whose name is the word all never reads as every one.
export const ALL = 'all';

export function teamValue(id) {
    return `team:${id}`;
}

export function scenarioValue(name) {
    return `scenario:${name}`;
}

// Whether a request passes the Team filter and the Scenario filter by their values, ALL passing
// every request.
export function passesTeam(r, value) {
    return value === ALL || shownTeams(r).some((id) => id !== null && teamValue(id) === value);
}

export function passesScenario(r, value) {
    const scenario = shownScenario(r);
    return value === ALL || (scenario !== null && scenarioValue(scenario) === value);
}

// The teams that the requests name and the registry does not hold, a team added since the page
// loaded the registry or one removed since.
export function unknownTeams(requests, teams) {
    const known = new Set(teams.map((x) => x.id));
    return [...new Set(requests.flatMap((r) => [r.left, r.right]))].filter((id) => typeof id === 'string' && !known.has(id));
}
