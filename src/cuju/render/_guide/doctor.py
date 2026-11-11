# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The diagnostic report of the renderer, which the Help page and `cuju render doctor` make.

The report gathers the versions of cuju, Python, PyTorch and NumPy, the system, the checks of the
renderer's home folder, the files and bytes of each of its folders, the counts of the library and
the registry, the server of the folder and the recent warnings and errors of the server. The page
adds what the browser can do. A report names no path beyond the home folder, and writes the
user's home directory in it and in every message as `~`, the renderer's home folder outside it as
`$CUJU_RENDER_HOME` and the user's name as `<user>`. It holds no key and no variable of the
environment, and only the messages of errors may name a recording or a team.

The server keeps its recent warnings and errors in memory, the records of the logger `cuju` from
`install_capture` on and every request that failed inside the server, which `note_error` adds.
`GET /api/help/doctor` returns `server_report`, and the command asks a running server for it.
"""

from __future__ import annotations

import argparse
import collections
import getpass
import http.client
import importlib.metadata
import json
import logging
import os
import platform
import re
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

from cuju import __version__

from .._http import launch as _launch
from .._store import home as _home

# The recent warnings and errors that the server keeps.
_KEPT = 50
_RECENT: collections.deque[dict[str, Any]] = collections.deque(maxlen=_KEPT)
_RECENT_LOCK = threading.Lock()
# A home folder with less free space than this fails the check of the disk.
LOW_DISK_BYTES = 500 * 1024 * 1024
# The lines of server.log that the command reads, from its end.
_LOG_LINES = 400
_LOG_WORDS = ('error', 'traceback', 'exception', 'failed')


# Windows reads a path or a name whatever its case, so the scrub matches them so there.
_CASELESS = os.name == 'nt'


def _spellings(path: str) -> set[str]:
    """Returns a path as written, resolved and in either kind of slash, or none for a root."""
    if not path or path in ('~', '.') or Path(path).parent == Path(path):
        return set()
    found = set()
    for written in (path, str(Path(path).resolve())):
        found |= {written, written.replace('\\', '/'), written.replace('/', '\\')}
    return found


def _user_names() -> set[str]:
    """Returns the names of the user that a message may hold, each of two characters or more."""
    names = {os.environ.get('USERNAME', ''), os.environ.get('USER', ''), Path.home().name}
    try:
        names.add(getpass.getuser())
    except Exception:
        # Some systems name no user for the process, and the other names stand.
        pass
    return {name for name in names if len(name.strip()) >= 2}


def scrub(text: Any) -> str:
    """Returns `text` with the private paths and names of the user written as placeholders.

    The user's home directory becomes `~`, the renderer's home folder, when it lies outside that,
    `$CUJU_RENDER_HOME`, and the user's name, as a whole word, `<user>`. A path matches in either
    kind of slash, and on Windows a path or a name matches whatever its case.
    """
    text = str(text)
    flags = re.IGNORECASE if _CASELESS else 0
    users = [path for path in (os.path.expanduser('~'), str(Path.home())) if _spellings(path)]
    renderer = _home.home()
    # A renderer's home inside the user's reads as a path under `~`, which names nothing private.
    inside = any(renderer.resolve().is_relative_to(Path(path).resolve()) for path in users)
    replacements = [(spelling, '~') for path in users for spelling in _spellings(path)]
    if not inside:
        token = f'${_home.HOME_VARIABLE}'
        replacements += [(spelling, token) for spelling in _spellings(str(renderer))]
    for found, written in sorted(replacements, key=lambda pair: len(pair[0]), reverse=True):
        text = re.sub(re.escape(found), lambda _, written=written: written, text, flags=flags)
    for name in sorted(_user_names(), key=len, reverse=True):
        text = re.sub(rf'(?<!\w){re.escape(name)}(?!\w)', '<user>', text, flags=flags)
    return text


class _Capture(logging.Handler):
    """Keeps the recent warnings and errors of the logger `cuju`.

    Python prints a warning to the standard error stream only while no handler would take it, so
    the capture prints it there itself in that case, and the server's console shows what it showed
    before.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        _keep(record.levelname, message)
        if not _other_handlers(self) and logging.lastResort is not None:
            if record.levelno >= logging.lastResort.level:
                logging.lastResort.handle(record)


