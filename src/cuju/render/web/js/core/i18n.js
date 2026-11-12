// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The languages of the page. Every text the page shows is a message of a language file, one JSON
// object per language keyed by message id, which web/languages/ ships and the folder languages of
// the renderer's home adds to. A message is a text with placeholders in braces, such as
// `{count} recordings`, or an object of plural forms keyed by the categories of
// Intl.PluralRules, `one`, `few`, `many`, `other` and the rest, and by exact counts such as `=0`.
// The key `@language` holds the code, the name, the locale of numbers and dates, the direction of
// the text and the plural categories of the language.
//
// A message may mark its words in two ways. Two asterisks on each side, **so**, give strong
// emphasis, and backticks, `so`, mark code such as a command, a program or a variable, or a
// shortcut, a chord of key names such as `Ctrl K`, which keys.js draws as keycaps. The marks are
// read from the message before its values fill it, so a value never adds one. t() gives the text
// without the marks, for attributes, titles, notifications and canvases, and tn() and tm() give
// strong, code and kbd elements, built as nodes with text, never as markup.
//
// The module loads English and the chosen language before any module that imports it runs, so
// t() answers at once everywhere, also in the tables that modules build as they load. The server
// puts the shipped files into the page itself, so they need no request of their own. A message
// that the chosen language lacks comes from English, and an id that English lacks shows as the
// id itself and is noted once on the console. The choice is the stored one, else the address
// parameter `lang`, else the first language of the browser that a file exists for, else English.
// Changing it stores the choice and tells the listeners, and the page then reloads at the same
// address, so every module renders again in the new language.

const STORE_KEY = 'cuju.language';
// How long a language file may take to arrive, in milliseconds.
const FETCH_MS = 10000;
const ID = /^[A-Za-z0-9_.-]+$/;
const CODE = /^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$/;
const PLACEHOLDER = /\{([A-Za-z0-9_]+)\}/g;
const BASE = new URL('../../languages/', import.meta.url);
const IN_BROWSER = typeof window !== 'undefined' && typeof document !== 'undefined';
// Node reads the files from the disk, while a page and a worker of the page fetch them.
const IN_NODE = !IN_BROWSER && typeof process !== 'undefined' && Boolean(process.versions && process.versions.node);

let english = {};
let table = {};
let info = { code: 'en', name: 'English', locale: 'en-US', dir: 'ltr', plurals: ['one', 'other'] };
let englishInfo = info;
const rules = new Map();
const missingIds = new Set();
const listeners = new Set();

// The plural rules of a locale for numbers shown with so many decimals, made once.
function pluralRules(locale, digits = 0) {
    const key = `${locale} ${digits}`;
    let r = rules.get(key);
    if (!r) {
        const options = digits ? { minimumFractionDigits: digits } : {};
        try {
            r = new Intl.PluralRules(locale, options);
        } catch {
            r = new Intl.PluralRules('en-US', options);
        }
        rules.set(key, r);
    }
    return r;
}

// A count given as text with decimals, such as 1.0 or 1,5, as a number and its decimals, since
// English reads 1 minute but 1.0 minutes. Any other value is a number without decimals.
const DECIMAL_COUNT = /^\s*(-?\d+)[.,](\d+)\s*$/;
function countOf(value) {
    const match = typeof value === 'string' ? DECIMAL_COUNT.exec(value) : null;
    if (match) {
        return { count: Number(`${match[1]}.${match[2]}`), digits: match[2].length };
    }
    return { count: Number(value), digits: 0 };
}

// Whether a code names a language file safely, a language tag of BCP 47 such as pt or pt-BR, of
// letters and digits in parts. Two codes that differ in case alone name the same language.
export function validCode(code) {
    return typeof code === 'string' && CODE.test(code);
}

// The shipped languages that the server put into the page, by code, read once, or null on a page
// served without them.
let inlined;
function inlinedFiles() {
    if (inlined === undefined) {
        inlined = null;
        try {
            const block = IN_BROWSER ? document.getElementById('cuju-languages') : null;
            const text = block ? block.textContent.trim() : '';
            inlined = text ? JSON.parse(text) : null;
        } catch {
            inlined = null;
        }
    }
    return inlined;
}

