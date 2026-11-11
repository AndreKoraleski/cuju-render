// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of contract 1.1 of team presentation, the bend of the ball, the reach, the checks of
// worker geometry and of shaders, the behaviours that drive attachments and lights, the sound
// rules of the team buses and the commands of reflexes, run from the repository root with
// `node tests/web/effects.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const folder = mkdtempSync(join(tmpdir(), 'cuju-effects-'));
const inner = join(folder, 'presentation');
mkdirSync(inner);
const names = ['values', 'reach', 'glsl', 'behaviors', 'commands', 'contract', 'budget', 'loudness', 'teamaudio', 'protocol', 'tracks'];
for (const name of names) {
    cpSync(fileURLToPath(new URL(`../../src/cuju/render/web/js/presentation/${name}.js`, import.meta.url)), join(inner, `${name}.js`));
}
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const load = (name) => import(pathToFileURL(join(inner, `${name}.js`)).href);
const R = await load('reach');
const G = await load('glsl');
const { BehaviourSet, checkBehaviour } = await load('behaviors');
const K = await load('commands');
const C = await load('contract');
const { Budget, TABLE } = await load('budget');
const A = await load('teamaudio');
const { helloMessage } = await load('protocol');

const close = (a, b, eps = 1e-9) => a.every((x, i) => Math.abs(x - b[i]) < eps);

test('the bend of the ball passes the contact point at the contact time', () => {
    const pb = [0, 0, 0.11];
    const pc = [1, 0.4, 0.11];
    const point = [0.2, 0.3, 0.11];
    assert.ok(close(R.bendBall(pb, pc, point, 0.3, 0), pb), 'it starts on the first sample');
    assert.ok(close(R.bendBall(pb, pc, point, 0.3, 0.3), point), 'it meets the contact at its time');
    assert.ok(close(R.bendBall(pb, pc, point, 0.3, 1), pc), 'it ends on the next sample');
    const mid = R.bendBall(pb, pc, point, 0.3, 0.15);
    assert.ok(close(mid, [0.1, 0.15, 0.11]), 'it goes straight to the contact');
    assert.ok(close(R.bendBall(pb, pc, point, 0, 0.5), [0.5, 0.2, 0.11]), 'a contact on a sample draws the straight line');
});

test('FABRIK keeps the bone lengths and reaches a target in range', () => {
    const joints = [[0, 1, 0], [0, 0.5, 0], [0, 0, 0]];
    const target = [0.4, 0.3, 0.2];
    const out = R.fabrik(joints, target, 16);
    const len = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
    assert.ok(Math.abs(len(out[0], out[1]) - 0.5) < 1e-6 && Math.abs(len(out[1], out[2]) - 0.5) < 1e-6);
    assert.ok(close(out[0], joints[0]), 'the root stays');
    assert.ok(len(out[2], target) < 1e-3, 'the tip reaches the target');
    const far = R.fabrik(joints, [0, 1, 5]);
    assert.ok(Math.abs(far[2][2] - 1) < 1e-9 && Math.abs(far[2][1] - 1) < 1e-9, 'a target out of reach stretches the chain toward it');
    assert.equal(R.reachWeight(10, 10, 0.15), 1);
    assert.equal(R.reachWeight(10.2, 10, 0.15), 0);
    assert.ok(R.reachWeight(10.075, 10, 0.15) > 0.4 && R.reachWeight(10.075, 10, 0.15) < 0.6);
});

