# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks the Help page's tour, lessons, samples, diagnostic report, installable page and offer.

ci/page_check.py runs help_checks with the other checks of the page. Run alone, this file
starts the mock server and Chrome itself and runs only these checks.

Usage:
    python ci/page_help.py [--port 8790] [--debug-port 8791] [--chrome google-chrome]
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WAIT = """
    const wait = async (test, tries = 200) => {
        for (let i = 0; i < tries; i++) {
            let value = null;
            try {
                value = await test();
            } catch {
                value = null;
            }
            if (value) {
                return value;
            }
            await new Promise((resolve) => setTimeout(resolve, 50));
        }
        return null;
    };
"""


def _run(client, body, name):
    result = client.evaluate(f'(async () => {{ {WAIT} {body} }})()')
    assert result is True, f'{name} {result}'
    return 1


def parts_checks(client):
    """Checks that the parts of Help load and each script object exists."""
    return _run(
        client,
        """
        await wait(() => cuju.helpCenter && cuju.tutorial && cuju.doctor && cuju.install);
        cuju.showPage('help');
        const ids = ['help-learn-title', 'help-lessons', 'help-samples-title', 'help-doctor-title',
            'help-install-title'];
        const all = {
            parts: ids.every((id) => !!document.getElementById(id)),
            scripts: ['tour', 'tutorial', 'samples', 'doctor',
                'install'].every((key) => !!cuju[key]),
            manifest: document.querySelector('link[rel="manifest"]')?.getAttribute('href')
                === 'manifest.webmanifest',
            lessons: !!(await wait(
                () => document.querySelectorAll('.lesson-list li').length === 8)),
            topics: (await import('./js/help/palette.js')).HELP_TOPICS
                .some((t) => t[0] === 'help-doctor-title'),
        };
        return Object.values(all).every(Boolean) || JSON.stringify(all);
        """,
        'The parts of Help',
    )


def sample_checks(client):
    """Checks the samples, their states, adding, the Trash and restoring from Help."""
    return _run(
        client,
        """
        cuju.showPage('help');
        const first = await cuju.samples.list();
        const kinds = first.map((entry) => entry.kind).join(' ');
        const added = await cuju.samples.add(['sample-5v5']);
        const held = added.samples.find((entry) => entry.id === 'sample-5v5').state === 'library';
        await fetch('/api/matches/sample-5v5', { method: 'DELETE' });
        await cuju.helpCenter.refreshSamples();
        const item = document.querySelector('[data-sample="sample-5v5"]');
        const trashed = item.textContent.includes('In the Trash');
        item.querySelector('button').click();
        const restored = await wait(() => document.querySelector('[data-sample="sample-5v5"]')
            .textContent.includes('In the library'));
        const note = document.querySelector('#help-samples [aria-live]').textContent;
        const team = await cuju.samples.add(['starter-team']);
        const teams = await (await fetch('/api/teams')).json();
        const registered = teams.some((entry) => entry.name === 'Starter team')
            && team.samples.find((entry) => entry.id === 'starter-team').state === 'library';
        const again = await cuju.samples.add(['starter-team']);
        const all = {
            kinds: kinds === 'recording recording team', held, trashed, restored: !!restored,
            note: note.startsWith('Restored'), registered, once: again.changes.length === 0,
        };
        return Object.values(all).every(Boolean) || JSON.stringify(all);
        """,
        'Samples on Help',
    )


