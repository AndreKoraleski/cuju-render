// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the page's annotations, their data, the lines of the overlay and their way through
// recordings and live streams, run from the repository root with `node tests/web/annotations.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { gunzipSync } from 'node:zlib';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from a copy beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-annotations-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/', import.meta.url)), folder, { recursive: true });
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const load = (name) => import(pathToFileURL(join(folder, name)).href);
const { Annotations, LABEL_VALUES, actionLabel, formatValue, labelHeight, labelTop, noteLines, seriesKey, seriesPath } = await load('recording/annotation-data.js');
const { StreamParser, parseHeader, parseRecording, readSections } = await load('recording/format.js');
const { decodeFrames } = await load('recording/codec.js');

const RECORDS = [
    { f: 0, p: 3, v: { value: 0.25, reward: 0 }, a: 12, k: [[12, 0.62], [11, 0.2], [13, 0.09]] },
    { f: 0, v: { pressure: 1.5 }, t: 'kick-off' },
    { f: 1, p: 3, v: { value: 0.3 } },
    { f: 2, p: 3, v: { value: 0.75 }, t: 'shot' },
    { f: 2, p: 4, v: { value: -1 } },
    { f: 9, p: 3, v: { value: 0.5 } },
];

function section(tag, payload) {
    const head = Buffer.alloc(8);
    head.write(tag);
    head.writeUInt32LE(payload.length, 4);
    return Buffer.concat([head, payload, Buffer.alloc((4 - (payload.length % 4)) % 4)]);
}

test('annotations keep one record per frame and player, the later in place of the earlier', () => {
    const data = new Annotations(RECORDS);
    assert.equal(data.size, 6);
    const first = data.at(0);
    assert.deepEqual(first.match.v, { pressure: 1.5 });
    assert.deepEqual([...first.players.keys()], [3]);
    assert.equal(data.at(5), null);
    const version = data.version;
    data.add([{ f: 0, p: 3, v: { value: 0.4 } }, { f: 'x' }, null, { f: -1 }]);
    assert.equal(data.size, 6);
    assert.ok(data.version > version);
    assert.deepEqual(data.at(0).players.get(3).v, { value: 0.4 });
});

test('the series of an annotation list the whole match first and hold their points in order', () => {
    const data = new Annotations(RECORDS);
    assert.deepEqual(data.list().map((s) => s.key), ['-1:pressure', '3:reward', '3:value', '4:value']);
    assert.equal(seriesKey('value', 3), '3:value');
    assert.equal(seriesKey('pressure'), '-1:pressure');
    assert.deepEqual(data.points('3:value'), [[0, 0.25], [1, 0.3], [2, 0.75], [9, 0.5]]);
    data.prune(2);
    assert.equal(data.size, 3);
    assert.equal(data.at(0), null);
    assert.deepEqual(data.points('3:value'), [[2, 0.75], [9, 0.5]]);
    assert.deepEqual(data.points('none'), []);
});

test('a label shows the numbers, the chosen and likely actions and the text of a record', () => {
    const lines = noteLines(RECORDS[0]);
    assert.equal(lines.values, 'value 0.25, reward 0');
    assert.equal(lines.action, 'Shot chosen, Shot 62%, Short pass 20%, Sprint 9%');
    assert.equal(lines.text, null);
    assert.deepEqual(noteLines(null), { values: null, action: null, text: null });
    assert.equal(noteLines({ f: 0, a: 0 }).action, 'Idle chosen');
    assert.equal(noteLines({ f: 0, t: 'shot' }).text, 'shot');
    const many = Object.fromEntries([...Array(9).keys()].map((k) => [`v${k}`, k]));
    assert.equal(noteLines({ f: 0, v: many }).values.split(', ').length, LABEL_VALUES);
    assert.equal(formatValue(0.123456), '0.123');
    assert.equal(formatValue(1234.5), '1230');
    assert.equal(formatValue(3), '3');
    assert.equal(actionLabel(19), 'Built-in AI');
    assert.equal(actionLabel(40), 'Action 40');
});

