// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Touch controls. During a game on Play, a touch screen shows an on-screen stick and the buttons
// of GRF's layout, short pass, long pass, high pass, shot, sprint and dribble, each held by a
// finger of its own, so several fingers play at once. They press the same inputs as the keys and
// the buttons of a controller, through a device of their own that drives the person's side as the
// keyboard does. A setting shows them always, never, or once a touch screen is used. On Watch,
// the controls grow to the size of a finger on a touch screen, and a swipe along the timeline
// moves through the match from where it stands, while a tap seeks to the place tapped. The rules
// at the top of the file touch nothing of the page, so they hold the same in a test.

export const TOUCH_KEY = 'cuju.touchControls';
export const TOUCH_CHOICES = [['auto', 'When a touch screen is used'], ['on', 'Always'], ['off', 'Never']];

// The buttons of the pad, each with the inputs it presses, the same as the keys of play send.
// High pass also slides when defending, as GRF reads one input for both.
export const TOUCH_BUTTONS = [
    { id: 'long_pass', label: 'Long pass', short: 'Long', names: ['long_pass'] },
    { id: 'high_pass', label: 'High pass or slide', short: 'High', names: ['high_pass', 'sliding'] },
    { id: 'shot', label: 'Shot', short: 'Shot', names: ['shot'] },
    { id: 'short_pass', label: 'Short pass', short: 'Pass', names: ['short_pass'] },
    { id: 'sprint', label: 'Sprint while held', short: 'Sprint', names: ['sprint'] },
    { id: 'dribble', label: 'Dribble while held', short: 'Dribble', names: ['dribble'] },
];

// The stored choice, auto for anything else.
export function touchChoice(value) {
    return TOUCH_CHOICES.some(([choice]) => choice === value) ? value : 'auto';
}

// Whether the pad shows for a choice, once a touch screen has been seen or not.
export function touchShown(choice, touched) {
    const chosen = touchChoice(choice);
    return chosen === 'on' || (chosen === 'auto' && !!touched);
}

// The directions that a stick pushed by dx and dy from its centre holds, as a controller's stick
// counts them, each axis past the dead zone as a share of the radius. Screen y grows downwards.
export function stickNames(dx, dy, radius, dead = 0.35) {
    const reach = Math.max(1, radius) * dead;
    const names = [];
    if (dx <= -reach) {
        names.push('left');
    } else if (dx >= reach) {
        names.push('right');
    }
    if (dy <= -reach) {
        names.push('up');
    } else if (dy >= reach) {
        names.push('down');
    }
    return names;
}

// The frame that a swipe along the timeline reaches, the width of the timeline being the whole
// match, kept within the frames held.
export function swipeFrame(from, dx, width, first, last) {
    const frame = from + (dx / Math.max(1, width)) * (last - first);
    return Math.max(first, Math.min(last, frame));
}

function h(tag, attributes = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) {
        if (value !== null && value !== undefined && value !== false) {
            node.setAttribute(key, value === true ? '' : value);
        }
    }
    node.append(...children.flat().filter((child) => child !== null && child !== undefined));
    return node;
}

function load() {
    try {
        return touchChoice(JSON.parse(localStorage.getItem(TOUCH_KEY)));
    } catch {
        return 'auto';
    }
}

export class TouchControls {
    constructor(app) {
        this.app = app;
        this.choice = load();
        this.touched = !!(window.matchMedia && window.matchMedia('(pointer: coarse)').matches);
        this.pad = null;
        this.device = null;
        this.stickHeld = [];
        window.addEventListener('pointerdown', (e) => {
            if (e.pointerType === 'touch' && !this.touched) {
                this.touched = true;
                this.update();
            }
        }, true);
        this.bindSetting();
        this.bindTimeline();
        setInterval(() => this.update(), 250);
        this.update();
    }

