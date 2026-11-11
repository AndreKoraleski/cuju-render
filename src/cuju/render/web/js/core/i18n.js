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
const CODE = /^[a-z]{2,3}(-[a-z0-9]{1,8})*$/;
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

// The plural rules of a locale, made once.
function pluralRules(locale) {
    let r = rules.get(locale);
    if (!r) {
        try {
            r = new Intl.PluralRules(locale);
        } catch {
            r = new Intl.PluralRules('en-US');
        }
        rules.set(locale, r);
    }
    return r;
}

// Whether a code names a language file safely, lowercase letters and digits in parts.
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

// Reads a shipped file from the page itself or from beside this module, or a language of the home
// folder from the server.
async function readFile(code) {
    if (!validCode(code)) {
        throw new Error(`no language ${code}`);
    }
    if (IN_NODE) {
        // Under Node a test may load a copy of the modules alone, so the files of the repository
        // root, the working folder of the tests, stand behind those beside the module.
        const { readFile: read } = await import('node:fs/promises');
        const { pathToFileURL } = await import('node:url');
        const places = [new URL(`${code}.json`, BASE)];
        if (typeof process !== 'undefined') {
            places.push(pathToFileURL(`${process.cwd()}/src/cuju/render/web/languages/${code}.json`));
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
    const shipped = inlinedFiles();
    if (shipped && shipped[code] && typeof shipped[code] === 'object') {
        return shipped[code];
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
        throw new Error(`no language ${code}`);
    }
    return res.json();
}

// Splits a file into its header and its messages, keeping well formed messages alone.
function parse(data, code) {
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
        throw new Error(`the language ${code} is not a JSON object`);
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
    return {
        info: {
            code,
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
        const c = String(code || '').toLowerCase();
        if (done || !validCode(c)) {
            return;
        }
        // English ends the list, and so does a variant of English the browser prefers, which the
        // page shows as English. A chosen variant, such as en-x-mine of the home folder, loads.
        if (c === 'en' || (!chosen && c.startsWith('en-'))) {
            done = true;
        } else if (!out.some((item) => item.code === c)) {
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
            const lower = String(tag || '').toLowerCase();
            add(lower, false);
            add(lower.split('-')[0], false);
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
        // holds, such as pt for pt-br, so the start asks the server for nothing it may not have.
        if (!chosen && shipped && !shipped[code] && list.slice(i + 1).some((item) => shipped[item.code])) {
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
    const count = Number(values && values.count);
    if (Number.isFinite(count) && typeof message[`=${count}`] === 'string') {
        return message[`=${count}`];
    }
    const category = Number.isFinite(count) ? pluralRules(locale).select(count) : 'other';
    return typeof message[category] === 'string' ? message[category] : message.other;
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
    return fill(pick(found.message, values, found.locale), values);
}

// The text of a message whose id the server or a table may lack, such as the title of a
// challenge, else the given fallback, which is the server's own English text.
export function tOr(id, fallback, values) {
    if (!id || !lookup(id)) {
        return fallback === undefined || fallback === null ? '' : fill(String(fallback), values);
    }
    return t(id, values);
}

// Whether a language holds the id.
export function has(id) {
    return lookup(id) !== null;
}

// The text of a message from the server, an object with the English text in `field` and, when
// the server gives them, its id in `field_id` and its values in `field_values`. A name that the
// server makes, such as that of the built-in AI or of a round, comes the same way, while a name
// that a person gave comes as text alone and shows as given.
export function serverText(object, field = 'error') {
    if (!object || typeof object !== 'object') {
        return object === undefined || object === null ? '' : String(object);
    }
    const values = object[`${field}_values`] && typeof object[`${field}_values`] === 'object' ? object[`${field}_values`] : undefined;
    return tOr(object[`${field}_id`], object[field], values && serverValues(values));
}

// The text of a label of the server, an object with its English `text`, its message `id` and
// its `values`, as a value of another message holds one, or a plain text. A label with a `kind`
// names a thing that a module of the page shows, such as a scenario by its `name`.
export function labelText(label) {
    if (!label || typeof label !== 'object') {
        return label === undefined || label === null ? '' : String(label);
    }
    if (typeof label.kind === 'string') {
        const show = valueKinds.get(label.kind);
        return show ? show(label.name, label) : String(label.text ?? label.name ?? '');
    }
    const values = label.values && typeof label.values === 'object' ? serverValues(label.values) : undefined;
    return tOr(label.id, label.text, values);
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
function serverValues(values) {
    const out = {};
    for (const [key, value] of Object.entries(values)) {
        if (value && typeof value === 'object') {
            out[key] = labelText(value);
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
    return splitNodes(pick(found.message, values, found.locale), values);
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

// Translates the static texts under root. An element with data-i18n takes the message as its
// text, and when it holds elements, they fill the placeholders {0}, {1} and on in their order.
// Each data-i18n-<attribute> sets that attribute.
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
            const children = [...node.children];
            if (children.length) {
                const values = {};
                children.forEach((child, i) => { values[i] = child; });
                node.replaceChildren(...tn(id, values));
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
        { code: 'pt', name: 'Português (Brasil)', source: 'shipped', usable: true },
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
