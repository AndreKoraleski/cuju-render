// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The loudness and peak safety of the renderer's sound, after ITU-R BS.1770-4 and EBU R 128 with
// its test signals of EBU Tech 3341.
//
// LoudnessMeter measures momentary, short-term and gated integrated loudness in LUFS with the K
// weighting of BS.1770-4, and the true peak of its input. TruePeak oversamples four times below
// 96 kHz and twice from 96 kHz, as Annex 2 of BS.1770-4 asks. Limiter is a look-ahead brickwall
// that holds the oversampled output under a ceiling in dBTP. Governor lowers a team bus whose
// loudness passes the ceilings of the safety numbers, guards against a startling rise and latches
// a penalty on a bus that keeps the governor busy. measure reads a decoded sample once, so a cue
// can be scaled at load, and sanitize clears the samples that are not finite.
//
// Every class allocates its memory when it is made, so a call for one AudioWorklet quantum of 128
// frames allocates nothing.

// The integrated target of EBU R 128 and the safety numbers, in LUFS.
export const TARGET_LUFS = -23;

// The offset of the loudness formula of BS.1770-4, which brings a 1 kHz sine at the level of full
// scale minus 23 dB in both channels of a stereo signal to -23 LUFS.
const OFFSET = -0.691;
// The absolute gate of BS.1770-4 in LUFS and the relative gate in LU below the gated mean.
const ABSOLUTE_GATE = -70;
const RELATIVE_GATE = -10;
// The mean square of the K weighted sum under which a window counts as silence and reads
// -Infinity, so the decaying tail of the filters after a sound ends in silence too.
const SILENCE = 1e-20;
// The histogram of the gating blocks covers -70 to +30 LUFS in steps of a hundredth of a LU. Each
// bin keeps its count and the sum of its mean squares, so the gated mean is exact apart from the
// blocks that share a bin with the relative gate.
const BIN_STEP = 0.01;
const BINS = 10000;
// Each 100 ms hop of the gating blocks splits into four parts of about 25 ms, so the momentary and
// short-term loudness follow the signal four times faster than the hop.
const PARTS = 4;
const MOMENTARY_PARTS = 4 * PARTS;
const SHORT_TERM_PARTS = 30 * PARTS;

// The taps per phase of the interpolation filter of the true peak and the shape of its Kaiser
// window. Each phase is a windowed sinc of 16 taps, half a width of 8 input samples on each side,
// with its sum held at one. Up to a third of the sample rate every phase keeps the level within
// 0.03 dB, and up to 0.4 of the rate within 0.05 dB.
export const TRUE_PEAK_TAPS = 16;
const KAISER_BETA = 5;

const LN_100 = Math.log(100);
// The loudest level the governor believes, in LUFS, well over any signal near full scale.
const LOUDEST = 30;

// The gain of a level in dB.
export function dbToGain(db) {
    return Math.pow(10, db / 20);
}

// The level in dB of a gain, -Infinity for zero.
export function gainToDb(g) {
    return 20 * Math.log10(Math.abs(g));
}

// The loudness in LUFS of a mean square of the weighted sum of the K weighted channels.
function lufs(meanSquare) {
    return meanSquare > SILENCE ? OFFSET + 10 * Math.log10(meanSquare) : -Infinity;
}