test('a label hangs under the feet of its player, or over the head near the controls', () => {
    // A player with the head at 300 and the feet at 340 on the screen.
    const under = labelTop(300, 340, 2, 600);
    assert.ok(under > 340, under);
    assert.ok(labelHeight(2) > labelHeight(1));
    // Near the top of the controls the label goes over the head, so it stays in view.
    const over = labelTop(300, 340, 2, 360);
    assert.ok(over + labelHeight(2) < 300, over);
});

test('a series draws as a path over the timeline that breaks across gaps', () => {
    const { path, min, max } = seriesPath([[0, 0], [1, 1], [2, 0.5], [40, 1]], 0, 100, 1000, 100);
    assert.equal(min, 0);
    assert.equal(max, 1);
    assert.equal(path, 'M0.0 100.0L10.0 0.0L20.0 50.0M400.0 0.0');
    assert.equal(seriesPath([[5, 2], [6, 2]], 0, 10, 100, 10).path, 'M50.0 5.0L60.0 5.0');
    assert.deepEqual(seriesPath([[50, 1]], 0, 10, 100, 10), { path: '', min: null, max: null });
});

test('a recording of version 2 brings its annotations section to the page', async () => {
    const bytes = gunzipSync(readFileSync(new URL('../../src/cuju/render/samples/sample-5v5.cjr', import.meta.url)));
    const plain = await parseRecording(new Uint8Array(bytes));
    assert.equal(plain.annotations, null);
    const notes = section('ANNO', Buffer.from(JSON.stringify({ records: RECORDS })));
    const annotated = await parseRecording(new Uint8Array(Buffer.concat([bytes, notes])));
    assert.deepEqual(annotated.annotations, RECORDS);
    const broken = await parseRecording(new Uint8Array(Buffer.concat([bytes, section('ANNO', Buffer.from('{oops'))])));
    assert.equal(broken.annotations, null);
    assert.equal(broken.frames.length, 3002);
});

test('a live stream with annotations hands them over between its frames', () => {
    const bytes = new Uint8Array(gunzipSync(readFileSync(new URL('../../src/cuju/render/samples/sample-5v5.cjr', import.meta.url))));
    const { header: stored, offset } = parseHeader(bytes);
    const coded = readSections(bytes, offset).get('FRMS');
    const frame = Buffer.from(decodeFrames(coded, stored.players.length, stored.frame_count, stored.keyframe_interval), 0, stored.frame_bytes);
    const { keyframe_interval: _, ...rest } = stored;
    const json = Buffer.from(JSON.stringify({ ...rest, version: 1, frame_count: null, stream_sequence: 1, stream_id: 's:0', stream_annotations: 1 }));
    const head = Buffer.alloc(12);
    head.write('CUJREC1\n');
    head.writeUInt32LE(json.length, 8);
    const serial = (value) => {
        const out = Buffer.alloc(8);
        out.writeBigUInt64LE(value);
        return out;
    };
    const payload = Buffer.from(JSON.stringify({ records: [{ f: 0, p: 1, v: { value: 2 } }] }));
    const length = Buffer.alloc(4);
    length.writeUInt32LE(payload.length);
    const stream = Buffer.concat([head, json, serial(0n), frame, serial(0xfffffffffffffffen), length, payload,
        serial(1n), frame, serial(0xffffffffffffffffn)]);
    const frames = [];
    const notes = [];
    const parser = new StreamParser(() => {}, (f) => frames.push(f.sequence), (records) => notes.push(...records));
    // Chunks of five bytes split every serial, length and object.
    for (let at = 0; at < stream.length; at += 5) {
        parser.push(stream.subarray(at, at + 5));
    }
    assert.deepEqual(frames, [0, 1]);
    assert.deepEqual(notes, [{ f: 0, p: 1, v: { value: 2 } }]);
    assert.ok(parser.ended);
});
