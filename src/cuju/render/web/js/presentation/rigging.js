// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The reach and the masked layers of a posed figure, on the world matrices of its bones, the
// features ik.fabrik and drivers.grf+layers. Both run after the pose and before the behaviours,
// the order of section 7.2.

import * as THREE from 'three';
import { boneIndex, poseLayers } from './stage.js';
import { fabrik } from './reach.js';

const v1 = new THREE.Vector3();
const v2 = new THREE.Vector3();
const v3 = new THREE.Vector3();
const q1 = new THREE.Quaternion();
const q2 = new THREE.Quaternion();
const s1 = new THREE.Vector3();
const m1 = new THREE.Matrix4();
const m2 = new THREE.Matrix4();
const IDENTITY = new THREE.Quaternion();

// Every bone below bone j, measured once per rig.
function descendants(rig, j) {
    if (!rig.cujuBelow) {
        rig.cujuBelow = rig.bones.map(() => []);
        rig.bones.forEach((b, k) => {
            for (let p = b.parent; p >= 0; p = rig.bones[p].parent) {
                rig.cujuBelow[p].push(k);
            }
        });
    }
    return rig.cujuBelow[j];
}

function depth(rig, j) {
    let d = 0;
    for (let p = rig.bones[j].parent; p >= 0; p = rig.bones[p].parent) {
        d += 1;
    }
    return d;
}

// Turns bone j and every bone below it about the bone's own position.
function turn(rig, world, j, q) {
    world[j].decompose(v1, q2, s1);
    m1.makeTranslation(v1.x, v1.y, v1.z).multiply(m2.makeRotationFromQuaternion(q)).multiply(new THREE.Matrix4().makeTranslation(-v1.x, -v1.y, -v1.z));
    world[j].premultiply(m1);
    for (const k of descendants(rig, j)) {
        world[k].premultiply(m1);
    }
}

// The bone indices of a chain, or null when the model lacks one of them.
export function chainOf(rig, names) {
    const out = names.map((n) => boneIndex(rig, n));
    return out.every((j) => j >= 0) ? out : null;
}

// Reaches a chain toward a target point of three's frame by FABRIK, by weight from 0 to 1.
// Returns the distance left from the tip to the target.
export function reach(rig, instance, chain, target, weight, iterations = 8) {
    const world = instance.world;
    const joints = chain.map((j) => {
        world[j].decompose(v1, q1, s1);
        return [v1.x, v1.y, v1.z];
    });
    const solved = fabrik(joints, [target.x, target.y, target.z], iterations);
    for (let i = 0; i < chain.length - 1; i++) {
        const j = chain[i];
        world[j].decompose(v1, q1, s1);
        world[chain[i + 1]].decompose(v2, q1, s1);
        const now = v3.subVectors(v2, v1);
        const want = new THREE.Vector3(solved[i + 1][0] - solved[i][0], solved[i + 1][1] - solved[i][1], solved[i + 1][2] - solved[i][2]);
        if (now.lengthSq() < 1e-10 || want.lengthSq() < 1e-10) {
            continue;
        }
        const q = new THREE.Quaternion().setFromUnitVectors(now.normalize(), want.normalize());
        turn(rig, world, j, IDENTITY.clone().slerp(q, weight));
    }
    world[chain[chain.length - 1]].decompose(v1, q1, s1);
    return v1.distanceTo(target);
}

// Lays the clips of masked layers over a pose of GRF's nodes. Each layer {clip, time, weight,
// mask} gives its masked bones, and every bone below each, the turns the clip gives them, blended
// by weight, on the parents GRF placed.
export function maskLayers(rig, instance, layers, frame) {
    const world = instance.world;
    for (const layer of layers) {
        if (!(layer.weight > 0) || !rig.clip(layer.clip)) {
            continue;
        }
        const set = new Set();
        for (const name of layer.mask) {
            const j = boneIndex(rig, name);
            if (j >= 0) {
                set.add(j);
                for (const k of descendants(rig, j)) {
                    set.add(k);
                }
            }
        }
        if (!set.size) {
            continue;
        }
        const grf = world.map((m) => m.clone());
        poseLayers(rig, instance, [{ clip: layer.clip, time: layer.time, weight: 1 }], frame, 'ignore');
        const clip = world.map((m) => m.clone());
        for (let j = 0; j < world.length; j++) {
            world[j].copy(grf[j]);
        }
        const order = [...set].sort((a, b) => depth(rig, a) - depth(rig, b));
        const pa = new THREE.Vector3();
        const pb = new THREE.Vector3();
        const qa = new THREE.Quaternion();
        const qb = new THREE.Quaternion();
        const sa = new THREE.Vector3();
        const sb = new THREE.Vector3();
        for (const j of order) {
            const parent = rig.bones[j].parent;
            const localGrf = parent >= 0 ? new THREE.Matrix4().copy(grf[parent]).invert().multiply(grf[j]) : grf[j].clone();
            const localClip = parent >= 0 ? new THREE.Matrix4().copy(clip[parent]).invert().multiply(clip[j]) : clip[j].clone();
            localGrf.decompose(pa, qa, sa);
            localClip.decompose(pb, qb, sb);
            qa.slerp(qb, layer.weight);
            const local = new THREE.Matrix4().compose(pa, qa, sa);
            world[j].copy(parent >= 0 ? new THREE.Matrix4().multiplyMatrices(world[parent], local) : local);
        }
    }
}
