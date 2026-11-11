// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Surprise me, a seeded generator of harmonious teams. A seed and a kit style give the same name,
// badge, kit, goalkeeper kit, number color, fans and roster names on every machine. Colors come
// from color schemes in CIE LCh, are checked for readable numbers by the WCAG contrast ratio, for
// shirts and shorts apart by CIEDE2000, and against common kits by the viewer's own clash measure.
// The module runs in the page and in Node, where the three package or a stub of it serves the
// import of kits.js.

import {
    BUILTIN_KIT, DEFAULT_GOALKEEPER, DEFAULT_KIT, FORMATS, KIT_CLASH, ciede2000, deltaE, kitDifference,
    labToRgb, rgbToLab,
} from '../players/kits.js';

// The kit styles, each setting the pattern, the color schemes it draws from and how the colors
// relate. Minimal wears shorts of the shirt's color.
export const KIT_STYLES = [
    { id: 'stripes', name: 'Classic stripes', pattern: 'stripes', schemes: ['complementary', 'split', 'analogous', 'monochrome'] },
    { id: 'hoops', name: 'Retro hoops', pattern: 'hoops', schemes: ['analogous', 'triadic', 'complementary'] },
    { id: 'sash', name: 'Sash', pattern: 'sash', schemes: ['split', 'complementary', 'triadic'] },
    { id: 'halves', name: 'Halves', pattern: 'halves', schemes: ['complementary', 'triadic', 'split'] },
    { id: 'checkers', name: 'Checkers', pattern: 'checkers', schemes: ['complementary', 'monochrome', 'analogous'] },
    { id: 'minimal', name: 'Minimal', pattern: 'plain', schemes: ['monochrome', 'analogous'], sameShorts: true },
    { id: 'neon', name: 'Bold neon', pattern: 'plain', schemes: ['complementary', 'triadic', 'split'] },
];
export const STYLE_IDS = ['any', ...KIT_STYLES.map((s) => s.id)];

// The hue offsets of each scheme in degrees, from the shirt's hue.
const SCHEMES = {
    complementary: { name: 'complementary', hues: [180] },
    split: { name: 'split complementary', hues: [150, 210] },
    analogous: { name: 'analogous', hues: [30, -30, 45, -45] },
    triadic: { name: 'triadic', hues: [120, 240] },
    monochrome: { name: 'monochrome', hues: [0] },
};

// The smallest CIEDE2000 between the shirt and its pattern, and between the shirt and the shorts.
export const MIN_PATTERN = 25;
export const MIN_SHORTS = 20;
// The smallest WCAG contrast ratio between the numbers and the shirt.
export const MIN_NUMBER_CONTRAST = 3;
// The numbers as kits.js numberColor draws them.
const NUMBER_RGB = { white: [250, 250, 250], black: [20, 20, 20] };

const plainKit = (c, shorts = c) => ({ pattern: 'plain', primary: c, secondary: c, shorts, socks: c });

// The kits a generated team must stay clear of, by the measure the viewer uses to pick an away kit.
export const COMMON_KITS = [
    { name: 'Built-in AI', kit: BUILTIN_KIT },
    { name: 'Default', kit: DEFAULT_KIT },
    { name: 'Red', kit: plainKit([200, 30, 45]) },
    { name: 'White', kit: plainKit([245, 245, 245]) },
    { name: 'Blue', kit: plainKit([25, 70, 190]) },
    { name: 'Black', kit: plainKit([22, 22, 26]) },
    { name: 'Yellow', kit: plainKit([250, 210, 20]) },
    { name: 'Green', kit: plainKit([20, 140, 60]) },
];

const NEUTRALS = {
    white: [246, 246, 244],
    cream: [238, 228, 204],
    black: [22, 22, 26],
    charcoal: [52, 54, 62],
};

