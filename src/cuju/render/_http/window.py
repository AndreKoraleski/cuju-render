# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The page in a window of its own, `cuju render app`.

The command reuses the server of the home folder, or starts one that ends with the window, and
opens the page by the first route that the computer has. The system's web view comes first,
through pywebview, the optional extra `cuju-render[app]`, which uses WebView2 on Windows, WKWebView
on macOS and WebKitGTK or Qt on Linux. A Chromium browser comes next, Edge, Chrome, Chromium or
Brave, in app mode, a window with no tabs and no address bar, with a profile of its own in the
folder `app` of the home folder. The default browser comes last, with a note on the other routes.
Every route opens the page from the loopback address of the server, and nothing is downloaded.
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cuju.errors import Error

from .._store import home as _home
from . import launch as _launch

# The routes that `--route` names, auto taking the first that the computer has.
ROUTES = ('auto', 'webview', 'chromium', 'browser')
# The folder of the home folder that holds the profiles of the app window and its launchers.
APP_FOLDER = 'app'
# The size of a new window, in pixels.
WINDOW_SIZE = (1280, 800)
MIN_SIZE = (720, 520)
BACKGROUND = '#202124'
# How often a wait for the window looks at the profile of the browser, in seconds.
_POLL_SECONDS = 1.0
WEBVIEW_ADVICE = "pip install 'cuju-render[app]'"


@dataclass(frozen=True)
class Browser:
    """A Chromium browser that opens the page in app mode.

    Attributes:
        name: The short name, `edge`, `chrome`, `chromium` or `brave`, which names its profile.
        path: The program.
    """

    name: str
    path: str


def app_folder() -> Path:
    """Returns the folder `app` of the home folder, made when missing."""
    folder = _home.home() / APP_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def icon(size: int = 512) -> Path:
    """Returns the cuju icon of the page at `size`, 192 or 512 pixels."""
    return Path(__file__).resolve().parents[1] / 'web' / 'assets' / 'icons' / f'cuju-{size}.png'


def chromium_candidates(
    platform: str = sys.platform, environ: dict[str, str] | None = None
) -> list[tuple[str, str]]:
    """Returns the Chromium browsers to look for, by name and program, in the order of choice.

    Windows looks in the folders of programs and of the user, Edge first, since every Windows has
    it. macOS looks in `/Applications` and `~/Applications`. Linux and others name the programs
    that the path finds.
    """
    environ = os.environ if environ is None else environ
    if platform == 'win32':
        roots = [
            environ.get(key)
            for key in ('ProgramFiles(x86)', 'ProgramFiles', 'ProgramW6432', 'LOCALAPPDATA')
        ]
        roots = list(dict.fromkeys(root for root in roots if root))
        programs = [
            ('edge', ('Microsoft', 'Edge', 'Application', 'msedge.exe')),
            ('chrome', ('Google', 'Chrome', 'Application', 'chrome.exe')),
            ('chromium', ('Chromium', 'Application', 'chrome.exe')),
            ('brave', ('BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe')),
        ]
        return [(name, str(Path(root, *parts))) for name, parts in programs for root in roots]
    if platform == 'darwin':
        apps = [
            ('chrome', 'Google Chrome'),
            ('chromium', 'Chromium'),
            ('brave', 'Brave Browser'),
            ('edge', 'Microsoft Edge'),
        ]
        home = Path(environ.get('HOME', '~')).expanduser()
        folders = ['/Applications', str(home / 'Applications')]
        return [
            (name, f'{folder}/{app}.app/Contents/MacOS/{app}')
            for name, app in apps
            for folder in folders
        ]
    return [
        ('chrome', 'google-chrome'),
        ('chrome', 'google-chrome-stable'),
        ('chromium', 'chromium'),
        ('chromium', 'chromium-browser'),
        ('brave', 'brave-browser'),
        ('edge', 'microsoft-edge'),
        ('edge', 'microsoft-edge-stable'),
    ]


