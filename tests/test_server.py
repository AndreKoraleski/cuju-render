# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the HTTP server, its routes and its checks, and the installable app."""

import gzip
import json
import os
import re
import struct
import threading
import time
import urllib.request

import pytest
import torch

import cuju
import cuju.errors
import cuju.state
from cuju.render._format import recording as _recording
from cuju.render._http import server as _server
from cuju.render._registry import teams as _teams
from cuju.render._store import home as _home
from support.common import _CRASH, _get, _send, _toy_team


def test_server_api(render_home):
    batch = cuju.BatchEnvironment(
        'academy_empty_goal_close_l1_r0', environment_count=1, device='cpu'
    )
    recorder = cuju.render.Recorder(batch, title='a test match')
    batch.reset()
    recorder.capture()
    for _ in range(5):
        _, _, done, _ = batch.step(torch.zeros((1, 1), dtype=torch.int32))
        recorder.capture(done)
    path = recorder.save()
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        status, body = _get(address, '/api/matches')
        listed = json.loads(body)
        assert status == 200 and [entry['title'] for entry in listed] == ['a test match']
        moved = _send(
            address,
            f'/api/matches/{path.stem}',
            b'{"folder": "League / Week 1", "title": "renamed"}',
            'PATCH',
        )
        assert (moved['folder'], moved['title']) == ('League/Week 1', 'renamed')
        with pytest.raises(urllib.error.HTTPError):
            _send(address, f'/api/matches/{path.stem}', b'{"folder": "../out"}', 'PATCH')
        status, body = _get(address, f'/api/matches/{path.stem}')
        assert gzip.decompress(body).startswith(_recording.MAGIC)
        assert 'academy_empty_goal_close' in json.loads(_get(address, '/api/scenarios')[1])
        assert json.loads(_get(address, '/api/info')[1]) == {'version': cuju.__version__}
        folder = _teams.folder_bundle(
            [
                ('submission/main.py', b'def agent(obs):\n    return [0]\n'),
                ('submission/w.bin', b'1'),
            ]
        )
        team = _send(address, '/api/teams?name=idle&filename=submission&format=5v5', folder)
        assert (team['format'], len(team['style']['players'])) == ('5v5', 5)
        teams = json.loads(_get(address, '/api/teams')[1])
        assert [entry['id'] for entry in teams] == ['builtin', team['id']]
        changes = {
            'format': '11v11',
            'style': {'kit': {'pattern': 'hoops'}, 'players': [{'name': 'Ana', 'number': 9}]},
        }
        team = _send(address, f'/api/teams/{team["id"]}', json.dumps(changes).encode(), 'PATCH')
        assert len(team['style']['players']) == 11
        assert team['style']['players'][0] == {
            'name': 'Ana',
            'number': 9,
            'skin': 'grf',
            'hair': 'grf',
            'hair_color': 'grf',
            'model': 'team',
            'celebration': 'team',
        }
        # A player takes a model of its own, and a model's colors give way to the team's.
        changes = {
            'style': {
                'players': [{}, {'model': 'kaykit-knight'}],
                'colors': {'kaykit-knight': {'#A1B2C3': '#ff0000'}},
            }
        }
        team = _send(address, f'/api/teams/{team["id"]}', json.dumps(changes).encode(), 'PATCH')
        assert team['style']['players'][1]['model'] == 'kaykit-knight'
        assert team['style']['colors'] == {'kaykit-knight': {'#a1b2c3': '#ff0000'}}
        moves = {
            'style': {
                'celebrations': ['knee_slide', 'clip:Cheer'],
                'players': [{'celebration': 'robot_dance'}],
            }
        }
        team = _send(address, f'/api/teams/{team["id"]}', json.dumps(moves).encode(), 'PATCH')
        assert team['style']['celebrations'] == ['knee_slide', 'clip:Cheer']
        assert team['style']['players'][0]['celebration'] == 'robot_dance'
        fans = {'style': {'crowd': {'colors': [[10, 20, 30], [200, 200, 0]]}}}
        team = _send(address, f'/api/teams/{team["id"]}', json.dumps(fans).encode(), 'PATCH')
        assert team['style']['crowd'] == {'colors': [[10, 20, 30], [200, 200, 0]]}
        for wrong in (
            {'players': [{'model': 'custom'}]},
            {'colors': {'grf': {}}},
            {'crowd': {'colors': []}},
            {'celebrations': ['Bad Name!']},
        ):
            with pytest.raises(urllib.error.HTTPError):
                _send(
                    address,
                    f'/api/teams/{team["id"]}',
                    json.dumps({'style': wrong}).encode(),
                    'PATCH',
                )
        with pytest.raises(urllib.error.HTTPError):
            _send(
                address,
                f'/api/teams/{team["id"]}',
                b'{"style": {"kit": {"pattern": "x"}}}',
                'PATCH',
            )
        png = b'\x89PNG\r\n\x1a\n' + bytes(32)
        team = _send(address, f'/api/teams/{team["id"]}/images/shirt-front', png, 'PUT')
        assert team['images'] == ['shirt-front']
        assert _get(address, f'/api/teams/{team["id"]}/images/shirt-front')[1] == png
        sound = b'OggS' + bytes(60)
        team = _send(address, f'/api/teams/{team["id"]}/sounds/goal', sound, 'PUT')
        assert team['sounds'] == ['goal']
        assert _get(address, f'/api/teams/{team["id"]}/sounds/goal')[1] == sound
        with pytest.raises(urllib.error.HTTPError):
            _send(address, f'/api/teams/{team["id"]}/sounds/goal', b'not a sound', 'PUT')
        archive = _get(address, f'/api/teams/{team["id"]}/export')[1]
        copy = _send(address, '/api/teams?filename=export.zip', archive)
        assert copy['name'] == 'idle' and copy['format'] == '11v11'
        assert copy['style'] == team['style'] and copy['images'] == ['shirt-front']
        assert copy['sounds'] == ['goal']
        assert _get(address, f'/api/teams/{copy["id"]}/images/shirt-front')[1] == png
        models = json.loads(_get(address, '/api/models')[1])
        assert all(model['joints']['body'] for model in models)
        request = json.dumps({'left': team['id'], 'right': 'builtin', 'scenario': '5_vs_5'})
        with pytest.raises(urllib.error.HTTPError):
            _send(address, '/api/requests', request.encode())
        for ability in ([1.5, None], [None], 'high', [True, None]):
            request = json.dumps({'left': 'builtin', 'right': 'builtin', 'ability': ability})
            with pytest.raises(urllib.error.HTTPError) as refused:
                _send(address, '/api/requests', request.encode())
            assert refused.value.code == 400
        if (_server._WEB / 'index.html').is_file():
            assert _get(address, '/index.html')[0] == 200
        with pytest.raises(urllib.error.HTTPError):
            _get(address, '/../../secret')
        # A page of another site, or a host name of another site that resolves here, is refused.
        port = server.server_address[1]
        for headers in (
            {'Origin': 'https://example.com'},
            {'Origin': 'http://127.0.0.1:1'},
            {'Host': f'evil.example:{port}'},
        ):
            connection = _server.http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            connection.request('DELETE', f'/api/teams/{team["id"]}', headers=headers)
            assert connection.getresponse().status == 403
            connection.close()
        for kind, identifier in (('matches', path.stem), ('teams', team['id'])):
            request = urllib.request.Request(f'{address}/api/{kind}/{identifier}', method='DELETE')
            with urllib.request.urlopen(request, timeout=10) as response:
                assert response.status == 204
        assert json.loads(_get(address, '/api/matches')[1]) == []
        # Deleting a recording moves it to the Trash, which restores it or deletes it for good.
        assert [entry['id'] for entry in json.loads(_get(address, '/api/trash')[1])] == [path.stem]
        assert path.is_file()
        for route in (f'/api/matches/{path.stem}', f'/api/matches/{path.stem}/details'):
            with pytest.raises(urllib.error.HTTPError):
                _get(address, route)
        restored = _send(address, f'/api/trash/{path.stem}/restore', b'')
        assert (restored['id'], restored['folder']) == (path.stem, 'League/Week 1')
        details = json.loads(_get(address, f'/api/matches/{path.stem}/details')[1])
        assert details['provenance']['source'] == 'recorder'
        noted = _send(
            address,
            f'/api/matches/{path.stem}',
            b'{"favorite": true, "tags": ["goal", " goal "], "notes": "Look again"}',
            'PATCH',
        )
        assert (noted['favorite'], noted['tags'], noted['notes']) == (True, ['goal'], 'Look again')
        with pytest.raises(urllib.error.HTTPError):
            _send(address, f'/api/trash/{path.stem}', b'', 'DELETE')
        assert path.is_file()
        for route in (f'/api/matches/{path.stem}', f'/api/trash/{path.stem}'):
            request = urllib.request.Request(f'{address}{route}', method='DELETE')
            with urllib.request.urlopen(request, timeout=10) as response:
                assert response.status == 204
        assert not path.exists()
        assert json.loads(_get(address, '/api/trash')[1]) == []
        for route in ('/api/trash/..%2Fmatches%2Fx', '/api/trash/%2E%2E', '/api/trash/A'):
            with pytest.raises(urllib.error.HTTPError) as refused:
                _send(address, route, b'', 'DELETE')
            assert refused.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_live_environment_switch_through_the_server(render_home):
    batch = cuju.BatchEnvironment('5_vs_5_l1_r0', environment_count=2, device='cpu')
    source = cuju.render.watch(batch)
    batch.reset()
    actions = torch.zeros((2, 1), dtype=torch.int32)
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def post(port, path, document, headers=None):
        connection = _server.http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        try:
            connection.request(
                'POST',
                path,
                json.dumps(document),
                {'Content-Type': 'application/json', **(headers or {})},
            )
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    try:
        port = server.server_address[1]
        path = f'/api/live/{source.identifier}/environment'
        (listed,) = json.loads(_get(f'http://127.0.0.1:{port}', '/api/live')[1])
        assert (listed['environment_count'], listed['generation']) == (2, 0)
        for invalid in (2, -1, True, '1', None):
            assert post(port, path, {'environment': invalid})[0] == 400
        assert post(port, path, {'environment': 1}, {'Origin': 'http://foreign.invalid'})[0] == 403
        assert post(port, '/api/live/missing/environment', {'environment': 1})[0] == 404
        # The source answers the server alone, and refuses any page that names an origin.
        direct = post(source.port, '/environment', {'environment': 1}, {'Origin': 'null'})
        assert direct[0] == 403
        status, body = post(port, path, {'environment': 1})
        assert status == 202 and json.loads(body) == {'environment': 1, 'generation': 0}
        assert source.environment == 0
        batch.step(actions)
        (listed,) = json.loads(_get(f'http://127.0.0.1:{port}', '/api/live')[1])
        assert (listed['environment'], listed['generation']) == (1, 1)
    finally:
        server.shutdown()
        server.server_close()
        source.close()
        batch.close()


