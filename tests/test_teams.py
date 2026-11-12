# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the team registry, its kits, styles, models and clips."""

import contextlib
import io
import json
import logging
import os
import shutil
import struct
import threading
import urllib.request
from pathlib import Path

import pytest
import torch

import cuju
import cuju.errors
import cuju.state
from cuju.render._format import recording as _recording
from cuju.render._http import launch as _launch
from cuju.render._http import server as _server
from cuju.render._registry import teams as _teams
from cuju.render._store import home as _home
from cuju.render._store import library as _library
from support.common import (
    _OGG,
    _SEVERAL,
    _SINGLE,
    _control,
    _frames,
    _get,
    _one_second,
    _package_team,
    _send,
    _short_matches,
    _template_variant,
    _toy_team,
    _zip_folder,
)


@pytest.mark.parametrize(
    'name', ['D:evil.py', '../out.py', '/etc/x', 'a\\b.py', 'a/../../b.py', 'a\x00b']
)
def test_hostile_member_names_are_refused(name):
    with pytest.raises(cuju.ArgumentError):
        _teams._check_member(name)


_DEVICE_NAMES = [
    'con',
    'com1.txt',
    '.. ',
    'nul',
    'NUL.py',
    'con .txt',
    'aux.tar.gz',
    'com0',
    'Com9.log',
    'lpt1',
    'COM\N{SUPERSCRIPT ONE}',
    'lpt\N{SUPERSCRIPT THREE}.txt',
    'conin$',
    'CONOUT$.log',
    'prn',
    'lib/nul/x.py',
    'main.py.',
    'main.py ',
    'a/.. /b',
]


@pytest.mark.parametrize('name', _DEVICE_NAMES)
def test_members_whose_names_open_a_device_on_windows_are_refused(name):
    """A device name of Windows, with any extension or case, or a part ending in a dot or space."""
    with pytest.raises(cuju.ArgumentError, match='open no device on Windows'):
        _teams._check_member(name)


@pytest.mark.parametrize('name', ['console.py', 'auxiliary.py', 'nul_test.py', 'com10.py', '.a'])
def test_names_close_to_devices_stay_members(name):
    assert str(_teams._check_member(name)) == name


def test_an_archive_with_a_device_member_is_refused_whole(render_home):
    """The member `nul` of the review would open a device on Windows, so the upload is refused."""
    for member in ('nul', 'cuju-team/con.txt', 'helpers/AUX.py'):
        with pytest.raises(cuju.ArgumentError, match='open no device on Windows'):
            _teams.add('', 'team.zip', _archive({'main.py': _MAIN_PY, member: b'x'}))
    assert list(_home.folder('teams').iterdir()) == []


def test_files_of_a_team_named_as_devices_are_removed(render_home, tmp_path, caplog):
    """A file of a team's folder named as a device, or ending in a dot or space, is removed."""
    kept = []
    with caplog.at_level(logging.WARNING, logger='cuju'):
        for name in ('nul', 'con .txt', 'conin$', 'shirt-front.png.', 'notes.md'):
            path = tmp_path / name
            path.write_bytes(b'x')
            kept.append(_teams._kept(path))
    assert kept == [False, False, False, False, True]
    assert sorted(path.name for path in tmp_path.iterdir()) == ['notes.md']
    assert 'opens a device on Windows' in caplog.text


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
    saved = json.loads(meta.read_text(encoding='utf-8'))
    saved['control'] = {'players': 10, 'goalkeeper': 'builtin'}
    meta.write_text(json.dumps(saved), encoding='utf-8')
    control = _teams.entry(team['id'])['control']
    assert control == _control(10, 'fixed', list(range(1, 11)), 'builtin')
    _, archive = _teams.export(team['id'])
    assert _teams.add('copy', 'copy.zip', archive)['control'] == control
    saved['control'] = {'players': 2, 'goalkeeper': 'agent'}
    meta.write_text(json.dumps(saved), encoding='utf-8')
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


def test_a_submission_folder_leaves_its_links_out(render_home, tmp_path, caplog):
    """A link in a submission folder, to a file or a folder, is never followed into the team."""
    secrets = tmp_path / 'secrets'
    secrets.mkdir()
    (secrets / 'id_ed25519').write_bytes(b'private key')
    folder = tmp_path / 'submission'
    (folder / 'lib' / '__pycache__').mkdir(parents=True)
    (folder / 'main.py').write_bytes(_MAIN_PY)
    (folder / 'lib' / 'helper.py').write_bytes(b'VALUE = 1\n')
    (folder / 'lib' / '__pycache__' / 'helper.pyc').write_bytes(b'cache')
    (folder / 'key').symlink_to(secrets / 'id_ed25519')
    (folder / 'lib' / 'keys').symlink_to(secrets, target_is_directory=True)
    with caplog.at_level(logging.WARNING, logger='cuju'):
        team = _teams.add_folder(folder, 'Linked')
    stored = _home.folder('teams') / team['id']
    assert sorted(p.relative_to(stored).as_posix() for p in stored.rglob('*') if p.is_file()) == [
        'cuju-team/team.json',
        'lib/helper.py',
        'main.py',
    ]
    assert 'key' in caplog.text and 'lib/keys' in caplog.text
    assert b'private key' not in _teams.export(team['id'])[1]