// The two biquads of the K weighting of BS.1770-4 for any sample rate, the high shelf of the head
// first and the RLB high pass second, each as {b, a} with a[0] one. The poles, zeros and gains come
// from the published 48 kHz filters by the bilinear derivation of libebur128, so at 48 kHz both
// filters equal the published coefficients.
export function kWeighting(sampleRate) {
    let f0 = 1681.974450955533;
    const G = 3.999843853973347;
    let Q = 0.7071752369554196;
    let K = Math.tan((Math.PI * f0) / sampleRate);
    const Vh = Math.pow(10, G / 20);
    const Vb = Math.pow(Vh, 0.4996667741545416);
    let a0 = 1 + K / Q + K * K;
    const shelf = {
        b: [(Vh + (Vb * K) / Q + K * K) / a0, (2 * (K * K - Vh)) / a0, (Vh - (Vb * K) / Q + K * K) / a0],
        a: [1, (2 * (K * K - 1)) / a0, (1 - K / Q + K * K) / a0],
    };
    f0 = 38.13547087602444;
    Q = 0.5003270373238773;
    K = Math.tan((Math.PI * f0) / sampleRate);
    a0 = 1 + K / Q + K * K;
    const highPass = {
        b: [1, -2, 1],
        a: [1, (2 * (K * K - 1)) / a0, (1 - K / Q + K * K) / a0],
    };
    return [shelf, highPass];
}

// The channel weights of BS.1770-4 for a channel count in the order of the Web Audio API. Five
// channels are left, right, centre and the two surrounds, six add the low frequency channel after
// the centre, which the standard leaves out of the sum.
export function defaultWeights(channels) {
    if (channels === 5) return [1, 1, 1, 1.41, 1.41];
    if (channels === 6) return [1, 1, 1, 0, 1.41, 1.41];
    return new Array(channels).fill(1);
}

function besselI0(x) {
    let sum = 1;
    let term = 1;
    for (let k = 1; k < 64; k += 1) {
        term *= (x / (2 * k)) * (x / (2 * k));
        sum += term;
        if (term < 1e-17 * sum) break;
    }
    return sum;
}

// The oversampling factor of the true peak at a sample rate, four below 96 kHz and two from it.
export function oversampling(sampleRate) {
    return sampleRate < 96000 ? 4 : 2;
}

// The interpolation filter of the true peak, one row of taps for each phase between two input
// samples. Row p minus one gives the value p over factor of the way from the input sample taps over
// two minus one samples old towards the next newer one, from the last taps input samples, oldest
// first. The phase at the input sample itself is the sample, so it has no row.
export function interpolationTable(factor, taps = TRUE_PEAK_TAPS) {
    const half = taps / 2;
    const table = new Float64Array((factor - 1) * taps);
    const norm = besselI0(KAISER_BETA);
    for (let p = 1; p < factor; p += 1) {
        let sum = 0;
        for (let k = 0; k < taps; k += 1) {
            const t = k - half + 1 - p / factor;
            const sinc = t === 0 ? 1 : Math.sin(Math.PI * t) / (Math.PI * t);
            const u = t / half;
            const w = Math.abs(u) >= 1 ? 0 : besselI0(KAISER_BETA * Math.sqrt(1 - u * u)) / norm;
            table[(p - 1) * taps + k] = sinc * w;
            sum += sinc * w;
        }
        for (let k = 0; k < taps; k += 1) table[(p - 1) * taps + k] /= sum;
    }
    return table;
}

// The value of one phase of the interpolation filter, its 16 taps from offset r of the table against
// the 16 samples from offset p of a ring, written out in full, about twice as fast as a loop.
function dot16(t, r, b, p) {
    return t[r] * b[p] + t[r + 1] * b[p + 1] + t[r + 2] * b[p + 2] + t[r + 3] * b[p + 3]
        + t[r + 4] * b[p + 4] + t[r + 5] * b[p + 5] + t[r + 6] * b[p + 6] + t[r + 7] * b[p + 7]
        + t[r + 8] * b[p + 8] + t[r + 9] * b[p + 9] + t[r + 10] * b[p + 10] + t[r + 11] * b[p + 11]
        + t[r + 12] * b[p + 12] + t[r + 13] * b[p + 13] + t[r + 14] * b[p + 14] + t[r + 15] * b[p + 15];
}

