// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Surprise me on the page, a panel in the Identity and Kit sections of the team editor, a button
// in the form that adds a team, and the scripting function window.cuju.surprise.

import { api } from '../core/api.js';
import { h } from './library.js';
import { kitShirt } from '../pages/matches.js';
import { KIT_STYLES, badgeFor, surprise } from './surprise.js';

const clone = (v) => JSON.parse(JSON.stringify(v));
// The seed and kit style last typed in each editor, kept while sections rebuild.
const choices = new WeakMap();

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

function styleSelect(value) {
    const select = h('select', { class: 'surprise-style', 'aria-label': 'Kit style' },
        h('option', { value: 'any', selected: value === 'any' }, 'Any style'),
        KIT_STYLES.map((s) => h('option', { value: s.id, selected: value === s.id }, s.name)));
    return select;
}

// The sentence that names how a team was made, so it can be made again.
export function surpriseNote(result) {
    const article = /^[aeiou]/.test(result.scheme) ? 'an' : 'a';
    return `Made from seed ${result.seed}, ${result.kitStyleName} in ${article} ${result.scheme} scheme. The same seed and style make it again.`;
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
        type: 'text', class: 'surprise-seed', value: state.seed, maxlength: '40', placeholder: 'Random',
        'aria-label': 'Seed, empty for a fresh one',
    });
    const style = styleSelect(state.style);
    const note = h('p', { class: 'surprise-note muted small', role: 'status' }, state.note
        || 'A whole new look and name, from color schemes that keep the numbers readable and stay clear of common kits.');
    const go = () => {
        const result = surprise({ seed: seed.value, style: style.value, format: editor.format });
        choices.set(editor, { seed: seed.value, style: style.value, note: surpriseNote(result) });
        applySurprise(editor, result);
        editor.formHost.querySelector('.surprise-go')?.focus();
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
    return h('div', { class: 'surprise-panel', role: 'group', 'aria-label': 'Surprise me' },
        h('button', { type: 'button', class: 'btn surprise-go', title: 'Fill the kit, goalkeeper, numbers, name, badge, fans and roster names', onclick: go }, 'Surprise me'),
        h('label', {}, 'Seed', seed),
        h('label', {}, 'Style', style),
        note);
}

// Surprise me in the form that adds a team. It fills the name, and the team added takes the
// generated kit. Returns the element, a function that styles the added team and a reset.
export function addFormSurprise(app, nameInput, formatSelect) {
    injectSurpriseStyle();
    let made = null;
    const shirt = h('span', { class: 'surprise-shirt' });
    const note = h('p', { class: 'surprise-note muted small', role: 'status' });
    const clear = h('button', { type: 'button', class: 'btn small ghost', hidden: true, onclick: () => reset() }, 'Plain kit');
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
        note.textContent = `${surpriseNote(result)} The team added wears this kit.`;
        clear.hidden = false;
    };
    const element = h('div', { class: 'surprise-add' },
        h('button', { type: 'button', class: 'btn surprise-go', onclick: go }, 'Surprise me'), shirt, note, clear);
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
            app.hud.toast(`The team was added, its kit could not be saved, ${err.message || err}.`, 'error', 7000);
        }
    };
    return { element, apply, reset, get made() { return made; } };
}

// window.cuju.surprise, the generator for scripts. With apply true it also fills the open team
// editor, as unsaved changes.
export function surpriseFor(app, options = {}) {
    const editor = app.editor;
    const open = !!(editor && editor.isOpen && editor.team);
    if (options.apply && !open) {
        throw new Error('open a team in the editor before applying a surprise');
    }
    const format = options.format === undefined && open ? editor.format : options.format;
    const result = surprise({ seed: options.seed, style: options.style, format });
    if (options.apply) {
        choices.set(editor, { seed: result.seed, style: result.kitStyle, note: surpriseNote(result) });
        applySurprise(editor, result);
    }
    return clone(result);
}
