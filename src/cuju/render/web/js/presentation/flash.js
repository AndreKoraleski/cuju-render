// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The flash governor of the renderer, after WCAG 2.3.1 with its definitions of the general flash
// and red flash thresholds, and after ITU-R BT.1702.
//
// A general transition is a change in relative luminance of a tenth of the maximum or more where
// the darker of the two states is below 0.80. A red transition is a change of more than 20 in the
// red value, the linear R minus G minus B times 320 held at zero or more, where one of the two
// states is a saturated red, its R at least 0.8 of R plus G plus B. A flash is a pair of opposing
// transitions. At most three general and three red flashes may fall in any one second, counting
// only flashes over more than a quarter of some ten degree field, which WCAG estimates as a 341 by
// 256 window of a 1024 by 768 screen, so a window a third of the screen wide and a third high.
//
// FlashCounter measures the frames the page shows on a small grid. Envelope holds one intensity
// channel of a team to three rises a second before anything reaches the screen. FlashGovernor
// keeps the envelopes and, as a backstop, clamps every team's effects for a second when the
// counter still reaches a third flash in a second.

export const SAFETY_FLASHES = Object.freeze({ perSecond: 3, areaFraction: 0.25, fieldDegrees: 10, fieldWidth: 1 / 3, fieldHeight: 1 / 3, version: 1 });

// The general flash threshold, a change of a tenth of the maximum relative luminance, counted
// while the darker state is below DARK_LIMIT.
export const LUMINANCE_STEP = 0.1;
export const DARK_LIMIT = 0.8;
// The red flash threshold, a change above RED_STEP in the red value, the linear R minus G minus B
// times RED_SCALE, where one state has R at least RED_SATURATION of R plus G plus B.
export const RED_SATURATION = 0.8;
export const RED_SCALE = 320;
export const RED_STEP = 20;

// A small slack on the edge of a window, so an event exactly one window old has left it whatever
// the rounding of the times.
const EDGE = 1e-9;
// The most area transitions a counter remembers per kind, enough for two a frame at 240 frames
// per second over a second.
const MEMORY = 1024;

// The linear value of one sRGB channel from 0 to 255, by the formula of WCAG 2.2.
export function linear(c) {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}

const LINEAR = new Float64Array(256);
for (let c = 0; c < 256; c += 1) LINEAR[c] = linear(c);