// The true peak of BS.1770-4 Annex 2 over any number of channels. Each channel keeps its last 16
// samples twice over in a ring, so the window of the filter is always one run of memory. A sample
// counts at once, and the values between two samples count once eight newer samples have come.
export class TruePeak {
    constructor(sampleRate, channels) {
        this.sampleRate = sampleRate;
        this.channels = channels;
        this.factor = oversampling(sampleRate);
        this.taps = TRUE_PEAK_TAPS;
        this.table = interpolationTable(this.factor, this.taps);
        this.rings = [];
        for (let c = 0; c < channels; c += 1) this.rings.push(new Float64Array(2 * this.taps));
        this.zeros = new Float32Array(this.taps);
        this.flushArrays = new Array(channels).fill(this.zeros);
        this.position = 0;
        this.peak = 0;
    }

    reset() {
        for (const ring of this.rings) ring.fill(0);
        this.position = 0;
        this.peak = 0;
    }

    // The largest absolute oversampled value of this call, which also raises the running peak.
    process(channelArrays) {
        const taps = this.taps;
        const phases = this.factor - 1;
        const table = this.table;
        let frames = 0;
        for (let c = 0; c < this.channels; c += 1) {
            const input = channelArrays[c];
            if (input && input.length > frames) frames = input.length;
        }
        let largest = 0;
        const start = this.position;
        let end = start;
        for (let c = 0; c < this.channels; c += 1) {
            const input = channelArrays[c];
            const length = input ? input.length : 0;
            const ring = this.rings[c];
            let p = start;
            for (let i = 0; i < frames; i += 1) {
                let x = i < length ? input[i] : 0;
                if (x - x !== 0) x = 0;
                ring[p] = x;
                ring[p + taps] = x;
                p = p + 1 === taps ? 0 : p + 1;
                const a = x < 0 ? -x : x;
                if (a > largest) largest = a;
                for (let ph = 0; ph < phases; ph += 1) {
                    const s = dot16(table, ph * taps, ring, p);
                    if (s > largest) largest = s;
                    else if (-s > largest) largest = -s;
                }
            }
            end = p;
        }
        this.position = end;
        if (largest > this.peak) this.peak = largest;
        return largest;
    }

    // Feeds silence through the filter, so the values between the last samples and the end of a
    // finished signal count too. Returns the largest of them.
    flush() {
        return this.process(this.flushArrays);
    }
}

// Loudness after BS.1770-4 over any number of channels. Each channel runs through the two K
// weighting biquads, and the weighted sum of their squares gathers in parts of about 25 ms, four to
// a 100 ms hop. The momentary loudness is the mean of the last 400 ms and the short-term loudness
// of the last 3 s, both counting the time before the first sample as silence. A gating block of
// 400 ms closes on every hop from 400 ms on, so the blocks overlap by 75 percent. The option
// truePeak false leaves out the true peak, which costs more than the loudness, and the meter then
// reads its true peak as -Infinity.
export class LoudnessMeter {
    constructor(sampleRate, channels, { weights, truePeak = true } = {}) {
        this.sampleRate = sampleRate;
        this.channels = channels;
        this.weights = Float64Array.from(weights ?? defaultWeights(channels));
        if (this.weights.length !== channels) throw new Error('one weight per channel');
        const [shelf, highPass] = kWeighting(sampleRate);
        this.coefficients = Float64Array.from([...shelf.b, shelf.a[1], shelf.a[2], highPass.a[1], highPass.a[2]]);
        this.states = new Float64Array(4 * channels);
        this.hop = Math.round(sampleRate / 10);
        this.partLengths = new Int32Array(PARTS);
        for (let j = 0; j < PARTS; j += 1) {
            this.partLengths[j] = Math.round(((j + 1) * this.hop) / PARTS) - Math.round((j * this.hop) / PARTS);
        }
        this.parts = new Float64Array(SHORT_TERM_PARTS);
        this.counts = new Float64Array(BINS);
        this.sums = new Float64Array(BINS);
        this.truePeakMeter = truePeak ? new TruePeak(sampleRate, channels) : null;
        this.reset();
    }

