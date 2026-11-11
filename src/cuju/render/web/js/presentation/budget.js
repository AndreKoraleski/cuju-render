// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Budgets of one team's package, section 13 of the contract, provisional numbers to calibrate
// with real packages. The main thread budgets follow the template of `cuju render pack new`,
// which costs about 0.4 ms a drawing on GRF's figure and 0.6 ms on a rigged model of eleven
// players in Chrome on a laptop with an RTX 3050, so the template runs in full at every quality. Static counts are taken as resources load, live meters watch the time the
// package costs, and a team past its budget steps down the degrade ladder, one rung at a time,
// each crossfaded over half a second, down to the stock look at worst. A team that runs well
// under its budget for a while climbs back one rung at a time, and a team that falls again after
// climbing waits twice as long before the next climb, up to RECOVERIES climbs.
//
// The meter reads the mean time of each drawing over the last WINDOW_S seconds. A browser that
// coarsens performance.now() to a tenth of a millisecond gives each drawing's time in steps of
// that size, and the mean over a hundred drawings evens them out, where a high percentile of
// single drawings would read the coarse steps as overruns.

export const KINDS = ['mainMs', 'gpuMs', 'drawCalls', 'triangles', 'textureBytes', 'particles', 'lights', 'shaders', 'voices', 'worklets', 'audioBytes', 'geometryBytes', 'decals', 'effects', 'localLights'];

const MB = 1024 * 1024;
export const TABLE = {
    high: { mainMs: 1.5, gpuMs: 2.5, drawCalls: 150, triangles: 400000, textureBytes: 128 * MB, particles: 20000, lights: 4, shaders: 16, voices: 32, worklets: 4, audioBytes: 64 * MB, fullscreen: 1, geometryBytes: 32 * MB, decals: 64, effects: 64, localLights: 16 },
    medium: { mainMs: 1.25, gpuMs: 2.0, drawCalls: 100, triangles: 200000, textureBytes: 64 * MB, particles: 8000, lights: 2, shaders: 16, voices: 24, worklets: 4, audioBytes: 64 * MB, fullscreen: 0, geometryBytes: 16 * MB, decals: 64, effects: 64, localLights: 16 },
    low: { mainMs: 1.0, gpuMs: 1.0, drawCalls: 60, triangles: 80000, textureBytes: 32 * MB, particles: 2000, lights: 1, shaders: 8, voices: 16, worklets: 2, audioBytes: 32 * MB, fullscreen: 0, geometryBytes: 8 * MB, decals: 32, effects: 32, localLights: 8 },
};
// A worker reply later than this is late, and a worker silent for SILENT_MS is restarted once.
// Before its first answer a worker has FIRST_SILENT_MS, since the page's own loading of models
// and programs holds the main thread then.
export const LATE_MS = 50;
export const SILENT_MS = 5000;
export const FIRST_SILENT_MS = 10000;
// The window of the meter, how long the mean must run over before the ladder steps down, and how
// long it must stay under UNDER of the budget before the ladder steps up, doubled after each
// relapse.
export const WINDOW_S = 2;
export const SUSTAIN_S = 3;
export const RECOVER_S = 10;
export const UNDER = 0.6;
export const RECOVERIES = 3;
// A drawing slower than this stalls the whole page, a load or a hidden tab, and is left out.
export const STALL_MS = 250;

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
        this.underSince = null;
        this.climbed = false;
        this.relapses = 0;
        // The direction of the meter's newest step, down or up.
        this.stepped = null;
        // The meter reads nothing before armAt, set once the package settled, its worker's first
        // answer or a moment after the page built its players.
        this.armAt = 0;
        this.mainMs = 0;
        this.p95 = 0;
    }

    // Arms the meter at a time of the cosmetic clock, forgetting what it read before.
    arm(at) {
        this.armAt = at;
        this.samples = [];
        this.overSince = null;
        this.underSince = null;
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
            // A fall after a climb is a relapse, which doubles the wait of the next climb.
            if (this.climbed) {
                this.climbed = false;
                this.relapses += 1;
            }
        }
        return LADDER[this.rung];
    }

    // Steps the ladder up one rung for a reason and returns the new rung's name.
    recover(reason) {
        if (this.rung > 0) {
            this.rung -= 1;
            this.climbed = true;
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

    // Records the main thread time of one drawing at time now in seconds of the cosmetic clock,
    // with the length of that drawing in milliseconds when known. The mean over the last
    // WINDOW_S seconds above the budget for SUSTAIN_S seconds steps the ladder down, and under
    // UNDER of the budget for RECOVER_S seconds, doubled after each relapse, steps it up.
    // Returns the rung stepped to, with `stepped` down or up, or null.
    meter(ms, now, frameMs = 0) {
        if (now < this.armAt || frameMs > STALL_MS || !Number.isFinite(ms)) {
            return null;
        }
        this.samples.push([now, ms]);
        while (this.samples.length && this.samples[0][0] < now - WINDOW_S) {
            this.samples.shift();
        }
        const values = this.samples.map((s) => s[1]);
        this.mainMs = values.reduce((a, b) => a + b, 0) / values.length;
        const sorted = values.sort((a, b) => a - b);
        this.p95 = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))] || 0;
        // A window is read once it is nearly full, so a few drawings after an arming or a step
        // never decide alone.
        if (now - this.samples[0][0] < WINDOW_S * 0.75) {
            return null;
        }
        const limit = this.limits.mainMs;
        if (this.mainMs > limit) {
            this.underSince = null;
            this.overSince = this.overSince ?? now;
            if (now - this.overSince >= SUSTAIN_S) {
                const reason = `main thread ${this.mainMs.toFixed(2)} ms over ${limit} ms`;
                this.arm(now);
                this.stepped = 'down';
                return this.degrade(reason);
            }
            return null;
        }
        this.overSince = null;
        if (this.rung === 0 || this.mainMs > limit * UNDER || this.relapses >= RECOVERIES) {
            this.underSince = null;
            return null;
        }
        this.underSince = this.underSince ?? now;
        if (now - this.underSince >= RECOVER_S * 2 ** this.relapses) {
            const reason = `main thread ${this.mainMs.toFixed(2)} ms under ${limit} ms`;
            this.arm(now);
            this.stepped = 'up';
            return this.recover(reason);
        }
        return null;
    }

    snapshot() {
        return { quality: this.quality, limits: { ...this.limits }, used: { ...this.used }, refused: { ...this.refused }, level: this.level, reasons: this.reasons.slice(), mainMs: this.mainMs || 0, p95: this.p95 || 0 };
    }
}
