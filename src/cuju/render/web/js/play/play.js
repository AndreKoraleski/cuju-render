// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The Play a game page, where a person controls one player of a side with the keyboard or a
// controller, Xbox, Nintendo or PlayStation. GRF's built-in AI or a team of the registry plays the
// other side, and either one plays the person's teammates. The server plays the game in a process
// of its own at ten steps a second and streams each frame at once, and the page sends the held
// keys and buttons of each person's side on every change. The keys and buttons follow Gameplay
// Football's layout, and the server turns them into GRF's 19 actions with GRF's own controller logic.

import * as THREE from 'three';
import { api } from '../core/api.js';
import { ChallengesPanel } from './challenges.js';
import { serverText, t, tn, tOr } from '../core/i18n.js';
import { LiveSource } from '../recording/live.js';
import { el as h } from '../core/menu.js';
import { icon, symbolOnly } from '../core/icons.js';
import { PLAYER_FLOATS } from '../recording/format.js';
import { SLOW_FPS, offersView2d } from '../watch/flat.js';
import { summaryTeams, teamName } from '../core/names.js';
import { listedScenarios, scenarioName, scenarioText } from '../core/scenarios.js';
import {
    BINDINGS, DEAD_ZONE, actionName, devicesClash, keyLabel, keyMap, keyProblem,
    loadSettings, defaultSettings, saveSettings, stickDirections,
} from '../core/input-settings.js';

const DEFAULT_SCENARIO = '11_vs_11_kaggle';
// The view keeps this many frames behind the newest one, enough to blend between two frames.
const PLAY_DELAY_FRAMES = 1.1;
// The page repeats its input this often, so the server knows it is still there.
const HEARTBEAT_MS = 500;
// A stick counts as pushed past half way along an axis, as GRF's gamepad player reads it.
const STICK = 0.5;
// The settings of the viewer that would hold play back, off while a game shows.
const HELD_BACK = { celebrations: false, replays: false, transitions: false, decisionReplays: false, podium: false, lineups: false };
// The steps in a row without an answer in time after which a registered team counts as falling
// behind, as the game reports it.
const LATE_STREAK = 10;
// The picture of a game is measured over windows of this many seconds, and a window below the
// rate of flat.js offers a lower quality once for each visit, as Watch offers the 2D view.
const SLOW_WINDOW = 5;
const SLOW_DECLINED = 'cuju.playSlowDeclined';
// The direction that GRF's sticky actions hold, by the held directions of the page.
const STICKY_NAMES = { up: 'top', down: 'bottom', left: 'left', right: 'right' };

// An error of the server as a sentence on a card, with its first letter in capitals.
function sentence(text) {
    const value = String(text);
    return value.charAt(0).toUpperCase() + value.slice(1);
}

// The keyboard's keys come from the input settings, by the physical key, so every layout plays the
// same. Controller actions bind to the position of a button, GRF's own Xbox layout, so the same hands
// play the same on every style of controller. South is the lower face button, east the right one,
// west the left one and north the upper one.
const PAD_BUTTONS = {
    south: ['short_pass'], east: ['shot'], west: ['high_pass', 'sliding'], north: ['long_pass'],
    rt: ['sprint'], rb: ['dribble'], up: ['up'], down: ['down'], left: ['left'], right: ['right'],
};
const POSITIONS = ['south', 'east', 'west', 'north', 'lb', 'rb', 'lt', 'rt', 'back', 'start', 'up', 'down', 'left', 'right'];
// The standard mapping of the Gamepad API, a button index for each position and the axes of the
// left stick. A source is a button, b, or an axis, a, with its sign, s, and threshold, t.
const STANDARD = {
    south: { b: 0 }, east: { b: 1 }, west: { b: 2 }, north: { b: 3 }, lb: { b: 4 }, rb: { b: 5 },
    lt: { b: 6 }, rt: { b: 7 }, back: { b: 8 }, start: { b: 9 },
    up: { b: 12 }, down: { b: 13 }, left: { b: 14 }, right: { b: 15 },
    stickX: { a: 0, s: 1, t: STICK }, stickY: { a: 1, s: 1, t: STICK },
};
// A hat axis gives the eight directions of a D-pad as values from -1 to 1 in steps of two
// sevenths, up first and then clockwise. A direction counts as held at its own value and at the
// two diagonals beside it. A value off that ring counts only when it matches the stored one.
const HAT_STEP = 2 / 7;
function hatIndex(value) {
    const k = Math.round((value + 1) / HAT_STEP);
    return k >= 0 && k <= 7 && Math.abs(value - (-1 + k * HAT_STEP)) < 0.1 ? k : -1;
}
function hatOn(value, stored) {
    if (value === undefined || Math.abs(value) > 1.05) {
        return false;
    }
    const k = hatIndex(value);
    const r = hatIndex(stored);
    if (k < 0 || r < 0) {
        return Math.abs(value - stored) < 0.1;
    }
    const d = Math.abs(k - r) % 8;
    return d === 0 || d === 1 || d === 7;
}

// A trigger or button that reports as an axis counts as pressed past this value.
const AXIS_ON = 0.5;
// The setup asks for each position in this order, the buttons, the left stick and the D-pad.
const SETUP_STEPS = ['south', 'east', 'west', 'north', 'lb', 'rb', 'lt', 'rt', 'back', 'start',
    'stickX', 'stickY', 'up', 'down', 'left', 'right'];
// The layouts set up by hand, one for each controller id.
const LAYOUTS_KEY = 'cuju.padLayouts';
const DIRECTIONS = new Set(['left', 'right', 'up', 'down']);
// A controller works the menus of the page by the positions of its buttons, as consoles do. A held
// direction moves once, then again after the delay and at the repeat rate while it stays held. A
// stick direction holds until the stick falls back under the release value, so one push is one move.
const NAV_DELAY_MS = 400;
const NAV_REPEAT_MS = 120;
const NAV_RELEASE = 0.3;
const FOCUSABLE = 'button, select, input, summary, a[href], [tabindex]:not([tabindex="-1"])';
// The input tester refreshes this often while it shows.
const TESTER_MS = 100;
// The names of the devices, which the status line shows and the page compares.
const KEYBOARD = t('play.device.keyboard');
const CONTROLLER = t('play.device.controller');

// The label of a binding of the input settings, by its id.
function bindingLabel(binding) {
    return t(`play.binding.${binding.id}`);
}

// The name of an input held, such as short pass, as the tester lists it.
function inputName(name) {
    return tOr(`play.input.${name}`, name.replaceAll('_', ' '));
}

// The name of one of GRF's engine actions, such as top left, by its index.
function engineAction(index) {
    const name = actionName(index);
    return tOr(`play.engineAction.${name.toLowerCase().replace(/[^a-z]+/g, '_')}`, name);
}

// Two names joined, such as A and B, and more joined in turn.
function joinAnd(names) {
    return names.reduce((left, right) => t('play.and', { left, right }));
}

// Focus that a controller moves shows the ring of keyboard focus.
function padFocus(el) {
    el.focus({ focusVisible: true });
}

// The keyboard rows of the current keys. The four arrows share a row while they move.
export function keyboardControls(settings) {
    const arrows = ['left', 'up', 'down', 'right'].every((id) => settings.keys[id] === `Arrow${id[0].toUpperCase()}${id.slice(1)}`);
    const rows = arrows ? [['Arrow keys', t('play.controls.move')]] : [];
    for (const binding of BINDINGS) {
        if (!(arrows && binding.names.length === 1 && ['left', 'right', 'up', 'down'].includes(binding.id))) {
            rows.push([keyLabel(settings.keys[binding.id]), bindingLabel(binding)]);
        }
    }
    return rows.concat([['Esc', t('play.controls.pause')], ['H or ?', t('play.controls.help')]]);
}
// The controller rows name positions, drawn in the icons of the controller's style.
export const PAD_CONTROLS = [
    ['stick or dpad', t('play.controls.move')],
    ['south', t('play.binding.short_pass')],
    ['east', t('play.binding.shot')],
    ['west', t('play.binding.high_pass')],
    ['north', t('play.binding.long_pass')],
    ['rt', t('play.binding.sprint')],
    ['rb', t('play.binding.dribble')],
    ['start', t('play.controls.pause')],
    ['back', t('play.controls.card')],
];