const PLACES = [
    'Harbor', 'Northgate', 'Eastbrook', 'Westmere', 'Kestrel Bay', 'Mossvale', 'Ironcrest',
    'Silverholm', 'Ashmere', 'Brightwater', 'Elmridge', 'Foxhollow', 'Glenwick', 'Highmoor',
    'Larkspur', 'Oakhaven', 'Pinecrest', 'Ravenmoor', 'Saltmarsh', 'Valewood', 'Willowmere',
    'Amberfield', 'Duskwater', 'Embervale', 'Frostholm', 'Hollowmere', 'Juniper Point',
    'Kingsreach', 'Lanternside', 'Pebblebrook', 'Seabright', 'Tidewater', 'Marigold Hill',
    'Copperdale', 'Starling Cove', 'Briarwood', 'Cloudmere', 'Thistlebank', 'Quillford Heath',
    'Nettlecombe Vale',
];
const ADJECTIVES = [
    'Crimson', 'Amber', 'Cobalt', 'Copper', 'Velvet', 'Electric', 'Midnight', 'Roaring', 'Silver',
    'Swift', 'Daring', 'Flying', 'Wandering', 'Rising', 'Lucky', 'Jolly', 'Bouncing', 'Dashing',
    'Sparkling', 'Cosmic', 'Thundering', 'Frosty', 'Sunny', 'Howling', 'Gallant', 'Nimble',
    'Fearless', 'Merry', 'Stormy', 'Twilight',
];
const CREATURES = [
    'Herons', 'Comets', 'Otters', 'Badgers', 'Lynxes', 'Hares', 'Kestrels', 'Owls', 'Puffins',
    'Moths', 'Newts', 'Geese', 'Bison', 'Yaks', 'Narwhals', 'Pelicans', 'Meteors', 'Stags',
    'Salamanders', 'Hedgehogs', 'Mantises', 'Albatrosses', 'Squirrels', 'Walruses', 'Fireflies',
    'Lemurs', 'Ibexes', 'Marmots', 'Cranes', 'Dragonflies', 'Starlings', 'Wombats',
];
const CLUB_WORDS = ['United', 'Athletic', 'Rovers', 'Wanderers', 'Town', 'City', 'Albion', 'Harriers', 'Rangers'];
const PREFIX_WORDS = ['Sporting', 'Athletic'];
const SUFFIX_WORDS = ['FC', 'AFC'];
const SURNAMES = [
    'Ashby', 'Barlow', 'Crane', 'Dalton', 'Ellery', 'Finch', 'Garnett', 'Hale', 'Ingram', 'Jessop',
    'Kerr', 'Lowe', 'Marsh', 'Nash', 'Oakley', 'Pryce', 'Quill', 'Rook', 'Sayer', 'Thorne',
    'Underhill', 'Vance', 'Wilde', 'Yates', 'Okafor', 'Tanaka', 'Silva', 'Novak', 'Haddad',
    'Moreau', 'Kowal', 'Larsen', 'Duarte', 'Ferreira', 'Mensah', 'Petrov', 'Ruiz', 'Sato', 'Varga',
    'Weber', 'Zhou', 'Ibrahim', 'Kaur', 'Nakamura', 'Rossi', 'Santos', 'Lindqvist', 'Brennan',
    'Moyo', 'Castillo', 'Demir', 'Faure', 'Achebe', 'Bergström', 'Costa', 'Delgado', 'Eriksen',
    'Fontaine', 'Gallo', 'Hughes', 'Iwu', 'Jovanovic', 'Kim', 'Lopes', 'Mbeki', 'Nilsen',
];

// The 32 bit number of a seed, FNV-1a over the code units of its text.
export function seedNumber(seed) {
    const text = String(seed).trim();
    let h = 0x811c9dc5;
    for (let i = 0; i < text.length; i++) {
        h ^= text.charCodeAt(i);
        h = Math.imul(h, 0x01000193);
    }
    return h >>> 0;
}

