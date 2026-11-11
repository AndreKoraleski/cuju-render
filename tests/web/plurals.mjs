// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of number agreement in the shipped language files, run from the repository root with
// `node tests/web/plurals.mjs`. A message whose words agree with a number is an object of plural
// forms, and the value `count` picks its form, so a message that holds {count} has forms unless
// its words read the same for every number.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = new URL('../../src/cuju/render/', import.meta.url);
// English ships with the page, and the Portuguese draft waits in translations/.
const read = (code) => JSON.parse(readFileSync(code === 'en' ? new URL(`web/languages/${code}.json`, root) : new URL(`../../translations/${code}.json`, import.meta.url), 'utf8'));
const files = { en: read('en'), pt: read('pt') };
const PLACEHOLDER = /\{([A-Za-z0-9_]+)\}/g;
const places = (value) => new Set((typeof value === 'string' ? [value] : Object.values(value)).flatMap((form) => [...form.matchAll(PLACEHOLDER)].map((m) => m[1])));
const ids = Object.keys(files.en).filter((id) => !id.startsWith('@'));
const plural = (value) => Boolean(value) && typeof value === 'object';

// Messages that hold {count} and read the same for every number, in both languages, each with
// the reason.
const COUNT_FREE = {
    'grid.range': 'a position within the count',
    'tour.announce': 'a step of the count',
    'tour.announce.missing': 'a step of the count',
    'tour.count': 'a step of the count',
    'lessons.count': 'a lesson of the count',
    'lessons.announce': 'a lesson of the count',
    'lessons.played': 'seconds of a fixed thirty',
    'challenges.run.attempt': 'an attempt of the count',
    'matches.queue.more': 'more of the count, without a noun',
    'recordings.action.trash.count': 'a number beside a button label',
    'recordings.action.purge.count': 'a number beside a button label',
    'home.recordings.all': 'shown only above five recordings',
    'format.error.too_many_frames': 'a count above the limit of the viewer',
    'format.error.player_count': 'a count above the limit of the viewer',
    'server.clips.animations_count': 'the count found, after the limit',
    'server.live.grid_range': 'the count found, after the range',
    'server.tournament.entrants': 'the count found, after the range',
    'server.tournament.label.round_of': 'the name of a round',
    'server.tournament.label.round_of_tie': 'the name of a round',
};

// Plural messages whose English reads the same for one and for more, while Portuguese differs.
const ENGLISH_SAME = new Set([
    'api.control.short.assignment.dynamic',
    'api.control.short.assignment.fixed',
    'tournament.view.running',
    'helpcenter.lessons.summary',
    'challenges.achievements.count',
    'challenges.achievements.again',
    'challenges.run.banner',
    'challenges.job.running',
    'recordings.count.selected.library',
    'recordings.count.selected.trash',
    'recordings.restore.failed',
    'recordings.trash.failed',
    'recordings.purge.failed',
    'show.mvp.saves',
]);

test('every message that holds a count has plural forms in both languages', () => {
    const lacking = [];
    for (const id of ids) {
        const counted = places(files.en[id]).has('count') || places(files.pt[id]).has('count');
        if (!counted || id in COUNT_FREE || id.startsWith('caption.')) {
            continue;
        }
        for (const code of ['en', 'pt']) {
            if (!plural(files[code][id])) {
                lacking.push(`${code} ${id}`);
            }
        }
    }
    assert.deepEqual(lacking, [], 'a message with {count} needs plural forms, or a place in COUNT_FREE with its reason');
});

test('the messages free of the count are still in the files and plain', () => {
    for (const id of Object.keys(COUNT_FREE)) {
        for (const code of ['en', 'pt']) {
            assert.equal(typeof files[code][id], 'string', `${code} ${id}`);
            assert.ok(places(files[code][id]).has('count'), `${code} ${id}`);
        }
    }
});

