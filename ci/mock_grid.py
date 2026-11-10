# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""A live source of the mock server whose batch has several environments, for the grid.

Each environment replays one of two synthetic matches of five a side at real time, from a moment
of its own, so the source starts in a few seconds even on a busy machine. The source
streams the environment it shows, answers the grid of environments from the frames of all of them,
as the real source answers from its states, and switches the environment it shows on request,
ending its stream so that the page follows the switch as it does with a real source.
"""

import json
import struct
import threading
import time

import mock_sample

ENVIRONMENTS = 12
PER_TEAM = 5
STEPS = 300
# The synthetic matches that the environments share, and the frames between two environments
# that show the same match.
MATCHES = 2
OFFSET = 37
# The most environments that one request of the grid may ask for, as for the real source.
MAXIMUM = 64
TEAMS = [
    {'name': 'Left', 'color': [214, 48, 49], 'secondary': [255, 255, 255]},
    {'name': 'Right', 'color': [9, 132, 227], 'secondary': [255, 255, 255]},
]
SOURCES = {}
_HEAD = struct.Struct('<8i7f4i')


class GridSource:
    """A source of a batch of ENVIRONMENTS environments, each a match that loops."""

    def __init__(self, identifier):
        self.id = identifier
        self.scenario = '5_vs_5'
        self.environment = 0
        self.generation = 0
        self.start = time.monotonic()
        self.cond = threading.Condition()
        self.matches = [
            mock_sample.generate_frames(PER_TEAM, STEPS, 40 + index, ('Left', 'Right'), TEAMS)
            for index in range(MATCHES)
        ]

    @property
    def title(self):
        return f'{self.scenario}, environment {self.environment}, grid of the mock server'

    def describe(self):
        return {
            'id': self.id,
            'title': self.title,
            'scenario': self.scenario,
            'environment': self.environment,
            'environment_count': ENVIRONMENTS,
            'generation': self.generation,
        }

    def position(self, environment):
        """Returns the index of the frame that an environment shows now."""
        now = int((time.monotonic() - self.start) * mock_sample.STEPS_PER_SECOND)
        return (now + environment // MATCHES * OFFSET) % STEPS

    def match(self, environment):
        """Returns the header and the frames of the match that an environment shows."""
        return self.matches[environment % MATCHES]

    def header(self, environment):
        header = dict(self.match(environment)[0])
        header.update(
            title=self.title,
            scenario=self.scenario,
            frame_count=None,
            environment_count=ENVIRONMENTS,
            provenance={'source': 'live', 'environment': environment},
        )
        return header

    def tile(self, environment):
        """Returns the tile of an environment from its frame, as the real source reads a state."""
        frame = self.match(environment)[1][self.position(environment)]
        head = _HEAD.unpack_from(frame)
        players = PER_TEAM * 2
        nodes = struct.unpack_from(f'<{players * 14 * 7}h', frame, _HEAD.size)
        flags = frame[_HEAD.size + players * 14 * 7 * 2 :][:players]
        lineup = self.match(environment)[0]['players']
        positions = []
        for player in range(players):
            base = player * 14 * 7
            positions += [round(nodes[base] / 500, 2), round(nodes[base + 1] / 500, 2)]
        return {
            'environment': environment,
            'step': head[0],
            'score': [head[2], head[3]],
            'clock': head[6],
            'mode': head[1],
            'ball': [round(value, 2) for value in head[8:11]],
            'teams': [entry['team'] for entry in lineup],
            'players': positions,
            'active': [flag & 1 for flag in flags],
        }

    def grid(self, first, count):
        if not 0 <= first < ENVIRONMENTS or not 1 <= count <= MAXIMUM:
            raise ValueError(
                f'expected a first environment from 0 to {ENVIRONMENTS - 1} and a count from 1 '
                f'to {MAXIMUM}, found {first} and {count}'
            )
        count = min(count, ENVIRONMENTS - first)
        return {
            'environment_count': ENVIRONMENTS,
            'first': first,
            'count': count,
            'tiles': [self.tile(index) for index in range(first, first + count)],
        }

    def select(self, environment):
        if isinstance(environment, bool) or not isinstance(environment, int):
            raise ValueError(f'expected an environment, found {environment!r}')
        if not 0 <= environment < ENVIRONMENTS:
            raise ValueError(f'expected an environment from 0 to {ENVIRONMENTS - 1}')
        with self.cond:
            if environment != self.environment:
                self.environment = environment
                self.generation += 1
                self.cond.notify_all()

    def stream(self, handler):
        """Streams the environment shown now until the source switches to another."""
        with self.cond:
            generation, environment = self.generation, self.environment
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/octet-stream')
        handler.send_header('Cache-Control', 'no-store')
        handler.end_headers()
        frames = self.match(environment)[1]
        handler.wfile.write(mock_sample.encode_header(self.header(environment)))
        last = self.position(environment)
        handler.wfile.write(frames[last])
        handler.wfile.flush()
        while True:
            with self.cond:
                self.cond.wait_for(lambda: self.generation != generation, timeout=0.1)
                if self.generation != generation:
                    return
            now = self.position(environment)
            if now != last:
                last = now
                handler.wfile.write(frames[now])
                handler.wfile.flush()


def start(live, identifier):
    """Adds a source of several environments to the mock server's live sources."""
    source = GridSource(identifier)
    SOURCES[identifier] = source
    live[identifier] = source
    return source


def owns(identifier):
    return identifier in SOURCES


def get(handler, identifier, action, query):
    """Answers the stream and the grid of a source of several environments."""
    source = SOURCES[identifier]
    if action == 'stream':
        source.stream(handler)
    elif action == 'grid':
        # As the real server, a page of another origin may not make the source read.
        origin = handler.headers.get('Origin')
        if origin is not None and origin != f'http://{handler.headers.get("Host")}':
            handler._error(403, 'expected a request from the page of this server')
            return
        values = []
        for name in ('first', 'count'):
            text = query.get(name, '')
            if not text.isdigit():
                raise ValueError(f'expected a whole number for {name}, found {text!r}')
            values.append(int(text))
        handler._json(source.grid(*values))
    else:
        handler._error(404, 'no such resource')


def post(handler, identifier, action):
    """Switches the environment that a source of several environments shows."""
    source = SOURCES[identifier]
    if action != 'environment':
        handler._error(404, 'no such resource')
        return
    environment = json.loads(handler._body() or b'{}').get('environment')
    source.select(environment)
    handler._json({'environment': environment, 'generation': source.generation}, 202)
