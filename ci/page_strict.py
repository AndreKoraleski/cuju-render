# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks a strict tournament of the Tournaments page and the strict check of a team's card.

ci/page_check.py runs strict_checks with the other checks of the page. Run alone, this file
starts the mock server and Chrome itself and runs these checks with the tournament checks of
ci/page_check.py and ci/page_tournaments.py.

The checks register four teams of five a side on the mock, Broken, which fails to load, Slow,
which runs past the time of a call in every match, Steady, and Wobbly, whose answers differ when
the same steps play again. They set up a round robin by hand in the wizard, add the random entrant
and the built-in AI in the Entrants step and remove the built-in AI again, turn on strict rules
and the pre-flight in Settings and read their limits and switches, run the pre-flight from the
review and start the tournament. The tournament leaves Broken out with its reason, Slow forfeits
by rule with the score at that moment, and the Results show the ratings with their intervals, the
matrix of mean goal difference as a heat table with named cells and the files to save. Add legs
plays one more leg and the results follow it. At the width of a phone the matrix scrolls in its
own box, and on the Teams page the cards of Broken, Steady and Wobbly fail, pass, and pass with a
warning.

Usage:
    python ci/page_strict.py [--port 8790] [--debug-port 8791] [--chrome google-chrome]
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import page_tournaments

# The teams of the checks and what each one does on the mock.
TEAMS = """
    const { api } = await import('./js/core/api.js');
    const strict = await import('./js/play/tournament-strict.js');
    const teams = {};
    for (const name of ['Broken strict', 'Slow strict', 'Steady strict', 'Wobbly strict']) {
        teams[name] = await api.uploadTeam(name, 'main.py',
            new Blob(['def agent(obs):\\n    return [0]\\n']), '5v5');
    }
    const text = (node) => (node ? node.textContent.replace(/\\s+/g, ' ').trim() : '');
"""


def _run(client, body, name):
    result = client.evaluate(
        '(async () => {' + page_tournaments.UNTIL + TEAMS + body + '})()',
    )
    assert result is True, f'{name} {result}'
    return 1


