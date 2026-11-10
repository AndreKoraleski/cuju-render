# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the command `cuju render`."""

import json

import pytest

import cuju
import cuju.errors
import cuju.state
from cuju.render._store import library as _library
from support.common import (
    _SAMPLES,
    _SINGLE,
    _help_json,
    _help_server,
    _library_ids,
    _serve_once,
    _short_challenges,
    _toy_team,
)


def test_command_line_reports_errors(render_home, capsys):
    from cuju.render.__main__ import main

    assert main(['team', 'export', 'no-such-team']) == 1
    assert 'expected a team of the registry' in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(['team', 'remove'])


@pytest.mark.parametrize(
    'arguments',
    [
        ['serve', '--port', 'bad'],
        ['serve', '--port', '-1'],
        ['serve', '--port', '65536'],
        ['team', 'export'],
        ['team', 'remove'],
        ['team', 'unknown'],
        ['team', 'add', '--format', 'bad'],
        ['team', 'add'],
        ['play', '--seed', 'bad'],
        ['play', '--left-ability', 'bad'],
        ['play', '--right-ability', 'bad'],
    ],
)
def test_cli_argument_refusals(arguments):
    """Invalid command arguments produce an error exit."""
    from cuju.render.__main__ import main

    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2


def test_deleted_sample_stays_deleted_until_requested(render_home, monkeypatch, capsys):
    from cuju.render.__main__ import main

    _serve_once(monkeypatch)
    assert _library.remove('sample-5v5')
    _serve_once(monkeypatch)
    assert _library_ids() == ['sample-11v11']
    capsys.readouterr()
    assert main(['sample', '5v5']) == 0
    assert 'added sample-5v5' in capsys.readouterr().out
    assert _library_ids() == _SAMPLES
    for name in _SAMPLES:
        assert _library.remove(name)
    assert main(['sample']) == 0
    assert _library_ids() == _SAMPLES
    capsys.readouterr()
    assert main(['sample']) == 0
    assert 'already holds' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(['sample', '7v7'])


def test_challenge_command_line(render_home, tmp_path, monkeypatch, capsys):
    from cuju.render import __main__ as command

    assert command.main(['challenge', 'list']) == 0
    listed = capsys.readouterr().out
    assert 'empty_goal_close  Empty goal from close range, 5 attempts' in listed
    assert 'one_on_one_hard' in listed
    team = _toy_team(tmp_path, 'toy', _SINGLE, '11v11')
    _short_challenges(monkeypatch, 5)
    assert command.main(['challenge', 'corner', '--team', team['id'], '--attempts', '1']) == 0
    out = capsys.readouterr().out
    assert 'attempt 1, seed' in out and 'recording m-' in out and 'practice' in out
    assert command.main(['challenge', 'one_on_one', '--team', team['id']]) == 0
    out = capsys.readouterr().out
    assert out.count('attempt ') == 3 and 'rank 1' in out and 'personal best' in out
    assert command.main(['challenge', 'nothing', '--team', 'builtin']) == 1
    assert 'expected a challenge' in capsys.readouterr().err
    with pytest.raises(SystemExit):
        command.main(['challenge', 'corner'])


def test_samples_through_the_server_and_the_command_line(render_home, capsys):
    from cuju.render.__main__ import main

    server, address = _help_server()
    try:
        status, listed = _help_json(address, '/api/help/samples')
        assert status == 200 and len(listed) == 3
        status, result = _help_json(address, '/api/help/samples', {'names': ['sample-5v5']})
        assert status == 200 and result['changes'][0]['id'] == 'sample-5v5'
        assert _help_json(address, '/api/help/samples', {'names': 'sample-5v5'})[0] == 400
        assert _help_json(address, '/api/help/samples', {'names': ['nowhere']})[0] == 400
        assert _help_json(address, '/api/help/nowhere')[0] == 404
        foreign = {'Origin': 'http://foreign.invalid', 'Content-Type': 'application/json'}
        assert _help_json(address, '/api/help/samples', {}, foreign)[0] == 403
    finally:
        server.shutdown()
        server.server_close()
    assert main(['sample', 'starter-team']) == 0
    assert capsys.readouterr().out.startswith('added starter-team as t-')
    assert main(['sample', '5v5']) == 0
    assert capsys.readouterr().out == 'the library already holds the samples\n'
    assert main(['sample', 'list']) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[:3] for line in lines] == [
        ['sample-11v11', 'recording', 'missing'],
        ['sample-5v5', 'recording', 'library'],
        ['starter-team', 'team', 'library'],
    ]


def test_tutorial_through_the_server_and_the_command_line(render_home, capsys, monkeypatch):
    import shlex

    from cuju.render import __main__ as command

    server, address = _help_server()
    try:
        status, state = _help_json(address, '/api/help/tutorial', {'done': ['make_photo']})
        assert status == 200 and state['page'] == ['make_photo']
        assert _help_json(address, '/api/help/tutorial/make_photo')[1]['done']
        assert _help_json(address, '/api/help/tutorial/nowhere')[0] == 404
        assert _help_json(address, '/api/help/tutorial', {'done': ['nowhere']})[0] == 400
        assert _help_json(address, '/api/help/tutorial', {'reset': True})[1]['page'] == []
    finally:
        server.shutdown()
        server.server_close()
    assert command.main(['tutorial', '--json']) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed['next'] == 'open_sample' and len(printed['lessons']) == 8
    assert command.main(['tutorial', 'open_sample', '--check']) == 2
    assert 'to do, lesson open_sample' in capsys.readouterr().out
    assert command.main(['sample', '5v5']) == 0
    assert command.main(['tutorial', 'open_sample', '--check']) == 0
    text = capsys.readouterr().out
    assert 'done, lesson open_sample' in text and 'run  cuju render sample sample-5v5' in text
    assert command.main(['tutorial']) == 0
    assert 'Next, Jump to a goal, cuju render tutorial seek_goal' in capsys.readouterr().out
    # Every command that a lesson names parses as the command line reads it.
    monkeypatch.setattr(command, '_run', lambda parser, options: 0)
    for lesson in printed['lessons']:
        for step in lesson['steps']:
            if 'run' in step:
                words = shlex.split(step['run'])
                assert words[:2] == ['cuju', 'render'], step
                assert command.main(words[2:]) == 0, step


def test_feed_command_prints_addresses(render_home, capsys):
    from cuju.render.__main__ import main

    arguments = ['feed', 'live:Evaluation', '--size', 'vertical', '--background', 'transparent']
    assert main(arguments) == 0
    out, err = capsys.readouterr()
    assert out.strip() == (
        'http://127.0.0.1:8780/feed?source=live:Evaluation&size=vertical&bg=transparent'
    )
    assert 'no server' in err
    arguments = ['feed', '--json', '--width', '1000', '--height', '1000', '--audio', '--fps', '30']
    assert main(arguments) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed['running'] is False
    assert [row['source'] for row in listed['feeds']][:2] == ['auto', 'latest']
    assert listed['feeds'][0]['url'].endswith('source=auto&size=1000x1000&audio=1&fps=30')
    assert main(['feed', 'live', '--size', 'huge']) == 1
    assert 'expected a size' in capsys.readouterr().err
    assert cuju.render.feed_url('queue', port=8790, size='4k', loop=True) == (
        'http://127.0.0.1:8790/feed?source=queue&size=4k&loop=1'
    )
