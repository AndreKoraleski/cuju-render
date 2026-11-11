// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Challenges on the Play page, short drills with bronze, silver and gold targets that people play
// in a game and registered teams play headless on the server. Every attempt plays a fixed seed, so
// people and agents face the same episodes, and the server scores each attempt from its recording
// and keeps one leaderboard per challenge. Achievements, which the server finds in the frames by
// the same rules for people and teams, show on the end cards and in a list of their own, kept on
// disk for teams and in the browser for the person. Scripts reach it all through
// window.cuju.challenges.

import { formatDateTime, formatNumber, serverText, t, tn, tOr } from '../core/i18n.js';
import { el as h } from '../core/menu.js';
import { icon, symbolOnly } from '../core/icons.js';
import { teamName } from '../core/names.js';
import { scenarioName } from '../core/scenarios.js';

const NAME_KEY = 'cuju.challengeName';
// Whether the attempts of a run stay as recordings, which the browser keeps, true by default.
const KEEP_KEY = 'cuju.challengeRecordings';
const EARNED_KEY = 'cuju.achievements';
// The achievements of a challenge's medals, which a run adds to those of its attempts' games.
const CHALLENGE_AWARDS = new Set(['podium', 'gold_standard', 'academy_graduate']);
const MEDAL_NAMES = { bronze: t('challenges.medal.bronze'), silver: t('challenges.medal.silver'), gold: t('challenges.medal.gold') };
const MEDALS = ['bronze', 'silver', 'gold'];
// Dates of the leaderboards and achievements, a calendar day in the numbers of the language.
const DAY = { year: 'numeric', month: 'numeric', day: 'numeric' };
// A headless run is followed this often while it waits or plays.
const POLL_MS = 1000;

function injectChallengeStyle() {
    if (document.getElementById('cuju-challenges-style')) {
        return;
    }
    const style = document.createElement('style');
    style.id = 'cuju-challenges-style';
    style.textContent = `
.challenges { margin-top: 24px; display: flex; flex-direction: column; gap: 10px; }
.challenges h2 { margin: 0; }
.challenges .setup-row { display: flex; flex-wrap: wrap; gap: 10px 14px; }
.challenge-banner, .challenge-job { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 0; }
.challenge-banner[hidden], .challenge-job[hidden] { display: none; }
.challenge-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 1fr)); }
.challenge-item { border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; display: flex;
    flex-direction: column; gap: 4px; }
.challenge-item h3 { margin: 0; font-size: 16px; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
.challenge-item p { margin: 0; }
.challenge-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
.challenge-medal { font-size: 12px; padding: 1px 6px; border-radius: 9px; border: 1px solid var(--border); }
.challenge-medal.gold { background: #d4a017; color: #1b1300; border-color: #d4a017; }
.challenge-medal.silver { background: #b8bec6; color: #15181c; border-color: #b8bec6; }
.challenge-medal.bronze { background: #b0703c; color: #fff; border-color: #b0703c; }
.challenge-item:has(.challenge-board:not([hidden])) { grid-column: 1 / -1; }
.challenge-board { overflow-x: auto; }
.challenge-board table { width: 100%; border-collapse: collapse; font-size: 13px; }
.challenge-board th, .challenge-board td { text-align: left; padding: 2px 6px; border-bottom: 1px solid var(--border); }
.challenge-board td.num, .challenge-board th.num { text-align: right; }
.challenge-kind { font-size: 11px; padding: 0 5px; border-radius: 8px; border: 1px solid var(--border); }
.challenge-kind.agent { border-style: dashed; }
.challenge-result { display: flex; flex-direction: column; gap: 4px; }
.achievement-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 240px), 1fr)); }
.achievement-list li { display: flex; gap: 8px; align-items: flex-start; padding: 6px 8px;
    border: 1px solid var(--border); border-radius: 6px; }
.achievement-list li.missing { opacity: 0.6; border-style: dashed; }
.achievement-glyph { flex: none; width: 2.4em; text-align: center; font-weight: 700; font-size: 12px;
    padding: 2px 0; border-radius: 4px; border: 1px solid var(--border); }
.achievement-list p { margin: 0; }
.achievement-new { display: flex; flex-direction: column; gap: 2px; }
`;
    document.head.appendChild(style);
}

async function call(method, path, json) {
    const init = { method, cache: 'no-store', headers: {} };
    if (json !== undefined) {
        init.body = JSON.stringify(json);
        init.headers['Content-Type'] = 'application/json';
    }
    let res;
    try {
        res = await fetch(path, init);
    } catch {
        throw new Error(t('api.unreachable', { origin: location.origin }));
    }
    const text = await res.text();
    let data = null;
    try {
        data = text ? JSON.parse(text) : null;
    } catch {
        data = null;
    }
    if (!res.ok) {
        const error = new Error((data && data.error && serverText(data, 'error')) || t('challenges.api.status', { status: res.status }));
        error.status = res.status;
        throw error;
    }
    return data;
}

