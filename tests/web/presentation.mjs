// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the team presentation contract, its clocks, protocol, behaviours, animator, tracks,
// custody, budgets, commands and worker host, run from the repository root with
// `node tests/web/presentation.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import vm from 'node:vm';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from copies beside a package file that names them modules.
const folder = mkdtempSync(join(tmpdir(), 'cuju-presentation-'));
const inner = join(folder, 'presentation');
mkdirSync(inner);
const names = ['values', 'clocks', 'contract', 'behaviors', 'animator', 'tracks', 'protocol', 'budget', 'commands', 'host'];
for (const name of names) {
    cpSync(fileURLToPath(new URL(`../../src/cuju/render/web/js/presentation/${name}.js`, import.meta.url)), join(inner, `${name}.js`));
}
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const load = (name) => import(pathToFileURL(join(inner, `${name}.js`)).href);
const { Clocks, MAX_STEP } = await load('clocks');
const C = await load('contract');
const { BehaviourSet, checkBehaviour } = await load('behaviors');
const { Animator, actionRole } = await load('animator');
const T = await load('tracks');
const { appendLog, checkResponse, frameMessage, helloMessage, LOG_LINES, MAXIMUM_COMMANDS } = await load('protocol');
const { Budget, LADDER, RECOVER_S, RECOVERIES, SUSTAIN_S, WINDOW_S } = await load('budget');
const K = await load('commands');
const { MAXIMUM_OVERLAYS, ModuleHost, RESTARTS, SILENT_STEP_MS, replyProblem } = await load('host');
const { FIRST_SILENT_MS, SILENT_MS } = await load('budget');
const { unit } = await load('values');

const manifestText = readFileSync(new URL('../support/team/cuju-team/presentation/presentation.json', import.meta.url), 'utf8');
const packageManifest = () => C.normalize(JSON.parse(manifestText));

test('the clocks follow the timeline, the ceremonies and real time, each step held', () => {
    const c = new Clocks();
    c.advance({ dt: 0.016, t: 10, sps: 10 });
    c.advance({ dt: 0.016, t: 10.32, sps: 10 });
    assert.ok(Math.abs(c.simStep - 0.032) < 1e-12, 'double speed doubles the simulation step');
    assert.equal(c.step, 10);
    assert.ok(Math.abs(c.fraction - 0.32) < 1e-9);
    assert.equal(c.ceremonyStep, 0, 'no ceremony, no ceremony time');
    c.advance({ dt: 0.016, t: 10, sps: 10, ceremony: true });
    assert.ok(c.simStep < 0, 'reverse runs the simulation clock back');
    assert.equal(c.ceremonyStep, 0.016);
    c.advance({ dt: 0.016, t: 10, sps: 10, ceremony: true, held: true });
    assert.equal(c.ceremonyStep, 0, 'a paused show holds the ceremony clock');
    const before = c.cosmetic;
    c.advance({ dt: 30, t: 500, sps: 10 });
    assert.equal(c.cosmetic - before, MAX_STEP, 'a tab back from the background resumes without a jump');
    assert.equal(c.sim, 50, 'a seek moves the simulation clock at once');
    c.seek();
    assert.equal(c.ceremony, 0, 'a seek starts the ceremony clock again');
    assert.deepEqual(Object.keys(c.snapshot()), ['sim', 'step', 'fraction', 'ceremony', 'cosmetic', 'audio']);
});

test('versions and features decide the level a package runs at', () => {
    assert.ok(C.supports('1.0') && C.supports('1.1'), 'a renderer of 1.1 serves the packages of 1.0');
    assert.ok(!C.supports('1.2') && !C.supports('2.0') && !C.supports('one'));
    assert.equal(C.normalize({ contract: '2.0' }), null);
    const m = packageManifest();
    assert.deepEqual(C.level(m), { level: 'worker', missing: [], lacking: ['audio.spatial'] });
    assert.equal(C.level({ requires: ['geometry.worker', 'shader.custom', 'post.layer'] }).level, 'worker', 'contract 1.1 implements every feature');
    assert.equal(C.level({ requires: ['future.thing'] }).level, 'stock', 'an unknown feature drops the package');
    assert.deepEqual(C.PLANNED, []);
    assert.equal(C.driverOf(m, { goalkeeper: true }), 'grf+layers');
    assert.equal(C.driverOf(m, { goalkeeper: false }), 'team');
    assert.equal(C.modelOf(m, { goalkeeper: true, number: 1 }), 'models/keeper.glb');
    assert.equal(C.modelOf(m, { goalkeeper: false, number: 7 }), null);
    assert.equal(C.pickClip(m, 'header').clip, 'Kick', 'header falls back to kick');
    assert.equal(C.pickClip(m, 'salute').clip, 'Cheer', 'salute falls back through reaction.win to celebration');
    assert.equal(C.stillRole('hands_on_head'), 'lament');
    const base = C.seedBase({ provenance: { seed: 7 } });
    assert.equal(C.seed(base, 0, 'p1', 'e'), C.seed(base, 0, 'p1', 'e'));
    assert.notEqual(C.seed(base, 0, 'p1', 'e'), C.seed(base, 1, 'p1', 'e'));
});

