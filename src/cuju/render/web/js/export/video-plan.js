// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The plan of a video export that the page draws and encodes itself, with nothing beyond the
// browser. It holds the parts that need no browser, so a test runs them on Node, the frames of a
// range and the steps before them, the settings of the page that draws them, the codecs to try
// and their bit rates, and the name of the file. The frames, the warm-up and the settings follow
// src/cuju/render/_export/video.py, which draws the same picture with Chrome and ffmpeg for the
// command cuju render video and for browsers without a video encoder.

// The page plays this long before the first frame, so the camera and graphics have settled, as
// WARMUP of video.py.
export const WARMUP = 1;
// The page settles this long in real time at the first frame of the warm-up, its players rebuilt
// in their kits and the camera in place.
export const SETTLE_MS = 1000;
// The largest file of an export, in bytes, as DEFAULT_MAX_MEGABYTES of video.py.
export const MAX_BYTES = 2048 * 1024 * 1024;
// A key frame starts every this many seconds, so a player seeks the file quickly.
export const KEY_SECONDS = 2;

// Each quality names the drawing quality of the page, as QUALITIES of video.py, and the bits that
// the encoder spends on each pixel of each frame.
export const QUALITY_DRAWING = Object.freeze({ draft: 'medium', standard: 'high', high: 'high' });
export const QUALITY_BITS = Object.freeze({ draft: 0.05, standard: 0.1, high: 0.2 });
// The bit rate stays within these bounds, in bits a second.
export const MIN_BITRATE = 250e3;
export const MAX_BITRATE = 60e6;

// The cameras that the stored setting of the page remembers, the others follow by the rig alone.
const REMEMBERED = ['broadcast', 'tactical', 'goal'];

// The frames of a range from start to end seconds at fps frames a second, one per frame interval
// and at least one, as frame_count of video.py.
export function frameCount(start, end, fps) {
    return Math.max(1, Math.round((end - start) * fps));
}

// The plan of an export, the frames to encode, the frames of the warm-up before them, the second
// the warm-up starts from and the milliseconds of one step, as export of video.py takes them.
export function exportPlan(start, end, fps) {
    const warm = Math.min(start, WARMUP);
    const warmFrames = Math.round(warm * fps);
    return {
        frames: frameCount(start, end, fps),
        warmFrames,
        warmFrom: start - warmFrames / fps,
        step: 1000 / fps,
        keyEvery: Math.max(1, Math.round(KEY_SECONDS * fps)),
    };
}

// The time of frame index in microseconds, as the encoder takes it, and the length of one frame.
export function frameTime(index, fps) {
    return Math.round((index * 1e6) / fps);
}

export function frameDuration(index, fps) {
    return frameTime(index + 1, fps) - frameTime(index, fps);
}

// The stored settings of the page that draws an export, as preload_script of video.py writes
// them. Sound stays muted, the pointer free and the page in its broadcast mode, without the team
// sheets, the presentation of restarts, celebrations, replays and the show after the match, so the
// video follows the match clock, unless broadcast keeps them as Watch presents the match. The
// labels and the box of a recording's annotations show only when asked for, and the offer of the
// 2D view never shows.
export function exportSettings(options) {
    const annotations = options.annotations === true;
    const broadcast = options.broadcast === true;
    const settings = {
        muted: true,
        volume: 0,
        music: false,
        quality: QUALITY_DRAWING[options.quality] || 'high',
        theme: 'dark',
        tvMode: true,
        idleReturn: false,
        pointerLock: false,
        camera: REMEMBERED.includes(options.camera) ? options.camera : 'broadcast',
        lineups: broadcast,
        celebrations: broadcast,
        replays: broadcast,
        decisionReplays: broadcast,
        transitions: broadcast,
        podium: false,
        motion: 'full',
        tips: { off: true },
        view2dDeclined: true,
        touchControls: 'off',
        annotations: { players: annotations, actions: annotations, text: annotations },
    };
    const field = {};
    if (typeof options.arena === 'string') {
        field.arena = options.arena;
    }
    if (typeof options.time === 'number' && Number.isFinite(options.time)) {
        field.time = Math.min(24, Math.max(0, options.time));
    }
    if (Object.keys(field).length) {
        settings.field = field;
    }
    return settings;
}

