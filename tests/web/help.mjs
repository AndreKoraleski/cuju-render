// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the Help page's guided tour, hands-on lessons, diagnostic report and service worker,
// run from the repository root with `node tests/web/help.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import vm from 'node:vm';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from a copy of the whole folder beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-help-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js', import.meta.url)), folder, { recursive: true });
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const load = (name) => import(pathToFileURL(join(folder, name)).href);
const tour = await load('help/tour-core.js');
const lessons = await load('help/lessons-core.js');
const { reportText } = await load('help/doctor.js');
const { installable, workerBuild } = await load('help/pwa.js');
const web = new URL('../../src/cuju/render/web/', import.meta.url);
const catalog = JSON.parse(readFileSync(new URL('lessons.json', web), 'utf8')).lessons;
const ids = catalog.map((lesson) => lesson.id);
const plain = (text) => !/[;:()!]/.test(text) && !/ - |—|–/.test(text);

test('the tour has a step on each page that the task names, in words alone', () => {
    const pages = new Set(tour.TOUR_STEPS.map((step) => step.page));
    for (const page of ['home', 'watch', 'play', 'teams', 'tournaments', 'help']) {
        assert.ok(pages.has(page), page);
    }
    assert.ok(tour.TOUR_STEPS.some((step) => step.id === 'challenges'));
    assert.ok(tour.TOUR_STEPS.some((step) => step.id === 'settings'));
    assert.equal(new Set(tour.TOUR_STEPS.map((step) => step.id)).size, tour.TOUR_STEPS.length);
    for (const step of tour.TOUR_STEPS) {
        assert.ok(plain(step.text) && plain(step.title), step.id);
        assert.ok(!step.needs || step.needs in tour.NEED_OFFERS, step.id);
    }
});

test('the tour moves, ends past its last step and resumes where it stopped', () => {
    const count = tour.TOUR_STEPS.length;
    assert.deepEqual(tour.tourState(null), { step: 0, done: false, started: false });
    assert.deepEqual(tour.tourState({ step: 99, done: 'yes', started: true }), { step: count - 1, done: false, started: true });
    assert.deepEqual(tour.tourState({ step: -3 }), { step: 0, done: false, started: false });
    assert.deepEqual(tour.moveTour({ step: 2, started: true }, 1), { step: 3, done: false, started: true });
    assert.deepEqual(tour.moveTour({ step: 0 }, -1), { step: 0, done: false, started: true });
    assert.deepEqual(tour.moveTour({ step: count - 1 }, 1), { step: 0, done: true, started: false });
    assert.equal(tour.resumeStep({ step: 4, started: true }), 4);
    assert.equal(tour.resumeStep({ step: 4, started: true, done: true }), 0);
    assert.equal(tour.resumeStep({ step: 4 }), 0);
});

test('a step shows once its need is there, and says so to a screen reader', () => {
    const watch = tour.TOUR_STEPS.find((step) => step.needs === 'recording');
    assert.equal(tour.needMet(watch, { recording: false }), false);
    assert.equal(tour.needMet(watch, { recording: true }), true);
    assert.equal(tour.needMet(tour.TOUR_STEPS[0], {}), true);
    const words = tour.stepAnnouncement(tour.TOUR_STEPS[0], 0);
    assert.ok(words.startsWith(`Step 1 of ${tour.TOUR_STEPS.length}. Home.`));
    assert.ok(tour.stepAnnouncement(tour.TOUR_STEPS[0], 0, 11, false).endsWith('This control shows once its page has it.'));
});

test('the card goes below its target, above it near the bottom, and stays in the window', () => {
    const view = { width: 800, height: 600 };
    const card = { width: 360, height: 200 };
    const below = tour.placeCard({ left: 10, top: 10, width: 40, height: 30, bottom: 40 }, card, view);
    assert.deepEqual(below, { left: 12, top: 52, side: 'below' });
    const above = tour.placeCard({ left: 700, top: 500, width: 60, height: 40, bottom: 540 }, card, view);
    assert.equal(above.side, 'above');
    assert.ok(above.left + card.width <= view.width - 12 && above.top === 288);
    assert.equal(tour.placeCard(null, card, view).side, 'none');
    const tall = tour.placeCard({ left: 100, top: 150, width: 60, height: 300, bottom: 450 }, card, view);
    assert.equal(tall.side, 'over');
    const narrow = tour.placeCard(null, { width: 360, height: 200 }, { width: 320, height: 500 });
    assert.equal(narrow.left, 12);
});

