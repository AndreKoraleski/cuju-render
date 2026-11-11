# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""Benchmarks of models, registered teams that play the chosen challenges headless as one job.

A benchmark plays every pair of a model and a challenge as a full headless run, in a child process
of its own, `python -m cuju.render._playing.challenges`, the very process that Run headless plays.
Each run therefore keeps the challenge's rules, seeds, abilities and scoring, scores exactly as a
person's run of the same challenge, and reaches the challenge's leaderboard as any full run does,
and no model's run shares a process with another. A policy that fails ends its attempt alone,
which counts as failed, and a run that cannot play at all leaves its cell failed, so the job always
goes on to the next pair.

The results form a table of models by challenges, each cell with its value and medal, and each
model with its totals, the medals it won and its score. The score is the mean over the challenges
of the benchmark of the share of the gold target that a model's value reached, from 0 to 1 and 0
for a cell without a result, times 100 and rounded to one decimal, so 100 means gold everywhere.
Models place by score, then by gold, silver and bronze medals, and models level on all four share
a place. `csv_text` writes the table as CSV, which the page writes the same way.

The server keeps its benchmarks in memory, the newest 20 ended ones with every waiting or running
one, plays one benchmark at a time, and within it plays several runs at once, `workers` of them,
one for every four logical processors of the machine by default, from 1 to 4.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from cuju.errors import ArgumentError

from .._registry import teams as _teams
from .._store import home as _home
from .._text import messages as _messages
from .._text.messages import MessageError
from . import challenges as _challenges

# A benchmark plays at most this many runs at once.
MOST_WORKERS = 8
# The server keeps this many ended benchmarks in its list.
_KEPT = 20
# The states of a cell. A skipped cell names a pair that cannot play, such as a team of another
# format than its challenge's scenario.
CELL_STATES = ('queued', 'running', 'done', 'failed', 'skipped', 'cancelled')


def default_workers() -> int:
    """Returns the runs a benchmark plays at once by default, one for every four processors."""
    return max(1, min(4, (os.cpu_count() or 1) // 4))


def _team_ids(value: Any) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) for item in value)
        or len(set(value)) != len(value)
    ):
        raise MessageError('server.bench.teams', teams=repr(value))
    return list(value)


def _challenge_ids(value: Any) -> list[str]:
    if value is None:
        return [entry['id'] for entry in _challenges.CATALOG]
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) for item in value)
        or len(set(value)) != len(value)
    ):
        raise MessageError('server.bench.challenges', challenges=repr(value))
    for identifier in value:
        _challenges.find(identifier)
    # The table lists the challenges in the order of the catalog, whatever the order asked.
    return [entry['id'] for entry in _challenges.CATALOG if entry['id'] in value]


def _workers(value: Any) -> int:
    if value is None:
        return default_workers()
    if not _challenges._whole(value) or not 1 <= value <= MOST_WORKERS:
        raise MessageError('server.bench.workers', most=MOST_WORKERS, workers=repr(value))
    return value


def plan(
    teams: Any,
    challenges: Any = None,
    keep_recordings: Any = False,
    workers: Any = None,
    device: str = 'cpu',
) -> dict[str, Any]:
    """Returns a new benchmark, its models, challenges and a queued cell for every pair.

    Args:
        teams: The models, a list of distinct team identifiers of the registry, `builtin` among
            them if wanted.
        challenges: The challenges, a list of distinct identifiers, or `None` for every one.
        keep_recordings: Whether the library keeps the attempts as recordings, false by default.
        workers: The runs played at once, from 1 to 8, or `None` for `default_workers`.
        device: `cpu` or `cuda`.

    Raises:
        ArgumentError: If a team, a challenge, the keeping or the workers do not fit.
    """
    identifiers = _team_ids(teams)
    chosen = _challenge_ids(challenges)
    keep = _challenges._keep_flag(keep_recordings)
    count = _workers(workers)
    builtin = _teams.entry(_teams.BUILTIN)
    models, cells = [], []
    for identifier in identifiers:
        entry = _teams.entry(identifier)
        models.append({'team': identifier, **_messages.named('name', _teams.shown_name(entry))})
        for challenge in chosen:
            spec = _challenges.find(challenge)
            cell = _cell(identifier, spec)
            try:
                _teams.check_scenario([entry, builtin], spec['scenario'])
            except ArgumentError as error:
                cell.update(state='skipped', **_messages.entry_fields(error))
            cells.append(cell)
    document = {
        'teams': identifiers,
        'challenges': chosen,
        'models': models,
        'cells': cells,
        'keep_recordings': keep,
        'workers': count,
        'device': device,
    }
    document['rows'] = table(document)
    document['progress'] = progress(document)
    return document


