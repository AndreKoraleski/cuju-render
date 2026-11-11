// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the groups of the Recordings page, run from the repository root with
// `node tests/web/recording_groups.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's module
// loads from a copy beside a package file that names it a module.
const folder = mkdtempSync(join(tmpdir(), 'cuju-groups-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js/pages/recording-groups.js', import.meta.url)), join(folder, 'pages/recording-groups.js'));
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const { groupOf, groupRows, groupTotals, navigationRows } = await import(pathToFileURL(join(folder, 'pages/recording-groups.js')).href);

function member(id, group, attempt, extra = {}) {
    return { id, group: { id: group, attempt, title: `Run ${group}` }, steps: 10, bytes: 100, created: `2026-11-1${attempt}T10:00:00`, ...extra };
}

test('a run of attempts is one item at the place of its first row, in attempt order', () => {
    const rows = [
        { id: 'm-a' },
        member('m-3', 'g-1', 2),
        { id: 'm-b' },
        member('m-1', 'g-1', 0),
        member('m-x', 'g-2', 0),
        member('m-2', 'g-1', 1),
    ];
    const items = groupRows(rows);
    assert.deepEqual(items.map((item) => item.kind), ['recording', 'group', 'recording', 'group']);
    assert.deepEqual(items[1].members.map((m) => m.id), ['m-1', 'm-2', 'm-3']);
    assert.equal(items[1].id, 'g-1');
    assert.deepEqual(items[3].members.map((m) => m.id), ['m-x']);
});

test('a summary without a valid group stays a recording of its own', () => {
    for (const group of [undefined, null, 'g-1', {}, { id: '' }, { id: 7 }]) {
        assert.equal(groupOf({ id: 'm', group }), null);
        assert.equal(groupRows([{ id: 'm', group }])[0].kind, 'recording');
    }
});

test('the totals of a group add steps and bytes and keep the newest date', () => {
    const members = [member('m-1', 'g', 0), member('m-2', 'g', 2), member('m-3', 'g', 1, { steps: null, created: 'never' })];
    assert.deepEqual(groupTotals(members), { steps: 20, bytes: 300, created: '2026-11-12T10:00:00' });
    assert.deepEqual(groupTotals([]), { steps: 0, bytes: 0, created: null });
});

test('the keyboard walks a closed group as one row and an open one with its members', () => {
    const items = groupRows([{ id: 'm-a' }, member('m-1', 'g-1', 0), member('m-2', 'g-1', 1)]);
    const closed = navigationRows(items, new Set());
    assert.deepEqual(closed.map((row) => row.key), ['m-a', 'group:g-1']);
    assert.deepEqual(closed[1].ids, ['m-1', 'm-2']);
    const open = navigationRows(items, new Set(['g-1']));
    assert.deepEqual(open.map((row) => row.key), ['m-a', 'group:g-1', 'm-1', 'm-2']);
    assert.equal(open[2].parent, 'g-1');
    assert.equal(open[1].group.id, 'g-1');
});