// The shipped file of a code that the server put into the page, whatever the case of the code, or
// null.
function inlinedLanguage(code) {
    const shipped = inlinedFiles();
    const lower = String(code).toLowerCase();
    const key = shipped ? Object.keys(shipped).find((name) => name.toLowerCase() === lower) : undefined;
    return key !== undefined && shipped[key] && typeof shipped[key] === 'object' ? shipped[key] : null;
}

// Reads a shipped file from the page itself or from beside this module, or a language of the home
// folder from the server.
async function readFile(code) {
    if (!validCode(code)) {
        throw new Error(tOr('language.error.none', `there is no language ${code}`, { code }));
    }
    if (IN_NODE) {
        // Under Node a test may load a copy of the modules alone, so the files of the repository
        // root, the working folder of the tests, stand behind those beside the module.
        const { readFile: read } = await import('node:fs/promises');
        const { pathToFileURL } = await import('node:url');
        const places = [new URL(`${code}.json`, BASE)];
        if (typeof process !== 'undefined') {
            places.push(pathToFileURL(`${process.cwd()}/src/cuju/render/web/languages/${code}.json`));
            // The drafts of other languages, which a page imports, wait in translations/, each in
            // a folder named after its code.
            places.push(pathToFileURL(`${process.cwd()}/translations/${code}/${code}.json`));
        }
        let failure;
        for (const place of places) {
            try {
                return JSON.parse(await read(place, 'utf8'));
            } catch (err) {
                failure = err;
            }
        }
        throw failure;
    }
    const inlinedFile = inlinedLanguage(code);
    if (inlinedFile) {
        return inlinedFile;
    }
    // Every module of the page waits on this load, so a request that never answers gives up after
    // a while and the page starts in English.
    const get = (url) => fetch(url, typeof AbortSignal.timeout === 'function' ? { signal: AbortSignal.timeout(FETCH_MS) } : {})
        .catch(() => null);
    let res = await get(new URL(`${code}.json`, BASE));
    if (!res || !res.ok) {
        res = await get(`/api/languages/${encodeURIComponent(code)}`);
    }
    if (!res || !res.ok) {
        throw new Error(tOr('language.error.none', `there is no language ${code}`, { code }));
    }
    return res.json();
}

// Splits a file into its header and its messages, keeping well formed messages alone.
function parse(data, code) {
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
        throw new Error(tOr('language.error.notObject', `the language ${code} is not a JSON object`, { code }));
    }
    const head = data['@language'] && typeof data['@language'] === 'object' ? data['@language'] : {};
    const messages = {};
    for (const [id, value] of Object.entries(data)) {
        if (id.startsWith('@') || !ID.test(id)) {
            continue;
        }
        if (typeof value === 'string' || (value && typeof value === 'object' && typeof value.other === 'string')) {
            messages[id] = value;
        }
    }
    const locale = typeof head.locale === 'string' && head.locale ? head.locale : (head.code || code);
    // The file spells its code as the list of languages does, such as pt-BR for pt-br.
    const spelled = typeof head.code === 'string' && head.code.toLowerCase() === String(code).toLowerCase() ? head.code : code;
    return {
        info: {
            code: spelled,
            name: typeof head.name === 'string' && head.name ? head.name : code,
            english: typeof head.english === 'string' ? head.english : '',
            locale,
            dir: head.dir === 'rtl' ? 'rtl' : 'ltr',
            plurals: Array.isArray(head.plurals) ? head.plurals : ['other'],
        },
        messages,
    };
}

