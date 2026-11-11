// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The team editor, in sections, for the team's identity, kit and artwork, roster, player model and
// its colors, fans, celebrations, sounds, sponsors and export, with a live 3D preview. Each change
// updates the part of the form it touches, the rest stays as it is.

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import {
    MAX_MODEL_BYTES, MAX_SOUND_BYTES, SOUND_SLOTS, api, controlForm, controlFromValue,
    controlValue, formatBytes,
} from '../core/api.js';
import { NODE_NAMES, PLAYER_FLOATS } from '../recording/format.js';
import { SHIRT_SIZE, SHIRT_SLOTS, SPONSOR_SIZE, SPONSOR_SLOTS, invalidateArt, loadTeamArt } from './art.js';
import {
    BUILTIN_KIT, DEFAULT_GOALKEEPER, DEFAULT_KIT, FORMATS, HAIR_COLORS_NAMED, NUMBER_COLORS, PATTERNS, PLAYER_HAIRS,
    PLAYER_SKINS, css, fromHex, hex, modelChoice, normalizeStyle, rosterEntry, serverStyle,
} from '../players/kits.js';
import { h } from './library.js';
import { kitShirt } from '../pages/matches.js';
import { Dropdown, enhanceSelect, icon, menuItem } from '../core/menu.js';
import { Painter } from './painter.js';
import { Players, Rig, clipNames, fileBoneNames, guessJoints, parseModel, restPoseNodes, walkPoseNodes } from '../players/players.js';
import { animationLibrary, danceNames, posePlayer } from '../broadcast/celebrate.js';
import { attachKayKitClips, kaykitLabel, menuClips } from '../players/kaykit.js';
import { clipMoveLabel, clipMoves, clipsPanel, openClips, previewMove } from './clip-editor.js';
import { surprisePanel } from './surprise-ui.js';
import { t } from '../core/i18n.js';
import { teamName } from '../core/names.js';

const LABELS = Object.fromEntries([
    'plain', 'stripes', 'hoops', 'halves', 'sash', 'checkers',
    'mixed', 'light', 'medium', 'dark', 'bald', 'short', 'long',
    'white', 'black', 'secondary', 'tan',
    'short01', 'short02', 'medium01', 'long01', 'long02',
    'brown', 'darkblonde', 'blonde', 'red',
].map((key) => [key, t(`editor.look.${key}`)]).concat([['grf', 'GRF']]));

const SECTIONS = ['identity', 'kit', 'roster', 'model', 'fans', 'celebrations', 'sounds', 'sponsors', 'export']
    .map((id) => ({ id, label: t(`editor.section.${id}.label`), hint: t(`editor.section.${id}.hint`) }));

const SOUND_LABELS = Object.fromEntries(['goal', 'shot', 'pass', 'tackle', 'save', 'kick', 'celebration', 'chant']
    .map((slot) => [slot, [t(`editor.sound.${slot}.label`), t(`editor.sound.${slot}.hint`)]]));

const MAX_RECOLORS = 32;
// The kit color each role of a model's color follows, and its name in the list.
const ROLE_KIT = { shirt: 'primary', trim: 'secondary', shorts: 'shorts', socks: 'socks' };
const ROLE_LABELS = { shirt: t('editor.kit.shirt'), trim: t('editor.kit.trim'), shorts: t('editor.kit.shorts'), socks: t('editor.kit.socks') };
// A color shown on the preview while its swatch is picked, and how long it blinks.
const FLASH = '#ff2bd6';
const FLASH_MS = 900;
const clone = (v) => JSON.parse(JSON.stringify(v));
const sameColors = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const pretty = (name) => String(name).replace(/^clip:/, '').replace(/[_-]+/g, ' ').replace(/^\w/, (c) => c.toUpperCase());

// Models shipped with cuju, listed by the server with id, name, url, joints, author and license.
let shippedPromise = null;
export function shippedModels() {
    if (!shippedPromise) {
        shippedPromise = (async () => {
            try {
                const list = await api.models();
                return Array.isArray(list) ? list.filter((m) => m && m.id && m.url) : [];
            } catch {
                shippedPromise = null;
                return [];
            }
        })();
    }
    return shippedPromise;
}

const shippedRigs = new Map();
export async function loadShippedRig(id) {
    if (!shippedRigs.has(id)) {
        shippedRigs.set(id, (async () => {
            const entry = (await shippedModels()).find((m) => m.id === id);
            if (!entry) {
                return null;
            }
            const gltf = await new GLTFLoader().loadAsync(entry.url);
            const joints = entry.joints || guessJoints(fileBoneNames(gltf));
            // The clips of the file travel with the rig, a celebration may play one of them, and
            // a model on KayKit's rig gains the clips of KayKit's animation packs.
            const rig = new Rig(gltf.scene, joints, { onlyKit: true, engineFrame: entry.frame === 'engine', animations: gltf.animations || [] });
            return attachKayKitClips(rig);
        })().catch((err) => {
            console.warn('shipped model not loaded', id, err);
            shippedRigs.delete(id);
            return null;
        }));
    }
    return shippedRigs.get(id);
}

// The optional modules of the figures, the colors of a model and its animations. The editor works
// without them and offers what they add once they load.
let recolorModule = null;
import('../players/recolor.js').then((m) => {
    recolorModule = m;
}).catch(() => {});

function modelColorsOf(rig) {
    if (!rig || !recolorModule || typeof recolorModule.modelColors !== 'function') {
        return null;
    }
    try {
        return recolorModule.modelColors(rig).map((c) => ({ hex: String(c.hex).toLowerCase(), weight: c.weight, role: c.role || null }));
    } catch (err) {
        console.warn('model colors not read', err);
        return null;
    }
}

// The clips a model offers as celebrations, by their names without the clip prefix. A model on
// KayKit's rig offers the clips of KayKit's packs that suit a celebration.
function clipsOf(rig) {
    if (!rig) {
        return [];
    }
    try {
        return rig.kaykit ? menuClips(rig) : (clipNames(rig) || []).map((n) => String(n).replace(/^clip:/, ''));
    } catch {
        return [];
    }
}

function celebrationNames() {
    try {
        return danceNames();
    } catch {
        return [];
    }
}

function celebrationLabel(name) {
    const lib = animationLibrary();
    const all = lib && lib.ANIMATIONS;
    const entry = Array.isArray(all) ? all.find((a) => a && a.name === name) : all && all[name];
    return (entry && (entry.label || entry.title)) || kaykitLabel(name) || pretty(name);
}

export class TeamEditor {
    constructor(app) {
        this.app = app;
        // The editor lives in the Teams page, beside the team list.
        this.dialog = document.getElementById('team-editor');
        this.painter = new Painter();
        // Every open takes a new token, and work that finishes for an earlier open is dropped.
        this.token = 0;
        this.loopId = 0;
        this.previewToken = 0;
        this.thumbs = new Map();
        this.team = null;
        this.section = 'identity';
    }

    async open(team) {
        const token = ++this.token;
        this.releaseThumbs();
        this.team = team;
        // A name that cuju made, such as the built-in AI's, shows in the page's language, and goes
        // back to the server as it came while it stays unchanged.
        this.shownName = teamName(team);
        this.name = this.shownName;
        this.format = FORMATS[team.format] ? team.format : '11v11';
        // The players the submission controls, as a value of controlValue.
        this.control = controlValue(team.control);
        const raw = team.style || {};
        this.style = normalizeStyle(team, 0);
        this.style.model = modelChoice(raw) === 'grf' && team.model && !raw.model ? 'custom' : modelChoice(raw);
        // Entries the kit helpers may not carry are taken from the saved style here.
        this.style.colors = raw.colors && typeof raw.colors === 'object' ? clone(raw.colors) : {};
        this.style.celebrations = Array.isArray(raw.celebrations) ? raw.celebrations.slice() : [];
        const kitPair = [this.style.kit.primary, this.style.kit.secondary];
        const crowd = raw.crowd && Array.isArray(raw.crowd.colors) && raw.crowd.colors.length ? clone(raw.crowd.colors).slice(0, 4) : clone(kitPair);
        this.style.crowd = { colors: crowd };
        // The fans follow the kit until the team picks colors of its own.
        this.crowdFollowsKit = sameColors(crowd, kitPair);
        const rawPlayers = Array.isArray(raw.players) ? raw.players : [];
        this.style.players = this.style.players.map((p, i) => ({
            ...p,
            model: (rawPlayers[i] && rawPlayers[i].model) || p.model || 'team',
            celebration: (rawPlayers[i] && rawPlayers[i].celebration) || p.celebration || 'team',
        }));
        this.fitRoster();
        this.images = new Set(team.images || []);
        this.sounds = new Set(team.sounds || []);
        this.model = null;
        this.modelDirty = false;
        this.modelNote = null;
        this.removeModel = false;
        this.saving = false;
        this.walk = false;
        this.previewGk = false;
        this.previewIndex = Math.min(9, FORMATS[this.format] - 1);
        this.playing = null;
        this.colorModel = null;
        this.built = new Map();
        try {
            this.shipped = await shippedModels();
            if (token !== this.token) {
                return;
            }
            this.render();
            this.opener = document.activeElement;
            this.dialog.hidden = false;
            this.dialog.querySelector('button')?.focus();
            document.getElementById('teams-placeholder').hidden = true;
            this.startPreview();
            this.initial = this.snapshot();
            this.loadArt(token);
            openClips(this, token);
            if (team.model) {
                this.loadExistingModel(token);
            }
        } catch (err) {
            this.app.hud.toast(t('editor.openFailed', { reason: err.message || err }), 'error', 7000);
        }
    }

    get isOpen() {
        return !this.dialog.hidden;
    }

    // What a save would send, to tell whether anything changed since the team opened.
    snapshot() {
        return JSON.stringify([this.name.trim(), this.format, this.control, this.payloadStyle(), this.modelDirty, this.removeModel]);
    }

    get dirty() {
        return !!this.team && this.initial !== undefined && this.snapshot() !== this.initial;
    }

    // Asks before unsaved changes are thrown away, true when the editor may move on.
    confirmLeave() {
        if (!this.isOpen || !this.dirty) {
            return true;
        }
        return confirm(t('editor.discard', { name: teamName(this.team) }));
    }

