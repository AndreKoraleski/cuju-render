// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

import * as THREE from 'three';

const trees = new WeakMap();

function tree(triangles) {
    const bounds = new THREE.Box3();
    for (const triangle of triangles) for (const point of triangle) bounds.expandByPoint(point);
    if (triangles.length <= 16) return { bounds, triangles };
    const size = bounds.getSize(new THREE.Vector3());
    const axis = size.x > size.y && size.x > size.z ? 'x' : size.y > size.z ? 'y' : 'z';
    triangles.sort((a, b) => (a[0][axis] + a[1][axis] + a[2][axis]) - (b[0][axis] + b[1][axis] + b[2][axis]));
    const middle = Math.floor(triangles.length / 2);
    return { bounds, left: tree(triangles.slice(0, middle)), right: tree(triangles.slice(middle)) };
}

// Static structural meshes share a triangle tree. Ray segments end before the player's head.
export function blocksPlayer(mesh, worldRay, far) {
    const geometry = mesh.geometry;
    const position = geometry.attributes.position;
    const index = geometry.index;
    let saved = trees.get(geometry);
    if (!saved || saved.positionVersion !== position.version || saved.indexVersion !== index?.version) {
        const triangles = [];
        const count = index ? index.count : position.count;
        for (let i = 0; i + 2 < count; i += 3) {
            triangles.push([0, 1, 2].map((offset) => new THREE.Vector3().fromBufferAttribute(position, index ? index.getX(i + offset) : i + offset)));
        }
        saved = { root: tree(triangles), positionVersion: position.version, indexVersion: index?.version };
        trees.set(geometry, saved);
    }
    const inverse = mesh.matrixWorld.clone().invert();
    const origin = worldRay.origin.clone().applyMatrix4(inverse);
    const end = worldRay.at(far, new THREE.Vector3()).applyMatrix4(inverse);
    const length = origin.distanceTo(end);
    const ray = new THREE.Ray(origin, end.sub(origin).normalize());
    const hit = new THREE.Vector3();
    const visits = (node) => {
        if (!node.bounds.containsPoint(origin)
            && (!ray.intersectBox(node.bounds, hit) || hit.distanceTo(origin) > length)) return false;
        if (node.triangles) return node.triangles.some(([a, b, c]) =>
            ray.intersectTriangle(a, b, c, false, hit) && hit.distanceTo(origin) <= length);
        return visits(node.left) || visits(node.right);
    };
    return visits(saved.root);
}