test('worker geometry is checked and counted', () => {
    const g = R.checkGeometry({ id: 'shard', positions: [0, 0, 0, 1, 0, 0, 0, 1, 0], indices: [0, 1, 2], colors: [1, 0, 0, 1, 0, 1, 0, 1, 0, 0, 1, 1] });
    assert.equal(g.count, 3);
    assert.equal(g.triangles, 1);
    assert.equal(g.colorSize, 4);
    assert.ok(g.bytes > 0 && g.positions instanceof Float32Array && g.indices instanceof Uint16Array);
    for (const bad of [
        { id: 'a', positions: [0, 0] },
        { id: 'a', positions: [0, 0, Infinity] },
        { id: 'a', positions: [0, 0, 500] },
        { id: 'a', positions: [0, 0, 0, 1, 0, 0, 0, 1, 0], indices: [0, 1, 3] },
        { id: 'a', positions: [0, 0, 0], normals: [0, 1] },
        { id: 'bad id!', positions: [0, 0, 0] },
        { id: 'a', positions: new Float32Array(3 * (R.MAX_VERTICES + 1)) },
    ]) {
        assert.throws(() => R.checkGeometry(bad));
    }
});

test('the page checks shaders before it compiles them', () => {
    assert.deepEqual(G.checkShader('vec4 cujuColor(vec4 c, vec2 uv) { return c * uPulse; }'), []);
    assert.ok(G.checkShader('uniform float x; vec4 cujuColor(vec4 c, vec2 uv) { return c; }').length);
    assert.ok(G.checkShader('#version 300 es\nvec4 cujuColor(vec4 c, vec2 uv) { return c; }').length);
    assert.ok(G.checkShader('vec4 cujuColor(vec4 c, vec2 uv) { while (true) {} return c; }').length);
    assert.ok(G.checkShader('#include <common>\nvec4 cujuColor(vec4 c, vec2 uv) { return c; }').length);
    assert.ok(G.checkShader('float helper() { return 1.0; }').length, 'a chunks shader defines a hook');
    assert.deepEqual(G.checkShader('#pragma cuju vertex\nvoid main() { gl_Position = vec4(position, 1.0); }\n#pragma cuju fragment\nvoid main() { gl_FragColor = vec4(1.0); }', 'material'), []);
    assert.ok(G.checkShader('void main() {}', 'material').length);
    const blink = readFileSync(new URL('../support/team/cuju-team/presentation/shaders/blink.glsl', import.meta.url), 'utf8');
    assert.deepEqual(G.checkShader(blink, 'chunks'), [], 'the test package’s blink passes');
});

// The shaders of the cost rules, the same as the Python tests of _glsl.py read.
const hook = (body) => `vec4 cujuColor(vec4 c, vec2 uv) {\n${body}\n    return c;\n}\n`;
const loop = (n, body, name = 'i') => `for (int ${name} = 0; ${name} < ${n}; ${name}++) { ${body} }`;
const COSTLY = {
    three: hook(loop(256, loop(256, loop(256, 'c.r += 0.0001;', 'k'), 'j'))),
    helper: `float h(float x) { ${loop(256, 'x += 0.1;')} return x; }\n${hook(loop(256, 'c.r += h(c.g);'))}`,
    tree: Array.from({ length: 20 }, (_, n) => `float f${n}(float x) { return f${n + 1}(x) + f${n + 1}(x) + f${n + 1}(x); }\n`).join('')
        + `float f20(float x) { return x; }\n${hook('c.r += f0(c.g);')}`,
    macros: '#define A x+x+x+x+x+x+x+x\n#define B A A A A A A A A\n#define C B B B B B B B B\n#define D C C C C C C C C\n'
        + `#define E D D D D D D D D\n#define F E E E E E E E E\n${hook('float x = 1.0; c.r += F;')}`,
    poisoned: hook(Array.from({ length: 140 }, (_, n) => `for (int i${n} = 0; i${n} < 256; i${n}++) {`).join('')
        + loop(0, 'c.r += 1.0;', 'z') + '}'.repeat(140)),
    material: `#pragma cuju vertex\nvoid main() { ${loop(64, loop(64, 'gl_Position += vec4(0.0);', 'j'))} }\n`
        + '#pragma cuju fragment\nvoid main() { gl_FragColor = vec4(1.0); }\n',
};

