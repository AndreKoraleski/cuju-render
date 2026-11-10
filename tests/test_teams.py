# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the team registry, its kits, styles, models and clips."""

import io
import json
import logging
import struct
import threading
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
from cuju.render._store import library as _library
from support.common import (
    _SEVERAL,
    _SINGLE,
    _control,
    _frames,
    _get,
    _one_second,
    _package_team,
    _send,
    _short_matches,
    _toy_team,
)


@pytest.mark.parametrize(
    'name', ['D:evil.py', '../out.py', '/etc/x', 'a\\b.py', 'a/../../b.py', 'a\x00b']
)
def test_hostile_member_names_are_refused(name):
    with pytest.raises(cuju.ArgumentError):
        _teams._check_member(name)


def test_team_control_is_checked_and_travels(render_home, tmp_path):
    team = _toy_team(tmp_path, 'several', _SEVERAL, '11v11')
    assert team['control'] == _teams.DEFAULT_CONTROL
    for wrong in (
        {'players': 12},
        {'players': 0},
        {'players': True},
        {'players': 9, 'goalkeeper': 'builtin'},
        {'players': 10, 'goalkeeper': 'nobody'},
        {'players': 2, 'extra': 1},
    ):
        with pytest.raises(cuju.ArgumentError):
            _teams.update(team['id'], control=wrong)
    keeper = {'players': 10, 'goalkeeper': 'builtin'}
    team = _teams.update(team['id'], control=keeper)
    assert _teams.agent_count(team) == 11
    # A change of format that the control does not fit returns it to the default.
    assert _teams.update(team['id'], format='5v5')['control']['players'] == 1
    team = _teams.update(team['id'], format='11v11', control=keeper)
    _, archive = _teams.export(team['id'])
    copy = _teams.add('copy', 'copy.zip', archive)
    assert copy['control'] == _teams.check_control(keeper, '11v11')
    with pytest.raises(cuju.ArgumentError):
        _teams.add('wrong', 'main.py', b'def agent(obs):\n    return [0]\n', '5v5', {'players': 6})


def test_single_player_team_plays_as_before(render_home, tmp_path, monkeypatch):
    """A team of one controlled player plays the match of one agent, frame for frame."""
    from cuju.kaggle import KaggleAgent

    _short_matches(monkeypatch, 80)
    team = _toy_team(tmp_path, 'single', _SINGLE, '5v5')
    path = cuju.render.play(team['id'], 'builtin', '5_vs_5', seed=9)
    _, frames = _frames(path)
    batch = cuju.BatchEnvironment(
        '5_vs_5_l1_r0',
        environment_count=1,
        representation='raw',
        seed=9,
        auto_reset=False,
        device='cpu',
    )
    player = KaggleAgent(_teams.load_agent(team['id']), batch, 0)
    reader = _recording.StateReader(10)
    batch.reset()
    expected = [reader.frame(batch.get_state(0))]
    for step in range(80):
        batch.step(player.act().reshape(1, 1))
        expected.append(reader.frame(batch.get_state(0), 1 if step == 79 else 0))
    assert frames == expected
    batch.close()


