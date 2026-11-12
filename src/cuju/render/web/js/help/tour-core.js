// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The steps of the guided tour and the rules that move through them. Each step names a page, the
// control it points at as a selector, a title and a line of text, and what it needs to show, a
// recording that plays or a team of the registry, which the tour offers to add first, and what
// its Try it button does, with the reason written beside each step. The browser keeps the step
// reached, so a tour left midway resumes there. Nothing here touches the page, so
// the rules hold the same in a test. The title and text of a step are the messages
// tour.step.<id>.title and tour.step.<id>.text.

import { t } from '../core/i18n.js';

export const TOUR_KEY = 'cuju.tour';

export const TOUR_STEPS = [
    {
        // None, the logo leads to Home, the page this step already shows.
        id: 'home', page: 'home', target: '#home-btn', title: t('tour.step.home.title'),
        text: t('tour.step.home.text'), tryIt: null,
    },
    {
        // Open, the button opens the command palette, which takes the focus to its search field.
        id: 'palette', page: 'home', target: '#open-palette', title: t('tour.step.palette.title'),
        text: t('tour.step.palette.text'), tryIt: 'open',
    },
    {
        // Open, the button opens the Match menu, and the focus moves to its first item.
        id: 'match', page: 'watch', target: '#match-menu-btn', title: t('tour.step.match.title'),
        text: t('tour.step.match.text'), tryIt: 'open',
        needs: 'recording',
    },
    {
        // Focus, the timeline is a slider moved by keys, so the focus moves to it and the keys
        // that seek are read out.
        id: 'timeline', page: 'watch', target: '#timeline', title: t('tour.step.timeline.title'),
        text: t('tour.step.timeline.text'), tryIt: 'focus',
        needs: 'recording',
    },
    {
        // Open, the button opens the View menu, and the focus moves to its first item.
        id: 'view', page: 'watch', target: '#view-menu-btn', title: t('tour.step.view.title'),
        text: t('tour.step.view.text'), tryIt: 'open',
        needs: 'recording',
    },
    {
        // None, the Play button starts a match, which leaves the tour behind, and the setup it
        // belongs to already shows on this page.
        id: 'play', page: 'play', target: '.play-setup .play-row .btn.primary', title: t('tour.step.play.title'),
        text: t('tour.step.play.text'), tryIt: null,
    },
    {
        // Open, the Leaderboard button of the first challenge opens its leaderboard on the card,
        // which the same button closes again. Play it yourself and Run a model beside it start
        // matches, so the step points past them.
        id: 'challenges', page: 'challenges', target: '#page-challenges .challenge-item [data-action="board"]',
        title: t('tour.step.challenges.title'), text: t('tour.step.challenges.text'), tryIt: 'open',
    },
    {
        // None, the target is the list of teams, and adding a team uploads a folder.
        id: 'teams', page: 'teams', target: '#teams-side', title: t('tour.step.teams.title'),
        text: t('tour.step.teams.text'), tryIt: null,
        needs: 'team',
    },
    {
        // Open, New tournament opens the wizard beside the list on this page, a draft that
        // nothing saves before its last step and that Cancel puts away.
        id: 'tournaments', page: 'tournaments', target: '.cup-side-head .btn', title: t('tour.step.tournaments.title'),
        text: t('tour.step.tournaments.text'), tryIt: 'open',
    },
    {
        // Open, the button opens the settings panel, and the focus moves to its first field.
        id: 'settings', page: 'home', target: '#open-settings', title: t('tour.step.settings.title'),
        text: t('tour.step.settings.text'), tryIt: 'open',
    },
    {
        // None, the target is the heading of the Learn by doing part, and its lessons start
        // tasks of their own.
        id: 'help', page: 'help', target: '#help-learn-title', title: t('tour.step.help.title'),
        text: t('tour.step.help.text'), tryIt: null,
    },
];

// What Try it does on a step. Open clicks the control as a person would, so whatever it opens
// behaves as usual and keeps the focus where it puts it, and focus moves the focus to a control
// used by keys and says which keys move it, the message tour.try.<id>. A step with neither shows
// no Try it.
export const TRY_KINDS = ['open', 'focus'];

// The offer of a step whose need is missing.
export const NEED_OFFERS = {
    recording: { label: t('tour.need.recording.label'), text: t('tour.need.recording.text') },
    team: { label: t('tour.need.team.label'), text: t('tour.need.team.text') },
};

// The stored state of the tour, the step reached and whether the tour ended, kept in range.
export function tourState(stored, count = TOUR_STEPS.length) {
    const source = stored && typeof stored === 'object' ? stored : {};
    const step = Number.isInteger(source.step) ? Math.max(0, Math.min(count - 1, source.step)) : 0;
    return { step, done: source.done === true, started: source.started === true };
}

// The state after moving by delta steps. Moving past the last step ends the tour, moving before
// the first stays there.
export function moveTour(state, delta, count = TOUR_STEPS.length) {
    const clean = tourState(state, count);
    const next = clean.step + delta;
    if (next >= count) {
        return { step: 0, done: true, started: false };
    }
    return { step: Math.max(0, next), done: false, started: true };
}

// The step where the tour starts, the one reached when a tour was left midway.
export function resumeStep(state, count = TOUR_STEPS.length) {
    const clean = tourState(state, count);
    return clean.started && !clean.done ? clean.step : 0;
}

// Whether a step can show as it stands, given what the page holds.
export function needMet(step, facts) {
    if (!step || !step.needs) {
        return true;
    }
    return !!(facts && facts[step.needs]);
}

