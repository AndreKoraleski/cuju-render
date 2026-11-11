// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the moments of a match, the wording and timing of its captions and the query helpers
// of the search of moments, run from the repository root with `node tests/web/captions.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from a copy of the whole folder beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-captions-'));
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js', import.meta.url)), folder, { recursive: true });
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const load = (name) => import(pathToFileURL(join(folder, name)).href);
const { parseRecording } = await load('recording/format.js');
const { FrameStore } = await load('recording/timeline.js');
const { MOMENT_DATA, MOMENT_KINDS, momentsOf } = await load('recording/moments.js');
const C = await load('recording/captions.js');
const { composeQuery, looksLikeMoments } = await load('recording/moments-query.js');
const language = JSON.parse(readFileSync(new URL('../../src/cuju/render/web/languages/en.json', import.meta.url), 'utf8'));
const table = { messages: Object.fromEntries(Object.entries(language).filter(([id]) => id.startsWith('caption.'))) };
const M = table.messages;

const parsed = {};
for (const name of ['sample-11v11', 'sample-5v5']) {
    parsed[name] = await parseRecording(readFileSync(new URL(`../../src/cuju/render/samples/${name}.cjr`, import.meta.url)));
}
const storeOf = (name) => new FrameStore(parsed[name].header, parsed[name].frames);

const context = {
    teams: ['Greens', null],
    players: [
        { team: 0, number: 1, name: '' },
        { team: 0, number: 9, name: 'Okafor' },
        { team: 1, number: 4, name: '' },
    ],
};

test('every message of the table is plain text with known values', () => {
    for (const [id, text] of Object.entries(M)) {
        assert.ok(/^(caption|describe)\./.test(id), id);
        assert.doesNotMatch(text, /[;:()!]/, id);
        for (const [, name] of text.matchAll(/\{([A-Za-z]+)\}/g)) {
            assert.ok(['player', 'team', 'otherTeam', 'left', 'right', 'number', 'name', 'kind'].includes(name), `${id} ${name}`);
        }
    }
});

test('a caption puts no article before a team and names every player of the team the same way', () => {
    const portuguese = JSON.parse(readFileSync(new URL('../../translations/pt.json', import.meta.url), 'utf8'));
    const own = (id) => id.startsWith('caption.') || id.startsWith('describe.');
    for (const [id, text] of Object.entries(language).filter(([key]) => own(key))) {
        assert.doesNotMatch(text, /\bthe \{(team|otherTeam)\}/i, id);
        if (text.includes('{player}') && /\{(team|otherTeam)\}/.test(text)) {
            assert.match(text, /\{player\} of \{(team|otherTeam)\}/, id);
        }
    }
    for (const [id, text] of Object.entries(portuguese).filter(([key]) => own(key))) {
        // Do, da, no and pelo hold an article, and a name such as Esquerda or Você takes none.
        assert.doesNotMatch(text, /(^|\s)(o|a|do|da|dos|das|no|na|pelo|pela) \{(team|otherTeam)\}/i, id);
        if (text.includes('{player}') && /\{(team|otherTeam)\}/.test(text)) {
            assert.match(text, /\{player\} de \{(team|otherTeam)\}/, id);
        }
    }
});