test('a spin integrates its rate, so a change of speed never makes it jump', () => {
    const set = new BehaviourSet({ entity: 5 });
    set.set(checkBehaviour({ id: 'spin', type: 'spin', clip: 'Orbit', period: 20, rate: { input: 'speed', keys: [[0, 2.4], [7, 4.4]] } }));
    let last = null;
    for (let i = 0; i < 600; i++) {
        const speed = i < 200 ? 0 : i < 400 ? 7 : 3;
        const phase = set.evaluate({ dt: 1 / 60, inputs: { speed } }).clipTime.get('Orbit');
        if (last !== null) {
            const step = ((phase - last) % 20 + 20) % 20;
            assert.ok(step <= 4.4 / 60 + 1e-9 && step >= 2.4 / 60 - 1e-9, `step ${step} at ${i}`);
        }
        last = phase;
    }
    set.reset();
    assert.equal(set.evaluate({ dt: 0, inputs: { speed: 3 } }).clipTime.get('Orbit'), last, 'a reset keeps the phase');
    // A spin by distance turns with the ground covered, forward and back.
    const road = new BehaviourSet({ entity: 1 });
    road.set(checkBehaviour({ id: 'wheel', type: 'spin', node: 'w', rate: 2, phaseFrom: 'distance' }));
    const a = road.evaluate({ dt: 1, distance: 1.5, inputs: {} }).nodes.get('w').spins[0].angle;
    const b = road.evaluate({ dt: 1, distance: -1.5, inputs: {} }).nodes.get('w').spins[0].angle;
    assert.ok(Math.abs(a - b - 3) < 1e-9, 'reverse play turns the wheel back');
});

test('oscillators start apart by seed, and reduced motion scales them', () => {
    const spec = checkBehaviour({ id: 'hover', type: 'oscillate', channel: 'y', amp: 1, freq: 1, seed: 'number' });
    const a = new BehaviourSet({ number: 4 });
    const b = new BehaviourSet({ number: 6 });
    a.set(spec);
    b.set(spec);
    for (let i = 0; i < 20; i++) {
        a.evaluate({ dt: 0.05, inputs: {} });
        b.evaluate({ dt: 0.05, inputs: {} });
    }
    assert.notEqual(a.evaluate({ dt: 0.01, inputs: {} }).root.y, b.evaluate({ dt: 0.01, inputs: {} }).root.y);
    assert.notEqual(unit(4, 'hover'), unit(6, 'hover'));
    const calm = new BehaviourSet({ number: 4 });
    const twin = new BehaviourSet({ number: 4 });
    calm.set(spec);
    twin.set(spec);
    for (let i = 0; i < 20; i++) {
        calm.evaluate({ dt: 0.05, inputs: {}, reducedMotion: 0.3 });
        twin.evaluate({ dt: 0.05, inputs: {} });
    }
    const full = twin.evaluate({ dt: 0, inputs: {} }).root.y;
    const quiet = calm.evaluate({ dt: 0, inputs: {}, reducedMotion: 0.3 }).root.y;
    assert.ok(Math.abs(quiet - 0.3 * full) < 1e-9, 'reduced motion takes the amplitude down to its share');
});

test('springs settle, gaze keeps its limits and slew, stopped behaviours fade', () => {
    const set = new BehaviourSet({});
    set.set(checkBehaviour({ id: 'lift', type: 'spring', channel: 'y', goal: { input: 'ceremony.amount', keys: [[0, 0], [1, 0.3]] } }));
    set.set(checkBehaviour({ id: 'look', type: 'lookAt', node: 'head', yawLimit: 0.5, slew: 2, rate: 100 }));
    const looks = (yaw) => () => ({ yaw, pitch: 0 });
    set.evaluate({ dt: 0.016, inputs: { 'ceremony.amount': 0 }, looks: looks(0) });
    let out;
    for (let i = 0; i < 300; i++) {
        out = set.evaluate({ dt: 0.016, inputs: { 'ceremony.amount': 1 }, looks: looks(3) });
    }
    assert.ok(Math.abs(out.root.y - 0.3) < 1e-3);
    assert.ok(Math.abs(out.looks[0].yaw - 0.5) < 1e-9, 'the yaw stays within its limit');
    const fresh = new BehaviourSet({});
    fresh.set(checkBehaviour({ id: 'look', type: 'lookAt', node: 'head', slew: 2, rate: 100 }));
    fresh.evaluate({ dt: 0.01, inputs: {}, looks: looks(0) });
    assert.ok(fresh.evaluate({ dt: 0.1, inputs: {}, looks: looks(3) }).looks[0].yaw <= 0.2 + 1e-9, 'the gaze turns at most at its slew');
    set.stop('lift', 0.2);
    for (let i = 0; i < 20; i++) {
        set.evaluate({ dt: 0.016, inputs: {} });
    }
    assert.ok(!set.items.has('lift'), 'a stopped behaviour goes once faded');
    set.set(checkBehaviour({ id: 'w', type: 'bank' }), 'worker');
    set.stopSource('worker', 0.5);
    assert.ok(set.items.get('w').stopping);
    assert.throws(() => checkBehaviour({ type: 'warp' }));
    assert.throws(() => checkBehaviour({ type: 'oscillate', amp: { input: 'mood' } }));
});