test('the catalog of lessons holds the eight lessons of the task, each with agent steps', () => {
    assert.deepEqual(ids, ['open_sample', 'seek_goal', 'switch_camera', 'follow_player', 'play_game', 'register_team', 'start_challenge', 'make_photo']);
    const checks = new Set(['recording', 'match_played', 'team', 'challenge', 'page']);
    for (const lesson of catalog) {
        assert.ok(plain(lesson.ask) && plain(lesson.praise) && plain(lesson.title), lesson.id);
        assert.ok(checks.has(lesson.agent.check), lesson.id);
        assert.ok(lesson.agent.steps.length > 0 && lesson.agent.steps.every((step) => step.say && (step.run || step.python || step.http || step.script)), lesson.id);
        assert.ok(['home', 'watch', 'play', 'teams'].includes(lesson.page), lesson.id);
    }
});

test('progress keeps known lessons, the first time of each, and finds the next one', () => {
    assert.deepEqual(lessons.progressState({ done: { seek_goal: 'a', nowhere: 'b', play_game: 3 }, current: 'nowhere' }, ids), { done: { seek_goal: 'a' }, current: null });
    let progress = lessons.markDone(null, 'open_sample', 't1', ids);
    progress = lessons.markDone(progress, 'open_sample', 't2', ids);
    assert.equal(progress.done.open_sample, 't1');
    assert.deepEqual(lessons.markDone(progress, 'nowhere', 't3', ids), progress);
    assert.equal(lessons.nextLesson(progress, ids), 'seek_goal');
    assert.equal(lessons.nextLesson(progress, ids, 'make_photo'), 'seek_goal');
    assert.equal(lessons.nextLesson(progress, ids, 'switch_camera'), 'follow_player');
    const all = ids.reduce((state, id) => lessons.markDone(state, id, 'x', ids), null);
    assert.equal(lessons.nextLesson(all, ids), null);
    assert.equal(lessons.doneCount(all, ids), 8);
});

const snap = (fields) => ({ at: 0, source: { kind: 'match', id: 'm' }, t: 0, sps: 10, playing: false, speed: 1, goals: [], camera: 'broadcast', ...fields });

test('a recording that opens ends the first lesson, a game of Play does not', () => {
    assert.equal(lessons.checkLesson('open_sample', snap({})), true);
    assert.equal(lessons.checkLesson('open_sample', snap({ source: { kind: 'file', id: 'f' } })), true);
    assert.equal(lessons.checkLesson('open_sample', snap({ source: null })), false);
    assert.equal(lessons.needMet(catalog[0], snap({ source: null })), false);
});

test('a jump to a goal counts, playing up to it does not', () => {
    const memory = {};
    const goals = [1000];
    assert.equal(lessons.checkLesson('seek_goal', snap({ t: 100, goals, at: 0, playing: true }), null, memory), false);
    // Playing for 40 seconds moves 400 frames, which is no jump.
    assert.equal(lessons.checkLesson('seek_goal', snap({ t: 500, goals, at: 40000, playing: true }), null, memory), false);
    assert.equal(memory.jumps, undefined);
    // N lands six seconds before the goal.
    assert.equal(lessons.checkLesson('seek_goal', snap({ t: 940, goals, at: 40400 }), null, memory), true);
    const away = {};
    lessons.checkLesson('seek_goal', snap({ t: 100, goals }), null, away);
    assert.equal(lessons.checkLesson('seek_goal', snap({ t: 600, goals, at: 400 }), null, away), false);
    assert.equal(away.jumps, 1);
    assert.equal(lessons.atGoal(snap({ t: 1040, goals })), true);
    assert.equal(lessons.atGoal(snap({ t: 1041, goals })), false);
    assert.equal(lessons.jumped(snap({ t: 0 }), snap({ t: 900, source: { kind: 'match', id: 'other' } })), false);
});

test('a camera that a person chooses ends the camera lessons, a show of the page does not', () => {
    const memory = {};
    assert.equal(lessons.checkLesson('switch_camera', snap({ camera: 'scripted' }), null, memory), false);
    assert.equal(lessons.checkLesson('switch_camera', snap({ camera: 'broadcast' }), null, memory), false);
    assert.equal(lessons.checkLesson('switch_camera', snap({ camera: 'podium' }), null, memory), false);
    assert.equal(lessons.checkLesson('switch_camera', snap({ camera: 'tactical' }), null, memory), true);
    assert.equal(lessons.checkLesson('follow_player', snap({ camera: 'player' })), true);
    assert.equal(lessons.checkLesson('follow_player', snap({ camera: 'owner' })), true);
    assert.equal(lessons.checkLesson('follow_player', snap({ camera: 'ball' })), false);
    assert.equal(lessons.checkLesson('follow_player', snap({ camera: 'player', source: null })), false);
});

