# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The routes of the Help page under `/api/help`, the samples, the tutorial, the diagnostic report
and the facts of the installable page.

- `GET /api/help/samples` lists the shipped samples with what the library holds of each, and
  `POST /api/help/samples` adds or restores those its `names` list, by default every one.
- `GET /api/help/tutorial` returns every lesson of the tutorial with its check, and
  `POST /api/help/tutorial` keeps the lessons a page reports in `done`, or clears them with
  `reset`.
- `GET /api/help/doctor` returns the server's side of the diagnostic report.
- `GET /api/help/app` returns the version and the build of the page, which the installed page
  compares with the files it keeps.

The server passes every request here through the same checks of host and origin as any other.
"""

from __future__ import annotations

from typing import Any

from .._text import messages as _messages


def get(parts: list[str], query: dict[str, str]) -> tuple[Any, int]:
    """Answers `GET /api/help/...` with a document and a status."""
    if parts == ['samples']:
        from .._store import samples as _samples

        return _samples.listing(), 200
    if parts[:1] == ['tutorial']:
        from . import tutorial as _tutorial

        return _tutorial.get(parts[1:], query)
    if parts == ['doctor']:
        from . import doctor as _doctor

        return _doctor.server_report(), 200
    if parts == ['app']:
        from .._http import pwa as _pwa

        return _pwa.app_info(), 200
    return _messages.fields('server.no_resource'), 404


def post(parts: list[str], document: dict[str, Any]) -> tuple[Any, int]:
    """Answers `POST /api/help/...` with a document and a status."""
    if parts == ['samples']:
        from .._store import samples as _samples

        names = document.get('names')
        if names is not None and (
            not isinstance(names, list) or not all(isinstance(name, str) for name in names)
        ):
            return _messages.fields('server.help.sample_names', names=repr(names)), 400
        return _samples.add(names), 200
    if parts[:1] == ['tutorial']:
        from . import tutorial as _tutorial

        return _tutorial.post(parts[1:], document)
    return _messages.fields('server.no_resource'), 404