def test_team_names_from_files_print_no_escapes_or_turned_text(render_home, capsys):
    """The name of an imported team file, or of one edited by hand, keeps only printing text."""
    from cuju.render.__main__ import main

    escape, bell = chr(27), chr(7)
    turned = '\N{RIGHT-TO-LEFT OVERRIDE}\N{LEFT-TO-RIGHT ISOLATE}\N{ZERO WIDTH SPACE}'
    hostile = f'{escape}[2J{escape}[31mRed{turned} FC{escape}]0;title{bell}\N{LINE SEPARATOR}'
    files = {'main.py': _MAIN_PY, 'cuju-team/team.json': json.dumps({'name': hostile}).encode()}
    team = _teams.add('', 'team.zip', _archive(files))
    assert team['name'].isprintable() and escape not in team['name']
    assert team['name'].startswith('[2J [31mRed') and 'FC' in team['name']
    meta = _teams._meta_path(team['id'])
    meta.write_text(
        json.dumps({**json.loads(meta.read_text(encoding='utf-8')), 'name': hostile}),
        encoding='utf-8',
    )
    builtin = _teams._meta_path(_teams.BUILTIN)
    builtin.parent.mkdir(parents=True)
    builtin.write_text(json.dumps({'name': hostile}), encoding='utf-8')
    assert all(entry['name'].isprintable() for entry in _teams.teams())
    assert main(['team', 'list']) == 0
    printed = capsys.readouterr().out
    assert 'Red' in printed and all(line.isprintable() for line in printed.splitlines())


def test_a_submission_reads_by_its_own_source_encoding(render_home):
    """A main.py reads as UTF-8, or by its encoding line, whatever the code page of the system."""
    name = 'Ação 中文 FC'
    utf8 = f'NAME = {name!r}\ndef agent(obs):\n    return [len(NAME)]\n'.encode()
    latin = b'# -*- coding: latin-1 -*-\nNAME = "\xe7"\ndef agent(obs):\n    return [NAME]\n'
    team = _teams.add('', 'team.zip', _archive({'main.py': utf8}))
    assert _teams.load_agent(team['id'])({}) == [len(name)]
    team = _teams.add('', 'team.zip', _archive({'main.py': latin}))
    assert _teams.load_agent(team['id'])({}) == ['ç']


def test_cli_team_archive_round_trip(render_home, tmp_path, capsys):
    """The command line imports its own export with the team settings intact."""
    from cuju.render.__main__ import main

    folder = tmp_path / 'submission'
    folder.mkdir()
    (folder / 'main.py').write_text('def agent(obs):\n    return [0]\n', encoding='utf-8')
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
            ('sounds/goal', _OGG + bytes(60)),
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
    # A tampered archive keeps the sound clips, sets a damaged one aside and one whose name is a
    # clip's name in another case, keeps a folder and other files that the page never reads as
    # clips, and drops a mapping to bones that the clip lacks.
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(buffer, 'w') as out:
        for item in source.infolist():
            content = source.read(item)
            if item.filename == 'cuju-team/clips/wave.json':
                content = json.dumps({'joints': {'body': 'Pelvis'}, 'animations': ['X']}).encode()
            out.writestr(item, content)
        out.writestr('cuju-team/clips/broken.glb', b'glTF' + bytes(40))
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
        'Upper.glb.rejected',
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
    ogg = _OGG + bytes(60)
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
    assert 'sponsor-1.png' in logged and 'model.glb' in logged
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


def _json_glb(document):
    """Returns a binary glTF file of a JSON chunk alone, for the checks that read its document."""
    text = json.dumps(document).encode()
    text += b' ' * (-len(text) % 4)
    body = struct.pack('<II', len(text), 0x4E4F534A) + text
    return b'glTF' + struct.pack('<II', 2, 12 + len(body)) + body


def _archive(files):
    """Returns a zip of the files, by their paths inside it."""
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


_MAIN_PY = b'def agent(obs):\n    return 0\n'


@pytest.mark.parametrize(
    'team_json',
    [
        b'{"format": []}',
        b'{"id": 5}',
        b'{"created": 5, "name": 7}',
        b'{"style": [1]}',
        b'{"style": {"players": 3}, "control": {"players": []}}',
        b'{"format": {"5v5": 1}, "model": {"joints": 4}}',
        b'[' * 100000 + b']' * 100000,
        b'{"a": ' * 5000 + b'1' + b'}' * 5000,
        b'{"name": "' + b'x' * (2 * 1024 * 1024) + b'"}',
    ],
)
def test_crafted_team_files_never_break_the_list(render_home, team_json):
    """A team file of an archive with values of the wrong type adds a team or fails cleanly."""
    data = _archive({'main.py': _MAIN_PY, 'cuju-team/team.json': team_json})
    try:
        team = _teams.add('', 'team.zip', data)
    except cuju.ArgumentError:
        team = None
    listed = _teams.teams()
    folders = sorted(path.name for path in _home.folder('teams').iterdir())
    if team is None:
        assert folders == [] and [t['id'] for t in listed] == ['builtin']
    else:
        assert folders == [team['id']]
        assert [t['id'] for t in listed] == ['builtin', team['id']]
        assert isinstance(team['name'], str) and team['format'] in _teams.FORMATS