def _other_handlers(own: logging.Handler) -> bool:
    logger: logging.Logger | None = logging.getLogger('cuju')
    while logger is not None:
        if any(handler is not own for handler in logger.handlers):
            return True
        if not logger.propagate:
            break
        logger = logger.parent
    return False


def _keep(level: str, message: str) -> None:
    with _RECENT_LOCK:
        _RECENT.append(
            {'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'level': level, 'message': scrub(message)}
        )


def install_capture() -> None:
    """Starts keeping the recent warnings and errors of the logger `cuju`, once per process."""
    logger = logging.getLogger('cuju')
    if not any(isinstance(handler, _Capture) for handler in logger.handlers):
        handler = _Capture(logging.WARNING)
        logger.addHandler(handler)


def note_error(text: str) -> None:
    """Keeps an error of the server that no logger saw, such as a request that failed inside."""
    _keep('ERROR', text)


def recent() -> list[dict[str, Any]]:
    """Returns the recent warnings and errors, the oldest first."""
    with _RECENT_LOCK:
        return list(_RECENT)


def _version_of(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _versions() -> dict[str, Any]:
    return {
        'cuju': __version__,
        'python': platform.python_version(),
        'implementation': platform.python_implementation(),
        'system': platform.system(),
        'release': platform.release(),
        'machine': platform.machine(),
        'torch': _version_of('torch'),
        'numpy': _version_of('numpy'),
    }


def _home_facts() -> dict[str, Any]:
    folder = _home.home()
    problems = []
    existing = folder
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    if folder.exists() and not folder.is_dir():
        problems.append('the home folder is a file')
    elif not folder.exists():
        if existing.exists() and not existing.is_dir():
            problems.append('the home folder lies under a file')
        else:
            problems.append('the home folder is missing, the server makes it as it starts')
    elif not os.access(folder, os.W_OK | os.X_OK):
        problems.append('the home folder is not writable')
    free = None
    try:
        free = shutil.disk_usage(existing if existing.is_dir() else existing.parent).free
    except OSError:
        free = None
    return {
        'path': scrub(folder),
        'moved': bool(os.environ.get(_home.HOME_VARIABLE)),
        'exists': folder.is_dir(),
        'writable': folder.is_dir() and os.access(folder, os.W_OK | os.X_OK),
        'free_bytes': free,
        'problems': problems,
    }


def _folders() -> dict[str, dict[str, int]]:
    folder = _home.home()
    sizes: dict[str, dict[str, int]] = {}
    if not folder.is_dir():
        return sizes
    for child in sorted(folder.iterdir()):
        if not child.is_dir():
            continue
        files = 0
        size = 0
        for path in child.rglob('*'):
            try:
                if path.is_file():
                    files += 1
                    size += path.stat().st_size
            except OSError:
                continue
        sizes[child.name] = {'files': files, 'bytes': size}
    loose = [path for path in folder.iterdir() if path.is_file()]
    sizes['.'] = {'files': len(loose), 'bytes': sum(path.stat().st_size for path in loose)}
    return sizes


def _library_counts() -> dict[str, Any]:
    from .._http import server as _server
    from .._registry import teams as _teams
    from .._store import library as _library

    counts: dict[str, Any] = {}
    try:
        counts['recordings'] = len(_library.matches())
        counts['trash'] = len(_library.matches(trash=True))
    except OSError as error:
        counts['recordings_error'] = scrub(error)
    try:
        counts['teams'] = sum(1 for entry in _teams.teams() if entry.get('kind') != 'builtin')
    except OSError as error:
        counts['teams_error'] = scrub(error)
    tournaments = _home.home() / 'tournaments'
    counts['tournaments'] = len(list(tournaments.glob('*.json'))) if tournaments.is_dir() else 0
    boards = 0
    challenges = _home.home() / 'challenges'
    for path in challenges.glob('*.json') if challenges.is_dir() else []:
        try:
            document = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(document, dict) and document.get('entries'):
            boards += 1
    counts['challenge_boards'] = boards
    try:
        counts['live_sources'] = len(_server._sources())
    except OSError:
        counts['live_sources'] = 0
    return counts


def _server_facts() -> dict[str, Any]:
    path = _home.home() / _launch.SERVER_FILE
    # The file is looked at first, since asking for the running server removes a stale one.
    found = path.is_file()
    server = _launch.running()
    if server is not None:
        return {'file': True, 'running': True, 'port': server.port, 'stale': False}
    return {'file': found, 'running': False, 'port': None, 'stale': found}


def _checks(report: dict[str, Any]) -> list[dict[str, Any]]:
    from .._store import library as _library

    home = report['home']
    checks = [
        {
            'name': 'home folder',
            'ok': home['exists'] and not home['problems'],
            'detail': ', '.join(home['problems']) or f'{home["path"]} exists',
        },
        {
            'name': 'writing',
            'ok': bool(home['writable']),
            'detail': 'the server can write its folder'
            if home['writable']
            else 'the server cannot write its folder, choose another with --home',
        },
    ]
    free = home['free_bytes']
    checks.append(
        {
            'name': 'disk space',
            'ok': free is None or free >= LOW_DISK_BYTES,
            'detail': 'unknown'
            if free is None
            else f'{free / 1024**3:.1f} GB free'
            + ('' if free >= LOW_DISK_BYTES else ', recordings may fail to save'),
        }
    )
    shipped = _library.samples()
    checks.append(
        {
            'name': 'samples',
            'ok': len(shipped) >= 2,
            'detail': f'{len(shipped)} sample recordings ship with the package',
        }
    )
    page = Path(__file__).parents[1] / 'web' / 'index.html'
    checks.append(
        {
            'name': 'page files',
            'ok': page.is_file(),
            'detail': 'the files of the page are in place'
            if page.is_file()
            else 'the page is missing, install cuju again',
        }
    )
    server = report['server']
    checks.append(
        {
            'name': 'server file',
            'ok': not server['stale'],
            'detail': 'a stale server.json names a server that does not answer, the next start '
            'replaces it'
            if server['stale']
            else ('the server of the folder answers' if server['running'] else 'no server runs'),
        }
    )
    try:
        from .._export import video_jobs as _video_jobs

        video = _video_jobs.availability()
        # Video export is optional, so a missing program warns and passes.
        checks.append(
            {
                'name': 'video export',
                'ok': True,
                'warning': not video['available'],
                'detail': 'Chrome and ffmpeg are found'
                if video['available']
                else scrub(' '.join(video['missing'])),
            }
        )
    except Exception as error:
        checks.append({'name': 'video export', 'ok': True, 'warning': True, 'detail': scrub(error)})
    return checks


def server_report() -> dict[str, Any]:
    """Returns the server's side of the diagnostic report, a document of plain values."""
    report: dict[str, Any] = {
        'kind': 'server',
        'created': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'versions': _versions(),
        'home': _home_facts(),
        'folders': _folders(),
        'library': _library_counts(),
        'server': _server_facts(),
        'errors': recent(),
    }
    report['checks'] = _checks(report)
    return report


def _log_errors() -> list[dict[str, Any]]:
    """Returns the lines of server.log near its end that name an error."""
    path = _home.home() / _launch.LOG_FILE
    try:
        lines = path.read_text(errors='replace').splitlines()[-_LOG_LINES:]
    except OSError:
        return []
    found = [line for line in lines if any(word in line.lower() for word in _LOG_WORDS)]
    return [{'at': None, 'level': 'LOG', 'message': scrub(line)} for line in found[-20:]]


def _ask_server(port: int, timeout: float = 3.0) -> dict[str, Any] | None:
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    try:
        connection.request('GET', '/api/help/doctor', headers={'Host': f'127.0.0.1:{port}'})
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            return None
        document = json.loads(body)
        return document if isinstance(document, dict) else None
    except (OSError, ValueError):
        return None
    finally:
        connection.close()


def report() -> dict[str, Any]:
    """Returns the report of the command, the local view with the running server's own.

    The server's recent errors come from the server itself, and the lines of server.log that
    name an error join them.
    """
    local = server_report()
    local['kind'] = 'command'
    local['errors'] = _log_errors()
    if local['server']['running']:
        answer = _ask_server(local['server']['port'])
        local['server']['report'] = answer
        if answer is not None:
            local['errors'] = [*local['errors'], *answer.get('errors', [])]
            versions = answer.get('versions', {})
            if versions.get('cuju') != __version__:
                local['checks'].append(
                    {
                        'name': 'server version',
                        'ok': False,
                        'detail': f'the server runs cuju {versions.get("cuju")}, this command '
                        f'{__version__}, restart the server',
                    }
                )
    return local


def _size(value: int | None) -> str:
    if value is None:
        return 'unknown'
    for unit in ('bytes', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            return f'{value} bytes' if unit == 'bytes' else f'{value:.1f} {unit}'
        value /= 1024
    return str(value)


def text(document: dict[str, Any]) -> str:
    """Returns a report as lines of text, the way it reads in an issue."""
    lines = [f'cuju render diagnostic report, {document.get("created", "")}', '']
    versions = document.get('versions', {})
    lines.append('Versions')
    for key in (
        'cuju',
        'python',
        'implementation',
        'system',
        'release',
        'machine',
        'torch',
        'numpy',
    ):
        if key in versions:
            lines.append(
                f'  {key}: {versions[key] if versions[key] is not None else "not installed"}'
            )
    home = document.get('home', {})
    lines += ['', 'Home folder', f'  path: {home.get("path")}']
    lines.append(f'  moved by {_home.HOME_VARIABLE}: {"yes" if home.get("moved") else "no"}')
    lines.append(f'  exists: {"yes" if home.get("exists") else "no"}')
    lines.append(f'  writable: {"yes" if home.get("writable") else "no"}')
    lines.append(f'  free space: {_size(home.get("free_bytes"))}')
    lines += ['', 'Folders']
    for name, entry in document.get('folders', {}).items():
        lines.append(f'  {name}: {entry["files"]} files, {_size(entry["bytes"])}')
    lines += ['', 'Library']
    for name, value in document.get('library', {}).items():
        lines.append(f'  {name.replace("_", " ")}: {value}')
    server = document.get('server', {})
    lines += ['', 'Server']
    if server.get('running'):
        lines.append(f'  runs on port {server.get("port")}')
    else:
        lines.append('  no server runs' + (', server.json is stale' if server.get('stale') else ''))
    lines += ['', 'Checks']
    for check in document.get('checks', []):
        mark = 'FAIL' if not check['ok'] else 'warn' if check.get('warning') else 'ok'
        lines.append(f'  {mark}  {check["name"]}, {check["detail"]}')
    errors = document.get('errors', [])
    lines += ['', 'Recent warnings and errors']
    if not errors:
        lines.append('  none')
    for entry in errors:
        when = f'{entry["at"]} ' if entry.get('at') else ''
        lines.append(f'  {when}{entry["level"]} {entry["message"]}')
    return '\n'.join(lines)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Adds the options of `cuju render doctor`."""
    parser.add_argument('--json', action='store_true', help='print the report as JSON')
    parser.add_argument('--out', help='write the report to this file as well')


def run(options: argparse.Namespace) -> int:
    """Runs `cuju render doctor`, and returns 0 when every check passes and 1 otherwise."""
    document = report()
    output = json.dumps(document, indent=2) if options.json else text(document)
    print(output)
    if options.out:
        Path(options.out).write_text(output + '\n', encoding='utf-8')
        print(f'wrote {options.out}', file=sys.stderr)
    return 0 if all(check['ok'] for check in document['checks']) else 1
