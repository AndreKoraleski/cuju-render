# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The build of the page, which the service worker of the installable page names its cache after.

The build is a short digest of cuju's version and of the name, size and modification time of
every file of the page's folder, so a new version, or any edit of a file of the page, makes a new
build. The page registers `sw.js?build=<build>`, so a new build brings a new worker, and the worker
compares its own build with the server's on each navigation. `GET /api/help/app` returns
`app_info`.
"""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from typing import Any

from cuju import __version__

_WEB = Path(__file__).parents[1] / 'web'
# A build stands this many seconds before the files are looked at again.
_FRESH_SECONDS = 1.0
_HELD: dict[str, Any] = {'at': -_FRESH_SECONDS, 'build': ''}
_LOCK = threading.Lock()


def _digest() -> str:
    digest = hashlib.sha256(f'cuju {__version__}\n'.encode())
    for path in sorted(_WEB.rglob('*')):
        if path.is_file():
            stat = path.stat()
            name = path.relative_to(_WEB).as_posix()
            digest.update(f'{name} {stat.st_size} {stat.st_mtime_ns}\n'.encode())
    return digest.hexdigest()[:16]


def build() -> str:
    """Returns the build of the page as it stands, looked at again at most once a second."""
    with _LOCK:
        now = time.monotonic()
        if now - _HELD['at'] >= _FRESH_SECONDS:
            _HELD['build'] = _digest()
            _HELD['at'] = now
        return _HELD['build']


def app_info() -> dict[str, str]:
    """Returns the version of cuju and the build of the page."""
    return {'version': __version__, 'build': build()}