const lengths = { Idle: 1, Run: 1, Kick: 1, Cheer: 1 };
const clipInfo = (n) => (lengths[n] ? { duration: lengths[n], marker: n === 'Kick' ? 0.5 : undefined } : null);

test('locomotion follows the distance covered and blends by speed', () => {
    const m = packageManifest();
    const anim = new Animator(m, clipInfo, 4);
    const at = (speed, distance) => anim.layers({ sim: 0, speed, distance, decel: 0, turnRate: 0, cosmetic: 0 });
    assert.deepEqual(at(0, 0).map((l) => l.clip), ['Idle']);
    const mid = at(2.5, 1);
    assert.deepEqual(mid.map((l) => [l.clip, l.weight]), [['Idle', 0.5], ['Run', 0.5]]);
    // Run's stride is 5 m, so 7.5 m of ground puts it half way through its cycle, whatever the time.
    assert.equal(at(5, 7.5).find((l) => l.clip === 'Run').time, 0.5);
    assert.equal(at(5, 7.5).find((l) => l.clip === 'Run').time, at(5, 7.5).find((l) => l.clip === 'Run').time);
    let last = null;
    for (let s = 0; s <= 5; s += 0.05) {
        const w = Object.fromEntries(at(s, 0).map((l) => [l.clip, l.weight]));
        const sum = Object.values(w).reduce((a, b) => a + b, 0);
        assert.ok(Math.abs(sum - 1) < 1e-9);
        if (last) {
            assert.ok(Math.abs((w.Run || 0) - (last.Run || 0)) < 0.011, 'the blend moves smoothly with speed');
        }
        last = w;
    }
    const none = new Animator(m, () => null, 1);
    assert.deepEqual(none.layers({ sim: 0, speed: 3 }), [], 'a model without the clips leaves GRF its nodes');
});

test('an action clip meets the contact, its wind-up sped up for a short warning', () => {
    const s = T.contactSchedule(0.5, 1, 10, 2.5);
    assert.deepEqual([s.from, s.to, s.rate], [9.5, 10.5, 1]);
    assert.equal(T.contactClipTime(s, 0.5, 10, 10), 0.5, 'the marker meets the contact');
    const short = T.contactSchedule(0.5, 1, 10, 0.3);
    assert.ok(Math.abs(short.rate - 5 / 3) < 1e-9, 'a wind-up longer than the warning plays faster');
    assert.equal(T.contactClipTime(short, 0.5, 10, 10), 0.5);
    const late = T.contactSchedule(0.5, 1, 10, 0.1);
    assert.equal(late.rate, 2, 'up to twice as fast');
    assert.ok(Math.abs(late.offset - 0.3) < 1e-9, 'past that the clip starts later');
    const m = packageManifest();
    const anim = new Animator(m, clipInfo, 2);
    const kick = { id: 'touch:100:1', kind: 'touch', t: 10, step: 100, player: 3, team: 0, data: { kind: 'kick', action: 0, contactT: 10 } };
    const action = anim.schedule(kick, 2.5);
    assert.equal(action.role, 'kick');
    assert.equal(anim.schedule(kick, 0.1), action, 'a seek back finds the same schedule');
    const at = (sim) => anim.layers({ sim, speed: 0, distance: 0, decel: 0, turnRate: 0, cosmetic: 0 });
    assert.equal(at(10).find((l) => l.clip === 'Kick').time, 0.5);
    assert.equal(at(10).find((l) => l.clip === 'Kick').weight, 1);
    assert.ok(!at(9).some((l) => l.clip === 'Kick'), 'nothing before the wind-up');
    assert.deepEqual(at(9.8), at(9.8), 'the same moment draws the same pose');
    anim.cancel(kick.id, 9.7);
    assert.ok(!at(9.9).some((l) => l.clip === 'Kick'), 'a cancelled forecast fades out within 0.15 s');
    assert.equal(actionRole({ kind: 'pass', data: { type: 'high' } }), 'pass.high');
    assert.equal(actionRole({ kind: 'save', data: { side: 'left' } }), 'dive.left');
    assert.equal(actionRole({ kind: 'restart.taken', data: { restart: 'corner' } }), 'restart.corner');
    assert.equal(actionRole({ kind: 'touch', data: { action: 4 } }, 5), 'throwIn');
});

