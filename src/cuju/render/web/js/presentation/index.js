// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Team presentation packages on the page, as docs/presentation.md describes them. The page calls
// in at a few places, prepare as it resolves a team, attach once the players are built, update
// before they are drawn, pose for each player of a package as it is drawn, afterPose once the
// ball is drawn, afterRender once the picture is drawn, timeScale as the timeline plays, reset
// after a seek and reveal at the show's fanfares. Everything else of the contract lives in this
// folder, the effects, shaders, passes, sound, moments and reach of contract 1.1 in modules of
// their own.

import * as THREE from 'three';
import { NODES_FLOAT, PLAYER_FLOATS, isCut } from '../recording/format.js';
import { guessJoints, parseModel, rigFromGltf, skinnedBones } from '../players/players.js';
import { Animator, preferred } from './animator.js';
import { BehaviourSet, checkBehaviour, emptyOutputs } from './behaviors.js';
import { Budget, LADDER } from './budget.js';
import { CONTACT_KINDS, Catalog, contactEstimate } from './catalog.js';
import { Clocks } from './clocks.js';
import { SAFETY, checkOverlay, dispatch, dropped, handlerOf, reflexActions, reflexesFor, register } from './commands.js';
import {
    CONTRACT, FEATURES, driverOf, level, modelOf, normalize, pickClip, roleOf, seed, seedBase, selects,
} from './contract.js';
import { evaluate as evaluateCurve } from './values.js';
import { ModuleHost } from './host.js';
import { MAXIMUM_COMMANDS, appendLog, checkResponse, frameMessage, helloMessage } from './protocol.js';
import {
    anchorOf, applyLook, applyOutputs, boneIndex, disposeObject, matches, measure, poseLayers, rootFrame, socketMatrix,
    stopLayers, writeBones,
} from './stage.js';
import { Custody, Ledger } from './tracks.js';
import { clamp, hash, wrap } from './values.js';
import { Effects } from './effects.js';
import { FlashCounter, FlashGovernor } from './flash.js';
import { Moments } from './moments.js';
import { Post, TEAM_LAYERS } from './post.js';
import { bendBall, checkGeometry, reachWeight } from './reach.js';
import { chainOf, maskLayers, reach } from './rigging.js';
import { checkShader, extendMaterial, shaderMaterial, teamUniforms, tryCompile } from './shaders.js';
import { TeamAudio } from './teamaudio.js';
import { SIDES, readSides } from './assign.js';
import { t } from '../core/i18n.js';

const LINEUP_LENGTH = 9;
const tmpMatrix = new THREE.Matrix4();
const tmpVector = new THREE.Vector3();

function fileUrl(teamId, file) {
    return `/api/teams/${encodeURIComponent(teamId)}/presentation/${file.split('/').map(encodeURIComponent).join('/')}`;
}

async function fetchFile(teamId, file, kind = 'arrayBuffer') {
    const res = await fetch(fileUrl(teamId, file), { cache: 'no-store' });
    if (!res.ok) {
        throw new Error(`${file} answered ${res.status}`);
    }
    return res[kind]();
}

// The contact marker of each clip of a glTF file, from extras.cuju.markers of its animations.
function markersOf(gltf) {
    const out = new Map();
    const json = gltf.parser && gltf.parser.json;
    for (const a of (json && json.animations) || []) {
        const m = a.extras && a.extras.cuju && a.extras.cuju.markers;
        if (a.name && m && Number.isFinite(Number(m.contact))) {
            out.set(a.name, Number(m.contact));
        }
    }
    return out;
}

// One team's package as loaded, shared by every rebuild of the players while it stays the same.
class TeamPackage {
    constructor(side, team, served, manifest, key) {
        this.side = side;
        this.teamId = team.id;
        this.teamModel = team.model || null;
        this.key = key;
        this.served = served;
        this.manifest = manifest;
        this.developer = !!served.developer;
        this.files = new Set(served.files || []);
        this.levels = level(manifest);
        this.budget = new Budget('medium');
        this.rigs = new Map();
        this.markers = new Map();
        this.scenes = new Map();
        this.host = null;
        this.instanceId = null;
        this.status = 'loading';
        this.detail = '';
        this.events = [];
        this.errors = [];
        this.cues = new Map();
    }

    async loadModel(file, joints) {
        const gltf = await parseModel(await fetchFile(this.teamId, file));
        let mapping = joints;
        if (!mapping || !mapping.body) {
            const names = skinnedBones(gltf.scene).map((b) => b.name);
            mapping = { ...guessJoints(names), ...(mapping || {}) };
            if (!mapping.body && names.length) {
                mapping.body = names[0];
            }
        }
        const rig = rigFromGltf(gltf, mapping, { onlyKit: true });
        this.markers.set(file, markersOf(gltf));
        rig.presentationFile = file;
        return rig;
    }

    async load() {
        const m = this.manifest;
        const files = new Set([m.models.outfield, m.models.goalkeeper, ...Object.values(m.models.byNumber || {})].filter(Boolean));
        const joints = m.rig.joints || (this.teamModel && this.teamModel.joints) || null;
        // Each model file parses once, for its attachments and its mesh effects alike.
        const scenes = new Map();
        const sceneOf = (file) => {
            if (!scenes.has(file)) {
                scenes.set(file, fetchFile(this.teamId, file).then(parseModel).then((gltf) => gltf.scene));
            }
            return scenes.get(file);
        };
        const models = [...files].map(async (file) => {
            try {
                this.rigs.set(file, await this.loadModel(file, joints));
            } catch (err) {
                this.errors.push(`model ${file} not used, ${err.message || err}`);
            }
        });
        const attachments = Object.entries(m.rig.attachments || {}).map(async ([name, a]) => {
            try {
                this.scenes.set(name, (await sceneOf(a.file)).clone(true));
            } catch (err) {
                this.errors.push(`attachment ${name} not used, ${err.message || err}`);
            }
        });
        // The text of every shader the package names, checked again before anything compiles.
        this.shaders = new Map();
        const sources = new Map();
        for (const look of Object.values(m.materials || {})) {
            if (look && look.shader) {
                sources.set(look.shader, look.mode || 'chunks');
            }
        }
        for (const e of Object.values(m.effects || {})) {
            if (e && e.shader) {
                sources.set(e.shader, 'material');
            }
        }
        if (m.post && m.post.layer && m.post.layer.shader) {
            sources.set(m.post.layer.shader, 'material');
        }
        const shaders = [...sources].map(async ([file, mode]) => {
            try {
                const text = await fetchFile(this.teamId, file, 'text');
                const problems = checkShader(text, mode);
                if (problems.length) {
                    throw new Error(problems.join(', '));
                }
                this.shaders.set(file, text);
            } catch (err) {
                this.errors.push(`shader ${file} not used, ${err.message || err}`);
            }
        });
        this.effectScenes = new Map();
        const meshes = Object.values(m.effects || {}).filter((e) => e && e.type === 'mesh' && e.file).map(async (e) => {
            try {
                this.effectScenes.set(e.file, await sceneOf(e.file));
            } catch (err) {
                this.errors.push(`effect model ${e.file} not used, ${err.message || err}`);
            }
        });
        this.textures = new Map();
        const textures = Object.values(m.materials || {}).flatMap((look) => Object.values((look && look.textures) || {})).map(async (file) => {
            try {
                const bitmap = await createImageBitmap(new Blob([await fetchFile(this.teamId, file)]));
                const t = new THREE.Texture(bitmap);
                t.colorSpace = THREE.SRGBColorSpace;
                t.flipY = false;
                t.needsUpdate = true;
                this.textures.set(file, t);
            } catch (err) {
                this.errors.push(`texture ${file} not used, ${err.message || err}`);
            }
        });
        await Promise.all([...models, ...attachments, ...shaders, ...meshes, ...textures]);
        this.status = 'ready';
    }

    dispose() {
        this.disposed = true;
        if (this.host) {
            this.host.dispose();
            this.host = null;
        }
    }
}

// The presentation of one player of a package, his stable identity, seeds, behaviours, animator,
// bounds and attachments.
class Entity {
    constructor(pkg, entry, header, styles, base) {
        const p = header.players[entry.k];
        const style = styles[p.team] || styles[0];
        const roster = style && style.players ? style.players[p.index] : null;
        this.pkg = pkg;
        this.k = entry.k;
        this.id = `p${entry.k}`;
        this.side = p.team;
        this.index = p.index;
        this.goalkeeper = !!p.goalkeeper;
        this.number = roster && Number.isInteger(roster.number) ? roster.number : p.index + 1;
        this.roster = { name: roster ? roster.name || null : null, number: this.number, goalkeeper: this.goalkeeper, celebration: roster ? roster.celebration || null : null };
        const m = pkg.manifest;
        // GRF's figure plays no clip of a package, so it keeps GRF's own driver.
        this.driver = entry.rig && entry.rig.grf ? 'grf' : driverOf(m, this);
        this.seeds = { entity: seed(base, this.side, this.id), number: hash(`number:${this.number}`), index: hash(`index:${this.index}`) };
        this.envelope = m.rig.bounds ? { radius: m.rig.bounds.radius, height: m.rig.bounds.height } : null;
        this.current = null;
        this.behaviours = new BehaviourSet(this.seeds);
        for (const [i, spec] of m.behaviours.entries()) {
            if (selects(spec.when, this)) {
                try {
                    this.behaviours.set(checkBehaviour(spec, i), 'manifest');
                } catch (err) {
                    pkg.errors.push(`behaviour ${i} left out, ${err.message}`);
                }
            }
        }
        const rig = entry.rig;
        const markers = pkg.markers.get(rig.presentationFile) || new Map();
        this.animator = this.driver === 'team' || this.driver === 'worker'
            ? new Animator(m, (name) => {
                const c = rig.clip(name);
                return c ? { duration: c.duration, marker: markers.get(name) } : null;
            }, this.seeds.entity)
            : null;
        this.cosmetic = new THREE.Matrix4();
        this.frame = new THREE.Matrix4();
        this.anchor = [0, 0, 0];
        this.lastAnchor = null;
        this.ceremonyVelocity = [0, 0, 0];
        this.facing = 0;
        this.inputs = {};
        this.overlay = null;
        this.overlayWeight = 0;
        this.lastOverlay = null;
        this.outputs = emptyOutputs();
        this.attachments = [];
        this.visible = true;
        this.posed = false;
        this.distance = 0;
        this.lastDistance = null;
        // The contacts this player meets, for the reach of his chains.
        this.contacts = [];
    }

    bounds() {
        return this.current || this.envelope;
    }
}

