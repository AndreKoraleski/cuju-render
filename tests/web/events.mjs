// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of the event catalog of the team presentation contract, its frame and inferred events,
// the contact moment, forecasts, cancels and the resync after a seek, on the two shipped samples,
// run from the repository root with `node tests/web/events.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules
// load from a copy of the whole folder beside a package file that names them modules, and every
// import among them resolves as it does on the page.
const folder = mkdtempSync(join(tmpdir(), 'cuju-events-'));
const inner = join(folder, 'presentation');
cpSync(fileURLToPath(new URL('../../src/cuju/render/web/js', import.meta.url)), folder, {
    recursive: true,
});
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const C = await import(pathToFileURL(join(inner, 'catalog.js')).href);
const { ACTION, parseRecording } = await import(pathToFileURL(join(folder, 'recording/format.js')).href);
const { FrameStore } = await import(pathToFileURL(join(folder, 'recording/timeline.js')).href);

const SAMPLES = ['sample-11v11.cjr', 'sample-5v5.cjr'];
const parsed = {};
for (const name of SAMPLES) {
    const bytes = readFileSync(new URL(`../../src/cuju/render/samples/${name}`, import.meta.url));
    parsed[name] = await parseRecording(bytes);
}
const storeOf = (name, frames = null) => new FrameStore(parsed[name].header, frames || parsed[name].frames);
const ELEVEN = storeOf('sample-11v11.cjr');
const FIVE = storeOf('sample-5v5.cjr');
const SPS = 10;
const FRAME = 1 / 60;
const EPS = 1e-9;

function allEvents(store) {
    const out = [];
    for (let i = store.first; i <= store.last; i++) {
        out.push(...C.stepEvents(store, i));
    }
    return out;
}

// Plays the store forward at a speed from timeline index from to index to, sixty drawings a
// second, and returns every event with the drawn index it came with.
function play(catalog, from, to, speed = 1, extra = {}) {
    const out = [];
    const step = speed * SPS * FRAME;
    for (let t = from; t <= to + EPS; t += step) {
        for (const ev of catalog.update({ t, playing: true, direction: 1, speed, dt: FRAME, ...extra })) {
            out.push({ ev, at: t });
        }
    }
    return out;
}

test('the touches match the counts the contract measured', () => {
    for (const [store, total] of [[ELEVEN, 454], [FIVE, 245]]) {
        let touches = 0;
        for (let i = store.first; i <= store.last; i++) {
            touches += C.frameEvents(store, i).filter((ev) => ev.kind === 'touch').length;
        }
        assert.equal(touches, total);
    }
    const kinds = {};
    const steps = new Map();
    for (let i = ELEVEN.first; i <= ELEVEN.last; i++) {
        for (const ev of C.frameEvents(ELEVEN, i)) {
            if (ev.kind === 'touch') {
                kinds[ev.data.kind] = (kinds[ev.data.kind] || 0) + 1;
                steps.set(i, (steps.get(i) || 0) + 1);
            }
        }
    }
    assert.deepEqual(kinds, { kick: 351, intended: 79, accidental: 24 });
    assert.equal(steps.size, 438, 'touch steps');
    assert.equal([...steps.values()].filter((c) => c > 1).length, 16, 'steps touched by more than one player');
});

test('every event has the contract shape and a stable id', () => {
    const events = allEvents(ELEVEN);
    const occurs = new Set();
    for (const ev of events) {
        assert.ok(['occur', 'resolve'].includes(ev.phase));
        assert.ok(['frame', 'inferred'].includes(ev.provenance), ev.kind);
        assert.equal(typeof ev.id, 'string');
        assert.ok(Number.isInteger(ev.step) && Number.isFinite(ev.t) && ev.lead === 0);
        assert.equal(ev.revision, ev.phase === 'resolve' ? 1 : 0);
        if (ev.provenance === 'inferred') {
            assert.match(ev.inference, /^[a-zA-Z]+\/\d+$/);
            assert.equal(Number(ev.inference.split('/')[1]), C.RULES[ev.inference.split('/')[0]]);
        }
        if (ev.phase === 'occur') {
            assert.ok(!occurs.has(ev.id), `duplicate id ${ev.id}`);
            occurs.add(ev.id);
        } else {
            assert.ok(occurs.has(ev.id), `a resolve refines an event sent before it, ${ev.id}`);
        }
    }
    // A fresh store of the same frames, which gets an analysis of its own, names the same ids.
    const again = allEvents(storeOf('sample-11v11.cjr'));
    assert.deepEqual(again.map((ev) => ev.id), events.map((ev) => ev.id));
});