test('the track ledger keeps tracks across epochs and replays them by policy', () => {
    const ledger = new T.Ledger();
    const clocks = new Clocks();
    const track = T.checkTrack({ id: 'fire', entity: 'p1', from: 1, to: 3, clock: 'sim', content: { kind: 'clip', clip: 'Kick' }, replay: 'skip' }, new Set(['p1']));
    ledger.put(track);
    assert.equal(T.checkTrack({ id: 'x', entity: 'p9', from: 0, to: 1, content: { kind: 'clip' } }, new Set(['p1'])), null, 'never the opponent');
    clocks.advance({ t: 20, sps: 10 });
    assert.equal(ledger.active(clocks)[0].local, 1);
    assert.equal(ledger.active(clocks, { replay: true }).length, 0, 'skip stays out of replays');
    clocks.advance({ t: 40, sps: 10 });
    assert.equal(ledger.active(clocks).length, 0);
    clocks.advance({ t: 15, sps: 10 });
    assert.equal(ledger.active(clocks).length, 1, 'a seek back finds the track again');
    ledger.dropSource('manifest');
    assert.equal(ledger.tracks.size, 0);
});

test('custody goes to the stronger touch and ends on the next one', () => {
    const touch = (team, kind, action, step = 5, player = team) => ({ id: `touch:${step}:${team}`, kind: 'touch', phase: 'occur', team, step, t: step / 10, player, data: { kind, action } });
    const a = touch(0, 'kick', 8);
    const b = touch(1, 'intended', 4);
    assert.equal(T.Custody.winner([a, b]), 0);
    assert.equal(T.Custody.winner([touch(0, 'kick', 4), touch(1, 'kick', 4)]), -1, 'an exact tie grants nobody');
    assert.equal(T.Custody.winner([touch(0, 'kick', 4), touch(1, 'kick', 8)]), 1, 'a shot beats a pass');
    const c = new T.Custody();
    assert.ok(!c.claim(1, b, [a, b]));
    assert.ok(c.claim(0, a, [a, b]));
    c.observe([touch(1, 'accidental', 0, 9)], 0.9);
    assert.equal(c.holder, null, 'a later touch ends custody');
    c.claim(0, a, [a]);
    c.observe([], 0.5 + T.MAX_CUSTODY + 0.1);
    assert.equal(c.holder, null, 'custody lasts six seconds at most');
});

test('a reply is checked, held to its ranges and kept to the team', () => {
    const expect = {
        instanceId: 'a.1', epoch: 3, own: new Set(['p1', 'p2']), files: new Set(['fx/ring.glb']),
        envelope: () => ({ radius: 0.8, height: 2 }),
    };
    assert.equal(checkResponse({ type: 'response', instanceId: 'a.1', epoch: 2 }, expect).reason, 'stale');
    assert.equal(checkResponse({ type: 'response', instanceId: 'b.1', epoch: 3 }, expect).reason, 'foreign');
    assert.equal(checkResponse({ type: 'hello' }, expect).reason, 'malformed');
    const many = Array.from({ length: 100 }, () => ({ entity: 'p1', current: { radius: 9, height: 9 } }));
    const { ok, response } = checkResponse({
        type: 'response', instanceId: 'a.1', epoch: 3, sourceFrameId: 7,
        bounds: [{ entity: 'p7', current: { radius: 1, height: 1 } }, ...many],
        behaviours: [
            { op: 'set', id: 'spin', behaviour: { type: 'spin', node: 'ring', rate: 2 } },
            { op: 'set', id: 'bad', behaviour: { type: 'warp' } },
            { op: 'stop', id: 'spin', entity: 'p7' },
        ],
        tracks: [{ id: 't', entity: 'p2', from: 0, to: 1, content: { kind: 'clip', clip: 'Kick' } }, { id: 'u', entity: 'p7', from: 0, to: 1, content: { kind: 'clip' } }],
        effects: [{ op: 'spawn', id: 'x', kind: 'trail', attach: 'ball' }, { op: 'spawn', id: 'y', kind: 'glow', attach: { entity: 'p7' } }],
        audio: [{ op: 'play', cue: 'goal', gain: 4 }, { op: 'blast' }],
        claims: [{ target: 'ball', event: 'touch:5:1' }, { target: 'referee', event: 'x' }],
        camera: { event: 'goal:1', shot: 'orbit', duration: 30 },
        time: { event: 'goal:1', freeze: 2 },
        overlays: [{ slot: 'scoreBug' }, { slot: 'badge' }],
        resources: [{ op: 'load', id: 'r', file: 'fx/ring.glb' }, { op: 'load', id: 's', file: '../x' }],
    }, expect);
    assert.ok(ok);
    assert.equal(response.bounds.length, MAXIMUM_COMMANDS - 1);
    assert.deepEqual(response.bounds[0], { entity: 'p1', current: { radius: 0.8, height: 2 } });
    assert.equal(response.behaviours.length, 1);
    assert.equal(response.tracks.length, 1);
    assert.equal(response.effects.length, 1, 'never an effect on the opponent');
    assert.equal(response.audio[0].gain, 1, 'a package can only lower its sound');
    assert.equal(response.claims.length, 1);
    assert.equal(response.camera.duration, 4);
    assert.equal(response.time.freeze, 0.3);
    assert.deepEqual(response.overlays, [{ slot: 'badge', op: 'show' }]);
    assert.equal(response.resources.length, 1);
    assert.ok(response.rejected >= 9);
});

