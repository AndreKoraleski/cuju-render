# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of `cuju render app`, the page in a window of its own, and of its launchers."""

import json
import os
import plistlib
import re
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
    assert (title, url) == ('Cuju', URL)
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
    assert 'Name=Cuju\n' in text
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
    assert bundle == folders['applications'] / 'Cuju.app'
    with (bundle / 'Contents' / 'Info.plist').open('rb') as stream:
        info = plistlib.load(stream)
    assert info['CFBundleIdentifier'] == _launchers.BUNDLE_ID
    assert info['CFBundleName'] == 'Cuju' and info['CFBundleDisplayName'] == 'Cuju'
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
    start, desktop = folders['start'] / 'Cuju.lnk', folders['desktop'] / 'Cuju.lnk'
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


def _old_install(render_home, made):
    """Writes the files and the record of an install made before the name Cuju."""
    for path in made:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'old')
    record = render_home / 'app' / 'launchers.json'
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({'created': [str(path) for path in made]}), encoding='utf-8')


def test_launchers_of_the_old_name_still_go(render_home, tmp_path):
    folders = _folders(tmp_path)
    old = [
        render_home / 'app' / 'cuju.ico',
        folders['start'] / 'cuju.lnk',
        folders['desktop'] / 'cuju.lnk',
    ]
    _old_install(render_home, old)
    assert set(_launchers.uninstall(render_home)) == set(old)
    assert not any(path.exists() for path in old)
    # An old app of macOS goes too, while its identifier is cuju's.
    bundle = folders['applications'] / 'cuju.app'
    (bundle / 'Contents').mkdir(parents=True)
    with (bundle / 'Contents' / 'Info.plist').open('wb') as stream:
        plistlib.dump({'CFBundleIdentifier': _launchers.BUNDLE_ID}, stream)
    _old_install(render_home, [])
    (render_home / 'app' / 'launchers.json').write_text(
        json.dumps({'created': [str(bundle)]}), encoding='utf-8'
    )
    assert _launchers.uninstall(render_home) == [bundle]
    assert not bundle.exists()


def test_an_install_replaces_the_launchers_of_the_old_name(render_home, tmp_path):
    folders = _folders(tmp_path)
    old = [
        render_home / 'app' / 'cuju.ico',
        folders['start'] / 'cuju.lnk',
        folders['desktop'] / 'cuju.lnk',
    ]
    _old_install(render_home, old)
    written = []

    def shortcut(link, command, icon, folder):
        link.write_bytes(b'link')
        written.append(link.name)

    made = _launchers.install(render_home, 'win32', folders, ['pythonw.exe'], shortcut)
    assert written == ['Cuju.lnk', 'Cuju.lnk']
    assert [path.name for path in made] == ['cuju.ico', 'Cuju.lnk', 'Cuju.lnk']
    # The shortcuts of the old name are gone, whether or not the system tells the case of names.
    for role in ('start', 'desktop'):
        assert [entry.name for entry in folders[role].iterdir()] == ['Cuju.lnk']
    assert set(_launchers.uninstall(render_home)) == set(made)


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


WEB = Path(_window.__file__).resolve().parents[1] / 'web'
LOGO = WEB / 'assets' / 'cuju-logo.svg'
# The bare marks, the letters alone on a clear background, for dark and for light surfaces.
MARK = WEB / 'assets' / 'cuju-mark.svg'
MARK_LIGHT = WEB / 'assets' / 'cuju-mark-light.svg'
# The gradients of the letters, from the back copy to the front one.
LAYERS = ('back', 'middle', 'front')
# Each PNG of the mark, its side and whether it is the maskable icon, as ci/make_logo.py makes them.
PICTURES = {
    'assets/cuju-logo.png': (128, False),
    'assets/cuju-logo-384.png': (384, False),
    'assets/icons/cuju-192.png': (192, False),
    'assets/icons/cuju-512.png': (512, False),
    'assets/icons/cuju-maskable-512.png': (512, True),
}
# The elements and attributes of plain shapes and their gray gradients, all the SVG may hold.
SHAPES = {'svg', 'defs', 'g', 'rect', 'path', 'linearGradient', 'radialGradient', 'stop'}
ATTRIBUTES = {
    'x1',
    'y1',
    'x2',
    'y2',
    'width',
    'height',
    'viewBox',
    'x',
    'y',
    'rx',
    'd',
    'fill',
    'transform',
    'id',
    'gradientUnits',
    'cx',
    'cy',
    'r',
    'offset',
    'stop-color',
}
SVG_NS = '{http://www.w3.org/2000/svg}'