const enc = encodeURIComponent;

// The client of the server's challenge routes.
export const challengeApi = {
    list: (person) => call('GET', `/api/challenges${person ? `?person=${enc(person)}` : ''}`),
    board: (id) => call('GET', `/api/challenges/${enc(id)}`),
    score: (id, match, attempt) => call('GET', `/api/challenges/${enc(id)}/score?match=${enc(match)}&attempt=${attempt}`),
    submit: (id, person, matches, keep = true) => call('POST', `/api/challenges/${enc(id)}/runs`,
        { person, matches, keep_recordings: keep }),
    leaveRun: (id, person, matches, keep = true) => call('POST', `/api/challenges/${enc(id)}/leave`,
        { person, matches, keep_recordings: keep }),
    runTeam: (id, team, attempts = null, keep = true) => call('POST', `/api/challenges/${enc(id)}/runs`,
        { team, ...(attempts == null ? {} : { attempts }), ...(keep ? {} : { keep_recordings: false }) }),
    jobs: () => call('GET', '/api/challenges/jobs'),
    cancel: (job) => call('DELETE', `/api/challenges/jobs/${enc(job)}`),
    achievements: () => call('GET', '/api/achievements'),
};

// The person's achievements, kept in the browser by identifier, each with its first time and
// count.
export function readEarned() {
    try {
        const value = JSON.parse(localStorage.getItem(EARNED_KEY) || '{}');
        return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    } catch {
        return {};
    }
}

// Adds achievements to the person's, and returns those earned for the first time.
export function addEarned(ids) {
    const earned = readEarned();
    const fresh = [];
    for (const id of ids) {
        const entry = earned[id];
        if (entry && typeof entry === 'object') {
            entry.count = (Number(entry.count) || 0) + 1;
        } else {
            earned[id] = { first: Date.now(), count: 1 };
            fresh.push(id);
        }
    }
    try {
        localStorage.setItem(EARNED_KEY, JSON.stringify(earned));
    } catch {
        // A browser that keeps no site data shows the achievements of this visit alone.
    }
    return fresh;
}

function readName() {
    try {
        return localStorage.getItem(NAME_KEY) || '';
    } catch {
        return '';
    }
}

function writeName(name) {
    try {
        localStorage.setItem(NAME_KEY, name);
    } catch {
        // A browser that keeps no site data asks for the name on every visit.
    }
}

function readKeep() {
    try {
        return localStorage.getItem(KEEP_KEY) !== 'false';
    } catch {
        return true;
    }
}

function writeKeep(keep) {
    try {
        localStorage.setItem(KEEP_KEY, keep ? 'true' : 'false');
    } catch {
        // A browser that keeps no site data keeps the recordings on every visit.
    }
}

// A number of the server in the numbers of the language, such as seconds with a decimal.
function num(value) {
    return typeof value === 'number' && Number.isFinite(value) ? formatNumber(value, { useGrouping: false, maximumFractionDigits: 10 }) : String(value);
}

// The title and goal of a challenge, and the name and description of an achievement, in the
// language of the page, else the server's English.
export function challengeTitle(challenge) {
    return tOr(`challenge.${challenge.id}.title`, challenge.title);
}

export function challengeGoal(challenge) {
    return tOr(`challenge.${challenge.id}.goal`, challenge.goal);
}

// The value of a run in words, by the measure of its challenge.
export function valueText(challenge, value) {
    if (challenge.measure === 'margin') {
        return t('challenges.value.margin', { count: Math.abs(value), value: `${value > 0 ? '+' : ''}${num(value)}` });
    }
    return t('challenges.value.attempts', { value: num(value), attempts: num(challenge.attempts) });
}

export function targetsText(challenge) {
    const [bronze, silver, gold] = MEDALS.map((m, i) => valueText(challenge, challenge.targets[i]));
    return t('challenges.targets', { bronze, silver, gold });
}

function medalBadge(medal, text = null) {
    return medal ? h('span', { class: `challenge-medal ${medal}` }, text || MEDAL_NAMES[medal]) : null;
}

// The words of a run's value with the seconds its counting attempts took to score in all, or the
// value alone for a run in which no attempt counted, whose seconds are none. `id` names the
// message with the seconds, and the same id with `.none` the one without.
export function runText(challenge, run, id, values = {}) {
    const value = valueText(challenge, run.value);
    if (!(Number(run.seconds) > 0)) {
        return t(`${id}.none`, { ...values, value });
    }
    return t(id, { ...values, value, count: run.seconds, seconds: num(run.seconds) });
}

