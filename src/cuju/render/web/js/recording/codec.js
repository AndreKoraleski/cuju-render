// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Decoder of the frames section of recording version 2, which yields the frames of version 1 bit
// for bit, as the section Recording format of docs/rendering.md describes it. Every product below
// is an integer under 2**53, so double precision computes it exactly, as the writer's integers do.

export const FRAMES_TAG = 'FRMS';
export const ANNOTATIONS_TAG = 'ANNO';
const UNIT = 32767;
const UNIT2 = UNIT * UNIT;
const JOINTS = 14;
const CHILDREN = JOINTS - 1;
const PARENTS = [-1, 0, 1, 2, 2, 4, 2, 6, 1, 8, 9, 1, 11, 12];
const HEAD_WORDS = 19;
const HEAD_BYTES = HEAD_WORDS * 4;

function padded(players) {
    return (players + 3) & ~3;
}

export function decodedFrameBytes(players) {
    return HEAD_BYTES + players * JOINTS * 14 + 3 * padded(players);
}

// The bytes of a frames section of count frames, which the header's frame_count gives.
export function sectionBytes(players, count) {
    const short = players * (3 + 4 + 3 * CHILDREN + 3 * CHILDREN + 4 * CHILDREN + 3 * CHILDREN);
    return count * (HEAD_BYTES + 2 * short + players * CHILDREN + 3 * padded(players));
}

function isqrt(value) {
    let root = Math.floor(Math.sqrt(value));
    while (root * root > value) {
        root--;
    }
    while ((root + 1) * (root + 1) <= value) {
        root++;
    }
    return root;
}

// Reads the lanes of a section. A lane holds one value per frame, zigzag coded, its low bytes in
// one plane and its high bytes in the next, and each kind of lane follows the one before. Each
// kind decodes at once into one array, lane after lane.
class Lanes {
    constructor(bytes, count) {
        this.bytes = bytes;
        this.count = count;
        this.at = 0;
    }

    // Returns lanes of a width in bytes as signed values, or as bytes for a width of one.
    take(lanes, width) {
        const { bytes, count } = this;
        const size = lanes * count;
        const base = this.at;
        this.at += size * width;
        if (width === 1) {
            return bytes.slice(base, base + size);
        }
        if (width === 2) {
            const out = new Int16Array(size);
            const high = base + size;
            for (let i = 0; i < size; i++) {
                const zigzag = bytes[base + i] | (bytes[high + i] << 8);
                out[i] = (zigzag >>> 1) ^ -(zigzag & 1);
            }
            return out;
        }
        const out = new Int32Array(size);
        for (let i = 0; i < size; i++) {
            const zigzag = (bytes[base + i] | (bytes[base + size + i] << 8) | (bytes[base + 2 * size + i] << 16)
                | (bytes[base + 3 * size + i] << 24)) >>> 0;
            out[i] = (zigzag >>> 1) ^ -(zigzag & 1);
        }
        return out;
    }
}

// Sums each lane from every keyframe on, in place, the typed array wrapping as the writer's does.
function sum(values, count, interval) {
    for (let base = 0; base < values.length; base += count) {
        for (let t = 1; t < count; t++) {
            if (t % interval !== 0) {
                values[base + t] += values[base + t - 1];
            }
        }
    }
    return values;
}

// XORs each lane of bytes from every keyframe on, in place.
function unxor(values, count, interval) {
    for (let base = 0; base < values.length; base += count) {
        for (let t = 1; t < count; t++) {
            if (t % interval !== 0) {
                values[base + t] ^= values[base + t - 1];
            }
        }
    }
    return values;
}

