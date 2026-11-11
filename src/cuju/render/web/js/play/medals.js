// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The medals of a challenge as items, gold, silver and bronze in that order, each with the medal's
// symbol in the color of its metal, its target in words and numbers, and a mark on the item that a
// run or a competitor's best reached. medalItems mirrors medal_items of challenges.py, and the two
// share their cases in tests/support/medal_items.json.

import { formatNumber, t, tn } from '../core/i18n.js';
import { el as h } from '../core/menu.js';
import { icon } from '../core/icons.js';

// The medals from the best down, and the order of a challenge's targets, from bronze up.
export const MEDAL_ORDER = ['gold', 'silver', 'bronze'];
const TARGET_ORDER = ['bronze', 'silver', 'gold'];

// The color of each metal's symbol and name in the dark and the light theme. Each keeps a contrast
// of 4.5 to 1 or more on every surface of its theme, the page, the cards and the raised parts.
export const METALS = {
    gold: { dark: '#f2c14e', light: '#7a5800' },
    silver: { dark: '#c5cbd3', light: '#5c636d' },
    bronze: { dark: '#e3a172', light: '#94501f' },
};

// The best medal whose target a value reaches, or null.
export function medalOf(challenge, value) {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
        return null;
    }
    let won = null;
    TARGET_ORDER.forEach((medal, index) => {
        if (value >= challenge.targets[index]) {
            won = medal;
        }
    });
    return won;
}

// The items of a challenge's medals, each its medal, its target, whether the target asks for a goal
// in every attempt, and whether `value`, a run's or a best run's, reached that medal, so one item at
// most is marked.
export function medalItems(challenge, value = null) {
    const won = value == null ? null : medalOf(challenge, value);
    return MEDAL_ORDER.map((medal) => {
        const target = challenge.targets[TARGET_ORDER.indexOf(medal)];
        return {
            medal,
            target,
            every: challenge.measure !== 'margin' && target >= challenge.attempts,
            reached: won === medal,
        };
    });
}

export function medalName(medal) {
    return t(`challenges.medal.${medal}`);
}

function number(value) {
    return formatNumber(value, { useGrouping: false, maximumFractionDigits: 10 });
}

// The target of an item in words, such as a goal in all 5 attempts or 3 goals or more ahead.
export function targetText(challenge, item) {
    const limit = number(challenge.limit);
    if (challenge.measure === 'margin') {
        return t('challenges.medals.margin', { count: item.target });
    }
    const kind = challenge.measure === 'within' ? 'within' : 'scored';
    if (item.every) {
        return t(`challenges.medals.${kind}.every`, { count: challenge.attempts, limit });
    }
    return t(`challenges.medals.${kind}`, { count: item.target, limit });
}

// The item in words alone, its medal and its target, as a screen reader or a tooltip reads it.
export function itemText(challenge, item) {
    return t('challenges.medals.item', { medal: medalName(item.medal), target: targetText(challenge, item) });
}

// The colors of the metals in both themes, the light one from the system or the page.
function metalRules(theme, scope = '') {
    return `${scope}{ ${Object.entries(METALS).map(([medal, colors]) => `--metal-${medal}: ${colors[theme]};`).join(' ')} }`;
}

export function medalStyle() {
    return `
${metalRules('dark', ':root ')}
@media (prefers-color-scheme: light) {
${metalRules('light', ':root:not([data-theme="dark"]) ')}
}
${metalRules('light', ':root[data-theme="light"] ')}
.medal-items { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; font-size: 13px; }
.medal-item { display: flex; align-items: center; flex-wrap: wrap; gap: 2px 6px; }
.medal-item > .icon, .medal-mark > .icon { width: 16px; height: 16px; flex: none; }
.medal-name { font-weight: 600; }
.medal-item.gold > .icon, .medal-item.gold .medal-name, .medal-mark.gold { color: var(--metal-gold); }
.medal-item.silver > .icon, .medal-item.silver .medal-name, .medal-mark.silver { color: var(--metal-silver); }
.medal-item.bronze > .icon, .medal-item.bronze .medal-name, .medal-mark.bronze { color: var(--metal-bronze); }
.medal-item.reached { font-weight: 600; }
.medal-reached { display: inline-flex; align-items: center; gap: 3px; font-size: 11px; line-height: 1.4; padding: 0 6px;
    border-radius: 8px; border: 1px solid currentColor; }
.medal-reached .icon { width: 12px; height: 12px; }
.medal-mark { display: inline-flex; align-items: center; gap: 4px; font-weight: 600; }
`;
}

// The list of a challenge's medals, with the item that `value` reached marked by `mark`, the words
// of the mark such as Your best.
export function medalList(challenge, value = null, mark = '', label = '') {
    return h('ul', { class: 'medal-items', ...(label ? { 'aria-label': label } : {}) },
        ...medalItems(challenge, value).map((item) => h('li', {
            class: `medal-item ${item.medal}${item.reached ? ' reached' : ''}`, 'data-medal': item.medal,
        },
        icon('podium'),
        h('span', {}, ...tn('challenges.medals.item', { medal: h('span', { class: 'medal-name' }, medalName(item.medal)), target: targetText(challenge, item) })),
        item.reached && mark ? [' ', h('span', { class: 'medal-reached' }, icon('check'), mark)] : null)));
}

// A medal by its symbol in its metal's color and its name, as a leaderboard or a table shows it,
// or the words for none.
export function medalMark(medal, none = '') {
    if (!MEDAL_ORDER.includes(medal)) {
        return h('span', { class: 'medal-mark none' }, none);
    }
    return h('span', { class: `medal-mark ${medal}`, 'data-medal': medal }, icon('podium'), medalName(medal));
}