// The relative luminance of an sRGB colour with channels from 0 to 255, by the formula of WCAG.
export function relativeLuminance(r, g, b) {
    return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

// The red value of WCAG's red flash for an sRGB colour, held at zero or more.
export function redValue(r, g, b) {
    return Math.max(0, (linear(r) - linear(g) - linear(b)) * RED_SCALE);
}

// Whether an sRGB colour is a saturated red in the sense of WCAG's red flash.
export function saturatedRed(r, g, b) {
    const R = linear(r);
    const sum = R + linear(g) + linear(b);
    return sum > 0 && R >= RED_SATURATION * sum;
}

// A queue of times in a ring of fixed size, oldest first. A full ring drops its oldest time.
class TimeQueue {
    constructor(capacity) {
        this.times = new Float64Array(Math.max(1, capacity));
        this.start = 0;
        this.length = 0;
    }

    clear() {
        this.start = 0;
        this.length = 0;
    }

    push(time) {
        const size = this.times.length;
        if (this.length === size) {
            this.start = (this.start + 1) % size;
            this.length -= 1;
        }
        this.times[(this.start + this.length) % size] = time;
        this.length += 1;
    }

    // Drops every time at or before the limit.
    expire(limit) {
        const size = this.times.length;
        while (this.length > 0 && this.times[this.start] <= limit) {
            this.start = (this.start + 1) % size;
            this.length -= 1;
        }
    }
}

// The area transitions and flashes of one kind, general or red. Each area transition opposite to
// the one before it, both within one window, completes a flash, and the pair is spent.
class FlashTrack {
    constructor(window) {
        this.window = window;
        this.transitions = new TimeQueue(MEMORY);
        this.flashes = new TimeQueue(MEMORY);
        this.reset();
    }

    reset() {
        this.transitions.clear();
        this.flashes.clear();
        this.lastArea = -Infinity;
        this.pendingDirection = 0;
        this.pendingTime = -Infinity;
        this.total = 0;
    }

    transition(time, direction) {
        this.transitions.push(time);
        this.lastArea = time;
        if (this.pendingDirection === -direction && this.pendingTime > time - this.window + EDGE) {
            this.flashes.push(time);
            this.total += 1;
            this.pendingDirection = 0;
            this.pendingTime = -Infinity;
        } else {
            this.pendingDirection = direction;
            this.pendingTime = time;
        }
    }

    expire(time) {
        const limit = time - this.window + EDGE;
        this.transitions.expire(limit);
        this.flashes.expire(limit);
    }
}

// Counts the general and red flashes of the frames the page shows, read back at a small grid,
// one cell a pixel. Each cell keeps the level of its last extreme and the direction of its last
// transition. A frame is an area transition of a direction when the cells whose latest transition
// went that way, since the last area transition of the kind and within the window, cover more
// than areaFraction of some field window, found with a summed area table. Every push reuses the
// same buffers and returns the same result object.
export class FlashCounter {
    constructor(width, height, { window = 1, areaFraction = 0.25, fieldWidth = 1 / 3, fieldHeight = 1 / 3 } = {}) {
        if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1) {
            throw new RangeError('the grid needs a whole width and height of one or more');
        }
        this.width = width;
        this.height = height;
        this.window = window;
        this.areaFraction = areaFraction;
        this.fieldCellsX = Math.min(width, Math.max(1, Math.round(width * fieldWidth)));
        this.fieldCellsY = Math.min(height, Math.max(1, Math.round(height * fieldHeight)));
        this.limit = areaFraction * this.fieldCellsX * this.fieldCellsY;
        const n = width * height;
        this._luminanceLow = new Float32Array(n);
        this._luminanceHigh = new Float32Array(n);
        this._luminanceDirection = new Int8Array(n);
        this._luminanceTime = new Float64Array(n);
        this._redLow = new Float32Array(n);
        this._redHigh = new Float32Array(n);
        this._redLowSaturated = new Uint8Array(n);
        this._redHighSaturated = new Uint8Array(n);
        this._redDirection = new Int8Array(n);
        this._redTime = new Float64Array(n);
        this._generalMask = new Int8Array(n);
        this._redMask = new Int8Array(n);
        this._table = new Int32Array((width + 1) * (height + 1));
        this._general = new FlashTrack(window);
        this._red = new FlashTrack(window);
        this._result = { general: 0, red: 0, transitions: 0, redTransitions: 0, generalTotal: 0, redTotal: 0 };
        this.reset();
    }

    get general() {
        return this._result.general;
    }

    get red() {
        return this._result.red;
    }

    reset() {
        this._started = false;
        this._time = -Infinity;
        this._general.reset();
        this._red.reset();
        const r = this._result;
        r.general = 0;
        r.red = 0;
        r.transitions = 0;
        r.redTransitions = 0;
        r.generalTotal = 0;
        r.redTotal = 0;
    }

    // Takes one frame shown at time seconds, width by height sRGB pixels with four bytes each.
    // A time before the last one is a seek and starts the count again. Returns the flashes and
    // area transitions in the last window, general and red, and the flashes since the start.
    push(time, rgba) {
        const n = this.width * this.height;
        if (!rgba || rgba.length < n * 4) throw new RangeError('the frame is smaller than the grid');
        if (this._started && time < this._time) this.reset();
        const first = !this._started;
        this._started = true;
        this._time = time;
        const since = time - this.window + EDGE;
        const generalFloor = Math.max(this._general.lastArea, since);
        const redFloor = Math.max(this._red.lastArea, since);
        const lLow = this._luminanceLow;
        const lHigh = this._luminanceHigh;
        const lDirection = this._luminanceDirection;
        const lTime = this._luminanceTime;
        const rLow = this._redLow;
        const rHigh = this._redHigh;
        const rLowSaturated = this._redLowSaturated;
        const rHighSaturated = this._redHighSaturated;
        const rDirection = this._redDirection;
        const rTime = this._redTime;
        const gMask = this._generalMask;
        const rMask = this._redMask;
        let generalUp = 0;
        let generalDown = 0;
        let redUp = 0;
        let redDown = 0;
        for (let i = 0, p = 0; i < n; i += 1, p += 4) {
            const R = LINEAR[rgba[p]];
            const G = LINEAR[rgba[p + 1]];
            const B = LINEAR[rgba[p + 2]];
            const L = 0.2126 * R + 0.7152 * G + 0.0722 * B;
            const sum = R + G + B;
            const saturated = sum > 0 && R >= RED_SATURATION * sum ? 1 : 0;
            let q = (R - G - B) * RED_SCALE;
            if (q < 0) q = 0;
            if (first) {
                lLow[i] = L;
                lHigh[i] = L;
                lDirection[i] = 0;
                lTime[i] = -Infinity;
                rLow[i] = q;
                rHigh[i] = q;
                rLowSaturated[i] = saturated;
                rHighSaturated[i] = saturated;
                rDirection[i] = 0;
                rTime[i] = -Infinity;
                gMask[i] = 0;
                rMask[i] = 0;
                continue;
            }
            // A cell after a rise follows its highest level, after a fall its lowest, and before
            // its first transition both.
            let d = lDirection[i];
            if (d !== -1 && lHigh[i] - L >= LUMINANCE_STEP && L < DARK_LIMIT) {
                lDirection[i] = -1;
                lLow[i] = L;
                lTime[i] = time;
            } else if (d !== 1 && L - lLow[i] >= LUMINANCE_STEP && lLow[i] < DARK_LIMIT) {
                lDirection[i] = 1;
                lHigh[i] = L;
                lTime[i] = time;
            } else {
                if (d !== -1 && L > lHigh[i]) lHigh[i] = L;
                if (d !== 1 && L < lLow[i]) lLow[i] = L;
            }
            d = lDirection[i];
            if (d !== 0 && lTime[i] > generalFloor) {
                gMask[i] = d;
                if (d > 0) generalUp += 1;
                else generalDown += 1;
            } else {
                gMask[i] = 0;
            }
            d = rDirection[i];
            if (d !== -1 && rHigh[i] - q > RED_STEP && (saturated || rHighSaturated[i])) {
                rDirection[i] = -1;
                rLow[i] = q;
                rLowSaturated[i] = saturated;
                rTime[i] = time;
            } else if (d !== 1 && q - rLow[i] > RED_STEP && (saturated || rLowSaturated[i])) {
                rDirection[i] = 1;
                rHigh[i] = q;
                rHighSaturated[i] = saturated;
                rTime[i] = time;
            } else {
                if (d !== -1 && q > rHigh[i]) {
                    rHigh[i] = q;
                    rHighSaturated[i] = saturated;
                }
                if (d !== 1 && q < rLow[i]) {
                    rLow[i] = q;
                    rLowSaturated[i] = saturated;
                }
            }
            d = rDirection[i];
            if (d !== 0 && rTime[i] > redFloor) {
                rMask[i] = d;
                if (d > 0) redUp += 1;
                else redDown += 1;
            } else {
                rMask[i] = 0;
            }
        }
        if (!first) {
            const limit = this.limit;
            if (generalUp > limit && this._covers(gMask, 1)) this._general.transition(time, 1);
            if (generalDown > limit && this._covers(gMask, -1)) this._general.transition(time, -1);
            if (redUp > limit && this._covers(rMask, 1)) this._red.transition(time, 1);
            if (redDown > limit && this._covers(rMask, -1)) this._red.transition(time, -1);
        }
        this._general.expire(time);
        this._red.expire(time);
        const r = this._result;
        r.general = this._general.flashes.length;
        r.red = this._red.flashes.length;
        r.transitions = this._general.transitions.length;
        r.redTransitions = this._red.transitions.length;
        r.generalTotal = this._general.total;
        r.redTotal = this._red.total;
        return r;
    }

    // Whether the cells of the mask equal to direction cover more than the limit in some field
    // window. The first row and column of the summed area table stay zero.
    _covers(mask, direction) {
        const w = this.width;
        const h = this.height;
        const stride = w + 1;
        const table = this._table;
        for (let y = 0; y < h; y += 1) {
            const row = (y + 1) * stride + 1;
            const above = y * stride + 1;
            const cells = y * w;
            let run = 0;
            for (let x = 0; x < w; x += 1) {
                if (mask[cells + x] === direction) run += 1;
                table[row + x] = table[above + x] + run;
            }
        }
        const fx = this.fieldCellsX;
        const fy = this.fieldCellsY;
        const limit = this.limit;
        for (let y = 0; y + fy <= h; y += 1) {
            const top = y * stride;
            const bottom = (y + fy) * stride;
            for (let x = 0; x + fx <= w; x += 1) {
                const area = table[bottom + x + fx] - table[top + x + fx] - table[bottom + x] + table[top + x];
                if (area > limit) return true;
            }
        }
        return false;
    }
}

