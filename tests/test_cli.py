# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the command `cuju render`."""

import pytest

from cuju.render._store import library as _library
from support.common import _SAMPLES, _library_ids, _serve_once


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
