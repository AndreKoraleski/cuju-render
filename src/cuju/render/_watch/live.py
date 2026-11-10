# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""A live source, which streams one environment of a running batch to the renderer's page.

The source listens on a port of the loopback interface and announces itself with a small file in
the renderer's folder, which the server lists. It reads a state only while a viewer watches, in
passages of five seconds of play paced to real time, so an unwatched batch pays one attribute check
per step and a watched one reads about ten states per second of wall time. Reading a state leaves
every output of the batch as it is, and a failure of the source turns it off, never the step.

The source keeps the last ten seconds of the steps it read, so a viewer who joins late starts with
that history. `CUJU_RENDER_BACKLOG` makes it read every step even unwatched, at the cost of one
state read per step, so that the first viewer finds a history as well.

A viewer may switch the environment that the source shows with `select_environment`, or through
the server, and the switch waits for the end of the next step. It changes which environment the
source reads and nothing of the batch, ends every stream of the last environment and starts a new
stream identifier, which the announcement names.

A viewer that asks for `/stream?sequence=1` receives every frame after a serial number of eight
bytes, and the stream ends with the serial `END`. The serials count the frames of one stream
identifier, which the header names, so a viewer that reconnects drops the frames it already holds
and sees the frames it missed as a gap.

A viewer that asks for `/grid?first=0&count=16` receives small views of a range of environments
as JSON, which the source reads at a low and bounded pace while a viewer asks, as `_grid` says.

