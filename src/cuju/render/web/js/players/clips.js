// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The celebration clips that a team uploads, binary glTF files with a skinned skeleton and one or
// more animations. Each animation is read at 30 frames a second on a rig of the clip's own
// skeleton, with the joint mapping that a custom model uses, and turned into GRF's nodes by
// retarget.js, so it plays on GRF's player and on any model as the procedural moves do.
//
// A team's style names an animation by the prefix upload, the clip's name and the animation's
// index, as PREFIX below shows. Two teams may hold clips of the same name, so while a match plays
// the names of each team's style carry the tag of that team as well, after a space.

import * as THREE from 'three';
import { api } from '../core/api.js';
import { Rig, fileBoneNames, guessJoints, parseModel } from './players.js';
import {
    FPS, MAX_SECONDS, REST_BODY_HEIGHT, forgetUploads, hasUpload, nodeClip, registerUpload,
} from './retarget.js';

export const MAX_CLIP_BYTES = 10 * 1024 * 1024;
export const MAX_TEAM_CLIP_BYTES = 40 * 1024 * 1024;
export const MAX_CLIPS = 16;
const PREFIX = 'upload:';
// Windows opens a device for these names, the server refuses them as clip names.
const DEVICES = /^(con|prn|aux|nul|com[0-9]|lpt[0-9])$/;

export function isUploadName(name) {
    return typeof name === 'string' && name.startsWith(PREFIX);
}

// The name of a clip made from the name of its file, lower case letters, digits and underscores.
export function clipNameOf(filename) {
    let name = String(filename || '').replace(/\.glb$/i, '').toLowerCase()
        .replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40);
    if (!name || DEVICES.test(name)) {
        name = `clip_${name}`.replace(/_+$/, '').slice(0, 40) || 'clip';
    }
    return name;
}

// The celebrations a team's clips offer, each its name in a style and the animation's name.
export function uploadMoves(team) {
    const clips = team && Array.isArray(team.clips) ? team.clips : [];
    return clips.flatMap((c) => (c.animations || []).map((label, i) => [`${PREFIX}${c.name}.${i}`, label, c.name]));
}

// The animation's name of a celebration that names a team's clip, or null.
export function uploadMoveLabel(team, value) {
    const found = uploadMoves(team).find(([v]) => v === value);
    return found ? found[1] : null;
}

// Checks the bytes of a clip as the server will, and reads it. Returns the parsed file, the names
// of its skinned bones and the mapping guessed from them, or throws an error to show.
export async function readClip(buffer) {
    if (buffer.byteLength > MAX_CLIP_BYTES) {
        throw new Error(`This clip is ${Math.ceil(buffer.byteLength / 1048576)} MB, the limit is 10 MB.`);
    }
    const gltf = await parseModel(buffer);
    const bones = fileBoneNames(gltf);
    if (!gltf.animations || !gltf.animations.length) {
        throw new Error('This file holds no animation. Export it with its animations, as described in the Help.');
    }
    return { gltf, bones, guess: guessJoints(bones) };
}

// Reads one animation of a parsed clip on the clip's own skeleton and returns a clip of nodes. The
// rig of the skeleton may be given, so the animations of one file share it.
export function retargetAnimation(gltf, animation, joints, rig = new Rig(gltf.scene, joints, {})) {
    const corrections = new Array(14).fill(null);
    const index = new Array(14).fill(-1);
    rig.bones.forEach((b, j) => {
        if (b.node > 0 && b.correction) {
            corrections[b.node] = b.correction.toArray();
            index[b.node] = j;
        }
    });
    // The rig places the pelvis this high above the clip's floor at rest, in its own frame.
    const floor = rig.bones[index[1]].position.y - rig.heightRatio * REST_BODY_HEIGHT;
    const instance = rig.instantiate();
    for (const b of instance.bones) {
        if (b) {
            b.matrixAutoUpdate = true;
            b.matrixWorldAutoUpdate = true;
        }
    }
    const mixer = new THREE.AnimationMixer(instance.root);
    const action = mixer.clipAction(animation);
    action.play();
    const duration = Math.min(MAX_SECONDS, Math.max(0, animation.duration || 0));
    const count = duration > 0 ? Math.max(2, Math.round(duration * FPS) + 1) : 1;
    const matrix = new THREE.Matrix4();
    const p = new THREE.Vector3();
    const q = new THREE.Quaternion();
    const s = new THREE.Vector3();
    const samples = [];
    try {
        for (let i = 0; i < count; i++) {
            const t = count > 1 ? (i / (count - 1)) * duration : 0;
            action.time = Math.max(0, Math.min(t, (animation.duration || 0) - 1e-4));
            mixer.update(0);
            instance.root.updateMatrixWorld(true);
            const bones = new Array(14).fill(null);
            let body = [0, 0, 0];
            for (let n = 1; n < 14; n++) {
                const j = index[n];
                const bone = j >= 0 ? instance.bones[j] : null;
                if (!bone) {
                    continue;
                }
                matrix.multiplyMatrices(rig.placement, bone.matrixWorld).decompose(p, q, s);
                bones[n] = q.toArray();
                if (n === 1) {
                    body = p.toArray();
                }
            }
            samples.push({ bones, body });
        }
    } finally {
        mixer.stopAllAction();
        mixer.uncacheRoot(instance.root);
        rig.release(instance);
    }
    return nodeClip(samples, { corrections, heightRatio: rig.heightRatio, floor }, duration);
}

