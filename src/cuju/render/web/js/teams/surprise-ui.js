// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Surprise me on the page, a panel in the Identity and Kit sections of the team editor, a button
// in the form that adds a team, and the scripting function window.cuju.surprise. A screen reader
// hears the name and the note of each team that a button makes.

import { api } from '../core/api.js';
import { t, tOr } from '../core/i18n.js';
import { h } from './library.js';
import { kitShirt } from '../pages/matches.js';
import { KIT_STYLES, badgeFor, surprise } from './surprise.js';

const clone = (v) => JSON.parse(JSON.stringify(v));
// The seed and kit style last typed in each editor, kept while sections rebuild.
const choices = new WeakMap();
// The scheme ids of the generator's scheme names. The generator keeps its English names, which
// scripts read from its results.
const SCHEME_IDS = {
    complementary: 'complementary', 'split complementary': 'split', analogous: 'analogous', triadic: 'triadic', monochrome: 'monochrome',
};

function injectSurpriseStyle() {
    if (document.getElementById('cuju-surprise-style')) {
        return;
    }
    const style = document.createElement('style');
    style.id = 'cuju-surprise-style';
    style.textContent = `
.surprise-panel { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 8px 10px; margin: 4px 0 12px;
    padding: 8px 10px; border: 1px dashed var(--border); border-radius: 6px; }
.surprise-panel label { display: flex; flex-direction: column; gap: 3px; color: var(--muted); font-size: 13px; }
.surprise-panel .surprise-seed { width: 9em; }
.surprise-panel .surprise-note { flex-basis: 100%; margin: 0; }
.surprise-add { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.surprise-add .surprise-note { margin: 0; flex: 1 1 12em; }
`;
    document.head.appendChild(style);
}

// Says a generated team aloud, its name and how it was made, through one polite live region of
// the page, so the panel that rebuilds around the result never reads it twice or drops it.
let announcer = null;
export function announceSurprise(result, extra = '') {
    if (!announcer || !announcer.isConnected) {
        announcer = h('p', { id: 'surprise-live', class: 'sr-only', 'aria-live': 'polite' });
        document.body.append(announcer);
    }
    const text = `${t('surprise-ui.announce', { name: result.name, note: surpriseNote(result) })}${extra ? ` ${extra}` : ''}`;
    // A fresh text each time, so the same team made twice is read twice.
    announcer.textContent = '';
    setTimeout(() => {
        announcer.textContent = text;
    }, 50);
    return text;
}

function styleSelect(value) {
    const select = h('select', { class: 'surprise-style', 'aria-label': t('surprise-ui.style.label') },
        h('option', { value: 'any', selected: value === 'any' }, t('surprise-ui.style.any')),
        KIT_STYLES.map((s) => h('option', { value: s.id, selected: value === s.id }, tOr(`surprise-ui.style.${s.id}`, s.name))));
    return select;
}

// The sentence that names how a team was made, so it can be made again.
export function surpriseNote(result) {
    const article = /^[aeiou]/.test(result.scheme) ? 'an' : 'a';
    const id = SCHEME_IDS[result.scheme];
    return t('surprise-ui.note', {
        seed: result.seed,
        style: tOr(`surprise-ui.style.${result.kitStyle}`, result.kitStyleName),
        scheme: tOr(id && `surprise-ui.scheme.${id}`, `${article} ${result.scheme} scheme`),
    });
}

// Fills the open editor with a generated team, as unsaved changes. Save keeps them and leaving
// discards them, as with any other edit.
export function applySurprise(editor, result) {
    const s = editor.style;
    const st = result.style;
    s.kit = clone(st.kit);
    s.goalkeeper = clone(st.goalkeeper);
    s.number = st.number;
    s.badge = st.badge;
    s.crowd = { colors: clone(st.crowd.colors) };
    editor.crowdFollowsKit = true;
    s.players.forEach((p, i) => {
        if (st.players[i]) {
            p.name = st.players[i].name;
        }
    });
    editor.name = result.name;
    const state = choices.get(editor) || {};
    choices.set(editor, { ...state, note: surpriseNote(result) });
    editor.built.clear();
    editor.invalidate(editor.section);
    editor.refreshPreview();
}

