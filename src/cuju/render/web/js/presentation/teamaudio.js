// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The sound of team packages, section 9 of the contract, cues, music and sound processors, each
// team on buses of its own that the renderer governs.
//
// Each team has an effects bus and a music bus. A bus runs through the renderer's loudness
// governor, which holds its short-term loudness at most 5 LU above the programme target of
// EBU R 128, its momentary loudness under its ceiling and its onsets under the startle guard, then
// through a true peak limiter at -6 dBTP and a fixed clipper of the browser's own, so even a broken
// processor of a package stays under that level. The buses reach the viewer's channels, effects
// for the effects bus and music for the music bus, under the viewer's volume. While a package
// plays sound the master passes a true peak limiter at -1 dBTP and a clipper of the browser's own.
// Levels only lower sound, mute always wins, and nothing starts while the page is not audible.
//
// Cues are measured as they decode and scaled down so that each alone stays under the bus
// ceilings. A team holds at most its budget of voices, a new one ending the oldest. While one team
// plays a moment, the other's beds lose 6 dB and its actions 3 dB, the renderer's fairness rule.
// Music stems loop on the team's musical clock, crossfade by command, sit under the crowd's swell
// after a goal and never above the renderer's own beds. A package's AudioWorklet module runs in an
// audio context of the team's own, whose AudioWorklet scope shares nothing with the page's, so
// the module reaches none of the renderer's meters, governors and limiters. Its nodes count
// against the worklet budget, and their sound reaches the page as a stream into the team's bus,
// through the governor and the limiter like every other sound of the team.

import { SAFETY } from './commands.js';
import { dbToGain, measure } from './loudness.js';
import { hash } from './values.js';

export const WORKLET = 'js/presentation/loudness-worklet.js';
export const FREEZE = 'js/presentation/freeze-worklet.js';
// The level of a cue's peak at most, that of a team's own sounds in 0.2.0, and the integrated
// loudness of a music stem, a bed under the crowd.
export const CUE_PEAK = 0.35;
export const MUSIC_LUFS = -30;
const L = SAFETY.loudness;

// A curve for a WaveShaperNode that passes a signal unchanged up to level and holds it there.
export function clipCurve(level, size = 4097) {
    const curve = new Float32Array(size);
    for (let i = 0; i < size; i++) {
        const x = (i / (size - 1)) * 2 - 1;
        curve[i] = Math.max(-level, Math.min(level, x));
    }
    return curve;
}

// The gain that brings a measured sound under the cue rules, never above one unless the sound is
// quieter than a team's own sounds, as 0.2.0 played them.
export function cueScale(m, peak) {
    const byPeak = peak > 1e-5 ? CUE_PEAK / peak : 0;
    const byShort = Number.isFinite(m.maxShortTerm) ? dbToGain(L.teamShortTerm - m.maxShortTerm) : Infinity;
    const byMoment = Number.isFinite(m.maxMomentary) ? dbToGain(L.teamMomentary - m.maxMomentary) : Infinity;
    const byTrue = Number.isFinite(m.truePeak) ? dbToGain(L.teamTruePeak - m.truePeak) : Infinity;
    return Math.max(0, Math.min(byPeak, byShort, byMoment, byTrue));
}

// An audio context of a team's own for its processors, at the sample rate of the page's context,
// or null where the browser makes none that can stream into the page's context. A package's
// module never loads into the page's own context.
export function teamContext(ctx, Context = globalThis.AudioContext) {
    if (typeof Context !== 'function' || typeof ctx.createMediaStreamSource !== 'function') {
        return null;
    }
    let own = null;
    try {
        own = new Context({ sampleRate: ctx.sampleRate, latencyHint: 'interactive' });
    } catch {
        return null;
    }
    if (!own.audioWorklet || typeof own.createMediaStreamDestination !== 'function') {
        own.close().catch(() => {});
        return null;
    }
    return own;
}

function channels(buffer, seconds = Infinity) {
    const n = Math.min(buffer.length, Math.floor(seconds * buffer.sampleRate));
    return Array.from({ length: buffer.numberOfChannels }, (_, c) => buffer.getChannelData(c).subarray(0, n));
}

function peakOf(buffer) {
    let peak = 0;
    for (const d of channels(buffer)) {
        for (let i = 0; i < d.length; i++) {
            peak = Math.max(peak, Math.abs(d[i]));
        }
    }
    return peak;
}

