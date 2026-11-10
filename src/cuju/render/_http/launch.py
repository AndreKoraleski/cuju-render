# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""Finds the renderer's server of a home folder, starts one in the background, and names what the
page opens.

A running server writes `server.json` into its home folder with its port, its process and the key
that lets a notebook frame its page, and removes the file when it stops. `running` reads that file
and asks the server whether it answers, so `show` and `cuju render open` reuse the server of their
folder and start one only when none answers.
"""

from __future__ import annotations

import atexit
import contextlib
import errno
import getpass
import gzip
import http.client
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cuju.errors import ArgumentError, Error

from .._format import recording as _recording
from .._store import home as _home
from .._store import library as _library

# The file of the home folder that names the running server.
SERVER_FILE = 'server.json'
# The file of the home folder that a server started in the background writes its messages to.
LOG_FILE = 'server.log'
# The port that a server takes when it is free.
DEFAULT_PORT = 8780
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
# The domains of the port proxy of Google Colab, whose names resolve to Google's servers alone.
COLAB_DOMAINS = ('.googleusercontent.com', '.colab.dev')
# The numbers of an address in use, on POSIX and on Windows, where 10013 also marks a port that the
# system reserves.
_IN_USE = {errno.EADDRINUSE, 10048, 10013}
# A server started in the background announces itself within this many seconds.
_START_SECONDS = 60


class LoopbackServer(http.server.ThreadingHTTPServer):
    """The HTTP server of the renderer, which refuses a port that another program holds.

    Windows lets a socket with `SO_REUSEADDR` take a port that another socket listens on, so the
    server sets the option only elsewhere, where it lets a restarted server take its port again.
    """

    allow_reuse_address = sys.platform != 'win32'
    daemon_threads = True


@dataclass
class Server:
    """A server of the renderer that answers for a home folder.

    Attributes:
        port: The port of the loopback interface.
        pid: The process of the server.
        key: The key that lets a notebook frame the page.
        home: The home folder.
        process: The process, when this one started it.
    """

    port: int
    pid: int
    key: str
    home: Path
    process: subprocess.Popen | None = field(default=None, repr=False, compare=False)

    @property
    def url(self) -> str:
        """The address of the page, such as `http://127.0.0.1:8780/`."""
        return f'http://127.0.0.1:{self.port}/'


def in_domains(hostname: str | None, domains: tuple[str, ...]) -> bool:
    """Returns whether `hostname` lies under one of `domains`, such as `.colab.dev`."""
    return bool(hostname) and any(hostname.endswith(domain) for domain in domains)


def check_home() -> Path:
    """Returns the home folder once it is a folder that the renderer can write to.

    Raises:
        Error: If the home folder is a file, lies under a file, or cannot be created or written.
    """
    folder = _home.home()
    advice = f'choose another with --home or ${_home.HOME_VARIABLE}'
    for parent in [folder, *folder.parents]:
        if parent.exists() and not parent.is_dir():
            raise Error(
                f'the renderer folder {folder} cannot be made, {parent} is a file; {advice}'
            )
        if parent.exists():
            break
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise Error(
            f'the renderer folder {folder} cannot be made, {error.strerror or error}; {advice}'
        ) from None
    if not os.access(folder, os.W_OK | os.X_OK):
        raise Error(f'the renderer folder {folder} is not writable; {advice}')
    return folder


def announce(port: int, key: str) -> Path:
    """Writes the file that names this process as the server of the home folder."""
    path = _home.home() / SERVER_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'{path.name}.{os.getpid()}.part')
    temporary.write_text(json.dumps({'port': port, 'pid': os.getpid(), 'key': key}))
    temporary.replace(path)
    return path


def withdraw(path: Path) -> None:
    """Removes the file of a stopping server, unless a later server has written its own."""
    with contextlib.suppress(OSError, ValueError):
        if json.loads(path.read_text()).get('pid') == os.getpid():
            path.unlink()


def answers(port: int, timeout: float = 2.0) -> str | None:
    """Returns the version of cuju whose renderer answers on `port`, or `None`."""
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    try:
        connection.request('GET', '/api/info', headers={'Host': f'127.0.0.1:{port}'})
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            return None
        version = json.loads(body).get('version')
        return version if isinstance(version, str) else None
    except (OSError, ValueError, AttributeError):
        return None
    finally:
        connection.close()


def running() -> Server | None:
    """Returns the server of the home folder when its process runs and it answers, else `None`."""
    from .server import _alive

    path = _home.home() / SERVER_FILE
    try:
        entry = json.loads(path.read_text())
        port, pid, key = entry['port'], entry['pid'], entry['key']
    except (OSError, ValueError, TypeError, KeyError):
        return None
    if not (
        isinstance(port, int)
        and isinstance(pid, int)
        and isinstance(key, str)
        and 0 < port < 65536
        and _alive(pid)
        and answers(port)
    ):
        return None
    return Server(port, pid, key, _home.home())


def port_free(port: int) -> bool:
    """Returns whether a server could listen on `port` of the loopback interface now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


