// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// A small writer of MP4 files of one H.264 video track, for the video export of the page. It
// takes the encoded frames in the order of decoding with their times in microseconds and writes
// the boxes of ISO/IEC 14496-12 and 14496-15 that a player needs, the file type, the movie with
// its sample tables, and the frames in one media box. The movie comes before the frames, so a
// player starts before the whole file has arrived. The frames gather into blobs as they come, so
// a browser may keep a long video on its disk rather than in memory.

const textBytes = (text) => Uint8Array.from(text, (c) => c.charCodeAt(0));

// A writer of big-endian fields into a growing list of bytes.
class Bytes {
    constructor() {
        this.parts = [];
        this.length = 0;
    }

    push(array) {
        this.parts.push(array);
        this.length += array.length;
        return this;
    }

    u8(value) {
        return this.push(Uint8Array.of(value & 255));
    }

    u16(value) {
        const b = new Uint8Array(2);
        new DataView(b.buffer).setUint16(0, value);
        return this.push(b);
    }

    u32(value) {
        const b = new Uint8Array(4);
        new DataView(b.buffer).setUint32(0, value >>> 0);
        return this.push(b);
    }

    i32(value) {
        const b = new Uint8Array(4);
        new DataView(b.buffer).setInt32(0, value);
        return this.push(b);
    }

    u64(value) {
        const b = new Uint8Array(8);
        new DataView(b.buffer).setBigUint64(0, BigInt(value));
        return this.push(b);
    }

    zeros(count) {
        return this.push(new Uint8Array(count));
    }

    text(value) {
        return this.push(textBytes(value));
    }

    bytes() {
        const out = new Uint8Array(this.length);
        let at = 0;
        for (const part of this.parts) {
            out.set(part, at);
            at += part.length;
        }
        return out;
    }
}

// A box of a type and a body that fill writes, or of children given as bytes.
function box(type, fill, ...children) {
    const body = new Bytes();
    if (fill) {
        fill(body);
    }
    for (const child of children) {
        body.push(child);
    }
    const out = new Bytes().u32(8 + body.length).text(type);
    out.push(body.bytes());
    return out.bytes();
}

// A full box, a box whose body starts with a version and flags.
function fullBox(type, version, flags, fill, ...children) {
    return box(type, (b) => {
        b.u8(version).u8(flags >> 16).u16(flags & 0xffff);
        if (fill) {
            fill(b);
        }
    }, ...children);
}

// The matrix of a track that shows as it was encoded.
const MATRIX = [0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000];

// Runs of equal values, as the sample tables count them.
function runs(values) {
    const out = [];
    for (const value of values) {
        const last = out[out.length - 1];
        if (last && last[1] === value) {
            last[0]++;
        } else {
            out.push([1, value]);
        }
    }
    return out;
}

// Gathers the encoded frames of one video track and writes the file.
export class Mp4Writer {
    // width and height are the picture's, fps the frame rate, which sets the time scale.
    constructor({ width, height, fps }) {
        this.width = width;
        this.height = height;
        this.timescale = Math.max(1, Math.round(fps)) * 1000;
        this.samples = [];
        this.description = null;
        this.pending = [];
        this.pendingBytes = 0;
        this.blobs = [];
        this.bytes = 0;
    }

    // Adds one encoded frame, its bytes, its time and length in microseconds and whether it is a
    // key frame. description is the AVC decoder configuration that the encoder gives with its
    // first frame.
    add(data, { timestamp, duration, key, description }) {
        if (description && !this.description) {
            this.description = new Uint8Array(description instanceof ArrayBuffer ? description : description.buffer.slice(description.byteOffset, description.byteOffset + description.byteLength));
        }
        const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
        this.samples.push({ size: bytes.length, timestamp, duration, key: !!key });
        this.pending.push(bytes);
        this.pendingBytes += bytes.length;
        this.bytes += bytes.length;
        // The frames gather into a blob every few megabytes.
        if (this.pendingBytes >= 8 << 20 && typeof Blob === 'function') {
            this.flushPending();
        }
    }

    flushPending() {
        if (this.pending.length) {
            this.blobs.push(typeof Blob === 'function' ? new Blob(this.pending) : this.pending.slice());
            this.pending = [];
            this.pendingBytes = 0;
        }
    }

    // The times of the samples in the units of the track, in the order of decoding, with their
    // offsets to the order of showing.
    timing() {
        const scale = this.timescale / 1e6;
        const shown = this.samples.map((s) => Math.round(s.timestamp * scale));
        const decoded = [...shown].sort((a, b) => a - b);
        const deltas = decoded.map((t, i) => (i + 1 < decoded.length ? decoded[i + 1] - t : Math.max(1, Math.round(this.samples[i].duration * scale))));
        const offsets = shown.map((t, i) => t - decoded[i]);
        const total = decoded.length ? decoded[decoded.length - 1] - decoded[0] + deltas[deltas.length - 1] : 0;
        return { deltas, offsets, total, start: decoded.length ? decoded[0] : 0 };
    }