function scaled(ctx, buffer, scale) {
    const out = ctx.createBuffer(buffer.numberOfChannels, buffer.length, buffer.sampleRate);
    channels(buffer).forEach((d, c) => {
        const o = out.getChannelData(c);
        for (let i = 0; i < d.length; i++) {
            o[i] = Number.isFinite(d[i]) ? d[i] * scale : 0;
        }
    });
    return out;
}

// The sound of one team, its buses, cues, voices, music and processors.
export class TeamBus {
    constructor(audio, pkg) {
        this.audio = audio;
        this.pkg = pkg;
        this.side = pkg.side;
        this.cues = new Map();
        this.voices = [];
        this.music = new Map();
        this.processors = new Map();
        this.meters = { effects: null, music: null };
        // The team's own context of its processors, and the streams from it into each bus.
        this.context = null;
        this.bridges = {};
        this.contextTime = null;
        this.contextStalled = 0;
        this.moments = 0;
        this.penalized = false;
        this.notes = [];
    }

    build(ctx, sound, worklets) {
        const make = (channel, ceiling) => {
            const input = ctx.createGain();
            const classes = { moment: ctx.createGain(), action: ctx.createGain(), bed: ctx.createGain() };
            for (const g of Object.values(classes)) {
                g.connect(input);
            }
            const clip = ctx.createWaveShaper();
            clip.curve = clipCurve(dbToGain(L.teamTruePeak));
            const target = sound.mix[channel] || sound.mix.effects;
            let tail = input;
            if (worklets) {
                const governor = new AudioWorkletNode(ctx, 'cuju-loudness', {
                    processorOptions: { govern: true, shortTermCeiling: ceiling, momentaryCeiling: L.teamMomentary, channels: 2 },
                    outputChannelCount: [2],
                });
                governor.port.onmessage = (e) => this.meter(channel, e.data);
                const limiter = new AudioWorkletNode(ctx, 'cuju-limiter', { processorOptions: { ceiling: L.teamTruePeak }, outputChannelCount: [2] });
                input.connect(governor).connect(limiter);
                tail = limiter;
            }
            tail.connect(clip).connect(target.dry);
            return { input, classes, clip, channel };
        };
        this.effects = make('effects', L.teamShortTerm);
        this.musicBus = make('music', L.integrated);
    }

    meter(channel, m) {
        if (!m) {
            return;
        }
        if (m.type === 'meter') {
            this.meters[channel] = m;
            if (m.penalized && !this.penalized) {
                this.penalized = true;
                this.audio.presentation.notice(this.pkg.manifest.name
                    ? { id: 'presentation.notice.loud', values: { team: this.pkg.manifest.name } }
                    : { id: 'presentation.notice.loudTeam' });
            }
        } else if (m.type === 'runaway') {
            this.notes.push(`the ${channel} bus ran away, ${m.reason || 'non finite'}, its processors stop`);
            this.stopProcessors();
        }
    }

    // The stream from the team's own context into the bus of channel, made on its first use.
    bridge(channel) {
        if (!this.bridges[channel]) {
            const out = this.context.createMediaStreamDestination();
            const source = this.audio.sound.ctx.createMediaStreamSource(out.stream);
            source.connect((channel === 'music' ? this.musicBus : this.effects).classes.action);
            this.bridges[channel] = { out, source };
        }
        return this.bridges[channel].out;
    }

    // The time of the team's own context that a time of the page's context names.
    contextAt(at) {
        const ctx = this.audio.sound.ctx;
        return this.context.currentTime + Math.max(0, at - ctx.currentTime);
    }

    stopProcessors() {
        for (const node of this.processors.values()) {
            try {
                node.disconnect();
            } catch {
                // A node already disconnected needs nothing more.
            }
        }
        this.processors.clear();
        this.pkg.budget.used.worklets = 0;
        for (const bridge of Object.values(this.bridges)) {
            try {
                bridge.source.disconnect();
            } catch {
                // A stream already disconnected needs nothing more.
            }
        }
        this.bridges = {};
        if (this.context) {
            this.context.close().catch(() => {});
            this.context = null;
        }
    }

    dispose() {
        this.stopProcessors();
        for (const v of this.voices) {
            try {
                v.source.stop();
            } catch {
                // A source that ended stops on its own.
            }
        }
        for (const m of this.music.values()) {
            for (const s of m.sources || []) {
                try {
                    s.stop();
                } catch {
                    // A stem that never started has nothing to stop.
                }
            }
        }
        for (const bus of [this.effects, this.musicBus]) {
            if (bus) {
                try {
                    bus.clip.disconnect();
                } catch {
                    // The context may already be gone.
                }
            }
        }
    }
}