test('a caption names the player, the team and the score', () => {
    const goal = { id: 'g', kind: 'goal', t: 10, team: 0, player: 1, data: { score: [2, 1], ownGoal: false } };
    assert.deepEqual(C.captionOf(goal, context, M), {
        id: 'caption.goal', params: { player: 'number 9 Okafor', team: 'Greens', left: 2, right: 1 },
    });
    assert.equal(C.format(M, 'caption.goal', C.captionOf(goal, context, M).params), 'Goal, number 9 Okafor of Greens, 2 to 1');
    const own = { ...goal, team: 1, data: { score: [2, 2], ownGoal: true } };
    assert.equal(C.cuesOf([own], context, M)[0].text, 'Own goal, number 9 Okafor of Greens, 2 to 2');
    const unknown = { ...goal, player: undefined, team: 1 };
    assert.equal(C.cuesOf([unknown], context, M)[0].text, 'Goal for Right, 2 to 1');
    const text = (moment) => (C.cuesOf([{ id: 'x', t: 1, ...moment }], context, M)[0] || {}).text;
    assert.equal(text({ kind: 'shot', team: 1, player: 2, data: { header: true } }), 'Header at goal, number 4 of Right');
    assert.equal(text({ kind: 'save', team: 0, player: 0, data: {} }), 'Save, number 1 of Greens');
    assert.equal(text({ kind: 'card', team: 1, player: 2, data: { colour: 'red', second: true } }), 'Second yellow card and off, number 4 of Right');
    assert.equal(text({ kind: 'card', team: 1, player: 2, data: { colour: 'yellow' } }), 'Yellow card, number 4 of Right');
    assert.equal(text({ kind: 'woodwork', data: { part: 'bar' } }), 'Off the bar');
    assert.equal(text({ kind: 'nearMiss', data: { line: 'wide' } }), 'Just wide');
    assert.equal(text({ kind: 'restart', team: 0, data: { restart: 'corner' } }), 'Corner for Greens');
    assert.equal(text({ kind: 'fulltime', data: { winner: 0, score: [3, 1] } }), 'Full time, Greens win 3 to 1');
    assert.equal(text({ kind: 'fulltime', data: { winner: null, draw: true, score: [1, 1] } }), 'Full time, a draw, 1 to 1');
    // Passes, changes of possession, kick offs and moments without a player stay silent.
    assert.equal(text({ kind: 'pass', team: 0, player: 1, data: {} }), undefined);
    assert.equal(text({ kind: 'possession', team: 0, player: 1, data: {} }), undefined);
    assert.equal(text({ kind: 'restart', team: 0, data: { restart: 'kickoff' } }), undefined);
    assert.equal(text({ kind: 'shot', team: 0, data: {} }), undefined);
});

test('cues last four seconds, end at the next one and last at least a second and a half', () => {
    const at = (t) => ({ id: `m${t}`, kind: 'woodwork', t, data: {} });
    const cues = C.cuesOf([at(10), at(1), at(12), at(12.5)], context, M);
    assert.deepEqual(cues.map((c) => [c.start, c.end]), [[1, 5], [10, 12], [12, 13.5], [12.5, 16.5]]);
    assert.deepEqual(C.activeCues(cues, 12.6).map((c) => c.start), [12, 12.5]);
    assert.deepEqual(C.activeCues(cues, 6), []);
    assert.deepEqual(C.crossedCues(cues, 9.9, 12).map((c) => c.start), [10, 12]);
    assert.equal(C.vttTime(3725.0005), '01:02:05.001');
    assert.equal(C.toVtt(cues.slice(0, 1)), 'WEBVTT\n\n1\n00:00:01.000 --> 00:00:05.000\nOff the post\n');
});

test('the context reads the rosters, and players without one wear the numbers of the kits', () => {
    const header = {
        teams: [{ name: ' Reds ' }, { name: '' }],
        players: [{ team: 0, index: 0, goalkeeper: true }, { team: 0, index: 3 }, { team: 1, index: 2 }],
    };
    const styles = [{ players: [{ number: 13, name: 'Keeper' }, {}, {}, { number: 120, name: 'A very long roster name indeed' }] }];
    assert.deepEqual(C.captionContext(header, styles), {
        teams: ['Reds', null],
        players: [{ team: 0, number: 13, name: 'Keeper' }, { team: 0, number: 4, name: 'A very long roster name' },
            { team: 1, number: 3, name: '' }],
    });
});

test('the moments of the samples hold their goals with scorers and only the listed data', () => {
    const moments = momentsOf(storeOf('sample-11v11'));
    const goals = moments.filter((m) => m.kind === 'goal');
    assert.deepEqual(goals.map((g) => g.data.score), [[1, 0], [1, 1]]);
    assert.ok(goals.every((g) => g.player === g.data.scorer));
    for (const m of moments) {
        assert.ok(MOMENT_KINDS.includes(m.kind), m.kind);
        assert.ok(Object.keys(m.data).every((key) => MOMENT_DATA[m.kind].includes(key)), m.kind);
        assert.ok(!Object.values(m.data).includes('pending'), m.id);
    }
    const changes = moments.filter((m) => m.kind === 'possession');
    assert.ok(changes.length > 10 && changes.every((m) => m.data.fromTeam !== m.data.toTeam && m.data.toTeam === m.team));
    // A range of steps finds the moments of those steps, with the outcomes settled after them.
    const shot = moments.find((m) => m.kind === 'shot');
    const ranged = momentsOf(storeOf('sample-11v11'), shot.step, shot.step);
    assert.deepEqual(ranged.find((m) => m.id === shot.id), shot);
});