    reset() {
        this.states.fill(0);
        this.parts.fill(0);
        this.counts.fill(0);
        this.sums.fill(0);
        if (this.truePeakMeter) this.truePeakMeter.reset();
        this.partIndex = 0;
        this.partCount = 0;
        this.filled = 0;
        this.energy = 0;
        this.momentarySum = 0;
        this.shortTermSum = 0;
        this.maxMomentarySum = 0;
        this.maxShortTermSum = 0;
        this.gatedSum = 0;
        this.gatedCount = 0;
        this.topBin = -1;
    }

    // Adds frames, a Float32Array for each channel, of any length. A missing channel is silence.
    push(channelArrays) {
        let frames = 0;
        for (let c = 0; c < this.channels; c += 1) {
            const input = channelArrays[c];
            if (input && input.length > frames) frames = input.length;
        }
        let offset = 0;
        while (offset < frames) {
            const want = this.partLengths[this.partCount % PARTS] - this.filled;
            const count = Math.min(want, frames - offset);
            this.energy += this.filter(channelArrays, offset, count);
            this.filled += count;
            offset += count;
            if (this.filled === this.partLengths[this.partCount % PARTS]) this.closePart();
        }
        if (this.truePeakMeter) this.truePeakMeter.process(channelArrays);
    }

    // Runs count frames from offset through the K weighting of every channel and returns the
    // weighted sum of the squares.
    filter(channelArrays, offset, count) {
        const k = this.coefficients;
        const b0 = k[0];
        const b1 = k[1];
        const b2 = k[2];
        const a1 = k[3];
        const a2 = k[4];
        const c1 = k[5];
        const c2 = k[6];
        const states = this.states;
        let total = 0;
        for (let c = 0; c < this.channels; c += 1) {
            const input = channelArrays[c];
            const length = input ? input.length : 0;
            const base = 4 * c;
            let s1 = states[base];
            let s2 = states[base + 1];
            let t1 = states[base + 2];
            let t2 = states[base + 3];
            let sum = 0;
            const end = offset + count;
            for (let i = offset; i < end; i += 1) {
                let x = i < length ? input[i] : 0;
                if (x - x !== 0) x = 0;
                const y = b0 * x + s1;
                s1 = b1 * x - a1 * y + s2;
                s2 = b2 * x - a2 * y;
                const z = y + t1;
                t1 = -2 * y - c1 * z + t2;
                t2 = y - c2 * z;
                sum += z * z;
            }
            // A decayed state becomes zero, so silence costs no subnormal arithmetic.
            if (Math.abs(s1) + Math.abs(s2) + Math.abs(t1) + Math.abs(t2) < 1e-30) {
                s1 = 0;
                s2 = 0;
                t1 = 0;
                t2 = 0;
            }
            states[base] = s1;
            states[base + 1] = s2;
            states[base + 2] = t1;
            states[base + 3] = t2;
            total += this.weights[c] * sum;
        }
        return total;
    }

    closePart() {
        const parts = this.parts;
        const e = this.energy;
        const i = this.partIndex;
        this.shortTermSum += e - parts[i];
        this.momentarySum += e - parts[(i + SHORT_TERM_PARTS - MOMENTARY_PARTS) % SHORT_TERM_PARTS];
        parts[i] = e;
        this.partIndex = i + 1 === SHORT_TERM_PARTS ? 0 : i + 1;
        if (this.partIndex === 0) {
            // The running sums start again from the parts once a turn, so rounding never builds up.
            let st = 0;
            let mo = 0;
            for (let j = 0; j < SHORT_TERM_PARTS; j += 1) {
                st += parts[j];
                if (j >= SHORT_TERM_PARTS - MOMENTARY_PARTS) mo += parts[j];
            }
            this.shortTermSum = st;
            this.momentarySum = mo;
        }
        this.partCount += 1;
        this.filled = 0;
        this.energy = 0;
        if (this.momentarySum > this.maxMomentarySum) this.maxMomentarySum = this.momentarySum;
        if (this.shortTermSum > this.maxShortTermSum) this.maxShortTermSum = this.shortTermSum;
        if (this.partCount % PARTS === 0 && this.partCount >= MOMENTARY_PARTS) this.gate(this.momentarySum / (4 * this.hop));
    }

