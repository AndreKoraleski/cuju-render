# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""The security headers of the server's responses, which say who may frame or open each one.

The module uses the standard library alone and imports nothing of the renderer, so the mock servers
of `ci` load it from its file and answer with the same headers as the server.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import Mapping
from pathlib import Path

# The pages that may frame the viewer once they hold the key of its server, the notebooks of
# Jupyter on this machine or behind a forwarded port, of VS Code and of Google Colab.
FRAME_ANCESTORS = ' '.join(
    [
        "'self'",
        'http://localhost:*',
        'http://127.0.0.1:*',
        'http://[::1]:*',
        'https://localhost:*',
        'https://127.0.0.1:*',
        'https://colab.research.google.com',
        'https://*.googleusercontent.com',
        'https://*.colab.dev',
        'https://*.vscode-cdn.net',
        'vscode-webview:',
        'vscode-file:',
    ]
)
# The policy of the sandbox page of team presentation workers, which runs its own bootstrap, blob
# scripts and WebAssembly alone, connects nowhere and may be framed by the pages it names. Its
# sandbox directive gives the page an opaque origin wherever it loads, in the renderer's frame or
# opened on its own as a whole window, so it never holds the storage, caches or service worker of
# the server's origin.
SANDBOX_POLICY = (
    'sandbox allow-scripts; '
    "default-src 'none'; script-src '{hash}' blob: 'wasm-unsafe-eval'; worker-src blob:; "
    "connect-src 'none'; img-src blob: data:; frame-ancestors {ancestors}; base-uri 'none'; "
    "form-action 'none'"
)
# The ways a response may be framed. Most responses may sit in no frame. The page asked for with
# the key of the server may sit in the frame of a notebook, the page of a clean feed and the page
# that draws a video export in a page of this server alone, and the sandbox says who may frame it
# in a policy of its own.
DENY = 'deny'
EMBED = 'embed'
SAME_ORIGIN = 'same-origin'
OWN = 'own'


def framing(relative: str, query: Mapping[str, str], key: str | None) -> str:
    """Returns how a file of the page may be framed, from its path inside `web` and its query.

    `key` is the key of the server that `show` hands to a notebook, or `None` when it has none.
    """
    if relative != 'index.html':
        return DENY
    given = query.get('embed', '').encode()
    if key and secrets.compare_digest(given, key.encode()):
        return EMBED
    # The clean feed and the video export of the browser each frame the page on its own origin.
    if 'feed' in query or ('capture' in query and 'export' in query):
        return SAME_ORIGIN
    return DENY


def security(kind: str = DENY) -> list[tuple[str, str]]:
    """Returns the headers that every response carries, for a response that may be framed so.

    Every response also keeps its window apart from a window of another site that opened it, so
    such a window can neither reach the page nor post to the sandbox opened on its own.
    """
    headers = []
    if kind == EMBED:
        headers.append(('Content-Security-Policy', f'frame-ancestors {FRAME_ANCESTORS}'))
    elif kind == SAME_ORIGIN:
        headers.append(('X-Frame-Options', 'SAMEORIGIN'))
        headers.append(('Content-Security-Policy', "frame-ancestors 'self'"))
    elif kind != OWN:
        headers.append(('X-Frame-Options', 'DENY'))
        headers.append(('Content-Security-Policy', "frame-ancestors 'none'"))
    headers.append(('X-Content-Type-Options', 'nosniff'))
    headers.append(('Cross-Origin-Opener-Policy', 'same-origin'))
    return headers


def sandbox_page(web: Path, ancestors: str = FRAME_ANCESTORS) -> tuple[bytes, str]:
    """Returns the page of the sandbox of team workers and its policy, which allows its script.

    The page inlines `js/presentation/sandbox.js` of the folder `web`, and the policy names the
    digest of that script, so nothing else runs in the sandbox but blob modules it starts itself.
    Every page above the sandbox must be among `ancestors`, so a viewer in the frame of a notebook
    passes the notebooks that may frame it.
    """
    script = (web / 'js' / 'presentation' / 'sandbox.js').read_text(encoding='utf-8')
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    page = f'<!doctype html><meta charset="utf-8"><title>sandbox</title><script>{script}</script>'
    return page.encode(), SANDBOX_POLICY.format(hash=f'sha256-{digest}', ancestors=ancestors)