test('thirty seconds of a game, a team, a challenge and a new photo end their lessons', () => {
    const memory = {};
    const game = (step, running = true, id = 'g1') => snap({ game: { id, running, step } });
    assert.equal(lessons.checkLesson('play_game', game(20), null, memory), false);
    assert.equal(lessons.checkLesson('play_game', game(319, false), null, memory), false);
    assert.equal(lessons.checkLesson('play_game', game(320), null, memory), true);
    const other = {};
    lessons.checkLesson('play_game', game(10, true, 'g1'), null, other);
    assert.equal(lessons.checkLesson('play_game', game(200, true, 'g2'), null, other), false);
    assert.equal(lessons.checkLesson('play_game', snap({ game: null }), null, {}), false);
    assert.equal(lessons.checkLesson('register_team', snap({ teams: 0 })), false);
    assert.equal(lessons.checkLesson('register_team', snap({ teams: 1 })), true);
    assert.equal(lessons.checkLesson('register_team', snap({ teams: null })), false);
    assert.equal(lessons.checkLesson('start_challenge', snap({ challenge: true })), true);
    assert.equal(lessons.checkLesson('start_challenge', snap({ challenge: false })), false);
    const base = snap({ photo: '{"name":"a"}' });
    assert.equal(lessons.checkLesson('make_photo', snap({ photo: '{"name":"a"}' }), base), false);
    assert.equal(lessons.checkLesson('make_photo', snap({ photo: '{"name":"b"}' }), base), true);
    assert.equal(lessons.checkLesson('make_photo', snap({ photo: null }), snap({ photo: null })), false);
    assert.equal(lessons.checkLesson('nowhere', snap({})), false);
    assert.ok(lessons.lessonAnnouncement(catalog[1], 1, 8).startsWith('Lesson 2 of 8. Jump to a goal.'));
});

const REPORT = {
    created: '2026-11-10T10:00:00',
    page: { version: '0.2.1', origin: 'http://127.0.0.1:8780', page: 'help', drawing: '3D', reducedMotion: false, theme: 'system', standalone: false, serviceWorker: 'none' },
    browser: { name: 'Chromium 140', platform: 'Linux', mobile: false, language: 'en-US', screen: '800 by 600', window: '800 by 600', pixelRatio: 1, cores: 8, storage: null },
    webgl: { webgl1: true, webgl2: true, renderer: 'SwiftShader', maxTexture: 8192 },
    webgpu: { state: 'not offered by this browser' },
    decode: { worker: 'runs', last: null },
    audio: { muted: true, volume: 0.5, context: 'not started' },
    server: {
        kind: 'server', versions: { cuju: '0.2.1', torch: null },
        home: { path: '~/.cuju/render', exists: true, writable: true, free_bytes: 3 * 1024 ** 3 },
        folders: { matches: { files: 4, bytes: 2048 } },
        library: { recordings: 2, challenge_boards: 0 },
        checks: [{ name: 'home folder', ok: true, detail: 'fine' }, { name: 'disk space', ok: false, detail: 'low' }],
        errors: [{ at: '2026-11-10T09:00:00', level: 'WARNING', message: 'cuju render skips a file' }],
    },
};

test('the report reads as text, with every part and the server', () => {
    const text = reportText(REPORT);
    for (const line of ['Page', 'Browser', 'Graphics', '  WebGL 2: yes', '  renderer: SwiftShader', '  WebGPU: not offered by this browser',
        '  worker: runs', '  last recording read by: none yet', '  muted: yes', '  torch: not installed', '  path: ~/.cuju/render',
        '  free space: 3.0 GB', '  matches: 4 files, 2.0 KB', '  challenge boards: 0', '  ok  home folder, fine', '  FAIL  disk space, low',
        '  2026-11-10T09:00:00 WARNING cuju render skips a file']) {
        assert.ok(text.includes(line), line);
    }
    assert.ok(!text.endsWith('\n'));
});

test('a report without the server says why and keeps the page side', () => {
    const text = reportText({ ...REPORT, server: { error: 'The server did not answer.' } });
    assert.ok(text.includes('Graphics') && text.endsWith('The server did not answer.'));
    assert.ok(!text.includes('Checks'));
    const empty = reportText({ ...REPORT, server: { ...REPORT.server, errors: [] } });
    assert.ok(empty.endsWith('Recent warnings and errors\n  none'));
});

// The service worker loads into a context of its own with a fake self, as the browser gives it.
function loadWorker(href) {
    const listeners = {};
    const self = { location: { href }, addEventListener: (name, fn) => { listeners[name] = fn; } };
    const source = readFileSync(new URL('sw.js', web), 'utf8');
    vm.runInNewContext(source, { self, URL, Response: class {}, fetch: () => {}, caches: {}, AbortSignal, Date, Promise });
    return { rules: self.cujuPage, listeners };
}

