// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// A small writer of WebM files of one video track, VP9 or VP8, for the video export of a browser
// without H.264. It writes the EBML header and a segment of Matroska, with a seek head, the
// segment's information and its track, the frames in clusters that each start at a key frame, and
// cues that point at the clusters, so a player seeks the file. The clusters gather into blobs as
// they close, so a browser may keep a long video on its disk rather than in memory.

const ID = {
    ebml: 0x1a45dfa3, ebmlVersion: 0x4286, ebmlReadVersion: 0x42f7, maxIdLength: 0x42f2, maxSizeLength: 0x42f3,
    docType: 0x4282, docTypeVersion: 0x4287, docTypeReadVersion: 0x4285,
    segment: 0x18538067, seekHead: 0x114d9b74, seek: 0x4dbb, seekId: 0x53ab, seekPosition: 0x53ac,
    info: 0x1549a966, timestampScale: 0x2ad7b1, duration: 0x4489, muxingApp: 0x4d80, writingApp: 0x5741,
    tracks: 0x1654ae6b, trackEntry: 0xae, trackNumber: 0xd7, trackUid: 0x73c5, trackType: 0x83,
    flagLacing: 0x9c, codecId: 0x86, codecPrivate: 0x63a2, defaultDuration: 0x23e383, video: 0xe0,
    pixelWidth: 0xb0, pixelHeight: 0xba,
    cluster: 0x1f43b675, timestamp: 0xe7, simpleBlock: 0xa3,
    cues: 0x1c53bb6b, cuePoint: 0xbb, cueTime: 0xb3, cueTrackPositions: 0xb7, cueTrack: 0xf7,
    cueClusterPosition: 0xf1,
};

// The codec names of Matroska for the codecs of the browser's encoder.
export const WEBM_CODECS = Object.freeze({ vp8: 'V_VP8', vp09: 'V_VP9', av01: 'V_AV1' });

// The bytes of an element's identifier, which carries its own length.
function idBytes(id) {
    const out = [];
    for (let value = id; value > 0; value = Math.floor(value / 256)) {
        out.unshift(value & 255);
    }
    return Uint8Array.from(out);
}

// A size as a variable length integer, of the given length or the shortest that holds it.
export function sizeBytes(size, length = 0) {
    let n = length;
    if (!n) {
        n = 1;
        while (n < 8 && size >= 2 ** (7 * n) - 1) {
            n++;
        }
    }
    const out = new Uint8Array(n);
    let value = BigInt(size);
    for (let i = n - 1; i >= 0; i--) {
        out[i] = Number(value & 255n);
        value >>= 8n;
    }
    out[0] |= 1 << (8 - n);
    return out;
}

function uintBytes(value, length = 0) {
    let n = length;
    if (!n) {
        n = 1;
        while (n < 8 && value >= 2 ** (8 * n)) {
            n++;
        }
    }
    const out = new Uint8Array(n);
    let v = BigInt(value);
    for (let i = n - 1; i >= 0; i--) {
        out[i] = Number(v & 255n);
        v >>= 8n;
    }
    return out;
}

function concat(parts) {
    const out = new Uint8Array(parts.reduce((sum, p) => sum + p.length, 0));
    let at = 0;
    for (const p of parts) {
        out.set(p, at);
        at += p.length;
    }
    return out;
}

const text = (value) => Uint8Array.from(value, (c) => c.charCodeAt(0));

// An element of an identifier and a body of bytes.
function element(id, body) {
    return concat([idBytes(id), sizeBytes(body.length), body]);
}

const master = (id, ...children) => element(id, concat(children));
const uint = (id, value, length = 0) => element(id, uintBytes(value, length));

function float(id, value) {
    const body = new Uint8Array(8);
    new DataView(body.buffer).setFloat64(0, value);
    return element(id, body);
}

// Gathers the encoded frames of one video track and writes the file.
export class WebmWriter {
    // codec is the codec string of the encoder, such as vp09.00.41.08 or vp8.
    constructor({ width, height, fps, codec }) {
        this.width = width;
        this.height = height;
        this.fps = fps;
        const family = Object.keys(WEBM_CODECS).find((key) => String(codec).startsWith(key));
        if (!family) {
            throw new Error(`WebM holds VP8, VP9 or AV1, not ${codec}.`);
        }
        this.codecId = WEBM_CODECS[family];
        this.description = null;
        this.clusters = [];
        this.cues = [];
        this.open = null;
        this.position = 0;
        this.bytes = 0;
        this.count = 0;
        this.end = 0;
    }