    // Files one gating block by its loudness, behind the absolute gate.
    gate(meanSquare) {
        const loudness = lufs(meanSquare);
        if (!(loudness > ABSOLUTE_GATE)) return;
        const bin = Math.min(BINS - 1, Math.floor((loudness - ABSOLUTE_GATE) / BIN_STEP));
        this.counts[bin] += 1;
        this.sums[bin] += meanSquare;
        this.gatedSum += meanSquare;
        this.gatedCount += 1;
        if (bin > this.topBin) this.topBin = bin;
    }

    // The loudness of the last 400 ms in LUFS.
    momentary() {
        return lufs(this.momentarySum / (4 * this.hop));
    }

    // The loudness of the last 3 s in LUFS.
    shortTerm() {
        return lufs(this.shortTermSum / (30 * this.hop));
    }

    // The gated loudness of everything so far in LUFS, from the blocks over the absolute gate of
    // -70 LUFS and then over the relative gate 10 LU under their mean.
    integrated() {
        if (this.gatedCount === 0) return -Infinity;
        const relative = lufs(this.gatedSum / this.gatedCount) + RELATIVE_GATE;
        const position = (relative - ABSOLUTE_GATE) / BIN_STEP;
        // A bin counts when its centre is over the relative gate.
        const first = Math.max(0, Math.ceil(position - 0.5));
        let sum = 0;
        let count = 0;
        for (let bin = first; bin <= this.topBin; bin += 1) {
            sum += this.sums[bin];
            count += this.counts[bin];
        }
        return count > 0 ? lufs(sum / count) : -Infinity;
    }

    // The largest momentary loudness so far in LUFS.
    maxMomentary() {
        return lufs(this.maxMomentarySum / (4 * this.hop));
    }

    // The largest short-term loudness so far in LUFS.
    maxShortTerm() {
        return lufs(this.maxShortTermSum / (30 * this.hop));
    }

    // The true peak so far in dBTP.
    truePeak() {
        return this.truePeakMeter ? gainToDb(this.truePeakMeter.peak) : -Infinity;
    }
}

// A look-ahead true peak brickwall limiter. The input waits in a delay line of the look-ahead while
// a detector reads the oversampled peak of every frame from the input, with the same filter as
// TruePeak. Each frame asks for the gain that brings its peak to the ceiling. The gain holds the
// least of these over the look-ahead, rises again with the release time constant and is smoothed
// by a moving mean over the attack, so it ramps down over the attack in time for the peak and stays
// down for the eight frames on each side whose samples shape the peak between two frames. Under the
// ceiling the gain is exactly one and the signal passes unchanged apart from the delay. The
// reduction is the deepest of the last call in dB and the latency the delay in frames.
export class Limiter {
    constructor(sampleRate, channels, { ceiling = -1, lookahead = 0.005, attack = 0.001, release = 0.08 } = {}) {
        this.sampleRate = sampleRate;
        this.channels = channels;
        this.ceilingDb = ceiling;
        this.ceiling = dbToGain(ceiling);
        this.factor = oversampling(sampleRate);
        this.taps = TRUE_PEAK_TAPS;
        this.table = interpolationTable(this.factor, this.taps);
        // The delay covers the half window of the detector, the attack ramp and the half window of
        // the filter around the peak.
        let delay = Math.max(1, Math.round(lookahead * sampleRate));
        let ramp = Math.max(1, Math.round(attack * sampleRate));
        delay = Math.max(delay, this.taps - 1);
        ramp = Math.min(ramp, delay - this.taps + 2);
        this.latency = delay;
        this.ramp = ramp;
        this.size = delay + this.taps + 1;
        this.lines = [];
        for (let c = 0; c < channels; c += 1) this.lines.push(new Float64Array(2 * this.size));
        this.hold = delay + 1;
        this.dequeValues = new Float64Array(this.hold + 1);
        this.dequeTimes = new Float64Array(this.hold + 1);
        this.means = new Float64Array(ramp);
        this.releaseStep = 1 - Math.exp(-1 / (Math.max(release, 1e-6) * sampleRate));
        this.reset();
    }