export class Presentation {
    constructor(app) {
        this.app = app;
        this.clocks = new Clocks();
        this.ledger = new Ledger();
        this.custody = new Custody();
        this.packages = [null, null];
        this.loading = [null, null];
        this.entities = new Map();
        this.epoch = 0;
        this.resetInfo = { reason: 'source', fromT: 0, toT: 0 };
        this.frameId = 0;
        this.instances = 0;
        this.catalog = null;
        this.distances = null;
        this.open = new Map();
        this.memory = {};
        this.lastIndex = -1;
        this.mode = null;
        this.drop = { stale: 0, foreign: 0, malformed: 0, rejected: 0 };
        this.statusShown = new Set();
        // metering false holds every team at its rung, for authors and checks on slow machines.
        // bendBall auto bends the ball's drawn path while a package names bend.ball, true always.
        this.settings = { fullLookahead: false, metering: true, bendBall: 'auto', flashCheck: true };
        this.effects = new Effects(this);
        this.post = new Post(this);
        this.audio = new TeamAudio(this);
        this.moments = new Moments(this);
        this.flash = new FlashGovernor();
        this.counter = new FlashCounter(64, 36);
        this.flashCounts = { general: 0, red: 0 };
        this.uniforms = [teamUniforms(), teamUniforms()];
        this.pulse = [0, 0];
        this.recent = new Map();
        this.geometries = new Map();
        this.materialsBySide = [new Map(), new Map()];
        try {
            this.settings.fullLookahead = JSON.parse(localStorage.getItem('cuju.fullLookahead') || 'false') === true;
        } catch {
            // Storage can be unavailable, the setting then keeps its default.
        }
        // The handlers of every kind of command, the core's and those of contract 1.1.
        register('claims', (c, ctx) => this.claim(ctx.pkg, c));
        register('audio', (c, ctx) => this.audio.command(ctx.pkg, c, ctx.event));
        register('effects', (c, ctx) => this.effects.command(ctx.pkg, c, ctx.event));
        register('camera', (c, ctx) => this.hasFeature(ctx.pkg, 'camera.suggest') && this.moments.suggestCamera(ctx.pkg, c));
        register('time', (c, ctx) => this.hasFeature(ctx.pkg, 'time.suggest') && this.moments.suggestTime(ctx.pkg, c));
        register('environment', (c, ctx) => this.moments.moment(ctx.pkg, c));
        register('overlays', (c, ctx) => this.hasFeature(ctx.pkg, 'overlay.offscreen') && this.moments.overlay(ctx.pkg, c, ctx.bitmap || null));
        register('resources', (c, ctx) => this.resource(ctx.pkg, c));
    }

    // The url and the bytes of a file of a package.
    fileUrl(pkg, file) {
        return fileUrl(pkg.teamId, file);
    }

    fetchFile(pkg, file, kind = 'arrayBuffer') {
        return fetchFile(pkg.teamId, file, kind);
    }

    // Whether a package names a feature among those it requires or prefers, which turns on the
    // parts of contract 1.1 that change shared things.
    hasFeature(pkg, feature) {
        const m = pkg && pkg.manifest;
        return !!m && (m.requires.includes(feature) || m.prefers.includes(feature));
    }

    sharedUniforms(side) {
        return this.uniforms[side];
    }

    shaderSource(pkg, file) {
        return pkg.shaders ? pkg.shaders.get(file) || null : null;
    }

    // A whole shader material of a package, once per file, counted against its shader budget and
    // compiled before it draws. A shader that fails falls back with a notice.
    customMaterial(pkg, file, options = {}) {
        if (!this.hasFeature(pkg, 'shader.custom') || pkg.budget.past('standardMaterials')) {
            return null;
        }
        pkg.customMaterials = pkg.customMaterials || new Map();
        const key = `${file}:${options.blending || 'normal'}`;
        if (pkg.customMaterials.has(key)) {
            return pkg.customMaterials.get(key);
        }
        const source = this.shaderSource(pkg, file);
        let material = null;
        if (source && this.program(pkg, file, 'material')) {
            material = shaderMaterial(source, { shared: this.uniforms[pkg.side], seed: hash(`${pkg.side}:${file}`), ...options });
            if (!tryCompile(this.app.view && this.app.view.renderer, material, this.app.view && this.app.view.camera)) {
                this.notice(t('presentation.notice.shader', { team: pkg.manifest.name || t('presentation.notice.aTeam') }));
                pkg.errors.push(`shader ${file} did not compile`);
                material.dispose();
                material = null;
            }
        }
        pkg.customMaterials.set(key, material);
        return material;
    }

    // Takes a program of the shader budget for a file and mode once, returns whether it fits.
    program(pkg, file, mode) {
        pkg.programs = pkg.programs || new Set();
        const key = `${file}:${mode}`;
        if (pkg.programs.has(key)) {
            return true;
        }
        if (!pkg.budget.take({ shaders: 1 })) {
            pkg.errors.push(`shader ${file} is past the team's budget of programs`);
            return false;
        }
        pkg.programs.add(key);
        return true;
    }

    // The flash governor's factor on every team effect now, 1 unless its backstop clamps.
    flashFactor() {
        return this.flash.factor(this.clocks.cosmetic);
    }

    // The occlusion rule is relaxed while the ball is dead and in ceremonies.
    relaxed() {
        const tl = this.app.timeline;
        const f = tl && tl.store ? tl.store.get(tl.index) : null;
        return this.clocks.ceremonyStep > 0 || !!(f && f.gameMode !== 0);
    }

    // Whether the package's team had one of these events within the last seconds of play.
    recentOwn(pkg, kinds, seconds) {
        for (const e of this.recent.values()) {
            if (e.team === pkg.side && kinds.includes(e.kind) && this.clocks.cosmetic - (e.seenAt ?? -Infinity) <= seconds) {
                return true;
            }
        }
        return false;
    }

    // Where a sound of a package plays from in three's frame, its socket or player, or null.
    audioPosition(pkg, c, event) {
        if (!c.attach || !this.effects.teams[pkg.side]) {
            return null;
        }
        const v = this.effects.resolve(this.effects.teams[pkg.side], { attach: c.attach, event, params: {} }, new THREE.Vector3());
        return v ? { x: v.x, y: v.y, z: v.z } : null;
    }

    // The lights of the manifest on this drawing, one for each visible player each selects.
    manifestLights(pkg) {
        const out = [];
        const lights = pkg.manifest.lights || {};
        if (!Object.keys(lights).length) {
            return out;
        }
        for (const entity of this.entities.values()) {
            if (entity.pkg !== pkg || !entity.visible) {
                continue;
            }
            const entry = this.entryOf(entity.k);
            for (const [name, l] of Object.entries(lights)) {
                if (!selects(l.when, entity)) {
                    continue;
                }
                const socket = l.socket !== 'root' ? pkg.manifest.rig.sockets[l.socket] : null;
                if (socket && entry) {
                    socketMatrix(entry.rig, entry.instance, socket, entity.cosmetic, tmpMatrix);
                } else {
                    tmpMatrix.copy(entity.cosmetic);
                }
                const pos = new THREE.Vector3(...l.offset).applyMatrix4(tmpMatrix);
                let intensity = l.intensity;
                let distance = l.distance;
                for (const o of entity.outputs.lights || []) {
                    if (o.light === name) {
                        if (o.param === 'distance') {
                            distance += (o.value - distance) * o.weight;
                        } else {
                            intensity += (o.value - intensity) * o.weight;
                        }
                    }
                }
                out.push({ id: `${entity.id}:${name}`, pos, color: l.color, intensity: Math.max(0, intensity), distance: Math.max(0.5, distance), decay: l.decay, kind: l.kind });
            }
        }
        return out;
    }

    // The local lights of a team in the view space of the camera, for its materials.
    setLocalLights(side, list) {
        const u = this.uniforms[side];
        const camera = this.app.view ? this.app.view.camera : null;
        if (!camera) {
            return;
        }
        camera.updateMatrixWorld();
        const view = camera.matrixWorldInverse;
        for (let i = 0; i < u.cujuLocalPos.value.length; i++) {
            const l = list[i];
            if (l) {
                u.cujuLocalPos.value[i].copy(l.pos).applyMatrix4(view);
                const c = l.color;
                const k = l.level / 4;
                u.cujuLocalColor.value[i].set((c[0] / 255) ** 2.2 * k, (c[1] / 255) ** 2.2 * k, (c[2] / 255) ** 2.2 * k);
                u.cujuLocalRange.value[i] = l.distance;
            } else {
                u.cujuLocalColor.value[i].set(0, 0, 0);
            }
        }
    }