def _make_logo():
    import importlib.util

    script = Path(__file__).resolve().parents[1] / 'ci' / 'make_logo.py'
    spec = importlib.util.spec_from_file_location('make_logo', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plain_shapes(path):
    """Returns the root of the SVG at `path` once every element is a plain shape or gradient."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(path.read_text(encoding='utf-8'))
    ids = {element.get('id') for element in root.iter()}
    for element in root.iter():
        namespace, _, tag = element.tag.rpartition('}')
        assert namespace == SVG_NS[:-1] and tag in SHAPES, (path.name, element.tag)
        assert set(element.attrib) <= ATTRIBUTES, (path.name, tag, element.attrib)
        assert not (element.text or '').strip() and not (element.tail or '').strip()
        # A fill names a color or a gradient of the file itself, never a file elsewhere.
        fill = element.get('fill', '#000000')
        found = re.fullmatch(r'url\(#([\w-]+)\)', fill)
        assert re.fullmatch(r'#[0-9a-f]{6}', fill) or (found and found.group(1) in ids), fill
    return root


def _stops(path):
    """Returns the colors of each radial gradient of the SVG at `path`, by its id."""
    return {
        gradient.get('id'): [stop.get('stop-color') for stop in gradient]
        for gradient in _plain_shapes(path).iter(f'{SVG_NS}radialGradient')
    }


def test_the_logo_is_plain_shapes_alone():
    assert '<!-- The cuju mark.' in LOGO.read_text(encoding='utf-8')
    root = _plain_shapes(LOGO)
    assert root.get('viewBox') == '0 0 512 512'
    assert root.find(f'{SVG_NS}g[@id="frame"]') is not None
    assert root.find(f'{SVG_NS}g[@id="mark"]') is not None


@pytest.mark.parametrize('path', [MARK, MARK_LIGHT], ids=lambda path: path.name)
def test_each_bare_mark_is_the_letters_alone_in_their_own_square(path):
    make_logo = _make_logo()
    root = _plain_shapes(path)
    side = make_logo.LETTERS + 2 * make_logo.MARGIN
    assert root.get('viewBox') == f'0 0 {side} {side}'
    assert root.get('width') == root.get('height') == str(side)
    # The letters alone, without the frame or the gradient of its border.
    assert root.find(f'{SVG_NS}g[@id="frame"]') is None
    assert not root.findall(f'.//{SVG_NS}rect')
    assert not root.findall(f'.//{SVG_NS}linearGradient')
    mark = root.find(f'{SVG_NS}g[@id="mark"]')
    margin = make_logo.MARGIN
    assert mark.get('transform') == f'translate({margin} {margin})'
    # The same three stacked copies and their paths as the logo's letters.
    logo = _plain_shapes(LOGO).find(f'{SVG_NS}g[@id="mark"]')
    shapes = [(item.get('fill'), ' '.join(item.get('d').split())) for item in logo]
    assert [(item.get('fill'), ' '.join(item.get('d').split())) for item in mark] == shapes
    assert [fill for fill, _ in shapes] == [f'url(#{name})' for name in LAYERS]


def test_the_bare_marks_are_written_from_the_logo():
    # ci/make_logo.py writes both bare marks from the shapes of the logo, so they never drift.
    make_logo = _make_logo()
    written = dict(make_logo.marks())
    assert set(written) == {MARK.name, MARK_LIGHT.name}
    for path in (MARK, MARK_LIGHT):
        assert path.read_text(encoding='utf-8') == written[path.name], path.name
    assert make_logo.LAYERS == LAYERS


def test_the_bare_marks_keep_the_logos_grays_or_take_dark_ones():
    logo, dark, light = _stops(LOGO), _stops(MARK), _stops(MARK_LIGHT)
    assert set(dark) == set(light) == set(LAYERS)
    assert all(dark[name] == logo[name] for name in LAYERS)
    assert light == {name: list(colors) for name, colors in _make_logo().LIGHT.items()}


def _palette(theme):
    """Returns the surfaces of the page's palette in a theme, from the tokens of style.css."""
    text = (WEB / 'style.css').read_text(encoding='utf-8')
    opening = ':root {' if theme == 'dark' else ':root[data-theme="light"] {'
    block = text.split(opening, 1)[1].split('}', 1)[0]
    tokens = dict(re.findall(r'--([\w-]+):\s*(#[0-9a-f]{6});', block))
    return [tokens[name] for name in ('bg', 'surface', 'surface-2')]


def _luminance(color):
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(one, other):
    high, low = sorted((_luminance(one), _luminance(other)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize(('path', 'theme'), [(MARK, 'dark'), (MARK_LIGHT, 'light')])
def test_each_bare_mark_reads_on_the_surfaces_of_its_theme(path, theme):
    stops = _stops(path)
    # The front letters hold a contrast of at least six and a half to one with every surface of
    # the theme, and each copy behind them stands closer to the page than the copy in front of it.
    for surface in _palette(theme):
        assert min(_contrast(color, surface) for color in stops['front']) >= 6.5, surface
        order = [min(_contrast(color, surface) for color in stops[name]) for name in LAYERS]
        assert order == sorted(order), (surface, order)
    # Each gray brightens outward from near the middle of the grid, as in the logo.
    for name in LAYERS:
        inner, outer = stops[name]
        assert _luminance(inner) < _luminance(outer), (name, stops[name])


def test_the_page_shows_the_bare_mark_by_theme_and_the_tile_as_an_icon():
    page = (WEB / 'index.html').read_text(encoding='utf-8')
    # The icons of the tab, the manifest and the home screen keep the tile.
    assert '<link rel="icon" type="image/svg+xml" sizes="any" href="assets/cuju-logo.svg">' in page
    assert '<link rel="apple-touch-icon" href="assets/icons/cuju-maskable-512.png">' in page
    # The bar holds the bare mark in both grays, and style.css hides the one the theme leaves out.
    assert '<img class="logo mark-for-dark" src="assets/cuju-mark.svg"' in page
    assert '<img class="logo mark-for-light" src="assets/cuju-mark-light.svg"' in page
    assert '<img class="stinger-logo" src="assets/cuju-mark.svg"' in page
    style = (WEB / 'style.css').read_text(encoding='utf-8')
    for rule in (
        ':root[data-theme="dark"] .mark-for-light,\n:root[data-theme="light"] .mark-for-dark {',
        '@media (prefers-color-scheme: light) {\n'
        '    :root:not([data-theme="dark"]) .mark-for-dark {',
        '@media not all and (prefers-color-scheme: light) {\n'
        '    :root:not([data-theme="light"]) .mark-for-light {',
    ):
        assert rule in style, rule
    home = (WEB / 'js' / 'pages' / 'home.js').read_text(encoding='utf-8')
    assert "['cuju-mark.svg', 'mark-for-dark'], ['cuju-mark-light.svg', 'mark-for-light']" in home
    assert 'cuju-logo' not in home
    # Over the match the bare mark in light grays stands on dark bands and panels.
    for name in ('broadcast/transition.js', 'export/feed.js', 'world/stadium.js'):
        source = (WEB / 'js' / name).read_text(encoding='utf-8')
        assert "'assets/cuju-mark.svg'" in source and 'cuju-logo' not in source, name


def test_the_manifest_names_cuju_with_the_svg_and_every_png():
    manifest = json.loads((WEB / 'manifest.webmanifest').read_text(encoding='utf-8'))
    assert manifest['name'] == manifest['short_name'] == _window.DISPLAY_NAME == 'Cuju'
    icons = {icon['src']: icon for icon in manifest['icons']}
    assert icons['assets/cuju-logo.svg'] == {
        'src': 'assets/cuju-logo.svg',
        'sizes': 'any',
        'type': 'image/svg+xml',
        'purpose': 'any',
    }
    for src, (side, mask) in PICTURES.items():
        if src.startswith('assets/icons/'):
            assert icons[src]['sizes'] == f'{side}x{side}' and icons[src]['type'] == 'image/png'
            assert icons[src]['purpose'] == ('maskable' if mask else 'any')
    assert len(icons) == 4
    page = (WEB / 'index.html').read_text(encoding='utf-8')
    assert '<link rel="icon" type="image/svg+xml" sizes="any" href="assets/cuju-logo.svg">' in page
    assert '<link rel="icon" type="image/png" sizes="128x128" href="assets/cuju-logo.png">' in page
    assert '<title>Cuju</title>' in page


def test_each_png_of_the_logo_has_its_size_and_shape():
    make_logo = _make_logo()
    assert {name: (side, mask) for name, side, mask in make_logo.PICTURES} == {
        src.removeprefix('assets/'): value for src, value in PICTURES.items()
    }
    for src, (side, mask) in PICTURES.items():
        data = (WEB / src).read_bytes()
        assert data[:8] == b'\x89PNG\r\n\x1a\n'
        assert struct.unpack('>II', data[16:24]) == (side, side), src
        _, _, rows = make_logo.rgba(data)
        corner = rows[0][:4]
        middle = rows[side // 2][side * 2 : side * 2 + 4]
        edge = rows[side // 2][:4]
        if mask:
            # The maskable icon fills its square with the dark background.
            assert corner == edge == bytes((0x20, 0x21, 0x24, 255)), src
        else:
            # The others are clear outside their rounded corners, with a gray border that holds
            # three quarters white over its top left half and darkens toward a quarter white at the
            # bottom right, so its left side is the light gray and its right side darker.
            right = rows[side // 2][(side - 1) * 4 : side * 4]
            assert corner[3] == 0 and edge == bytes((0xBF, 0xBF, 0xBF, 255)), src
            assert (
                right[3] == 255 and right[0] == right[1] == right[2] and 0x40 < right[0] < 0xBF
            ), src
        assert middle[3] == 255, src
