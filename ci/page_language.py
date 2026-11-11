# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the languages of the page, for ci/page_check.py.

The checks read the text of every page in English, with no message missing after the other
checks visited the page, then import the Portuguese draft of translations/pt.json, which the page
then chooses and reloads in, and read every page again, changed and with no message missing.
They import a malformed file, which the server refuses with a message in Portuguese, and a well
formed one, which joins the list and shows its own texts, and then follow the browser back to
English, where every page reads as before. The imported languages are removed at the end.
"""

import json
import time
from pathlib import Path

DRAFT = Path(__file__).resolve().parents[1] / 'translations' / 'pt.json'

PAGES = ['home', 'watch', 'play', 'recordings', 'matches', 'tournaments', 'teams', 'field', 'help']
# The headings of the Help page, which stay as they are while its lessons are done.
HEADINGS = (
    "[...document.querySelectorAll('#page-help h2, #page-help h3')].map((x) => x.textContent)"
)
PORTUGUESE_TABS = [
    'Assistir',
    'Jogar',
    'Gravações',
    'Partidas',
    'Torneios',
    'Times',
    'Campo',
    'Ajuda',
]


def _wait(client, expression, seconds=60):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            if client.evaluate(expression):
                return True
        except RuntimeError:
            # The page reloads, and its context goes away for a moment.
            pass
        time.sleep(0.2)
    raise AssertionError(f'timed out waiting for {expression}')


def _missing(client):
    return client.evaluate("import('./js/core/i18n.js').then((m) => m.missing())")


def _texts(client):
    """Returns the text of each page, of the bar and of the Settings panel, by name."""
    texts = {}
    for page in PAGES:
        texts[page] = client.evaluate(f"""
            (async () => {{
                cuju.showPage('{page}');
                const node = document.getElementById('page-{page}');
                const end = performance.now() + 10000;
                while (performance.now() < end && node.innerText.trim().length < 20) {{
                    await new Promise((resolve) => setTimeout(resolve, 100));
                }}
                await new Promise((resolve) => setTimeout(resolve, 300));
                return node.innerText;
            }})()
        """)
    texts['bar'] = client.evaluate("document.getElementById('topbar').innerText")
    # The menus of the team presentations list the registered teams, which load in their own time,
    # so the text of the panel leaves their entries out.
    texts['settings'] = client.evaluate("""
        (() => {
            const panel = document.getElementById('settings').cloneNode(true);
            panel.querySelectorAll('[id^="presentation-"] option').forEach((option) => {
                if (option.value) option.remove();
            });
            return panel.textContent;
        })()
    """)
    return texts


def _reloaded(client, locale):
    _wait(
        client,
        f"document.documentElement.lang === '{locale}' && !!(window.cuju && window.cuju.menus) "
        '&& !!window.cuju.language && document.readyState === "complete"',
    )


def check_languages(client):
    """Switches the page to Portuguese and back, and returns how many checks passed."""
    checks = 0
    # The other checks visited every page in English, and no message was missing.
    assert _missing(client) == [], _missing(client)
    checks += 1
    english = _texts(client)
    client.evaluate("cuju.showPage('help'); true")
    english_headings = client.evaluate(HEADINGS)
    assert client.evaluate('document.documentElement.lang') == 'en-US'
    assert _missing(client) == [], _missing(client)
    checks += 1
    # English ships alone, so the Language list waits out of sight until another one exists.
    listed = client.evaluate('cuju.language.refresh().then((list) => list.map((l) => l.code))')
    assert listed == ['en'], listed
    assert client.evaluate("document.getElementById('language-row').hidden") is True, 'shown'
    checks += 1

    draft = json.dumps(DRAFT.read_text(encoding='utf-8'))
    client.evaluate(f'cuju.language.importText({draft}).catch(() => {{}}); true')
    _reloaded(client, 'pt-BR')
    # The list shows once the page has listed the languages again, with the draft among them.
    assert _wait(client, "!document.getElementById('language-row').hidden"), 'the list stays hidden'
    assert client.evaluate("localStorage.getItem('cuju.language')") == '"pt"'
    assert client.evaluate("localStorage.getItem('cuju.muted')") == 'true'
    portuguese = _texts(client)
    for name, text in english.items():
        assert portuguese[name] != text, name
        checks += 1
    tabs = client.evaluate(
        "[...document.querySelectorAll('#topbar .menu [data-page]')]"
        '.map((b) => b.textContent.trim())'
    )
    assert tabs == PORTUGUESE_TABS, tabs
    assert 'Idioma' in portuguese['settings'] and 'Português (Brasil)' in client.evaluate(
        "document.getElementById('language').selectedOptions[0].textContent"
    )
    assert _missing(client) == [], _missing(client)
    checks += 2

    # A malformed file is refused, and the reason reads in Portuguese.
    refused = client.evaluate("""
        (async () => {
            const file = { '@language': { code: 'pt-x-check', name: 'Check',
                plurals: ['one', 'many', 'other'] },
                'api.status': 'Resposta {code}' };
            try {
                await cuju.language.importText(JSON.stringify(file));
                return null;
            } catch (err) {
                return document.getElementById('language-status').textContent;
            }
        })()
    """)
    assert refused and refused.startswith(
        'O arquivo de idioma foi recusado. há mensagens mal formadas'
    ), refused
    checks += 1
    # A well formed file joins the list and shows its own texts, English where it has none.
    client.evaluate("""
        (async () => {
            const file = { '@language': { code: 'en-x-check', name: 'Checked English',
                locale: 'en-GB',
                plurals: ['one', 'other'] }, 'html.nav.watch': 'Watch it' };
            cuju.language.importText(JSON.stringify(file)).catch(() => {});
            return true;
        })()
    """)
    _reloaded(client, 'en-GB')
    tab = client.evaluate(
        'document.querySelector(\'#topbar .menu [data-page="watch"]\').textContent.trim()'
    )
    play = client.evaluate(
        'document.querySelector(\'#topbar .menu [data-page="play"]\').textContent.trim()'
    )
    assert (tab, play) == ('Watch it', 'Play'), (tab, play)
    codes = client.evaluate('cuju.language.refresh().then((list) => list.map((l) => l.code))')
    assert codes == ['en', 'en-x-check', 'pt'], codes
    checks += 2

    for code in ('en-x-check', 'pt'):
        removed = client.evaluate(
            f"fetch('/api/languages/{code}', {{ method: 'DELETE' }}).then((r) => r.json())"
        )
        assert removed == {'code': code, 'removed': True}, json.dumps(removed)
        checks += 1

    # Following the browser again returns to English, and every page reads as before.
    client.evaluate('cuju.language.choose(null); true')
    _reloaded(client, 'en-US')
    assert client.evaluate("localStorage.getItem('cuju.language')") is None
    again = _texts(client)
    # Help shows the lessons done so far, which the visits of the pages above may add to, so its
    # headings stand for it.
    for name in ('bar', 'settings', 'teams', 'field'):
        if again[name] != english[name]:
            import difflib

            changed = difflib.unified_diff(
                english[name].split('\n'), again[name].split('\n'), lineterm='', n=0
            )
            raise AssertionError(f'{name} differs: ' + ' | '.join(list(changed)[2:40]))
        checks += 1
    client.evaluate("cuju.showPage('help'); true")
    assert client.evaluate(HEADINGS) == english_headings, client.evaluate(HEADINGS)
    checks += 1
    assert _missing(client) == [], _missing(client)
    checks += 1
    return checks