export class TeamAudio {
    constructor(presentation) {
        this.presentation = presentation;
        this.teams = [null, null];
        this.ready = null;
        this.worklets = false;
        this.master = null;
        this.masterMeter = null;
        this.lastTime = null;
        this.stalled = 0;
    }

    get sound() {
        return this.presentation.app.sound;
    }

    // Loads the renderer's processors once into the page's audio context. Resolves to whether they
    // run, a browser without AudioWorklet keeps the fixed clippers alone.
    load(ctx) {
        if (!this.ready) {
            this.ready = (ctx.audioWorklet ? ctx.audioWorklet.addModule(WORKLET).then(() => ctx.audioWorklet.addModule(FREEZE)).then(() => true) : Promise.resolve(false))
                .catch((err) => {
                    console.warn('team sound runs without its meters', err);
                    return false;
                });
        }
        return this.ready;
    }

    // The buses of the packages on screen, once the sound is unlocked.
    async attach(packages) {
        this.dispose();
        const sound = this.sound;
        const ctx = sound && sound.ctx;
        const any = packages.some((p) => p && (Object.keys(p.manifest.audio.cues || {}).length || Object.keys(p.manifest.audio.music || {}).length || p.manifest.audio.worklet));
        if (!ctx || !any) {
            this.pending = any ? packages : null;
            return;
        }
        this.pending = null;
        this.worklets = await this.load(ctx);
        this.masterChain(ctx, sound);
        for (const pkg of packages) {
            if (!pkg) {
                continue;
            }
            const team = new TeamBus(this, pkg);
            team.build(ctx, sound, this.worklets);
            this.teams[pkg.side] = team;
            this.loadMusic(team);
            if (this.worklets && pkg.manifest.audio.worklet && !pkg.budget.past('noWorker')) {
                this.loadProcessors(team).catch((err) => pkg.errors.push(`the worklet did not load, ${err.message || err}`));
            }
        }
    }

    // The master's true peak limiter and clipper, between the renderer's compressor and the device.
    masterChain(ctx, sound) {
        if (this.master || !sound.comp) {
            return;
        }
        const clip = ctx.createWaveShaper();
        clip.curve = clipCurve(dbToGain(L.truePeak));
        let head = clip;
        if (this.worklets) {
            const limiter = new AudioWorkletNode(ctx, 'cuju-limiter', { processorOptions: { ceiling: L.truePeak }, outputChannelCount: [2] });
            limiter.port.onmessage = (e) => {
                this.limiter = e.data;
            };
            limiter.connect(clip);
            head = limiter;
            const meter = new AudioWorkletNode(ctx, 'cuju-loudness', { processorOptions: { govern: false, channels: 2 }, outputChannelCount: [2] });
            meter.port.onmessage = (e) => {
                if (e.data && e.data.type === 'meter') {
                    this.masterMeter = e.data;
                }
            };
            const sink = ctx.createGain();
            sink.gain.value = 0;
            clip.connect(meter).connect(sink).connect(ctx.destination);
        }
        sound.comp.disconnect();
        sound.comp.connect(head);
        clip.connect(ctx.destination);
        this.master = { head, clip };
    }

    // Loads a package's module into a context of the team's own and makes its processors there,
    // each streaming into the team's effects or music bus.
    async loadProcessors(team, Context = globalThis.AudioContext) {
        const m = team.pkg.manifest.audio;
        const own = teamContext(this.sound.ctx, Context);
        if (!own) {
            throw new Error('the browser makes no audio context of the team’s own');
        }
        team.context = own;
        await own.audioWorklet.addModule(this.presentation.fileUrl(team.pkg, m.worklet));
        if (team.context !== own) {
            return;
        }
        for (const [name, spec] of Object.entries(m.processors || {})) {
            if (!team.pkg.budget.take({ worklets: 1 })) {
                team.pkg.errors.push(`processor ${name} is past the team's budget`);
                continue;
            }
            try {
                const node = new AudioWorkletNode(own, spec.processor, { parameterData: spec.parameters || {}, processorOptions: spec.options || {}, outputChannelCount: [2] });
                node.onprocessorerror = () => {
                    team.notes.push(`processor ${name} failed and stops`);
                    node.disconnect();
                    team.processors.delete(name);
                };
                node.connect(team.bridge(spec.bus === 'music' ? 'music' : 'effects'));
                team.processors.set(name, node);
            } catch (err) {
                team.pkg.errors.push(`processor ${name} not made, ${err.message || err}`);
                team.pkg.budget.give({ worklets: 1 });
            }
        }
    }

