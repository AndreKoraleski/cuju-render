// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of photo mode's looks, frame guides, photo sizes, file names, settings and controller
// reading, run from the repository root with `node tests/web/photo.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's module
// loads from a copy beside a package file that names it a module.
const folder = mkdtempSync(join(tmpdir(), 'cuju-photo-'));
for (const name of ['export/photo-core.js', 'export/sizes.js']) {
    cpSync(fileURLToPath(new URL(`../../src/cuju/render/web/js/${name}`, import.meta.url)), join(folder, name));
}
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const photo = await import(pathToFileURL(join(folder, 'export/photo-core.js')).href);
const {
    DEFAULTS, FOCUS_MAX, FOCUS_MIN, GUIDES, LOOKS, MAX_SIDE, RESOLUTIONS, captureFov, captureRegion,
    fitAspect, focusToSlider, guideGeometry, lookById, nextGuide, nextLook, normalizeSettings,
    photoFileName, readPad, resolveResolution, sliderToFocus,
} = photo;

const close = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) <= eps, `${a} is not ${b}`);

test('the looks are complete, named and within their ranges', () => {
    assert.deepEqual(LOOKS.map((l) => l.id), ['natural', 'warm', 'cold', 'noir', 'vintage', 'vivid', 'matchday']);
    const natural = lookById('natural');
    for (const l of LOOKS) {
        assert.equal(typeof l.label, 'string');
        assert.ok(l.label.length > 0 && !l.label.includes('_'));
        for (const key of ['exposure', 'temperature', 'tint', 'contrast', 'saturation', 'fade', 'mono']) {
            assert.ok(Number.isFinite(l[key]), `${l.id} ${key}`);
        }
        for (const key of ['shadows', 'highlights', 'gain']) {
            assert.equal(l[key].length, 3);
            assert.ok(l[key].every(Number.isFinite));
        }
        assert.ok(Math.abs(l.exposure) <= 1 && Math.abs(l.temperature) <= 1 && Math.abs(l.tint) <= 1);
        assert.ok(l.contrast > 0.5 && l.contrast < 2 && l.saturation >= 0 && l.saturation <= 2);
        assert.ok(l.fade >= 0 && l.fade < 0.3 && l.mono >= 0 && l.mono <= 1);
        assert.ok(Object.isFrozen(l));
    }
    assert.deepEqual([natural.exposure, natural.contrast, natural.saturation, natural.mono], [0, 1, 1, 0]);
    assert.deepEqual(natural.gain, [1, 1, 1]);
    assert.equal(lookById('noir').mono, 1);
    assert.ok(lookById('warm').temperature > 0 && lookById('cold').temperature < 0);
    assert.equal(lookById('missing').id, 'natural');
    assert.equal(nextLook('natural'), 'warm');
    assert.equal(nextLook('matchday'), 'natural');
    assert.equal(nextLook('natural', -1), 'matchday');
    assert.equal(nextGuide('off'), 'thirds');
    assert.equal(nextGuide('off', -1), 'crop-4-5');
});

test('guides divide the picture or the frame of the photo', () => {
    assert.deepEqual(GUIDES.map((g) => g.id), ['off', 'thirds', 'golden', 'center', 'crop-16-9', 'crop-4-5']);
    const off = guideGeometry('off', 900, 600);
    assert.deepEqual(off.lines, []);
    assert.equal(off.frame, null);
    const thirds = guideGeometry('thirds', 900, 600);
    assert.equal(thirds.lines.length, 4);
    assert.deepEqual(thirds.lines[0], [300, 0, 300, 600]);
    assert.deepEqual(thirds.lines[1], [0, 200, 900, 200]);
    close(thirds.lines[2][0], 600);
    const golden = guideGeometry('golden', 1000, 1000);
    close(golden.lines[0][0], 381.9660112501051, 1e-6);
    close(golden.lines[2][0], 618.0339887498949, 1e-6);
    const center = guideGeometry('center', 800, 600);
    assert.equal(center.lines.length, 2);
    assert.deepEqual(center.lines[0], [370, 300, 430, 300]);
    assert.deepEqual(center.lines[1], [400, 270, 400, 330]);
    const wide = guideGeometry('crop-16-9', 800, 800);
    assert.deepEqual(wide.frame, { x: 0, y: 175, width: 800, height: 450 });
    const portrait = guideGeometry('crop-4-5', 1600, 900);
    assert.deepEqual(portrait.frame, { x: 440, y: 0, width: 720, height: 900 });
    assert.equal(guideGeometry('crop-16-9', 1600, 900).frame, null);
    // A photo of another shape keeps its part of the view and the guide divides that part.
    const square = guideGeometry('thirds', 1600, 900, { width: 1080, height: 1080 });
    assert.deepEqual(square.frame, { x: 350, y: 0, width: 900, height: 900 });
    assert.deepEqual(square.lines[0], [650, 0, 650, 900]);
    const cropInPortrait = guideGeometry('crop-16-9', 1600, 900, { width: 1080, height: 1350 });
    close(cropInPortrait.frame.width, 720);
    close(cropInPortrait.frame.height, 405);
});