    reset() {
        for (const line of this.lines) line.fill(0);
        this.write = 0;
        this.time = 0;
        this.dequeStart = 0;
        this.dequeLength = 0;
        this.means.fill(1);
        this.meanIndex = 0;
        this.meanSum = this.ramp;
        this.envelope = 1;
        this.gain = 1;
        this.reduction = 0;
    }

    // Limits inputs into outputs, arrays of Float32Array of equal length, which may be the same
    // arrays. A missing input channel is silence and a missing output channel is skipped.
    process(inputs, outputs) {
        let frames = 0;
        for (let c = 0; c < this.channels; c += 1) {
            const x = inputs[c];
            if (x && x.length > frames) frames = x.length;
        }
        const channels = this.channels;
        const taps = this.taps;
        const half = taps / 2;
        const phases = this.factor - 1;
        const table = this.table;
        const size = this.size;
        const ceiling = this.ceiling;
        const hold = this.hold;
        const capacity = this.dequeValues.length;
        const values = this.dequeValues;
        const times = this.dequeTimes;
        const means = this.means;
        const ramp = this.ramp;
        const releaseStep = this.releaseStep;
        const lines = this.lines;
        const latency = this.latency;
        let write = this.write;
        let now = this.time;
        let first = this.dequeStart;
        let length = this.dequeLength;
        let envelope = this.envelope;
        let meanIndex = this.meanIndex;
        let meanSum = this.meanSum;
        let g = this.gain;
        let lowest = 1;
        for (let i = 0; i < frames; i += 1) {
            let peak = 0;
            // The detector reads the frame half a window old and the values after it.
            const start = write + size - taps + 1;
            for (let c = 0; c < channels; c += 1) {
                const input = inputs[c];
                let x = input && i < input.length ? input[i] : 0;
                if (x - x !== 0) x = 0;
                const line = lines[c];
                line[write] = x;
                line[write + size] = x;
                const centre = line[start + half - 1];
                let a = centre < 0 ? -centre : centre;
                if (a > peak) peak = a;
                for (let ph = 0; ph < phases; ph += 1) {
                    const v = dot16(table, ph * taps, line, start);
                    a = v < 0 ? -v : v;
                    if (a > peak) peak = a;
                }
            }
            const wanted = peak > ceiling ? ceiling / peak : 1;
            // The least wanted gain of the hold window, from a deque of rising values.
            while (length > 0 && values[(first + length - 1) % capacity] >= wanted) length -= 1;
            const slot = (first + length) % capacity;
            values[slot] = wanted;
            times[slot] = now;
            length += 1;
            while (times[first] <= now - hold) {
                first = first + 1 === capacity ? 0 : first + 1;
                length -= 1;
            }
            const least = values[first];
            if (least <= envelope) envelope = least;
            else {
                envelope += (least - envelope) * releaseStep;
                if (envelope > 1 - 1e-9) envelope = 1;
            }
            meanSum += envelope - means[meanIndex];
            means[meanIndex] = envelope;
            meanIndex = meanIndex + 1 === ramp ? 0 : meanIndex + 1;
            if (meanIndex === 0) {
                let sum = 0;
                for (let j = 0; j < ramp; j += 1) sum += means[j];
                meanSum = sum;
            }
            g = meanSum / ramp;
            if (g > 1) g = 1;
            if (g < lowest) lowest = g;
            const read = write + size - latency;
            for (let c = 0; c < channels; c += 1) {
                const output = outputs[c];
                if (output && i < output.length) output[i] = lines[c][read] * g;
            }
            write = write + 1 === size ? 0 : write + 1;
            now += 1;
        }
        this.write = write;
        this.time = now;
        this.dequeStart = first;
        this.dequeLength = length;
        this.envelope = envelope;
        this.meanIndex = meanIndex;
        this.meanSum = meanSum;
        this.gain = g;
        this.reduction = lowest < 1 ? -gainToDb(lowest) : 0;
    }
}