def tour_checks(client):
    """Checks the guided tour, its focus, keys, ring, resume, offers and the ways to start it."""
    count = _run(
        client,
        """
        localStorage.removeItem('cuju.tour');
        cuju.showPage('help');
        document.querySelector('#help-learn .btn.primary').click();
        const opened = await wait(() => cuju.tour.state().open && cuju.tour.state().target);
        const card = document.getElementById('tour');
        const ring = document.getElementById('tour-ring');
        const home = document.getElementById('home-btn').getBoundingClientRect();
        const box = ring.getBoundingClientRect();
        const around = !ring.hidden && box.left <= home.left && box.right >= home.right
            && box.top <= home.top && box.bottom >= home.bottom;
        const first = {
            opened: !!opened, page: cuju.page === 'home',
                dialog: card.getAttribute('role') === 'dialog',
            focus: document.activeElement === document.getElementById('tour-title'),
            live: document.getElementById('tour-live').textContent.startsWith('Step 1 of 11'),
            around, back: card.querySelector('.tour-actions button').disabled,
        };
        return Object.values(first).every(Boolean) || JSON.stringify(first);
        """,
        'The tour opens on Home',
    )
    for kind in ('keyDown', 'keyUp'):
        client.call(
            'Input.dispatchKeyEvent', {'type': kind, 'key': 'ArrowRight', 'code': 'ArrowRight'}
        )
    count += _run(
        client,
        """
        const moved = await wait(() => cuju.tour.state().step === 1 && cuju.tour.state().target);
        const palette = document.getElementById('open-palette').getBoundingClientRect();
        const ring = document.getElementById('tour-ring').getBoundingClientRect();
        const all = { moved: !!moved, ring: ring.left <= palette.left
            && ring.right >= palette.right };
        return Object.values(all).every(Boolean) || JSON.stringify(all);
        """,
        'ArrowRight moves the tour',
    )
    client.evaluate("document.getElementById('tour-title').focus()")
    for kind in ('keyDown', 'keyUp'):
        client.call('Input.dispatchKeyEvent', {'type': kind, 'key': 'Escape', 'code': 'Escape'})
    count += _run(
        client,
        """
        const closed = await wait(() => !cuju.tour.state().open);
        const kept = JSON.parse(localStorage.getItem('cuju.tour'));
        cuju.showPage('help');
        const button = document.querySelector('#help-learn .btn.primary');
        await wait(() => button.textContent === 'Resume the tour at step 2');
        const resume = button.textContent === 'Resume the tour at step 2';
        // The steps that point at Play, Teams and Tournaments find their controls.
        const found = {};
        for (const index of [5, 6, 7, 8]) {
            await cuju.tour.start(index);
            found[index] = !!(await wait(() => cuju.tour.state().target));
        }
        const pages = cuju.page === 'tournaments';
        cuju.reducedMotion = true;
        await cuju.tour.start(9);
        const still = document.getElementById('tour').classList.contains('still');
        cuju.reducedMotion = false;
        await cuju.tour.next();
        await cuju.tour.next();
        const done = !cuju.tour.state().open && cuju.tour.state().done
            && cuju.tour.state().resumeAt === 0;
        const all = {
            closed: !!closed, kept: kept.step === 1 && kept.started, resume,
            found: Object.values(found).every(Boolean), pages, still, done,
        };
        return Object.values(all).every(Boolean) || JSON.stringify({ ...all, found });
        """,
        'The tour leaves, resumes and finds the controls of each page',
    )
    count += _run(
        client,
        """
        // The palette starts the tour, and so does the tip of the first run.
        cuju.palette.open('take the guided tour');
        cuju.palette.run(cuju.palette.active);
        const palette = !!(await wait(() => cuju.tour.state().open));
        cuju.tour.leave();
        const tip = [...cuju.firstRun.tip.querySelectorAll('button')].map((b) => b.textContent);
        cuju.firstRun.tip.querySelector('button + button').click();
        const fromTip = !!(await wait(() => cuju.tour.state().open));
        cuju.tour.leave();
        const all = { palette, tip: tip[0] === 'Got it' && tip[1] === 'Take the tour', fromTip };
        return Object.values(all).every(Boolean) || JSON.stringify(all);
        """,
        'The palette and the tip start the tour',
    )
    return count