TOURNAMENT = """
    const all = {};
    let made = null;
    try {
        page.root.querySelector('.cup-side-head button').click();
        await until(() => Object.values(teams).every((x) => page.teams.some((y) => y.id === x.id)));
        // A round robin by hand, which starts without strict rules or added entrants.
        press(await until(() => main().querySelector('[data-preset="round_robin"]')));
        const d = page.draft;
        all.preset = d.preset === 'round_robin' && d.strict === null && d.preflight === false
            && d.include.length === 0;
        press(named('Next'));
        // The random entrant and the built-in AI enter through the Entrants step.
        press(main().querySelector('[data-focus="add-random"]'));
        press(named('Add built-in AI'));
        all.included = d.entrants.map((e) => e.kind).join() === 'random,builtin';
        all.kinds = [...main().querySelectorAll('.cup-entrant-kind')].map(text).join('|')
            === 'Random entrant|Built-in AI';
        all.glyph = !!main().querySelector('.cup-kind.random svg');
        // The random entrant enters once.
        press(main().querySelector('[data-focus="add-random"]'));
        all.once = d.entrants.filter((e) => e.kind === 'random').length === 1
            && toasts.at(-1) === 'The random entrant has entered already.';
        for (const name of ['Broken strict', 'Slow strict', 'Steady strict']) {
            main().querySelector('.cup-adder select').value = teams[name].id;
            press(named('Add team'));
        }
        // Removing the built-in AI leaves no entrant for the server to add back.
        const rows = [...main().querySelectorAll('.cup-entrants > li')];
        const builtin = rows.find((row) => text(row.querySelector('.cup-entrant-kind'))
            === 'Built-in AI');
        press(builtin.querySelector('.cup-remove'));
        all.dropped = d.entrants.length === 4 && d.include.length === 0
            && !d.entrants.some((e) => e.kind === 'builtin');
        // Settings turn on strict rules, with their limits and switches at their defaults, and
        // the pre-flight.
        press(named('Next'));
        const limits = [...main().querySelectorAll('.cup-strict [data-limit]')];
        const flags = [...main().querySelectorAll('.cup-strict [data-flag]')];
        const off = limits.every((input) => input.disabled) && flags.every((box) => box.disabled);
        press(main().querySelector('.cup-strict-switch'));
        press(main().querySelector('.cup-preflight-switch'));
        all.settings = off && main().querySelector('.cup-strict-switch').checked
            && main().querySelector('.cup-preflight-switch').checked && limits.length === 9
            && limits.every((input) => !input.disabled && input.getAttribute('aria-label'))
            && limits.map((input) => input.value).join() === '1,30,10,1,5,20,100,2048,120'
            && flags.map((box) => `${box.dataset.flag}:${box.checked}`).join()
                === 'frozen:true,gpu:false,deterministic:false'
            && flags.every((box) => !box.disabled) && d.strict && d.strict.frozen === true
            && d.preflight === true;
        // A switch changes the rules the draft sends, and goes back to its default.
        press(flags[1]);
        const gpu = d.strict.gpu === true;
        press(flags[1]);
        all.flag = gpu && d.strict.gpu === false;
        const call = limits.find((input) => input.dataset.limit === 'call_seconds');
        call.focus();
        call.value = '0';
        call.dispatchEvent(new Event('input', { bubbles: true }));
        const refused = call.getAttribute('aria-invalid') === 'true';
        call.value = '1';
        call.dispatchEvent(new Event('input', { bubbles: true }));
        all.limit = refused && !call.hasAttribute('aria-invalid')
            && d.strict.call_seconds === 1 && d.strict.load_seconds === 30
            && call.getAttribute('aria-label') === 'Each later call within, in seconds';
        // Two legs keep the league short.
        d.stages[0].legs = 2;
        page.goStep(4);
        const review = await until(() => main().querySelector('.cup-review-strict'));
        const reviewed = text(review.querySelector('.cup-review-limits'));
        all.review = /^Strict rules: 1 thread for each team, loading within 30 s/.test(reviewed)
            && reviewed.includes('memory of at most 2,048 MB, 120 s of computing in all for '
                + 'a match, frozen team folders, no GPU, answers that differ on a replay only '
                + 'warned.')
            && text(review).includes('A pre-flight check runs before the first match');
        // The pre-flight runs from the review, busy at once, and names who it would leave out.
        press(main().querySelector('[data-focus="preflight-run"]'));
        const host = () => main().querySelector('.cup-preflight-result');
        all.busy = host().getAttribute('aria-busy') === 'true';
        await until(() => host().querySelectorAll('.cup-checks > li').length === 3);
        // Each check names both sides it played, the right one unplayed after a failed left.
        const checks = [...host().querySelectorAll('.cup-checks > li')].map(text);
        const broken = checks.find((c) => c.startsWith('Broken strict, failed, '));
        all.checks = !!broken && /Broken strict failed to load, ImportError/.test(broken)
            && broken.includes('Right side left unplayed after the left side failed')
            && checks.filter((c) => /, passed, folder of [\\d.]+ MB/.test(c)
                && c.includes('Left side passed, loaded in ')
                && c.includes('Right side passed, loaded in ')).length === 2
            && checks.some((c) => c.includes(
                'Steady strict answered the action 5 in 95% of its actions.'))
            && /1 entrant would be left out: Broken strict\\./.test(text(host()));
        // The tournament starts, leaves Broken out and plays on without it.
        press(main().querySelector('.cup-start'));
        await until(() => page.mode === 'view' && page.current);
        made = page.current.id;
        await until(() => page.current.state === 'done' && main().querySelector('.cup-fixture'),
            20000);
        const head = main().querySelector('.cup-strict-head');
        all.head = /^Strict rules: 1 thread/.test(text(head.querySelector('.cup-strict-line')))
            && text(head.querySelector('.cup-preflight-state'))
                === 'Pre-flight check done, 1 team left out';
        const out = text(main().querySelector('.cup-excluded li'));
        all.excluded = /^Broken strict, Broken strict failed to load, ImportError/.test(out)
            && page.current.config.entrants.length === 3;
        // Slow forfeits by rule, with the reason and the score at that moment.
        const forfeits = [...main().querySelectorAll('.cup-fixture')].filter((f) => {
            const spoken = f.getAttribute('aria-label');
            return /forfeit at \\d+ to \\d+, Slow strict did not answer/.test(spoken)
                && /answer action call \\d+ within 1 second/.test(spoken)
                && /forfeit at/.test(text(f));
        });
        all.forfeits = forfeits.length === 4;
        // The results ask for the analysis only while they show.
        let asked = 0;
        const analysis = strict.strictApi.analysis;
        strict.strictApi.analysis = (...args) => {
            asked += 1;
            return analysis(...args);
        };
        const toggle = main().querySelector('[data-focus="results-toggle"]');
        all.closed = toggle.getAttribute('aria-expanded') === 'false' && asked === 0;
        press(toggle);
        await until(() => main().querySelectorAll('.cup-ratings tbody tr').length === 3);
        all.open = active() === toggle && toggle.getAttribute('aria-expanded') === 'true'
            && asked === 1;
        const ratings = main().querySelector('.cup-ratings');
        all.caption = /from 200 resamples$/.test(text(ratings.querySelector('caption')));
        const values = [...ratings.querySelectorAll('tbody tr')].map((row) => Number(
            text(row.children[2]).replace(/,/g, '')));
        all.best = values.every((value, i) => i === 0 || value <= values[i - 1]);
        all.bars = [...ratings.querySelectorAll('.cup-interval')].every((bar) =>
            bar.getAttribute('role') === 'img' && /^Rating \\S+, from \\S+ to \\S+$/.test(
                bar.getAttribute('aria-label'))
            && bar.querySelector('.cup-interval-range').style.width);
        const box = main().querySelector('.cup-matrix-scroll');
        const table = box.querySelector('table');
        all.matrix = box.tabIndex === 0 && box.getAttribute('aria-label')
            === 'Mean goal difference, row against column' && !!table.querySelector('caption')
            && table.querySelectorAll('thead th[scope="col"]').length === 3
            && table.querySelectorAll('tbody th[scope="row"]').length === 3
            && table.querySelectorAll('tbody td').length === 9;
        const cells = [...table.querySelectorAll('tbody td')].map((td) => td.getAttribute(
            'aria-label'));
        all.cells = cells.filter((c) => / against itself$/.test(c)).length === 3
            && cells.filter((c) => /^.+ against .+, mean goal difference /.test(c)
                && /(plus |minus )?\\d\\.\\d over 2 matches$/.test(c)).length === 6
            && cells.includes(
                'Slow strict against Steady strict, mean goal difference minus 3.0 over 2 matches');
        all.heat = !!table.querySelector('td.heat-up-4')
            && !!table.querySelector('td.heat-down-4');
        all.sticky = getComputedStyle(table.querySelector('tbody th')).position === 'sticky';
        box.focus();
        all.keyboard = active() === box;
        const links = [...main().querySelectorAll('.cup-file-list a')];
        all.files = links.map(text).join() === 'standings.csv,ratings.csv,ratings_method.json,'
            + 'pairwise_gd.csv,pairwise_counts.csv,matches.jsonl,entrants.json,excluded.json';
        // The results say how many matches ended early, the prior and the resamples.
        const summary = text(main().querySelector('.cup-results-summary'));
        all.summary = summary.startsWith('The ratings rest on 6 played matches. 4 matches among '
            + 'them ended early, by a forfeit or before full time.')
            && summary.includes('1 virtual draw against an entrant of a fixed strength')
            && summary.includes('from 200 resamples of the played matches');
        const saved = await fetch(links[0].getAttribute('href'));
        all.saved = saved.ok && /^attachment; filename=".+-standings\\.csv"$/.test(
            saved.headers.get('Content-Disposition'))
            && (await saved.text()).startsWith('position,entrant,id,name,kind,team,played');
        // One more leg plays the missing matches, and the results follow the played count.
        const count = main().querySelector('.cup-legs-count');
        count.focus();
        count.value = '1';
        press(main().querySelector('.cup-legs-add'));
        await until(() => toasts.at(-1) === '1 leg added. Its matches play next.');
        await until(() => page.current.state === 'done' && page.current.played === 9, 20000);
        await until(() => main().querySelector('.cup-ratings tbody tr td:last-child')
            && text(main().querySelector('.cup-ratings tbody tr td:last-child')) === '6', 10000);
        all.legs = asked >= 2 && page.current.scheduled === 9;
        strict.strictApi.analysis = analysis;
        all.errors = !main().querySelector('.notice.error');
        all.dialogs = dialogs.length === 0;
    } finally {
        cuju.hud.toast = toast;
        window.confirm = confirm;
        if (page.mode === 'wizard') {
            page.cancelWizard();
        }
        if (made) {
            await fetch(`/api/tournaments/${made}/cancel`, { method: 'POST' });
            await fetch(`/api/tournaments/${made}`, { method: 'DELETE' });
        }
        for (const team of Object.values(teams)) {
            await api.deleteTeam(team.id);
        }
    }
    return Object.values(all).every(Boolean) || JSON.stringify(all);
"""