test('the ids are the same in two catalogs, across epochs and a replay', () => {
    const a = play(new C.Catalog(ELEVEN), 0, 600).map((x) => `${x.ev.phase}:${x.ev.id}`);
    const b = play(new C.Catalog(ELEVEN), 0, 600).map((x) => `${x.ev.phase}:${x.ev.id}`);
    assert.deepEqual(a, b);
    // Playing the same stretch again after a reset sends the same ids again in the new epoch.
    const catalog = new C.Catalog(ELEVEN);
    const first = play(catalog, 300, 450).filter((x) => x.ev.phase === 'occur').map((x) => x.ev.id);
    catalog.reset('replay');
    const second = play(catalog, 300, 450).filter((x) => x.ev.phase === 'occur').map((x) => x.ev.id);
    assert.deepEqual(second, first);
    assert.ok(first.length > 20);
});

test('the contact moment lies inside the touch interval', () => {
    let intersections = 0;
    for (const store of [ELEVEN, FIVE]) {
        for (let i = store.first; i <= store.last; i++) {
            for (const ev of C.frameEvents(store, i)) {
                if (ev.kind !== 'touch') {
                    continue;
                }
                const c = C.contactEstimate(store, i);
                assert.ok(c.t >= (i - 1) / SPS - EPS && c.t <= i / SPS + EPS, `touch at ${i}, contact ${c.t}`);
                assert.ok(c.fraction >= 0 && c.fraction < 1);
                assert.ok(Math.abs(c.step + c.fraction - c.t * SPS) < 1e-9);
                assert.equal(ev.t, c.t);
                assert.equal(ev.data.contactT, c.t);
                assert.deepEqual(ev.data.contactPoint, c.point);
                // The point lies near the straight drawn segment of the interval, off it by as
                // much as the drawn path cuts the corner of the true one.
                const a = store.get(i - 1).data;
                const b = store.get(i).data;
                const ux = b[8] - a[8];
                const uy = b[9] - a[9];
                const w = Math.min(1, Math.max(0, ((c.point[0] - a[8]) * ux + (c.point[1] - a[9]) * uy) / Math.max(1e-9, ux * ux + uy * uy)));
                const d = Math.hypot(c.point[0] - a[8] - w * ux, c.point[1] - a[9] - w * uy);
                assert.ok(d < 1, `contact point at ${i} lies ${d} meters off the drawn segment`);
                intersections += c.method === 'intersection' ? 1 : 0;
            }
        }
    }
    assert.equal(intersections, 454 + 245, 'every sample touch has both segments');
    // A touch on the first frame after a cut falls back to its own sample.
    const short = storeOf('sample-11v11.cjr', parsed['sample-11v11.cjr'].frames.slice(0, 3));
    assert.equal(C.contactEstimate(short, 0).method, 'sample');
});

test('the action lags are the medians measured on the samples', () => {
    const lags = {};
    for (const store of [ELEVEN, FIVE]) {
        for (let i = store.first + 1; i <= store.last; i++) {
            const f = store.get(i);
            for (let k = 0; k < f.touches.length; k++) {
                if (!f.touches[k]) {
                    continue;
                }
                const action = f.actions[k];
                let b = i;
                while (b > store.first && store.get(b - 1).actions[k] === action) {
                    b--;
                }
                (lags[C.ACTION_NAMES[action]] ||= []).push(i - b);
            }
        }
    }
    for (const [name, lag] of Object.entries(C.ACTION_LAGS)) {
        const list = lags[name].sort((x, y) => x - y);
        const m = list.length;
        const median = m % 2 ? list[(m - 1) / 2] : (list[m / 2 - 1] + list[m / 2]) / 2;
        assert.equal(lag, median, name);
    }
});

