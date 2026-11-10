# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the home folder, the library of recordings, its Trash and the samples."""

import json
import logging
import os
import threading
import urllib.request

import pytest
import torch

import cuju
import cuju.errors
import cuju.state
from cuju.render._format import recording as _recording
from cuju.render._http import launch as _launch
from cuju.render._http import server as _server
from cuju.render._store import home as _home
from cuju.render._store import library as _library
from support.common import (
    _SAMPLES,
    _filtered_episodes,
    _get,
    _goals,
    _help_json,
    _help_server,
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


def test_tutorial_checks_each_lesson_from_the_home_folder(render_home, monkeypatch):
    from cuju.render._guide import tutorial as _tutorial
    from cuju.render._store import samples as _samples

    lessons = _tutorial.lessons()
    page = json.loads((_server._WEB / 'lessons.json').read_text())['lessons']
    assert [lesson['id'] for lesson in lessons] == [lesson['id'] for lesson in page]
    assert {lesson['agent']['check'] for lesson in lessons} <= set(_tutorial.CHECKS)
    state = _tutorial.state()
    assert state['next'] == 'open_sample' and not any(e['done'] for e in state['lessons'])
    _samples.add(['sample-5v5', 'starter-team'])
    done = {entry['id'] for entry in _tutorial.state()['lessons'] if entry['done']}
    assert done == {'open_sample', 'register_team'}
    # A page reports the lessons only it can check, which the reset forgets again.
    assert _tutorial.report(['seek_goal'])['next'] == 'switch_camera'
    with pytest.raises(cuju.errors.ArgumentError):
        _tutorial.report(['nowhere'])
    with pytest.raises(cuju.errors.ArgumentError):
        _tutorial.report('seek_goal')
    assert _tutorial.reset()['page'] == []
    # A game of at least 300 steps and an attempt of a challenge end their lessons.
    real = _library.matches
    extra = [
        {'steps': 299, 'provenance': {'source': 'human_game'}},
        {'steps': 300, 'provenance': {'source': 'requested_match'}},
    ]
    monkeypatch.setattr(_library, 'matches', lambda trash=False: [*real(trash), *extra])
    assert _tutorial.lesson_state('play_game')['done']
    assert not _tutorial.lesson_state('start_challenge')['done']
    (render_home / 'challenges').mkdir()
    (render_home / 'challenges' / 'corner.json').write_text('{"entries": [{"name": "Ana"}]}')
    assert _tutorial.lesson_state('start_challenge')['done']
    with pytest.raises(cuju.errors.ArgumentError):
        _tutorial.lesson_state('nowhere')


def test_doctor_through_the_server_and_the_command_line(render_home, capsys, monkeypatch, tmp_path):
    from cuju.render.__main__ import main
    from cuju.render._guide import doctor as _doctor

    def broken(trash=False):
        raise RuntimeError('the library broke')

    server, address = _help_server()
    try:
        real = _library.matches
        monkeypatch.setattr(_library, 'matches', broken)
        assert _help_json(address, '/api/matches')[0] == 500
        monkeypatch.setattr(_library, 'matches', real)
        status, report = _help_json(address, '/api/help/doctor')
        assert status == 200 and report['kind'] == 'server'
        assert any('RuntimeError: the library broke' in e['message'] for e in report['errors'])
        port = server.server_address[1]
        connection = _server.http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        connection.request('GET', '/api/help/doctor', headers={'Host': f'evil.example:{port}'})
        assert connection.getresponse().status == 403
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
    status = main(['doctor', '--json'])
    printed = json.loads(capsys.readouterr().out)
    assert printed['kind'] == 'command'
    assert status == (0 if all(check['ok'] for check in printed['checks']) else 1)
    out = tmp_path / 'report.txt'
    main(['doctor', '--out', str(out)])
    text = capsys.readouterr().out
    assert text.startswith('cuju render diagnostic report') and out.read_text() == text
    (render_home / _launch.LOG_FILE).write_text('started\nTraceback (most recent call last)\n')
    assert any(e['level'] == 'LOG' for e in _doctor.report()['errors'])


def test_moment_index_follows_the_library(render_home, monkeypatch):
    from cuju.render._moments import search as _search

    _library.add_samples()
    assert _search.sync() == {'recordings': 2, 'built': 2, 'removed': 0, 'failed': 0}
    assert _search.sync()['built'] == 0
    assert _search.search('goal')['total'] == 4
    index = _home.folder('index')
    assert sorted(path.name for path in index.iterdir()) == ['sample-11v11.json', 'sample-5v5.json']
    # A recording in the Trash leaves the results and keeps its index, a purge removes both.
    assert _library.trash('sample-5v5')
    found = _search.search('goal')
    assert found['total'] == 2 and found['recordings'] == 1
    assert _search.sync()['built'] == 0 and (index / 'sample-5v5.json').is_file()
    assert _library.trash('sample-5v5', restore=True)
    assert _search.search('goal')['total'] == 4
    assert _library.trash('sample-5v5') and _library.purge('sample-5v5')
    assert _search.sync()['removed'] == 1
    assert not (index / 'sample-5v5.json').exists()
    # A recording that arrives is read once, a broken one keeps an empty entry.
    assert _library.add_samples(['sample-5v5'])
    broken = _home.folder('matches') / 'm-broken.cjr'
    broken.write_bytes(b'not a recording')
    done = _search.sync()
    assert done['built'] == 2 and done['failed'] == 1
    assert _search.sync()['built'] == 0
    assert _search.search('goal')['total'] == 4
    # A new version of the moments rebuilds every file, from disk as from memory.
    _search._CACHES.clear()
    assert _search.sync()['built'] == 0
    monkeypatch.setattr(_search, 'VERSION', 'other')
    assert _search.sync()['built'] == 3


class _FeedRequests:
    def __init__(self, entries):
        self.listed = entries

    def entries(self):
        return list(self.listed)


class _FeedTournaments:
    def __init__(self, full):
        self.full = full

    def entries(self):
        return [{key: self.full[key] for key in ('id', 'name')}]

    def get(self, identifier):
        return self.full if identifier == self.full['id'] else None


def test_feed_route_and_resolve(render_home):
    from cuju.render._store import library as _library

    requests = _FeedRequests([])
    cup = {'id': 't-1', 'name': 'Cup', 'matches': [{'result': None}]}
    handler = _server.make_handler(requests, tournaments=_FeedTournaments(cup))
    server = _server.http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_address[1]}'

    def resolve(source):
        query = urllib.parse.urlencode({'source': source})
        return json.loads(_get(address, f'/api/feed/resolve?{query}')[1])

    def headers(path):
        with urllib.request.urlopen(address + path, timeout=10) as response:
            return response.headers, response.read()

    try:
        found, page = headers('/feed?source=live&size=vertical')
        assert found['Content-Type'].startswith('text/html') and b'feed-frame' in page
        assert found['X-Frame-Options'] == 'DENY'
        found, page = headers('/?feed=1&size=vertical')
        assert b'feed-boot.js' in page
        assert found['X-Frame-Options'] == 'SAMEORIGIN'
        assert found['Content-Security-Policy'] == "frame-ancestors 'self'"
        assert headers('/')[0]['X-Frame-Options'] == 'DENY'
        assert resolve('auto') == {
            'kind': 'none',
            'id': '',
            'title': '',
            'message': 'The library holds no recording yet',
        }
        assert resolve('live')['message'] == 'No live source streams now'
        added = sorted(path.stem for path in _library.add_samples())
        assert len(added) == 2
        newest = _library.matches()[0]['id']
        assert resolve('auto')['kind'] == 'match' and resolve('latest')['id'] == newest
        assert resolve(f'recording:{added[0]}')['id'] == added[0]
        assert resolve(added[0])['kind'] == 'match'
        assert resolve('recording:m-missing')['kind'] == 'none'
        announcement = {
            'id': 'live-20261110-101500-aaaa',
            'title': 'Evaluation',
            'scenario': '5_vs_5',
            'environment': 0,
            'pid': os.getpid(),
        }
        live = _home.folder('live') / 'live-20261110-101500-aaaa.json'
        live.write_text(json.dumps(announcement))
        assert resolve('auto') == {
            'kind': 'live',
            'id': 'live-20261110-101500-aaaa',
            'title': 'Evaluation',
        }
        assert resolve('live:evaluation')['id'] == 'live-20261110-101500-aaaa'
        assert resolve('live:Training')['kind'] == 'none'
        assert resolve('queue')['message'] == 'No requested match has finished yet'
        requests.listed = [
            {'id': 'r-2', 'state': 'done', 'match': added[1], 'finished': 20.0},
            {'id': 'r-1', 'state': 'done', 'match': added[0], 'finished': 30.0},
            {'id': 'r-3', 'state': 'running', 'match': None, 'finished': None},
        ]
        assert resolve('queue')['id'] == added[0] and resolve('queue')['request'] == 'r-1'
        assert resolve('tournament')['message'] == 'Cup has no finished match yet'
        cup['matches'] = [{'result': {'match': added[0]}}, {'result': {'match': added[1]}}]
        assert resolve('tournament:Cup')['id'] == added[1]
        assert resolve('tournament:t-9')['kind'] == 'none'
        with pytest.raises(urllib.error.HTTPError) as refused:
            resolve('../up')
        assert refused.value.code == 400
        listed = json.loads(_get(address, '/api/feed')[1])
        sources = [row['source'] for row in listed]
        assert sources[:5] == ['auto', 'latest', 'live', 'queue', 'tournament']
        assert 'live:live-20261110-101500-aaaa' in sources and 'tournament:t-1' in sources
        assert all(row['url'].startswith(f'{address}/feed?source=') for row in listed)
    finally:
        server.shutdown()
        server.server_close()
