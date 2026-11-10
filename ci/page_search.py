# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the search of moments and of the captions, for ci/page_check.py.

The checks open the panel of moments on the Recordings page, search the mock's recordings, open a
result in Watch, find moments from the command palette, and turn the captions on to read a cue
on the view and in the live region and to save them as WebVTT. Each check leaves the settings as
it found them, the captions off.
"""

import json

UNTIL = """
    const until = async (test, ms = 10000) => {
        const end = performance.now() + ms;
        while (performance.now() < end) {
            const value = test();
            if (value) {
                return value;
            }
            await new Promise((resolve) => setTimeout(resolve, 100));
        }
        return test();
    };
"""


def press(client, key, code, modifiers=0):
    for kind in ('keyDown', 'keyUp'):
        client.call(
            'Input.dispatchKeyEvent',
            {'type': kind, 'key': key, 'code': code, 'modifiers': modifiers},
        )


def check_search(client):
    """Checks the panel of moments, a result that opens Watch and the palette's moments."""
    result = client.evaluate(
        '(async () => {'
        + UNTIL
        + """
        cuju.showPage('recordings');
        await cuju.recordings.refresh();
        const toggle = document.getElementById('moments-toggle');
        const closed = document.getElementById('moments-panel').hidden;
        toggle.click();
        const panel = document.getElementById('moments-panel');
        const input = document.getElementById('moments-query');
        const opened = !panel.hidden && document.activeElement === input
            && toggle.getAttribute('aria-expanded') === 'true';
        const want = await (await fetch('/api/search?q=goal&limit=200')).json();
        input.value = 'goal';
        input.dispatchEvent(new Event('input'));
        const rows = await until(() => {
            const list = document.querySelectorAll('#moments-results .moment-row');
            return list.length === want.results.length && list.length ? list : null;
        }, 30000);
        const texts = rows
            ? [...rows].map((row) => row.querySelector('.moment-text').textContent) : [];
        const same = texts.join('|') === want.results.map((r) => r.text).join('|');
        const status = document.querySelector('.moments-status').textContent;
        input.value = 'goal zz:1';
        input.dispatchEvent(new Event('input'));
        const status2 = () => document.querySelector('.moments-status').textContent;
        const refused = await until(() => /expected a filter/.test(status2()));
        input.value = 'goal';
        input.dispatchEvent(new Event('input'));
        const count = () => document.querySelectorAll('#moments-results .moment-row').length;
        await until(() => count() === want.results.length);
        input.focus();
        const counted = status.startsWith(`${want.total} moment`);
        const state = {
            status: document.querySelector('.moments-status').textContent,
            panels: document.querySelectorAll('#moments-panel').length,
            text: cuju.moments.text, query: cuju.moments.query(), open: cuju.moments.open,
            error: cuju.moments.error, total: cuju.moments.results && cuju.moments.results.total,
            recordings: want.recordings, wanted: want.total,
        };
        return { closed, opened, found: want.total > 0, same, counted,
                 refused, first: want.results[0], state };
    })()
    """
    )
    first = result.pop('first')
    state = result.pop('state')
    assert all(result.values()), f'The panel of moments searches the library {result} {state}'
    press(client, 'ArrowDown', 'ArrowDown')
    focused = client.evaluate(
        "document.activeElement && document.activeElement.classList.contains('moment-row')"
    )
    assert focused, 'ArrowDown moves from the query to the first moment'
    press(client, 'Enter', 'Enter')
    result = client.evaluate(
        '(async () => {'
        + UNTIL
        + f"""
        const want = {json.dumps(first)};
        const open = await until(() => cuju.page === 'watch' && cuju.source
            && cuju.source.id === want.match
            && cuju.timeline && cuju.timeline.store.size > 0);
        // The source opens before the view seeks, so the check waits for the seek.
        const at = () => (cuju.timeline ? cuju.timeline.t / cuju.timeline.sps : -1);
        await until(() => Math.abs(at() - want.seek) < 2.5, 5000);
        const t = at();
        cuju.timeline && cuju.timeline.pause();
        return {{ open: !!open, near: Math.abs(t - want.seek) < 2.5, before: t <= want.t + 0.5,
                  t, seek: want.seek }};
    }})()
    """
    )
    shown = {key: result[key] for key in ('open', 'near', 'before')}
    assert all(shown.values()), f'A moment opens Watch a few seconds before it {result}'
    result = client.evaluate(
        '(async () => {'
        + UNTIL
        + """
        document.getElementById('open-settings').focus();
        cuju.palette.open('goal');
        const moments = () => cuju.palette.shown.filter((a) => a.group === 'Moments');
        const search = moments().some((a) => a.title === 'Search moments, goal');
        const found = await until(() => moments().length > 1);
        cuju.palette.input.value = 'go teams';
        cuju.palette.render();
        const quiet = !cuju.palette.shown.some((a) => a.group === 'Moments');
        cuju.palette.close(true);
        return { search, found: !!found, quiet };
    })()
    """
    )
    assert all(result.values()), f'The palette finds moments {result}'
    return 3


