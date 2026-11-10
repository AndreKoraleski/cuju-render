// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The static rules of package shaders on the page, the main checks of _glsl.py again before
// anything compiles, with no three.js, so Node tests load them as they are.

export const HOOKS = ['cujuVertex', 'cujuColor', 'cujuEmissive', 'cujuRoughness', 'cujuMetalness'];
export const MODES = ['chunks', 'material'];

export function stripComments(text) {
    return String(text).replace(/\/\*[\s\S]*?(\*\/|$)/g, ' ').replace(/\/\/[^\n]*/g, ' ');
}

// The main static rules of _glsl.py again, a second line of defence before a compile. Returns a
// list of problems, empty when the text may compile.
export function checkShader(text, mode = 'chunks') {
    const problems = [];
    if (typeof text !== 'string' || text.length > 256 * 1024) {
        return ['expected the text of a shader of at most 256 KB'];
    }
    const code = stripComments(text);
    if (/#\s*(version|extension)\b/.test(code)) {
        problems.push('names a version or an extension, which the renderer writes');
    }
    if (/\buniform\b/.test(code)) {
        problems.push('declares a uniform, which the renderer declares');
    }
    if (/\b(while|do)\b/.test(code)) {
        problems.push('holds a while or do loop');
    }
    for (const m of code.matchAll(/#\s*include\s*<([^>]*)>/g)) {
        if (m[1] !== 'cuju_noise') {
            problems.push(`includes ${m[1]}`);
        }
    }
    for (const m of code.matchAll(/\bfor\s*\(([^;]*);([^;]*);([^)]*)\)/g)) {
        const init = /int\s+\w+\s*=\s*(-?\d+)/.exec(m[1]);
        const bound = /[<>]=?\s*(-?\d+|\w+)/.exec(m[2]);
        if (!init || !bound) {
            problems.push('holds a loop without constant bounds');
        }
    }
    if (mode === 'chunks') {
        if (!HOOKS.some((h) => new RegExp(`\\b${h}\\s*\\(`).test(code))) {
            problems.push('defines no hook');
        }
    } else if (mode === 'material') {
        const v = code.indexOf('#pragma cuju vertex');
        const f = code.indexOf('#pragma cuju fragment');
        if (v < 0 || f < v) {
            problems.push('expected a vertex section and then a fragment section');
        }
    } else {
        problems.push(`has no mode ${mode}`);
    }
    return problems;
}