test('a photo of another shape shows the matching part of the view', () => {
    assert.deepEqual(captureRegion(1600, 900, 1920, 1080), { x: 0, y: 0, width: 1600, height: 900 });
    assert.deepEqual(captureRegion(1600, 900, 1080, 1350), { x: 440, y: 0, width: 720, height: 900 });
    assert.deepEqual(captureRegion(900, 900, 1920, 1080), { x: 0, y: 196.875, width: 900, height: 506.25 });
    assert.deepEqual(fitAspect({ x: 10, y: 20, width: 100, height: 100 }, 2), { x: 10, y: 45, width: 100, height: 50 });
    assert.equal(captureFov(40, 16 / 9, 4 / 5), 40);
    assert.equal(captureFov(40, 16 / 9, 16 / 9), 40);
    // A wider photo narrows the vertical view so its width matches the window's.
    const fov = captureFov(40, 1, 16 / 9);
    const half = (deg) => Math.tan((deg * Math.PI) / 360);
    close(half(fov) * (16 / 9), half(40) * 1, 1e-12);
});

test('resolutions resolve to whole sizes within limits', () => {
    assert.equal(RESOLUTIONS[0].id, 'window');
    for (const id of ['1920x1080', '3840x2160', '1080x1350']) {
        assert.ok(RESOLUTIONS.some((r) => r.id === id), id);
    }
    assert.deepEqual(resolveResolution('window', 800.4, 553.6), { width: 800, height: 554 });
    assert.deepEqual(resolveResolution(undefined, 640, 480), { width: 640, height: 480 });
    assert.deepEqual(resolveResolution('3840x2160', 1, 1), { width: 3840, height: 2160 });
    assert.deepEqual(resolveResolution('1280x720', 1, 1), { width: 1280, height: 720 });
    assert.deepEqual(resolveResolution({ width: 320, height: 200 }, 1, 1), { width: 320, height: 200 });
    assert.deepEqual(resolveResolution('vertical', 1, 1), { width: 1080, height: 1920 });
    assert.deepEqual(resolveResolution('2160p', 1, 1), { width: 3840, height: 2160 });
    assert.ok(RESOLUTIONS.some((r) => r.id === '1080x1080' && r.preset === 'square'));
    assert.throws(() => resolveResolution('huge', 1, 1), /Unknown resolution/);
    assert.throws(() => resolveResolution({ width: 8, height: 200 }, 1, 1), /width of a photo/);
    assert.throws(() => resolveResolution({ width: 300.5, height: 200 }, 1, 1), /width/);
    assert.throws(() => resolveResolution('3840x2160', 1, 1, 2048), /from 16 to 2048/);
    assert.throws(() => resolveResolution({ width: MAX_SIDE + 1, height: 100 }, 1, 1, 1e6), /width/);
});

test('file names name the recording and the frame', () => {
    assert.equal(photoFileName('m-20261106-105640-3a3f', 412), 'cuju-photo-m-20261106-105640-3a3f-412.png');
    assert.equal(photoFileName('My Match.cjr', 0), 'cuju-photo-my-match.cjr-0.png');
    assert.equal(photoFileName('../../etc/passwd', 3), 'cuju-photo-etc-passwd-3.png');
    assert.equal(photoFileName(null, null), 'cuju-photo-view.png');
    assert.equal(photoFileName('', 5), 'cuju-photo-view-5.png');
    assert.equal(photoFileName('live', -1), 'cuju-photo-live.png');
    const long = photoFileName('x'.repeat(200), 1);
    assert.ok(long.length <= 'cuju-photo-'.length + 64 + '-1.png'.length);
    assert.match(photoFileName('a/b\\c:d*e?f"g<h>i|j', 2), /^cuju-photo-[a-z0-9._-]+-2\.png$/);
});