def test_a_failed_import_removes_its_folder(render_home, monkeypatch):
    """Any failure after the folder of a new team is made removes the folder again."""
    data = _archive({'main.py': _MAIN_PY, 'cuju-team/team.json': b'{"id": "../../../.ssh"}'})

    def broken(*_):
        raise RuntimeError('a check broke')

    monkeypatch.setattr(_teams, '_import', broken)
    with pytest.raises(RuntimeError):
        _teams.add('', 'team.zip', data)
    assert list(_home.folder('teams').iterdir()) == []
    monkeypatch.setattr(_teams, '_import', lambda *_: (_ for _ in ()).throw(TypeError('x')))
    with pytest.raises(cuju.ArgumentError):
        _teams.add('', 'team.zip', data)
    assert list(_home.folder('teams').iterdir()) == []
    assert [t['id'] for t in _teams.teams()] == ['builtin']


def test_a_team_file_never_names_the_folder_of_its_team(render_home, tmp_path):
    """The identifier of a team is its folder's name, so a team file cannot point elsewhere."""
    secret = tmp_path / '.ssh'
    secret.mkdir()
    (secret / 'id_ed25519').write_bytes(b'private key')
    team_json = {
        'id': '../../../.ssh',
        'name': 'Cool FC',
        'kind': 'kaggle',
        'format': '11v11',
        'created': '2026-11-11T00:00:00',
    }
    data = _archive(
        {
            'main.py': _MAIN_PY,
            'cuju-team/team.json': json.dumps(team_json).encode(),
            'cuju-team/model.glb': _json_glb({'asset': {'version': '2.0'}, 'buffers': 1}),
        }
    )
    team = _teams.add('', 'team.zip', data)
    assert team['name'] == 'Cool FC' and _home.valid_identifier(team['id'])
    assert team['model'] is None
    listed = _teams.teams()
    assert [t['id'] for t in listed] == ['builtin', team['id']]
    _, exported = _teams.export(team['id'])
    assert b'private key' not in exported
    # A folder that a stopped import left behind lists under its own name, whatever its file says.
    left = _home.folder('teams') / 't-left' / _teams.TEAM_FOLDER
    left.mkdir(parents=True)
    (left / 'team.json').write_text(
        json.dumps({**team_json, 'kind': 'builtin', 'format': []}), encoding='utf-8'
    )
    (left.parent / 'main.py').write_bytes(_MAIN_PY)
    odd = _home.folder('teams') / 'Not An Identifier' / _teams.TEAM_FOLDER
    odd.mkdir(parents=True)
    (odd / 'team.json').write_text(json.dumps({'name': 'Odd'}), encoding='utf-8')
    listed = {t['id']: t for t in _teams.teams()}
    assert set(listed) == {'builtin', team['id'], 't-left'}
    assert listed['t-left']['kind'] == 'kaggle' and listed['t-left']['format'] == '11v11'
    for identifier in ('../../../.ssh', str(secret), '..', 'Not An Identifier'):
        with pytest.raises(cuju.ArgumentError):
            _teams.entry(identifier)
        with pytest.raises(cuju.ArgumentError):
            _teams._meta_path(identifier)
        with pytest.raises(cuju.ArgumentError):
            _teams.export(identifier)


def test_glb_documents_of_the_wrong_types_are_refused_cleanly(render_home):
    """A model, a clip or a package model whose arrays are numbers fails its check by name."""
    from cuju.render._packages import presentation as _presentation
    from cuju.render._registry import clips as _clips

    documents = [
        {'asset': {'version': '2.0'}, 'buffers': 1},
        {'asset': {'version': '2.0'}, 'extensionsRequired': 1},
        {'asset': {'version': '2.0'}, 'skins': [{'joints': 5}], 'nodes': 3},
        {'asset': {'version': '2.0'}, 'images': 1, 'skins': 1},
        {
            'asset': {'version': '2.0'},
            'a': [[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]],
        },
    ]
    for document in documents:
        data = _json_glb(document)
        # Each check passes the file or refuses it by name, and fails in no other way.
        with contextlib.suppress(cuju.ArgumentError):
            assert isinstance(_teams._skin_joints(data), set)
        with pytest.raises(cuju.ArgumentError):
            _clips.check(data)
        with contextlib.suppress(cuju.ArgumentError):
            _presentation._glb(data)
    text = b'[' * 100000 + b']' * 100000
    deep = (
        b'glTF' + struct.pack('<II', 2, 20 + len(text)) + struct.pack('<II', len(text), 0x4E4F534A)
    )
    deep += text
    with pytest.raises(cuju.ArgumentError):
        _teams._skin_joints(deep)
    with pytest.raises(cuju.ArgumentError):
        _clips.check(deep)
    with pytest.raises(cuju.ArgumentError):
        _presentation._glb(deep)


def test_a_crafted_archive_leaves_the_server_serving_teams(render_home):
    """The archive of the review, a team file whose format is a list, leaves every route working."""
    server, address = _clip_server()
    try:
        data = _archive({'main.py': _MAIN_PY, 'cuju-team/team.json': b'{"format": []}'})
        added = _send(address, '/api/teams?filename=team.zip&format=5v5', data)
        status, body = _get(address, '/api/teams')
        listed = json.loads(body)
        assert status == 200 and [t['id'] for t in listed] == ['builtin', added['id']]
        assert added['format'] == '5v5'
    finally:
        server.shutdown()
        server.server_close()


def _bounded_refusal(filename, data, match):
    """Adds an archive that must be refused, and returns the peak memory and seconds it took."""
    import time
    import tracemalloc

    tracemalloc.start()
    started = time.monotonic()
    try:
        with pytest.raises(cuju.ArgumentError, match=match):
            _teams.add('', filename, data)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert list(_home.folder('teams').iterdir()) == []
    return peak, time.monotonic() - started


