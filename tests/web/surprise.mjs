// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Tests of Surprise me, the seeded generator of teams, run from the repository root with
// `node tests/web/surprise.mjs`.

import assert from 'node:assert/strict';
import { cpSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Node 18 reads a .js file outside a package of type module as CommonJS, so the page's modules load
// from a copy beside a package file that names them modules. kits.js imports three for its
// textures, which a small stub stands in for, the generator never draws.
const folder = mkdtempSync(join(tmpdir(), 'cuju-surprise-'));
const web = new URL('../../src/cuju/render/web/js/', import.meta.url);
for (const name of ['players/kits.js', 'teams/surprise.js']) {
    cpSync(fileURLToPath(new URL(name, web)), join(folder, name));
}
writeFileSync(join(folder, 'package.json'), '{"type": "module"}\n');
mkdirSync(join(folder, 'node_modules', 'three'), { recursive: true });
writeFileSync(join(folder, 'node_modules', 'three', 'package.json'), '{"name": "three", "type": "module", "main": "index.js"}\n');
writeFileSync(join(folder, 'node_modules', 'three', 'index.js'),
    'export class Color {}\nexport class CanvasTexture {}\nexport const SRGBColorSpace = "srgb";\n');
process.on('exit', () => rmSync(folder, { recursive: true, force: true }));
const kits = await import(pathToFileURL(join(folder, 'players/kits.js')).href);
const generator = await import(pathToFileURL(join(folder, 'teams/surprise.js')).href);
const { BUILTIN_KIT, DEFAULT_KIT, KIT_CLASH, deltaE, kitDifference } = kits;
const {
    COMMON_KITS, KIT_STYLES, STYLE_IDS, badgeFor, fallbackStyle, mulberry32, seedNumber, styleProblems,
    surprise,
} = generator;

// The WCAG contrast ratio, written again here so the test does not lean on the module's own.
function ratio(a, b) {
    const lum = (c) => {
        const [r, g, bl] = c.map((v) => {
            const s = v / 255;
            return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
        });
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
    };
    const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
}

const numberOn = (number, kit) => ({ white: [250, 250, 250], black: [20, 20, 20] }[number] || kit.secondary);
const isColor = (c) => Array.isArray(c) && c.length === 3 && c.every((v) => Number.isInteger(v) && v >= 0 && v <= 255);
const plain = (c) => ({ pattern: 'plain', primary: c, secondary: c, shorts: c, socks: c });
// The opponents of the brief, written out here as well.
const OPPONENTS = [
    BUILTIN_KIT, DEFAULT_KIT, plain([200, 30, 45]), plain([245, 245, 245]), plain([25, 70, 190]),
    plain([22, 22, 26]), plain([250, 210, 20]), plain([20, 140, 60]),
];
const REAL = [
    'Real', 'Inter', 'Ajax', 'Celtic', 'Juventus', 'Arsenal', 'Chelsea', 'Liverpool', 'Everton',
    'Bayern', 'Benfica', 'Porto', 'Boca', 'Galaxy', 'Sounders', 'Red Devils', 'Black Stars',
    'Super Eagles', 'Flying Eagles', 'Crimson Tide', 'Mighty Ducks', 'Black Cats', 'Wolves',
    'Manchester', 'Madrid', 'Milan', 'Barcelona', 'Dortmund', 'Glasgow',
];

// FNV-1a over the JSON of many teams, pinned below so every machine draws the same teams.
function digest(values) {
    let hash = 0x811c9dc5;
    const text = JSON.stringify(values);
    for (let i = 0; i < text.length; i++) {
        hash ^= text.charCodeAt(i);
        hash = Math.imul(hash, 0x01000193);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
}

test('the generator is a known mulberry32 over an FNV-1a seed', () => {
    assert.equal(seedNumber(''), 0x811c9dc5);
    assert.equal(seedNumber('a'), 0xe40c292c);
    assert.equal(seedNumber(' 42 '), seedNumber('42'));
    // The reference mulberry32 by Tommy Ettinger, as commonly written.
    const reference = (a) => () => {
        let t = (a += 0x6d2b79f5);
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    for (const seed of [0, 1, 0x811c9dc5, 0xffffffff]) {
        const ours = mulberry32(seed);
        const theirs = reference(seed | 0);
        for (let i = 0; i < 100; i++) {
            assert.equal(ours(), theirs());
        }
    }
});

test('a seed and a style give the same team every time and on every machine', () => {
    for (const style of STYLE_IDS) {
        for (const seed of ['harbor', 7, '0', 'Northgate United']) {
            assert.deepEqual(surprise({ seed, style }), surprise({ seed: String(seed), style }));
        }
    }
    assert.notDeepEqual(surprise({ seed: 1 }).style.kit, surprise({ seed: 2 }).style.kit);
    // The name and roster follow the seed alone, the kit style changes only the colors.
    const a = surprise({ seed: 'same', style: 'hoops' });
    const b = surprise({ seed: 'same', style: 'neon' });
    assert.equal(a.name, b.name);
    assert.deepEqual(a.style.players, b.style.players);
    // Any makes the same team as the style it picked.
    for (let seed = 0; seed < 50; seed++) {
        const any = surprise({ seed });
        assert.deepEqual(surprise({ seed, style: any.kitStyle }), any);
    }
    const all = [];
    for (const style of STYLE_IDS) {
        for (let seed = 0; seed < 40; seed++) {
            all.push(surprise({ seed, style }));
        }
    }
    assert.equal(digest(all), '89184336');
});

test('a surprise without a seed draws one that makes it again', () => {
    for (let i = 0; i < 20; i++) {
        const first = surprise({});
        assert.match(first.seed, /^[1-9][0-9]{5}$/);
        assert.deepEqual(surprise({ seed: first.seed }), first);
        const styled = surprise({ seed: '', style: 'sash' });
        assert.deepEqual(surprise({ seed: styled.seed, style: 'sash' }), styled);
    }
});

test('options outside their choices are refused', () => {
    assert.throws(() => surprise({ seed: 1, style: 'tartan' }), /kit style/);
    assert.throws(() => surprise({ seed: 1, format: '7v7' }), /format/);
    assert.equal(surprise({ seed: 1, style: null }).seed, '1');
});

test('every style over thousands of seeds keeps its colors readable and clear of common kits', () => {
    let count = 0;
    const patterns = new Map(KIT_STYLES.map((s) => [s.id, s.pattern]));
    const schemes = new Set();
    for (const style of STYLE_IDS) {
        const seeds = style === 'any' ? 800 : 400;
        for (let seed = 0; seed < seeds; seed++) {
            const r = surprise({ seed: `t${seed}`, style });
            const { kit, goalkeeper: gk, number } = r.style;
            const where = `${style} seed t${seed}`;
            count++;
            schemes.add(r.scheme);
            assert.deepEqual(styleProblems(r.style, r.kitStyle), [], where);
            if (style !== 'any') {
                assert.equal(r.kitStyle, style, where);
            }
            assert.equal(kit.pattern, patterns.get(r.kitStyle), where);
            for (const c of [kit.primary, kit.secondary, kit.shorts, kit.socks, gk.primary, gk.secondary, gk.shorts, gk.socks, ...r.style.crowd.colors]) {
                assert.ok(isColor(c), `${where} ${JSON.stringify(c)}`);
            }
            assert.ok(['white', 'black', 'secondary'].includes(number), where);
            assert.ok(ratio(numberOn(number, kit), kit.primary) >= 3, `${where} numbers on the shirt`);
            assert.ok(ratio(numberOn(number, gk), gk.primary) >= 3, `${where} numbers on the keeper`);
            if (r.kitStyle === 'minimal') {
                assert.deepEqual(kit.shorts, kit.primary, where);
            } else {
                assert.ok(deltaE(kit.primary, kit.shorts) >= 20, `${where} shirt and shorts`);
            }
            if (kit.pattern !== 'plain') {
                assert.ok(deltaE(kit.primary, kit.secondary) >= 25, `${where} pattern`);
            }
            const keeper = { pattern: 'plain', ...gk };
            assert.ok(kitDifference(keeper, kit) >= KIT_CLASH, `${where} keeper against the kit`);
            for (const opponent of OPPONENTS) {
                assert.ok(kitDifference(kit, opponent) >= KIT_CLASH, `${where} clash ${JSON.stringify(opponent.primary)}`);
                assert.ok(kitDifference(keeper, opponent) >= KIT_CLASH, `${where} keeper clash`);
            }
        }
    }
    assert.ok(count >= 3000);
    assert.equal(schemes.size, 5);
    assert.equal(COMMON_KITS.length, OPPONENTS.length);
});

test('the safe fallback passes every check of its style', () => {
    for (const look of KIT_STYLES) {
        const style = { ...fallbackStyle(look), badge: 'AB' };
        style.crowd = { colors: [style.kit.primary, style.kit.secondary] };
        assert.deepEqual(styleProblems(style, look.id), [], look.id);
    }
});

test('names, badges and rosters are made of the word lists', () => {
    const names = new Set();
    for (let seed = 0; seed < 600; seed++) {
        const r = surprise({ seed: `n${seed}`, format: seed % 2 ? '5v5' : '11v11' });
        names.add(r.name);
        assert.match(r.name, /^[A-Z][a-z]+( [A-Z][a-z]+)+( A?FC)?$|^[A-Z][a-z]+( [A-Z][a-z]+)* A?FC$/, r.name);
        assert.ok(r.name.length <= 60, r.name);
        for (const real of REAL) {
            assert.ok(!r.name.split(' ').join(' ').includes(real), `${r.name} holds ${real}`);
        }
        assert.match(r.badge, /^[A-Z]{1,3}$/, r.badge);
        assert.equal(r.badge, badgeFor(r.name));
        assert.equal(r.style.badge, r.badge);
        const roster = r.style.players.map((p) => p.name);
        assert.equal(roster.length, seed % 2 ? 5 : 11);
        assert.equal(new Set(roster).size, roster.length);
        assert.ok(roster.every((n) => typeof n === 'string' && n.length >= 2 && n.length <= 24));
        assert.deepEqual(Object.keys(r.style).sort(), ['badge', 'crowd', 'goalkeeper', 'kit', 'number', 'players']);
    }
    assert.ok(names.size >= 450, `only ${names.size} names`);
    // A smaller roster is the start of the larger one.
    const big = surprise({ seed: 'roster' }).style.players;
    assert.deepEqual(surprise({ seed: 'roster', format: '5v5' }).style.players, big.slice(0, 5));
    assert.equal(badgeFor('Harbor Herons FC'), 'HH');
    assert.equal(badgeFor('Northgate United'), 'NU');
    assert.equal(badgeFor('Quillford Heath Lynxes'), 'QHL');
    assert.equal(badgeFor('Comets'), 'COM');
    assert.equal(badgeFor(''), '');
});