def find_chromium(
    platform: str = sys.platform,
    environ: dict[str, str] | None = None,
    exists: Any = os.path.isfile,
    which: Any = shutil.which,
) -> Browser | None:
    """Returns the first Chromium browser that the computer has, or `None`."""
    for name, program in chromium_candidates(platform, environ):
        if platform in ('win32', 'darwin'):
            if exists(program):
                return Browser(name, program)
        else:
            found = which(program)
            if found:
                return Browser(name, found)
    return None


def named_browser(path: str) -> Browser:
    """Returns the browser of the program that `--browser` names.

    Raises:
        Error: If no program is at `path` or on the path by that name.
    """
    found = path if os.path.isfile(path) else shutil.which(path)
    if not found:
        raise Error(f'no browser program at {path}')
    stem = Path(found).stem.lower()
    for name in ('edge', 'chrome', 'chromium', 'brave'):
        if name in stem:
            return Browser(name, found)
    return Browser('chromium', found)


def chromium_command(
    browser: Browser, url: str, profile: Path, platform: str = sys.platform
) -> list[str]:
    """Returns the command line that opens `url` in app mode with the profile folder `profile`.

    The profile of its own keeps the app window apart from the person's browser, its sign in, its
    extensions and its tabs, and lets the command tell when the window is closed.
    """
    command = [
        browser.path,
        f'--app={url}',
        f'--user-data-dir={profile}',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-background-mode',
        f'--window-size={WINDOW_SIZE[0]},{WINDOW_SIZE[1]}',
    ]
    if platform not in ('win32', 'darwin'):
        # The class names the window for the launcher of Linux, whose StartupWMClass is cuju.
        command.append('--class=cuju')
    return command


def profile_in_use(profile: Path, platform: str = sys.platform) -> bool:
    """Returns whether a browser holds the profile folder `profile`.

    A Chromium browser locks the file `lockfile` of its profile on Windows while it runs, and on
    other systems keeps the link `SingletonLock`, which names its host and process.
    """
    if platform == 'win32':
        lock = profile / 'lockfile'
        if not lock.exists():
            return False
        try:
            with lock.open('ab'):
                return False
        except PermissionError:
            return True
        except OSError:
            return False
    link = profile / 'SingletonLock'
    try:
        target = os.readlink(link)
    except OSError:
        return False
    pid = target.rpartition('-')[2]
    if not pid.isdigit():
        return os.path.lexists(link)
    from .server import _alive

    return _alive(int(pid))


def webview_module() -> Any | None:
    """Returns pywebview when it is installed, else `None`."""
    if importlib.util.find_spec('webview') is None:
        return None
    try:
        import webview
    except Exception as error:
        # A pywebview without its system parts fails as it loads, which leaves the other routes.
        print(f'cuju render: pywebview did not load, {error}', file=sys.stderr)
        return None
    return webview


def choose(route: str, webview: bool, chromium: Browser | None) -> str:
    """Returns the route to take, `webview`, `chromium` or `browser`, for the route asked for.

    Raises:
        Error: If the route asked for is missing on this computer.
    """
    if route == 'webview' and not webview:
        raise Error(f'the system web view needs pywebview, {WEBVIEW_ADVICE}')
    if route == 'chromium' and chromium is None:
        raise Error('no Chromium browser was found, name one with --browser')
    if route != 'auto':
        return route
    if webview:
        return 'webview'
    return 'chromium' if chromium is not None else 'browser'


def open_webview(webview: Any, url: str, folder: Path) -> None:
    """Opens `url` in a window of the system's web view and returns once the window closes.

    The window keeps the page's storage in the folder `webview` of `folder`, so settings and the
    offline copy last from one start to the next, and allows downloads, which video export and
    saved files need.
    """
    settings = getattr(webview, 'settings', None)
    if isinstance(settings, dict):
        settings['ALLOW_DOWNLOADS'] = True
        settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
    webview.create_window(
        'cuju',
        url,
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=MIN_SIZE,
        background_color=BACKGROUND,
    )
    storage = folder / 'webview'
    storage.mkdir(parents=True, exist_ok=True)
    webview.start(private_mode=False, storage_path=str(storage), icon=str(icon()))