// A governor on one intensity channel of a team, a light, an emissive multiplier, a sky or
// floodlight moment or a full screen pass. A rise is an increase of at least rise of the range
// above the lowest value since a fall of at least as much. Once perSecond rises fell within the
// window, a further rise is held, so the value may only fall or stay until the window frees a
// rise. Red channels keep their own count. Falls pass at once.
export class Envelope {
    constructor({ perSecond = 3, rise = 0.1, window = 1, range = 1 } = {}) {
        this.perSecond = Math.max(0, Math.floor(perSecond));
        this.window = window;
        this.step = rise * range;
        this._general = new TimeQueue(this.perSecond);
        this._red = new TimeQueue(this.perSecond);
        this.reset();
    }

    // The rises in the current window, general and red together.
    get rises() {
        return this._general.length + this._red.length;
    }

    get redRises() {
        return this._red.length;
    }

    // Whether the last value asked for was held below its request.
    get held() {
        return this._held;
    }

    get value() {
        return this._out;
    }

    reset() {
        this._general.clear();
        this._red.clear();
        this._out = 0;
        this._low = 0;
        this._peak = 0;
        this._armed = true;
        this._held = false;
        this._time = -Infinity;
    }

    // Takes the intensity asked for at time seconds, a multiplier of zero or more, and returns
    // the intensity allowed now. A time before the last one starts the channel again.
    apply(time, value, red = false) {
        const v = Number.isFinite(value) && value > 0 ? value : 0;
        if (time < this._time) this.reset();
        this._time = time;
        const limit = time - this.window + EDGE;
        this._general.expire(limit);
        this._red.expire(limit);
        this._held = false;
        if (v <= this._out) {
            this._out = v;
            if (!this._armed && this._peak - v >= this.step) {
                this._armed = true;
                this._low = v;
            }
            if (this._armed && v < this._low) this._low = v;
            return v;
        }
        if (!this._armed || v - this._low < this.step) {
            this._out = v;
            if (v > this._peak) this._peak = v;
            return v;
        }
        const queue = red ? this._red : this._general;
        if (queue.length >= this.perSecond) {
            this._held = true;
            return this._out;
        }
        queue.push(time);
        this._armed = false;
        this._peak = v;
        this._out = v;
        return v;
    }
}

