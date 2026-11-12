// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the languages of the page, the runtime web/js/core/i18n.js and the shipped language files,
// run from the repository root with `node tests/web/i18n.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the module loads from
// a copy beside a package file that names it a module. It finds the files of the repository.
const folder = mkdtempSync(join(tmpdir(), 'cuju-i18n-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/core/i18n.js', import.meta.url)), join(folder, 'core/i18n.js'));
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const i18n = await import(pathToFileURL(join(folder, 'core/i18n.js')).href);
const languages = new URL('../../src/cuju/render/web/languages/', import.meta.url);
// English ships with the page, and the Portuguese draft waits in translations/.
const read = (code) => JSON.parse(readFileSync(code === 'en' ? new URL(`${code}.json`, languages) : new URL(`../../translations/${code}/${code}.json`, import.meta.url), 'utf8'));
const english = read('en');
const PLACEHOLDER = /\{([A-Za-z0-9_]+)\}/g;
const places = (value) => new Set((typeof value === 'string' ? [value] : Object.values(value)).flatMap((form) => [...form.matchAll(PLACEHOLDER)].map((m) => m[1])));

test('a message fills its placeholders and keeps the unknown ones', () => {
    assert.equal(i18n.t('api.status', { status: 404, text: 'Not Found' }), 'The server answered 404 Not Found.');
    assert.equal(i18n.t('api.status', { status: 404 }), 'The server answered 404 {text}.');
    assert.equal(i18n.language().code, 'en');
    assert.equal(i18n.locale(), 'en-US');
});

test('plural forms follow Intl.PluralRules, exact counts first', () => {
    const one = i18n.t('language.refusedNote', { count: 1, names: 'a.json' });
    const two = i18n.t('language.refusedNote', { count: 2, names: 'a.json, b.json' });
    assert.match(one, /^The file a\.json /);
    assert.match(two, /^The files a\.json, b\.json /);
    const portuguese = new Intl.PluralRules('pt-BR');
    assert.equal(portuguese.select(0), 'one');
    assert.equal(portuguese.select(1000000), 'many');
    assert.equal(new Intl.PluralRules('en-US').select(0), 'other');
});

test('a missing id shows as itself and is noted once, a fallback stands in for server texts', () => {
    assert.equal(i18n.t('no.such.message'), 'no.such.message');
    assert.equal(i18n.t('no.such.message'), 'no.such.message');
    assert.deepEqual(i18n.missing().filter((id) => id === 'no.such.message'), ['no.such.message']);
    assert.equal(i18n.tOr('no.such.title', 'From the server'), 'From the server');
    assert.equal(i18n.tOr(null, 'Plain {x}', { x: 1 }), 'Plain 1');
    assert.equal(i18n.has('api.status'), true);
    assert.equal(i18n.has('no.such.title'), false);
});

test('server texts translate by their id and keep the English without one', () => {
    assert.equal(i18n.serverText({ error: 'no such resource' }), 'no such resource');
    assert.equal(i18n.serverText({ error: 'x', error_id: 'server.no_resource', error_values: {} }), 'no such resource');
    assert.equal(i18n.serverText({ error: 'kept', error_id: 'server.not.a.message' }), 'kept');
    assert.equal(i18n.serverText(null), '');
});

test('a label of the server holds labels and decimals that show in the language', () => {
    const inner = { id: 'server.no_resource', text: 'kept', values: {} };
    const sides = { id: 'server.game.sides_left', text: 'x', values: {} };
    const shown = i18n.serverText({ error: 'x', error_id: 'server.game.side', error_values: { sides, side: inner } });
    assert.equal(shown, 'expected a side that a person plays in this game, 0 for the left, found no such resource');
    assert.equal(i18n.labelText({ id: 'server.game.side', text: 'x', values: { sides: 'none', side: '0.50' } }), 'expected a side that a person plays in this game, none, found 0.50');
    assert.equal(i18n.labelText({ id: 'server.not.a.message', text: 'Built-in AI 0.50', values: {} }), 'Built-in AI 0.50');
    assert.equal(i18n.labelText('Lakeside United'), 'Lakeside United');
});

test('a message with nodes splits around them and never parses markup', () => {
    const node = { tag: 'kbd' };
    const parts = i18n.tn('api.status', { status: node, text: '<b>x</b>' });
    assert.deepEqual(parts, ['The server answered ', node, ' ', '<b>x</b>', '.']);
});

test('numbers, dates and lists use the locale of the language', () => {
    assert.equal(i18n.formatNumber(1234.5), '1,234.5');
    assert.equal(i18n.formatList(['a', 'b', 'c']), 'a, b, and c');
    assert.equal(i18n.formatDateTime(Date.UTC(2026, 10, 10, 12), { dateStyle: 'medium', timeZone: 'UTC' }), 'Nov 10, 2026');
    assert.equal(i18n.formatDateTime('not a date'), '');
    // A code is a language tag of BCP 47, whose case BCP 47 leaves free.
    assert.equal(i18n.validCode('pt-BR'), true);
    assert.equal(i18n.validCode('pt-br'), true);
    assert.equal(i18n.validCode('../en'), false);
    assert.equal(i18n.validCode('pt_BR'), false);
    assert.equal(i18n.validCode('p'), false);
});

test('English and the Portuguese draft hold the ids of English with its placeholders and plural forms', () => {
    // English ships alone, and the Portuguese draft, which the page imports, follows the same rules.
    const files = readdirSync(languages).filter((name) => name.endsWith('.json'));
    assert.deepEqual(files, ['en.json']);
    for (const name of [...files, 'pt-BR.json']) {
        const file = read(name.replace(/\.json$/, ''));
        const head = file['@language'];
        assert.equal(head.code, name.replace(/\.json$/, ''), name);
        const categories = new Intl.PluralRules(head.locale).resolvedOptions().pluralCategories;
        assert.deepEqual([...head.plurals].sort(), [...categories].sort(), name);
        for (const [id, value] of Object.entries(english)) {
            if (id === '@language') {
                continue;
            }
            // A draft may lack a message, which the page then shows in English.
            if (!(id in file)) {
                assert.notEqual(name, 'en.json', `${name} lacks ${id}`);
                continue;
            }
            const own = file[id];
            // A language may count what English leaves alone, when the English text holds {count}.
            if (typeof value === 'object' || !places(value).has('count')) {
                assert.equal(typeof own === 'string', typeof value === 'string', `${name} ${id} plural`);
            }
            if (typeof own === 'object') {
                for (const form of head.plurals) {
                    assert.equal(typeof own[form], 'string', `${name} ${id} lacks ${form}`);
                }
            }
            const theirs = places(value);
            for (const p of places(own)) {
                assert.ok(theirs.has(p), `${name} ${id} has {${p}}`);
            }
        }
        assert.deepEqual(Object.keys(file).filter((id) => !(id in english)), [], name);
    }
});