def lesson_checks(client):
    """Checks lessons that the page detects, their progress, the server's copy and the reset.

    Each lesson runs in an evaluation of its own, so a slow machine stays inside the time that
    the connection to Chrome allows one evaluation.
    """
    done = 'await wait(() => cuju.tutorial.state().done.includes(LESSON), 200)'

    def until(lesson):
        return done.replace('LESSON', repr(lesson))

    steps = [
        (
            'The first lesson opens Watch and notices a recording',
            """
            await cuju.tutorial.reset();
            const count = cuju.tutorial.lessons().length === 8;
            cuju.showPage('help');
            document.querySelector('[data-lesson="open_sample"] button').click();
            const panel = document.getElementById('lesson-panel');
            const shown = !panel.hidden && cuju.page === 'watch'
                && document.activeElement === document.getElementById('lesson-title');
            await cuju.openMatch('sample-5v5');
            const opened = !!(OPEN);
            cuju.director.stop(true);
            return (count && shown && opened) || JSON.stringify({ count, shown, opened });
            """.replace('OPEN', until('open_sample')),
        ),
        (
            'A jump to a goal ends its lesson',
            """
            cuju.tutorial.start('seek_goal');
            cuju.act('restart');
            await new Promise((resolve) => setTimeout(resolve, 500));
            cuju.act('next-goal');
            return !!(SEEK) || JSON.stringify(cuju.tutorial.snapshot());
            """.replace('SEEK', until('seek_goal')),
        ),
        (
            'A camera and a followed player end their lessons',
            """
            // The lesson counts from a camera the viewer chose, whatever an earlier check left.
            cuju.director.stop(false);
            cuju.setCamera('broadcast');
            cuju.tutorial.start('switch_camera');
            await new Promise((resolve) => setTimeout(resolve, 500));
            cuju.setCamera('tactical');
            const camera = !!(CAMERA);
            cuju.tutorial.start('follow_player');
            cuju.cameras.followIndex = 0;
            cuju.setCamera('player');
            const followed = !!(FOLLOW);
            cuju.setCamera('broadcast');
            return (camera && followed) || JSON.stringify({ camera, followed });
            """.replace('CAMERA', until('switch_camera')).replace('FOLLOW', until('follow_player')),
        ),
        (
            'A photo and a team end their lessons',
            """
            cuju.tutorial.start('make_photo');
            await wait(() => cuju.photo);
            cuju.photo.open();
            await cuju.photo.capture({ width: 64, height: 36 });
            cuju.photo.close();
            const photo = !!(PHOTO);
            cuju.tutorial.start('register_team');
            const team = !!(TEAM);
            return (photo && team) || JSON.stringify({ photo, team });
            """.replace('PHOTO', until('make_photo')).replace('TEAM', until('register_team')),
        ),
        (
            'Lessons keep their progress, reach the server and reset',
            """
            const panel = document.getElementById('lesson-panel');
            const stored = JSON.parse(localStorage.getItem('cuju.lessons'));
            // A lesson counts as reported when the page reported it, or when the server already
            // knew it done, which Help takes in each time it shows. The reports travel on their
            // own, so the check asks again for a while.
            let unknown = [];
            const reportedNow = async () => {
                const server = await (await fetch('/api/help/tutorial')).json();
                const known = (id) => server.page.includes(id)
                    || (server.lessons || []).some((entry) => entry.id === id && entry.done);
                unknown = ['open_sample', 'seek_goal', 'switch_camera', 'follow_player',
                    'make_photo'].filter((id) => !known(id));
                return unknown.length === 0;
            };
            let reported = await reportedNow();
            for (let i = 0; i < 50 && !reported; i++) {
                await new Promise((resolve) => setTimeout(resolve, 200));
                reported = await reportedNow();
            }
            const status = document.querySelector('#lesson-panel .lesson-status').textContent;
            panel.querySelector('h2').focus();
            panel.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            const closed = panel.hidden;
            cuju.showPage('help');
            // Help takes in what the server knows as it shows, then counts the lessons again.
            await new Promise((resolve) => setTimeout(resolve, 800));
            const counted = cuju.tutorial.state();
            const summary = counted.done.length >= 6
                && document.querySelector('#help-learn [aria-live]').textContent
                    .startsWith(`${counted.done.length} of ${counted.count}`);
            await cuju.tutorial.reset();
            const cleared = cuju.tutorial.state().done.length === 0
                && (await (await fetch('/api/help/tutorial')).json()).page.length === 0;
            const all = {
                stored: 'make_photo' in stored.done, reported, praised: status.startsWith('Done'),
                closed, summary, cleared,
            };
            return Object.values(all).every(Boolean) || JSON.stringify({ ...all, unknown });
            """,
        ),
    ]
    return sum(_run(client, body, name) for name, body in steps)


