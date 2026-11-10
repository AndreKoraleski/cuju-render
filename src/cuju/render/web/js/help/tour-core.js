// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The steps of the guided tour and the rules that move through them. Each step names a page, the
// control it points at as a selector, a title and a line of text, and what it needs to show, a
// recording that plays or a team of the registry, which the tour offers to add first. The browser
// keeps the step reached, so a tour left midway resumes there. Nothing here touches the page, so
// the rules hold the same in a test.

export const TOUR_KEY = 'cuju.tour';

export const TOUR_STEPS = [
    {
        id: 'home', page: 'home', target: '#home-btn', title: 'Home',
        text: 'The logo leads Home from every page. Home starts a match, a game, a tournament or a challenge.',
    },
    {
        id: 'palette', page: 'home', target: '#open-palette', title: 'Commands',
        text: 'Ctrl K, or this button, opens the command palette on any page. Type to find a page, a recording, a setting or a camera.',
    },
    {
        id: 'match', page: 'watch', target: '#match-menu-btn', title: 'Watch',
        text: 'The Match menu opens a recording, a live source or one goal of the match that plays.',
        needs: 'recording',
    },
    {
        id: 'timeline', page: 'watch', target: '#timeline', title: 'The timeline',
        text: 'A click or a drag seeks, and the marks are goals. Space plays and pauses, N jumps to the next goal.',
        needs: 'recording',
    },
    {
        id: 'view', page: 'watch', target: '#view-menu-btn', title: 'Cameras and view',
        text: 'The View menu holds the cameras, the time of day, the weather and photo mode. V cycles the cameras.',
        needs: 'recording',
    },
    {
        id: 'play', page: 'play', target: '.play-setup .play-row .btn.primary', title: 'Play',
        text: 'Choose a scenario and a side, then Play. Arrow keys move, D shoots, Esc pauses, and a controller works too.',
    },
    {
        id: 'challenges', page: 'play', target: '.play-setup .challenges', title: 'Challenges',
        text: 'Short drills with bronze, silver and gold targets. A person plays them here, and a team plays them headless.',
    },
    {
        id: 'teams', page: 'teams', target: '#teams-side', title: 'Teams',
        text: 'A team is a Kaggle submission folder with a main.py. Add one here, then choose it to dress its kit, players and sounds.',
        needs: 'team',
    },
    {
        id: 'tournaments', page: 'tournaments', target: '.cup-side-head .btn', title: 'Tournaments',
        text: 'New tournament starts a cup, a league or another format from a preset, for agents and people alike.',
    },
    {
        id: 'settings', page: 'home', target: '#open-settings', title: 'Settings',
        text: 'Settings hold the presets, the sound levels, motion and the theme. Sound starts muted, and M turns it on.',
    },
    {
        id: 'help', page: 'help', target: '#help-learn', title: 'Help',
        text: 'H opens Help on any page. It holds the keys, the hands-on lessons, the samples and the diagnostic report.',
    },
];

// The offer of a step whose need is missing.
export const NEED_OFFERS = {
    recording: { label: 'Open the sample match', text: 'This step shows a recording that plays.' },
    team: { label: 'Add the starter team', text: 'This step shows best with a team of your own.' },
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
    const where = found ? '' : ' This control shows once its page has it.';
    return `Step ${index + 1} of ${count}. ${step.title}. ${step.text}${where}`;
}

// Where the card of a step goes beside its target, below it when there is room, above it when
// not, and at the bottom of the window without a target. Every value is a pixel position of the
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
    return { left, top: Math.round(Math.max(margin, view.height - card.height - margin)), side: 'over' };
}