test('the page counts the cost of a shader through nested loops, helpers and macros', () => {
    const has = (problems, words) => problems.some((p) => p.includes(words));
    assert.ok(has(G.checkShader(COSTLY.three), 'run their body 16777216 times, at most 1024'));
    assert.ok(has(G.checkShader(COSTLY.helper), 'run their body 65536 times'), 'through a helper call');
    assert.ok(has(G.checkShader(COSTLY.tree), 'words of code in the hooks, at most 65536'), 'a tree of helper calls');
    assert.ok(has(G.checkShader(COSTLY.macros), 'once its macros expand, at most 262144'), 'macros of macros');
    assert.ok(has(G.checkShader(COSTLY.poisoned), 'at most 1024'), 'a loop of no trips inside never hides the count');
    assert.ok(has(G.checkShader(COSTLY.material, 'material'), 'in the vertex section that run their body 4096 times'));
    assert.ok(has(G.checkShader(hook(loop(300, 'c.r += 0.1;'))), 'runs a loop 300 times, at most 256'));
    assert.deepEqual(G.checkShader(hook(loop(32, loop(32, 'c.r += 0.001 * float(i * j);', 'j')))), [], '32 by 32 passes');
    // A large file of many loops is counted at once, in one pass over its loops.
    const many = hook(Array.from({ length: 4000 }, (_, n) => loop(2, 'c.r += 0.0;', `i${n}`)).join('\n'));
    const start = Date.now();
    G.checkShader(many);
    assert.ok(Date.now() - start < 2000, 'four thousand loops check within two seconds');
    const deep = hook(Array.from({ length: 20000 }, (_, n) => `for (int i${n} = 0; i${n} < 2; i${n}++) `).join('') + ';');
    assert.ok(G.checkShader(deep).length, 'nesting past the stack names a problem');
});

test('behaviours drive attachments and lights', () => {
    const set = new BehaviourSet({ entity: 7 });
    set.set(checkBehaviour({ id: 'bob', type: 'oscillate', attachment: 'halo', channel: 'y', amp: 0.1, freq: 1 }));
    set.set(checkBehaviour({ id: 'turn', type: 'spin', attachment: 'halo', rate: 2 }));
    set.set(checkBehaviour({ id: 'beat', type: 'lightParam', light: 'core', value: { input: 'speed', keys: [[0, 1], [10, 5]] } }));
    set.set(checkBehaviour({ id: 'wake', type: 'materialParam', attachment: 'halo', uniform: 'wake', value: 0.5 }));
    let out = null;
    for (let i = 0; i < 40; i++) {
        out = set.evaluate({ dt: 0.016, inputs: { speed: 5 } });
    }
    const halo = out.attachments.get('halo');
    assert.ok(halo && Math.abs(halo.y) <= 0.1 && halo.spins.length === 1);
    assert.equal(out.lights.length, 1);
    assert.equal(out.lights[0].light, 'core');
    assert.ok(Math.abs(out.lights[0].value - 3) < 1e-9);
    assert.equal(out.materials[0].attachment, 'halo');
    assert.throws(() => checkBehaviour({ type: 'lightParam' }), 'a light parameter names its light');
    assert.throws(() => checkBehaviour({ type: 'spin' }), 'a spin names what it turns');
});