@pytest.mark.parametrize(
    ('scenario', 'format', 'control', 'active', 'engine_count', 'side', 'opponent'),
    [
        ('5_vs_5', '5v5', _control(2), None, 2, 0, False),
        (
            '11_vs_11_kaggle',
            '11v11',
            _control(3, 'fixed', ['CF', 'CB', 'CB'], 'builtin'),
            [9, 2, 3],
            11,
            0,
            True,
        ),
        ('11_vs_11_kaggle', '11v11', _control(2, 'fixed', [0, 9], 'agent'), [0, 9], 11, 1, True),
        (
            'benchmark_full_game_11_vs_11_hard',
            '11v11',
            _control(10, 'fixed', list(range(1, 11))),
            list(range(1, 11)),
            10,
            0,
            False,
        ),
        ('5_vs_5', '5v5', _control(2, action_set='v2'), None, 2, 1, True),
        (
            'academy_3_vs_1_with_keeper',
            '11v11',
            _control(2, 'fixed', [3, 1], 'builtin'),
            [3, 1],
            4,
            0,
            True,
        ),
        (
            'academy_3_vs_1_with_keeper',
            '11v11',
            _control(1, 'fixed', ['CB'], 'builtin'),
            [1],
            2,
            1,
            False,
        ),
    ],
)
def test_team_assignments_match_engine(
    render_home,
    tmp_path,
    monkeypatch,
    scenario,
    format,
    control,
    active,
    engine_count,
    side,
    opponent,
):
    """Toy actions reach their selected players in either side of a mixed match."""
    from cuju.raw import grf_observation, team_sizes

    steps = 80
    _short_matches(monkeypatch, steps)
    source = f"""
expected = {active!r}
count = {control['players']}
hand = {control['action_set'] == 'v2'}

def agent(obs):
    players = [raw['active'] for raw in obs['players_raw']]
    assert obs['controlled_players'] == count
    assert expected is None or players == expected
    return [19 if hand and k == 0 else (3 if player % 2 else 7)
            for k, player in enumerate(players)]
"""
    team = _toy_team(tmp_path, 'selected', source, format, control)
    other = _toy_team(tmp_path, 'single', 'def agent(obs):\n    return [-1]\n', format)
    sides = [team['id'], other['id'] if opponent else 'builtin']
    if side:
        sides.reverse()
    path = cuju.render.play(*sides, scenario, seed=7, device='cpu')
    document, frames = _frames(path)
    counts = [engine_count, int(opponent)]
    if side:
        counts.reverse()
    extended = control['assignment'] == 'fixed' or control['action_set'] == 'v2'
    asset = str(_teams.scenario_path(scenario)) if scenario.startswith('benchmark_') else scenario
    batch = cuju.BatchEnvironment(
        asset,
        environment_count=1,
        representation='raw',
        seed=7,
        auto_reset=False,
        device='cpu',
        agent_counts=[tuple(counts)],
        action_set='v2' if extended else 'default',
    )
    try:
        batch.reset()
        reader = _recording.StateReader(len(document['players']))
        expected = [reader.frame(batch.get_state(0))]
        first = 0 if side == 0 else counts[0]
        for step in range(steps):
            raw = batch.raw()
            columns = list(range(first, first + engine_count))
            by_player = {
                int(
                    grf_observation(raw, 0, column, *team_sizes(batch, 0, column))['active']
                ): column
                for column in columns
            }
            # A step on which GRF hands the players out again leaves them to the built-in AI,
            # as the runner does.
            complete = len(by_player) == len(columns) and all(i in by_player for i in active or ())
            chosen = (
                columns
                if active is None
                else ([by_player[index] for index in active] if complete else [])
            )
            actions = torch.zeros((1, sum(counts)), dtype=torch.int32)
            if opponent:
                actions[0, counts[0] if side == 0 else 0] = 18
            for column in columns:
                actions[0, column] = 19
            for k, column in enumerate(chosen):
                player = int(
                    grf_observation(raw, 0, column, *team_sizes(batch, 0, column))['active']
                )
                actions[0, column] = (
                    19 if control['action_set'] == 'v2' and k == 0 else 3 if player % 2 else 7
                )
            _, _, done, _ = batch.step(actions)
            final = bool(done[0]) or step == steps - 1
            expected.append(reader.frame(batch.get_state(0), int(final)))
            if final:
                break
        assert frames == expected
    finally:
        batch.close()


def test_earlier_team_control_migrates(render_home, tmp_path):
    """Earlier metadata selects the same players after loading and export."""
    team = _toy_team(tmp_path, 'earlier', _SEVERAL, '11v11')
    meta = _teams._meta_path(team['id'])
    saved = json.loads(meta.read_text())
    saved['control'] = {'players': 10, 'goalkeeper': 'builtin'}
    meta.write_text(json.dumps(saved))
    control = _teams.entry(team['id'])['control']
    assert control == _control(10, 'fixed', list(range(1, 11)), 'builtin')
    _, archive = _teams.export(team['id'])
    assert _teams.add('copy', 'copy.zip', archive)['control'] == control
    saved['control'] = {'players': 2, 'goalkeeper': 'agent'}
    meta.write_text(json.dumps(saved))
    assert _teams.entry(team['id'])['control'] == _control(2)


@pytest.mark.parametrize('size', [5, 11])
@pytest.mark.parametrize(('level', 'difficulty'), [('easy', 0.05), ('medium', 0.6), ('hard', 1.0)])
def test_training_scenario_description(size, level, difficulty):
    """Training scenarios keep the upstream formation, timing and episode parity."""
    from cuju.scenarios import Builder, load_scenario

    name = f'benchmark_full_game_{size}_vs_{size}_{level}'
    assert name in _server._scenarios()
    build = load_scenario(_teams.scenario_path(name))
    configs = []
    for episode in (0, 1):
        builder = Builder(episode)
        build(builder)
        config = builder.config()
        assert config.game_duration == 3000
        assert config.second_half == 1500
        assert config.deterministic is False
        assert config.left_team_difficulty == difficulty
        assert config.right_team_difficulty == difficulty
        for formation in (config.left_team, config.right_team):
            assert len(formation) == size
            assert formation[0].role == 0
            assert formation[0].lazy is False
            assert formation[0].controllable is False
            assert all(player.controllable for player in formation[1:])
        configs.append(config)
    assert [p.key() for p in configs[0].left_team] == [p.key() for p in configs[1].right_team]
    assert [p.key() for p in configs[0].right_team] == [p.key() for p in configs[1].left_team]