    // Adds one encoded frame, its bytes, its time and length in microseconds and whether it is a
    // key frame.
    add(data, { timestamp, duration, key, description }) {
        if (description && !this.description) {
            const view = description instanceof ArrayBuffer ? new Uint8Array(description) : new Uint8Array(description.buffer, description.byteOffset, description.byteLength);
            this.description = view.slice();
        }
        const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
        const ms = Math.round(timestamp / 1000);
        if (!this.open || key || ms - this.open.time > 32767) {
            this.close();
            this.open = { time: ms, parts: [uint(ID.timestamp, ms)], size: 0 };
            this.open.size = this.open.parts[0].length;
            if (key) {
                this.cues.push({ time: ms, position: this.position });
            }
        }
        const head = new Uint8Array(4);
        head[0] = 0x81;
        new DataView(head.buffer).setInt16(1, ms - this.open.time);
        head[3] = key ? 0x80 : 0;
        const block = concat([idBytes(ID.simpleBlock), sizeBytes(head.length + bytes.length), head]);
        this.open.parts.push(block, bytes);
        this.open.size += block.length + bytes.length;
        this.bytes += bytes.length;
        this.count++;
        this.end = Math.max(this.end, (timestamp + duration) / 1000);
    }

    // Closes the open cluster into a blob, or a list of byte arrays where the runtime has none.
    close() {
        if (!this.open) {
            return;
        }
        const head = concat([idBytes(ID.cluster), sizeBytes(this.open.size, 8)]);
        const parts = [head, ...this.open.parts];
        this.clusters.push(typeof Blob === 'function' ? new Blob(parts) : parts);
        this.position += head.length + this.open.size;
        this.open = null;
    }

    // The finished file as a blob of the type video/webm, or as a list of byte arrays where the
    // runtime has no Blob.
    finish() {
        if (!this.count) {
            throw new Error('The video holds no frames.');
        }
        this.close();
        const header = master(ID.ebml,
            uint(ID.ebmlVersion, 1), uint(ID.ebmlReadVersion, 1), uint(ID.maxIdLength, 4), uint(ID.maxSizeLength, 8),
            element(ID.docType, text('webm')), uint(ID.docTypeVersion, 4), uint(ID.docTypeReadVersion, 2));
        const info = master(ID.info, uint(ID.timestampScale, 1e6), float(ID.duration, this.end),
            element(ID.muxingApp, text('cuju')), element(ID.writingApp, text('cuju')));
        const entry = [
            uint(ID.trackNumber, 1), uint(ID.trackUid, 1), uint(ID.trackType, 1), uint(ID.flagLacing, 0),
            element(ID.codecId, text(this.codecId)),
        ];
        if (this.description) {
            entry.push(element(ID.codecPrivate, this.description));
        }
        entry.push(uint(ID.defaultDuration, Math.round(1e9 / this.fps)),
            master(ID.video, uint(ID.pixelWidth, this.width), uint(ID.pixelHeight, this.height)));
        const tracks = master(ID.tracks, master(ID.trackEntry, ...entry));
        // The seek head takes positions of eight bytes, so its size is known before the positions.
        const seekHead = (positions) => master(ID.seekHead, ...positions.map(([id, at]) => master(ID.seek,
            element(ID.seekId, idBytes(id)), uint(ID.seekPosition, at, 8))));
        const headSize = seekHead([[ID.info, 0], [ID.tracks, 0], [ID.cues, 0]]).length;
        const first = headSize + info.length + tracks.length;
        const cues = master(ID.cues, ...this.cues.map((cue) => master(ID.cuePoint, uint(ID.cueTime, cue.time),
            master(ID.cueTrackPositions, uint(ID.cueTrack, 1), uint(ID.cueClusterPosition, first + cue.position)))));
        const seek = seekHead([[ID.info, headSize], [ID.tracks, headSize + info.length], [ID.cues, first + this.position]]);
        const segmentSize = first + this.position + cues.length;
        const segment = concat([idBytes(ID.segment), sizeBytes(segmentSize, 8)]);
        const parts = [header, segment, seek, info, tracks, ...this.clusters, cues];
        if (typeof Blob === 'function') {
            return new Blob(parts, { type: 'video/webm' });
        }
        return parts.flat();
    }
}
