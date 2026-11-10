# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The grid of a live source, small views of many environments of its batch at once.

A viewer asks the source for a range of environments, and the source answers at once with the
tiles it holds, each the score, the clock, the ball and the positions of the players of one
environment at the step it was read. The source reads states for the grid only while a viewer
asks, at most `_LINGER` seconds after the last request, and at the end of a step of the batch, as
the stream does. The reads are bounded four ways. No step reads more than `_PER_STEP` states, and
the grid reads at most `_RATE` states a second, the pace at which a watched stream reads its own.
A pass over the range starts at most once every `_PERIOD` seconds, so each tile is read at most
twice a second, and after each step that read, the grid waits until its reads amount to at most
`_SHARE` of the wall time. Reading a state leaves every output of the batch as it is.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
from typing import Any

import numpy as np

from cuju import state as _state

from .._format import recording as _recording

# The most environments that one request may ask for.
MAXIMUM = 64
# A grid that no viewer asked for within this many seconds stops reading.
_LINGER = 3.0
# A pass over the range starts at most once in this many seconds.
_PERIOD = 0.5
# The most states that one step of the batch reads for the grid.
_PER_STEP = 4
# The most states that the grid reads in a second of wall time, as many as a watched stream.
_RATE = 10.0
# The share of the wall time that the grid's reads may take, one twentieth.
_SHARE = 0.05


class TileReader:
    """Reads the tile of one environment out of its state, the fields a small view draws."""

    _HEAD = (
        ('reverse', 'environment.scenario.reverseTeamProcessing'),
        ('first', 'match.firstTeam'),
        ('left', 'environment.scenario.leftTeamSize'),
        ('right', 'environment.scenario.rightTeamSize'),
        ('step', 'environment.step'),
        ('goals_first', 'match.goalCount[0]'),
        ('goals_second', 'match.goalCount[1]'),
        ('in_set_piece', 'match.inSetPiece'),
        ('set_piece', 'match.referee.buffer.desiredSetPiece'),
        ('clock', 'match.matchTimeMilliseconds'),
        ('ball', 'match.ball.positionBuffer'),
    )

    def __init__(self, players: int) -> None:
        """Prepares the fields of matches with `players` players in all."""
        self.players = players
        fields, layout = [], []
        for name, path in self._HEAD:
            fields.append(_recording._field(path))
            layout.append((name, *_recording._dtype(fields[-1])))
        for player in range(players):
            prefix = f'match.players[{player}]'
            # The root node of the skeleton stands where the player stands.
            for name, path in (
                ('position', 'base.humanoid.nodes[0].position'),
                ('active', 'base.isActive'),
            ):
                fields.append(_recording._field(f'{prefix}.{path}'))
                layout.append((f'{name}{player}', *_recording._dtype(fields[-1])))
        self._fields = fields
        self._dtype = np.dtype(layout)

    def tile(self, state: bytes, environment: int) -> dict[str, Any]:
        """Returns the tile of a state, in the frame of the pitch as a recording's frames are.

        Args:
            state: A state of the match, as `get_state` returns it.
            environment: The index of the environment, which the tile names.
        """
        values = np.frombuffer(_state.gather(state, self._fields, 'pitch'), self._dtype, 1)[0]
        # GRF: the state lists the team processed first before the other, and its ID flips with
        # the reverse team processing.
        first = int(values['first']) ^ int(bool(values['reverse']))
        sizes = (int(values['left']), int(values['right']))
        order = [first] * sizes[first] + [1 - first] * sizes[1 - first]
        score = [0, 0]
        score[first], score[1 - first] = int(values['goals_first']), int(values['goals_second'])
        positions = []
        for player in range(self.players):
            x, y = values[f'position{player}'][:2].tolist()
            positions += [round(x, 2), round(y, 2)]
        return {
            'environment': environment,
            # GRF: the engine counts -1 after a reset and adds one per step.
            'step': int(values['step']) + 1,
            'score': score,
            'clock': int(values['clock']),
            'mode': int(values['set_piece']) if values['in_set_piece'] else 0,
            'ball': [round(value, 2) for value in values['ball'].tolist()],
            'teams': order[: self.players],
            'players': positions,
            'active': [int(bool(values[f'active{player}'])) for player in range(self.players)],
        }