    bindSetting() {
        const anchor = document.getElementById('pointer-lock')?.closest('label');
        if (!anchor) {
            return;
        }
        this.select = h('select', { id: 'touch-controls', 'aria-label': 'Touch controls on Play' },
            TOUCH_CHOICES.map(([value, label]) => h('option', { value }, label)));
        this.select.value = this.choice;
        this.select.addEventListener('change', () => {
            this.choice = touchChoice(this.select.value);
            try {
                localStorage.setItem(TOUCH_KEY, JSON.stringify(this.choice));
            } catch {
                // Storage can be unavailable, the setting then lasts for this visit only.
            }
            this.update();
        });
        anchor.after(h('label', {}, 'Touch controls on Play', this.select));
        import('../core/menu.js').then((menu) => menu.enhanceSelect(this.select, { className: 'in-panel', align: 'right' }))
            .catch(() => {});
    }

    // The pad of the Play page, built into its stage the first time the stage exists.
    build(play) {
        this.play = play;
        this.device = new play.keyboard.constructor('touch', 'Touch screen');
        play.touch = this.device;
        this.knob = h('div', { class: 'touch-knob' });
        this.stick = h('div', { class: 'touch-stick' }, this.knob);
        this.buttons = TOUCH_BUTTONS.map((button) => {
            const node = h('button', {
                type: 'button', class: `touch-btn touch-${button.id}`, tabindex: '-1',
                'data-action': button.id, title: button.label,
            }, button.short);
            this.hold(node, (down) => this.press(button.names, down));
            return node;
        });
        this.pause = h('button', { type: 'button', class: 'touch-pause', tabindex: '-1', title: 'Pause menu' }, 'Pause');
        this.pause.addEventListener('click', () => {
            if (play.game && !play.game.ended) {
                play.pause(true);
            }
        });
        // Keys and screen readers have the keys of play, so the pad stays out of their way.
        this.pad = h('div', { class: 'touch-pad', 'aria-hidden': 'true', hidden: true },
            this.stick, h('div', { class: 'touch-cluster' }, this.buttons), this.pause);
        this.pad.addEventListener('contextmenu', (e) => e.preventDefault());
        this.bindStick();
        play.stage.append(this.pad);
    }

    // A button held by one finger, pressed until that finger lifts or leaves the screen.
    hold(node, change) {
        let finger = null;
        node.addEventListener('pointerdown', (e) => {
            e.preventDefault();
            if (finger !== null) {
                return;
            }
            finger = e.pointerId;
            node.setPointerCapture?.(e.pointerId);
            node.classList.add('held');
            change(true);
        });
        const up = (e) => {
            if (e.pointerId !== finger) {
                return;
            }
            finger = null;
            node.classList.remove('held');
            change(false);
        };
        node.addEventListener('pointerup', up);
        node.addEventListener('pointercancel', up);
        node.addEventListener('lostpointercapture', up);
    }

    bindStick() {
        let finger = null;
        const move = (e) => {
            const rect = this.stick.getBoundingClientRect();
            const radius = rect.width / 2;
            let dx = e.clientX - (rect.left + radius);
            let dy = e.clientY - (rect.top + radius);
            const length = Math.hypot(dx, dy);
            if (length > radius) {
                dx *= radius / length;
                dy *= radius / length;
            }
            this.knob.style.transform = `translate(${dx}px, ${dy}px)`;
            this.steer(stickNames(dx, dy, radius));
        };
        this.stick.addEventListener('pointerdown', (e) => {
            e.preventDefault();
            if (finger !== null) {
                return;
            }
            finger = e.pointerId;
            this.stick.setPointerCapture?.(e.pointerId);
            this.stick.classList.add('held');
            move(e);
        });
        this.stick.addEventListener('pointermove', (e) => {
            if (e.pointerId === finger) {
                move(e);
            }
        });
        const up = (e) => {
            if (e.pointerId !== finger) {
                return;
            }
            finger = null;
            this.stick.classList.remove('held');
            this.knob.style.transform = '';
            this.steer([]);
        };
        this.stick.addEventListener('pointerup', up);
        this.stick.addEventListener('pointercancel', up);
        this.stick.addEventListener('lostpointercapture', up);
    }

