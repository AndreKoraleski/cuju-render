// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Framing of the automatic cameras at any shape of picture. Their shots are tuned for a picture of
// 16 by 9, and the field of view of three is vertical, so a narrower picture keeps the height of
// the shot and loses its sides. These functions widen the vertical field of view of a narrower
// picture so it keeps the area of the shot, and shrink the lead of the broadcast camera with the
// width. They do not use three, so the tests load them in Node.

// The shape the shots are tuned for, width over height.
export const REFERENCE_ASPECT = 16 / 9;
// The widest vertical field of view in degrees that a narrow picture is given.
export const MAX_FOV = 75;

const RAD = Math.PI / 180;

// The vertical field of view in degrees for a picture of the given aspect, for a shot tuned at the
// reference. A picture as wide as the reference or wider keeps the field of view exactly. A
// narrower one keeps the product of the half tangents across and up the picture, so the width of
// the shot shrinks with the square root of the aspect rather than in proportion and its height
// grows to make up for it. At 9 by 16 this turns the lens on its side, the vertical view of the
// portrait picture is the horizontal view of the landscape one. The result never passes the
// larger of MAX_FOV and the given field of view, and it never narrows the field of view.
export function aspectFov(fov, aspect, reference = REFERENCE_ASPECT) {
    if (!(aspect < reference) || !(aspect > 0)) {
        return fov;
    }
    const tan = Math.tan(fov * RAD / 2) * Math.sqrt(reference / aspect);
    const wide = 2 * Math.atan(tan) / RAD;
    return Math.min(wide, Math.max(fov, MAX_FOV));
}

// The share of the width of a reference shot that a picture of the given aspect keeps once its
// field of view is corrected, 1 for a picture as wide as the reference or wider.
export function widthShare(fov, aspect, reference = REFERENCE_ASPECT) {
    if (!(aspect < reference) || !(aspect > 0)) {
        return 1;
    }
    const across = Math.tan(aspectFov(fov, aspect, reference) * RAD / 2) * aspect;
    return across / (Math.tan(fov * RAD / 2) * reference);
}

// The scale of the lead of the broadcast camera for a picture of the given aspect. The lead keeps
// to the same share of the width of the picture, so the ball stays as far inside a narrow picture
// as it does inside a wide one. It is exactly 1 at the reference aspect and wider.
export function leadScale(aspect, fov = 30, reference = REFERENCE_ASPECT) {
    return widthShare(fov, aspect, reference);
}

// The rate of the springs that follow the ball for the broadcast camera, a multiple of their rate
// in a reference picture. A narrower picture follows faster, so the ball lags behind the middle of
// the picture by the same share of its width. It is exactly 1 at the reference aspect and wider.
export function trackRate(aspect, fov = 30, reference = REFERENCE_ASPECT) {
    return 1 / widthShare(fov, aspect, reference);
}

// How far a picture is from the reference towards a portrait of 9 by 16, 0 at the reference and
// wider, 1 at 9 by 16 and narrower, so a shot can turn towards its subjects as the width shrinks.
export function narrowShare(aspect, reference = REFERENCE_ASPECT) {
    if (!(aspect < reference) || !(aspect > 0)) {
        return 0;
    }
    const portrait = 1 - Math.sqrt(9 / 16 / reference);
    return Math.min(1, (1 - Math.sqrt(aspect / reference)) / portrait);
}

// The level direction from pos halfway between the directions to a and to b, as fields x and z
// of a unit vector, so a camera turned that way keeps both points equally far from the middle.
export function levelBisector(pos, a, b) {
    const ax = a.x - pos.x;
    const az = a.z - pos.z;
    const bx = b.x - pos.x;
    const bz = b.z - pos.z;
    const la = Math.hypot(ax, az) || 1;
    const lb = Math.hypot(bx, bz) || 1;
    let x = ax / la + bx / lb;
    let z = az / la + bz / lb;
    const l = Math.hypot(x, z);
    if (!(l > 1e-9)) {
        return { x: ax / la, z: az / la };
    }
    x /= l;
    z /= l;
    return { x, z };
}

// Moves target, seen from pos, the given share of the way to the level direction halfway between
// a and b, keeping its level distance from pos and its height. The share 0 leaves it as it is.
// Changes target in place and returns it.
export function turnBetween(pos, target, a, b, share) {
    if (!(share > 0)) {
        return target;
    }
    const aim = levelBisector(pos, a, b);
    const reach = Math.hypot(target.x - pos.x, target.z - pos.z);
    target.x += (pos.x + aim.x * reach - target.x) * share;
    target.z += (pos.z + aim.z * reach - target.z) * share;
    return target;
}

// Where a point lands in the picture of a camera at pos looking at target with the world up kept
// up, as three's lookAt makes it, with the vertical field of view fov in degrees. Returns x and y
// from minus 1 to 1 across the picture and the depth in front of the camera, or null when the point
// is not in front of it. Points are objects with fields x, y and z.
export function project(pos, target, fov, aspect, point) {
    let fx = target.x - pos.x;
    let fy = target.y - pos.y;
    let fz = target.z - pos.z;
    const length = Math.hypot(fx, fy, fz);
    if (!(length > 1e-9)) {
        return null;
    }
    fx /= length;
    fy /= length;
    fz /= length;
    // The right of the view is level, and straight down looks along the x axis.
    const flat = Math.hypot(fx, fz);
    const rx = flat > 1e-9 ? -fz / flat : 1;
    const rz = flat > 1e-9 ? fx / flat : 0;
    const ux = -rz * fy;
    const uy = rz * fx - rx * fz;
    const uz = rx * fy;
    const dx = point.x - pos.x;
    const dy = point.y - pos.y;
    const dz = point.z - pos.z;
    const depth = dx * fx + dy * fy + dz * fz;
    if (!(depth > 1e-6)) {
        return null;
    }
    const tanV = Math.tan(fov * RAD / 2);
    const tanH = tanV * aspect;
    return {
        x: (dx * rx + dz * rz) / depth / tanH,
        y: (dx * ux + dy * uy + dz * uz) / depth / tanV,
        depth,
    };
}

// Whether a point lands inside the picture with a margin, a share of the half width and the half
// height of the picture kept clear at every edge.
export function inFrame(pos, target, fov, aspect, point, margin = 0) {
    const p = project(pos, target, fov, aspect, point);
    const edge = 1 - margin;
    return p !== null && Math.abs(p.x) <= edge && Math.abs(p.y) <= edge;
}
