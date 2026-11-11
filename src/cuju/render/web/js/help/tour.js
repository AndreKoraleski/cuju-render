// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The guided tour, a card that walks through the pages and points at the real control of each
// step with a ring around it. The card is a dialog that leaves the page usable, marked with
// aria-modal false, so menu.js leaves the focus and the Tab key free and a person can try each
// control while it shows. Next and Back move through the steps, the arrow keys too while
// the card has the focus, and Esc or Leave the tour closes it, keeping the step for the next start.
// Try it opens what the control of the step opens, by a click as a person would make it, or
// moves the focus to a control used by keys and says its keys. The card keeps clear of its
// target and of every menu, palette, panel or dialog open over the page, and moves as soon as
// one opens or closes. While one of them is open, Esc closes it first and leaves the tour only
// the next time. The focus moves to the title of each step and the text is read out. A step that
// needs a recording or a team offers to add a sample first. Under reduced motion the ring and the
// card move at once. Scripts reach it as window.cuju.tour.

import { NEED_OFFERS, TOUR_KEY, TOUR_STEPS, moveTour, needMet, placeCard, resumeStep, stepAnnouncement, tourState } from './tour-core.js';
import { POINTER_PANELS } from '../core/comfort.js';
import { t, tm, tn } from '../core/i18n.js';
import { icon, reicon, relabel, symbolOnly } from '../core/icons.js';

function h(tag, attributes = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) {
        if (key.startsWith('on') && typeof value === 'function') {
            node.addEventListener(key.slice(2), value);
        } else if (value !== null && value !== undefined && value !== false) {
            node.setAttribute(key, value === true ? '' : value);
        }
    }
    node.append(...children.flat().filter((child) => child !== null && child !== undefined));
    return node;
}

function readState() {
    try {
        return tourState(JSON.parse(localStorage.getItem(TOUR_KEY)));
    } catch {
        return tourState(null);
    }
}

// How long after a step shows its target is scrolled back into view when the page moves it.
const SETTLE_MS = 2000;

// Whether a box lies whole inside the window, or fills it when it is larger.
const inView = (box, view) => (box.top >= 0 || box.height > view.height) && (box.bottom <= view.height || box.height > view.height)
    && (box.left >= 0 || box.width > view.width) && (box.right <= view.width || box.width > view.width);

const shown = (node) => !!node && node.isConnected && node.getClientRects().length > 0 && !node.closest('[hidden]');

// The elements whose opening or closing moves the card, the parts of POINTER_PANELS that float
// over the page and the command palette.
const OVERLAYS = '.dd-panel, #palette, dialog, details, [role="dialog"], [role="alertdialog"], [role="menu"], '
    + '#team-editor, #lineups, .post-card, #victory, #spotlight, [data-prompt]';

