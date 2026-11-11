// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Watching a tournament without spoilers. A person turns it on for one tournament, and the
// browser remembers it with the matches the person has watched or revealed, by their keys. While
// it is on, nothing that tells the outcome of an unwatched match shows, neither in the tournament
// nor in the lists of recordings, Home, the palette and the search of moments. The tournament
// itself comes from the server as the person sees it, through `POST /api/tournaments/ID/spoilers`,
// and the recordings of its unwatched matches lose their scores, teams and titles here. The
// store holds plain data, so the module works alike on the page and in a Node test.

import { serverText, t } from './i18n.js';

const KEY = 'cuju.spoilers';
// The most tournaments the browser remembers, the oldest forgotten first.
const MOST = 200;

let memory = null;

function storage() {
    try {
        return typeof localStorage === 'undefined' ? null : localStorage;
    } catch {
        return null;
    }
}

// Every tournament the browser remembers, by identifier, each with whether it is on, the keys
// of the watched matches, the recordings of its matches by key and the predictions by key.
function load() {
    if (memory) {
        return memory;
    }
    memory = {};
    try {
        const raw = storage()?.getItem(KEY);
        const parsed = raw ? JSON.parse(raw) : null;
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
            for (const [id, entry] of Object.entries(parsed)) {
                if (entry && typeof entry === 'object') {
                    memory[id] = {
                        on: entry.on === true,
                        watched: Array.isArray(entry.watched) ? entry.watched.filter((k) => typeof k === 'string') : [],
                        recordings: entry.recordings && typeof entry.recordings === 'object' ? { ...entry.recordings } : {},
                        predictions: entry.predictions && typeof entry.predictions === 'object' ? { ...entry.predictions } : {},
                        autoplay: entry.autoplay === true,
                        touched: Number(entry.touched) || 0,
                    };
                }
            }
        }
    } catch {
        // A store that cannot be read starts empty, and the page works without it.
    }
    return memory;
}

function save() {
    const all = load();
    const ids = Object.keys(all).sort((a, b) => all[b].touched - all[a].touched);
    for (const id of ids.slice(MOST)) {
        delete all[id];
    }
    try {
        storage()?.setItem(KEY, JSON.stringify(all));
    } catch {
        // A full or blocked store keeps the state for this visit alone.
    }
}

function entry(id, make = false) {
    const all = load();
    if (!all[id] && make) {
        all[id] = { on: false, watched: [], recordings: {}, predictions: {}, autoplay: false, touched: 0 };
    }
    if (all[id] && make) {
        all[id].touched = Date.now();
    }
    return all[id] || null;
}

// Forgets what the module read, so a test or another tab's change reads the store again.
export function reloadSpoilers() {
    memory = null;
}

// Whether a tournament hides its outcomes until they are watched.
export function spoilerFree(id) {
    const own = entry(id);
    return !!(own && own.on);
}

export function setSpoilerFree(id, on) {
    entry(id, true).on = !!on;
    save();
}

// The keys of the matches of a tournament that the person has watched or revealed.
export function watchedKeys(id) {
    const own = entry(id);
    return own ? [...own.watched] : [];
}

export function markWatched(id, ...keys) {
    const own = entry(id, true);
    for (const key of keys) {
        if (typeof key === 'string' && !own.watched.includes(key)) {
            own.watched.push(key);
        }
    }
    save();
}

// Whether the next match plays by itself after a short countdown when one ends.
export function autoplay(id) {
    const own = entry(id);
    return !!(own && own.autoplay);
}

export function setAutoplay(id, on) {
    entry(id, true).autoplay = !!on;
    save();
}

// Keeps the recordings of a tournament's unwatched matches by key, so a list that holds only a
// recording's identifier, such as the hits of a search, knows to leave it out.
export function noteRecordings(id, byKey) {
    const own = entry(id, true);
    let changed = false;
    for (const [key, recording] of Object.entries(byKey || {})) {
        if (typeof recording === 'string' && own.recordings[key] !== recording) {
            own.recordings[key] = recording;
            changed = true;
        }
    }
    if (changed) {
        save();
    }
}

// The prediction of a match, `home`, `draw` or `away`, or null.
export function prediction(id, key) {
    const own = entry(id);
    return own && ['home', 'draw', 'away'].includes(own.predictions[key]) ? own.predictions[key] : null;
}

export function predict(id, key, pick) {
    const own = entry(id, true);
    if (['home', 'draw', 'away'].includes(pick)) {
        own.predictions[key] = pick;
    } else {
        delete own.predictions[key];
    }
    save();
}

// The outcome of a score as a prediction names it.
export function outcome(score) {
    if (!Array.isArray(score) || score.length !== 2) {
        return null;
    }
    return score[0] > score[1] ? 'home' : score[0] < score[1] ? 'away' : 'draw';
}

// The predictions of a tournament scored against the watched matches, the right ones and the
// ones that can be scored, a match counting once its result shows.
export function predictionScore(id, matches) {
    const own = entry(id);
    let right = 0;
    let scored = 0;
    for (const match of matches || []) {
        const pick = own ? own.predictions[match.key] : null;
        if (!pick || !match.result || !Array.isArray(match.result.score)) {
            continue;
        }
        scored += 1;
        if (outcome(match.result.score) === pick) {
            right += 1;
        }
    }
    return { right, scored };
}

// Whether a recording, by the provenance its header or summary keeps, tells the outcome of a
// match that the person has not watched yet.
export function hidesOutcome(provenance) {
    const cup = provenance && provenance.tournament;
    if (!cup || typeof cup.id !== 'string' || typeof cup.key !== 'string') {
        return false;
    }
    const own = entry(cup.id);
    return !!(own && own.on && !own.watched.includes(cup.key));
}

// Whether the recording of this identifier belongs to an unwatched match of a tournament that
// hides its outcomes.
export function hiddenRecording(recording) {
    for (const own of Object.values(load())) {
        if (!own.on) {
            continue;
        }
        for (const [key, id] of Object.entries(own.recordings)) {
            if (id === recording && !own.watched.includes(key)) {
                return true;
            }
        }
    }
    return false;
}

// A summary of a recording as a list shows it, without its score, its teams and its title where
// it tells the outcome of an unwatched match, so the title names only its tournament.
export function hideSummary(summary) {
    if (!summary || !(hidesOutcome(summary.provenance) || hiddenRecording(summary.id))) {
        return summary;
    }
    const cup = (summary.provenance && summary.provenance.tournament) || {};
    const name = cup.name ? serverText(cup, 'name') : '';
    const provenance = { ...summary.provenance, tournament: { id: cup.id, key: cup.key, name: cup.name, name_id: cup.name_id, name_values: cup.name_values } };
    return {
        ...summary,
        title: name ? t('spoilers.recording.title', { name }) : t('spoilers.recording.untitled'),
        title_id: undefined,
        title_values: undefined,
        teams: [],
        team_labels: [],
        score: null,
        provenance,
        spoiler: true,
    };
}

// A list of summaries with the outcomes of unwatched matches hidden.
export function hideSummaries(list) {
    return Array.isArray(list) ? list.map(hideSummary) : list;
}
