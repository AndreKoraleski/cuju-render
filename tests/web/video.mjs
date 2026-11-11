// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the range and settings of the page's video export, run from the repository root with
// `node tests/web/video.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from a copy beside a package file that names them modules. flat.js imports three for its
// view without WebGL, which an empty stub stands in for, the tests never draw.
const folder = mkdtempSync(join(tmpdir(), 'cuju-video-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/', import.meta.url)), folder, { recursive: true });
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
mkdirSync(join(folder, 'node_modules', 'three'), { recursive: true });
writeFileSync(join(folder, 'node_modules', 'three', 'package.json'), '{"name": "three", "type": "module", "main": "index.js"}\n');
writeFileSync(join(folder, 'node_modules', 'three', 'index.js'), 'export {};\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const { offersView2d, slowText } = await import(pathToFileURL(join(folder, 'watch/flat.js')).href);
const {
    VIDEO_MAX_SECONDS, checkRange, exportRequest, fileSize, formatMoment, goalRange, parseMoment, progressText, videoSize,
} = await import(pathToFileURL(join(folder, 'export/video-range.js')).href);

test('moments read as seconds or as minutes and seconds', () => {
    assert.equal(parseMoment('75'), 75);
    assert.equal(parseMoment(' 75.5 '), 75.5);
    assert.equal(parseMoment('1:15'), 75);
    assert.equal(parseMoment('2:03.5'), 123.5);
    for (const text of ['', 'soon', '1:75', '-3', '1:2:3', null, undefined]) {
        assert.equal(parseMoment(text), null, String(text));
    }
    assert.equal(formatMoment(75), '1:15');
    assert.equal(formatMoment(123.46), '2:03.5');
    assert.equal(formatMoment(-1), '0:00');
    assert.equal(parseMoment(formatMoment(299.9)), 299.9);
});

test('a range is checked against the recording', () => {
    assert.deepEqual(checkRange('0:10', '0:25', 300), { start: 10, end: 25 });
    assert.deepEqual(checkRange('290', '400', 300.1), { start: 290, end: 300.1 });
    assert.match(checkRange('a', '10', 300).error, /Type the start and end/);
    assert.match(checkRange('20', '10', 300).error, /after the start/);
    assert.match(checkRange('400', '410', 300).error, /past the end/);
    assert.match(checkRange('0', String(VIDEO_MAX_SECONDS + 1), 5400).error, /at most 10 minutes/);
    assert.deepEqual(goalRange(10, 300), { start: 2, end: 14 });
    assert.deepEqual(goalRange(3, 5), { start: 0, end: 5 });
});

test('the request names only what the server accepts', () => {
    const body = exportRequest({ start: 1.23456, end: 9 }, {
        size: '1080p', fps: '60', quality: 'high', camera: 'ball', score: false,
    }, { arena: 'beach', time: 19.25, grass: '#ffffff' });
    assert.deepEqual(body, {
        start: 1.235, end: 9, camera: 'ball', width: 1920, height: 1080, fps: 60, quality: 'high',
        score: false, arena: 'beach', time: 19.25,
    });
    const fallback = exportRequest({ start: 0, end: 2 }, {
        size: 'huge', fps: 29, quality: 'best', camera: 'free',
    }, null);
    assert.deepEqual(fallback, {
        start: 0, end: 2, camera: 'broadcast', width: 1280, height: 720, fps: 30, quality: 'standard', score: true,
    });
});

test('the annotations join the request only when asked for', () => {
    const shown = exportRequest({ start: 0, end: 2 }, { size: '720p', annotations: true }, null);
    assert.equal(shown.annotations, true);
    for (const annotations of [false, undefined, 'yes', 1]) {
        assert.equal('annotations' in exportRequest({ start: 0, end: 2 }, { annotations }, null), false);
    }
});

test('a video export and a clean feed never offer the 2D view', () => {
    assert.equal(offersView2d(''), true);
    assert.equal(offersView2d('?lang=en'), true);
    assert.equal(offersView2d('?capture=1&safe=auto'), false);
    assert.equal(offersView2d('?feed=1&source=live&fps=10'), false);
    assert.equal(slowText(1.2), 'The 3D picture draws 1 frame a second here. The 2D view plays the same match from above and needs much less.');
    assert.match(slowText(0.2), /draws 1 frame a second/);
    assert.match(slowText(7.4), /draws 7 frames a second/);
});

test('the request takes every shared size, a custom even size, the scale and the safe area', () => {
    const vertical = exportRequest({ start: 0, end: 2 }, {
        size: 'vertical', fps: 30, quality: 'standard', camera: 'broadcast', scale: 1.25, safe: 'social',
    }, null);
    assert.equal(vertical.width, 1080);
    assert.equal(vertical.height, 1920);
    assert.equal(vertical.scale, 1.25);
    assert.equal(vertical.safe, 'social');
    const custom = exportRequest({ start: 0, end: 2 }, { size: { width: 1000, height: 1000 }, scale: '1', safe: 'auto' }, null);
    assert.deepEqual([custom.width, custom.height, 'scale' in custom, 'safe' in custom], [1000, 1000, false, false]);
    assert.deepEqual(videoSize({ width: 1001, height: 1000 }), videoSize('720p'));
    assert.deepEqual(videoSize({ width: 3840, height: 3840 }), videoSize('720p'));
    const odd = exportRequest({ start: 0, end: 2 }, { size: '4k', scale: 9, safe: 'wide' }, null);
    assert.deepEqual([odd.width, odd.height, 'scale' in odd, 'safe' in odd], [3840, 2160, false, false]);
});

test('progress reads as a sentence', () => {
    assert.equal(progressText(null), '');
    assert.match(progressText({ state: 'running', frame: 0 }), /Starting Chrome/);
    assert.equal(progressText({ state: 'running', frame: 30, frames: 60, progress: 0.5 }), 'Drawing frame 30 of 60, 50 percent.');
    assert.match(progressText({ state: 'running', frame: 60, frames: 60, progress: 1 }), /Finishing/);
    assert.equal(progressText({ state: 'done', bytes: 2500000 }), 'The video is ready, 2.5 MB.');
    // A finished export names its range, which may differ from the fields of the dialog.
    assert.equal(progressText({ state: 'done', bytes: 56000, start: 30, end: 45.5 }), 'The video of 0:30 to 0:45.5 is ready, 56 KB.');
    assert.equal(progressText({ state: 'done', start: 75, end: 90 }), 'The video of 1:15 to 1:30 is ready.');
    assert.equal(progressText({ state: 'failed', error: 'ffmpeg stopped.' }), 'The export failed. ffmpeg stopped.');
    assert.match(progressText({ state: 'cancelled' }), /cancelled/);
});

test('a small video reads in KB and a larger one in MB', () => {
    assert.equal(fileSize(22000), '22 KB');
    assert.equal(fileSize(400), '1 KB');
    assert.equal(fileSize(999400), '999 KB');
    assert.equal(fileSize(2500000), '2.5 MB');
    assert.equal(progressText({ state: 'done', bytes: 22000 }), 'The video is ready, 22 KB.');
});