    close(force = false) {
        if (!force && !this.confirmLeave()) {
            return false;
        }
        this.token++;
        this.stopPreview();
        this.stopSound();
        this.releaseThumbs();
        this.dialog.hidden = true;
        this.opener?.focus();
        document.getElementById('teams-placeholder').hidden = false;
        this.team = null;
        this.initial = undefined;
        for (const el of document.querySelectorAll('#teams-side .teams-list > li.selected')) {
            el.classList.remove('selected');
            el.setAttribute('aria-selected', 'false');
        }
        if (this.app.library) {
            this.app.library.selectedId = null;
        }
        return true;
    }

    releaseThumbs() {
        for (const url of this.thumbs.values()) {
            URL.revokeObjectURL(url);
        }
        this.thumbs.clear();
    }

    fitRoster() {
        const n = FORMATS[this.format];
        const list = (this.style.players || []).slice(0, n);
        while (list.length < n) {
            list.push(null);
        }
        this.style.players = list.map((p, i) => ({
            ...rosterEntry(p, i),
            model: (p && p.model) || 'team',
            celebration: (p && p.celebration) || 'team',
        }));
    }

    get grf() {
        return this.style.model === 'grf';
    }

    // The model a roster entry plays with, the team's unless it has one of its own.
    playerModel(i) {
        const p = this.style.players[i];
        return p && p.model && p.model !== 'team' ? p.model : this.style.model;
    }

    // The models that may be chosen, by id and name.
    modelOptions() {
        const list = [['grf', t('editor.model.grf')]];
        for (const m of this.shipped) {
            list.push([m.id, m.name || m.id]);
        }
        if (this.model || (this.team.model && !this.removeModel)) {
            list.push(['custom', this.model ? t('editor.model.ownNamed', { label: this.model.label }) : t('editor.model.own')]);
        }
        return list;
    }

    modelName(id) {
        const found = this.modelOptions().find(([v]) => v === id);
        return found ? found[1] : id;
    }

    // The style as the server takes it, with the entries that the kit helpers leave out.
    payloadStyle() {
        const s = serverStyle(this.style);
        const models = new Set(['custom', ...this.shipped.map((m) => m.id)]);
        const colors = {};
        for (const [model, pairs] of Object.entries(this.style.colors || {})) {
            if (models.has(model) && pairs && Object.keys(pairs).length) {
                colors[model] = { ...pairs };
            }
        }
        s.colors = colors;
        s.crowd = { colors: this.style.crowd.colors.map((c) => c.map((v) => Math.round(v))) };
        s.celebrations = this.style.celebrations.slice(0, 32);
        s.players = s.players.map((p, i) => ({
            ...p,
            model: this.style.players[i].model || 'team',
            celebration: this.style.players[i].celebration || 'team',
        }));
        return s;
    }

    // Loads the team's shirt artwork for the preview and thumbnails of every slot.
    async loadArt(token = this.token) {
        const team = this.team;
        try {
            invalidateArt();
            const art = await loadTeamArt({ ...team, images: [...this.images] });
            if (token !== this.token) {
                return;
            }
            this.style.art = art;
            for (const slot of [...SHIRT_SLOTS, ...SPONSOR_SLOTS]) {
                if (this.images.has(slot) && !this.thumbs.has(slot)) {
                    let url = null;
                    try {
                        url = URL.createObjectURL(await api.image(team.id, slot));
                    } catch {
                        // The thumbnail stays empty, the slot still works.
                    }
                    if (url && (token !== this.token || this.thumbs.has(slot))) {
                        URL.revokeObjectURL(url);
                    } else if (url) {
                        this.thumbs.set(slot, url);
                    }
                    if (token !== this.token) {
                        return;
                    }
                }
            }
            this.updateSlots();
            this.refreshPreview();
        } catch (err) {
            if (token === this.token) {
                this.app.hud.toast(t('editor.art.loadFailed', { reason: err.message || err }), 'error');
            }
        }
    }

    async loadExistingModel(token = this.token) {
        const team = this.team;
        let loaded = false;
        let reason = '';
        try {
            const bytes = await api.modelBytes(team.id);
            if (token !== this.token) {
                return;
            }
            loaded = await this.useModelBytes(bytes, t('editor.model.savedLabel'), team.model.joints, false, false, token);
        } catch (err) {
            reason = String(err.message || err).replace(/\.$/, '');
        }
        if (!loaded && token === this.token) {
            this.modelNote = { text: reason ? t('editor.model.savedFailedReason', { reason }) : t('editor.model.savedFailed'), kind: 'error' };
            this.invalidate('model');
        }
    }

    // Takes a model from a file the user picked or dropped, after checking its size.
    async useModelFile(file) {
        if (!file) {
            return;
        }
        if (file.size > MAX_MODEL_BYTES) {
            this.app.hud.toast(t('editor.model.tooLarge', { size: formatBytes(file.size) }), 'error');
            return;
        }
        const token = this.token;
        try {
            const bytes = await file.arrayBuffer();
            if (token === this.token) {
                await this.useModelBytes(bytes, file.name, null, true, true, token);
            }
        } catch (err) {
            this.app.hud.toast(t('editor.model.readFailed', { reason: err.message || err }), 'error', 7000);
        }
    }

    // Returns whether the model was taken.
    async useModelBytes(bytes, label, joints, dirty, select = true, token = this.token) {
        if (bytes.byteLength > MAX_MODEL_BYTES) {
            this.app.hud.toast(t('editor.model.tooLarge', { size: formatBytes(bytes.byteLength) }), 'error');
            return false;
        }
        let gltf;
        try {
            // The same checks as the match view, a self contained file of bounded size.
            gltf = await parseModel(bytes);
        } catch (err) {
            this.app.hud.toast(t('editor.model.notGltf', { reason: err.message || err }), 'error', 7000);
            return false;
        }
        if (token !== this.token) {
            return false;
        }
        let bones;
        try {
            bones = fileBoneNames(gltf);
        } catch (err) {
            this.app.hud.toast(err.message, 'error', 7000);
            return false;
        }
        this.model = { bytes, label, scene: gltf.scene, animations: gltf.animations || [], bones, joints: joints ? { ...joints } : guessJoints(bones) };
        this.customRig = null;
        this.modelNote = null;
        this.modelDirty = dirty;
        this.removeModel = false;
        if (select) {
            this.style.model = 'custom';
        }
        this.invalidate('model', 'kit', 'roster', 'celebrations');
        this.refreshPreview();
        return true;
    }

    modelMessage(text, kind = 'info') {
        const el = this.dialog.querySelector('.model-message');
        if (el) {
            el.textContent = text;
            el.dataset.kind = kind;
        }
    }

    // The frame of the editor, built once per team. Sections fill in when first shown.
    render() {
        const oldStage = this.stage;
        this.formHost = h('div', { class: 'editor-form', tabindex: '-1' });
        this.sectionLabel = h('span', { class: 'section-name' });
        this.sectionCount = h('span', { class: 'section-count' });
        const sectionBtn = h('button', { type: 'button', class: 'section-btn', title: t('editor.nav.choose') },
            this.sectionLabel, this.sectionCount, h('span', { class: 'dd-caret', 'aria-hidden': 'true' }));
        const sectionMenu = h('div', { role: 'menu', class: 'section-menu', 'aria-label': t('editor.nav.sections') });
        const fillSections = () => {
            sectionMenu.replaceChildren(...SECTIONS.map((sec, i) => menuItem(sec.label, {
                hint: sec.hint, checked: sec.id === this.section, kbd: String(i + 1), onSelect: () => this.showSection(sec.id, true),
            })));
        };
        this.sectionDropdown = new Dropdown(sectionBtn, sectionMenu, { onOpen: fillSections });
        const step = (d) => {
            const i = SECTIONS.findIndex((s) => s.id === this.section);
            this.showSection(SECTIONS[(i + d + SECTIONS.length) % SECTIONS.length].id, true);
        };
        this.prevBtn = h('button', { type: 'button', class: 'icon-btn step-btn', 'aria-label': t('editor.nav.previous'), title: t('editor.nav.previous'), onclick: () => step(-1) }, '‹');
        this.nextBtn = h('button', { type: 'button', class: 'icon-btn step-btn', 'aria-label': t('editor.nav.next'), title: t('editor.nav.next'), onclick: () => step(1) }, '›');
        this.titleShirt = h('span', { class: 'title-shirt' });
        this.titleName = h('h2', {});
        this.titleMeta = h('span', { class: 'muted small' });
        const preview = h('div', { class: 'editor-preview' },
            h('div', { class: 'preview-stage', id: 'preview-stage' }),
            h('div', { class: 'preview-caption muted small' }),
            h('div', { class: 'chips center preview-modes' },
                h('button', { type: 'button', class: 'chip-btn active', 'data-mode': 'idle', onclick: () => this.setPreviewMode('idle') }, t('editor.preview.idle')),
                h('button', { type: 'button', class: 'chip-btn', 'data-mode': 'walk', onclick: () => this.setPreviewMode('walk') }, t('editor.preview.walk')),
                h('button', { type: 'button', class: 'chip-btn', 'data-mode': 'gk', 'aria-pressed': 'false', onclick: () => this.setPreviewMode('gk') }, t('editor.preview.goalkeeper'))));
        this.saveBtn = h('button', { type: 'button', class: 'btn primary', onclick: () => this.save() }, t('editor.save'));
        this.dirtyNote = h('span', { class: 'dirty-note muted small', hidden: true }, t('editor.unsaved'));
        const actions = h('div', { class: 'editor-actions' },
            h('button', { type: 'button', class: 'btn ghost', onclick: () => this.resetDefaults() }, t('editor.resetDefaults')),
            h('span', { class: 'spacer' }),
            this.dirtyNote,
            h('button', { type: 'button', class: 'btn', onclick: () => this.close() }, t('editor.cancel')),
            this.saveBtn);
        const body = h('div', { class: 'editor' },
            h('header', { class: 'editor-head' },
                h('div', { class: 'editor-title' }, this.titleShirt, h('div', {}, this.titleName, this.titleMeta)),
                h('nav', { class: 'section-nav', 'aria-label': t('editor.nav.label') }, this.prevBtn, sectionBtn, this.nextBtn),
                h('button', { type: 'button', class: 'icon-btn', 'aria-label': t('editor.close.label'), title: t('editor.close.title'), onclick: () => this.close() }, '✕')),
            h('div', { class: 'editor-grid' }, preview, this.formHost), actions, sectionMenu);
        // Keep the preview canvas across teams, a new WebGL context each time is slow.
        if (oldStage && this.renderer) {
            body.querySelector('#preview-stage').replaceWith(oldStage);
        } else {
            this.stage = body.querySelector('#preview-stage');
        }
        this.dialog.replaceChildren(body);
        // Changes anywhere in the form update the unsaved mark.
        this.formHost.addEventListener('input', () => this.markDirty());
        this.formHost.addEventListener('change', () => this.markDirty());
        this.formHost.addEventListener('click', () => this.markDirty());
        this.updateTitle();
        this.showSection(SECTIONS.some((s) => s.id === this.section) ? this.section : 'identity');
    }