A viewer of numbered frames that also asks for `annotations=1` receives the annotations of
`annotate`, each batch of them after the serial `NOTES`, the length of a JSON object and the
object, before the next frame.
"""

from __future__ import annotations

import atexit
import collections
import contextlib
import http.server
import json
import logging
import os
import queue
import struct
import threading
import time
import urllib.parse
import weakref
from typing import Any

from cuju.errors import ArgumentError

from .._format import annotations as _annotations
from .._format import recording as _recording
from .._store import home as _home
from . import grid as _grid

# The variable that turns live sources on for every batch, with the environment to show.
LIVE_VARIABLE = 'CUJU_RENDER'
# Frames a viewer may hold before the source skips steps, five seconds of play.
_BUFFER = 50
# The variable that makes a source read every step, watched or not, for a history of its seconds.
BACKLOG_VARIABLE = 'CUJU_RENDER_BACKLOG'
# The history that a late viewer receives, ten seconds of steps.
_HISTORY = 100
# A watched source reads passages of this many consecutive steps, five seconds of play, and starts
# the next one when the wall clock has caught up, so a fast batch reads ten states a second.
_PASSAGE = 50
_STEPS_PER_SECOND = 10
_LOOPBACK = ('127.0.0.1', 'localhost', '::1')
# The serial that ends a numbered stream, which no frame carries.
END = 2**64 - 1
# The serial that opens a batch of annotations, which no frame carries either.
NOTES = 2**64 - 2
_SERIAL = struct.Struct('<Q')
_LENGTH = struct.Struct('<I')
_LOGGER = logging.getLogger('cuju')


class _Viewer:
    """One connected viewer, with its queue of frames, numbered when `sequence` is true.

    A viewer with `annotations` receives the annotations too, which need numbered frames.
    """

    def __init__(self, sequence: bool = False, annotations: bool = False) -> None:
        self.frames: queue.Queue[bytes | None] = queue.Queue(_BUFFER)
        self.header: bytes | None = None
        self.sequence = sequence
        self.annotations = sequence and annotations


class LiveSource:
    """Streams one environment of a batch to the renderer while a viewer watches.

    Attributes:
        identifier: The name of the source in the renderer's list.
        environment: The index of the environment that the source shows.
        environment_count: The number of environments of the batch, which a viewer may switch
            between.
        title: The title that the viewer shows.
        port: The port of the loopback interface that the source listens on.
    """

    def __init__(
        self,
        batch: Any,
        environment: int = 0,
        title: str | None = None,
        teams: list[dict[str, Any]] | None = None,
        scenario: str | None = None,
        backlog: bool = False,
        announce: bool = True,
    ) -> None:
        """Starts a source for `environment` of `batch` and announces it to the renderer.

        Args:
            batch: The batch, which `watch` or `CUJU_RENDER` gives the source as an observer.
            environment: The environment to show.
            title: The title, by default the scenario, the environment and the process.
            teams: The names and colors of the left and right team, as for a recording.
            scenario: The name of the scenario, for the title and the list of sources, by default
                the batch's.
            backlog: Whether to read every step, watched or not, so that any viewer starts with
                ten seconds of history, at the cost of one state read per step.
            announce: Whether the source joins the renderer's list of live sources. A game that a
                person plays streams through the server alone, so it stays off the list.
        """
        self._batch = weakref.ref(batch)
        self.environment = int(environment)
        self.environment_count = int(batch.environment_count)
        # The environment that a viewer chose, which the source shows after the next step.
        self._pending_environment: int | None = None
        players = int(batch.left_players[self.environment] + batch.right_players[self.environment])
        self._reader = _recording.StateReader(players)
        self._scenario = scenario or scenario_name(batch)
        # A title of the caller stays through a switch, the default one names the environment.
        self._title = title
        self.title = title or self._default_title()
        self._teams = teams
        # The scenario's timing comes with the first state read, since a batch may announce its
        # source before its first reset.
        self._timing: dict[str, Any] | None = None
        self._backlog = backlog
        self._history: collections.deque[bytes] = collections.deque(maxlen=_HISTORY)
        # The serial of each frame of the history, and the serial of the next frame.
        self._serials: collections.deque[int] = collections.deque(maxlen=_HISTORY)
        self._sequence = 0
        self._generation = 0
        # The annotations of the frames of the history, by serial and player, and those that the
        # viewers have not received yet.
        self._notes: dict[tuple[int, int], dict[str, Any]] = {}
        self._fresh: dict[tuple[int, int], dict[str, Any]] = {}
        self._lineup: list[dict[str, Any]] | None = None
        self._viewers: list[_Viewer] = []
        self._lock = threading.Lock()
        self._passage = 0
        self._passage_start = 0.0
        # Small views of many environments, read only while a viewer asks for them.
        self._grid = _grid.Grid(self.environment_count)
        self.identifier = _home.new_identifier('live')
        self._server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), self._handler())
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._closed = False
        self._thread.start()
        self._announcement = _home.folder('live') / f'{self.identifier}.json'
        self._announce = announce
        if announce:
            self._write_announcement()
        atexit.register(self.close)

    def _default_title(self) -> str:
        """Returns the title that names the scenario, the environment and the process."""
        return f'{self._scenario}, environment {self.environment}, process {os.getpid()}'

    def _write_announcement(self) -> None:
        """Writes the small file through which the server lists the source.

        The file is written beside its place and moved there, so the server never reads half of it.
        """
        temporary = self._announcement.with_suffix('.part')
        try:
            temporary.write_text(
                json.dumps(
                    {
                        'id': self.identifier,
                        'title': self.title,
                        'scenario': self._scenario,
                        'environment': self.environment,
                        'environment_count': self.environment_count,
                        'generation': self._generation,
                        'port': self.port,
                        'pid': os.getpid(),
                    }
                )
            )
            temporary.replace(self._announcement)
        except OSError:
            with contextlib.suppress(OSError):
                temporary.unlink()
            raise

    def _handler(self) -> type[http.server.BaseHTTPRequestHandler]:
        """Returns the request handler class, bound to this source."""
        source = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *arguments: Any) -> None:
                pass

            def do_POST(self) -> None:
                # The server relays a switch without an origin, a page of any site sends one.
                host = urllib.parse.urlsplit('//' + (self.headers.get('Host') or '')).hostname
                if (
                    host not in _LOOPBACK
                    or self.headers.get('Origin') is not None
                    or self.headers.get('Content-Type') != 'application/json'
                ):
                    self.send_error(403)
                    return
                if self.path != '/environment':
                    self.send_error(404)
                    return
                try:
                    length = int(self.headers.get('Content-Length') or 0)
                    if not 0 < length <= 1024:
                        raise ArgumentError('expected a request body of at most 1024 bytes')
                    document = json.loads(self.rfile.read(length))
                    if not isinstance(document, dict):
                        raise ArgumentError('expected a JSON object')
                    source.select_environment(document.get('environment'))
                except ValueError as error:
                    self.send_error(400, str(error))
                    return
                self.send_response(202)
                self.send_header('Content-Length', '0')
                self.end_headers()

            def do_GET(self) -> None:
                # The same guard as the server's, against pages of other sites that resolve here.
                host = urllib.parse.urlsplit('//' + (self.headers.get('Host') or '')).hostname
                if host not in _LOOPBACK:
                    self.send_error(403)
                    return
                route = urllib.parse.urlsplit(self.path)
                if route.path == '/grid':
                    _grid.respond(self, source._grid, route.query)
                    return
                if route.path != '/stream':
                    self.send_error(404)
                    return
                query = urllib.parse.parse_qs(route.query)
                viewer = _Viewer(query.get('sequence') == ['1'], query.get('annotations') == ['1'])
                # The history and the registration share the lock, so no step is sent twice.
                with source._lock:
                    history = list(source._history)
                    if viewer.sequence:
                        history = [
                            _SERIAL.pack(serial) + frame
                            for serial, frame in zip(source._serials, history, strict=True)
                        ]
                    if viewer.annotations and source._notes:
                        history.append(_notes_payload(source._notes.values()))
                    if source._lineup is not None:
                        viewer.header = source._header(viewer.sequence, viewer.annotations)
                    if source._closed:
                        return
                    source._viewers.append(viewer)
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    if viewer.header is not None:
                        self.wfile.write(viewer.header + b''.join(history))
                        self.wfile.flush()
                    while True:
                        frame = viewer.frames.get()
                        if frame is None:
                            # A numbered stream ends with its marker, so the viewer can tell the
                            # end from a lost connection.
                            if viewer.sequence:
                                self.wfile.write(_SERIAL.pack(END))
                                self.wfile.flush()
                            break
                        self.wfile.write(frame)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                finally:
                    with source._lock:
                        if viewer in source._viewers:
                            source._viewers.remove(viewer)

        return Handler

    def _header(self, sequence: bool = False, annotations: bool = False) -> bytes:
        """Returns the header of a stream, once a state has given the lineup.

        Args:
            sequence: Whether the stream numbers its frames, which the header then announces with
                the identifier of the stream that the numbers count.
            annotations: Whether the stream carries annotations, which the header announces.
        """
        fields = dict(self._timing or {})
        fields['environment_count'] = self.environment_count
        if sequence:
            fields['stream_sequence'] = 1
            fields['stream_id'] = f'{self.identifier}:{self._generation}'
        if sequence and annotations:
            fields['stream_annotations'] = 1
        return _recording.header(
            self.title,
            self._scenario,
            self._lineup,
            self._teams,
            timing=fields,
            provenance={'source': 'live', 'environment': self.environment},
        )

    def _paced(self) -> bool:
        """Returns whether this step belongs to a passage that a viewer receives."""
        now = time.monotonic()
        if self._passage >= _PASSAGE:
            if now < self._passage_start + _PASSAGE / _STEPS_PER_SECOND:
                return False
            self._passage = 0
        if self._passage == 0:
            self._passage_start = now
        self._passage += 1
        return True

    def __call__(self, batch: Any, done: Any, information: dict[str, Any]) -> None:
        """Captures a step as a step observer of the batch, and closes with the batch.

        A failure closes the source and raises, so the batch removes it with one warning and
        steps on.
        """
        if done is None:
            if information.get('close'):
                self.close()
            return
        try:
            self.after_step(done)
        except Exception:
            self.close()
            raise

    def after_step(self, done: Any) -> None:
        """Captures the environment's frame for every viewer with room in its queue.

        Args:
            done: The done flags of the step.
        """
        with self._lock:
            if self._pending_environment is not None:
                self._switch()
            viewers = [viewer for viewer in self._viewers if not viewer.frames.full()]
        if self._grid.watched:
            batch = self._batch()
            if batch is not None:
                self._grid.step(batch)
        if viewers and not self._paced():
            viewers = []
        if not viewers and not self._backlog:
            return
        batch = self._batch()
        if batch is None:
            return
        state = batch.get_state(self.environment, stacked=batch.stacked)
        frame = self._reader.frame(state, _end_flags(batch, done, self.environment))
        with self._lock:
            if self._lineup is None:
                self._lineup = self._reader.lineup(state)
            if self._timing is None:
                self._timing = _recording.scenario_timing(state)
        self._deliver(frame, viewers)

    def _switch(self) -> None:
        """Shows the pending environment from this step on, with the lock held.

        The switch changes which environment the source reads and nothing of the batch. The
        streams of the last environment end, and the next stream starts with a new header, its own
        history and its own serials. A failure to rewrite the announcement leaves the source
        running under its old entry, with one warning.
        """
        batch = self._batch()
        if batch is None:
            return
        self.environment, self._pending_environment = self._pending_environment, None
        if self._title is None:
            self.title = self._default_title()
        players = int(batch.left_players[self.environment] + batch.right_players[self.environment])
        self._reader = _recording.StateReader(players)
        self._lineup = self._timing = None
        self._history.clear()
        self._serials.clear()
        self._notes.clear()
        self._fresh.clear()
        self._sequence = 0
        self._passage = 0
        self._generation += 1
        # The announcement changes before the streams end, so a viewer that asks the server
        # straight after the end finds the new stream.
        if self._announce:
            try:
                self._write_announcement()
            except OSError as error:
                _LOGGER.warning(
                    'cuju render: the live source could not announce environment %d, %s: %s',
                    self.environment,
                    type(error).__name__,
                    error,
                )
        viewers, self._viewers = self._viewers, []
        for viewer in viewers:
            _end(viewer)

    def select_environment(self, environment: int) -> None:
        """Shows another environment of the batch from the end of its next step on.

        Every stream of the current environment ends then, and a viewer who connects again
        receives the new environment with a header of its own. A batch that is not stepping keeps
        the choice until its next step, and the last choice before that step wins.

        Args:
            environment: The index of the environment to show.

        Raises:
            ArgumentError: When the index is not a whole number of the batch, or the source is
                closed.
        """
        if (
            isinstance(environment, bool)
            or not isinstance(environment, int)
            or not 0 <= environment < self.environment_count
        ):
            raise ArgumentError(
                f'expected an environment from 0 to {self.environment_count - 1}, '
                f'found {environment!r}'
            )
        with self._lock:
            if self._closed:
                raise ArgumentError('expected an open live source, found a closed one')
            self._pending_environment = None if environment == self.environment else environment

    def annotate(
        self,
        values: dict[str, Any] | None = None,
        text: str | None = None,
        player: Any = None,
        step: int | None = None,
        probabilities: Any = None,
        action: Any = None,
    ) -> bool:
        """Attaches numbers or text to a frame that the source streamed, for its viewers.

        The arguments are those of `Recorder.annotate`. The annotation reaches the viewers with
        the next frame, and a viewer who joins later receives those of the frames of the history.
        Annotating reads nothing of the batch and changes nothing of it.

        Returns:
            Whether a frame took the annotation, which an unwatched source, holding no frame of the
            step, declines.

        Raises:
            ArgumentError: If a part of the annotation is invalid.
        """
        record = _annotations.note([], values, text, None, probabilities, action)
        with self._lock:
            lineup = self._lineup
            frames = list(zip(self._serials, self._history, strict=True))
        if lineup is None or not frames:
            return False
        if player is not None:
            record['p'] = _annotations.player_index(lineup, player)
        if step is None:
            serial = frames[-1][0]
        else:
            found = [
                serial for serial, frame in frames if struct.unpack_from('<i', frame)[0] == step
            ]
            if not found:
                return False
            serial = found[-1]
        with self._lock:
            if not self._serials or serial < self._serials[0]:
                return False
            merged = _annotations.merge(self._notes, serial, record)
            self._fresh[(serial, merged.get('p', -1))] = merged
        return True

    def push(self, frame: bytes, lineup: list[dict[str, Any]]) -> None:
        """Sends a frame that the caller read to every viewer at once, without pacing.

        A game that a person plays reads each frame for its recording and streams the same bytes,
        so the source reads no state of its own and the page receives every step as it happens.

        Args:
            frame: The frame, as `StateReader.frame` returns it.
            lineup: The header entry of each player, as `StateReader.lineup` returns it.
        """
        with self._lock:
            if self._lineup is None:
                self._lineup = lineup
            viewers = list(self._viewers)
        self._deliver(frame, viewers)

    def _deliver(self, frame: bytes, viewers: list[_Viewer]) -> None:
        """Adds a frame to the history and queues it for `viewers`, a header first for new ones."""
        with self._lock:
            # The history holds consecutive steps only, so a gap starts it again.
            if self._history:
                (last,) = struct.unpack_from('<i', self._history[-1])
                (step,) = struct.unpack_from('<i', frame)
                if step != last + 1:
                    self._history.clear()
                    self._serials.clear()
            if self._closed:
                return
            serial = self._sequence
            self._sequence += 1
            self._history.append(frame)
            self._serials.append(serial)
            # The annotations of frames that left the history go with them, and those that the
            # viewers have not received go before this frame.
            first = self._serials[0]
            if any(key[0] < first for key in self._notes):
                self._notes = {key: note for key, note in self._notes.items() if key[0] >= first}
            notes = _notes_payload(self._fresh.values()) if self._fresh else b''
            self._fresh.clear()
            for viewer in viewers:
                payload = _SERIAL.pack(serial) + frame if viewer.sequence else frame
                if viewer.annotations:
                    payload = notes + payload
                if viewer.header is None:
                    viewer.header = self._header(viewer.sequence, viewer.annotations)
                    payload = viewer.header + payload
                with contextlib.suppress(queue.Full):
                    viewer.frames.put_nowait(payload)

    def close(self) -> None:
        """Ends every stream, stops listening and withdraws the announcement."""
        if self._closed:
            return
        self._closed = True
        atexit.unregister(self.close)
        batch = self._batch()
        if batch is not None and any(
            observer is self for observer in getattr(batch, 'observers', ())
        ):
            batch.remove_observer(self)
        # The announcement goes first, so a viewer whose stream ends finds the source gone.
        with contextlib.suppress(OSError):
            self._announcement.unlink()
        with self._lock:
            viewers, self._viewers = self._viewers, []
        for viewer in viewers:
            _end(viewer)
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> LiveSource:
        return self

    def __exit__(self, *exception: object) -> None:
        """Closes the source, so that `with cuju.render.watch(batch):` withdraws it at the end."""
        self.close()


def _notes_payload(records: Any) -> bytes:
    """Returns a batch of annotations as a numbered stream carries it."""
    data = _annotations.encode(records)
    return _SERIAL.pack(NOTES) + _LENGTH.pack(len(data)) + data


def _end(viewer: _Viewer) -> None:
    """Ends the stream of a viewer, dropping the frames it has not received yet."""
    while True:
        try:
            viewer.frames.get_nowait()
        except queue.Empty:
            break
    viewer.frames.put_nowait(None)


def _end_flags(batch: Any, done: Any, environment: int) -> int:
    """Returns the flags of a frame for the done flags of its step.

    With automatic resets the step that ends an episode already shows the next kick-off, so its
    frame carries 2, an episode ended just before it, and otherwise the frame that ends one carries
    1.
    """
    if done is None or not bool(done[environment]):
        return 0
    return 2 if batch.auto_reset else 1


def from_environment(batch: Any) -> LiveSource | None:
    """Returns a source for `batch` when `CUJU_RENDER` asks for one, else `None`.

    `CUJU_RENDER` holds `on` for environment 0, or the index of the environment to show, and an
    empty value or `off` leaves the batch without a source. A non-empty `CUJU_RENDER_BACKLOG` other
    than `0` or `off` makes the source read every step, so that any viewer starts with a history.
    The caller adds the source to the batch's observers.

    Args:
        batch: The batch.
    """
    value = os.environ.get(LIVE_VARIABLE, '').strip().lower()
    if value in ('', 'off', 'false', 'no'):
        return None
    environment = int(value) if value.isdigit() else 0
    if not 0 <= environment < batch.environment_count:
        environment = 0
    backlog = os.environ.get(BACKLOG_VARIABLE, '').strip().lower() not in ('', '0', 'off', 'no')
    return LiveSource(batch, environment, scenario=scenario_name(batch), backlog=backlog)


def scenario_name(batch: Any) -> str:
    """Returns the scenarios a batch was created with, as `scenario_name` names them, or `match`."""
    return getattr(batch, 'scenario_name', None) or 'match'
