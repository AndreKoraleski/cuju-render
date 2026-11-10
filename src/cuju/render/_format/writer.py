# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The writer of recorders, one thread that codes and writes recordings while training steps on.

A recorder hands the frames of an ended episode over and returns at once, and the writer codes and
writes them in the order they came. The queue holds a few recordings, so a recorder that saves
faster than the writer keeps up waits for room. The process waits for the queue when it exits.
"""

from __future__ import annotations

import atexit
import queue
import threading
from collections.abc import Callable

# The recordings that wait for the writer, beyond which a save waits for room.
_ROOM = 4


class Writer:
    """Runs jobs one after another on a thread of its own, started at the first job."""

    def __init__(self, room: int = _ROOM) -> None:
        self._queue: queue.Queue[Callable[[], None]] = queue.Queue(room)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def submit(self, job: Callable[[], None]) -> None:
        """Queues a job, waiting for room when the queue is full. A job must not raise."""
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name='cuju-render-writer', daemon=True
                )
                self._thread.start()
        self._queue.put(job)

    def join(self) -> None:
        """Waits until every queued job has run."""
        self._queue.join()

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try:
                job()
            finally:
                self._queue.task_done()


WRITER = Writer()
atexit.register(WRITER.join)
