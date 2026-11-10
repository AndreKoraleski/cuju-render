// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The query helpers of the search of moments, which touch nothing of the page, so they hold the
// same under Node. The server reads the query language, src/cuju/render/_moments/search.py, and these
// helpers only tell a search from other typing and add the terms of the panel's filters.

// The words of the query language that name kinds of moments, as the server reads them.
export const KIND_WORDS = Object.freeze([
    'goal', 'goals', 'own-goal', 'shot', 'shots', 'header', 'headers', 'save', 'saves', 'block',
    'blocks', 'woodwork', 'post', 'bar', 'near-miss', 'miss', 'pass', 'passes', 'tackle', 'tackles',
    'slide', 'foul', 'fouls', 'card', 'cards', 'yellow', 'red', 'offside', 'offsides', 'restart',
    'restarts', 'set-piece', 'set-pieces', 'corner', 'corners', 'free-kick', 'free-kicks', 'penalty',
    'penalties', 'throw-in', 'throw-ins', 'goal-kick', 'goal-kicks', 'kickoff', 'kick-off',
    'possession', 'turnover', 'turnovers', 'halftime', 'half-time', 'fulltime', 'full-time',
]);
const KINDS = new Set(KIND_WORDS);
const FILTER = /(^|\s)-?[a-z]+:/i;

// Whether a line typed in the palette reads as a search of moments, a kind first or a filter.
export function looksLikeMoments(query) {
    const text = String(query || '').trim().toLowerCase();
    if (!text) {
        return false;
    }
    const first = text.split(/\s+/)[0].replace(/^-/, '');
    return KINDS.has(first) || FILTER.test(text);
}

// The query of the panel, the typed line with the terms of the chosen filters.
export function composeQuery(text, filters = {}) {
    const terms = [String(text || '').trim()];
    const quote = (v) => (/\s/.test(v) ? `"${v.replace(/"/g, '')}"` : v);
    if (filters.kind) {
        terms.push(`kind:${filters.kind}`);
    }
    if (filters.team) {
        terms.push(`team:${quote(filters.team)}`);
    }
    if (filters.player) {
        terms.push(`player:${quote(String(filters.player).trim())}`);
    }
    if (filters.scenario) {
        terms.push(`scenario:${filters.scenario}`);
    }
    if (filters.source) {
        terms.push(`source:${filters.source}`);
    }
    if (filters.since) {
        terms.push(`since:${filters.since}`);
    }
    if (filters.score) {
        terms.push(`score:${filters.score}`);
    }
    if (filters.time) {
        terms.push(filters.time);
    }
    return terms.filter(Boolean).join(' ');
}
