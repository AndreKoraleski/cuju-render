// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Shirt numbers on the backs of player models other than GRF's, KayKit's characters and a team's
// own model. Each number is a small square of the atlas of numbers that rides the model's chest
// bone, placed once per model from its torso in GRF's rest pose, as number-patch.js measures it.
// A model whose torso is too small, or that a team lists among hidden_numbers, shows none.

import * as THREE from 'three';
import { backPatch, numberCell, numbersShown } from './number-patch.js';

// The patch of each rig, measured once, or null for a rig without room for a number.
const patches = new WeakMap();

// Where a number sits on a rig, as the index of the bone it rides, the bone mapped to GRF's
// middle node, else its body node, and the patch's matrix in that bone's frame. The torso is the
// bones mapped to the body and middle nodes with the bones below them that no other node moves,
// such as a spine between the two, so a cape or a pack on the back counts as the back.
function measure(rig, restNodes) {
    if (patches.has(rig)) {
        return patches.get(rig);
    }
    let patch = null;
    try {
        patch = measureRig(rig, restNodes);
    } catch (err) {
        console.warn('shirt number not placed', err);
    }
    patches.set(rig, patch);
    return patch;
}

function measureRig(rig, restNodes) {
    let bone = rig.bones.findIndex((b) => b.node === 2);
    if (bone < 0) {
        bone = rig.bones.findIndex((b) => b.node === 1);
    }
    if (bone < 0) {
        return null;
    }
    const torso = rig.bones.map((b, j) => {
        for (let i = j; i >= 0; i = rig.bones[i].parent) {
            if (rig.bones[i].node >= 0) {
                return rig.bones[i].node === 1 || rig.bones[i].node === 2;
            }
        }
        return false;
    });
    const inst = rig.instantiate();
    try {
        rig.pose(inst, restNodes, 0);
        const index = new Map(inst.bones.map((b, j) => [b, j]));
        const points = [];
        const v = new THREE.Vector4();
        const w = new THREE.Vector4();
        const m = new THREE.Matrix4();
        inst.root.traverse((obj) => {
            if (!obj.isSkinnedMesh) {
                return;
            }
            const g = obj.geometry;
            const pos = g.attributes.position;
            const si = g.attributes.skinIndex;
            const sw = g.attributes.skinWeight;
            if (!pos || !si || !sw) {
                return;
            }
            for (let i = 0; i < pos.count; i++) {
                let best = 0;
                for (let c = 1; c < 4; c++) {
                    if (sw.getComponent(i, c) > sw.getComponent(i, best)) {
                        best = c;
                    }
                }
                const j = index.get(obj.skeleton.bones[si.getComponent(i, best)]);
                if (j === undefined || !torso[j]) {
                    continue;
                }
                v.set(pos.getX(i), pos.getY(i), pos.getZ(i), 1).applyMatrix4(obj.bindMatrix);
                w.set(0, 0, 0, 0);
                for (let c = 0; c < 4; c++) {
                    const weight = sw.getComponent(i, c);
                    if (weight) {
                        const b = si.getComponent(i, c);
                        m.multiplyMatrices(obj.skeleton.bones[b].matrixWorld, obj.skeleton.boneInverses[b]);
                        w.addScaledVector(v.clone().applyMatrix4(m), weight);
                    }
                }
                points.push(w.x, w.y, w.z);
            }
        });
        const found = backPatch(points);
        if (!found) {
            return null;
        }
        const place = new THREE.Matrix4().compose(
            new THREE.Vector3(found.x, found.y, found.z), new THREE.Quaternion(),
            new THREE.Vector3(found.size, found.size, found.size));
        return { bone, local: inst.world[bone].clone().invert().multiply(place) };
    } finally {
        rig.release(inst);
    }
}

// The numbers of one set of posed models. Add gives a player a number, update follows the bones
// after every pose, and dispose frees the meshes and materials, never the shared atlas.
export class RigNumbers {
    constructor(parent, atlas, restNodes) {
        this.group = new THREE.Group();
        parent.add(this.group);
        this.atlas = atlas;
        this.restNodes = restNodes;
        this.materials = new Map();
        this.items = [];
    }

    // Gives a posed model a number on its back, when the team shows numbers on that model and
    // its torso holds one. Entry is the model's player, its rig and instance.
    add(entry, style, model, number, color) {
        if (!numbersShown(style, model)) {
            return;
        }
        const patch = measure(entry.rig, this.restNodes);
        if (!patch) {
            return;
        }
        const key = color.getHexString();
        if (!this.materials.has(key)) {
            this.materials.set(key, new THREE.MeshStandardMaterial({
                map: this.atlas, color, transparent: true, alphaTest: 0.4, roughness: 0.6,
                polygonOffset: true, polygonOffsetFactor: -2, depthWrite: false,
            }));
        }
        const geometry = new THREE.PlaneGeometry(1, 1);
        // The square faces minus z, the back, and reads from behind.
        geometry.rotateY(Math.PI);
        const [u0, v0, u1, v1] = numberCell(number);
        const uv = geometry.attributes.uv;
        for (let i = 0; i < uv.count; i++) {
            uv.setXY(i, uv.getX(i) ? u1 : u0, uv.getY(i) ? v1 : v0);
        }
        const mesh = new THREE.Mesh(geometry, this.materials.get(key));
        // Skinning places the models in the world from their bones alone, and so does the number.
        mesh.matrixAutoUpdate = false;
        mesh.matrixWorldAutoUpdate = false;
        mesh.frustumCulled = false;
        mesh.visible = false;
        this.group.add(mesh);
        this.items.push({ entry, mesh, bone: patch.bone, local: patch.local });
    }

    // Follows each model's chest as last posed, and hides the numbers of hidden models.
    update() {
        for (const item of this.items) {
            const instance = item.entry.instance;
            item.mesh.visible = instance.root.visible;
            if (item.mesh.visible) {
                item.mesh.matrixWorld.multiplyMatrices(instance.world[item.bone], item.local);
            }
        }
    }

    dispose() {
        this.group.removeFromParent();
        for (const item of this.items) {
            item.mesh.geometry.dispose();
        }
        for (const material of this.materials.values()) {
            material.dispose();
        }
        this.items = [];
        this.materials.clear();
    }
}