    // A resource of a worker, a geometry it built, checked and counted, or the end of one.
    resource(pkg, c) {
        if (c.op === 'dispose') {
            const g = this.geometries.get(`${pkg.side}:${c.id}`);
            if (g) {
                this.dropGeometry(pkg, `${pkg.side}:${c.id}`, g);
            }
            return !!g;
        }
        if (c.op !== 'geometry' || !this.hasFeature(pkg, 'geometry.worker')) {
            return false;
        }
        let geo;
        try {
            geo = checkGeometry(c);
        } catch (err) {
            pkg.errors.push(`geometry ${c.id} refused, ${err.message}`);
            return false;
        }
        const key = `${pkg.side}:${geo.id}`;
        const old = this.geometries.get(key);
        if (old) {
            this.dropGeometry(pkg, key, old);
        }
        if (!pkg.budget.take({ triangles: geo.triangles, geometryBytes: geo.bytes, drawCalls: 1 })) {
            pkg.errors.push(`geometry ${geo.id} is past the team's budget`);
            return false;
        }
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.BufferAttribute(geo.positions, 3));
        if (geo.normals) {
            g.setAttribute('normal', new THREE.BufferAttribute(geo.normals, 3));
        }
        if (geo.uvs) {
            g.setAttribute('uv', new THREE.BufferAttribute(geo.uvs, 2));
        }
        if (geo.colors) {
            g.setAttribute('color', new THREE.BufferAttribute(geo.colors, geo.colorSize));
        }
        if (geo.indices) {
            g.setIndex(new THREE.BufferAttribute(geo.indices, 1));
        }
        if (!geo.normals) {
            g.computeVertexNormals();
        }
        const spec = c.material && typeof c.material === 'object' ? c.material : {};
        const color = Array.isArray(spec.color) ? spec.color : [220, 220, 220];
        const emissive = Array.isArray(spec.emissive) ? spec.emissive : [0, 0, 0];
        let material = spec.shader ? this.customMaterial(pkg, String(spec.shader)) : null;
        if (material) {
            material = material.clone();
        } else {
            material = new THREE.MeshStandardMaterial({ vertexColors: !!geo.colors, transparent: (spec.opacity ?? 1) < 1, opacity: clamp(Number(spec.opacity ?? 1) || 0, 0, 1) });
            material.color.setRGB(...color.map((x) => clamp(Number(x) || 0, 0, 255) / 255), THREE.SRGBColorSpace);
            material.emissive.setRGB(...emissive.map((x) => clamp(Number(x) || 0, 0, 255) / 255), THREE.SRGBColorSpace);
        }
        const mesh = new THREE.Mesh(g, material);
        mesh.matrixAutoUpdate = false;
        mesh.frustumCulled = false;
        mesh.layers.enable(TEAM_LAYERS[pkg.side]);
        this.app.view.scene.add(mesh);
        this.geometries.set(key, { mesh, attach: c.attach || 'self', entity: c.entity || null, socket: typeof c.attach === 'string' && c.attach.startsWith('socket:') ? c.attach.slice(7) : null, cost: { triangles: geo.triangles, geometryBytes: geo.bytes, drawCalls: 1 }, pkg });
        return true;
    }

    dropGeometry(pkg, key, g) {
        g.mesh.removeFromParent();
        g.mesh.geometry.dispose();
        g.mesh.material.dispose();
        pkg.budget.give(g.cost);
        this.geometries.delete(key);
    }

    // Loads the package of the team on side, or drops it, while the page resolves the team, and
    // adds the rigs of its models to the team's table of rigs.
    async prepare(side, team, style, table) {
        const read = async (id) => {
            try {
                const res = await fetch(`/api/teams/${encodeURIComponent(id)}/presentation`, { cache: 'no-store' });
                return res.ok ? await res.json() : null;
            } catch {
                return null;
            }
        };
        // A side may draw the package of a team the viewer chose for it, section Q11. The choice
        // and the playing team's package are read together.
        const [sides, own] = await Promise.all([
            side === 0 || !this.sides ? readSides() : this.sides,
            team && team.id ? read(team.id) : null,
        ]);
        this.sides = sides;
        let served = own;
        const chosen = sides[SIDES[side]];
        if (chosen && (!team || team.id !== chosen)) {
            team = { id: chosen, name: team && team.name, model: null, assigned: true };
            served = await read(chosen);
        }
        const manifest = served ? normalize(served.manifest) : null;
        const key = manifest ? `${team.id}:${JSON.stringify(served)}` : null;
        let pkg = this.packages[side];
        if (pkg && (pkg.key !== key || pkg.developer)) {
            pkg.dispose();
            pkg = null;
            this.packages[side] = null;
        }
        if (!pkg && manifest) {
            // Rebuilds that overlap share one load of the same package.
            let pending = this.loading[side];
            if (!pending || pending.key !== key) {
                pending = { key, promise: this.load(side, team, served, manifest, key) };
                this.loading[side] = pending;
            }
            pkg = await pending.promise;
            if (this.loading[side] === pending) {
                this.loading[side] = null;
            }
        }
        if (this.packages[side] && this.packages[side] !== pkg) {
            this.packages[side].dispose();
        }
        this.packages[side] = pkg || null;
        if (!pkg) {
            return;
        }
        for (const [file, rig] of pkg.rigs) {
            table.set(`pkg:${file}`, rig);
        }
        style.presentation = { developer: pkg.developer, pkg };
    }

    async load(side, team, served, manifest, key) {
        const pkg = new TeamPackage(side, team, served, manifest, key);
        if (pkg.levels.level === 'stock') {
            this.notice(t('presentation.notice.stock', { team: team.name || t('presentation.notice.aTeam'), missing: pkg.levels.missing.join(', ') }));
            return null;
        }
        await pkg.load();
        for (const w of [...(served.warnings || []), ...pkg.errors]) {
            console.warn(`presentation of ${team.name || team.id}:`, w);
        }
        if (pkg.levels.missing.length) {
            this.notice(t('presentation.notice.noWorker', { team: team.name || t('presentation.notice.aTeam'), missing: pkg.levels.missing.join(', ') }));
        }
        return pkg;
    }

    // A notice for people, as a text or as the id and values of a message, which a module that
    // loads without the page's messages sends.
    notice(text) {
        if (text && typeof text === 'object') {
            text = t(text.id, text.values);
        }
        if (!this.statusShown.has(text)) {
            this.statusShown.add(text);
            if (this.app.hud) {
                this.app.hud.toast(text, 'info', 4000);
            }
        }
    }

    // The model a header player draws by his team's package, or null for the team's choice.
    modelFor(p, style) {
        const pkg = style && style.presentation ? style.presentation.pkg : null;
        if (!pkg) {
            return null;
        }
        const roster = style.players ? style.players[p.index] : null;
        const number = roster && Number.isInteger(roster.number) ? roster.number : p.index + 1;
        const file = modelOf(pkg.manifest, { goalkeeper: !!p.goalkeeper, number, index: p.index });
        return file && pkg.rigs.has(file) ? `pkg:${file}` : null;
    }

    // Builds the presentation of every player of a package once the page built its players.
    attach(players, header, styles) {
        this.players = players;
        this.header = header;
        this.styles = styles;
        this.entities.clear();
        this.base = seedBase(header);
        const tl = this.app.timeline;
        const any = !!(this.packages[0] || this.packages[1]);
        this.catalog = tl && any ? new Catalog(tl.store, { fullLookahead: this.settings.fullLookahead, live: !!tl.live }) : null;
        this.distances = new Map();
        this.ledger = new Ledger();
        this.custody.reset();
        this.open.clear();
        this.memory = {};
        this.lastIndex = -1;
        this.newEpoch('source');
        const quality = this.app.settings ? this.app.settings.quality : 'medium';
        for (const pkg of this.packages) {
            if (pkg) {
                pkg.budget.setQuality(quality);
                pkg.budget.used = Object.fromEntries(Object.keys(pkg.budget.used).map((k) => [k, 0]));
                pkg.programs = new Set();
                this.startWorker(pkg);
                // The meter reads the package once it settled, after its worker's first answer,
                // or a second after the players were built for a package without a worker, so
                // the page's own loading never counts against the team.
                pkg.budget.arm(pkg.host || pkg.hostPending ? Infinity : this.clocks.cosmetic + 1);
            }
        }
        const entries = players.packageEntries ? players.packageEntries() : [];
        for (const { entry: e, group } of entries) {
            const pkg = this.packages[e.team];
            if (!pkg) {
                continue;
            }
            const entity = new Entity(pkg, e, header, styles, this.base);
            e.presentation = entity;
            this.entities.set(entity.id, entity);
            this.dress(pkg, entity, e, group);
            this.emit({ kind: 'appearance', team: entity.side, player: entity.k, data: { player: entity.k } });
        }
        for (const pkg of this.packages) {
            if (pkg && pkg.developer) {
                this.notice(t('presentation.notice.developer', { team: pkg.manifest.name || t('presentation.notice.aTeam') }));
            }
        }
        for (const [key, g] of this.geometries) {
            this.dropGeometry(g.pkg, key, g);
        }
        this.moments.end();
        this.moments.disposeSlots();
        if (this.app.view) {
            this.effects.attach(this.app.view.scene, this.packages);
            for (const team of this.effects.teams) {
                if (team) {
                    team.group.traverse((o) => o.layers.enable(TEAM_LAYERS[team.side]));
                }
            }
        }
        this.post.attach(this.packages);
        this.audio.attach(this.packages);
        styles.forEach((style, side) => {
            const kit = style && style.kit;
            if (kit && Array.isArray(kit.primary)) {
                this.uniforms[side].uTeamColor.value.setRGB(...kit.primary.map((c) => c / 255), THREE.SRGBColorSpace);
            }
            if (kit && Array.isArray(kit.secondary)) {
                this.uniforms[side].uTeamColor2.value.setRGB(...kit.secondary.map((c) => c / 255), THREE.SRGBColorSpace);
            }
        });
    }

    // What the page draws of player k for a package, the entry of his rigged model or of GRF's
    // figure, or null.
    entryOf(k) {
        return this.players && this.players.packageEntry ? this.players.packageEntry(k) : null;
    }

    // A player's look, the material looks that select him, his shaders and his attachments.
    dress(pkg, entity, e, parent) {
        for (const [name, look] of Object.entries(pkg.manifest.materials)) {
            if (look && Array.isArray(look.rules) && selects(look.when, entity)) {
                applyLook(e.instance, look.rules);
            } else if (look && !look.rules && selects(look.when, entity)) {
                applyLook(e.instance, [{ match: look.match || name, ...look }]);
            }
        }
        this.shade(pkg, entity, e.instance, e.rig);
        e.instance.root.traverse((o) => o.layers.enable(TEAM_LAYERS[pkg.side]));
        for (const [name, spec] of Object.entries(pkg.manifest.rig.attachments || {})) {
            const scene = pkg.scenes.get(name);
            if (!scene || !selects(spec.when, entity)) {
                continue;
            }
            const object = scene.clone(true);
            const cost = measure(object);
            if (!pkg.budget.take({ drawCalls: cost.drawCalls, triangles: cost.triangles, textureBytes: cost.textureBytes })) {
                pkg.errors.push(`attachment ${name} is past the team's budget`);
                continue;
            }
            object.matrixAutoUpdate = false;
            object.traverse((obj) => {
                obj.layers.enable(TEAM_LAYERS[pkg.side]);
                if (obj.isMesh) {
                    obj.castShadow = spec.shadows !== false;
                    obj.receiveShadow = spec.shadows !== false;
                    obj.frustumCulled = false;
                    // Each attachment owns its materials, which behaviours may drive.
                    obj.material = Array.isArray(obj.material) ? obj.material.map((m) => m.clone()) : obj.material.clone();
                }
            });
            this.shade(pkg, entity, { root: object, materials: [] }, null);
            parent.add(object);
            const r = (spec.rotation || [0, 0, 0]).map((d) => d * Math.PI / 180);
            const s = spec.scale || 1;
            const local = new THREE.Matrix4().compose(new THREE.Vector3(...(spec.offset || [0, 0, 0])), new THREE.Quaternion().setFromEuler(new THREE.Euler(...r)), new THREE.Vector3(s, s, s));
            entity.attachments.push({ name, object, socket: spec.socket || 'root', local, cost });
        }
    }

    // Gives the standard materials of an instance the team's chunk, the hooks of its chunks
    // shaders and its local lights, on copies the instance owns, kept beside the originals so the
    // degrade ladder can hand back the standard look.
    shade(pkg, entity, instance, rig) {
        const m = pkg.manifest;
        const lights = Object.values(m.lights || {}).length > 0 || Object.values(m.effects || {}).some((x) => x.type === 'light');
        const looks = Object.entries(m.materials || {}).filter(([, look]) => look && look.shader && (look.mode || 'chunks') === 'chunks' && selects(look.when, entity));
        const custom = this.hasFeature(pkg, 'shader.custom') && !pkg.budget.past('standardMaterials');
        if (!lights && !(custom && looks.length)) {
            return;
        }
        const originals = instance.cujuOriginals || (instance.cujuOriginals = []);
        instance.root.traverse((obj) => {
            if (!obj.isMesh) {
                return;
            }
            const swap = (mat) => {
                if (!mat || !mat.isMeshStandardMaterial || (mat.userData && mat.userData.cuju)) {
                    return mat;
                }
                let hit = custom ? looks.find(([name, look]) => matches({ match: look.match || name }, mat.name)) : null;
                let source = hit ? this.shaderSource(pkg, hit[1].shader) : null;
                if (hit && source && !this.program(pkg, hit[1].shader, 'chunks')) {
                    return mat;
                }
                const textures = hit ? Object.fromEntries(Object.entries(hit[1].textures || {}).map(([k, f]) => [k, pkg.textures && pkg.textures.get(f)]).filter(([, t]) => t)) : null;
                const options = () => ({
                    shared: this.uniforms[pkg.side], seed: entity.seeds.entity, source,
                    spec: hit ? { ...hit[1], seeds: entity.seeds } : null, textures, key: hit ? `${pkg.side}:${hit[1].shader}` : `${pkg.side}:local`,
                });
                // A chunks shader that does not compile leaves the material standard, with only
                // the local lights when the package has lights, and the page names it once.
                if (hit && source && !this.chunksCompile(pkg, hit[1].shader, mat, options())) {
                    hit = null;
                    source = null;
                    if (!lights) {
                        return mat;
                    }
                }
                const copy = extendMaterial(mat, options());
                // GRF's figure keeps its own edit of the program, the head it hides.
                if (instance.repatch) {
                    instance.repatch(mat, copy);
                }
                originals.push({ obj, original: mat, copy });
                if (instance.materials) {
                    instance.materials.push(copy);
                }
                this.materialsBySide[pkg.side].set(copy, entity);
                return copy;
            };
            obj.material = Array.isArray(obj.material) ? obj.material.map(swap) : swap(obj.material);
        });
    }

    // Whether a chunks shader of a package compiles, tried once for each file on a copy of the
    // first material it extends. A shader that fails is named in a notice and in the package's
    // errors, and the materials it would extend stay standard.
    chunksCompile(pkg, file, material, options) {
        pkg.chunksCompiled = pkg.chunksCompiled || new Map();
        if (!pkg.chunksCompiled.has(file)) {
            const copy = extendMaterial(material, options);
            const view = this.app.view;
            const logs = [];
            const ok = tryCompile(view && view.renderer, copy, view && view.camera, null, logs);
            copy.dispose();
            if (!ok) {
                this.notice(t('presentation.notice.shader', { team: pkg.manifest.name || t('presentation.notice.aTeam') }));
                pkg.errors.push(`shader ${file} did not compile`);
                console.warn(`presentation of ${pkg.manifest.name || pkg.teamId}: shader ${file} did not compile`, ...logs);
            }
            pkg.chunksCompiled.set(file, ok);
        }
        return pkg.chunksCompiled.get(file);
    }

    // Hands the standard materials back to every player of a package, the ladder's rung
    // standardMaterials.
    unshade(pkg) {
        for (const entity of this.entities.values()) {
            if (entity.pkg !== pkg) {
                continue;
            }
            const entry = this.entryOf(entity.k);
            for (const o of (entry && entry.instance.cujuOriginals) || []) {
                o.obj.material = Array.isArray(o.obj.material) ? o.obj.material.map((m) => (m === o.copy ? o.original : m)) : (o.obj.material === o.copy ? o.original : o.obj.material);
            }
        }
    }

    // Gives the package's own materials back to every player of a package, as the ladder climbs
    // back past standardMaterials.
    reshade(pkg) {
        for (const entity of this.entities.values()) {
            if (entity.pkg !== pkg) {
                continue;
            }
            const entry = this.entryOf(entity.k);
            for (const o of (entry && entry.instance.cujuOriginals) || []) {
                o.obj.material = Array.isArray(o.obj.material) ? o.obj.material.map((m) => (m === o.original ? o.copy : m)) : (o.obj.material === o.original ? o.copy : o.obj.material);
            }
        }
    }

    startWorker(pkg) {
        const m = pkg.manifest;
        if (!m.worker || pkg.levels.level !== 'worker' || pkg.budget.past('noWorker') || ((pkg.host || pkg.hostPending) && !pkg.developer)) {
            return;
        }
        if (pkg.host) {
            pkg.host.dispose();
            pkg.host = null;
        }
        // Only the newest start of a package creates its host, an older one that resolves late
        // leaves it alone.
        const token = (pkg.starting || 0) + 1;
        pkg.starting = token;
        pkg.hostPending = true;
        this.instances += 1;
        pkg.instanceId = `${pkg.side}.${this.instances}`;
        pkg.events = [];
        const start = (source) => {
            if (pkg.starting !== token || pkg.disposed) {
                return;
            }
            pkg.hostPending = false;
            pkg.host = new ModuleHost({
                source,
                url: fileUrl(pkg.teamId, m.worker),
                instanceId: pkg.instanceId,
                developer: pkg.developer,
                context: pkg.developer ? { app: this.app, THREE } : null,
                hello: this.hello(pkg),
                onResponse: (msg) => this.respond(pkg, msg),
                onStatus: (status, detail) => this.workerStatus(pkg, status, detail),
            });
        };
        if (pkg.developer) {
            start(null);
        } else {
            fetchFile(pkg.teamId, m.worker, 'text').then(start).catch((err) => {
                pkg.hostPending = false;
                this.workerStatus(pkg, 'failed', `the worker did not load, ${err.message}`);
            });
        }
    }

    hello(pkg) {
        const header = this.header;
        const style = this.styles ? this.styles[pkg.side] : null;
        return helloMessage({
            features: Object.keys(FEATURES), lacking: pkg.levels.lacking, limits: pkg.budget.limits, quality: pkg.budget.quality,
            reducedMotion: !!this.app.reducedMotion, instanceId: pkg.instanceId, team: pkg.side, attack: pkg.side === 0 ? 1 : -1,
            roster: header.players.map((p, k) => ({ player: k, team: p.team, index: p.index, goalkeeper: !!p.goalkeeper }))
                .filter((p) => p.team === pkg.side).map((p) => ({ ...p, ...(style && style.players && style.players[p.index] ? { name: style.players[p.index].name, number: style.players[p.index].number } : {}) })),
            header: { format: header.players.length > 10 ? '11v11' : '5v5', scenario: header.scenario || null, sps: header.steps_per_second || 10, provenance: header.provenance || null },
            seedBase: this.base,
            slots: Object.keys(pkg.manifest.overlays || {}),
        });
    }

    // A worker that failed or restarts hands what it drove back to the manifest's own look,
    // faded so nothing snaps.
    workerStatus(pkg, status, detail) {
        // A worker that failed for good keeps its status and reason, a later disposal included.
        if (pkg.status === 'failed') {
            return;
        }
        pkg.status = status;
        pkg.detail = detail;
        if (status === 'failed') {
            // The team draws its manifest alone from now on, and the viewer learns why.
            pkg.levels.level = pkg.levels.level === 'stock' ? 'stock' : 'manifest';
            this.notice(t('presentation.notice.workerStopped', { team: pkg.manifest.name || t('presentation.notice.aTeam'), detail }));
        }
        if (status === 'stopped') {
            this.notice(t('presentation.notice.workerResting', { team: pkg.manifest.name || t('presentation.notice.aTeam') }));
        }
        if (status === 'failed' || status === 'stopped') {
            // The meter goes on reading the package without its worker.
            pkg.budget.armAt = Math.min(pkg.budget.armAt, this.clocks.cosmetic + 1);
        }
        if (status === 'restarting' || status === 'failed' || status === 'stopped') {
            console.warn(`presentation worker of ${pkg.manifest.name || pkg.teamId} ${status}, ${detail}`);
            for (const entity of this.entities.values()) {
                if (entity.pkg === pkg) {
                    entity.behaviours.stopSource('worker', 0.5);
                    entity.current = null;
                }
            }
            this.ledger.dropSource(`worker:${pkg.side}`);
            if (status === 'failed') {
                pkg.budget.stopWorker(detail);
            }
            this.newEpoch('package', false);
        }
    }

    // A new epoch for a reason. Transient effects die, tracks and persistent behaviours survive.
    newEpoch(reason, catalog = true) {
        this.epoch += 1;
        const t = this.app.timeline ? this.app.timeline.t / (this.app.timeline.sps || 10) : 0;
        this.resetInfo = { reason, fromT: this.clocks.sim, toT: t };
        this.resetPending = true;
        if (catalog && this.catalog && reason !== 'source') {
            this.pushEvents(this.catalog.reset(reason));
        }
        this.custody.reset();
        for (const entity of this.entities.values()) {
            entity.behaviours.reset();
            entity.lastAnchor = null;
            entity.ceremonyVelocity = [0, 0, 0];
        }
        for (const pkg of this.packages) {
            if (pkg) {
                pkg.events = pkg.events.filter((e) => e.phase === 'cancel');
            }
        }
        this.effects.endTransient();
        this.post.endTransient();
        this.moments.end();
        this.audio.stop();
        for (const entity of this.entities.values()) {
            entity.contacts = [];
        }
    }

    // A seek of the page, after the timeline moved.
    reset(reason = 'seek') {
        this.clocks.seek();
        this.newEpoch(reason);
        this.resync = true;
    }

    // A presentation or transport event, with an id stable across replays.
    emit(e) {
        const step = this.app.timeline ? Math.floor(this.app.timeline.t) : 0;
        const event = {
            id: `${e.kind}:${step}:${hash(`${e.kind}|${step}|${e.player ?? e.team ?? ''}|${e.key || ''}`).toString(16)}`,
            kind: e.kind, phase: 'occur', revision: 0, step, t: this.clocks.sim, lead: 0,
            team: e.team, player: e.player, subjects: e.subjects, provenance: e.provenance || 'presentation',
            replay: this.replaying ? { of: this.replayOf || null, angle: null, speed: this.app.timeline ? this.app.timeline.speed : 1 } : undefined,
            data: e.data || {},
        };
        this.pushEvents([event]);
        return event;
    }

    pushEvents(events) {
        for (const event of events) {
            if (event.phase === 'occur' || event.phase === 'forecast') {
                this.recent.set(event.id, { ...event, seenAt: this.clocks.cosmetic });
                while (this.recent.size > 128) {
                    this.recent.delete(this.recent.keys().next().value);
                }
            }
            if (event.phase === 'occur' && (event.team === 0 || event.team === 1) && ['touch', 'goal', 'shot', 'save', 'celebration.begin', 'winner.reveal', 'mvp.reveal'].includes(event.kind)) {
                this.pulse[event.team] = 1;
            }
            if (event.kind === 'halftime' && event.phase === 'occur') {
                this.effects.halftime();
            }
            for (const pkg of this.packages) {
                if (pkg) {
                    this.audio.event(pkg, event);
                }
            }
            for (const pkg of this.packages) {
                if (!pkg) {
                    continue;
                }
                if (pkg.host) {
                    pkg.events.push(event);
                    if (pkg.events.length > 1024) {
                        pkg.events.shift();
                    }
                }
                this.react(pkg, event);
            }
            this.custody.observe([event], this.clocks.sim);
            if (event.phase === 'cancel') {
                for (const entity of this.entities.values()) {
                    if (entity.animator) {
                        entity.animator.cancel(event.id, this.clocks.sim);
                    }
                }
            }
            this.schedule(event);
        }
    }

    // Starts the action clip of a contact event on the player who meets the ball.
    schedule(event) {
        if (event.player == null || (event.phase !== 'forecast' && event.phase !== 'occur') || !CONTACT_KINDS.includes(event.kind)) {
            return;
        }
        const entity = this.entities.get(`p${event.player}`);
        if (entity && entity.pkg.manifest.rig.ik && Object.keys(entity.pkg.manifest.rig.ik).length) {
            const t = event.data && event.data.contactT != null ? event.data.contactT : event.t;
            if (!entity.contacts.some((c) => Math.abs(c.t - t) < 1e-6)) {
                entity.contacts.push({ t, kind: event.kind, data: event.data });
                entity.contacts = entity.contacts.slice(-8);
            }
        }
        if (!entity || !entity.animator) {
            return;
        }
        const same = this.catalog ? this.catalog.eventsAt(event.step).filter((x) => x.player === event.player && CONTACT_KINDS.includes(x.kind)) : [event];
        const best = preferred(same.length ? same : [event]);
        if (best.id === event.id || !same.some((x) => x.id === best.id)) {
            const frame = this.app.timeline ? this.app.timeline.store.get(event.step) : null;
            entity.animator.schedule(event, event.phase === 'forecast' ? event.lead : 0, frame ? frame.gameMode : 0);
        }
    }

    // Runs the reflexes of a package for an event.
    react(pkg, event) {
        const own = new Set([...this.entities.values()].filter((e) => e.pkg === pkg).map((e) => e.id));
        for (const reflex of reflexesFor(pkg.manifest, event, pkg.side, this.header ? this.header.players : null)) {
            for (const { kind, command } of reflexActions(reflex, event, own)) {
                this.run(pkg, kind, command, event);
            }
        }
    }

    // Runs one checked command, the core's own kinds here and the rest through the registry.
    run(pkg, kind, command, event = null) {
        if (kind === 'clip') {
            const targets = command.on === 'team' ? [...this.entities.values()].filter((e) => e.pkg === pkg)
                : [this.entities.get(`p${event && event.player}`)].filter((e) => e && e.pkg === pkg);
            for (const entity of targets) {
                const entry = pickClip(pkg.manifest, command.role, entity.seeds.entity);
                const rig = this.players ? this.players.rigOf(entity.k) : null;
                const clip = entry && rig ? rig.clip(entry.clip) : null;
                if (clip) {
                    const clock = event && event.provenance !== 'presentation' ? 'sim' : 'ceremony';
                    const from = clock === 'sim' ? event.t : this.clocks.ceremony;
                    this.ledger.put({ id: `${event ? event.id : 'clip'}:${entity.id}`, entity: entity.id, event: event ? event.id : null, from, to: from + clip.duration, clock, content: { kind: 'clip', role: command.role, clip: entry.clip }, seed: entity.seeds.entity, replay: 'repeat', rate: 1, source: `reflex:${pkg.side}` });
                }
            }
            return;
        }
        if (kind === 'behaviour') {
            for (const entity of this.entities.values()) {
                if (entity.pkg === pkg && (command.on === 'team' || (event && entity.k === event.player))) {
                    try {
                        entity.behaviours.set(checkBehaviour(command.spec), 'reflex');
                    } catch {
                        this.drop.rejected += 1;
                    }
                }
            }
            return;
        }
        if (kind === 'claim') {
            this.claim(pkg, command);
            return;
        }
        dispatch(kind, command, { pkg, event, presentation: this });
    }

    // A claim of custody of the ball on a team's own touch, section 6.
    claim(pkg, c) {
        if (c.target !== 'ball' || !this.catalog) {
            return false;
        }
        const step = Number(String(c.event).split(':')[1]);
        const touches = Number.isFinite(step) ? this.catalog.eventsAt(step).filter((e) => e.kind === 'touch') : [];
        const event = touches.find((e) => e.team === pkg.side) || null;
        return this.custody.claim(pkg.side, event, touches);
    }

    // An event of the team on side made up at once, for the preview of a package. It carries the
    // ball where it is drawn as its contact and the team's first visible player, and reaches the
    // reflexes, the worker and the effects as a real event would. Returns the event.
    inject(side, kind) {
        const entity = [...this.entities.values()].find((e) => e.side === side && e.visible) || null;
        const ball = this.app.ball ? this.app.ball.mesh.position : null;
        const point = ball ? [ball.x, -ball.z, ball.y] : [0, 0, 0.11];
        this.injected = (this.injected || 0) + 1;
        const step = this.app.timeline ? Math.floor(this.app.timeline.t) : 0;
        const event = {
            id: `${kind}:${step}:preview${this.injected}`, kind, phase: 'occur', revision: 0, step, t: this.clocks.sim, lead: 0,
            team: side, player: entity ? entity.k : undefined, provenance: 'presentation',
            data: { kind: 'kick', contactT: this.clocks.sim, contactPoint: point, scoringTeam: side, team: side, preview: true },
        };
        this.pushEvents([event]);
        return event;
    }

    // A reveal of the show after the match. A package that answers it with a moment of its own
    // sound replaces the renderer's fanfare for its team. Returns whether one did.
    reveal(kind, team) {
        const event = this.emit({ kind: kind === 'mvp' ? 'mvp.reveal' : 'winner.reveal', team, data: { team } });
        let replaced = false;
        for (const pkg of this.packages) {
            if (pkg && pkg.side === team) {
                for (const reflex of reflexesFor(pkg.manifest, event, pkg.side)) {
                    replaced = (reflex.do || []).some((a) => a.audio != null && (a.class || 'action') === 'moment') || replaced;
                }
            }
        }
        return replaced && !!(this.app.sound && this.app.sound.audible);
    }

    // The distance player k covered from the start of the store to timeline index t, a prefix
    // sum of the steps of his root, cuts left out.
    distanceAt(k, t) {
        const store = this.app.timeline.store;
        let table = this.distances.get(k);
        if (!table) {
            table = { first: store.first, values: [0] };
            this.distances.set(k, table);
        }
        const i = Math.floor(t);
        while (table.first + table.values.length - 1 < Math.min(i + 1, store.last)) {
            const j = table.first + table.values.length;
            const a = store.get(j - 1);
            const b = store.get(j);
            const o = NODES_FLOAT + k * PLAYER_FLOATS;
            const d = a && b && !isCut(a, b) ? Math.hypot(b.data[o] - a.data[o], b.data[o + 1] - a.data[o + 1]) : 0;
            table.values.push(table.values[table.values.length - 1] + d);
        }
        const at = (j) => table.values[clamp(j - table.first, 0, table.values.length - 1)];
        return at(i) + (at(i + 1) - at(i)) * (t - i);
    }

    // The state of the timeline and the director on this drawing, before the players are drawn.
    update(dt, sample) {
        const app = this.app;
        const tl = app.timeline;
        // A match without a package costs the page nothing.
        if (!tl || !this.players || !this.header || (!this.packages[0] && !this.packages[1])) {
            return;
        }
        const drawn = performance.now();
        this.drawingMs = this.lastDrawing == null ? 0 : drawn - this.lastDrawing;
        this.lastDrawing = drawn;
        const director = app.director;
        const ceremony = !!(director && director.running) || !!(app.postMatch && app.postMatch.running);
        this.clocks.advance({ dt, t: tl.t, sps: tl.sps || 10, ceremony, held: !!app.userPaused && ceremony, audio: app.sound && app.sound.ctx ? app.sound.ctx.currentTime : null });
        this.observeTransport(tl);
        const replaying = !!(director && director.active);
        if (replaying !== !!this.replaying) {
            this.replaying = replaying;
            this.emit({ kind: replaying ? 'replay.begin' : 'replay.end', data: {} });
            this.reset(replaying ? 'replay' : 'resume');
        }
        if (!this.catalog || this.catalog.store !== tl.store) {
            this.catalog = new Catalog(tl.store, { fullLookahead: this.settings.fullLookahead, live: !!tl.live });
        }
        if (this.catalog) {
            const before = this.catalog.epoch;
            const events = this.catalog.update({ t: tl.t, playing: tl.playing, direction: tl.direction, speed: tl.speed, ahead: tl.live ? tl.behindLive : null, dt: app.playDt || dt });
            if (this.catalog.epoch !== before && this.catalog.resetReason) {
                this.newEpoch(this.catalog.resetReason === 'seek' ? 'seek' : this.catalog.resetReason, false);
            }
            if (this.resync) {
                this.resync = false;
                events.push(...this.catalog.window(tl.t));
            }
            for (const e of events) {
                if (replaying) {
                    e.replay = { of: this.replayOf || null, angle: null, speed: tl.speed };
                }
            }
            this.pushEvents(events);
        }
        this.observePresentation(sample);
        this.updateInputs(sample, tl);
        this.bend(sample, tl);
        this.updateUniforms();
        this.moments.update();
        this.moments.updateSlots();
        this.audio.update(this.entities.values());
    }

    // The share of real time the timeline plays this drawing, a team's time suggestion.
    timeScale(dt) {
        return this.packages[0] || this.packages[1] ? this.moments.timeScale(dt) : 1;
    }

    // Bends the drawn ball through the estimated contact of a touch in the interval on screen,
    // while a package names bend.ball, or always with the setting true. It moves the drawn ball
    // alone, after every hook of the page placed it, and only where the ball is still where the
    // frames put it.
    bend(sample, tl) {
        const on = this.settings.bendBall === true || (this.settings.bendBall === 'auto' && this.packages.some((p) => p && this.hasFeature(p, 'bend.ball')));
        const pose = this.app.pose;
        if (!on || !pose || !sample.b || isCut(sample.a, sample.b) || !(sample.b.touches && sample.b.touches.some((x) => x))) {
            this.bent = null;
            return;
        }
        const i = sample.index + 1;
        const est = contactEstimate(tl.store, i);
        if (!est || est.method !== 'intersection' || est.step !== sample.index) {
            this.bent = null;
            return;
        }
        const pa = [sample.a.data[8], sample.a.data[9], sample.a.data[10]];
        const pb = [sample.b.data[8], sample.b.data[9], sample.b.data[10]];
        const w = sample.w;
        const straight = [0, 1, 2].map((k) => pa[k] + (pb[k] - pa[k]) * w);
        if (Math.hypot(pose.ball[0] - straight[0], pose.ball[1] - straight[1], pose.ball[2] - straight[2]) > 1e-3) {
            return;
        }
        const p = bendBall(pa, pb, est.point, est.fraction, w);
        pose.ball[0] = p[0];
        pose.ball[1] = p[1];
        pose.ball[2] = p[2];
        this.bent = { step: i, fraction: est.fraction, point: est.point, drawn: p };
    }

    // The uniforms every shader of a team reads, the clocks, the ball, the pulse of its last own
    // event and the factor of the flash governor.
    updateUniforms() {
        const ball = this.app.ball ? this.app.ball.mesh.position : null;
        const renderer = this.app.view ? this.app.view.renderer : null;
        const high = this.app.view && this.app.view.quality === 'high';
        for (const side of [0, 1]) {
            const u = this.uniforms[side];
            const pkg = this.packages[side];
            this.pulse[side] *= Math.exp(-3 * this.clocks.cosmeticStep);
            u.uTime.value = this.clocks.cosmetic;
            u.uSim.value = this.clocks.sim;
            u.uCeremony.value = this.clocks.ceremony;
            u.uPulse.value = this.pulse[side] * (this.app.reducedMotion ? 0.5 : 1);
            u.uExcitement.value = this.app.excitement || 0;
            u.uIntensity.value = this.flashFactor();
            if (ball) {
                u.uBall.value.copy(ball);
            }
            if (renderer) {
                renderer.getDrawingBufferSize(u.uResolution.value);
            }
            // The frame drawn so far reaches a package that names shader.sceneColor at high quality.
            u.uSceneColor.value = pkg && high && this.hasFeature(pkg, 'shader.sceneColor') && this.app.view.frame ? this.app.view.frame : u.uLayer.value;
        }
        for (const entity of this.entities.values()) {
            const entry = this.entryOf(entity.k);
            for (const o of (entry && entry.instance.cujuOriginals) || []) {
                o.copy.userData.cuju.instance.uSpeed.value = entity.inputs.speed || 0;
            }
        }
    }

    // Transport events, and the epochs that a change of direction starts.
    observeTransport(tl) {
        const mode = !tl.playing ? 'pause' : tl.direction < 0 ? 'reverse' : 'play';
        if (this.mode !== null && mode !== this.mode) {
            this.emit({ kind: mode === 'reverse' ? 'reverse' : mode, data: { speed: tl.speed } });
            if (mode === 'reverse' || this.mode === 'reverse') {
                this.newEpoch('reverse');
            }
        }
        if (this.speed != null && tl.speed !== this.speed) {
            this.emit({ kind: 'speed', data: { speed: tl.speed } });
        }
        this.mode = mode;
        this.speed = tl.speed;
        const motion = !!this.app.reducedMotion;
        if (this.motion != null && motion !== this.motion) {
            this.emit({ kind: 'reducedMotion', data: { on: motion } });
        }
        this.motion = motion;
    }

    // The presentation events of the director and the show, from the edges of their state.
    observePresentation(sample) {
        const app = this.app;
        const director = app.director;
        const edge = (key, on, begin, end, data) => {
            if (on && !this.open.has(key)) {
                this.open.set(key, { event: this.emit({ kind: begin, ...data() }), ceremony: this.clocks.ceremony });
            } else if (!on && this.open.has(key)) {
                const opened = this.open.get(key);
                this.open.delete(key);
                if (end) {
                    this.emit({ kind: end, team: opened.event.team, data: { begin: opened.event.id } });
                }
            }
        };
        edge('lineup', !!(director && director.lineup), 'lineup.begin', 'lineup.end', () => ({ data: { duration: LINEUP_LENGTH } }));
        const cel = director ? director.cel : null;
        edge('celebration', !!cel, 'celebration.begin', 'celebration.end', () => ({ team: cel.goal.team, player: cel.celebrant, data: { celebrant: cel.celebrant, duration: 9.4 } }));
        const react = app.postMatch && app.postMatch.running ? app.postMatch.react : null;
        edge('reaction', !!react, 'reaction.begin', 'reaction.end', () => ({
            data: { outcome: [0, 1].map((t) => (react.winner < 0 ? 'draw' : react.winner === t ? 'win' : 'loss')), hero: react.hero, beaten: react.beaten },
        }));
        const seen = this.memory.visible || (this.memory.visible = new Map());
        for (const entity of this.entities.values()) {
            const on = !!(sample.a.playerFlags[entity.k] & 1);
            const was = seen.get(entity.id);
            if (was !== undefined && was && !on) {
                this.emit({ kind: 'entity.remove', team: entity.side, player: entity.k, data: { entity: entity.id } });
            }
            seen.set(entity.id, on);
        }
    }

    // The inputs of every entity, from the simulation's frames and the ceremonies on screen.
    updateInputs(sample, tl) {
        const store = tl.store;
        const a = sample.a;
        let b = store.get(sample.index + 1);
        let from = a;
        let to = b;
        if (!b || isCut(a, b)) {
            to = a;
            from = store.get(sample.index - 1);
            if (!from || isCut(from, a)) {
                from = a;
            }
        }
        const back = store.get(sample.index - 1);
        const sps = tl.sps || 10;
        const ball = this.app.ball ? this.app.ball.mesh.position : null;
        const lineup = this.open.get('lineup');
        for (const entity of this.entities.values()) {
            const o = NODES_FLOAT + entity.k * PLAYER_FLOATS;
            const vx = (to.data[o] - from.data[o]) * sps;
            const vy = (to.data[o + 1] - from.data[o + 1]) * sps;
            entity.velocity = [vx, vy];
            const speed = Math.hypot(vx, vy);
            const before = back && !isCut(back, a) ? Math.hypot(a.data[o] - back.data[o], a.data[o + 1] - back.data[o + 1]) * sps : speed;
            entity.decel = (before - speed) * sps;
            entity.turnRate = wrap(headingOf(to.data, o) - headingOf(from.data, o)) * sps;
            entity.action = a.actions ? a.actions[entity.k] : 0;
            entity.touch = a.touches ? a.touches[entity.k] : 0;
            entity.owner = a.ownedPlayer === entity.k;
            entity.gameMode = a.gameMode;
            const distance = this.distanceAt(entity.k, tl.t);
            entity.distanceStep = entity.lastDistance == null ? 0 : distance - entity.lastDistance;
            entity.lastDistance = distance;
            entity.distance = distance;
            // The ceremony this entity takes part in, the lineups, a clip a reflex started, or a pose
            // of the worker driver.
            let overlay = null;
            if (lineup) {
                const clip = pickClip(entity.pkg.manifest, 'lineup', entity.seeds.entity);
                if (clip) {
                    overlay = { role: 'lineup', clip: clip.clip, time: Math.max(0, this.clocks.ceremony - lineup.ceremony) * (clip.rate || 1), weight: 1 };
                }
            }
            for (const { track, local } of this.ledger.active(this.clocks, { replay: !!this.replaying, entity: entity.id })) {
                const c = track.content;
                if ((c.kind === 'clip' || c.kind === 'pose') && c.clip) {
                    overlay = { role: c.role || 'worker', clip: c.clip, time: c.time != null ? c.time : local * track.rate, weight: c.weight != null ? clamp(c.weight, 0, 1) : 1 };
                }
            }
            entity.overlay = overlay;
            if (overlay) {
                entity.lastOverlay = overlay;
            }
            entity.overlayWeight += ((overlay ? overlay.weight : 0) - entity.overlayWeight) * -Math.expm1(-8 * this.clocks.cosmeticStep);
            const anchor = entity.anchor;
            const ballDistance = ball ? Math.hypot(ball.x - anchor[0], ball.z - anchor[2]) : 1e3;
            const attack = entity.side === 0 ? 1 : -1;
            entity.inputs = {
                speed,
                accel: -entity.decel,
                ballDistance,
                excitement: this.app.excitement || 0,
                'ceremony.amount': Math.max(entity.overlayWeight, this.clocks.ceremonyStep > 0 ? 1 : 0),
                'ballX.attack': ball ? ball.x * attack : 0,
                alert: ballDistance < 15 || (a.ownedTeam >= 0 && a.ownedTeam !== entity.side) ? 1 : 0,
            };
        }
    }

    // Poses one player of a package as Rigged draws it, returning false to leave him to the
    // renderer's own drawing.
    pose(e, nodes, base) {
        const entity = e.presentation;
        if (!entity || !this.entities.has(entity.id) || entity.pkg.budget.past('stock')) {
            return false;
        }
        // What posing costs counts against the team's main thread budget, apart from the page's
        // own pose of the figure, which it draws without a package too.
        const started = performance.now();
        let own = 0;
        const rig = e.rig;
        const instance = e.instance;
        const m = entity.pkg.manifest;
        const frame = rootFrame(nodes, base, entity.frame);
        entity.facing = Math.atan2(frame.elements[8], frame.elements[10]);
        const request = e.request;
        let overlay = entity.overlay;
        if (request && request.weight > 0) {
            overlay = { role: 'celebration', clip: request.clip.name, time: request.t, weight: request.weight };
        } else if (!entity.animator) {
            // GRF's nodes fade into and out of a ceremony's clip.
            overlay = entity.overlayWeight > 0.01 && entity.lastOverlay ? { ...entity.lastOverlay, weight: entity.overlayWeight } : null;
        }
        let layers = [];
        if (entity.animator) {
            const ceremony = this.clocks.ceremonyStep > 0;
            layers = entity.animator.layers({
                sim: this.clocks.sim,
                speed: ceremony ? Math.hypot(entity.ceremonyVelocity[0], entity.ceremonyVelocity[2]) : entity.inputs.speed,
                distance: entity.distance, decel: entity.decel, turnRate: entity.turnRate,
                alert: !!entity.inputs.alert, cosmetic: this.clocks.cosmetic, overlay,
            });
            Object.assign(entity.inputs, Animator.roleWeights(layers));
        } else if (overlay) {
            entity.inputs[`role:${overlay.role}`] = overlay.weight;
        }
        this.evaluate(entity);
        for (const l of layers) {
            if (entity.outputs.clipTime.has(l.clip)) {
                l.time = entity.outputs.clipTime.get(l.clip);
            }
        }
        if (layers.length) {
            poseLayers(rig, instance, layers, frame, m.rig.rootMotion === 'cosmetic' ? 'vertical' : 'ignore');
        } else {
            stopLayers(instance);
            const clip = overlay ? rig.clip(overlay.clip) : null;
            const before = performance.now();
            if (clip) {
                const time = entity.outputs.clipTime.has(clip.name) ? entity.outputs.clipTime.get(clip.name) : overlay.time;
                rig.poseClip(instance, clip, time % (clip.duration || 1), overlay.weight, nodes, base, false);
            } else {
                rig.pose(instance, nodes, base, false);
            }
            own += performance.now() - before;
            if (entity.driver === 'grf+layers' && (m.rig.layers || []).length && !overlay) {
                maskLayers(rig, instance, m.rig.layers.map((l) => {
                    const entry = l.clip ? { clip: l.clip } : pickClip(m, l.role, entity.seeds.entity);
                    const c = entry ? rig.clip(entry.clip) : null;
                    return { mask: l.mask, clip: entry ? entry.clip : null, weight: clamp(evaluateCurve(l.weight, entity.inputs), 0, 1), time: c ? (this.clocks.cosmetic * (l.rate || 1)) % (c.duration || 1) : 0 };
                }), frame);
            }
        }
        this.reachFor(entity, rig, instance);
        const pivot = m.rig.sockets.root && !m.rig.sockets.root.node ? tmpVector.fromArray(m.rig.sockets.root.offset || [0, 0, 0]) : tmpVector.set(0, 0, 0);
        applyOutputs(rig, instance, frame, entity.outputs, pivot, m.rig.sockets.gaze || null, entity.cosmetic);
        const before = performance.now();
        if (rig.write) {
            rig.write(instance);
        } else {
            writeBones(rig, instance, e.hideHead);
        }
        own += performance.now() - before;
        entity.posed = true;
        entity.pkg.spent = (entity.pkg.spent || 0) + performance.now() - started - own;
        return true;
    }

    // Reaches each chain of the rig toward the drawn ball over the window around a contact.
    reachFor(entity, rig, instance) {
        const chains = entity.pkg.manifest.rig.ik || {};
        const ball = this.app.ball ? this.app.ball.mesh.position : null;
        if (!ball || !entity.contacts.length || !this.hasFeature(entity.pkg, 'ik.fabrik')) {
            return;
        }
        for (const [name, chain] of Object.entries(chains)) {
            if (!selects(chain.when, entity)) {
                continue;
            }
            let weight = 0;
            for (const c of entity.contacts) {
                weight = Math.max(weight, reachWeight(this.clocks.sim, c.t, chain.window ?? 0.15));
            }
            weight *= chain.weight ?? 1;
            if (weight <= 0.001) {
                continue;
            }
            rig.cujuChains = rig.cujuChains || new Map();
            if (!rig.cujuChains.has(name)) {
                rig.cujuChains.set(name, chainOf(rig, chain.chain));
            }
            const bones = rig.cujuChains.get(name);
            if (bones) {
                entity.reach = { chain: name, weight, left: reach(rig, instance, bones, ball, weight, chain.iterations || 8) };
            }
        }
    }

    // The behaviours of one entity on this drawing, read against its anchors of the last drawing.
    evaluate(entity) {
        const h = entity.facing;
        const [vx, vy] = entity.velocity || [0, 0];
        // The simulation's velocity in three's frame is x and minus y.
        const tx = vx;
        const tz = -vy;
        const eyeHeight = entity.bounds() ? entity.bounds().height * 0.6 : 1.2;
        const eye = [entity.anchor[0], entity.anchor[1] + eyeHeight, entity.anchor[2]];
        const toward = (p) => {
            const dx = p.x - eye[0];
            const dy = p.y - eye[1];
            const dz = p.z - eye[2];
            const lx = Math.cos(h) * dx - Math.sin(h) * dz;
            const lz = Math.sin(h) * dx + Math.cos(h) * dz;
            return { yaw: Math.atan2(lx, lz), pitch: Math.atan2(dy, Math.hypot(lx, lz)) };
        };
        const app = this.app;
        const target = (name) => {
            if (name === 'ball') {
                return app.ball && app.ball.mesh.visible !== false ? app.ball.mesh.position : null;
            }
            if (name === 'camera') {
                return app.view ? app.view.camera.position : null;
            }
            if (/^p\d+$/.test(String(name)) && this.players && app.pose) {
                const k = Number(name.slice(1));
                return this.players.position(app.pose, k, new THREE.Vector3()).setY(1.2);
            }
            return null;
        };
        entity.outputs = entity.behaviours.evaluate({
            dt: this.clocks.cosmeticStep,
            distance: entity.distanceStep || 0,
            inputs: entity.inputs,
            velocity: { forward: tx * Math.sin(h) + tz * Math.cos(h), lateral: tx * Math.cos(h) - tz * Math.sin(h) },
            looks: (name) => {
                const p = target(name);
                return p ? toward(p) : null;
            },
            follow: (name) => {
                const p = target(name);
                if (!p) {
                    return null;
                }
                const dx = p.x - entity.anchor[0];
                const dz = p.z - entity.anchor[2];
                return [Math.cos(h) * dx - Math.sin(h) * dz, p.y - entity.anchor[1], Math.sin(h) * dx + Math.cos(h) * dz];
            },
            clocks: this.clocks,
            reducedMotion: app.reducedMotion ? entity.pkg.manifest.reducedMotion.amplitude : 1,
        });
        // Material parameters of the core, a numeric property of the entity's own materials.
        for (const p of entity.outputs.materials) {
            const entry = this.entryOf(entity.k);
            if (p.attachment) {
                const a = entity.attachments.find((x) => x.name === p.attachment);
                if (a) {
                    setMaterialParam({ root: a.object, materials: a.materials || (a.materials = []) }, p);
                }
            } else if (entry && !(handlerOf('materials') && dispatch('materials', p, { pkg: entity.pkg, entity, presentation: this }))) {
                setMaterialParam(entry.instance, p);
            }
        }
    }

    // The bounds a package gives a figure, for camera framing and ceremony spacing.
    size(e) {
        const entity = e.presentation;
        return entity && this.entities.has(entity.id) ? entity.bounds() : null;
    }

    // The clip name a role plays on player k, for the choreographies' still poses.
    roleClip(k, role) {
        const entity = this.entities.get(`p${k}`);
        if (!entity) {
            return null;
        }
        const entry = pickClip(entity.pkg.manifest, role, entity.seeds.entity);
        return entry ? `clip:${entry.clip}` : null;
    }

    // Frees what one player of a package holds, as the page disposes him.
    release(e) {
        const entity = e.presentation;
        if (!entity) {
            return;
        }
        for (const a of entity.attachments) {
            disposeObject(a.object);
            entity.pkg.budget.give({ drawCalls: a.cost.drawCalls, triangles: a.cost.triangles, textureBytes: a.cost.textureBytes });
        }
        entity.attachments = [];
        if (this.entities.get(entity.id) === entity) {
            this.entities.delete(entity.id);
            this.emit({ kind: 'entity.remove', team: entity.side, player: entity.k, data: { entity: entity.id } });
        }
        e.presentation = null;
    }

    // Once the players and the ball are drawn, sockets and attachments follow the final poses
    // and each worker gets the rendered state of this drawing.
    afterPose() {
        if (!this.players || (!this.packages[0] && !this.packages[1])) {
            return;
        }
        const step = this.clocks.cosmeticStep;
        for (const entity of this.entities.values()) {
            const started = performance.now();
            const entry = this.entryOf(entity.k);
            const visible = !!(entry && entry.instance.root.visible && entity.posed);
            entity.visible = visible;
            if (visible) {
                anchorOf(entity.cosmetic, entity.anchor);
                if (entity.lastAnchor && step > 0) {
                    for (let i = 0; i < 3; i++) {
                        entity.ceremonyVelocity[i] += ((entity.anchor[i] - entity.lastAnchor[i]) / step - entity.ceremonyVelocity[i]) * -Math.expm1(-8 * step);
                    }
                }
                entity.lastAnchor = entity.anchor.slice();
            }
            for (const a of entity.attachments) {
                a.object.visible = visible && !entry.hideHead;
                if (!a.object.visible) {
                    continue;
                }
                const socket = a.socket === 'root' ? null : entity.pkg.manifest.rig.sockets[a.socket];
                if (socket) {
                    socketMatrix(entry.rig, entry.instance, socket, entity.cosmetic, tmpMatrix);
                } else {
                    tmpMatrix.copy(entity.cosmetic);
                }
                a.object.matrix.copy(tmpMatrix).multiply(a.local);
                const o = entity.outputs.attachments && entity.outputs.attachments.get(a.name);
                if (o) {
                    a.object.matrix.multiply(attachmentOffset(o));
                }
                a.object.matrixWorldNeedsUpdate = true;
            }
            entity.posed = false;
            entity.pkg.spent = (entity.pkg.spent || 0) + performance.now() - started;
        }
        const now = this.clocks.cosmetic;
        for (const pkg of this.packages) {
            if (!pkg) {
                continue;
            }
            pkg.lastSpent = pkg.spent || 0;
            const rung = this.settings.metering ? pkg.budget.meter(pkg.lastSpent, now, this.drawingMs || 0) : null;
            pkg.spent = 0;
            if (rung && pkg.budget.stepped === 'up') {
                // A team that ran well under its budget for a while climbs back one rung.
                console.info(`presentation of ${pkg.manifest.name || pkg.teamId} steps up to ${rung}`);
                if (!pkg.budget.past('standardMaterials')) {
                    this.reshade(pkg);
                }
                if (!pkg.budget.past('noWorker') && !pkg.host && pkg.status === 'stopped') {
                    this.startWorker(pkg);
                }
            } else if (rung) {
                console.warn(`presentation of ${pkg.manifest.name || pkg.teamId} steps down to ${rung}`);
                this.effects.degrade(pkg);
                if (pkg.budget.past('standardMaterials')) {
                    this.unshade(pkg);
                }
                // The ladder rests the worker, which starts again when the team climbs back.
                if (pkg.budget.past('noWorker') && pkg.host && pkg.host.status !== 'failed') {
                    pkg.host.dispose();
                    pkg.host = null;
                    this.workerStatus(pkg, 'stopped', 'the team is past its time budget');
                }
            }
            if (pkg.host && pkg.host.wants()) {
                const sent = performance.now();
                pkg.host.send(this.frame(pkg));
                pkg.spent += performance.now() - sent;
            }
        }
        this.effects.update(this.clocks.cosmeticStep);
        const started = performance.now();
        this.placeGeometries();
        const placed = performance.now() - started;
        // Each team's effects count against its own budget, and the geometries of the workers
        // against the teams that hold them.
        const holders = new Set([...this.geometries.values()].map((g) => g.pkg));
        for (const pkg of this.packages) {
            if (pkg) {
                const team = this.effects.teams[pkg.side];
                pkg.spent = (pkg.spent || 0) + (team ? team.spent || 0 : 0) + (holders.has(pkg) ? placed / holders.size : 0);
            }
        }
    }

    // The worker's geometries follow their sockets, players or the world.
    placeGeometries() {
        for (const g of this.geometries.values()) {
            const team = this.effects.teams[g.pkg.side];
            if (!team) {
                continue;
            }
            const attach = g.attach === 'world' ? { to: 'world' } : g.socket ? { to: 'entity', entity: g.entity, socket: g.socket } : { to: 'entity', entity: g.entity };
            const at = this.effects.resolve(team, { attach, event: null, params: {} }, new THREE.Vector3(), tmpMatrix);
            if (attach.to === 'world') {
                g.mesh.matrix.identity();
            } else if (at) {
                g.mesh.matrix.copy(tmpMatrix);
            }
            g.mesh.visible = attach.to === 'world' || !!at;
            g.mesh.matrixWorldNeedsUpdate = true;
        }
    }

    // After the picture is drawn, the team passes draw over it and the flash backstop reads a small
    // copy of it, while any team effect, light, pass or moment is on.
    afterRender(renderer, scene, camera) {
        if (!this.packages[0] && !this.packages[1]) {
            return;
        }
        this.post.render(renderer, scene, camera);
        const busy = this.effects.teams.some((t) => t && (t.instances.size || t.poolCount || t.localCount))
            || this.post.active() || !!this.moments.environment;
        if (!busy || !this.settings.flashCheck) {
            return;
        }
        try {
            const canvas = this.flashCanvas || (this.flashCanvas = Object.assign(document.createElement('canvas'), { width: 64, height: 36 }));
            const ctx = this.flashContext || (this.flashContext = canvas.getContext('2d', { willReadFrequently: true }));
            ctx.drawImage(renderer.domElement, 0, 0, 64, 36);
            const counts = this.counter.push(this.clocks.cosmetic, ctx.getImageData(0, 0, 64, 36).data);
            this.flashCounts = { general: counts.general, red: counts.red };
            this.flash.observe(this.clocks.cosmetic, counts);
        } catch {
            // A canvas that cannot be read leaves the envelopes of the governor alone.
        }
    }

    // The rendered state of this drawing as a Frame for one package, in the pitch frame.
    frame(pkg) {
        const app = this.app;
        const tl = app.timeline;
        const store = tl.store;
        const s = tl.sample();
        const a = s.a;
        const sps = tl.sps || 10;
        this.frameId += 1;
        const pose = app.pose;
        const players = this.header.players.map((p, k) => {
            const entity = this.entities.get(`p${k}`);
            const style = this.styles ? this.styles[p.team] : null;
            const roster = style && style.players ? style.players[p.index] : null;
            const o = k * PLAYER_FLOATS;
            const root = entity && entity.visible
                ? [entity.anchor[0], -entity.anchor[2], entity.anchor[1]]
                : [pose.nodes[o], pose.nodes[o + 1], pose.nodes[o + 2]];
            const hidden = this.players.hidden ? ['none', 'head', 'all'][this.players.hidden[k]] || 'none' : 'none';
            const velocity = entity ? entity.velocity.map((v) => v / sps) : [0, 0];
            return {
                entity: `p${k}`, player: k, team: p.team,
                roster: { name: roster ? roster.name || null : null, number: roster ? roster.number : null, goalkeeper: !!p.goalkeeper, celebration: roster ? roster.celebration || null : null },
                onPitch: !!(a.playerFlags[k] & 1), visible: entity ? entity.visible : !!this.players.visible[k], hidden,
                root, facing: pitchHeading(pose.nodes, o), velocity, speed: entity ? entity.inputs.speed || 0 : 0,
                distance: entity ? entity.distance : this.distanceAt(k, tl.t), action: a.actions ? a.actions[k] : 0,
                touch: a.touches ? a.touches[k] : 0, owner: a.ownedPlayer === k,
                driver: entity ? entity.driver : 'stock', mode: entity && entity.overlay ? 'ceremony' : 'locomotion',
                ceremonyRole: entity && entity.overlay ? entity.overlay.role : null, bounds: entity ? entity.bounds() : null,
                own: p.team === pkg.side,
            };
        });
        const ball = pose.ball;
        const next = store.get(s.index + 1);
        const bv = next && !isCut(a, next) ? [0, 1, 2].map((i) => next.data[8 + i] - a.data[8 + i]) : [0, 0, 0];
        const director = app.director;
        const context = director && director.active ? 'replay' : director && director.cel ? 'celebration' : director && director.lineup ? 'lineup'
            : app.postMatch && app.postMatch.running ? 'post' : app.transition && app.transition.active ? 'transition' : 'play';
        const message = frameMessage({
            instanceId: pkg.instanceId,
            epoch: this.epoch,
            frameId: this.frameId,
            reset: this.resetPending ? { ...this.resetInfo } : null,
            clocks: this.clocks.snapshot(),
            playback: { playing: tl.playing, direction: tl.direction, speed: tl.speed, live: !!tl.live, ahead: tl.live ? tl.behindLive : (tl.last - tl.t) / sps, context },
            quality: pkg.budget.quality,
            reducedMotion: !!app.reducedMotion,
            audible: !!(app.sound && app.sound.audible),
            players,
            ball: { pos: [ball[0], ball[1], ball[2]], rot: [ball[3], ball[4], ball[5], ball[6]], velocity: bv, owner: a.ownedPlayer, custody: this.custody.holder ? { team: this.custody.holder.team, event: this.custody.holder.event } : null },
            game: { mode: a.gameMode, score: [a.scoreLeft, a.scoreRight], clockMs: a.timeMs, ownedTeam: a.ownedTeam, attack: [1, -1], excitement: app.excitement || 0 },
            events: pkg.events,
            camera: app.view ? { pos: toPitch(app.view.camera.position), target: toPitch(app.view.camera.getWorldDirection(new THREE.Vector3()).add(app.view.camera.position)), fov: app.view.camera.fov, mode: app.cameras ? app.cameras.mode : null } : null,
        });
        this.resetPending = false;
        pkg.events = [];
        return message;
    }

    // A reply of a worker, checked, then applied when it answers this epoch. The time it takes
    // counts against the team's budget, and the first answer arms the team's meter.
    respond(pkg, message) {
        const started = performance.now();
        try {
            this.apply(pkg, message);
        } finally {
            pkg.spent = (pkg.spent || 0) + performance.now() - started;
            if (pkg.budget.armAt === Infinity) {
                pkg.budget.arm(this.clocks.cosmetic + 0.5);
            }
        }
    }

    apply(pkg, message) {
        const own = new Set([...this.entities.values()].filter((e) => e.pkg === pkg).map((e) => e.id));
        const checked = checkResponse(message, {
            instanceId: pkg.instanceId, epoch: this.epoch, own, files: pkg.files,
            envelope: (id) => (this.entities.get(id) ? this.entities.get(id).envelope : null),
        });
        if (!checked.ok) {
            this.drop[checked.reason] = (this.drop[checked.reason] || 0) + 1;
            return;
        }
        const r = checked.response;
        this.drop.rejected += r.rejected;
        pkg.lastResponse = { frameId: r.sourceFrameId, ms: r.ms, roundTrip: message.roundTrip || 0 };
        // The log keeps the newest lines across replies, and each line shows in the console.
        if (r.log.length) {
            pkg.log = appendLog(pkg.log, r.log);
            for (const line of r.log) {
                console.info(`presentation worker of ${pkg.manifest.name || pkg.teamId}: ${line}`);
            }
        }
        const mine = (id) => (id == null ? [...this.entities.values()].filter((e) => e.pkg === pkg) : [this.entities.get(id)].filter((e) => e && e.pkg === pkg));
        for (const b of r.behaviours) {
            for (const entity of mine(b.entity)) {
                if (b.op === 'set') {
                    entity.behaviours.set(b.behaviour, 'worker');
                } else if (b.op === 'update') {
                    entity.behaviours.update(b.id, b.patch);
                } else {
                    entity.behaviours.stop(b.id, b.fadeOut);
                }
            }
        }
        for (const t of r.tracks) {
            const entity = this.entities.get(t.entity);
            if (t.entity === 'world' || (entity && entity.pkg === pkg)) {
                this.ledger.put({ ...t, source: `worker:${pkg.side}` });
            }
        }
        for (const b of r.bounds) {
            const entity = this.entities.get(b.entity);
            if (entity && entity.pkg === pkg) {
                entity.current = b.current;
            }
        }
        const context = { pkg, presentation: this, event: null };
        for (const c of r.claims) {
            dispatch('claims', c, context);
        }
        for (const c of r.effects) {
            dispatch('effects', c, context);
        }
        for (const c of r.audio) {
            dispatch('audio', c, context);
        }
        // The overlays the check kept, in order, each beside the raw command it came from.
        const raws = Array.isArray(message.overlays) ? message.overlays.slice(0, MAXIMUM_COMMANDS).filter((o) => checkOverlay(o)) : [];
        r.overlays.forEach((c, i) => {
            const raw = raws[i] || null;
            const bitmap = raw && typeof ImageBitmap !== 'undefined' && raw.bitmap instanceof ImageBitmap ? raw.bitmap : null;
            dispatch('overlays', c, { ...context, bitmap });
        });
        for (const c of r.resources) {
            dispatch('resources', c, context);
        }
        if (r.camera) {
            dispatch('camera', r.camera, context);
        }
        if (r.time) {
            dispatch('time', r.time, context);
        }
    }

    // A summary of the packages on screen, for the page check and for authors.
    status() {
        return {
            contract: CONTRACT,
            epoch: this.epoch,
            reset: this.resetInfo,
            clocks: this.clocks.snapshot(),
            dropped: { ...this.drop, commands: { ...dropped } },
            effects: this.effects.snapshot(),
            post: this.post.snapshot(),
            audio: this.audio.snapshot(),
            moments: this.moments.snapshot(),
            flash: { counts: { ...this.flashCounts }, clamped: this.flash.clamped, factor: this.flashFactor(), events: this.flash.events.slice(-8) },
            bent: this.bent || null,
            geometries: [...this.geometries.keys()],
            custody: this.custody.holder,
            tracks: this.ledger.tracks.size,
            safety: SAFETY,
            ladder: LADDER,
            packages: this.packages.map((pkg) => (pkg ? {
                team: pkg.teamId, side: pkg.side, name: pkg.manifest.name || null, developer: pkg.developer, status: pkg.status,
                detail: pkg.detail, level: pkg.levels.level, missing: pkg.levels.missing, lacking: pkg.levels.lacking,
                worker: !!pkg.manifest.worker, starting: !!pkg.hostPending, sealed: pkg.host ? pkg.host.sealed : null, late: pkg.host ? pkg.host.late : 0,
                answered: pkg.host ? pkg.host.answered : 0, failures: pkg.host ? pkg.host.failures.slice() : [],
                budget: pkg.budget.snapshot(), spentMs: pkg.lastSpent || 0, lastResponse: pkg.lastResponse || null, log: pkg.log || [],
                warnings: pkg.served.warnings || [], errors: pkg.errors.slice(),
            } : null)),
            entities: [...this.entities.values()].map((e) => ({
                id: e.id, side: e.side, number: e.number, goalkeeper: e.goalkeeper, seed: e.seeds.entity, driver: e.driver,
                bounds: e.bounds(), envelope: e.envelope, anchor: e.anchor.slice(), distance: e.distance,
                behaviours: [...e.behaviours.items.keys()], attachments: e.attachments.map((a) => a.name),
                overlay: e.overlay ? e.overlay.role : null, visible: e.visible, reach: e.reach || null,
                actions: e.animator ? [...e.animator.actions.values()].slice(-3).map((x) => ({ role: x.role, clip: x.clip, contactT: x.contactT, rate: x.schedule.rate })) : [],
            })),
        };
    }

    dispose() {
        for (const pkg of this.packages) {
            if (pkg) {
                pkg.dispose();
            }
        }
        this.effects.dispose();
        this.post.dispose();
        this.audio.dispose();
        this.moments.end();
        this.moments.disposeSlots();
        this.packages = [null, null];
        this.entities.clear();
    }
}

