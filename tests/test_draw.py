# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of requested matches drawn at random, their teams, scenarios, pools and seeds."""

import json
import re
import threading
import urllib.error
from pathlib import Path

import pytest

import cuju
from cuju.render._format import recording as _recording
from cuju.render._http import server as _server
from cuju.render._playing import draw as _draw
from cuju.render._registry import teams as _teams
from cuju.render._store import library as _library
from support.common import _control, _get, _send, _short_matches, _toy_team

RANDOM = _draw.RANDOM
# A toy submission that sends one action for each player it controls.
_EACH = """
def agent(obs):
    return [5] * len(obs['players_raw'])
"""


def _registry(tmp_path):
    """Adds two 5v5 teams, one that plays three players, and one 11v11 team."""
    four = _toy_team(tmp_path, 'four', _EACH, '5v5', _control(4))
    three = _toy_team(tmp_path, 'three', _EACH, '5v5', _control(3))
    eleven = _toy_team(tmp_path, 'eleven', _EACH, '11v11')
    return four['id'], three['id'], eleven['id']


def test_listed_scenarios_follow_the_page():
    source = (Path(_draw.__file__).parents[1] / 'web' / 'js' / 'core' / 'scenarios.js').read_text(
        encoding='utf-8'
    )
    hidden = re.search(r'const HIDDEN = /\^\((.+?)\)/;', source)
    assert hidden and hidden.group(1) == _draw._HIDDEN.pattern[1:-1]
    names = ['test_example_multiagent', '5_vs_5', 'benchmark_full_game_5_vs_5_easy']
    assert _draw.listed(names) == ['5_vs_5']


def test_pick_keeps_two_sides_apart_unless_a_team_may_meet_itself():
    options = [('5_vs_5', ['a', 'b'], ['a', 'b'])]
    for seed in range(200):
        _, left, right = _draw.pick(seed, options)
        assert left != right
    meetings = {_draw.pick(seed, options, same_team=True)[1:] for seed in range(200)}
    assert ('a', 'a') in meetings and ('a', 'b') in meetings
    # One team alone meets itself, since nothing else fits.
    assert _draw.pick(3, [('5_vs_5', ['a'], ['a'])]) == ('5_vs_5', 'a', 'a')
    # A side with one candidate leaves the other side the rest.
    assert {_draw.pick(seed, [('5_vs_5', ['a', 'b'], ['a'])])[1] for seed in range(50)} == {'b'}
    assert _draw.pick(1, [('5_vs_5', ['a'], [])]) is None


def test_the_seed_decides_the_draw():
    options = [(name, ['a', 'b', 'c', 'd'], ['a', 'b', 'c', 'd']) for name in ('x', 'y', 'z')]
    # The same seed draws the same match, which a retry relies on.
    assert all(_draw.pick(seed, options) == _draw.pick(seed, options) for seed in range(50))
    # The draw of a seed is fixed, the same on every system and version of Python.
    assert _draw.pick(7, options) == _draw.pick(7, list(options))
    draws = {_draw.pick(seed, options) for seed in range(100)}
    assert len(draws) > 20
    assert {found[0] for found in draws} == {'x', 'y', 'z'}


def test_resolve_checks_its_request():
    def fail(message_id, **values):
        return ValueError(message_id)

    def run(sides=(RANDOM, RANDOM), scenario='s', pool=None, same_team=False):
        return _draw.resolve(sides, scenario, 1, pool, same_team, ['a', 'b'], ['s'], fits, fail)

    def fits(identifier, name, side):
        return identifier == 'a' or side == 1

    assert run(('a', 'b')) is None
    found = run()
    assert (found['left'], found['right'], found['scenario']) == ('a', 'b', 's')
    assert found['draw'] == {
        'sides': [True, True],
        'scenario': False,
        'pool': None,
        'same_team': False,
    }
    assert _draw.valid(found['draw']) and _draw.valid(None)
    assert not _draw.valid({**found['draw'], 'sides': [True]})
    assert not _draw.valid({**found['draw'], 'pool': 'a'})
    for wrong, message_id in (
        ({'pool': []}, 'server.draw.pool'),
        ({'pool': 'a'}, 'server.draw.pool'),
        ({'pool': [1]}, 'server.draw.pool'),
        ({'pool': ['a', 'zz']}, 'server.teams.unknown'),
        ({'sides': ('zz', RANDOM)}, 'server.teams.unknown'),
        ({'same_team': 'yes'}, 'server.draw.same_team'),
        ({'pool': ['b']}, 'server.draw.left'),
        ({'sides': ('b', RANDOM), 'scenario': RANDOM, 'pool': ['b']}, 'server.draw.scenario'),
    ):
        with pytest.raises(ValueError, match=re.escape(message_id)):
            run(**wrong)


