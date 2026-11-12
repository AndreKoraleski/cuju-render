# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""Runs one team's policy in a process of its own, for a match under strict rules.

The match starts this file as a script, with Python's option `-I`, so the process imports the
team's folder first and the installed packages after it, and nothing of the renderer, of another
team or of the folder it started in. Two teams so never share a module, even modules of the same
name. The variables of the usual libraries limit the process to the threads that the rules give,
and torch, once the team imports it, takes the same limit. This is isolation for fairness, so that
every team plays on the same terms, not a sandbox for code that one cannot trust.

The process loads the team's `main.py` as Kaggle does and takes its last callable as the agent. A
callable named `reset` that is not the agent is the team's reset, which the match calls before its
first observation. The process then answers one request at a time, each a line of JSON on a copy
of its standard input, with one line of JSON on a copy of its standard output. Before the team's
code runs, its standard input reads as empty and its standard output goes to standard error, which
the match writes to the team's log, so no team reads the requests or forges an answer. The
working folder is a private temporary folder that the match removes afterwards, so a team reads
its own files by their path, beside its `main.py`. The protocol is JSON alone in both directions,
and each side reads its pipe on a thread of its own, which works alike on every system.

- At its start it waits for `{"start": true}`, which the match sends once the process stands
  under its limits, and then answers `{"ready": true}` once the agent loads, or the error.
- `{"reset": true}` calls the team's reset and answers `{"reset": true}`.
- `{"obs": ...}` calls the agent with the observation and answers `{"answer": ..., "compute": s}`,
  the answer as JSON and the seconds that the call took.
- An error answers `{"error": text, "stage": stage}`, the stage being `load`, `reset`, `call` or
  `answer`, the last for an answer that is no JSON, or `memory` for memory that ran out and
  `process` for a process that the team tried to start, which the rules refuse.
"""

import contextlib
import inspect
import json
import os
import sys
import threading
import time
import traceback
import types

# The variables that set the threads of the usual libraries of numbers.
THREAD_VARIABLES = (
    'OMP_NUM_THREADS',
    'MKL_NUM_THREADS',
    'OPENBLAS_NUM_THREADS',
    'NUMEXPR_NUM_THREADS',
    'VECLIB_MAXIMUM_THREADS',
    'BLIS_NUM_THREADS',
)
_MAIN = 'main.py'


class _Struct(dict):
    """A dictionary whose keys are also attributes, as Kaggle's observations are."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


def _takes_configuration(function):
    """Returns whether Kaggle would pass the configuration to an agent, as a second argument."""
    try:
        parameters = inspect.signature(function).parameters.values()
    except (TypeError, ValueError):
        return False
    positional = [
        parameter
        for parameter in parameters
        if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
    ]
    return len(positional) >= 2 or any(
        parameter.kind == parameter.VAR_POSITIONAL for parameter in parameters
    )


def _plain(value):
    """Returns an answer as JSON values, an array or an enum as Kaggle's helpers make them."""
    if hasattr(value, 'tolist') and callable(value.tolist):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if not isinstance(value, (int, float, str, bool)) and value is not None:
        found = getattr(value, 'value', None)
        if isinstance(found, int):
            return found
    return value


def _limit_torch(threads):
    """Gives torch the limit of threads, once the team has imported it."""
    torch = sys.modules.get('torch')
    if torch is None:
        return
    with contextlib.suppress(Exception):
        torch.set_num_threads(threads)
    with contextlib.suppress(Exception):
        torch.set_num_interop_threads(threads)


def _reason(error):
    return f'{type(error).__name__}: {error}'


# The audit events of Python that start another process, which strict rules refuse a team.
_PROCESS_EVENTS = frozenset(
    {
        'subprocess.Popen',
        'os.system',
        'os.posix_spawn',
        'os.fork',
        'os.forkpty',
        'os.exec',
        'os.spawn',
        'os.startfile',
        'pty.spawn',
        '_winapi.CreateProcess',
    }
)


