// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The scenarios that the page lists, and a short text for each. The texts take their facts from
// the scenario files and the scenarios page of the docs. The GRF MARL training variants and GRF's
// example of several agents stay playable from Python and the API, and the page lists leave them
// out.

import { formatNumber, has, setValueKind, t, tOr } from './i18n.js';

const HIDDEN = /^(benchmark_full_game_|test_)/;

// The scenarios with a name and a text of their own, whose messages are scenario.<name>.name and
// scenario.<name>.text. The text of a drill ends on the sentences of its end and its difficulty,
// the placeholders end and level, and the end of an academy episode is a goal, the ball out of
// play or a change of possession, else the number of steps of the drill.
const NAMED = [
    '11_vs_11_stochastic', '11_vs_11_easy_stochastic', '11_vs_11_hard_stochastic', '11_vs_11_competition',
    '11_vs_11_kaggle', '5_vs_5', '1_vs_1_easy', 'academy_empty_goal_close', 'academy_empty_goal',
    'academy_run_to_score', 'academy_run_to_score_with_keeper', 'academy_pass_and_shoot_with_keeper',
    'academy_run_pass_and_shoot_with_keeper', 'academy_3_vs_1_with_keeper', 'academy_corner',
    'academy_counterattack_easy', 'academy_counterattack_hard', 'academy_single_goal_versus_lazy',
];
const ACADEMY_STEPS = { academy_single_goal_versus_lazy: 3001 };

function textOf(name) {
    const id = `scenario.${name}.text`;
    if (!has(id)) {
        return '';
    }
    return t(id, {
        end: t('scenario.academy.end', { steps: formatNumber(ACADEMY_STEPS[name] || 401) }),
        level: t('scenario.academy.level'),
    });
}

export const SCENARIO_TEXT = Object.fromEntries(NAMED.map((name) => [name, textOf(name)]));

// The agents of a name such as 5_vs_5_l4_r0, in words. The built-in AI playing both teams, l0 r0,
// says nothing, since the teams of a recording already name who plays.
function agentsText(left, right) {
    const count = (n) => t('scenario.agents.count', { count: n });
    if (!left && !right) {
        return '';
    }
    if (!right) {
        return t('scenario.agents.left', { agents: count(left) });
    }
    if (!left) {
        return t('scenario.agents.right', { agents: count(right) });
    }
    return left === right ? t('scenario.agents.aSide', { agents: count(left) }) : t('scenario.agents.both', { agents: count(left), right });
}

// The name of a scenario as the page shows it. A scenario without its own name, such as a
// training variant or a custom file, reads in words, with its underscores as spaces. The suffix
// of agents on each side, as in 5_vs_5_l0_r0, reads in words after the scenario's name.
export function scenarioName(name) {
    if (!name) {
        return '';
    }
    if (has(`scenario.${name}.name`)) {
        return t(`scenario.${name}.name`);
    }
    const agents = /^(.+)_l(\d+)_r(\d+)$/.exec(name);
    if (agents) {
        const words = agentsText(Number(agents[2]), Number(agents[3]));
        const base = scenarioName(agents[1]);
        return words ? t('scenario.agents.join', { base, words }) : base;
    }
    const marl = /^benchmark_full_game_(\d+)_vs_(\d+)_(easy|medium|hard)$/.exec(name);
    if (marl) {
        return tOr('scenario.marl.name', `GRF MARL ${marl[1]} vs ${marl[2]}, ${marl[3]}`, {
            left: marl[1], right: marl[2], level: tOr(`scenario.marl.level.${marl[3]}`, marl[3]),
        });
    }
    const words = String(name).replace(/_/g, ' ').trim();
    return tOr(`scenario.${name}.name`, words.charAt(0).toUpperCase() + words.slice(1));
}

// A title as the page shows it. Titles that a batch or a recorder made by itself start with the
// name of their scenario, which reads in the language of the page here, so older recordings show the
// same.
export function titleText(title, scenario) {
    if (!title) {
        return '';
    }
    if (scenario && title.startsWith(scenario)) {
        return scenarioName(scenario) + title.slice(scenario.length);
    }
    return title.replace(/^([a-z0-9]+(?:_[a-z0-9]+)+)(?=,|$)/, (name) => scenarioName(name));
}

// The names a page list shows, in the order given.
export function listedScenarios(names) {
    return names.filter((name) => !HIDDEN.test(name));
}

// The short text of a scenario, empty for one without a text.
export function scenarioText(name) {
    return SCENARIO_TEXT[name] || textOf(name);
}

// A scenario that a message of the server names shows by its name on the page.
setValueKind('scenario', (name) => scenarioName(String(name || '')));
