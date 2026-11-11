// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Labels over the players of the Watch page, each with the number and the name, and a click on a
// player that turns the player camera on that player. A player behind the stands, a goal or the
// roof keeps no label and takes no click.

import * as THREE from 'three';
import { t } from '../core/i18n.js';
import { h } from '../teams/library.js';
import { blocksPlayer } from '../world/occlusion.js';

function load(key, fallback) {
    try {
        const v = localStorage.getItem(`cuju.${key}`);
        return v === null ? fallback : JSON.parse(v);
    } catch {
        return fallback;
    }
}

function save(key, value) {
    try {
        localStorage.setItem(`cuju.${key}`, JSON.stringify(value));
    } catch {
        // Storage can be unavailable, the setting then lasts for this visit only.
    }
}

export class PlayerTools {
    constructor(app) {
        this.app = app;
        this.points = [];
        this.labels = load('playerLabels', false) === true;
        this.picking = load('clickFollow', false) === true;
        // Whether another layer, the annotations, wants the players in view without labels.
        this.wanted = false;
        this.ray = new THREE.Raycaster();
        this.layer = h('div', { class: 'player-labels', 'aria-hidden': 'true', hidden: true });
        document.body.append(this.layer);
        const check = (id, text, key, stored) => {
            const input = h('input', { type: 'checkbox', id });
            input.checked = this[key];
            input.addEventListener('change', () => {
                this[key] = input.checked;
                save(stored, input.checked);
                this.update(true);
            });
            return h('label', { class: 'check' }, input, ` ${text}`);
        };
        // The two settings follow the ball trail in the settings panel.
        const trail = document.getElementById('trail');
        const anchor = trail && trail.closest('label');
        if (anchor) {
            anchor.after(check('labels-on', t('playerTools.labels'), 'labels', 'playerLabels'),
                check('click-follow', t('playerTools.clickFollow'), 'picking', 'clickFollow'));
        }
        // A short click without a drag picks, so dragging keeps turning the camera.
        const canvas = app.view.renderer.domElement;
        canvas.addEventListener('pointerdown', (event) => {
            this.down = event.button === 0 ? [event.clientX, event.clientY, performance.now()] : null;
        });
        canvas.addEventListener('pointercancel', () => {
            this.down = null;
        });
        canvas.addEventListener('pointerup', (event) => {
            const down = this.down;
            this.down = null;
            if (!this.picking || !down || document.pointerLockElement || app.page !== 'watch'
                || performance.now() - down[2] > 500 || Math.hypot(event.clientX - down[0], event.clientY - down[1]) > 6) {
                return;
            }
            this.pick(event.clientX, event.clientY);
        });
    }

    // The nearest visible player within a short reach of a point of the window, followed with
    // the player camera. Returns the index of the player, or -1 when none is near.
    pick(x, y) {
        const app = this.app;
        this.update(true);
        const point = this.points.map((p) => ({ ...p, distance: Math.hypot(p.x - x, p.y - y) }))
            .filter((p) => p.distance < 22).sort((a, b) => a.distance - b.distance || a.depth - b.depth)[0];
        if (!point) {
            return -1;
        }
        app.cameras.followIndex = point.index;
        app.setCamera('player');
        app.announcePlayer();
        return point.index;
    }

    // Shows and hides the label layer and finds the players in view about ten times a second.
    // With labels off the search runs only for a click.
    update(force = false) {
        const app = this.app;
        const covered = app.page !== 'watch' || app.director.running || app.postMatch.running || app.transition.active;
        const ready = !covered && app.source && app.pose && app.players;
        this.layer.hidden = !this.labels || !ready;
        const wanted = this.labels || this.wanted;
        if (!ready || (!wanted && !force) || (!wanted && !this.picking)) {
            this.points = [];
            if (this.layer.childElementCount) {
                this.layer.replaceChildren();
            }
            return;
        }
        const now = performance.now();
        if (!force && this.source === app.source && now - this.updated < 100) {
            return;
        }
        this.source = app.source;
        this.updated = now;
        this.points = [];
        const camera = app.view.camera;
        if (camera.position.y < 0) {
            this.layer.replaceChildren();
            return;
        }
        const rect = app.view.renderer.domElement.getBoundingClientRect();
        const direction = new THREE.Vector3();
        const world = new THREE.Vector3();
        const meshes = [];
        app.view.scene.traverseVisible((object) => {
            if (!object.isMesh || (object.material?.transparent && object.material.opacity < 0.25)) {
                return;
            }
            for (let parent = object; parent; parent = parent.parent) {
                if (parent === app.players.group) {
                    return;
                }
            }
            if (object.isInstancedMesh) {
                if (!object.boundingBox) {
                    object.computeBoundingBox();
                }
            } else if (!object.geometry.boundingBox) {
                object.geometry.computeBoundingBox();
            }
            const bounds = (object.isInstancedMesh ? object.boundingBox : object.geometry.boundingBox)?.clone();
            if (bounds) {
                meshes.push({ object, bounds: bounds.applyMatrix4(object.matrixWorld) });
            }
        });
        const controls = document.getElementById('controls').getBoundingClientRect();
        for (let index = 0; index < app.source.header.players.length; index++) {
            if (!app.players.visible[index]) {
                continue;
            }
            app.players.position(app.pose, index, world).setY(1.8);
            const distance = world.distanceTo(camera.position);
            const screen = world.clone().project(camera);
            if (screen.z < -1 || screen.z > 1 || Math.abs(screen.x) > 1 || Math.abs(screen.y) > 1) {
                continue;
            }
            this.ray.set(camera.position, direction.subVectors(world, camera.position).normalize());
            this.ray.far = Math.max(0, distance - 0.8);
            const hit = new THREE.Vector3();
            const candidates = meshes.filter(({ bounds }) => bounds.containsPoint(camera.position)
                || (this.ray.ray.intersectBox(bounds, hit) && hit.distanceTo(camera.position) <= this.ray.far))
                .map(({ object }) => object);
            if (candidates.some((object) => (!object.isInstancedMesh && !object.isSkinnedMesh
                ? blocksPlayer(object, this.ray.ray, this.ray.far)
                : this.ray.intersectObject(object, false).length > 0))) {
                continue;
            }
            const x = rect.left + (screen.x + 1) * rect.width / 2;
            const y = rect.top + (1 - screen.y) * rect.height / 2;
            if (y < rect.top + 32 || (controls.height && y > controls.top - 8)) {
                continue;
            }
            this.points.push({ index, x, y, depth: distance });
        }
        if (!this.labels) {
            return;
        }
        // The nearest players keep their labels where labels would overlap.
        const used = [];
        const nodes = [];
        for (const point of this.points.slice().sort((a, b) => a.depth - b.depth)) {
            if (used.some((other) => Math.abs(other.x - point.x) < 110 && Math.abs(other.y - point.y) < 22)) {
                continue;
            }
            used.push(point);
            const label = h('span', {}, app.playerLabel(point.index));
            label.style.left = `${Math.max(rect.left + 82, Math.min(rect.right - 82, point.x))}px`;
            label.style.top = `${point.y - 12}px`;
            nodes.push(label);
        }
        this.layer.replaceChildren(...nodes);
    }
}
