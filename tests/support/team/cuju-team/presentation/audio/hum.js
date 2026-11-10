// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The sound processor of the test package, a single file AudioWorklet module. It hums a quiet
// tone whose level the parameter level gives, and a short tick for each of its team's touches,
// which the renderer sends to its port.

class TestHum extends AudioWorkletProcessor {
    static get parameterDescriptors() {
        return [{ name: 'level', defaultValue: 0, minValue: 0, maxValue: 1 }];
    }

    constructor() {
        super();
        this.phase = 0;
        this.tick = 0;
        this.port.onmessage = (e) => {
            if (e.data && e.data.type === 'event' && e.data.kind === 'touch') {
                this.tick = 0.05 * sampleRate;
            }
        };
    }

    process(inputs, outputs, parameters) {
        const out = outputs[0];
        const level = parameters.level;
        for (let i = 0; i < out[0].length; i++) {
            this.phase += (2 * Math.PI * 110) / sampleRate;
            const tick = this.tick > 0 ? Math.sin(this.phase * 9) * (this.tick-- / (0.05 * sampleRate)) : 0;
            const v = 0.02 * (level.length > 1 ? level[i] : level[0]) * Math.sin(this.phase) + 0.05 * tick;
            for (const channel of out) {
                channel[i] = v;
            }
        }
        return true;
    }
}

registerProcessor('test-hum', TestHum);
