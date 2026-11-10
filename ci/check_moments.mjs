// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Prints the moments of recording files as the page finds them, one JSON list per file, for the
// test that holds the server's index to the page, `node ci/check_moments.mjs FILE...`. With
// --cues first it prints the caption cues of each file instead, from the rosters of its header.

import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from a copy of the whole folder beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-moments-'));
cpSync(fileURLToPath(new URL('../src/cuju/render/web/js', import.meta.url)), folder, { recursive: true });
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const { parseRecording } = await import(pathToFileURL(join(folder, 'recording/format.js')).href);
const { FrameStore } = await import(pathToFileURL(join(folder, 'recording/timeline.js')).href);
const { momentsOf } = await import(pathToFileURL(join(folder, 'recording/moments.js')).href);
const { captionContext, cuesOf } = await import(pathToFileURL(join(folder, 'recording/captions.js')).href);

const cues = process.argv[2] === '--cues';
const table = JSON.parse(readFileSync(new URL('../src/cuju/render/web/captions.json', import.meta.url), 'utf8'));
const out = [];
for (const file of process.argv.slice(cues ? 3 : 2)) {
    const { header, frames } = await parseRecording(readFileSync(file));
    const moments = momentsOf(new FrameStore(header, frames));
    out.push(cues ? cuesOf(moments, captionContext(header), table.messages) : moments);
}
process.stdout.write(JSON.stringify(out));