// One attempt's result in words.
export function attemptText(challenge, result) {
    const values = { for: num(result.goals[0]), against: num(result.goals[1]), count: result.seconds, seconds: num(result.seconds), limit: num(challenge.limit) };
    if (!result.match && !result.finished) {
        return t('challenges.attempt.missed');
    }
    if (!result.finished) {
        return t('challenges.attempt.left', values);
    }
    if (!result.scored) {
        return t('challenges.attempt.noGoal', values);
    }
    if (challenge.measure === 'within') {
        return t(result.counts ? 'challenges.attempt.within' : 'challenges.attempt.late', values);
    }
    return t(challenge.measure === 'margin' ? 'challenges.attempt.scoredGoals' : 'challenges.attempt.scored', values);
}

function abilityText(challenge) {
    const [left, right] = challenge.played_ability || [null, null];
    const two = { minimumFractionDigits: 2, maximumFractionDigits: 2 };
    return t('challenges.ability', { left: formatNumber(Number(left), two), right: formatNumber(Number(right), two) });
}

// A person, a team of the registry, or a Python policy, which a board ranks by its name alone, so a
// policy that shares a team's name stays apart from the team.
function competitorKind(entry) {
    if (entry.kind === 'person') {
        return t('challenges.board.person');
    }
    return entry.team ? t('challenges.board.team') : t('challenges.board.policy');
}

export class ChallengesPanel {
    constructor(play) {
        this.play = play;
        this.app = play.app;
        this.catalog = [];
        this.teams = [];
        this.run = null;
        this.jobs = [];
        this.polling = false;
        this.root = null;
        this.boards = new Map();
        // Scripts and agents reach the challenges through the page object.
        this.app.challenges = this.script();
    }

    // The section, built once for the setup view of Play.
    element() {
        injectChallengeStyle();
        this.nameField = h('input', { type: 'text', maxlength: '40', value: readName() || t('challenges.name.default'), 'aria-label': t('challenges.name.label'), class: 'challenge-name' });
        this.nameField.addEventListener('change', () => writeName(this.personName()));
        this.keepBox = h('input', { type: 'checkbox', checked: readKeep(), class: 'challenge-keep', 'aria-describedby': 'challenge-keep-hint' });
        this.keepBox.addEventListener('change', () => writeKeep(this.keepBox.checked));
        this.teamSelect = h('select', { 'aria-label': t('challenges.team'), class: 'challenge-team' });
        this.attemptSelect = h('select', { 'aria-label': t('challenges.attempts.label'), class: 'challenge-attempts' },
            h('option', { value: 'full' }, t('challenges.attempts.full')), h('option', { value: '1' }, t('challenges.attempts.practice')));
        this.banner = h('div', { class: 'challenge-banner', role: 'status', hidden: true });
        this.jobLine = h('div', { class: 'challenge-job', role: 'status', 'aria-live': 'polite', hidden: true });
        this.list = h('ul', { class: 'challenge-list', 'aria-label': t('challenges.title') });
        this.note = h('p', { class: 'muted small', role: 'status' });
        this.root = h('section', { class: 'challenges', 'aria-labelledby': 'challenges-title' },
            h('h2', { id: 'challenges-title' }, t('challenges.title')),
            h('p', { class: 'muted' }, t('challenges.text')),
            h('div', { class: 'setup-row' },
                h('label', { class: 'field' }, t('challenges.name'), this.nameField),
                h('label', { class: 'field' }, t('challenges.team'), this.teamSelect),
                h('label', { class: 'field' }, t('challenges.attempts'), this.attemptSelect)),
            h('label', { class: 'check' }, this.keepBox, t('challenges.keep')),
            h('p', { class: 'muted small', id: 'challenge-keep-hint' }, t('challenges.keep.hint')),
            this.banner, this.jobLine, this.note, this.list, this.achievementsPart());
        return this.root;
    }

    achievementsPart() {
        this.whoseSelect = h('select', { 'aria-label': t('challenges.achievements.whose'), class: 'achievement-whose' });
        this.whoseSelect.addEventListener('change', () => this.renderAchievements());
        this.achievementList = h('ul', { class: 'achievement-list', 'aria-label': t('challenges.achievements.title') });
        this.achievementNote = h('p', { class: 'muted small', role: 'status' });
        return h('section', { class: 'achievements', 'aria-labelledby': 'achievements-title' },
            h('h3', { id: 'achievements-title' }, t('challenges.achievements.title')),
            h('p', { class: 'muted' }, t('challenges.achievements.text')),
            h('label', { class: 'field' }, t('challenges.achievements.whose'), this.whoseSelect),
            this.achievementNote, this.achievementList);
    }

