# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The launchers of the app window, `cuju render app --install` and `--uninstall`.

A launcher runs `cuju render app` with the Python of this install, so it opens the app window by
the same routes. Windows gets a shortcut in the Start menu and on the desktop, Linux an entry of
the applications menu in `~/.local/share/applications`, and macOS an app `cuju.app` in
`~/Applications`, each with the cuju icon of the page. The launchers go only into the person's own
folders, and only on the explicit command. The folder `app` of the home folder keeps the icon files
and `launchers.json`, the list of what the install made, so `--uninstall` removes exactly that and
leaves alone any file of the same name that the install did not make.
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import shlex
import shutil
import struct
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cuju.errors import Error

from .._store import home as _home
from . import window as _window

RECORD = 'launchers.json'
NAME = 'cuju'
# The bundle identifier of the app of macOS, which uninstall checks before it removes the bundle.
BUNDLE_ID = 'io.github.andrekoraleski.cuju-render'
# The names of what an install makes, the only names that uninstall removes.
MADE_NAMES = {f'{NAME}.lnk', f'{NAME}.ico', f'{NAME}.png', f'{NAME}.desktop', f'{NAME}.app'}
COMMENT = "Watch, play and run tournaments of cuju's football matches, served from this computer."


def launcher_command(
    home: Path,
    platform: str | None = None,
    route: str = 'auto',
    browser: str | None = None,
    python: str | None = None,
) -> list[str]:
    """Returns the command of a launcher, the Python of this install running `cuju render app`.

    Windows takes `pythonw.exe` beside the Python, which opens no console. A home folder other than
    the default one, a route and a browser go along as options.
    """
    platform = sys.platform if platform is None else platform
    program = Path(python or sys.executable)
    if platform == 'win32':
        windowed = program.with_name('pythonw.exe')
        if windowed.exists():
            program = windowed
    command = [str(program)]
    if sys.version_info >= (3, 11):
        command.append('-P')
    command += ['-m', 'cuju.render']
    default = Path.home() / '.cuju' / 'render'
    if home.resolve() != default.resolve():
        command += ['--home', str(home)]
    command.append('app')
    if route != 'auto':
        command += ['--route', route]
    if browser:
        command += ['--browser', browser]
    return command


def _known_folder(csidl: int) -> Path | None:
    """Returns a folder of the Windows shell by its CSIDL number, or `None`."""
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buffer) == 0:
            return Path(buffer.value)
    except (AttributeError, OSError):
        pass
    return None


def user_folders(
    platform: str | None = None, environ: dict[str, str] | None = None
) -> dict[str, Path]:
    """Returns the person's own folders that the launchers go into, by their role.

    Windows has `start`, the programs of the Start menu, and `desktop`. Linux and others have
    `applications`, the folder of the applications menu, and macOS has `applications`, the
    folder `~/Applications`.
    """
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ
    user = Path(environ.get('USERPROFILE') or environ.get('HOME') or Path.home())
    if platform == 'win32':
        # Windows: CSIDL_PROGRAMS is 0x02 and CSIDL_DESKTOPDIRECTORY 0x10.
        appdata = Path(environ.get('APPDATA') or user / 'AppData' / 'Roaming')
        start = _known_folder(0x02) or appdata / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs'
        return {'start': start, 'desktop': _known_folder(0x10) or user / 'Desktop'}
    if platform == 'darwin':
        return {'applications': user / 'Applications'}
    data = Path(environ.get('XDG_DATA_HOME') or user / '.local' / 'share')
    return {'applications': data / 'applications'}