// Mulberry32, a small generator of numbers in [0, 1) from a 32 bit state.
export function mulberry32(a) {
    let state = a >>> 0;
    return () => {
        state = (state + 0x6d2b79f5) >>> 0;
        let t = state;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

// A fresh seed of six digits, for a surprise asked without one.
export function drawSeed() {
    let n;
    const c = globalThis.crypto;
    if (c && typeof c.getRandomValues === 'function') {
        n = c.getRandomValues(new Uint32Array(1))[0];
    } else {
        n = Math.floor(Math.random() * 4294967296);
    }
    return String(100000 + (n % 900000));
}

function linear(v) {
    const c = v / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

// The WCAG relative luminance of an sRGB color.
export function luminance(c) {
    return 0.2126 * linear(c[0]) + 0.7152 * linear(c[1]) + 0.0722 * linear(c[2]);
}

// The WCAG contrast ratio of two sRGB colors, from 1 to 21.
export function contrastRatio(a, b) {
    const la = luminance(a);
    const lb = luminance(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

// The rendered color of the numbers on a kit, as kits.js numberColor draws it.
export function numberRgb(number, kit) {
    return number === 'secondary' ? kit.secondary : NUMBER_RGB[number] || NUMBER_RGB.white;
}

// An sRGB color of whole numbers from a lightness, chroma and hue in degrees, the chroma lowered
// until the color sits inside the gamut.
function lch(L, C, hue) {
    const l = Math.max(2, Math.min(98, L));
    const r = (((hue % 360) + 360) % 360) * Math.PI / 180;
    let c = C;
    for (let k = 0; k < 60 && c >= 1; k++) {
        const lab = [l, c * Math.cos(r), c * Math.sin(r)];
        const rgb = labToRgb(lab).map((v) => Math.round(v));
        if (ciede2000(rgbToLab(rgb), lab) < 2) {
            return rgb;
        }
        c *= 0.9;
    }
    return labToRgb([l, 0, 0]).map((v) => Math.round(v));
}

function shade(rgb, dL) {
    const lab = rgbToLab(rgb);
    const C = Math.hypot(lab[1], lab[2]);
    const hue = Math.atan2(lab[2], lab[1]) * 180 / Math.PI;
    return lch(Math.max(4, Math.min(97, lab[0] + dL)), C, hue);
}

const pick = (rng, list) => list[Math.floor(rng() * list.length)];
const range = (rng, lo, hi) => lo + (hi - lo) * rng();

// A neutral far in lightness from the color, light on dark and dark on light.
function neutralFor(rng, rgb) {
    const L = rgbToLab(rgb)[0];
    if (L < 55) {
        return NEUTRALS[rng() < 0.7 ? 'white' : 'cream'].slice();
    }
    return NEUTRALS[rng() < 0.7 ? 'black' : 'charcoal'].slice();
}

// Neon hues in degrees of CIE LCh with the lightness where sRGB holds their brightest chroma, green,
// pink, hot pink, orange, cyan, lime, aqua, purple and coral.
const NEON = [[135, 85], [330, 60], [356, 57], [47, 62], [196, 88], [114, 92], [168, 88], [318, 52], [19, 60]];

function hueGap(a, b) {
    const d = Math.abs((((a - b) % 360) + 360) % 360);
    return Math.min(d, 360 - d);
}

// A neon color near a hue, its lightness and hue jittered.
function neon(rng, hue) {
    const [h, L] = NEON.reduce((best, n) => (hueGap(n[0], hue) < hueGap(best[0], hue) ? n : best));
    return lch(L + range(rng, -5, 5), 130, h + range(rng, -6, 6));
}

// The outfield kit of a style and scheme, before any check.
function drawKit(rng, look, scheme) {
    const hue = look.id === 'neon' ? pick(rng, NEON)[0] : range(rng, 0, 360);
    const offsets = SCHEMES[scheme].hues;
    const other = hue + pick(rng, offsets);
    let primary;
    let secondary;
    let shorts;
    let socks;
    if (look.id === 'neon') {
        primary = neon(rng, hue);
        secondary = rng() < 0.5 ? NEUTRALS.black.slice() : neon(rng, other);
        shorts = rng() < 0.75 ? NEUTRALS.black.slice() : NEUTRALS.charcoal.slice();
        socks = rng() < 0.6 ? primary.slice() : secondary.slice();
    } else if (look.id === 'minimal') {
        const L = range(rng, 22, 78);
        primary = lch(L, range(rng, 15, 60), hue);
        const trimHue = scheme === 'monochrome' ? hue : other;
        secondary = lch(L + (L < 50 ? 1 : -1) * range(rng, 14, 24), range(rng, 10, 50), trimHue);
        shorts = primary.slice();
        socks = primary.slice();
    } else if (look.id === 'hoops') {
        // Retro, softer chroma and a cream or a muted second color.
        primary = lch(range(rng, 30, 68), range(rng, 25, 55), hue);
        secondary = rng() < 0.45 ? NEUTRALS.cream.slice()
            : lch(range(rng, 25, 80), range(rng, 20, 50), scheme === 'monochrome' ? hue : other);
        shorts = rng() < 0.5 ? NEUTRALS.cream.slice() : shade(primary, -range(rng, 18, 30));
        socks = rng() < 0.5 ? primary.slice() : secondary.slice();
    } else {
        primary = lch(range(rng, 28, 82), range(rng, 35, 95), hue);
        if (scheme === 'monochrome') {
            const L = rgbToLab(primary)[0];
            secondary = lch(L < 55 ? range(rng, L + 35, 96) : range(rng, 8, L - 35), range(rng, 10, 60), hue);
        } else if (rng() < 0.35 && look.id !== 'halves') {
            secondary = neutralFor(rng, primary);
        } else {
            secondary = lch(range(rng, 25, 88), range(rng, 35, 95), other);
        }
        const r = rng();
        if (r < 0.4) {
            shorts = neutralFor(rng, primary);
        } else if (r < 0.7) {
            shorts = secondary.slice();
        } else {
            shorts = shade(primary, rgbToLab(primary)[0] > 50 ? -range(rng, 30, 45) : range(rng, 30, 45));
        }
        const s = rng();
        socks = (s < 0.5 ? primary : s < 0.8 ? secondary : shorts).slice();
    }
    return { pattern: look.pattern, primary, secondary, shorts, socks };
}

// A goalkeeper kit whose shirt keeps the numbers readable.
function drawKeeper(rng, number) {
    const hue = range(rng, 0, 360);
    let L;
    if (number === 'white') {
        L = range(rng, 18, 50);
    } else if (number === 'black') {
        L = range(rng, 62, 92);
    } else {
        L = range(rng, 20, 85);
    }
    const primary = lch(L, range(rng, 35, 100), hue);
    let secondary;
    if (number === 'secondary') {
        secondary = neutralFor(rng, primary);
    } else {
        secondary = shade(primary, L > 50 ? -range(rng, 25, 40) : range(rng, 25, 40));
    }
    const shorts = rng() < 0.5 ? shade(primary, -range(rng, 25, 40)) : (L > 50 ? NEUTRALS.charcoal.slice() : NEUTRALS.black.slice());
    return { primary, secondary, shorts, socks: primary.slice() };
}

const keeperKit = (gk) => ({ pattern: 'plain', ...gk });
const swappedKit = (kit) => ({ ...kit, primary: kit.secondary, secondary: kit.primary, shorts: kit.socks, socks: kit.shorts });

// The problems of the outfield kit alone, an empty list when it passes.
function kitProblems(kit, look) {
    const out = [];
    if (kit.pattern !== 'plain' && deltaE(kit.primary, kit.secondary) < MIN_PATTERN) {
        out.push('pattern too close to the shirt');
    }
    if (look && look.sameShorts) {
        if (kit.shorts.join() !== kit.primary.join()) {
            out.push('shorts differ from the shirt in a style that matches them');
        }
    } else if (deltaE(kit.primary, kit.shorts) < MIN_SHORTS) {
        out.push('shorts too close to the shirt');
    }
    for (const c of COMMON_KITS) {
        if (kitDifference(kit, c.kit) < KIT_CLASH) {
            out.push(`clashes with ${c.name}`);
        }
    }
    return out;
}

// The problems of the goalkeeper kit and the numbers, an empty list when they pass.
function keeperProblems(kit, gk, number) {
    const out = [];
    for (const [label, k] of [['shirt', kit], ['goalkeeper shirt', gk]]) {
        if (contrastRatio(numberRgb(number, k), k.primary) < MIN_NUMBER_CONTRAST) {
            out.push(`numbers unreadable on the ${label}`);
        }
    }
    const keeper = keeperKit(gk);
    if (kitDifference(keeper, kit) < KIT_CLASH || kitDifference(keeper, swappedKit(kit)) < KIT_CLASH) {
        out.push('goalkeeper looks like the outfield kit');
    }
    if (kitDifference(keeper, keeperKit(DEFAULT_GOALKEEPER)) < KIT_CLASH) {
        out.push('goalkeeper looks like the default goalkeeper');
    }
    for (const c of COMMON_KITS) {
        if (kitDifference(keeper, c.kit) < KIT_CLASH) {
            out.push(`goalkeeper clashes with ${c.name}`);
        }
    }
    return out;
}

// Every problem of a generated style, by the rules above, an empty list for a sound team. The
// kit style id tells whether the shorts should match the shirt.
export function styleProblems(style, kitStyle) {
    const look = KIT_STYLES.find((s) => s.id === kitStyle);
    const out = [...kitProblems(style.kit, look), ...keeperProblems(style.kit, style.goalkeeper, style.number)];
    const colors = [
        ...['primary', 'secondary', 'shorts', 'socks'].flatMap((k) => [style.kit[k], style.goalkeeper[k]]),
        ...style.crowd.colors,
    ];
    if (!colors.every((c) => Array.isArray(c) && c.length === 3 && c.every((v) => Number.isInteger(v) && v >= 0 && v <= 255))) {
        out.push('a color is not three whole numbers from 0 to 255');
    }
    return out;
}

// The number colors to try for a kit, the best of white and black first.
function numberChoices(rng, kit) {
    const white = contrastRatio(NUMBER_RGB.white, kit.primary);
    const black = contrastRatio(NUMBER_RGB.black, kit.primary);
    const order = white >= black ? ['white', 'black'] : ['black', 'white'];
    if (kit.pattern === 'plain' && rng() < 0.35) {
        order.unshift('secondary');
    }
    return order.filter((n) => contrastRatio(numberRgb(n, kit), kit.primary) >= MIN_NUMBER_CONTRAST);
}

const clone = (v) => JSON.parse(JSON.stringify(v));

// A safe style for the rare seed that draws nothing that passes, purple and white, purple and
// orange over black shorts for a pattern, plum for Minimal, with a teal goalkeeper.
export function fallbackStyle(look) {
    const purple = [120, 40, 150];
    const plum = [100, 30, 90];
    let kit;
    if (look.sameShorts) {
        kit = { primary: plum, secondary: [246, 246, 244], shorts: plum, socks: plum };
    } else if (look.pattern === 'plain') {
        kit = { primary: purple, secondary: [246, 246, 244], shorts: [246, 246, 244], socks: purple };
    } else {
        kit = { primary: purple, secondary: [240, 150, 30], shorts: [22, 22, 26], socks: purple };
    }
    const goalkeeper = { primary: [0, 128, 128], secondary: [52, 54, 62], shorts: [52, 54, 62], socks: [0, 128, 128] };
    return clone({ kit: { pattern: look.pattern, ...kit }, goalkeeper, number: 'white' });
}

// The colors of a style and scheme that pass every check, drawn from the generator.
function drawStyle(rng, look, scheme) {
    for (let attempt = 0; attempt < 400; attempt++) {
        const kit = drawKit(rng, look, scheme);
        if (kitProblems(kit, look).length) {
            continue;
        }
        for (const number of numberChoices(rng, kit)) {
            for (let k = 0; k < 40; k++) {
                const gk = drawKeeper(rng, number);
                if (!keeperProblems(kit, gk, number).length) {
                    return { kit, goalkeeper: gk, number };
                }
            }
        }
    }
    return fallbackStyle(look);
}

const words = (name) => name.split(/\s+/).filter(Boolean);
const initial = (w) => w[0].toUpperCase();

// A badge of up to three letters, the initials of the name without FC and AFC, or the first
// letters of a single word.
export function badgeFor(name) {
    const parts = words(String(name || '').replace(/[^\p{L}\p{N}\s]/gu, ' ')).filter((w) => !SUFFIX_WORDS.includes(w.toUpperCase()));
    if (!parts.length) {
        return '';
    }
    if (parts.length === 1) {
        return Array.from(parts[0]).slice(0, 3).join('').toUpperCase();
    }
    return parts.slice(0, 3).map(initial).join('');
}

// A club name from the word lists, often alliterating.
function drawName(rng) {
    const alliterate = (first, list) => {
        const same = list.filter((w) => w[0] === first[0]);
        return same.length && rng() < 0.5 ? pick(rng, same) : pick(rng, list);
    };
    const form = rng();
    if (form < 0.3) {
        const adjective = pick(rng, ADJECTIVES);
        return `${adjective} ${alliterate(adjective, CREATURES)}`;
    }
    const place = pick(rng, PLACES);
    if (form < 0.55) {
        return `${place} ${alliterate(place, CREATURES)}`;
    }
    if (form < 0.7) {
        return `${place} ${alliterate(place, CREATURES)} ${pick(rng, SUFFIX_WORDS)}`;
    }
    if (form < 0.9) {
        return `${place} ${pick(rng, CLUB_WORDS)}`;
    }
    return `${pick(rng, PREFIX_WORDS)} ${place}`;
}

// Distinct surnames for a roster, in a shuffled order.
function drawRoster(rng, n) {
    const list = SURNAMES.slice();
    for (let i = list.length - 1; i > 0; i--) {
        const j = Math.floor(rng() * (i + 1));
        [list[i], list[j]] = [list[j], list[i]];
    }
    return list.slice(0, n);
}

// A whole team from a seed and a kit style.
//
// options.seed   Any text or number. Empty or absent draws a fresh seed of six digits, which the
//                result names, so the team can be made again.
// options.style  A kit style id from KIT_STYLES, or any, the default, for one chosen by the seed.
// options.format 5v5 or 11v11, the default, the length of the roster names.
//
// Returns { seed, kitStyle, kitStyleName, scheme, name, badge, style }, where style is a partial
// style that PATCH /api/teams/<id> takes as it is, with the kit, goalkeeper kit, badge, number
// color, fan colors and roster names.
export function surprise(options = {}) {
    const given = options.seed;
    if (given !== undefined && given !== null && !['string', 'number'].includes(typeof given)) {
        throw new Error(`expected the seed as text or a number, found ${Array.isArray(given) ? 'a list' : typeof given === 'object' ? 'an object' : `a ${typeof given}`}`);
    }
    const seed = given === undefined || given === null || String(given).trim() === '' ? drawSeed() : String(given).trim();
    const wanted = options.style === undefined || options.style === null || options.style === '' ? 'any' : String(options.style);
    if (!STYLE_IDS.includes(wanted)) {
        throw new Error(`expected a kit style among ${STYLE_IDS.join(', ')}, found ${wanted}`);
    }
    const format = options.format === undefined ? '11v11' : String(options.format);
    if (!FORMATS[format]) {
        throw new Error(`expected the format 5v5 or 11v11, found ${format}`);
    }
    const rng = mulberry32(seedNumber(seed));
    // The name and roster draw from a generator of their own, so the same seed keeps its name
    // across kit styles. Any picks the style from a third, so a seed with any makes the same team
    // as that seed with the style it picked.
    const naming = mulberry32(seedNumber(`${seed}:name`));
    const look = wanted === 'any' ? pick(mulberry32(seedNumber(`${seed}:style`)), KIT_STYLES)
        : KIT_STYLES.find((s) => s.id === wanted);
    const scheme = pick(rng, look.schemes);
    const colors = drawStyle(rng, look, scheme);
    const name = drawName(naming);
    const badge = badgeFor(name);
    const roster = drawRoster(naming, FORMATS[format]);
    const style = {
        kit: colors.kit,
        goalkeeper: colors.goalkeeper,
        badge,
        number: colors.number,
        crowd: { colors: [colors.kit.primary.slice(), colors.kit.secondary.slice()] },
        players: roster.map((n) => ({ name: n })),
    };
    return {
        seed,
        kitStyle: look.id,
        kitStyleName: look.name,
        scheme: SCHEMES[scheme].name,
        name,
        badge,
        style: clone(style),
    };
}
