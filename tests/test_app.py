# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of `cuju render app`, the page in a window of its own, and of its launchers."""

import json
import os
import plistlib
import struct
import sys
import types
from pathlib import Path

import pytest

from cuju.errors import Error
from cuju.render._http import launch as _launch
from cuju.render._http import launchers as _launchers
from cuju.render._http import window as _window
from support.common import _install_translation

URL = 'http://127.0.0.1:8780/'


def _server(home, process=None):
    return _launch.Server(8780, 1, 'key', home, process)


def test_a_server_names_the_call_that_started_it(render_home, monkeypatch):
    monkeypatch.setenv(_launch.STARTER_VARIABLE, 'abc')
    path = _launch.announce(8999, 'k')
    assert json.loads(path.read_text(encoding='utf-8'))['starter'] == 'abc'
    assert _launch._starter() == 'abc'
    monkeypatch.delenv(_launch.STARTER_VARIABLE)
    _launch.announce(8999, 'k')
    assert 'starter' not in json.loads(path.read_text(encoding='utf-8'))
    assert _launch._starter() is None


def test_the_route_is_the_first_that_the_computer_has():
    edge = _window.Browser('edge', 'msedge.exe')
    assert _window.choose('auto', True, edge) == 'webview'
    assert _window.choose('auto', False, edge) == 'chromium'
    assert _window.choose('auto', False, None) == 'browser'
    assert _window.choose('chromium', True, edge) == 'chromium'
    assert _window.choose('browser', True, edge) == 'browser'
    with pytest.raises(Error, match=r'cuju-render\[app\]'):
        _window.choose('webview', False, edge)
    with pytest.raises(Error, match='--browser'):
        _window.choose('chromium', True, None)


def test_windows_looks_for_edge_first_in_the_folders_of_programs():
    environ = {
        'ProgramFiles(x86)': r'C:\Program Files (x86)',
        'ProgramFiles': r'C:\Program Files',
        'LOCALAPPDATA': r'C:\Users\a\AppData\Local',
    }
    names = [name for name, _ in _window.chromium_candidates('win32', environ)]
    assert names[0] == 'edge'
    assert names.index('chrome') < names.index('chromium') < names.index('brave')
    chrome = str(Path(r'C:\Program Files', 'Google', 'Chrome', 'Application', 'chrome.exe'))
    found = _window.find_chromium('win32', environ, exists=lambda path: path == chrome)
    assert found == _window.Browser('chrome', chrome)
    assert _window.find_chromium('win32', environ, exists=lambda path: False) is None


def test_linux_and_macos_find_their_browsers():
    which = {'chromium': '/usr/bin/chromium', 'microsoft-edge': '/usr/bin/microsoft-edge'}.get
    assert _window.find_chromium('linux', {}, which=which) == _window.Browser(
        'chromium', '/usr/bin/chromium'
    )
    brave = '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser'
    found = _window.find_chromium('darwin', {'HOME': '/Users/a'}, exists=lambda path: path == brave)
    assert found == _window.Browser('brave', brave)


def test_app_mode_opens_the_page_with_a_profile_of_its_own(tmp_path):
    browser = _window.Browser('edge', 'msedge.exe')
    command = _window.chromium_command(browser, URL, tmp_path / 'edge', 'win32')
    assert command[0] == 'msedge.exe'
    assert f'--app={URL}' in command
    assert f'--user-data-dir={tmp_path / "edge"}' in command
    assert '--no-first-run' in command and '--class=cuju' not in command
    assert not any(part.startswith('--remote-debugging') for part in command)
    assert '--class=cuju' in _window.chromium_command(browser, URL, tmp_path, 'linux')


def test_a_free_profile_is_in_use_by_no_browser(tmp_path):
    assert not _window.profile_in_use(tmp_path, sys.platform)
    (tmp_path / 'lockfile').write_bytes(b'')
    assert not _window.profile_in_use(tmp_path, 'win32')


def _fake_webview(calls, fail=None):
    module = types.SimpleNamespace(settings={'ALLOW_DOWNLOADS': False})

    def create_window(title, url, **options):
        calls.append(('window', title, url, options))

    def start(**options):
        if fail:
            raise fail
        calls.append(('start', options))

    module.create_window = create_window
    module.start = start
    return module


def test_the_system_web_view_opens_the_page_of_a_running_server(render_home, monkeypatch):
    calls = []
    monkeypatch.setattr(_window, 'webview_module', lambda: _fake_webview(calls))
    monkeypatch.setattr(_window, 'find_chromium', lambda: None)
    monkeypatch.setattr(_launch, 'running', lambda: _server(render_home))
    monkeypatch.setattr(_launch, 'start', lambda port: pytest.fail('a running server is reused'))
    assert _window.run(None) == 0
    (_, title, url, options), (_, started) = calls
    assert (title, url) == ('cuju', URL)
    assert options['background_color'] == '#202124'
    assert started['private_mode'] is False
    assert Path(started['storage_path']) == render_home / 'app' / 'webview'
    assert Path(started['icon']).name == 'cuju-512.png' and Path(started['icon']).is_file()