def respond(handler: Any, grid: Grid, query: str) -> None:
    """Answers a request of the source's `/grid` with the tiles of the asked range, as JSON.

    The server relays the request without an origin and without a body, so a request with either
    comes from elsewhere and is refused, as the source refuses a switch from a page.

    Args:
        handler: The request handler of the source, whose host is already checked.
        grid: The grid of the source.
        query: The query of the request, with `first` and `count`.
    """
    length = handler.headers.get('Content-Length') or '0'
    if handler.headers.get('Origin') is not None or length != '0':
        handler.send_error(403)
        return
    fields = urllib.parse.parse_qs(query)
    try:
        first, count = (int(fields.get(name, ['x'])[0]) for name in ('first', 'count'))
        document = grid.request(first, count)
    except ValueError as error:
        handler.send_error(400, str(error))
        return
    body = json.dumps(document, separators=(',', ':')).encode()
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    handler.wfile.write(body)


class Grid:
    """The grid of one live source, which its batch's steps fill while a viewer asks.

    Attributes:
        reads: The number of states that the grid read, for the tests and the documentation.
    """

    def __init__(
        self,
        environment_count: int,
        clock: Any = time.monotonic,
        timer: Any = time.perf_counter,
    ) -> None:
        """Prepares an idle grid of a batch of `environment_count` environments.

        Args:
            environment_count: The number of environments of the batch.
            clock: The clock in seconds that paces the reads, which a test may replace.
            timer: The clock in seconds that times the reads, which a test may replace too.
        """
        self.environment_count = environment_count
        self._clock = clock
        self._timer = timer
        self._lock = threading.Lock()
        # The range that a viewer asked for, and until when the grid reads for it.
        self._range = (0, 0)
        self._until = 0.0
        self._tiles: dict[int, dict[str, Any]] = {}
        # The environments left in the current pass, when it started, and when the next read may.
        self._queue: list[int] = []
        self._pass_start = -float('inf')
        self._next = 0.0
        self._readers: dict[int, TileReader] = {}
        self.reads = 0

    @property
    def watched(self) -> bool:
        """Whether a viewer asked for the grid lately, a check of one attribute per step."""
        return self._until > 0.0

    def request(self, first: int, count: int) -> dict[str, Any]:
        """Records a viewer's wish for a range and returns the tiles held for it.

        Args:
            first: The first environment of the range.
            count: The number of environments, from 1 to `MAXIMUM`.

        Raises:
            ValueError: When the range is not one of the batch.
        """
        for name, value in (('first', first), ('count', count)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f'expected a whole number for {name}, found {value!r}')
        if not 0 <= first < self.environment_count:
            raise ValueError(
                f'expected a first environment from 0 to {self.environment_count - 1}, '
                f'found {first}'
            )
        if not 1 <= count <= MAXIMUM:
            raise ValueError(f'expected a count from 1 to {MAXIMUM}, found {count}')
        count = min(count, self.environment_count - first)
        with self._lock:
            if self._range != (first, count):
                self._range = (first, count)
                self._queue = []
                self._pass_start = -float('inf')
                self._tiles = {
                    index: tile
                    for index, tile in self._tiles.items()
                    if first <= index < first + count
                }
            self._until = self._clock() + _LINGER
            tiles = [self._tiles.get(index) for index in range(first, first + count)]
        return {
            'environment_count': self.environment_count,
            'first': first,
            'count': count,
            'tiles': tiles,
        }

    def step(self, batch: Any) -> None:
        """Reads the states that are due at the end of a step, at most `_PER_STEP` of them."""
        now = self._clock()
        with self._lock:
            if now >= self._until:
                # Nobody watches any more, so the grid stops reading and forgets its tiles.
                self._until = 0.0
                self._tiles = {}
                self._queue = []
                self._pass_start = -float('inf')
                return
            if now < self._next:
                return
            if not self._queue:
                if now < self._pass_start + _PERIOD:
                    return
                first, count = self._range
                self._queue = list(range(first, first + count))
                self._pass_start = now
            due, self._queue = self._queue[:_PER_STEP], self._queue[_PER_STEP:]
        start = self._timer()
        tiles = {}
        for environment in due:
            players = int(batch.left_players[environment] + batch.right_players[environment])
            reader = self._readers.get(players)
            if reader is None:
                reader = self._readers[players] = TileReader(players)
            state = batch.get_state(environment, stacked=batch.stacked)
            tiles[environment] = reader.tile(state, environment)
        elapsed = self._timer() - start
        with self._lock:
            self.reads += len(due)
            first, count = self._range
            for environment, tile in tiles.items():
                if first <= environment < first + count:
                    self._tiles[environment] = tile
            self._next = now + max(elapsed / _SHARE, len(due) / _RATE)
