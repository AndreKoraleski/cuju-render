// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Challenges on the Play page, short drills with bronze, silver and gold targets that people play
// in a game and registered teams play headless on the server. Every attempt plays a fixed seed, so
// people and agents face the same episodes, and the server scores each attempt from its recording
// and keeps one leaderboard per challenge. Achievements, which the server finds in the frames by
// the same rules for people and teams, show on the end cards and in a list of their own, kept on
// disk for teams and in the browser for the person. Scripts reach it all through
// window.cuju.challenges.

import { el as h } from '../core/menu.js';
import { scenarioName } from '../core/scenarios.js';

const NAME_KEY = 'cuju.challengeName';
const EARNED_KEY = 'cuju.achievements';
// The achievements of a challenge's medals, which a run adds to those of its attempts' games.
const CHALLENGE_AWARDS = new Set(['podium', 'gold_standard', 'academy_graduate']);
const MEDAL_NAMES = { bronze: 'Bronze', silver: 'Silver', gold: 'Gold' };
const MEDALS = ['bronze', 'silver', 'gold'];
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
        throw new Error(`Cannot reach the cuju server at ${location.origin}. Is it still running?`);
    }
    const text = await res.text();
    let data = null;
    try {
        data = text ? JSON.parse(text) : null;
    } catch {
        data = null;
    }
    if (!res.ok) {
        const error = new Error((data && data.error) || `The server answered ${res.status}.`);
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
    submit: (id, person, matches) => call('POST', `/api/challenges/${enc(id)}/runs`, { person, matches }),
    runTeam: (id, team, attempts = null) => call('POST', `/api/challenges/${enc(id)}/runs`,
        attempts == null ? { team } : { team, attempts }),
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

// The value of a run in words, by the measure of its challenge.
export function valueText(challenge, value) {
    if (challenge.measure === 'margin') {
        return `${value > 0 ? '+' : ''}${value} ${Math.abs(value) === 1 ? 'goal' : 'goals'}`;
    }
    return `${value} of ${challenge.attempts}`;
}

export function targetsText(challenge) {
    const parts = MEDALS.map((m, i) => `${MEDAL_NAMES[m]} ${valueText(challenge, challenge.targets[i])}`);
    return `${parts.join(', ')}.`;
}

function medalBadge(medal) {
    return medal ? h('span', { class: `challenge-medal ${medal}` }, MEDAL_NAMES[medal]) : null;
}

// One attempt's result in words.
export function attemptText(challenge, result) {
    const goals = `${result.goals[0]} for, ${result.goals[1]} against`;
    if (!result.match && !result.finished) {
        return 'Missed, nothing was played.';
    }
    if (!result.finished) {
        return `Left before the end, so it counts no goals for. ${goals}.`;
    }
    if (!result.scored) {
        return `No goal. ${goals}.`;
    }
    const time = `Scored after ${result.seconds} seconds of play`;
    if (challenge.measure === 'within') {
        return result.counts ? `${time}, within the ${challenge.limit} seconds.` : `${time}, past the ${challenge.limit} seconds, so it does not count.`;
    }
    return challenge.measure === 'margin' ? `${time}. ${goals}.` : `${time}.`;
}

function abilityText(challenge) {
    const [left, right] = challenge.played_ability || [null, null];
    return `The built-in AI plays at ability ${Number(left).toFixed(2)} on your side and ${Number(right).toFixed(2)} on the other.`;
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
        this.nameField = h('input', { type: 'text', maxlength: '40', value: readName() || 'Player', 'aria-label': 'Your name on the leaderboards', class: 'challenge-name' });
        this.nameField.addEventListener('change', () => writeName(this.personName()));
        this.teamSelect = h('select', { 'aria-label': 'Team for headless runs', class: 'challenge-team' });
        this.attemptSelect = h('select', { 'aria-label': 'Attempts of a headless run', class: 'challenge-attempts' },
            h('option', { value: 'full' }, 'Full run'), h('option', { value: '1' }, 'Practice, one attempt'));
        this.banner = h('div', { class: 'challenge-banner', role: 'status', hidden: true });
        this.jobLine = h('div', { class: 'challenge-job', role: 'status', 'aria-live': 'polite', hidden: true });
        this.list = h('ul', { class: 'challenge-list', 'aria-label': 'Challenges' });
        this.note = h('p', { class: 'muted small', role: 'status' });
        this.root = h('section', { class: 'challenges', 'aria-labelledby': 'challenges-title' },
            h('h2', { id: 'challenges-title' }, 'Challenges'),
            h('p', { class: 'muted' }, 'Each challenge plays a set of attempts, each on a fixed seed, so every person and every agent faces the same episodes. Start challenge plays them here, and Run headless plays them with a registered team on the server, faster than real time.'),
            h('div', { class: 'setup-row' },
                h('label', { class: 'field' }, 'Your name', this.nameField),
                h('label', { class: 'field' }, 'Team for headless runs', this.teamSelect),
                h('label', { class: 'field' }, 'Attempts', this.attemptSelect)),
            this.banner, this.jobLine, this.note, this.list, this.achievementsPart());
        return this.root;
    }

    achievementsPart() {
        this.whoseSelect = h('select', { 'aria-label': 'Whose achievements', class: 'achievement-whose' });
        this.whoseSelect.addEventListener('change', () => this.renderAchievements());
        this.achievementList = h('ul', { class: 'achievement-list', 'aria-label': 'Achievements' });
        this.achievementNote = h('p', { class: 'muted small', role: 'status' });
        return h('section', { class: 'achievements', 'aria-labelledby': 'achievements-title' },
            h('h3', { id: 'achievements-title' }, 'Achievements'),
            h('p', { class: 'muted' }, 'Achievements come from the frames of each game, by the same rules for people and for registered teams. Yours stay in this browser, and those of the teams stay with the server.'),
            h('label', { class: 'field' }, 'Whose achievements', this.whoseSelect),
            this.achievementNote, this.achievementList);
    }

    // The catalog and the teams' achievements from the server, and the person's from the browser.
    async loadAchievements() {
        try {
            this.achievements = await challengeApi.achievements();
        } catch (err) {
            this.achievements = this.achievements || { catalog: [], teams: {} };
            if (this.achievementNote) {
                this.achievementNote.textContent = `The achievements are unavailable, ${err.message}`;
            }
        }
        return this.achievements;
    }

    nameOf(id) {
        const entry = this.achievements && this.achievements.catalog.find((a) => a.id === id);
        return entry ? entry.name : id;
    }

    renderAchievements() {
        if (!this.achievementList || !this.achievements) {
            return;
        }
        const before = this.whoseSelect.value || 'you';
        const teams = this.teams.filter((team) => team.kind !== 'builtin');
        this.whoseSelect.replaceChildren(h('option', { value: 'you' }, 'You'),
            ...teams.map((team) => h('option', { value: team.id }, team.name)));
        this.whoseSelect.value = before === 'you' || teams.some((team) => team.id === before) ? before : 'you';
        const whose = this.whoseSelect.value;
        const earned = whose === 'you' ? readEarned() : (this.achievements.teams[whose] || {});
        const count = this.achievements.catalog.filter((a) => earned[a.id]).length;
        this.achievementNote.textContent = `${count} of ${this.achievements.catalog.length} earned.`;
        this.achievementList.replaceChildren(...this.achievements.catalog.map((a) => {
            const got = earned[a.id];
            const first = got ? new Date(whose === 'you' ? got.first : got.first * 1000).toLocaleDateString() : '';
            return h('li', { class: got ? 'earned' : 'missing', 'data-id': a.id },
                h('span', { class: 'achievement-glyph', 'aria-hidden': 'true' }, a.glyph),
                h('div', {}, h('p', {}, h('strong', {}, a.name), got ? `, earned ${got.count} ${got.count === 1 ? 'time' : 'times'}, first on ${first}` : ', not yet'),
                    h('p', { class: 'muted small' }, a.description)));
        }));
    }

    // The lines of an end card that name achievements, the new ones first.
    achievementLines(ids, fresh) {
        if (!ids.length) {
            return null;
        }
        const others = ids.filter((id) => !fresh.includes(id));
        return h('div', { class: 'achievement-new', role: 'status' },
            fresh.length ? h('p', {}, `New ${fresh.length === 1 ? 'achievement' : 'achievements'}, ${fresh.map((id) => this.nameOf(id)).join(', ')}.`) : null,
            others.length ? h('p', { class: 'muted' }, `Earned again, ${others.map((id) => this.nameOf(id)).join(', ')}.`) : null);
    }

    // The person's achievements of a game, from the ended report of the game's process.
    gameAchievements(entry) {
        const sides = Array.isArray(entry.achievements) ? entry.achievements : [];
        const ids = [...new Set(sides.filter(Array.isArray).flat().filter((id) => typeof id === 'string'))];
        const fresh = addEarned(ids);
        this.renderAchievements();
        return this.achievementLines(ids, fresh);
    }

    personName() {
        const name = (this.nameField ? this.nameField.value : readName()).trim().slice(0, 40);
        return name || 'Player';
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
            this.note.textContent = `The challenges are unavailable, ${err.message}`;
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
            h('option', { value: team.id }, team.kind === 'builtin' ? "GRF's built-in AI, the whole side" : team.name)));
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
        const best = mine ? `Your best, ${valueText(c, mine.value)} in ${mine.seconds} seconds to score, rank ${mine.rank}.` : 'No run of yours yet.';
        const open = this.boards.has(c.id);
        const board = h('div', { class: 'challenge-board', hidden: !open });
        if (open) {
            this.fillBoard(c, board, this.boards.get(c.id));
        }
        const toggle = h('button', { type: 'button', class: 'btn small', 'data-action': 'board', 'aria-expanded': open ? 'true' : 'false', onclick: () => this.toggleBoard(c, board, toggle) }, 'Leaderboard');
        const leaders = c.board && c.board.top && c.board.top.length
            ? `Leader ${c.board.top[0].name}, ${valueText(c, c.board.top[0].value)}. ${c.board.people} ${c.board.people === 1 ? 'person' : 'people'} and ${c.board.agents} ${c.board.agents === 1 ? 'agent' : 'agents'} on the board.`
            : 'The leaderboard is empty.';
        return h('li', { class: 'challenge-item', 'data-id': c.id },
            h('h3', {}, c.title, medalBadge(mine && mine.medal)),
            h('p', {}, c.goal),
            h('p', { class: 'muted small' }, `${scenarioName(c.scenario)}, ${c.attempts} attempts. ${targetsText(c)}`),
            h('p', { class: 'muted small' }, abilityText(c)),
            h('p', { class: 'small' }, best),
            h('p', { class: 'muted small' }, leaders),
            h('div', { class: 'challenge-actions' },
                h('button', { type: 'button', class: 'btn small', 'data-action': 'start', onclick: () => this.start(c.id) }, 'Start challenge'),
                h('button', { type: 'button', class: 'btn small', 'data-action': 'headless', onclick: () => this.runHeadless(c.id) }, 'Run headless'),
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
        board.replaceChildren(h('p', { class: 'muted small' }, 'Loading the leaderboard.'));
        try {
            const data = await challengeApi.board(c.id);
            this.boards.set(c.id, data.entries);
            this.fillBoard(c, board, data.entries);
        } catch (err) {
            board.replaceChildren(h('p', { class: 'error-text' }, err.message));
        }
    }

    fillBoard(c, board, entries) {
        const seeds = h('p', { class: 'muted small' }, `Seeds of the attempts in order, ${c.seeds.join(', ')}.`);
        if (!entries.length) {
            board.replaceChildren(h('p', { class: 'muted small' }, 'No runs yet. A full run of people or agents lands here.'), seeds);
            return;
        }
        const rows = entries.map((e) => h('tr', { class: e.kind },
            h('td', { class: 'num' }, String(e.rank)),
            h('td', {}, e.name, ' ', h('span', { class: `challenge-kind ${e.kind}` }, e.kind === 'person' ? 'Person' : 'Agent')),
            h('td', { class: 'num' }, valueText(c, e.value)),
            h('td', { class: 'num' }, `${e.seconds} s`),
            h('td', {}, e.medal ? MEDAL_NAMES[e.medal] : 'None'),
            h('td', {}, new Date(e.time * 1000).toLocaleDateString())));
        board.replaceChildren(h('table', { 'aria-label': `Leaderboard of ${c.title}` },
            h('thead', {}, h('tr', {}, h('th', { class: 'num', scope: 'col' }, 'Rank'), h('th', { scope: 'col' }, 'Competitor'),
                h('th', { class: 'num', scope: 'col' }, 'Result'), h('th', { class: 'num', scope: 'col' }, 'Seconds to score'),
                h('th', { scope: 'col' }, 'Medal'), h('th', { scope: 'col' }, 'Date'))),
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
        this.run = { id, challenge, index: 0, matches: [], results: [], name: this.personName(), outcome: null };
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

    leave() {
        this.run = null;
        this.renderBanner();
        this.play.showSetup();
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
            h('span', {}, `${run.challenge.title} is under way, ${run.matches.length} of ${run.challenge.attempts} attempts played.`),
            last ? null : h('button', { type: 'button', class: 'btn small', onclick: () => this.next() }, 'Next attempt'),
            h('button', { type: 'button', class: 'btn small', onclick: () => this.leave() }, 'Leave challenge')].filter(Boolean));
    }

    // The end card of a game. A game of a challenge shows its attempt's result and leads on to the
    // next attempt, or after the last one to the run's medal, and any other game keeps its card.
    endCard(entry, game, lines) {
        const run = this.run;
        const earned = this.gameAchievements(entry);
        if (!game || !game.spec || !game.spec.challenge || game.spec.challenge !== run) {
            return earned ? [lines[0], lines[1], earned, ...lines.slice(2)] : lines;
        }
        const c = run.challenge;
        const index = run.index;
        const match = entry.match || null;
        run.matches[index] = match;
        const last = index === c.attempts - 1;
        const result = h('div', { class: 'challenge-result', role: 'status', 'aria-live': 'polite' },
            h('p', {}, `${c.title}, attempt ${index + 1} of ${c.attempts}.`),
            h('p', { class: 'muted' }, match ? 'Scoring the attempt from its recording.' : 'Nothing was played, so the attempt counts as missed.'));
        const buttons = [];
        if (!last) {
            buttons.push(h('button', { type: 'button', class: 'btn primary', onclick: () => this.next() }, 'Next attempt'));
        }
        if (match) {
            buttons.push(h('button', { type: 'button', class: 'btn', onclick: () => this.app.openMatchInWatch(match) }, 'Watch it'));
        }
        buttons.push(h('button', { type: 'button', class: 'btn', onclick: () => this.leave() }, last ? 'Challenges' : 'Leave challenge'));
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
                host.append(h('p', { class: 'error-text' }, `This recording cannot count, ${scored.problem}.`));
            }
        } catch (err) {
            host.children[1].textContent = `The attempt could not be scored, ${err.message}`;
        }
    }

    async finishRun(run, host, buttons) {
        if (this.run !== run) {
            return;
        }
        const c = run.challenge;
        host.append(h('p', { class: 'muted' }, 'Sending the run to the leaderboard.'));
        try {
            const outcome = await challengeApi.submit(run.id, run.name, run.matches.slice(0, c.attempts));
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
            host.lastChild.textContent = `The run could not reach the leaderboard, ${err.message}`;
        }
        const again = h('button', { type: 'button', class: 'btn primary', onclick: () => this.start(c.id) }, 'Try again');
        const panel = buttons[0] && buttons[0].parentNode;
        if (panel) {
            panel.insertBefore(again, buttons[0]);
            again.focus();
        }
        this.renderBanner();
        this.show();
    }

    // The lines of a finished run, its value, medal, personal best and rank.
    outcomeLines(c, outcome) {
        const lines = [
            h('p', { class: 'play-score' }, `${valueText(c, outcome.value)}, ${outcome.seconds} seconds to score.`),
            h('p', {}, outcome.medal ? `${MEDAL_NAMES[outcome.medal]} medal.` : 'No medal this time.', ' ', medalBadge(outcome.medal)),
        ];
        if (outcome.practice) {
            lines.push(h('p', { class: 'muted' }, 'Practice, fewer attempts than the challenge, so no medal and no leaderboard.'));
        } else if (outcome.personal_best) {
            const best = outcome.personal_best;
            lines.push(h('p', {}, outcome.improved ? `A new personal best, rank ${outcome.rank ?? 'outside the board'}.`
                : `Personal best ${valueText(c, best.value)} in ${best.seconds} seconds, rank ${outcome.rank ?? 'outside the board'}.`));
        }
        return lines;
    }

    // Headless runs of registered teams.

    async runHeadless(id, team = null, attempts = undefined) {
        const chosen = team || (this.teamSelect && this.teamSelect.value) || 'builtin';
        const count = attempts !== undefined ? attempts : (this.attemptSelect && this.attemptSelect.value !== 'full' ? Number(this.attemptSelect.value) : null);
        let job;
        try {
            job = await challengeApi.runTeam(id, chosen, count);
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
        let text;
        if (job.state === 'queued') {
            text = `${job.name} waits to play ${c.title}.`;
        } else if (job.state === 'running') {
            text = `${job.name} plays ${c.title}, ${job.results.length} of ${job.attempts} attempts done.`;
        } else if (job.state === 'done' && job.result) {
            const r = job.result;
            const medal = r.practice ? 'practice' : r.medal ? `${MEDAL_NAMES[r.medal]} medal, rank ${r.rank ?? 'outside the board'}` : `no medal, rank ${r.rank ?? 'outside the board'}`;
            const won = (r.achievements || []).map((id) => this.nameOf(id));
            text = `${job.name} finished ${c.title}, ${valueText(c, r.value)}, ${medal}.${won.length ? ` Achievements, ${won.join(', ')}.` : ''}`;
        } else {
            text = `${job.name} stopped on ${c.title}, ${job.error || 'without a result'}.`;
        }
        const live = job.state === 'queued' || job.state === 'running';
        this.jobLine.hidden = false;
        this.jobLine.replaceChildren(...[h('span', { class: job.state === 'failed' ? 'error-text' : '' }, text),
            live ? h('button', { type: 'button', class: 'btn small', onclick: () => this.cancelJob(job.id) }, 'Cancel run') : null].filter(Boolean));
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
            run: (id, { team = 'builtin', attempts = null } = {}) => self.runHeadless(id, team, attempts),
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
