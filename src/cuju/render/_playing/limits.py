# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""Holds a team's process under strict rules to its limits of memory, threads and processes.

Each system enforces what it can, and the guard watches the rest four times a second.

- On Windows the process runs in a job object, which limits the memory that it commits, allows it
  no second process and ends it with the job, so the system itself refuses what goes beyond. The
  launcher of a virtual environment, which starts the interpreter as a process of its own, counts
  as the first process of the job and stays out of the count of threads. The guard counts the
  threads, and reads the job's peak of memory to name a forfeit.
- On Linux the process starts with a limit of its data segment, `RLIMIT_DATA`, which counts the
  memory it allocates and leaves alone the address space that PyTorch reserves without using it,
  which `RLIMIT_AS` would refuse. The guard reads its resident memory, its threads and its
  children from `/proc`.
- On macOS, whose limits of data the system does not hold allocations to, the guard reads the
  resident memory, the threads and the children of the process with `ps`.

The process itself also refuses to start another process once its team has loaded, by an audit
hook of Python, so the forfeit names the reason on every system, while the job object of Windows
stands behind it. While a team loads, Linux and macOS allow a short helper process, as Python's
ctypes runs one on Linux to find a library.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
from typing import Any

# The threads of a team's process beyond those the rules give it, for the interpreter's main
# thread, the thread that watches the match and those that the system and libraries keep, such
# as the few that PyTorch and the loader of Windows start whatever the limit of threads.
THREAD_ALLOWANCE = 10
# The seconds between two looks at a process.
_INTERVAL = 0.25
_MB = 1024 * 1024


def _launched() -> bool:
    """Returns whether Python starts through the launcher of a virtual environment on Windows.

    That launcher runs the interpreter as a process of its own beside it, which the job of a
    team's process then holds as well, and which the guard counts apart.
    """
    base = getattr(sys, '_base_executable', sys.executable)
    return os.name == 'nt' and os.path.normcase(base) != os.path.normcase(sys.executable)


class Guard:
    """Watches one team's process, and ends it once it breaks a limit.

    Args:
        memory_mb: The memory that the process may use, in megabytes.
        threads: The threads that the rules give the process, before the allowance.

    Attributes:
        broken: The limit that the process broke, `(kind, values)` with the kind `memory`,
            `threads` or `process`, or `None`.
        peak_mb: The most memory that the process was seen to use, in megabytes.
        enforced: What the system itself holds the process to, as the names of the limits.
    """

    def __init__(self, memory_mb: float, threads: int) -> None:
        self.memory = int(memory_mb * _MB)
        self.memory_mb = memory_mb
        self.threads = threads + THREAD_ALLOWANCE
        self.broken: tuple[str, dict[str, Any]] | None = None
        self.peak_mb = 0.0
        self.enforced: list[str] = []
        # Whether the process may have children, while its team loads, as libraries may run a
        # helper process to find their files. The match turns it off once the team has loaded.
        self.loading = True
        self._process: Any = None
        self._job: Any = None
        self._stop = threading.Event()

    def preexec(self) -> Any:
        """Returns what a process runs before Python starts on Linux and macOS, or `None`."""
        if os.name == 'nt':
            return None
        limit = self.memory

        def limited() -> None:
            import resource

            with contextlib.suppress(ValueError, OSError):
                resource.setrlimit(resource.RLIMIT_DATA, (limit, limit))

        if sys.platform.startswith('linux'):
            self.enforced.append('memory')
        return limited

    def attach(self, process: Any) -> None:
        """Puts a started process under the guard, in a job object on Windows."""
        self._process = process
        if os.name == 'nt':
            with contextlib.suppress(OSError, AttributeError):
                self._job = _Job(self.memory, int(process._handle), 2 if _launched() else 1)
                self.enforced += ['memory', 'process']
        threading.Thread(target=self._watch, daemon=True, name='cuju-strict-guard').start()

    def _break(self, kind: str, **values: Any) -> None:
        if self.broken is None:
            self.broken = (kind, values)
        with contextlib.suppress(OSError):
            self._process.kill()

    def _watch(self) -> None:
        pid = self._process.pid
        while not self._stop.wait(_INTERVAL) and self._process.poll() is None:
            try:
                memory, threads, children = _look(pid, self._job)
            except (OSError, ValueError, subprocess.SubprocessError):
                continue
            if memory is not None:
                self.peak_mb = max(self.peak_mb, memory / _MB)
                if memory > self.memory:
                    self._break('memory', used=f'{memory / _MB:.0f}', limit=f'{self.memory_mb:g}')
                    return
            if threads is not None and threads > self.threads:
                self._break('threads', found=str(threads), limit=str(self.threads))
                return
            if children and not self.loading:
                self._break('process')
                return

    def peak(self) -> float:
        """Returns the most memory that the process used, from the job object where it has one."""
        if self._job is not None:
            with contextlib.suppress(OSError):
                self.peak_mb = max(self.peak_mb, self._job.peak() / _MB)
        return self.peak_mb

    def close(self) -> None:
        """Stops watching and closes the job object, which ends what is left of the process."""
        self._stop.set()
        if self._job is not None:
            self.peak()
            self._job.close()
            self._job = None