// The language codes to try, in order, each marked chosen when the stored choice or the address
// names it. English ends the list, since it is always there.
function wanted() {
    const out = [];
    let done = false;
    const add = (code, chosen) => {
        const c = String(code || '');
        const lower = c.toLowerCase();
        if (done || !validCode(c)) {
            return;
        }
        // English ends the list, and so does a variant of English the browser prefers, which the
        // page shows as English. A chosen variant, such as en-x-mine of the home folder, loads.
        if (lower === 'en' || (!chosen && lower.startsWith('en-'))) {
            done = true;
        } else if (!out.some((item) => item.code.toLowerCase() === lower)) {
            out.push({ code: c, chosen });
        }
    };
    if (IN_BROWSER) {
        try {
            const stored = localStorage.getItem(STORE_KEY);
            if (stored) {
                add(JSON.parse(stored), true);
            }
        } catch {
            // Storage can be unavailable, the browser's language then decides.
        }
        try {
            add(new URLSearchParams(location.search).get('lang'), true);
        } catch {
            // An address without parameters leaves the choice to the browser.
        }
        // The first languages of the browser, each also by its base language, up to English.
        for (const tag of (navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language]).slice(0, 3)) {
            const whole = String(tag || '');
            add(whole, false);
            add(whole.split('-')[0], false);
        }
    }
    return out;
}

// Loads English and the language to show. A language that fails to load leaves English.
async function start() {
    try {
        const parsed = parse(await readFile('en'), 'en');
        english = parsed.messages;
        englishInfo = parsed.info;
        info = englishInfo;
        table = english;
    } catch (err) {
        // Without the English file every message shows its id, which the console notes.
        console.warn(`i18n: the English messages failed to load, ${err.message}`);
    }
    const list = wanted();
    const shipped = inlinedFiles();
    for (const [i, { code, chosen }] of list.entries()) {
        // A language the browser prefers that the page does not hold gives way to a later one it
        // holds, such as pt for pt-BR, so the start asks the server for nothing it may not have.
        if (!chosen && shipped && !inlinedLanguage(code) && list.slice(i + 1).some((item) => inlinedLanguage(item.code))) {
            continue;
        }
        try {
            const parsed = parse(await readFile(code), code);
            table = parsed.messages;
            info = parsed.info;
            break;
        } catch {
            // The next language of the list is tried.
        }
    }
    applyDocument();
}

// The language and direction of the document, and its static texts.
function applyDocument() {
    if (!IN_BROWSER) {
        return;
    }
    document.documentElement.lang = info.locale;
    document.documentElement.dir = info.dir;
    // An install of the page names its description and shortcuts in the page's language.
    const manifest = typeof document.querySelector === 'function' ? document.querySelector('link[rel="manifest"]') : null;
    if (manifest) {
        manifest.setAttribute('href', info.code === 'en' ? 'manifest.webmanifest' : `manifest.webmanifest?lang=${encodeURIComponent(info.code)}`);
    }
    translateDom(document);
}

// Notes an id that no language holds, once.
function noteMissing(id) {
    if (!missingIds.has(id)) {
        missingIds.add(id);
        console.warn(`i18n: missing message ${id}`);
    }
}

// The message of an id in the shown language, else in English, else undefined.
function lookup(id) {
    if (Object.prototype.hasOwnProperty.call(table, id)) {
        return { message: table[id], locale: info.locale };
    }
    if (Object.prototype.hasOwnProperty.call(english, id)) {
        return { message: english[id], locale: englishInfo.locale };
    }
    return null;
}

// The form of a plural message for the count of the values.
function pick(message, values, locale) {
    if (typeof message === 'string') {
        return message;
    }
    const { count, digits } = countOf(values ? values.count : undefined);
    if (Number.isFinite(count) && !digits && typeof message[`=${count}`] === 'string') {
        return message[`=${count}`];
    }
    const category = Number.isFinite(count) ? pluralRules(locale, digits).select(count) : 'other';
    return typeof message[category] === 'string' ? message[category] : message.other;
}