// The buttons of each style of controller by position, each with its classes, spoken name, text
// on the icon and short name, drawn without images so they stay crisp at any size. A button named
// by its letters is spoken as the letters with the word button.
const padButton = (name) => t('play.pad.button', { name });
const PAD_STYLES = {
    xbox: {
        name: 'Xbox',
        south: ['pad-face pad-a', padButton('A'), 'A', 'A'],
        east: ['pad-face pad-b', padButton('B'), 'B', 'B'],
        west: ['pad-face pad-x', padButton('X'), 'X', 'X'],
        north: ['pad-face pad-y', padButton('Y'), 'Y', 'Y'],
        lb: ['pad-shoulder', t('play.pad.xbox.lb'), 'LB', 'LB'],
        rb: ['pad-shoulder', t('play.pad.xbox.rb'), 'RB', 'RB'],
        lt: ['pad-trigger', t('play.pad.xbox.lt'), 'LT', 'LT'],
        rt: ['pad-trigger', t('play.pad.xbox.rt'), 'RT', 'RT'],
        back: ['pad-view', t('play.pad.xbox.back'), '', t('play.pad.xbox.back.short')],
        start: ['pad-menu', t('play.pad.xbox.start'), '', t('play.pad.xbox.start.short')],
    },
    nintendo: {
        name: 'Nintendo',
        south: ['pad-face', padButton('B'), 'B', 'B'],
        east: ['pad-face', padButton('A'), 'A', 'A'],
        west: ['pad-face', padButton('Y'), 'Y', 'Y'],
        north: ['pad-face', padButton('X'), 'X', 'X'],
        lb: ['pad-shoulder', padButton('L'), 'L', 'L'],
        rb: ['pad-shoulder', padButton('R'), 'R', 'R'],
        lt: ['pad-trigger', padButton('ZL'), 'ZL', 'ZL'],
        rt: ['pad-trigger', padButton('ZR'), 'ZR', 'ZR'],
        back: ['pad-sys', t('play.pad.nintendo.back'), '−', t('play.pad.nintendo.back.short')],
        start: ['pad-sys', t('play.pad.nintendo.start'), '+', t('play.pad.nintendo.start.short')],
    },
    playstation: {
        name: 'PlayStation',
        south: ['pad-face pad-ps pad-cross', t('play.pad.playstation.south'), '✕', t('play.pad.playstation.south.short')],
        east: ['pad-face pad-ps pad-circle', t('play.pad.playstation.east'), '○', t('play.pad.playstation.east.short')],
        west: ['pad-face pad-ps pad-square', t('play.pad.playstation.west'), '□', t('play.pad.playstation.west.short')],
        north: ['pad-face pad-ps pad-triangle', t('play.pad.playstation.north'), '△', t('play.pad.playstation.north.short')],
        lb: ['pad-shoulder', padButton('L1'), 'L1', 'L1'],
        rb: ['pad-shoulder', padButton('R1'), 'R1', 'R1'],
        lt: ['pad-trigger', padButton('L2'), 'L2', 'L2'],
        rt: ['pad-trigger', padButton('R2'), 'R2', 'R2'],
        back: ['pad-sys', t('play.pad.playstation.back'), '', t('play.pad.playstation.back.short')],
        start: ['pad-menu', t('play.pad.playstation.start'), '', t('play.pad.playstation.start.short')],
    },
};
const PAD_COMMON = {
    stick: ['pad-stick', t('play.pad.stick'), 'L', t('play.pad.stick.short')],
    dpad: ['pad-dpad', t('play.pad.dpad'), '', t('play.pad.dpad.short')],
};
const ARROWS = [['←', t('play.key.left')], ['↑', t('play.key.up')], ['↓', t('play.key.down')], ['→', t('play.key.right')]];

function padInfo(style, pos) {
    return PAD_COMMON[pos] || (PAD_STYLES[style] || PAD_STYLES.xbox)[pos];
}

export function padIcon(style, pos) {
    const [kind, label, text] = padInfo(style, pos);
    return h('span', { class: `padicon ${kind}`, role: 'img', 'aria-label': label, title: label }, text);
}

// The likely style of a controller from the id the browser reports, Xbox when nothing says.
function detectStyle(id) {
    if (/xbox|xinput|microsoft|045e/i.test(id)) {
        return 'xbox';
    }
    if (/dualsense|dualshock|playstation|wireless controller|054c/i.test(id)) {
        return 'playstation';
    }
    if (/pro controller|joy-con|nintendo|057e/i.test(id)) {
        return 'nintendo';
    }
    return 'xbox';
}

function loadLayouts() {
    try {
        return JSON.parse(localStorage.getItem(LAYOUTS_KEY) || '{}') || {};
    } catch {
        return {};
    }
}

function saveLayout(id, entry) {
    const all = loadLayouts();
    all[id] = entry;
    try {
        localStorage.setItem(LAYOUTS_KEY, JSON.stringify(all));
    } catch {
        // The layout holds for this visit.
    }
}

// The keys of a row as keycaps or controller icons, alternatives joined by or.
function controlKeys(key, style) {
    if (key === 'Arrow keys') {
        return h('span', { class: 'keys' }, ARROWS.map(([text, label]) => h('kbd', { 'aria-label': label, title: label }, text)));
    }
    const parts = key.split(' or ');
    return h('span', { class: 'keys' }, parts.flatMap((part, i) => {
        const info = style && padInfo(style, part);
        return [
            i ? h('span', { class: 'keys-or' }, t('play.controls.or')) : null,
            info ? padIcon(style, part) : h('kbd', {}, part),
            info && !info[2] && (part === 'back' || part === 'start') ? h('span', { class: 'pad-name' }, info[3]) : null,
        ];
    }).filter(Boolean));
}

// A table of controls, the keyboard's or, given a style, the controller's.
function controlsTable(rows, style = null) {
    return h('table', { class: 'controls-table' },
        h('tbody', {}, rows.map(([key, what]) => h('tr', {}, h('th', {}, controlKeys(key, style)), h('td', {}, what)))));
}

// The controller line of the Help page in a style's icons.
function padHelp(style) {
    const icons = {};
    for (const pos of ['stick', 'dpad', 'south', 'east', 'west', 'north', 'rt', 'rb', 'start', 'back']) {
        icons[pos] = padIcon(style, pos);
    }
    return tn('play.help.controller', icons);
}

// A small sketch of a controller with one position lit, the face buttons in the style's labels.
function padSketch(style, on) {
    const ps = style === 'playstation';
    const [sx, sy] = ps ? [80, 86] : [58, 58];
    const [dx, dy] = ps ? [58, 58] : [80, 86];
    const lit = (pos) => (pos === on || (pos === 'stick' && (on === 'stickX' || on === 'stickY')) ? 'part on' : 'part');
    const text = (x, y, t, size = 9) => `<text x="${x}" y="${y}" font-size="${size}" text-anchor="middle" dominant-baseline="central">${t}</text>`;
    const info = (pos) => padInfo(style, pos)[2];
    const face = [['north', 146, 44], ['south', 146, 80], ['west', 128, 62], ['east', 164, 62]];
    const pad = [['up', dx - 5, dy - 16, 10, 11], ['down', dx - 5, dy + 5, 10, 11], ['left', dx - 16, dy - 5, 11, 10], ['right', dx + 5, dy - 5, 11, 10]];
    return `<svg class="pad-sketch" viewBox="0 0 200 124" aria-hidden="true">
<rect class="${lit('lt')}" x="26" y="2" width="40" height="13" rx="5"/>${text(46, 9, info('lt'), 7)}
<rect class="${lit('rt')}" x="134" y="2" width="40" height="13" rx="5"/>${text(154, 9, info('rt'), 7)}
<rect class="${lit('lb')}" x="22" y="17" width="48" height="9" rx="4"/>${text(46, 21.5, info('lb'), 7)}
<rect class="${lit('rb')}" x="130" y="17" width="48" height="9" rx="4"/>${text(154, 21.5, info('rb'), 7)}
<rect class="body" x="10" y="28" width="180" height="92" rx="44"/>
<circle class="${lit('stick')}" cx="${sx}" cy="${sy}" r="12"/>
${pad.map(([pos, x, y, w, hh]) => `<rect class="${lit(pos)}" x="${x}" y="${y}" width="${w}" height="${hh}" rx="2"/>`).join('')}
<circle class="${lit('back')}" cx="88" cy="48" r="5"/><circle class="${lit('start')}" cx="112" cy="48" r="5"/>
${face.map(([pos, x, y]) => `<circle class="${lit(pos)}" cx="${x}" cy="${y}" r="9"/>${text(x, y, info(pos))}`).join('')}
</svg>`;
}

// One input device, its held inputs and the buttons pressed since the last send.
class Device {
    constructor(id, label) {
        this.id = id;
        this.label = label;
        this.held = new Set();
        this.pressed = new Set();
        this.usedAt = 0;
    }

    set(names, down) {
        for (const name of names) {
            if (down && !this.held.has(name) && !DIRECTIONS.has(name)) {
                this.pressed.add(name);
            }
            if (down) {
                this.held.add(name);
            } else {
                this.held.delete(name);
            }
        }
        this.usedAt = performance.now();
    }
}

export class PlayPage {
    constructor(app) {
        this.app = app;
        this.root = document.getElementById('page-play');
        this.setup = { scenario: DEFAULT_SCENARIO, side: 'left', ability: [null, null], record: true, teams: ['builtin', 'builtin'] };
        this.teamList = [];
        this.game = null;
        this.keyboard = new Device('keyboard', KEYBOARD);
        this.input = loadSettings();
        this.keys = keyMap(this.input);
        this.testerAt = 0;
        this.pads = new Map();
        this.built = false;
        this.saved = null;
        window.addEventListener('keydown', (e) => this.onKey(e, true), true);
        window.addEventListener('keyup', (e) => this.onKey(e, false), true);
        window.addEventListener('blur', () => this.releaseKeys());
        document.addEventListener('visibilitychange', () => {
            if (document.hidden && this.playing) {
                this.pause(true);
            }
        });
        window.addEventListener('pagehide', () => {
            if (this.game && !this.game.ended) {
                fetch(`/api/game/${encodeURIComponent(this.game.id)}/pause`, {
                    method: 'POST', keepalive: true, headers: { 'Content-Type': 'application/json' }, body: '{"paused": true}',
                }).catch(() => {});
            }
        });
        const loop = () => {
            requestAnimationFrame(loop);
            this.pollPads();
        };
        requestAnimationFrame(loop);
        setInterval(() => this.heartbeat(), HEARTBEAT_MS);
        this.marker = this.makeMarker();
        app.poseHooks.push((pose, s) => this.placeMarker(pose, s));
        this.challenges = new ChallengesPanel(this);
    }

    get visible() {
        return !this.root.hidden;
    }

    get playing() {
        return !!(this.game && !this.game.ended && !this.game.paused && this.game.started);
    }

    // The page.

