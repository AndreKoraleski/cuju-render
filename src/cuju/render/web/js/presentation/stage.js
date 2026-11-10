// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// How a package's presentation reaches the drawn figures.
//
// Transforms compose in one order. The simulation root, where the engine puts the player and
// where he faces, comes first. The cosmetic offset of the persistent behaviours, a lift, sway,
// bank, turn or scale about the pivot socket, comes next. Then comes the pose, GRF's nodes, a
// clip or the package's own clips, with any root motion of a clip ignored or kept to its height
// as the manifest declares, and the bone channels and gaze of the behaviours over it. Sockets and
// the attachments on them resolve last, from the final pose, so they never trail their figure.

import * as THREE from 'three';
import { PLAYER_FLOATS } from '../recording/format.js';

const ZERO_SCALE = new THREE.Matrix4().makeScale(0, 0, 0);
const UP = new THREE.Vector3(0, 1, 0);
const m1 = new THREE.Matrix4();
const m2 = new THREE.Matrix4();
const m3 = new THREE.Matrix4();
const q1 = new THREE.Quaternion();
const q2 = new THREE.Quaternion();
const v1 = new THREE.Vector3();
const v2 = new THREE.Vector3();
const v3 = new THREE.Vector3();
const e1 = new THREE.Euler();

// The heading of a player in three's frame, from the turn of node player of the nodes.
export function heading(nodes, base) {
    q1.set(nodes[base + 3], nodes[base + 5], -nodes[base + 4], nodes[base + 6]);
    if (q1.lengthSq() < 1e-8) {
        return 0;
    }
    q1.normalize();
    v1.set(0, 0, 1).applyQuaternion(q1);
    return Math.atan2(v1.x, v1.z);
}

// The simulation root of a player, its ground point lifted by node player's height, turned to
// its heading, in three's frame and in meters.
export function rootFrame(nodes, base, out = new THREE.Matrix4()) {
    return out.makeRotationY(heading(nodes, base)).setPosition(nodes[base], nodes[base + 2] || 0, -nodes[base + 1]);
}

// The children of each bone of a rig and every bone below each, measured once per rig.
function below(rig) {
    if (!rig.presentationBelow) {
        const out = rig.bones.map(() => []);
        rig.bones.forEach((b, j) => {
            for (let p = b.parent; p >= 0; p = rig.bones[p].parent) {
                out[p].push(j);
            }
        });
        rig.presentationBelow = out;
        rig.presentationIndex = new Map(rig.bones.map((b, j) => [b.name, j]));
    }
    return rig.presentationBelow;
}

export function boneIndex(rig, name) {
    below(rig);
    const clean = THREE.PropertyBinding.sanitizeNodeName(String(name));
    const j = rig.presentationIndex.get(name);
    return j !== undefined ? j : (rig.presentationIndex.get(clean) ?? -1);
}

// The bone whose translation is root motion, the one mapped to node player, else the top bone.
function rootBone(rig) {
    const mapped = rig.bones.findIndex((b) => b.node === 0);
    return mapped >= 0 ? mapped : 0;
}

