# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the team registry, its kits, styles, models and clips."""

import io
import json
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
from support.common import (
    _SEVERAL,
    _control,
    _frames,
    _get,
    _one_second,
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


_SINGLE = """
def agent(obs):
    return [5 if obs['step'] % 7 else 12]
"""


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
    # A tampered archive keeps the sound clips and drops a damaged one, unsafe names, a folder,
    # another file and a mapping to bones that the clip lacks.
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
        'bounce.glb',
        'bounce.json',
        'wave.glb',
        'wave.json',
    ]
    duplicate = _teams.duplicate(team['id'])
    assert duplicate['clips'] == original['clips']
    # A clip whose JSON file went missing is checked again and maps its bones by their names.
    (folder / 'bounce.json').unlink()
    clips = {item['name']: item for item in _teams.entry(tampered['id'])['clips']}
    assert clips['bounce']['animations'] == ['Up', 'Down'] and clips['bounce']['joints'] == {}
    assert (folder / 'bounce.json').is_file()
