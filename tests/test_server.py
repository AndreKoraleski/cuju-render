# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the HTTP server, its routes and its checks, and the installable app."""

import gzip
import json
import os
import struct
import threading
import time
import urllib.request

import pytest
import torch

import cuju
import cuju.errors
import cuju.state
from conftest import actions_at
from cuju.render._format import recording as _recording
from cuju.render._http import server as _server
from cuju.render._registry import teams as _teams
from cuju.render._store import home as _home


def _get(address, path):
    with urllib.request.urlopen(address + path, timeout=10) as response:
        return response.status, response.read()


def _send(address, path, data, method='POST'):
    request = urllib.request.Request(address + path, data=data, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


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
    finally:
        server.shutdown()
        server.server_close()


def test_live_stream_through_the_server(render_home):
    batch = cuju.BatchEnvironment('5_vs_5_l4_r0', environment_count=1, device='cpu')
    source = cuju.render.watch(batch, backlog=True)
    batch.reset()
    for step in range(5):
        batch.step(actions_at(step, 1, 4, 19))
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        listed = json.loads(_get(f'http://127.0.0.1:{port}', '/api/live')[1])
        assert [entry['id'] for entry in listed] == [source.identifier]
        connection = _server.http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        connection.request('GET', f'/api/live/{source.identifier}/stream')
        response = connection.getresponse()
        assert response.status == 200
        assert response.read(8) == _recording.MAGIC
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        source.close()
    # A closed source lets go of its batch.
    assert batch._live is None
    batch.close()


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
    requests._lock = threading.Lock()
    requests._processes = {}
    entry = {
        'id': 'race',
        'state': 'queued',
        'left': 'builtin',
        'right': 'builtin',
        'scenario': '5_vs_5',
        'seed': None,
        'ability': [None, None],
        'progress': 0,
        'error': None,
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


def test_api_methods_and_request_boundaries(render_home):
    """Every route refuses foreign hosts and origins before handling a request."""
    routes = [
        '/api/info',
        '/api/scenarios',
        '/api/models',
        '/api/matches',
        '/api/matches/missing',
        '/api/live',
        '/api/live/missing/stream',
        '/api/teams',
        '/api/teams/missing',
        '/api/teams/missing/export',
        '/api/teams/missing/model',
        '/api/teams/missing/images/shirt-front',
        '/api/teams/missing/sounds/goal',
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


def test_api_team_assets_and_missing_resources(render_home):
    """Team assets support upload, download and removal with clear refusals."""
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        team = _send(address, '/api/teams?filename=main.py', b'def agent(obs):\n    return 0\n')
        prefix = f'/api/teams/{team["id"]}'
        model = (_server._WEB / 'assets/player.glb').read_bytes()
        bones = _teams._skin_joints(model)
        joints = urllib.parse.quote(json.dumps({'body': sorted(bones)[0]}))
        for payload, mapping in [(b'bad', joints), (model, '%7B%7D')]:
            with pytest.raises(urllib.error.HTTPError) as error:
                _send(address, f'{prefix}/model?joints={mapping}', payload, 'PUT')
            assert error.value.code == 400
        entry = _send(address, f'{prefix}/model?joints={joints}', model, 'PUT')
        assert entry['model']['bytes'] == len(model)
        assert _get(address, f'{prefix}/model')[1] == model
        for slot, payload in [
            ('images/shirt-front', b'\x89PNG\r\n\x1a\n' + bytes(32)),
            ('sounds/goal', b'OggS' + bytes(60)),
        ]:
            _send(address, f'{prefix}/{slot}', payload, 'PUT')
            assert _get(address, f'{prefix}/{slot}')[1] == payload
        for resource in ['model', 'images/shirt-front', 'sounds/goal']:
            request = urllib.request.Request(f'{address}{prefix}/{resource}', method='DELETE')
            with urllib.request.urlopen(request, timeout=5) as response:
                assert response.status == 204
            for method in ['GET', 'DELETE']:
                request = urllib.request.Request(f'{address}{prefix}/{resource}', method=method)
                with pytest.raises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(request, timeout=5)
                assert error.value.code == 404
        for path in [
            '/api/matches/missing',
            '/api/live/missing/stream',
            '/api/teams/missing/export',
            '/api/game/missing/stream',
        ]:
            with pytest.raises(urllib.error.HTTPError) as error:
                _get(address, path)
            assert error.value.code == 404
        for path in ['/api/matches/missing', '/api/requests/missing', '/api/game/missing']:
            with pytest.raises(urllib.error.HTTPError) as error:
                _send(address, path, b'', 'DELETE')
            assert error.value.code == 404
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
        assert [source['id'] for source in json.loads(_get(address, '/api/live')[1])] == ['running']
    finally:
        server.shutdown()
        server.server_close()