    // The file type, the movie and the head of the media box, with the frames placed after them.
    head(large) {
        if (!this.description) {
            throw new Error('The encoder gave no decoder configuration of H.264.');
        }
        const { deltas, offsets, total } = this.timing();
        const ftyp = box('ftyp', (b) => b.text('isom').u32(512).text('isom').text('iso2').text('avc1').text('mp41'));
        const movieDuration = Math.round((total * 1000) / this.timescale);
        const mdatHead = large ? 16 : 8;
        // The offsets of the frames follow the movie, whose size changes with the offsets only when
        // they outgrow 32 bits, so the movie is built again until its size holds.
        const build = (first) => {
            const count = this.samples.length;
            let at = first;
            const offsetsOfChunks = this.samples.map((s) => {
                const here = at;
                at += s.size;
                return here;
            });
            const wide = at > 0xffffffff;
            const stsd = fullBox('stsd', 0, 0, (b) => b.u32(1), box('avc1', (b) => {
                b.zeros(6).u16(1).zeros(16).u16(this.width).u16(this.height)
                    .u32(0x00480000).u32(0x00480000).u32(0).u16(1).zeros(32).u16(0x0018).u16(0xffff);
            }, box('avcC', (b) => b.push(this.description)),
            box('pasp', (b) => b.u32(1).u32(1))));
            const stts = fullBox('stts', 0, 0, (b) => {
                const list = runs(deltas);
                b.u32(list.length);
                for (const [n, delta] of list) {
                    b.u32(n).u32(delta);
                }
            });
            const tables = [stsd, stts];
            if (offsets.some((o) => o !== 0)) {
                tables.push(fullBox('ctts', 1, 0, (b) => {
                    const list = runs(offsets);
                    b.u32(list.length);
                    for (const [n, offset] of list) {
                        b.u32(n).i32(offset);
                    }
                }));
            }
            if (this.samples.some((s) => !s.key)) {
                tables.push(fullBox('stss', 0, 0, (b) => {
                    const keys = [];
                    this.samples.forEach((s, i) => s.key && keys.push(i + 1));
                    b.u32(keys.length);
                    for (const k of keys) {
                        b.u32(k);
                    }
                }));
            }
            tables.push(fullBox('stsc', 0, 0, (b) => b.u32(1).u32(1).u32(1).u32(1)));
            tables.push(fullBox('stsz', 0, 0, (b) => {
                b.u32(0).u32(count);
                for (const s of this.samples) {
                    b.u32(s.size);
                }
            }));
            tables.push(wide
                ? fullBox('co64', 0, 0, (b) => {
                    b.u32(count);
                    for (const o of offsetsOfChunks) {
                        b.u64(o);
                    }
                })
                : fullBox('stco', 0, 0, (b) => {
                    b.u32(count);
                    for (const o of offsetsOfChunks) {
                        b.u32(o);
                    }
                }));
            const stbl = box('stbl', null, ...tables);
            const dinf = box('dinf', null, fullBox('dref', 0, 0, (b) => b.u32(1), fullBox('url ', 0, 1)));
            const minf = box('minf', null, fullBox('vmhd', 0, 1, (b) => b.zeros(8)), dinf, stbl);
            const hdlr = fullBox('hdlr', 0, 0, (b) => b.u32(0).text('vide').zeros(12).text('VideoHandler').u8(0));
            const mdhd = fullBox('mdhd', 0, 0, (b) => b.u32(0).u32(0).u32(this.timescale).u32(total).u16(0x55c4).u16(0));
            const mdia = box('mdia', null, mdhd, hdlr, minf);
            const tkhd = fullBox('tkhd', 0, 3, (b) => {
                b.u32(0).u32(0).u32(1).u32(0).u32(movieDuration).zeros(8).u16(0).u16(0).u16(0).u16(0);
                for (const value of MATRIX) {
                    b.u32(value);
                }
                b.u32(this.width * 65536).u32(this.height * 65536);
            });
            const trak = box('trak', null, tkhd, mdia);
            const mvhd = fullBox('mvhd', 0, 0, (b) => {
                b.u32(0).u32(0).u32(1000).u32(movieDuration).u32(0x00010000).u16(0x0100).zeros(10);
                for (const value of MATRIX) {
                    b.u32(value);
                }
                b.zeros(24).u32(2);
            });
            return box('moov', null, mvhd, trak);
        };
        let moov = build(ftyp.length + mdatHead);
        for (let tries = 0; tries < 3; tries++) {
            const next = build(ftyp.length + moov.length + mdatHead);
            const settled = next.length === moov.length;
            moov = next;
            if (settled) {
                break;
            }
        }
        const mdatSize = mdatHead + this.bytes;
        const mdat = new Bytes();
        if (large) {
            mdat.u32(1).text('mdat').u64(mdatSize);
        } else {
            mdat.u32(mdatSize).text('mdat');
        }
        return [ftyp, moov, mdat.bytes()];
    }

    // The finished file as a blob of the type video/mp4, or as a list of byte arrays where the
    // runtime has no Blob.
    finish() {
        if (!this.samples.length) {
            throw new Error('The video holds no frames.');
        }
        const large = 8 + this.bytes > 0xffffffff;
        const head = this.head(large);
        this.flushPending();
        if (typeof Blob === 'function') {
            return new Blob([...head, ...this.blobs], { type: 'video/mp4' });
        }
        return [...head, ...this.blobs.flat()];
    }
}