export class GuidedTour {
    // helpers holds facts(), what the page holds, and ensure(need), which adds the sample a step
    // needs and resolves once it is there.
    constructor(app, helpers) {
        this.app = app;
        this.helpers = helpers;
        this.steps = TOUR_STEPS;
        this.state = readState();
        this.index = -1;
        this.target = null;
        this.token = 0;
        this.title = h('h2', { id: 'tour-title', tabindex: '-1' });
        this.count = h('p', { class: 'tour-count', id: 'tour-count' });
        this.text = h('p', { id: 'tour-text', class: 'tour-text' });
        this.live = h('p', { class: 'sr-only', 'aria-live': 'polite', id: 'tour-live' });
        this.offerText = h('span', {});
        this.offerButton = h('button', { type: 'button', class: 'btn small', onclick: () => this.fillNeed() });
        this.offer = h('div', { class: 'tour-offer', hidden: true }, this.offerText, this.offerButton);
        this.backButton = h('button', { type: 'button', class: 'btn', ...symbolOnly(t('tour.back')), onclick: () => this.back() }, icon('back'));
        this.nextButton = h('button', { type: 'button', class: 'btn primary', ...symbolOnly(t('tour.next')), onclick: () => this.next() }, icon('next'));
        this.tryButton = h('button', { type: 'button', class: 'btn', ...symbolOnly(t('tour.try')), onclick: () => this.tryIt() }, icon('cursor'));
        // The focus on the title reads the title, and the live region reads the count and the
        // text once, so the card names no description that a screen reader would read again.
        this.card = h('div', {
            id: 'tour', class: 'tour', role: 'dialog', 'aria-modal': 'false', 'aria-labelledby': 'tour-title', hidden: true,
        },
        this.count, this.title, this.text, this.offer,
        h('div', { class: 'tour-actions' }, this.backButton, this.nextButton, this.tryButton,
            h('button', { type: 'button', class: 'link small', ...symbolOnly(t('tour.leave')), onclick: () => this.leave() }, icon('close'))),
        h('p', { class: 'muted small tour-keys' }, ...tn('tour.keys')),
        this.live);
        this.ring = h('div', { id: 'tour-ring', class: 'tour-ring', 'aria-hidden': 'true', hidden: true });
        (document.getElementById('app') || document.body).append(this.ring, this.card);
        this.card.addEventListener('keydown', (e) => {
            if (e.target.closest('input, select, textarea')) {
                return;
            }
            if (e.key === 'ArrowRight' && !e.altKey && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                this.next();
            } else if (e.key === 'ArrowLeft' && !e.altKey && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                this.back();
            }
        });
        // Esc leaves the tour from the card, or from the page when nothing else is open over it,
        // before the keys of the page see it. A menu, the palette or a panel open over the page
        // keeps its Esc, which closes it, so the next Esc leaves the tour.
        window.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape' || !this.isOpen || e.defaultPrevented) {
                return;
            }
            if (this.card.contains(document.activeElement) || !this.otherOpen()) {
                e.preventDefault();
                e.stopImmediatePropagation();
                this.leave();
            }
        }, true);
        this.place = () => this.position();
        window.addEventListener('resize', this.place);
        window.addEventListener('scroll', this.place, true);
        // A menu, the palette or a panel that opens or closes moves the card at once, in the
        // next frame, rather than at the next beat of the timer.
        this.observer = new MutationObserver((records) => {
            if (this.isOpen && !this.frame && records.some((record) => this.overlayChanged(record.target))) {
                this.frame = requestAnimationFrame(() => {
                    this.frame = 0;
                    this.position();
                });
            }
        });
    }

    // Whether a change of an element may open or close something over the page.
    overlayChanged(node) {
        return node instanceof Element && node !== this.ring && !this.card.contains(node) && node.matches(OVERLAYS);
    }

    // The elements open over the page that show, other than the card, as POINTER_PANELS names
    // them, and the command palette.
    openOver() {
        const nodes = [...document.querySelectorAll(POINTER_PANELS), ...document.querySelectorAll('#palette:not([hidden])')];
        return nodes.filter((node) => node !== this.card && !this.card.contains(node) && shown(node));
    }

    // Whether anything other than the card is open over the page.
    otherOpen() {
        return this.openOver().length > 0;
    }

    // The boxes of the menus, popovers, panels, dialogs and the palette open over the page, which
    // the card keeps clear of. A button that shows as expanded is left to its panel, the palette
    // counts by its box rather than its scrim, and a layer that covers the whole window counts
    // not at all, since no place of the card could clear it.
    openBoxes(view) {
        const boxes = [];
        for (const found of this.openOver()) {
            const node = found.id === 'palette' ? found.querySelector('.palette-box') : found;
            if (!node || node.matches('button') || node.contains(this.card)) {
                continue;
            }
            const style = getComputedStyle(node);
            if (style.position !== 'fixed' && style.position !== 'absolute' && !node.matches('dialog[open]')) {
                continue;
            }
            const box = node.getBoundingClientRect();
            if (box.width < 1 || box.height < 1 || (box.width >= 0.9 * view.width && box.height >= 0.9 * view.height)) {
                continue;
            }
            boxes.push({ left: box.left, top: box.top, right: box.right, bottom: box.bottom });
        }
        return boxes;
    }

    get isOpen() {
        return !this.card.hidden;
    }

    save() {
        try {
            localStorage.setItem(TOUR_KEY, JSON.stringify(this.state));
        } catch {
            // Storage can be unavailable, the tour then resumes within this visit only.
        }
    }

    // The step a start resumes at, or 0.
    get resumeAt() {
        return resumeStep(this.state, this.steps.length);
    }

    // Opens the tour at a step, by default where it stopped.
    start(index = this.resumeAt) {
        if (document.pointerLockElement) {
            document.exitPointerLock();
        }
        if (this.app.palette && this.app.palette.isOpen) {
            this.app.palette.close(false);
        }
        this.returnTo = this.returnTo || (document.activeElement !== document.body ? document.activeElement : null);
        return this.show(Math.max(0, Math.min(this.steps.length - 1, Number(index) || 0)));
    }

    async show(index) {
        const token = ++this.token;
        const step = this.steps[index];
        this.closeTried();
        this.index = index;
        this.state = { step: index, done: false, started: true };
        this.save();
        if (this.app.page !== step.page) {
            this.app.showPage(step.page);
        }
        this.card.hidden = false;
        this.observer.observe(document.getElementById('app') || document.body, {
            subtree: true, attributes: true, attributeFilter: ['class', 'hidden', 'open'],
        });
        this.tryButton.hidden = true;
        this.card.classList.toggle('still', !!this.app.reducedMotion);
        this.ring.classList.toggle('still', !!this.app.reducedMotion);
        this.count.textContent = t('tour.count', { index: index + 1, count: this.steps.length });
        this.title.textContent = step.title;
        // The text shows with its marks, the message tour.step.<id>.text.
        this.text.replaceChildren(tm(`tour.step.${step.id}.text`));
        this.backButton.disabled = index === 0;
        relabel(this.nextButton, index === this.steps.length - 1 ? t('tour.finish') : t('tour.next'));
        reicon(this.nextButton, index === this.steps.length - 1 ? 'check' : 'next');
        this.updateOffer(step);
        this.target = null;
        this.settleUntil = 0;
        this.ring.hidden = true;
        this.position();
        this.title.focus({ preventScroll: true });
        // A page builds its controls after it shows, some only once the server answers, so the
        // target is looked for up to five seconds.
        let found = null;
        for (let i = 0; i < 100 && token === this.token; i++) {
            found = [...document.querySelectorAll(step.target)].find(shown) || null;
            if (found) {
                break;
            }
            await new Promise((resolve) => setTimeout(resolve, 50));
        }
        if (token !== this.token) {
            return this.scriptState();
        }
        this.target = found;
        if (found) {
            found.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'auto' });
            // A page that is still laying out can push the target down after this scroll, so
            // position scrolls it back into view for a moment.
            this.settleUntil = performance.now() + SETTLE_MS;
        }
        this.tryButton.hidden = !found || !step.tryIt;
        this.live.textContent = stepAnnouncement(step, index, this.steps.length, !!found);
        this.position();
        clearInterval(this.timer);
        this.timer = setInterval(() => this.position(), 250);
        return this.scriptState();
    }

    updateOffer(step) {
        const facts = this.helpers.facts();
        const missing = !needMet(step, facts);
        this.offer.hidden = !missing;
        if (missing) {
            const offer = NEED_OFFERS[step.needs];
            this.offerText.replaceChildren(tm(`tour.need.${step.needs}.text`), ' ');
            this.offerButton.textContent = offer.label;
            this.offerButton.disabled = false;
        }
    }

    async fillNeed() {
        const step = this.steps[this.index];
        if (!step || !step.needs) {
            return;
        }
        this.offerButton.disabled = true;
        this.live.textContent = t('tour.adding');
        try {
            await this.helpers.ensure(step.needs);
        } catch (err) {
            this.offerButton.disabled = false;
            this.live.textContent = t('tour.addFailed', { error: err.message });
            return;
        }
        if (this.isOpen && this.steps[this.index] === step) {
            await this.show(this.index);
        }
    }

    position() {
        if (!this.isOpen) {
            return;
        }
        const view = { width: window.innerWidth, height: window.innerHeight };
        let whole = shown(this.target) ? this.target.getBoundingClientRect() : null;
        if (whole && performance.now() < (this.settleUntil || 0) && !inView(whole, view)) {
            this.target.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'auto' });
            whole = this.target.getBoundingClientRect();
        }
        // A region taller or wider than the window is ringed where it shows.
        const target = whole && whole.width > 0 ? (() => {
            const left = Math.max(whole.left, 4);
            const top = Math.max(whole.top, 4);
            const right = Math.min(whole.right, view.width - 4);
            const bottom = Math.min(whole.bottom, view.height - 4);
            return right > left && bottom > top
                ? { left, top, right, bottom, width: right - left, height: bottom - top } : null;
        })() : null;
        if (target && target.width > 0) {
            const pad = 4;
            Object.assign(this.ring.style, {
                left: `${Math.round(target.left - pad)}px`, top: `${Math.round(target.top - pad)}px`,
                width: `${Math.round(target.width + 2 * pad)}px`, height: `${Math.round(target.height + 2 * pad)}px`,
            });
            this.ring.hidden = false;
        } else {
            this.ring.hidden = true;
        }
        // The card is measured at its own size, and a docked card is made smaller after.
        this.card.style.maxWidth = '';
        this.card.style.maxHeight = '';
        this.card.style.overflowY = '';
        const box = this.card.getBoundingClientRect();
        const card = { width: box.width || 360, height: box.height || 200 };
        const spot = placeCard(target && target.width > 0 ? {
            left: target.left - 4, top: target.top - 4, right: target.right + 4, bottom: target.bottom + 4,
        } : null, card, view, this.openBoxes(view));
        this.card.style.left = `${spot.left}px`;
        this.card.style.top = `${spot.top}px`;
        if (spot.width < card.width) {
            this.card.style.maxWidth = `${spot.width}px`;
        }
        if (spot.height < card.height) {
            this.card.style.maxHeight = `${spot.height}px`;
            this.card.style.overflowY = 'auto';
        }
        this.card.dataset.side = spot.side;
    }

    // Try it, as the step names it. Open clicks the control as a person would, so menu.js, the
    // palette and the page open what they open as usual and put the focus where they put it, and
    // leaves an open control open. Focus moves the focus to the control and says its keys.
    tryIt() {
        const step = this.steps[this.index];
        const target = this.target;
        if (!step || !step.tryIt || !shown(target)) {
            return;
        }
        if (step.tryIt === 'open') {
            const open = target.getAttribute('aria-expanded') === 'true'
                || (target.id === 'open-palette' && this.app.palette && this.app.palette.isOpen);
            if (!open) {
                target.focus({ preventScroll: true });
                this.tried = target;
                target.click();
            }
        } else if (step.tryIt === 'focus') {
            target.focus({ preventScroll: true });
            this.live.textContent = t(`tour.try.${step.id}`);
        }
        this.position();
    }

    // Closes the menu or the palette that Try it opened, when it is still open as the step changes
    // or the tour closes.
    closeTried() {
        const tried = this.tried;
        this.tried = null;
        if (!tried) {
            return;
        }
        if (tried.id === 'open-palette' && this.app.palette && this.app.palette.isOpen) {
            this.app.palette.close(false);
            return;
        }
        for (const menu of Object.values(this.app.menus || {})) {
            if (menu && menu.button === tried && menu.isOpen) {
                menu.close(false);
            }
        }
    }

    next() {
        if (!this.isOpen) {
            return this.scriptState();
        }
        const moved = moveTour(this.state, 1, this.steps.length);
        if (moved.done) {
            return this.finish();
        }
        return this.show(moved.step);
    }

    back() {
        if (!this.isOpen || this.index <= 0) {
            return this.scriptState();
        }
        return this.show(this.index - 1);
    }

    close() {
        this.token++;
        this.settleUntil = 0;
        clearInterval(this.timer);
        this.observer.disconnect();
        cancelAnimationFrame(this.frame);
        this.frame = 0;
        this.closeTried();
        this.card.hidden = true;
        this.ring.hidden = true;
        this.target = null;
        const back = this.returnTo;
        this.returnTo = null;
        if (back && shown(back)) {
            back.focus({ preventScroll: true });
        } else {
            document.getElementById('pages')?.focus({ preventScroll: true });
        }
    }

    // Leaves the tour midway, which resumes at this step.
    leave() {
        if (!this.isOpen) {
            return this.scriptState();
        }
        this.close();
        this.app.hud?.toast(t('tour.stopped', { index: this.index + 1 }), 'info', 3500);
        return this.scriptState();
    }

    finish() {
        this.state = { step: 0, done: true, started: false };
        this.save();
        this.close();
        this.app.hud?.toast(t('tour.done'), 'info', 4500);
        return this.scriptState();
    }

    scriptState() {
        return {
            open: this.isOpen,
            step: this.isOpen ? this.index : null,
            id: this.isOpen ? this.steps[this.index].id : null,
            resumeAt: this.resumeAt,
            done: this.state.done,
            target: this.isOpen ? !!this.target : null,
            steps: this.steps.length,
        };
    }

    // The functions of window.cuju.tour.
    script() {
        return {
            start: (index) => this.start(index === undefined ? this.resumeAt : index),
            next: () => this.next(),
            back: () => this.back(),
            leave: () => this.leave(),
            state: () => this.scriptState(),
            steps: () => this.steps.map((step) => ({ id: step.id, page: step.page, title: step.title, text: step.text, needs: step.needs || null })),
        };
    }
}