    build() {
        this.built = true;
        this.scenarioSelect = h('select', { 'aria-label': t('play.setup.scenario') });
        this.scenarioSelect.addEventListener('change', () => {
            this.setup.scenario = this.scenarioSelect.value;
            this.scenarioText.textContent = scenarioText(this.setup.scenario);
        });
        this.scenarioText = h('p', { class: 'scenario-text muted small', 'aria-live': 'polite' });
        const sides = ['left', 'right', 'both'].map((v) => [v, t(`play.setup.side.${v}`)]);
        this.sideSelect = h('select', { 'aria-label': t('play.setup.side') }, sides.map(([v, text]) => h('option', { value: v }, text)));
        this.sideSelect.addEventListener('change', () => {
            this.setup.side = this.sideSelect.value;
            this.syncTeams();
        });
        // The team of each side, which plays a side without a person and joins a person as teammates.
        this.teamLabels = [0, 1].map(() => h('span', {}));
        this.teamSelects = [0, 1].map((side) => {
            const select = h('select', {});
            select.addEventListener('change', () => {
                this.setup.teams[side] = select.value;
            });
            return select;
        });
        const ability = (side) => {
            const where = side ? 'right' : 'left';
            const own = h('input', { type: 'checkbox', 'aria-label': t(`play.setup.ability.${where}.own`) });
            const range = h('input', { type: 'range', min: '0', max: '1', step: '0.05', value: '0.5', disabled: true, 'aria-label': t(`play.setup.ability.${where}.range`) });
            const shown = h('output', { class: 'ability-value' }, t('play.setup.ability.scenario'));
            const sync = () => {
                this.setup.ability[side] = own.checked ? Number(range.value) : null;
                range.disabled = !own.checked;
                shown.textContent = own.checked ? Number(range.value).toFixed(2) : t('play.setup.ability.scenario');
            };
            own.addEventListener('change', sync);
            range.addEventListener('input', sync);
            return h('div', { class: 'ability' }, h('label', { class: 'check' }, own, t(`play.setup.ability.${where}`)), range, shown);
        };
        this.recordBox = h('input', { type: 'checkbox', checked: true });
        this.recordBox.addEventListener('change', () => {
            this.setup.record = this.recordBox.checked;
        });
        this.startButton = h('button', { type: 'button', class: 'btn primary', onclick: () => this.start() }, icon('play'), t('play.setup.start'));
        this.padNote = h('div', { class: 'muted small play-pads' });
        this.padTable = h('div', {}, h('h3', {}, CONTROLLER), controlsTable(PAD_CONTROLS, 'xbox'));
        this.setupView = h('section', { class: 'play-setup', 'aria-labelledby': 'play-title' },
            h('header', {}, h('h2', { id: 'play-title' }, t('play.setup.title')),
                h('p', { class: 'muted' }, t('play.setup.lead'))),
            h('div', { class: 'setup-row' },
                h('label', { class: 'field' }, t('play.setup.scenario'), this.scenarioSelect),
                h('label', { class: 'field' }, t('play.setup.side'), this.sideSelect)),
            this.scenarioText,
            h('div', { class: 'setup-row' }, [0, 1].map((side) => h('label', { class: 'field' }, this.teamLabels[side], this.teamSelects[side]))),
            h('div', { class: 'setup-row', title: t('play.setup.ability.title') }, ability(0), ability(1)),
            h('label', { class: 'check' }, this.recordBox, t('play.setup.record')),
            h('div', { class: 'play-tables' },
                this.keyTable = h('div', {}, h('h3', {}, KEYBOARD), controlsTable(keyboardControls(this.input))),
                this.padTable),
            this.padNote,
            this.inputSettings(),
            h('div', { class: 'play-row' }, this.startButton),
            this.challenges.element());
        this.view = h('div', { class: 'play-view', tabindex: '0', 'aria-label': t('play.view') });
        this.view.addEventListener('focusout', () => this.releaseKeys());
        this.status = h('div', { class: 'play-status', 'aria-live': 'polite' });
        this.card = h('div', { class: 'play-card', hidden: true });
        this.resumeButton = h('button', { type: 'button', class: 'btn primary', onclick: () => this.pause(false) }, icon('play'), t('play.pause.resume'));
        this.controlsButton = h('button', { type: 'button', class: 'btn', onclick: () => this.openCard() }, icon('keyboard'), t('play.pause.controls'));
        this.menu = h('div', { class: 'play-menu', role: 'dialog', 'aria-label': t('play.pause.title'), hidden: true },
            h('div', { class: 'play-panel' }, h('h2', {}, t('play.pause.title')),
                this.resumeButton,
                this.controlsButton,
                h('button', { type: 'button', class: 'btn', onclick: () => this.openPadSetup() }, icon('gamepad'), t('play.padSetup.open')),
                h('button', { type: 'button', class: 'btn danger', onclick: () => this.quit() }, icon('exit'), t('play.pause.quit')),
                h('button', { type: 'button', class: 'btn danger', onclick: () => this.goHome(true) }, icon('exit'), t('play.pause.quitHome')),
                h('button', { type: 'button', class: 'btn', onclick: () => this.goHome() }, icon('home'), t('play.home')),
                this.menuHint = h('p', { class: 'muted small keys pad-hint', hidden: true })));
        this.endPanel = h('div', { class: 'play-panel' });
        this.end = h('div', { class: 'play-menu', role: 'dialog', 'aria-label': t('play.end.fullTime'), hidden: true }, this.endPanel);
        this.end.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                this.showSetup();
                this.startButton.focus();
            }
        });
        this.wait = h('div', { class: 'play-wait', hidden: true }, h('div', { class: 'spinner' }), h('span', {}, t('play.starting')));
        // The card follows the pause menu, so the card that Controls opens is the dialog on top.
        this.stage = h('div', { class: 'play-stage', hidden: true }, this.view, this.status, this.wait, this.menu, this.card, this.end);
        // The offer names the controller that reports its own layout, which its button sets up.
        this.offerPad = null;
        this.offer = h('div', { class: 'pad-offer', role: 'status', hidden: true },
            h('span', {}, t('play.padOffer.text')),
            h('button', { type: 'button', class: 'btn primary', onclick: () => this.openPadSetup(this.offerPad) }, icon('gamepad'), t('play.padSetup.open')),
            h('button', { type: 'button', class: 'btn', ...symbolOnly(t('play.padOffer.later')), onclick: () => { this.offer.hidden = true; } }, icon('close')));
        this.slowText = h('span', {});
        this.slowOffer = h('div', { class: 'pad-offer play-slow-offer', role: 'status', hidden: true },
            this.slowText,
            h('button', { type: 'button', class: 'btn primary', onclick: () => {
                this.slowOffer.hidden = true;
                this.app.setQuality('low');
                this.app.hud.toast(t('play.slow.done'), 'info', 4000);
            } }, t('play.slow.low')),
            h('button', { type: 'button', class: 'btn', onclick: () => {
                this.slowOffer.hidden = true;
                try {
                    localStorage.setItem(SLOW_DECLINED, 'true');
                } catch {
                    // Storage can be unavailable, the offer then stays away for this visit only.
                }
            } }, t('play.slow.keep')));
        this.setupBox = h('div', { class: 'play-panel pad-setup-panel' });
        this.setupPanel = h('div', { class: 'pad-setup', role: 'dialog', 'aria-modal': 'true', 'aria-label': t('play.padSetup.open'), hidden: true }, this.setupBox);
        this.stage.append(this.slowOffer);
        this.root.replaceChildren(this.setupView, this.stage, this.offer, this.setupPanel);
        this.shownStyle = null;
        this.refreshStyle();
    }

    async show() {
        if (!this.built) {
            this.build();
        }
        try {
            const scenarios = listedScenarios(await api.scenarios());
            this.scenarioSelect.replaceChildren(...scenarios.map((s) => h('option', { value: s }, scenarioName(s))));
            this.scenarioSelect.value = scenarios.includes(this.setup.scenario) ? this.setup.scenario : scenarios[0];
            this.setup.scenario = this.scenarioSelect.value;
            this.scenarioText.textContent = scenarioText(this.setup.scenario);
            this.teamList = await api.teams();
        } catch {
            // The server is away, the start says so.
        }
        this.syncTeams();
        this.updatePadNote();
        this.challenges.show(this.teamList);
        if (this.game) {
            this.enterStage();
            // A game that the page started away from Play, such as a match of a tournament, has
            // no stream yet, and a game whose picture another source took connects again.
            const game = this.game;
            if (!game.ended && (game.source ? this.app.source !== game.source : !game.live)) {
                this.connect();
            }
        }
    }

    hide() {
        if (this.game && !this.game.ended && this.game.started && !this.game.paused) {
            this.pause(true);
        }
        this.leaveStage();
    }

    // The stage borrows the viewer's picture and its scoreboard while it shows.
    enterStage() {
        this.setupView.hidden = true;
        this.stage.hidden = false;
        this.app.view.attach(this.view);
        this.updateStatus();
        const hud = document.getElementById('hud');
        if (hud.parentNode !== this.stage) {
            this.stage.insertBefore(hud, this.status);
        }
        if (!this.saved) {
            this.saved = this.app.settings;
            this.app.settings = { ...this.saved, ...HELD_BACK };
        }
        this.app.cameras.setMode('broadcast');
    }

    leaveStage() {
        if (!this.built) {
            return;
        }
        const hud = document.getElementById('hud');
        if (hud.parentNode === this.stage) {
            document.getElementById('watch').insertBefore(hud, document.getElementById('stinger'));
        }
        this.app.view.attach(document.getElementById('stage'));
        if (this.saved) {
            // Changes made in the settings panel meanwhile stay, the held back ones return.
            const now = this.app.settings;
            this.app.settings = this.saved;
            for (const key of Object.keys(now)) {
                if (!(key in HELD_BACK)) {
                    this.saved[key] = now[key];
                }
            }
            this.saved = null;
        }
        this.marker.visible = false;
    }

    // The team lists of both sides. A side without a person lists every team, and a person's side
    // lists the teams of dynamic assignment, which share a side with a person as GRF's agents do.
    syncTeams() {
        if (!this.built) {
            return;
        }
        const humans = [this.setup.side !== 'right', this.setup.side !== 'left'];
        const two = humans[0] && humans[1];
        [0, 1].forEach((side) => {
            const human = humans[side];
            const role = human ? (two ? t('play.team.role.player', { number: side + 1 }) : t('play.team.role.yours')) : t('play.team.role.opponents');
            const where = side ? 'right' : 'left';
            this.teamLabels[side].textContent = t(`play.team.${where}`, { role });
            const teams = this.teamList.filter((team) => team.kind !== 'builtin'
                && (!human || (team.control && team.control.assignment === 'dynamic')));
            const select = this.teamSelects[side];
            select.setAttribute('aria-label', t(`play.team.${where}.select`, { role }));
            select.replaceChildren(h('option', { value: 'builtin' }, t('play.team.builtin')),
                ...teams.map((team) => h('option', { value: team.id }, t(team.format === '5v5' ? 'play.team.five' : 'play.team.eleven', { name: teamName(team) }))));
            select.value = teams.some((team) => team.id === this.setup.teams[side]) ? this.setup.teams[side] : 'builtin';
            this.setup.teams[side] = select.value;
        });
    }

    showSetup() {
        this.leaveStage();
        this.game = null;
        this.setupView.hidden = false;
        this.stage.hidden = true;
        this.startButton.focus();
    }

    // A game.

    // A spec in place of the setup starts a game of a challenge, with its own seed.
    async start(spec = null) {
        const s = spec || this.setup;
        const humans = [s.side !== 'right', s.side !== 'left'];
        this.startButton.disabled = true;
        let entry;
        try {
            entry = await api.startGame({ scenario: s.scenario, humans, ability: s.ability.slice(), record: s.record, teams: s.teams.slice(), ...(s.seed != null ? { seed: s.seed } : {}) });
        } catch (err) {
            this.app.hud.toast(err.status === 409 ? t('play.toast.busy') : err.message, 'error', 7000);
            this.startButton.disabled = false;
            return;
        }
        this.startButton.disabled = false;
        this.begin(entry, humans, null, s);
    }

    // Shows a game that the server started, from the setup or as a match of a tournament, whose
    // context names it and leads back to the tournament at the end.
    begin(entry, humans, context = null, spec = null) {
        this.game = { id: entry.id, humans, entry, started: false, paused: false, ended: false, source: null, sent: {}, busy: false, behind: false, context, spec };
        if (!this.built) {
            return;
        }
        this.menu.hidden = true;
        this.end.hidden = true;
        if (this.app.page === 'play') {
            this.enterStage();
            this.view.focus();
            this.connect();
        }
    }

    connect() {
        const game = this.game;
        this.wait.hidden = false;
        // The scoreboard of the game before, its clock and score, leaves at once, and the new
        // game's header brings the scoreboard back.
        this.app.hud.hide();
        const live = new LiveSource(game.id, {
            open: (signal) => api.gameStream(game.id, signal),
            onHeader: async (header, store) => {
                if (this.game !== game) {
                    live.stop();
                    return;
                }
                const source = { kind: 'live', id: game.id, header, store, live, game: true };
                game.source = source;
                await this.app.setSource(source);
                const tl = this.app.timeline;
                tl.delay = PLAY_DELAY_FRAMES;
                tl.lean = 0.5;
                tl.jump = 8;
                tl.goLive();
                this.app.cameras.setMode('broadcast');
                this.wait.hidden = true;
                if (!game.started) {
                    game.started = true;
                    this.toggleCard(true, 8000);
                    await this.sendPause(false);
                } else if (game.paused) {
                    this.hush();
                }
            },
            onFrame: () => {},
            onEnd: () => this.refresh(),
            onError: (err) => {
                this.wait.hidden = true;
                if (game.live === live) {
                    game.live = null;
                }
                if (this.game === game && !game.ended) {
                    this.app.hud.toast(t('play.toast.streamStopped', { reason: err.message }), 'error', 7000);
                }
            },
        });
        game.live = live;
        live.start();
    }

    async sendPause(paused) {
        const game = this.game;
        if (!game || game.ended) {
            return;
        }
        game.paused = paused;
        try {
            this.apply(await api.pauseGame(game.id, paused));
        } catch (err) {
            this.app.hud.toast(err.message, 'error');
        }
    }

    pause(on) {
        const game = this.game;
        if (!game || game.ended || !game.started) {
            return;
        }
        this.menu.hidden = !on;
        if (!on && !this.card.hidden && this.card.getAttribute('role') === 'dialog') {
            // The card of the pause menu leaves with it, so play keeps its focus.
            this.toggleCard(false);
        }
        if (on) {
            this.releaseKeys();
            this.resumeButton.focus();
            this.hush();
        } else if (this.app.timeline) {
            this.view.focus();
            this.app.timeline.goLive();
        }
        this.sendPause(on);
    }

    // A paused or ended game holds its picture, and the sound, which plays only while the
    // timeline plays, falls silent. Resume plays the timeline again.
    hush() {
        const tl = this.app.timeline;
        if (tl && this.game && this.app.source === this.game.source) {
            tl.pause();
        }
    }

    async quit() {
        const game = this.game;
        if (!game) {
            return;
        }
        this.menu.hidden = true;
        try {
            this.apply(await api.quitGame(game.id));
        } catch {
            // The poll below reads the end.
        }
        this.refresh();
    }

    async goHome(quit = false) {
        if (!quit && this.game && !this.game.ended) {
            this.pause(true);
            this.app.showPage('home');
            document.getElementById('home-btn').focus();
            return;
        }
        const game = this.game;
        if (game && !game.ended) {
            try {
                this.apply(await api.quitGame(game.id));
                await this.refresh();
            } catch (err) {
                this.app.hud.toast(err.message, 'error');
                return;
            }
            if (!game.ended) {
                this.app.hud.toast(t('play.toast.stillEnding'), 'error');
                return;
            }
        }
        if (game && game.source) {
            game.source.live.stop();
        }
        this.showSetup();
        this.app.showPage('home');
        document.getElementById('home-btn').focus();
    }

    // The entry the server answers with, its state and score.
    apply(entry) {
        const game = this.game;
        if (!game || !entry || entry.id !== game.id) {
            return;
        }
        game.entry = entry;
        // A registered team that keeps missing its time is named once, until it catches up again.
        if ((entry.streak || 0) >= LATE_STREAK && !game.behind) {
            game.behind = true;
            this.notice(t('play.notice.late'));
        } else if (!entry.streak && game.behind) {
            game.behind = false;
        }
        this.updateStatus();
        if (entry.state === 'paused' && entry.reason === 'input' && !game.waiting) {
            game.waiting = true;
            this.notice(t('play.notice.waiting'));
        } else if (entry.state === 'playing' && game.waiting) {
            game.waiting = false;
        }
        if ((entry.state === 'ended' || entry.state === 'failed') && !game.ended) {
            this.finish(entry);
        }
    }

    async refresh() {
        if (!this.game || this.game.ended) {
            return;
        }
        const game = this.game;
        for (let tries = 0; tries < 40 && this.game === game && !game.ended; tries++) {
            try {
                this.apply(await api.game());
            } catch {
                return;
            }
            await new Promise((resolve) => setTimeout(resolve, 250));
        }
    }

    finish(entry) {
        const game = this.game;
        game.ended = true;
        this.menu.hidden = true;
        this.toggleCard(false);
        this.slowOffer.hidden = true;
        this.marker.visible = false;
        this.hush();
        const score = entry.score || [0, 0];
        const names = entry.teams ? summaryTeams(entry) : [t('play.end.left'), t('play.end.right')];
        const header = game.source && game.source.header;
        const store = game.source && game.source.store;
        const frame = store && store.get(store.last);
        const full = entry.ending === 'full time' && header && header.full_match && frame &&
            !!(frame.flags & 1) &&
            frame.step >= header.duration && frame.timeMs >= header.duration * 1800;
        const played = entry.ending === 'full time' || entry.ending === 'episode';
        const title = entry.state === 'failed' || entry.ending === 'policy' ? t('play.end.stopped') :
            full ? t('play.end.fullTime') : played ? t('play.end.episode') : t('play.end.over');
        this.end.setAttribute('aria-label', title);
        const lines = [h('h2', {}, title),
            h('p', { class: 'play-score' }, t('play.end.score', { left: names[0], leftScore: score[0], right: names[1], rightScore: score[1] }))];
        if (entry.error) {
            lines.push(h('p', { class: 'error-text' }, sentence(serverText(entry))));
        } else if (entry.ending === 'timeout') {
            lines.push(h('p', { class: 'muted' }, t('play.end.timeout')));
        }
        if (entry.late) {
            lines.push(h('p', { class: 'muted' }, t('play.end.late', { count: entry.late })));
        }
        if (entry.match) {
            lines.push(h('p', { class: 'muted' }, t('play.end.saved')),
                h('button', { type: 'button', class: 'btn primary', onclick: () => this.app.openMatchInWatch(entry.match) }, icon('watch'), t('play.end.watch')));
        }
        if (game.context) {
            lines.push(h('p', { class: 'muted' }, game.context.label),
                h('button', { type: 'button', class: 'btn', onclick: () => {
                    this.showSetup();
                    game.context.back();
                } }, icon('trophy'), t('play.end.tournament')));
        } else {
            lines.push(h('button', { type: 'button', class: 'btn', onclick: () => this.start() }, icon('replay'), t('play.end.again')),
                h('button', { type: 'button', class: 'btn', onclick: () => this.showSetup() }, icon('plus'), t('play.end.new')));
        }
        lines.push(h('button', { type: 'button', class: 'btn', onclick: () => this.goHome() }, icon('home'), t('play.home')));
        this.endPanel.replaceChildren(...this.challenges.endCard(entry, game, lines));
        this.end.hidden = false;
    }

    // Input settings, kept in the browser, with a tester of every device.

    inputSettings() {
        this.inputNote = h('p', { class: 'muted small', role: 'status' });
        this.keyButtons = {};
        const rows = BINDINGS.map((binding) => {
            const button = h('button', { type: 'button', class: 'btn small key-bind' });
            this.keyButtons[binding.id] = button;
            button.addEventListener('click', () => this.listenKey(binding.id));
            button.addEventListener('keydown', (e) => this.bindKey(e, binding.id));
            button.addEventListener('blur', () => this.listenKey(null));
            return h('tr', {}, h('th', {}, bindingLabel(binding)), h('td', {}, button));
        });
        this.deadZone = h('input', {
            type: 'range', min: String(DEAD_ZONE.min), max: String(DEAD_ZONE.max), step: String(DEAD_ZONE.step),
            'aria-label': t('play.input.deadZone.range'),
        });
        this.deadZoneShown = h('output', { class: 'ability-value' });
        this.deadZone.addEventListener('input', () => {
            this.input.deadZone = Number(this.deadZone.value);
            this.saveInput();
        });
        const options = [['auto', t('play.input.device.auto')], ['keyboard', KEYBOARD],
            ...[0, 1, 2, 3].map((slot) => [`pad${slot}`, t('play.input.device.slot', { slot: slot + 1 })])];
        this.deviceSelects = [0, 1].map((side) => {
            const select = h('select', { 'aria-label': t(side ? 'play.input.device.right.select' : 'play.input.device.left.select') },
                options.map(([value, text]) => h('option', { value }, text)));
            select.addEventListener('change', () => {
                const devices = this.input.devices.slice();
                devices[side] = select.value;
                if (devicesClash(devices)) {
                    select.value = this.input.devices[side];
                    this.inputNote.textContent = t('play.input.device.clash');
                    return;
                }
                this.input.devices = devices;
                this.saveInput();
                this.flush();
            });
            return select;
        });
        this.tester = h('div', { class: 'input-tester', tabindex: '0', 'aria-label': t('play.tester.label') },
            this.testerLines = h('div', { 'aria-live': 'polite' }));
        this.testerKeys = new Set();
        const test = (e, down) => {
            if (e.code === 'Tab' || e.ctrlKey || e.metaKey || e.altKey) {
                return;
            }
            e.preventDefault();
            e.stopPropagation();
            if (down) {
                this.testerKeys.add(e.code);
            } else {
                this.testerKeys.delete(e.code);
            }
            this.updateTester(true);
        };
        this.tester.addEventListener('keydown', (e) => test(e, true));
        this.tester.addEventListener('keyup', (e) => test(e, false));
        this.tester.addEventListener('blur', () => {
            this.testerKeys.clear();
            this.updateTester(true);
        });
        this.inputPanel = h('details', { class: 'input-settings' },
            h('summary', {}, t('play.input.summary')),
            h('p', { class: 'muted small' }, t('play.input.lead')),
            h('table', { class: 'controls-table key-bindings' }, h('tbody', {}, rows)),
            h('div', { class: 'setup-row' },
                h('label', { class: 'field' }, t('play.input.deadZone'), h('div', { class: 'ability' }, this.deadZone, this.deadZoneShown)),
                ...[0, 1].map((side) => h('label', { class: 'field' }, t(side ? 'play.input.device.right' : 'play.input.device.left'), this.deviceSelects[side]))),
            this.inputNote,
            h('h3', {}, t('play.tester.title')),
            this.tester,
            h('div', { class: 'play-row' }, h('button', { type: 'button', class: 'btn', ...symbolOnly(t('play.input.reset')), onclick: () => {
                this.input = defaultSettings();
                this.saveInput();
                this.inputNote.textContent = t('play.input.resetDone');
            } }, icon('reset'))));
        this.inputPanel.addEventListener('toggle', () => this.updateTester(true));
        this.showInput();
        return this.inputPanel;
    }

    // The settings as the panel and the tables show them.
    showInput() {
        for (const binding of BINDINGS) {
            const button = this.keyButtons[binding.id];
            const code = this.input.keys[binding.id];
            button.textContent = this.listening === binding.id ? t('play.input.pressKey') : keyLabel(code);
            button.setAttribute('aria-label', this.listening === binding.id ? t('play.input.bindWaiting', { action: bindingLabel(binding) })
                : t('play.input.bind', { action: bindingLabel(binding), key: keyLabel(code) }));
            button.setAttribute('aria-pressed', String(this.listening === binding.id));
        }
        this.deadZone.value = String(this.input.deadZone);
        this.deadZoneShown.textContent = this.input.deadZone.toFixed(2);
        this.deviceSelects.forEach((select, side) => {
            select.value = this.input.devices[side];
        });
        this.keyTable.replaceChildren(h('h3', {}, KEYBOARD), controlsTable(keyboardControls(this.input)));
    }

    saveInput() {
        this.releaseKeys();
        this.keys = keyMap(this.input);
        if (!saveSettings(this.input)) {
            this.inputNote.textContent = t('play.input.notKept');
        }
        this.showInput();
        this.updateTester(true);
    }

    listenKey(id) {
        if (this.listening === id) {
            return;
        }
        this.listening = id;
        if (id) {
            this.inputNote.textContent = t('play.input.listening');
        }
        this.showInput();
    }

    // The key pressed while a binding waits for one. Tab moves on, Esc keeps the old key, and a
    // reserved, unknown or taken key is refused with the reason.
    bindKey(e, id) {
        if (this.listening !== id || e.code === 'Tab') {
            return;
        }
        e.preventDefault();
        e.stopPropagation();
        if (e.code === 'Escape') {
            this.inputNote.textContent = '';
            this.listenKey(null);
            return;
        }
        const problem = keyProblem(this.input, id, e.code);
        if (problem) {
            this.inputNote.textContent = t(`play.input.problem.${problem}`);
            return;
        }
        this.input.keys = { ...this.input.keys, [id]: e.code };
        this.listening = null;
        this.inputNote.textContent = t('play.input.bound', { action: bindingLabel(BINDINGS.find((b) => b.id === id)), key: keyLabel(e.code) });
        this.saveInput();
    }

    // What each device holds now, read live while the tester shows. The keyboard counts while the
    // tester has focus, and a controller shows its stick past the dead zone and its buttons.
    updateTester(now = false) {
        if (!this.tester || !this.inputPanel.open || this.setupView.hidden) {
            return;
        }
        const time = performance.now();
        if (!now && time - this.testerAt < TESTER_MS) {
            return;
        }
        this.testerAt = time;
        const names = (list) => (list.length ? [...new Set(list)].map(inputName).join(', ') : t('play.tester.nothing'));
        const keys = [...this.testerKeys];
        const mapped = keys.flatMap((code) => this.keys[code] || []);
        const unmapped = keys.filter((code) => !this.keys[code]).map(keyLabel);
        const held = document.activeElement === this.tester ? names(mapped) : t('play.tester.focus');
        const lines = [unmapped.length ? t('play.tester.keyboardUnused', { held, keys: joinAnd(unmapped) }) : t('play.tester.keyboard', { held })];
        const list = navigator.getGamepads ? Array.from(navigator.getGamepads() || []) : [];
        for (const pad of list) {
            const device = pad && pad.connected ? this.pads.get(pad.index) : null;
            if (!device) {
                continue;
            }
            const { held, x, y } = this.padHeld(pad, device.entry.layout);
            lines.push(t('play.tester.pad', { slot: pad.index + 1, x: x.toFixed(2), y: y.toFixed(2), held: names([...held]) }));
        }
        if (lines.length === 1) {
            lines.push(t('play.tester.noPad'));
        }
        const text = lines.join('\n');
        if (text !== this.testerText) {
            this.testerText = text;
            this.testerLines.replaceChildren(...lines.map((line) => h('div', {}, line)));
        }
    }

    // Input.

    onKey(e, down) {
        const mapped = this.keys[e.code];
        if (!down && mapped && this.keyboard.held.size) {
            this.keyboard.set(mapped, false);
            this.flush();
        }
        if (this.padSetup) {
            // The setup panel takes the keyboard, Escape cancels it and Tab and Enter work its buttons.
            if (down && e.code === 'Escape' && this.app.page === 'play') {
                e.preventDefault();
                e.stopImmediatePropagation();
                this.closePadSetup(false);
            }
            return;
        }
        if (this.app.page !== 'play' || !this.game || this.game.ended || !this.game.started) {
            return;
        }
        if (e.defaultPrevented || e.target.closest('input, select, textarea, [contenteditable], .dd-panel, dialog') || e.ctrlKey || e.metaKey || e.altKey) {
            return;
        }
        if (e.code === 'Escape' && down) {
            e.preventDefault();
            e.stopImmediatePropagation();
            if (!this.menu.hidden && !this.card.hidden) {
                this.closeCard();
            } else {
                this.pause(this.menu.hidden);
            }
            return;
        }
        if (e.target.closest('button, a') || !this.menu.hidden) {
            return;
        }
        if (down && e.code === 'KeyH') {
            this.app.toggleHelp();
        } else if (down && e.code === 'KeyM') {
            this.app.setMuted(!this.app.settings.muted);
        } else if (down && e.code === 'KeyF') {
            this.app.toggleFullscreen();
        }
        const names = mapped;
        if (!names) {
            return;
        }
        e.preventDefault();
        e.stopImmediatePropagation();
        if (!this.menu.hidden || e.repeat) {
            return;
        }
        this.use(this.keyboard);
        this.keyboard.set(names, down);
        this.flush();
    }

    releaseKeys() {
        if (this.keyboard.held.size) {
            this.keyboard.held.clear();
            this.flush();
        }
    }

    pollPads() {
        const list = navigator.getGamepads ? Array.from(navigator.getGamepads() || []) : [];
        const seen = new Set();
        for (const pad of list) {
            if (!pad || !pad.connected) {
                continue;
            }
            seen.add(pad.index);
            let device = this.pads.get(pad.index);
            if (!device || device.gpId !== pad.id) {
                device = new Device(`pad${pad.index}`, CONTROLLER);
                device.index = pad.index;
                device.gpId = pad.id;
                device.mapping = pad.mapping;
                device.buttons = {};
                const stored = loadLayouts()[pad.id];
                device.custom = !!(stored && stored.layout);
                device.entry = device.custom ? stored : { style: detectStyle(pad.id), layout: STANDARD };
                this.pads.set(pad.index, device);
                this.notice(this.pads.size > 1 ? t('play.notice.connectedNumber', { number: this.pads.size }) : t('play.notice.connected'));
                if (pad.mapping !== 'standard' && !device.custom && this.built) {
                    this.offerPad = pad.index;
                    this.offer.hidden = false;
                }
            }
            if (this.padSetup) {
                // While the setup shows, no controller plays. The controller being set up works the
                // style choice, then records its presses. Another controller works the buttons of
                // the panel while presses are taken, and before the style is chosen a press on it
                // sets that one up instead, so each person sets up their own.
                const { now, x, y } = this.padHeld(pad, device.entry.layout);
                const before = device.buttons;
                const pressed = POSITIONS.some((pos) => now[pos] && !before[pos]);
                device.buttons = now;
                const s = this.padSetup;
                const mine = s.index === pad.index;
                const works = mine ? s.step < 0 : s.step >= 0;
                const move = this.navStep(device, this.navDirection(device, now, x, y), works);
                if (mine && s.step >= 0) {
                    this.recordPad(pad);
                } else if (works) {
                    this.navigate([this.setupBox], (pos) => now[pos] && !before[pos], move);
                } else if (pressed) {
                    this.lastPad = device;
                    this.padSetup = { ...this.padSetup, index: pad.index, id: pad.id, style: device.entry.style, layout: { ...device.entry.layout } };
                    this.renderSetup();
                }
                continue;
            }
            this.readPad(pad, device);
        }
        this.updateTester();
        for (const [index, device] of this.pads) {
            if (!seen.has(index)) {
                this.pads.delete(index);
                device.held.clear();
                if (this.padSetup && this.padSetup.index === index) {
                    this.closePadSetup(false);
                }
                this.notice(t('play.notice.disconnected'));
                this.flush();
            }
        }
    }

    // The positions a controller holds in a layout, and the actions they press.
    padHeld(pad, layout) {
        const button = (i) => !!(pad.buttons[i] && (pad.buttons[i].pressed || pad.buttons[i].value > AXIS_ON));
        const axis = (src) => (src && src.a !== undefined ? src.s * (pad.axes[src.a] || 0) : 0);
        const on = (src) => {
            if (!src) {
                return false;
            }
            if (src.b !== undefined) {
                return button(src.b);
            }
            if (src.v !== undefined) {
                return hatOn(pad.axes[src.a], src.v);
            }
            return axis(src) > (src.t ?? AXIS_ON);
        };
        const now = {};
        for (const pos of POSITIONS) {
            now[pos] = on(layout[pos]);
        }
        const held = new Set();
        for (const [pos, names] of Object.entries(PAD_BUTTONS)) {
            if (now[pos]) {
                names.forEach((n) => held.add(n));
            }
        }
        const x = axis(layout.stickX);
        const y = axis(layout.stickY);
        // The stick counts along each axis past the dead zone of the input settings.
        stickDirections(x, y, this.input.deadZone).forEach((name) => held.add(name));
        return { now, held, x, y };
    }

    readPad(pad, device) {
        const { now, held, x, y } = this.padHeld(pad, device.entry.layout);
        const before = device.buttons;
        device.buttons = now;
        const edge = (pos) => now[pos] && !before[pos];
        const scopes = this.navScopes();
        const move = this.navStep(device, this.navDirection(device, now, x, y), !!scopes);
        const live = this.game && !this.game.ended && this.game.started && this.app.page === 'play';
        if (live && edge('start')) {
            // The controller that opens the menu is the one its setup button sets up.
            this.lastPad = device;
            this.pause(this.menu.hidden);
            return;
        }
        if (live && edge('back')) {
            this.lastPad = device;
            this.toggleCard(this.card.hidden);
        }
        if (scopes) {
            // A button pressed in a menu stays out of play until it is released, so the press that
            // picks Resume or Play again passes no ball.
            device.navHeld = new Set([...held].filter((n) => !DIRECTIONS.has(n) && !device.held.has(n)));
            this.navigate(scopes, edge, move);
            return;
        }
        if (!live) {
            return;
        }
        if (device.navHeld) {
            for (const n of device.navHeld) {
                if (held.has(n)) {
                    held.delete(n);
                } else {
                    device.navHeld.delete(n);
                }
            }
        }
        const same = held.size === device.held.size && [...held].every((n) => device.held.has(n));
        if (same) {
            return;
        }
        for (const n of held) {
            if (!device.held.has(n) && !DIRECTIONS.has(n)) {
                device.pressed.add(n);
            }
        }
        device.held = held;
        device.usedAt = performance.now();
        this.use(device);
        this.flush();
    }

    // Menu navigation by controller.

    // The parts of the page that a controller works as a menu, or null while the buttons play.
    navScopes() {
        if (!this.built || this.app.page !== 'play') {
            return null;
        }
        if (this.padSetup) {
            return [this.setupBox];
        }
        const offer = this.offer.hidden ? [] : [this.offer];
        if (!this.setupView.hidden) {
            return [this.setupView, ...offer];
        }
        if (!this.end.hidden) {
            return [this.end];
        }
        if (!this.menu.hidden) {
            return [this.menu, ...(this.card.hidden ? [] : [this.card]), ...offer];
        }
        return null;
    }

    // The direction a controller points, the D-pad first, then the left stick past half way.
    navDirection(device, now, x, y) {
        const pull = { left: -x, right: x, up: -y, down: y };
        const dpad = [...DIRECTIONS].find((d) => now[d]);
        if (device.navDir === 'held') {
            return dpad || Object.values(pull).some((v) => v > NAV_RELEASE) ? 'held' : null;
        }
        if (dpad) {
            return dpad;
        }
        if (device.navDir && pull[device.navDir] > NAV_RELEASE) {
            return device.navDir;
        }
        const best = Object.keys(pull).reduce((a, b) => (pull[b] > pull[a] ? b : a));
        return pull[best] > STICK ? best : null;
    }

    // The move a direction makes this frame, once on its press and then repeated while held. The
    // direction is followed during play too, so a menu that opens under a held stick waits for a
    // fresh push.
    navStep(device, dir, active) {
        const time = performance.now();
        let move = null;
        if (dir !== device.navDir) {
            move = dir;
            device.navAt = time + NAV_DELAY_MS;
        } else if (dir && device.navAt && time >= device.navAt) {
            move = dir;
            device.navAt = time + NAV_REPEAT_MS;
        }
        device.navDir = dir;
        if (!active || dir === 'held') {
            device.navAt = 0;
            return null;
        }
        return move;
    }

    navTargets(scopes) {
        return scopes.flatMap((scope) => [...scope.querySelectorAll(FOCUSABLE)])
            .filter((el) => !el.disabled && !el.closest('[hidden]') && el.getClientRects().length);
    }

    // South works the focused control, east goes back, and a direction moves the focus in reading
    // order, or changes a select or a slider with left and right. The first press focuses the main
    // action of the menu.
    navigate(scopes, edge, move) {
        if (edge('east')) {
            this.navBack();
            return;
        }
        const south = edge('south');
        if (!south && !move) {
            return;
        }
        const targets = this.navTargets(scopes);
        const el = document.activeElement;
        const at = targets.indexOf(el);
        if (at < 0) {
            const first = targets.find((t) => t.classList.contains('primary')) || targets[0];
            if (first) {
                padFocus(first);
            }
            return;
        }
        if (south) {
            this.navActivate(el);
            return;
        }
        if ((move === 'left' || move === 'right') && this.navAdjust(el, move === 'right' ? 1 : -1)) {
            return;
        }
        const next = targets[at + (move === 'up' || move === 'left' ? -1 : 1)];
        if (next) {
            padFocus(next);
        }
    }

    // A select steps to its next option and wraps, a slider waits for left and right, and any
    // other control takes a click, which toggles a checkbox.
    navActivate(el) {
        if (el.tagName === 'SELECT') {
            if (el.options.length) {
                el.selectedIndex = (el.selectedIndex + 1) % el.options.length;
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }
        } else if (el.type !== 'range') {
            el.click();
        }
    }

    // Left and right change a select or a slider directly, and report whether they did.
    navAdjust(el, step) {
        if (el.tagName === 'SELECT') {
            const i = el.selectedIndex + step;
            if (i >= 0 && i < el.options.length) {
                el.selectedIndex = i;
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }
            return true;
        }
        if (el.type === 'range') {
            if (step > 0) {
                el.stepUp();
            } else {
                el.stepDown();
            }
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }
        return false;
    }

    // East closes the setup panel or the controls card, resumes from the pause menu, and leaves
    // the end card for the setup, as Esc does.
    navBack() {
        if (this.padSetup) {
            this.closePadSetup(false);
        } else if (!this.menu.hidden && !this.card.hidden) {
            const inside = this.card.contains(document.activeElement);
            this.closeCard();
            if (inside) {
                padFocus(this.controlsButton);
            }
        } else if (!this.menu.hidden) {
            this.pause(false);
        } else if (!this.end.hidden) {
            this.showSetup();
        }
    }

    // The devices of each person's side. One person takes every device. Two people take the
    // devices the input settings name for their sides, and a side left to the page takes, of the
    // devices the other side leaves, the keyboard and the first controller for the left and the
    // second controller for the right, or with one controller, the keyboard and the controller.
    devicesOf(side) {
        const pads = [...this.pads.keys()].sort((a, b) => a - b).map((i) => this.pads.get(i));
        // The touch screen, once its controls exist, goes with the keyboard.
        const keys = this.touch ? [this.keyboard, this.touch] : [this.keyboard];
        const all = [...keys, ...pads];
        if (!this.game || !this.game.humans[0] || !this.game.humans[1]) {
            return all;
        }
        const [own, other] = [this.input.devices[side], this.input.devices[1 - side]];
        const named = (device, id) => device.id === id || (id === 'keyboard' && device === this.touch);
        if (own !== 'auto') {
            return all.filter((device) => named(device, own));
        }
        if (other !== 'auto') {
            return all.filter((device) => !named(device, other));
        }
        if (pads.length >= 2) {
            return side === 0 ? [...keys, pads[0]] : [pads[1]];
        }
        return side === 0 ? keys : pads.slice(0, 1);
    }

    activeOf(side) {
        const devices = this.devicesOf(side);
        return devices.reduce((best, d) => (!best || d.usedAt > best.usedAt ? d : best), null);
    }

    // Whichever device was used last drives its side, and a change shows its controls.
    use(device) {
        const pad = device !== this.keyboard && device !== this.touch;
        const changed = this.lastDevice !== device.label || (pad && this.lastPad !== device);
        if (pad) {
            this.lastPad = device;
            this.refreshStyle();
        }
        if (changed) {
            this.lastDevice = device.label;
            if (this.game && this.game.started) {
                this.toggleCard(true, 5000);
            }
        }
        this.updateStatus();
    }

    flush() {
        const game = this.game;
        if (!game || game.ended || !game.started) {
            return;
        }
        game.humans.forEach((human, side) => {
            if (human) {
                this.send(side, false);
            }
        });
    }

    async send(side, always) {
        const game = this.game;
        const device = this.activeOf(side);
        const held = device ? [...device.held].sort() : [];
        const pressed = device ? [...device.pressed] : [];
        const key = held.join(',');
        if (!always && !pressed.length && game.sent[side] === key) {
            return;
        }
        if (game.busy) {
            game.dirty = true;
            return;
        }
        if (device) {
            device.pressed.clear();
        }
        game.sent[side] = key;
        game.busy = true;
        try {
            this.apply(await api.gameInput(game.id, { side, held, pressed }));
        } catch {
            // The heartbeat sends again.
        } finally {
            game.busy = false;
        }
        if (game.dirty) {
            game.dirty = false;
            this.flush();
        }
    }

    heartbeat() {
        const game = this.game;
        if (!game || game.ended || !game.started || game.busy) {
            return;
        }
        const side = game.humans[0] ? 0 : 1;
        this.send(side, true);
    }

    // Notices and cards.

    notice(text) {
        if (this.app.page === 'play') {
            this.app.hud.toast(text, 'info', 3000);
        }
        this.refreshStyle();
        this.updatePadNote();
        this.updateStatus();
    }

    // The controller in use, the last one used or else the first.
    activePad() {
        if (this.lastPad && this.pads.get(this.lastPad.index) === this.lastPad) {
            return this.lastPad;
        }
        const first = [...this.pads.keys()].sort((a, b) => a - b)[0];
        return first === undefined ? null : this.pads.get(first);
    }

    // The number of a controller, by the order the browser lists them.
    padNumber(index) {
        return [...this.pads.keys()].sort((a, b) => a - b).indexOf(index) + 1;
    }

    padStyle() {
        const pad = this.activePad();
        return pad ? pad.entry.style : 'xbox';
    }

    // What the browser reports of the controller in use, to tell a standard one from a custom one.
    padReport(pad) {
        const mapping = t(pad.mapping === 'standard' ? 'play.pad.mapping.standard' : 'play.pad.mapping.custom');
        return t(pad.custom ? 'play.pad.reportSetUp' : 'play.pad.report', { id: pad.gpId, mapping });
    }

    // The tables, the pause menu and the Help page draw the style of the controller in use.
    refreshStyle() {
        const style = this.padStyle();
        if (!this.built || style === this.shownStyle) {
            return;
        }
        this.shownStyle = style;
        const name = PAD_STYLES[style].name;
        this.padTable.replaceChildren(h('h3', {}, t('play.controls.pad', { style: name })), controlsTable(PAD_CONTROLS, style));
        this.menuHint.replaceChildren(...tn('play.pause.hint', { select: padIcon(style, 'south'), resume: padIcon(style, 'east') }));
        const help = document.querySelector('.pad-help');
        if (help) {
            help.replaceChildren(...padHelp(style));
        }
    }

    // The report line of a controller and the action that sets it up.
    padTools(pad) {
        return pad ? [h('p', { class: 'muted small pad-report' }, this.padReport(pad)),
            h('button', { type: 'button', class: 'btn', ...symbolOnly(t('play.padSetup.open')), onclick: () => this.openPadSetup() }, icon('gamepad'))] : [];
    }

    updatePadNote() {
        if (this.padNote) {
            const n = this.pads.size;
            const pad = this.activePad();
            this.padNote.replaceChildren(
                h('p', {}, n ? t('play.pads.connected', { count: n }) : t('play.pads.none')),
                ...this.padTools(pad));
            this.menuHint.hidden = !n;
        }
    }

    updateStatus() {
        if (!this.status) {
            return;
        }
        const pads = this.pads.size;
        const parts = [`${this.lastDevice || KEYBOARD}`];
        if (pads && this.lastDevice !== CONTROLLER) {
            parts.push(t('play.status.pads', { count: pads }));
        }
        const entry = this.game && this.game.entry;
        // The engine's action of each person, as the game last reported it, once every second or
        // so, which shows what GRF's controller logic made of the keys and buttons.
        const taken = entry && Array.isArray(entry.actions) ? entry.actions : [];
        const two = this.game && this.game.humans[0] && this.game.humans[1];
        taken.forEach((action, side) => {
            if (typeof action === 'number') {
                // GRF keeps a held direction, sprint and dribble as sticky actions, so the engine
                // takes no new action while they stay held, and the line names what is held.
                const where = two ? (side ? '.right' : '.left') : '';
                parts.push(action === 0 ? t(`play.status.idle${where}`) : t(`play.status.action${where}`, { action: engineAction(action) }));
                parts.push(...this.heldParts(side, action));
            }
        });
        const late = entry && entry.late;
        if (late) {
            parts.push(t('play.status.late', { count: late }));
        }
        this.status.textContent = parts.join(', ');
    }

    // The sticky actions that a person's side holds, the direction while the engine's action is
    // none of the directions, then sprint and dribble, each as a part of the status line.
    heldParts(side, action) {
        const device = this.game && this.game.humans[side] ? this.activeOf(side) : null;
        if (!device) {
            return [];
        }
        const parts = [];
        const direction = action === 0 || action > 8 ? this.heldDirection(side) : null;
        if (direction) {
            parts.push(t('play.status.held.direction', { direction }));
        }
        for (const name of ['sprint', 'dribble']) {
            if (device.held.has(name)) {
                parts.push(t(`play.status.held.${name}`));
            }
        }
        return parts;
    }

    // The direction a person's side holds, as GRF names its sticky direction, or null.
    heldDirection(side) {
        const device = this.game && this.game.humans[side] ? this.activeOf(side) : null;
        if (!device) {
            return null;
        }
        const vertical = ['up', 'down'].find((n) => device.held.has(n) && !device.held.has(n === 'up' ? 'down' : 'up'));
        const horizontal = ['left', 'right'].find((n) => device.held.has(n) && !device.held.has(n === 'left' ? 'right' : 'left'));
        const names = [vertical, horizontal].filter(Boolean).map((n) => STICKY_NAMES[n]);
        // The names join as one of GRF's directions, such as top left, in the page's language.
        return names.length ? tOr(`play.engineAction.${names.join('_')}`, names.join(' ')) : null;
    }

    // The controls card from the pause menu, a dialog that takes the focus until Esc or the
    // back button closes it, and gives the focus back to Controls.
    openCard() {
        // The card hides and shows again, so the dialogs of the page take it up and focus it.
        this.card.hidden = true;
        this.toggleCard(true);
        this.card.setAttribute('role', 'dialog');
        this.card.setAttribute('aria-label', t('play.card.dialog.label'));
    }

    closeCard() {
        const inside = this.card.contains(document.activeElement);
        this.toggleCard(false);
        if (inside) {
            this.controlsButton.focus();
        }
    }

    toggleCard(on, ms = 0) {
        clearTimeout(this.cardTimer);
        if (this.card.hidden && this.card.getAttribute('role') === 'dialog') {
            // A card that shows during play is no dialog, so it never takes the focus of the game.
            this.card.removeAttribute('role');
            this.card.removeAttribute('aria-label');
            this.card.removeAttribute('tabindex');
        }
        const pad = this.activePad();
        if (pad && this.lastDevice === CONTROLLER) {
            const style = pad.entry.style;
            this.card.replaceChildren(h('h3', {}, t('play.controls.pad', { style: PAD_STYLES[style].name })), controlsTable(PAD_CONTROLS, style), ...this.padTools(pad));
        } else {
            this.card.replaceChildren(h('h3', {}, KEYBOARD), controlsTable(keyboardControls(this.input)), ...this.padTools(pad));
        }
        this.card.hidden = !on;
        if (on && ms) {
            this.cardTimer = setTimeout(() => {
                this.card.hidden = true;
            }, ms);
        }
    }

    // The controller setup, which asks the style of the controller, then each button in turn by
    // its position, and keeps the layout for the controller's id.

    openPadSetup(index = null) {
        const pad = (index !== null && this.pads.get(index)) || this.activePad();
        if (!this.built || !pad) {
            this.app.hud.toast(t('play.toast.noPad'), 'info', 4000);
            return;
        }
        if (this.playing) {
            this.pause(true);
        }
        // The notice of a controller without the standard layout comes back on Cancel, unless
        // the setup saved a layout for that controller.
        const offered = !this.offer.hidden;
        this.offer.hidden = true;
        this.card.hidden = true;
        this.padSetup = {
            index: pad.index, id: pad.gpId, style: pad.entry.style,
            layout: { ...pad.entry.layout }, step: -1, armed: false, still: null, stillAt: 0, rest: [],
            back: document.activeElement, offered,
        };
        this.setupPanel.hidden = false;
        this.renderSetup();
    }

    closePadSetup(save) {
        const s = this.padSetup;
        if (!s) {
            return;
        }
        this.padSetup = null;
        this.setupPanel.hidden = true;
        const device = this.pads.get(s.index);
        if (save) {
            const entry = { style: s.style, layout: s.layout };
            saveLayout(s.id, entry);
            if (device) {
                device.entry = entry;
                device.custom = true;
                // The new layout reads the buttons still held differently, so each waits for its release.
                device.buttons = Object.fromEntries(POSITIONS.map((pos) => [pos, true]));
                device.navDir = 'held';
                device.navAt = 0;
            }
            this.shownStyle = null;
            this.app.hud.toast(t('play.toast.padSaved'), 'info', 4000);
        }
        const offeredPad = this.offerPad !== null ? this.pads.get(this.offerPad) : null;
        if (s.offered && offeredPad && !offeredPad.custom) {
            this.offer.hidden = false;
        }
        this.refreshStyle();
        this.updatePadNote();
        if (!this.menu.hidden) {
            this.resumeButton.focus();
        } else if (s.back && s.back.isConnected) {
            s.back.focus();
        }
    }

    setupStep(step) {
        const s = this.padSetup;
        s.step = step;
        s.armed = false;
        if (step >= SETUP_STEPS.length) {
            this.closePadSetup(true);
            return;
        }
        this.renderSetup();
    }

    renderSetup() {
        const s = this.padSetup;
        const button = (text, onclick, cls = 'btn') => h('button', { type: 'button', class: cls, onclick }, text);
        const cancel = h('button', { type: 'button', class: 'btn', ...symbolOnly(t('play.padSetup.cancel')), onclick: () => this.closePadSetup(false) }, icon('close'));
        if (s.step < 0) {
            const choices = Object.entries(PAD_STYLES).map(([style, info]) => {
                const b = button(info.name, () => {
                    s.style = style;
                    this.setupStep(0);
                }, style === s.style ? 'btn primary' : 'btn');
                b.setAttribute('aria-pressed', String(style === s.style));
                return b;
            });
            this.setupBox.replaceChildren(h('h2', {}, t('play.padSetup.open')),
                h('p', {}, t('play.padSetup.style')),
                h('div', { class: 'pad-setup-row' }, choices),
                h('p', { class: 'muted small' }, t('play.padSetup.which', { number: this.padNumber(s.index), id: s.id })),
                ...(this.pads.size > 1 ? [h('p', { class: 'muted small' }, t('play.padSetup.another'))] : []),
                h('div', { class: 'pad-setup-row' }, cancel));
            choices[Object.keys(PAD_STYLES).indexOf(s.style)].focus();
            return;
        }
        const pos = SETUP_STEPS[s.step];
        let prompt;
        if (pos === 'stickX') {
            prompt = t('play.padSetup.stickX');
        } else if (pos === 'stickY') {
            prompt = t('play.padSetup.stickY');
        } else if (DIRECTIONS.has(pos)) {
            prompt = t(`play.padSetup.dpad.${pos}`);
        } else {
            prompt = t('play.padSetup.press', { button: padInfo(s.style, pos)[3] });
        }
        const icon = pos.startsWith('stick') ? 'stick' : DIRECTIONS.has(pos) ? 'dpad' : pos;
        const sketch = h('div', { class: 'pad-sketch-box' });
        sketch.innerHTML = padSketch(s.style, pos);
        const skip = button(t('play.padSetup.skip'), () => this.setupStep(s.step + 1));
        this.setupBox.replaceChildren(h('h2', {}, t('play.padSetup.open')),
            h('p', { class: 'muted small' }, t('play.padSetup.step', { step: s.step + 1, total: SETUP_STEPS.length, style: PAD_STYLES[s.style].name })),
            h('p', { class: 'pad-prompt keys', 'aria-live': 'polite' }, padIcon(s.style, icon), prompt),
            sketch,
            h('p', { class: 'muted small' }, t('play.padSetup.release')),
            h('div', { class: 'pad-setup-row' }, button(t('play.padSetup.back'), () => this.setupStep(s.step - 1)), skip, cancel));
        skip.focus();
    }

    // One frame of the controller being set up. It waits until every button is up and the axes
    // rest for a moment, then takes the first button pressed, or the first axis that moves well
    // away from its rest past the threshold, with the sign of the move.
    recordPad(pad) {
        const s = this.padSetup;
        if (s.step < 0) {
            return;
        }
        const time = performance.now();
        const axes = Array.from(pad.axes);
        if (!s.still || axes.some((v, i) => Math.abs(v - (s.still[i] ?? 0)) > 0.1)) {
            s.still = axes;
            s.stillAt = time;
        }
        const pressed = pad.buttons.map((b) => !!(b && (b.pressed || b.value > AXIS_ON)));
        if (!s.armed) {
            if (!pressed.some(Boolean) && time - s.stillAt > 250) {
                s.armed = true;
                s.rest = s.still;
            }
            return;
        }
        const pos = SETUP_STEPS[s.step];
        let src = null;
        const button = pressed.indexOf(true);
        if (button >= 0 && !pos.startsWith('stick')) {
            src = { b: button };
        }
        for (let i = 0; !src && i < axes.length; i++) {
            const rest = s.rest[i] ?? 0;
            const move = axes[i] - rest;
            const sign = move > 0 ? 1 : -1;
            if (Math.abs(move) <= 0.6) {
                continue;
            }
            // A D-pad that reports as one hat axis rests outside the range of a stick and gives
            // each direction a value of its own, which is stored as it is.
            if (Math.abs(rest) > 1.05 || (DIRECTIONS.has(pos) && Math.abs(axes[i]) < 0.9)) {
                src = { a: i, v: axes[i] };
            } else if (sign * axes[i] > AXIS_ON) {
                src = { a: i, s: sign, t: AXIS_ON };
            }
        }
        if (src) {
            s.layout[pos] = src;
            this.setupStep(s.step + 1);
        }
    }

    // The marker, an arrow in the team's color over each person's player.

    makeMarker() {
        const group = new THREE.Group();
        group.visible = false;
        this.arrows = [0, 1].map(() => {
            const geometry = new THREE.ConeGeometry(0.28, 0.6, 16);
            geometry.rotateX(Math.PI);
            const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color: 0xffffff, depthTest: false, transparent: true, opacity: 0.95 }));
            mesh.renderOrder = 10;
            group.add(mesh);
            return mesh;
        });
        this.app.view.scene.add(group);
        return group;
    }

    // The frame rate of the picture while a game plays, which offers a lower quality once for each
    // visit below the rate at which Watch offers the 2D view, and never after it was declined.
    measureFrames(on) {
        const now = performance.now();
        const dt = this.slowAt ? (now - this.slowAt) / 1000 : 0;
        this.slowAt = now;
        if (!on || this.game.paused || document.hidden || dt <= 0 || dt > 1) {
            this.slowFrames = 0;
            this.slowSeconds = 0;
            return;
        }
        this.slowFrames = (this.slowFrames || 0) + 1;
        this.slowSeconds = (this.slowSeconds || 0) + dt;
        if (this.slowSeconds < SLOW_WINDOW) {
            return;
        }
        const fps = this.slowFrames / this.slowSeconds;
        this.slowFrames = 0;
        this.slowSeconds = 0;
        let declined = false;
        try {
            declined = localStorage.getItem(SLOW_DECLINED) === 'true';
        } catch {
            // Without storage the offer shows once for this visit.
        }
        if (fps >= SLOW_FPS || this.slowOffered || declined || this.app.settings.quality === 'low'
            || !offersView2d(location.search)) {
            return;
        }
        this.slowOffered = true;
        const rate = Math.max(1, Math.round(fps));
        this.slowText.textContent = t('play.slow.text', { count: rate });
        this.slowOffer.hidden = false;
    }

    placeMarker(pose, s) {
        const game = this.game;
        const on = !!(game && game.started && !game.ended && this.app.source === game.source && this.app.page === 'play' && s.a);
        this.measureFrames(on);
        this.marker.visible = on;
        if (!on) {
            return;
        }
        const header = game.source.header;
        const bob = Math.sin(performance.now() / 180) * 0.08;
        for (let side = 0; side < 2; side++) {
            const arrow = this.arrows[side];
            // On a side shared with a registered team the frames mark every player of its agents,
            // so the game names the person's own player.
            const own = game.entry && game.entry.controlled ? game.entry.controlled[side] : null;
            const k = !game.humans[side] ? -1 : typeof own === 'number'
                ? header.players.findIndex((p) => p.team === side && p.index === own)
                : header.players.findIndex((p, i) => p.team === side && (s.a.playerFlags[i] & 8));
            arrow.visible = k >= 0;
            if (k < 0) {
                continue;
            }
            const style = this.app.styles && this.app.styles[side];
            if (style) {
                const c = style.kit.primary;
                arrow.material.color.setRGB(c[0] / 255, c[1] / 255, c[2] / 255, THREE.SRGBColorSpace);
            }
            const o = k * PLAYER_FLOATS;
            arrow.position.set(pose.nodes[o], 2.55 + bob, -pose.nodes[o + 1]);
        }
    }
}