def test_a_random_side_draws_a_team_that_fits_its_format_and_control(render_home, tmp_path):
    four, three, eleven = _registry(tmp_path)

    def drawn(left, right, scenario, side):
        found = (_draw.draw_request(left, right, scenario, seed, None, True) for seed in range(60))
        return {entry[side] for entry in found}

    assert drawn(RANDOM, 'builtin', '5_vs_5', 'left') == {'builtin', four, three}
    assert drawn(RANDOM, 'builtin', '11_vs_11_kaggle', 'left') == {'builtin', eleven}
    # A random side meets another team than the other side's, unless a team may meet itself.
    found = {_draw.draw_request(RANDOM, 'builtin', '5_vs_5', s)['left'] for s in range(60)}
    assert found == {four, three}
    # In the drill of three against one, the right side holds two controllable players, too few for
    # a team of three, and the left side holds four.
    scenario = 'academy_3_vs_1_with_keeper'
    assert three not in drawn('builtin', RANDOM, scenario, 'right')
    assert {four, three} <= drawn(RANDOM, 'builtin', scenario, 'left')
    pool = [four, three]
    for seed in range(40):
        found = _draw.draw_request(RANDOM, RANDOM, '5_vs_5', seed, pool)
        assert {found['left'], found['right']} == {four, three}
        assert found['draw']['pool'] == sorted(pool)
    with pytest.raises(cuju.ArgumentError) as refused:
        _draw.draw_request('builtin', RANDOM, scenario, 1, [three])
    assert refused.value.message_id == 'server.draw.right'
    assert 'right side of academy_3_vs_1_with_keeper' in str(refused.value)


def test_a_random_scenario_fits_both_teams(render_home, tmp_path):
    four, _, eleven = _registry(tmp_path)
    drawn = {_draw.draw_request(four, 'builtin', RANDOM, seed)['scenario'] for seed in range(80)}
    assert '5_vs_5' in drawn
    assert not any(name.startswith('11_vs_11') for name in drawn)
    assert not any(name.startswith(('benchmark_', 'test_')) for name in drawn)
    for seed in range(20):
        found = _draw.draw_request(four, eleven, RANDOM, seed)
        assert found['scenario'].startswith('academy_')
    # Two random sides of a pool of both formats draw a scenario that the two teams drawn play.
    for seed in range(20):
        found = _draw.draw_request(RANDOM, RANDOM, RANDOM, seed, [four, eleven])
        sides = [_teams.entry(found['left']), _teams.entry(found['right'])]
        _teams.check_scenario(sides, found['scenario'])


def test_requests_keep_their_draw_and_retry_draws_it_again(monkeypatch, render_home, tmp_path):
    monkeypatch.setattr(_server._Requests, '_run', lambda self: None)
    four, three, eleven = _registry(tmp_path)
    requests = _server._Requests()
    first = requests.add(RANDOM, RANDOM, '5_vs_5', None, (None, None), None, False)
    assert isinstance(first['seed'], int)
    assert first['left'] != first['right']
    assert {first['left'], first['right']} <= {'builtin', four, three}
    assert first['draw'] == {
        'sides': [True, True],
        'scenario': False,
        'pool': None,
        'same_team': False,
    }
    # Retry sends the request again with its seed, and draws the same teams.
    retry = requests.add(RANDOM, RANDOM, '5_vs_5', first['seed'])
    assert (retry['left'], retry['right']) == (first['left'], first['right'])
    # Repeat leaves the seed to the server, which draws anew.
    repeats = {
        (entry['seed'], entry['left'], entry['right'])
        for entry in (requests.add(RANDOM, RANDOM, '5_vs_5', None) for _ in range(12))
    }
    assert len({teams[1:] for teams in repeats}) > 1
    scenario = requests.add('builtin', RANDOM, RANDOM, 5, pool=[eleven])
    assert scenario['right'] == eleven and scenario['draw']['scenario'] is True
    assert scenario['draw']['pool'] == [eleven]
    plain = requests.add('builtin', 'builtin', '5_vs_5', 3)
    assert plain['draw'] is None
    # The history keeps each draw across a restart of the server.
    recovered = {entry['id']: entry for entry in _server._Requests().entries()}
    assert recovered[first['id']]['draw'] == first['draw']
    assert recovered[scenario['id']]['draw'] == scenario['draw']
    assert recovered[plain['id']]['draw'] is None
    with pytest.raises(cuju.ArgumentError) as refused:
        requests.add(RANDOM, 'builtin', '11_vs_11_kaggle', 1, pool=[four, three])
    assert refused.value.message_id == 'server.draw.left'