// The tag of each team whose clips the page loaded, so the names of two teams never meet.
const tags = new Map();
const loads = new Map();

function tagOf(id) {
    if (!tags.has(id)) {
        tags.set(id, `c${tags.size + 1}`);
    }
    return tags.get(id);
}

// The name a celebration of a team plays under while its clips are loaded, the name itself for
// every other move.
export function qualify(value, tag) {
    if (!tag || !isUploadName(value)) {
        return value;
    }
    const name = `${value} ${tag}`;
    return hasUpload(name) ? name : value;
}

// The name in a style of a celebration that plays under a tagged name.
export function unqualify(name) {
    return isUploadName(name) ? name.replace(/ c\d+$/, '') : name;
}

// Gives the celebrations of a style the names their loaded clips play under, in place.
export function qualifyStyle(style, tag) {
    if (!style || !tag) {
        return style;
    }
    if (Array.isArray(style.celebrations)) {
        style.celebrations = style.celebrations.map((v) => qualify(v, tag));
    }
    for (const p of Array.isArray(style.players) ? style.players : []) {
        if (p && typeof p.celebration === 'string') {
            p.celebration = qualify(p.celebration, tag);
        }
    }
    return style;
}

// Loads the clips of a registry team and returns the team's tag, or null when it holds none.
// The clips load once while they stay the same, and a clip that fails is left out quietly, so its
// celebrations give way to the procedural moves.
export async function loadTeamClips(team) {
    if (!team || !team.id || !Array.isArray(team.clips) || !team.clips.length) {
        if (team && team.id && tags.has(team.id)) {
            forgetUploads(` ${tags.get(team.id)}`);
            loads.delete(team.id);
        }
        return null;
    }
    const tag = tagOf(team.id);
    const signature = JSON.stringify(team.clips);
    const cached = loads.get(team.id);
    if (cached && cached.signature === signature) {
        await cached.promise;
        return tag;
    }
    const entry = { signature, promise: null };
    loads.set(team.id, entry);
    entry.promise = (async () => {
        const made = [];
        for (const clip of team.clips) {
            try {
                const buffer = await api.clipBytes(team.id, clip.name);
                const { gltf, guess } = await readClip(buffer);
                const joints = clip.joints && clip.joints.body ? clip.joints : guess;
                if (!joints.body) {
                    console.warn('clip without a pelvis left out', clip.name);
                    continue;
                }
                const rig = new Rig(gltf.scene, joints, {});
                gltf.animations.forEach((animation, i) => {
                    try {
                        const label = (clip.animations && clip.animations[i]) || animation.name || `Animation ${i + 1}`;
                        made.push([`${PREFIX}${clip.name}.${i} ${tag}`, retargetAnimation(gltf, animation, joints, rig), label]);
                    } catch (err) {
                        console.warn('clip animation left out', clip.name, i, err);
                    }
                });
            } catch (err) {
                console.warn('clip left out', clip.name, err);
            }
        }
        // Only the newest load of a team registers its clips.
        if (loads.get(team.id) === entry) {
            forgetUploads(` ${tag}`);
            for (const [name, nodes, label] of made) {
                registerUpload(name, nodes, label);
            }
        }
    })();
    await entry.promise;
    return tag;
}