test('the worker keeps only the static files of the page on a loopback origin', () => {
    const { rules, listeners } = loadWorker('http://127.0.0.1:8780/sw.js?build=abc');
    assert.ok(['install', 'activate', 'fetch', 'message'].every((name) => name in listeners));
    assert.equal(rules.BUILD, 'abc');
    assert.equal(rules.CACHE, 'cuju-page-abc');
    const scope = new URL('http://127.0.0.1:8780/');
    const ok = (path, method = 'GET', ranged = false) => rules.cacheable(method, new URL(path, scope), scope, ranged);
    for (const path of ['/', '/index.html', '/js/main.js', '/style.css', '/assets/player.glb', '/assets/sounds/goal.ogg', '/lessons.json', '/manifest.webmanifest']) {
        assert.ok(ok(path), path);
    }
    for (const path of ['/api/matches', '/api/matches/m-1', '/api', '/api/help/app', '/sandbox/presentation', '/?embed=key', '/js/main.js?v=2', '/assets/promo.mp4', '/sw.js', 'http://example.com/js/main.js']) {
        assert.ok(!ok(path), path);
    }
    assert.ok(!ok('/js/main.js', 'POST'));
    assert.ok(!ok('/assets/player.glb', 'GET', true));
    for (const origin of ['http://localhost:8780/', 'http://[::1]:8780/']) {
        const here = new URL(origin);
        assert.ok(rules.cacheable('GET', new URL('js/main.js', here), here), origin);
    }
    const away = new URL('https://abc-8780.colab.googleusercontent.com/');
    assert.ok(!rules.cacheable('GET', new URL('js/main.js', away), away));
    const lan = new URL('http://192.168.1.4:8780/');
    assert.ok(!rules.cacheable('GET', new URL('js/main.js', lan), lan));
});

test('navigations share the key of the page, and a build decides how the worker answers', () => {
    const { rules } = loadWorker('http://127.0.0.1:8780/sw.js?build=abc');
    const scope = new URL('http://127.0.0.1:8780/');
    assert.equal(rules.cacheKey(new URL('/index.html', scope), scope), scope.href);
    assert.equal(rules.cacheKey(new URL('/', scope), scope), scope.href);
    assert.equal(rules.cacheKey(new URL('/teams', scope), scope, true), scope.href);
    assert.equal(rules.cacheKey(new URL('/js/broadcast/hud.js', scope), scope), 'http://127.0.0.1:8780/js/broadcast/hud.js');
    assert.equal(rules.modeFor({ build: 'abc' }), 'cache');
    assert.equal(rules.modeFor({ build: 'new' }), 'network');
    assert.equal(rules.modeFor(null), 'offline');
    assert.deepEqual(rules.staleCaches(['cuju-page-abc', 'cuju-page-old', 'other']), ['cuju-page-old']);
    assert.equal(loadWorker('http://127.0.0.1:8780/sw.js').rules.BUILD, 'none');
});

test('the page registers its worker only at the top of a loopback http page', () => {
    globalThis.navigator ??= {};
    const had = 'serviceWorker' in globalThis.navigator;
    if (!had) {
        Object.defineProperty(globalThis.navigator, 'serviceWorker', { value: {}, configurable: true });
    }
    try {
        assert.equal(installable({ protocol: 'http:', hostname: '127.0.0.1' }, false), true);
        assert.equal(installable({ protocol: 'http:', hostname: '[::1]' }, false), true);
        assert.equal(installable({ protocol: 'http:', hostname: '127.0.0.1' }, true), false);
        assert.equal(installable({ protocol: 'https:', hostname: 'x.colab.dev' }, false), false);
        assert.equal(installable({ protocol: 'http:', hostname: '10.0.0.2' }, false), false);
    } finally {
        if (!had) {
            delete globalThis.navigator.serviceWorker;
        }
    }
    assert.equal(workerBuild('http://127.0.0.1:8780/sw.js?build=abc'), 'abc');
    assert.equal(workerBuild('not a url'), null);
});

test('the manifest names the icons that ship, and the start address opens Home', () => {
    const manifest = JSON.parse(readFileSync(new URL('manifest.webmanifest', web), 'utf8'));
    assert.equal(manifest.display, 'standalone');
    assert.equal(manifest.start_url, './#page=home');
    for (const icon of manifest.icons) {
        const bytes = readFileSync(new URL(icon.src, web));
        const [width, height] = [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
        assert.equal(`${width}x${height}`, icon.sizes, icon.src);
    }
    assert.ok(manifest.icons.some((icon) => icon.purpose === 'maskable'));
});