def _cell(team: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {
        'team': team,
        'challenge': spec['id'],
        'state': 'queued',
        'attempts': spec['attempts'],
        'played': 0,
        'value': None,
        'seconds': None,
        'medal': None,
        'failed_attempts': 0,
        'rank': None,
        'group': None,
        'results': [],
        **_messages.entry_fields(None),
    }


def share(spec: dict[str, Any], cell: dict[str, Any]) -> float:
    """Returns the share of the gold target that a cell's value reached, from 0 to 1."""
    if cell['state'] != 'done' or not _challenges._number(cell['value']):
        return 0.0
    gold = spec['targets'][_challenges.MEDALS.index('gold')]
    return min(1.0, max(0.0, cell['value'] / gold))


def table(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Returns the row of each model, its medals, score and place, in the order of the models.

    The score is 100 times the mean share of the gold targets over the benchmark's challenges,
    rounded to one decimal, and the place counts the models ahead by score and then by gold,
    silver and bronze medals, so models level on all four share a place.
    """
    specs = {identifier: _challenges.find(identifier) for identifier in document['challenges']}
    rows = []
    for model in document['models']:
        cells = [cell for cell in document['cells'] if cell['team'] == model['team']]
        won = [cell['medal'] for cell in cells if cell['state'] == 'done' and cell['medal']]
        shares = [share(specs[cell['challenge']], cell) for cell in cells]
        score = round(100 * sum(shares) / len(specs), 1) if specs else 0.0
        rows.append(
            {
                **model,
                'gold': won.count('gold'),
                'silver': won.count('silver'),
                'bronze': won.count('bronze'),
                'score': score,
                'done': sum(cell['state'] == 'done' for cell in cells),
                'place': None,
            }
        )

    def standing(row: dict[str, Any]) -> tuple[float, int, int, int]:
        return (row['score'], row['gold'], row['silver'], row['bronze'])

    for row in rows:
        row['place'] = 1 + sum(standing(other) > standing(row) for other in rows)
    return rows


def progress(document: dict[str, Any]) -> float:
    """Returns the share of the attempts played over the cells that play, from 0 to 1."""
    playing = [cell for cell in document['cells'] if cell['state'] != 'skipped']
    total = sum(cell['attempts'] for cell in playing)
    if not total:
        return 1.0
    played = sum(
        cell['attempts'] if cell['state'] in ('done', 'failed') else cell['played']
        for cell in playing
    )
    return round(played / total, 4)


def csv_text(document: dict[str, Any]) -> str:
    """Returns the table of a benchmark as CSV, one row for each model.

    The columns are the model's name and team, the value and medal of each challenge, empty for a
    cell without a result, and the model's gold, silver and bronze medals, score and place.
    """
    output = io.StringIO()
    writer = csv.writer(output, lineterminator='\n')
    header = ['model', 'team']
    for identifier in document['challenges']:
        header += [f'{identifier} value', f'{identifier} medal']
    writer.writerow([*header, 'gold', 'silver', 'bronze', 'score', 'place'])
    cells = {(cell['team'], cell['challenge']): cell for cell in document['cells']}
    for row in document['rows']:
        line = [row['name'], row['team']]
        for identifier in document['challenges']:
            cell = cells[(row['team'], identifier)]
            done = cell['state'] == 'done'
            line += ['' if not done else str(cell['value']), (done and cell['medal']) or '']
        writer.writerow(
            [*line, row['gold'], row['silver'], row['bronze'], f'{row["score"]:.1f}', row['place']]
        )
    return output.getvalue()


class CellError(Exception):
    """Raised for a run of a benchmark that ended without a result, with its error fields."""

    def __init__(self, fields: dict[str, Any]) -> None:
        super().__init__(fields.get('error'))
        self.fields = fields


def play_cell(
    document: dict[str, Any],
    cell: dict[str, Any],
    attempt: Callable[[dict[str, Any]], None],
    started: Callable[[subprocess.Popen], None] | None = None,
) -> dict[str, Any]:
    """Plays one cell of a benchmark in a child process and returns the result of its run.

    Raises:
        CellError: If the run ended without a result.
    """
    command = _challenges.child_command(
        cell['challenge'], cell['team'], None, document['keep_recordings'], document['device']
    )
    found: dict[str, Any] = {}

    def report(line: dict[str, Any]) -> None:
        if isinstance(line.get('attempt'), dict):
            attempt(line['attempt'])
        if isinstance(line.get('result'), dict):
            found['result'] = line['result']
        if isinstance(line.get('error'), str):
            found['error'] = _messages.report_fields(line)

    code, tail = _challenges.play_child(command, report, started)
    if code == 0 and 'result' in found:
        return found['result']
    raise CellError(
        found.get('error') or _messages.exit_fields('server.challenges.exit', code, tail)
    )


def run(
    document: dict[str, Any],
    play: Callable[..., dict[str, Any]] = play_cell,
    changed: Callable[[dict[str, Any] | None], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    started: Callable[[subprocess.Popen], None] | None = None,
    lock: Any = None,
) -> dict[str, Any]:
    """Plays every queued cell of a benchmark, `workers` at a time, and returns the benchmark.

    Each cell takes its value, seconds, medal, rank, failed attempts and the results of its
    attempts from its run, and a run without a result leaves its cell failed with the error.

    Args:
        document: The benchmark, as `plan` returns it, which the function fills in.
        play: The function that plays a cell, as `play_cell` does, by default `play_cell`.
        changed: A function called with the cell after each attempt and each end of a cell.
        cancelled: A function that says whether the benchmark should stop, after which no cell
            starts.
        started: A function called with each child process once it has started.
        lock: The lock that guards the document, a new one by default.
    """
    lock = lock or threading.Lock()

    def attempt_of(cell: dict[str, Any]) -> Callable[[dict[str, Any]], None]:
        def seen(result: dict[str, Any]) -> None:
            with lock:
                cell['results'] = [*cell['results'], result]
                cell['played'] = len(cell['results'])
                document['progress'] = progress(document)
            if changed is not None:
                changed(cell)

        return seen

    def worker() -> None:
        while True:
            with lock:
                if cancelled is not None and cancelled():
                    return
                cell = next((item for item in document['cells'] if item['state'] == 'queued'), None)
                if cell is None:
                    return
                cell['state'] = 'running'
            try:
                result = play(document, cell, attempt_of(cell), started)
                ended = {
                    'state': 'done',
                    'value': result['value'],
                    'seconds': result['seconds'],
                    'medal': result['medal'],
                    'rank': result.get('rank'),
                    'group': result.get('group'),
                    'failed_attempts': result.get('failed_attempts', 0),
                    'results': list(result['attempts']),
                    'played': len(result['attempts']),
                }
            except CellError as failure:
                ended = {'state': 'failed', **_messages.entry_fields(None), **failure.fields}
            except Exception as error:
                ended = {'state': 'failed', **_messages.entry_fields(error, str(error))}
            with lock:
                if cell['state'] == 'running':
                    cell.update(ended)
                document['rows'] = table(document)
                document['progress'] = progress(document)
            if changed is not None:
                changed(cell)

    threads = [
        threading.Thread(target=worker, daemon=True, name=f'cuju-bench-{number}')
        for number in range(document['workers'])
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    with lock:
        document['rows'] = table(document)
        document['progress'] = progress(document)
    return document


# The benchmarks of the server, played one at a time.


class _Benches:
    """The benchmarks of the page and of agents, queued and played one at a time."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: list[dict[str, Any]] = []
        self._processes: dict[str, set[subprocess.Popen]] = {}
        self._wake = threading.Event()
        threading.Thread(target=self._run, daemon=True, name='cuju-benches').start()

    def add(self, document: dict[str, Any]) -> dict[str, Any]:
        """Queues a benchmark of `plan` and returns its entry."""
        job = {
            'id': _home.new_identifier('b'),
            'state': 'queued',
            **document,
            **_messages.entry_fields(None),
            'created': time.time(),
            'ended': None,
        }
        with self._lock:
            self._entries.append(job)
            ended = [item for item in self._entries if item['state'] in ('done', 'failed')]
            for item in ended[: max(0, len(ended) - _KEPT)]:
                self._entries.remove(item)
            copied = copy.deepcopy(job)
        self._wake.set()
        return copied

    def entries(self) -> list[dict[str, Any]]:
        """Returns a copy of every benchmark, newest first."""
        with self._lock:
            return [copy.deepcopy(job) for job in reversed(self._entries)]

    def get(self, identifier: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._find(identifier)
            return None if job is None else copy.deepcopy(job)

    def _find(self, identifier: str) -> dict[str, Any] | None:
        return next((item for item in self._entries if item['id'] == identifier), None)

    def cancel(self, identifier: str) -> bool:
        """Cancels a waiting or running benchmark, and returns whether there was one."""
        with self._lock:
            job = self._find(identifier)
            if job is None or job['state'] not in ('queued', 'running'):
                return False
            job.update(
                state='failed', ended=time.time(), **_messages.fields('server.requests.cancelled')
            )
            for cell in job['cells']:
                if cell['state'] in ('queued', 'running'):
                    cell['state'] = 'cancelled'
            job['rows'] = table(job)
            processes = list(self._processes.get(identifier, ()))
        for process in processes:
            process.kill()
        return True

    def _run(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            while True:
                with self._lock:
                    job = next((item for item in self._entries if item['state'] == 'queued'), None)
                    if job is not None:
                        job['state'] = 'running'
                        self._processes[job['id']] = set()
                if job is None:
                    break
                self._play(job)

    def _play(self, job: dict[str, Any]) -> None:
        identifier = job['id']

        def started(process: subprocess.Popen) -> None:
            with self._lock:
                self._processes[identifier].add(process)
                stopped = job['state'] != 'running'
            if stopped:
                process.kill()

        try:
            run(
                job,
                cancelled=lambda: job['state'] != 'running',
                started=started,
                lock=self._lock,
            )
        except Exception as error:
            with self._lock:
                job.update(
                    state='failed', **_messages.entry_fields(error, _messages.described(error))
                )
        finally:
            with self._lock:
                self._processes.pop(identifier, None)
                if job['state'] == 'running':
                    job.update(state='done', ended=time.time())


_BENCHES: _Benches | None = None
_BENCHES_LOCK = threading.Lock()


def benches() -> _Benches:
    """Returns the server's queue of benchmarks, started on first use."""
    global _BENCHES
    with _BENCHES_LOCK:
        if _BENCHES is None:
            _BENCHES = _Benches()
        return _BENCHES


# The routes of the server under /api/challenges/benches.

_FIELDS = {'teams', 'challenges', 'keep_recordings', 'workers'}


def get(parts: list[str]) -> tuple[Any, int]:
    """Answers `GET /api/challenges/benches` and `GET /api/challenges/benches/<bench>`."""
    if not parts:
        return benches().entries(), 200
    job = benches().get(parts[0]) if len(parts) == 1 else None
    if job is None:
        return _messages.fields('server.bench.no_bench'), 404
    return job, 200


def post(document: dict[str, Any]) -> tuple[Any, int]:
    """Answers `POST /api/challenges/benches`, which queues a benchmark of `plan`."""
    unknown = set(document) - _FIELDS
    if unknown or 'teams' not in document:
        raise MessageError('server.bench.fields', unknown=repr(sorted(unknown)))
    queued = plan(
        document['teams'],
        document.get('challenges'),
        document.get('keep_recordings', False),
        document.get('workers'),
    )
    return benches().add(queued), 201


def delete(identifier: str) -> tuple[Any, int]:
    """Answers `DELETE /api/challenges/benches/<bench>`, which cancels a benchmark."""
    if benches().cancel(identifier):
        return {'cancelled': identifier}, 200
    return _messages.fields('server.bench.no_bench'), 404


def csv_of(identifier: str) -> str | None:
    """Returns the table of a benchmark of the server as CSV, or `None` for no such benchmark."""
    job = benches().get(identifier)
    return None if job is None else csv_text(job)


# The command line, `cuju render challenge bench`.


def _cell_line(document: dict[str, Any], cell: dict[str, Any]) -> str:
    name = next(model['name'] for model in document['models'] if model['team'] == cell['team'])
    spec = _challenges.find(cell['challenge'])
    if cell['state'] == 'done':
        failed = cell['failed_attempts']
        shown = f'{_value_text(spec, cell["value"])}, {cell["medal"] or "no medal"}'
        if failed:
            shown += f', {_messages.counted(failed, "failed attempt")}'
        return f'{name}, {cell["challenge"]}, {shown}'
    return f'{name}, {cell["challenge"]}, {cell["state"]}, {cell["error"]}'


def _value_text(spec: dict[str, Any], value: Any) -> str:
    if spec['measure'] == 'margin':
        return f'margin {value:+d}' if value else 'margin 0'
    return f'{value} of {spec["attempts"]}'


def command(options: Any) -> int:
    """Plays the benchmark that `cuju render challenge bench` names and prints its table.

    Each run plays in a child process as on the server, and its end prints one line on standard
    error. The table goes to standard output, as text, as JSON under `--json` or as CSV under
    `--csv`.
    """
    teams = options.team or []
    document = plan(
        teams,
        options.challenge or None,
        options.keep_recordings,
        options.workers,
        options.device,
    )
    processes: set[subprocess.Popen] = set()
    stop = threading.Event()

    def changed(cell: dict[str, Any] | None) -> None:
        if cell is not None and cell['state'] in ('done', 'failed'):
            print(_cell_line(document, cell), file=sys.stderr, flush=True)

    for cell in document['cells']:
        if cell['state'] == 'skipped':
            print(_cell_line(document, cell), file=sys.stderr, flush=True)
    worker = threading.Thread(
        target=run,
        kwargs={
            'document': document,
            'changed': changed,
            'cancelled': stop.is_set,
            'started': processes.add,
        },
        daemon=True,
    )
    worker.start()
    try:
        while worker.is_alive():
            worker.join(0.2)
    except KeyboardInterrupt:
        stop.set()
        for process in list(processes):
            process.kill()
        print('cuju render: the benchmark was cancelled', file=sys.stderr)
        return 130
    if options.json:
        print(json.dumps(document, indent=1))
    elif options.csv:
        print(csv_text(document), end='')
    else:
        for row in sorted(document['rows'], key=lambda item: item['place']):
            medals = f'gold {row["gold"]}, silver {row["silver"]}, bronze {row["bronze"]}'
            print(f'place {row["place"]}, {row["name"]}, score {row["score"]:.1f}, {medals}')
            for cell in document['cells']:
                if cell['team'] == row['team']:
                    print(f'    {_cell_line(document, cell).split(", ", 1)[1]}')
    return 0