def test_a_web_view_that_fails_leaves_app_mode(render_home, monkeypatch):
    opened = []
    monkeypatch.setattr(
        _window, 'webview_module', lambda: _fake_webview([], fail=RuntimeError('no GTK'))
    )
    monkeypatch.setattr(_window, 'find_chromium', lambda: _window.Browser('chrome', 'chrome'))
    monkeypatch.setattr(_launch, 'running', lambda: _server(render_home))
    monkeypatch.setattr(
        _window, 'open_chromium', lambda browser, url, folder, wait: opened.append((url, wait))
    )
    assert _window.run(None) == 0
    assert opened == [(URL, False)]
    with pytest.raises(Error, match='no GTK'):
        _window.run(None, 'webview')


class _Process:
    def __init__(self, command, **options):
        self.command = command
        self.options = options
        self.waited = False
        _Process.made.append(self)

    def wait(self):
        self.waited = True
        return 0


def test_app_mode_waits_for_the_window_of_a_server_it_started(render_home, monkeypatch):
    _Process.made = []
    monkeypatch.setattr(_window.subprocess, 'Popen', _Process)
    monkeypatch.setattr(_window, 'webview_module', lambda: None)
    monkeypatch.setattr(_window, 'find_chromium', lambda: _window.Browser('edge', 'msedge'))
    monkeypatch.setattr(_launch, 'running', lambda: None)
    monkeypatch.setattr(_launch, 'start', lambda port: _server(render_home))
    assert _window.run(None) == 0
    (process,) = _Process.made
    assert process.waited
    assert f'--user-data-dir={render_home / "app" / "edge"}' in process.command
    # A server that runs already stays, so the command returns at once.
    monkeypatch.setattr(_launch, 'running', lambda: _server(render_home))
    assert _window.run(None, 'chromium') == 0
    assert not _Process.made[-1].waited


def test_the_default_browser_comes_last_with_a_note(render_home, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(_window, 'webview_module', lambda: None)
    monkeypatch.setattr(_window, 'find_chromium', lambda: None)
    monkeypatch.setattr(_launch, 'running', lambda: _server(render_home))
    monkeypatch.setattr(_launch, 'open_browser', lambda url: opened.append(url) or True)
    assert _window.run(None) == 0
    assert opened == [URL]
    assert 'cuju-render[app]' in capsys.readouterr().err


def test_a_launcher_runs_the_app_with_this_python(tmp_path):
    command = _launchers.launcher_command(tmp_path / 'home', 'linux', 'chromium', '/bin/brave')
    assert command[0] == sys.executable
    assert command[command.index('-m') + 1] == 'cuju.render'
    assert command[command.index('--home') + 1] == str(tmp_path / 'home')
    assert command[-5:] == ['app', '--route', 'chromium', '--browser', '/bin/brave']
    default = _launchers.launcher_command(Path.home() / '.cuju' / 'render', 'linux')
    assert '--home' not in default and default[-1] == 'app'


def test_the_exec_line_of_linux_quotes_as_its_specification_asks():
    line = _launchers.desktop_exec(['/opt/my python/bin/python3', '-m', 'cuju.render', '100%'])
    assert line == '"/opt/my python/bin/python3" -m cuju.render 100%%'
    assert _launchers.desktop_exec(['a"b$c']) == r'"a\\"b\\$c"'


def _folders(tmp_path):
    return {
        'start': tmp_path / 'Start Menu' / 'Programs',
        'desktop': tmp_path / 'Desktop',
        'applications': tmp_path / 'applications',
    }


def test_linux_gets_an_entry_of_the_applications_menu(render_home, tmp_path):
    folders = _folders(tmp_path)
    command = ['/usr/bin/python3', '-m', 'cuju.render', 'app']
    # A language of the folder, such as the Portuguese draft, names the launcher in its words.
    _install_translation('pt')
    made = _launchers.install(render_home, 'linux', folders, command)
    entry = folders['applications'] / 'cuju.desktop'
    icon = render_home / 'app' / 'cuju.png'
    assert set(made) == {entry, icon}
    text = entry.read_text(encoding='utf-8')
    assert 'Exec=/usr/bin/python3 -m cuju.render app\n' in text
    assert f'Icon={icon}\n' in text and 'Terminal=false' in text
    assert 'Comment[pt_BR]=' in text
    assert icon.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
    assert _launchers.installed_paths(render_home) == made
    # A second install replaces its own launcher.
    assert _launchers.install(render_home, 'linux', folders, command) == made
    assert set(_launchers.uninstall(render_home)) == set(made)
    assert not entry.exists() and not icon.exists()
    assert not (render_home / 'app' / 'launchers.json').exists()
    assert _launchers.uninstall(render_home) == []


def test_a_launcher_that_no_install_made_stays(render_home, tmp_path):
    folders = _folders(tmp_path)
    foreign = folders['applications'] / 'cuju.desktop'
    foreign.parent.mkdir(parents=True)
    foreign.write_text('mine', encoding='utf-8')
    with pytest.raises(Error, match='in the way'):
        _launchers.install(render_home, 'linux', folders, ['python'])
    assert foreign.read_text(encoding='utf-8') == 'mine'
    # A record that names other files removes none of them.
    other = tmp_path / 'notes.txt'
    other.write_text('keep', encoding='utf-8')
    record = render_home / 'app' / 'launchers.json'
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({'created': [str(other), str(foreign)]}), encoding='utf-8')
    _launchers.uninstall(render_home)
    assert other.read_text(encoding='utf-8') == 'keep'


