// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The steps of the guided tour and the rules that move through them. Each step names a page, the
// control it points at as a selector, a title and a line of text, and what it needs to show, a
// recording that plays or a team of the registry, which the tour offers to add first. The browser
// keeps the step reached, so a tour left midway resumes there. Nothing here touches the page, so
// the rules hold the same in a test. The title and text of a step are the messages
// tour.step.<id>.title and tour.step.<id>.text.

import { t } from '../core/i18n.js';

export const TOUR_KEY = 'cuju.tour';

export const TOUR_STEPS = [
    {
        id: 'home', page: 'home', target: '#home-btn', title: t('tour.step.home.title'),
        text: t('tour.step.home.text'),
    },
    {
        id: 'palette', page: 'home', target: '#open-palette', title: t('tour.step.palette.title'),
        text: t('tour.step.palette.text'),
    },
    {
        id: 'match', page: 'watch', target: '#match-menu-btn', title: t('tour.step.match.title'),
        text: t('tour.step.match.text'),
        needs: 'recording',
    },
    {
        id: 'timeline', page: 'watch', target: '#timeline', title: t('tour.step.timeline.title'),
        text: t('tour.step.timeline.text'),
        needs: 'recording',
    },
    {
        id: 'view', page: 'watch', target: '#view-menu-btn', title: t('tour.step.view.title'),
        text: t('tour.step.view.text'),
        needs: 'recording',
    },
    {
        id: 'play', page: 'play', target: '.play-setup .play-row .btn.primary', title: t('tour.step.play.title'),
        text: t('tour.step.play.text'),
    },
    {
        id: 'challenges', page: 'play', target: '.play-setup .challenges h2', title: t('tour.step.challenges.title'),
        text: t('tour.step.challenges.text'),
    },
    {
        id: 'teams', page: 'teams', target: '#teams-side', title: t('tour.step.teams.title'),
        text: t('tour.step.teams.text'),
        needs: 'team',
    },
    {
        id: 'tournaments', page: 'tournaments', target: '.cup-side-head .btn', title: t('tour.step.tournaments.title'),
        text: t('tour.step.tournaments.text'),
    },
    {
        id: 'settings', page: 'home', target: '#open-settings', title: t('tour.step.settings.title'),
        text: t('tour.step.settings.text'),
    },
    {
        id: 'help', page: 'help', target: '#help-learn-title', title: t('tour.step.help.title'),
        text: t('tour.step.help.text'),
    },
];

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

// Where the card of a step goes beside its target, below it when there is room, above it when
// not, then to its right or left, over it as the last resort, and at the bottom of the window
// without a target. Every value is a pixel position of the
// window, inside its margins.
export function placeCard(target, card, view, margin = 12) {
    const width = Math.min(card.width, view.width - 2 * margin);
    if (!target) {
        return { left: Math.round((view.width - width) / 2), top: Math.round(view.height - card.height - margin), side: 'none' };
    }
    const left = Math.round(Math.max(margin, Math.min(view.width - width - margin, target.left + target.width / 2 - width / 2)));
    if (target.bottom + margin + card.height <= view.height - margin) {
        return { left, top: Math.round(target.bottom + margin), side: 'below' };
    }
    if (target.top - margin - card.height >= margin) {
        return { left, top: Math.round(target.top - margin - card.height), side: 'above' };
    }
    // A tall target leaves room at its side more often than above or below it.
    const top = Math.round(Math.max(margin, Math.min(view.height - card.height - margin, target.top)));
    const right = target.left + target.width;
    if (right + margin + width <= view.width - margin) {
        return { left: Math.round(right + margin), top, side: 'right' };
    }
    if (target.left - margin - width >= margin) {
        return { left: Math.round(target.left - margin - width), top, side: 'left' };
    }
    return { left, top: Math.round(Math.max(margin, view.height - card.height - margin)), side: 'over' };
}
