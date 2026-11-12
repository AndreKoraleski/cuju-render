// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the Help page's guided tour, hands-on lessons, diagnostic report and service worker,
// run from the repository root with `node tests/web/help.mjs`.

import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import vm from 'node:vm';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from a copy of the whole folder beside a package file that names them modules. The icons
// that core/icons.js reads come along in vendor/lucide, beside the folder as in the page.
const root = mkdtempSync(join(tmpdir(), 'cuju-help-'));
const folder = join(root, 'js');
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js', import.meta.url)), folder, { recursive: true });
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/vendor/lucide', import.meta.url)), join(root, 'vendor', 'lucide'), { recursive: true });
writeFileSync(join(root, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(root, { recursive: true, force: true }));
const load = (name) => import(pathToFileURL(join(folder, name)).href);
const tour = await load('help/tour-core.js');
const lessons = await load('help/lessons-core.js');
const { reportStatus, reportText } = await load('help/doctor.js');
const { installable, workerBuild } = await load('help/pwa.js');
const web = new URL('../../src/cuju/render/web/', import.meta.url);
const catalog = JSON.parse(readFileSync(new URL('lessons.json', web), 'utf8')).lessons;
const ids = catalog.map((lesson) => lesson.id);
const plain = (text) => !/[;:()!]/.test(text) && !/ - |—|–/.test(text);

test('the tour has a step on each page that the task names, in words alone', () => {
    const pages = new Set(tour.TOUR_STEPS.map((step) => step.page));
    for (const page of ['home', 'watch', 'play', 'challenges', 'teams', 'tournaments', 'help']) {
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
    // The focus on the title reads the title, so the live region reads the count and the text.
    assert.equal(words, `Step 1 of ${tour.TOUR_STEPS.length}. ${tour.TOUR_STEPS[0].text}`);
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
    // A tall target leaves room at its sides, and a target that fills the window has the card over it.
    const tall = tour.placeCard({ left: 100, top: 150, width: 60, height: 300, bottom: 450 }, card, view);
    assert.deepEqual(tall, { left: 172, top: 150, side: 'right' });
    const wideRight = tour.placeCard({ left: 600, top: 150, width: 100, height: 300, bottom: 450 }, card, view);
    assert.deepEqual(wideRight, { left: 228, top: 150, side: 'left' });
    const filled = tour.placeCard({ left: 20, top: 20, width: 760, height: 560, bottom: 580 }, card, view);
    assert.equal(filled.side, 'over');
    const narrow = tour.placeCard(null, { width: 360, height: 200 }, { width: 320, height: 500 });
    assert.equal(narrow.left, 12);
});

// Whether two boxes share some area, the card given by its place and size.
const covers = (spot, card, box) => spot.left < box.right && box.left < spot.left + card.width
    && spot.top < box.bottom && box.top < spot.top + card.height;

test('the card keeps clear of the menus and panels open over the page, side by side', () => {
    const view = { width: 800, height: 600 };
    const card = { width: 360, height: 200 };
    const middle = { left: 300, top: 250, right: 340, bottom: 280 };
    assert.deepEqual(tour.placeCard(middle, card, view, []), { left: 140, top: 292, side: 'below' });
    // A menu that opens below its button sends the card above it.
    const below = { left: 300, top: 284, right: 560, bottom: 500 };
    assert.deepEqual(tour.placeCard(middle, card, view, [below]), { left: 140, top: 38, side: 'above' });
    // A button near the top with a narrow menu under it has the card at its right, or at its left
    // near the right edge.
    const leftButton = { left: 20, top: 20, right: 60, bottom: 50 };
    const leftMenu = { left: 20, top: 54, right: 60, bottom: 400 };
    assert.deepEqual(tour.placeCard(leftButton, card, view, [leftMenu]), { left: 72, top: 20, side: 'right' });
    const rightButton = { left: 740, top: 20, right: 780, bottom: 50 };
    const rightMenu = { left: 740, top: 54, right: 780, bottom: 400 };
    assert.deepEqual(tour.placeCard(rightButton, card, view, [rightMenu]), { left: 368, top: 20, side: 'left' });
    // A wide menu leaves no side clear, so the card docks in the corner farthest from it.
    const wideMenu = { left: 20, top: 54, right: 400, bottom: 300 };
    const docked = tour.placeCard(leftButton, card, view, [wideMenu]);
    assert.deepEqual(docked, { left: 428, top: 388, width: 360, height: 200, side: 'dock' });
    for (const box of [leftButton, wideMenu]) {
        assert.ok(!covers(docked, docked, box));
    }
    // A panel across the middle of the window leaves only short corners, so the card docks smaller,
    // inside its margins.
    const band = { left: 0, top: 150, right: 800, bottom: 450 };
    const smaller = tour.placeCard(leftButton, card, view, [band]);
    assert.deepEqual(smaller, { left: 428, top: 12, width: 360, height: 126, side: 'dock' });
    assert.ok(!covers(smaller, smaller, band) && !covers(smaller, smaller, leftButton));
    assert.ok(smaller.left >= 12 && smaller.top >= 12 && smaller.left + smaller.width <= 788 && smaller.top + smaller.height <= 588);
    // Without a target the card leaves the bottom of the window to a panel that lies there.
    const low = { left: 120, top: 350, right: 680, bottom: 590 };
    assert.deepEqual(tour.placeCard(null, card, view, [low]), { left: 12, top: 12, width: 360, height: 200, side: 'dock' });
    assert.equal(tour.placeCard(null, card, view, [{ left: 0, top: 0, right: 100, bottom: 100 }]).side, 'none');
});

// The text of the page, its index.html and the modules of js, where the targets of the tour live.
const html = readFileSync(new URL('index.html', web), 'utf8');
const modules = readdirSync(fileURLToPath(new URL('js', web)), { recursive: true })
    .filter((name) => name.endsWith('.js'))
    .map((name) => readFileSync(join(fileURLToPath(new URL('js', web)), name), 'utf8'))
    .join('\n');
const english = JSON.parse(readFileSync(new URL('languages/en.json', web), 'utf8'));

test('each step of the tour names what Try it does, on a target the page has', () => {
    const opens = [];
    for (const step of tour.TOUR_STEPS) {
        assert.ok(step.tryIt === null || tour.TRY_KINDS.includes(step.tryIt), step.id);
        if (step.tryIt === 'open') {
            opens.push(step.id);
        }
        if (step.tryIt === 'focus') {
            assert.ok(typeof english[`tour.try.${step.id}`] === 'string', step.id);
            assert.ok(plain(english[`tour.try.${step.id}`].replace(/`[^`]*`/g, 'key')), step.id);
        }
        // Each id and class of the selector is in index.html or in a module that builds the page.
        for (const [, mark, name] of step.target.matchAll(/([#.])([\w-]+)/g)) {
            const quoted = new RegExp(`['"\`][^'"\`]*\\b${name}\\b[^'"\`]*['"\`]`);
            const found = mark === '#'
                ? html.includes(`id="${name}"`) || modules.includes(`id: '${name}'`)
                : quoted.test(html) || quoted.test(modules);
            assert.ok(found, `${step.id} ${mark}${name}`);
        }
    }
    // Try it opens the palette, the menus, a leaderboard, the settings and the wizard, and
    // starts no match.
    assert.deepEqual(opens, ['palette', 'match', 'view', 'challenges', 'tournaments', 'settings']);
    assert.equal(tour.TOUR_STEPS.find((step) => step.id === 'play').tryIt, null);
    assert.equal(tour.TOUR_STEPS.find((step) => step.id === 'timeline').tryIt, 'focus');
});

test('the catalog of lessons holds the eight lessons of the task, each with agent steps', () => {
    assert.deepEqual(ids, ['open_sample', 'seek_goal', 'switch_camera', 'follow_player', 'play_game', 'register_team', 'start_challenge', 'make_photo']);
    const checks = new Set(['recording', 'match_played', 'team', 'challenge', 'page']);
    for (const lesson of catalog) {
        assert.ok(plain(lesson.ask) && plain(lesson.praise) && plain(lesson.title), lesson.id);
        assert.ok(checks.has(lesson.agent.check), lesson.id);
        assert.ok(lesson.agent.steps.length > 0 && lesson.agent.steps.every((step) => step.say && (step.run || step.python || step.http || step.script)), lesson.id);
        assert.ok(['home', 'watch', 'play', 'challenges', 'teams'].includes(lesson.page), lesson.id);
    }
});

test('the challenges step and lesson point at the Challenges page, and a stored place resumes there', () => {
    const index = tour.TOUR_STEPS.findIndex((step) => step.id === 'challenges');
    const step = tour.TOUR_STEPS[index];
    assert.equal(step.page, 'challenges');
    assert.ok(step.target.startsWith('#page-challenges '), step.target);
    // The leaderboard button is a disclosure, which Try it opens and the same button closes,
    // rather than Play it yourself or Run a model's Run, which start matches.
    assert.match(step.target, /data-action="board"/);
    assert.equal(step.tryIt, 'open');
    assert.ok(html.includes('id="page-challenges"'));
    assert.ok(html.includes('data-page="challenges"'));
    // A tour left at the step of the challenges, when they were a section of Play, resumes at
    // the same step, which now opens the Challenges page.
    assert.equal(tour.TOUR_STEPS[tour.resumeStep({ step: index, started: true })].page, 'challenges');
    const lesson = catalog.find((entry) => entry.id === 'start_challenge');
    assert.equal(lesson.page, 'challenges');
    assert.match(english['lesson.start_challenge.ask'], /Challenges page/);
    // A lesson under way or done before the move keeps its progress.
    assert.deepEqual(lessons.progressState({ done: { register_team: 'a' }, current: 'start_challenge' }, ids),
        { done: { register_team: 'a' }, current: 'start_challenge' });
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

test('the jumps the timeline counts end the lesson, even when the recording opened since the last look', () => {
    const goals = [1000];
    // A script opens a recording and jumps to a goal between two looks.
    const fast = {};
    assert.equal(lessons.checkLesson('seek_goal', snap({ source: null, goals: [] }), null, fast), false);
    assert.equal(lessons.checkLesson('seek_goal', snap({ t: 940, goals, jumps: 1, at: 400 }), null, fast), true);
    // Jumps made before the lesson began stay out.
    const before = {};
    const base = snap({ t: 940, goals, jumps: 3 });
    assert.equal(lessons.checkLesson('seek_goal', snap({ t: 940, goals, jumps: 3 }), base, before), false);
    assert.equal(lessons.checkLesson('seek_goal', snap({ t: 945, goals, jumps: 4, at: 400 }), base, before), true);
    // The seeks of a replay stay out, those after it count.
    const replay = {};
    assert.equal(lessons.checkLesson('seek_goal', snap({ t: 100, goals, jumps: 0 }), null, replay), false);
    assert.equal(lessons.checkLesson('seek_goal', snap({ t: 950, goals, jumps: 1, show: true, at: 400 }), null, replay), false);
    assert.equal(lessons.checkLesson('seek_goal', snap({ t: 1010, goals, jumps: 2, at: 800 }), null, replay), false);
    assert.equal(lessons.checkLesson('seek_goal', snap({ t: 940, goals, jumps: 3, at: 1200 }), null, replay), true);
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

test('the status of a report names the checks that fail and those that warn', () => {
    assert.equal(reportStatus(REPORT), 'The report is ready. 1 check fails, disk space.');
    const warned = { ...REPORT, server: { ...REPORT.server, checks: [
        { name: 'home folder', ok: true, detail: 'fine' },
        { name: 'video export', ok: true, warning: true, detail: 'ffmpeg is missing' },
    ] } };
    assert.equal(reportStatus(warned), 'The report is ready. 1 check warns, video export.');
    const both = { ...REPORT, server: { ...REPORT.server, checks: [...REPORT.server.checks, ...warned.server.checks.slice(1),
        { name: 'samples', ok: false, detail: 'none' }] } };
    assert.equal(reportStatus(both), 'The report is ready. 2 checks fail, disk space and samples. 1 check warns, video export.');
    const fine = { ...REPORT, server: { ...REPORT.server, checks: [REPORT.server.checks[0]] } };
    assert.equal(reportStatus(fine), 'The report is ready, every check passes.');
    assert.equal(reportStatus({ ...REPORT, server: { error: 'away' } }), 'The report is ready, without the server, which did not answer.');
});

// The service worker loads into a context of its own with a fake self, as the browser gives it.
function loadWorker(href) {
    const listeners = {};
    const self = { location: { href }, addEventListener: (name, fn) => { listeners[name] = fn; } };
    const source = readFileSync(new URL('sw.js', web), 'utf8');
    vm.runInNewContext(source, { self, URL, Response, fetch: () => {}, caches: {}, crypto: globalThis.crypto, AbortSignal, Date, Promise, Uint8Array, Array, Object });
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

test('the worker answers only with entries that carry the digest of their file', async () => {
    const source = readFileSync(new URL('sw.js', web), 'utf8');
    assert.equal(source.split('const DIGESTS = null;').length, 2, 'one line for the server to fill');
    const { rules } = loadWorker('http://127.0.0.1:8780/sw.js?build=abc');
    const scope = new URL('http://127.0.0.1:8780/');
    assert.equal(rules.DIGESTS, null);
    assert.equal(rules.digestFor(scope.href, scope), null, 'without digests the worker keeps nothing');
    const digests = { 'index.html': 'aa', 'js/main.js': 'bb' };
    assert.equal(rules.digestFor(scope.href, scope, digests), 'aa', 'the page itself');
    assert.equal(rules.digestFor('http://127.0.0.1:8780/js/main.js', scope, digests), 'bb');
    assert.equal(rules.digestFor('http://127.0.0.1:8780/js/other.js', scope, digests), null);
    assert.equal(rules.digestFor('http://127.0.0.1:8780/constructor', scope, digests), null);
    assert.equal(rules.digestFor('http://example.com/js/main.js', scope, digests), null);
    const good = new Response('kept');
    const digest = createHash('sha256').update('kept').digest('hex');
    assert.equal(await rules.hasDigest(good, digest), true);
    assert.equal(await rules.hasDigest(new Response('<script>planted</script>'), digest), false);
    assert.equal(await rules.hasDigest(good, null), false);
    assert.equal(await good.text(), 'kept', 'the check reads a copy');
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

test('the manifest names Cuju and the icons that ship, and the start address opens Home', () => {
    const manifest = JSON.parse(readFileSync(new URL('manifest.webmanifest', web), 'utf8'));
    assert.equal(manifest.name, 'Cuju');
    assert.equal(manifest.short_name, 'Cuju');
    assert.equal(manifest.display, 'standalone');
    assert.equal(manifest.start_url, './#page=home');
    for (const icon of manifest.icons) {
        const bytes = readFileSync(new URL(icon.src, web));
        if (icon.type === 'image/svg+xml') {
            assert.equal(icon.sizes, 'any', icon.src);
            assert.match(bytes.toString('utf8'), /^<svg /, icon.src);
            continue;
        }
        const [width, height] = [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
        assert.equal(`${width}x${height}`, icon.sizes, icon.src);
    }
    assert.ok(manifest.icons.some((icon) => icon.purpose === 'maskable'));
    assert.ok(manifest.icons.some((icon) => icon.src === 'assets/cuju-logo.svg'));
    // The icons keep the tiled logo, and the bare marks stay inside the page.
    assert.ok(manifest.icons.every((icon) => !icon.src.includes('cuju-mark')));
});

test('the shell of the worker holds files that ship, the logo and both bare marks among them', () => {
    const { rules } = loadWorker('http://127.0.0.1:8780/sw.js?build=abc');
    for (const path of rules.SHELL.filter(Boolean)) {
        assert.ok(readFileSync(new URL(path, web)).length > 0, path);
    }
    for (const path of ['assets/cuju-logo.svg', 'assets/cuju-mark.svg', 'assets/cuju-mark-light.svg']) {
        assert.ok(rules.SHELL.includes(path), path);
    }
});
