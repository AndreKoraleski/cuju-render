// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The worker of the test package, a single file module without imports. It runs in the
// renderer's sandbox, gets the Hello once and a Frame at a time, and answers each Frame with
// commands. It sets one behaviour again after every reset, sends its players' current bounds,
// claims the ball on its own touches, builds a small geometry once, draws its badge in its overlay
// slot and logs what it saw.

let hello = null;
let frames = 0;
let events = 0;

export function init(h) {
    hello = h;
    frames = 0;
    events = 0;
}

export function frame(f) {
    frames += 1;
    events += f.events.length;
    const out = { behaviours: [], bounds: [], claims: [], log: [], resources: [], overlays: [] };
    if (frames === 1) {
        // A flat triangle over the halo of every player, a geometry of the worker's own.
        out.resources.push({
            op: 'geometry', id: 'shard', attach: 'socket:halo',
            positions: [-0.1, 0.3, 0, 0.1, 0.3, 0, 0, 0.5, 0], indices: [0, 1, 2],
            material: { color: [255, 210, 120], emissive: [120, 80, 20] },
        });
    }
    const badge = hello.canvases && hello.canvases.badge;
    if (badge && frames % 30 === 1) {
        const g = badge.getContext('2d');
        g.clearRect(0, 0, badge.width, badge.height);
        g.fillStyle = 'rgba(255, 200, 90, 0.85)';
        g.beginPath();
        g.arc(48, 48, 40, 0, Math.PI * 2);
        g.fill();
        g.fillStyle = '#201000';
        g.font = 'bold 28px sans-serif';
        g.textAlign = 'center';
        g.fillText(String(frames % 100), 48, 58);
        out.overlays.push({ slot: 'badge', op: 'draw' });
    }
    if (frames === 1 || f.reset) {
        out.behaviours.push({
            op: 'set', id: 'pulse',
            behaviour: { type: 'oscillate', channel: 'scale', amp: 0.01, freq: 0.5 },
        });
        out.log.push(`epoch ${f.epoch} ${f.reset ? f.reset.reason : 'start'}, team ${hello.team}`);
    }
    for (const p of f.players) {
        if (p.team === hello.team && p.visible && p.driver !== 'stock') {
            out.bounds.push({ entity: p.entity, current: { radius: 0.5, height: 2.0 } });
        }
    }
    for (const e of f.events) {
        if (e.kind === 'touch' && e.phase === 'occur' && e.team === hello.team) {
            out.claims.push({ target: 'ball', event: e.id });
        }
    }
    out.log.push(`frames ${frames}, events ${events}`);
    return out;
}