test('a frame and a hello carry what the contract lists', () => {
    const c = new Clocks().advance({ dt: 0.01, t: 20, sps: 10 });
    const f = frameMessage({
        instanceId: 'a.1', epoch: 1, frameId: 4, clocks: c.snapshot(), playback: null, quality: 'high',
        players: [{ entity: 'p1', player: 1, team: 0, root: [1.234567, 2, 0], facing: 0.1234567, velocity: [0.1, 0], speed: 1, distance: 3 }],
        ball: { pos: [0, 0, 0.11], rot: [0, 0, 0, 1], velocity: [0, 0, 0] }, game: {}, events: [], camera: null,
    });
    assert.equal(f.players[0].root[0], 1.2346);
    assert.equal(f.clocks.sim, 2);
    assert.doesNotThrow(() => structuredClone(f));
    const h = helloMessage({ features: ['drivers.team'], instanceId: 'a.1', team: 0, attack: 1, roster: [], header: {}, seedBase: 1 });
    assert.equal(h.contract, '1.1');
});

test('budgets count, refuse and step down the ladder on sustained overruns', () => {
    const b = new Budget('low');
    assert.equal(b.limits.lights, 1);
    assert.ok(b.take({ lights: 1, triangles: 60000 }));
    assert.ok(!b.take({ lights: 1 }));
    assert.equal(b.snapshot().refused.lights, 1);
    b.give({ lights: 1 });
    assert.ok(b.take({ lights: 1 }));
    const sustained = WINDOW_S * 0.75 + SUSTAIN_S;
    for (let t = 0; t < sustained - 0.1; t += 0.016) {
        assert.equal(b.meter(2, t), null, 'a short overrun is forgiven');
    }
    let rung = null;
    for (let t = sustained - 0.1; t < sustained + 0.3 && !rung; t += 0.016) {
        rung = b.meter(2, t);
    }
    assert.equal(rung, LADDER[1]);
    assert.equal(b.stepped, 'down');
    while (b.level !== 'stock') {
        b.degrade('test');
    }
    assert.ok(b.past('noWorker'));
    assert.equal(b.degrade('again'), 'stock', 'the ladder ends at the stock look');
});

// A browser that coarsens performance.now() reads each drawing's time in steps of 0.1 ms, here
// a package of a given mean whose drawings read in coarse steps up to three times the mean.
function coarse(index, mean) {
    const steps = [0, 0.1, 0.3, 0.6, 0, 0.1, 0.3, 0.2];
    return steps[index % steps.length] * (mean / 0.2);
}

test('the meter reads the mean of a coarse clock and keeps a package under its budget', () => {
    const b = new Budget('low');
    assert.equal(b.limits.mainMs, 1);
    let i = 0;
    for (let t = 0; t < 60; t += 0.016, i++) {
        assert.equal(b.meter(coarse(i, 0.5), t), null, 'single drawings over the budget never step down');
    }
    assert.ok(Math.abs(b.mainMs - 0.5) < 0.02, `the mean of the window, ${b.mainMs}`);
    assert.ok(b.p95 > b.limits.mainMs, 'the 95th percentile of the coarse steps reads over the budget');
    assert.equal(b.level, 'full');
});

test('the meter waits for the package to settle and leaves out stalled drawings', () => {
    const b = new Budget('low');
    b.arm(Infinity);
    for (let t = 0; t < 20; t += 0.016) {
        assert.equal(b.meter(5, t), null, 'nothing counts before the package settled');
    }
    b.arm(20);
    for (let t = 20; t < 40; t += 0.5) {
        assert.equal(b.meter(5, t, 400), null, 'a drawing that stalls the page is left out');
    }
    assert.equal(b.samples.length, 0);
    assert.equal(b.level, 'full');
});