    markDirty() {
        queueMicrotask(() => {
            if (this.team && this.dirtyNote) {
                this.dirtyNote.hidden = !this.dirty;
            }
        });
    }

    updateTitle() {
        this.titleName.textContent = this.name || teamName(this.team);
        this.titleMeta.textContent = [this.team.kind === 'builtin' ? t('editor.meta.builtin') : t('editor.meta.submission'), t(`editor.format.${this.format === '5v5' ? '5v5' : '11v11'}`), this.modelName(this.style.model)].join(', ');
        this.titleShirt.replaceChildren(kitShirt({ style: this.style }, 0));
    }

    // Shows one section, building it the first time and after a change marked it stale.
    showSection(id, focus = false) {
        this.section = id;
        const i = SECTIONS.findIndex((s) => s.id === id);
        this.sectionLabel.textContent = SECTIONS[i].label;
        this.sectionCount.textContent = t('editor.nav.count', { index: i + 1, total: SECTIONS.length });
        let el = this.built.get(id);
        if (!el) {
            el = this.buildSection(id);
            this.built.set(id, el);
        }
        if (id === 'model') {
            this.syncColorModel();
        }
        if (el.parentNode !== this.formHost || this.formHost.childNodes.length !== 1) {
            this.formHost.replaceChildren(el);
            this.formHost.scrollTop = 0;
            el.classList.remove('enter');
            void el.offsetWidth;
            el.classList.add('enter');
        }
        if (focus) {
            this.formHost.focus({ preventScroll: true });
        }
    }

    // Marks sections stale, the one in view is rebuilt at once.
    invalidate(...ids) {
        if (!this.team || !this.built) {
            return;
        }
        for (const id of ids) {
            this.built.delete(id);
        }
        if (ids.includes(this.section)) {
            const top = this.formHost.scrollTop;
            const el = this.buildSection(this.section);
            this.built.set(this.section, el);
            this.formHost.replaceChildren(el);
            this.formHost.scrollTop = top;
        }
        this.updateTitle();
        this.markDirty();
    }

    buildSection(id) {
        const sec = SECTIONS.find((s) => s.id === id);
        const parts = {
            identity: () => this.identitySection(),
            kit: () => this.kitSection(),
            roster: () => this.rosterSection(),
            model: () => this.modelSection(),
            fans: () => this.fansSection(),
            celebrations: () => this.celebrationsSection(),
            sounds: () => this.soundsSection(),
            sponsors: () => this.sponsorSection(),
            export: () => this.exportSection(),
        }[id]();
        return h('section', { class: `editor-section sec-${id}`, 'aria-label': sec.label },
            h('header', { class: 'sec-head' }, h('h3', {}, sec.label), h('p', { class: 'muted small' }, sec.hint)), parts);
    }

    colorInput(label, get, set, extra = {}) {
        const input = h('input', { type: 'color', value: hex(get()), 'aria-label': label });
        input.addEventListener('input', () => {
            set(fromHex(input.value));
            // A model other than GRF's follows the kit in place, without a rebuild.
            if (!this.liveRecolor(null)) {
                this.refreshPreview();
            }
            if (extra.onInput) {
                extra.onInput();
            }
        });
        return h('label', { class: 'swatch' }, input, h('span', {}, label));
    }

    chips(list, current, onPick, extra = () => null) {
        const box = h('div', { class: 'chips', role: 'radiogroup' });
        box.append(...list.map((v) => h('button', {
            type: 'button', role: 'radio', class: `chip-btn${v === current ? ' active' : ''}`, 'aria-checked': v === current ? 'true' : 'false', 'data-value': v,
            onclick: () => {
                for (const b of box.children) {
                    const on = b.dataset.value === v;
                    b.classList.toggle('active', on);
                    b.setAttribute('aria-checked', on ? 'true' : 'false');
                }
                onPick(v);
            },
        }, extra(v), LABELS[v] || v)));
        return box;
    }

    identitySection() {
        const s = this.style;
        const nameInput = h('input', { type: 'text', value: this.name, maxlength: '60' });
        nameInput.addEventListener('input', () => {
            this.name = nameInput.value;
            this.updateTitle();
        });
        const format = h('select', {}, Object.keys(FORMATS).map((f) => h('option', { value: f, selected: f === this.format }, t(`editor.format.${f === '5v5' ? '5v5' : '11v11'}`))));
        const control = controlForm(this.format, controlFromValue(this.control));
        const fillControl = () => {
            control.setFormat(this.format);
            this.control = control.value;
        };
        control.addEventListener('change', () => {
            this.control = control.value;
        });
        control.addEventListener('input', () => {
            this.control = control.value;
        });
        format.addEventListener('change', () => {
            this.format = format.value;
            fillControl();
            this.fitRoster();
            this.previewIndex = Math.min(this.previewIndex, FORMATS[this.format] - 1);
            this.invalidate('roster');
            this.refreshPreview();
        });
        const badge = h('input', { type: 'text', value: s.badge, maxlength: '8', placeholder: t('editor.identity.badgePlaceholder'), class: 'badge-input' });
        badge.addEventListener('input', () => {
            s.badge = Array.from(badge.value).slice(0, 3).join('');
            this.updateTitle();
            this.refreshPreview();
        });
        return h('div', { class: 'sec-body' },
            surprisePanel(this),
            h('div', { class: 'grid2' },
                h('label', { class: 'field' }, t('editor.identity.name'), nameInput),
                h('label', { class: 'field' }, t('editor.identity.format'), format)),
            this.team.kind === 'builtin' ? null : h('div', {}, control),
            h('label', { class: 'field' }, t('editor.identity.badge'), badge),
            h('p', { class: 'muted small' }, this.team.kind === 'builtin'
                ? t('editor.identity.builtinNote')
                : t('editor.identity.formatNote')));
    }

    kitSection() {
        const s = this.style;
        const patternIcon = (p) => h('span', { class: `pattern-icon p-${p}`, style: `--a:${css(s.kit.primary)};--b:${css(s.kit.secondary)}` });
        const kitChanged = () => {
            for (const el of this.formHost.querySelectorAll('.pattern-icon')) {
                el.style.setProperty('--a', css(s.kit.primary));
                el.style.setProperty('--b', css(s.kit.secondary));
            }
            // The swatches of the model show the kit colors they follow.
            this.built.delete('model');
            if (this.crowdFollowsKit) {
                s.crowd.colors = [s.kit.primary.slice(), s.kit.secondary.slice()];
                this.built.delete('fans');
            }
            this.updateTitle();
        };
        const color = (label, group, part) => this.colorInput(label, () => s[group][part], (c) => {
            s[group][part] = c;
        }, { onInput: kitChanged });
        const lockNote = this.grf ? null : h('p', { class: 'note' },
            t('editor.kit.lockNote', { model: this.modelName(s.model) }));
        return h('div', { class: 'sec-body' },
            surprisePanel(this),
            lockNote,
            h('h4', {}, t('editor.kit.pattern')),
            this.chips(PATTERNS, s.kit.pattern, (v) => {
                s.kit.pattern = v;
                this.updateTitle();
                this.refreshPreview();
            }, patternIcon),
            h('h4', {}, t('editor.kit.kit')),
            h('div', { class: 'swatches' },
                color(t('editor.kit.shirt'), 'kit', 'primary'), color(t('editor.kit.trimPattern'), 'kit', 'secondary'),
                color(t('editor.kit.shorts'), 'kit', 'shorts'), color(t('editor.kit.socks'), 'kit', 'socks')),
            h('h4', {}, t('editor.kit.goalkeeper')),
            h('div', { class: 'swatches' },
                color(t('editor.kit.shirt'), 'goalkeeper', 'primary'), color(t('editor.kit.trim'), 'goalkeeper', 'secondary'),
                color(t('editor.kit.shorts'), 'goalkeeper', 'shorts'), color(t('editor.kit.socks'), 'goalkeeper', 'socks')),
            h('div', { class: 'field-row' }, h('span', { class: 'field-label' }, t('editor.kit.numbers')), this.chips(NUMBER_COLORS, s.number, (v) => {
                s.number = v;
                this.refreshPreview();
            })),
            h('section', { class: 'art' },
                h('h4', {}, t('editor.kit.art')),
                h('p', { class: 'muted small' }, t('editor.kit.artNote')),
                h('div', { class: 'slots two' }, this.slotTile('shirt-front', t('editor.kit.front'), 'shirt'), this.slotTile('shirt-back', t('editor.kit.back'), 'shirt'))));
    }