PHONE = """
    const all = {};
    const info = {};
    let made = null;
    try {
        const { tournamentsApi } = await import('./js/play/tournament.js');
        const entry = await tournamentsApi.create({ name: 'Strict phone check', seed: 4,
            strict: true, entrants: [...Object.values(teams).map((x) => ({ kind: 'team',
                team: x.id })), { kind: 'random' }, ...[0.2, 0.4, 0.6, 0.8].map((ability) => ({
                kind: 'builtin', ability }))],
            defaults: { scenario: '5_vs_5' },
            stages: [{ format: 'league', name: 'League' }] });
        made = entry.id;
        await page.open(made);
        await until(() => page.current.state === 'done', 20000);
        page.renderView();
        const toggle = main().querySelector('[data-focus="results-toggle"]');
        // Another tournament opens with its Results closed, whatever the one before showed.
        all.switched = toggle.getAttribute('aria-expanded') === 'false';
        press(toggle);
        const box = await until(() => main().querySelector('.cup-matrix-scroll table')
            && main().querySelector('.cup-matrix-scroll'));
        await wait(100);
        box.scrollLeft = 80;
        const scrolled = box.scrollLeft;
        // A redraw of the view keeps the box where it was.
        page.renderView();
        await wait(0);
        all.kept = scrolled > 0 && main().querySelector('.cup-matrix-scroll').scrollLeft
            === scrolled;
        info.sizes = [box.scrollWidth, box.clientWidth, box.getBoundingClientRect().right,
            box.querySelectorAll('thead th').length];
        all.inside = box.scrollWidth > box.clientWidth
            && box.getBoundingClientRect().right <= 391;
        all.noScroll = document.documentElement.scrollWidth <= 390;
        // The names of the rows stay at the left edge of the box while it scrolls.
        const first = main().querySelector('.cup-matrix-scroll tbody th');
        all.sticky = Math.abs(first.getBoundingClientRect().left
            - main().querySelector('.cup-matrix-scroll').getBoundingClientRect().left) < 2;
    } finally {
        if (made) {
            await fetch(`/api/tournaments/${made}`, { method: 'DELETE' });
        }
        for (const team of Object.values(teams)) {
            await api.deleteTeam(team.id);
        }
        cuju.hud.toast = toast;
        window.confirm = confirm;
    }
    return Object.values(all).every(Boolean) || JSON.stringify({ ...all, ...info });
"""