    async decode(team, file) {
        const ctx = this.sound.ctx;
        const data = await this.presentation.fetchFile(team.pkg, file);
        const decoded = await ctx.decodeAudioData(data);
        const bytes = decoded.length * decoded.numberOfChannels * 4;
        if (!team.pkg.budget.take({ audioBytes: bytes })) {
            throw new Error('past the team’s budget of decoded sound');
        }
        return decoded;
    }

    // A cue's buffer, decoded once and scaled under the cue rules.
    cue(team, file) {
        let entry = team.cues.get(file);
        if (!entry) {
            entry = { buffer: null, promise: null };
            team.cues.set(file, entry);
            entry.promise = this.decode(team, file).then((decoded) => {
                const m = measure(decoded.sampleRate, channels(decoded, 30));
                entry.measure = m;
                entry.scale = cueScale(m, peakOf(decoded));
                entry.buffer = scaled(this.sound.ctx, decoded, entry.scale);
                return entry.buffer;
            }).catch((err) => {
                team.pkg.errors.push(`cue ${file} not played, ${err.message || err}`);
                return null;
            });
        }
        return entry;
    }

    // The audio time a command's at names, the contact of its event or an offset of it.
    when(c, event) {
        const ctx = this.sound.ctx;
        const p = this.presentation;
        const now = ctx.currentTime;
        if (c.at && c.at.mode === 'audio') {
            return Math.max(now, c.at.time);
        }
        const tl = p.app.timeline;
        const speed = tl && tl.playing && tl.direction > 0 ? Math.max(0.05, tl.speed) : 1;
        const base = event ? (c.at && c.at.mode === 'contact' && event.data && event.data.contactT != null ? event.data.contactT : event.t) : p.clocks.sim;
        const offset = (c.at && c.at.offset) || 0;
        const lead = (base + offset - p.clocks.sim) / speed;
        return now + Math.max(0, Math.min(3, lead));
    }

    // A command of kind audio, from a reflex or a worker. Returns whether it was taken.
    command(pkg, c, event = null) {
        const sound = this.sound;
        if (!sound || !sound.ctx) {
            return false;
        }
        const team = this.teams[pkg.side];
        if (!team) {
            if (this.pending) {
                this.attach(this.pending);
            }
            return false;
        }
        if (c.op === 'play') {
            return this.play(team, c, event);
        }
        if (c.op === 'music' || (c.op === 'stop' && pkg.manifest.audio.music && pkg.manifest.audio.music[c.id])) {
            return this.musicCommand(team, c, event);
        }
        if (c.op === 'param') {
            const node = team.processors.get(c.node);
            const param = node && c.param ? node.parameters.get(c.param) : null;
            if (param) {
                param.setTargetAtTime(c.value, team.contextAt(this.when(c, event)), 0.02);
            }
            return !!param;
        }
        if (c.op === 'stop') {
            const ctx = sound.ctx;
            for (const v of team.voices.filter((x) => x.id === c.id)) {
                v.gain.gain.setTargetAtTime(0, ctx.currentTime, 0.05);
                v.source.stop(ctx.currentTime + 0.3);
            }
            return true;
        }
        return false;
    }

    play(team, c, event) {
        const sound = this.sound;
        if (!sound.audible) {
            return false;
        }
        const cues = team.pkg.manifest.audio.cues || {};
        const files = [].concat(cues[c.cue] || []);
        if (!files.length) {
            return false;
        }
        const file = files[(hash(`${c.event || (event && event.id) || ''}:${c.cue}`) >>> 0) % files.length];
        const entry = this.cue(team, file);
        const start = (buffer) => {
            if (buffer && sound.audible) {
                this.voice(team, buffer, c, event);
            }
        };
        if (entry.buffer) {
            start(entry.buffer);
        } else {
            entry.promise.then(start);
        }
        return true;
    }