test('contract 1.1 lists every feature and adds budgets', () => {
    for (const f of ['bend.ball', 'ik.fabrik', 'shader.custom', 'shader.sceneColor', 'post.layer', 'post.fullscreen', 'geometry.worker',
        'overlay.offscreen', 'audio.worklet', 'audio.music', 'camera.suggest', 'time.suggest', 'environment.sky', 'environment.lightning', 'fans.tifo', 'drivers.grf+layers']) {
        assert.ok(f in C.FEATURES, f);
    }
    assert.equal(C.FEATURES['geometry.worker'], 'worker');
    assert.equal(C.CONTRACT, '1.1');
    const m = C.normalize(JSON.parse(readFileSync(new URL('../support/team/cuju-team/presentation/presentation.json', import.meta.url), 'utf8')));
    assert.deepEqual(C.level(m), { level: 'worker', missing: [], lacking: ['audio.spatial'] });
    assert.ok(m.lights.core && m.post.layer && m.overlays.badge && m.rig.ik.kick && m.rig.layers.length === 1);
    assert.equal(C.driverOf(m, { goalkeeper: true }), 'grf+layers');
    for (const q of ['high', 'medium', 'low']) {
        for (const k of ['geometryBytes', 'decals', 'effects', 'localLights']) {
            assert.ok(TABLE[q][k] > 0, `${q} ${k}`);
        }
    }
    assert.equal(TABLE.high.fullscreen, 1);
    assert.equal(TABLE.medium.fullscreen, 0);
    const b = new Budget('low');
    assert.ok(b.take({ geometryBytes: 1024 }));
    assert.ok(!b.take({ geometryBytes: 64 * 1024 * 1024 }));
    const worker = new Budget('high');
    worker.stopWorker('silent');
    assert.ok(worker.past('noWorker') && !worker.past('standardMaterials') && !worker.past('noPasses'),
        'a failed worker leaves the shaders, passes and lights of the package');
    assert.equal(worker.level, 'noWorker');
    const h = helloMessage({ features: [], instanceId: 'a', team: 0, attack: 1, roster: [], header: {}, seedBase: 1, slots: ['badge'] });
    assert.deepEqual(h.slots, ['badge']);
});

test('reflexes start time, music and environment commands of their own events', () => {
    const own = new Set(['p0']);
    const event = { id: 'goal:10:x', kind: 'goal', team: 0, t: 1, data: {} };
    const actions = K.reflexActions({ do: [
        { time: { freeze: 0.9, slow: { speed: 0.1, seconds: 9 } } },
        { music: 'anthem', stems: [0, 2], fade: 2 },
        { music: 'anthem', stop: true },
        { environment: { sky: { tint: [255, 0, 0] } } },
    ] }, event, own);
    const time = actions.find((a) => a.kind === 'time').command;
    assert.equal(time.freeze, 0.3, 'a freeze lasts at most 0.3 seconds');
    assert.deepEqual(time.slow, { speed: 0.25, seconds: 1.5 }, 'slow motion holds to a quarter for 1.5 seconds');
    const music = actions.filter((a) => a.kind === 'audio').map((a) => a.command);
    assert.equal(music[0].op, 'music');
    assert.deepEqual(music[0].stems, [0, 2]);
    assert.equal(music[1].op, 'stop');
    assert.ok(actions.some((a) => a.kind === 'environment'));
    assert.equal(K.SAFETY.version, 2);
    assert.equal(K.SAFETY.loudness.teamShortTerm, K.SAFETY.loudness.integrated + K.SAFETY.loudness.shortTermAboveTarget);
    assert.ok(K.checkOverlay({ slot: 'badge', op: 'draw' }));
    const gain = K.checkAudio({ op: 'play', cue: 'x', gain: 7 }, own);
    assert.equal(gain.gain, 1, 'a package only lowers its sounds');
});

test('team sound only lowers, and its clippers hold their levels', () => {
    const curve = A.clipCurve(0.5, 101);
    assert.equal(curve[0], -0.5);
    assert.equal(curve[100], 0.5);
    assert.ok(Math.abs(curve[60] - 0.2) < 1e-6, 'a quiet signal passes unchanged');
    // A loud cue is brought under every ceiling, a quiet one up to a team sound's level at most.
    const loud = A.cueScale({ maxShortTerm: -8, maxMomentary: -6, truePeak: -1 }, 0.9);
    assert.ok(loud <= 10 ** ((-18 + 8) / 20) + 1e-9 && loud <= A.CUE_PEAK / 0.9 + 1e-9);
    const quiet = A.cueScale({ maxShortTerm: -40, maxMomentary: -38, truePeak: -30 }, 0.03);
    assert.ok(quiet * 0.03 <= A.CUE_PEAK + 1e-9);
    assert.equal(A.cueScale({ maxShortTerm: -Infinity, maxMomentary: -Infinity, truePeak: -Infinity }, 0), 0, 'silence stays silent');
});