def open_chromium(browser: Browser, url: str, folder: Path, wait: bool) -> subprocess.Popen:
    """Opens `url` in app mode and, with `wait`, returns once its window closes."""
    profile = folder / browser.name
    profile.mkdir(parents=True, exist_ok=True)
    options: dict[str, Any] = {}
    if sys.platform == 'win32':
        # Windows: 0x08000000 is CREATE_NO_WINDOW, which keeps a console from opening.
        options['creationflags'] = 0x08000000
    process = subprocess.Popen(
        chromium_command(browser, url, profile),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **options,
    )
    if wait:
        process.wait()
        # A browser that holds the profile already opens the window in its own process and the
        # new one ends at once, so the wait follows the profile until no browser holds it.
        with contextlib.suppress(KeyboardInterrupt):
            while profile_in_use(profile):
                time.sleep(_POLL_SECONDS)
    return process


def run(port: int | None, route: str = 'auto', browser: str | None = None) -> int:
    """Runs `cuju render app`, which opens the page in a window of its own.

    Args:
        port: The port of a server that it starts, by default 8780 when it is free.
        route: One of `ROUTES`.
        browser: The Chromium browser to open, a path to its program, for the route chromium.

    Raises:
        Error: If the route asked for is missing, or the server does not start.
    """
    if route not in ROUTES:
        raise Error(f'expected a route among {", ".join(ROUTES)}, found {route!r}')
    webview = webview_module() if route in ('auto', 'webview') else None
    chromium = named_browser(browser) if browser else None
    if chromium is None and route in ('auto', 'chromium'):
        chromium = find_chromium()
    choice = choose(route, webview is not None, chromium)
    server = _launch.running()
    if choice == 'browser':
        return _default_browser(server, port)
    started = server is None
    if server is None:
        server = _launch.start(port)
    folder = app_folder()
    if choice == 'webview':
        try:
            open_webview(webview, server.url, folder)
            return 0
        except Exception as error:
            # A web view without its system parts, such as GTK on a bare Linux, leaves the
            # other routes, unless the person asked for this one.
            if route == 'webview':
                raise Error(f'the system web view did not open, {error}') from None
            print(f'cuju render: the system web view did not open, {error}', file=sys.stderr)
            if chromium is None:
                return _default_browser(server, port, owned=started)
    assert chromium is not None
    open_chromium(chromium, server.url, folder, wait=started)
    if not started:
        print(f'cuju render serves {_home.home()} already, opened {server.url} in a window')
    return 0


def _default_browser(server: _launch.Server | None, port: int | None, owned: bool = False) -> int:
    """Opens the page in the default browser, with a note on the routes to a window of its own.

    A server that this command started, `owned`, ends with the command, so the command then waits
    for it until interrupted, as a bare `cuju render` does.
    """
    print(
        'cuju render: no system web view or Chromium browser was found, so the page opens in the '
        f'default browser. {WEBVIEW_ADVICE} gives the page a window of its own.',
        file=sys.stderr,
    )
    if server is not None:
        action = 'opened' if _launch.open_browser(server.url) else 'open it in a browser at'
        if not owned:
            print(f'cuju render serves {_home.home()} already, {action} {server.url}', flush=True)
            return 0
        print(f'cuju render serves {_home.home()} at {server.url}, {action} it', flush=True)
        if server.process is not None:
            with contextlib.suppress(KeyboardInterrupt):
                server.process.wait()
        return 0
    from . import server as _server

    _server.serve(_launch.DEFAULT_PORT if port is None else port, True)
    return 0