test('a forecast precedes its occur with the right lead', () => {
    const seen = play(new C.Catalog(ELEVEN), 0, ELEVEN.last);
    const forecasts = new Map();
    const occurs = new Map();
    for (const { ev, at } of seen) {
        assert.ok(Math.abs(ev.lead - (ev.t - at / SPS)) < 1e-9, 'lead is t minus the drawn time');
        if (ev.phase === 'forecast') {
            assert.ok(!forecasts.has(ev.id), 'a forecast is sent once per epoch');
            forecasts.set(ev.id, { ev, at });
        } else if (ev.phase === 'occur') {
            assert.ok(!occurs.has(ev.id), 'an occur is sent once per epoch');
            occurs.set(ev.id, { ev, at });
        }
        assert.notEqual(ev.phase, 'cancel', 'steady play cancels nothing');
    }
    let touches = 0;
    let early = 0;
    for (const [id, { ev, at }] of occurs) {
        early += ev.kind === 'touch' && ev.t <= C.CONTACT_HORIZON + 0.1 ? 1 : 0;
        assert.ok(ev.lead <= 0 && ev.lead > -FRAME - EPS, `occur lead ${ev.lead}`);
        assert.ok(ev.t <= at / SPS + EPS);
        const forecast = forecasts.get(id);
        if (C.CONTACT_KINDS.includes(ev.kind) && ev.t > C.CONTACT_HORIZON + 0.1) {
            assert.ok(forecast, `${ev.kind} at ${ev.step} was forecast`);
            assert.ok(forecast.at < at);
            assert.ok(forecast.ev.lead <= C.CONTACT_HORIZON + EPS && forecast.ev.lead > C.CONTACT_HORIZON - FRAME - EPS, `lead ${forecast.ev.lead}`);
            assert.equal(forecast.ev.t, ev.t);
            touches += ev.kind === 'touch' ? 1 : 0;
        } else if (!C.CONTACT_KINDS.includes(ev.kind) && !C.OUTCOME_KINDS.includes(ev.kind)) {
            assert.ok(!forecast, `${ev.kind} is not forecast`);
        }
    }
    assert.equal(touches + early, 454);
    assert.ok(early < 10);
    for (const id of forecasts.keys()) {
        assert.ok(occurs.has(id), `every forecast occurs in steady play, ${id}`);
    }
});

test('outcomes are not forecast earlier than half a second unless full look ahead is on', () => {
    for (const fullLookahead of [false, true]) {
        const seen = play(new C.Catalog(ELEVEN, { fullLookahead }), 0, ELEVEN.last);
        const goals = seen.filter((x) => x.ev.kind === 'goal' && x.ev.phase === 'forecast');
        assert.equal(goals.length, 2);
        for (const { ev } of goals) {
            if (fullLookahead) {
                assert.ok(ev.lead > C.CONTACT_HORIZON - FRAME - EPS);
            } else {
                assert.ok(ev.lead <= C.OUTCOME_HORIZON + EPS && ev.lead > C.OUTCOME_HORIZON - FRAME - EPS, `goal lead ${ev.lead}`);
            }
        }
        const reach = fullLookahead ? C.CONTACT_HORIZON : C.OUTCOME_HORIZON;
        for (const { ev, at } of seen) {
            if (ev.phase === 'resolve') {
                assert.ok(ev.data.resolvedT - at / SPS <= reach + EPS, `${ev.kind} resolve before its horizon`);
            }
            if (ev.phase === 'forecast' && C.OUTCOME_KINDS.includes(ev.kind)) {
                assert.ok(ev.lead <= reach + EPS);
            }
        }
        const scorer = seen.find((x) => x.ev.kind === 'goal' && x.ev.phase === 'resolve');
        assert.ok(scorer && scorer.ev.data.scorer >= 0 && scorer.ev.revision === 1);
    }
});