    // The catalog and the teams' achievements from the server, and the person's from the browser.
    async loadAchievements() {
        try {
            this.achievements = await challengeApi.achievements();
        } catch (err) {
            this.achievements = this.achievements || { catalog: [], teams: {} };
            if (this.achievementNote) {
                this.achievementNote.textContent = t('challenges.achievements.unavailable', { reason: err.message });
            }
        }
        return this.achievements;
    }

    nameOf(id) {
        const entry = this.achievements && this.achievements.catalog.find((a) => a.id === id);
        return entry ? tOr(`achievement.${id}.name`, entry.name) : id;
    }

    renderAchievements() {
        if (!this.achievementList || !this.achievements) {
            return;
        }
        const before = this.whoseSelect.value || 'you';
        const teams = this.teams.filter((team) => team.kind !== 'builtin');
        this.whoseSelect.replaceChildren(h('option', { value: 'you' }, t('challenges.achievements.you')),
            ...teams.map((team) => h('option', { value: team.id }, teamName(team))));
        this.whoseSelect.value = before === 'you' || teams.some((team) => team.id === before) ? before : 'you';
        const whose = this.whoseSelect.value;
        const earned = whose === 'you' ? readEarned() : (this.achievements.teams[whose] || {});
        const count = this.achievements.catalog.filter((a) => earned[a.id]).length;
        this.achievementNote.textContent = t('challenges.achievements.count', { earned: count, count: this.achievements.catalog.length });
        this.achievementList.replaceChildren(...this.achievements.catalog.map((a) => {
            const got = earned[a.id];
            const first = got ? formatDateTime(whose === 'you' ? got.first : got.first * 1000, DAY) : '';
            const name = h('strong', {}, tOr(`achievement.${a.id}.name`, a.name));
            return h('li', { class: got ? 'earned' : 'missing', 'data-id': a.id },
                h('span', { class: 'achievement-glyph', 'aria-hidden': 'true' }, tOr(`achievement.${a.id}.glyph`, a.glyph)),
                h('div', {}, h('p', {}, ...(got ? tn('challenges.achievements.earned', { name, count: got.count, date: first }) : tn('challenges.achievements.notYet', { name }))),
                    h('p', { class: 'muted small' }, tOr(`achievement.${a.id}.description`, a.description))));
        }));
    }

    // The lines of an end card that name achievements, the new ones first.
    achievementLines(ids, fresh) {
        if (!ids.length) {
            return null;
        }
        const others = ids.filter((id) => !fresh.includes(id));
        return h('div', { class: 'achievement-new', role: 'status' },
            fresh.length ? h('p', {}, t('challenges.achievements.new', { count: fresh.length, names: fresh.map((id) => this.nameOf(id)).join(', ') })) : null,
            others.length ? h('p', { class: 'muted' }, t('challenges.achievements.again', { names: others.map((id) => this.nameOf(id)).join(', ') })) : null);
    }

    // The person's achievements of a game, from the ended report of the game's process.
    // The attempts of a challenge's run pass the achievements their run has shown, `seen`, so an
    // achievement earned again on every attempt shows on the first card alone.
    gameAchievements(entry, seen = null) {
        const sides = Array.isArray(entry.achievements) ? entry.achievements : [];
        const ids = [...new Set(sides.filter(Array.isArray).flat().filter((id) => typeof id === 'string'))];
        const fresh = addEarned(ids);
        this.renderAchievements();
        const shown = seen ? ids.filter((id) => fresh.includes(id) || !seen.has(id)) : ids;
        if (seen) {
            ids.forEach((id) => seen.add(id));
        }
        return this.achievementLines(shown, fresh);
    }

    personName() {
        const name = (this.nameField ? this.nameField.value : readName()).trim().slice(0, 40);
        return name || t('challenges.name.default');
    }

    find(id) {
        return this.catalog.find((c) => c.id === id) || null;
    }

    // Reads the catalog with the person's best runs and the registry, and draws the list.
    async show(teams = null) {
        if (teams) {
            this.teams = teams;
        }
        try {
            this.catalog = await challengeApi.list(this.personName());
            this.note.textContent = '';
        } catch (err) {
            this.note.textContent = t('challenges.unavailable', { reason: err.message });
        }
        await this.loadAchievements();
        this.renderTeams();
        this.render();
        this.renderAchievements();
        this.renderBanner();
        this.followJobs();
    }