// The marks of a message, strong emphasis in double asterisks and code in backticks. A mark
// that does not close is text, as the two asterisks of 2**64 are.
const MARK = /\*\*(.+?)\*\*|`([^`]+)`/g;

// A text as its parts, each with its kind, text, strong or code, in order.
export function markParts(text) {
    const parts = [];
    let last = 0;
    for (const match of String(text).matchAll(MARK)) {
        if (match.index > last) {
            parts.push({ kind: 'text', text: text.slice(last, match.index) });
        }
        parts.push(match[1] !== undefined ? { kind: 'strong', text: match[1] } : { kind: 'code', text: match[2] });
        last = match.index + match[0].length;
    }
    if (last < text.length) {
        parts.push({ kind: 'text', text: text.slice(last) });
    }
    return parts;
}

// How the page shows code, as text and as a node, which keys.js sets so that a shortcut shows
// as keycaps. Without it, code shows as it is written, inside a code element.
let codeKind = {
    text: (code) => code,
    node: (code) => {
        const node = document.createElement('code');
        node.textContent = code;
        return node;
    },
};
export function setCodeKind(kind) {
    codeKind = { ...codeKind, ...kind };
}

// A text without its marks, the code as codeKind writes it, such as a shortcut in its legends.
export function plainMarks(text) {
    return markParts(text).map((part) => (part.kind === 'code' ? codeKind.text(part.text) : part.text)).join('');
}

function fill(text, values) {
    if (!values) {
        return text;
    }
    return text.replace(PLACEHOLDER, (whole, name) => (values[name] === undefined || values[name] === null ? whole : String(values[name])));
}

// The text of a message, with its placeholders filled from values. A count in the values picks
// the plural form.
export function t(id, values) {
    const found = lookup(id);
    if (!found) {
        noteMissing(id);
        return id;
    }
    return markParts(pick(found.message, values, found.locale))
        .map((part) => (part.kind === 'code' ? codeKind.text(fill(part.text, values)) : fill(part.text, values)))
        .join('');
}

// The text of a message whose id the server or a table may lack, such as the title of a
// challenge, else the given fallback, which is the server's own English text.
export function tOr(id, fallback, values) {
    if (typeof id !== 'string' || !id || !lookup(id)) {
        return fill(plainText(fallback), values);
    }
    return t(id, values);
}

// A value as text, a text as it is and a number or a truth value in digits or words. Anything
// else, such as an object of a malformed file, is the empty text, since some objects throw when
// made text.
export function plainText(value) {
    const kind = typeof value;
    if (kind === 'string') {
        return value;
    }
    return kind === 'number' || kind === 'boolean' || kind === 'bigint' ? String(value) : '';
}

// Whether a language holds the id.
export function has(id) {
    return lookup(id) !== null;
}

// The text of a message from the server, an object with the English text in `field` and, when
// the server gives them, its id in `field_id` and its values in `field_values`. A name that the
// server makes, such as that of the built-in AI or of a round, comes the same way, while a name
// that a person gave comes as text alone and shows as given. `allow`, when given, says which
// message ids may show, in the object and in the labels of its values, and a label of any other
// id shows its English text.
export function serverText(object, field = 'error', allow = null) {
    if (!object || typeof object !== 'object') {
        return plainText(object);
    }
    return labelText({ id: object[`${field}_id`], text: object[field], values: object[`${field}_values`] }, allow);
}

// Labels nest this deep at most, as an entrant inside a match inside the title of a tournament
// recording does, and a deeper label shows its English text.
const LABEL_DEPTH = 16;

// The text of a label of the server, an object with its English `text`, its message `id` and
// its `values`, as a value of another message holds one, or a plain text. A label with a `kind`
// names a thing that a module of the page shows, such as a scenario by its `name`. `allow` reads
// as in serverText.
export function labelText(label, allow = null, depth = 0) {
    if (!label || typeof label !== 'object') {
        return plainText(label);
    }
    if (typeof label.kind === 'string') {
        const show = valueKinds.get(label.kind);
        return show ? show(plainText(label.name), label) : plainText(label.text ?? label.name);
    }
    const id = typeof label.id === 'string' && (!allow || allow(label.id)) ? label.id : null;
    if (!id || depth >= LABEL_DEPTH) {
        return plainText(label.text);
    }
    const values = label.values && typeof label.values === 'object' ? serverValues(label.values, allow, depth + 1) : undefined;
    return tOr(id, label.text, values);
}

// How the page shows each kind of label, such as `scenario`, which scenarios.js gives, so this
// module imports none of them.
const valueKinds = new Map();
export function setValueKind(kind, show) {
    valueKinds.set(kind, show);
}

// A decimal number among the values, such as the ability 0.50 of a name, which shows with the
// decimal sign of the language and as many digits.
const DECIMAL = /^-?\d+\.\d+$/;

// The values of a server message for the page's language. A value is text, or a label of its
// own, such as the name of an entrant inside the title of a recording.
function serverValues(values, allow, depth) {
    const out = {};
    for (const [key, value] of Object.entries(values)) {
        if (value && typeof value === 'object') {
            out[key] = labelText(value, allow, depth);
        } else if (typeof value === 'string' && DECIMAL.test(value)) {
            const digits = value.length - value.indexOf('.') - 1;
            out[key] = formatNumber(Number(value), { minimumFractionDigits: digits, maximumFractionDigits: digits });
        } else {
            out[key] = value;
        }
    }
    return out;
}

// A message as a list of texts and nodes, where a placeholder whose value is a node, or a number
// in braces that indexes the nodes given, takes the node itself. Text stays text, so a message
// never carries markup.
export function tn(id, values = {}) {
    const found = lookup(id);
    if (!found) {
        noteMissing(id);
        return [id];
    }
    return markNodes(pick(found.message, values, found.locale), values);
}

// A message as a fragment of nodes, its marks as strong, code and kbd elements, for a place that
// takes one node, such as the text of a paragraph.
export function tm(id, values = {}) {
    const fragment = document.createDocumentFragment();
    fragment.append(...tn(id, values).map((part) => (typeof part === 'string' ? document.createTextNode(part) : part)));
    return fragment;
}

// The nodes of a text with marks, each mark an element whose text the values fill, and each
// placeholder whose value is a node the node itself.
function markNodes(text, values) {
    const out = [];
    for (const part of markParts(text)) {
        if (part.kind === 'text') {
            out.push(...splitNodes(part.text, values));
        } else if (part.kind === 'code') {
            out.push(codeKind.node(fill(part.text, plainValues(values))));
        } else {
            const node = document.createElement('strong');
            node.append(...splitNodes(part.text, values));
            out.push(node);
        }
    }
    return out;
}

// The values as text, a node as its text content, for the inside of code.
function plainValues(values) {
    const out = {};
    for (const [key, value] of Object.entries(values || {})) {
        out[key] = value && typeof value === 'object' && 'textContent' in value ? value.textContent : value;
    }
    return out;
}

// The nodes of a message of the server, with its marks, as serverText reads it in text.
export function serverNodes(object, field = 'error', allow = null) {
    if (!object || typeof object !== 'object') {
        return [plainText(object)];
    }
    return labelNodes({ id: object[`${field}_id`], text: object[field], values: object[`${field}_values`] }, allow);
}

// The nodes of a label of the server, as labelText reads it in text. Its values show as text.
export function labelNodes(label, allow = null) {
    const id = label && typeof label === 'object' && typeof label.id === 'string' && !label.kind && (!allow || allow(label.id)) ? label.id : null;
    if (!id || !lookup(id)) {
        return [labelText(label, allow)];
    }
    const values = label.values && typeof label.values === 'object' ? serverValues(label.values, allow, 1) : undefined;
    return tn(id, values);
}

function splitNodes(text, values) {
    const out = [];
    let last = 0;
    for (const match of text.matchAll(PLACEHOLDER)) {
        const value = values[match[1]];
        if (value === undefined || value === null) {
            continue;
        }
        if (match.index > last) {
            out.push(text.slice(last, match.index));
        }
        out.push(typeof value === 'object' ? value : String(value));
        last = match.index + match[0].length;
    }
    if (last < text.length) {
        out.push(text.slice(last));
    }
    return out;
}

// The attributes that static markup translates, each read from data-i18n-<attribute>.
const ATTRIBUTES = ['title', 'aria-label', 'placeholder', 'alt', 'aria-description', 'aria-roledescription', 'label'];

// A symbol of the sprite, an svg of the class icon, which a message of static markup leaves alone.
const isSymbol = (node) => node.localName === 'svg' && /(^|\s)icon(\s|$)/.test(node.getAttribute('class') || '');

// Translates the static texts under root. An element with data-i18n takes the message as its
// text, and when it holds elements, they fill the placeholders {0}, {1} and on in their order. A
// symbol among them fills no placeholder and stays in front of the message. Each
// data-i18n-<attribute> sets that attribute.
export function translateDom(root = document) {
    if (!root || !root.querySelectorAll) {
        return;
    }
    const nodes = [];
    if (root.nodeType === 1) {
        nodes.push(root);
    }
    nodes.push(...root.querySelectorAll('[data-i18n], [data-i18n-title], [data-i18n-aria-label], [data-i18n-placeholder], [data-i18n-alt], [data-i18n-aria-description], [data-i18n-aria-roledescription], [data-i18n-label]'));
    for (const node of nodes) {
        const id = node.dataset.i18n;
        if (id) {
            const symbols = [...node.children].filter(isSymbol);
            const children = [...node.children].filter((child) => !isSymbol(child));
            const found = lookup(id);
            const marked = found && markParts(pick(found.message, {}, found.locale)).some((part) => part.kind !== 'text');
            if (children.length || symbols.length) {
                const values = {};
                children.forEach((child, i) => { values[i] = child; });
                node.replaceChildren(...symbols, ...tn(id, values));
            } else if (marked) {
                node.replaceChildren(...tn(id));
            } else {
                node.textContent = t(id);
            }
        }
        for (const name of ATTRIBUTES) {
            const key = node.getAttribute(`data-i18n-${name}`);
            if (key) {
                node.setAttribute(name, t(key));
            }
        }
    }
}

// A number in the locale of the language.
export function formatNumber(value, options) {
    try {
        return new Intl.NumberFormat(info.locale, options).format(value);
    } catch {
        return String(value);
    }
}

// A date in the locale of the language, from a Date, an ISO text or milliseconds.
export function formatDateTime(value, options = { dateStyle: 'medium', timeStyle: 'short' }) {
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) {
        return '';
    }
    try {
        return new Intl.DateTimeFormat(info.locale, options).format(date);
    } catch {
        return date.toISOString();
    }
}

// Items joined as a list in the language, such as `a, b and c`.
export function formatList(items, type = 'conjunction') {
    const list = [...items].map(String);
    try {
        return new Intl.ListFormat(info.locale, { style: 'long', type }).format(list);
    } catch {
        return list.join(', ');
    }
}

// The language shown, its code, name, locale, direction and plural categories.
export function language() {
    return { ...info };
}

// The locale of numbers and dates.
export function locale() {
    return info.locale;
}

// The stored choice, or null while the page follows the browser.
export function storedLanguage() {
    try {
        const v = localStorage.getItem(STORE_KEY);
        return v ? JSON.parse(v) : null;
    } catch {
        return null;
    }
}

// The ids that no language held since the page loaded, for checks.
export function missing() {
    return [...missingIds];
}

// The raw messages whose ids start with prefix, in the shown language with English beneath, for
// a module with its own formatter such as the captions.
export function messages(prefix = '') {
    const out = {};
    for (const source of [english, table]) {
        for (const [id, value] of Object.entries(source)) {
            if (id.startsWith(prefix)) {
                out[id] = value;
            }
        }
    }
    return out;
}

// The languages to choose from, shipped first, from the server, else the shipped pair.
export async function listLanguages() {
    try {
        const res = await fetch('/api/languages');
        if (res.ok) {
            const body = await res.json();
            if (Array.isArray(body.languages)) {
                return body.languages;
            }
        }
    } catch {
        // Without the server the shipped languages remain.
    }
    return [
        { code: 'en', name: 'English', source: 'shipped', usable: true },
    ];
}

// Calls fn with the new language after each change.
export function onLanguageChange(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
}

// Chooses a language, or null to follow the browser. The language loads first, so a file that
// fails leaves the page as it is and the promise rejects. Listeners then hear of the change.
export async function setLanguage(code) {
    if (code === null) {
        try {
            localStorage.removeItem(STORE_KEY);
        } catch {
            // Storage can be unavailable.
        }
    } else {
        const parsed = code === 'en' ? { messages: english, info: englishInfo } : parse(await readFile(code), code);
        table = parsed.messages;
        info = parsed.info;
        try {
            localStorage.setItem(STORE_KEY, JSON.stringify(code));
        } catch {
            // Storage can be unavailable, the choice then lasts for this visit only.
        }
        applyDocument();
    }
    for (const fn of listeners) {
        fn(language());
    }
}

await start();