def test_cli_team_archive_round_trip(render_home, tmp_path, capsys):
    """The command line imports its own export with the team settings intact."""
    from cuju.render.__main__ import main

    folder = tmp_path / 'submission'
    folder.mkdir()
    (folder / 'main.py').write_text('def agent(obs):\n    return [0]\n')
    assert main(['team', 'add', str(folder), '--name', 'Visitors', '--format', '5v5']) == 0
    team = _teams.teams()[-1]
    control = {'players': 2, 'assignment': 'fixed', 'selection': [1, 2]}
    team = _teams.update(team['id'], control=control)
    archive = tmp_path / 'team.zip'
    assert main(['team', 'export', team['id'], '--out', str(archive)]) == 0
    assert main(['team', 'add', str(archive)]) == 0
    copy = _teams.teams()[-1]
    assert copy['control'] == team['control']
    assert copy['style'] == team['style']
    assert copy['format'] == '5v5'
    assert copy['name'] == 'Visitors'
    duplicate = _teams.duplicate(team['id'])
    assert (duplicate['name'], duplicate['control']) == ('Visitors copy', team['control'])
    assert duplicate['id'] not in (team['id'], copy['id'])
    with pytest.raises(cuju.ArgumentError):
        _teams.duplicate(_teams.BUILTIN)
    assert main(['team', 'list']) == 0
    assert 'Visitors' in capsys.readouterr().out
    assert main(['team', 'remove', copy['id']]) == 0
    assert all(entry['id'] != copy['id'] for entry in _teams.teams())
    assert main(['team', 'add', str(tmp_path / 'missing.zip')]) == 1
    broken = tmp_path / 'broken.zip'
    broken.write_bytes(b'bad archive')
    assert main(['team', 'add', str(broken)]) == 1


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
        # A duplicate takes the saved files, controls and look, and then changes on its own.
        control = {'players': 1, 'assignment': 'fixed', 'selection': [3]}
        _teams.update(team['id'], changes={'badge': 'DUP'}, control=control)
        original = _teams.entry(team['id'])
        assert (original['style']['badge'], original['control']['selection']) == ('DUP', [3])
        copy = _send(address, f'{prefix}/duplicate', b'')
        assert copy['id'] != team['id']
        assert copy['name'] == f'{original["name"]} copy'
        for key in ('format', 'control', 'style', 'model', 'images', 'sounds'):
            assert copy[key] == original[key], key
        twin = f'/api/teams/{copy["id"]}'
        assert _get(address, f'{twin}/model')[1] == model
        assert (
            _get(address, f'{twin}/images/shirt-front')[1]
            == _get(address, f'{prefix}/images/shirt-front')[1]
        )
        assert (_home.folder('teams') / copy['id'] / 'main.py').read_bytes() == (
            _home.folder('teams') / team['id'] / 'main.py'
        ).read_bytes()
        _send(address, twin, b'{"name": "Independent"}', 'PATCH')
        assert _teams.entry(team['id'])['name'] == original['name']
        for refused in ('builtin', 'missing', '..'):
            with pytest.raises(urllib.error.HTTPError) as error:
                _send(address, f'/api/teams/{refused}/duplicate', b'')
            assert error.value.code == 400
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


def test_team_identifiers_are_unique_within_a_second(render_home, monkeypatch):
    _one_second(monkeypatch)
    source = b'def agent(obs):\n    return [0]\n'
    added = [_teams.add(f'team {k}', 'main.py', source) for k in range(6)]
    added.append(_teams.duplicate(added[0]['id']))
    identifiers = [team['id'] for team in added]
    assert len(set(identifiers)) == 7
    assert sorted(team['id'] for team in _teams.teams() if team['kind'] != 'builtin') == sorted(
        identifiers
    )
    assert _teams.entry(identifiers[-1])['name'] == 'team 0 copy'


def _clip_server():
    """Starts a server of the renderer on a free port and returns it with its address."""
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{server.server_address[1]}'