def test_game_policy_crash_through_the_server(render_home, tmp_path, monkeypatch):
    """The game's process reports a failing policy, ends cleanly and saves the recording."""
    monkeypatch.setattr(_server, '_GAME_PACE', 100)
    team = _toy_team(tmp_path, 'fails', _CRASH, '5v5')
    fixed = _toy_team(
        tmp_path, 'fixed', _CRASH, '5v5', {'players': 2, 'assignment': 'fixed', 'selection': [1, 2]}
    )
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        start = {'scenario': '5_vs_5', 'humans': [True, False], 'seed': 4}
        with pytest.raises(urllib.error.HTTPError) as refused:
            _send(
                address,
                '/api/game',
                json.dumps({**start, 'teams': [fixed['id'], 'builtin']}).encode(),
            )
        assert refused.value.code == 400
        game = _send(
            address, '/api/game', json.dumps({**start, 'teams': ['builtin', team['id']]}).encode()
        )
        assert game['team_ids'] == ['builtin', team['id']]
        connection = _server.http.client.HTTPConnection(*server.server_address, timeout=120)
        connection.request('GET', f'/api/game/{game["id"]}/stream')
        assert connection.getresponse().status == 200
        _send(address, f'/api/game/{game["id"]}/pause', b'{"paused": false}')
        entry = _until_ended(address, time.monotonic() + 120)
        connection.close()
        assert entry['state'] == 'ended' and entry['ending'] == 'policy', entry
        assert 'the policy of fails failed, ValueError: the policy broke' in entry['error']
        document = _recording.read_header(render_home / 'matches' / f'{entry["match"]}.cjr')
        assert document['frame_count'] == entry['step'] + 1
        assert document['provenance']['teams'] == ['builtin', team['id']]
        assert document['teams'][1]['name'] == 'fails'
    finally:
        server.shutdown()
        server.server_close()