    renderTeams() {
        if (!this.teamSelect) {
            return;
        }
        const before = this.teamSelect.value;
        this.teamSelect.replaceChildren(...this.teams.map((team) =>
            h('option', { value: team.id }, team.kind === 'builtin' ? t('challenges.team.builtin') : teamName(team))));
        if (this.teams.some((team) => team.id === before)) {
            this.teamSelect.value = before;
        }
    }

    render() {
        if (!this.list) {
            return;
        }
        const focused = document.activeElement && this.list.contains(document.activeElement)
            ? [document.activeElement.closest('[data-id]')?.dataset.id, document.activeElement.dataset.action] : null;
        this.list.replaceChildren(...this.catalog.map((c) => this.item(c)));
        if (focused && focused[0]) {
            const again = this.list.querySelector(`[data-id="${focused[0]}"] [data-action="${focused[1]}"]`);
            if (again) {
                again.focus();
            }
        }
    }

    item(c) {
        const mine = c.board && c.board.mine;
        const best = mine ? runText(c, mine, 'challenges.item.best', { rank: String(mine.rank) }) : t('challenges.item.noRun');
        // Every challenge has the same buttons, so each names its challenge for screen readers.
        const title = challengeTitle(c);
        const named = (id) => t(`${id}.label`, { title });
        const open = this.boards.has(c.id);
        const board = h('div', { class: 'challenge-board', hidden: !open });
        if (open) {
            this.fillBoard(c, board, this.boards.get(c.id));
        }
        const toggle = h('button', { type: 'button', class: 'btn small', 'data-action': 'board', 'aria-expanded': open ? 'true' : 'false', ...symbolOnly(named('challenges.item.board')), onclick: () => this.toggleBoard(c, board, toggle) }, icon('podium'));
        const leaders = c.board && c.board.top && c.board.top.length
            ? t('challenges.item.leader', {
                name: teamName(c.board.top[0]), value: valueText(c, c.board.top[0].value),
                people: t('challenges.item.people', { count: c.board.people }), agents: t('challenges.item.agents', { count: c.board.agents }),
            })
            : t('challenges.item.empty');
        return h('li', { class: 'challenge-item', 'data-id': c.id },
            h('h3', {}, title, medalBadge(mine && mine.medal)),
            h('p', {}, challengeGoal(c)),
            h('p', { class: 'muted small' }, t('challenges.item.plays', { scenario: scenarioName(c.scenario), count: c.attempts, targets: targetsText(c) })),
            h('p', { class: 'muted small' }, abilityText(c)),
            h('p', { class: 'small' }, best),
            h('p', { class: 'muted small' }, leaders),
            h('div', { class: 'challenge-actions' },
                h('button', { type: 'button', class: 'btn small', 'data-action': 'start', ...symbolOnly(named('challenges.item.start')), onclick: () => this.start(c.id) }, icon('play')),
                h('button', { type: 'button', class: 'btn small', 'data-action': 'headless', ...symbolOnly(named('challenges.item.headless')), onclick: () => this.runHeadless(c.id) }, icon('robot')),
                toggle),
            board);
    }

    async toggleBoard(c, board, button) {
        if (this.boards.has(c.id)) {
            this.boards.delete(c.id);
            board.hidden = true;
            button.setAttribute('aria-expanded', 'false');
            return;
        }
        button.setAttribute('aria-expanded', 'true');
        board.hidden = false;
        board.replaceChildren(h('p', { class: 'muted small' }, t('challenges.board.loading')));
        try {
            const data = await challengeApi.board(c.id);
            this.boards.set(c.id, data.entries);
            this.fillBoard(c, board, data.entries);
        } catch (err) {
            board.replaceChildren(h('p', { class: 'error-text' }, err.message));
        }
    }

    fillBoard(c, board, entries) {
        const seeds = h('p', { class: 'muted small' }, t('challenges.board.seeds', { seeds: c.seeds.join(', ') }));
        if (!entries.length) {
            board.replaceChildren(h('p', { class: 'muted small' }, t('challenges.board.empty')), seeds);
            return;
        }
        const rows = entries.map((e) => h('tr', { class: e.kind },
            h('td', { class: 'num' }, String(e.rank)),
            h('td', {}, teamName(e), ' ', h('span', { class: `challenge-kind ${e.kind}` }, competitorKind(e))),
            h('td', { class: 'num' }, valueText(c, e.value)),
            h('td', { class: 'num' }, t('challenges.board.seconds', { seconds: num(e.seconds) })),
            h('td', {}, e.medal ? MEDAL_NAMES[e.medal] : t('challenges.board.noMedal')),
            h('td', {}, formatDateTime(e.time * 1000, DAY))));
        board.replaceChildren(h('table', {}, h('caption', { class: 'sr-only' }, t('challenges.board.label', { title: challengeTitle(c) })),
            h('thead', {}, h('tr', {}, h('th', { class: 'num', scope: 'col' }, t('challenges.board.rank')), h('th', { scope: 'col' }, t('challenges.board.competitor')),
                h('th', { class: 'num', scope: 'col' }, t('challenges.board.result')), h('th', { class: 'num', scope: 'col' }, t('challenges.board.toScore')),
                h('th', { scope: 'col' }, t('challenges.board.medal')), h('th', { scope: 'col' }, t('challenges.board.date')))),
            h('tbody', {}, rows)), seeds);
    }