CARDS = """
    const all = {};
    const shown = {};
    try {
        cuju.showPage('teams');
        const card = (name) => document.querySelector(
            `.teams-list > li[data-id="${teams[name].id}"]`);
        await until(() => card('Broken strict') && card('Steady strict'));
        const button = (name) => card(name).querySelector('.team-check-run');
        const status = (name) => card(name).querySelector('.team-check-status');
        all.label = button('Broken strict').getAttribute('aria-label')
            === 'Strict check of Broken strict';
        press(button('Broken strict'));
        all.busy = status('Broken strict').getAttribute('aria-busy') === 'true'
            && button('Broken strict').getAttribute('aria-disabled') === 'true'
            && text(button('Broken strict')) === 'Checking';
        await until(() => status('Broken strict').getAttribute('aria-busy') === 'false');
        all.failed = status('Broken strict').classList.contains('failed')
            && /^Failed under strict rules, Broken strict failed to load/.test(
                text(status('Broken strict')))
            && active() === button('Broken strict');
        press(button('Steady strict'));
        await until(() => status('Steady strict').classList.contains('passed'));
        const passed = text(status('Steady strict'));
        all.passed = /^Passed under strict rules, folder of [\\d.]+ MB/.test(passed)
            && /Left side passed, loaded in [\\d.]+ s, reset in [\\d.]+ s, 50 calls, /.test(passed)
            && /first call [\\d.]+ ms, mean call after the first [\\d.]+ ms, /.test(passed)
            && /Right side passed, loaded in /.test(passed)
            && passed.endsWith('Steady strict answered the action 5 in 95% of its actions.');
        shown.passed = passed;
        all.unplayed = text(status('Broken strict')).includes(
            'Right side left unplayed after the left side failed');
        // A team whose answers differ on a replay passes with the warning of it.
        press(button('Wobbly strict'));
        await until(() => status('Wobbly strict').classList.contains('passed'));
        all.wobbly = text(status('Wobbly strict')).endsWith('Wobbly strict answered differently '
            + 'when the same steps played again from the same seed.');
        // The check leaves the team's editor closed.
        all.closed = cuju.page === 'teams' && !card('Steady strict').classList.contains(
            'selected');
    } finally {
        for (const team of Object.values(teams)) {
            await api.deleteTeam(team.id);
        }
        cuju.showPage('tournaments');
        cuju.hud.toast = toast;
        window.confirm = confirm;
    }
    return Object.values(all).every(Boolean) || JSON.stringify({ ...all, ...shown });
"""


