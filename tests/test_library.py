# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the home folder, the library of recordings, its Trash and the samples."""

import json

from cuju.render._store import home as _home
from cuju.render._store import library as _library
from support.common import _serve_once


def test_relative_home_resolves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(_home.HOME_VARIABLE, 'relative-home')
    assert _home.home() == tmp_path / 'relative-home'


def test_samples_keep_the_users_files(render_home, monkeypatch):
    matches = _home.folder('matches')
    (matches / 'sample-11v11.cjr').write_bytes(b'mine')
    (matches / 'sample-5v5.json').write_text('{"id": "sample-5v5", "title": "mine"}')
    _serve_once(monkeypatch)
    assert (matches / 'sample-11v11.cjr').read_bytes() == b'mine'
    assert json.loads((matches / 'sample-5v5.json').read_text())['title'] == 'mine'
    assert not (matches / 'sample-5v5.cjr').exists()
    assert _library.add_samples() == []
