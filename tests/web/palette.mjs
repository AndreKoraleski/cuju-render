// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the matching of the command palette, run from the repository root with
// `node tests/web/palette.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from copies beside a package file that names them modules, with the icons that the
// keyboard kit draws.
const root = mkdtempSync(join(tmpdir(), 'cuju-palette-'));
const folder = join(root, 'js');
for (const name of ['help/palette.js', 'core/names.js', 'core/scenarios.js', 'core/i18n.js', 'core/keys.js']) {
    cpSync(fileURLToPath(new URL(`../../src/cuju/render/web/js/${name}`, import.meta.url)), join(folder, name));
}
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/vendor/lucide', import.meta.url)), join(root, 'vendor', 'lucide'), { recursive: true });
writeFileSync(join(root, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(root, { recursive: true, force: true }));
const { HELP_TOPICS, LIMIT, fold, languageChoices, matchScore, rankActions } = await import(pathToFileURL(join(folder, 'help/palette.js')).href);

const ACTIONS = [
    { group: 'Pages', title: 'Go to Recordings', keywords: 'page open' },
    { group: 'Pages', title: 'Go to Teams', keywords: 'page open' },
    { group: 'Settings', title: 'Dark theme', keywords: 'colors appearance mode' },
    { group: 'Settings', title: 'Mute', keywords: 'sound volume audio' },
    { group: 'View', title: 'Weather, Snow', keywords: 'rain snow sky' },
    { group: 'View', title: 'Camera, Broadcast', keywords: 'camera view broadcast' },
    { group: 'Follow', title: 'Follow 10 Marta, Home', keywords: 'player camera number name' },
    { group: 'Follow', title: 'Follow 1 Goalkeeper, Away', keywords: 'player camera number name' },
];

test('letters match in order, and words, starts and runs score more', () => {
    assert.equal(matchScore('', 'anything'), 0);
    assert.equal(matchScore('xyz', 'Go to Teams'), null);
    assert.equal(matchScore('smaet', 'Go to Teams'), null);
    assert.ok(matchScore('tms', 'Go to Teams') > 0);
    // A word the query starts beats letters scattered through the text.
    assert.ok(matchScore('tea', 'Go to Teams') > matchScore('tea', 'the extra area'));
    // A run of letters beats the same letters apart.
    assert.ok(matchScore('rec', 'Recordings') > matchScore('rec', 'Rare echo'));
    // Case and accents never matter.
    assert.equal(matchScore('ÉQUIPE', 'equipe'), matchScore('equipe', 'Équipe'));
    assert.equal(fold('Árbitro'), 'arbitro');
});

test('every word of a query must match, the title counting more than the keywords', () => {
    assert.deepEqual(rankActions('go teams', ACTIONS).map((a) => a.title), ['Go to Teams']);
    assert.equal(rankActions('snow', ACTIONS)[0].title, 'Weather, Snow');
    // A keyword finds an action whose title says something else.
    assert.deepEqual(rankActions('volume', ACTIONS).map((a) => a.title), ['Mute']);
    assert.equal(rankActions('dark', ACTIONS)[0].title, 'Dark theme');
    assert.deepEqual(rankActions('nothing like it', ACTIONS), []);
});

test('players are found by name or number', () => {
    assert.equal(rankActions('marta', ACTIONS)[0].title, 'Follow 10 Marta, Home');
    assert.equal(rankActions('follow 10', ACTIONS)[0].title, 'Follow 10 Marta, Home');
    assert.equal(rankActions('keeper', ACTIONS)[0].title, 'Follow 1 Goalkeeper, Away');
});

test('an empty query keeps the order of the list, within the limit', () => {
    assert.deepEqual(rankActions('', ACTIONS).map((a) => a.title), ACTIONS.map((a) => a.title));
    assert.deepEqual(rankActions('   ', ACTIONS).map((a) => a.title), ACTIONS.map((a) => a.title));
    const many = Array.from({ length: LIMIT + 20 }, (_, i) => ({ group: 'X', title: `Item ${i}` }));
    assert.equal(rankActions('', many).length, LIMIT);
    assert.equal(rankActions('item', many, 5).length, 5);
    // Equal scores keep the list order, so the first item stays first.
    assert.equal(rankActions('item', many)[0].title, 'Item 0');
});

test('the help topics have distinct identifiers and titles', () => {
    assert.equal(new Set(HELP_TOPICS.map(([id]) => id)).size, HELP_TOPICS.length);
    assert.ok(HELP_TOPICS.every(([id, title]) => id.startsWith('help-') && title));
    assert.ok(HELP_TOPICS.some(([id]) => id === 'help-teams'));
});

test('the example of the docs finds Go to Teams, and photo and surprise find their actions', () => {
    const pages = ['Home', 'Watch', 'Play', 'Recordings', 'Matches', 'Tournaments', 'Teams', 'Field', 'Help']
        .map((label) => ({ group: 'Pages', title: `Go to ${label}`, keywords: `page open ${label.toLowerCase()}` }));
    const actions = [...pages,
        { group: 'View', title: 'Photo mode', keywords: 'photo picture screenshot capture still image' },
        { group: 'Teams', title: 'Surprise me, a new team', keywords: 'surprise random generate kit name colors seed team' },
        { group: 'Play', title: 'Challenge, Empty goal', keywords: 'challenge drill medal leaderboard empty_goal_close' }];
    assert.equal(rankActions('gotea', actions)[0].title, 'Go to Teams');
    assert.equal(rankActions('photo', actions)[0].title, 'Photo mode');
    assert.equal(rankActions('surprise', actions)[0].title, 'Surprise me, a new team');
    assert.equal(rankActions('challenge', actions)[0].title, 'Challenge, Empty goal');
});

test('the palette offers each other language and following the browser', () => {
    const languages = [
        { code: 'en', name: 'English', usable: true },
        { code: 'pt', name: 'Português (Brasil)', usable: true },
        { code: 'xx', name: 'Broken', usable: false },
    ];
    // Following the browser in English offers Portuguese alone, a stored choice adds following.
    assert.deepEqual(languageChoices(languages, 'en'), [{ code: 'pt', name: 'Português (Brasil)' }]);
    assert.deepEqual(languageChoices(languages, 'pt', 'pt'), [{ code: 'en', name: 'English' }, { code: null, name: null }]);
    assert.deepEqual(languageChoices(null, 'en'), []);
    const actions = languageChoices(languages, 'en', 'en').map((choice) => ({
        group: 'Settings', title: `Language, ${choice.name || 'follow the browser'}`, keywords: `language translation locale ${choice.code || ''} ${choice.name || ''}`,
    }));
    assert.equal(rankActions('language', actions)[0].title, 'Language, Português (Brasil)');
    assert.equal(rankActions('portugues', actions)[0].title, 'Language, Português (Brasil)');
});