// The flash governor of the page. It keeps one Envelope per intensity channel, and as a backstop
// clamps every team's effects to clampFactor for clampSeconds once the counter reaches the
// perSecond flash of a second, general or red, then returns to full over returnSeconds.
export class FlashGovernor {
    constructor({ perSecond = 3, clampSeconds = 1, clampFactor = 0.25, returnSeconds = 0.3 } = {}) {
        this.perSecond = perSecond;
        this.clampSeconds = clampSeconds;
        this.clampFactor = clampFactor;
        this.returnSeconds = returnSeconds;
        this.events = [];
        this._envelopes = new Map();
        this.reset();
    }

    // The Envelope of a channel, made with the options of the first call for its id.
    envelope(id, options = {}) {
        let envelope = this._envelopes.get(id);
        if (!envelope) {
            envelope = new Envelope({ perSecond: this.perSecond, ...options });
            this._envelopes.set(id, envelope);
        }
        return envelope;
    }

    // Whether the backstop clamp is on at the last time the governor saw.
    get clamped() {
        return this._time < this._until;
    }

    reset() {
        for (const envelope of this._envelopes.values()) envelope.reset();
        this.events.length = 0;
        this._until = -Infinity;
        this._time = -Infinity;
        this._general = 0;
        this._red = 0;
        this._generalTotal = 0;
        this._redTotal = 0;
    }

    // Takes the counts of a FlashCounter at time seconds. A new flash while the count stands at
    // perSecond or more starts the clamp, or holds it on for clampSeconds from now.
    observe(time, counts) {
        if (time < this._time) {
            this._until = -Infinity;
            this._generalTotal = 0;
            this._redTotal = 0;
        }
        this._time = time;
        const general = Number(counts && counts.general) || 0;
        const red = Number(counts && counts.red) || 0;
        const generalTotal = counts && Number.isFinite(counts.generalTotal) ? counts.generalTotal : null;
        const redTotal = counts && Number.isFinite(counts.redTotal) ? counts.redTotal : null;
        const generalNew = generalTotal === null ? general > this._general : generalTotal > this._generalTotal;
        const redNew = redTotal === null ? red > this._red : redTotal > this._redTotal;
        this._general = general;
        this._red = red;
        if (generalTotal !== null) this._generalTotal = generalTotal;
        if (redTotal !== null) this._redTotal = redTotal;
        let kind = null;
        let count = 0;
        if (general >= this.perSecond && generalNew) {
            kind = 'general';
            count = general;
        } else if (red >= this.perSecond && redNew) {
            kind = 'red';
            count = red;
        }
        if (kind === null) return;
        const until = time + this.clampSeconds;
        if (time < this._until && this.events.length > 0) {
            const last = this.events[this.events.length - 1];
            if (until > last.until) last.until = until;
        } else {
            this.events.push({ time, kind, count, until });
            if (this.events.length > 32) this.events.shift();
        }
        if (until > this._until) this._until = until;
    }