// The words a screen reader hears for a step.
export function stepAnnouncement(step, index, count = TOUR_STEPS.length, found = true) {
    return t(found ? 'tour.announce' : 'tour.announce.missing', { index: index + 1, count, title: step.title, text: step.text });
}

// The edges of a box given by its left and top and either its right and bottom or its size.
function edges(box) {
    const right = Number.isFinite(box.right) ? box.right : box.left + (box.width || 0);
    const bottom = Number.isFinite(box.bottom) ? box.bottom : box.top + (box.height || 0);
    return { left: box.left, top: box.top, right, bottom };
}

// Whether two boxes share some area, and boxes that only touch do not.
const overlaps = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

// The distance between two boxes, zero when they overlap or touch.
const apart = (a, b) => Math.hypot(Math.max(0, b.left - a.right, a.left - b.right), Math.max(0, b.top - a.bottom, a.top - b.bottom));

// The smallest the card becomes when it docks in a corner.
const DOCK_WIDTH = 240;
const DOCK_HEIGHT = 120;

// The card docked in the corner of the window farthest from the boxes, at its full size when a
// corner has room for it, else made narrower or shorter until it clears them, or null when no
// corner has room for the smallest card.
function dock(boxes, width, height, view, margin) {
    const minWidth = Math.min(width, DOCK_WIDTH);
    const minHeight = Math.min(height, DOCK_HEIGHT);
    const at = (right, bottom, w, h) => {
        const left = right ? view.width - margin - w : margin;
        const top = bottom ? view.height - margin - h : margin;
        return { left, top, right: left + w, bottom: top + h };
    };
    let best = null;
    for (const [right, bottom] of [[false, false], [true, false], [false, true], [true, true]]) {
        let w = width;
        let h = height;
        let clear = false;
        for (let pass = 0; pass <= boxes.length; pass++) {
            const hit = boxes.find((box) => overlaps(at(right, bottom, w, h), box));
            if (!hit) {
                clear = true;
                break;
            }
            // The card keeps clear of the box by its width or by its height, whichever keeps more
            // of the card.
            const freeWidth = Math.floor(right ? view.width - margin - (hit.right + margin) : hit.left - 2 * margin);
            const freeHeight = Math.floor(bottom ? view.height - margin - (hit.bottom + margin) : hit.top - 2 * margin);
            const byWidth = freeWidth >= minWidth ? Math.min(w, freeWidth) * h : -1;
            const byHeight = freeHeight >= minHeight ? w * Math.min(h, freeHeight) : -1;
            if (byWidth < 0 && byHeight < 0) {
                break;
            }
            if (byWidth >= byHeight) {
                w = Math.min(w, freeWidth);
            } else {
                h = Math.min(h, freeHeight);
            }
        }
        if (!clear) {
            continue;
        }
        const spot = at(right, bottom, w, h);
        const area = w * h;
        const distance = Math.min(...boxes.map((box) => apart(spot, box)));
        if (!best || area > best.area || (area === best.area && distance > best.distance)) {
            best = { spot, w, h, area, distance };
        }
    }
    return best ? {
        left: Math.round(best.spot.left), top: Math.round(best.spot.top), width: best.w, height: best.h, side: 'dock',
    } : null;
}

// Where the card of a step goes beside its target, below it when there is room, above it when
// not, then to its right or left, each only where the card covers neither the target nor any of
// the boxes to avoid, such as a menu or a panel open over the page. When no side is clear the
// card docks in the corner of the window farthest from them, smaller when it must, and when no
// corner is clear either it goes over the target at the bottom of the window. Without a target
// the card goes to the bottom of the window, or docks when a box covers that spot. Every value is
// a pixel position of the window, inside its margins, and a docked card also has its width and
// height.
export function placeCard(target, card, view, avoid = [], margin = 12) {
    const width = Math.min(card.width, view.width - 2 * margin);
    const boxes = [target, ...(avoid || [])].filter(Boolean).map(edges);
    const clear = (left, top) => !boxes.some((box) => overlaps({ left, top, right: left + width, bottom: top + card.height }, box));
    const docked = () => dock(boxes, width, Math.min(card.height, view.height - 2 * margin), view, margin);
    if (!target) {
        const spot = { left: Math.round((view.width - width) / 2), top: Math.round(view.height - card.height - margin), side: 'none' };
        return clear(spot.left, spot.top) ? spot : docked() || spot;
    }
    const box = edges(target);
    const left = Math.round(Math.max(margin, Math.min(view.width - width - margin, box.left + (box.right - box.left) / 2 - width / 2)));
    const sides = [];
    if (box.bottom + margin + card.height <= view.height - margin) {
        sides.push({ left, top: Math.round(box.bottom + margin), side: 'below' });
    }
    if (box.top - margin - card.height >= margin) {
        sides.push({ left, top: Math.round(box.top - margin - card.height), side: 'above' });
    }
    // A tall target leaves room at its side more often than above or below it.
    const top = Math.round(Math.max(margin, Math.min(view.height - card.height - margin, box.top)));
    if (box.right + margin + width <= view.width - margin) {
        sides.push({ left: Math.round(box.right + margin), top, side: 'right' });
    }
    if (box.left - margin - width >= margin) {
        sides.push({ left: Math.round(box.left - margin - width), top, side: 'left' });
    }
    const side = sides.find((spot) => clear(spot.left, spot.top));
    if (side) {
        return side;
    }
    return docked() || { left, top: Math.round(Math.max(margin, view.height - card.height - margin)), side: 'over' };
}
