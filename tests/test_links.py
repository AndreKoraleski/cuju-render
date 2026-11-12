# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks that the links of the page, the docs and the README lead somewhere, without the network.

A relative link names a file of the repository, a link into this repository on GitHub names a
file that exists here, a link into cuju names a path that tests/support/links.json lists, an
anchor into a Markdown file of this repository names one of its headings, and no file mentions a
thing that was removed. The page shows the version of the package. ci/check_links.py holds the
checks, and the same script, run by hand, requests every external link and checks the list of
cuju's paths against cuju's repository.
"""

import importlib.util
import json
import re
from pathlib import Path

import cuju
from cuju.render import _version
from support.common import _help_json, _help_server

ROOT = Path(__file__).resolve().parents[1]


def _checker():
    spec = importlib.util.spec_from_file_location('check_links', ROOT / 'ci' / 'check_links.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


links = _checker()


def test_every_link_of_the_page_the_docs_and_the_readme_holds():
    problems = links.offline_problems(ROOT)
    assert not problems, 'Stale links, each with its file and line\n' + '\n'.join(problems)


def test_the_data_gives_a_reason_for_each_removed_thing_and_skipped_host():
    data = links.load(ROOT)
    assert data['cuju'] == sorted(set(data['cuju']), key=data['cuju'].index)
    for entry in data['removed']:
        re.compile(entry['pattern'])
        assert entry['reason'].strip(), entry
    assert all(entry['reason'].strip() for entry in data['skip'])


def _write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def test_the_check_names_the_file_the_line_and_the_stale_link(tmp_path):
    data = {
        'cuju': ['blob/main/docs/api.md', 'blob/main/docs/gone.md'],
        'skip': [{'host': '127.0.0.1', 'reason': 'this computer'}],
        'removed': [{'pattern': 'montage', 'reason': 'it was removed'}],
    }
    _write(tmp_path, 'tests/support/links.json', json.dumps(data))
    _write(tmp_path, 'docs/guide.md', '# A guide\n\n## The first part\n\nText.\n')
    _write(
        tmp_path,
        'README.md',
        '\n'.join(
            [
                '# Title',
                '',
                '[Guide](docs/guide.md#the-first-part) and [old](docs/old.md).',
                '[Part](docs/guide.md#a-later-part) and [here](#title).',
                '[Source](https://github.com/AndreKoraleski/cuju-render/blob/main/docs/guide.md)',
                '[Moved](https://github.com/AndreKoraleski/cuju-render/blob/main/ARCHITECTURE.md)',
                '[Engine](https://github.com/AndreKoraleski/cuju/blob/main/docs/api.md)',
                '[States](https://github.com/AndreKoraleski/cuju/blob/main/docs/states.md)',
                'The server at http://127.0.0.1:8780 shows the montage.',
                '',
                '```sh',
                'open docs/missing.md',
                '```',
            ]
        )
        + '\n',
    )
    _write(
        tmp_path,
        'src/cuju/render/web/index.html',
        '<link rel="icon" href="assets/logo.svg"><a href="#main">Skip</a><main id="main"></main>\n',
    )
    problems = links.offline_problems(tmp_path)
    expected = [
        'README.md:3: docs/old.md, names docs/old.md',
        'README.md:4: docs/guide.md#a-later-part, names the anchor #a-later-part',
        'README.md:6: https://github.com/AndreKoraleski/cuju-render/blob/main/ARCHITECTURE.md, '
        'names ARCHITECTURE.md',
        'README.md:8: https://github.com/AndreKoraleski/cuju/blob/main/docs/states.md, links into '
        "cuju at 'blob/main/docs/states.md'",
        'src/cuju/render/web/index.html:1: assets/logo.svg, names '
        'src/cuju/render/web/assets/logo.svg',
        "tests/support/links.json: lists 'blob/main/docs/gone.md' of cuju",
        'README.md:9: mentions montage, it was removed',
    ]
    assert len(problems) == len(expected), '\n'.join(problems)
    for problem, start in zip(problems, expected, strict=True):
        assert problem.startswith(start), (problem, start)


def test_slugs_follow_github():
    assert links.slug('The `cuju render video` command') == 'the-cuju-render-video-command'
    assert links.slug('Teams, kits and [models](a.md)') == 'teams-kits-and-models'
    assert links.slug('What is new in 0.1.0?') == 'what-is-new-in-010'
    text = '# Notes\n\n## Notes\n\n```md\n# Not a heading\n```\n\n<a id="kept"></a>\n'
    assert links.anchors_of(text) == {'notes', 'notes-1', 'kept'}


def test_the_page_shows_the_version_of_the_package(render_home):
    server, address = _help_server()
    try:
        status, info = _help_json(address, '/api/info')
    finally:
        server.shutdown()
        server.server_close()
    assert status == 200
    assert info == {'version': _version.__version__, 'cuju': cuju.__version__}
    home = (ROOT / 'src/cuju/render/web/js/pages/home.js').read_text(encoding='utf-8')
    assert 'info.version' in home and 'info.cuju' in home
    citation = (ROOT / 'CITATION.cff').read_text(encoding='utf-8')
    assert re.search(r'^version: (\S+)$', citation, re.MULTILINE)[1] == _version.__version__
    changelog = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
    newest = re.search(r'^## \[(\d[^\]]*)\]', changelog, re.MULTILINE)[1]
    assert newest == _version.__version__
