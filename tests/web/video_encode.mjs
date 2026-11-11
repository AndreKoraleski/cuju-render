// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the parts of the browser's video export that need no browser, the plan of the frames,
// the settings of the page that draws them, the choice of encoder and the two writers of files,
// run from the repository root with `node tests/web/video_encode.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from a copy beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-video-encode-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/', import.meta.url)), folder, { recursive: true });
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const load = (name) => import(pathToFileURL(join(folder, 'export', name)).href);
const plan = await load('video-plan.js');
const { Mp4Writer } = await load('mp4-mux.js');
const { WebmWriter, sizeBytes } = await load('webm-mux.js');
// The boot of the drawing page reads the address as it loads, which holds no export here.
globalThis.location = { search: '' };
const { readSettings } = await load('video-boot.js');

test('the frames of a range follow the server export', () => {
    // The same counts as frame_count of video.py gives.
    assert.equal(plan.frameCount(2, 4, 30), 60);
    assert.equal(plan.frameCount(0, 0.01, 30), 1);
    assert.equal(plan.frameCount(1.234, 5.678, 25), 111);
    const a = plan.exportPlan(10, 12, 30);
    assert.deepEqual({ ...a }, { frames: 60, warmFrames: 30, warmFrom: 9, step: 1000 / 30, keyEvery: 60 });
    // A range near the start warms up for as long as the recording allows.
    const b = plan.exportPlan(0.4, 1, 25);
    assert.equal(b.warmFrames, 10);
    assert.ok(Math.abs(b.warmFrom) < 1e-9);
    assert.equal(plan.exportPlan(0, 3, 60).warmFrames, 0);
});

test('frame times are whole microseconds that add up to the length', () => {
    for (const fps of [24, 25, 30, 50, 60]) {
        let total = 0;
        for (let i = 0; i < fps * 3; i++) {
            assert.equal(plan.frameTime(i, fps), total);
            total += plan.frameDuration(i, fps);
        }
        assert.equal(total, 3e6);
    }
});

test('the page draws with the settings of the server export', () => {
    const settings = plan.exportSettings({ quality: 'draft', camera: 'ball', annotations: false, arena: 'beach', time: 30 });
    assert.equal(settings.quality, 'medium');
    assert.equal(settings.camera, 'broadcast');
    assert.equal(settings.muted, true);
    assert.equal(settings.tvMode, true);
    assert.equal(settings.view2dDeclined, true);
    for (const key of ['lineups', 'celebrations', 'replays', 'decisionReplays', 'transitions', 'podium', 'pointerLock']) {
        assert.equal(settings[key], false, key);
    }
    assert.deepEqual(settings.annotations, { players: false, actions: false, text: false });
    assert.deepEqual(settings.field, { arena: 'beach', time: 24 });
    const shown = plan.exportSettings({ quality: 'high', camera: 'goal', annotations: true });
    assert.equal(shown.quality, 'high');
    assert.equal(shown.camera, 'goal');
    assert.deepEqual(shown.annotations, { players: true, actions: true, text: true });
    assert.equal(shown.field, undefined);
    // Broadcast keeps the presentation of the match, as --broadcast of the command does.
    const broadcast = plan.exportSettings({ quality: 'standard', broadcast: true });
    for (const key of ['lineups', 'celebrations', 'replays', 'decisionReplays', 'transitions']) {
        assert.equal(broadcast[key], true, key);
    }
    assert.equal(broadcast.podium, false);
});

test('the address of the drawing page carries the export and the layout', () => {
    const address = plan.exportAddress({ quality: 'standard', camera: 'broadcast', safe: 'social' }, { ratio: 1.5, lang: 'pt', match: 'm-1 2' });
    const url = new URL(address, 'http://127.0.0.1/');
    assert.equal(url.pathname, '/');
    assert.equal(url.searchParams.get('capture'), '1');
    assert.equal(url.searchParams.get('safe'), 'social');
    assert.equal(url.searchParams.get('ratio'), '1.5');
    assert.equal(url.searchParams.get('lang'), 'pt');
    assert.equal(url.hash, '#match=m-1%202');
    assert.equal(JSON.parse(url.searchParams.get('export')).quality, 'high');
    assert.deepEqual(readSettings(url.searchParams.get('export')), plan.exportSettings({ quality: 'standard', camera: 'broadcast' }));
    assert.equal(readSettings('[1]'), null);
    assert.equal(readSettings('{'), null);
});

