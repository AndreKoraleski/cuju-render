# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The hidden folder of the renderer, which holds saved matches, teams and live sources."""

from __future__ import annotations

import os
import re
import secrets
import sys
import time
from pathlib import Path

# The variable that moves the folder, read on every call so that a test can set it.
HOME_VARIABLE = 'CUJU_RENDER_HOME'

_IDENTIFIER = re.compile(r'[a-z0-9][a-z0-9_-]{0,63}')


def home() -> Path:
    """Returns the folder of the renderer, `~/.cuju/render` or the one `CUJU_RENDER_HOME` names."""
    folder = os.environ.get(HOME_VARIABLE)
    return Path(folder).expanduser().resolve() if folder else Path.home() / '.cuju' / 'render'


def folder(kind: str) -> Path:
    """Returns the subfolder `matches`, `teams`, `live` or `requests`, created when missing."""
    path = home() / kind
    path.mkdir(parents=True, exist_ok=True)
    return path


def python_command() -> list[str]:
    """Returns the start of the command of a Python process that the renderer starts.

    Python 3.11 brought `-P`, which keeps the working folder off the path of modules, so no folder
    of the home, such as `teams` or `requests`, imports as a package in the process.
    """
    return [sys.executable, '-P'] if sys.version_info >= (3, 11) else [sys.executable]


def process_environment() -> dict[str, str]:
    """Returns the environment of a Python process that the renderer starts.

    The process reads and writes its pipes in UTF-8, the encoding the renderer reads and writes
    them in, whatever the code page of the system.
    """
    return {**os.environ, 'PYTHONIOENCODING': 'utf-8'}


def process_folder() -> Path:
    """Returns the working folder of a Python process that the renderer starts, made when missing.

    That is the home folder, which `-P` keeps off the path of modules. Python 3.10 has no `-P`,
    so there the process starts in the folder `run` of the home, which the renderer keeps empty.
    """
    folder = home() if sys.version_info >= (3, 11) else home() / 'run'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def new_identifier(prefix: str) -> str:
    """Returns an identifier that sorts by creation time, such as `m-20261106-101500-3fa9`."""
    return f'{prefix}-{time.strftime("%Y%m%d-%H%M%S")}-{secrets.token_hex(2)}'


def valid_identifier(identifier: str) -> bool:
    """Returns whether `identifier` is safe as a file name, so no request can leave the folder."""
    return bool(_IDENTIFIER.fullmatch(identifier))