def _tar_header(name, size=0, kind=None):
    import tarfile

    member = tarfile.TarInfo(name)
    member.size = size
    if kind is not None:
        member.type = kind
    return member.tobuf(tarfile.USTAR_FORMAT)


@pytest.mark.parametrize('codec', ['bz2', 'gzip', 'lzma'])
def test_a_small_tar_of_a_great_many_members_is_refused_early(render_home, codec):
    """The bomb of the review, 200,000 empty members in a few kB, stops at the 10,001st member."""
    import importlib

    compress = importlib.import_module(codec).compress
    # Streams joined end to end decompress as one, so the archive takes one compression.
    data = compress(_tar_header('a') * 1000) * 200
    assert len(data) < 1_000_000
    peak, seconds = _bounded_refusal('team.tar', data, '10,000 files')
    assert peak < 32 * 1024 * 1024 and seconds < 30


def test_a_tar_header_that_claims_a_gigabyte_is_refused_early(render_home):
    """A pax header of a gigabyte of zeros is refused after a megabyte, never held whole."""
    import bz2
    import tarfile

    data = bz2.compress(_tar_header('././@PaxHeader', 1 << 30, tarfile.XHDTYPE))
    data += bz2.compress(bytes(1 << 20)) * 1024
    peak, seconds = _bounded_refusal('team.tar.gz', data, '10,000 files')
    assert peak < 32 * 1024 * 1024 and seconds < 30
    # A member that claims more than the whole limit is refused before anything moves past it.
    data = bz2.compress(_tar_header('main.py', 600 * 1024 * 1024))
    _bounded_refusal('team.tgz', data, '500 MB')


def _many_entry_zip(count, declared):
    """Returns a zip of `count` entries in its central directory, whose end declares `declared`."""
    local = struct.pack('<4s5H3L2H', b'PK\x03\x04', 20, 0, 0, 0, 0, 0, 0, 0, 1, 0) + b'a'
    entry = struct.pack(
        '<4s6H3L5H2L', b'PK\x01\x02', 20, 20, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0
    )
    directory = (entry + b'a') * count
    end = struct.pack(
        '<4s4H2LH', b'PK\x05\x06', 0, 0, declared, declared, len(directory), len(local), 0
    )
    return local + directory + end


@pytest.mark.parametrize('declared', [0xFFFF, 1])
def test_a_zip_of_a_great_many_entries_is_refused_before_zipfile_reads_them(render_home, declared):
    """A zip whose directory holds 200,000 entries is refused before a list of them is built."""
    import zipfile

    data = _many_entry_zip(200_000, declared)
    # zipfile itself reads every entry of the directory, whatever the end record declares.
    assert len(zipfile.ZipFile(io.BytesIO(_many_entry_zip(20, 1))).infolist()) == 20
    peak, seconds = _bounded_refusal('team.zip', data, '10,000 files')
    assert peak < 16 * 1024 * 1024 and seconds < 10


@pytest.mark.parametrize('codec', [None, 'gzip', 'bz2', 'lzma'])
def test_tar_submissions_of_every_compression_still_import(render_home, codec):
    """A tar archive, plain or compressed, with a pax header of a long name, imports whole."""
    import importlib
    import tarfile

    long_name = 'lib/' + 'x' * 150 + '.py'
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.PAX_FORMAT) as archive:
        for name, data in (('main.py', _MAIN_PY), (long_name, b'VALUE = 1\n')):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    data = buffer.getvalue()
    if codec is not None:
        data = importlib.import_module(codec).compress(data)
    team = _teams.add('', 'team.tar.gz', data)
    folder = _home.folder('teams') / team['id']
    assert (folder / 'main.py').read_bytes() == _MAIN_PY
    assert (folder / long_name).read_bytes() == b'VALUE = 1\n'


# Python 3.12 and later warn of a tar extracted without a filter, which this test makes.
@pytest.mark.filterwarnings('ignore::DeprecationWarning')
def test_a_tar_without_the_data_filter_writes_its_members_plain(render_home, monkeypatch):
    """Python before 3.10.12 has no data filter, and the members land without their mode bits."""
    import tarfile

    monkeypatch.delattr(tarfile, 'data_filter', raising=False)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        member = tarfile.TarInfo('main.py')
        member.size, member.mode = len(_MAIN_PY), 0o6777
        archive.addfile(member, io.BytesIO(_MAIN_PY))
    team = _teams.add('', 'team.tar', buffer.getvalue())
    main = _home.folder('teams') / team['id'] / 'main.py'
    assert main.read_bytes() == _MAIN_PY
    assert main.stat().st_mode & 0o7000 == 0