    rosterSection() {
        const modelOptions = [['team', t('editor.roster.teamModel', { model: this.modelName(this.style.model) })], ...this.modelOptions()];
        const moves = [...celebrationNames(), ...this.lastClips.map((c) => `clip:${c}`), ...clipMoves(this)];
        const select = (list, value, onChange, label, disabled = false) => {
            const el = h('select', { 'aria-label': label, disabled }, list.map(([v, text]) => h('option', { value: v, selected: v === value }, text)));
            el.addEventListener('change', () => onChange(el.value));
            return el;
        };
        const named = (list) => list.map((v) => [v, LABELS[v] || v]);
        const cards = this.style.players.map((p, i) => {
            const name = h('input', { type: 'text', value: p.name, maxlength: '24', placeholder: i === 0 ? t('editor.roster.goalkeeper') : t('editor.roster.player', { n: i + 1 }), 'aria-label': t('editor.roster.nameOf', { n: i + 1 }) });
            name.addEventListener('input', () => {
                p.name = name.value.slice(0, 24);
            });
            const number = h('input', { type: 'number', min: '0', max: '99', value: String(p.number), class: 'num', 'aria-label': t('editor.roster.numberOf', { n: i + 1 }) });
            const badge = h('span', { class: 'player-number' }, String(p.number));
            number.addEventListener('change', () => {
                const n = Math.max(0, Math.min(99, Number.parseInt(number.value, 10) || 0));
                p.number = n;
                number.value = String(n);
                badge.textContent = String(n);
                this.focusPlayer(i);
                this.refreshPreview();
            });
            const look = (key) => (v) => {
                p[key] = v;
                this.focusPlayer(i);
                this.refreshPreview();
            };
            const grfOnly = this.playerModel(i) !== 'grf';
            const lookSelects = [
                h('label', { class: 'mini' }, t('editor.roster.skin'), select(named(PLAYER_SKINS), p.skin, look('skin'), t('editor.roster.skin'), grfOnly)),
                h('label', { class: 'mini' }, t('editor.roster.hair'), select(named(PLAYER_HAIRS), p.hair, look('hair'), t('editor.roster.hair'), grfOnly)),
                h('label', { class: 'mini' }, t('editor.roster.hairColor'), select(named(HAIR_COLORS_NAMED), p.hair_color, look('hair_color'), t('editor.roster.hairColor'), grfOnly)),
            ];
            const modelSelect = select(modelOptions, p.model || 'team', (v) => {
                p.model = v;
                const off = this.playerModel(i) !== 'grf';
                for (const sel of lookSelects.map((l) => l.querySelector('select'))) {
                    sel.disabled = off;
                }
                this.built.delete('model');
                this.focusPlayer(i);
                this.refreshPreview();
            }, t('editor.roster.model'));
            const celebration = select([['team', t('editor.roster.teamDefault')], ...moves.map((m) => [m, clipMoveLabel(this, m) || celebrationLabel(m)])], p.celebration || 'team', (v) => {
                p.celebration = v;
                this.focusPlayer(i);
                if (v !== 'team') {
                    this.playCelebration(v);
                }
            }, t('editor.roster.celebration'));
            const card = h('li', {
                class: `player-card${i === this.previewIndex && !this.previewGk ? ' focused' : ''}${i === 0 && this.previewGk ? ' focused' : ''}`,
                'data-index': String(i),
            },
            h('div', { class: 'player-head' },
                badge,
                h('span', { class: 'player-role' }, i === 0 ? t('editor.roster.goalkeeper') : t('editor.roster.outfield', { n: i })),
                h('button', { type: 'button', class: 'link small', onclick: () => this.focusPlayer(i) }, t('editor.roster.preview'))),
            h('div', { class: 'player-fields' },
                h('label', { class: 'mini grow' }, t('editor.roster.name'), name),
                h('label', { class: 'mini' }, t('editor.roster.number'), number)),
            h('div', { class: 'player-looks' }, ...lookSelects,
                h('label', { class: 'mini' }, t('editor.roster.model'), modelSelect),
                h('label', { class: 'mini' }, t('editor.roster.celebration'), celebration)));
            card.addEventListener('focusin', () => this.focusPlayer(i, false));
            return card;
        });
        return h('div', { class: 'sec-body' },
            h('p', { class: 'muted small' }, t('editor.roster.note')),
            h('ul', { class: 'player-cards' }, cards));
    }

    // Shows a roster player in the preview, redrawn when the player or a look changed.
    focusPlayer(i, changed = true) {
        const gk = i === 0;
        const moved = this.previewIndex !== i || this.previewGk !== gk;
        this.previewIndex = i;
        this.previewGk = gk;
        for (const el of this.formHost.querySelectorAll('.player-card')) {
            el.classList.toggle('focused', Number(el.dataset.index) === i);
        }
        this.syncPreviewModes();
        if (moved || changed) {
            this.refreshPreview();
        }
    }

    setPreviewMode(mode) {
        if (mode === 'gk') {
            this.previewGk = !this.previewGk;
            if (!this.previewGk && this.previewIndex === 0) {
                this.previewIndex = Math.min(9, FORMATS[this.format] - 1);
            }
            if (this.section === 'model') {
                this.syncColorModel();
            }
            this.refreshPreview();
        } else {
            this.walk = mode === 'walk';
            this.playing = null;
        }
        this.syncPreviewModes();
    }

    syncPreviewModes() {
        for (const b of this.dialog.querySelectorAll('.preview-modes .chip-btn')) {
            const m = b.dataset.mode;
            const on = m === 'gk' ? this.previewGk : (m === 'walk') === this.walk && !this.playing;
            b.classList.toggle('active', on);
            if (m === 'gk') {
                b.setAttribute('aria-pressed', on ? 'true' : 'false');
            }
        }
        const cap = this.dialog.querySelector('.preview-caption');
        if (cap && this.team) {
            const i = this.previewGk ? 0 : this.previewIndex;
            const p = this.style.players[i];
            const values = {
                number: p ? p.number : '',
                name: p ? p.name || (i === 0 ? t('editor.roster.goalkeeper') : t('editor.roster.player', { n: i + 1 })) : '',
                model: this.modelName(this.playerModel(i)),
                move: this.playing ? clipMoveLabel(this, this.playing.name) || celebrationLabel(this.playing.name) : '',
            };
            cap.textContent = t(values.move ? 'editor.preview.captionMove' : 'editor.preview.caption', values);
        }
    }

    slotTile(slot, label, kind) {
        const has = this.images.has(slot);
        const thumb = this.thumbs.get(slot);
        return h('div', { class: `slot ${kind}`, 'data-slot': slot },
            h('div', { class: 'slot-thumb', style: thumb ? `background-image:url(${thumb})` : '' }, has ? null : h('span', { class: 'muted small' }, t('editor.slot.empty'))),
            h('div', { class: 'slot-label' }, label),
            h('div', { class: 'row' },
                h('button', { type: 'button', class: 'btn small', onclick: () => this.paint(slot, label, kind) }, has ? t('editor.slot.edit') : t('editor.slot.create')),
                has ? h('button', { type: 'button', class: 'btn small ghost danger', onclick: () => this.removeSlot(slot) }, t('editor.remove')) : null));
    }

    // Redraws the artwork tiles where they are shown, after a drawing saved or loaded.
    updateSlots() {
        for (const tile of this.formHost.querySelectorAll('.slot[data-slot]')) {
            const slot = tile.dataset.slot;
            const kind = tile.classList.contains('sponsor') ? 'sponsor' : 'shirt';
            const label = tile.querySelector('.slot-label').textContent;
            tile.replaceWith(this.slotTile(slot, label, kind));
        }
        this.built.delete(this.section === 'kit' ? 'sponsors' : 'kit');
        if (this.section !== 'sponsors') {
            this.built.delete('sponsors');
        }
    }

    sponsorSection() {
        return h('div', { class: 'sec-body' },
            h('p', { class: 'muted small' }, t('editor.sponsors.note')),
            h('div', { class: 'slots sponsors' }, SPONSOR_SLOTS.map((s, i) => this.slotTile(s, t('editor.sponsors.slot', { n: i + 1 }), 'sponsor'))));
    }

    exportSection() {
        return h('div', { class: 'sec-body' },
            h('a', { class: 'btn primary', href: api.exportUrl(this.team.id), download: `${this.team.name || 'team'}.zip` }, t('editor.export.button')),
            h('p', { class: 'muted small' }, t('editor.export.note')),
            this.team.kind !== 'builtin' ? h('button', { class: 'btn', type: 'button', onclick: (e) => this.duplicate(e.currentTarget) }, t('editor.export.duplicate')) : null,
            this.team.kind !== 'builtin' ? h('p', { class: 'muted small' }, t('editor.export.duplicateNote')) : null);
    }

    // Copies the saved team as a new team of the registry, which then changes on its own.
    async duplicate(button) {
        button.disabled = true;
        try {
            const copy = await api.duplicateTeam(this.team.id);
            this.app.teamsChanged();
            this.app.hud.toast(t('editor.export.duplicated', { name: copy.name }));
        } catch (err) {
            this.app.hud.toast(err.message, 'error', 7000);
        } finally {
            button.disabled = false;
        }
    }

    // A guide for the shirt painter, the shirt region of the kit mask, front or back.
    shirtGuide(slot) {
        const mask = this.app.assets.grf && this.app.assets.grf.mask;
        if (!mask) {
            return null;
        }
        const canvas = document.createElement('canvas');
        canvas.width = SHIRT_SIZE.width;
        canvas.height = SHIRT_SIZE.height;
        const ctx = canvas.getContext('2d');
        const sx = slot === 'shirt-back' ? mask.width / 2 : 0;
        const full = document.createElement('canvas');
        full.width = mask.width;
        full.height = mask.height;
        const img = new ImageData(new Uint8ClampedArray(mask.data), mask.width, mask.height);
        for (let i = 0; i < img.data.length; i += 4) {
            const r = img.data[i];
            img.data[i] = 60;
            img.data[i + 1] = 64;
            img.data[i + 2] = 67;
            img.data[i + 3] = r > 0 ? 255 : 0;
        }
        full.getContext('2d').putImageData(img, 0, 0);
        ctx.drawImage(full, sx, 0, mask.width / 2, mask.height * 0.41, 0, 0, canvas.width, canvas.height);
        return canvas.toDataURL();
    }