    voice(team, buffer, c, event) {
        const sound = this.sound;
        const ctx = sound.ctx;
        const limit = team.pkg.budget.limits.voices || 24;
        while (team.voices.length >= limit) {
            const old = team.voices.shift();
            old.gain.gain.setTargetAtTime(0, ctx.currentTime, 0.02);
            try {
                old.source.stop(ctx.currentTime + 0.1);
            } catch {
                // A source that ended stops on its own.
            }
        }
        const at = this.when(c, event);
        sound.voices.run(ctx, () => {
            const source = ctx.createBufferSource();
            source.buffer = buffer;
            source.playbackRate.value = c.rate || 1;
            const gain = ctx.createGain();
            gain.gain.value = Math.max(0, Math.min(1, c.gain ?? 1));
            source.connect(gain);
            const tapped = sound.voices.tap(ctx, gain, source, at - ctx.currentTime);
            const bus = c.bus === 'music' ? team.musicBus : team.effects;
            const klass = c.class === 'moment' || c.class === 'bed' ? c.class : 'action';
            const position = this.presentation.audioPosition(team.pkg, c, event);
            if (position) {
                tapped.connect(sound.panner(position)).connect(bus.classes[klass]);
            } else {
                tapped.connect(bus.classes[klass]);
            }
            source.start(at);
            const voice = { id: c.id, source, gain, klass, end: at + buffer.duration / (c.rate || 1) };
            team.voices.push(voice);
            source.onended = () => {
                team.voices = team.voices.filter((v) => v !== voice);
            };
        }, buffer.duration + 0.2);
        return true;
    }

    // Decodes a team's music stems, each scaled to a bed's loudness, while the page waits.
    loadMusic(team) {
        for (const [name, spec] of Object.entries(team.pkg.manifest.audio.music || {})) {
            const entry = { spec, buffers: null, sources: null, gains: null, started: null };
            team.music.set(name, entry);
            entry.promise = Promise.all(spec.stems.map((file) => this.decode(team, file).then((decoded) => {
                const m = measure(decoded.sampleRate, channels(decoded, 30));
                const scale = Number.isFinite(m.integrated) ? Math.min(1, dbToGain(MUSIC_LUFS - m.integrated)) : 0;
                return scaled(this.sound.ctx, decoded, scale);
            }))).then((buffers) => {
                entry.buffers = buffers;
            }).catch((err) => team.pkg.errors.push(`music ${name} not played, ${err.message || err}`));
        }
    }

    musicCommand(team, c, event) {
        const entry = team.music.get(c.id);
        const ctx = this.sound.ctx;
        if (!entry) {
            return false;
        }
        const apply = () => {
            if (!entry.buffers) {
                return;
            }
            const spec = entry.spec;
            const beat = 60 / spec.bpm;
            const bar = beat * spec.beats;
            if (!entry.sources && c.op === 'music') {
                if (!this.sound.audible) {
                    return;
                }
                const t0 = ctx.currentTime + 0.05;
                entry.started = t0;
                entry.gains = entry.buffers.map(() => ctx.createGain());
                entry.sources = entry.buffers.map((b, i) => {
                    const s = ctx.createBufferSource();
                    s.buffer = b;
                    s.loop = true;
                    entry.gains[i].gain.value = 0;
                    s.connect(entry.gains[i]).connect(team.musicBus.classes.bed);
                    s.start(t0);
                    return s;
                });
            }
            if (!entry.sources) {
                return;
            }
            let at = ctx.currentTime;
            const q = c.at && c.at.quantize;
            if (q) {
                const step = q === 'bar' ? bar : beat;
                at = entry.started + Math.ceil((at - entry.started) / step) * step;
            }
            const fade = Math.max(0.05, c.fade ?? 1);
            const level = Math.max(0, Math.min(1, (c.gain ?? 1) * (spec.gain ?? 1)));
            entry.gains.forEach((g, i) => {
                const on = c.op === 'music' && (c.stems === 'all' || !Array.isArray(c.stems) || c.stems.includes(i));
                g.gain.setTargetAtTime(on ? level : 0, at, fade / 3);
            });
            if (c.op === 'stop') {
                const sources = entry.sources;
                entry.sources = null;
                for (const s of sources) {
                    s.stop(at + fade * 2);
                }
            }
        };
        if (entry.buffers) {
            apply();
        } else {
            entry.promise.then(apply);
        }
        return true;
    }