def test_only_the_exact_names_of_slots_are_served(render_home, caplog):
    """A file named like a slot but not as one is set aside at import and never served."""
    png = b'\x89PNG\r\n\x1a\n' + bytes(32)
    files = {
        'main.py': _MAIN_PY,
        'cuju-team/shirt-back.png': png,
        'cuju-team/shirt-front.x.png': b'<script>unchecked</script>',
        'cuju-team/Sponsor-1.png': b'unchecked',
        'cuju-team/sponsor-2.PNG': b'unchecked',
        'cuju-team/sound-goal.OGG': b'unchecked',
        'cuju-team/MODEL.GLB': b'unchecked',
        'cuju-team/clips/foo.GLB': b'unchecked',
        'cuju-team/clips/foo.json': b'{"animations": ["dance"], "joints": {}}',
        'cuju-team/notes.shirt-front.png': png,
    }
    with caplog.at_level(logging.WARNING, logger='cuju'):
        team = _teams.add('', 'team.zip', _archive(files))
    assert team['images'] == ['shirt-back'] and team['sounds'] == [] and team['clips'] == []
    folder = _home.folder('teams') / team['id'] / _teams.TEAM_FOLDER
    names = sorted(path.relative_to(folder).as_posix() for path in folder.rglob('*'))
    assert names == [
        'MODEL.GLB.rejected',
        'Sponsor-1.png.rejected',
        'clips',
        'clips/foo.GLB.rejected',
        'clips/foo.json',
        'notes.shirt-front.png',
        'shirt-back.png',
        'shirt-front.x.png.rejected',
        'sound-goal.OGG.rejected',
        'sponsor-2.PNG.rejected',
        'team.json',
    ]
    # A file put beside the slots later is never served by a name that is not exactly the slot's.
    (folder / 'shirt-front.x.png').write_bytes(b'<script>planted</script>')
    (folder / 'sound-shot.x.ogg').write_bytes(b'planted')
    assert _teams.image_path(team['id'], 'shirt-front') is None
    assert _teams.sound_path(team['id'], 'shot') is None
    assert _teams.entry(team['id'])['images'] == ['shirt-back']


def test_files_of_a_team_that_are_links_are_never_served(render_home, tmp_path):
    """An image, sound, model or clip that is a link, which could point anywhere, is not served."""
    from cuju.render._registry import clips as _clips

    team = _teams.add('Linked', 'main.py', _MAIN_PY)
    folder = _home.folder('teams') / team['id'] / _teams.TEAM_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'clips').mkdir()
    outside = tmp_path / 'outside.bin'
    outside.write_bytes(b'\x89PNG\r\n\x1a\n' + bytes(32))
    for name in ('shirt-front.png', 'sound-goal.ogg', 'model.glb', 'clips/foo.glb'):
        (folder / name).symlink_to(outside)
    assert _teams.image_path(team['id'], 'shirt-front') is None
    assert _teams.sound_path(team['id'], 'goal') is None
    assert _teams.model_path(team['id']) is None
    assert _clips.clip_path(team['id'], 'foo') is None
    listed = _teams.entry(team['id'])
    assert listed['images'] == [] and listed['sounds'] == [] and listed['clips'] == []


def test_team_sounds_version_follows_the_files(render_home):
    """The version of a team's sounds changes whenever a sound is stored, replaced or removed."""
    import zipfile

    team = _teams.add('Singers', 'main.py', b'def agent(obs):\n    return 0\n')
    assert team['sounds'] == [] and team['sounds_version'] == ''
    first = _teams.set_sound(team['id'], 'goal', _OGG + bytes(60))
    assert first['sounds'] == ['goal'] and first['sounds_version']
    assert _teams.entry(team['id'])['sounds_version'] == first['sounds_version']
    # The same slot and kind with other bytes, as a replaced file, makes a new version.
    second = _teams.set_sound(team['id'], 'goal', _OGG + bytes(61))
    assert second['sounds_version'] not in ('', first['sounds_version'])
    third = _teams.set_sound(team['id'], 'goal', _OGG + bytes(61))
    assert third['sounds_version'] != second['sounds_version']
    meta = _home.folder('teams') / team['id'] / _teams.TEAM_FOLDER / 'team.json'
    assert 'sounds_version' not in json.loads(meta.read_text(encoding='utf-8'))
    _teams.update(team['id'], name='Choir')
    assert 'sounds_version' not in json.loads(meta.read_text(encoding='utf-8'))
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
    return json.loads(path.read_text(encoding='utf-8'))


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
    assert 'attachment halo left out' in warnings and 'behaviour x left out' in warnings
    assert 'reflex 6 left out' in warnings
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
    assert json.loads((path / 'presentation.json').read_text(encoding='utf-8')) == {
        'contract': '1.9'
    }
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


def test_pack_check_and_import_agree_on_the_team_model(render_home, tmp_path):
    """A rigged model without joints in team.json maps by its bone names in both, else neither."""
    from cuju.render._packages import pack as _pack
    from support.package import package_files

    model = next(v for k, v in package_files().items() if k.endswith('cuju-team/model.glb'))
    folder = _template_variant(tmp_path, 'model', lambda p, m: None)
    (folder / 'cuju-team/model.glb').write_bytes(model)
    result = _pack.check(folder)
    assert result['ok'], result['errors']
    mapped = 'import maps model.glb by its bone names, body to mixamorig:Hips'
    assert any(mapped in item for item in result['info']), result['info']
    entry = _teams.add('', 'team.zip', _zip_folder(folder, tmp_path / 'model.zip').read_bytes())
    assert entry['model']['joints']['body'] == 'mixamorig:Hips'
    assert entry['model']['joints']['right_ankle'] == 'mixamorig:RightFoot'
    assert entry['style']['model'] == 'custom'
    # A model without a skin is set aside by import and is an error of the check.
    (folder / 'cuju-team/model.glb').write_bytes(_pack.ring_bytes())
    result = _pack.check(folder)
    aside = 'the team model.glb fails the checks of an uploaded model'
    assert any(aside in error for error in result['errors']), result['errors']
    entry = _teams.add('', 'team.zip', _zip_folder(folder, tmp_path / 'ring.zip').read_bytes())
    assert entry['model'] is None