// Poses an instance from layers of clips, each {clip, time, weight}, with weights summing to
// one, standing on the root frame given. Root motion of the clips is ignored, kept to its
// height, or allowed as the manifest says. Fills instance.world, the bones are written later.
export function poseLayers(rig, instance, layers, frame, rootMotion = 'ignore') {
    if (!instance.mixer) {
        instance.mixer = new THREE.AnimationMixer(instance.root);
    }
    const actions = instance.layerActions || (instance.layerActions = new Map());
    if (!instance.restLocal) {
        // The rest of each bone before any clip moved it, for root motion.
        instance.restLocal = instance.bones.map((b) => (b ? b.position.clone() : null));
    }
    const wanted = new Set();
    for (const l of layers) {
        const clip = rig.clip(l.clip);
        if (!clip) {
            continue;
        }
        let action = actions.get(clip.name);
        if (!action) {
            action = instance.mixer.clipAction(clip);
            action.play();
            actions.set(clip.name, action);
        }
        wanted.add(clip.name);
        action.enabled = true;
        action.setEffectiveWeight(l.weight);
        const d = clip.duration || 0;
        action.time = d > 0 ? Math.max(0, Math.min(d - 1e-4, l.time % d)) : 0;
    }
    for (const [name, action] of actions) {
        if (!wanted.has(name)) {
            action.enabled = false;
        }
    }
    instance.mixer.update(0);
    const top = rootBone(rig);
    const bone = instance.bones[top];
    const rest = instance.restLocal[top];
    if (bone && rest && rootMotion !== 'allow') {
        bone.position.x = rest.x;
        bone.position.z = rest.z;
        if (rootMotion === 'ignore') {
            bone.position.y = rest.y;
        }
    }
    const root = instance.root;
    root.matrixAutoUpdate = false;
    root.matrix.copy(frame).multiply(rig.placement);
    for (const b of instance.bones) {
        if (b) {
            b.matrixAutoUpdate = true;
            b.matrixWorldAutoUpdate = true;
        }
    }
    root.updateMatrixWorld(true);
    for (const b of instance.bones) {
        if (b) {
            b.matrixAutoUpdate = false;
            b.matrixWorldAutoUpdate = false;
        }
    }
    const world = instance.world;
    for (let j = 0; j < rig.bones.length; j++) {
        const b = instance.bones[j];
        if (b) {
            world[j].copy(b.matrixWorld);
        } else {
            const p = rig.bones[j].parent;
            world[j].multiplyMatrices(p >= 0 ? world[p] : root.matrixWorld, rig.bones[j].local);
        }
    }
    root.matrix.identity();
    root.matrixAutoUpdate = true;
}

// Drops the clips of layers from an instance, before GRF's nodes pose it again.
export function stopLayers(instance) {
    if (instance.layerActions) {
        for (const action of instance.layerActions.values()) {
            action.enabled = false;
        }
    }
}

// Premultiplies bone j, and every bone below it when asked, by a matrix of three's frame.
function moveBones(rig, world, j, matrix, descendants) {
    world[j].premultiply(matrix);
    if (descendants) {
        for (const c of below(rig)[j]) {
            world[c].premultiply(matrix);
        }
    }
}

// The matrix of a socket in three's frame, from the node it names or the cosmetic root. A socket
// has an offset in metres and a turn in degrees from its node, and its own frame, its forward
// along z and its up along y, given as vectors of the node's frame.
export function socketMatrix(rig, instance, socket, cosmeticRoot, out = new THREE.Matrix4()) {
    const j = socket.node ? boneIndex(rig, socket.node) : -1;
    if (j >= 0) {
        instance.world[j].decompose(v1, q1, v2);
        out.compose(v1, q1, v2.set(1, 1, 1));
    } else {
        out.copy(cosmeticRoot);
    }
    const r = socket.rotation || [0, 0, 0];
    e1.set(r[0] * Math.PI / 180, r[1] * Math.PI / 180, r[2] * Math.PI / 180);
    m1.makeRotationFromEuler(e1).setPosition(...(socket.offset || [0, 0, 0]));
    out.multiply(m1);
    const f = v1.fromArray(socket.forward || [0, 0, 1]).normalize();
    const u = v2.fromArray(socket.up || [0, 1, 0]);
    // Up is made square to forward, so any up that is not along forward works.
    u.addScaledVector(f, -u.dot(f));
    if (u.lengthSq() < 1e-9) {
        u.set(0, 1, 0).addScaledVector(f, -f.y);
    }
    u.normalize();
    const x = v3.crossVectors(u, f);
    m2.makeBasis(x, u, f);
    return out.multiply(m2);
}

// The cosmetic offset of the behaviours as a matrix about a pivot of the root frame.
function offsetMatrix(root, pivot, out) {
    e1.set(root.rotX, root.rotY, root.rotZ, 'YXZ');
    const s = Math.max(0.05, 1 + root.scale);
    m1.makeTranslation(pivot.x, pivot.y, pivot.z);
    m2.makeRotationFromEuler(e1).scale(v1.set(s, s, s)).setPosition(root.x, root.y, root.z);
    m3.makeTranslation(-pivot.x, -pivot.y, -pivot.z);
    return out.copy(m1).multiply(m2).multiply(m3);
}