test('the encoders run from H.264 in MP4 to VP8 in WebM, at a level that holds the size', () => {
    assert.equal(plan.avcLevel(1280, 720, 30), 31);
    assert.equal(plan.avcLevel(1920, 1080, 30), 40);
    assert.equal(plan.avcLevel(1920, 1080, 60), 42);
    assert.equal(plan.avcLevel(1080, 1920, 30), 40);
    assert.equal(plan.avcLevel(3840, 2160, 30), 51);
    assert.equal(plan.avcLevel(3840, 2160, 60), 52);
    const list = plan.encoderCandidates(1920, 1080, 30, 'standard');
    assert.deepEqual(list.map((c) => c.container), ['mp4', 'mp4', 'mp4', 'webm', 'webm']);
    assert.deepEqual(list.map((c) => c.config.codec), ['avc1.640028', 'avc1.4D0028', 'avc1.42E028', 'vp09.00.40.08', 'vp8']);
    assert.ok(list.every((c) => c.config.width === 1920 && c.config.height === 1080 && c.config.framerate === 30));
    assert.equal(list[0].config.avc.format, 'avc');
    assert.deepEqual(plan.encoderCandidates(1920, 1080, 30, 'standard', 'webm').map((c) => c.config.codec), ['vp09.00.40.08', 'vp8']);
    assert.ok(plan.encoderCandidates(640, 360, 30, 'draft', 'mp4').every((c) => c.container === 'mp4'));
    assert.equal(plan.bitrate('standard', 1920, 1080, 30), 6220800);
    assert.ok(plan.bitrate('high', 1920, 1080, 30) > plan.bitrate('standard', 1920, 1080, 30));
    assert.equal(plan.bitrate('high', 3840, 2160, 60), plan.MAX_BITRATE);
    assert.equal(plan.bitrate('draft', 160, 90, 24), plan.MIN_BITRATE);
});

test('the first supported encoder wins, and a refusal counts as missing', async () => {
    const list = plan.encoderCandidates(1280, 720, 30, 'draft');
    const vp9 = await plan.chooseEncoder(list, async (config) => {
        if (config.codec.startsWith('avc1.64')) {
            throw new TypeError('unknown');
        }
        return { supported: config.codec.startsWith('vp09') };
    });
    assert.equal(vp9.container, 'webm');
    assert.equal(await plan.chooseEncoder(list, async () => ({ supported: false })), null);
});

test('the file name follows the server export', () => {
    // The same names as _filename of video_jobs.py gives.
    assert.equal(plan.videoFileName('Greens against Golds, synthetic sample', 2, 4), 'Greens against Golds, synthetic sample 0m02-0m04.mp4');
    assert.equal(plan.videoFileName('Équipe: A/B ~ test', 75.5, 125.9), 'quipe AB  test 1m15-2m05.mp4');
    assert.equal(plan.videoFileName('...', 0, 0.5), 'match 0m00-0m00.mp4');
    assert.equal(plan.videoFileName('x'.repeat(80), 600, 659.99, 'webm'), `${'x'.repeat(60)} 10m00-10m59.webm`);
});

// Reads the boxes of an MP4 file into a tree of types, offsets and sizes.
function boxes(bytes, start = 0, end = bytes.length) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const out = [];
    const holders = new Set(['moov', 'trak', 'mdia', 'minf', 'stbl', 'dinf']);
    for (let at = start; at < end;) {
        let size = view.getUint32(at);
        const type = String.fromCharCode(...bytes.subarray(at + 4, at + 8));
        let head = 8;
        if (size === 1) {
            size = Number(view.getBigUint64(at + 8));
            head = 16;
        }
        assert.ok(size >= head && at + size <= end, `${type} fits its parent`);
        const node = { type, at, size, head, children: [] };
        if (holders.has(type)) {
            node.children = boxes(bytes, at + head, at + size);
        } else if (type === 'stsd') {
            node.children = boxes(bytes, at + head + 8, at + size);
        } else if (type === 'avc1') {
            node.children = boxes(bytes, at + head + 78, at + size);
        }
        out.push(node);
        at += size;
    }
    return out;
}

const find = (list, path) => {
    let nodes = list;
    let node = null;
    for (const type of path.split('/')) {
        node = nodes.find((n) => n.type === type);
        assert.ok(node, `the file holds ${path}`);
        nodes = node.children;
    }
    return node;
};

const frames = (count, size = (i) => 10 + i) => Array.from({ length: count }, (_, i) => {
    const data = new Uint8Array(size(i));
    data.fill(i & 255);
    return data;
});