def _until_ended(address, deadline):
    entry = None
    while time.monotonic() < deadline:
        entry = json.loads(_get(address, '/api/game')[1])
        if entry['state'] in ('ended', 'failed'):
            break
        time.sleep(0.2)
    return entry


def test_game_through_the_server(render_home, monkeypatch):
    monkeypatch.setattr(_server, '_GAME_PACE', 400)
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    address = f'http://127.0.0.1:{port}'
    try:
        assert json.loads(_get(address, '/api/game')[1]) is None
        for wrong in (
            {'scenario': 'no_such_scenario'},
            {'humans': [False, False]},
            {'humans': [1, 0]},
            {'ability': [2, None]},
            {'record': 'yes'},
            {'teams': 'builtin'},
            {'teams': ['builtin', 'no-such-team']},
        ):
            with pytest.raises(urllib.error.HTTPError) as refused:
                _send(address, '/api/game', json.dumps(wrong).encode())
            assert refused.value.code == 400
        start = {'scenario': 'academy_empty_goal_close', 'humans': [True, False], 'seed': 4}
        game = _send(address, '/api/game', json.dumps(start).encode())
        assert game['state'] == 'starting'
        with pytest.raises(urllib.error.HTTPError) as refused:
            _send(address, '/api/game', json.dumps(start).encode())
        assert refused.value.code == 409
        identifier = game['id']
        connection = _server.http.client.HTTPConnection('127.0.0.1', port, timeout=120)
        connection.request('GET', f'/api/game/{identifier}/stream')
        response = connection.getresponse()
        assert response.status == 200
        head = response.read(12)
        assert head[:8] == _recording.MAGIC
        header = json.loads(response.read(struct.unpack_from('<I', head, 8)[0]))
        assert [team['person'] for team in header['teams']] == [True, False]
        first = response.read(header['frame_bytes'])
        assert struct.unpack_from('<i', first)[0] == 0
        # Bad input and input from another site are refused.
        path = f'/api/game/{identifier}/input'
        for wrong in (
            {'side': 1, 'held': []},
            {'side': 0, 'held': ['jump']},
            {'side': 0, 'pressed': ['left']},
            {'side': 0, 'held': 'right'},
            {'side': 0, 'extra': 1},
            {'side': True},
        ):
            with pytest.raises(urllib.error.HTTPError) as refused:
                _send(address, path, json.dumps(wrong).encode())
            assert refused.value.code == 400
        with pytest.raises(urllib.error.HTTPError) as refused:
            _send(address, f'/api/game/{identifier}/pause', b'{"paused": "no"}')
        assert refused.value.code == 400
        with pytest.raises(urllib.error.HTTPError) as refused:
            _send(address, '/api/game/g-other/input', b'{"side": 0}')
        assert refused.value.code == 404
        for headers in ({'Origin': 'https://example.com'}, {'Host': f'evil.example:{port}'}):
            other = _server.http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            other.request('POST', path, body=b'{"side": 0, "held": ["right"]}', headers=headers)
            assert other.getresponse().status == 403
            other.close()
        _send(address, f'/api/game/{identifier}/pause', b'{"paused": false}')
        steps = []
        held = json.dumps({'side': 0, 'held': ['right'], 'pressed': ['shot']}).encode()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            entry = _send(address, path, held)
            if entry['state'] in ('ended', 'failed'):
                break
            frame = response.read(header['frame_bytes'])
            if len(frame) < header['frame_bytes']:
                break
            steps.append(struct.unpack_from('<i', frame)[0])
        entry = _until_ended(address, deadline)
        assert entry['state'] == 'ended', entry
        assert len(steps) > 5 and steps == list(range(1, len(steps) + 1))
        # The engine's action of the person, sampled, and none for the built-in AI's side.
        assert entry['actions'][0] in range(19) and entry['actions'][1] is None
        connection.close()
        recording = render_home / 'matches' / f'{entry["match"]}.cjr'
        document = _recording.read_header(recording)
        assert document['title'].startswith('You against ')
        assert document['frame_count'] == entry['step'] + 1
        # A second game starts once the first has ended, and quitting ends it.
        game = _send(address, '/api/game', json.dumps({**start, 'record': False}).encode())
        _send(address, f'/api/game/{game["id"]}/pause', b'{"paused": false}')
        request = urllib.request.Request(f'{address}/api/game/{game["id"]}', method='DELETE')
        with urllib.request.urlopen(request, timeout=10) as answer:
            assert answer.status == 200
        entry = _until_ended(address, time.monotonic() + 120)
        assert entry['state'] == 'ended' and entry['match'] is None, entry
    finally:
        server.shutdown()
        server.server_close()