// A turn of world matrix j about its own position, applied to it and, when asked, below it.
function turnAt(rig, world, j, rotation, descendants) {
    world[j].decompose(v1, q1, v2);
    const at = new THREE.Matrix4().makeTranslation(v1.x, v1.y, v1.z);
    const back = new THREE.Matrix4().makeTranslation(-v1.x, -v1.y, -v1.z);
    moveBones(rig, world, j, at.multiply(rotation).multiply(back), descendants);
}

// Applies the outputs of the behaviours to a posed instance, the composition of section 7. frame
// is the simulation root, cosmetic receives it with the cosmetic offset, for root sockets, and
// gazeSocket gives the forward of a node that looks, the manifest's gaze socket.
export function applyOutputs(rig, instance, frame, outputs, pivot, gazeSocket, cosmetic) {
    const world = instance.world;
    const offset = offsetMatrix(outputs.root, pivot, new THREE.Matrix4());
    cosmetic.copy(frame).multiply(offset);
    m1.copy(frame).multiply(offset).multiply(m2.copy(frame).invert());
    for (let j = 0; j < world.length; j++) {
        world[j].premultiply(m1);
    }
    const order = [...outputs.nodes.entries()].map(([name, o]) => [boneIndex(rig, name), o]).filter(([j]) => j >= 0).sort((a, b) => a[0] - b[0]);
    for (const [j, o] of order) {
        world[j].decompose(v1, q1, v2);
        const local = new THREE.Quaternion();
        if (o.rotX || o.rotY || o.rotZ) {
            local.setFromEuler(e1.set(o.rotX, o.rotY, o.rotZ, 'XYZ'));
        }
        for (const spin of o.spins) {
            local.multiply(q2.setFromAxisAngle(v3.fromArray(spin.axis).normalize(), spin.angle));
        }
        if (local.lengthSq() > 0 && Math.abs(local.w) < 1 - 1e-12) {
            // A turn about the node's own axes, at the node, carrying the nodes below it.
            const delta = new THREE.Matrix4().makeRotationFromQuaternion(q1.clone().multiply(local).multiply(q1.clone().invert()));
            turnAt(rig, world, j, delta, true);
        }
        if (o.scale) {
            const s = Math.max(0.05, 1 + o.scale);
            turnAt(rig, world, j, new THREE.Matrix4().makeScale(s, s, s), true);
        }
        if (o.x || o.y || o.z) {
            v3.set(o.x, o.y, o.z).applyMatrix4(m2.copy(frame).setPosition(0, 0, 0));
            moveBones(rig, world, j, new THREE.Matrix4().makeTranslation(v3.x, v3.y, v3.z), true);
        }
    }
    for (const f of outputs.follows) {
        const j = boneIndex(rig, f.node);
        if (j >= 0) {
            v3.fromArray(f.offset).applyMatrix4(m2.copy(frame).setPosition(0, 0, 0));
            moveBones(rig, world, j, new THREE.Matrix4().makeTranslation(v3.x, v3.y, v3.z), true);
        }
    }
    const h = Math.atan2(frame.elements[8], frame.elements[10]);
    for (const g of outputs.looks) {
        const j = boneIndex(rig, g.node);
        if (j < 0 || !(g.weight > 0)) {
            continue;
        }
        // The node's forward now, from the gaze socket on it, the behaviour's own forward or the
        // node's z axis, as yaw and pitch.
        const forward = new THREE.Vector3();
        if (gazeSocket && gazeSocket.node && boneIndex(rig, gazeSocket.node) === j) {
            socketMatrix(rig, instance, gazeSocket, cosmetic, m3);
            forward.setFromMatrixColumn(m3, 2).normalize();
        } else {
            world[j].decompose(v1, q1, v2);
            forward.fromArray(g.forward || [0, 0, 1]).applyQuaternion(q1).normalize();
        }
        const nowYaw = Math.atan2(forward.x, forward.z);
        const nowPitch = Math.atan2(forward.y, Math.hypot(forward.x, forward.z));
        const dYaw = Math.atan2(Math.sin(h + g.yaw - nowYaw), Math.cos(h + g.yaw - nowYaw)) * g.weight;
        const dPitch = (g.pitch - nowPitch) * g.weight;
        const side = new THREE.Vector3(Math.cos(nowYaw + dYaw), 0, -Math.sin(nowYaw + dYaw));
        const turn = new THREE.Matrix4().makeRotationAxis(UP, dYaw);
        const tilt = new THREE.Matrix4().makeRotationAxis(side, -dPitch);
        turnAt(rig, world, j, tilt.multiply(turn), g.descendants);
    }
}

