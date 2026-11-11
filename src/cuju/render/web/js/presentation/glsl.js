// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The static rules of package shaders on the page, the main checks of _glsl.py again before
// anything compiles, with no three.js, so Node tests load them as they are. Besides the forms of
// loops, uniforms and includes, the page counts the cost of what a vertex or a fragment runs as
// _glsl.py does, the times the body of nested loops runs and the words of code it runs, each
// through the loops around it, the helper functions it calls and the macros it names, and the
// words of the whole file once its macros expand.

export const HOOKS = ['cujuVertex', 'cujuColor', 'cujuEmissive', 'cujuRoughness', 'cujuMetalness'];
export const MODES = ['chunks', 'material'];
export const MAXIMUM_ITERATIONS = 256;
export const MAXIMUM_NESTED = 1024;
export const MAXIMUM_FETCHES = 16;
export const MAXIMUM_WORK = 65536;
export const MAXIMUM_EXPANDED = 262144;
// The largest count the checks keep, far past every limit, so no count grows past exact numbers.
const CAP = 2 ** 52;

const FETCHES = new Set([
    'texture', 'textureProj', 'textureLod', 'textureOffset', 'textureProjOffset', 'textureLodOffset',
    'textureProjLod', 'textureProjLodOffset', 'textureGrad', 'textureGradOffset', 'textureProjGrad',
    'textureProjGradOffset', 'texelFetch', 'texelFetchOffset', 'texture2D', 'texture2DProj',
    'texture2DLod', 'texture2DProjLod', 'texture2DLodEXT', 'texture2DProjLodEXT', 'texture2DGradEXT',
    'texture2DProjGradEXT', 'textureCube', 'textureCubeLod', 'textureCubeLodEXT', 'textureCubeGradEXT',
]);
const VALUE = String.raw`[-+]?\s*(?:0[xX][0-9a-fA-F]+|\d+)[uU]?|[A-Za-z_]\w*`;
const INIT = new RegExp(String.raw`^(?:(?:lowp|mediump|highp)\s+)?int\s+([A-Za-z_]\w*)\s*=\s*(${VALUE})$`);
const CONDITION = new RegExp(String.raw`^([A-Za-z_]\w*)\s*(<=|>=|<|>)\s*(${VALUE})$`);
const STEP = new RegExp(String.raw`^(?:([A-Za-z_]\w*)\s*(\+\+|--)|(\+\+|--)\s*([A-Za-z_]\w*)|([A-Za-z_]\w*)\s*(\+=|-=)\s*(${VALUE}))$`);
const LITERAL = /^\s*([A-Za-z_]\w*)\s*=\s*([-+]?\s*(?:0[xX][0-9a-fA-F]+|\d+)[uU]?)\s*$/;
const HEAD = /(?:(?:lowp|mediump|highp)\s+)?([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*\(([^()]*)\)\s*$/;
const TOKEN = /[A-Za-z_]\w*|\d+(?:\.\d*)?|\.\d+/g;
const CALL = /\b([A-Za-z_]\w*)\s*\(/g;

export function stripComments(text) {
    return String(text).replace(/\/\*[\s\S]*?(\*\/|$)/g, ' ').replace(/\/\/[^\n]*/g, ' ');
}

// The text with its comments and line continuations as spaces, each character at its offset.
function clean(text) {
    return String(text).replace(/\/\/[^\n]*|\/\*[\s\S]*?(?:\*\/|$)|\\\n/g, (m) => (m === '\\\n' ? '  ' : m.replace(/[^\n]/g, ' ')));
}

// The code with its directive lines as spaces, and the text after each #define.
function directives(code) {
    const defines = [];
    const lines = code.split('\n').map((line) => {
        const stripped = line.trimStart();
        if (!stripped.startsWith('#')) {
            return line;
        }
        const m = /^#\s*define\s+(.*)$/.exec(stripped);
        if (m) {
            defines.push(m[1]);
        }
        return ' '.repeat(line.length);
    });
    return { code: lines.join('\n'), defines };
}

function integer(value, constants) {
    const v = value.replace(/\s/g, '').replace(/[uU]$/, '');
    if (constants.has(v)) {
        return constants.get(v);
    }
    const sign = v.startsWith('-') ? -1 : 1;
    const digits = v.replace(/^[-+]+/, '');
    if (/^0[xX][0-9a-fA-F]+$/.test(digits)) {
        return sign * parseInt(digits.slice(2), 16);
    }
    return /^\d+$/.test(digits) ? sign * parseInt(digits, 10) : null;
}

function constantsOf(code) {
    const found = new Map();
    for (const m of code.matchAll(/\bconst\s+(?:(?:lowp|mediump|highp)\s+)?int\s+([^;]*);/g)) {
        for (const part of m[1].split(',')) {
            const item = LITERAL.exec(part);
            if (item && !found.has(item[1])) {
                const value = integer(item[2], new Map());
                if (value !== null) {
                    found.set(item[1], value);
                }
            }
        }
    }
    return found;
}

function trips(start, op, bound, step) {
    if (op === '<' || op === '<=') {
        const last = op === '<=' ? bound : bound - 1;
        if (start > last) {
            return 0;
        }
        return step <= 0 ? null : Math.floor((last - start) / step) + 1;
    }
    const last = op === '>=' ? bound : bound + 1;
    if (start < last) {
        return 0;
    }
    return step >= 0 ? null : Math.floor((start - last) / -step) + 1;
}

// The offset of the bracket that closes the one at start, or -1.
function closing(code, start, open, close) {
    let depth = 0;
    for (let i = start; i < code.length; i++) {
        if (code[i] === open) {
            depth++;
        } else if (code[i] === close && --depth === 0) {
            return i;
        }
    }
    return -1;
}

function split(header) {
    const parts = [];
    let depth = 0;
    let last = 0;
    for (let i = 0; i < header.length; i++) {
        const c = header[i];
        if (c === '(') {
            depth++;
        } else if (c === ')') {
            depth--;
        } else if (c === ';' && depth === 0) {
            parts.push(header.slice(last, i));
            last = i + 1;
        }
    }
    parts.push(header.slice(last));
    return parts;
}

// The trip count of a loop's header, or null for one whose count cannot be read.
function headerTrips(parts, constants) {
    if (parts.length !== 3) {
        return null;
    }
    const init = INIT.exec(parts[0].trim());
    const condition = CONDITION.exec(parts[1].trim());
    const step = STEP.exec(parts[2].trim());
    if (!init || !condition || !step) {
        return null;
    }
    const start = integer(init[2], constants);
    const bound = integer(condition[3], constants);
    let amount = 0;
    if (step[2]) {
        amount = step[2] === '++' ? 1 : -1;
    } else if (step[3]) {
        amount = step[3] === '++' ? 1 : -1;
    } else {
        const by = integer(step[7], constants);
        amount = by === null ? null : step[6] === '+=' ? by : -by;
    }
    if (start === null || bound === null || amount === null) {
        return null;
    }
    return trips(start, condition[2], bound, amount);
}

// The loops of the code, each the span of its body and its trip count, read as _glsl.py reads
// them, sorted by where their body starts. A loop whose count cannot be read or that never ends
// counts MAXIMUM_ITERATIONS.
function loopsOf(code, constants) {
    const loops = [];
    const seen = new Set();
    let loop = null;
    const statement = (start) => {
        let i = start;
        while (i < code.length && /\s/.test(code[i])) {
            i++;
        }
        if (code[i] === '{') {
            const end = closing(code, i, '{', '}');
            return end < 0 ? code.length : end + 1;
        }
        if (/^for\b/.test(code.slice(i, i + 4))) {
            return loop(i);
        }
        let depth = 0;
        for (; i < code.length; i++) {
            const c = code[i];
            if (c === '(' || c === '{') {
                depth++;
            } else if (c === ')' || c === '}') {
                if (--depth < 0) {
                    return i;
                }
            } else if (c === ';' && depth === 0) {
                return i + 1;
            }
        }
        return code.length;
    };
    loop = (start) => {
        seen.add(start);
        const open = code.indexOf('(', start);
        const close = open >= 0 ? closing(code, open, '(', ')') : -1;
        if (open < 0 || code.slice(start + 3, open).trim() || close < 0) {
            return start + 3;
        }
        const end = statement(close + 1);
        loops.push([close + 1, end, headerTrips(split(code.slice(open + 1, close)), constants) ?? MAXIMUM_ITERATIONS]);
        return end;
    };
    for (const m of code.matchAll(/\bfor\b/g)) {
        if (!seen.has(m.index)) {
            loop(m.index);
        }
    }
    return loops.sort((a, b) => a[0] - b[0]);
}

// How many times the code at each of offsets runs, in order, the product of the counts of the
// loops of the function from low to high around it, and the most times a loop body runs there.
function weights(loops, offsets, low, high) {
    const stack = [];
    const out = [];
    let deepest = 1;
    let k = 0;
    while (k < loops.length && loops[k][0] < low) {
        k++;
    }
    const enter = (limit) => {
        while (k < loops.length && loops[k][0] <= limit && loops[k][0] < high) {
            const [start, end, count] = loops[k++];
            while (stack.length && stack[stack.length - 1][0] <= start) {
                stack.pop();
            }
            const product = Math.min(CAP, (stack.length ? stack[stack.length - 1][1] : 1) * count);
            stack.push([end, product]);
            deepest = Math.max(deepest, product);
        }
    };
    for (const offset of offsets) {
        enter(offset);
        while (stack.length && stack[stack.length - 1][0] <= offset) {
            stack.pop();
        }
        out.push(stack.length ? stack[stack.length - 1][1] : 1);
    }
    enter(high);
    return { out, deepest };
}

function functionsOf(code) {
    const found = [];
    let i = code.indexOf('{');
    while (i >= 0) {
        const low = Math.max(0, i - 400);
        const head = HEAD.exec(code.slice(low, i));
        const end = closing(code, i, '{', '}');
        if (head && !['struct', 'return', 'else'].includes(head[1])) {
            found.push({ type: head[1], name: head[2], at: low + head.index, body: [i, end < 0 ? code.length : end] });
        }
        if (end < 0) {
            break;
        }
        i = code.indexOf('{', end + 1);
    }
    return found;
}

// The words each macro expands to, through the macros it names.
function sizesOf(defines) {
    const bodies = new Map();
    for (const rest of defines) {
        const m = /^([A-Za-z_]\w*)(?:\(([^)]*)\))?([\s\S]*)$/.exec(rest);
        if (m) {
            const parameters = new Set((m[2] || '').match(/[A-Za-z_]\w*/g) || []);
            bodies.set(m[1], (m[3].match(TOKEN) || []).filter((w) => !parameters.has(w)));
        }
    }
    const sizes = new Map();
    const busy = new Set();
    const size = (name) => {
        if (sizes.has(name)) {
            return sizes.get(name);
        }
        if (busy.has(name)) {
            // The preprocessor never expands a macro inside its own expansion.
            return 1;
        }
        busy.add(name);
        let total = 0;
        for (const word of bodies.get(name)) {
            total += bodies.has(word) ? size(word) : 1;
        }
        busy.delete(name);
        sizes.set(name, Math.max(1, total));
        return sizes.get(name);
    };
    for (const name of bodies.keys()) {
        size(name);
    }
    return sizes;
}

// The cost of each function, its fetches, the words of code it runs and the most times a body of
// its nested loops runs, counted through loops and helper calls.
function costsOf(code, loops, functions, sizes) {
    const byName = new Map();
    for (const f of functions) {
        if (!byName.has(f.name)) {
            byName.set(f.name, []);
        }
        byName.get(f.name).push(f);
    }
    const costs = new Map();
    const busy = new Set();
    const cost = (name) => {
        if (costs.has(name)) {
            return costs.get(name);
        }
        if (busy.has(name)) {
            return [0, 0, 1];
        }
        busy.add(name);
        // Overloads share a name, so a call counts the costliest of them.
        const total = [0, 0, 1];
        for (const f of byName.get(name)) {
            const [start, end] = f.body;
            const body = code.slice(start, end);
            const tokens = [...body.matchAll(TOKEN)];
            const { out, deepest } = weights(loops, tokens.map((m) => start + m.index), start, end);
            const at = new Map(tokens.map((m, i) => [m.index, out[i]]));
            const own = [0, 0, deepest];
            tokens.forEach((m, i) => {
                own[1] = Math.min(CAP, own[1] + out[i] * (sizes.get(m[0]) || 1));
            });
            for (const m of body.matchAll(CALL)) {
                const w = at.get(m.index) || 1;
                if (FETCHES.has(m[1])) {
                    own[0] = Math.min(CAP, own[0] + w);
                } else if (byName.has(m[1])) {
                    const inner = cost(m[1]);
                    own[0] = Math.min(CAP, own[0] + w * inner[0]);
                    own[1] = Math.min(CAP, own[1] + w * inner[1]);
                    own[2] = Math.max(own[2], Math.min(CAP, w * inner[2]));
                }
            }
            for (let k = 0; k < 3; k++) {
                total[k] = Math.max(total[k], own[k]);
            }
        }
        busy.delete(name);
        costs.set(name, total);
        return total;
    };
    for (const name of byName.keys()) {
        cost(name);
    }
    return costs;
}

function limits(where, [fetches, work, nested], problems, fragment) {
    if (nested > MAXIMUM_NESTED) {
        problems.push(`holds nested loops in ${where} that run their body ${nested} times, at most ${MAXIMUM_NESTED}`);
    }
    if (work > MAXIMUM_WORK) {
        problems.push(`runs ${work} words of code in ${where}, at most ${MAXIMUM_WORK}`);
    }
    if (fragment && fetches > MAXIMUM_FETCHES) {
        problems.push(`fetches textures ${fetches} times in ${where}, at most ${MAXIMUM_FETCHES}`);
    }
}

// The cost rules of _glsl.py, the length of each loop, the nesting, the work and the fetches of
// what a vertex or a fragment runs and the size of the file once its macros expand.
function checkCost(text, mode, problems) {
    const cleaned = clean(text);
    const { code, defines } = directives(cleaned);
    const sizes = sizesOf(defines);
    let expanded = 0;
    for (const m of code.matchAll(TOKEN)) {
        expanded += sizes.get(m[0]) || 1;
    }
    if (expanded > MAXIMUM_EXPANDED) {
        problems.push(`holds ${expanded} words once its macros expand, at most ${MAXIMUM_EXPANDED}`);
    }
    const loops = loopsOf(code, constantsOf(code));
    const longest = loops.reduce((most, l) => Math.max(most, l[2]), 0);
    if (longest > MAXIMUM_ITERATIONS) {
        problems.push(`runs a loop ${longest} times, at most ${MAXIMUM_ITERATIONS}`);
    }
    const functions = functionsOf(code);
    if (mode === 'chunks') {
        const costs = costsOf(code, loops, functions, sizes);
        const hooks = HOOKS.filter((h) => costs.has(h)).map((h) => costs.get(h));
        const sum = (k) => hooks.reduce((a, c) => a + c[k], 0);
        limits('the hooks', [sum(0), sum(1), Math.max(1, ...hooks.map((c) => c[2]))], problems, true);
        return;
    }
    const vertex = cleaned.indexOf('#pragma cuju vertex');
    const fragment = cleaned.indexOf('#pragma cuju fragment');
    if (vertex < 0 || fragment < vertex) {
        return;
    }
    const shared = functions.filter((f) => f.at < vertex);
    for (const [kind, low, high] of [['vertex', vertex, fragment], ['fragment', fragment, code.length]]) {
        const own = functions.filter((f) => f.at >= low && f.at < high);
        const names = new Set(own.map((f) => f.name));
        const costs = costsOf(code, loops, shared.filter((f) => !names.has(f.name)).concat(own), sizes);
        limits(`the ${kind} section`, costs.get('main') || [0, 0, 1], problems, kind === 'fragment');
    }
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
        return problems;
    }
    try {
        checkCost(text, mode, problems);
    } catch {
        // A shader whose loops or helper calls nest past the depth of the stack cannot be counted.
        problems.push('nests its loops or its helper calls too deeply to count');
    }
    return problems;
}