test('settings are checked and kept in range', () => {
    const s = normalizeSettings({}, null);
    assert.deepEqual(s, { ...DEFAULTS });
    const t = normalizeSettings(s, { look: 'noir', vignette: 2, grain: -1, focus: 12, aperture: 0.5, fov: 5, roll: 400, guide: 'thirds', resolution: '1080x1350' });
    assert.deepEqual(t, { ...DEFAULTS, look: 'noir', vignette: 1, grain: 0, focus: 12, aperture: 0.5, fov: 10, roll: 90, guide: 'thirds', resolution: '1080x1350' });
    assert.equal(normalizeSettings(t, { focus: 'auto' }).focus, 'auto');
    assert.equal(normalizeSettings(t, { focus: 9999 }).focus, FOCUS_MAX);
    assert.deepEqual(normalizeSettings(t, { resolution: { width: 300, height: 200 } }).resolution, { width: 300, height: 200 });
    assert.throws(() => normalizeSettings(s, { look: 'sepia' }), /Unknown look "sepia", use one of natural/);
    assert.throws(() => normalizeSettings(s, { guide: 'grid' }), /Unknown guide/);
    assert.throws(() => normalizeSettings(s, { focus: 'near' }), /focus is 'auto'/);
    assert.throws(() => normalizeSettings(s, { vignette: '0.5' }), /vignette is a number/);
    assert.throws(() => normalizeSettings(s, { exposure: 1 }), /Unknown photo setting "exposure"/);
    assert.throws(() => normalizeSettings(s, { resolution: '1x1' }), /width of a photo/);
    assert.throws(() => normalizeSettings(s, 'noir'), /object/);
    // A failed change leaves the settings as they were.
    assert.deepEqual(s, { ...DEFAULTS });
});

test('the focus slider is logarithmic and returns its distance', () => {
    assert.equal(focusToSlider(FOCUS_MIN), 0);
    assert.equal(focusToSlider(FOCUS_MAX), 1000);
    assert.equal(focusToSlider(0), 0);
    assert.equal(focusToSlider(1e6), 1000);
    assert.equal(sliderToFocus(0), FOCUS_MIN);
    assert.equal(sliderToFocus(1000), FOCUS_MAX);
    for (const m of [1, 5, 12, 30, 80, 150]) {
        const back = sliderToFocus(focusToSlider(m));
        assert.ok(Math.abs(back - m) / m < 0.01, `${m} came back as ${back}`);
    }
    assert.ok(focusToSlider(10) > 400 && focusToSlider(10) < 500);
});

test('a controller flies past its dead zone and presses once', () => {
    const button = (value) => ({ pressed: value > 0.5, value });
    const buttons = (pressed = [], values = {}) => Array.from({ length: 17 }, (_, i) => button(values[i] ?? (pressed.includes(i) ? 1 : 0)));
    const idle = readPad({ axes: [0.1, -0.1, 0.05, 0], buttons: buttons() });
    assert.deepEqual(idle.move, [0, 0]);
    assert.deepEqual(idle.look, [0, 0]);
    assert.deepEqual(idle.pressed, []);
    const full = readPad({ axes: [1, 0, 0, -1], buttons: buttons([0, 5, 13, 15], { 7: 0.75, 6: 0.25 }) });
    assert.deepEqual(full.move, [1, 0]);
    assert.deepEqual(full.look, [0, -1]);
    close(full.rise, 0.5);
    assert.equal(full.zoom, 1);
    assert.equal(full.roll, 1);
    assert.deepEqual(full.pressed, ['save', 'nextLook']);
    // A button held since the last poll does not press again.
    const held = readPad({ axes: [0, 0, 0, 0], buttons: buttons([0, 5, 1]) }, full.buttons);
    assert.deepEqual(held.pressed, ['leave']);
    const half = readPad({ axes: [0.575, 0, 0, 0], buttons: [] }, [], 0.15);
    close(half.move[0], 0.5, 1e-9);
    assert.deepEqual(readPad(null).pressed, []);
    assert.deepEqual(readPad({ axes: [], buttons: [1, 0, 0, 0, 1] }).pressed, ['save', 'previousLook']);
});

test('a script that sets a number out of range learns its mistake', () => {
    const s = normalizeSettings({}, null);
    const strict = { strict: true };
    assert.throws(() => normalizeSettings(s, { vignette: 2 }, strict), /vignette is a number from 0 to 1, not 2/);
    assert.throws(() => normalizeSettings(s, { roll: -91 }, strict), /roll is a number from -90 to 90/);
    assert.throws(() => normalizeSettings(s, { focus: 9999 }, strict), /focus is 'auto' or a distance/);
    assert.equal(normalizeSettings(s, { vignette: 1, focus: FOCUS_MAX }, strict).vignette, 1);
    // The keys and the controller step past an end and stay at it.
    assert.equal(normalizeSettings(s, { vignette: 2 }).vignette, 1);
    const message = (() => {
        try {
            resolveResolution('huge', 1, 1);
        } catch (err) {
            return err.message;
        }
        return '';
    })();
    assert.equal(message.split('window').length, 2, message);
    for (const name of ['vertical', 'square', '1080p', '4k']) {
        assert.ok(message.includes(name), message);
    }
});