test('every plural message has the forms its language needs', () => {
    for (const code of ['en', 'pt']) {
        const needed = files[code]['@language'].plurals;
        for (const id of ids) {
            const value = files[code][id];
            if (!plural(value)) {
                continue;
            }
            for (const form of needed) {
                assert.equal(typeof value[form], 'string', `${code} ${id} lacks ${form}`);
            }
            for (const form of Object.keys(value)) {
                assert.ok(needed.includes(form) || /^=\d+$/.test(form), `${code} ${id} has the form ${form}`);
            }
        }
    }
});

test('Portuguese says zero apart, since pt-BR counts 0 as one', () => {
    assert.equal(new Intl.PluralRules('pt-BR').select(0), 'one');
    for (const id of ids) {
        const value = files.pt[id];
        if (plural(value) && value.one !== value.other) {
            assert.equal(typeof value['=0'], 'string', `pt ${id} needs =0`);
        }
    }
});

test('English says one apart, unless its words read the same', () => {
    for (const id of ids) {
        const value = files.en[id];
        if (!plural(value)) {
            continue;
        }
        if (ENGLISH_SAME.has(id)) {
            assert.equal(value.one, value.other, `en ${id} is in ENGLISH_SAME`);
        } else {
            assert.notEqual(value.one, value.other, `en ${id} reads the same for one and more`);
        }
    }
    for (const id of ENGLISH_SAME) {
        assert.ok(plural(files.en[id]) && plural(files.pt[id]), id);
    }
});

// The message ids that the page names literally with the values it passes, read from the
// modules, so a plural message that is given no count shows.
function calls() {
    const found = [];
    const walk = (dir) => {
        for (const entry of readdirSync(dir, { withFileTypes: true })) {
            const path = join(dir, entry.name);
            if (entry.isDirectory()) {
                walk(path);
            } else if (entry.name.endsWith('.js')) {
                const text = readFileSync(path, 'utf8');
                for (const match of text.matchAll(/\b(?:t|tn|tOr)\('([A-Za-z0-9_.-]+)'/g)) {
                    // The arguments run to the parenthesis that closes the call.
                    let depth = 0;
                    let end = match.index + match[0].length - match[1].length - 3;
                    for (let i = end; i < text.length; i += 1) {
                        depth += text[i] === '(' ? 1 : text[i] === ')' ? -1 : 0;
                        if (depth === 0) {
                            end = i;
                            break;
                        }
                    }
                    found.push({ id: match[1], args: text.slice(match.index + match[0].length, end), file: entry.name });
                }
            }
        }
    };
    walk(fileURLToPath(new URL('web/js/', root)));
    return found;
}

test('the page gives a count to every plural message it names', () => {
    const missing = calls()
        .filter(({ id }) => plural(files.en[id]) || plural(files.pt[id]))
        .filter(({ args }) => !/\bcount\b/.test(args))
        .map(({ id, file }) => `${file} ${id}`);
    assert.deepEqual(missing, []);
});

// The runtime, loaded from a copy beside a package file that names it a module.
const folder = mkdtempSync(join(tmpdir(), 'cuju-plurals-'));
cpSync(fileURLToPath(new URL('web/js/core/i18n.js', root)), join(folder, 'core/i18n.js'));
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const i18n = await import(pathToFileURL(join(folder, 'core/i18n.js')).href);

test('a count with decimals picks the form of a number shown with them', () => {
    assert.equal(i18n.t('show.chart.mark', { mark: 'Goal', team: 'A', count: 1 }), 'Goal, A, 1 minute');
    assert.equal(i18n.t('show.chart.mark', { mark: 'Goal', team: 'A', count: '1.0' }), 'Goal, A, 1.0 minutes');
    assert.equal(i18n.t('show.chart.mark', { mark: 'Goal', team: 'A', count: '2,5' }), 'Goal, A, 2,5 minutes');
    assert.equal(i18n.t('recordings.purge.confirm', { count: 3 }).startsWith('Delete 3 recordings'), true);
    assert.equal(i18n.t('server.tournament.stage_entrants', { where: 'Stage 2', count: '0' }), 'Stage 2 needs at least 2 entrants, and none reaches it');
    assert.equal(i18n.t('server.tournament.stage_entrants', { where: 'Stage 2', count: '1' }), 'Stage 2 needs at least 2 entrants, and 1 reaches it');
});