def _raw(address, method, path, body=b''):
    """Sends a request with its path as given and returns its status and body."""
    port = int(address.rsplit(':', 1)[1])
    connection = _server.http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    try:
        connection.request(method, path, body=body)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_clip_uploads_are_checked(render_home, monkeypatch):
    """A clip arrives when it is a sound binary glTF file with a skin and an animation."""
    from cuju.render._registry import clips as _clips
    from support.clip import clip_bytes

    server, address = _clip_server()
    try:
        team = _send(address, '/api/teams?filename=main.py', b'def agent(obs):\n    return 0\n')
        prefix = f'/api/teams/{team["id"]}/clips'
        clip = clip_bytes()
        mapping = {'body': 'mixamorig:Hips', 'right_shoulder': 'mixamorig:RightArm'}
        joints = urllib.parse.quote(json.dumps(mapping))
        entry = _send(address, f'{prefix}/wave?joints={joints}', clip, 'PUT')
        assert entry['clips'] == [
            {
                'name': 'wave',
                'bytes': len(clip),
                'animations': ['Wave', 'Bounce'],
                'joints': mapping,
            }
        ]
        assert _get(address, f'{prefix}/wave')[1] == clip
        # Without a mapping, the page maps the bones by their names.
        assert _send(address, f'{prefix}/plain', clip, 'PUT')['clips'][0]['joints'] == {}
        # A shipped animation pack of KayKit, with its own rig, passes as a clip.
        kaykit = (_server._WEB / 'assets/animations/kaykit-rig-medium-general.glb').read_bytes()
        assert 'Idle_A' in _clips.check(kaykit)['animations']
        broken = bytearray(clip)
        struct.pack_into('<I', broken, 12, 6)
        refused = {
            'wrong magic': b'glTX' + clip[4:],
            'no animation': clip_bytes(animations=False),
            'no skin': clip_bytes(skin=False),
            'too big': clip + bytes(_clips.MAXIMUM_CLIP_BYTES),
            'external link': clip_bytes(uri='https://example.invalid/clip.bin'),
            'broken chunk': bytes(broken),
            'wrong length': clip[:-4],
            'version 1': clip[:4] + struct.pack('<I', 1) + clip[8:],
        }
        for reason, payload in refused.items():
            status, body = _raw(address, 'PUT', f'{prefix}/refused', payload)
            assert status == 400, (reason, body)
        for wrong in [
            {'player': 'mixamorig:Hips'},
            {'body': 'Pelvis'},
            {'body': 'mixamorig:Hips', 'tail': 'mixamorig:Spine'},
        ]:
            query = urllib.parse.quote(json.dumps(wrong))
            assert _raw(address, 'PUT', f'{prefix}/refused?joints={query}', clip)[0] == 400
        # Names that could leave the folder, open a device on Windows or are not the page's own.
        for name in ['..', '%2E%2E', '..%2F..%2Fteam', 'CON', 'con', 'a.glb', 'Wave', 'x' * 41]:
            assert _raw(address, 'PUT', f'{prefix}/{name}', clip)[0] in (400, 404), name
            assert _raw(address, 'GET', f'{prefix}/{name}')[0] in (400, 404), name
        for path in [f'{prefix}/../../model', f'{prefix}/a/b', f'{prefix}/%00']:
            assert _raw(address, 'PUT', path, clip)[0] in (400, 404), path
        folder = _home.folder('teams') / team['id'] / _teams.TEAM_FOLDER / 'clips'
        assert sorted(path.name for path in folder.iterdir()) == [
            'plain.glb',
            'plain.json',
            'wave.glb',
            'wave.json',
        ]
        # A team holds at most so many clips and bytes of them, and a replacement counts once.
        with monkeypatch.context() as patch:
            patch.setattr(_clips, 'MAXIMUM_CLIPS', 2)
            assert _raw(address, 'PUT', f'{prefix}/third', clip)[0] == 400
            assert _raw(address, 'PUT', f'{prefix}/plain', clip)[0] == 200
            patch.setattr(_clips, 'MAXIMUM_TEAM_BYTES', 2 * len(clip) - 1)
            assert _raw(address, 'PUT', f'{prefix}/plain', clip)[0] == 400
        # The mapping changes alone, and a removal takes the clip's celebrations with it.
        document = json.dumps({'joints': {'body': 'mixamorig:Hips'}}).encode()
        changed = _send(address, f'{prefix}/wave', document, 'PATCH')
        assert changed['clips'][1]['joints'] == {'body': 'mixamorig:Hips'}
        assert _raw(address, 'PATCH', f'{prefix}/wave', b'{"joints": {"body": "x"}}')[0] == 400
        assert _raw(address, 'PATCH', f'{prefix}/missing', b'{"joints": {}}')[0] == 400
        _teams.update(
            team['id'],
            changes={
                'celebrations': ['upload:wave.0', 'upload:plain.1', 'arms_up'],
                'players': [{}, {'celebration': 'upload:wave.1'}],
            },
        )
        assert _raw(address, 'DELETE', f'{prefix}/wave')[0] == 204
        assert _raw(address, 'DELETE', f'{prefix}/wave')[0] == 404
        assert _raw(address, 'GET', f'{prefix}/wave')[0] == 404
        after = _teams.entry(team['id'])
        assert [item['name'] for item in after['clips']] == ['plain']
        assert after['style']['celebrations'] == ['upload:plain.1', 'arms_up']
        assert after['style']['players'][1]['celebration'] == 'team'
        assert not (folder / 'wave.json').exists()
        # The built-in AI keeps clips as well.
        builtin = _send(address, '/api/teams/builtin/clips/wave', clip, 'PUT')
        assert builtin['clips'][0]['name'] == 'wave'
    finally:
        server.shutdown()
        server.server_close()