def strict_checks(client):
    """Checks a strict tournament with its exclusion, forfeits, results and legs, and team cards."""
    checks = _run(client, TOURNAMENT, 'A strict tournament and its results')
    client.call(
        'Emulation.setDeviceMetricsOverride',
        {'width': 390, 'height': 844, 'deviceScaleFactor': 1, 'mobile': True},
    )
    try:
        checks += _run(client, PHONE, 'The matrix of a strict tournament at the width of a phone')
    finally:
        client.call('Emulation.clearDeviceMetricsOverride')
    checks += _run(client, CARDS, 'The strict check of a team card')
    return checks


def main():
    import page_check as page

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--port', type=int, default=8790)
    parser.add_argument('--debug-port', type=int, default=8791)
    parser.add_argument('--chrome', default='google-chrome')
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    processes = []
    client = None
    checks = 0
    try:
        with tempfile.TemporaryDirectory(
            prefix='cuju-page-strict-', ignore_cleanup_errors=True
        ) as profile:
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(root / 'ci/mock_server.py'),
                        '--port',
                        str(options.port),
                        '--short',
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            page.wait_json(f'http://127.0.0.1:{options.port}/api/scenarios')
            processes.append(
                subprocess.Popen(
                    [
                        options.chrome,
                        '--headless=new',
                        '--mute-audio',
                        # The checks read the English page, whatever the language of the machine.
                        '--lang=en-US',
                        '--no-sandbox',
                        '--disable-background-networking',
                        '--proxy-server=http://127.0.0.1:9',
                        '--proxy-bypass-list=127.0.0.1',
                        '--no-first-run',
                        f'--remote-debugging-port={options.debug_port}',
                        f'--user-data-dir={profile}',
                        '--window-size=800,600',
                        'about:blank',
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env={**os.environ, 'XDG_CONFIG_HOME': profile, 'XDG_DATA_HOME': profile},
                )
            )
            debug = page.debugging_port(profile, options.debug_port)
            targets = page.wait_json(f'http://127.0.0.1:{debug}/json')
            target = next(item for item in targets if item['type'] == 'page')
            client = page.CDP(target['webSocketDebuggerUrl'])
            client.call('Runtime.enable')
            client.call('Page.enable')
            client.call(
                'Page.addScriptToEvaluateOnNewDocument',
                {
                    'source': """
                localStorage.setItem('cuju.muted', 'true');
                localStorage.setItem('cuju.quality', '"low"');
                localStorage.setItem('cuju.tips', '{"off": true}');
                if (localStorage.getItem('cuju.installOffer') === null) {
                    localStorage.setItem('cuju.installOffer', '{"dismissed": true}');
                }
                Element.prototype.requestPointerLock = function () {
                    throw new Error('Pointer capture refused by the page check.');
                };
            """
                },
            )
            client.call('Page.navigate', {'url': f'http://127.0.0.1:{options.port}/'})
            for _ in range(150):
                if client.evaluate('!!(window.cuju && window.cuju.menus)'):
                    break
                time.sleep(0.2)
            checks = strict_checks(client)
            # The other checks of the Tournaments page, so a change here shows its effect there.
            checks += page.tournament_checks(client)
            checks += page.tournament_play_checks(client, debug, options.port)
            checks += page_tournaments.wizard_checks(client)
            checks += page_tournaments.phone_checks(client)
            checks += page_tournaments.view_checks(client)
            assert client.evaluate("localStorage.getItem('cuju.muted')") == 'true'
            assert not client.evaluate('!!document.pointerLockElement')
            assert not client.errors, client.errors
            print(f'PASS. {checks} strict tournament and tournament checks. Chrome stayed muted.')
    except Exception as error:
        print(f'FAIL. {checks} checks passed. {error}', file=sys.stderr)
        return 1
    finally:
        if client:
            client.socket.close()
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    return 0


if __name__ == '__main__':
    sys.exit(main())
