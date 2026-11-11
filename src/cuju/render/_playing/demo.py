# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The demo of the renderer, `cuju render demo`, a live match between the built-in AIs.

The command starts the server, or uses one that already answers on its port, starts a match in a
process of its own and opens the page on that match, so a newcomer sees play within seconds. The
match plays one environment on the CPU at real time, ten steps a second, with the built-in AI on
both sides and automatic resets, so one match follows another until Ctrl+C. Its stream is a live
source like any other, listed on the page while it runs.

The match process reports the identifier of its source as one JSON line on standard output and
stops when its standard input closes, so the command ends it cleanly on every platform, and its
source withdraws its announcement on the way out. Ctrl+C ends the command, the match and the
server within about a second.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any, TextIO

from .._http import launch as _launch
from .._text import messages as _messages

# The scenario of each format, a short five a side match by default and eleven a side on request.
SCENARIOS = {'5v5': '5_vs_5', '11v11': '11_vs_11_stochastic'}
# The title of the match, a label that the page shows in its language, and its English text.
_TITLE_LABEL = _messages.label('server.names.demo')
_TITLE = _TITLE_LABEL['text']
# How long the command waits for the server, and for the match to load and announce itself.
_SERVER_WAIT = 30.0
_MATCH_WAIT = 120.0
# How long a match or server that was asked to stop may take before it is ended by force, and
# how long a server that Ctrl+C reached too may take to end by itself before it is asked to.
_STOP_WAIT = 1.0
_SERVER_GRACE = 0.5


def _info(address: str) -> dict[str, Any] | None:
    """Returns the answer of a renderer's server at `address`, or `None` when none answers."""
    try:
        with urllib.request.urlopen(address + 'api/info', timeout=2) as response:
            document = json.loads(response.read())
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) and 'version' in document else None


def _listed(address: str, identifier: str) -> bool:
    """Returns whether the server at `address` lists the live source `identifier`."""
    try:
        with urllib.request.urlopen(address + 'api/live', timeout=2) as response:
            sources = json.loads(response.read())
    except (OSError, ValueError):
        return False
    return any(isinstance(item, dict) and item.get('id') == identifier for item in sources)


def _lines(stream: TextIO, lines: queue.Queue[str | None], echo: bool) -> None:
    """Moves the lines of a child's output into `lines`, then `None`, echoing them when asked."""
    for line in stream:
        if echo:
            print(line, end='', flush=True)
        lines.put(line)
    lines.put(None)


def _reader(stream: TextIO, echo: bool = False) -> queue.Queue[str | None]:
    """Starts a thread that reads a child's output and returns the queue of its lines."""
    lines: queue.Queue[str | None] = queue.Queue()
    threading.Thread(target=_lines, args=(stream, lines, echo), daemon=True).start()
    return lines


def _next_line(lines: queue.Queue[str | None], process: subprocess.Popen, wait: float) -> str:
    """Returns the next line of a child's output, or an empty string when it ended or took long."""
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            line = lines.get(timeout=0.2)
        except queue.Empty:
            if process.poll() is not None and lines.empty():
                return ''
            continue
        return line or ''
    return ''


def _wait_all(processes: list[subprocess.Popen], seconds: float) -> None:
    """Waits until every process ended or `seconds` passed, in short sleeps that Ctrl+C breaks."""
    deadline = time.monotonic() + seconds
    while any(process.poll() is None for process in processes) and time.monotonic() < deadline:
        time.sleep(0.05)


def _stop(
    match: subprocess.Popen | None, server: subprocess.Popen | None, interrupted: bool
) -> None:
    """Stops the match and the server together, by force when they take too long.

    Closing its input ends the match, which withdraws its source. The server ends on a terminate
    signal, which it takes as Ctrl+C, and after a Ctrl+C that reached it as well it has a moment
    to end by itself first. Another Ctrl+C on the way ends both at once.
    """
    running = [process for process in (match, server) if process is not None]
    running = [process for process in running if process.poll() is None]
    if not running:
        return
    try:
        if match in running and match.stdin is not None:
            with contextlib.suppress(OSError):
                match.stdin.close()
        if server in running:
            if interrupted:
                _wait_all([server], _SERVER_GRACE)
            if server.poll() is None:
                server.terminate()
        _wait_all(running, _STOP_WAIT)
        for process in running:
            if process.poll() is None:
                process.terminate()
        _wait_all(running, _STOP_WAIT)
    except KeyboardInterrupt:
        pass
    for process in running:
        if process.poll() is None:
            process.kill()
            process.wait()


def _child(arguments: list[str]) -> subprocess.Popen:
    """Starts `python -m` with `arguments`, with piped input and output and the same folder."""
    return subprocess.Popen(
        [sys.executable, '-m', *arguments],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=dict(os.environ),
    )