def port_error(port: int, error: OSError) -> Exception:
    """Returns the error to raise when the server cannot listen on `port`, with what to do."""
    if error.errno not in _IN_USE and getattr(error, 'winerror', None) not in _IN_USE:
        return error
    server = running()
    if server is not None and server.port == port:
        return Error(
            f'port {port} is in use by the server of this folder, which serves {server.url}; '
            f'open that page, or run cuju render open, or choose another port with --port '
            f'{port + 10} or --port 0 for a free one'
        )
    owner = 'another cuju render server' if answers(port) else 'another program'
    return Error(
        f'port {port} is in use by {owner}; choose another port with --port {port + 10}, '
        f'or --port 0 for a free one'
    )


def open_browser(url: str) -> bool:
    """Opens `url` in the default browser and returns whether one opened.

    A machine without a display, such as a server reached over SSH, has only browsers of the
    terminal, which would take over the terminal of a running program, so none opens there.
    """
    graphical = ('DISPLAY', 'WAYLAND_DISPLAY', 'BROWSER')
    if os.name == 'posix' and sys.platform != 'darwin' and not any(map(os.environ.get, graphical)):
        return False
    import webbrowser

    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def _package_path() -> str:
    """Returns the folder that holds the package cuju, for the path of a child process."""
    return str(Path(__file__).resolve().parents[3])


def start(port: int | None = None, stay: bool = False, colab: bool = False) -> Server:
    """Returns the server of the home folder, started in a process of its own when none answers.

    Args:
        port: The port of a server that this call starts, by default 8780 when it is free and a
            free port otherwise.
        stay: Whether a server that this call starts keeps running after this process ends. By
            default it ends with this process.
        colab: Whether a server that this call starts also answers through Colab's port proxy.

    Raises:
        Error: If the server does not start, with the end of its messages.
    """
    server = running()
    if server is not None:
        return server
    home = check_home()
    if port is None:
        port = DEFAULT_PORT if port_free(DEFAULT_PORT) else 0
    command = [sys.executable, '-m', 'cuju.render', '--home', str(home), 'serve', '--port']
    command.append(str(port))
    if not stay:
        command += ['--parent', str(os.getpid())]
    if colab:
        command.append('--colab')
    environment = os.environ.copy()
    paths = [_package_path(), *filter(None, environment.get('PYTHONPATH', '').split(os.pathsep))]
    environment['PYTHONPATH'] = os.pathsep.join(dict.fromkeys(paths))
    options: dict[str, Any] = {}
    if sys.platform == 'win32':
        # Windows: 0x08000000 is CREATE_NO_WINDOW, 0x00000008 DETACHED_PROCESS and 0x00000200
        # CREATE_NEW_PROCESS_GROUP, which keeps a staying server out of this console's Ctrl+C.
        options['creationflags'] = 0x00000208 if stay else 0x08000000
    else:
        options['start_new_session'] = stay
    log = home / LOG_FILE
    with log.open('ab') as stream:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            cwd=home,
            env=environment,
            **options,
        )
    if not stay:
        atexit.register(_stop, process)
    deadline = time.monotonic() + _START_SECONDS
    while time.monotonic() < deadline:
        server = running()
        if server is not None and server.pid == process.pid:
            server.process = process
            return server
        if process.poll() is not None:
            break
        time.sleep(0.1)
    _stop(process)
    tail = ''
    with contextlib.suppress(OSError):
        tail = log.read_text(errors='replace').strip().splitlines()[-1]
    raise Error('the renderer server did not start' + (f', {tail}' if tail else f', see {log}'))


def _stop(process: subprocess.Popen) -> None:
    """Ends a server that this process started."""
    if process.poll() is None:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)


