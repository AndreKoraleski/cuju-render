// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Budgets of one team's package, section 13 of the contract, provisional numbers to calibrate
// with real packages. Static counts are taken as resources load, live meters watch the time the
// package costs, and a team past its budget steps down the degrade ladder, one rung at a time,
// each crossfaded over half a second, down to the stock look at worst.

export const KINDS = ['mainMs', 'gpuMs', 'drawCalls', 'triangles', 'textureBytes', 'particles', 'lights', 'shaders', 'voices', 'worklets', 'audioBytes', 'geometryBytes', 'decals', 'effects', 'localLights'];

const MB = 1024 * 1024;
export const TABLE = {
    high: { mainMs: 0.75, gpuMs: 2.5, drawCalls: 150, triangles: 400000, textureBytes: 128 * MB, particles: 20000, lights: 4, shaders: 16, voices: 32, worklets: 4, audioBytes: 64 * MB, fullscreen: 1, geometryBytes: 32 * MB, decals: 64, effects: 64, localLights: 16 },
    medium: { mainMs: 0.75, gpuMs: 2.0, drawCalls: 100, triangles: 200000, textureBytes: 64 * MB, particles: 8000, lights: 2, shaders: 16, voices: 24, worklets: 4, audioBytes: 64 * MB, fullscreen: 0, geometryBytes: 16 * MB, decals: 64, effects: 64, localLights: 16 },
    low: { mainMs: 0.5, gpuMs: 1.0, drawCalls: 60, triangles: 80000, textureBytes: 32 * MB, particles: 2000, lights: 1, shaders: 8, voices: 16, worklets: 2, audioBytes: 32 * MB, fullscreen: 0, geometryBytes: 8 * MB, decals: 32, effects: 32, localLights: 8 },
};
// A worker reply later than this is late, and a worker silent for SILENT_MS is restarted once.
export const LATE_MS = 50;
export const SILENT_MS = 2000;
// How long a meter must run over before the ladder steps down.
export const SUSTAIN_S = 2;

// The rungs of the degrade ladder, from the full package down to the stock look.
export const LADDER = ['full', 'fewerParticles', 'noPasses', 'localLights', 'standardMaterials', 'noWorker', 'manifest', 'stock'];

export function limitsFor(quality) {
    return { ...(TABLE[quality] || TABLE.medium) };
}

export class Budget {
    constructor(quality = 'medium') {
        this.setQuality(quality);
        this.used = Object.fromEntries(KINDS.map((k) => [k, 0]));
        this.refused = Object.fromEntries(KINDS.map((k) => [k, 0]));
        this.rung = 0;
        this.reasons = [];
        this.samples = [];
        this.overSince = null;
    }

    setQuality(quality) {
        this.quality = TABLE[quality] ? quality : 'medium';
        this.limits = limitsFor(this.quality);
    }

    // Whether a cost, {kind: amount}, fits what is left of every budget it names.
    fits(cost) {
        return Object.entries(cost).every(([k, v]) => !(k in this.limits) || (this.used[k] || 0) + v <= this.limits[k]);
    }

    // Takes a cost when it fits and returns whether it did, counting a refusal otherwise.
    take(cost) {
        if (!this.fits(cost)) {
            for (const [k, v] of Object.entries(cost)) {
                if (k in this.limits && (this.used[k] || 0) + v > this.limits[k]) {
                    this.refused[k] = (this.refused[k] || 0) + 1;
                }
            }
            return false;
        }
        for (const [k, v] of Object.entries(cost)) {
            if (k in this.limits) {
                this.used[k] = (this.used[k] || 0) + v;
            }
        }
        return true;
    }

    give(cost) {
        for (const [k, v] of Object.entries(cost)) {
            if (k in this.used) {
                this.used[k] = Math.max(0, this.used[k] - v);
            }
        }
    }

    // Steps the ladder down one rung for a reason and returns the new rung's name.
    degrade(reason) {
        if (this.rung < LADDER.length - 1) {
            this.rung += 1;
            this.reasons.push(`${LADDER[this.rung]}, ${reason}`);
        }
        return LADDER[this.rung];
    }

    get level() {
        return this.workerOff && this.rung < LADDER.indexOf('noWorker') ? 'noWorker' : LADDER[this.rung];
    }

    // A worker that failed for good stops the worker alone, the rest of the package keeps its
    // rung, its shaders, passes and lights among it.
    stopWorker(reason) {
        if (!this.workerOff) {
            this.workerOff = true;
            this.reasons.push(`noWorker, ${reason}`);
        }
    }

    // Whether the ladder has reached or passed a rung.
    past(rung) {
        return this.rung >= LADDER.indexOf(rung) || (rung === 'noWorker' && !!this.workerOff);
    }

    // Records the main thread time of one drawing at time now in seconds. A 95th percentile over
    // the last two seconds above the budget for SUSTAIN_S seconds steps the ladder down. Returns
    // the rung stepped to, or null.
    meter(ms, now) {
        this.samples.push([now, ms]);
        while (this.samples.length && this.samples[0][0] < now - 2) {
            this.samples.shift();
        }
        const sorted = this.samples.map((s) => s[1]).sort((a, b) => a - b);
        const p95 = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))] || 0;
        this.p95 = p95;
        if (p95 <= this.limits.mainMs) {
            this.overSince = null;
            return null;
        }
        if (this.overSince == null) {
            this.overSince = now;
        }
        if (now - this.overSince >= SUSTAIN_S) {
            this.overSince = now;
            this.samples = [];
            return this.degrade(`main thread ${p95.toFixed(2)} ms over ${this.limits.mainMs} ms`);
        }
        return null;
    }

    snapshot() {
        return { quality: this.quality, limits: { ...this.limits }, used: { ...this.used }, refused: { ...this.refused }, level: this.level, reasons: this.reasons.slice(), p95: this.p95 || 0 };
    }
}