def test_clips_travel_in_export_and_import(render_home):
    """An exported team brings its clips back, each checked again, and leaves out the rest."""
    import zipfile

    from cuju.render._registry import clips as _clips
    from support.clip import clip_bytes

    team = _teams.add('Dancers', 'main.py', b'def agent(obs):\n    return 0\n')
    clip = clip_bytes()
    _clips.set_clip(team['id'], 'wave', clip, {'body': 'mixamorig:Hips'})
    _clips.set_clip(team['id'], 'bounce', clip_bytes(names=('Up', 'Down')))
    _teams.update(
        team['id'],
        changes={
            'celebrations': ['upload:wave.0'],
            'players': [{}, {'celebration': 'upload:bounce.1'}],
        },
    )
    original = _teams.entry(team['id'])
    filename, data = _teams.export(team['id'])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert 'cuju-team/clips/wave.glb' in names and 'cuju-team/clips/wave.json' in names
        assert 'clips' not in json.loads(archive.read('cuju-team/team.json'))
    copy = _teams.add('', filename, data)
    assert copy['clips'] == original['clips']
    assert copy['style']['celebrations'] == ['upload:wave.0']
    assert copy['style']['players'][1]['celebration'] == 'upload:bounce.1'
    assert _clips.clip_path(copy['id'], 'wave').read_bytes() == clip
    # A tampered archive keeps the sound clips, sets a damaged one aside, removes a name that
    # opens a device on Windows, keeps a folder and other files that the page never reads as
    # clips, and drops a mapping to bones that the clip lacks.
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(buffer, 'w') as out:
        for item in source.infolist():
            content = source.read(item)
            if item.filename == 'cuju-team/clips/wave.json':
                content = json.dumps({'joints': {'body': 'Pelvis'}, 'animations': ['X']}).encode()
            out.writestr(item, content)
        out.writestr('cuju-team/clips/broken.glb', b'glTF' + bytes(40))
        out.writestr('cuju-team/clips/con.glb', clip)
        out.writestr('cuju-team/clips/Upper.glb', clip)
        out.writestr('cuju-team/clips/nested/inner.glb', clip)
        out.writestr('cuju-team/clips/notes.txt', b'hello')
    tampered = _teams.add('Tampered', 'team.zip', buffer.getvalue())
    clips = {item['name']: item for item in tampered['clips']}
    assert sorted(clips) == ['bounce', 'wave']
    assert clips['wave']['joints'] == {}
    assert clips['wave']['animations'] == ['Wave', 'Bounce']
    folder = _home.folder('teams') / tampered['id'] / _teams.TEAM_FOLDER / 'clips'
    assert sorted(path.name for path in folder.iterdir()) == [
        'Upper.glb',
        'bounce.glb',
        'bounce.json',
        'broken.glb.rejected',
        'nested',
        'notes.txt',
        'wave.glb',
        'wave.json',
    ]
    assert (folder / 'broken.glb.rejected').read_bytes() == b'glTF' + bytes(40)
    assert (folder / 'nested' / 'inner.glb').read_bytes() == clip
    duplicate = _teams.duplicate(team['id'])
    assert duplicate['clips'] == original['clips']
    # A clip whose JSON file went missing is checked again and maps its bones by their names.
    (folder / 'bounce.json').unlink()
    clips = {item['name']: item for item in _teams.entry(tampered['id'])['clips']}
    assert clips['bounce']['animations'] == ['Up', 'Down'] and clips['bounce']['joints'] == {}
    assert (folder / 'bounce.json').is_file()