test('the MP4 writer places every frame where its tables say', async () => {
    const fps = 30;
    const writer = new Mp4Writer({ width: 640, height: 360, fps });
    const description = Uint8Array.of(1, 0x64, 0, 0x1f, 0xff, 0xe1, 0, 4, 0x67, 0x64, 0, 0x1f, 1, 0, 2, 0x68, 0xee);
    const list = frames(75);
    list.forEach((data, i) => writer.add(data, {
        timestamp: plan.frameTime(i, fps), duration: plan.frameDuration(i, fps), key: i % 60 === 0,
        description: i === 0 ? description.buffer : undefined,
    }));
    const blob = writer.finish();
    assert.equal(blob.type, 'video/mp4');
    const bytes = new Uint8Array(await blob.arrayBuffer());
    const view = new DataView(bytes.buffer);
    const tree = boxes(bytes);
    assert.deepEqual(tree.map((b) => b.type), ['ftyp', 'moov', 'mdat']);
    assert.equal(String.fromCharCode(...bytes.subarray(8, 12)), 'isom');
    const stbl = 'moov/trak/mdia/minf/stbl';
    const avcC = find(tree, `${stbl}/stsd/avc1/avcC`);
    assert.deepEqual([...bytes.subarray(avcC.at + 8, avcC.at + avcC.size)], [...description]);
    const avc1 = find(tree, `${stbl}/stsd/avc1`);
    assert.equal(view.getUint16(avc1.at + 32), 640);
    assert.equal(view.getUint16(avc1.at + 34), 360);
    const stsz = find(tree, `${stbl}/stsz`);
    assert.equal(view.getUint32(stsz.at + 16), list.length);
    const stco = find(tree, `${stbl}/stco`);
    assert.equal(view.getUint32(stco.at + 12), list.length);
    const mdat = find(tree, 'mdat');
    list.forEach((data, i) => {
        const size = view.getUint32(stsz.at + 20 + 4 * i);
        const offset = view.getUint32(stco.at + 16 + 4 * i);
        assert.equal(size, data.length);
        assert.ok(offset >= mdat.at + mdat.head && offset + size <= mdat.at + mdat.size);
        assert.deepEqual(bytes.subarray(offset, offset + size), data);
    });
    // One run of equal steps, the key frames at the first and the sixty first frame.
    const stts = find(tree, `${stbl}/stts`);
    assert.deepEqual([view.getUint32(stts.at + 12), view.getUint32(stts.at + 16), view.getUint32(stts.at + 20)], [1, 75, 1000]);
    const stss = find(tree, `${stbl}/stss`);
    assert.deepEqual([view.getUint32(stss.at + 12), view.getUint32(stss.at + 16), view.getUint32(stss.at + 20)], [2, 1, 61]);
    const mdhd = find(tree, 'moov/trak/mdia/mdhd');
    assert.deepEqual([view.getUint32(mdhd.at + 20), view.getUint32(mdhd.at + 24)], [30000, 75000]);
    const mvhd = find(tree, 'moov/mvhd');
    assert.equal(view.getUint32(mvhd.at + 24), 2500);
    assert.equal(tree.some((b) => b.type === 'ctts'), false);
});

test('the MP4 writer needs the decoder configuration and a frame', () => {
    const writer = new Mp4Writer({ width: 2, height: 2, fps: 30 });
    assert.throws(() => writer.finish(), /no frames/);
    writer.add(new Uint8Array(4), { timestamp: 0, duration: 33333, key: true });
    assert.throws(() => writer.finish(), /decoder configuration/);
});

// Reads the elements of EBML, with the masters that the writer makes opened.
const MASTERS = new Set([0x1a45dfa3, 0x18538067, 0x114d9b74, 0x4dbb, 0x1549a966, 0x1654ae6b, 0xae, 0xe0, 0x1f43b675, 0x1c53bb6b, 0xbb, 0xb7]);

function readVint(bytes, at, keepMarker) {
    const first = bytes[at];
    let length = 1;
    while (length <= 8 && !(first & (0x80 >> (length - 1)))) {
        length++;
    }
    let value = BigInt(keepMarker ? first : first & (0xff >> length));
    for (let i = 1; i < length; i++) {
        value = (value << 8n) | BigInt(bytes[at + i]);
    }
    return { value: Number(value), length };
}