    // A person's run.

    async start(id) {
        if (!this.catalog.length) {
            await this.show();
        }
        const challenge = this.find(id);
        if (!challenge) {
            throw new Error(`No challenge ${id}.`);
        }
        writeName(this.personName());
        this.abandon(this.run);
        this.run = { id, challenge, index: 0, matches: [], results: [], name: this.personName(), outcome: null, keep: this.keepRecordings() };
        await this.attempt();
        return this.state();
    }

    async attempt() {
        const run = this.run;
        if (!run) {
            return;
        }
        if (this.app.page !== 'play') {
            this.app.showPage('play');
        }
        const c = run.challenge;
        await this.play.start({
            scenario: c.scenario, side: 'left', ability: c.ability.slice(), record: true,
            teams: ['builtin', 'builtin'], seed: c.seeds[run.index], challenge: run,
        });
    }

    async next() {
        if (this.run && !this.run.outcome && this.run.index < this.run.challenge.attempts - 1 && this.run.matches.length > this.run.index) {
            this.run.index++;
            await this.attempt();
        }
        return this.state();
    }

    // Leaves a run for the setup, and with the id of its challenge puts the focus on that
    // challenge's Start challenge, so the end card leads back to the challenge just played.
    leave(id = null) {
        this.abandon(this.run);
        this.run = null;
        this.renderBanner();
        this.play.showSetup();
        const again = id && this.list ? this.list.querySelector(`[data-id="${CSS.escape(id)}"] [data-action="start"]`) : null;
        if (again) {
            again.focus({ preventScroll: true });
            again.scrollIntoView({ block: 'center' });
        }
    }

    // Whether runs keep their attempts as recordings, as the setting of the section says.
    keepRecordings() {
        return this.keepBox ? this.keepBox.checked : readKeep();
    }

    // Hands the attempts of a run left before its end to the server, which keeps them as a group
    // or, for a run without recordings, removes them.
    abandon(run) {
        if (!run || run.outcome || !run.matches.some(Boolean)) {
            return;
        }
        challengeApi.leaveRun(run.id, run.name, run.matches.slice(), run.keep !== false)
            .catch((err) => this.app.hud && this.app.hud.toast(err.message, 'error'));
    }

    renderBanner() {
        if (!this.banner) {
            return;
        }
        const run = this.run;
        const waiting = run && !run.outcome && run.matches.length > run.index;
        this.banner.hidden = !waiting;
        if (!waiting) {
            this.banner.replaceChildren();
            return;
        }
        const last = run.index === run.challenge.attempts - 1;
        this.banner.replaceChildren(...[
            h('span', {}, t('challenges.run.banner', { title: challengeTitle(run.challenge), played: run.matches.length, count: run.challenge.attempts })),
            last ? null : h('button', { type: 'button', class: 'btn small', ...symbolOnly(t('challenges.run.next')), onclick: () => this.next() }, icon('next')),
            h('button', { type: 'button', class: 'btn small', ...symbolOnly(t('challenges.run.leave')), onclick: () => this.leave() }, icon('exit'))].filter(Boolean));
    }

    // The end card of a game. A game of a challenge shows its attempt's result and leads on to the
    // next attempt, or after the last one to the run's medal, and any other game keeps its card.
    endCard(entry, game, lines) {
        const run = this.run;
        const ofRun = !!(run && game && game.spec && game.spec.challenge === run);
        const earned = this.gameAchievements(entry, ofRun ? (run.seen ||= new Set()) : null);
        if (!ofRun) {
            return earned ? [lines[0], lines[1], earned, ...lines.slice(2)] : lines;
        }
        const c = run.challenge;
        const index = run.index;
        const match = entry.match || null;
        run.matches[index] = match;
        const last = index === c.attempts - 1;
        const result = h('div', { class: 'challenge-result', role: 'status', 'aria-live': 'polite' },
            h('p', {}, t('challenges.run.attempt', { title: challengeTitle(c), number: index + 1, count: c.attempts })),
            h('p', { class: 'muted' }, match ? t('challenges.run.scoring') : t('challenges.run.missed')));
        const buttons = [];
        if (!last) {
            buttons.push(h('button', { type: 'button', class: 'btn primary', onclick: () => this.next() }, icon('next'), t('challenges.run.next')));
        }
        if (match) {
            buttons.push(h('button', { type: 'button', class: 'btn', onclick: () => this.app.openMatchInWatch(match) }, icon('watch'), t('challenges.run.watch')));
            buttons[buttons.length - 1].dataset.action = 'watch';
        }
        buttons.push(h('button', { type: 'button', class: 'btn', onclick: () => this.leave(c.id) }, icon('exit'), last ? t('challenges.title') : t('challenges.run.leave')));
        const shown = [lines[0], lines[1], ...lines.filter((line) => line.classList && line.classList.contains('error-text')), result, earned, ...buttons].filter(Boolean);
        this.scoreAttempt(run, index, match, result).then(() => (last ? this.finishRun(run, result, buttons) : null));
        this.renderBanner();
        return shown;
    }

