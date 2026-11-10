// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The celebration clips that teams upload, as poses of GRF's skeleton of 14 nodes. A clip moves
// the bones of a skeleton of its own, and clips.js reads those bones at 30 frames a second. This
// module turns each moment into nodes by the joint mapping of the clip, the inverse of the way a
// custom model follows the nodes, so a clip plays on GRF's player and on every model alike.
//
// A custom model draws a mapped bone with the world rotation of its node times a correction, the
// inverse of GRF's rest rotation of the node times the bone's own rest rotation. A clip's bone
// gives its node the world rotation of the bone times the inverse of that correction, and an
// unmapped node keeps its rest turn relative to its parent. The pelvis gives the body its height
// above the floor, scaled from the clip's skeleton to GRF's, and every other node hangs from its
// parent at GRF's own bone lengths, as the procedural animations do.
//
// The pelvis may travel. A clip that ends more than a quarter meter from where it began walks or
// runs, so that steady travel is taken out and the clip plays in place, and any movement left
// stays within a meter and a half of the spot. A choreography that pins a player to his place
// takes the travel out entirely, and a scorer stays inside the touch and goal lines.
//
// Poses use the engine frame of a recording, z up in meters with the player facing engine minus
// y at heading 0. Bones arrive in three.js's frame, y up, which glTF shares, facing plus z.

import { NODE_COUNT, NODE_PARENTS, PLAYER_FLOATS } from '../recording/format.js';

// Local rest positions of GRF's player, as in animate.js and players.js. Every local rotation of
// the rest pose is the identity.
export const REST_LOCAL = [
    [0, 0, 0], [0, 0, 0.96], [0, 0, 0.15], [0, -0.03, 0.5], [0.16, -0.01, 0.48], [-0.01, 0, -0.33],
    [-0.16, -0.01, 0.48], [0.01, 0, -0.33], [0.087, 0, -0.01], [0, 0, -0.42], [0, -0.04, -0.44],
    [-0.087, 0, -0.01], [0, 0, -0.42], [0, -0.04, -0.44],
];
// The height of the pelvis above the ground point in the rest pose.
export const REST_BODY_HEIGHT = 0.96;
export const FPS = 30;
// The longest stretch of a clip that plays, in seconds.
export const MAX_SECONDS = 30;
// A clip that ends farther than this from its start travels, in meters.
export const DRIFT = 0.25;
// The farthest the pelvis strays from the spot, in meters.
export const ROOT_LIMIT = 1.5;

// Quaternions are arrays x, y, z, w.
export function multiply(a, b, out = [0, 0, 0, 1]) {
    const [ax, ay, az, aw] = a;
    const [bx, by, bz, bw] = b;
    out[0] = aw * bx + ax * bw + ay * bz - az * by;
    out[1] = aw * by - ax * bz + ay * bw + az * bx;
    out[2] = aw * bz + ax * by - ay * bx + az * bw;
    out[3] = aw * bw - ax * bx - ay * by - az * bz;
    return out;
}

export function invert(q, out = [0, 0, 0, 1]) {
    const n = q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3] || 1;
    out[0] = -q[0] / n;
    out[1] = -q[1] / n;
    out[2] = -q[2] / n;
    out[3] = q[3] / n;
    return out;
}

function normalize(q) {
    const n = Math.hypot(q[0], q[1], q[2], q[3]);
    if (!(n > 1e-9)) {
        q[0] = 0;
        q[1] = 0;
        q[2] = 0;
        q[3] = 1;
        return q;
    }
    q[0] /= n;
    q[1] /= n;
    q[2] /= n;
    q[3] /= n;
    return q;
}

// The vector v turned by the unit quaternion q.
export function rotate(q, v, out = [0, 0, 0]) {
    const [x, y, z, w] = q;
    const [vx, vy, vz] = v;
    const tx = 2 * (y * vz - z * vy);
    const ty = 2 * (z * vx - x * vz);
    const tz = 2 * (x * vy - y * vx);
    out[0] = vx + w * tx + y * tz - z * ty;
    out[1] = vy + w * ty + z * tx - x * tz;
    out[2] = vz + w * tz + x * ty - y * tx;
    return out;
}

// three.js's frame to the engine's, the inverse of the turn players.js makes for every node.
export function engineRotation(q, out = [0, 0, 0, 1]) {
    const [x, y, z, w] = q;
    out[0] = x;
    out[1] = -z;
    out[2] = y;
    out[3] = w;
    return out;
}

