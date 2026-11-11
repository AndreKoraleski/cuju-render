# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the home folder, the library of recordings, its Trash and the samples."""

import json
import logging
import os
import threading
import time
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
    _SINGLE,
    _challenge_frames,
    _FeedRequests,
    _FeedTournaments,
    _filtered_episodes,
    _get,
    _goals,
    _help_json,
    _help_server,
    _library_ids,
    _names_lineup,
    _one_second,
    _person_recording,
    _sample_head,
    _serve_once,
    _short_challenges,
    _toy_team,
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


def _without_recordings(outcome):
    """Returns a run's result without what names its recordings or the time of its best run."""

    def attempts(results):
        return [{key: value for key, value in item.items() if key != 'match'} for item in results]

    best = outcome.get('personal_best')
    if best is not None:
        best = {key: value for key, value in best.items() if key != 'time'}
        best['attempts'] = attempts(best['attempts'])
    plain = {key: value for key, value in outcome.items() if key != 'group'}
    return {**plain, 'attempts': attempts(outcome['attempts']), 'personal_best': best}


def _clear_boards(render_home):
    """Removes every leaderboard and achievement, so a run of the same competitor ranks afresh."""
    for folder in ('challenges', 'achievements'):
        for path in (render_home / folder).glob('*.json'):
            path.unlink()


def test_challenge_runs_group_their_recordings(render_home, tmp_path, monkeypatch, capsys):
    from cuju.render import __main__ as command

    team = _toy_team(tmp_path, 'toy', _SINGLE, '11v11')
    _short_challenges(monkeypatch, 6)
    outcome = cuju.render.challenge('empty_goal_close', team=team['id'], attempts=2)
    group = outcome['group']
    members = cuju.render.recordings(group=group)
    assert [member['id'] for member in members] == [r['match'] for r in outcome['attempts']]
    for index, member in enumerate(members):
        fields = member['group']
        assert (fields['id'], fields['attempt'], fields['attempts']) == (group, index, 2)
        assert fields['challenge'] == 'empty_goal_close' and fields['state'] == 'done'
        assert fields['title_id'] == 'server.names.challenge_run'
        assert fields['title'] == 'Empty goal from close range, toy'
        assert fields['title_values']['challenge']['kind'] == 'challenge'
        assert fields['result_id'] == 'server.names.run_practice' and fields['practice']
        assert fields['value'] == outcome['value'] and fields['competitor'] == 'toy'
    # Every summary of the library names its group, and another run makes a group of its own.
    listed = {entry['id']: entry for entry in cuju.render.recordings()}
    assert all(listed[member['id']]['group']['id'] == group for member in members)
    other = cuju.render.challenge('one_on_one', team='builtin', attempts=1)
    assert other['group'] != group and len(cuju.render.recordings(group=other['group'])) == 1
    other_fields = cuju.render.recordings(group=other['group'])[0]['group']
    assert other_fields['competitor_id'] == 'server.names.builtin'
    # Deleting a group moves all its recordings to the Trash at once, each restorable.
    ids = [member['id'] for member in members]
    assert sorted(cuju.render.delete_group(group)) == sorted(ids)
    assert cuju.render.recordings(group=group) == []
    assert [entry['id'] for entry in cuju.render.recordings(group=group, trash=True)] == ids
    assert cuju.render.delete_group(group) == [] and cuju.render.delete_group('g-none') == []
    assert _library.trash(ids[0], restore=True)
    assert cuju.render.restore_group(group) == [ids[1]]
    assert [entry['id'] for entry in cuju.render.recordings(group=group)] == ids
    # The command line lists the groups, one group, and moves a group to the Trash and back.
    assert command.main(['recordings']) == 0
    out = capsys.readouterr().out
    assert f'{group}  Empty goal from close range, toy, ' in out and '2 recordings' in out
    assert f'    {ids[1]}  attempt 2' in out
    assert command.main(['recordings', '--group', group, '--json']) == 0
    assert [entry['id'] for entry in json.loads(capsys.readouterr().out)] == ids
    assert command.main(['recordings', '--delete-group', group]) == 0
    assert 'moved 2 recordings' in capsys.readouterr().out
    assert command.main(['recordings', '--restore-group', group, '--json']) == 0
    assert sorted(json.loads(capsys.readouterr().out)['restored']) == sorted(ids)
    assert command.main(['recordings', '--group', 'g-none']) == 1
    # A group of a hand edited summary that does not fit is left out, and the rest stays.
    path = render_home / 'matches' / f'{ids[0]}.json'
    summary = json.loads(path.read_text())
    summary['group'] = {'id': '../evil', 'title': 'x'}
    path.write_text(json.dumps(summary))
    assert 'group' not in _library.details(ids[0])
    summary['group'] = {'id': group, 'attempt': 'first', 'practice': 1, 'title': 7}
    path.write_text(json.dumps(summary))
    assert _library.details(ids[0])['group'] == {
        'id': group,
        'title': group,
        'competitor': '',
        'result': '',
    }