def test_team_import_keeps_unknown_files(render_home, caplog):
    """An imported team keeps the files the page never reads and sets aside those that fail."""
    import zipfile

    png = b'\x89PNG\r\n\x1a\n' + bytes(32)
    ogg = b'OggS' + bytes(60)
    files = {
        'main.py': b'def agent(obs):\n    return 0\n',
        'cuju-team/team.json': json.dumps({'name': 'Keepers', 'format': '5v5'}).encode(),
        'cuju-team/shirt-front.png': png,
        'cuju-team/sponsor-1.png': b'not an image',
        'cuju-team/sound-goal.ogg': ogg,
        'cuju-team/sound-shot.ogg': b'not a sound',
        'cuju-team/sound-shot.ogg.rejected': b'an older one',
        'cuju-team/sound-whistle.ogg': ogg,
        'cuju-team/notes.md': b'# Our kit',
        'cuju-team/art/logo.svg': b'<svg/>',
        'cuju-team/model.glb': b'glTF' + bytes(40),
        'cuju-team/con.txt': b'a device on Windows',
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    with caplog.at_level(logging.WARNING, logger='cuju'):
        team = _teams.add('', 'team.zip', buffer.getvalue())
    assert team['name'] == 'Keepers' and team['format'] == '5v5'
    assert team['images'] == ['shirt-front'] and team['sounds'] == ['goal']
    assert team['model'] is None
    folder = _home.folder('teams') / team['id'] / _teams.TEAM_FOLDER
    names = sorted(
        path.relative_to(folder).as_posix() for path in folder.rglob('*') if path.is_file()
    )
    assert names == [
        'art/logo.svg',
        'model.glb.rejected',
        'notes.md',
        'shirt-front.png',
        'sound-goal.ogg',
        'sound-shot.ogg.2.rejected',
        'sound-shot.ogg.rejected',
        'sound-whistle.ogg',
        'sponsor-1.png.rejected',
        'team.json',
    ]
    assert (folder / 'notes.md').read_bytes() == b'# Our kit'
    assert (folder / 'sound-shot.ogg.2.rejected').read_bytes() == b'not a sound'
    assert (folder / 'sound-shot.ogg.rejected').read_bytes() == b'an older one'
    logged = caplog.text
    assert 'sponsor-1.png' in logged and 'model.glb' in logged and 'con.txt' in logged
    # The kept files travel in the export, and a second import keeps them as they are.
    filename, data = _teams.export(team['id'])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        exported = set(archive.namelist())
    assert {'cuju-team/notes.md', 'cuju-team/art/logo.svg'} <= exported
    again = _teams.add('', filename, data)
    folder = _home.folder('teams') / again['id'] / _teams.TEAM_FOLDER
    assert (
        sorted(path.relative_to(folder).as_posix() for path in folder.rglob('*') if path.is_file())
        == names
    )
    assert again['images'] == ['shirt-front'] and again['sounds'] == ['goal']


def test_team_sounds_version_follows_the_files(render_home):
    """The version of a team's sounds changes whenever a sound is stored, replaced or removed."""
    import zipfile

    team = _teams.add('Singers', 'main.py', b'def agent(obs):\n    return 0\n')
    assert team['sounds'] == [] and team['sounds_version'] == ''
    first = _teams.set_sound(team['id'], 'goal', b'OggS' + bytes(60))
    assert first['sounds'] == ['goal'] and first['sounds_version']
    assert _teams.entry(team['id'])['sounds_version'] == first['sounds_version']
    # The same slot and kind with other bytes, as a replaced file, makes a new version.
    second = _teams.set_sound(team['id'], 'goal', b'OggS' + bytes(61))
    assert second['sounds_version'] not in ('', first['sounds_version'])
    third = _teams.set_sound(team['id'], 'goal', b'OggS' + bytes(61))
    assert third['sounds_version'] != second['sounds_version']
    meta = _home.folder('teams') / team['id'] / _teams.TEAM_FOLDER / 'team.json'
    assert 'sounds_version' not in json.loads(meta.read_text())
    _teams.update(team['id'], name='Choir')
    assert 'sounds_version' not in json.loads(meta.read_text())
    with zipfile.ZipFile(io.BytesIO(_teams.export(team['id'])[1])) as archive:
        assert 'sounds_version' not in json.loads(archive.read('cuju-team/team.json'))
    assert _teams.remove_sound(team['id'], 'goal')
    assert _teams.entry(team['id'])['sounds_version'] == ''


def test_team_hides_numbers_on_chosen_models(render_home):
    """A team lists the models on which its shirt numbers stay hidden, each a known model."""
    import zipfile

    team = _teams.add('Numbers', 'main.py', b'def agent(obs):\n    return 0\n')
    assert team['style']['hidden_numbers'] == []
    shipped = _teams.shipped_models()[0]['id']
    changes = {'hidden_numbers': ['custom', shipped, 'custom', 'gone']}
    team = _teams.update(team['id'], changes=changes)
    # A repeat and a model that is no longer shipped are left out, so an old style still loads.
    assert team['style']['hidden_numbers'] == ['custom', shipped]
    for wrong in ('custom', [1], ['x' * 65], ['grf'] * 65):
        with pytest.raises(cuju.errors.ArgumentError):
            _teams.update(team['id'], changes={'hidden_numbers': wrong})
    assert _teams.entry(team['id'])['style']['hidden_numbers'] == ['custom', shipped]
    filename, data = _teams.export(team['id'])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        saved = json.loads(archive.read('cuju-team/team.json'))
    assert saved['style']['hidden_numbers'] == ['custom', shipped]
    assert _teams.add('', filename, data)['style']['hidden_numbers'] == ['custom', shipped]


def _package_manifest():
    from pathlib import Path

    path = Path(__file__).parent / 'support/team/cuju-team/presentation/presentation.json'
    return json.loads(path.read_text())


def test_presentation_package_imports_checks_and_exports(render_home):
    """A team's presentation package arrives checked, is served whole and travels in exports."""
    import zipfile

    from cuju.render._packages import presentation as _presentation

    team = _package_team()
    served = _presentation.served(team['id'])
    assert served['warnings'] == [] and served['developer'] is False
    assert served['files'] == [
        'audio/hum.js',
        'audio/strike.wav',
        'models/halo.glb',
        'models/keeper.glb',
        'shaders/blink.glsl',
        'textures/tifo.png',
        'worker.js',
    ]
    assert served['contract'] == '1.1' and served['missing'] == []
    manifest = served['manifest']
    assert manifest['rig']['driver'] == {'outfield': 'team', 'goalkeeper': 'grf+layers'}
    assert manifest['clips']['move'] == {'space': 'speed', 'clips': [{'clip': 'Run', 'speed': 5.0}]}
    assert manifest['rig']['sockets']['gaze']['forward'] == [0.0, 0.0, 1.0]
    assert manifest['rig']['bounds'] == {'radius': 0.6, 'height': 2.2, 'clearance': 0.0}
    assert [b['id'] for b in manifest['behaviours']] == [
        'spin',
        'hover',
        'bank',
        'look',
        'glow',
        'bob',
        'beat',
        'awake',
    ]
    assert manifest['audio']['cues'] == {'strike': ['audio/strike.wav']}
    assert manifest['reflexes'][3] == {
        'on': 'winner.reveal',
        'phase': 'occur',
        'where': {'team': 'self'},
        'do': [{'audio': 'strike', 'class': 'moment'}],
    }
    _, data = _teams.export(team['id'])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
    assert {
        'cuju-team/presentation/presentation.json',
        'cuju-team/presentation/worker.js',
        'cuju-team/presentation/models/halo.glb',
    } <= names
    copy = _teams.add('', 'copy.zip', data)
    assert _presentation.served(copy['id'])['manifest'] == manifest
    # The engine never reads a package, so the team's entry holds the same keys as without one.
    plain = _teams.add('Plain', 'main.py', b'def agent(obs):\n    return [0]\n')
    assert set(_teams.entry(team['id'])) == set(_teams.entry(plain['id']))


def test_presentation_package_refuses_bad_files_and_parts(render_home):
    """Files of a wrong path, kind or size go, and a failing part leaves the rest standing."""
    import zipfile

    from cuju.render._packages import presentation as _presentation

    manifest = _package_manifest()
    manifest['rig']['sockets']['bad'] = {'forward': [0, 1, 0], 'up': [0, 2, 0]}
    manifest['unknown'] = 1
    manifest['behaviours'].append({'id': 'x', 'type': 'teleport'})
    manifest['reflexes'].append({'on': 'touch', 'do': [{'audio': 'missing'}]})
    manifest['requires'].append('future.feature')
    folder = 'cuju-team/presentation/'
    extra = {
        f'{folder}presentation.json': json.dumps(manifest).encode(),
        f'{folder}models/halo.glb': b'not a glb',
        f'{folder}Upper.js': b'export {}',
        f'{folder}con.js': b'export {}',
        f'{folder}a/b/c/d/deep.js': b'export {}',
        f'{folder}notes.txt': b'hello',
        f'{folder}big.js': b'/' * (3 * 1024 * 1024),
        f'{folder}sound.wav': b'OggS' + bytes(60),
        f'{folder}uses.js': b"import x from './y.js';\nexport function frame() {}\n",
        f'{folder}shaders/ok.glsl': b'void main() {}\n',
    }
    team = _package_team('Tampered', extra)
    root = _home.folder('teams') / team['id'] / _teams.TEAM_FOLDER / 'presentation'
    kept = sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file())
    assert kept == [
        'audio/hum.js',
        'audio/strike.wav',
        'models/keeper.glb',
        'presentation.json',
        'shaders/blink.glsl',
        'shaders/ok.glsl',
        'textures/tifo.png',
        'worker.js',
    ]
    served = _presentation.served(team['id'])
    warnings = ' | '.join(served['warnings'])
    assert 'socket bad left out' in warnings and 'the manifest ignores unknown' in warnings
    assert 'attachment halo left out' in warnings and 'behaviour 8 left out' in warnings
    assert 'reflex 5 left out' in warnings
    assert served['missing'] == ['future.feature']
    # The parts that passed stay.
    assert 'bad' not in served['manifest']['rig']['sockets']
    assert served['manifest']['rig']['attachments'] == {}
    assert served['manifest']['clips']['kick'] == [{'clip': 'Kick'}]
    assert len(served['manifest']['behaviours']) == 8 and len(served['manifest']['reflexes']) == 4
    # A manifest of a newer contract stays on disk and the team is drawn without it.
    newer = {f'{folder}presentation.json': json.dumps({'contract': '1.9'}).encode()}
    later = _package_team('Later', newer)
    path = _home.folder('teams') / later['id'] / _teams.TEAM_FOLDER / 'presentation'
    assert json.loads((path / 'presentation.json').read_text()) == {'contract': '1.9'}
    assert _presentation.served(later['id'])['manifest'] is None
    assert 'contract 1.9' in _presentation.served(later['id'])['warnings'][0]
    # A manifest that is no JSON goes on import.
    broken = _package_team('Broken', {f'{folder}presentation.json': b'{not json'})
    assert _presentation.served(broken['id'])['manifest'] is None
    # A file changed on disk after import fails its check again before it is served or exported.
    (root / 'worker.js').write_bytes(b'\xff\xfe')
    assert _presentation.file_path(team['id'], 'worker.js') is None
    assert _presentation.file_path(team['id'], '../team.json') is None
    _, data = _teams.export(team['id'])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert f'{folder}worker.js' not in archive.namelist()
        assert f'{folder}models/keeper.glb' in archive.namelist()


