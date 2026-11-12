// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the marks of messages in web/js/core/i18n.js and the keyboard kit web/js/core/keys.js,
// run from the repository root with `node tests/web/keys.mjs`. A small stand-in of the document
// takes the elements the kit builds.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Elements with a tag, attributes, children and text, enough for the kit.
class Element {
    constructor(tag) {
        this.tagName = tag.toUpperCase();
        this.attributes = {};
        this.children = [];
        this.className = '';
        this.dataset = {};
        this.text = '';
    }
    setAttribute(name, value) {
        this.attributes[name] = String(value);
    }
    getAttribute(name) {
        return this.attributes[name] ?? null;
    }
    append(...nodes) {
        this.children.push(...nodes);
    }
    set textContent(value) {
        this.children = [];
        this.text = String(value);
    }
    get textContent() {
        return this.text + this.children.map((child) => (typeof child === 'string' ? child : child.textContent)).join('');
    }
}
globalThis.document = {
    createElement: (tag) => new Element(tag),
    createElementNS: (ns, tag) => new Element(tag),
    createTextNode: (text) => text,
    createDocumentFragment: () => new Element('#fragment'),
};

const root = mkdtempSync(join(tmpdir(), 'cuju-keys-'));
const web = new URL('../../src/cuju/render/web/', import.meta.url);
cpSync(fileURLToPath(new URL('js/core', web)), join(root, 'js', 'core'), { recursive: true });
cpSync(fileURLToPath(new URL('vendor/lucide', web)), join(root, 'vendor', 'lucide'), { recursive: true });
writeFileSync(join(root, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(root, { recursive: true, force: true }));
const i18n = await import(pathToFileURL(join(root, 'js', 'core', 'i18n.js')).href);
const keys = await import(pathToFileURL(join(root, 'js', 'core', 'keys.js')).href);
// English ships with the page, and the Portuguese draft waits in translations/.
const read = (code) => JSON.parse(readFileSync(code === 'en' ? new URL(`languages/${code}.json`, web) : new URL(`../../translations/${code}/${code}.json`, import.meta.url), 'utf8'));
const files = { en: read('en'), pt: read('pt-BR') };

test('marks part a text into strong, code and plain words', () => {
    assert.deepEqual(i18n.markParts('Run `cuju render serve`, **then** reload.'), [
        { kind: 'text', text: 'Run ' },
        { kind: 'code', text: 'cuju render serve' },
        { kind: 'text', text: ', ' },
        { kind: 'strong', text: 'then' },
        { kind: 'text', text: ' reload.' },
    ]);
    // A mark that does not close stays text.
    assert.deepEqual(i18n.markParts('2**64 - 1'), [{ kind: 'text', text: '2**64 - 1' }]);
    assert.equal(i18n.plainMarks('Press `Ctrl K` or `ffmpeg` **now**'), 'Press Ctrl K or ffmpeg now');
    assert.equal(i18n.plainMarks('`Shift + ?` and `Space`'), '⇧ ? and Space');
});

test('marks in both languages come in pairs and match in kind', () => {
    const count = (text, kind) => i18n.markParts(text).filter((part) => part.kind === kind).length;
    for (const [id, english] of Object.entries(files.en)) {
        const portuguese = files.pt[id];
        if (id.startsWith('@') || typeof english !== 'string' || typeof portuguese !== 'string') {
            continue;
        }
        for (const text of [english, portuguese]) {
            const rest = i18n.markParts(text).filter((part) => part.kind === 'text').map((part) => part.text).join('');
            assert.ok(!/`/.test(rest), `${id} has a backtick that does not close`);
        }
        assert.equal(count(english, 'code'), count(portuguese, 'code'), `${id} marks code alike in both languages`);
        assert.equal(Math.sign(count(english, 'strong')), Math.sign(count(portuguese, 'strong')), `${id} marks strong words in both languages`);
    }
});

test('t gives the text without marks, and values never add one', () => {
    const fake = { en: { 'x.a': 'Run `cuju render open {name}` **now**' } };
    assert.equal(i18n.plainMarks(fake.en['x.a']), 'Run cuju render open {name} now');
    assert.equal(i18n.t('keys.name.ctrl'), 'Control');
});

test('a chord reads as its keys, and any other code is no chord', () => {
    assert.deepEqual(keys.chordKeys('Ctrl K'), ['ctrl', 'K']);
    assert.deepEqual(keys.chordKeys('Ctrl+K'), ['ctrl', 'K']);
    assert.deepEqual(keys.chordKeys('Shift + ?'), ['shift', '?']);
    assert.deepEqual(keys.chordKeys('Space'), ['space']);
    assert.deepEqual(keys.chordKeys('Esc'), ['esc']);
    assert.deepEqual(keys.chordKeys('F2'), ['F2']);
    assert.deepEqual(keys.chordKeys('k'), ['K']);
    assert.equal(keys.chordKeys('cuju render serve'), null);
    assert.equal(keys.chordKeys('ffmpeg'), null);
    assert.equal(keys.chordKeys('$CUJU_FFMPEG'), null);
    assert.equal(keys.chordText('Ctrl K'), 'Ctrl K');
    assert.equal(keys.chordText('Shift + ?'), '⇧ ?');
    assert.equal(keys.chordName('Ctrl K'), 'Control K');
    assert.equal(keys.chordName('Shift Enter'), 'Shift Enter');
    assert.equal(keys.chordName('Mod K'), keys.isMac() ? 'Command K' : 'Control K');
});

test('every key the page binds has a keycap and a name in both languages', () => {
    const bound = new Set();
    const walk = (dir) => {
        for (const entry of readdirSync(dir, { withFileTypes: true })) {
            const path = join(dir, entry.name);
            if (entry.isDirectory()) {
                walk(path);
            } else if (entry.name.endsWith('.js')) {
                const text = readFileSync(path, 'utf8');
                for (const match of text.matchAll(/\be\.(?:key|code) === '([^']+)'/g)) {
                    bound.add(match[1]);
                }
            }
        }
    };
    walk(fileURLToPath(new URL('js', web)));
    assert.ok(bound.size > 10);
    for (const key of bound) {
        const id = keys.keyId(key);
        assert.ok(id, `the kit knows the key ${key}`);
        if (/^[a-z]+$/.test(id)) {
            for (const code of ['en', 'pt']) {
                const name = id === 'meta' ? 'command' : id;
                assert.equal(typeof files[code][`keys.name.${name}`], 'string', `${code} names ${key}`);
            }
        }
    }
});

test('a keycap shows the printed legend or the Lucide symbol, in the shape of its key', () => {
    const ctrl = keys.keycap('ctrl');
    assert.equal(ctrl.tagName, 'KBD');
    if (!keys.isMac()) {
        assert.equal(ctrl.textContent, 'Ctrl');
    }
    assert.match(ctrl.className, /keycap-square/);
    const space = keys.keycap('space');
    assert.match(space.className, /keycap-space/);
    assert.equal(space.children[0].tagName, 'SVG');
    assert.equal(space.children[0].children[0].tagName, 'PATH');
    assert.match(keys.keycap('shift').className, /keycap-wide/);
    assert.match(keys.keycap('enter').className, /keycap-wide/);
    assert.match(keys.keycap('backspace').className, /keycap-wide/);
    assert.match(keys.keycap('left').className, /keycap-square/);
    for (const id of ['space', 'enter', 'shift', 'backspace', 'tab', 'left', 'right', 'up', 'down']) {
        const svg = keys.keycap(id).children[0];
        assert.equal(svg.tagName, 'SVG', id);
        assert.equal(svg.getAttribute('stroke'), 'currentColor', id);
        assert.ok(svg.children.length > 0, id);
    }
});

test('a chord reads by the full names of its keys and draws them as keycaps', () => {
    const node = keys.chord('Ctrl K');
    assert.equal(node.tagName, 'KBD');
    const [name, caps] = node.children;
    assert.equal(name.className, 'sr-only');
    assert.equal(name.textContent, keys.isMac() ? 'Control K' : 'Control K');
    assert.equal(caps.getAttribute('aria-hidden'), 'true');
    assert.equal(caps.children.length, 2);
    assert.equal(keys.chord('ffmpeg').tagName, 'CODE');
    // A message draws its shortcut code as keycaps and its command as code.
    const parts = i18n.tn('keys.name.ctrl');
    assert.deepEqual(parts, ['Control']);
});

// A code span that reads as keys, capitalized key names, function keys and single signs apart
// by spaces or a plus, as against a command, a file or a variable. A program that the messages
// name by its capitalized name, such as Chrome, is code too.
const KEY_SHAPE = /^(?:[A-Z][A-Za-z]*|F\d{1,2}|\S)(?:(?:\s*\+\s*|\s+)(?:[A-Z][A-Za-z]*|F\d{1,2}|\S))*$/;
const PROGRAMS = new Set(['Chrome', 'Chromium', 'Google Chrome', 'Edge', 'Firefox', 'Safari', 'OBS']);
const keyLike = (span) => KEY_SHAPE.test(span) && !PROGRAMS.has(span);
const codeSpans = (value) => (typeof value === 'string' ? [value] : Object.values(value))
    .flatMap((text) => i18n.markParts(text).filter((part) => part.kind === 'code').map((part) => part.text));

test('every shortcut of the language files reads as a chord the kit draws', () => {
    let shortcuts = 0;
    for (const code of ['en', 'pt']) {
        for (const [id, value] of Object.entries(files[code])) {
            if (id.startsWith('@')) {
                continue;
            }
            for (const span of codeSpans(value)) {
                if (keyLike(span)) {
                    shortcuts++;
                    assert.ok(keys.chordKeys(span), `${code} ${id} names the keys ${span}`);
                }
            }
        }
    }
    assert.ok(shortcuts > 100);
    // Commands, programs, files and variables stay code.
    for (const span of ['cuju render serve', 'ffmpeg', '$CUJU_FFMPEG', 'CUJU_RENDER=on', '.cjr', 'main.py', 'team:', 'CUJREC1']) {
        assert.ok(!keyLike(span) || !keys.chordKeys(span), span);
    }
});

test('both languages name the same shortcuts in the same messages', () => {
    for (const [id, english] of Object.entries(files.en)) {
        if (id.startsWith('@') || !(id in files.pt)) {
            continue;
        }
        const chords = (value) => codeSpans(typeof value === 'string' ? value : value.other)
            .filter(keyLike).map((span) => keys.chordKeys(span).join(' ')).sort();
        assert.deepEqual(chords(files.pt[id]), chords(english), `${id} names the same keys`);
    }
});

test('every kbd of the static markup names a key the kit knows', () => {
    const markup = readFileSync(new URL('index.html', web), 'utf8');
    const found = [...markup.matchAll(/<kbd([^>]*)>([^<]*)<\/kbd>/g)];
    assert.ok(found.length > 30);
    for (const [, attributes, text] of found) {
        assert.ok(!/data-i18n/.test(attributes), `a kbd takes its key from data-key, not a message, ${attributes}`);
        const named = /data-key="([^"]+)"/.exec(attributes);
        const key = named ? named[1] : text;
        assert.ok(keys.chordKeys(key), `the kit knows the key ${key}`);
        if (!named) {
            assert.ok([...text].length === 1, `a key named by its text is one character, ${text}`);
        }
    }
});

test('the codes of KeyboardEvent read as their keys', () => {
    assert.equal(keys.chordText('KeyQ'), 'Q');
    assert.equal(keys.chordText('Digit3'), '3');
    assert.equal(keys.chordText('ArrowUp'), '↑');
    assert.equal(keys.chordText('Escape'), 'Esc');
    assert.equal(keys.chordName('ArrowLeft'), 'Left arrow');
    assert.deepEqual(keys.chordKeys('ShiftLeft'), ['shift']);
    assert.deepEqual(keys.chordKeys('Space'), ['space']);
    assert.deepEqual(keys.chordKeys('BracketRight'), [']']);
});

test('the static texts translated before the kit loaded take their keycaps and legends', () => {
    // A stand-in of the page, a paragraph whose message drew its shortcut as plain code and a
    // button whose title named the keys as the message writes them.
    const code = { textContent: 'Shift Tab', replaced: null, replaceWith(node) { this.replaced = node; } };
    const command = { textContent: 'cuju render serve', replaced: null, replaceWith(node) { this.replaced = node; } };
    const button = {
        attributes: { 'data-i18n-title': 'html.top.palette.title', title: 'Commands (Mod K)' },
        getAttribute(name) { return this.attributes[name] ?? null; },
        setAttribute(name, value) { this.attributes[name] = value; },
    };
    const root = {
        querySelectorAll(selector) {
            if (selector === '[data-i18n] code') {
                return [code, command];
            }
            return selector === '[data-i18n-title]' ? [button] : [];
        },
    };
    keys.upgradeStatic(root);
    assert.equal(code.replaced.className, 'chord');
    assert.equal(command.replaced, null);
    assert.equal(button.attributes.title, `Commands (${keys.isMac() ? '⌘' : 'Ctrl'} K)`);
});