// The matrix of the behaviours' offset of an attachment in its socket frame.
function attachmentOffset(o) {
    const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(o.rotX, o.rotY, o.rotZ, 'XYZ'));
    for (const spin of o.spins) {
        q.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(...spin.axis).normalize(), spin.angle));
    }
    const s = Math.max(0.05, 1 + o.scale);
    return new THREE.Matrix4().compose(new THREE.Vector3(o.x, o.y, o.z), q, new THREE.Vector3(s, s, s));
}

// A numeric property of the entity's own materials that a materialParam behaviour drives, such
// as emissiveIntensity or opacity, on copies the entity owns.
function setMaterialParam(instance, p) {
    const owned = instance.presentationParams || (instance.presentationParams = new Map());
    instance.root.traverse((obj) => {
        if (!obj.isMesh) {
            return;
        }
        const list = Array.isArray(obj.material) ? obj.material : [obj.material];
        list.forEach((mat, i) => {
            const own = mat.userData && mat.userData.cuju && mat.userData.cuju.own && mat.userData.cuju.own[p.uniform];
            if ((p.material === '*' || mat.name === p.material) && own && typeof own.value === 'number') {
                // A package uniform of a custom shader, which the material owns already.
                if (mat.userData.cujuBase === undefined || !(p.uniform in mat.userData.cujuBase)) {
                    mat.userData.cujuBase = { ...(mat.userData.cujuBase || {}), [p.uniform]: own.value };
                }
                own.value = mat.userData.cujuBase[p.uniform] + (p.value - mat.userData.cujuBase[p.uniform]) * p.weight;
                return;
            }
            if (!(p.material === '*' || mat.name === p.material) || typeof mat[p.uniform] !== 'number') {
                return;
            }
            let copy = owned.get(mat);
            if (!copy && !instance.materials.includes(mat)) {
                copy = mat.clone();
                instance.materials.push(copy);
                owned.set(mat, copy);
                if (Array.isArray(obj.material)) {
                    obj.material[i] = copy;
                } else {
                    obj.material = copy;
                }
            }
            const target = copy || mat;
            if (target.userData.presentationBase === undefined) {
                target.userData.presentationBase = target[p.uniform];
            }
            target[p.uniform] = target.userData.presentationBase + (p.value - target.userData.presentationBase) * p.weight;
        });
    });
}

// The heading of a player's forward in three's frame, from the frame data.
function headingOf(data, o) {
    const x = data[o + 3];
    const y = data[o + 4];
    const z = data[o + 5];
    const w = data[o + 6];
    const fx = 2 * (x * y - w * z);
    const fy = 1 - 2 * (x * x + z * z);
    return Math.atan2(-fx, fy);
}

// The heading of a player's forward in the pitch frame, the angle from positive x toward
// positive y.
function pitchHeading(nodes, o) {
    const x = nodes[o + 3];
    const y = nodes[o + 4];
    const z = nodes[o + 5];
    const w = nodes[o + 6];
    // GRF's player faces along minus y of his own frame.
    const fx = -2 * (x * y - w * z);
    const fy = -(1 - 2 * (x * x + z * z));
    return Math.atan2(fy, fx);
}

function toPitch(v) {
    return [v.x, -v.z, v.y];
}

export { boneIndex, roleOf };