def ico(images: list[bytes]) -> bytes:
    """Returns an icon file of Windows that holds the PNG images `images`."""
    header = struct.pack('<HHH', 0, 1, len(images))
    entries = b''
    offset = 6 + 16 * len(images)
    for data in images:
        width, height = struct.unpack('>II', data[16:24])
        size = (width if width < 256 else 0, height if height < 256 else 0)
        entries += struct.pack('<BBBBHHII', *size, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return header + entries + b''.join(images)


def icns(png512: bytes) -> bytes:
    """Returns an icon file of macOS that holds a PNG image of 512 pixels."""
    chunk = b'ic09' + struct.pack('>I', 8 + len(png512)) + png512
    return b'icns' + struct.pack('>I', 8 + len(chunk)) + chunk


def desktop_exec(command: list[str]) -> str:
    """Returns `command` as the Exec value of a desktop entry, quoted as its specification asks."""
    parts = []
    for argument in command:
        argument = argument.replace('%', '%%')
        if re.search(r'[\s"\'\\><~|&;$*?#()`]', argument):
            argument = '"' + re.sub(r'(["`$\\])', r'\\\1', argument) + '"'
        parts.append(argument)
    # The string rules of the file come after the quoting, so each backslash is doubled.
    return ' '.join(parts).replace('\\', '\\\\')


def desktop_entry(command: list[str], icon_path: Path, comments: dict[str, str]) -> str:
    """Returns the desktop entry of Linux that runs `command`."""
    lines = [
        '[Desktop Entry]',
        'Type=Application',
        'Version=1.0',
        f'Name={NAME}',
        f'Comment={COMMENT}',
        *(f'Comment[{code}]={text}' for code, text in sorted(comments.items())),
        f'Exec={desktop_exec(command)}',
        f'Icon={icon_path}',
        'Terminal=false',
        'Categories=Game;SportsGame;',
        'StartupWMClass=cuju',
    ]
    return '\n'.join(lines) + '\n'


def write_shortcut(link: Path, command: list[str], icon_path: Path, folder: Path) -> None:
    """Writes a shortcut of Windows through the shell of Windows itself, WScript.Shell.

    The values go to PowerShell as variables of its environment, so no quoting reaches its script,
    and PowerShell writes its errors in UTF-8, the encoding they are read in.
    """
    script = (
        '[Console]::OutputEncoding = [Text.Encoding]::UTF8; '
        '$s =(New-Object -ComObject WScript.Shell).CreateShortcut($env:CUJU_LINK); '
        '$s.TargetPath = $env:CUJU_TARGET; $s.Arguments = $env:CUJU_ARGUMENTS; '
        "$s.WorkingDirectory = $env:CUJU_FOLDER; $s.IconLocation = $env:CUJU_ICON + ',0'; "
        '$s.Description = $env:CUJU_COMMENT; $s.Save()'
    )
    root = os.environ.get('SystemRoot', r'C:\Windows')
    shell = Path(root, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    environment = {
        **os.environ,
        'CUJU_LINK': str(link),
        'CUJU_TARGET': command[0],
        'CUJU_ARGUMENTS': subprocess.list2cmdline(command[1:]),
        'CUJU_FOLDER': str(folder),
        'CUJU_ICON': str(icon_path),
        'CUJU_COMMENT': COMMENT,
    }
    program = str(shell) if shell.exists() else 'powershell'
    result = subprocess.run(
        [program, '-NoProfile', '-NonInteractive', '-Command', script],
        env=environment,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=60,
        creationflags=0x08000000 if sys.platform == 'win32' else 0,
    )
    if result.returncode != 0 or not link.exists():
        tail = (result.stderr or result.stdout).strip().splitlines()
        raise Error(f'the shortcut {link} was not made' + (f', {tail[-1]}' if tail else ''))


def _record_path(home: Path) -> Path:
    return home / _window.APP_FOLDER / RECORD


def installed_paths(home: Path) -> list[Path]:
    """Returns what an earlier install made, from `launchers.json` of the home folder."""
    try:
        entry = json.loads(_record_path(home).read_text(encoding='utf-8'))
        return [Path(path) for path in entry['created'] if isinstance(path, str)]
    except (OSError, ValueError, TypeError, KeyError):
        return []


def _bundle_is_ours(bundle: Path) -> bool:
    try:
        with (bundle / 'Contents' / 'Info.plist').open('rb') as stream:
            return plistlib.load(stream).get('CFBundleIdentifier') == BUNDLE_ID
    except (OSError, ValueError, plistlib.InvalidFileException):
        return False


def _comments() -> dict[str, str]:
    """Returns the comment of the launcher in each usable language other than English."""
    from .._text import languages as _languages

    out = {}
    try:
        entries = [e for e in _languages.listing() if e['code'] != 'en' and e['usable']]
    except Exception:
        entries = []
    for entry in entries:
        locale = str(entry['locale']).replace('-', '_')
        try:
            text = _languages.read(entry['code']).get('pwa.manifest.description')
        except Exception:
            text = None
        if isinstance(text, str) and text.strip():
            out[locale] = text.strip()
    return out


def install(
    home: Path | None = None,
    platform: str | None = None,
    folders: dict[str, Path] | None = None,
    command: list[str] | None = None,
    shortcut: Callable[[Path, list[str], Path, Path], None] = write_shortcut,
) -> list[Path]:
    """Makes the launchers of the app window and returns what it made.

    Args:
        home: The home folder, by default the one in use.
        platform: The system whose launchers it makes, `win32`, `darwin` or another.
        folders: The folders of the launchers by role, by default `user_folders`. Tests name
            folders of their own.
        command: The command of the launchers, by default `launcher_command`.
        shortcut: The writer of a shortcut of Windows.

    Raises:
        Error: If a launcher of the same name that no install of cuju made is in the way.
    """
    platform = sys.platform if platform is None else platform
    home = _home.home() if home is None else home
    folders = user_folders(platform) if folders is None else folders
    command = launcher_command(home, platform) if command is None else command
    folder = home / _window.APP_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    before = set(installed_paths(home))
    if platform == 'win32':
        targets = [folders['start'] / f'{NAME}.lnk', folders['desktop'] / f'{NAME}.lnk']
    elif platform == 'darwin':
        targets = [folders['applications'] / f'{NAME}.app']
    else:
        targets = [folders['applications'] / f'{NAME}.desktop']
    for target in targets:
        if os.path.lexists(target) and target not in before:
            raise Error(f'{target} is in the way and no install of cuju made it, remove it first')
    made: list[Path] = []
    if platform == 'win32':
        icon_path = folder / f'{NAME}.ico'
        icon_path.write_bytes(ico([_window.icon(192).read_bytes(), _window.icon(512).read_bytes()]))
        made.append(icon_path)
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            shortcut(target, command, icon_path, _home.process_folder())
            made.append(target)
    elif platform == 'darwin':
        made += _write_bundle(targets[0], command)
    else:
        icon_path = folder / f'{NAME}.png'
        shutil.copyfile(_window.icon(512), icon_path)
        made.append(icon_path)
        target = targets[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(desktop_entry(command, icon_path, _comments()), encoding='utf-8')
        target.chmod(0o755)
        made.append(target)
    _record_path(home).write_text(
        json.dumps({'created': [str(path) for path in made]}, indent=1), encoding='utf-8'
    )
    return made


def _write_bundle(bundle: Path, command: list[str]) -> list[Path]:
    """Writes the app `cuju.app` of macOS, whose program is a script that runs `command`."""
    from .._version import __version__

    if bundle.exists():
        shutil.rmtree(bundle)
    contents = bundle / 'Contents'
    (contents / 'MacOS').mkdir(parents=True)
    (contents / 'Resources').mkdir()
    info: dict[str, Any] = {
        'CFBundleName': NAME,
        'CFBundleDisplayName': NAME,
        'CFBundleIdentifier': BUNDLE_ID,
        'CFBundleExecutable': NAME,
        'CFBundleIconFile': NAME,
        'CFBundlePackageType': 'APPL',
        'CFBundleShortVersionString': __version__,
        'CFBundleVersion': __version__,
        'NSHighResolutionCapable': True,
    }
    with (contents / 'Info.plist').open('wb') as stream:
        plistlib.dump(info, stream)
    program = contents / 'MacOS' / NAME
    program.write_text(
        '#!/bin/sh\nexec ' + ' '.join(map(shlex.quote, command)) + '\n',
        encoding='utf-8',
        newline='\n',
    )
    program.chmod(0o755)
    (contents / 'Resources' / f'{NAME}.icns').write_bytes(icns(_window.icon(512).read_bytes()))
    return [bundle]


def uninstall(home: Path | None = None) -> list[Path]:
    """Removes what an earlier install made and returns what it removed.

    Only the names that an install makes go, a bundle of macOS only while its identifier is cuju's,
    and every other path only while it is a file.
    """
    home = _home.home() if home is None else home
    removed = []
    for path in installed_paths(home):
        if path.name not in MADE_NAMES:
            continue
        if path.is_dir() and not path.is_symlink():
            if path.suffix == '.app' and _bundle_is_ours(path):
                shutil.rmtree(path)
                removed.append(path)
        elif path.is_file():
            path.unlink()
            removed.append(path)
    record = _record_path(home)
    if record.exists():
        record.unlink()
    return removed


def run(install_it: bool, route: str = 'auto', browser: str | None = None) -> int:
    """Runs `cuju render app --install` or `--uninstall` and says what changed."""
    home = _home.home()
    if not install_it:
        removed = uninstall(home)
        if not removed:
            print('cuju render: no launcher of the app was found to remove')
        for path in removed:
            print(f'removed {path}')
        return 0
    if route not in _window.ROUTES:
        raise Error(f'expected a route among {", ".join(_window.ROUTES)}, found {route!r}')
    made = install(home, sys.platform, command=launcher_command(home, sys.platform, route, browser))
    for path in made:
        print(f'made {path}')
    print('cuju render app opens from the launcher, and cuju render app --uninstall removes it')
    return 0