    async scoreAttempt(run, index, match, host) {
        const c = run.challenge;
        if (!match) {
            run.results[index] = { index, seed: c.seeds[index], match: null, finished: false, goals: [0, 0], scored: false, seconds: null, counts: false };
            return;
        }
        try {
            const scored = await challengeApi.score(run.id, match, index);
            run.results[index] = scored.result;
            host.children[1].textContent = attemptText(c, scored.result);
            if (scored.problem) {
                host.append(h('p', { class: 'error-text' }, t('challenges.run.problem', { problem: serverText(scored, 'problem') })));
            }
        } catch (err) {
            host.children[1].textContent = t('challenges.run.scoreFailed', { reason: err.message });
        }
    }

    async finishRun(run, host, buttons) {
        if (this.run !== run) {
            return;
        }
        const c = run.challenge;
        host.append(h('p', { class: 'muted' }, t('challenges.run.sending')));
        try {
            const outcome = await challengeApi.submit(run.id, run.name, run.matches.slice(0, c.attempts), run.keep !== false);
            run.outcome = outcome;
            host.lastChild.remove();
            host.append(...this.outcomeLines(c, outcome));
            // The games of the attempts already counted their own achievements.
            const awards = (outcome.achievements || []).filter((id) => CHALLENGE_AWARDS.has(id));
            const lines = this.achievementLines(awards, addEarned(awards));
            if (lines) {
                host.append(lines);
            }
            this.renderAchievements();
        } catch (err) {
            host.lastChild.textContent = t('challenges.run.sendFailed', { reason: err.message });
        }
        const again = h('button', { type: 'button', class: 'btn primary', onclick: () => this.start(c.id) }, icon('replay'), t('challenges.run.again'));
        const panel = buttons[0] && buttons[0].parentNode;
        if (panel) {
            panel.insertBefore(again, buttons[0]);
            again.focus();
        }
        if (run.outcome && run.keep === false) {
            // A run without recordings has nothing left to watch.
            buttons.filter((button) => button.dataset.action === 'watch').forEach((button) => button.remove());
        }
        this.renderBanner();
        this.show();
    }

    // The lines of a finished run, its value, medal, personal best and rank.
    outcomeLines(c, outcome) {
        const lines = [
            h('p', { class: 'play-score' }, runText(c, outcome, 'challenges.outcome.value')),
            // The medal shows once, as a badge that says its name.
            h('p', {}, outcome.medal ? medalBadge(outcome.medal, t('challenges.outcome.medal', { medal: MEDAL_NAMES[outcome.medal] })) : t('challenges.outcome.noMedal')),
        ];
        if (outcome.practice) {
            lines.push(h('p', { class: 'muted' }, t('challenges.outcome.practice')));
        } else if (outcome.personal_best) {
            const best = outcome.personal_best;
            const rank = outcome.rank ?? t('challenges.rank.outside');
            // A competitor's first run is its best by default, so it says first rather than new best.
            const id = outcome.first ? 'challenges.outcome.first' : 'challenges.outcome.improved';
            lines.push(h('p', {}, outcome.first || outcome.improved ? t(id, { rank })
                : runText(c, best, 'challenges.outcome.best', { rank })));
        }
        return lines;
    }

    // Headless runs of registered teams.

    async runHeadless(id, team = null, attempts = undefined, keep = this.keepRecordings()) {
        const chosen = team || (this.teamSelect && this.teamSelect.value) || 'builtin';
        const count = attempts !== undefined ? attempts : (this.attemptSelect && this.attemptSelect.value !== 'full' ? Number(this.attemptSelect.value) : null);
        let job;
        try {
            job = await challengeApi.runTeam(id, chosen, count, keep);
        } catch (err) {
            if (this.jobLine) {
                this.jobLine.hidden = false;
                this.jobLine.replaceChildren(h('span', { class: 'error-text' }, err.message));
            }
            throw err;
        }
        this.jobs = [job, ...this.jobs.filter((j) => j.id !== job.id)];
        this.renderJob();
        this.followJobs();
        return job;
    }