test('reverse and fast play cancel the pending forecasts and send nothing more', () => {
    const goal = ELEVEN.goals[0].index;
    for (const turn of [{ direction: -1, speed: 1 }, { direction: 1, speed: 4 }]) {
        const catalog = new C.Catalog(ELEVEN);
        const seen = play(catalog, goal - 40, goal - 15);
        const pending = new Set();
        for (const { ev } of seen) {
            if (ev.phase === 'forecast') {
                pending.add(ev.id);
            } else if (ev.phase === 'occur') {
                pending.delete(ev.id);
            }
        }
        assert.ok(pending.size > 0);
        const cancels = catalog.update({ t: goal - 15.1, direction: turn.direction, speed: turn.speed, dt: FRAME });
        assert.ok(cancels.every((ev) => ev.phase === 'cancel'));
        assert.deepEqual(new Set(cancels.map((ev) => ev.id)), pending);
        for (let t = goal - 15.2; t > goal - 30; t -= 0.2) {
            assert.deepEqual(catalog.update({ t: turn.direction < 0 ? t : 2 * goal - t, direction: turn.direction, speed: turn.speed, dt: FRAME }), []);
        }
        // Forward play returns in a new epoch, which forecasts again.
        const back = catalog.update({ t: goal - 30, direction: 1, speed: 1, dt: FRAME });
        assert.ok(back.some((ev) => ev.phase === 'forecast'));
        assert.ok(back.every((ev) => ev.phase === 'forecast' || ev.phase === 'resolve'));
    }
});

test('a reset cancels and the window after a seek holds the events in flight', () => {
    const goal = ELEVEN.goals[0].index;
    const catalog = new C.Catalog(ELEVEN);
    play(catalog, goal - 50, goal - 20);
    const cancels = catalog.reset('seek');
    assert.ok(cancels.length > 0 && cancels.every((ev) => ev.phase === 'cancel' && ev.lead > 0));
    assert.deepEqual(catalog.reset('seek'), []);
    // Just after the goal, the window holds the shot, its touch and the goal, all in the past.
    const t = goal + 5;
    const window = catalog.window(t);
    assert.ok(window.every((ev) => ev.lead <= 0 && ev.lead >= -3 - EPS));
    const kinds = new Set(window.map((ev) => ev.kind));
    for (const kind of ['touch', 'shot', 'goal', 'restart.taken']) {
        assert.ok(kinds.has(kind), kind);
    }
    assert.ok(window.some((ev) => ev.kind === 'goal' && ev.phase === 'resolve'));
    // A jump in an update is a seek too, which resyncs with the same window.
    const jumping = new C.Catalog(ELEVEN);
    play(jumping, goal - 50, goal - 20);
    const resync = jumping.update({ t, dt: FRAME });
    const occurs = resync.filter((ev) => ev.phase === 'occur' || ev.phase === 'resolve');
    assert.deepEqual(occurs.map((ev) => ev.id), window.map((ev) => ev.id));
    assert.ok(resync.some((ev) => ev.phase === 'cancel'));
    assert.equal(jumping.epoch, 1);
    // Playing on from there neither repeats the window nor misses what comes next.
    const later = play(jumping, t + 1 / 6, t + 60);
    assert.ok(!later.some((x) => x.ev.phase === 'occur' && x.ev.t <= t / SPS));
    assert.ok(later.some((x) => x.ev.phase === 'occur' && x.ev.kind === 'touch'));
});

test('action.begin expects its contact, certain when the frames reach it', () => {
    let certain = 0;
    let begin = null;
    for (let i = ELEVEN.first; i <= ELEVEN.last; i++) {
        for (const ev of C.frameEvents(ELEVEN, i)) {
            if (ev.kind !== 'action.begin' || !ev.data.expectedContact) {
                continue;
            }
            const e = ev.data.expectedContact;
            assert.ok(e.certain);
            const touch = C.frameEvents(ELEVEN, e.step).find((x) => x.kind === 'touch' && x.player === ev.player);
            assert.equal(touch.t, e.t);
            certain++;
            if (!begin && ev.data.action === 'shortPass' && e.step > i) {
                begin = ev;
            }
        }
    }
    assert.ok(certain > 300);
    // With the frames cut just after the start of the action, the median lag stands in.
    const frames = parsed['sample-11v11.cjr'].frames.slice(0, begin.step + 1);
    const short = storeOf('sample-11v11.cjr', frames);
    const cut = C.frameEvents(short, begin.step).find((ev) => ev.id === begin.id);
    assert.deepEqual(cut.data.expectedContact, { t: (begin.step + 3) / SPS, step: begin.step + 3, certain: false });
    // A live store that grows settles the estimate into the certain contact.
    const live = new FrameStore(parsed['sample-11v11.cjr'].header, frames.slice(), 18000);
    assert.equal(C.frameEvents(live, begin.step).find((ev) => ev.id === begin.id).data.expectedContact.certain, false);
    for (const f of parsed['sample-11v11.cjr'].frames.slice(begin.step + 1, begin.step + 40)) {
        live.push(f);
    }
    assert.deepEqual(C.frameEvents(live, begin.step).find((ev) => ev.id === begin.id).data.expectedContact, begin.data.expectedContact);
});