def demo(
    port: int = 8780,
    scenario: str = SCENARIOS['5v5'],
    open_browser: bool = True,
    seed: int | None = None,
    steps: int | None = None,
) -> int:
    """Streams a live match between the built-in AIs to the page until Ctrl+C.

    Args:
        port: The port of the server, which the command starts unless a server answers there.
        scenario: A shipped scenario, played with the built-in AI on both sides.
        open_browser: Whether to open the page on the match in the default browser.
        seed: The seed of the match, or `None` for one drawn from the clock.
        steps: The number of steps after which the match ends, or `None` to play on.

    Returns:
        The exit status, 0 when the demo ran and ended, 1 when it could not start.
    """
    address = f'http://127.0.0.1:{port}/'
    server = match = None
    interrupted = False
    try:
        info = _info(address) if port else None
        if info is None:
            server = _child(['cuju.render', 'serve', '--port', str(port)])
            lines = _reader(server.stdout)
            deadline = time.monotonic() + _SERVER_WAIT
            first = 'serves'
            while first and 'serves http://' not in first:
                first = _next_line(lines, server, max(0.0, deadline - time.monotonic()))
                if first and 'serves http://' not in first:
                    print(first, end='', flush=True)
            if not first:
                print(
                    f'cuju render demo: the server could not start on port {port}, which another '
                    'program may hold, so try another with --port',
                    file=sys.stderr,
                )
                return 1
            address = first[first.index('http://') :].split()[0]
            print(first, end='', flush=True)
            # The server's later lines reach the terminal as they come.
            threading.Thread(
                target=lambda: [print(line, end='', flush=True) for line in iter(lines.get, None)],
                daemon=True,
            ).start()
        else:
            print(f'cuju render demo uses the server at {address}', flush=True)
        command = ['cuju.render._playing.demo', '--scenario', scenario]
        if seed is not None:
            command += ['--seed', str(seed)]
        if steps is not None:
            command += ['--steps', str(steps)]
        match = _child(command)
        lines = _reader(match.stdout)
        line = _next_line(lines, match, _MATCH_WAIT)
        try:
            identifier = json.loads(line)['live']
        except (ValueError, TypeError, KeyError):
            print('cuju render demo: the match could not start', file=sys.stderr)
            return 1
        deadline = time.monotonic() + 10
        while not _listed(address, identifier) and time.monotonic() < deadline:
            time.sleep(0.2)
        if _listed(address, identifier):
            page = f'{address}#live={identifier}'
        else:
            page = address
            print(
                'cuju render demo: the server lists no demo, since it keeps another folder, '
                'so start it with the same --home',
                file=sys.stderr,
            )
        print(f'cuju render demo streams {scenario} at {page}, Ctrl+C stops it', flush=True)
        if open_browser and not _launch.open_browser(page):
            print(f'Open {page} in a browser.', flush=True)
        # A wait in short sleeps, which Ctrl+C breaks on every platform.
        while match.poll() is None:
            time.sleep(0.1)
        return 0 if match.returncode == 0 else 1
    except KeyboardInterrupt:
        interrupted = True
        print('cuju render demo stopped', flush=True)
        return 0
    finally:
        _stop(match, server, interrupted)


def _input_closed(stop: threading.Event) -> None:
    """Sets `stop` when standard input closes, the command's way to end the match."""
    with contextlib.suppress(OSError, ValueError):
        while sys.stdin.readline():
            pass
    stop.set()


def play(scenario: str, seed: int | None, steps: int | None, stop: threading.Event) -> None:
    """Plays the demo's match at real time and streams it until `stop` is set or `steps` ran.

    Args:
        scenario: A shipped scenario, played with the built-in AI on both sides.
        seed: The seed, or `None` for one drawn from the clock.
        steps: The number of steps to play, or `None` to play on.
        stop: The event that ends the match.
    """
    import torch

    from cuju import BatchEnvironment

    from .._format import recording as _recording
    from .._registry import teams as _teams
    from .._watch import live as _live

    batch = BatchEnvironment(
        f'{scenario}_l0_r0',
        environment_count=1,
        device='cpu',
        seed=int(time.time()) % 2**31 if seed is None else seed,
    )
    source = None
    try:
        reader = _recording.StateReader(int(batch.left_players[0] + batch.right_players[0]))
        batch.reset()
        state = batch.get_state(0)
        lineup = reader.lineup(state)
        teams = _teams.match_teams('builtin', 'builtin')
        source = _live.LiveSource(batch, 0, _TITLE_LABEL, teams, scenario)
        source._timing = _recording.scenario_timing(state)
        source.push(reader.frame(state), lineup)
        print(json.dumps({'live': source.identifier}), flush=True)
        actions = torch.zeros((1, batch.agents), dtype=torch.int32)
        played = 0
        due = time.monotonic()
        while not stop.is_set() and (steps is None or played < steps):
            _, _, done, _ = batch.step(actions)
            played += 1
            flags = 2 if bool(done[0]) else 0
            source.push(reader.frame(batch.get_state(0), flags), lineup)
            due = max(due + 0.1, time.monotonic() - 0.2)
            stop.wait(max(0.0, due - time.monotonic()))
    finally:
        if source is not None:
            source.close()
        batch.close()


def main(arguments: list[str] | None = None) -> None:
    """Runs the demo's match, the process that `demo` starts."""
    parser = argparse.ArgumentParser(prog='python -m cuju.render._playing.demo')
    parser.add_argument('--scenario', default=SCENARIOS['5v5'])
    parser.add_argument('--seed', type=int, default=None)
    parser.add_argument('--steps', type=int, default=None)
    options = parser.parse_args(arguments)
    stop = threading.Event()
    threading.Thread(target=_input_closed, args=(stop,), daemon=True).start()
    with contextlib.suppress(KeyboardInterrupt):
        play(options.scenario, options.seed, options.steps, stop)
    # The source and the batch are closed, so the process ends at once and skips the teardown of
    # torch, which takes about a second.
    with contextlib.suppress(Exception, KeyboardInterrupt):
        sys.stdout.flush()
        sys.stderr.flush()
    os._exit(0)


if __name__ == '__main__':
    main()