// Writes the world matrices of an instance into its bones, a hidden head shrunk to a point.
export function writeBones(rig, instance, hideHead) {
    const world = instance.world;
    for (let j = 0; j < rig.bones.length; j++) {
        const bone = instance.bones[j];
        if (!bone) {
            continue;
        }
        if (hideHead && rig.headIndex >= 0 && rig.headMask[j]) {
            const h = world[rig.headIndex].elements;
            bone.matrixWorld.copy(ZERO_SCALE).setPosition(h[12], h[13], h[14]);
        } else {
            bone.matrixWorld.copy(world[j]);
        }
    }
}

// A material rule matches a name exactly, every name with a star, or names that start with the
// part before a closing star.
export function matches(rule, name) {
    const m = rule.match || '*';
    if (m === '*') {
        return true;
    }
    return m.endsWith('*') ? String(name).startsWith(m.slice(0, -1)) : name === m;
}

// Gives an instance its own copy of every material a rule matches and sets the rule's values.
export function applyLook(instance, rules) {
    if (!rules || !rules.length) {
        return;
    }
    const owned = new Set(instance.materials);
    const copies = new Map();
    instance.root.traverse((obj) => {
        if (!obj.isMesh) {
            return;
        }
        const swap = (mat) => {
            const hit = rules.filter((r) => matches(r, mat.name));
            if (!hit.length) {
                return mat;
            }
            let copy = copies.get(mat);
            if (!copy) {
                copy = owned.has(mat) ? mat : mat.clone();
                if (copy !== mat) {
                    instance.materials.push(copy);
                }
                for (const r of hit) {
                    if (r.baseColor && copy.color) {
                        copy.color.setRGB(...r.baseColor.map((c) => c / 255), THREE.SRGBColorSpace);
                    }
                    if (r.emissive && copy.emissive) {
                        copy.emissive.setRGB(...r.emissive.map((c) => c / 255), THREE.SRGBColorSpace);
                    }
                    for (const key of ['roughness', 'metalness', 'emissiveIntensity']) {
                        if (r[key] != null && key in copy) {
                            copy[key] = r[key];
                        }
                    }
                    if (r.opacity != null) {
                        copy.opacity = r.opacity;
                        copy.transparent = r.opacity < 1;
                    }
                }
                copies.set(mat, copy);
            }
            return copy;
        };
        obj.material = Array.isArray(obj.material) ? obj.material.map(swap) : swap(obj.material);
    });
}

// What drawing an object costs, its draw calls, triangles and textures.
export function measure(object) {
    let drawCalls = 0;
    let triangles = 0;
    const textures = new Set();
    let textureBytes = 0;
    object.traverse((obj) => {
        if (!obj.isMesh) {
            return;
        }
        const g = obj.geometry;
        const groups = g.groups && g.groups.length ? g.groups.length : 1;
        drawCalls += groups;
        triangles += Math.floor((g.index ? g.index.count : (g.attributes.position ? g.attributes.position.count : 0)) / 3);
        for (const mat of Array.isArray(obj.material) ? obj.material : [obj.material]) {
            for (const value of Object.values(mat || {})) {
                if (value && value.isTexture && !textures.has(value)) {
                    textures.add(value);
                    const img = value.image;
                    textureBytes += img && img.width && img.height ? img.width * img.height * 4 : 0;
                }
            }
        }
    });
    return { drawCalls, triangles, textures: textures.size, textureBytes };
}

// Frees what an attachment holds of its own.
export function disposeObject(object) {
    object.removeFromParent();
    object.traverse((obj) => {
        if (obj.isMesh) {
            obj.geometry.dispose();
        }
    });
}

// The drawn anchor of an instance, the position of its root frame with the cosmetic offset.
export function anchorOf(cosmetic, out = [0, 0, 0]) {
    out[0] = cosmetic.elements[12];
    out[1] = cosmetic.elements[13];
    out[2] = cosmetic.elements[14];
    return out;
}

export { PLAYER_FLOATS };