def _board_entry(name, value, seconds, when, kind='person', team=None):
    from cuju.render._playing import challenges as _challenges

    return {
        'kind': kind,
        'name': name,
        'team': team,
        'value': value,
        'seconds': seconds,
        'medal': _challenges.medal(_challenges.find('corner'), value),
        'attempts': [],
        'time': when,
        'cuju_version': cuju.__version__,
    }


def test_challenge_leaderboard_ranks_and_keeps_personal_bests(render_home, monkeypatch, caplog):

    from cuju.render._playing import challenges as _challenges

    record = _challenges.record
    assert record('corner', _board_entry('Ana', 2, 9.0, 1))['rank'] == 1
    assert record('corner', _board_entry('Bo', 2, 7.0, 2))['rank'] == 1
    # The tie on value and seconds goes to the earlier run.
    assert record('corner', _board_entry('Cy', 2, 9.0, 3))['rank'] == 3
    worse = record('corner', _board_entry('Ana', 1, 1.0, 4))
    assert not worse['improved'] and worse['personal_best']['value'] == 2 and worse['rank'] == 2
    better = record('corner', _board_entry('Ana', 4, 20.0, 5))
    assert better['improved'] and better['rank'] == 1
    agent = _board_entry('Toy', 3, 5.0, 6, kind='agent', team='t-toy')
    assert record('corner', agent)['rank'] == 2
    # An agent keeps its runs under its team, whatever name the team has now.
    renamed = record('corner', {**_board_entry('Toy renamed', 5, 5.0, 7, 'agent', 't-toy')})
    assert renamed['rank'] == 1
    board = _challenges.board('corner')
    assert [(entry['name'], entry['rank']) for entry in board] == [
        ('Toy renamed', 1),
        ('Ana', 2),
        ('Bo', 3),
        ('Cy', 4),
    ]
    assert _challenges.personal_bests('person', 'Ana') == {'corner': {**board[1]}}
    path = render_home / 'challenges' / 'corner.json'
    assert not list(path.parent.glob('*.part')) and not (path.parent / '.lock').exists()
    # A failed write leaves the board as it was.
    before = path.read_bytes()

    def broken(target, data):
        raise OSError('disk full')

    with monkeypatch.context() as patch, pytest.raises(OSError):
        patch.setattr(_teams, '_replace', broken)
        record('corner', _board_entry('Dee', 9, 1.0, 8))
    assert path.read_bytes() == before and not (path.parent / '.lock').exists()
    # The board keeps the best 100 competitors.
    for number in range(120):
        record('empty_goal', _board_entry(f'P{number}', number % 6, number / 10, number))
    kept = _challenges.board('empty_goal')
    assert len(kept) == _challenges.BOARD_SIZE and kept[0]['value'] == 5
    assert kept[-1]['value'] == 1 and all(entry['value'] >= 1 for entry in kept)
    late = record('empty_goal', _board_entry('Late', 0, 0.0, 999))
    assert late['rank'] is None and late['personal_best']['rank'] is None
    # Invalid entries and files are skipped with one warning each.
    document = json.loads(path.read_text())
    document['entries'].append({**document['entries'][0], 'value': 'many'})
    document['entries'].append({**document['entries'][0], 'kind': 'robot'})
    path.write_text(json.dumps(document))
    (path.parent / 'run_to_score.json').write_text('{')
    (path.parent / 'counterattack_easy.json').write_text('{"challenge": "corner", "entries": []}')
    with caplog.at_level(logging.WARNING, logger='cuju'):
        assert len(_challenges.board('corner')) == 4
        assert _challenges.board('run_to_score') == []
        assert _challenges.board('counterattack_easy') == []
    warnings = [record.getMessage() for record in caplog.records if record.name == 'cuju']
    assert len(warnings) == 3 and '2 invalid entries' in warnings[0]


