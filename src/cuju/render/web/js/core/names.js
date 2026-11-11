// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The names and titles that the server makes, such as the built-in AI, the sides Left and Right,
// You or the title of a recording, in the language of the page. The server sends each such name
// as a label, its English text in `name` or `title` with the message beside it in `name_id` and
// `name_values`, or `title_id` and `title_values`, and a name that a person gave as text alone,
// which shows as given. A recording of before holds the English text alone and shows it.

import { labelText, serverText, setValueKind, tOr } from './i18n.js';
import { titleText } from './scenarios.js';

// A challenge that a message names, as in the title of an attempt, shows by its own title.
setValueKind('challenge', (name, label) => tOr(`challenge.${name}.title`, (label && label.text) || name));

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
    return typeof team.name === 'string' ? serverText(team, 'name') : '';
}

// The names of the two teams of a summary of the library or of a game's entry, which hold the
// English names in `teams` and the label of each made name in `team_labels`.
export function summaryTeams(summary) {
    const names = summary && Array.isArray(summary.teams) ? summary.teams : [];
    const labels = summary && Array.isArray(summary.team_labels) ? summary.team_labels : [];
    return names.map((name, i) => (labels[i] && typeof labels[i] === 'object' ? labelText(labels[i]) : name == null ? '' : String(name)));
}

// The title of a recording, a summary, a header or a live source, in the page's language. A
// title that the server made comes with its message, a shipped sample is known by its id, and any
// other title reads as titleText reads it, with its scenario in words. `id` is the recording's
// identifier when the object itself holds none, as a header does.
export function recordingTitle(item, id = null) {
    if (!item || typeof item !== 'object') {
        return '';
    }
    if (typeof item.title === 'string' && item.title_id) {
        return serverText(item, 'title');
    }
    const sample = SAMPLES[id || item.id];
    if (sample && item.title === sample[0]) {
        return tOr(sample[1], item.title);
    }
    return titleText(item.title, item.scenario);
}
