# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The commands of `cuju render` that serve the page or open it, `serve`, `open` and the bare one.

A server of the home folder that already runs is reused, so `cuju render open` and a bare
`cuju render` open its page and return, and otherwise they serve the page in the foreground until
interrupted, with the browser opened on what they name.
"""

from __future__ import annotations

import argparse
import urllib.parse

from .._store import home as _home
from . import launch as _launch
from . import server as _server

_LOOPBACK = ('127.0.0.1', 'localhost', '::1')


def _opened(url: str) -> int:
    """Opens `url` in the browser of a running server, says so, and returns the exit status."""
    action = 'opened' if _launch.open_browser(url) else 'open it in a browser at'
    print(f'cuju render serves {_home.home()} already, {action} {url}', flush=True)
    return 0


def serve_page(port: int, options: argparse.Namespace) -> int:
    """Runs `cuju render serve`, or a bare `cuju render`, which also opens the Home page."""
    if options.command is None:
        server = _launch.running()
        if server is not None:
            return _opened(server.url)
        _server.serve(port, True)
        return 0
    chosen = {'remote': options.remote, 'parent': options.parent, 'colab': options.colab}
    _server.serve(port, options.open, **{key: value for key, value in chosen.items() if value})
    return 0


def open_target(target: str, port: int) -> int:
    """Runs `cuju render open`, which opens a recording file, an identifier or a URL."""
    place = _launch.resolve(target)
    server = _launch.running()
    if '://' in place:
        address = urllib.parse.urlsplit(place)
        if server is not None or address.hostname not in _LOOPBACK:
            return _opened(place)
        fragment = f'#{address.fragment}' if address.fragment else ''
        _server.serve(address.port or 80, True, page=fragment)
        return 0
    if server is not None:
        return _opened(server.url + place)
    _server.serve(port, True, page=place)
    return 0