test('the captions of a sample time each event and read the score', () => {
    const store = storeOf('sample-5v5');
    const cues = C.cuesOf(momentsOf(store), C.captionContext(store.header), M);
    const texts = cues.map((c) => c.text);
    assert.ok(texts.some((t) => /^Goal, number \d+ of .+, 1 to 0$/.test(t)), texts.join('\n'));
    assert.match(texts.at(-1), /^Full time, a draw, 1 to 1$/);
    for (let i = 1; i < cues.length; i++) {
        assert.ok(cues[i].start >= cues[i - 1].start);
        assert.ok(cues[i - 1].end <= Math.max(cues[i].start, cues[i - 1].start + C.MIN_CUE_SECONDS) + 1e-9);
    }
    const goal = cues.find((c) => c.kind === 'goal');
    const frame = store.get(Math.round(goal.start * 10));
    assert.equal(frame.scoreLeft + frame.scoreRight, 1);
});

test('a live track holds its newest steps back until they settle', () => {
    const { header, frames } = parsed['sample-5v5'];
    const store = new FrameStore(header, frames.slice(0, 120), 4096);
    const track = new C.CueTrack(store, C.captionContext(header), M, true);
    assert.equal(track.done, 120 - 1 - C.LIVE_HOLD_STEPS);
    for (const f of frames.slice(120)) {
        store.push(f);
    }
    track.extend();
    const whole = C.cuesOf(momentsOf(new FrameStore(header, frames)), C.captionContext(header), M);
    const settled = whole.filter((c) => c.start * 10 <= store.last - C.LIVE_HOLD_STEPS + 1);
    assert.deepEqual(track.cues.map((c) => c.moment), settled.map((c) => c.moment));
});

test('the palette reads a kind or a filter as a search of moments, and the panel adds its filters', () => {
    assert.ok(looksLikeMoments('goal team:Greens'));
    assert.ok(looksLikeMoments('corners'));
    assert.ok(looksLikeMoments('team:left'));
    assert.ok(!looksLikeMoments('go to teams'));
    assert.ok(!looksLikeMoments(''));
    assert.equal(composeQuery(' goal ', { team: 'Harbour Rovers', player: '9', time: 'after:45', score: 'level' }),
        'goal team:"Harbour Rovers" player:9 score:level after:45');
    assert.equal(composeQuery('', { kind: 'corner', source: 'tournament', since: '2026-11-01' }),
        'kind:corner source:tournament since:2026-11-01');
});

test('a track that reads a recording in chunks ends with the cues of the whole of it', () => {
    const store = storeOf('sample-5v5');
    const context = C.captionContext(store.header);
    const whole = C.cuesOf(momentsOf(store), context, M);
    const track = new C.CueTrack(store, context, M, false, 100);
    assert.equal(track.done, store.first + 99);
    let rounds = 0;
    while (track.pending) {
        track.extend(100);
        rounds += 1;
    }
    assert.ok(rounds > 5);
    assert.deepEqual(track.cues, whole);
});

test('three events of one step show together', () => {
    const at = (id) => ({ id, kind: 'woodwork', t: 36.6, data: {} });
    const cues = C.cuesOf([at('a'), at('b'), at('c')], context, M);
    assert.equal(C.activeCues(cues, 36.7).length, 3);
});

test('a name in a cue stays on its line and its markup stays text in the WebVTT file', () => {
    const name = 'Reds\n\n00:00:00.000 --> 99:00:00.000\n<b>Hi</b> & <c.x>';
    const header = { teams: [{ name }, { name: 'Blues\r\n' }], players: [{ team: 0, index: 0, goalkeeper: false }] };
    const local = C.captionContext(header);
    const cues = C.cuesOf([{ id: 'g', kind: 'goal', t: 1, team: 0, player: 0, data: { score: [1, 0], ownGoal: false } }], local, M);
    assert.ok(cues[0].text.includes(name.trim()), cues[0].text);
    const vtt = C.toVtt(cues);
    const lines = vtt.split('\n');
    assert.equal(lines.length, 6, vtt);
    assert.equal(lines.filter((line) => line.includes('-->')).length, 1, vtt);
    assert.ok(!/[<>]/.test(lines[4]) && lines[4].includes('&lt;b&gt;Hi&lt;/b&gt; &amp; &lt;c.x&gt;'), lines[4]);
    assert.ok(lines[4].includes('Reds 00:00:00.000 --&gt; 99:00:00.000 &lt;b&gt;'), lines[4]);
    assert.equal(C.vttText('a \r\n\r\n  b\rc\nd'), 'a b c d');
    assert.equal(C.vttText('1 < 2 > 0 && -->'), '1 &lt; 2 &gt; 0 &amp;&amp; --&gt;');
    assert.equal(C.vttText(null), '');
});