function elements(bytes, start = 0, end = bytes.length) {
    const out = [];
    for (let at = start; at < end;) {
        const id = readVint(bytes, at, true);
        const size = readVint(bytes, at + id.length, false);
        const body = at + id.length + size.length;
        assert.ok(body + size.value <= end, `element ${id.value.toString(16)} fits its parent`);
        const node = { id: id.value, at, body, size: size.value, children: [] };
        if (MASTERS.has(id.value)) {
            node.children = elements(bytes, body, body + size.value);
        }
        out.push(node);
        at = body + size.value;
    }
    return out;
}

const uintOf = (bytes, node) => [...bytes.subarray(node.body, node.body + node.size)].reduce((v, b) => v * 256 + b, 0);

test('variable length sizes take the shortest form unless told', () => {
    assert.deepEqual([...sizeBytes(5)], [0x85]);
    assert.deepEqual([...sizeBytes(126)], [0x80 | 126]);
    assert.deepEqual([...sizeBytes(127)], [0x40, 127]);
    assert.deepEqual([...sizeBytes(1, 8)], [1, 0, 0, 0, 0, 0, 0, 1]);
});

test('the WebM writer starts a cluster at each key frame and cues every one', async () => {
    const fps = 25;
    const writer = new WebmWriter({ width: 320, height: 180, fps, codec: 'vp09.00.31.08' });
    const list = frames(130, (i) => 5 + (i % 7));
    list.forEach((data, i) => writer.add(data, { timestamp: plan.frameTime(i, fps), duration: plan.frameDuration(i, fps), key: i % 50 === 0 }));
    const blob = writer.finish();
    assert.equal(blob.type, 'video/webm');
    const bytes = new Uint8Array(await blob.arrayBuffer());
    const top = elements(bytes);
    assert.deepEqual(top.map((e) => e.id), [0x1a45dfa3, 0x18538067]);
    const docType = top[0].children.find((e) => e.id === 0x4282);
    assert.equal(String.fromCharCode(...bytes.subarray(docType.body, docType.body + docType.size)), 'webm');
    const segment = top[1];
    assert.equal(segment.body + segment.size, bytes.length);
    const kinds = segment.children.map((e) => e.id);
    assert.deepEqual(kinds, [0x114d9b74, 0x1549a966, 0x1654ae6b, 0x1f43b675, 0x1f43b675, 0x1f43b675, 0x1c53bb6b]);
    const codec = segment.children[2].children[0].children.find((e) => e.id === 0x86);
    assert.equal(String.fromCharCode(...bytes.subarray(codec.body, codec.body + codec.size)), 'V_VP9');
    const duration = segment.children[1].children.find((e) => e.id === 0x4489);
    assert.equal(new DataView(bytes.buffer).getFloat64(duration.body), 5200);
    // Every frame lies in its cluster, in order, the first of each cluster a key frame.
    const clusters = segment.children.filter((e) => e.id === 0x1f43b675);
    let index = 0;
    for (const cluster of clusters) {
        const time = uintOf(bytes, cluster.children[0]);
        cluster.children.slice(1).forEach((block, j) => {
            const relative = new DataView(bytes.buffer).getInt16(block.body + 1);
            assert.equal(time + relative, Math.round(plan.frameTime(index, fps) / 1000));
            assert.equal(!!(bytes[block.body + 3] & 0x80), j === 0);
            assert.deepEqual(bytes.subarray(block.body + 4, block.body + block.size), list[index]);
            index++;
        });
    }
    assert.equal(index, list.length);
    // The seek head and the cues point at the elements they name, from the segment's start.
    const cues = segment.children[6].children;
    assert.equal(cues.length, 3);
    cues.forEach((cue, i) => {
        const position = uintOf(bytes, cue.children[1].children[1]);
        assert.equal(segment.body + position, clusters[i].at);
    });
    for (const seek of segment.children[0].children) {
        const id = uintOf(bytes, seek.children[0]);
        const position = uintOf(bytes, seek.children[1]);
        assert.equal(segment.children.find((e) => e.at === segment.body + position).id, id);
    }
});

test('the WebM writer holds the codecs of WebM alone', () => {
    assert.throws(() => new WebmWriter({ width: 2, height: 2, fps: 30, codec: 'avc1.640028' }), /VP8, VP9 or AV1/);
    const vp8 = new WebmWriter({ width: 2, height: 2, fps: 30, codec: 'vp8' });
    assert.equal(vp8.codecId, 'V_VP8');
    assert.throws(() => vp8.finish(), /no frames/);
});
