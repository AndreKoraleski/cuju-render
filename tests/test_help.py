# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the Help page, the tutorial and the diagnostic report."""

import json
import logging

from cuju.render._http import launch as _launch
from cuju.render._store import home as _home


def test_doctor_report_keeps_private_paths_out(tmp_path, monkeypatch):
    from pathlib import Path

    from cuju.render._guide import doctor as _doctor

    user = tmp_path / 'person'
    for variable in ('HOME', 'USERPROFILE'):
        monkeypatch.setenv(variable, str(user))
    home = user / '.cuju' / 'render'
    monkeypatch.setenv(_home.HOME_VARIABLE, str(home))
    (home / 'matches').mkdir(parents=True)
    (home / 'matches' / 'a.bin').write_bytes(b'12345')
    (home / _launch.SERVER_FILE).write_text(
        json.dumps({'port': 1, 'pid': 0, 'key': 'secret-key'}), encoding='utf-8'
    )
    _doctor.install_capture()
    _doctor.install_capture()
    capture = [h for h in logging.getLogger('cuju').handlers if isinstance(h, _doctor._Capture)]
    assert len(capture) == 1
    try:
        logging.getLogger('cuju').warning('cuju render skips the file %s', user / 'x.json')
        _doctor.note_error(f'GET /api/matches, OSError: {user}/broken')
        report = _doctor.server_report()
    finally:
        logging.getLogger('cuju').removeHandler(capture[0])
    flat = json.dumps(report)
    assert str(user) not in flat and str(user).replace('\\', '/') not in flat
    assert 'secret-key' not in flat
    assert report['home']['path'] == str(Path('~') / '.cuju' / 'render')
    assert report['folders']['matches'] == {'files': 1, 'bytes': 5}
    assert report['server']['stale'] and not report['server']['running']
    messages = [entry['message'] for entry in report['errors']]
    assert messages[-2:] == [
        f'cuju render skips the file {Path("~") / "x.json"}',
        'GET /api/matches, OSError: ~/broken',
    ]
    checks = {check['name']: check for check in report['checks']}
    names = {'home folder', 'writing', 'disk space', 'samples', 'page files', 'server file'}
    assert names <= set(checks)
    assert checks['home folder']['ok'] and not checks['server file']['ok']
    assert set(report['versions']) >= {'cuju', 'python', 'system', 'torch', 'numpy'}
    text = _doctor.text(report)
    assert 'FAIL  server file' in text and str(user) not in text
    # A home folder that is a file fails its check and is named as such.
    (tmp_path / 'file').write_text('', encoding='utf-8')
    monkeypatch.setenv(_home.HOME_VARIABLE, str(tmp_path / 'file'))
    broken = _doctor.server_report()
    assert broken['home']['problems'] == ['the home folder is a file']
    assert not {check['name']: check for check in broken['checks']}['home folder']['ok']


def test_doctor_scrubs_the_home_of_the_renderer_and_the_name_of_the_user(tmp_path, monkeypatch):
    from cuju.render._guide import doctor as _doctor

    user = tmp_path / 'Ana Lima'
    for variable in ('HOME', 'USERPROFILE'):
        monkeypatch.setenv(variable, str(user))
    for variable in ('USER', 'USERNAME'):
        monkeypatch.setenv(variable, 'Ana Lima')
    monkeypatch.setattr(_doctor.getpass, 'getuser', lambda: 'Ana Lima')
    elsewhere = tmp_path / 'data' / 'render'
    monkeypatch.setenv(_home.HOME_VARIABLE, str(elsewhere))
    text = f'cannot read {elsewhere}/teams/t-1 of Ana Lima, see {user}/notes, Ana Limas'
    assert _doctor.scrub(text) == (
        'cannot read $CUJU_RENDER_HOME/teams/t-1 of <user>, see ~/notes, Ana Limas'
    )
    report = _doctor.server_report()
    assert report['home']['path'] == '$CUJU_RENDER_HOME'
    assert str(elsewhere) not in json.dumps(report) and 'Ana Lima' not in json.dumps(report)
    # Windows reads a path whatever its case, and so does the scrub there.
    shouted = f'{str(elsewhere).upper()}/x and {str(user).lower()}/y of ana lima'
    assert _doctor.scrub(shouted) == shouted
    monkeypatch.setattr(_doctor, '_CASELESS', True)
    assert _doctor.scrub(shouted) == '$CUJU_RENDER_HOME/x and ~/y of <user>'


def test_doctor_keeps_warnings_on_the_console(render_home, capfd, monkeypatch):
    from cuju.render._guide import doctor as _doctor

    # Python prints a warning only while no handler takes it, as outside pytest's own handlers.
    monkeypatch.setattr(logging.root, 'handlers', [])
    _doctor.install_capture()
    logger = logging.getLogger('cuju')
    capture = [h for h in logger.handlers if isinstance(h, _doctor._Capture)]
    try:
        logger.warning('cuju render warns once')
    finally:
        logger.removeHandler(capture[0])
    assert capfd.readouterr().err.count('cuju render warns once') == 1
