# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the medal items of the challenges, model runs that count failed attempts, and the
benchmark of models by challenges, its table, its command and its routes."""

import json
import os
import struct
import threading
import time
import urllib.error
import urllib.request

import pytest

import cuju.errors
from cuju.render._format import recording as _recording
from cuju.render._http import server as _server
from support.common import (
    _SINGLE,
    _control,
    _frames,
    _get,
    _send,
    _short_challenges,
    _toy_team,
)

_SUPPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'support')


def _shared(name):
    with open(os.path.join(_SUPPORT, name), encoding='utf-8') as stream:
        return json.load(stream)


def _played(attempts):
    """The results of attempts without the recordings they name, which differ from run to run."""
    return [{key: value for key, value in item.items() if key != 'match'} for item in attempts]


def test_medal_items_list_gold_silver_and_bronze_with_the_reached_one():
    from cuju.render._playing import challenges as _challenges

    for case in _shared('medal_items.json'):
        spec = _challenges.find(case['challenge']['id'])
        assert _challenges.medal_items(spec, case['value']) == case['items']
        assert _challenges.medal_text(spec, case['value']) == case['text']
    corner = _challenges.find('corner')
    assert corner['medals'] == _challenges.medal_items(corner)
    assert [item['medal'] for item in corner['medals']] == ['gold', 'silver', 'bronze']
    assert not any(item['reached'] for item in corner['medals'])
    reached = _challenges.medal_items(corner, 3)
    assert [item['medal'] for item in reached if item['reached']] == ['silver']
    assert [item['every'] for item in _challenges.medal_items(_challenges.find('empty_goal'))] == [
        True,
        False,
        False,
    ]
    margin = _challenges.find('one_on_one')
    assert _challenges.medal_text(margin, 9) == (
        'medals gold, 6 goals or more ahead, reached; silver, 3 goals or more ahead; '
        'bronze, 1 goal or more ahead'
    )
    assert not any(item['every'] for item in _challenges.medal_items(margin, 9))


def test_a_model_run_counts_a_failing_attempt_as_failed_and_goes_on(render_home, monkeypatch):
    from cuju.render._playing import challenges as _challenges
    from cuju.render._playing import play as _play

    _short_challenges(monkeypatch, 4)
    calls = []

    def flaky(obs):
        calls.append(obs['step'])
        if len(calls) == 6:
            raise RuntimeError('no idea')
        return [12]

    outcome = _challenges.run('corner', policy=flaky, fail_attempts=True)
    attempts = outcome['attempts']
    assert [attempt['failed'] for attempt in attempts] == [False, True, False, False, False]
    failed = attempts[1]
    assert 'no idea' in failed['error'] and failed['error_id'] == 'server.policy.failed'
    assert not failed['finished'] and failed['goals'][0] == 0 and not failed['counts']
    assert outcome['failed_attempts'] == 1 and outcome['rank'] == 1 and not outcome['practice']
    # The failed attempt keeps the frames it played, and its recording says it failed.
    document, frames = _frames(render_home / 'matches' / f'{failed["match"]}.cjr')
    assert document['provenance']['failed'] is True and len(frames) == 2
    assert not struct.unpack_from('<i', frames[-1], 28)[0] & 1
    stored = _challenges.board('corner')[0]['attempts']
    assert [attempt['failed'] for attempt in stored] == [False, True, False, False, False]
    assert outcome['medals'] == _challenges.medal_items(
        _challenges.find('corner'), outcome['value']
    )
    # Without fail_attempts a failing policy raises, as before.
    calls.clear()
    with pytest.raises(_play.PolicyError, match='no idea'):
        _challenges.run('corner', policy=flaky, name='strict')


def test_a_model_that_cannot_load_fails_every_attempt(render_home, tmp_path, monkeypatch):
    from cuju.render._playing import challenges as _challenges

    _short_challenges(monkeypatch, 4)
    broken = _toy_team(tmp_path, 'broken', 'raise ImportError("no weights")\n', '11v11')
    outcome = _challenges.run('one_on_one', team=broken['id'], fail_attempts=True)
    assert [attempt['failed'] for attempt in outcome['attempts']] == [True, True, True]
    assert all('no weights' in attempt['error'] for attempt in outcome['attempts'])
    assert all(attempt['match'] is None for attempt in outcome['attempts'])
    assert outcome['value'] == 0 and outcome['medal'] is None and outcome['failed_attempts'] == 3
    assert _challenges.board('one_on_one')[0]['team'] == broken['id']


def test_a_model_run_is_reproducible(render_home, tmp_path, monkeypatch):
    from cuju.render._playing import challenges as _challenges

    _short_challenges(monkeypatch, 12)
    team = _toy_team(tmp_path, 'steady', _SINGLE, '11v11')
    first = _challenges.run('run_to_score', team=team['id'], keep_recordings=False)
    second = _challenges.run('run_to_score', team=team['id'], fail_attempts=True)
    assert _played(first['attempts']) == _played(second['attempts'])
    assert (first['value'], first['seconds'], first['medal']) == (
        second['value'],
        second['seconds'],
        second['medal'],
    )
    seeds = _challenges.find('run_to_score')['seeds']
    assert [attempt['seed'] for attempt in second['attempts']] == seeds


def _in_process(document, cell, attempt, started=None):
    """Plays a cell in the test's own process, so a shortened episode reaches it."""
    from cuju.render._playing import challenges as _challenges

    return _challenges.run(
        cell['challenge'],
        team=cell['team'],
        progress=attempt,
        keep_recordings=document['keep_recordings'],
        fail_attempts=True,
    )