def test_samples_add_restore_and_register_the_starter_team(render_home):
    from cuju.render._store import samples as _samples

    listed = {entry['id']: entry for entry in _samples.listing()}
    assert list(listed) == ['sample-11v11', 'sample-5v5', 'starter-team']
    assert {entry['state'] for entry in listed.values()} == {'missing'}
    added = _samples.add(['sample-5v5'])
    assert added['changes'] == [{'id': 'sample-5v5', 'change': 'added'}]
    assert _library.trash('sample-5v5')
    assert {e['id']: e['state'] for e in _samples.listing()}['sample-5v5'] == 'trash'
    assert _samples.add(['sample-5v5'])['changes'] == [{'id': 'sample-5v5', 'change': 'restored'}]
    team = _samples.add(['starter-team'])
    entry = next(item for item in team['samples'] if item['id'] == 'starter-team')
    assert team['changes'] == [{'id': 'starter-team', 'change': 'added'}]
    registered = _teams.entry(entry['target'])
    assert (registered['name'], registered['format'], entry['state']) == (
        'Starter team',
        '11v11',
        'library',
    )
    assert (render_home / 'teams' / entry['target'] / 'main.py').is_file()
    # A sample that the library holds stays as it is, and a removed team comes back as new.
    assert _samples.add(['starter-team', 'sample-5v5'])['changes'] == []
    assert _teams.remove(entry['target'])
    assert {e['id']: e['state'] for e in _samples.listing()}['starter-team'] == 'missing'
    every = _samples.add()
    assert {change['id'] for change in every['changes']} == {'sample-11v11', 'starter-team'}
    with pytest.raises(cuju.errors.ArgumentError):
        _samples.add(['sample-3v3'])
