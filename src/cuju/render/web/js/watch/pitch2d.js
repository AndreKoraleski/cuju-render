// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// A top-down drawing of a match on a 2D canvas, without WebGL. The pitch lies as the broadcast
// camera sees it, the left goal at the left edge and the engine's positive y at the top, players
// are discs in their team's colors with their numbers, and the ball rises towards the top of the
// picture with its height, over a shadow that stays on the ground. Nothing here touches the page,
// so the Watch page, the grid of environments and the tests share it.

import { BALL_FLOAT, NODES_FLOAT, PLAYER_FLOATS } from '../recording/format.js';

// The pitch as GRF sizes it, the same values as pitch.js gives the 3D view.
export const HALF_W = 55;
export const HALF_H = 36;
export const FULL_HALF_W = 60;
export const FULL_HALF_H = 40;
const GOAL_HALF_WIDTH = 3.7;
const GOAL_DEPTH = 2.55;
const PENALTY_DEPTH = 16.5;
const PENALTY_HALF_WIDTH = 20.15;
const GOAL_AREA_DEPTH = 5.5;
const GOAL_AREA_HALF_WIDTH = 9.16;
const PENALTY_SPOT = 11;
const CIRCLE_RADIUS = 9.15;
const CORNER_RADIUS = 1;
// A player is drawn as a disc of this radius in meters, and never smaller than PLAYER_MIN_PX.
export const PLAYER_RADIUS = 1.3;
const PLAYER_MIN_PX = 2.5;
// The ball is drawn larger than its 0.11 meters so that it shows at every size.
export const BALL_DRAWN_RADIUS = 0.55;
const BALL_MIN_PX = 2;
// The ball rises on the picture by this share of its height, as a camera on the near side sees
// it, and grows by one part in HEIGHT_GROWTH for each meter, up to HEIGHT_CAP meters.
export const HEIGHT_LIFT = 0.6;
const HEIGHT_GROWTH = 6;
const HEIGHT_CAP = 12;
const GRASS = '#2f6b34';
const SURROUND = '#1d3d21';
const LINES = 'rgba(255, 255, 255, 0.85)';

// The transform from the pitch, in meters with the left goal at negative x and positive y at the
// top, to a canvas of width by height pixels. The whole grass fits inside the box that the
// margins leave, centered, and one meter is scale pixels either way.
export function pitchTransform(width, height, { top = 0, bottom = 0, side = 0 } = {}) {
    const w = Math.max(0, width - 2 * side);
    const h = Math.max(0, height - top - bottom);
    const scale = Math.min(w / (2 * FULL_HALF_W), h / (2 * FULL_HALF_H));
    const cx = width / 2;
    const cy = top + h / 2;
    return {
        width,
        height,
        scale,
        cx,
        cy,
        x: (px) => cx + px * scale,
        y: (py) => cy - py * scale,
    };
}

// The shadow on the ground and the ball above it, each a center and a radius in pixels. The
// shadow shrinks as the ball rises and the ball moves up the picture and grows.
export function ballGeometry(t, x, y, z) {
    const height = Math.max(0, Math.min(HEIGHT_CAP, z || 0));
    const base = Math.max(BALL_MIN_PX, BALL_DRAWN_RADIUS * t.scale);
    return {
        height,
        shadow: { x: t.x(x), y: t.y(y), r: base * Math.max(0.45, 1 - height / (2 * HEIGHT_GROWTH)) },
        ball: { x: t.x(x), y: t.y(y) - height * HEIGHT_LIFT * t.scale, r: base * (1 + height / HEIGHT_GROWTH) },
    };
}

// The radius of a player's disc in pixels.
export function playerRadius(t) {
    return Math.max(PLAYER_MIN_PX, PLAYER_RADIUS * t.scale);
}

// The number of a player, the roster's number when a style lists one, else 1 for a goalkeeper and
// one more than the index for the others, as the 3D view's labels count them.
export function playerNumber(styles, p) {
    const roster = styles && styles[p.team] && styles[p.team].players ? styles[p.team].players[p.index] : null;
    if (roster && roster.number != null) {
        return String(roster.number);
    }
    return String(p.goalkeeper ? 1 : p.index + 1);
}

function rgb(c, fallback) {
    return Array.isArray(c) && c.length >= 3 ? `rgb(${c[0] | 0}, ${c[1] | 0}, ${c[2] | 0})` : fallback;
}

