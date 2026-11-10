# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the home folder, the library of recordings, its Trash and the samples."""

import json
import logging
import threading

import pytest
import torch

import cuju
import cuju.errors
import cuju.state
from cuju.render._format import recording as _recording
from cuju.render._http import launch as _launch
from cuju.render._store import home as _home
from cuju.render._store import library as _library
from support.common import (
    _SAMPLES,
    _filtered_episodes,
    _goals,
    _library_ids,
    _one_second,
    _sample_head,
    _serve_once,
)


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


def test_recording_identifiers_are_unique_within_a_second(render_home, monkeypatch):
    head, frames = _sample_head('sample-5v5', 3)
    _one_second(monkeypatch)
    saved = []

    def save_many():
        for _ in range(10):
            saved.append(_library.save(head, frames).stem)

    workers = [threading.Thread(target=save_many) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(60)
    assert len(saved) == len(set(saved)) == 40
    assert sorted(saved) == _library_ids()
    for name in saved:
        assert list(_recording.frames(_library.path_of(name))) == frames
        assert _library.details(name)['steps'] == 3


def test_recorder_keeps_episodes_with_goals(render_home):
    episodes, kept, _, recorder = _filtered_episodes(keep='goals')
    expected = [frames for frames in episodes if _goals(frames)]
    assert 0 < len(expected) < len(episodes)
    assert kept == expected
    assert recorder.dropped == len(episodes) - len(expected)
    # A dropped episode writes no file, so the library holds the saved ones alone.
    assert len(_library.matches()) == len(episodes) + len(kept)


def test_recorder_writes_on_a_thread_and_reports_failures(render_home, monkeypatch, caplog):
    """The step that ends an episode hands its frames over, and a failed write reports itself."""
    written = _library.save
    gate = threading.Event()

    def slow(*arguments):
        gate.wait(30)
        return written(*arguments)

    monkeypatch.setattr(_library, 'save', slow)
    batch = cuju.BatchEnvironment(
        'academy_empty_goal_close_l1_r0', environment_count=1, device='cpu', seed=11
    )
    recorder = cuju.render.Recorder(batch)
    batch.reset()
    step = 0
    while not recorder.episodes:
        batch.step(torch.tensor([[12 if step % 3 else 5]], dtype=torch.int32))
        step += 1
    # The writer waits at the gate, so the episode ended and training stepped on without it.
    assert recorder.saved == [] and recorder._pending == 1
    gate.set()
    recorder.flush()
    assert len(recorder.saved) == 1 and recorder.saved[0].is_file()
    assert _library.details(recorder.saved[0].stem)['steps'] > 0

    def failing(*arguments):
        raise OSError('the disk is full')

    monkeypatch.setattr(_library, 'save', failing)
    with caplog.at_level(logging.WARNING, logger='cuju'):
        while recorder.episodes < 2:
            batch.step(torch.tensor([[12 if step % 3 else 5]], dtype=torch.int32))
            step += 1
        recorder._wait()
    assert 'could not write' in caplog.text and 'the disk is full' in caplog.text
    assert len(recorder.saved) == 1 and len(_library.matches()) == 1
    assert not list((render_home / 'matches').glob('*.part'))
    with pytest.raises(OSError, match='the disk is full'):
        recorder.save()
    recorder.flush()
    # Closing the batch waits for the recordings handed over.
    monkeypatch.setattr(_library, 'save', slow)
    gate.clear()
    while recorder.episodes < 3:
        batch.step(torch.tensor([[12 if step % 3 else 5]], dtype=torch.int32))
        step += 1
    threading.Timer(0.5, gate.set).start()
    batch.close()
    assert recorder._pending == 0 and len(recorder.saved) == 2