// The address of the page that draws an export, relative to the page, from the body of an export
// request, the scale of its layout, the language and the recording. The page reads the settings
// from the parameter export, as video-boot.js does.
export function exportAddress(body, { ratio, lang, match }) {
    const params = new URLSearchParams();
    params.set('capture', '1');
    params.set('export', JSON.stringify(exportSettings(body)));
    params.set('safe', String(body.safe ?? 'auto'));
    params.set('ratio', String(Math.round(ratio * 1e4) / 1e4));
    if (lang) {
        params.set('lang', lang);
    }
    return `./?${params.toString()}#match=${encodeURIComponent(match)}`;
}

// The bit rate of a quality at a size and frame rate, in bits a second.
export function bitrate(quality, width, height, fps) {
    const bits = QUALITY_BITS[quality] || QUALITY_BITS.standard;
    return Math.round(Math.min(MAX_BITRATE, Math.max(MIN_BITRATE, width * height * fps * bits)));
}

// The levels of H.264, each with its largest rate of macroblocks a second, its largest frame in
// macroblocks and its largest bit rate of the High profile in bits a second.
const AVC_LEVELS = [
    [30, 40500, 1620, 12.5e6],
    [31, 108000, 3600, 17.5e6],
    [32, 216000, 5120, 25e6],
    [40, 245760, 8192, 25e6],
    [41, 245760, 8192, 62.5e6],
    [42, 522240, 8704, 62.5e6],
    [50, 589824, 22080, 168.75e6],
    [51, 983040, 36864, 300e6],
    [52, 2073600, 36864, 300e6],
];

// The lowest level of H.264 that holds a size, a frame rate and a bit rate.
export function avcLevel(width, height, fps, rate = 0) {
    const across = Math.ceil(width / 16);
    const down = Math.ceil(height / 16);
    const frame = across * down;
    for (const [level, perSecond, largest, bits] of AVC_LEVELS) {
        const side = Math.sqrt(largest * 8);
        if (frame <= largest && frame * fps <= perSecond && across <= side && down <= side && rate <= bits) {
            return level;
        }
    }
    return 52;
}

// The level of VP9 that holds a size and a frame rate, by the samples a second of each level.
export function vp9Level(width, height, fps) {
    const samples = width * height * fps;
    const levels = [[31, 36864000], [40, 83558400], [41, 160432128], [50, 311951360], [51, 588251136]];
    const found = levels.find(([, most]) => samples <= most);
    return found ? found[0] : 52;
}

const hex = (value) => value.toString(16).padStart(2, '0').toUpperCase();

// The encoders to try, best first. MP4 with H.264 plays everywhere, in the High, Main and
// Constrained Baseline profiles, and WebM with VP9 or VP8 follows for a browser without H.264.
// A container, mp4 or webm, keeps the encoders of that container alone.
export function encoderCandidates(width, height, fps, quality, container = null) {
    const rate = bitrate(quality, width, height, fps);
    const level = hex(avcLevel(width, height, fps, rate));
    const base = { width, height, bitrate: rate, framerate: fps, bitrateMode: 'variable', latencyMode: 'quality' };
    const vp9 = String(vp9Level(width, height, fps)).padStart(2, '0');
    const all = [
        { container: 'mp4', config: { ...base, codec: `avc1.6400${level}`, avc: { format: 'avc' } } },
        { container: 'mp4', config: { ...base, codec: `avc1.4D00${level}`, avc: { format: 'avc' } } },
        { container: 'mp4', config: { ...base, codec: `avc1.42E0${level}`, avc: { format: 'avc' } } },
        { container: 'webm', config: { ...base, codec: `vp09.00.${vp9}.08` } },
        { container: 'webm', config: { ...base, codec: 'vp8' } },
    ];
    return container ? all.filter((c) => c.container === container) : all;
}

// The first encoder that the browser supports, asked of isSupported for each candidate, or null.
export async function chooseEncoder(candidates, isSupported) {
    for (const candidate of candidates) {
        try {
            const answer = await isSupported(candidate.config);
            if (answer && answer.supported) {
                return candidate;
            }
        } catch {
            // A codec that the browser cannot name counts as missing.
        }
    }
    return null;
}

// The name that a downloaded video suggests, from the title and the range, as _filename of
// video_jobs.py, with the extension of its container.
export function videoFileName(title, start, end, container = 'mp4') {
    const stem = String(title ?? '').replace(/[^A-Za-z0-9 _.,-]+/g, '').replace(/^[ .]+|[ .]+$/g, '') || 'match';
    const moment = (value) => {
        const whole = Math.trunc(value);
        return `${Math.trunc(whole / 60)}m${String(whole % 60).padStart(2, '0')}`;
    };
    return `${stem.slice(0, 60)} ${moment(start)}-${moment(end)}.${container === 'webm' ? 'webm' : 'mp4'}`;
}