// Dark ink on a light color, light ink on a dark one, by the color's luminance.
export function inkFor(c) {
    if (!Array.isArray(c) || c.length < 3) {
        return '#ffffff';
    }
    const lum = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    return lum > 150 ? '#111111' : '#ffffff';
}

// The colors of each team, from the kit styles the page resolved when it has them and from the
// header's team colors otherwise. Each holds the fill and ink of an outfield player and of the
// goalkeeper.
export function teamPaint(header, styles = null) {
    const fallback = [[214, 48, 49], [9, 132, 227]];
    return [0, 1].map((t) => {
        const style = styles && styles[t];
        const team = (header && header.teams && header.teams[t]) || {};
        const primary = (style && style.kit && style.kit.primary) || team.color || fallback[t];
        const secondary = (style && style.kit && style.kit.secondary) || team.secondary || [255, 255, 255];
        const keeper = (style && style.goalkeeper && style.goalkeeper.primary) || secondary;
        return {
            fill: rgb(primary, '#888'),
            edge: rgb(secondary, '#fff'),
            ink: inkFor(primary),
            keeper: rgb(keeper, '#ccc'),
            keeperInk: inkFor(keeper),
        };
    });
}

// The scene of a moment of the timeline, frame a blended towards frame b by w, as the 3D view
// blends them. Each player has the position of its root node, its team and the flags of frame a.
export function sceneFromFrames(header, a, b = null, w = 0) {
    const da = a.data;
    const db = b ? b.data : da;
    const k = b ? w : 0;
    const lerp = (i) => da[i] + (db[i] - da[i]) * k;
    const players = header.players.map((p, i) => {
        const o = NODES_FLOAT + i * PLAYER_FLOATS;
        const flags = a.playerFlags ? a.playerFlags[i] : 1;
        return {
            slot: i,
            x: lerp(o),
            y: lerp(o + 1),
            team: p.team,
            index: p.index,
            goalkeeper: !!p.goalkeeper,
            active: !!(flags & 1),
            controlled: !!(flags & 8),
            owner: a.ownedPlayer === i,
        };
    });
    return {
        players,
        ball: [lerp(BALL_FLOAT), lerp(BALL_FLOAT + 1), lerp(BALL_FLOAT + 2)],
        score: [a.scoreLeft, a.scoreRight],
        clockMs: a.timeMs,
        step: a.step,
        mode: a.gameMode,
    };
}

export function formatClock(ms) {
    const total = Math.max(0, Math.floor((ms || 0) / 1000));
    return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
}

// The grass, its surround and the markings.
export function drawPitch(ctx, t) {
    ctx.fillStyle = SURROUND;
    ctx.fillRect(0, 0, t.width, t.height);
    const s = t.scale;
    ctx.fillStyle = GRASS;
    ctx.fillRect(t.x(-FULL_HALF_W), t.y(FULL_HALF_H), 2 * FULL_HALF_W * s, 2 * FULL_HALF_H * s);
    ctx.strokeStyle = LINES;
    ctx.fillStyle = LINES;
    ctx.lineWidth = Math.max(1, 0.12 * s);
    const line = (x0, y0, x1, y1) => {
        ctx.beginPath();
        ctx.moveTo(t.x(x0), t.y(y0));
        ctx.lineTo(t.x(x1), t.y(y1));
        ctx.stroke();
    };
    // Engine angles turn counterclockwise, the canvas's y runs down, so they turn the other way.
    const arc = (x, y, r, a0, a1) => {
        ctx.beginPath();
        ctx.arc(t.x(x), t.y(y), r * s, -a1, -a0);
        ctx.stroke();
    };
    const spot = (x, y) => {
        ctx.beginPath();
        ctx.arc(t.x(x), t.y(y), Math.max(1, 0.2 * s), 0, Math.PI * 2);
        ctx.fill();
    };
    ctx.strokeRect(t.x(-HALF_W), t.y(HALF_H), 2 * HALF_W * s, 2 * HALF_H * s);
    line(0, -HALF_H, 0, HALF_H);
    arc(0, 0, CIRCLE_RADIUS, 0, Math.PI * 2);
    spot(0, 0);
    for (const side of [-1, 1]) {
        const gx = side * HALF_W;
        const box = side * (HALF_W - PENALTY_DEPTH);
        const area = side * (HALF_W - GOAL_AREA_DEPTH);
        line(gx, -PENALTY_HALF_WIDTH, box, -PENALTY_HALF_WIDTH);
        line(box, -PENALTY_HALF_WIDTH, box, PENALTY_HALF_WIDTH);
        line(box, PENALTY_HALF_WIDTH, gx, PENALTY_HALF_WIDTH);
        line(gx, -GOAL_AREA_HALF_WIDTH, area, -GOAL_AREA_HALF_WIDTH);
        line(area, -GOAL_AREA_HALF_WIDTH, area, GOAL_AREA_HALF_WIDTH);
        line(area, GOAL_AREA_HALF_WIDTH, gx, GOAL_AREA_HALF_WIDTH);
        const sx = side * (HALF_W - PENALTY_SPOT);
        spot(sx, 0);
        const half = Math.acos((PENALTY_DEPTH - PENALTY_SPOT) / CIRCLE_RADIUS);
        if (side < 0) {
            arc(sx, 0, CIRCLE_RADIUS, -half, half);
        } else {
            arc(sx, 0, CIRCLE_RADIUS, Math.PI - half, Math.PI + half);
        }
        for (const cy of [-1, 1]) {
            const start = side < 0 ? (cy < 0 ? 0 : -Math.PI / 2) : (cy < 0 ? Math.PI / 2 : Math.PI);
            arc(gx, cy * HALF_H, CORNER_RADIUS, start, start + Math.PI / 2);
        }
        // The goal, its mouth on the line and its depth behind it.
        const back = side * (HALF_W + GOAL_DEPTH);
        ctx.strokeRect(Math.min(t.x(gx), t.x(back)), t.y(GOAL_HALF_WIDTH), GOAL_DEPTH * s, 2 * GOAL_HALF_WIDTH * s);
    }
}