    async paint(slot, label, kind) {
        // The team is fixed when the painter opens, so its save lands on this team whatever opens next.
        const token = this.token;
        const team = this.team;
        let json = null;
        if (this.images.has(`${slot}-edit`)) {
            try {
                json = await (await api.image(team.id, `${slot}-edit`)).text();
            } catch {
                json = null;
            }
        }
        if (token !== this.token) {
            return;
        }
        const size = kind === 'sponsor' ? SPONSOR_SIZE : SHIRT_SIZE;
        // The slot names the texts, front, back or the sponsor's number.
        const which = kind === 'sponsor' ? 'sponsor' : slot === 'shirt-back' ? 'back' : 'front';
        const n = SPONSOR_SLOTS.indexOf(slot) + 1;
        this.painter.open({
            title: t(`editor.paint.title.${which}`, { team: teamName(team), n }),
            width: size.width,
            height: size.height,
            json,
            guide: kind === 'shirt' ? this.shirtGuide(slot) : null,
            note: kind === 'shirt'
                ? t('editor.paint.shirtNote')
                : t('editor.paint.sponsorNote'),
            onSave: async (png, doc) => {
                await api.putImage(team.id, slot, png, 'image/png');
                await api.putImage(team.id, `${slot}-edit`, doc, 'application/json');
                this.app.hud.toast(t(`editor.paint.saved.${which}`, { n }));
                this.app.teamsChanged();
                if (token !== this.token) {
                    return;
                }
                this.images.add(slot);
                this.images.add(`${slot}-edit`);
                if (this.thumbs.has(slot)) {
                    URL.revokeObjectURL(this.thumbs.get(slot));
                }
                this.thumbs.set(slot, URL.createObjectURL(png));
                this.loadArt(token);
            },
        }).catch((err) => this.app.hud.toast(t('editor.paint.openFailed', { reason: err.message || err }), 'error'));
    }

    async removeSlot(slot) {
        if (!confirm(t('editor.slot.removeConfirm'))) {
            return;
        }
        const token = this.token;
        const team = this.team;
        const hadEdit = this.images.has(`${slot}-edit`);
        try {
            await api.deleteImage(team.id, slot);
            if (hadEdit) {
                await api.deleteImage(team.id, `${slot}-edit`).catch(() => {});
            }
            this.app.teamsChanged();
            if (token !== this.token) {
                return;
            }
            this.images.delete(slot);
            this.images.delete(`${slot}-edit`);
            if (this.thumbs.has(slot)) {
                URL.revokeObjectURL(this.thumbs.get(slot));
                this.thumbs.delete(slot);
            }
            this.updateSlots();
            this.loadArt(token);
        } catch (err) {
            this.app.hud.toast(err.message, 'error');
        }
    }