test('the ladder climbs back after a while under budget, slower after each relapse', () => {
    const b = new Budget('low');
    let t = 0;
    const run = (ms, seconds) => {
        const steps = [];
        for (const end = t + seconds; t < end; t += 0.016) {
            const rung = b.meter(ms, t);
            if (rung) {
                steps.push([rung, b.stepped, t]);
            }
        }
        return steps;
    };
    const down = run(2, 6);
    assert.deepEqual(down.map((s) => s[0]), ['fewerParticles'], 'one rung for a sustained overrun');
    const up = run(0.1, RECOVER_S + 3);
    assert.deepEqual(up.map((s) => [s[0], s[1]]), [['full', 'up']], 'a team well under budget climbs back');
    assert.ok(up[0][2] - down[0][2] >= RECOVER_S, 'after RECOVER_S under budget');
    run(2, 6);
    assert.equal(b.level, 'fewerParticles');
    assert.equal(b.relapses, 1, 'a fall after a climb is a relapse');
    assert.deepEqual(run(0.1, RECOVER_S + 3), [], 'a relapse doubles the wait');
    assert.equal(run(0.1, RECOVER_S + 3).length, 1);
    assert.equal(b.level, 'full');
    // Between the budget and its share UNDER the ladder holds.
    run(2, 6);
    assert.deepEqual(run(0.9, 4 * RECOVER_S), [], 'a team just under its budget stays where it is');
    for (let k = 0; k < 3 * RECOVERIES; k++) {
        run(2, 6);
        run(0.1, RECOVER_S * 2 ** RECOVERIES + 3);
    }
    assert.ok(b.relapses >= RECOVERIES);
    const rung = b.rung;
    run(0.1, 4 * RECOVER_S * 2 ** RECOVERIES);
    assert.equal(b.rung, rung, `after ${RECOVERIES} relapses the ladder stays down`);
    while (b.level !== 'stock') {
        run(5, 6);
    }
    assert.equal(b.level, 'stock', 'a package that really overruns still ends at the stock look');
});

test('reflexes fire for their team and phase, and commands reach their handlers', () => {
    const m = packageManifest();
    const own = new Set(['p1']);
    const touch = { id: 'touch:5:1', kind: 'touch', phase: 'occur', team: 0, player: 1 };
    assert.equal(K.reflexesFor(m, touch, 0).length, 1);
    assert.equal(K.reflexesFor(m, touch, 1).length, 0, 'a team answers its own touches');
    assert.equal(K.reflexesFor(m, { ...touch, phase: 'forecast' }, 0).length, 0);
    const actions = K.reflexActions(K.reflexesFor(m, touch, 0)[0], { ...touch, replay: { of: 'goal' } }, own);
    assert.deepEqual(actions.map((a) => a.kind), ['audio', 'effects', 'claim', 'effects']);
    assert.equal(actions[0].command.gain, 0.5, 'a quiet replay halves the sound');
    const seen = [];
    K.register('effects', (c) => seen.push(c) > 0);
    assert.ok(K.dispatch('effects', actions[1].command, {}));
    assert.ok(!K.dispatch('environment', {}, {}));
    assert.equal(K.dropped.environment, 1, 'a command without a handler is counted');
    assert.equal(K.occlusion([0, 1, 5], [0, 1, 0], [[0, 1, 10]]), K.OCCLUSION.floor, 'an effect in front of the ball fades');
    assert.equal(K.occlusion([3, 1, 5], [0, 1, 0], [[0, 1, 10]]), 1);
    assert.equal(K.SAFETY.loudness.integrated, -23);
    assert.equal(K.SAFETY.flashes.perSecond, 3);
});

// A stand-in for the sandbox iframe and its port, which answers as the test tells it.
class FakeDocument {
    constructor() {
        this.frames = [];
        this.body = { appendChild: (f) => this.frames.push(f) };
    }
    createElement() {
        const listeners = {};
        return {
            setAttribute(k, v) {
                this[k] = v;
            },
            style: {},
            addEventListener(k, fn) {
                listeners[k] = fn;
            },
            fire(k) {
                listeners[k]();
            },
            contentWindow: { postMessage: (m) => { this.started = m; } },
            remove() {
                this.removed = true;
            },
        };
    }
}

