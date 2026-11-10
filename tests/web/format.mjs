// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the page's reader of recording versions 1 and 2, run from the repository root with
// `node tests/web/format.mjs`.

import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { gunzipSync, gzipSync } from 'node:zlib';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from a copy beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-format-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/', import.meta.url)), folder, { recursive: true });
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const load = (name) => import(pathToFileURL(join(folder, name)).href);
const { FormatError, parseHeader, parseRecording, readSections } = await load('recording/format.js');
const { FRAMES_TAG, decodeFrames } = await load('recording/codec.js');

// The SHA-256 of the frames of each shipped sample as version 1 stores them, which the samples of
// version 2 must decode to bit for bit. tests/test_recordings.py checks the same digests in Python.
const DIGESTS = {
    'sample-11v11': '518c377d7b32648e94e9fb9c33baa70fcf5ea9232be7d8c4bf368638fdd94076',
    'sample-5v5': 'b41e32efb5decbece8ea3a1ab949e2f1e62c8052e4929f7a1f429a938e6b0d27',
};

const sample = (name) => new Uint8Array(gunzipSync(readFileSync(new URL(`../../src/cuju/render/samples/${name}.cjr`, import.meta.url))));

// The frames of a sample decoded to version 1, with its header.
function decoded(name) {
    const bytes = sample(name);
    const { header, offset } = parseHeader(bytes);
    const coded = readSections(bytes, offset).get(FRAMES_TAG);
    const frames = new Uint8Array(decodeFrames(coded, header.players.length, header.frame_count, header.keyframe_interval));
    return { header, frames };
}

// A recording of version 1 with the same frames, magic, header and frames back to back.
function versionOne(header, frames, version = 1) {
    const document = { ...header, version };
    delete document.keyframe_interval;
    let json = Buffer.from(JSON.stringify(document));
    json = Buffer.concat([json, Buffer.alloc((4 - ((12 + json.length) % 4)) % 4, 0x20)]);
    const head = Buffer.alloc(12);
    head.write('CUJREC1\n');
    head.writeUInt32LE(json.length, 8);
    return new Uint8Array(Buffer.concat([head, json, Buffer.from(frames)]));
}

for (const name of Object.keys(DIGESTS)) {
    test(`${name} of version 2 decodes to the frames of version 1 bit for bit`, () => {
        const started = performance.now();
        const { header, frames } = decoded(name);
        const seconds = (performance.now() - started) / 1000;
        assert.equal(header.version, 2);
        assert.equal(frames.length, header.frame_count * header.frame_bytes);
        assert.equal(createHash('sha256').update(frames).digest('hex'), DIGESTS[name]);
        console.log(`# ${name} decodes in ${seconds.toFixed(2)} s`);
    });

    test(`${name} reads the same through versions 1 and 2`, async () => {
        const compressed = readFileSync(new URL(`../../src/cuju/render/samples/${name}.cjr`, import.meta.url));
        const two = await parseRecording(new Uint8Array(compressed));
        const { header, frames } = decoded(name);
        const one = await parseRecording(gzipSync(versionOne(header, frames)));
        assert.equal(one.header.version, 1);
        assert.equal(two.frames.length, header.frame_count);
        assert.equal(one.frames.length, two.frames.length);
        for (const index of [0, 1, 99, 100, 101, 1500, two.frames.length - 1]) {
            assert.deepEqual(two.frames[index], one.frames[index], `frame ${index}`);
        }
    });
}

test('a reader skips sections it does not know and refuses a cut frames section', async () => {
    const bytes = sample('sample-5v5');
    const { offset } = parseHeader(bytes);
    const extra = Buffer.alloc(8 + 4);
    extra.write('XTRA');
    extra.writeUInt32LE(3, 4);
    const longer = new Uint8Array(Buffer.concat([Buffer.from(bytes.subarray(0, offset)), extra, Buffer.from(bytes.subarray(offset))]));
    const parsed = await parseRecording(longer);
    assert.equal(parsed.frames.length, 3002);
    await assert.rejects(parseRecording(bytes.subarray(0, bytes.length - 100)), FormatError);
});

test('a header of an unknown version is refused with its number', async () => {
    const { header, frames } = decoded('sample-5v5');
    const bytes = versionOne(header, frames.subarray(0, header.frame_bytes), 3);
    await assert.rejects(parseRecording(bytes), /version 3 is not supported/);
});
