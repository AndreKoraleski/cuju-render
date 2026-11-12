# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the HTTP server, its routes and its checks, and the installable app."""

import gzip
import hashlib
import json
import logging
import os
import re
import struct
import subprocess
import sys
import threading
import time
import urllib.request

import pytest
import torch

import cuju
import cuju.errors
import cuju.state
from conftest import actions_at, tensor_bytes
from cuju.render import _version
from cuju.render._format import recording as _recording
from cuju.render._http import launch as _launch
from cuju.render._http import server as _server
from cuju.render._registry import teams as _teams
from cuju.render._store import home as _home
from cuju.render._store import library as _library
from cuju.render._watch import live as _live
from support.common import (
    _CRASH,
    _OGG,
    _achievement_frames,
    _achievement_header,
    _challenge_frames,
    _fake_server,
    _get,
    _help_json,
    _help_server,
    _package_team,
    _person_recording,
    _play_to_end,
    _send,
    _shipped_language,
    _toy_team,
    _translation,
    _until,
)

# What `GET /api/info` answers, the version of the renderer, which Home shows, and that of cuju.
INFO = {'version': _version.__version__, 'cuju': cuju.__version__}


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
        assert json.loads(_get(address, '/api/info')[1]) == INFO
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
        sound = _OGG + bytes(60)
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
        # The person's achievements of the game, by the rules that teams earn by.
        assert isinstance(entry['achievements'][0], list) and entry['achievements'][1] is None
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


def test_game_starts_in_a_new_process_when_the_warm_one_cannot(render_home, monkeypatch):
    """A kept process that died, or whose environment changed, gives way to a new process."""
    monkeypatch.setattr(_server, '_GAME_PACE', 400)
    games = _server._Games(warm=True)
    try:
        start = ('5_vs_5', [True, False], [None, None], 2, False, ['builtin', 'builtin'], 50)
        assert _play_to_end(games, games.start(*start))['state'] == 'ended'
        dead = games._spare
        dead.kill()
        dead.wait()
        game = games.start(*start)
        assert games._process is not dead and games._process.pid != dead.pid
        assert _play_to_end(games, game)['state'] == 'ended'
        kept = games._spare
        assert kept is not None and kept.poll() is None
        monkeypatch.setenv('CUJU_RENDER_TEST_MARK', 'changed')
        game = games.start(*start)
        assert games._process is not kept and kept.poll() is not None
        ended = _play_to_end(games, game)
        assert ended['state'] == 'ended' and ended['step'] > 0, ended
    finally:
        games.close()


def test_game_warm_process_ends_with_the_server(render_home, monkeypatch):
    """The kept process ends with the server, after its idle time, and when its input closes."""
    made, spares = [], []

    class Kept(_server._Games):
        def __init__(self, *arguments, **options):
            super().__init__(*arguments, **options)
            made.append(self)

    def stop(server):
        made[0]._prepare()
        spares.append(made[0]._spare)
        raise KeyboardInterrupt

    monkeypatch.setattr(_server, '_Games', Kept)
    monkeypatch.setattr(_server.http.server.ThreadingHTTPServer, 'serve_forever', stop)
    _server.serve(0)
    assert made[0]._warm and spares[0] is not None
    assert spares[0].poll() is not None and made[0]._spare is None
    # A kept process ends after its idle time without a game.
    monkeypatch.setattr(_server, '_WARM_IDLE_SECONDS', 1)
    games = Kept(warm=True)
    try:
        games._prepare()
        idle = games._spare
        assert _until(lambda: games._spare is None and idle.poll() is not None, 30)
    finally:
        games.close()
    # A server that ends without closing it, killed for one, closes its input, and it ends too.
    orphan = _server._Games._spawn(['--warm'])
    orphan.stdin.close()
    assert orphan.wait(timeout=120) == 0
    assert orphan.stdout.read() == ''
    orphan.stdout.close()
    orphan.stderr.close()


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