// The players, the ball and, when options.scoreboard is given, a strip at the top of the canvas
// with that text. options.numbers draws each player's number from options.numberOf(player) on
// discs large enough to hold it.
export function drawScene(ctx, t, scene, paint, options = {}) {
    const r = playerRadius(t);
    const numbers = options.numbers !== false && r >= 5;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.font = `bold ${Math.max(7, Math.round(r * 1.1))}px system-ui, sans-serif`;
    for (const p of scene.players) {
        if (!p.active) {
            continue;
        }
        const colors = paint[p.team] || paint[0];
        const x = t.x(p.x);
        const y = t.y(p.y);
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fillStyle = p.goalkeeper ? colors.keeper : colors.fill;
        ctx.fill();
        ctx.lineWidth = Math.max(1, r * 0.18);
        ctx.strokeStyle = p.owner ? '#ffffff' : colors.edge;
        ctx.stroke();
        if (p.controlled && options.controlled !== false) {
            ctx.beginPath();
            ctx.arc(x, y, r * 1.45, 0, Math.PI * 2);
            ctx.lineWidth = Math.max(1, r * 0.15);
            ctx.strokeStyle = 'rgba(255, 235, 59, 0.9)';
            ctx.stroke();
        }
        if (numbers && options.numberOf) {
            ctx.fillStyle = p.goalkeeper ? colors.keeperInk : colors.ink;
            ctx.fillText(options.numberOf(p), x, y + r * 0.06);
        }
    }
    if (scene.ball) {
        drawBall(ctx, t, scene.ball);
    }
    if (options.scoreboard) {
        const size = Math.max(10, Math.min(16, Math.round(t.height * 0.09)));
        ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
        ctx.fillRect(0, 0, t.width, size + 8);
        ctx.fillStyle = '#ffffff';
        ctx.font = `${size}px system-ui, sans-serif`;
        ctx.textAlign = 'center';
        ctx.fillText(options.scoreboard, t.width / 2, (size + 8) / 2);
    }
}

// The ball over its shadow, joined by a thin line while it is in the air.
function drawBall(ctx, t, ball) {
    const g = ballGeometry(t, ball[0], ball[1], ball[2]);
    ctx.beginPath();
    ctx.ellipse(g.shadow.x, g.shadow.y, g.shadow.r, g.shadow.r * 0.7, 0, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
    ctx.fill();
    if (g.ball.y < g.shadow.y - 1) {
        ctx.beginPath();
        ctx.moveTo(g.shadow.x, g.shadow.y);
        ctx.lineTo(g.ball.x, g.ball.y);
        ctx.lineWidth = 1;
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.35)';
        ctx.stroke();
    }
    ctx.beginPath();
    ctx.arc(g.ball.x, g.ball.y, g.ball.r, 0, Math.PI * 2);
    ctx.fillStyle = '#ffffff';
    ctx.fill();
    ctx.lineWidth = Math.max(1, g.ball.r * 0.3);
    ctx.strokeStyle = '#111111';
    ctx.stroke();
}