    // Moves the sound on by one drawing, the fairness rule, the music under the crowd's swell, the
    // processors' parameters from behaviours, and the watchdog of the audio thread.
    update(entities) {
        const sound = this.sound;
        const ctx = sound && sound.ctx;
        if (!ctx) {
            return;
        }
        if (this.pending && !this.attaching) {
            this.attaching = true;
            this.attach(this.pending).finally(() => {
                this.attaching = false;
            });
        }
        const now = ctx.currentTime;
        const moments = this.teams.map((t) => (t ? t.voices.filter((v) => v.klass === 'moment' && v.end > now).length : 0));
        const swell = Math.min(1, (this.presentation.app.goalBoost || 0) * 1.6);
        this.teams.forEach((team, side) => {
            if (!team) {
                return;
            }
            const other = moments[1 - side] > 0;
            const both = other && moments[side] > 0;
            for (const bus of [team.effects, team.musicBus]) {
                bus.classes.bed.gain.setTargetAtTime(dbToGain(other ? -6 : 0), now, 0.1);
                bus.classes.action.gain.setTargetAtTime(dbToGain(both ? -3 : other ? -3 : 0), now, 0.1);
                bus.classes.moment.gain.setTargetAtTime(dbToGain(both ? -3 : 0), now, 0.1);
            }
            // Music sits under the crowd's swell after a goal and under the renderer's own beds.
            team.musicBus.input.gain.setTargetAtTime(dbToGain(-9 * swell), now, 0.2);
        });
        for (const entity of entities) {
            const team = this.teams[entity.side];
            if (!team) {
                continue;
            }
            for (const a of entity.outputs.audio || []) {
                const node = team.processors.get(a.processor);
                const param = node ? node.parameters.get(a.param) : null;
                if (param) {
                    param.setTargetAtTime(param.defaultValue + (a.value - param.defaultValue) * a.weight, team.context.currentTime, 0.03);
                }
            }
        }
        // A context that runs but whose time stands still for a second stops the processors.
        if (ctx.state === 'running' && this.lastTime === now) {
            this.stalled += 1;
            if (this.stalled > 60) {
                for (const t of this.teams) {
                    if (t && t.processors.size) {
                        t.notes.push('the audio thread stalled, the processors stop');
                        t.stopProcessors();
                    }
                }
            }
        } else {
            this.stalled = 0;
        }
        this.lastTime = now;
        for (const team of this.teams) {
            if (team && team.context) {
                this.follow(ctx, team);
            }
        }
    }

    // A team's own context runs while the page's runs and rests while it rests, and one whose
    // time stands still for a second while it runs stops its processors.
    follow(ctx, team) {
        const own = team.context;
        const want = ctx.state === 'running' ? 'running' : 'suspended';
        if (own.state !== want && own.state !== 'closed' && team.wanted !== want) {
            team.wanted = want;
            (want === 'running' ? own.resume() : own.suspend()).catch(() => {}).finally(() => {
                team.wanted = null;
            });
        }
        if (own.state === 'running' && team.contextTime === own.currentTime) {
            team.contextStalled += 1;
            if (team.contextStalled > 60 && team.processors.size) {
                team.notes.push('the audio thread of the team stalled, the processors stop');
                team.stopProcessors();
                return;
            }
        } else {
            team.contextStalled = 0;
        }
        team.contextTime = own.currentTime;
    }

    // Sends an event to the processors of its team, which may sound it.
    event(pkg, event) {
        const team = this.teams[pkg.side];
        if (!team || !team.processors.size || event.team !== pkg.side) {
            return;
        }
        for (const node of team.processors.values()) {
            node.port.postMessage({ type: 'event', kind: event.kind, phase: event.phase, t: event.t, lead: event.lead, player: event.player ?? null });
        }
    }

    // A seek ends every voice of the teams, the music plays on.
    stop() {
        const ctx = this.sound && this.sound.ctx;
        for (const t of this.teams) {
            if (t && ctx) {
                for (const v of t.voices) {
                    v.gain.gain.setTargetAtTime(0, ctx.currentTime, 0.03);
                }
                t.voices = [];
            }
        }
    }

    snapshot() {
        return {
            worklets: this.worklets, master: this.masterMeter, limiter: this.limiter || null, masterChain: !!this.master,
            teams: this.teams.map((t) => (t ? {
                voices: t.voices.length, cues: t.cues.size, music: [...t.music.keys()].filter((k) => t.music.get(k).sources),
                processors: [...t.processors.keys()], ownContext: !!t.context, meters: t.meters, penalized: t.penalized, notes: t.notes.slice(-8),
                scales: [...t.cues.entries()].map(([file, e]) => ({ file, scale: e.scale ?? null, maxShortTerm: e.measure ? e.measure.maxShortTerm : null })),
            } : null)),
        };
    }

    dispose() {
        for (const t of this.teams) {
            if (t) {
                t.dispose();
            }
        }
        this.teams = [null, null];
    }
}
