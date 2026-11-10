// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// How a recording or a live stream ends, and which episode its statistics describe.

import { EPISODE_END, episodeBoundary } from './format.js';

// Whether a header names a full match. A recording from before the timing fields carries no
// `full_match`, and its episode end flag brings End of episode rather than Full time.
export function fullMatch(header) {
    return !!header && header.full_match === true;
}

// The latest boundary between episodes in the frames from first to last, as the index of the
// frame after it, or -1 when none lies there.
function lastBoundary(store, first, last) {
    for (let i = last; i > first; i--) {
        const a = store.get(i - 1);
        const b = store.get(i);
        if (a && b && episodeBoundary(a, b)) {
            return i;
        }
    }
    return -1;
}

// The frames that the statistics of a live source describe, as the first and last index of its
// store. An episode has completed when an end flag closes it or the next episode starts after
// it, and sources with automatic resets mark only that start. The latest completed episode of
// at least two frames is chosen, and the current episode when none has completed.
export function summaryRange(store) {
    let first = store.first;
    let last = store.last;
    const end = store.get(last);
    if (!(end && end.flags & EPISODE_END)) {
        const start = lastBoundary(store, first, last);
        if (start > first + 1) {
            last = start - 1;
        }
    }
    const start = lastBoundary(store, first, last);
    if (start >= 0) {
        first = start;
    }
    return { first, last };
}
