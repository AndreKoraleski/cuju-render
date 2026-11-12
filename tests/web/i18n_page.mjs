// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the choice of language as the page makes it in a browser, with the shipped languages in
// the page, a language of the home folder from the server and the stored choice, run from the
// repository root with `node tests/web/i18n_page.mjs`. Each case loads its own copy of
// web/js/core/i18n.js under a document, storage, navigator and fetch of its own.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const folder = mkdtempSync(join(tmpdir(), 'cuju-i18n-page-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/core/i18n.js', import.meta.url)), join(folder, 'core/i18n.js'));
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const languages = new URL('../../src/cuju/render/web/languages/', import.meta.url);
// English ships with the page, and the Portuguese draft waits in translations/. The page of
// these tests carries both, as a page carries the languages it has.
const read = (code) => JSON.parse(readFileSync(code === 'en' ? new URL(`${code}.json`, languages) : new URL(`../../translations/${code}/${code}.json`, import.meta.url), 'utf8'));
const shipped = { en: read('en'), 'pt-BR': read('pt-BR') };
// A language of the home folder, a variant of English, as a person imports it.
const own = {
    '@language': { code: 'en-x-check', name: 'Checked English', locale: 'en-GB', plurals: ['one', 'other'] },
    'html.nav.watch': 'Watch it',
};

let copies = 0;

// Loads a fresh copy of the runtime as a page whose server answers the home folder's language,
// with the stored choice, the address and the browser's languages given, and returns the module
// with the addresses it fetched.
async function page({ stored = null, search = '', browser = ['en-US'], inline = true }) {
    const fetched = [];
    const block = { textContent: inline ? JSON.stringify(shipped) : '' };
    const html = { lang: '', dir: '' };
    globalThis.window = {};
    globalThis.document = {
        documentElement: html,
        getElementById: (id) => (id === 'cuju-languages' ? block : null),
        querySelectorAll: () => [],
    };
    const store = new Map(stored === null ? [] : [['cuju.language', JSON.stringify(stored)]]);
    globalThis.localStorage = {
        getItem: (key) => (store.has(key) ? store.get(key) : null),
        setItem: (key, value) => store.set(key, String(value)),
        removeItem: (key) => store.delete(key),
    };
    globalThis.location = { search };
    Object.defineProperty(globalThis, 'navigator', {
        value: { languages: browser, language: browser[0] }, configurable: true, writable: true,
    });
    globalThis.fetch = async (url) => {
        const address = String(url);
        fetched.push(address);
        const answer = (status, body) => ({ ok: status === 200, status, json: async () => body });
        if (address.endsWith('/api/languages/en-x-check')) {
            return answer(200, own);
        }
        const file = /\/languages\/([A-Za-z-]+)\.json$/.exec(address);
        return file && shipped[file[1]] ? answer(200, shipped[file[1]]) : answer(404, {});
    };
    copies += 1;
    const module = await import(`${pathToFileURL(join(folder, 'core/i18n.js')).href}?case=${copies}`);
    return { module, fetched, html, store };
}

test('a chosen language of the home folder loads on the reload, also a variant of English', async () => {
    const { module, fetched, html } = await page({ stored: 'en-x-check', browser: ['pt-BR'] });
    assert.equal(module.language().code, 'en-x-check');
    assert.equal(html.lang, 'en-GB');
    assert.equal(module.t('html.nav.watch'), 'Watch it');
    assert.equal(module.t('html.nav.play'), shipped.en['html.nav.play']);
    assert.ok(fetched.some((address) => address.endsWith('/api/languages/en-x-check')), fetched);
    assert.deepEqual(module.missing(), []);
});

test('the address chooses a language of the home folder for one visit', async () => {
    const { module, store } = await page({ search: '?lang=en-x-check' });
    assert.equal(module.language().code, 'en-x-check');
    assert.equal(store.size, 0);
});

test('a stored English choice stays English on a browser of another language', async () => {
    const { module, fetched, html } = await page({ stored: 'en', browser: ['pt-BR', 'pt'] });
    assert.equal(module.language().code, 'en');
    assert.equal(html.lang, 'en-US');
    assert.deepEqual(fetched, []);
});

test('the browser picks a shipped language from the page without asking the server', async () => {
    const { module, fetched, html } = await page({ browser: ['pt-BR', 'en-US'] });
    assert.equal(module.language().code, 'pt-BR');
    assert.equal(html.lang, 'pt-BR');
    assert.deepEqual(fetched, []);
    // A variant of English that the browser prefers shows English.
    const english = await page({ browser: ['en-GB', 'pt-BR'] });
    assert.equal(english.module.language().code, 'en');
    // A browser that writes its language in lowercase finds the file, spelled as the file has it.
    const lowercase = await page({ browser: ['pt-br'] });
    assert.equal(lowercase.module.language().code, 'pt-BR');
    assert.deepEqual(lowercase.fetched, []);
});

test('a page without the shipped languages in it fetches them', async () => {
    const { module, fetched } = await page({ browser: ['pt-BR'], inline: false });
    assert.equal(module.language().code, 'pt-BR');
    assert.ok(fetched.some((address) => address.endsWith('/languages/en.json')), fetched);
    assert.ok(fetched.some((address) => address.endsWith('/languages/pt-BR.json')), fetched);
});

test('choosing a language of the home folder loads it before the reload', async () => {
    const { module, store } = await page({ browser: ['en-US'] });
    let heard = null;
    module.onLanguageChange((info) => {
        heard = info.code;
    });
    await module.setLanguage('en-x-check');
    assert.equal(heard, 'en-x-check');
    assert.equal(store.get('cuju.language'), '"en-x-check"');
    assert.equal(module.t('html.nav.watch'), 'Watch it');
});
