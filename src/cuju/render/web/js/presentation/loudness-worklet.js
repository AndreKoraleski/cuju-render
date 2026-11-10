// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The AudioWorklet processors of the loudness safety, on the meter, governor and limiter of
// loudness.js.
//
// cuju-loudness passes its input to its output. With processorOptions.govern it applies the gain
// of a Governor, which reads a meter of the input and ramps across each quantum, so the gain moves
// smoothly from sample to sample. A second meter reads the output and every 100 ms the processor
// posts {type: 'meter', momentary, shortTerm, integrated, truePeak, reduction, penalized,
// nonFinite}, the levels in LUFS and dBTP with null for silence, the reduction in dB and the count
// of samples that were not finite since the message before. Samples that are not finite become
// zero. Input that keeps arriving with samples that are not finite, or with a DC offset over -20
// dBFS on a channel, for a second posts {type: 'runaway', reason} once, with the reason nonFinite
// or dc. The message {type: 'reset'} starts the meters, the governor and the watch again. The
// options are govern, shortTermCeiling, momentaryCeiling and channels, the channel count the
// meters start with.
//
// cuju-limiter runs the Limiter at processorOptions.ceiling in dBTP, -1 by default, with the
// optional lookahead, attack and release in seconds. Every 100 ms it posts {type: 'limiter',
// reduction, truePeak}, the largest reduction in dB since the message before and the true peak of
// its output so far in dBTP, null for silence. The message {type: 'reset'} starts it again.
//
// Both processors follow the channel count of their input and make their meters again when it
// changes. A missing input is silence. Both return true, so they live as long as their node.

import { Governor, Limiter, LoudnessMeter, TruePeak, dbToGain } from './loudness.js';

// The time between two messages to the page, in seconds.
const REPORT = 0.1;
// The time a runaway input lasts before the processor reports it, in seconds.
const RUNAWAY = 1;
// The DC offset that counts as runaway, -20 dBFS, and the time constant of its estimate.
const DC_LIMIT = 0.1;
const DC_TIME = 0.2;

function value(x) {
    return Number.isFinite(x) ? x : null;
}

// The channel arrays of the input, or one channel of silence.
function inputChannels(input, silence) {
    return input && input.length > 0 ? input : silence;
}

class LoudnessProcessor extends AudioWorkletProcessor {
    constructor(options) {
        super();
        const o = (options && options.processorOptions) || {};
        this.govern = Boolean(o.govern);
        this.governorOptions = {};
        if (Number.isFinite(o.shortTermCeiling)) this.governorOptions.shortTermCeiling = o.shortTermCeiling;
        if (Number.isFinite(o.momentaryCeiling)) this.governorOptions.momentaryCeiling = o.momentaryCeiling;
        this.governor = new Governor(sampleRate, this.governorOptions);
        this.silence = [new Float32Array(128)];
        this.configure(Math.max(1, Math.min(32, Math.floor(o.channels) || 2)));
        this.port.onmessage = (event) => {
            if (event.data && event.data.type === 'reset') this.reset();
        };
        this.reset();
    }

    configure(channels) {
        this.channels = channels;
        this.inputMeter = this.govern ? new LoudnessMeter(sampleRate, channels, { truePeak: false }) : null;
        this.outputMeter = new LoudnessMeter(sampleRate, channels);
        this.dc = new Float64Array(channels);
    }

    reset() {
        if (this.inputMeter) this.inputMeter.reset();
        this.outputMeter.reset();
        this.governor.reset();
        this.dc.fill(0);
        this.linear = 1;
        this.sinceReport = 0;
        this.nonFinite = 0;
        this.nonFiniteTime = 0;
        this.dcTime = 0;
        this.runaway = false;
    }