def doctor_checks(client):
    """Checks the diagnostic report, its parts, its text, Copy, Save and the script."""
    return _run(
        client,
        """
        cuju.showPage('help');
        const host = document.getElementById('help-doctor');
        host.querySelector('.btn.primary').click();
        const area = document.getElementById('doctor-text');
        const filled = await wait(() => !area.hidden
            && area.value.includes('Recent warnings and errors'));
        const text = area.value;
        const clicked = [];
        const click = HTMLAnchorElement.prototype.click;
        HTMLAnchorElement.prototype.click = function () { clicked.push(this.download); };
        try {
            await cuju.doctor.save();
        } finally {
            HTMLAnchorElement.prototype.click = click;
        }
        const copied = await cuju.doctor.copy();
        const report = await cuju.doctor.gather();
        const buttons = [...host.querySelectorAll('button')];
        const all = {
            filled: !!filled,
            parts: ['Browser', 'WebGL 2', 'WebGPU', 'Decoding', 'Sound', 'Home folder', 'Checks']
                .every((word) => text.includes(word)),
            muted: text.includes('muted: yes'), server: report.server
                && report.server.kind === 'server',
            saved: clicked.length === 1
                && /^cuju-report-\\d{4}-\\d{2}-\\d{2}\\.txt$/.test(clicked[0]),
            copy: typeof copied === 'boolean', keys: buttons.every((b) => b.tabIndex === 0
                && !b.disabled),
            status: host.querySelector('[role="status"]').textContent.length > 0,
        };
        return Object.values(all).every(Boolean) || JSON.stringify(all);
        """,
        'The diagnostic report',
    )


def pwa_checks(client, port):
    """Checks the worker of the installable page, its cache and its update to a new build."""
    count = _run(
        client,
        """
        const state = await cuju.install.ready();
        await wait(() => navigator.serviceWorker.controller, 200);
        const build = cuju.install.state().build;
        const name = `cuju-page-${build}`;
        await wait(async () => (await caches.keys()).includes(name), 200);
        await fetch('/api/matches');
        await fetch('js/broadcast/hud.js');
        const cache = await caches.open(name);
        const urls = (await cache.keys()).map((request) => new URL(request.url).pathname);
        const manifest = await fetch('manifest.webmanifest');
        const parsed = await manifest.json();
        const all = {
            registered: state.registered && state.supported,
                controlled: !!navigator.serviceWorker.controller,
            build: cuju.install.state().controllerBuild === build,
                shell: urls.includes('/js/main.js'),
            lazy: urls.includes('/js/broadcast/hud.js') || urls.includes('/js/main.js'),
            api: !urls.some((path) => path.startsWith('/api/')),
            manifest: manifest.headers.get('Content-Type') === 'application/manifest+json'
                && parsed.icons.length === 3,
        };
        return Object.values(all).every(Boolean) || JSON.stringify({ ...all, urls });
        """,
        'The worker keeps the static files alone',
    )
    count += _run(
        client,
        """
        const before = cuju.install.state().build;
        await fetch('/api/help/mock-build', { method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ build: 'next' }) });
        cuju.showPage('home');
        cuju.showPage('help');
        const ready = await wait(() => cuju.install.state().updateReady);
        const button = [...document.querySelectorAll('#help-install button')]
            .find((b) => b.textContent === 'Update');
        const offered = !!button && !button.hidden;
        await cuju.install.update();
        const moved = await wait(() => cuju.install.state().controllerBuild === 'next', 200);
        const gone = await wait(
            async () => !(await caches.keys()).includes(`cuju-page-${before}`), 200);
        window.helpBuild = before;
        const all = { ready: !!ready, offered, moved: !!moved, gone: !!gone };
        return Object.values(all).every(Boolean) || JSON.stringify(all);
        """,
        'A new build replaces the worker',
    )
    count += _run(
        client,
        """
        const before = window.helpBuild;
        await fetch('/api/help/mock-build', { method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ build: '' }) });
        await cuju.install.update();
        const back = await wait(() => cuju.install.state().controllerBuild === before, 200);
        return !!back || JSON.stringify(cuju.install.state());
        """,
        'The build of the server takes the worker back',
    )
    return count


# A synthetic offer of the browser to install the page, which counts the asks in window.asked.
OFFER = """
    const offer = (outcome) => {
        const event = new Event('beforeinstallprompt', { cancelable: true });
        event.prompt = async () => { window.asked = (window.asked || 0) + 1; };
        event.userChoice = Promise.resolve({ outcome, platform: 'web' });
        window.dispatchEvent(event);
        return event;
    };
    const card = () => document.getElementById('install-offer');
    const seen = () => card() && !card().hidden && card().getClientRects().length > 0;
"""