def check_captions(client):
    """Checks the captions of Watch, their live region, their size, their place and the file."""
    result = client.evaluate(
        '(async () => {'
        + UNTIL
        + """
        const check = document.getElementById('captions-on');
        const size = document.getElementById('captions-size');
        const off = check && !check.checked && localStorage.getItem('cuju.captions') !== 'true';
        cuju.showPage('watch');
        check.click();
        // The page reads the cues a few hundred steps a drawing, slowly where it draws seldom.
        const cues = await until(() => {
            const list = cuju.captions.cues();
            return list.length ? list : null;
        }, 60000);
        if (!cues) {
            return { cues: false };
        }
        const tl = cuju.timeline;
        // A cue with room before it, so the seek lands before its start and play crosses it.
        const cue = cues.find((c) => c.start - 0.6 > tl.first / tl.sps + 0.2) || cues[0];
        cuju.director.stop(false);
        tl.seek(Math.max(tl.first, (cue.start - 0.6) * tl.sps));
        cuju.afterSeek();
        // A quarter of the speed, so a page that draws seldom still draws the cue.
        tl.play(0.25);
        const shown = await until(() => {
            const box = document.getElementById('captions');
            return box && !box.hidden && box.textContent.includes(cue.text);
        }, 60000);
        const lines = [...document.getElementById('captions-live').children];
        const spoken = lines.some((p) => p.textContent === cue.text);
        tl.pause();
        const box = document.getElementById('captions').getBoundingClientRect();
        const view = document.getElementById('stage').getBoundingClientRect();
        const controls = document.getElementById('controls').getBoundingClientRect();
        const app = document.getElementById('app');
        const inside = box.left >= view.left && box.right <= view.right && box.top >= view.top
            && (app.classList.contains('idle') || box.bottom <= controls.top + 1);
        size.value = 'large';
        size.dispatchEvent(new Event('change', { bubbles: true }));
        const large = document.getElementById('captions').dataset.size === 'large';
        const vtt = cuju.captions.download({ save: false });
        const file = typeof vtt === 'string' && vtt.startsWith('WEBVTT\\n\\n1\\n')
            && vtt.includes(cue.text);
        size.value = 'medium';
        size.dispatchEvent(new Event('change', { bubbles: true }));
        check.click();
        const stored = localStorage.getItem('cuju.captions');
        const hidden = document.getElementById('captions').hidden && stored === 'false';
        localStorage.removeItem('cuju.captions');
        localStorage.removeItem('cuju.captionSize');
        return { off, cues: true, shown: !!shown, spoken, inside, large, file, hidden };
    })()
    """
    )
    assert all(result.values()), f'The captions of Watch {result}'
    return 1