def test_a_benchmark_plays_two_models_on_two_challenges(render_home, tmp_path, monkeypatch):
    from cuju.render._playing import bench as _bench
    from cuju.render._playing import challenges as _challenges

    _short_challenges(monkeypatch, 6)
    steady = _toy_team(tmp_path, 'steady', _SINGLE, '11v11')
    crashing = _toy_team(
        tmp_path,
        'crashing',
        "def agent(obs):\n    if obs['step'] == 2:\n        raise ValueError('broke')\n"
        '    return [5]\n',
        '11v11',
    )
    # A team of two players fits the empty goal, and the one on one has a single player a side.
    pair = _toy_team(tmp_path, 'pair', _SINGLE, '11v11', control=_control(2))
    teams = [steady['id'], crashing['id'], pair['id']]
    document = _bench.plan(teams, ['one_on_one', 'empty_goal_close'], workers=1)
    # The challenges follow the order of the catalog, and a team that cannot play a scenario
    # skips its challenge.
    assert document['challenges'] == ['empty_goal_close', 'one_on_one']
    assert [cell['state'] for cell in document['cells']] == ['queued'] * 5 + ['skipped']
    assert document['cells'][5]['error_id'] == 'server.teams.cannot_play'
    seen = []
    _bench.run(document, play=_in_process, changed=seen.append)
    cells = {(cell['team'], cell['challenge']): cell for cell in document['cells']}
    assert all(cells[(steady['id'], c)]['state'] == 'done' for c in document['challenges'])
    broken = cells[(crashing['id'], 'empty_goal_close')]
    assert broken['state'] == 'done' and broken['failed_attempts'] == 5
    assert all(result['failed'] for result in broken['results'])
    for cell in document['cells'][:5]:
        spec = _challenges.find(cell['challenge'])
        assert cell['played'] == spec['attempts'] == len(cell['results'])
        assert cell['medal'] == _challenges.medal(spec, cell['value'])
        board = _challenges.board(cell['challenge'])
        assert cell['team'] in [entry['team'] for entry in board]
    rows = {row['team']: row for row in document['rows']}
    for team in teams:
        row = rows[team]
        mine = [cell for cell in document['cells'] if cell['team'] == team]
        shares = [_bench.share(_challenges.find(cell['challenge']), cell) for cell in mine]
        assert row['score'] == round(100 * sum(shares) / 2, 1)
        assert row['gold'] + row['silver'] + row['bronze'] == sum(bool(c['medal']) for c in mine)
    assert rows[pair['id']]['done'] == 1
    assert sorted(row['place'] for row in document['rows'])[0] == 1
    assert document['progress'] == 1.0 and seen
    lines = _bench.csv_text(document).splitlines()
    assert lines[0].startswith('model,team,empty_goal_close value,empty_goal_close medal')
    assert len(lines) == 4 and lines[3].startswith(f'pair,{pair["id"]},')
    assert lines[3].split(',')[4:6] == ['', '']