def test_challenge_without_recordings_scores_the_same(render_home, tmp_path, monkeypatch, capsys):
    from cuju.render import __main__ as command
    from cuju.render._playing import challenges as _challenges

    team = _toy_team(tmp_path, 'toy', _SINGLE, '11v11')
    _short_challenges(monkeypatch, 8)
    kept = cuju.render.challenge('one_on_one', team=team['id'])
    _clear_boards(render_home)
    before = {entry['id'] for entry in cuju.render.recordings()}
    bare = cuju.render.challenge('one_on_one', team=team['id'], keep_recordings=False)
    assert bare['group'] is None and all(r['match'] is None for r in bare['attempts'])
    assert _without_recordings(bare) == _without_recordings(kept)
    assert {entry['id'] for entry in cuju.render.recordings()} == before
    assert cuju.render.recordings(trash=True) == []
    board = _challenges.board('one_on_one')
    assert [attempt['match'] for attempt in board[0]['attempts']] == [None, None, None]
    with pytest.raises(cuju.errors.ArgumentError, match='keep_recordings'):
        cuju.render.challenge('corner', team='builtin', keep_recordings='no')
    with pytest.raises(cuju.errors.ArgumentError, match='keep_recordings'):
        _challenges.post(['corner', 'runs'], {'team': 'builtin', 'keep_recordings': 0})
    options = ['--team', team['id'], '--attempts', '1', '--no-recordings']
    assert command.main(['challenge', 'corner', *options]) == 0
    out = capsys.readouterr().out
    assert 'no recording kept' in out and 'group ' not in out
    assert {entry['id'] for entry in cuju.render.recordings()} == before
    # A person's run without recordings scores the same, then removes its recordings for good.
    challenge = _challenges.find('one_on_one')

    def attempts():
        return [
            _person_recording(challenge, 0, _challenge_frames(goal_at=12, length=30)),
            _person_recording(challenge, 1, _challenge_frames(goal_at=20, against_at=25)),
            None,
        ]

    _clear_boards(render_home)
    first = attempts()
    shown = _challenges.person_run('one_on_one', 'Ana', first)
    fields = cuju.render.recordings(group=shown['group'])[0]['group']
    assert fields['result_id'] == 'server.names.run_medal' and fields['medal'] == 'bronze'
    assert fields['result'] == 'goal difference +1, bronze medal' and fields['competitor'] == 'Ana'
    _clear_boards(render_home)
    second = attempts()
    hidden = _challenges.person_run('one_on_one', 'Ana', second, keep_recordings=False)
    assert hidden['group'] is None and (hidden['value'], hidden['medal']) == (1, 'bronze')
    assert _without_recordings(hidden) == _without_recordings(shown)
    assert all(_library.path_of(match, include_trash=True) is None for match in second[:2])
    # A run that a person leaves keeps its attempts as a group, or removes them.
    third = attempts()[:2]
    left = _challenges.leave_run('one_on_one', 'Ana', third)
    fields = cuju.render.recordings(group=left['group'])[1]['group']
    assert fields['state'] == 'left' and fields['result'] == 'left after 2 of 3'
    fourth = attempts()[:1]
    gone = _challenges.leave_run('one_on_one', 'Ana', fourth, keep_recordings=False)
    assert gone == {'challenge': 'one_on_one', 'group': None, 'removed': fourth}
    assert _library.path_of(fourth[0], include_trash=True) is None
    wrong = _person_recording(challenge, 1, _challenge_frames(), seed=5)
    with pytest.raises(cuju.errors.ArgumentError, match='seed'):
        _challenges.leave_run('one_on_one', 'Ana', [None, wrong], keep_recordings=False)
    assert _library.path_of(wrong) is not None
    with pytest.raises(cuju.errors.ArgumentError):
        _challenges.leave_run('one_on_one', 'Ana', [])


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

    def broken(trash=False, group=None):
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
        # The message of a slate comes with its id, so the page shows it in its language.
        assert resolve('auto') == {
            'kind': 'none',
            'id': '',
            'title': '',
            'message': 'The library holds no recording yet',
            'message_id': 'server.feed.no_recordings',
            'message_values': {},
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
        assert 'live:Evaluation' in sources and 'tournament:t-1' in sources
        assert all(row['url'].startswith(f'{address}/feed?source=') for row in listed)
    finally:
        server.shutdown()
        server.server_close()


def test_feed_command_refuses_a_recording_outside_the_library(render_home, capsys):
    from cuju.render.__main__ import main
    from cuju.render._store import library as _library

    assert main(['feed', 'nosuchthing']) == 1
    err = capsys.readouterr().err
    assert 'expected a recording of the library, found none named nosuchthing' in err
    assert 'Traceback' not in err and len(err.strip().splitlines()) == 1
    identifier = sorted(path.stem for path in _library.add_samples())[0]
    assert main(['feed', identifier]) == 0
    assert capsys.readouterr().out.strip().endswith(f'source=recording:{identifier}&size=1080p')
    # A live source may start later, so its name passes.
    assert main(['feed', 'live:Later']) == 0


def test_samples_date_from_their_files_and_list_five_a_side_first(render_home):
    assert _library.samples() == ['sample-5v5', 'sample-11v11']
    _library.add_samples()
    dates = {entry['id']: entry['created'] for entry in _library.matches()}
    shipped = time.localtime((_library._SAMPLES / 'sample-5v5.cjr').stat().st_mtime)
    assert dates['sample-5v5'] == time.strftime('%Y-%m-%dT%H:%M:%S', shipped)


def test_names_reach_the_library_summary_and_a_new_title_drops_them(render_home):
    from cuju.render._text import messages as _messages

    title = _messages.label('server.names.demo')
    head = _recording.header(title, '5_vs_5', _names_lineup())
    frame = bytes(_recording.frame_bytes(2))
    path = _library.save(head, [frame])
    summary = _library.details(path.stem)
    assert summary['title'] == 'Demo, the built-in AI against itself'
    assert summary['title_id'] == 'server.names.demo' and summary['title_values'] == {}
    assert summary['teams'] == ['Left', 'Right']
    assert [label['id'] for label in summary['team_labels']] == [
        'server.names.left',
        'server.names.right',
    ]
    # The stored summary keeps the label, so a list read from the files shows it again.
    stored = json.loads(path.with_suffix('.json').read_text())
    assert stored['title_id'] == 'server.names.demo'
    renamed = _library.update(path.stem, title='Our demo')
    assert renamed['title'] == 'Our demo' and 'title_id' not in renamed
    assert 'title_id' not in _library.details(path.stem)
    # A summary made again from the header keeps the labels too.
    path.with_suffix('.json').unlink()
    assert _library.details(path.stem)['title_id'] == 'server.names.demo'


def test_names_of_the_samples_come_by_their_name(render_home):
    _library.add_samples(['sample-5v5'])
    summary = _library.details('sample-5v5')
    assert summary['title'] == 'Sample match, 5 vs 5'
    assert summary['title_id'] == 'server.names.sample_5v5'
    # The teams of a sample have names of their own, which stay text.
    assert summary['team_labels'] == [None, None]
    _library.update('sample-5v5', title='Five')
    assert 'title_id' not in _library.details('sample-5v5')