// The Surprise me panel of the editor, a button, a seed field and a kit style.
export function surprisePanel(editor) {
    injectSurpriseStyle();
    const state = choices.get(editor) || { seed: '', style: 'any', note: '' };
    const seed = h('input', {
        type: 'text', class: 'surprise-seed', value: state.seed, maxlength: '40', placeholder: t('surprise-ui.seed.placeholder'),
        'aria-label': t('surprise-ui.seed.label'),
    });
    const style = styleSelect(state.style);
    const note = h('p', { class: 'surprise-note muted small' }, state.note
        || t('surprise-ui.intro'));
    const go = () => {
        const result = surprise({ seed: seed.value, style: style.value, format: editor.format });
        choices.set(editor, { seed: seed.value, style: style.value, note: surpriseNote(result) });
        applySurprise(editor, result);
        editor.formHost.querySelector('.surprise-go')?.focus();
        announceSurprise(result);
    };
    const keep = () => choices.set(editor, { ...(choices.get(editor) || {}), seed: seed.value, style: style.value });
    seed.addEventListener('input', keep);
    style.addEventListener('change', keep);
    seed.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            go();
        }
    });
    return h('div', { class: 'surprise-panel', role: 'group', 'aria-label': t('surprise-ui.button') },
        h('button', { type: 'button', class: 'btn surprise-go', title: t('surprise-ui.title'), onclick: go }, t('surprise-ui.button')),
        h('label', {}, t('surprise-ui.seed'), seed),
        h('label', {}, t('surprise-ui.style'), style),
        note);
}

// Surprise me in the form that adds a team. It fills the name, and the team added takes the
// generated kit. Returns the element, a function that styles the added team and a reset.
export function addFormSurprise(app, nameInput, formatSelect) {
    injectSurpriseStyle();
    let made = null;
    const shirt = h('span', { class: 'surprise-shirt' });
    const note = h('p', { class: 'surprise-note muted small' });
    const clear = h('button', { type: 'button', class: 'btn small ghost', hidden: true, onclick: () => reset() }, t('surprise-ui.plainKit'));
    const reset = () => {
        made = null;
        shirt.replaceChildren();
        note.textContent = '';
        clear.hidden = true;
    };
    const go = () => {
        const result = surprise({ format: formatSelect.value });
        made = { seed: result.seed, style: result.kitStyle };
        nameInput.value = result.name;
        shirt.replaceChildren(kitShirt({ style: result.style }, 0));
        note.textContent = t('surprise-ui.addedNote', { note: surpriseNote(result) });
        clear.hidden = false;
        announceSurprise(result, t('surprise-ui.addedKit'));
    };
    const element = h('div', { class: 'surprise-add' },
        h('button', { type: 'button', class: 'btn surprise-go', onclick: go }, t('surprise-ui.button')), shirt, note, clear);
    // Gives the team just added the generated style, its badge taken from the name it got.
    const apply = async (team) => {
        if (!made || !team || !team.id) {
            reset();
            return;
        }
        const format = team.format || formatSelect.value;
        const result = surprise({ ...made, format });
        const style = { ...result.style, badge: badgeFor(team.name || result.name) };
        reset();
        try {
            await api.updateTeam(team.id, { style });
        } catch (err) {
            app.hud.toast(t('surprise-ui.kitFailed', { reason: err.message || err }), 'error', 7000);
        }
    };
    return { element, apply, reset, get made() { return made; } };
}

// window.cuju.surprise, the generator for scripts. With apply true it also fills the open team
// editor, as unsaved changes.
export function surpriseFor(app, options = {}) {
    const editor = app.editor;
    const open = !!(editor && editor.isOpen && editor.team);
    // A surprise applies only to an editor in view, so no unsaved change lands out of sight.
    if (options.apply && !(open && app.page === 'teams')) {
        throw new Error('open a team in the editor of the Teams page before applying a surprise');
    }
    const format = options.format === undefined && open ? editor.format : options.format;
    const result = surprise({ seed: options.seed, style: options.style, format });
    if (options.apply) {
        choices.set(editor, { seed: result.seed, style: result.kitStyle, note: surpriseNote(result) });
        applySurprise(editor, result);
    }
    return clone(result);
}