def test_pack_preview_updates_its_team_and_opens_no_browser(
    render_home, tmp_path, capsys, monkeypatch
):
    """A second preview of a folder keeps the team's id, named by the manifest, on its side."""
    from cuju.render.__main__ import main
    from cuju.render._packages import pack as _pack
    from cuju.render._packages import presentation as _presentation

    folder = _template_variant(tmp_path, 'team', lambda p, m: m.__setitem__('name', 'Lanterns'))
    first = _pack.register_preview(folder, 'right')
    assert first['name'] == 'Lanterns' and first['place'].endswith('&preview=right')
    count = len(_teams.teams())
    manifest = folder / 'cuju-team/presentation/presentation.json'
    manifest.write_text(
        manifest.read_text(encoding='utf-8').replace('Lanterns', 'Lanterns two'), encoding='utf-8'
    )
    second = _pack.register_preview(manifest, 'right')
    assert second['team'] == first['team'] and len(_teams.teams()) == count
    assert _teams.entry(first['team'])['name'] == 'Lanterns two'
    assert _presentation.served(first['team'])['manifest']['name'] == 'Lanterns two'
    assert _presentation.sides()['right'] == first['team']
    # With a server running, --no-open prints the address as JSON and opens nothing.
    opened = []
    server = _launch.Server(port=8799, pid=os.getpid(), key='k', home=render_home)
    monkeypatch.setattr(_launch, 'running', lambda: server)
    monkeypatch.setattr(_launch, 'open_browser', lambda url: opened.append(url) or True)
    assert main(['pack', 'preview', str(folder), '--json', '--no-open', '--side', 'left']) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown['team'] == first['team'] and shown['side'] == 'left' and opened == []
    assert shown['url'].startswith('http://127.0.0.1:8799/#match=')
    assert shown['url'].endswith('&preview=left')
    assert main(['pack', 'preview', str(folder)]) == 0
    assert opened and opened[0].endswith('&preview=left')


def test_teams_without_a_kit_take_kits_in_turn(render_home, tmp_path):
    """A team file without a kit keeps the kit of the turn, and a preview keeps its team's kit."""
    from cuju.render._packages import pack as _pack

    first = _template_variant(tmp_path, 'first', lambda p, m: None)
    second = _template_variant(tmp_path, 'second', lambda p, m: m.__setitem__('name', 'Other'))
    one = _pack.register_preview(first)
    two = _pack.register_preview(second, 'right')
    kits = [_teams.entry(x['team'])['style']['kit']['primary'] for x in (one, two)]
    assert kits[0] != kits[1], kits
    again = _pack.register_preview(first)
    assert again['team'] == one['team']
    assert _teams.entry(one['team'])['style']['kit']['primary'] == kits[0]
    # A team file that names a kit keeps it.
    named = tmp_path / 'named'
    _pack.new(named, 'Named')
    team = json.loads((named / 'cuju-team/team.json').read_text(encoding='utf-8'))
    team['style'] = {'kit': {'primary': [10, 200, 30]}}
    (named / 'cuju-team/team.json').write_text(json.dumps(team), encoding='utf-8')
    shown = _pack.register_preview(named)
    assert _teams.entry(shown['team'])['style']['kit']['primary'] == [10, 200, 30]


def test_team_sounds_are_read_past_their_first_bytes(render_home):
    """A sound must hold what its kind holds, a header alone or a stray sync is refused."""
    from cuju.render._packages import pack as _pack

    team = _teams.add('Singers', 'main.py', b'def agent(obs):\n    return 0\n')
    assert _teams.set_sound(team['id'], 'shot', _pack.tone_bytes())['sounds'] == ['shot']
    assert _teams.set_sound(team['id'], 'goal', _OGG)['sounds'] == ['goal', 'shot']
    tagged = b'ID3\x04\x00\x00\x00\x00\x00\x00' + b'\xff\xfb\x90\x00' + bytes(400)
    assert _teams.set_sound(team['id'], 'pass', tagged)['sounds'] == ['goal', 'shot', 'pass']
    refused = {
        b'RIFF\x08\x00\x00\x00WAVEfmt ': ('server.teams.sound_damaged', 'WAV'),
        _pack.tone_bytes()[:44]: ('server.teams.sound_damaged', 'WAV'),
        b'OggS' + bytes(60): ('server.teams.sound_damaged', 'Ogg'),
        b'ID3' + bytes(40): ('server.teams.sound_damaged', 'MP3'),
        b'\xff\xfb\x90\x00' + bytes(12): ('server.teams.sound_type', None),
    }
    for data, (message, kind) in refused.items():
        with pytest.raises(cuju.errors.ArgumentError) as caught:
            _teams.set_sound(team['id'], 'save', data)
        assert caught.value.message_id == message, (data[:16], caught.value.message_id)
        if kind:
            assert f'expected a whole {kind} sound' in str(caught.value)
    assert 'save' not in _teams.entry(team['id'])['sounds']


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
    first = record('corner', _board_entry('Ana', 2, 9.0, 1))
    # A competitor's first run says so, rather than a new personal best.
    assert first['rank'] == 1 and first['improved'] and first['first']
    assert record('corner', _board_entry('Bo', 2, 7.0, 2))['rank'] == 1
    # The tie on value and seconds goes to the earlier run.
    assert record('corner', _board_entry('Cy', 2, 9.0, 3))['rank'] == 3
    worse = record('corner', _board_entry('Ana', 1, 1.0, 4))
    assert not worse['improved'] and worse['personal_best']['value'] == 2 and worse['rank'] == 2
    assert not worse['first']
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
    document = json.loads(path.read_text(encoding='utf-8'))
    document['entries'].append({**document['entries'][0], 'value': 'many'})
    document['entries'].append({**document['entries'][0], 'kind': 'robot'})
    path.write_text(json.dumps(document), encoding='utf-8')
    (path.parent / 'run_to_score.json').write_text('{', encoding='utf-8')
    (path.parent / 'counterattack_easy.json').write_text(
        '{"challenge": "corner", "entries": []}', encoding='utf-8'
    )
    with caplog.at_level(logging.WARNING, logger='cuju'):
        assert len(_challenges.board('corner')) == 4
        assert _challenges.board('run_to_score') == []
        assert _challenges.board('counterattack_easy') == []
    warnings = [record.getMessage() for record in caplog.records if record.name == 'cuju']
    assert len(warnings) == 3 and '2 invalid entries' in warnings[0]