    modelSection() {
        const s = this.style;
        const pick = h('select', { 'aria-label': t('editor.model.team') },
            h('option', { value: 'grf', selected: s.model === 'grf' }, t('editor.model.grf')),
            this.shipped.length ? h('optgroup', { label: t('editor.model.shipped') }, this.shipped.map((m) =>
                h('option', { value: m.id, selected: s.model === m.id }, m.name || m.id))) : null,
            h('option', { value: 'custom', selected: s.model === 'custom' }, this.model ? t('editor.model.ownNamed', { label: this.model.label }) : t('editor.model.ownUpload')));
        pick.addEventListener('change', () => {
            s.model = pick.value;
            this.colorModel = null;
            this.invalidate('model', 'kit', 'roster', 'celebrations');
            this.refreshPreview();
        });
        const parts = [h('label', { class: 'field' }, t('editor.model.team'), pick)];
        const entry = this.shipped.find((m) => m.id === s.model);
        if (entry && (entry.author || entry.license)) {
            parts.push(h('p', { class: 'muted small' }, [entry.author ? t('editor.model.by', { author: entry.author }) : null, entry.license].filter(Boolean).join(', ')));
        }
        if (s.model === 'custom') {
            const file = h('input', { type: 'file', accept: '.glb,model/gltf-binary', hidden: true });
            file.addEventListener('change', () => {
                const f = file.files[0];
                file.value = '';
                this.useModelFile(f);
            });
            const drop = h('div', { class: 'dropzone small' },
                h('p', {}, t('editor.model.drop')),
                h('button', { type: 'button', class: 'btn', onclick: () => file.click() }, t('editor.model.choose')), file);
            drop.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.stopPropagation();
                drop.classList.add('over');
            });
            drop.addEventListener('dragleave', () => drop.classList.remove('over'));
            drop.addEventListener('drop', (e) => {
                e.preventDefault();
                e.stopPropagation();
                drop.classList.remove('over');
                this.useModelFile(e.dataTransfer.files[0]);
            });
            const note = this.modelNote;
            parts.push(drop, h('div', { class: 'model-message', 'data-kind': note ? note.kind : 'info' },
                note ? note.text
                    : this.model ? t('editor.model.summary', { label: this.model.label, bones: this.model.bones.length, size: formatBytes(this.model.bytes.byteLength) }) : t('editor.model.none')));
            if (this.model) {
                parts.push(h('details', { class: 'joints-box' }, h('summary', {}, t('editor.joints.summary')), this.jointTable()));
            }
            if (this.team.model || this.model) {
                parts.push(h('button', {
                    type: 'button', class: 'btn ghost danger',
                    onclick: () => {
                        this.model = null;
                        this.customRig = null;
                        this.modelNote = null;
                        this.removeModel = true;
                        this.modelDirty = false;
                        s.model = 'grf';
                        this.invalidate('model', 'kit', 'roster', 'celebrations');
                        this.refreshPreview();
                    },
                }, t('editor.model.remove')));
            }
        }
        parts.push(this.colorsBlock());
        const wrap = h('div', { class: 'sec-body' }, parts);
        queueMicrotask(() => enhanceSelect(pick, { label: t('editor.model.team'), className: 'wide' }));
        return wrap;
    }

    // The models whose colors the team may change, the team's and those of roster players.
    recolorable() {
        const used = [this.style.model, ...this.style.players.map((p, i) => this.playerModel(i))];
        return [...new Set(used)].filter((m) => m !== 'grf' && (m !== 'custom' || this.model));
    }

    // The colors present in a model as swatches. Each follows a part of the kit, shirt, trim,
    // shorts or socks, or keeps the model's own color, and the team may give any of them a color
    // of its own. A pair of a color to itself keeps that color where the kit would replace it.
    colorsBlock() {
        const box = h('div', { class: 'colors-block' }, h('h4', {}, t('editor.colors.heading')));
        const models = this.recolorable();
        this.swatchUpdates = [];
        if (!models.length) {
            box.append(h('p', { class: 'muted small' }, this.style.model === 'custom'
                ? t('editor.colors.upload')
                : t('editor.colors.grf')));
            return box;
        }
        if (!models.includes(this.colorModel)) {
            const shown = this.playerModel(this.previewGk ? 0 : this.previewIndex);
            this.colorModel = models.includes(shown) ? shown : models[0];
        }
        const key = this.colorModel;
        const wearers = this.style.players.filter((p, i) => this.playerModel(i) === key).length;
        const worn = wearers === this.style.players.length ? t('editor.colors.wornAll') : t('editor.colors.worn', { count: wearers });
        const whichLabel = t('editor.colors.which');
        if (models.length > 1) {
            const which = h('select', { 'aria-label': whichLabel }, models.map((m) => h('option', { value: m, selected: m === key }, this.modelName(m))));
            which.addEventListener('change', () => {
                this.colorModel = which.value;
                this.invalidate('model');
                // The rebuilt list keeps the focus on its own select.
                const again = [...this.formHost.querySelectorAll('select')].find((el) => el.getAttribute('aria-label') === whichLabel);
                if (again) {
                    again.focus();
                }
            });
            box.append(h('label', { class: 'field' }, t('editor.colors.of'), which), h('p', { class: 'muted small' }, worn));
        } else {
            box.append(h('p', { class: 'small' }, t('editor.colors.single', { model: this.modelName(key), worn })));
        }
        this.showColorModel();
        const pairsOf = () => this.style.colors[key] || (this.style.colors[key] = {});
        const follow = h('input', { type: 'checkbox' });
        const resetAll = h('button', { type: 'button', class: 'btn small ghost' }, t('editor.colors.resetAll'));
        const tools = h('div', { class: 'row colors-tools' },
            h('label', { class: 'check' }, follow, ` ${t('editor.colors.follow')}`), resetAll);
        // The shirt numbers ride the back of the model, and a team turns them off on a model where
        // they do not fit.
        const numbered = h('input', { type: 'checkbox', checked: !(this.style.hidden_numbers || []).includes(key) });
        numbered.addEventListener('change', () => {
            const hidden = new Set(this.style.hidden_numbers || []);
            if (numbered.checked) {
                hidden.delete(key);
            } else {
                hidden.add(key);
            }
            this.style.hidden_numbers = [...hidden];
            this.refreshPreview();
        });
        tools.append(h('label', { class: 'check' }, numbered, ` ${t('editor.colors.numbers')}`));
        const host = h('div', { class: 'model-colors', role: 'list', 'aria-label': t('editor.colors.listLabel', { model: this.modelName(key) }) },
            h('p', { class: 'muted small' }, t('editor.colors.reading')));
        box.append(tools, host, h('p', { class: 'muted small' }, t('editor.colors.note')));
        let colors = [];
        const syncTools = () => {
            const roles = colors.filter((c) => c.role);
            const pairs = pairsOf();
            follow.checked = roles.some((c) => pairs[c.hex] !== c.hex);
            follow.disabled = !roles.length;
            resetAll.disabled = !Object.keys(pairs).length;
        };
        const changed = () => {
            for (const update of this.swatchUpdates) {
                update();
            }
            syncTools();
            this.liveRecolor(key);
            this.markDirty();
        };
        follow.addEventListener('change', () => {
            const pairs = pairsOf();
            for (const c of colors.filter((x) => x.role)) {
                if (follow.checked && pairs[c.hex] === c.hex) {
                    delete pairs[c.hex];
                } else if (!follow.checked && !(c.hex in pairs)) {
                    pairs[c.hex] = c.hex;
                }
            }
            changed();
        });
        resetAll.addEventListener('click', () => {
            this.style.colors[key] = {};
            changed();
        });
        const token = this.token;
        this.rigFor(key).then((rig) => {
            if (token !== this.token || !host.isConnected) {
                return;
            }
            const list = modelColorsOf(rig);
            if (!list) {
                host.replaceChildren(h('p', { class: 'muted small' }, rig ? t('editor.colors.unreadable') : t('editor.colors.notLoaded')));
                return;
            }
            colors = list;
            this.lastClips = clipsOf(rig);
            host.replaceChildren(...colors.map((c, i) => this.colorSwatch(key, c, i, changed)));
            syncTools();
        });
        return box;
    }

    // Lists the colors of the model in the preview when the team may change them, else moves
    // the preview to a player who wears the model listed, so the two always agree.
    syncColorModel() {
        const shown = this.playerModel(this.previewGk ? 0 : this.previewIndex);
        if (shown !== this.colorModel && this.recolorable().includes(shown)) {
            this.colorModel = shown;
            if (this.section === 'model' && this.built.has('model')) {
                this.invalidate('model');
            } else {
                this.built.delete('model');
            }
        } else {
            this.showColorModel();
        }
    }

    // Moves the preview to a player who wears the model whose colors are listed.
    showColorModel() {
        const key = this.colorModel;
        if (!key || this.playerModel(this.previewGk ? 0 : this.previewIndex) === key) {
            return;
        }
        const wearers = this.style.players.map((p, i) => i).filter((i) => this.playerModel(i) === key);
        if (wearers.length) {
            const i = wearers.find((n) => n > 0) ?? wearers[0];
            this.previewIndex = i;
            this.previewGk = i === 0;
            this.syncPreviewModes();
            this.refreshPreview();
        }
    }

    // Redraws the colors of the preview in place, at most once a frame, after a change to the
    // colors of model key or, with key null, to the kit. False when the preview has to be
    // rebuilt instead, as GRF's player and an uploaded model with kit materials are.
    liveRecolor(key) {
        const model = this.previewModel;
        if (key && key !== model) {
            // The preview shows another model, it changes when that model is shown.
            return true;
        }
        if (!this.players || !model || model === 'grf' || model === 'custom') {
            return false;
        }
        if (!this.recolorFrame) {
            this.recolorFrame = requestAnimationFrame(() => {
                this.recolorFrame = 0;
                if (this.players && this.previewModel === model) {
                    this.players.setColors(0, model, this.flashPairs(model));
                }
            });
        }
        this.markDirty();
        return true;
    }

    // The team's pairs of a model, with the color being shown blinking over them.
    flashPairs(model) {
        const pairs = { ...(this.style.colors[model] || {}) };
        const f = this.flash;
        if (f && f.model === model && Math.floor((performance.now() - f.start) / 150) % 2 === 0) {
            pairs[f.hex] = FLASH;
        }
        return pairs;
    }

    // Blinks one color of the model on the preview, so the parts it covers show.
    flashColor(model, color) {
        if (this.previewModel !== model) {
            return;
        }
        this.flash = { model, hex: color, start: performance.now() };
        clearInterval(this.flashTimer);
        this.flashTimer = setInterval(() => {
            if (!this.flash || performance.now() - this.flash.start > FLASH_MS) {
                clearInterval(this.flashTimer);
                this.flash = null;
            }
            this.liveRecolor(model);
        }, 75);
        this.liveRecolor(model);
    }

    stopFlash() {
        clearInterval(this.flashTimer);
        this.flash = null;
    }

    colorSwatch(key, c, i, changed) {
        const pairsOf = () => this.style.colors[key] || (this.style.colors[key] = {});
        const name = i < 2 ? t('editor.colors.main', { n: i + 1 }) : t('editor.colors.percent', { n: Math.max(1, Math.round(c.weight * 100)) });
        const input = h('input', { type: 'color', value: c.hex });
        const state = h('span', { class: 'color-state small' });
        const reset = h('button', { type: 'button', class: 'link small' }, t('editor.colors.reset'));
        const original = h('span', { class: 'orig-chip', style: `background:${c.hex}`, title: t('editor.colors.original', { hex: c.hex }) });
        const row = h('div', { class: `model-color${i < 2 ? ' main' : ''}`, role: 'listitem' },
            h('label', { class: 'swatch' }, input, h('span', {}, name)),
            h('span', { class: 'color-meta' }, original, state, reset));
        // The color shown is the team's own, else the kit's, else the model's.
        const update = () => {
            const own = pairsOf()[c.hex];
            const follows = !!c.role && own === undefined;
            const custom = own !== undefined && own !== c.hex;
            const shown = custom ? own : follows ? hex(this.style.kit[ROLE_KIT[c.role]]) : c.hex;
            if (document.activeElement !== input) {
                input.value = shown;
            }
            let text = c.role ? t('editor.colors.state.off') : t('editor.colors.state.model');
            if (custom) {
                text = t('editor.colors.state.custom');
            } else if (follows) {
                text = t('editor.colors.state.kit', { part: ROLE_LABELS[c.role] });
            }
            state.textContent = text;
            row.dataset.state = custom ? 'custom' : follows ? 'kit' : 'model';
            reset.hidden = own === undefined;
            reset.textContent = c.role ? t('editor.colors.resetKit') : t('editor.colors.reset');
            input.setAttribute('aria-label', t('editor.colors.swatchLabel', { name, state: text, hex: c.hex }));
        };
        input.addEventListener('input', () => {
            const map = pairsOf();
            if (!(c.hex in map) && Object.keys(map).length >= MAX_RECOLORS) {
                this.app.hud.toast(t('editor.colors.max', { max: MAX_RECOLORS }), 'error');
                update();
                return;
            }
            map[c.hex] = input.value.toLowerCase();
            this.stopFlash();
            changed();
        });
        input.addEventListener('focus', () => this.flashColor(key, c.hex));
        reset.addEventListener('click', () => {
            delete pairsOf()[c.hex];
            changed();
            this.flashColor(key, c.hex);
        });
        row.addEventListener('pointerenter', () => {
            if (document.activeElement !== input) {
                this.flashColor(key, c.hex);
            }
        });
        update();
        this.swatchUpdates.push(update);
        return row;
    }

    jointTable() {
        const joints = this.model.joints;
        const rows = NODE_NAMES.map((node) => {
            const select = h('select', {},
                h('option', { value: '' }, node === 'player' ? t('editor.joints.root') : t('editor.joints.unmapped')),
                this.model.bones.map((b) => h('option', { value: b, selected: joints[node] === b }, b)));
            select.addEventListener('change', () => {
                if (select.value) {
                    joints[node] = select.value;
                } else {
                    delete joints[node];
                }
                this.modelDirty = true;
                this.customRig = null;
                const req = select.closest('tr').querySelector('.req');
                if (node === 'body' && req) {
                    req.textContent = ` ${joints.body ? t('editor.joints.required') : t('editor.joints.requiredPelvis')}`;
                }
                this.refreshPreview();
            });
            return h('tr', {}, h('td', {}, t(`editor.joints.node.${node}`), node === 'body' ? h('span', { class: 'req' }, ` ${joints.body ? t('editor.joints.required') : t('editor.joints.requiredPelvis')}`) : null), h('td', {}, select));
        });
        return h('div', { class: 'joints' },
            h('p', { class: 'muted small' }, t('editor.joints.note')),
            h('table', {}, h('tbody', {}, rows)));
    }

    fansSection() {
        const s = this.style;
        const strip = h('canvas', { class: 'stands', width: '640', height: '96', 'aria-label': t('editor.fans.standsLabel'), role: 'img' });
        const list = h('div', { class: 'fan-colors' });
        const status = h('p', { class: 'muted small' });
        // The canvas takes the width it shows at, so the fans keep their shape.
        const draw = () => {
            const w = Math.round(strip.clientWidth);
            if (w && strip.width !== w) {
                strip.width = w;
            }
            this.paintStands(strip, s.crowd.colors);
        };
        setTimeout(draw, 0);
        const fill = () => {
            const colors = s.crowd.colors;
            list.replaceChildren(...colors.map((c, i) => {
                const input = h('input', { type: 'color', value: hex(c), 'aria-label': t('editor.fans.colorLabel', { n: i + 1 }) });
                input.addEventListener('input', () => {
                    colors[i] = fromHex(input.value);
                    this.crowdFollowsKit = false;
                    status.textContent = t('editor.fans.own');
                    draw();
                });
                return h('div', { class: 'fan-color' },
                    h('label', { class: 'swatch' }, input, h('span', {}, t('editor.fans.color', { n: i + 1 }))),
                    colors.length > 1 ? h('button', {
                        type: 'button', class: 'link small danger', 'aria-label': t('editor.fans.removeLabel', { n: i + 1 }),
                        onclick: () => {
                            colors.splice(i, 1);
                            this.crowdFollowsKit = false;
                            fill();
                            this.markDirty();
                        },
                    }, t('editor.remove')) : null);
            }), ...(colors.length < 4 ? [h('button', {
                type: 'button', class: 'btn small add-color',
                onclick: () => {
                    colors.push(colors[colors.length - 1].slice());
                    this.crowdFollowsKit = false;
                    fill();
                    this.markDirty();
                },
            }, t('editor.fans.add'))] : []));
            status.textContent = this.crowdFollowsKit ? t('editor.fans.followsKit') : t('editor.fans.own');
            draw();
        };
        fill();
        return h('div', { class: 'sec-body' },
            h('p', { class: 'muted small' }, t('editor.fans.note')),
            strip, list, status,
            h('button', {
                type: 'button', class: 'btn ghost',
                onclick: () => {
                    s.crowd.colors = [s.kit.primary.slice(), s.kit.secondary.slice()];
                    this.crowdFollowsKit = true;
                    this.invalidate('fans');
                },
            }, t('editor.fans.useKit')));
    }

    // A strip of stands with seated fans in the given colors, a rough sketch of the crowd.
    paintStands(canvas, colors) {
        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const ht = canvas.height;
        const g = ctx.createLinearGradient(0, 0, 0, ht);
        g.addColorStop(0, '#1c1d20');
        g.addColorStop(1, '#3a3d42');
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, w, ht);
        let seed = 7;
        const rnd = () => {
            seed = (seed * 16807) % 2147483647;
            return seed / 2147483647;
        };
        const skins = ['#f3d2b8', '#d39e74', '#b47a50', '#8d5a36', '#5a341f'];
        const rows = 4;
        const rowH = ht / rows;
        for (let r = 0; r < rows; r++) {
            const y = (r + 1) * rowH;
            ctx.fillStyle = 'rgba(255,255,255,0.06)';
            ctx.fillRect(0, y - 3, w, 3);
            const step = 16;
            for (let x = (r % 2) * 8 + 4; x < w; x += step) {
                const c = colors[Math.floor(rnd() * colors.length)] || [200, 200, 200];
                const scale = 0.8 + r * 0.08;
                ctx.fillStyle = css(c);
                ctx.fillRect(x - 5 * scale, y - 15 * scale, 10 * scale, 12 * scale);
                ctx.fillStyle = skins[Math.floor(rnd() * skins.length)];
                ctx.beginPath();
                ctx.arc(x, y - 19 * scale, 4 * scale, 0, Math.PI * 2);
                ctx.fill();
                if (rnd() < 0.18) {
                    // A raised scarf in the second color.
                    ctx.fillStyle = css(colors[(colors.indexOf(c) + 1) % colors.length] || c);
                    ctx.fillRect(x + 4 * scale, y - 30 * scale, 3 * scale, 14 * scale);
                }
            }
        }
    }

    celebrationsSection() {
        const s = this.style;
        const host = h('div', { class: 'moves' });
        const fill = () => {
            const names = celebrationNames();
            const clips = (this.lastClips || []).map((c) => `clip:${c}`);
            const all = [...names, ...clips, ...clipMoves(this)];
            if (!all.length) {
                host.replaceChildren(h('p', { class: 'muted small' }, t('editor.celebrations.loading')));
                return;
            }
            host.replaceChildren(...all.map((name) => {
                const id = `cel-${name.replace(/[^a-z0-9]+/gi, '-')}`;
                const box = h('input', { type: 'checkbox', id, checked: s.celebrations.includes(name) });
                box.addEventListener('change', () => {
                    if (box.checked && !s.celebrations.includes(name)) {
                        if (s.celebrations.length >= 32) {
                            box.checked = false;
                            this.app.hud.toast(t('editor.celebrations.max'), 'error');
                            return;
                        }
                        s.celebrations.push(name);
                    } else if (!box.checked) {
                        s.celebrations = s.celebrations.filter((n) => n !== name);
                    }
                    summary.textContent = summaryText();
                });
                const own = clipMoveLabel(this, name);
                const label = own || celebrationLabel(name);
                const hint = own ? ` ${t('editor.celebrations.teamClip')}` : name.startsWith('clip:') ? ` ${t('editor.celebrations.modelClip')}` : null;
                return h('div', { class: `move${name.startsWith('clip:') || own ? ' clip' : ''}` },
                    box,
                    h('label', { for: id }, label, hint ? h('span', { class: 'muted small' }, hint) : null),
                    h('button', { type: 'button', class: 'btn small ghost', 'aria-label': t('editor.celebrations.playLabel', { name: label }), onclick: () => this.playCelebration(name) }, icon('play'), t('editor.play')));
            }));
        };
        const summaryText = () => (s.celebrations.length
            ? t('editor.celebrations.ticked', { count: s.celebrations.length })
            : t('editor.celebrations.none'));
        const summary = h('p', { class: 'small celebration-summary' }, summaryText());
        fill();
        if (!celebrationNames().length) {
            // The library may still be loading, the list fills when it is there.
            setTimeout(() => {
                if (host.isConnected && celebrationNames().length) {
                    fill();
                }
            }, 1500);
        }
        // Clips come with the rig of the team's model.
        this.rigFor(this.style.model).then((rig) => {
            const clips = clipsOf(rig);
            if (host.isConnected && clips.join() !== (this.lastClips || []).join()) {
                this.lastClips = clips;
                fill();
            }
        });
        return h('div', { class: 'sec-body' },
            h('p', { class: 'muted small' }, t('editor.celebrations.note')),
            summary, host, clipsPanel(this));
    }

    playCelebration(name) {
        this.playing = { name, start: performance.now(), ...previewMove(this, name) };
        this.walk = false;
        this.syncPreviewModes();
    }

    soundsSection() {
        const rows = SOUND_SLOTS.map((slot) => this.soundRow(slot));
        return h('div', { class: 'sec-body' },
            h('p', { class: 'muted small' }, t('editor.sounds.note')),
            h('ul', { class: 'sound-list' }, rows));
    }

    soundRow(slot) {
        const [label, hint] = SOUND_LABELS[slot] || [pretty(slot), ''];
        const has = this.sounds.has(slot);
        const file = h('input', { type: 'file', accept: '.ogg,.mp3,.wav,audio/ogg,audio/mpeg,audio/wav,audio/x-wav', hidden: true });
        file.addEventListener('change', () => {
            const f = file.files[0];
            file.value = '';
            if (f) {
                this.uploadSound(slot, f);
            }
        });
        const li = h('li', { class: `sound-row${has ? ' has' : ''}`, 'data-slot': slot },
            h('span', { class: 'sound-icon', 'aria-hidden': 'true' }, has ? '♪' : '·'),
            h('span', { class: 'sound-text' }, h('span', { class: 'sound-label' }, label), h('span', { class: 'muted small' }, has ? t('editor.sounds.uploaded', { hint }) : hint)),
            h('span', { class: 'row sound-actions' },
                has ? h('button', { type: 'button', class: 'btn small', 'aria-label': t('editor.sounds.playLabel', { name: label.toLowerCase() }), onclick: () => this.playSound(slot) }, icon('play'), t('editor.play')) : null,
                h('button', { type: 'button', class: 'btn small', onclick: () => file.click() }, has ? t('editor.sounds.replace') : t('editor.sounds.upload')),
                has ? h('button', { type: 'button', class: 'btn small ghost danger', onclick: () => this.removeSound(slot) }, t('editor.remove')) : null,
                file));
        li.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.stopPropagation();
            li.classList.add('over');
        });
        li.addEventListener('dragleave', () => li.classList.remove('over'));
        li.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation();
            li.classList.remove('over');
            const f = e.dataTransfer.files[0];
            if (f) {
                this.uploadSound(slot, f);
            }
        });
        return li;
    }

    replaceSoundRow(slot) {
        const old = this.formHost.querySelector(`.sound-row[data-slot="${slot}"]`);
        if (old) {
            old.replaceWith(this.soundRow(slot));
        } else {
            this.built.delete('sounds');
        }
    }

    async uploadSound(slot, f) {
        if (!/\.(ogg|oga|mp3|wav)$/i.test(f.name) && !/^audio\/(ogg|mpeg|mp3|wav|x-wav|wave)$/.test(f.type)) {
            this.app.hud.toast(t('editor.sounds.wrongType'), 'error');
            return;
        }
        if (f.size > MAX_SOUND_BYTES) {
            this.app.hud.toast(t('editor.sounds.tooLarge', { size: formatBytes(f.size) }), 'error');
            return;
        }
        const team = this.team;
        const token = this.token;
        try {
            await api.putSound(team.id, slot, f, f.type || 'application/octet-stream');
            this.app.hud.toast(t('editor.sounds.saved', { name: (SOUND_LABELS[slot] || [slot])[0] }));
            // The sound is stored at once, so the match on the page takes the new one now.
            this.app.teamsChanged();
            if (token !== this.token) {
                return;
            }
            this.sounds.add(slot);
            team.sounds = [...this.sounds];
            this.replaceSoundRow(slot);
        } catch (err) {
            this.app.hud.toast(err.message, 'error', 7000);
        }
    }

    async removeSound(slot) {
        if (!confirm(t('editor.sounds.removeConfirm', { name: (SOUND_LABELS[slot] || [slot])[0].toLowerCase() }))) {
            return;
        }
        const team = this.team;
        const token = this.token;
        try {
            await api.deleteSound(team.id, slot);
            this.app.teamsChanged();
            if (token !== this.token) {
                return;
            }
            this.sounds.delete(slot);
            team.sounds = [...this.sounds];
            this.replaceSoundRow(slot);
        } catch (err) {
            this.app.hud.toast(err.message, 'error');
        }
    }

    // Plays a team sound through a gain at the page's volume and a limiter, never above the
    // page's level, and not at all while the page is muted.
    async playSound(slot) {
        const settings = this.app.settings;
        if (settings.muted || !(settings.volume > 0)) {
            this.app.hud.toast(t('editor.sounds.muted'), 'info', 5000);
            return;
        }
        this.stopSound();
        try {
            const bytes = await api.soundBytes(this.team.id, slot);
            const Ctx = window.AudioContext || window.webkitAudioContext;
            if (!this.audio) {
                this.audio = new Ctx();
            }
            const ctx = this.audio;
            await ctx.resume();
            const buffer = await ctx.decodeAudioData(bytes);
            if (this.app.settings.muted) {
                return;
            }
            const src = ctx.createBufferSource();
            src.buffer = buffer;
            const gain = ctx.createGain();
            gain.gain.value = Math.min(1, this.app.settings.volume) * 0.8;
            const limit = ctx.createDynamicsCompressor();
            limit.threshold.value = -14;
            limit.knee.value = 0;
            limit.ratio.value = 20;
            limit.attack.value = 0.002;
            limit.release.value = 0.15;
            src.connect(gain).connect(limit).connect(ctx.destination);
            src.start();
            this.soundSource = src;
        } catch (err) {
            this.app.hud.toast(t('editor.sounds.playFailed', { reason: err.message || err }), 'error');
        }
    }

    stopSound() {
        if (this.soundSource) {
            try {
                this.soundSource.stop();
            } catch {
                // It had already ended.
            }
            this.soundSource = null;
        }
    }

    // The server's defaults of a new team, the built in AI keeping its own blue kit.
    resetDefaults() {
        if (!confirm(t('editor.resetConfirm'))) {
            return;
        }
        const builtin = this.team.kind === 'builtin' || this.team.id === 'builtin';
        const fresh = normalizeStyle({ style: { kit: builtin ? BUILTIN_KIT : DEFAULT_KIT, goalkeeper: DEFAULT_GOALKEEPER } }, 0);
        fresh.model = this.style.model;
        fresh.art = this.style.art;
        fresh.players = [];
        fresh.colors = {};
        fresh.celebrations = [];
        fresh.crowd = { colors: [fresh.kit.primary.slice(), fresh.kit.secondary.slice()] };
        this.crowdFollowsKit = true;
        this.style = fresh;
        this.fitRoster();
        this.built.clear();
        this.invalidate(this.section);
        this.refreshPreview();
    }

    async save() {
        if (!this.team || this.saving) {
            return;
        }
        // The team, the token and every value sent are taken now, so a save still running when
        // another team opens writes only to its own team.
        const token = this.token;
        const team = this.team;
        const style = this.payloadStyle();
        const model = this.model;
        const modelDirty = this.modelDirty;
        const removeModel = this.removeModel;
        // A saved model that did not load in the page stays the team's model on the server.
        const keepSaved = !model && team.model && !removeModel;
        const usesCustom = style.model === 'custom' || style.players.some((p) => p.model === 'custom');
        if (usesCustom && !model && !keepSaved) {
            this.app.hud.toast(t('editor.saveNeedsModel'), 'error', 7000);
            this.showSection('model');
            return;
        }
        if (model && usesCustom && !model.joints.body) {
            this.app.hud.toast(t('editor.saveNeedsPelvis'), 'error');
            this.showSection('model');
            return;
        }
        const typed = this.name.trim();
        const changes = { name: !typed || typed === this.shownName ? team.name : typed, format: this.format, style };
        if (team.kind !== 'builtin') {
            changes.control = controlFromValue(this.control);
        }
        this.saving = true;
        this.saveBtn.disabled = true;
        this.saveBtn.textContent = t('editor.saving');
        try {
            if (removeModel && team.model) {
                await api.deleteModel(team.id);
            }
            if (model && modelDirty) {
                await api.putModel(team.id, model.joints, model.bytes);
            }
            // Sending the whole style is a valid partial update, every field is present.
            await api.updateTeam(team.id, changes);
            this.app.hud.toast(t('editor.saved', { name: changes.name }));
            if (token === this.token) {
                this.close(true);
            }
            this.app.teamsChanged();
        } catch (err) {
            this.app.hud.toast(err.message, 'error', 7000);
        } finally {
            this.saving = false;
            this.saveBtn.disabled = false;
            this.saveBtn.textContent = t('editor.save');
        }
    }

    // The preview, one player or the keeper on a small patch of grass, turning slowly.
    startPreview() {
        if (!this.renderer) {
            this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
            this.renderer.outputColorSpace = THREE.SRGBColorSpace;
            this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
            this.renderer.shadowMap.enabled = true;
            this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
            this.scene = new THREE.Scene();
            this.camera = new THREE.PerspectiveCamera(30, 1, 0.05, 80);
            this.camera.position.set(0, 1.3, 5.6);
            this.camera.lookAt(0, 1.08, 0);
            this.view = { pos: this.camera.position.clone(), target: new THREE.Vector3(0, 1.08, 0), want: null };
            const sun = new THREE.DirectionalLight(0xfff1dc, 2.6);
            sun.position.set(-2, 5, 3);
            sun.castShadow = true;
            sun.shadow.mapSize.set(1024, 1024);
            this.scene.add(sun, new THREE.HemisphereLight(0xcfe3ff, 0x3a5a2a, 1.2));
            this.ground = new THREE.Mesh(new THREE.CircleGeometry(1.4, 48), new THREE.MeshStandardMaterial({ color: 0x3f7f2c, roughness: 1 }));
            this.ground.rotation.x = -Math.PI / 2;
            this.ground.receiveShadow = true;
            this.scene.add(this.ground);
            this.fixed = new Set(this.scene.children);
            this.stage.appendChild(this.renderer.domElement);
        }
        this.pose = { players: 1, nodes: new Float32Array(PLAYER_FLOATS), ball: new Float32Array(7) };
        this.frame = { playerFlags: new Uint8Array([1]), ownedPlayer: -1 };
        this.running = true;
        this.clock = performance.now();
        this.refreshPreview();
        // Only the newest loop runs, an older one ends at its next frame.
        const id = ++this.loopId;
        const loop = () => {
            if (!this.running || id !== this.loopId) {
                return;
            }
            requestAnimationFrame(loop);
            this.drawPreview();
        };
        loop();
    }

    stopPreview() {
        this.running = false;
        this.loopId++;
        this.previewToken++;
        this.stopFlash();
        clearTimeout(this.previewTimer);
        if (this.players) {
            this.players.dispose();
            this.players = null;
        }
    }

    // The rig of a model id, the team's own upload, a shipped model, or none for GRF.
    async rigFor(m) {
        if (m === 'custom') {
            if (!this.model || !this.model.joints.body) {
                return null;
            }
            if (!this.customRig) {
                try {
                    this.customRig = new Rig(this.model.scene, this.model.joints, { onlyKit: true, animations: this.model.animations });
                    // An upload on KayKit's rig plays KayKit's clips as the shipped models do.
                    const rig = this.customRig;
                    await attachKayKitClips(rig);
                    if (this.customRig !== rig) {
                        return this.customRig;
                    }
                } catch (err) {
                    this.modelMessage(err.message, 'error');
                    return null;
                }
            }
            return this.customRig;
        }
        if (m && m !== 'grf') {
            return loadShippedRig(m);
        }
        return null;
    }

    get lastClips() {
        return this.clips || [];
    }

    set lastClips(v) {
        this.clips = v || [];
    }

    refreshPreview() {
        clearTimeout(this.previewTimer);
        this.markDirty();
        const token = ++this.previewToken;
        this.previewTimer = setTimeout(async () => {
            if (!this.scene || !this.team) {
                return;
            }
            const index = this.previewGk ? 0 : (this.previewIndex || 0) % FORMATS[this.format];
            const model = this.playerModel(index);
            this.previewModel = undefined;
            let rig = null;
            try {
                rig = await this.rigFor(model);
            } catch (err) {
                console.warn('preview model not loaded', err);
            }
            // A newer refresh, a stop or another team took over while the model loaded.
            if (token !== this.previewToken || !this.team) {
                return;
            }
            if (this.players) {
                this.players.dispose();
                this.players = null;
            }
            const header = {
                players: [{ team: 0, index, goalkeeper: index === 0, controlled: false }],
                teams: [{ name: this.name }, { name: '' }],
            };
            // The preview shows the one player's model as the team's, the roster entries follow it.
            const style = {
                ...this.style,
                model,
                art: model === 'grf' ? this.style.art : null,
                players: this.style.players.map((p) => ({ ...p, model: 'team' })),
            };
            try {
                this.players = new Players(this.scene, header, [style, style], this.app.assets, [rig, null], { clash: false });
                this.previewModel = rig ? model : 'grf';
                this.frameModel = true;
            } catch (err) {
                console.warn('preview not drawn', err);
            }
            this.syncPreviewModes();
        }, 60);
    }

    // Frames the model by its bounding box, so tall and wide models fit the stage.
    fitCamera() {
        this.scene.updateMatrixWorld(true);
        const box = new THREE.Box3();
        for (const child of this.scene.children) {
            if (!this.fixed.has(child)) {
                box.expandByObject(child, true);
            }
        }
        if (box.isEmpty()) {
            return;
        }
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        const height = Math.max(0.5, size.y);
        const radius = Math.max(0.3, Math.hypot(size.x, size.z) / 2);
        const half = THREE.MathUtils.degToRad(this.camera.fov / 2);
        const byHeight = (height / 2) / Math.tan(half);
        const byWidth = radius / (Math.tan(half) * Math.max(0.3, this.camera.aspect));
        const distance = Math.max(byHeight, byWidth) * 1.18 + radius;
        this.view.want = {
            target: new THREE.Vector3(0, center.y, 0),
            pos: new THREE.Vector3(0, center.y + height * 0.06, distance),
        };
    }

    drawPreview() {
        const stage = this.renderer.domElement.parentElement;
        if (!stage) {
            return;
        }
        const w = stage.clientWidth;
        const hgt = stage.clientHeight;
        if (w && hgt && (this.renderer.domElement.width !== Math.floor(w * this.renderer.getPixelRatio()) || this.renderer.domElement.height !== Math.floor(hgt * this.renderer.getPixelRatio()))) {
            this.renderer.setSize(w, hgt, false);
            this.camera.aspect = w / hgt;
            this.camera.updateProjectionMatrix();
            this.frameModel = true;
        }
        const now = performance.now();
        const t = (now - this.clock) / 1000;
        // Reduced motion holds the preview still.
        const still = this.app.reducedMotion;
        const heading = still ? 0 : t * 0.6;
        if (this.playing) {
            const pt = (now - this.playing.start) / 1000;
            if (pt > (this.playing.length || 5)) {
                this.playing = null;
                this.syncPreviewModes();
            } else {
                try {
                    posePlayer(this.playing.pose || this.playing.name, pt, this.pose.nodes, 0, 0, 0, heading * 0.3);
                    // A clip of the model plays over the standing pose for this drawing.
                    if (this.playing.name.startsWith('clip:') && this.players) {
                        this.players.playClip(0, this.playing.name, pt);
                    }
                } catch {
                    this.playing = null;
                }
            }
        }
        if (!this.playing) {
            if (this.walk) {
                walkPoseNodes(t * 9, 5, heading, this.pose.nodes);
            } else {
                restPoseNodes(heading, this.pose.nodes);
                // A slight breathing sway on the trunk keeps the idle pose alive.
                this.pose.nodes[1 * 7 + 2] += still ? 0 : Math.sin(t * 2) * 0.006;
            }
        }
        if (this.players) {
            this.players.update(this.pose, this.frame);
            if (this.frameModel) {
                this.frameModel = false;
                this.fitCamera();
            }
        }
        const v = this.view;
        if (v.want) {
            const k = 1 - Math.exp(-6 * (1 / 60));
            v.pos.lerp(v.want.pos, k);
            v.target.lerp(v.want.target, k);
            this.camera.position.copy(v.pos);
            this.camera.lookAt(v.target);
        }
        this.renderer.render(this.scene, this.camera);
    }
}