// The time constant of a one pole that covers 99 percent of a step in the given time.
function stepFraction(dt, time) {
    return time > 0 ? 1 - Math.exp((-dt * LN_100) / time) : 1;
}

// A loudness in LUFS as the governor reads it, silence for anything that is not a number and at
// most the loudest level a signal at full scale can reach.
function level(value) {
    return typeof value === 'number' && !Number.isNaN(value) ? Math.min(value, LOUDEST) : -Infinity;
}

// The loudness governor of a team bus. It reads the momentary and short-term loudness of the bus
// before its own gain and returns the gain in dB to apply now, zero or less.
//
// Three reductions work at once and the deepest counts. The short-term reduction brings the bus to
// its short-term ceiling with the short attack, and the momentary one to its momentary ceiling with
// the momentary attack. The startle guard compares the momentary loudness with the short-term
// loudness of a startle window before, held at least at the startle floor, so a cue out of silence
// may reach the target of -23 LUFS at once. A rise of more than the startle rise clamps the bus at
// once to that reference plus the startle rise. Each reduction recovers with the release. Every
// time is the time to cover 99 percent of a step.
//
// The bus keeps an account of the time its reduction is over the sustained level in buckets of a
// sixtieth of the sustained window. Once that time reaches the sustained time within the window the
// penalty latches and lowers the bus by the penalty for the rest of the session.
export class Governor {
    constructor(sampleRate, {
        shortTermCeiling = -18,
        momentaryCeiling = -14,
        startleRise = 18,
        startleWindow = 0.1,
        startleFloor = TARGET_LUFS - 18,
        sustainedDb = 6,
        sustainedSeconds = 3,
        sustainedWithin = 60,
        penaltyDb = 6,
        shortAttack = 1,
        momentaryAttack = 0.05,
        release = 2,
    } = {}) {
        this.sampleRate = sampleRate;
        this.shortTermCeiling = shortTermCeiling;
        this.momentaryCeiling = momentaryCeiling;
        this.startleRise = startleRise;
        this.startleWindow = startleWindow;
        this.startleFloor = startleFloor;
        this.sustainedDb = sustainedDb;
        this.sustainedSeconds = sustainedSeconds;
        this.sustainedWithin = sustainedWithin;
        this.penaltyDb = penaltyDb;
        this.shortAttack = shortAttack;
        this.momentaryAttack = momentaryAttack;
        this.release = release;
        this.historyTimes = new Float64Array(512);
        this.historyValues = new Float64Array(512);
        this.buckets = new Float64Array(60);
        this.reset();
    }

    reset() {
        this.time = 0;
        this.historyStart = 0;
        this.historyLength = 0;
        this.reference = -Infinity;
        this.shortGain = 0;
        this.momentaryGain = 0;
        this.startleGain = 0;
        this.buckets.fill(0);
        this.bucket = 0;
        this.penalized = false;
        this.gain = 0;
        this.reduction = 0;
    }