def test_samples_add_restore_and_register_the_starter_team(render_home):
    from cuju.render._store import samples as _samples

    listed = {entry['id']: entry for entry in _samples.listing()}
    assert list(listed) == ['sample-5v5', 'sample-11v11', 'starter-team']
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


def test_cli_team_control_show_set_and_json(render_home, tmp_path, capsys):
    from cuju.render.__main__ import main

    folder = tmp_path / 'submission'
    folder.mkdir()
    (folder / 'main.py').write_text('def agent(obs):\n    return [0]\n', encoding='utf-8')
    assert (
        main(['team', 'add', str(folder), '--format', '5v5', '--selection', '1,2', '--json']) == 0
    )
    added = json.loads(capsys.readouterr().out)
    assert added['control'] == {
        'players': 2,
        'assignment': 'fixed',
        'selection': [1, 2],
        'goalkeeper': 'scenario',
        'action_set': 'default',
    }
    assert main(['team', 'set', added['id'], '--assignment', 'dynamic', '--players', '3']) == 0
    assert 'changed' in capsys.readouterr().out
    control = _teams.entry(added['id'])['control']
    assert (control['players'], control['assignment'], control['selection']) == (3, 'dynamic', [])
    assert main(['team', 'set', added['id'], '--name', 'Renamed', '--action-set', 'v2']) == 0
    capsys.readouterr()
    assert main(['team', 'show', added['id']]) == 0
    shown = capsys.readouterr().out
    assert 'Renamed' in shown and 'action set v2' in shown and '3 controlled' in shown
    assert main(['team', 'list', '--json']) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [team['id'] for team in listed] == ['builtin', added['id']]
    assert main(['sample', 'list', '--json']) == 0
    assert [entry['id'] for entry in json.loads(capsys.readouterr().out)][:2] == [
        'sample-5v5',
        'sample-11v11',
    ]
    assert main(['team', 'remove', added['id']]) == 0
    assert f'removed {added["id"]}' in capsys.readouterr().out
    assert main(['team', 'add', str(tmp_path / 'nowhere')]) == 1
    assert 'found nothing at' in capsys.readouterr().err


def test_new_teams_take_kits_in_turn(render_home, tmp_path):
    folder = tmp_path / 'submission'
    folder.mkdir()
    (folder / 'main.py').write_text('def agent(obs):\n    return [0]\n', encoding='utf-8')
    kits = [_teams.add_folder(folder, f'Team {k}')['style']['kit']['primary'] for k in range(3)]
    assert len({tuple(kit) for kit in kits}) == 3


def test_message_error_reads_and_catches_as_before():
    from cuju.render._text import messages as _messages

    error = _messages.MessageError('server.scenario', scenario=repr('nowhere'))
    assert str(error) == "expected a shipped scenario, found 'nowhere'"
    assert isinstance(error, cuju.errors.ArgumentError) and isinstance(error, ValueError)
    assert (error.message_id, error.values) == ('server.scenario', {'scenario': "'nowhere'"})
    assert _messages.described(error) == f'ArgumentError: {error}'
    with pytest.raises(cuju.errors.ArgumentError, match=r'^expected an ability from 0 to 1'):
        _teams.check_ability([None, 2])
    with pytest.raises(ValueError, match=r'^expected a seed from 0 to 2\*\*64 - 1, found -1$'):
        _server._seed(-1)
    try:
        _teams.check_ability([None, 2])
    except ValueError as caught:
        assert _messages.error_fields(caught) == {
            'error': 'expected an ability from 0 to 1, found 2',
            'error_id': 'server.teams.ability',
            'error_values': {'value': '2'},
        }
    # A message keeps a brace that names no placeholder as text, as the page does.
    assert _messages.text('server.teams.crowd', value='1') == (
        'expected the crowd as {"colors": [...]}, found 1'
    )
    assert _messages.error_fields(ValueError('plain')) == {'error': 'plain'}