def test_cancel_during_child_start(monkeypatch, render_home):
    requests = object.__new__(_server._Requests)
    requests._folder = _home.folder('requests')
    requests._lock = threading.Lock()
    requests._processes = {}
    entry = {
        'id': 'race',
        'state': 'queued',
        'left': 'builtin',
        'right': 'builtin',
        'scenario': '5_vs_5',
        'seed': 7,
        'ability': [None, None],
        'progress': 0,
        'match': None,
        'error': None,
        'created': time.time(),
        'started': None,
        'finished': None,
    }
    requests._entries = [entry]
    started, release, killed = threading.Event(), threading.Event(), threading.Event()

    class Process:
        stderr = ()

        @property
        def stdout(self):
            assert killed.wait(5)
            return ()

        def kill(self):
            killed.set()

        def wait(self):
            return -1

    def start(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return Process()

    monkeypatch.setattr(_server.subprocess, 'Popen', start)
    worker = threading.Thread(target=requests._play_child, args=(entry,))
    worker.start()
    assert started.wait(5)
    canceller = threading.Thread(target=requests.cancel, args=('race',))
    canceller.start()
    release.set()
    worker.join(5)
    canceller.join(5)
    assert not worker.is_alive()
    assert not canceller.is_alive()
    assert killed.is_set()
    assert entry['error'] == 'cancelled'


def test_requests_survive_restart(monkeypatch, render_home):
    monkeypatch.setattr(_server._Requests, '_run', lambda self: None)
    first = _server._Requests()
    queued = first.add('builtin', 'builtin', '5_vs_5', None)
    assert isinstance(queued['seed'], int)
    assert isinstance(queued['created'], float)
    running = first.add('builtin', 'builtin', '5_vs_5', 42)
    first._entries[1].update(state='running', started=time.time())
    first._persist(first._entries[1])
    finished = first.add('builtin', 'builtin', '5_vs_5', 43)
    first._entries[2].update(state='done', match='m-finished', progress=1.0, finished=time.time())
    first._persist(first._entries[2])
    recovered = _server._Requests()
    entries = {entry['id']: entry for entry in recovered.entries()}
    assert list(entries) == [finished['id'], running['id'], queued['id']]
    for old, error in (
        (queued, _server._INTERRUPTED),
        (running, _server._INTERRUPTED_PLAYING),
    ):
        assert entries[old['id']]['state'] == 'failed'
        assert entries[old['id']]['error'] == error
        assert entries[old['id']]['seed'] == old['seed']
        assert entries[old['id']]['finished'] is not None
    assert entries[running['id']]['started'] is not None
    assert entries[finished['id']]['match'] == 'm-finished'
    assert entries[finished['id']]['state'] == 'done'
    # A retry is a new request with the same seed, which can be cancelled as any other.
    repeated = recovered.add('builtin', 'builtin', '5_vs_5', str(queued['seed']))
    assert repeated['id'] != queued['id']
    assert repeated['seed'] == queued['seed']
    assert recovered.cancel(repeated['id'])
    assert _server._Requests().entries()[0]['error'] == 'cancelled'


def test_request_identifiers_are_unique_within_a_second(monkeypatch, render_home):
    """Requests of one second draw again whenever their random end is taken."""
    import itertools
    import types

    monkeypatch.setattr(_server._Requests, '_run', lambda self: None)
    monkeypatch.setattr(
        _home, 'time', types.SimpleNamespace(strftime=lambda form: '20261109-120000')
    )
    lock = threading.Lock()

    def draws():
        # Every value comes three times, so most draws collide with an earlier request.
        return itertools.chain.from_iterable([f'{value:04x}'] * 3 for value in itertools.count())

    source = draws()

    def token_hex(count):
        with lock:
            return next(source)

    monkeypatch.setattr(_home, 'secrets', types.SimpleNamespace(token_hex=token_hex))
    requests = _server._Requests()
    added = []

    def add_many():
        for _ in range(25):
            added.append(requests.add('builtin', 'builtin', '5_vs_5', 1)['id'])

    workers = [threading.Thread(target=add_many) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(30)
    assert len(added) == len(set(added)) == 100
    assert all(name.startswith('r-20261109-120000-') for name in added)
    # A new server draws from the start again and still skips the identifiers of the history.
    source = draws()
    again = _server._Requests()
    later = [again.add('builtin', 'builtin', '5_vs_5', 1)['id'] for _ in range(20)]
    assert not set(later) & set(added)
    assert len(set(later)) == 20
    assert len(list(again._folder.glob('*.json'))) == 120
    for identifier in later:
        assert again.cancel(identifier)
    states = {entry['id']: (entry['state'], entry['error']) for entry in again.entries()}
    assert all(states[identifier] == ('failed', 'cancelled') for identifier in later)
    assert all(states[identifier][1] == _server._INTERRUPTED for identifier in added)


def test_request_history_skips_invalid_files(monkeypatch, render_home, caplog):
    import logging

    monkeypatch.setattr(_server._Requests, '_run', lambda self: None)
    first = _server._Requests()
    kept = first.add('builtin', 'builtin', '5_vs_5', 3)
    stored = json.loads((first._folder / f'{kept["id"]}.json').read_text())
    folder = first._folder
    broken = {
        'r-text-created': {**stored, 'id': 'r-text-created', 'created': 'yesterday'},
        'r-bool-seed': {**stored, 'id': 'r-bool-seed', 'seed': True},
        'r-negative-seed': {**stored, 'id': 'r-negative-seed', 'seed': -1},
        'r-state': {**stored, 'id': 'r-state', 'state': 'paused'},
        'r-ability': {**stored, 'id': 'r-ability', 'ability': [2, None]},
        'r-missing': {key: value for key, value in stored.items() if key != 'scenario'},
        'r-other-name': stored,
        'r-list': [stored],
    }
    broken['r-missing']['id'] = 'r-missing'
    for name, value in broken.items():
        (folder / f'{name}.json').write_text(json.dumps(value))
    (folder / 'r-broken.json').write_text('{')
    leftover = folder / f'{kept["id"]}.json.part'
    leftover.write_text('{"half": ')
    with caplog.at_level(logging.WARNING, logger='cuju'):
        recovered = _server._Requests()
    assert [entry['id'] for entry in recovered.entries()] == [kept['id']]
    assert not leftover.exists()
    skipped = [record.getMessage() for record in caplog.records if record.name == 'cuju']
    assert len(skipped) == len(broken) + 1
    assert any('r-text-created.json' in message and 'created' in message for message in skipped)


def test_request_seeds_beyond_javascript_stay_exact(monkeypatch, render_home):
    monkeypatch.setattr(_server._Requests, '_run', lambda self: None)
    requests = _server._Requests()
    large = requests.add('builtin', 'builtin', '5_vs_5', 2**64 - 1)
    assert large['seed'] == str(2**64 - 1)
    assert requests.entries()[0]['seed'] == str(2**64 - 1)
    stored = json.loads((requests._folder / f'{large["id"]}.json').read_text())
    assert stored['seed'] == 2**64 - 1
    assert _server._Requests().entries()[0]['seed'] == str(2**64 - 1)
    small = requests.add('builtin', 'builtin', '5_vs_5', 2**53 - 1)
    assert small['seed'] == 2**53 - 1
    game = _server._Games._public({'id': 'g', 'seed': 2**53, 'port': 1})
    assert game == {'id': 'g', 'seed': str(2**53)}
    assert _server._Games._public({'seed': None})['seed'] is None
    with pytest.raises(cuju.ArgumentError):
        requests.add('builtin', 'builtin', '5_vs_5', 2**64)


def test_request_disk_error_does_not_prevent_cancel(monkeypatch, render_home):
    monkeypatch.setattr(_server._Requests, '_run', lambda self: None)
    requests = _server._Requests()
    queued = requests.add('builtin', 'builtin', '5_vs_5', 42)
    killed = []

    class Process:
        def kill(self):
            killed.append(True)

    requests._processes[queued['id']] = Process()

    def full(entry):
        raise OSError('disk full')

    monkeypatch.setattr(requests, '_persist', full)
    assert requests.cancel(queued['id'])
    assert killed == [True]
    assert 'disk full' in requests.entries()[0]['persistence_error']
    monkeypatch.setattr(requests, '_play_child', full)
    requests._play(requests._entries[0])
    assert requests.entries()[0]['state'] == 'failed'
    with pytest.raises(OSError):
        requests.add('builtin', 'builtin', '5_vs_5', 1)
    assert len(requests.entries()) == 1


def test_api_methods_and_request_boundaries(render_home):
    """Every route refuses foreign hosts and origins before handling a request."""
    routes = [
        '/api/info',
        '/api/scenarios',
        '/api/models',
        '/api/matches',
        '/api/matches/missing',
        '/api/matches/missing/details',
        '/api/trash',
        '/api/trash/missing',
        '/api/trash/missing/restore',
        '/api/live',
        '/api/live/missing/stream',
        '/api/live/missing/environment',
        '/api/teams',
        '/api/teams/missing',
        '/api/teams/missing/export',
        '/api/teams/missing/duplicate',
        '/api/teams/missing/model',
        '/api/teams/missing/images/shirt-front',
        '/api/teams/missing/sounds/goal',
        '/api/teams/missing/clips/wave',
        '/api/requests',
        '/api/requests/missing',
        '/api/game',
        '/api/game/missing',
        '/api/game/missing/stream',
        '/api/game/missing/input',
        '/api/game/missing/pause',
    ]
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        for method in ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']:
            for path in routes:
                for headers in [
                    {'Host': f'foreign.invalid:{port}'},
                    {'Origin': 'http://foreign.invalid'},
                    {'Origin': 'null'},
                    {'Origin': 'http://127.0.0.1:1'},
                ]:
                    if method == 'GET' and 'Origin' in headers:
                        continue
                    connection = _server.http.client.HTTPConnection('127.0.0.1', port, timeout=5)
                    connection.request(method, path, body=b'{}', headers=headers)
                    response = connection.getresponse()
                    assert response.status == 403, (method, path, headers, response.read())
                    response.read()
                    connection.close()
            connection = _server.http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            connection.request(method, '/api/unknown', body=b'{}')
            response = connection.getresponse()
            assert response.status == 404
            response.read()
            connection.close()
        for origin in [None, f'http://127.0.0.1:{port}']:
            connection = _server.http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            headers = {'Origin': origin} if origin else {}
            connection.request('GET', '/api/info', headers=headers)
            response = connection.getresponse()
            assert response.status == 200
            assert json.loads(response.read()) == {'version': cuju.__version__}
            connection.close()
    finally:
        server.shutdown()
        server.server_close()


def test_responses_refuse_framing_and_bad_announcements_are_skipped(render_home):
    """Every response forbids framing and sniffing, and a bad live announcement spares the list."""
    live = _home.folder('live')
    (live / 'missing.json').write_text('{"id": "missing"}')
    (live / 'text.json').write_text('{"id": "text", "pid": "many"}')
    (live / 'null.json').write_text('{"id": "null", "pid": null}')
    (live / 'list.json').write_text('[1, 2]')
    running = {'id': 'running', 'title': 'a', 'scenario': 'b', 'environment': 0}
    (live / 'running.json').write_text(json.dumps({**running, 'pid': os.getpid()}))
    assert [source['id'] for source in _server._sources()] == ['running']
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_address[1]}'
    expected = {
        'X-Frame-Options': 'DENY',
        'Content-Security-Policy': "frame-ancestors 'none'",
        'X-Content-Type-Options': 'nosniff',
    }
    try:
        for path in ['/', '/api/live', '/api/matches/missing']:
            try:
                with urllib.request.urlopen(address + path, timeout=10) as response:
                    headers = response.headers
            except urllib.error.HTTPError as error:
                headers = error.headers
            assert {name: headers[name] for name in expected} == expected, path
        (listed,) = json.loads(_get(address, '/api/live')[1])
        # An announcement of 0.2.0 lists one environment and the first stream.
        assert listed == {**running, 'environment_count': 1, 'generation': 0}
    finally:
        server.shutdown()
        server.server_close()


def test_request_history_keeps_the_newest_ended_requests(render_home, monkeypatch):
    monkeypatch.setattr(_server._Requests, '_run', lambda self: None)
    monkeypatch.setattr(_server, '_KEPT_REQUESTS', 3)
    requests = _server._Requests()
    ended = []
    for seed in range(5):
        ended.append(requests.add('builtin', 'builtin', '5_vs_5', seed)['id'])
        entry = requests._entries[-1]
        entry.update(state='done', match=f'm-{seed}', progress=1.0, finished=time.time())
        requests._persist(entry)
    waiting = requests.add('builtin', 'builtin', '5_vs_5', 9)['id']
    # The oldest ended requests go with their files, and a waiting one always stays.
    assert [entry['id'] for entry in requests.entries()] == [waiting, *ended[:1:-1]]
    assert sorted(path.stem for path in requests._folder.glob('*.json')) == sorted(
        [waiting, *ended[2:]]
    )
    # A restart interrupts the waiting request, which then counts as ended.
    recovered = _server._Requests()
    assert [entry['id'] for entry in recovered.entries()] == [waiting, ended[4], ended[3]]
    assert len(list(recovered._folder.glob('*.json'))) == 3


def test_page_modules_resolve_and_are_served(render_home):
    """Every module that a page module imports exists and the server sends it as JavaScript."""
    scripts = _server._WEB / 'js'
    found = {path.relative_to(scripts).as_posix() for path in scripts.rglob('*.js')}
    assert {
        'watch/player-tools.js',
        'world/occlusion.js',
        'core/accessibility.js',
        'core/comfort.js',
    } <= found
    for path in scripts.rglob('*.js'):
        pattern = r"""(?:from|import\()\s*'(\.\.?/[\w./-]+\.js)'"""
        for name in re.findall(pattern, path.read_text()):
            assert (path.parent / name).resolve().is_file(), f'{path} imports {name}'
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        for name in sorted(found):
            with urllib.request.urlopen(f'{address}/js/{name}', timeout=10) as response:
                assert response.status == 200
                assert 'javascript' in response.headers['Content-Type']
    finally:
        server.shutdown()
        server.server_close()


def test_demo_streams_on_a_running_server(render_home, capsys):
    """The demo uses a server that answers, streams the built-in AIs and withdraws at its end."""
    from cuju.render._playing import demo as _demo

    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    address = f'http://127.0.0.1:{port}'
    result = []
    thread = threading.Thread(
        target=lambda: result.append(_demo.demo(port, '5_vs_5', False, seed=1, steps=40))
    )
    try:
        thread.start()
        deadline = time.monotonic() + 120
        sources = []
        while not sources and time.monotonic() < deadline:
            sources = json.loads(_get(address, '/api/live')[1])
            time.sleep(0.2)
        assert [source['title'] for source in sources] == [_demo._TITLE]
        with urllib.request.urlopen(
            f'{address}/api/live/{sources[0]["id"]}/stream', timeout=30
        ) as response:
            header = _recording._parse_header(response)
            assert header['scenario'] == '5_vs_5' and len(header['players']) == 10
            assert header['provenance']['source'] == 'live' and header['duration'] == 3000
            assert len(response.read(header['frame_bytes'])) == header['frame_bytes']
        thread.join(60)
        assert result == [0]
        assert json.loads(_get(address, '/api/live')[1]) == []
        assert f'#live={sources[0]["id"]}' in capsys.readouterr().out
    finally:
        thread.join(60)
        server.shutdown()
        server.server_close()


def test_page_serves_the_palette_and_its_stylesheet(render_home):
    """The top bar holds the palette's button, and the server sends the stylesheet it needs."""
    page = (_server._WEB / 'index.html').read_text()
    assert 'id="open-palette"' in page and 'href="easy.css"' in page
    for topic in ('help-keyboard', 'help-start', 'help-teams', 'help-play', 'help-cameras'):
        assert f'id="{topic}"' in page
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        address = f'http://127.0.0.1:{server.server_address[1]}'
        with urllib.request.urlopen(f'{address}/easy.css', timeout=10) as response:
            assert 'text/css' in response.headers['Content-Type']
            assert b'#palette' in response.read()
    finally:
        server.shutdown()
        server.server_close()


def test_grid_through_the_server(render_home):
    batch = cuju.BatchEnvironment('5_vs_5_l1_r0', environment_count=3, device='cpu')
    source = cuju.render.watch(batch)
    batch.reset()
    actions = torch.zeros((3, 1), dtype=torch.int32)
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # A source of 0.2.0, which answers 404 to every path but its stream.
    class Old(_server.http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802, the name that http.server calls
            self.send_error(404)

        def log_message(self, *arguments) -> None:
            pass

    old = _server.http.server.ThreadingHTTPServer(('127.0.0.1', 0), Old)
    threading.Thread(target=old.serve_forever, daemon=True).start()
    announcement = {'id': 'old', 'title': 'old', 'scenario': 'old', 'environment': 0}
    announcement.update(port=old.server_address[1], pid=os.getpid())
    (render_home / 'live' / 'old.json').write_text(json.dumps(announcement))

    def get(port, path, headers=None, body=None):
        connection = _server.http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        try:
            connection.request('GET', path, body, headers or {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    try:
        port = server.server_address[1]
        path = f'/api/live/{source.identifier}/grid'
        status, body = get(port, f'{path}?first=0&count=3')
        assert status == 200 and json.loads(body)['tiles'] == [None] * 3
        status, body = get(port, f'{path}?first=1&count=2')
        document = json.loads(body)
        assert status == 200 and (document['first'], document['count']) == (1, 2)
        batch.step(actions)
        tiles = json.loads(get(port, f'{path}?first=1&count=2')[1])['tiles']
        assert [tile['environment'] for tile in tiles] == [1, 2]
        assert len(tiles[0]['players']) == 20 and tiles[0]['step'] == 1
        for query in ('first=0&count=0', 'first=0&count=65', 'first=3&count=1', 'first=x&count=1'):
            assert get(port, f'{path}?{query}')[0] == 400, query
        assert get(port, f'{path}?first=0')[0] == 400
        assert get(port, '/api/live/missing/grid?first=0&count=1')[0] == 404
        foreign = {'Origin': 'http://foreign.invalid'}
        assert get(port, f'{path}?first=0&count=1', foreign)[0] == 403
        own = {'Origin': f'http://127.0.0.1:{port}'}
        assert get(port, f'{path}?first=0&count=1', own)[0] == 200
        assert get(port, f'{path}?first=0&count=1', {'Host': 'evil.invalid'})[0] == 403
        status, body = get(port, '/api/live/old/grid?first=0&count=1')
        assert status == 404 and b'older cuju' in body
        # The source answers the server alone, without an origin, a body or another host.
        assert get(source.port, '/grid?first=0&count=1', {'Origin': 'null'})[0] == 403
        assert get(source.port, '/grid?first=0&count=1', body=b'x')[0] == 403
        assert get(source.port, '/grid?first=0&count=1', {'Host': 'evil.invalid'})[0] == 403
        assert get(source.port, '/grid?first=0&count=99')[0] == 400
        assert get(source.port, '/grid?first=0&count=1')[0] == 200
    finally:
        server.shutdown()
        server.server_close()
        old.shutdown()
        old.server_close()
        source.close()
        batch.close()