export function enginePosition(p, out = [0, 0, 0]) {
    const [x, y, z] = p;
    out[0] = x;
    out[1] = -z;
    out[2] = y;
    return out;
}

const world = Array.from({ length: NODE_COUNT }, () => [0, 0, 0, 1]);
const place = Array.from({ length: NODE_COUNT }, () => [0, 0, 0]);
const turned = [0, 0, 0];
const inverse = [0, 0, 0, 1];
const bone = [0, 0, 0, 1];

// Writes the nodes of one moment of a clip into out at o. bones holds, for each node, the world
// rotation in three.js's frame of the bone mapped to it, or null for a node without a bone, and
// body the world position in that frame of the bone mapped to body, the pelvis. rig holds
// corrections, the correction of each node or null, heightRatio, the clip's pelvis height over
// GRF's, and floor, the height of the clip's floor in the frame of the bones. offset is the
// pelvis's travel from the spot along engine x and y.
export function nodesFromBones(bones, body, rig, offset, out, o = 0) {
    world[0][0] = 0;
    world[0][1] = 0;
    world[0][2] = 0;
    world[0][3] = 1;
    for (let n = 1; n < NODE_COUNT; n++) {
        const q = bones[n];
        const c = rig.corrections[n];
        if (q && c) {
            multiply(q, invert(c, inverse), bone);
            normalize(engineRotation(bone, world[n]));
        } else {
            const p = world[NODE_PARENTS[n]];
            world[n][0] = p[0];
            world[n][1] = p[1];
            world[n][2] = p[2];
            world[n][3] = p[3];
        }
    }
    place[0][0] = offset[0];
    place[0][1] = offset[1];
    place[0][2] = 0;
    place[1][0] = offset[0];
    place[1][1] = offset[1];
    place[1][2] = (body[1] - rig.floor) / (rig.heightRatio || 1);
    for (let n = 2; n < NODE_COUNT; n++) {
        const parent = NODE_PARENTS[n];
        rotate(world[parent], REST_LOCAL[n], turned);
        place[n][0] = place[parent][0] + turned[0];
        place[n][1] = place[parent][1] + turned[1];
        place[n][2] = place[parent][2] + turned[2];
    }
    for (let n = 0; n < NODE_COUNT; n++) {
        const k = o + n * 7;
        out[k] = place[n][0];
        out[k + 1] = place[n][1];
        out[k + 2] = place[n][2];
        out[k + 3] = world[n][0];
        out[k + 4] = world[n][1];
        out[k + 5] = world[n][2];
        out[k + 6] = world[n][3];
    }
    return out;
}

// The travel of the pelvis at each sample along engine x and y, with steady travel taken out of
// a clip that goes somewhere and the rest kept within ROOT_LIMIT of the spot.
export function rootOffsets(bodies) {
    const count = bodies.length;
    const first = bodies[0];
    const last = bodies[count - 1];
    // Engine x is three's x and engine y is three's minus z.
    const endX = last[0] - first[0];
    const endY = -(last[2] - first[2]);
    const travels = Math.hypot(endX, endY) > DRIFT;
    return bodies.map((p, i) => {
        let x = p[0] - first[0];
        let y = -(p[2] - first[2]);
        if (travels) {
            const u = count > 1 ? i / (count - 1) : 0;
            x -= endX * u;
            y -= endY * u;
        }
        const d = Math.hypot(x, y);
        if (d > ROOT_LIMIT) {
            x *= ROOT_LIMIT / d;
            y *= ROOT_LIMIT / d;
        }
        return [x, y];
    });
}

// A clip of nodes from its samples, each the bones and pelvis of one moment as nodesFromBones
// takes them, FPS apart, the last at duration.
export function nodeClip(samples, rig, duration) {
    const count = samples.length;
    const frames = new Float32Array(count * PLAYER_FLOATS);
    const offsets = rootOffsets(samples.map((s) => s.body));
    samples.forEach((s, i) => nodesFromBones(s.bones, s.body, rig, offsets[i], frames, i * PLAYER_FLOATS));
    return { duration: count > 1 ? duration : 0, count, frames };
}

const qa = [0, 0, 0, 1];
const qb = [0, 0, 0, 1];
const yaw = [0, 0, 0, 1];
const pose = new Float32Array(PLAYER_FLOATS);