    process(inputs, outputs) {
        const output = outputs[0];
        if (!output || output.length === 0) return true;
        const frames = output[0].length;
        if (this.silence[0].length < frames) this.silence = [new Float32Array(frames)];
        const input = inputChannels(inputs[0], this.silence);
        const count = input.length;
        if (count !== this.channels && input !== this.silence) {
            this.configure(count);
            this.reset();
        }
        let bad = 0;
        const dcStep = 1 - Math.exp(-frames / (DC_TIME * sampleRate));
        let offset = false;
        for (let c = 0; c < output.length; c += 1) {
            const source = input[c < count ? c : count - 1];
            const target = output[c];
            const n = Math.min(frames, source.length, target.length);
            let sum = 0;
            for (let i = 0; i < n; i += 1) {
                let x = source[i];
                if (x - x !== 0) {
                    x = 0;
                    bad += 1;
                }
                target[i] = x;
                sum += x;
            }
            for (let i = n; i < target.length; i += 1) target[i] = 0;
            if (c < this.dc.length) {
                this.dc[c] += (sum / Math.max(1, n) - this.dc[c]) * dcStep;
                if (Math.abs(this.dc[c]) > DC_LIMIT) offset = true;
            }
        }
        this.watch(bad, offset, frames);
        if (this.govern) {
            this.inputMeter.push(output);
            const db = this.governor.update(this.inputMeter.momentary(), this.inputMeter.shortTerm(), frames / sampleRate);
            const next = dbToGain(db);
            const start = this.linear;
            if (next !== 1 || start !== 1) {
                const step = (next - start) / frames;
                for (let c = 0; c < output.length; c += 1) {
                    const target = output[c];
                    for (let i = 0; i < target.length; i += 1) target[i] *= start + step * (i + 1);
                }
            }
            this.linear = next;
        }
        this.outputMeter.push(output);
        this.nonFinite += bad;
        this.sinceReport += frames;
        if (this.sinceReport >= REPORT * sampleRate) {
            this.sinceReport = 0;
            const meter = this.outputMeter;
            this.port.postMessage({
                type: 'meter',
                momentary: value(meter.momentary()),
                shortTerm: value(meter.shortTerm()),
                integrated: value(meter.integrated()),
                truePeak: value(meter.truePeak()),
                reduction: this.govern ? this.governor.reduction : 0,
                penalized: this.govern ? this.governor.penalized : false,
                nonFinite: this.nonFinite,
            });
            this.nonFinite = 0;
        }
        return true;
    }

    // Counts how long the input has been runaway and reports it once a second of it has passed.
    watch(bad, offset, frames) {
        const dt = frames / sampleRate;
        this.nonFiniteTime = bad > 0 ? this.nonFiniteTime + dt : 0;
        this.dcTime = offset ? this.dcTime + dt : 0;
        const nonFinite = this.nonFiniteTime >= RUNAWAY;
        const dc = this.dcTime >= RUNAWAY;
        if ((nonFinite || dc) && !this.runaway) {
            this.runaway = true;
            this.port.postMessage({ type: 'runaway', reason: nonFinite ? 'nonFinite' : 'dc' });
        } else if (!nonFinite && !dc && this.nonFiniteTime === 0 && this.dcTime === 0) {
            this.runaway = false;
        }
    }
}

class LimiterProcessor extends AudioWorkletProcessor {
    constructor(options) {
        super();
        const o = (options && options.processorOptions) || {};
        this.settings = { ceiling: Number.isFinite(o.ceiling) ? o.ceiling : -1 };
        for (const key of ['lookahead', 'attack', 'release']) {
            if (Number.isFinite(o[key]) && o[key] > 0) this.settings[key] = o[key];
        }
        this.silence = [new Float32Array(128)];
        this.configure(Math.max(1, Math.min(32, Math.floor(o.channels) || 2)));
        this.port.onmessage = (event) => {
            if (event.data && event.data.type === 'reset') this.reset();
        };
    }

    configure(channels) {
        this.channels = channels;
        this.limiter = new Limiter(sampleRate, channels, this.settings);
        this.meter = new TruePeak(sampleRate, channels);
        this.scratch = [];
        for (let c = 0; c < channels; c += 1) this.scratch.push(new Float32Array(128));
        this.reset();
    }

    reset() {
        this.limiter.reset();
        this.meter.reset();
        this.largest = 0;
        this.sinceReport = 0;
    }

    process(inputs, outputs) {
        const output = outputs[0];
        if (!output || output.length === 0) return true;
        const frames = output[0].length;
        if (this.silence[0].length < frames) this.silence = [new Float32Array(frames)];
        const input = inputChannels(inputs[0], this.silence);
        if (input !== this.silence && input.length !== this.channels) this.configure(input.length);
        if (this.scratch[0].length < frames) {
            this.scratch = [];
            for (let c = 0; c < this.channels; c += 1) this.scratch.push(new Float32Array(frames));
        }
        // The limiter writes into its own channels, so a missing input still drains the delay.
        this.limiter.process(input, this.scratch);
        for (let c = 0; c < output.length; c += 1) {
            const from = this.scratch[c < this.channels ? c : this.channels - 1];
            const target = output[c];
            for (let i = 0; i < target.length; i += 1) target[i] = i < from.length ? from[i] : 0;
        }
        this.meter.process(this.scratch);
        if (this.limiter.reduction > this.largest) this.largest = this.limiter.reduction;
        this.sinceReport += frames;
        if (this.sinceReport >= REPORT * sampleRate) {
            this.sinceReport = 0;
            this.port.postMessage({
                type: 'limiter',
                reduction: this.largest,
                truePeak: value(20 * Math.log10(this.meter.peak)),
            });
            this.largest = 0;
        }
        return true;
    }
}

registerProcessor('cuju-loudness', LoudnessProcessor);
registerProcessor('cuju-limiter', LimiterProcessor);