test('a live catalog forecasts only as far as the buffer allows', () => {
    const catalog = new C.Catalog(ELEVEN, { live: true });
    const seen = play(catalog, 100, 1100, 1, { ahead: 1.0 });
    const forecasts = seen.filter((x) => x.ev.phase === 'forecast');
    assert.ok(forecasts.length > 50);
    assert.ok(forecasts.every((x) => x.ev.lead <= 0.8 + EPS));
    assert.ok(forecasts.some((x) => x.ev.lead > 0.8 - FRAME - EPS));
});

test('the frame events of the samples', () => {
    const count = (events, kind) => events.filter((ev) => ev.kind === kind && ev.phase === 'occur').length;
    const eleven = allEvents(ELEVEN);
    const five = allEvents(FIVE);
    for (const events of [eleven, five]) {
        const full = events.filter((ev) => ev.kind === 'fulltime');
        assert.equal(full.length, 1);
        assert.deepEqual(full[0].data, { winner: null, draw: true, score: [1, 1] });
        assert.equal(count(events, 'episode.begin'), 1);
        assert.equal(count(events, 'episode.end'), 1);
        assert.equal(count(events, 'goal'), 2);
        assert.equal(count(events, 'action.begin'), count(events, 'action.end'));
    }
    assert.equal(count(eleven, 'restart.begin'), 7);
    assert.equal(count(eleven, 'restart.taken'), 7);
    assert.equal(count(five, 'restart.begin'), 2);
    assert.deepEqual(eleven.filter((ev) => ev.kind === 'halftime').map((ev) => ev.step), [1500]);
    assert.equal(count(five, 'halftime'), 0);
    const penalty = eleven.find((ev) => ev.kind === 'restart.begin' && ev.data.restart === 'penalty');
    assert.equal(penalty.step, 416);
    const taken = eleven.find((ev) => ev.kind === 'restart.taken' && ev.step === 422);
    assert.equal(taken.data.taker, penalty.data.taker);
    assert.ok(taken.t < 42.2 && taken.t >= 42.1, 'restart.taken takes the moment of the taker\'s touch');
    assert.deepEqual(eleven.filter((ev) => ev.kind === 'foul').map((ev) => [ev.step, ev.data.offender, ev.data.victim, ev.data.type]),
        [[416, 14, 9, 'foul'], [2906, 13, 5, 'foul']]);
    assert.deepEqual(eleven.filter((ev) => ev.kind === 'offside').map((ev) => [ev.step, ev.player]), [[2532, 2]]);
    const shot = eleven.find((ev) => ev.kind === 'shot' && ev.phase === 'resolve' && ev.data.outcome === 'goal');
    assert.ok(shot && shot.data.onTarget === true);
    const save = eleven.find((ev) => ev.kind === 'save' && ev.phase === 'resolve');
    assert.ok(save && save.data.saved === true && ['catch', 'parry'].includes(save.data.style));
    for (const ev of eleven.filter((x) => x.kind === 'pass' && x.phase === 'resolve')) {
        assert.ok(['complete', 'intercepted', 'out', 'stopped'].includes(ev.data.outcome));
        assert.ok(ev.data.resolvedStep > ev.step && ev.data.resolvedStep - ev.step <= 100);
    }
    const begins = eleven.filter((ev) => ev.kind === 'sprint.begin').length;
    assert.ok(begins > 0 && Math.abs(begins - eleven.filter((ev) => ev.kind === 'sprint.end').length) <= 22);
});

test('a whole recording scans quickly and then comes from the cache', () => {
    const store = storeOf('sample-11v11.cjr');
    const start = performance.now();
    allEvents(store);
    const cold = performance.now() - start;
    const again = performance.now();
    allEvents(store);
    const warm = performance.now() - again;
    assert.ok(cold < 15000, `cold scan ${cold} ms`);
    assert.ok(warm < 500, `warm scan ${warm} ms`);
    // Header kinds read the ACTION table of the format, which the names follow.
    assert.equal(C.ACTION_NAMES[ACTION.shot], 'shot');
});