def test_the_match_process_keeps_the_draw(monkeypatch, render_home, tmp_path):
    seen = []

    class StartError(Exception):
        pass

    def start(command, **options):
        seen.append(command)
        raise StartError

    monkeypatch.setattr(_server._Requests, '_run', lambda self: None)
    monkeypatch.setattr(_server.subprocess, 'Popen', start)
    four, three, _ = _registry(tmp_path)
    requests = _server._Requests()
    added = requests.add(RANDOM, RANDOM, '5_vs_5', 11, pool=[four, three])
    entry = requests._entries[-1]
    with pytest.raises(StartError):
        requests._play_child(entry)
    command = seen[0]
    assert command[command.index('--left') + 1] == added['left']
    assert json.loads(command[command.index('--draw') + 1]) == added['draw']


def test_requests_route_draws_teams(monkeypatch, render_home, tmp_path):
    monkeypatch.setattr(_server._Requests, '_run', lambda self: None)
    four, three, _ = _registry(tmp_path)
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        body = {'left': RANDOM, 'right': RANDOM, 'scenario': '5_vs_5', 'seed': 21}
        pooled = json.dumps({**body, 'pool': [four, three]}).encode()
        first = _send(address, '/api/requests', pooled)
        assert {first['left'], first['right']} == {four, three}
        assert first['draw']['sides'] == [True, True]
        again = _send(address, '/api/requests', pooled)
        assert (again['left'], again['right']) == (first['left'], first['right'])
        same = _send(
            address,
            '/api/requests',
            json.dumps({**body, 'pool': [four], 'same_team': True}).encode(),
        )
        assert same['left'] == same['right'] == four
        listed = json.loads(_get(address, '/api/requests')[1])
        assert listed[0]['draw']['same_team'] is True
        for wrong, message_id in (
            ({'pool': 'all'}, 'server.draw.pool'),
            ({'same_team': 1}, 'server.draw.same_team'),
            ({'pool': ['t-missing']}, 'server.teams.unknown'),
            ({'scenario': '11_vs_11_kaggle', 'pool': [four, three]}, 'server.draw.left'),
        ):
            with pytest.raises(urllib.error.HTTPError) as refused:
                _send(address, '/api/requests', json.dumps({**body, **wrong}).encode())
            assert refused.value.code == 400
            answer = json.loads(refused.value.read())
            assert answer['error_id'] == message_id, answer
    finally:
        server.shutdown()
        server.server_close()


def test_command_line_plays_a_drawn_match(monkeypatch, render_home, tmp_path, capsys):
    from cuju.render.__main__ import main

    _short_matches(monkeypatch, 20)
    four, three, _ = _registry(tmp_path)
    arguments = ['play', '--left', 'random', '--right', 'random', '--scenario', '5_vs_5']
    arguments += ['--pool', f'{four},{three}', '--seed', '4', '--json']
    assert main(arguments) == 0
    answer = json.loads(capsys.readouterr().out)
    assert {answer['left'], answer['right']} == {four, three}
    assert answer['seed'] == 4 and answer['scenario'] == '5_vs_5'
    assert answer['draw']['pool'] == sorted([four, three])
    header = _recording.read_header(Path(answer['path']))
    assert header['provenance']['teams'] == [answer['left'], answer['right']]
    assert header['provenance']['draw'] == answer['draw']
    assert main(arguments) == 0
    assert json.loads(capsys.readouterr().out)['left'] == answer['left']
    assert main(['play', '--right', 'random', '--pool', four, '--scenario', '5_vs_5']) == 0
    printed = capsys.readouterr().out
    assert f'drew builtin on the left and {four} on the right in 5_vs_5' in printed
    assert main(['play', '--left', 'random', '--pool', four, '--json']) == 1
    assert json.loads(capsys.readouterr().out)['error_id'] == 'server.draw.left'
    assert len(_library.matches()) == 3