def import_recording(path: str | os.PathLike) -> str:
    """Returns the identifier of a recording file in the library, copying the file in when needed.

    A file of the library's folder keeps its identifier, and a file whose bytes the library
    already holds opens that recording, so opening a file twice adds it once.

    Raises:
        ArgumentError: If the file is missing or is not a recording of cuju.
    """
    source = Path(path).expanduser()
    if not source.is_file():
        raise ArgumentError(f'expected a recording file, found no file {source}')
    source = source.resolve()
    folder = _home.folder('matches').resolve()
    if source.parent == folder and source.suffix == '.cjr' and _home.valid_identifier(source.stem):
        return source.stem
    try:
        header = _recording.read_header(source)
    except (OSError, ValueError, EOFError, gzip.BadGzipFile, Error):
        raise ArgumentError(
            f'expected a recording of cuju, found other bytes in {source}'
        ) from None
    size = source.stat().st_size
    data = None
    for other in folder.glob('*.cjr'):
        if other.stat().st_size == size:
            data = data if data is not None else source.read_bytes()
            if other.read_bytes() == data and _library.path_of(other.stem) is not None:
                return other.stem
    target = _library._reserve()
    try:
        shutil.copyfile(source, target)
        count, last = 0, None
        for frame in _recording.frames(target):
            count, last = count + 1, frame
        _library._write_summary(target, header, last, count)
    except BaseException:
        target.unlink(missing_ok=True)
        target.with_suffix('.json').unlink(missing_ok=True)
        raise
    return target.stem


def resolve(target: str | os.PathLike | None) -> str:
    """Returns the part of the page's address that opens `target`, from `#` on, or a whole URL.

    Args:
        target: A recording file, the identifier of a recording or live source, a URL, or `None`
            for the Home page.

    Raises:
        ArgumentError: If the target names nothing that the page can open.
    """
    if target is None:
        return '#page=home'
    text = os.fspath(target)
    if isinstance(target, str) and urllib.parse.urlsplit(text).scheme in ('http', 'https'):
        return text
    path = Path(text).expanduser()
    separator = '/' in text or os.sep in text
    if not isinstance(target, str) or path.is_file() or path.suffix == '.cjr' or separator:
        return f'#match={urllib.parse.quote(import_recording(path))}'
    if _home.valid_identifier(text):
        from .server import _sources

        if any(source.get('id') == text for source in _sources()):
            return f'#live={urllib.parse.quote(text)}'
        # A shipped sample that the library lacks yet, as in a home folder whose server never
        # started, comes in on request, as `cuju render sample` brings it.
        if _library.path_of(text, include_trash=True) is None and text in _library.samples():
            _library.add_samples([text])
        if _library.path_of(text) is not None:
            return f'#match={urllib.parse.quote(text)}'
        if _library.path_of(text, include_trash=True) is not None:
            raise ArgumentError(
                f'the recording {text} is in the Trash, restore it on the Recordings page first'
            )
    raise ArgumentError(
        f'expected a recording file, the identifier of a recording or live source, or a URL, '
        f'found {text!r}, which names none in {_home.home()}'
    )


def tunnel_command(port: int) -> str:
    """Returns the SSH command that forwards `port` of this machine to the same port of another.

    Inside an SSH session the command names the address and port that the session came in on,
    and otherwise the name of this machine.
    """
    user = ''
    with contextlib.suppress(Exception):
        user = getpass.getuser()
    host, ssh_port = socket.gethostname(), None
    connection = os.environ.get('SSH_CONNECTION', '').split()
    if len(connection) == 4:
        host, ssh_port = connection[2], connection[3]
    login = f'{user}@{host}' if user else host
    option = f' -p {ssh_port}' if ssh_port and ssh_port != '22' else ''
    return f'ssh -N -L {port}:127.0.0.1:{port}{option} {login}'


def remote_note(port: int) -> str:
    """Returns the lines that `cuju render serve --remote` prints, how to reach the page."""
    return '\n'.join(
        [
            'To watch from another computer, run this there and keep it running:',
            f'    {tunnel_command(port)}',
            f'then open http://127.0.0.1:{port}/ in its browser.',
            'VS Code forwards the port from its Ports view, and Google Colab shows the page with',
            'cuju.render.show in a notebook cell.',
        ]
    )