def test_the_shared_table_case_matches_the_page():
    from cuju.render._playing import bench as _bench

    shared = _shared('bench_table.json')
    document = shared['document']
    assert _bench.table(document) == document['rows']
    assert _bench.progress(document) == document['progress']
    assert _bench.csv_text(document) == shared['csv']


def test_a_benchmark_checks_what_it_is_given(render_home):
    from cuju.render._playing import bench as _bench

    for teams, challenges, workers in (
        ([], None, None),
        (['builtin', 'builtin'], None, None),
        ('builtin', None, None),
        (['no-such-team'], None, None),
        (['builtin'], ['corner', 'corner'], None),
        (['builtin'], ['no_such_drill'], None),
        (['builtin'], [], None),
        (['builtin'], None, 0),
        (['builtin'], None, 9),
        (['builtin'], None, True),
    ):
        with pytest.raises(cuju.errors.ArgumentError):
            _bench.plan(teams, challenges, workers=workers)
    every = _bench.plan(['builtin'])
    assert every['challenges'] == [entry['id'] for entry in _bench._challenges.CATALOG]
    assert 1 <= every['workers'] == _bench.default_workers() <= 4
    assert not every['keep_recordings'] and every['progress'] == 0.0


def test_benchmark_command_keeps_each_model_apart(render_home, tmp_path, capsys):
    """Each run of the command plays in a process of its own, so no model sees another's state."""
    from cuju.render.__main__ import main

    marking = _toy_team(
        tmp_path,
        'marking',
        'import builtins\n\n\ndef agent(obs):\n    builtins.cuju_bench_mark = True\n'
        '    return [12]\n',
        '11v11',
    )
    looking = _toy_team(
        tmp_path,
        'looking',
        'import builtins\n\n\ndef agent(obs):\n'
        "    if getattr(builtins, 'cuju_bench_mark', False):\n"
        "        raise RuntimeError('saw another model')\n"
        '    return [12]\n',
        '11v11',
    )
    arguments = ['challenge', 'bench', '--team', marking['id'], '--team', looking['id']]
    arguments += ['--challenge', 'empty_goal_close', '--workers', '1', '--json']
    assert main(arguments) == 0
    document = json.loads(capsys.readouterr().out)
    assert [cell['state'] for cell in document['cells']] == ['done', 'done']
    assert [cell['failed_attempts'] for cell in document['cells']] == [0, 0]
    # The two models answer alike, so the same seeds give them the same results.
    first, second = document['cells']
    assert _played(first['results']) == _played(second['results'])
    assert first['value'] == second['value'] and first['medal'] == second['medal']
    assert document['rows'][0]['score'] == document['rows'][1]['score']
    assert all(result['match'] is None for result in first['results'])


def test_challenge_command_run_and_bench_arguments(render_home, capsys):
    from cuju.render.__main__ import main

    run = ['challenge', 'run', 'corner', '--team', 'builtin', '--attempts', '1']
    assert main([*run, '--json']) == 0
    outcome = json.loads(capsys.readouterr().out)
    assert outcome['practice'] and outcome['failed_attempts'] == 0 and len(outcome['medals']) == 3
    assert main(run) == 0
    assert 'medals gold, a goal in 4 attempts or more' in capsys.readouterr().out
    for wrong in (
        ['challenge', 'run', '--team', 'builtin'],
        ['challenge', 'run', 'corner'],
        ['challenge', 'run', 'corner', '--team', 'builtin', '--team', 'builtin'],
        ['challenge', 'corner', 'one_on_one', '--team', 'builtin'],
        ['challenge', 'bench'],
    ):
        with pytest.raises(SystemExit):
            main(wrong)
    capsys.readouterr()
    assert main(['challenge', 'bench', '--team', 'no-such-team', '--json']) == 1
    assert 'no-such-team' in json.loads(capsys.readouterr().out)['error']


