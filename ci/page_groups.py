# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the groups of challenge runs on the Recordings page, for ci/page_check.py.

The mock server's library holds one run of One on one, three attempts in one group. The check
finds its row, a disclosure button that names the run, opens and closes it by mouse and by
keyboard, and moves the whole group to the Trash and back in one step each. It leaves the library
as it found it, with the group closed.
"""

UNTIL = """
    const until = async (test, ms = 10000) => {
        const end = performance.now() + ms;
        while (performance.now() < end) {
            const value = test();
            if (value) {
                return value;
            }
            await new Promise((resolve) => setTimeout(resolve, 50));
        }
        return test();
    };
    const settled = async (test, ms = 10000) => {
        const end = performance.now() + ms;
        while (performance.now() < end) {
            if (await test()) {
                return true;
            }
            await new Promise((resolve) => setTimeout(resolve, 50));
        }
        return !!(await test());
    };
"""


def press(client, key, code):
    for kind in ('keyDown', 'keyUp'):
        client.call('Input.dispatchKeyEvent', {'type': kind, 'key': key, 'code': code})


def _state(client):
    """Returns whether the group shows open, its rows and where the focus is."""
    return client.evaluate("""
        (() => {
            const row = document.querySelector('#page-recordings tr.group-row');
            const button = row && row.querySelector('.group-toggle');
            const ids = button ? button.getAttribute('aria-controls').split(' ') : [];
            const members = ids.map((id) => document.getElementById(id));
            return {
                expanded: button ? button.getAttribute('aria-expanded') : null,
                shown: members.filter((tr) => tr && !tr.hidden).length,
                count: members.filter(Boolean).length,
                focus: document.activeElement === row ? 'row'
                    : document.activeElement === button ? 'button' : 'elsewhere',
            };
        })()
    """)


def check_groups(client):
    """Checks a group's row, its opening and closing, and its deletion and restoring."""
    result = client.evaluate(
        '(async () => {'
        + UNTIL
        + """
        const { serverText } = await import('./js/core/i18n.js');
        cuju.showPage('recordings');
        const page = cuju.recordings;
        page.trash = false;
        page.query = '';
        page.folder = '';
        page.open.clear();
        page.render();
        await page.refresh();
        const row = await until(() => document.querySelector('#page-recordings tr.group-row'));
        if (!row) {
            return { row: false };
        }
        const button = row.querySelector('.group-toggle');
        const group = page.list.find((m) => m.group && m.group.id === row.dataset.group).group;
        const members = page.list.filter((m) => m.group && m.group.id === group.id);
        const title = serverText(group, 'title');
        const result = serverText(group, 'result');
        const named = button.tagName === 'BUTTON' && button.textContent.includes(title)
            && button.getAttribute('aria-label').startsWith(title)
            && button.getAttribute('aria-label').includes(result)
            && row.textContent.includes(result) && members.length === 3;
        const controls = button.getAttribute('aria-controls')
            === members.sort((a, b) => a.group.attempt - b.group.attempt)
                .map((m) => `recording-row-${m.id}`).join(' ');
        const closed = button.getAttribute('aria-expanded') === 'false'
            && members.every((m) => document.getElementById(`recording-row-${m.id}`).hidden);
        // A click focuses the button, as a pointer's click does, and the focus stays on it.
        button.focus();
        button.click();
        const again = document.querySelector('#page-recordings tr.group-row .group-toggle');
        const opened = again.getAttribute('aria-expanded') === 'true'
            && members.every((m) => !document.getElementById(`recording-row-${m.id}`).hidden)
            && document.activeElement === again;
        again.focus();
        again.click();
        const shut = document.querySelector('#page-recordings tr.group-row .group-toggle')
            .getAttribute('aria-expanded') === 'false';
        document.querySelector('#page-recordings tr.group-row').focus();
        return { row: true, named, controls, closed, opened, shut };
    })()
    """
    )
    assert result and all(result.values()), f'A group of a challenge run {result}'
    # The keyboard opens a focused group with the right arrow and Enter, and closes it with the
    # left arrow and Enter, and the left arrow on an attempt goes back to its group.
    press(client, 'ArrowRight', 'ArrowRight')
    opened = _state(client)
    press(client, 'ArrowDown', 'ArrowDown')
    down = client.evaluate("document.activeElement.classList.contains('group-member')")
    press(client, 'ArrowLeft', 'ArrowLeft')
    back = _state(client)
    press(client, 'ArrowLeft', 'ArrowLeft')
    closed = _state(client)
    press(client, 'Enter', 'Enter')
    entered = _state(client)
    press(client, 'Enter', 'Enter')
    left = _state(client)
    keys = {
        'opened': opened == {'expanded': 'true', 'shown': 3, 'count': 3, 'focus': 'row'},
        'down': down,
        'back': back['focus'] == 'row' and back['expanded'] == 'true',
        'closed': closed == {'expanded': 'false', 'shown': 0, 'count': 3, 'focus': 'row'},
        'entered': entered['expanded'] == 'true' and entered['focus'] == 'row',
        'left': left['expanded'] == 'false' and left['focus'] == 'row',
    }
    assert all(keys.values()), f'The keyboard opens and closes a group {keys} {opened} {closed}'
    # Delete on the group's row moves all its recordings to the Trash in one request, and the
    # Trash view restores the group in one step.
    client.evaluate("""
        window.__groupRequests = [];
        window.__fetch = window.fetch;
        window.fetch = (url, init) => {
            window.__groupRequests.push(`${(init && init.method) || 'GET'} ${url}`);
            return window.__fetch(url, init);
        };
    """)
    press(client, 'Delete', 'Delete')
    result = client.evaluate(
        '(async () => {'
        + UNTIL
        + """
        const { api } = await import('./js/core/api.js');
        const page = cuju.recordings;
        const id = await until(() => {
            const requests = window.__groupRequests.filter((r) => r.startsWith('DELETE'));
            return requests.length ? requests : null;
        });
        const one = !!id && id.length === 1 && id[0].startsWith('DELETE /api/groups/');
        const group = one ? decodeURIComponent(id[0].split('/').pop()) : '';
        const mine = (list) => list.filter((m) => m.group && m.group.id === group);
        const gone = await settled(async () => mine(await api.matches()).length === 0);
        const trashed = mine(await api.trash());
        page.trash = true;
        await page.refresh();
        const row = document.querySelector('#page-recordings tr.group-row');
        row.click();
        await page.restoreSelected();
        const restored = await settled(async () => mine(await api.trash()).length === 0);
        window.fetch = window.__fetch;
        const asked = window.__groupRequests.some((r) => r.startsWith('POST /api/groups/'));
        page.trash = false;
        page.selected.clear();
        await page.refresh();
        const back = mine(page.list).length === 3;
        return { one, gone, trashed: trashed.length === 3, restored, asked, back };
    })()
    """
    )
    assert result and all(result.values()), f'A group moves to the Trash and back {result}'
    return 3