test('the host refuses an open network, restarts a silent worker once and then gives up', () => {
    globalThis.location = { href: 'http://127.0.0.1:1/' };
    globalThis.addEventListener = () => {};
    globalThis.removeEventListener = () => {};
    const doc = new FakeDocument();
    const statuses = [];
    const make = () => new ModuleHost({
        source: 'export function frame() { return {}; }', instanceId: 'a.1', hello: { instanceId: 'a.1' }, document: doc,
        onResponse: () => {}, onStatus: (s, d) => statuses.push([s, d]),
    });
    const open = make();
    const frame = doc.frames.at(-1);
    assert.equal(frame.sandbox, 'allow-scripts', 'an opaque origin');
    frame.fire('load');
    assert.equal(doc.started.type, 'start');
    open.receive({ type: 'ready', instanceId: 'a.1', network: 'open' });
    assert.equal(open.status, 'failed', 'a sandbox that could connect never runs a worker');
    assert.ok(frame.removed);
    const host = make();
    doc.frames.at(-1).fire('load');
    host.receive({ type: 'ready', instanceId: 'a.1', network: 'blocked', storage: 'blocked' });
    let now = 1000;
    assert.ok(host.wants(now));
    host.send({ frameId: 1, epoch: 1 }, now);
    // The page's own load stalls it for seconds before the worker's first answer.
    for (const stall of [4000, 6000, 3000]) {
        now += stall;
        assert.equal(host.wants(now), false);
    }
    assert.equal(host.status, 'ready', 'a stall of the page never counts as the silence of the worker');
    const drawings = (ms, count) => {
        for (let i = 0; i < count; i++) {
            now += ms;
            host.wants(now);
        }
    };
    drawings(16, Math.ceil(SILENT_MS / 16) + 3);
    assert.equal(host.status, 'ready', `a worker has ${FIRST_SILENT_MS} ms of drawing for its first answer`);
    host.receive({ type: 'response', instanceId: 'a.1' });
    assert.equal(host.answered, 1);
    assert.ok(host.wants(now));
    host.send({ frameId: 2, epoch: 1 }, now);
    drawings(16, Math.floor(SILENT_MS / 16) - 2);
    assert.equal(host.status, 'ready');
    drawings(SILENT_STEP_MS * 10, 2);
    assert.equal(host.status, 'ready', 'a slow page waits a few drawings more');
    drawings(16, 3);
    assert.equal(host.status, 'restarting', 'a silent worker is restarted');
    assert.equal(RESTARTS, 1);
    host.restarts = RESTARTS;
    host.status = 'ready';
    host.fail('again');
    assert.equal(host.status, 'failed', 'a second failure leaves the team without its worker');
    host.dispose();
    assert.equal(host.status, 'disposed');
});

// Runs the sandbox's bootstrap with the given origin and parent, and returns what it listens to.
function bootSandbox({ origin, framed, href = 'http://127.0.0.1:8780/sandbox/presentation' }) {
    const source = readFileSync(new URL('../../src/cuju/render/web/js/presentation/sandbox.js', import.meta.url), 'utf8');
    const listeners = [];
    const workers = [];
    const parent = { postMessage() {} };
    const win = {};
    win.parent = framed ? parent : win;
    class FakeWorker {
        constructor(url) {
            this.url = url;
            this.sent = [];
            workers.push(this);
        }
        postMessage(m) {
            this.sent.push(m);
        }
    }
    const self = { origin };
    vm.runInNewContext(source, {
        self, window: win, location: { href }, URL, Blob, Worker: FakeWorker, JSON, String,
        addEventListener: (name, fn) => listeners.push([name, fn]),
    });
    const start = (source, origin) => {
        for (const [, fn] of listeners) {
            fn({ source, origin, data: { type: 'start', module: 'export function frame() {}', instanceId: 'a.1' }, ports: [{}] });
        }
    };
    return { listeners, workers, parent, win, start };
}

test('the sandbox starts a worker only in an opaque origin, framed, for the page above it', () => {
    const top = bootSandbox({ origin: 'http://127.0.0.1:8780', framed: false });
    assert.equal(top.listeners.length, 0, 'a window of the route on its own listens to nothing');
    assert.equal(bootSandbox({ origin: 'null', framed: false }).listeners.length, 0, 'unframed');
    assert.equal(bootSandbox({ origin: 'http://127.0.0.1:8780', framed: true }).listeners.length, 0, 'an origin');
    const box = bootSandbox({ origin: 'null', framed: true });
    assert.equal(box.listeners.length, 1);
    box.start({ postMessage() {} }, 'http://127.0.0.1:8780');
    assert.equal(box.workers.length, 0, 'another window is no sender');
    box.start(box.parent, 'https://evil.example');
    assert.equal(box.workers.length, 0, 'a parent of another site starts nothing');
    box.start(box.parent, 'http://127.0.0.1:8780');
    assert.equal(box.workers.length, 1, 'the page above it starts the worker');
    const [sent] = box.workers[0].sent;
    assert.equal(sent.type, 'port');
    assert.equal(sent.probe, 'http://127.0.0.1:8780/api/presentation-probe', 'the sandbox names the probe itself');
});

test('the host keeps a worker off unless both network and storage are blocked', () => {
    globalThis.location = { href: 'http://127.0.0.1:1/' };
    globalThis.addEventListener = () => {};
    globalThis.removeEventListener = () => {};
    const doc = new FakeDocument();
    const host = new ModuleHost({
        source: 'export function frame() { return {}; }', instanceId: 'a.1', hello: { instanceId: 'a.1' }, document: doc,
        onResponse: () => {}, onStatus: () => {},
    });
    doc.frames.at(-1).fire('load');
    host.receive({ type: 'ready', instanceId: 'a.1', network: 'blocked', storage: 'open' });
    assert.equal(host.status, 'failed', 'a sandbox that holds storage never runs a worker');
    const later = new ModuleHost({
        source: 'export function frame() { return {}; }', instanceId: 'a.1', hello: { instanceId: 'a.1' }, document: doc,
        onResponse: () => {}, onStatus: () => {},
    });
    doc.frames.at(-1).fire('load');
    later.receive({ type: 'ready', instanceId: 'a.1', network: 'blocked' });
    assert.equal(later.status, 'failed', 'a sandbox that does not say is not sealed');
});

