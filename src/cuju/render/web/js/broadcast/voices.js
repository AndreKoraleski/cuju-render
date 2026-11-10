// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The one-shot sounds of the page, a whistle, a goal's roar, a team's own sound, each gathered
// into a voice whose nodes can fade out together. A seek, a restart or another match fades
// every voice at once, so nothing of the match left behind keeps sounding, and at most
// MAX_VOICES voices sound together, a new one ending the oldest, so a burst of events cannot
// pile up. The beds of the arenas, the crowd's murmur, the weather and the ambience are no
// voices and play on.

export const MAX_VOICES = 12;
// How long a voice is taken to sound when nothing tells, in seconds.
const DEFAULT_LENGTH = 3;
// The fades of a voice ended early, in seconds, quick for a stolen voice and for a seek.
export const STEAL_FADE = 0.05;
export const STOP_FADE = 0.08;

export class Voices {
    constructor(max = MAX_VOICES) {
        this.max = max;
        // The voices that may still sound, oldest first.
        this.list = [];
        // The voice that gathers the nodes made now, or null.
        this.current = null;
        // Counts the stops of every voice, a voice made before the last one never sounds again.
        this.epoch = 0;
    }

    // Runs fn with every node it routes gathered into one voice, and returns what fn returns.
    // A call inside another joins the voice that runs. Length is how long the voice is taken to
    // sound, in seconds, and buffers it plays lengthen it as they need.
    run(ctx, fn, length = DEFAULT_LENGTH) {
        if (this.current || !ctx) {
            return fn();
        }
        this.current = {
            gains: [], sources: [], end: 0, length, listed: false, stopped: false, epoch: this.epoch,
        };
        try {
            return fn();
        } finally {
            this.current = null;
        }
    }

    // Wraps fn, run later by a timer, so the nodes it makes join the voice that runs now, and
    // so it does nothing once that voice has ended early. Without a voice fn runs as it is.
    later(fn) {
        const voice = this.current;
        if (!voice) {
            return fn;
        }
        return (...args) => {
            if (voice.stopped || voice.epoch !== this.epoch) {
                return undefined;
            }
            const outer = this.current;
            this.current = voice;
            try {
                return fn(...args);
            } finally {
                this.current = outer;
            }
        };
    }

    // Puts a gain of the voice that gathers after node and returns that gain, which the caller
    // connects onwards in place of node. Without a voice node comes back as it is. A source
    // given is stopped when the voice ends early, and its buffer lengthens the voice.
    tap(ctx, node, source = null, when = 0) {
        const voice = this.current;
        if (!voice || !ctx || voice.stopped) {
            return node;
        }
        const now = ctx.currentTime;
        if (!voice.listed) {
            this.open(ctx, voice, now);
        }
        const gain = ctx.createGain();
        gain.gain.value = 1;
        node.connect(gain);
        voice.gains.push(gain);
        if (source) {
            voice.sources.push(source);
            const buffer = source.buffer;
            const rate = (source.playbackRate && source.playbackRate.value) || 1;
            if (buffer && Number.isFinite(buffer.duration)) {
                voice.end = Math.max(voice.end, now + when + buffer.duration / rate + 0.1);
            }
        }
        return gain;
    }

    // Lists a voice that starts sounding, or sounds again from a timer, after the voices that
    // ended and the oldest beyond the limit leave the list.
    open(ctx, voice, now) {
        this.list = this.list.filter((v) => {
            const sounding = !v.stopped && v.end > now;
            v.listed = sounding;
            return sounding;
        });
        while (this.list.length >= this.max) {
            this.cut(ctx, this.list.shift(), STEAL_FADE);
        }
        voice.listed = true;
        voice.end = Math.max(voice.end, now + voice.length);
        this.list.push(voice);
    }

    // Fades a voice out over fade seconds, stops its sources and lets its nodes go.
    cut(ctx, voice, fade) {
        voice.stopped = true;
        const t = ctx.currentTime;
        for (const g of voice.gains) {
            g.gain.cancelScheduledValues(t);
            g.gain.setValueAtTime(g.gain.value, t);
            g.gain.linearRampToValueAtTime(0, t + fade);
        }
        for (const s of voice.sources) {
            try {
                s.stop(t + fade + 0.02);
            } catch {
                // A source that already ended has nothing to stop.
            }
        }
        const gains = voice.gains;
        voice.gains = [];
        voice.sources = [];
        setTimeout(() => {
            for (const g of gains) {
                g.disconnect();
            }
        }, (fade + 0.1) * 1000);
    }

    // Fades every voice out, for a seek, a restart or another match.
    stopAll(ctx, fade = STOP_FADE) {
        const list = this.list;
        this.list = [];
        this.epoch++;
        if (this.current) {
            this.current.stopped = true;
        }
        for (const voice of list) {
            this.cut(ctx, voice, fade);
        }
    }

    // How many voices may still sound at time now.
    count(now) {
        return this.list.filter((v) => !v.stopped && v.end > now).length;
    }
}