def test_child_processes_keep_the_home_off_their_path(monkeypatch, render_home):
    """A process of a match, a game or a tournament imports nothing from the renderer's home."""
    from cuju.render._tournaments import tournament_runner as _runner

    seen = []

    class StartError(Exception):
        pass

    def start(command, **options):
        seen.append((command, options.get('cwd')))
        raise StartError

    original = subprocess.Popen
    monkeypatch.setattr(_server.subprocess, 'Popen', start)
    with pytest.raises(StartError):
        _server._Games._spawn(['--warm'])
    requests = object.__new__(_server._Requests)
    requests._folder = _home.folder('requests')
    requests._lock = threading.Lock()
    requests._processes = {}
    entry = {
        'id': 'child',
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
    with pytest.raises(StartError):
        requests._play_child(entry)
    cups = _runner.Tournaments(player=lambda *a: {'score': [0, 0]}, start=False)
    match = {'key': 'k', 'scenario': '5_vs_5', 'seed': 1, 'length': None, 'ability': [None, None]}
    with pytest.raises(StartError):
        cups._play_process(match, ['builtin', 'builtin'], {'id': 'cup-x'}, lambda *a: None)
    cups.close()
    assert len(seen) == 3
    safe = ['-P'] if sys.version_info >= (3, 11) else []
    for command, folder in seen:
        assert command[: 1 + len(safe)] == [sys.executable, *safe], command
        assert command[command.index('-m') + 1].startswith('cuju.render.'), command
        assert folder == _home.process_folder()
    # The folders of the home, such as teams and requests, import as no package in such a process,
    # where a namespace package, which has no origin, would stand for each of them.
    monkeypatch.setattr(_server.subprocess, 'Popen', original)
    names = ('teams', 'matches', 'requests')
    for kind in names:
        _home.folder(kind)
    namespace = '(s := u.find_spec(n)) is not None and s.origin is None'
    probe = f'import importlib.util as u; print(*[{namespace} for n in {names!r}])'

    def namespaces(command, folder):
        found = subprocess.run(
            [*command, '-c', probe],
            cwd=folder,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=60,
        )
        return found.stdout.split().count('True')

    assert namespaces([sys.executable], _home.home()) >= 2
    assert namespaces(_home.python_command(), _home.process_folder()) == 0


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

    monkeypatch.setattr(_server._Requests, '_run', lambda self: None)
    first = _server._Requests()
    kept = first.add('builtin', 'builtin', '5_vs_5', 3)
    stored = json.loads((first._folder / f'{kept["id"]}.json').read_text(encoding='utf-8'))
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
        (folder / f'{name}.json').write_text(json.dumps(value), encoding='utf-8')
    (folder / 'r-broken.json').write_text('{', encoding='utf-8')
    leftover = folder / f'{kept["id"]}.json.part'
    leftover.write_text('{"half": ', encoding='utf-8')
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
    stored = json.loads((requests._folder / f'{large["id"]}.json').read_text(encoding='utf-8'))
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
        '/api/help/samples',
        '/api/help/tutorial',
        '/api/help/doctor',
        '/api/help/app',
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
            assert json.loads(response.read()) == INFO
            connection.close()
    finally:
        server.shutdown()
        server.server_close()


def test_responses_refuse_framing_and_bad_announcements_are_skipped(render_home):
    """Every response forbids framing and sniffing, and a bad live announcement spares the list."""
    live = _home.folder('live')
    (live / 'missing.json').write_text('{"id": "missing"}', encoding='utf-8')
    (live / 'text.json').write_text('{"id": "text", "pid": "many"}', encoding='utf-8')
    (live / 'null.json').write_text('{"id": "null", "pid": null}', encoding='utf-8')
    (live / 'list.json').write_text('[1, 2]', encoding='utf-8')
    running = {'id': 'running', 'title': 'a', 'scenario': 'b', 'environment': 0, 'port': 8781}
    (live / 'running.json').write_text(
        json.dumps({**running, 'pid': os.getpid()}), encoding='utf-8'
    )
    # An announcement of a running process with any field the server cannot read is skipped alone.
    for name, change in [
        ('untitled', {'title': None}),
        ('portless', {'port': None}),
        ('textport', {'port': '8781'}),
        ('boolport', {'port': True}),
        ('lowport', {'port': 22}),
        ('highport', {'port': 70000}),
        ('environs', {'environment': '0'}),
        ('counted', {'environment_count': 1.5}),
        ('outside', {'id': '../../x'}),
    ]:
        bad = {**running, 'id': name, 'pid': os.getpid(), **change}
        (live / f'{name}.json').write_text(json.dumps(bad), encoding='utf-8')
    keyless = {**running, 'id': 'keyless', 'pid': os.getpid()}
    del keyless['scenario']
    (live / 'keyless.json').write_text(json.dumps(keyless), encoding='utf-8')
    assert [source['id'] for source in _server._sources()] == ['running']
    # The list leaves the port out.
    del running['port']
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


def test_show_attaches_sources_and_reuses_them(render_home, monkeypatch):
    """`show` attaches one live source per environment and closes only the one it attached."""
    started = []

    def start(port, stay, colab=False):
        started.append((port, stay, colab))
        return _fake_server(render_home)

    monkeypatch.setattr(_launch, 'start', start)
    batch = cuju.BatchEnvironment('5_vs_5_l1_r0', environment_count=2, device='cpu')
    with cuju.render.show(batch, environment=1, display='none', stay=True) as view:
        assert view.url == f'http://127.0.0.1:8999/#live={view.source.identifier}'
        assert view.source.environment == 1 and view.source in batch.observers
        again = cuju.render.show(batch, environment=1, display='none')
        assert again.source is view.source
        again.close()
        assert view.source in batch.observers
    assert view.source not in batch.observers
    assert started == [(None, True, False), (None, False, False)]
    assert cuju.render.show(display='none').url.endswith('/#page=home')
    with pytest.raises(cuju.ArgumentError, match='display'):
        cuju.render.show(display='window')
    with pytest.raises(cuju.ArgumentError, match='MultiDeviceBatch'):
        cuju.render.show(3, display='none')


def test_show_starts_a_server_that_ends_with_its_process(render_home):
    """A server that `show` starts answers, is found again, and ends with its parent."""
    view = cuju.render.show(display='none')
    try:
        server = view.server
        # A Python of a virtual environment on Windows runs the server beneath the process that
        # show made, so the server file names the call that started it.
        entry = json.loads((render_home / _launch.SERVER_FILE).read_text(encoding='utf-8'))
        assert server.process is not None and entry['pid'] == server.pid and entry['starter']
        assert _launch.running().pid == server.pid
        assert cuju.render.show('sample-5v5', display='none').server.pid == server.pid
        _, body = _get(server.url[:-1], '/api/matches')
        assert 'sample-5v5' in {entry['id'] for entry in json.loads(body)}
    finally:
        _launch._stop(view.server.process)
    assert _launch.running() is None
    # A server whose parent is gone stops by itself and withdraws its file.
    child = subprocess.Popen([sys.executable, '-c', 'pass'])
    child.wait()
    finished = threading.Event()

    def serve():
        _server.serve(0, parent=child.pid)
        finished.set()

    threading.Thread(target=serve, daemon=True).start()
    assert finished.wait(30)
    assert not (render_home / _launch.SERVER_FILE).exists()


def test_framed_page_and_proxied_origin(render_home):
    """Only the page asked for with the server's key may sit in a notebook's frame."""
    server = _launch.LoopbackServer(('127.0.0.1', 0), _server.make_handler(_server._Requests()))
    server.frame_key = 'secret-key'
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    address = f'http://127.0.0.1:{port}'
    try:
        for path, framed in [
            ('/?embed=secret-key', True),
            ('/index.html?embed=secret-key', True),
            ('/?embed=other', False),
            ('/', False),
            ('/js/main.js?embed=secret-key', False),
        ]:
            with urllib.request.urlopen(address + path, timeout=10) as response:
                policy = response.headers['Content-Security-Policy']
                denied = response.headers['X-Frame-Options']
            if framed:
                assert policy == f'frame-ancestors {_launch.FRAME_ANCESTORS}', path
                assert denied is None, path
            else:
                assert (policy, denied) == ("frame-ancestors 'none'", 'DENY'), path
        # Colab's proxy shows the page under https at the same loopback host and port.
        for origin, allowed in [
            (f'https://127.0.0.1:{port}', True),
            ('https://example.com', False),
        ]:
            request = urllib.request.Request(
                f'{address}/api/teams/builtin/duplicate', method='POST', headers={'Origin': origin}
            )
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    answered = response.status
            except urllib.error.HTTPError as error:
                answered = error.code
            assert (answered != 403) == allowed, (origin, answered)
        # Inside Colab the server also answers the names of Colab's proxy, and only then.
        proxy = 'abc-8780-colab.googleusercontent.com'
        for domains, allowed in [((), False), (_launch.COLAB_DOMAINS, True)]:
            server.proxy_domains = domains
            for path, headers in [
                ('/api/info', {'Host': proxy}),
                ('/api/teams/builtin/duplicate', {'Host': proxy, 'Origin': f'https://{proxy}'}),
            ]:
                method = 'POST' if 'Origin' in headers else 'GET'
                request = urllib.request.Request(address + path, method=method, headers=headers)
                try:
                    with urllib.request.urlopen(request, timeout=10) as response:
                        answered = response.status
                except urllib.error.HTTPError as error:
                    answered = error.code
                assert (answered != 403) == allowed, (domains, headers, answered)
        # A page of another notebook, under another name of Colab's domains, changes nothing.
        server.proxy_domains = _launch.COLAB_DOMAINS
        for host, origin in [
            (proxy, 'https://evil-8780-colab.googleusercontent.com'),
            (proxy, 'https://abc.colab.dev'),
            (f'127.0.0.1:{port}', f'https://{proxy}'),
            (proxy.upper(), 'https://evil.colab.dev'),
        ]:
            request = urllib.request.Request(
                f'{address}/api/teams/builtin/duplicate',
                method='POST',
                headers={'Host': host, 'Origin': origin},
            )
            with pytest.raises(urllib.error.HTTPError) as refused:
                urllib.request.urlopen(request, timeout=10)
            assert refused.value.code == 403, (host, origin)
    finally:
        server.shutdown()
        server.server_close()


def test_open_targets(render_home, tmp_path):
    _library.add_samples()
    assert _launch.resolve(None) == '#page=home'
    assert _launch.resolve('sample-5v5') == '#match=sample-5v5'
    assert _launch.resolve('http://127.0.0.1:8780/#live=a') == 'http://127.0.0.1:8780/#live=a'
    copy = tmp_path / 'final.cjr'
    copy.write_bytes((_library._SAMPLES / 'sample-5v5.cjr').read_bytes())
    # A file whose bytes the library holds opens that recording.
    assert _launch.resolve(copy) == '#match=sample-5v5'
    assert _launch.resolve(_library.path_of('sample-5v5')) == '#match=sample-5v5'
    _library.trash('sample-5v5')
    fragment = _launch.resolve(str(copy))
    identifier = fragment.removeprefix('#match=')
    assert identifier != 'sample-5v5'
    assert _library.path_of(identifier).read_bytes() == copy.read_bytes()
    assert _launch.resolve(str(copy)) == fragment
    assert _library.details(identifier)['steps'] > 0
    with pytest.raises(cuju.ArgumentError, match='Trash'):
        _launch.resolve('sample-5v5')
    with pytest.raises(cuju.ArgumentError, match='no file'):
        _launch.resolve(str(tmp_path / 'missing.cjr'))
    other = tmp_path / 'notes.cjr'
    other.write_bytes(b'not a recording')
    with pytest.raises(cuju.ArgumentError, match='other bytes'):
        _launch.resolve(other)
    with pytest.raises(cuju.ArgumentError, match='names none'):
        _launch.resolve('nothing-here')
    batch = cuju.BatchEnvironment('5_vs_5_l1_r0', environment_count=1, device='cpu')
    with cuju.render.watch(batch) as source:
        assert _launch.resolve(source.identifier) == f'#live={source.identifier}'


def test_render_command_line(render_home, tmp_path, monkeypatch, capsys):
    from cuju.render import __main__ as command

    opened, served = [], []
    monkeypatch.setattr(_launch, 'open_browser', lambda url: opened.append(url) or True)

    def serve(*arguments, **options):
        served.append((arguments, options))

    monkeypatch.setattr(_server, 'serve', serve)
    _library.add_samples()
    assert command.main(['open', 'sample-5v5']) == 0
    assert command.main([]) == 0
    assert served == [((8780, True), {'page': '#match=sample-5v5'}), ((8780, True), {})]
    assert command.main(['open', 'http://127.0.0.1:8790/#live=a']) == 0
    assert served[-1] == ((8790, True), {'page': '#live=a'})
    monkeypatch.setattr(_launch, 'running', lambda: _fake_server(render_home))
    assert command.main(['open', 'sample-5v5']) == 0
    assert command.main([]) == 0
    assert opened == ['http://127.0.0.1:8999/#match=sample-5v5', 'http://127.0.0.1:8999/']
    assert len(served) == 3
    capsys.readouterr()
    assert command.main(['open', 'missing.cjr']) == 1
    assert 'no file' in capsys.readouterr().err
    blocker = tmp_path / 'blocker'
    blocker.write_text('', encoding='utf-8')
    assert command.main(['--home', str(blocker / 'render'), 'team', 'list']) == 1
    message = capsys.readouterr().err
    assert 'is a file' in message and '--home' in message


def test_port_in_use_and_remote_use(render_home, monkeypatch, capsys):
    import socket

    from cuju.render import __main__ as command

    with socket.socket() as taken:
        taken.bind(('127.0.0.1', 0))
        taken.listen()
        port = taken.getsockname()[1]
        assert not _launch.port_free(port)
        assert command.main(['serve', '--port', str(port)]) == 1
        message = capsys.readouterr().err
        assert f'port {port} is in use by another program' in message
        assert f'--port {port + 10}' in message and '--port 0' in message
    monkeypatch.setenv('SSH_CONNECTION', '10.0.0.2 51000 10.0.0.9 2222')
    monkeypatch.setattr(_launch.getpass, 'getuser', lambda: 'ana')
    assert _launch.tunnel_command(8780) == 'ssh -N -L 8780:127.0.0.1:8780 -p 2222 ana@10.0.0.9'
    original = _launch.LoopbackServer.serve_forever

    def visited(server):
        thread = threading.Thread(target=original, args=(server,))
        thread.start()
        assert (render_home / _launch.SERVER_FILE).exists()
        _get(f'http://127.0.0.1:{server.server_address[1]}', '/')
        server.shutdown()
        thread.join()

    monkeypatch.setattr(_launch.LoopbackServer, 'serve_forever', visited)
    assert command.main(['serve', '--port', '0', '--remote']) == 0
    printed = capsys.readouterr().out
    assert 'ssh -N -L' in printed and 'ana@10.0.0.9' in printed
    assert 'A browser reached the page' in printed
    assert not (render_home / _launch.SERVER_FILE).exists()


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


def test_page_sounds_of_the_play_stop_on_a_seek():
    """The events of the play sound as voices, which a seek, a restart or a new match fades out.

    tests/web/voices.mjs runs the voices themselves.
    """
    scripts = _server._WEB / 'js'
    audio = (scripts / 'broadcast/audio.js').read_text(encoding='utf-8')
    main = (scripts / 'main.js').read_text(encoding='utf-8')
    assert "import { Voices } from './voices.js';" in audio
    events = re.search(r'const EVENT_LENGTH = \{([^}]*)\}', audio).group(1)
    for name in ('whistle', 'goal', 'ooh', 'applause', 'fanfare', 'teamSound'):
        assert re.search(rf'\b{name}: \d', events), name
    assert 'this.voices.tap(' in audio and 'this.sound.voices.tap(' in audio
    assert 'this.sound.voices.later(fn)' in audio
    seek = main[main.index('    afterSeek() {') :]
    assert 'this.sound.stopEvents();' in seek[: seek.index('\n    }\n')]
    source = main[main.index('    async setSource(source) {') :]
    assert 'this.sound.stopEvents();' in source[: source.index('this.source = source;')]


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
        for name in re.findall(pattern, path.read_text(encoding='utf-8')):
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
    page = (_server._WEB / 'index.html').read_text(encoding='utf-8')
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
    (render_home / 'live' / 'old.json').write_text(json.dumps(announcement), encoding='utf-8')

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


def test_presentation_routes_and_sandbox_policy(render_home):
    """The server serves a package and a framable sandbox whose policy keeps it off the network."""
    import base64

    team = _package_team()
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        status, body = _get(address, f'/api/teams/{team["id"]}/presentation')
        served = json.loads(body)
        assert status == 200 and served['manifest']['name'] == 'Test package'
        prefix = f'{address}/api/teams/{team["id"]}/presentation'
        # The worker goes out as text, which no page runs by its address, the worklet that the
        # page loads by its address as JavaScript.
        with urllib.request.urlopen(f'{prefix}/worker.js', timeout=10) as response:
            assert response.headers['Content-Type'] == 'text/plain; charset=utf-8'
            assert b'export function frame' in response.read()
        with urllib.request.urlopen(f'{prefix}/audio/hum.js', timeout=10) as response:
            assert response.headers['Content-Type'] == 'text/javascript'
        with urllib.request.urlopen(f'{prefix}/models/halo.glb', timeout=10) as response:
            assert response.headers['Content-Type'] == 'model/gltf-binary'
        for path in ('presentation/missing.js', 'presentation/..%2Fteam.json', 'presentation/../x'):
            with pytest.raises(urllib.error.HTTPError) as error:
                _get(address, f'/api/teams/{team["id"]}/{path}')
            assert error.value.code in (403, 404)
        plain = _teams.add('Plain', 'main.py', b'def agent(obs):\n    return [0]\n')
        assert (
            json.loads(_get(address, f'/api/teams/{plain["id"]}/presentation')[1])['manifest']
            is None
        )
        with urllib.request.urlopen(f'{address}/sandbox/presentation', timeout=10) as reply:
            page = reply.read().decode()
            policy = reply.headers.get_all('Content-Security-Policy')
            framing = reply.headers.get('X-Frame-Options')
        assert len(policy) == 1 and framing is None
        assert "connect-src 'none'" in policy[0]
        # Opened as a whole window, the sandbox still has an opaque origin and no opener.
        assert policy[0].startswith('sandbox allow-scripts;')
        assert reply.headers.get('Cross-Origin-Opener-Policy') == 'same-origin'
        assert "self.origin !== 'null'" in page and 'e.source !== window.parent' in page
        # A viewer in the frame of a notebook starts its sandbox there too.
        assert f'frame-ancestors {_launch.FRAME_ANCESTORS};' in policy[0]
        script = page.split('<script>', 1)[1].rsplit('</script>', 1)[0]
        digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        assert f"script-src 'sha256-{digest}' blob:" in policy[0]
        # Every other response still refuses framing.
        with urllib.request.urlopen(f'{address}/js/presentation/host.js', timeout=10) as reply:
            assert reply.headers.get('X-Frame-Options') == 'DENY'
            assert reply.headers.get_all('Content-Security-Policy') == ["frame-ancestors 'none'"]
        with urllib.request.urlopen(f'{address}/', timeout=10) as reply:
            assert reply.headers.get('Cross-Origin-Opener-Policy') == 'same-origin'
        # The service worker carries the digest of each file as the server serves it.
        with urllib.request.urlopen(f'{address}/sw.js?build=x', timeout=10) as reply:
            worker = reply.read().decode()
        assert 'const DIGESTS = null;' not in worker
        filled = json.loads(worker.split('const DIGESTS = ', 1)[1].split(';' + chr(10), 1)[0])
        for name in ('index.html', 'js/main.js'):
            with urllib.request.urlopen(f'{address}/{name}', timeout=10) as reply:
                assert filled[name] == hashlib.sha256(reply.read()).hexdigest(), name
        request = urllib.request.Request(
            f'{address}/api/teams/{team["id"]}/presentation', headers={'Host': 'example.com'}
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=10)
        assert error.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def _mock_server():
    """Returns the mock server of `ci`, loaded from its file as the page checks start it."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / 'ci' / 'mock_server.py'
    spec = importlib.util.spec_from_file_location('cuju_test_mock_server', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_mock_server_sends_the_headers_of_the_server(render_home):
    """The page checks run against the mock, so its answers say who may frame them as the server's.

    A page that the server forbids to frame, and that a page of its own frames anyway, then fails
    its check rather than only the real server.
    """
    from support.package import package_zip

    mock = _mock_server()
    real_team = _package_team()['id']
    mock_team = mock.add('Test package', 'team.zip', package_zip())['id']
    real = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    fake = mock.ReusedThreadsServer(('127.0.0.1', 0), mock.make_handler(mock.Requests()))
    for running in (real, fake):
        threading.Thread(target=running.serve_forever, daemon=True).start()

    def answer(server, path):
        address = f'http://127.0.0.1:{server.server_address[1]}'
        with urllib.request.urlopen(address + path, timeout=10) as response:
            response.read()
            return sorted(
                (name, value)
                for name, value in response.headers.items()
                if name not in ('Date', 'Server', 'Content-Length')
            )

    try:
        for path in [
            '/',
            '/index.html',
            '/?feed=1',
            '/feed',
            '/?capture=1&export=1&safe=0',
            '/?capture=1',
            '/export.html',
            '/js/main.js',
            '/js/export/video-browser.js',
            '/style.css',
            '/sandbox/presentation',
            '/api/teams/{team}/presentation/worker.js',
            '/api/teams/{team}/presentation/audio/hum.js',
            '/api/teams/{team}/presentation/models/halo.glb',
            '/api/scenarios',
        ]:
            served = answer(real, path.format(team=real_team))
            assert answer(fake, path.format(team=mock_team)) == served, path
            assert ('Cross-Origin-Opener-Policy', 'same-origin') in served, path
    finally:
        for running in (real, fake):
            running.shutdown()
            running.server_close()


def test_engine_outputs_stay_identical_while_a_package_plays(render_home):
    """A batch played by a package team and watched while its package is served stays exact."""
    team = _package_team()
    agent = _teams.load_agent(team['id'])
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_address[1]}'
    stop = threading.Event()

    def page():
        # A page that plays the package reads its manifest, files and sandbox again and again.
        while not stop.is_set():
            for path in (
                f'/api/teams/{team["id"]}/presentation',
                f'/api/teams/{team["id"]}/presentation/worker.js',
                f'/api/teams/{team["id"]}/presentation/models/halo.glb',
                '/sandbox/presentation',
            ):
                _get(address, path)

    outputs = []
    try:
        for watched in (False, True):
            stop.clear()
            batch = cuju.BatchEnvironment(
                '5_vs_5_l4_r0', environment_count=2, seed=11, device='cpu'
            )
            viewer = None
            if watched:
                source = cuju.render.watch(batch, environment=1)
                viewer = _live._Viewer()
                source._viewers.append(viewer)
                threading.Thread(target=page, daemon=True).start()
            seen = [tensor_bytes(batch.reset())]
            for step in range(80):
                if viewer is not None:
                    while not viewer.frames.empty():
                        viewer.frames.get_nowait()
                actions = actions_at(step, 2, 4, 19)
                actions[:, 0] = int(agent({})[0])
                observation, reward, done, _ = batch.step(actions)
                seen += [tensor_bytes(observation), tensor_bytes(reward), tensor_bytes(done)]
            seen += [batch.get_state(0), batch.get_state(1)]
            outputs.append(seen)
            stop.set()
            batch.close()
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
    assert outputs[0] == outputs[1]


def test_page_preview_panel_speaks_the_page_language():
    """Every level, status, rung, budget and event of the preview panel has a message."""
    scripts = _server._WEB / 'js' / 'presentation'
    preview = (scripts / 'preview.js').read_text(encoding='utf-8')
    budget = (scripts / 'budget.js').read_text(encoding='utf-8')
    assert 'formatNumber' in preview and '.toFixed(' not in preview
    ladder = re.search(r'export const LADDER = \[([^\]]*)\]', budget).group(1)
    kinds = re.search(r'const KINDS = \[([^\]]*)\]', preview).group(1)
    events = re.search(r'export const EVENTS = \[([^\]]*)\]', preview).group(1)

    def names(text):
        return re.findall(r"'([^']+)'", text)

    wanted = [f'rung.{k}' for k in names(ladder)] + [f'kind.{k}' for k in names(kinds)]
    wanted += [f'event.{k}' for k in names(events)]
    wanted += [f'level.{k}' for k in ('worker', 'manifest', 'stock')]
    wanted += [f'status.{k}' for k in ('none', 'starting', 'ready', 'restarting', 'stopped')]
    wanted += [f'status.{k}' for k in ('failed', 'disposed')]
    for code in ('en', 'pt-BR'):
        messages = _shipped_language(code) if code == 'en' else _translation(code)
        missing = [k for k in wanted if f'presentation.preview.{k}' not in messages]
        assert missing == [], (code, missing)
    assert 'presentation.notice.workerResting' in messages


def test_challenge_server_routes(render_home, tmp_path):
    from cuju.render._playing import challenges as _challenges

    challenge = _challenges.find('one_on_one')
    first = _person_recording(challenge, 0, _challenge_frames(goal_at=12, length=30))
    second = _person_recording(challenge, 1, _challenge_frames())
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    address = f'http://127.0.0.1:{port}'
    try:
        listed = json.loads(_get(address, '/api/challenges?person=Ana')[1])
        assert [entry['id'] for entry in listed] == [entry['id'] for entry in _challenges.CATALOG]
        assert listed[0]['seeds'] and listed[0]['board'] == {
            'entries': 0,
            'people': 0,
            'agents': 0,
            'top': [],
            'mine': None,
        }
        score = json.loads(
            _get(address, f'/api/challenges/one_on_one/score?match={first}&attempt=0')[1]
        )
        assert score['result']['seconds'] == 1.2 and score['problem'] is None
        for path, code in (
            ('/api/challenges/no_such', 404),
            ('/api/challenges/one_on_one/score?match=m-missing&attempt=0', 404),
            (f'/api/challenges/one_on_one/score?match={first}&attempt=7', 400),
        ):
            with pytest.raises(urllib.error.HTTPError) as refused:
                _get(address, path)
            assert refused.value.code == code
        run = json.dumps({'person': 'Ana', 'matches': [first, second, None]}).encode()
        for headers in ({'Origin': 'https://example.com'}, {'Host': f'evil.example:{port}'}):
            other = _server.http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            other.request('POST', '/api/challenges/one_on_one/runs', body=run, headers=headers)
            assert other.getresponse().status == 403
            other.close()
        for wrong in (
            {'person': 'Ana', 'matches': [first, first, None]},
            {'person': 'Ana'},
            {'team': 'builtin', 'attempts': 9},
            {'team': 'no-such-team'},
            {'person': 'Ana', 'matches': [first, second, None], 'extra': 1},
        ):
            with pytest.raises(urllib.error.HTTPError) as refused:
                _send(address, '/api/challenges/one_on_one/runs', json.dumps(wrong).encode())
            assert refused.value.code == 400, wrong
        outcome = _send(address, '/api/challenges/one_on_one/runs', run)
        assert outcome['rank'] == 1 and outcome['value'] == 1
        board = json.loads(_get(address, '/api/challenges/one_on_one')[1])
        assert [entry['name'] for entry in board['entries']] == ['Ana']
        mine = json.loads(_get(address, '/api/challenges?person=Ana')[1])
        assert next(e for e in mine if e['id'] == 'one_on_one')['board']['mine']['rank'] == 1
        # A team's run plays in a child process, and the page follows it.
        job = _send(address, '/api/challenges/corner/runs', b'{"team": "builtin", "attempts": 1}')
        waiting = _send(address, '/api/challenges/one_on_one/runs', b'{"team": "builtin"}')
        request = urllib.request.Request(
            f'{address}/api/challenges/jobs/{waiting["id"]}', method='DELETE'
        )
        with urllib.request.urlopen(request, timeout=10) as answer:
            assert answer.status == 200
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            jobs = {
                entry['id']: entry for entry in json.loads(_get(address, '/api/challenges/jobs')[1])
            }
            if jobs[job['id']]['state'] in ('done', 'failed'):
                break
            time.sleep(0.5)
        done = jobs[job['id']]
        assert done['state'] == 'done', done
        assert done['result']['practice'] and len(done['results']) == 1
        assert (
            jobs[waiting['id']]['state'] == 'failed' and jobs[waiting['id']]['error'] == 'cancelled'
        )
        recording = render_home / 'matches' / f'{done["results"][0]["match"]}.cjr'
        assert _recording.read_header(recording)['provenance']['source'] == 'challenge'
        with pytest.raises(urllib.error.HTTPError) as refused:
            request = urllib.request.Request(
                f'{address}/api/challenges/jobs/j-none', method='DELETE'
            )
            urllib.request.urlopen(request, timeout=10)
        assert refused.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_challenge_group_routes(render_home):
    from cuju.render._playing import challenges as _challenges

    challenge = _challenges.find('one_on_one')
    matches = [
        _person_recording(challenge, 0, _challenge_frames(goal_at=12, length=30)),
        _person_recording(challenge, 1, _challenge_frames()),
        None,
    ]
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        run = json.dumps({'person': 'Ana', 'matches': matches}).encode()
        group = _send(address, '/api/challenges/one_on_one/runs', run)['group']
        listed = json.loads(_get(address, '/api/matches')[1])
        assert {entry['group']['id'] for entry in listed if 'group' in entry} == {group}
        members = json.loads(_get(address, f'/api/matches?group={group}')[1])
        assert [entry['id'] for entry in members] == matches[:2]
        trashed = _send(address, f'/api/groups/{group}', None, method='DELETE')
        assert trashed['group'] == group and sorted(trashed['trashed']) == sorted(matches[:2])
        assert json.loads(_get(address, f'/api/matches?group={group}')[1]) == []
        assert len(json.loads(_get(address, f'/api/trash?group={group}')[1])) == 2
        for method, path in (
            ('DELETE', f'/api/groups/{group}'),
            ('POST', '/api/groups/g-x/restore'),
        ):
            with pytest.raises(urllib.error.HTTPError) as refused:
                _send(address, path, b'' if method == 'POST' else None, method=method)
            assert refused.value.code == 404
        restored = _send(address, f'/api/groups/{group}/restore', b'')
        assert sorted(restored['restored']) == sorted(matches[:2])
        # A person's run without recordings and a left run, over HTTP.
        again = [
            _person_recording(challenge, 0, _challenge_frames(goal_at=12, length=30)),
            None,
            None,
        ]
        body = {'person': 'Ana', 'matches': again, 'keep_recordings': False}
        outcome = _send(address, '/api/challenges/one_on_one/runs', json.dumps(body).encode())
        assert outcome['group'] is None and _library.path_of(again[0]) is None
        left = [_person_recording(challenge, 0, _challenge_frames())]
        body = {'person': 'Ana', 'matches': left}
        answer = _send(address, '/api/challenges/one_on_one/leave', json.dumps(body).encode())
        assert answer['group'] and answer['removed'] == []
        with pytest.raises(urllib.error.HTTPError) as refused:
            body = {'person': 'Ana', 'matches': left, 'keep_recordings': 'yes'}
            _send(address, '/api/challenges/one_on_one/leave', json.dumps(body).encode())
        assert refused.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_achievements_through_the_server(render_home):
    from cuju.render._playing import achievements as _achievements

    frames = _achievement_frames(60, goals=[(10, 0, 1)])
    _achievements.award_match(_achievement_header(), frames, ['t-left', 't-right'], 'm-x')
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        address = f'http://127.0.0.1:{server.server_address[1]}'
        listed = json.loads(_get(address, '/api/achievements')[1])
        assert len(listed['catalog']) == len(_achievements.CATALOG)
        assert set(listed['teams']) == {'t-left'}
        assert set(listed['teams']['t-left']) == {'off_the_mark', 'giant_slayer', 'clean_sheet'}
    finally:
        server.shutdown()
        server.server_close()


def test_installable_page_files_build_and_routes(render_home, tmp_path, monkeypatch):
    from cuju.render._http import pwa as _pwa

    web = _server._WEB
    manifest = json.loads((web / 'manifest.webmanifest').read_text(encoding='utf-8'))
    assert manifest['display'] == 'standalone' and manifest['start_url'] == './#page=home'
    # tests/test_app.py checks the icons themselves.
    assert all((web / icon['src']).is_file() for icon in manifest['icons'])
    assert '<link rel="manifest" href="manifest.webmanifest">' in (web / 'index.html').read_text(
        encoding='utf-8'
    )
    # The build follows every file of the page.
    copy = tmp_path / 'web'
    copy.mkdir()
    (copy / 'index.html').write_text('one', encoding='utf-8')
    monkeypatch.setattr(_pwa, '_WEB', copy)
    monkeypatch.setitem(_pwa._HELD, 'at', -10.0)
    first = _pwa.build()
    assert _pwa.build() == first
    (copy / 'index.html').write_text('two!', encoding='utf-8')
    monkeypatch.setitem(_pwa._HELD, 'at', -10.0)
    assert _pwa.build() != first
    monkeypatch.setattr(_pwa, '_WEB', web)
    monkeypatch.setitem(_pwa._HELD, 'at', -10.0)
    server, address = _help_server()
    try:
        status, info = _help_json(address, '/api/help/app')
        assert status == 200 and info['version'] == _version.__version__
        assert len(info['build']) == 16
        with urllib.request.urlopen(address + '/manifest.webmanifest', timeout=10) as response:
            assert response.headers['Content-Type'] == 'application/manifest+json'
        with urllib.request.urlopen(address + '/sw.js', timeout=10) as response:
            assert response.headers['Cache-Control'] == 'no-cache'
            assert b'cuju-page-' in response.read()
        with urllib.request.urlopen(address + '/index.html', timeout=10) as response:
            assert response.headers.get('Cache-Control') is None
    finally:
        server.shutdown()
        server.server_close()


def test_a_stale_server_file_goes_once_its_process_ended(render_home):
    render_home.mkdir(parents=True, exist_ok=True)
    path = render_home / _launch.SERVER_FILE
    dead = subprocess.run(
        [sys.executable, '-c', 'import os; print(os.getpid())'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=True,
    )
    path.write_text(
        json.dumps({'port': 8999, 'pid': int(dead.stdout), 'key': 'k'}), encoding='utf-8'
    )
    assert _launch.running() is None
    assert not path.exists()


def test_server_error_answers_carry_message_ids(render_home):
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_address[1]}'

    def refused(path, data=None, method='GET'):
        request = urllib.request.Request(address + path, data=data, method=method)
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=10)
        return caught.value.code, json.loads(caught.value.read())

    try:
        assert refused('/api/nothing') == (
            404,
            {'error': 'no such resource', 'error_id': 'server.no_resource', 'error_values': {}},
        )
        status, body = refused('/api/requests', b'{"scenario": "nowhere"}', 'POST')
        assert status == 400 and body == {
            'error': "expected a shipped scenario, found 'nowhere'",
            'error_id': 'server.scenario',
            'error_values': {'scenario': "'nowhere'"},
        }
        status, body = refused('/api/matches/zzz', b'{"title": "x"}', 'PATCH')
        assert status == 400 and body['error'] == "expected a recording of the library, found 'zzz'"
        assert (body['error_id'], body['error_values']) == (
            'server.library.unknown',
            {'identifier': "'zzz'"},
        )
        status, body = refused('/api/requests/r-none', method='DELETE')
        assert (status, body['error'], body['error_id']) == (404, 'no such item', 'server.no_item')
        # A limit that is no number names its message.
        status, body = refused('/api/search?limit=x')
        assert (status, body['error_id']) == (400, 'server.search.limit')
        status, body = refused('/api/help/samples', b'{"names": 3}', 'POST')
        assert status == 400 and body == {
            'error': 'expected names as a list of samples, found 3',
            'error_id': 'server.help.sample_names',
            'error_values': {'names': '3'},
        }
    finally:
        server.shutdown()
        server.server_close()


def test_interrupted_requests_carry_message_ids(render_home):
    folder = _home.folder('requests')
    base = {
        'left': 'builtin',
        'right': 'builtin',
        'scenario': '11_vs_11_kaggle',
        'seed': 1,
        'ability': [None, None],
        'progress': 0.0,
        'match': None,
        'error': None,
        'created': 1.0,
        'started': None,
        'finished': None,
    }
    # A request of an earlier version lacks the id fields and loads all the same.
    (folder / 'r-old.json').write_text(
        json.dumps({**base, 'id': 'r-old', 'state': 'queued'}), encoding='utf-8'
    )
    done = {**base, 'id': 'r-done', 'state': 'failed', 'error': 'cancelled', 'created': 2.0}
    (folder / 'r-done.json').write_text(json.dumps(done), encoding='utf-8')
    entries = {entry['id']: entry for entry in _server._Requests().entries()}
    assert entries['r-old']['error'] == 'interrupted by a server restart'
    assert (entries['r-old']['error_id'], entries['r-old']['error_values']) == (
        'server.requests.interrupted',
        {},
    )
    assert entries['r-done']['error'] == 'cancelled'
    assert (entries['r-done']['error_id'], entries['r-done']['error_values']) == (None, None)
    stored = json.loads((folder / 'r-old.json').read_text(encoding='utf-8'))
    assert stored['error_id'] == 'server.requests.interrupted'
    assert _server._stored_request(folder / 'r-old.json')['error_values'] == {}


# The languages of the page.

_LITERAL = r"(?:'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"|`(?:[^`\\\n]|\\.)*`)"
# The places of a module where a literal reaches people, its text, title, label, placeholder,
# a toast or a child of an element made by the element helpers.
_SHOWN = [
    re.compile(pattern)
    for pattern in (
        rf'\.(?:textContent|innerText|title|placeholder|ariaLabel|alt)\s*=\s*({_LITERAL})',
        rf"setAttribute\(\s*'(?:aria-label|title|placeholder|alt|aria-description)'\s*,\s*({_LITERAL})",
        rf"['\"]?(?:aria-label|title|placeholder|alt|text|label|hint|note|tip)['\"]?\s*:\s*({_LITERAL})",
        rf'\b(?:toast|alert|confirm|announce|setWaiting|showLoading|notice)\(\s*({_LITERAL})',
        rf'\b(?:h|el|menuItem|menuHeading)\(\s*{_LITERAL}\s*,\s*(?:\{{[^}}]*\}}|null)\s*,\s*({_LITERAL})',
    )
]
# The literals that stay as they are, each a value whose shown text comes from a message by its
# id, or a text that no person reads, by file and the start of the literal.
_UNTRANSLATED = {
    'js/export/photo-core.js': ('Off', 'Rule of', 'Golden', 'Center', 'Crop', 'Window size'),
    'js/export/sizes.js': ('Square', 'Portrait', 'Vertical'),
    'js/broadcast/show.js': ('Goal',),
    'js/presentation/host.js': ('Team presentation sandbox',),
}


def _shown_literal(literal):
    """Returns whether a literal reads as words for people, not as a value, an id or code."""
    body = re.sub(r'\$\{[^}]*\}', ' ', literal[1:-1]).strip()
    if 't(' in literal or re.fullmatch(r'[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+', body):
        return False
    if re.fullmatch(r'[a-z0-9 _=:./-]+', body):
        return False
    return bool(re.search(r'\b[A-Za-z][a-z]{2,}', body))


def _untranslated_literals(web):
    found = []
    for path in sorted((web / 'js').rglob('*.js')):
        name = path.relative_to(web).as_posix()
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if re.match(r'\s*(//|\*|/\*)', line) or 'console.' in line:
                continue
            for pattern in _SHOWN:
                for match in pattern.finditer(line):
                    literal = match.group(1)
                    if not _shown_literal(literal):
                        continue
                    if literal[1:].startswith(_UNTRANSLATED.get(name, ())):
                        continue
                    found.append(f'{name}:{number} {literal}')
    return found


def _untranslated_markup(markup):
    """Returns the texts and attributes of a page that carry no message id."""
    import html.parser

    found = []

    class Parser(html.parser.HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []

        def handle_starttag(self, tag, attributes):
            attributes = dict(attributes)
            for name in ('title', 'aria-label', 'placeholder', 'alt'):
                value = attributes.get(name)
                if (
                    value
                    and re.search(r'[A-Za-z]{2}', value)
                    and not attributes.get(f'data-i18n-{name}')
                ):
                    if not (tag == 'img' and value == ''):
                        found.append(f'<{tag}> {name}={value!r}')
            if tag not in ('meta', 'link', 'input', 'img', 'br', 'use', 'path', 'source'):
                self.stack.append((tag, 'data-i18n' in attributes))

        def handle_endtag(self, tag):
            # A tag that never opened, such as the use of a symbol that closes itself, closes
            # nothing.
            if all(name != tag for name, _ in self.stack):
                return
            while self.stack:
                if self.stack.pop()[0] == tag:
                    break

        def handle_data(self, data):
            text = data.strip()
            inside = [tag for tag, _ in self.stack]
            if not text or {'script', 'style', 'title', 'symbol', 'svg'} & set(inside):
                return
            if any(translated for _, translated in self.stack):
                return
            # Key letters and symbols, such as V, Ctrl or the arrows, read the same everywhere.
            if re.fullmatch(r'[A-Z0-9]?|[^A-Za-z]*|[A-Z][a-z]?|0:00|00:00', text) or inside[
                -1:
            ] == ['kbd']:
                return
            found.append(f'<{inside[-1] if inside else "?"}> {text!r}')

    Parser().feed(markup)
    return found


def test_page_texts_come_from_the_language_files():
    web = _server._WEB
    assert _untranslated_literals(web) == []
    assert _untranslated_markup((web / 'index.html').read_text(encoding='utf-8')) == []
    assert _untranslated_markup((web / 'feed.html').read_text(encoding='utf-8')) == []


def test_page_message_ids_are_in_english():
    web = _server._WEB
    english = _shipped_language('en')
    called = re.compile(r"\b(?:t|tn|tOr)\(\s*'([A-Za-z0-9_.-]+)'")
    marked = re.compile(r'data-i18n(?:-[a-z-]+)?="([^"]+)"')
    ids = set()
    for path in [*(web / 'js').rglob('*.js'), web / 'index.html', web / 'feed.html']:
        text = path.read_text(encoding='utf-8')
        ids.update(called.findall(text))
        ids.update(marked.findall(text))
    tolerated = {
        key for key in ids if not key.startswith(('lesson.', 'challenge.', 'achievement.'))
    }
    assert sorted(key for key in tolerated if key not in english) == []


def test_language_routes(render_home):
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_address[1]}'

    def call(path, data=None, method='GET', headers=None):
        request = urllib.request.Request(
            address + path, data=data, method=method, headers=headers or {}
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    try:
        # The page and the feed carry the shipped languages, so they start without asking.
        for path in ('/', '/feed'):
            with urllib.request.urlopen(address + path, timeout=10) as response:
                page = response.read().decode('utf-8')
            start = page.index('<script type="application/json" id="cuju-languages">') + 52
            block = page[start : page.index('</script>', start)]
            assert '<' not in block
            shipped = json.loads(block)
            assert sorted(shipped) == ['en']
        status, body = call('/api/languages')
        assert status == 200
        assert [(e['code'], e['source'], e['usable']) for e in body['languages']] == [
            ('en', 'shipped', True),
        ]
        # The Portuguese draft joins through the import, as any language of a person's own.
        status, body = call('/api/languages', json.dumps(_translation('pt-BR')).encode(), 'POST')
        assert status == 201 and (body['code'], body['source'], body['usable']) == (
            'pt-BR',
            'home',
            True,
        )
        assert call('/api/languages/pt-BR')[1]['@language']['locale'] == 'pt-BR'
        # Codes differ in case alone as BCP 47 has them, so pt-br names the same language.
        assert call('/api/languages/pt-br')[1]['@language']['code'] == 'pt-BR'
        assert call('/api/languages/pt')[0] == 404
        status, body = call('/api/languages/xx')
        assert (status, body['error_id'], body['error']) == (
            404,
            'server.language.none',
            'no language xx',
        )
        assert call('/api/languages/..%2Fen')[0] == 400
        own = {
            '@language': {'code': 'pt-x-test', 'name': 'Teste', 'plurals': ['one', 'many', 'other']}
        }
        own['html.nav.watch'] = 'Assistir aqui'
        data = json.dumps(own).encode()
        # Another site may not store a language.
        assert call('/api/languages', data, 'POST', {'Origin': 'https://example.com'})[0] == 403
        status, body = call('/api/languages', data, 'POST')
        assert status == 201 and (body['code'], body['source'], body['usable']) == (
            'pt-x-test',
            'home',
            True,
        )
        assert body['missing'] == len(_shipped_language('en')) - 2
        assert call('/api/languages/pt-x-test')[1]['html.nav.watch'] == 'Assistir aqui'
        assert [e['code'] for e in call('/api/languages')[1]['languages']] == [
            'en',
            'pt-BR',
            'pt-x-test',
        ]
        bad = dict(own, **{'api.status': 'Resposta {code}'})
        status, body = call('/api/languages', json.dumps(bad).encode(), 'POST')
        assert status == 400 and body['error_id'] == 'server.language.malformed'
        first = body['error_values']['first']
        assert first['text'] == 'api.status, expected the placeholders of English, found {code}'
        # The problem travels as a label of its own, which the page shows in its language.
        assert first['id'] == 'server.language.problem_at'
        assert first['values']['problem']['id'] == 'server.language.problem.extra'
        shipped = dict(own, **{'@language': dict(own['@language'], code='en')})
        status, body = call('/api/languages', json.dumps(shipped).encode(), 'POST')
        assert (status, body['error_id']) == (400, 'server.language.shipped')
        assert call('/api/languages', b'{', 'POST')[1]['error_id'] == 'server.language.json'
        # A file dropped into the folder by hand that is malformed lists as refused.
        (_home.home() / 'languages' / 'zz.json').write_text(
            '{"@language": {"code": "zz"}}', encoding='utf-8'
        )
        listed = {e['code']: e for e in call('/api/languages')[1]['languages']}
        assert listed['zz']['usable'] is False and listed['zz']['problems']
        assert call('/api/languages/en', method='DELETE')[1]['error_id'] == 'server.language.keep'
        assert call('/api/languages/pt-x-test', method='DELETE') == (
            200,
            {'code': 'pt-x-test', 'removed': True},
        )
        assert call('/api/languages/pt-x-test')[0] == 404
    finally:
        server.shutdown()
        server.server_close()


def test_loopback_server_reuses_its_threads():
    import http.server
    import socket

    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *arguments):
            pass

        def do_GET(self):
            seen.append(threading.get_ident())
            if self.path == '/slow':
                time.sleep(0.4)
            self.send_response(200)
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'ok')

    server = _launch.LoopbackServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def get(path='/'):
        with socket.create_connection(('127.0.0.1', port), timeout=10) as connection:
            connection.sendall(f'GET {path} HTTP/1.0\r\n\r\n'.encode())
            data = b''
            while chunk := connection.recv(65536):
                data += chunk
        return data

    try:
        for _ in range(10):
            assert get().endswith(b'ok')
        # One request at a time runs on the threads that already wait.
        assert len(set(seen)) <= 2
        # Requests that wait run side by side, each on a thread of its own.
        start = time.monotonic()
        threads = [threading.Thread(target=get, args=('/slow',)) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert time.monotonic() - start < 2.0
        assert _server.make_handler(_server._Requests()).disable_nagle_algorithm is True
    finally:
        server.shutdown()
        server.server_close()


def test_serve_remote_on_a_port_of_cuju_prints_the_ssh_command(render_home, monkeypatch):
    import errno

    busy = OSError(errno.EADDRINUSE, 'in use')
    own = _launch.Server(8790, os.getpid(), 'key', render_home)
    monkeypatch.setattr(_launch, 'running', lambda: own)
    assert 'ssh -N -L 8790:127.0.0.1:8790' in str(_launch.port_error(8790, busy, True))
    assert 'ssh' not in str(_launch.port_error(8790, busy))
    monkeypatch.setattr(_launch, 'running', lambda: None)
    monkeypatch.setattr(_launch, 'answers', lambda port, timeout=2.0: '0.2.1')
    shown = str(_launch.port_error(8790, busy, True))
    assert 'another cuju render server' in shown and 'ssh -N -L 8790:127.0.0.1:8790' in shown
    monkeypatch.setattr(_launch, 'answers', lambda port, timeout=2.0: None)
    shown = str(_launch.port_error(8790, busy, True))
    assert 'another program' in shown and 'ssh' not in shown


def test_loopback_server_takes_a_burst_of_connections():
    import http.server
    import socket

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *arguments):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'ok')

    # Windows refuses a connection beyond the queue, which lost a module of the page.
    assert _launch.LoopbackServer.request_queue_size >= 128
    server = _launch.LoopbackServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    count = 80
    barrier = threading.Barrier(count)
    answers = []

    def get():
        barrier.wait()
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=20) as connection:
                connection.sendall(b'GET / HTTP/1.0\r\n\r\n')
                data = b''
                while chunk := connection.recv(65536):
                    data += chunk
            answers.append(data.endswith(b'ok'))
        except OSError as error:
            answers.append(type(error).__name__)

    try:
        threads = [threading.Thread(target=get) for _ in range(count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert answers == [True] * count
    finally:
        server.shutdown()
        server.server_close()


def test_requests_keep_the_names_of_their_teams(monkeypatch, render_home, tmp_path):
    monkeypatch.setattr(_server._Requests, '_run', lambda self: None)
    team = _toy_team(tmp_path, 'gone', 'def agent(obs):\n    return [0]\n', '5v5')
    _teams.update(team['id'], name='Équipe São Ñandú')
    requests = _server._Requests()
    made = requests.add(team['id'], 'builtin', '5_vs_5', 3)
    builtin = made['team_names'][1]
    assert made['team_names'][0] == 'Équipe São Ñandú'
    # The built-in AI keeps the label of its name, which the page shows in its own language.
    assert builtin['id'] == 'server.names.builtin' and isinstance(builtin['text'], str)
    _teams.remove(team['id'])
    assert _server._Requests().entries()[0]['team_names'] == made['team_names']
    # A request of an earlier version, without the names, still loads, and a malformed list of
    # names leaves its file out.
    path = requests._folder / f'{made["id"]}.json'
    stored = json.loads(path.read_text(encoding='utf-8'))
    del stored['team_names']
    path.write_text(json.dumps(stored), encoding='utf-8')
    assert _server._Requests().entries()[0]['team_names'] is None
    path.write_text(json.dumps({**stored, 'team_names': ['one']}), encoding='utf-8')
    assert _server._Requests().entries() == []


def test_scenario_sides_name_the_players_that_a_team_can_control():
    sides = _server._scenario_sides()
    assert set(sides) == set(_server._scenarios())
    # The drill of three against one with a keeper gives the left side four players to control.
    left, right = sides['academy_3_vs_1_with_keeper']
    assert len(left) == 4 and all(player['controllable'] for player in left)
    assert left[0]['role'] == 0 and len(right) == 2