def _look(pid: int, job: Any) -> tuple[int | None, int | None, int]:
    """Returns the resident memory in bytes, the threads and the children of a process."""
    if os.name == 'nt':
        if job is None:
            return None, _windows_threads({pid}), 0
        # The launcher of a virtual environment only waits for the interpreter, so its threads
        # stay out of the count.
        pids = set(job.pids()) - ({pid} if _launched() else set())
        return job.peak(), _windows_threads(pids), job.extra_processes()
    if sys.platform.startswith('linux'):
        status = {}
        with open(f'/proc/{pid}/status', encoding='ascii', errors='replace') as stream:
            for line in stream:
                name, _, value = line.partition(':')
                status[name] = value.split()
        memory = int(status['VmRSS'][0]) * 1024 if 'VmRSS' in status else None
        threads = int(status['Threads'][0]) if 'Threads' in status else None
        children = 0
        for task in os.listdir(f'/proc/{pid}/task'):
            with contextlib.suppress(OSError):
                with open(f'/proc/{pid}/task/{task}/children', encoding='ascii') as stream:
                    children += len(stream.read().split())
        return memory, threads, children
    # macOS and other systems read the process with ps, which every one of them ships.
    found = subprocess.run(
        ['ps', '-o', 'rss=', '-p', str(pid)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    ).stdout.split()
    memory = int(found[0]) * 1024 if found else None
    lines = subprocess.run(
        ['ps', '-M', '-p', str(pid)], capture_output=True, text=True, encoding='utf-8', check=False
    ).stdout.splitlines()
    threads = max(0, len(lines) - 1) or None
    table = subprocess.run(
        ['ps', '-A', '-o', 'ppid='], capture_output=True, text=True, encoding='utf-8', check=False
    ).stdout.split()
    return memory, threads, sum(1 for value in table if value == str(pid))


def _windows_threads(pids: set[int]) -> int | None:
    """Returns the threads of processes on Windows, from a snapshot of the system's threads."""
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = (
            ('size', wintypes.DWORD),
            ('usage', wintypes.DWORD),
            ('thread', wintypes.DWORD),
            ('owner', wintypes.DWORD),
            ('base', wintypes.LONG),
            ('delta', wintypes.LONG),
            ('flags', wintypes.DWORD),
        )

    kernel = ctypes.windll.kernel32
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel.CreateToolhelp32Snapshot(4, 0)
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return None
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(Entry)
        count = 0
        found = kernel.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.owner in pids:
                count += 1
            found = kernel.Thread32Next(snapshot, ctypes.byref(entry))
        return count
    finally:
        kernel.CloseHandle(snapshot)


class _Job:
    """A job object of Windows that limits one process's memory and allows it no other process."""

    # The limits of a job, the memory of each process, the processes at once and the end of
    # every process with the job.
    _PROCESS_MEMORY = 0x100
    _ACTIVE_PROCESS = 0x8
    _KILL_ON_CLOSE = 0x2000

    def __init__(self, memory: int, handle: int, processes: int = 1) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes

        class Basic(ctypes.Structure):
            _fields_ = (
                ('per_process_time', ctypes.c_int64),
                ('per_job_time', ctypes.c_int64),
                ('flags', wintypes.DWORD),
                ('minimum_working_set', ctypes.c_size_t),
                ('maximum_working_set', ctypes.c_size_t),
                ('active_processes', wintypes.DWORD),
                ('affinity', ctypes.c_size_t),
                ('priority', wintypes.DWORD),
                ('scheduling', wintypes.DWORD),
            )

        class Counters(ctypes.Structure):
            _fields_ = tuple((name, ctypes.c_uint64) for name in ('a', 'b', 'c', 'd', 'e', 'f'))

        class Extended(ctypes.Structure):
            _fields_ = (
                ('basic', Basic),
                ('io', Counters),
                ('process_memory', ctypes.c_size_t),
                ('job_memory', ctypes.c_size_t),
                ('peak_process_memory', ctypes.c_size_t),
                ('peak_job_memory', ctypes.c_size_t),
            )

        class Accounting(ctypes.Structure):
            _fields_ = (
                ('user', ctypes.c_int64),
                ('kernel', ctypes.c_int64),
                ('this_user', ctypes.c_int64),
                ('this_kernel', ctypes.c_int64),
                ('page_faults', wintypes.DWORD),
                ('total_processes', wintypes.DWORD),
                ('active_processes', wintypes.DWORD),
                ('terminated_processes', wintypes.DWORD),
            )

        self._extended, self._accounting = Extended, Accounting
        kernel = ctypes.windll.kernel32
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError('cannot make a job object')
        info = Extended()
        info.basic.flags = self._PROCESS_MEMORY | self._ACTIVE_PROCESS | self._KILL_ON_CLOSE
        info.basic.active_processes = processes
        self.processes = processes
        info.process_memory = memory
        if not kernel.SetInformationJobObject(
            wintypes.HANDLE(self.handle), 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            self.close()
            raise OSError('cannot limit a job object')
        if not kernel.AssignProcessToJobObject(
            wintypes.HANDLE(self.handle), wintypes.HANDLE(handle)
        ):
            self.close()
            raise OSError('cannot put the process in a job object')

    def peak(self) -> int:
        """Returns the most memory that the process has committed, in bytes."""
        ctypes = self._ctypes
        info = self._extended()
        self._kernel.QueryInformationJobObject(
            ctypes.c_void_p(self.handle), 9, ctypes.byref(info), ctypes.sizeof(info), None
        )
        return int(info.peak_process_memory)

    def extra_processes(self) -> int:
        """Returns the processes of the job beyond the team's own."""
        ctypes = self._ctypes
        info = self._accounting()
        self._kernel.QueryInformationJobObject(
            ctypes.c_void_p(self.handle), 1, ctypes.byref(info), ctypes.sizeof(info), None
        )
        return max(0, int(info.active_processes) - self.processes)

    def pids(self) -> list[int]:
        """Returns the processes of the job."""
        ctypes = self._ctypes

        class Listed(ctypes.Structure):
            _fields_ = (
                ('assigned', ctypes.c_uint32),
                ('listed', ctypes.c_uint32),
                ('ids', ctypes.c_size_t * 16),
            )

        info = Listed()
        self._kernel.QueryInformationJobObject(
            ctypes.c_void_p(self.handle), 3, ctypes.byref(info), ctypes.sizeof(info), None
        )
        return [int(info.ids[index]) for index in range(min(info.listed, 16))]

    def close(self) -> None:
        if self.handle:
            self._kernel.CloseHandle(self._ctypes.c_void_p(self.handle))
            self.handle = None
