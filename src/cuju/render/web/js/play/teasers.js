// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The pictures of the challenge cards on the Play page. Each card shows a still of its challenge,
// and its short teaser video plays while the pointer rests on the card or the keyboard focus is
// inside it, or after a press of its play button. Under reduced motion, from the system or the
// page's own setting, only the play button starts a teaser. One teaser plays at a time, every
// teaser is muted, and a card that loses the pointer and the focus goes back to its still. A
// card without a teaser keeps its still, and a card without either draws a picture of its kind.
// ci/make_challenge_teasers.py makes the files and their manifest.

export const TEASER_FOLDER = 'assets/challenges/';

// Whether a name from the manifest is a plain file of the folder.
function plainName(name, suffix) {
    return typeof name === 'string' && /^[a-z0-9_]+\.[a-z0-9]+$/.test(name) && name.endsWith(suffix);
}

// The teaser and still of each challenge, by identifier, from the manifest's document. Entries
// whose names are not plain files of the folder are left out.
export function teaserFiles(document) {
    const files = {};
    const entries = document && typeof document === 'object' ? document.challenges : null;
    if (!entries || typeof entries !== 'object') {
        return files;
    }
    for (const [id, entry] of Object.entries(entries)) {
        if (!entry || typeof entry !== 'object') {
            continue;
        }
        const teaser = plainName(entry.teaser, '.mp4') ? TEASER_FOLDER + entry.teaser : null;
        const still = plainName(entry.still, '.webp') ? TEASER_FOLDER + entry.still : null;
        if (teaser || still) {
            files[id] = { teaser, still };
        }
    }
    return files;
}

let loaded = null;

// The files of the teasers, read once from the manifest, or none when it cannot be read.
export function loadTeasers(fetcher = globalThis.fetch) {
    if (!loaded) {
        loaded = (async () => {
            try {
                const res = await fetcher(`${TEASER_FOLDER}manifest.json`);
                return res.ok ? teaserFiles(await res.json()) : {};
            } catch {
                return {};
            }
        })();
    }
    return loaded;
}

// What a card shows. picture is still, or drawn when no still is there to show, button whether
// it offers its play button, and playing whether its teaser plays. A card plays for a request of
// its button, or under full motion for the pointer or the focus.
export function teaserView({ still = false, teaser = false, reduced = false, reasons = [] } = {}) {
    const why = new Set(reasons);
    const playing = !!teaser && (why.has('request') || (!reduced && (why.has('hover') || why.has('focus'))));
    return { picture: still ? 'still' : 'drawn', button: !!teaser, playing };
}

// The teasers of a list of cards. A card is an object with an id, whether it has a still and a
// teaser, and show(view), which draws what teaserView returns. The controller keeps the reasons
// each card has to play and lets one card play at a time.
export class TeaserCards {
    constructor({ reduced = () => false } = {}) {
        this.reduced = reduced;
        this.cards = new Map();
        this.current = null;
    }

    add(card) {
        this.cards.set(card.id, { card, reasons: new Set() });
        this.update(card.id);
        return card;
    }

    clear() {
        for (const entry of this.cards.values()) {
            entry.reasons.clear();
            this.draw(entry);
        }
        this.cards.clear();
        this.current = null;
    }

    view(id) {
        const entry = this.cards.get(id);
        return entry ? this.viewOf(entry) : null;
    }

    viewOf(entry) {
        const { card } = entry;
        return teaserView({ still: !!card.still, teaser: !!card.teaser, reduced: this.reduced(), reasons: [...entry.reasons] });
    }

    // The pointer rests on the card, or the focus moves into it.
    enter(id, reason) {
        this.reason(id, reason, true);
    }

    // The pointer or the focus leaves the card. Once neither is left, the card goes back to its
    // still, a request of its button included.
    leave(id, reason) {
        const entry = this.cards.get(id);
        if (!entry) {
            return;
        }
        entry.reasons.delete(reason);
        if (!entry.reasons.has('hover') && !entry.reasons.has('focus')) {
            entry.reasons.delete('request');
        }
        this.update(id);
    }

    // The play button of the card, which starts the teaser or stops it.
    toggle(id) {
        const entry = this.cards.get(id);
        if (!entry) {
            return false;
        }
        if (this.viewOf(entry).playing) {
            entry.reasons.clear();
        } else {
            entry.reasons.add('request');
        }
        this.update(id);
        return this.viewOf(entry).playing;
    }

    // A teaser that fails to load stays off, and its card keeps its still.
    fail(id) {
        const entry = this.cards.get(id);
        if (entry) {
            entry.card.teaser = null;
            entry.reasons.clear();
            this.update(id);
        }
    }

    // The motion setting changed, so every card draws again.
    refresh() {
        for (const id of this.cards.keys()) {
            this.update(id);
        }
    }

    reason(id, reason, on) {
        const entry = this.cards.get(id);
        if (!entry) {
            return;
        }
        if (on) {
            entry.reasons.add(reason);
        } else {
            entry.reasons.delete(reason);
        }
        this.update(id);
    }

    update(id) {
        const entry = this.cards.get(id);
        if (!entry) {
            return;
        }
        if (this.viewOf(entry).playing && this.current !== id) {
            // Another card that plays stops, and forgets why it played.
            const before = this.current && this.cards.get(this.current);
            this.current = id;
            if (before) {
                before.reasons.clear();
                this.draw(before);
            }
        }
        if (!this.viewOf(entry).playing && this.current === id) {
            this.current = null;
        }
        this.draw(entry);
    }

    draw(entry) {
        entry.card.show(this.viewOf(entry));
    }
}