def _reload(client, port):
    """Loads the page again and waits for its offer to install."""
    client.evaluate('window.__before = true')
    client.call('Page.navigate', {'url': f'http://127.0.0.1:{port}/'})
    ready = 'cuju.menus && cuju.installOffer && cuju.install && cuju.tour'
    for _ in range(150):
        if client.evaluate(f'!window.__before && !!(window.cuju && {ready})'):
            return
        time.sleep(0.2)
    raise RuntimeError('The page did not load again.')


def offer_checks(client, port):
    """Checks the offer to install on Home, its Install, its Not now and that it stays away."""
    # The checks start the offer from a later visit, with nothing dismissed.
    client.evaluate("localStorage.setItem('cuju.installOffer', '{\"visits\": 3}')")
    _reload(client, port)
    count = _run(
        client,
        OFFER
        + """
        cuju.tour.leave?.();
        cuju.showPage('home');
        const event = offer('accepted');
        const shown = !!(await wait(seen));
        const install = card().querySelector('button.primary');
        install.focus();
        const help = [...document.querySelectorAll('#help-install button')]
            .find((b) => b.textContent === 'Install the app');
        const all = {
            prevented: event.defaultPrevented,
            shown,
            title: document.getElementById('install-offer-title').textContent
                === 'Install cuju as an app',
            focus: document.activeElement === install,
            help: !!help && !help.hidden,
            command: document.getElementById('help-install-command').textContent
                .includes('cuju render app --install'),
            state: cuju.installOffer.state().prompt && cuju.install.state().installable,
        };
        install.click();
        all.asked = !!(await wait(() => window.asked === 1));
        all.gone = !!(await wait(() => !seen()));
        all.kept = !JSON.parse(localStorage.getItem('cuju.installOffer')).dismissed;
        all.spent = !cuju.install.state().installable;
        return Object.values(all).every(Boolean) || JSON.stringify(all);
        """,
        'The offer to install shows on Home and asks the browser',
    )
    count += _run(
        client,
        OFFER
        + """
        offer('dismissed');
        const shown = !!(await wait(seen));
        const later = [...card().querySelectorAll('button')]
            .find((b) => b.textContent === 'Not now');
        later.focus();
        later.click();
        const all = {
            shown,
            gone: !!(await wait(() => !seen())),
            stored: JSON.parse(localStorage.getItem('cuju.installOffer')).dismissed === true,
            focus: card().hidden && !card().contains(document.activeElement),
        };
        offer('accepted');
        await new Promise((resolve) => setTimeout(resolve, 1500));
        all.away = !seen();
        all.help = cuju.install.state().installable;
        return Object.values(all).every(Boolean) || JSON.stringify(all);
        """,
        'Not now keeps the offer away',
    )
    _reload(client, port)
    count += _run(
        client,
        OFFER
        + """
        cuju.showPage('home');
        offer('accepted');
        await new Promise((resolve) => setTimeout(resolve, 1500));
        const state = cuju.installOffer.state();
        const all = { away: !seen(), visits: state.visits >= 4, dismissed: state.dismissed,
            prompt: state.prompt };
        return Object.values(all).every(Boolean) || JSON.stringify(all);
        """,
        'A dismissed offer stays away on the next visit',
    )
    return count


def help_checks(client, port):
    """Runs every check of the Help page's parts, and returns how many passed."""
    checks = parts_checks(client)
    checks += sample_checks(client)
    checks += tour_checks(client)
    checks += lesson_checks(client)
    checks += doctor_checks(client)
    checks += pwa_checks(client, port)
    checks += offer_checks(client, port)
    assert client.evaluate("localStorage.getItem('cuju.muted')") == 'true'
    assert not client.evaluate('!!document.pointerLockElement')
    return checks


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
            prefix='cuju-page-help-', ignore_cleanup_errors=True
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
                // The offer to install the page stays away unless a check asks for it.
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
            checks = help_checks(client, options.port)
            assert not client.errors, client.errors
            print(f'PASS. {checks} Help checks.')
    except Exception as error:
        detail = json.dumps(client.errors)[:2000] if client else ''
        print(f'FAIL. {checks} checks passed. {error} {detail}', file=sys.stderr)
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