def test_benchmark_routes(render_home):
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    address = f'http://127.0.0.1:{port}'
    try:
        for wrong in (
            {},
            {'teams': []},
            {'teams': ['builtin'], 'challenges': ['no_such_drill']},
            {'teams': ['builtin'], 'workers': 99},
            {'teams': ['builtin'], 'extra': 1},
            {'teams': ['builtin'], 'keep_recordings': 'yes'},
        ):
            with pytest.raises(urllib.error.HTTPError) as refused:
                _send(address, '/api/challenges/benches', json.dumps(wrong).encode())
            assert refused.value.code == 400, wrong
        body = json.dumps({'teams': ['builtin'], 'challenges': ['empty_goal_close']}).encode()
        other = _server.http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        other.request(
            'POST', '/api/challenges/benches', body=body, headers={'Origin': 'https://example.com'}
        )
        assert other.getresponse().status == 403
        other.close()
        job = _send(address, '/api/challenges/benches', body)
        assert job['state'] == 'queued' and job['challenges'] == ['empty_goal_close']
        waiting = _send(address, '/api/challenges/benches', body)
        request = urllib.request.Request(
            f'{address}/api/challenges/benches/{waiting["id"]}', method='DELETE'
        )
        with urllib.request.urlopen(request, timeout=10) as answer:
            assert answer.status == 200
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            done = json.loads(_get(address, f'/api/challenges/benches/{job["id"]}')[1])
            if done['state'] not in ('queued', 'running'):
                break
            time.sleep(0.5)
        assert done['state'] == 'done', done
        cell = done['cells'][0]
        assert cell['state'] == 'done' and cell['played'] == 5 and done['progress'] == 1.0
        assert done['rows'][0]['team'] == 'builtin' and done['rows'][0]['place'] == 1
        listed = json.loads(_get(address, '/api/challenges/benches')[1])
        assert {entry['id'] for entry in listed} == {job['id'], waiting['id']}
        cancelled = next(entry for entry in listed if entry['id'] == waiting['id'])
        assert cancelled['state'] == 'failed' and cancelled['error'] == 'cancelled'
        assert {c['state'] for c in cancelled['cells']} == {'cancelled'}
        with urllib.request.urlopen(
            f'{address}/api/challenges/benches/{job["id"]}/table.csv', timeout=10
        ) as answer:
            assert answer.headers['Content-Type'] == 'text/csv; charset=utf-8'
            text = answer.read().decode()
        assert text.splitlines()[1].startswith("GRF's built-in AI,builtin,")
        board = json.loads(_get(address, '/api/challenges/empty_goal_close')[1])
        assert [entry['team'] for entry in board['entries']] == ['builtin']
        for path in (
            '/api/challenges/benches/b-none',
            '/api/challenges/benches/b-none/table.csv',
            '/api/challenges/jobs/j-none',
        ):
            with pytest.raises(urllib.error.HTTPError) as refused:
                _get(address, path)
            assert refused.value.code == 404, path
        with pytest.raises(urllib.error.HTTPError) as refused:
            request = urllib.request.Request(
                f'{address}/api/challenges/benches/{job["id"]}', method='DELETE'
            )
            urllib.request.urlopen(request, timeout=10)
        assert refused.value.code == 404
        # A run of the page reads back on its own as well.
        run = _send(address, '/api/challenges/corner/runs', b'{"team": "builtin", "attempts": 1}')
        again = json.loads(_get(address, f'/api/challenges/jobs/{run["id"]}')[1])
        assert again['id'] == run['id'] and again['team'] == 'builtin'
    finally:
        server.shutdown()
        server.server_close()


def test_a_failed_attempt_reads_back_from_its_recording(render_home, monkeypatch):
    from cuju.render._playing import challenges as _challenges

    _short_challenges(monkeypatch, 4)

    def failing(obs):
        if obs['step'] == 1:
            raise RuntimeError('stop')
        return [0]

    outcome = _challenges.run('corner', policy=failing, attempts=1, fail_attempts=True)
    head = _recording.read_header(
        render_home / 'matches' / f'{outcome["attempts"][0]["match"]}.cjr'
    )
    assert head['provenance']['failed'] is True and outcome['practice']
    assert outcome['medals'] == _challenges.medal_items(_challenges.find('corner'))
