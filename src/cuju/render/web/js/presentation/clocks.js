// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The four clocks of the presentation contract, section 3.
//
// sim is the match time on screen in seconds, with the step and the fraction of the way to the
// next one. It follows the timeline, so it stops on a pause, runs at the playback speed, runs
// backwards in reverse and jumps on a seek. ceremony runs while a lineup, a celebration, a
// replay, a decision or a step of the show after the match plays, in real time whatever the
// playback speed, holds while the viewer pauses a show and starts again from zero on a seek.
// cosmetic runs in real time while the page draws, a pause included, so idle motion goes on.
// audio is the time of the page's sound device. Each step of ceremony and cosmetic is held to at
// most MAX_STEP, so a tab back from the background resumes without a jump, and while the page is
// captured the capture's fixed step drives them, so a capture draws the same frames every time.

export const MAX_STEP = 0.05;

export class Clocks {
    constructor() {
        this.sim = 0;
        this.step = 0;
        this.fraction = 0;
        this.ceremony = 0;
        this.cosmetic = 0;
        this.audio = 0;
        this.simStep = 0;
        this.ceremonyStep = 0;
        this.cosmeticStep = 0;
        this.started = false;
    }

    // Advances the clocks by one drawing. dt is the real time since the last drawing, t the
    // timeline's index on screen and sps its steps per second, ceremony whether a ceremony plays
    // and held whether the viewer paused it, audio the sound device's time. Returns this.
    advance({ dt = 0, t = null, sps = 10, ceremony = false, held = false, audio = null } = {}) {
        const step = Math.min(MAX_STEP, Math.max(0, Number(dt) || 0));
        this.cosmeticStep = step;
        this.cosmetic += step;
        this.ceremonyStep = ceremony && !held ? step : 0;
        this.ceremony += this.ceremonyStep;
        if (Number.isFinite(t)) {
            const sim = t / (sps || 10);
            this.simStep = this.started ? sim - this.sim : 0;
            this.sim = sim;
            this.step = Math.floor(t);
            this.fraction = t - this.step;
        } else {
            this.simStep = 0;
        }
        if (Number.isFinite(audio)) {
            this.audio = audio;
        }
        this.started = true;
        return this;
    }

    // A seek starts the ceremony clock again.
    seek() {
        this.ceremony = 0;
        this.ceremonyStep = 0;
    }

    // The clocks as a Frame carries them.
    snapshot() {
        return { sim: this.sim, step: this.step, fraction: this.fraction, ceremony: this.ceremony, cosmetic: this.cosmetic, audio: this.audio };
    }

    // The time of a clock by name, cosmetic for an unknown one.
    read(name) {
        return name === 'sim' ? this.sim : name === 'ceremony' ? this.ceremony : this.cosmetic;
    }
}