def test_macos_gets_an_app_in_applications(render_home, tmp_path):
    folders = _folders(tmp_path)
    command = ['/usr/local/bin/python3', '-m', 'cuju.render', 'app']
    (bundle,) = _launchers.install(render_home, 'darwin', folders, command)
    assert bundle == folders['applications'] / 'cuju.app'
    with (bundle / 'Contents' / 'Info.plist').open('rb') as stream:
        info = plistlib.load(stream)
    assert info['CFBundleIdentifier'] == _launchers.BUNDLE_ID
    assert info['CFBundleExecutable'] == 'cuju' and info['CFBundleIconFile'] == 'cuju'
    script = (bundle / 'Contents' / 'MacOS' / 'cuju').read_text(encoding='utf-8')
    assert script == '#!/bin/sh\nexec /usr/local/bin/python3 -m cuju.render app\n'
    icns = (bundle / 'Contents' / 'Resources' / 'cuju.icns').read_bytes()
    assert icns[:4] == b'icns' and struct.unpack('>I', icns[4:8])[0] == len(icns)
    assert icns[8:12] == b'ic09' and icns[16:24] == b'\x89PNG\r\n\x1a\n'
    assert _launchers.uninstall(render_home) == [bundle]
    assert not bundle.exists()


def test_windows_gets_shortcuts_of_the_start_menu_and_the_desktop(render_home, tmp_path):
    folders = _folders(tmp_path)
    written = []

    def shortcut(link, command, icon, folder):
        link.write_bytes(b'link')
        written.append((link, command, icon, folder))

    command = [r'C:\Python\pythonw.exe', '-m', 'cuju.render', 'app']
    made = _launchers.install(render_home, 'win32', folders, command, shortcut)
    start, desktop = folders['start'] / 'cuju.lnk', folders['desktop'] / 'cuju.lnk'
    icon = render_home / 'app' / 'cuju.ico'
    assert made == [icon, start, desktop]
    assert [entry[0] for entry in written] == [start, desktop]
    assert all(entry[1] == command and entry[2] == icon for entry in written)
    data = icon.read_bytes()
    assert struct.unpack('<HHH', data[:6]) == (0, 1, 2)
    width, height = struct.unpack('<BB', data[6:8])
    assert (width, height) == (192, 192)
    assert data[struct.unpack('<I', data[18:22])[0] :][:4] == b'\x89PNG'
    assert set(_launchers.uninstall(render_home)) == set(made)
    assert not any(path.exists() for path in made)


@pytest.mark.skipif(sys.platform != 'win32', reason='the shell of Windows writes the shortcut')
def test_windows_writes_a_real_shortcut(tmp_path):
    import subprocess

    link = tmp_path / 'folder with space' / 'cuju.lnk'
    link.parent.mkdir()
    icon = tmp_path / 'cuju.ico'
    icon.write_bytes(_launchers.ico([_window.icon(192).read_bytes()]))
    command = [sys.executable, '-m', 'cuju.render', '--home', str(tmp_path / 'a home'), 'app']
    _launchers.write_shortcut(link, command, icon, tmp_path)
    script = (
        '[Console]::OutputEncoding = [Text.Encoding]::UTF8; '
        '$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:CUJU_LINK); '
        'Write-Output $s.TargetPath; Write-Output $s.Arguments; Write-Output $s.IconLocation'
    )
    out = subprocess.run(
        ['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
        env={**os.environ, 'CUJU_LINK': str(link)},
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=True,
    ).stdout.splitlines()
    assert Path(out[0]) == Path(sys.executable)
    assert out[1] == subprocess.list2cmdline(command[1:])
    assert out[2].lower() == f'{icon},0'.lower()


def test_the_command_line_installs_and_removes_the_launchers(
    render_home, tmp_path, monkeypatch, capsys
):
    from cuju.render.__main__ import main

    folders = _folders(tmp_path)
    monkeypatch.setattr(_launchers, 'user_folders', lambda platform=None, environ=None: folders)
    monkeypatch.setattr(_launchers.sys, 'platform', 'linux')
    assert main(['app', '--install']) == 0
    entry = folders['applications'] / 'cuju.desktop'
    assert entry.exists()
    text = entry.read_text(encoding='utf-8')
    line = next(line for line in text.splitlines() if line.startswith('Exec='))
    assert '--home' in line and line.endswith(' app')
    assert main(['app', '--uninstall']) == 0
    assert not entry.exists()
    assert 'removed' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(['app', '--install', '--uninstall'])
    with pytest.raises(SystemExit):
        main(['app', '--route', 'nowhere'])
