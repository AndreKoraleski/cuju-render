// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The search of a menu by typing, as in the lists of the system. Letters typed within a short
// pause build a word, and the focus goes to the first item from the current one whose label starts
// with it, whatever its case and accents, so typing e finds Équipe and sev finds Several Five. The
// same letter typed again moves on to the next item that starts with it. The module touches no
// page, so the Node tests run it alone.

// The pause in milliseconds after which a typed letter starts a new word.
export const PAUSE = 700;

// Lower case without accents, so a typed word finds a name however it is written.
export function fold(text) {
    return String(text ?? '').normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase();
}

// The index of the item that a typed word reaches among the labels, from the item at `current`,
// or -1 when no label starts with it. A word of one letter, or of one letter typed again and
// again, moves past the current item, and a longer word keeps the current item while it matches.
export function typedMatch(labels, current, typed) {
    const word = fold(typed).trimStart();
    const count = labels.length;
    if (!word || !count) {
        return -1;
    }
    const letters = [...word];
    const repeated = letters.every((letter) => letter === letters[0]);
    const search = repeated ? letters[0] : word;
    const from = repeated ? current + 1 : Math.max(current, 0);
    for (let k = 0; k < count; k++) {
        const i = (((from + k) % count) + count) % count;
        if (fold(labels[i]).trimStart().startsWith(search)) {
            return i;
        }
    }
    return -1;
}