def test_names_of_the_built_in_ai_travel_as_a_label_until_renamed(render_home):
    builtin = _teams.teams()[0]
    assert builtin['name'] == "GRF's built-in AI"
    assert builtin['name_id'] == 'server.names.builtin' and builtin['name_values'] == {}
    header = _teams.header_team(_teams.BUILTIN)
    assert header['name_id'] == 'server.names.builtin'
    # The page sends the name back with every change of the style, which keeps the label.
    kept = _teams.update(_teams.BUILTIN, name="GRF's built-in AI")
    assert kept['name_id'] == 'server.names.builtin'
    renamed = _teams.update(_teams.BUILTIN, name='House AI')
    assert renamed['name'] == 'House AI' and 'name_id' not in renamed
    assert 'name_id' not in _teams.entry(_teams.BUILTIN)
    stored = json.loads(_teams._meta_path(_teams.BUILTIN).read_text(encoding='utf-8'))
    assert stored['name'] == 'House AI' and 'name_id' not in stored
    _teams.update(_teams.BUILTIN, name="GRF's built-in AI")
    assert _teams.entry(_teams.BUILTIN)['name_id'] == 'server.names.builtin'


def test_names_of_scenarios_in_team_messages_travel_as_scenarios(render_home):
    from cuju.render._text import messages as _messages

    team = {'id': 't', 'name': 'Multi four', 'kind': 'submission', 'format': '5v5'}
    with pytest.raises(_messages.MessageError) as raised:
        _teams.check_scenario([team, _teams.entry(_teams.BUILTIN)], '11_vs_11_kaggle')
    error = raised.value
    assert error.message_id == 'server.teams.scenario_format'
    assert error.values['scenario'] == _messages.scenario('11_vs_11_kaggle')
    # The English text of the command line stays as it was.
    assert str(error) == 'expected a scenario of 5v5 for Multi four, found 11_vs_11_kaggle'
    assert _messages.valid_label(
        {'id': error.message_id, 'text': str(error), 'values': error.values}
    )


def test_names_of_games_and_challenges(render_home):
    from cuju.render._playing import challenges as _challenges
    from cuju.render._playing import play as _play
    from cuju.render._text import messages as _messages

    builtin = _messages.label('server.names.builtin')
    title = _play.game_title([_messages.label('server.names.you'), builtin], None)
    assert title['text'] == "You against GRF's built-in AI"
    assert title['values']['right'] == builtin
    entry = {'kind': 'agent', 'name': "GRF's built-in AI", 'team': _teams.BUILTIN}
    assert _challenges.competitor_name(entry) == builtin
    policy = {'kind': 'agent', 'name': 'Python policy', 'team': None}
    assert _challenges.competitor_name(policy)['id'] == 'server.names.python_policy'
    # A person's name and a renamed team stay text.
    assert _challenges.competitor_name({'kind': 'person', 'name': 'Ana', 'team': None}) == 'Ana'
    renamed = {'kind': 'agent', 'name': 'House AI', 'team': _teams.BUILTIN}
    assert _challenges.competitor_name(renamed) == 'House AI'
    spec = _challenges.find('empty_goal_close')
    attempt = _messages.label(
        'server.names.challenge_attempt',
        challenge=_challenges.challenge_value(spec),
        attempt=5,
        competitor='Rule bot',
    )
    assert attempt['text'] == f'{spec["title"]}, attempt 5, Rule bot'
    assert _messages.valid_label(attempt)


def test_a_team_folder_named_as_a_random_side_is_left_out(render_home, tmp_path, caplog):
    from cuju.render._playing import draw as _draw

    assert _draw.RANDOM in _teams.RESERVED
    kept = _toy_team(tmp_path, 'kept', 'def agent(obs):\n    return [0]\n', '5v5')
    folders = render_home / 'teams'
    shutil.copytree(folders / kept['id'], folders / _draw.RANDOM)
    with caplog.at_level(logging.WARNING):
        identifiers = [team['id'] for team in _teams.teams()]
    # The team by its own folder stays, and the folder that a request would read as a random side
    # is left out with a word on how to keep it.
    assert identifiers == ['builtin', kept['id']]
    assert 'rename the folder' in caplog.text


_FITS = json.loads(
    (Path(__file__).with_name('support') / 'control_fits.json').read_text(encoding='utf-8')
)


@pytest.mark.parametrize('case', _FITS['controls'], ids=lambda case: str(case['fault']))
def test_the_control_of_a_team_fits_a_side_as_the_page_checks_it(case):
    # tests/web/draw.mjs checks the page's rule with the same cases.
    from types import SimpleNamespace

    control = _teams.check_control(case['control'], case['format'])
    formation = [SimpleNamespace(role=role, controllable=free) for role, free in case['formation']]
    try:
        _teams.selected_players(control, formation)
    except cuju.ArgumentError as error:
        values = {key: str(value) for key, value in error.values.items()}
        fault = {'id': error.message_id, 'values': values}
    else:
        fault = None
    expected = case['fault'] and {
        'id': case['fault']['id'],
        'values': {key: str(value) for key, value in case['fault']['values'].items()},
    }
    assert fault == expected


@pytest.mark.parametrize('case', _FITS['formats'], ids=lambda case: case['scenario'])
def test_the_format_of_a_team_fits_a_scenario_as_the_page_checks_it(case):
    size = _teams.scenario_size(case['scenario'].removeprefix('benchmark_full_game_'))
    assert (size is None or size == _teams.FORMATS[case['format']]) == case['fits']


def test_the_mock_knows_the_players_of_each_scenario_as_the_server():
    table = json.loads(
        (Path(__file__).parents[1] / 'ci' / 'mock_scenario_sides.json').read_text(encoding='utf-8')
    )
    for name, sides in table.items():
        found = [[[role, free] for role, free in side] for side in _teams.scenario_sides(name)]
        assert found == sides, name
