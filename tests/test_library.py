# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the home folder, the library of recordings, its Trash and the samples."""

import json

import pytest

import cuju
import cuju.errors
import cuju.state
from cuju.render._http import launch as _launch
from cuju.render._store import home as _home
from cuju.render._store import library as _library
from support.common import _SAMPLES, _library_ids, _serve_once


def test_relative_home_resolves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(_home.HOME_VARIABLE, 'relative-home')
    assert _home.home() == tmp_path / 'relative-home'


def test_open_sample_on_a_new_home(render_home):
    # A home folder whose server never started still opens a shipped sample by name, as the
    # notebook example of the docs does.
    assert _library.path_of('sample-11v11') is None
    assert _launch.resolve('sample-11v11') == '#match=sample-11v11'
    assert _library.path_of('sample-11v11') is not None
    assert _library.path_of('sample-5v5') is None


def test_recording_details_and_trash(render_home):
    _library.add_samples()
    path = _library.path_of('sample-5v5')
    original = path.read_bytes()
    entry = _library.update(
        path.stem, folder='League/Week 1', favorite=True, tags=['final', 'final '], notes='Goal'
    )
    assert (entry['tags'], entry['favorite'], entry['notes']) == (['final'], True, 'Goal')
    assert _library.details(path.stem) == entry
    # Only a recording of the Trash is deleted for good.
    assert not _library.purge(path.stem)
    assert not _library.trash(path.stem, restore=True)
    assert _library.trash(path.stem)
    assert not _library.trash(path.stem)
    assert _library.path_of(path.stem) is None
    assert _library.path_of(path.stem, include_trash=True) == path
    assert path.stem not in _library_ids()
    assert [item['id'] for item in _library.matches(trash=True)] == [path.stem]
    assert _library.matches(trash=True)[0]['notes'] == 'Goal'
    for refused in (_library.details, lambda name: _library.update(name, title='Other')):
        with pytest.raises(cuju.ArgumentError):
            refused(path.stem)
    assert _library.trash(path.stem, restore=True)
    assert _library.path_of(path.stem).read_bytes() == original
    restored = _library.details(path.stem)
    assert (restored['folder'], restored['tags']) == ('League/Week 1', ['final'])
    assert 'deleted_at' not in restored
    for changes in (
        {'favorite': 1},
        {'tags': 'final'},
        {'tags': [' ']},
        {'tags': ['x' * 41]},
        {'tags': [str(index) for index in range(21)]},
        {'notes': []},
        {'notes': 'x' * 10001},
        {'notes': 'kept', 'title': ' '},
    ):
        with pytest.raises(cuju.ArgumentError):
            _library.update(path.stem, **changes)
    assert _library.details(path.stem)['notes'] == 'Goal'
    assert path.read_bytes() == original
    assert _library.trash(path.stem)
    assert _library.purge(path.stem)
    assert not path.exists()
    assert not path.with_suffix('.json').exists()
    for unsafe in ('../sample-11v11', '..', 'Sample-11v11', ''):
        assert not _library.trash(unsafe)
        assert not _library.purge(unsafe)
    assert _library.path_of('sample-11v11') is not None


def test_recording_summary_fields_of_the_wrong_type_fall_back(render_home):
    _library.add_samples(['sample-5v5'])
    summary = _home.folder('matches') / 'sample-5v5.json'
    stored = json.loads(summary.read_text())
    stored.update(favorite='yes', tags=['kept', 3], notes=None, provenance=[], folder=7)
    stored['deleted_at'] = 12
    summary.write_text(json.dumps(stored))
    entry = _library.matches()[0]
    assert (entry['favorite'], entry['tags'], entry['notes']) == (False, ['kept'], '')
    assert (entry['provenance'], entry['folder']) == ({}, '')
    assert 'deleted_at' not in entry


def test_samples_keep_the_users_files(render_home, monkeypatch):
    matches = _home.folder('matches')
    (matches / 'sample-11v11.cjr').write_bytes(b'mine')
    (matches / 'sample-5v5.json').write_text('{"id": "sample-5v5", "title": "mine"}')
    _serve_once(monkeypatch)
    assert (matches / 'sample-11v11.cjr').read_bytes() == b'mine'
    assert json.loads((matches / 'sample-5v5.json').read_text())['title'] == 'mine'
    assert not (matches / 'sample-5v5.cjr').exists()
    assert _library.add_samples() == []


def test_sample_in_the_trash_comes_back_on_request(render_home, monkeypatch, capsys):
    from cuju.render.__main__ import main

    _serve_once(monkeypatch)
    _library.update('sample-5v5', tags=['kept'])
    assert _library.trash('sample-5v5')
    # The start of the server leaves the Trash as it is.
    _serve_once(monkeypatch)
    assert _library_ids() == ['sample-11v11']
    capsys.readouterr()
    assert main(['sample']) == 0
    assert 'restored sample-5v5' in capsys.readouterr().out
    assert _library_ids() == _SAMPLES
    assert _library.details('sample-5v5')['tags'] == ['kept']
    assert _library.matches(trash=True) == []
    assert main(['sample', '5v5']) == 0
    assert 'already holds' in capsys.readouterr().out