    // Holds the directions of the stick, releasing those it left and pressing those it reached.
    steer(names) {
        const off = this.stickHeld.filter((name) => !names.includes(name));
        const on = names.filter((name) => !this.stickHeld.includes(name));
        this.stickHeld = names;
        if (off.length) {
            this.press(off, false);
        }
        if (on.length) {
            this.press(on, true);
        }
    }

    // Sends inputs as a key of play does, while a game runs and its pause menu is closed.
    press(names, down) {
        const play = this.play;
        const game = play && play.game;
        if (!game || game.ended || !game.started || (down && !play.menu.hidden)) {
            return;
        }
        play.use(this.device);
        this.device.set(names, down);
        play.flush();
    }

    // Lets every finger go, as a key of play does when the window loses focus.
    releaseAll() {
        if (this.device && this.device.held.size) {
            this.device.held.clear();
            this.play.flush();
        }
        this.stickHeld = [];
        for (const node of this.pad ? this.pad.querySelectorAll('.held') : []) {
            node.classList.remove('held');
        }
        if (this.knob) {
            this.knob.style.transform = '';
        }
    }

    update() {
        const app = this.app;
        document.getElementById('app')?.classList.toggle('touch', this.touched);
        const play = app.play;
        if (!this.pad && play && play.stage) {
            this.build(play);
        }
        if (!this.pad) {
            return;
        }
        const game = play.game;
        const show = touchShown(this.choice, this.touched) && app.page === 'play' && !play.stage.hidden
            && !!game && game.started && !game.ended && play.menu.hidden && play.end.hidden;
        if (this.pad.hidden === show) {
            this.pad.hidden = !show;
            if (!show) {
                this.releaseAll();
            }
        }
    }

    // A swipe along the timeline by touch moves through the match from where it stands, and a
    // tap seeks to the place tapped. Mouse and pen keep the timeline's own drag.
    bindTimeline() {
        const track = document.getElementById('timeline');
        const controls = document.getElementById('controls');
        if (!track || !controls) {
            return;
        }
        let swipe = null;
        controls.addEventListener('pointerdown', (e) => {
            const tl = this.app.timeline;
            if (e.pointerType !== 'touch' || !tl || !track.contains(e.target)) {
                return;
            }
            e.stopPropagation();
            e.preventDefault();
            swipe = { id: e.pointerId, x: e.clientX, from: tl.t, moved: false, playing: tl.playing && !tl.following };
            tl.playing = false;
            tl.following = false;
            track.setPointerCapture?.(e.pointerId);
        }, true);
        const seek = (frame) => {
            const tl = this.app.timeline;
            tl.seek(frame);
            this.app.afterSeek();
        };
        controls.addEventListener('pointermove', (e) => {
            const tl = this.app.timeline;
            if (!swipe || e.pointerId !== swipe.id || !tl) {
                return;
            }
            e.stopPropagation();
            const dx = e.clientX - swipe.x;
            swipe.moved ||= Math.abs(dx) > 8;
            if (swipe.moved) {
                seek(swipeFrame(swipe.from, dx, track.getBoundingClientRect().width, tl.first, tl.last));
            }
        }, true);
        const end = (e) => {
            const tl = this.app.timeline;
            if (!swipe || e.pointerId !== swipe.id) {
                return;
            }
            e.stopPropagation();
            const done = swipe;
            swipe = null;
            if (!tl) {
                return;
            }
            if (!done.moved && e.type === 'pointerup') {
                const rect = track.getBoundingClientRect();
                const share = Math.max(0, Math.min(1, (done.x - rect.left) / Math.max(1, rect.width)));
                seek(tl.first + share * (tl.last - tl.first));
            }
            if (done.playing) {
                tl.playing = true;
            }
            this.app.updateHash();
            this.app.updatePlayUi();
        };
        controls.addEventListener('pointerup', end, true);
        controls.addEventListener('pointercancel', end, true);
    }
}
