// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The presentation each side draws, section Q11 of the contract. A side draws the package of the
// team that plays it, or the package of a registered team the viewer chose, which serves matches
// whose teams are no registered teams, such as the live batches of a training run. The choice
// lives on the server, at /api/presentation/sides, so the page, the command line and an agent's
// requests share it, and the settings panel holds a choice for each side.

import { t } from '../core/i18n.js';
import { h } from '../teams/library.js';
import { teamName } from '../core/names.js';

export const SIDES = ['left', 'right'];

export async function readSides() {
    try {
        const res = await fetch('/api/presentation/sides', { cache: 'no-store' });
        return res.ok ? await res.json() : { left: null, right: null };
    } catch {
        return { left: null, right: null };
    }
}

export async function writeSides(changes) {
    const res = await fetch('/api/presentation/sides', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes),
    });
    if (!res.ok) {
        throw new Error(t('presentation.sides.status', { status: res.status }));
    }
    return res.json();
}

// Two choices in the settings panel, one for each side, among the registered teams.
export class SideChoices {
    constructor(app) {
        this.app = app;
        this.selects = {};
        const panel = document.getElementById('settings');
        if (!panel) {
            return;
        }
        const rows = SIDES.map((side) => {
            const select = h('select', { id: `presentation-${side}`, 'aria-label': t(`presentation.sides.${side}.label`) },
                h('option', { value: '' }, t('presentation.sides.playing')));
            select.addEventListener('change', () => this.choose(side, select.value || null));
            this.selects[side] = select;
            return h('label', {}, t(`presentation.sides.${side}`), select);
        });
        panel.append(...rows);
        this.refresh();
    }

    async refresh() {
        let teams = [];
        try {
            const res = await fetch('/api/teams', { cache: 'no-store' });
            teams = res.ok ? await res.json() : [];
        } catch {
            teams = [];
        }
        const sides = await readSides();
        for (const side of SIDES) {
            const select = this.selects[side];
            for (const team of Array.isArray(teams) ? teams : []) {
                if (team && team.id && team.id !== 'builtin' && ![...select.options].some((o) => o.value === team.id)) {
                    select.append(h('option', { value: team.id }, teamName(team) || team.id));
                }
            }
            select.value = sides[side] || '';
        }
    }

    async choose(side, team) {
        try {
            await writeSides({ [side]: team });
            await this.app.rebuildPlayers();
        } catch (err) {
            if (this.app.hud) {
                this.app.hud.toast(t('presentation.sides.failed', { reason: err.message }), 'info', 4000);
            }
        }
    }
}