def _refuse_processes(answer):
    """Ends the process with its reason when the team starts another, by an audit hook."""

    def hook(event, arguments):
        if event in _PROCESS_EVENTS:
            with contextlib.suppress(Exception):
                answer(error=f'the team started another process, {event}', stage='process')
            os._exit(1)

    sys.addaudithook(hook)


def _stage(error, stage):
    """Returns the stage of an error, `memory` for memory that ran out whatever the stage."""
    return 'memory' if isinstance(error, MemoryError) else stage


def _watch(parent):
    """Ends this process once the match that started it ends, even while the team computes."""
    if os.name == 'nt':
        import ctypes

        kernel = ctypes.windll.kernel32
        # SYNCHRONIZE, which lets the wait below see the parent end.
        handle = kernel.OpenProcess(0x00100000, False, parent)
        if not handle:
            os._exit(1)
        kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
        os._exit(1)
    while os.getppid() == parent:
        time.sleep(0.5)
    os._exit(1)


def main():
    folder = os.path.abspath(sys.argv[1])
    threads = int(sys.argv[2])
    threading.Thread(target=_watch, args=(os.getppid(),), daemon=True).start()
    # The requests and the answers keep copies of standard input and output, and the team's own
    # standard input then reads as empty while its prints go to standard error.
    sys.stdout.flush()
    channel = os.fdopen(os.dup(1), 'w', encoding='utf-8')
    requests = os.fdopen(os.dup(0), 'r', encoding='utf-8')
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    empty = os.open(os.devnull, os.O_RDONLY)
    os.dup2(empty, 0)
    os.close(empty)
    sys.stdin = open(os.devnull, encoding='utf-8')

    def answer(**entries):
        channel.write(json.dumps(entries) + '\n')
        channel.flush()

    # The match holds the process to its limits before any of the team's code runs.
    for line in requests:
        with contextlib.suppress(ValueError):
            if json.loads(line).get('start'):
                break
    else:
        return
    sys.path.insert(0, folder)
    module = types.ModuleType('main')
    module.__file__ = os.path.join(folder, _MAIN)
    try:
        with open(module.__file__, 'rb') as stream:
            source = stream.read()
        # Kaggle: `get_last_callable` runs the file and takes the last callable it defined.
        exec(compile(source, module.__file__, 'exec'), module.__dict__)
        callables = [value for value in module.__dict__.values() if callable(value)]
        if not callables:
            raise LookupError('main.py defines no function')
        agent = callables[-1]
        reset = module.__dict__.get('reset')
        if not callable(reset) or reset is agent:
            reset = None
        two = _takes_configuration(agent)
    except BaseException as error:
        traceback.print_exc()
        answer(error=_reason(error), stage=_stage(error, 'load'))
        return
    _limit_torch(threads)
    # Libraries may run a short helper process while they load, as Python's ctypes does to find a
    # library on Linux, so the refusal starts once the team has loaded.
    _refuse_processes(answer)
    configuration = _Struct()
    answer(ready=True)
    for line in requests:
        try:
            request = json.loads(line)
        except ValueError:
            continue
        if not isinstance(request, dict) or request.get('end'):
            break
        if request.get('reset'):
            try:
                if reset is not None:
                    reset()
            except BaseException as error:
                traceback.print_exc()
                answer(error=_reason(error), stage=_stage(error, 'reset'))
                return
            _limit_torch(threads)
            answer(reset=True)
            continue
        obs = _Struct(request.get('obs') or {})
        started = time.perf_counter()
        try:
            value = agent(obs, configuration) if two else agent(obs)
        except BaseException as error:
            traceback.print_exc()
            answer(error=_reason(error), stage=_stage(error, 'call'))
            return
        compute = time.perf_counter() - started
        try:
            text = json.dumps({'answer': _plain(value), 'compute': compute})
        except (TypeError, ValueError) as error:
            answer(error=f'the answer {value!r:.200} is no action, {error}', stage='answer')
            return
        channel.write(text + '\n')
        channel.flush()


if __name__ == '__main__':
    main()