    // The factor on every team's effect intensity at time seconds, 1 normally, clampFactor while
    // the clamp is on and a smooth return to 1 over returnSeconds after it ends.
    factor(time) {
        if (time > this._time) this._time = time;
        if (time < this._until) return this.clampFactor;
        const s = this.returnSeconds > 0 ? (time - this._until) / this.returnSeconds : 1;
        if (!(s < 1)) return 1;
        const smooth = s * s * (3 - 2 * s);
        return this.clampFactor + (1 - this.clampFactor) * smooth;
    }
}

// The cells a side of the grid that a slot's guard reads, and the seconds a slot that flashed past
// the limit stays hidden.
export const SLOT_GRID = 16;
export const SLOT_HOLD = 3;

// The sRGB value from 0 to 255 of a linear value from 0 to 1, the inverse of linear.
function encode(v) {
    const s = v <= 0.0031308 ? v * 12.92 : 1.055 * Math.pow(v, 1 / 2.4) - 0.055;
    return Math.max(0, Math.min(255, Math.round(s * 255)));
}

// A grid by grid copy of an sRGB image of width by height pixels with four bytes each, each cell
// the mean of the linear light of the pixels that fall in it, so a pattern finer than a cell
// counts by its mean and never slips between the cells it would sample. Into out when given.
export function downsample(rgba, width, height, grid = SLOT_GRID, out = new Uint8ClampedArray(grid * grid * 4)) {
    const sums = new Float64Array(grid * grid * 3);
    const counts = new Uint32Array(grid * grid);
    for (let y = 0; y < height; y += 1) {
        const row = Math.min(grid - 1, Math.floor((y * grid) / height)) * grid;
        for (let x = 0; x < width; x += 1) {
            const cell = row + Math.min(grid - 1, Math.floor((x * grid) / width));
            const p = (y * width + x) * 4;
            sums[cell * 3] += LINEAR[rgba[p]];
            sums[cell * 3 + 1] += LINEAR[rgba[p + 1]];
            sums[cell * 3 + 2] += LINEAR[rgba[p + 2]];
            counts[cell] += 1;
        }
    }
    for (let cell = 0; cell < grid * grid; cell += 1) {
        const n = counts[cell] || 1;
        out[cell * 4] = encode(sums[cell * 3] / n);
        out[cell * 4 + 1] = encode(sums[cell * 3 + 1] / n);
        out[cell * 4 + 2] = encode(sums[cell * 3 + 2] / n);
        out[cell * 4 + 3] = 255;
    }
    return out;
}

// The flash guard of one overlay slot. A worker's drawing in a slot reaches the screen beside the
// picture the backstop reads, so each slot counts its own flashes, on a grid over the slot as one
// field, what the slot shows each drawing and black while it is hidden. A slot that reaches
// perSecond flashes in a second, general or red, hides for hold seconds, and a drawing that could
// not be read never shows.
export class SlotGuard {
    constructor({ perSecond = SAFETY_FLASHES.perSecond, hold = SLOT_HOLD, grid = SLOT_GRID } = {}) {
        this.perSecond = perSecond;
        this.hold = hold;
        this.counter = new FlashCounter(grid, grid, { areaFraction: SAFETY_FLASHES.areaFraction, fieldWidth: 1, fieldHeight: 1 });
        this.dark = new Uint8ClampedArray(grid * grid * 4);
        this.sample = this.dark;
        this.until = -Infinity;
        this.time = -Infinity;
        this.trips = 0;
    }

    // Takes the drawing a slot shows from now on, grid by grid sRGB pixels over black, or null for
    // one that could not be read.
    draw(rgba) {
        this.sample = rgba;
    }

    // Whether the slot shows at time seconds when it would show by its window, wanted. Counts
    // what the screen then shows.
    show(time, wanted) {
        if (time < this.time) {
            this.until = -Infinity;
        }
        this.time = time;
        const shown = wanted && !!this.sample && time >= this.until;
        const counts = this.counter.push(time, shown ? this.sample : this.dark);
        if (shown && (counts.general >= this.perSecond || counts.red >= this.perSecond)) {
            this.until = time + this.hold;
            this.trips += 1;
            return false;
        }
        return shown;
    }
}
