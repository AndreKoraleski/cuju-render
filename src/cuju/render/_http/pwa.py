# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The build of the page, which the service worker of the installable page names its cache after.

The build is a short digest of cuju's version and of the name, size and modification time of
every file of the page's folder, so a new version, or any edit of a file of the page, makes a new
build. The page registers `sw.js?build=<build>`, so a new build brings a new worker, and the worker
compares its own build with the server's on each navigation. `GET /api/help/app` returns
`app_info`.

The server writes into `sw.js` the SHA-256 of every file of the page as it serves them, and the
worker answers from its cache only with an entry whose bytes have that digest, so an entry that
anything else put into the cache never reaches the page.

The manifest of the installable page, `manifest.webmanifest`, comes in the page's language when
the page asks for it with `?lang=<code>`, as it does for any language but English, so an install
names its description and shortcuts in that language.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

from cuju import __version__

from .. import _version

_WEB = Path(__file__).parents[1] / 'web'
# A build stands this many seconds before the files are looked at again.
_FRESH_SECONDS = 1.0
_HELD: dict[str, Any] = {'at': -_FRESH_SECONDS, 'build': '', 'digests': None, 'of': None}
_LOCK = threading.Lock()
# The line of `sw.js` that the server fills with the digests of the page's files.
_DIGESTS_SLOT = b'const DIGESTS = null;'


def _digest() -> str:
    digest = hashlib.sha256(f'cuju-render {_version.__version__} cuju {__version__}\n'.encode())
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


def digests() -> dict[str, str]:
    """Returns the SHA-256 of every file of the page as the server serves it, by its path.

    The page itself, and the page of a clean feed, carry the shipped languages as the server
    inlines them. The digests are made once a build.
    """
    from .._text import languages as _languages

    current = build()
    with _LOCK:
        if _HELD['of'] == current and _HELD['digests'] is not None:
            return _HELD['digests']
    out = {}
    for path in sorted(_WEB.rglob('*')):
        if not path.is_file():
            continue
        name = path.relative_to(_WEB).as_posix()
        data = path.read_bytes()
        if name in ('index.html', 'feed.html'):
            data = _languages.inline(data)
        out[name] = hashlib.sha256(data).hexdigest()
    with _LOCK:
        _HELD.update(digests=out, of=current)
    return out


def worker(data: bytes) -> bytes:
    """Returns the service worker `sw.js` with the digests of the page's files written into it."""
    filled = json.dumps(digests(), sort_keys=True, separators=(',', ':')).encode()
    return data.replace(_DIGESTS_SLOT, b'const DIGESTS = ' + filled + b';', 1)


# The messages of the manifest's texts, the description and the name of each shortcut by page.
_MANIFEST_DESCRIPTION = 'pwa.manifest.description'
_MANIFEST_SHORTCUT = 'pwa.manifest.shortcut.'


def manifest(data: bytes, code: str | None) -> bytes:
    """Returns the manifest `data` with its texts in the language `code`, as they are without one.

    A text that the language lacks, or a language that is unknown, keeps the English of the file.
    """
    if not code or code == 'en':
        return data
    from .._text import languages as _languages

    try:
        messages = _languages.read(code)
    except Exception:
        return data
    document = json.loads(data)
    text = messages.get(_MANIFEST_DESCRIPTION)
    if isinstance(text, str) and text.strip():
        document['description'] = text
    for shortcut in document.get('shortcuts') or ():
        page = str(shortcut.get('url', '')).rpartition('page=')[2]
        name = messages.get(_MANIFEST_SHORTCUT + page)
        if isinstance(name, str) and name.strip():
            shortcut['name'] = name
    document['lang'] = code
    return json.dumps(document, ensure_ascii=False, indent=4).encode('utf-8')


def app_info() -> dict[str, str]:
    """Returns the version of cuju-render and the build of the page."""
    return {'version': _version.__version__, 'build': build()}