    followJobs() {
        if (this.polling) {
            return;
        }
        this.polling = true;
        const tick = async () => {
            try {
                const before = new Map(this.jobs.map((j) => [j.id, j.state]));
                this.jobs = await challengeApi.jobs();
                this.renderJob();
                const ended = this.jobs.some((j) => j.state === 'done' && before.get(j.id) && before.get(j.id) !== 'done');
                if (ended) {
                    this.boards.clear();
                    this.show();
                }
            } catch {
                // The next refresh of the page tries again.
            }
            if (this.jobs.some((j) => j.state === 'queued' || j.state === 'running')) {
                setTimeout(tick, POLL_MS);
            } else {
                this.polling = false;
            }
        };
        tick();
    }

    renderJob() {
        if (!this.jobLine) {
            return;
        }
        const job = this.jobs[0];
        if (!job) {
            this.jobLine.hidden = true;
            return;
        }
        const c = this.find(job.challenge) || { title: job.challenge, measure: 'scored', attempts: job.attempts };
        const title = this.find(job.challenge) ? challengeTitle(c) : c.title;
        let text;
        if (job.state === 'queued') {
            text = t('challenges.job.queued', { name: teamName(job), title });
        } else if (job.state === 'running') {
            text = t('challenges.job.running', { name: teamName(job), title, done: job.results.length, count: job.attempts });
        } else if (job.state === 'done' && job.result) {
            const r = job.result;
            const rank = r.rank ?? t('challenges.rank.outside');
            const medal = r.practice ? t('challenges.job.practice') : r.medal ? t('challenges.job.medal', { medal: MEDAL_NAMES[r.medal], rank }) : t('challenges.job.noMedal', { rank });
            const won = (r.achievements || []).map((id) => this.nameOf(id));
            const values = { name: teamName(job), title, value: valueText(c, r.value), medal, names: won.join(', ') };
            text = t(won.length ? 'challenges.job.doneAchievements' : 'challenges.job.done', values);
        } else {
            text = t('challenges.job.stopped', { name: teamName(job), title, reason: job.error ? serverText(job, 'error') : t('challenges.job.noResult') });
        }
        const live = job.state === 'queued' || job.state === 'running';
        this.jobLine.hidden = false;
        this.jobLine.replaceChildren(...[h('span', { class: job.state === 'failed' ? 'error-text' : '' }, text),
            live ? h('button', { type: 'button', class: 'btn small', ...symbolOnly(t('challenges.job.cancel')), onclick: () => this.cancelJob(job.id) }, icon('stop')) : null].filter(Boolean));
    }

    async cancelJob(id) {
        try {
            await challengeApi.cancel(id);
        } catch (err) {
            this.app.hud.toast(err.message, 'error');
        }
        this.polling = false;
        this.followJobs();
    }

    // The state of a person's run, for scripts.
    state() {
        const run = this.run;
        return {
            run: run ? { challenge: run.id, attempt: run.index, attempts: run.challenge.attempts, matches: run.matches.slice(), results: run.results.slice(), outcome: run.outcome } : null,
            jobs: this.jobs.slice(),
        };
    }

    // The scripting functions of window.cuju.challenges, which need no mouse.
    script() {
        const self = this;
        return {
            list: async () => (self.catalog = await challengeApi.list(self.personName())),
            board: async (id) => (await challengeApi.board(id)).entries,
            start: async (id, { name } = {}) => {
                if (!self.play.built) {
                    self.app.showPage('play');
                }
                if (name) {
                    writeName(String(name).trim().slice(0, 40));
                    if (self.nameField) {
                        self.nameField.value = name;
                    }
                }
                return self.start(id);
            },
            next: () => self.next(),
            leave: () => self.leave(),
            run: (id, { team = 'builtin', attempts = null, keepRecordings } = {}) => self.runHeadless(id, team, attempts, keepRecordings ?? self.keepRecordings()),
            jobs: async () => (self.jobs = await challengeApi.jobs()),
            cancel: (job) => self.cancelJob(job),
            score: (id, match, attempt) => challengeApi.score(id, match, attempt),
            achievements: async () => {
                const data = await self.loadAchievements();
                self.renderAchievements();
                return { catalog: data.catalog, person: readEarned(), teams: data.teams };
            },
            state: () => self.state(),
            api: challengeApi,
        };
    }
}