// Writes the nodes of a clip at time t seconds into out at o, looping, standing at x, y and
// turned to heading, radians about engine z. With pin the pelvis keeps to the spot, and bounds,
// half the length and width of the pitch, keep the ground point inside the lines.
export function poseNodeClip(clip, t, out, o = 0, { x = 0, y = 0, heading = 0, pin = false, bounds = null } = {}) {
    const span = clip.duration;
    let time = Math.max(0, Number(t) || 0);
    if (span > 0) {
        time %= span;
    }
    const f = span > 0 ? (time / span) * (clip.count - 1) : 0;
    const i0 = Math.min(clip.count - 1, Math.floor(f));
    const i1 = Math.min(clip.count - 1, i0 + 1);
    const w = f - i0;
    const a = i0 * PLAYER_FLOATS;
    const b = i1 * PLAYER_FLOATS;
    const frames = clip.frames;
    for (let n = 0; n < NODE_COUNT; n++) {
        const k = n * 7;
        for (let c = 0; c < 3; c++) {
            pose[k + c] = frames[a + k + c] + (frames[b + k + c] - frames[a + k + c]) * w;
        }
        for (let c = 0; c < 4; c++) {
            qa[c] = frames[a + k + 3 + c];
            qb[c] = frames[b + k + 3 + c];
        }
        // The shorter way round, then a normalized blend, close enough a thirtieth of a second
        // apart.
        const dot = qa[0] * qb[0] + qa[1] * qb[1] + qa[2] * qb[2] + qa[3] * qb[3];
        const s = dot < 0 ? -1 : 1;
        for (let c = 0; c < 4; c++) {
            qa[c] += (qb[c] * s - qa[c]) * w;
        }
        normalize(qa);
        for (let c = 0; c < 4; c++) {
            pose[k + 3 + c] = qa[c];
        }
    }
    if (pin) {
        const px = pose[0];
        const py = pose[1];
        for (let n = 0; n < NODE_COUNT; n++) {
            pose[n * 7] -= px;
            pose[n * 7 + 1] -= py;
        }
    }
    yaw[2] = Math.sin(heading / 2);
    yaw[3] = Math.cos(heading / 2);
    const cos = Math.cos(heading);
    const sin = Math.sin(heading);
    let dx = x;
    let dy = y;
    if (bounds) {
        const gx = x + cos * pose[0] - sin * pose[1];
        const gy = y + sin * pose[0] + cos * pose[1];
        dx += Math.max(-bounds[0], Math.min(bounds[0], gx)) - gx;
        dy += Math.max(-bounds[1], Math.min(bounds[1], gy)) - gy;
    }
    for (let n = 0; n < NODE_COUNT; n++) {
        const k = n * 7;
        const px = pose[k];
        const py = pose[k + 1];
        out[o + k] = dx + cos * px - sin * py;
        out[o + k + 1] = dy + sin * px + cos * py;
        out[o + k + 2] = pose[k + 2];
        qb[0] = pose[k + 3];
        qb[1] = pose[k + 4];
        qb[2] = pose[k + 5];
        qb[3] = pose[k + 6];
        multiply(yaw, qb, qa);
        out[o + k + 3] = qa[0];
        out[o + k + 4] = qa[1];
        out[o + k + 5] = qa[2];
        out[o + k + 6] = qa[3];
    }
    return out;
}

// The uploaded clips that the page has loaded, by the names celebrations play them under, each
// with its clip of nodes and the name of its animation.
const uploads = new Map();

export function registerUpload(name, clip, label) {
    uploads.set(name, { clip, label });
}

// Forgets every loaded clip whose name ends with suffix.
export function forgetUploads(suffix) {
    for (const name of [...uploads.keys()]) {
        if (name.endsWith(suffix)) {
            uploads.delete(name);
        }
    }
}

export function hasUpload(name) {
    return typeof name === 'string' && uploads.has(name);
}

export function uploadDuration(name) {
    const entry = uploads.get(name);
    return entry ? entry.clip.duration : 0;
}

export function uploadLabel(name) {
    const entry = uploads.get(name);
    return entry ? entry.label : null;
}

// Poses a loaded clip as poseNodeClip does, false for a name the page has not loaded.
export function poseUpload(name, t, out, o, options) {
    const entry = uploads.get(name);
    if (!entry) {
        return false;
    }
    poseNodeClip(entry.clip, t, out, o, options);
    return true;
}