// Decodes a frames section into the frames of version 1, back to back in one buffer.
export function decodeFrames(section, players, count, interval) {
    const size = decodedFrameBytes(players);
    const out = new ArrayBuffer(count * size);
    const bytes = new Uint8Array(out);
    const lanes = new Lanes(section, count);
    const n = players;
    const head = sum(lanes.take(HEAD_WORDS, 4), count, interval);
    const rootPosition = sum(sum(lanes.take(3 * n, 2), count, interval), count, interval);
    const rootRotation = sum(lanes.take(4 * n, 2), count, interval);
    const turn = sum(lanes.take(3 * CHILDREN * n, 2), count, interval);
    const sign = unxor(lanes.take(CHILDREN * n, 1), count, interval);
    const offset = sum(lanes.take(3 * CHILDREN * n, 2), count, interval);
    const rotationResidual = lanes.take(4 * CHILDREN * n, 2);
    const positionResidual = lanes.take(3 * CHILDREN * n, 2);
    const tailBytes = 3 * padded(n);
    const tail = unxor(lanes.take(tailBytes, 1), count, interval);
    const nodesEnd = HEAD_BYTES + n * JOINTS * 14;
    const words = new Int32Array(out);
    const nodes = new Int16Array(out);
    for (let t = 0; t < count; t++) {
        const frameAt = t * size;
        for (let l = 0; l < HEAD_WORDS; l++) {
            words[frameAt / 4 + l] = head[l * count + t];
        }
        for (let l = 0; l < tailBytes; l++) {
            bytes[frameAt + nodesEnd + l] = tail[l * count + t];
        }
        for (let p = 0; p < n; p++) {
            const root = (frameAt + HEAD_BYTES) / 2 + p * JOINTS * 7;
            for (let c = 0; c < 3; c++) {
                nodes[root + c] = rootPosition[(c * n + p) * count + t];
            }
            for (let c = 0; c < 4; c++) {
                nodes[root + 3 + c] = rootRotation[(c * n + p) * count + t];
            }
            for (let j = 1; j < JOINTS; j++) {
                const parent = root + PARENTS[j] * 7;
                const at = root + j * 7;
                const i = j - 1;
                const x1 = nodes[parent + 3];
                const y1 = nodes[parent + 4];
                const z1 = nodes[parent + 5];
                const w1 = nodes[parent + 6];
                // The local rotation, its w from the unit length and the sign lane.
                const lane = (i * 3 * n + p) * count + t;
                const x2 = turn[lane];
                const y2 = turn[lane + n * count];
                const z2 = turn[lane + 2 * n * count];
                let w2 = isqrt(Math.max(UNIT2 - x2 * x2 - y2 * y2 - z2 * z2, 0));
                if (sign[(i * n + p) * count + t]) {
                    w2 = -w2;
                }
                const turned = (i * 4 * n + p) * count + t;
                const step = n * count;
                nodes[at + 3] = Math.floor((2 * (w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2) + UNIT) / (2 * UNIT))
                    + rotationResidual[turned];
                nodes[at + 4] = Math.floor((2 * (w1 * y2 + y1 * w2 + z1 * x2 - x1 * z2) + UNIT) / (2 * UNIT))
                    + rotationResidual[turned + step];
                nodes[at + 5] = Math.floor((2 * (w1 * z2 + z1 * w2 + x1 * y2 - y1 * x2) + UNIT) / (2 * UNIT))
                    + rotationResidual[turned + 2 * step];
                nodes[at + 6] = Math.floor((2 * (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2) + UNIT) / (2 * UNIT))
                    + rotationResidual[turned + 3 * step];
                // The offset in the parent's frame, turned by the parent's rotation.
                const ox = offset[lane];
                const oy = offset[lane + step];
                const oz = offset[lane + 2 * step];
                const tx = y1 * oz - z1 * oy;
                const ty = z1 * ox - x1 * oz;
                const tz = x1 * oy - y1 * ox;
                nodes[at] = nodes[parent] + positionResidual[lane]
                    + Math.floor((2 * (ox * UNIT2 + 2 * w1 * tx + 2 * (y1 * tz - z1 * ty)) + UNIT2) / (2 * UNIT2));
                nodes[at + 1] = nodes[parent + 1] + positionResidual[lane + step]
                    + Math.floor((2 * (oy * UNIT2 + 2 * w1 * ty + 2 * (z1 * tx - x1 * tz)) + UNIT2) / (2 * UNIT2));
                nodes[at + 2] = nodes[parent + 2] + positionResidual[lane + 2 * step]
                    + Math.floor((2 * (oz * UNIT2 + 2 * w1 * tz + 2 * (x1 * ty - y1 * tx)) + UNIT2) / (2 * UNIT2));
            }
        }
    }
    return out;
}