// A bitmap of the size given, as the page receives one from the sandbox.
class FakeBitmap {
    constructor(width, height) {
        this.width = width;
        this.height = height;
        this.closed = false;
    }
    close() {
        this.closed = true;
    }
}

test('a reply of the sandbox holds plain data and bitmaps of its slots alone', () => {
    globalThis.ImageBitmap = FakeBitmap;
    const badge = () => ({ slot: 'badge', op: 'draw', bitmap: new FakeBitmap(96, 96) });
    assert.equal(replyProblem({ type: 'response', log: ['a'], resources: [{ positions: new Float32Array(9) }] }), null);
    assert.equal(replyProblem({ type: 'response', overlays: [badge(), { slot: 'card', op: 'hide' }, null] }), null);
    assert.equal(replyProblem({ overlays: [{ slot: 'badge', op: 'draw', bitmap: new FakeBitmap(4000, 96) }] }),
        'a bitmap of 4000 by 96 pixels for the slot badge');
    assert.equal(replyProblem({ overlays: [{ slot: '__proto__', op: 'draw', bitmap: new FakeBitmap(96, 96) }] }),
        'a bitmap of 96 by 96 pixels for the slot __proto__');
    assert.equal(replyProblem({ overlays: [{ slot: 'badge', bitmap: { width: 96, height: 96 } }] }), 'something else for the slot badge');
    assert.equal(replyProblem({ log: [], extra: { picture: new FakeBitmap(96, 96) } }), 'a bitmap outside its slot');
    assert.equal(replyProblem({ overlays: Array.from({ length: MAXIMUM_OVERLAYS + 1 }, badge) }), 'overlays beyond a list of 8');
    assert.equal(replyProblem({ log: new Map([[1, 'x'.repeat(10)]]) }), 'an object other than plain data');
    assert.equal(replyProblem({ data: new ArrayBuffer(1 << 20) }), 'an object other than plain data');
    let deep = {};
    for (let i = 0; i < 100; i++) deep = { deep };
    assert.equal(replyProblem(deep), 'more parts than a reply holds');
    // The host ends a worker that answers so, and frees the bitmaps it sent.
    globalThis.location = { href: 'http://127.0.0.1:1/' };
    globalThis.addEventListener = () => {};
    globalThis.removeEventListener = () => {};
    const doc = new FakeDocument();
    const statuses = [];
    const host = new ModuleHost({
        source: 'export function frame() { return {}; }', instanceId: 'a.1', hello: { instanceId: 'a.1' }, document: doc,
        onResponse: () => assert.fail('no reply reaches the page'), onStatus: (st, d) => statuses.push([st, d]),
    });
    doc.frames.at(-1).fire('load');
    host.receive({ type: 'ready', instanceId: 'a.1', network: 'blocked', storage: 'blocked' });
    host.send({ frameId: 1, epoch: 1 });
    const big = new FakeBitmap(96, 4000);
    host.receive({ type: 'response', instanceId: 'a.1', epoch: 1, sourceFrameId: 1, overlays: [{ slot: 'badge', op: 'draw', bitmap: big }] });
    assert.deepEqual(statuses.at(-1), ['restarting', 'the worker answered with a bitmap of 96 by 4000 pixels for the slot badge']);
    assert.ok(big.closed);
    host.dispose();
    delete globalThis.ImageBitmap;
});

test('the worker log keeps the newest lines across replies', () => {
    let log = appendLog(undefined, ['epoch 1, start']);
    log = appendLog(log, []);
    assert.deepEqual(log, ['epoch 1, start'], 'an empty reply keeps the log');
    log = appendLog(log, ['goal at 12.0 seconds']);
    assert.deepEqual(log, ['epoch 1, start', 'goal at 12.0 seconds']);
    for (let i = 0; i < LOG_LINES + 5; i++) {
        log = appendLog(log, [`line ${i}`]);
    }
    assert.equal(log.length, LOG_LINES);
    assert.equal(log[log.length - 1], `line ${LOG_LINES + 4}`, 'the newest line comes last');
    const checked = checkResponse({ type: 'response', instanceId: 'a', epoch: 1, log: ['one', 'two'] }, { instanceId: 'a', epoch: 1, own: new Set(), files: [] });
    assert.deepEqual(appendLog(log, checked.response.log).slice(-2), ['one', 'two']);
});
