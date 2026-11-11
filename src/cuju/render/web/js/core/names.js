// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The names and titles that the server makes, such as the built-in AI, the sides Left and Right,
// You or the title of a recording, in the language of the page. The server sends each such name
// as a label, its English text in `name` or `title` with the message beside it in `name_id` and
// `name_values`, or `title_id` and `title_values`, and a name that a person gave as text alone,
// which shows as given. A recording of before holds the English text alone and shows it. A
// field of a malformed file that is no text shows as the empty text, or as the digits of a number.

import { labelText, plainText, serverText, setValueKind, tOr } from './i18n.js';
import { titleText } from './scenarios.js';

// A challenge that a message names, as in the title of an attempt, shows by its own title.
setValueKind('challenge', (name, label) => tOr(`challenge.${name}.title`, (label && label.text) || name));

// The messages that the names and titles of recordings carry, the names that cuju makes and the
// labels of tournaments. A name or a title that names any other message shows its English text.
const NAME_MESSAGE = /^server\.(names|tournament\.label)\./;
const isNameMessage = (id) => typeof id === 'string' && NAME_MESSAGE.test(id);

// The shipped samples, whose files keep the English title they ship with, by recording id.
const SAMPLES = {
    'sample-5v5': ['Sample match, 5 vs 5', 'server.names.sample_5v5'],
    'sample-11v11': ['Sample match, 11 vs 11', 'server.names.sample_11v11'],
};

// The name of a team, of a recording's header, of the registry or of a game, in the page's
// language, or the empty text for none.
export function teamName(team) {
    if (!team || typeof team !== 'object') {
        return typeof team === 'string' ? team : '';
    }
    return typeof team.name === 'string' ? serverText(team, 'name', isNameMessage) : '';
}

// The names of the two teams of a summary of the library or of a game's entry, which hold the
// English names in `teams` and the label of each made name in `team_labels`.
export function summaryTeams(summary) {
    const names = summary && Array.isArray(summary.teams) ? summary.teams : [];
    const labels = summary && Array.isArray(summary.team_labels) ? summary.team_labels : [];
    return names.map((name, i) => (labels[i] && typeof labels[i] === 'object' ? labelText(labels[i], isNameMessage) : plainText(name)));
}

// The texts of a list of a summary, such as its English team names or its tags, and the empty list
// for anything that is no list.
export function textList(value) {
    return Array.isArray(value) ? value.map(plainText) : [];
}

// The summaries of the library as the lists of the page read them. A field of the wrong kind, as
// a malformed header leaves it, becomes text, a list of texts or nothing, so every list shows each
// recording, its id where its title is no text. Anything but a list of summaries is no recording.
const TEXT_FIELDS = ['title', 'scenario', 'notes', 'folder'];
const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
export function summaryList(list) {
    return Array.isArray(list) ? list.filter((m) => isObject(m) && typeof m.id === 'string').map(cleanSummary) : [];
}

function cleanSummary(summary) {
    const m = { ...summary };
    for (const key of TEXT_FIELDS) {
        if (key in m && typeof m[key] !== 'string') {
            m[key] = plainText(m[key]);
        }
    }
    for (const key of ['teams', 'tags']) {
        if (key in m) {
            m[key] = textList(m[key]);
        }
    }
    if ('team_labels' in m) {
        m.team_labels = Array.isArray(m.team_labels) ? m.team_labels.map((label) => (isObject(label) ? label : null)) : null;
    }
    if ('score' in m && !(Array.isArray(m.score) && m.score.length === 2 && m.score.every(Number.isFinite))) {
        delete m.score;
    }
    for (const key of ['created', 'steps', 'bytes']) {
        if (key in m && !(typeof m[key] === 'string' || Number.isFinite(m[key]))) {
            delete m[key];
        }
    }
    for (const key of ['provenance', 'group']) {
        if (key in m && !isObject(m[key])) {
            delete m[key];
        }
    }
    return m;
}

// The title of a recording, a summary, a header or a live source, in the page's language. A
// title that the server made comes with its message, a shipped sample is known by its id, and any
// other title reads as titleText reads it, with its scenario in words. `id` is the recording's
// identifier when the object itself holds none, as a header does.
export function recordingTitle(item, id = null) {
    if (!item || typeof item !== 'object') {
        return '';
    }
    if (typeof item.title === 'string' && isNameMessage(item.title_id)) {
        return serverText(item, 'title', isNameMessage);
    }
    const sample = Object.prototype.hasOwnProperty.call(SAMPLES, id || item.id) ? SAMPLES[id || item.id] : null;
    if (sample && item.title === sample[0]) {
        return tOr(sample[1], item.title);
    }
    return titleText(item.title, item.scenario);
}