    update(momentaryLufs, shortTermLufs, dt) {
        const m = level(momentaryLufs);
        const s = level(shortTermLufs);
        const step = Number.isFinite(dt) && dt > 0 ? dt : 0;
        this.time += step;
        const now = this.time;
        // The short-term loudness one startle window ago becomes the reference.
        const size = this.historyTimes.length;
        while (this.historyLength > 0 && this.historyTimes[this.historyStart] <= now - this.startleWindow) {
            this.reference = this.historyValues[this.historyStart];
            this.historyStart = (this.historyStart + 1) % size;
            this.historyLength -= 1;
        }
        if (this.historyLength === size) {
            this.reference = this.historyValues[this.historyStart];
            this.historyStart = (this.historyStart + 1) % size;
            this.historyLength -= 1;
        }
        const slot = (this.historyStart + this.historyLength) % size;
        this.historyTimes[slot] = now;
        this.historyValues[slot] = s;
        this.historyLength += 1;

        const release = stepFraction(step, this.release);
        const shortTarget = s > this.shortTermCeiling ? this.shortTermCeiling - s : 0;
        const momentaryTarget = m > this.momentaryCeiling ? this.momentaryCeiling - m : 0;
        const reference = Math.max(this.reference, this.startleFloor);
        const startleTarget = m - reference > this.startleRise ? reference + this.startleRise - m : 0;
        const attackShort = shortTarget < this.shortGain ? stepFraction(step, this.shortAttack) : release;
        this.shortGain += (shortTarget - this.shortGain) * attackShort;
        const attackMomentary = momentaryTarget < this.momentaryGain ? stepFraction(step, this.momentaryAttack) : release;
        this.momentaryGain += (momentaryTarget - this.momentaryGain) * attackMomentary;
        if (startleTarget < this.startleGain) this.startleGain = startleTarget;
        else this.startleGain += (startleTarget - this.startleGain) * release;
        const governed = Math.min(0, this.shortGain, this.momentaryGain, this.startleGain);

        if (!this.penalized) {
            const width = this.sustainedWithin / this.buckets.length;
            const bucket = Math.floor(now / width);
            const skipped = Math.min(this.buckets.length, bucket - this.bucket);
            for (let j = 1; j <= skipped; j += 1) this.buckets[(this.bucket + j) % this.buckets.length] = 0;
            this.bucket = bucket;
            if (-governed > this.sustainedDb) this.buckets[bucket % this.buckets.length] += step;
            let over = 0;
            for (let j = 0; j < this.buckets.length; j += 1) over += this.buckets[j];
            if (over >= this.sustainedSeconds) this.penalized = true;
        }
        this.gain = governed - (this.penalized ? this.penaltyDb : 0);
        this.reduction = -this.gain;
        return this.gain;
    }
}

// Reads a decoded sample, a Float32Array for each channel, for its integrated loudness, largest
// momentary and short-term loudness in LUFS, true peak in dBTP and sample peak in dBFS. A sample
// shorter than one gating block of 400 ms reads its mean loudness over its whole length as its
// integrated loudness.
export function measure(sampleRate, channelArrays) {
    const channels = channelArrays.length;
    const meter = new LoudnessMeter(sampleRate, channels);
    meter.push(channelArrays);
    meter.truePeakMeter.flush();
    let samplePeak = 0;
    let frames = 0;
    for (const input of channelArrays) {
        frames = Math.max(frames, input.length);
        for (let i = 0; i < input.length; i += 1) {
            const a = Math.abs(input[i]);
            if (a > samplePeak && Number.isFinite(a)) samplePeak = a;
        }
    }
    let integrated = meter.integrated();
    if (meter.partCount < MOMENTARY_PARTS && frames > 0) {
        const fresh = new LoudnessMeter(sampleRate, channels);
        integrated = lufs(fresh.filter(channelArrays, 0, frames) / frames);
    }
    return {
        integrated,
        maxMomentary: meter.maxMomentary(),
        maxShortTerm: meter.maxShortTerm(),
        truePeak: meter.truePeak(),
        samplePeak: gainToDb(samplePeak),
    };
}

// Turns every sample that is not finite into zero and returns how many it replaced.
export function sanitize(array) {
    let replaced = 0;
    for (let i = 0; i < array.length; i += 1) {
        const x = array[i];
        if (x - x !== 0) {
            array[i] = 0;
            replaced += 1;
        }
    }
    return replaced;
}
