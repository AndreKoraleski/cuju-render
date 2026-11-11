# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""Turns GRF states into the frames of a recording, and writes and reads recording files.

A frame holds what a viewer draws for one step, the world transform of every joint of every player,
the ball, the score, the clock and the game mode, all in the frame of the pitch. The format is in
the repository's `docs/rendering.md`, under Recording format.
"""

from __future__ import annotations

import functools
import gzip
import json
import math
import struct
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from cuju import __version__
from cuju import state as _state
from cuju.errors import StateError

from .._text import messages as _messages
from . import annotations as _annotations
from . import codec as _codec

MAGIC = b'CUJREC1\n'
# The version that `write` gives a recording by default. Version 1 stores the frames one after
# another, and version 2 stores them coded in sections, about a third of the size.
VERSION = 2
VERSIONS = (1, 2)
# The tag and length that open every section of a recording of version 2.
_SECTION = struct.Struct('<4sI')
FRAMES_TAG = b'FRMS'
# The limits that the readers hold a recording to, far above any recording that cuju writes. A
# header of 22 players takes about 4 KB, GRF plays at most 11 a side, and the longest match, one
# of a tournament, lasts 5000 steps, 22 MB once decompressed in version 1 and 41 MB in version 2.
MAX_HEADER_BYTES = 1 << 20
MAX_PLAYERS = 32
MAX_FRAMES = 50_000
MAX_BYTES = 256 << 20
# The frames of version 2 that the reader decodes at once, ten keyframe intervals.
_DECODE_FRAMES = 10 * _codec.KEYFRAME_INTERVAL
# The bytes that the reader passes over at once in a section that it skips.
_SKIP_BYTES = 1 << 20
# The messages that a recording names its title and its teams by, those of the names that cuju
# makes, so a header names no other message of the page.
_LABEL_PREFIXES = ('server.names.', 'server.tournament.label.')
NODES = (
    'player',
    'body',
    'middle',
    'neck',
    'left_shoulder',
    'left_elbow',
    'right_shoulder',
    'right_elbow',
    'left_thigh',
    'left_knee',
    'left_ankle',
    'right_thigh',
    'right_knee',
    'right_ankle',
)
# GRF: the skeleton of `player.object`, in pre-order, so every parent comes before its children.
PARENTS = (-1, 0, 1, 2, 2, 4, 2, 6, 1, 8, 9, 1, 11, 12)
# GRF: a node holds a position, a rotation, a scale and a local mode, 44 bytes in all.
_NODE_BYTES = 44
_NODE_SPAN = _NODE_BYTES * len(NODES)
_LOCAL_MODE_RELATIVE = 0
# GRF: `e_PlayerRole_GK`, the first role.
_GOALKEEPER = 0
# The head of a frame, eight integers, the ball's seven floats and four integers of the referee.
_FRAME_HEAD = struct.Struct('<8i7f4i')
# A team without a name of its own takes the name of its side, which the page shows in its own
# language, with the English text in `name` as before.
_DEFAULT_TEAMS = (
    {
        **_messages.named('name', _messages.label('server.names.left')),
        'color': [214, 48, 49],
        'secondary': [255, 255, 255],
    },
    {
        **_messages.named('name', _messages.label('server.names.right')),
        'color': [9, 132, 227],
        'secondary': [255, 255, 255],
    },
)


# A joint's position is stored in steps of 2 mm, which spans 65 m either way of the center spot,
# and its rotation in steps of 1 / 32767, so each joint takes seven 16-bit integers.
POSITION_SCALE = 500
ROTATION_SCALE = 32767


def frame_bytes(players: int) -> int:
    """Returns the size of one frame of a recording of `players` players."""
    return _FRAME_HEAD.size + players * len(NODES) * 14 + 3 * (-(-players // 4) * 4)


def _quantize(nodes: np.ndarray) -> np.ndarray:
    """Returns joints `[..., 7]` as the 16-bit integers that a recording stores."""
    scale = np.array([POSITION_SCALE] * 3 + [ROTATION_SCALE] * 4, np.float64)
    return np.clip(np.rint(nodes * scale), -32767, 32767).astype('<i2')


# GRF: the state names each type as C++'s `typeid` does, and stores it little-endian.
_DTYPES = {
    'f': ('<f4', ()),
    'i': ('<i4', ()),
    'j': ('<u4', ()),
    'b': ('u1', ()),
    'c': ('i1', ()),
    'm': ('<u8', ()),
    'N7blunted7Vector3E': ('<f4', (3,)),
    'N7blunted10QuaternionE': ('<f4', (4,)),
}


@functools.cache
def _layout() -> dict[str, _state.Field]:
    """Returns the layout of the match in memory, read once."""
    return _state.layout()


def _field(path: str) -> _state.Field:
    """Returns the `Field` of a path of the layout."""
    return _layout()[path]


def _dtype(field: _state.Field) -> tuple[str, tuple[int, ...]]:
    """Returns the numpy type and shape of a field of the layout."""
    dtype, shape = _DTYPES.get(field.type, (None, ()))
    # GRF: an enumeration is a C++ `enum`, four bytes on every platform it runs on.
    if dtype is None and field.size == 4 and field.type[:1].isdigit():
        dtype = '<i4'
    if dtype is None or np.dtype(dtype).itemsize * int(np.prod(shape)) != field.size:
        return 'u1', (field.size,)
    return dtype, shape


class StateReader:
    """Reads the frames of a recording out of the states of one scenario's matches.

    The reader gathers every field it needs from a state in one call into the library, and derives
    the world transform of each joint from the local ones, as GRF's renderer does.

    Attributes:
        players: The number of players of the matches.
    """

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
        ('touch_team', 'match.lastTouchTeamID'),
        ('touch_first', 'match.teams[0].lastTouchPlayer'),
        ('touch_second', 'match.teams[1].lastTouchPlayer'),
        ('clock', 'match.matchTimeMilliseconds'),
        ('actual', 'match.actualTimeMilliseconds'),
        ('ball_position', 'match.ball.positionBuffer'),
        ('ball_rotation', 'match.ball.orientationBuffer'),
        ('foul_player', 'match.referee.foul.foulPlayer'),
        ('foul_victim', 'match.referee.foul.foulVictim'),
        ('foul_type', 'match.referee.foul.foulType'),
        ('offside_count', 'match.referee.offsidePlayers.count'),
        ('offside_first', 'match.referee.offsidePlayers[0]'),
        ('buffer_active', 'match.referee.buffer.active'),
        ('scorer', 'match.lastGoalScorer'),
    )
    _PLAYER = (
        ('active', 'base.isActive'),
        ('cards', 'cards'),
        ('possession', 'hasPossession'),
        ('controller', 'base.externalController'),
        ('action', 'base.humanoid.currentAnimation.functionType'),
        ('touch_time', 'base.lastTouchTimeMilliseconds'),
        ('touch_type', 'base.lastTouchType'),
    )

    def __init__(self, players: int) -> None:
        """Prepares the fields of matches with `players` players in all."""
        self.players = players
        fields, layout = [], []
        for name, path in self._HEAD:
            fields.append(_field(path))
            layout.append((name, *_dtype(fields[-1])))
        for player in range(players):
            prefix = f'match.players[{player}]'
            first = _field(f'{prefix}.base.humanoid.nodes[0].position')
            # The nodes lie one after another in memory, so one field covers all fourteen.
            fields.append(
                _state.Field(f'{prefix}.base.humanoid.nodes', first.offset, _NODE_SPAN, 'nodes')
            )
            layout.append((f'nodes{player}', 'u1', (_NODE_SPAN,)))
            for name, path in self._PLAYER:
                fields.append(_field(f'{prefix}.{path}'))
                layout.append((f'{name}{player}', *_dtype(fields[-1])))
        self._fields = fields
        self._dtype = np.dtype(layout)
        known = _layout()
        self._roles = {
            (team, index): known[path]
            for team, side in enumerate(('left', 'right'))
            for index in range(players)
            if (path := f'environment.scenario.{side}Team[{index}].role') in known
        }

    def _values(self, state: bytes, frame: str) -> np.void:
        """Returns the gathered fields of a state as one structured record."""
        return np.frombuffer(_state.gather(state, self._fields, frame), self._dtype, 1)[0]

    def _order(self, values: np.void) -> list[tuple[int, int]]:
        """Returns the team and the index in its team of each player of the state.

        GRF: the state lists the team processed first before the other, and its ID flips with the
        reverse team processing.
        """
        first = int(values['first']) ^ int(bool(values['reverse']))
        sizes = (int(values['left']), int(values['right']))
        if sum(sizes) != self.players:
            raise StateError(f'expected a match of {self.players} players, found {sizes}')
        return [(first, index) for index in range(sizes[first])] + [
            (1 - first, index) for index in range(sizes[1 - first])
        ]

    def lineup(self, state: bytes) -> list[dict[str, Any]]:
        """Returns the header entry of each player, its team, index, role and control.

        Args:
            state: A state of the match, as `get_state` returns it.
        """
        values = self._values(state, 'rest')
        order = self._order(values)
        roles = _state.read(state, [self._roles[entry] for entry in order])
        return [
            {
                'team': team,
                'index': index,
                'goalkeeper': int(role) == _GOALKEEPER,
                'controlled': int(values[f'controller{player}']) >= 0,
            }
            for player, ((team, index), role) in enumerate(zip(order, roles, strict=True))
        ]

    def frame(self, state: bytes, flags: int = 0) -> bytes:
        """Returns the frame of a state, as a recording stores it.

        Args:
            state: A state of the match, as `get_state` returns it.
            flags: The frame's flags, 1 when the episode ends on this step and 2 when an episode
                ended just before it, as an automatic reset shows.
        """
        values = self._values(state, 'pitch')
        order = self._order(values)
        first = order[0][0] if order else 0
        score = [0, 0]
        score[first], score[1 - first] = int(values['goals_first']), int(values['goals_second'])
        # GRF: `teams` holds the team processed first at index 0, as the goal counts do.
        touch = {first: int(values['touch_first']), 1 - first: int(values['touch_second'])}
        touch_team = int(values['touch_team'])
        nodes = _world_transforms(
            np.stack([values[f'nodes{player}'] for player in range(self.players)])
        )
        padded = -(-self.players // 4) * 4
        states = np.zeros(padded, np.uint8)
        actions = np.zeros(padded, np.uint8)
        touches = np.zeros(padded, np.uint8)
        # GRF: a step runs ten ticks of 10 ms, so a touch of this step lies within its last 100 ms.
        step_start = int(values['actual']) - 100
        owner = -1
        for player in range(self.players):
            cards = int(values[f'cards{player}'])
            # GRF: the engine moves a gamer's controller to the designated player as play moves,
            # so 8 marks the player that an agent or a person controls on this step.
            states[player] = (
                (1 if values[f'active{player}'] else 0)
                | (2 if cards > 0 else 0)
                | (4 if cards > 1 else 0)
                | (8 if int(values[f'controller{player}']) >= 0 else 0)
            )
            actions[player] = int(values[f'action{player}']) & 0xFF
            if int(values[f'touch_time{player}']) > step_start:
                touches[player] = int(values[f'touch_type{player}']) + 1
            team = order[player][0]
            # GRF: the raw observation's owner, a player in possession whose team touched last.
            if values[f'possession{player}'] and touch_team == team and touch[team] == player:
                owner = player
        game_mode = int(values['set_piece']) if values['in_set_piece'] else 0
        called = (
            bool(values['buffer_active'])
            and int(values['set_piece']) == 3
            and int(values['foul_type']) == 0
            and touch_team in touch
        )
        offside = (
            touch[touch_team]
            if called
            else (int(values['offside_first']) if int(values['offside_count']) > 0 else -1)
        )
        flags |= 4 if called else 0
        flags |= (int(values['scorer']) + 1) << 8
        head = _FRAME_HEAD.pack(
            # GRF: the engine counts -1 after a reset and adds one per step.
            int(values['step']) + 1,
            game_mode,
            score[0],
            score[1],
            touch_team if owner >= 0 else -1,
            owner,
            int(values['clock']),
            int(flags),
            *values['ball_position'].tolist(),
            *values['ball_rotation'].tolist(),
            # GRF: a foul type of 1 is a foul, 2 a yellow card and 3 a red card, and both players
            # index the match's players, as the header lists them.
            int(values['foul_player']) if int(values['foul_type']) else -1,
            int(values['foul_victim']) if int(values['foul_type']) else -1,
            int(values['foul_type']),
            offside,
        )
        return head + b''.join(
            (_quantize(nodes).tobytes(), states.tobytes(), actions.tobytes(), touches.tobytes())
        )


def _multiply(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """Returns the Hamilton products of quaternions stored x, y, z, w, as GRF multiplies them."""
    x1, y1, z1, w1 = np.moveaxis(first, -1, 0)
    x2, y2, z2, w2 = np.moveaxis(second, -1, 0)
    return np.stack(
        (
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 + y1 * w2 + z1 * x2 - x1 * z2,
            w1 * z2 + z1 * w2 + x1 * y2 - y1 * x2,
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        ),
        -1,
    )


def _rotate(quaternion: np.ndarray, vector: np.ndarray) -> np.ndarray:
    """Returns each `vector` rotated by its `quaternion`, with GRF's two cross products."""
    part = quaternion[..., :3]
    first = np.cross(part, vector)
    second = np.cross(part, first)
    return vector + first * (2.0 * quaternion[..., 3:]) + second * 2.0


def _world_transforms(blocks: np.ndarray) -> np.ndarray:
    """Returns `[players, nodes, 7]`, the world position and rotation of every node of each player.

    Speed: the nodes come in pre-order, so each node needs its parent alone, and every player goes
    at once.

    Args:
        blocks: `[players, nodes * 44]` bytes, the fourteen nodes of each player as the state holds
            them, each a position, a rotation, a scale and a local mode.
    """
    count = blocks.shape[0]
    records = np.ascontiguousarray(blocks, np.uint8).reshape(count, len(NODES), _NODE_BYTES)
    floats = records[..., :40].copy().view('<f4').astype(np.float64)
    modes = records[..., 40:44].copy().view('<i4')[..., 0]
    positions, rotations, scales = floats[..., 0:3], floats[..., 3:7], floats[..., 7:10]
    world = np.empty((count, len(NODES), 7))
    world_scale = np.empty((count, len(NODES), 3))
    for node, parent in enumerate(PARENTS):
        world[:, node, 3:] = rotations[:, node]
        world_scale[:, node] = scales[:, node]
        world[:, node, :3] = positions[:, node]
        if parent < 0:
            continue
        relative = modes[:, node] == _LOCAL_MODE_RELATIVE
        if not relative.any():
            continue
        rotation = _multiply(world[:, parent, 3:], rotations[:, node])
        rotation /= np.linalg.norm(rotation, axis=-1, keepdims=True)
        scale = world_scale[:, parent] * scales[:, node]
        position = (
            _rotate(world[:, parent, 3:], world_scale[:, parent] * positions[:, node])
            + world[:, parent, :3]
        )
        world[relative, node, 3:] = rotation[relative]
        world_scale[relative, node] = scale[relative]
        world[relative, node, :3] = position[relative]
    return world.astype(np.float32)


def header(
    title: str | dict[str, Any],
    scenario: str,
    lineup: list[dict[str, Any]],
    teams: list[dict[str, Any]] | None = None,
    frame_count: int | None = None,
    timing: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> bytes:
    """Returns the magic, the header length and the header of a recording, as version 1 has it.

    A live stream sends the header as it is, and `write` turns it into the version it writes.

    Args:
        title: The title that the viewer shows, text that a person gave or a label that
            `_messages.label` returns for a title that cuju made, which the header keeps as its
            English `title` with `title_id` and `title_values` beside it.
        scenario: The name of the scenario.
        lineup: The entry of each player, as `StateReader.lineup` returns it.
        teams: The name, `color` and `secondary` color of the left and right team, each optional.
            A name is text or a label, as the title is, and a team without one takes the name of
            its side, Left or Right, as a label.
        frame_count: The number of frames, or None for a live stream.
        timing: The optional scenario timing fields.
        provenance: What is known of where the recording comes from, such as its source, seed
            and configuration. The version of cuju joins it, and a field left out stays unknown.
    """
    given = [*(teams or ()), {}, {}]
    sides = []
    for side in range(2):
        team = {**_DEFAULT_TEAMS[side], **given[side]}
        if 'name' in given[side]:
            # A name given as text is a person's and travels alone, a label keeps its message.
            team = {key: value for key, value in team.items() if key not in _NAME_FIELDS}
            team.update(_name_fields(given[side]))
        sides.append(team)
    document = {
        'version': 1,
        'engine_scorer': True,
        'offside_called': True,
        **(timing or {}),
        **_messages.named('title', title),
        'scenario': scenario,
        'steps_per_second': 10,
        'nodes': list(NODES),
        'parents': list(PARENTS),
        'players': lineup,
        'teams': sides,
        'frame_bytes': frame_bytes(len(lineup)),
        'frame_count': frame_count,
        'provenance': {**(provenance or {}), 'cuju_version': __version__},
    }
    # JavaScript holds integers exactly only up to 2**53 - 1, so a larger seed travels as text.
    seed = document['provenance'].get('seed')
    if isinstance(seed, int) and not isinstance(seed, bool) and seed > 2**53 - 1:
        document['provenance']['seed'] = str(seed)
    return _encode_header(document)


# The fields of a name that cuju made, beside its English text.
_NAME_FIELDS = ('name_id', 'name_values')


def _name_fields(team: dict[str, Any]) -> dict[str, Any]:
    """Returns the name of a team as a header keeps it, its text and, for a label, its message.

    The name is text, a label that `_messages.label` returns, or text beside the `name_id` and
    `name_values` of an entry of the registry, such as the built-in AI's.
    """
    name = team.get('name')
    if isinstance(name, dict):
        return _messages.named('name', name)
    found = {'name': name}
    if isinstance(team.get('name_id'), str) and isinstance(team.get('name_values'), dict):
        found.update(name_id=team['name_id'], name_values=dict(team['name_values']))
    return found


def label_of(document: dict[str, Any], field: str) -> dict[str, Any] | str | None:
    """Returns a name of a header or summary as a label when it holds a valid one, else as text.

    A file of before, or a name that a person gave, holds the text alone and returns it.
    """
    text = document.get(field)
    found = {
        'id': document.get(f'{field}_id'),
        'text': text,
        'values': document.get(f'{field}_values'),
    }
    return found if _messages.valid_label(found) else text


def _document(head: bytes) -> dict[str, Any]:
    """Returns the header of the bytes that `header` returns."""
    return json.loads(head[len(MAGIC) + 4 :])


def _encode_header(document: dict[str, Any]) -> bytes:
    """Returns the magic, the length and a header, padded so that what follows aligns to four."""
    text = json.dumps(document, separators=(',', ':')).encode()
    # Spaces after the JSON align the frames to four bytes, so a reader views their floats in place.
    text += b' ' * (-(len(MAGIC) + 4 + len(text)) % 4)
    return MAGIC + struct.pack('<I', len(text)) + text


def _section(tag: bytes, payload: bytes) -> bytes:
    """Returns a section of version 2, its tag, its length, the payload and zeros to four bytes."""
    return _SECTION.pack(tag, len(payload)) + payload + bytes(-len(payload) % 4)


def encode(
    head: bytes,
    frames: list[bytes],
    version: int = VERSION,
    annotations: list[dict[str, Any]] | None = None,
) -> bytes:
    """Returns a recording before compression, in version 1 or 2.

    Args:
        head: The magic, length and header, as `header` returns them.
        frames: The frames, each as `StateReader.frame` returns it.
        version: The version of the file.
        annotations: The records of the annotations, which version 2 keeps in a section of its own
            and version 1 has no room for.

    Raises:
        StateError: If the version is unknown.
    """
    if version == 1:
        return head + b''.join(frames)
    if version != 2:
        raise StateError(f'expected a recording version from {VERSIONS}, found {version!r}')
    document = _document(head)
    players = len(document['players'])
    document.update(version=2, frame_count=len(frames), keyframe_interval=_codec.KEYFRAME_INTERVAL)
    data = _encode_header(document) + _section(FRAMES_TAG, _codec.encode(frames, players))
    if annotations:
        data += _section(_annotations.TAG, _annotations.encode(annotations))
    return data


def write(
    path: Path,
    head: bytes,
    frames: list[bytes],
    version: int = VERSION,
    annotations: list[dict[str, Any]] | None = None,
) -> None:
    """Writes a recording, gzip-compressed, through a temporary file.

    Args:
        path: The path of the file.
        head: The magic, length and header, as `header` returns them.
        frames: The frames, each as `StateReader.frame` returns it.
        version: The version of the file, 2 by default, or 1 for readers of cuju 0.2.0.
        annotations: The records of the annotations, kept by version 2 alone.
    """
    data = encode(head, frames, version, annotations)
    path = Path(path)
    temporary = path.with_name(path.name + '.part')
    with gzip.open(temporary, 'wb', compresslevel=6) as stream:
        stream.write(data)
    temporary.replace(path)


def _whole(value: Any) -> bool:
    """Returns whether a value of a header is a whole number, which `True` is not."""
    return isinstance(value, int) and not isinstance(value, bool)


def validate_header(document: Any) -> dict[str, Any]:
    """Returns a header after checking that every field the readers use holds its type.

    A field that a header may leave out, such as the title, the teams or the provenance, may also
    be null, and the readers then take its default.

    Raises:
        StateError: If the header is not an object, names a version that this module does not
            read, holds players, a frame size, a number of frames or a keyframe interval that does
            not fit its version or the limits of a recording, or holds a field of the wrong type.
    """
    if not isinstance(document, dict):
        raise StateError(f'expected a header object, found {type(document).__name__}')
    version = document.get('version', 1)
    if not _whole(version) or version not in VERSIONS:
        raise StateError(f'expected a recording version from {VERSIONS}, found {version!r}')
    players = document.get('players')
    if not isinstance(players, list) or len(players) > MAX_PLAYERS:
        raise StateError(f'expected a list of at most {MAX_PLAYERS} players in the header')
    for player in players:
        if not (
            isinstance(player, dict)
            and _whole(player.get('team'))
            and player['team'] in (0, 1)
            and _whole(player.get('index'))
            and 0 <= player['index'] < MAX_PLAYERS
            and all(
                isinstance(player.get(key, False), bool) for key in ('goalkeeper', 'controlled')
            )
        ):
            raise StateError(
                'expected each player of the header with its team, 0 or 1, its index and flags, '
                f'found {str(player)[:80]}'
            )
    size = document.get('frame_bytes')
    if (version == 1 or size is not None) and not (
        _whole(size) and size == frame_bytes(len(players))
    ):
        raise StateError(
            f'expected frames of {frame_bytes(len(players))} bytes for {len(players)} players, '
            f'found {size!r}'
        )
    count = document.get('frame_count')
    if (version == 2 or count is not None) and not (_whole(count) and 0 <= count <= MAX_FRAMES):
        raise StateError(f'expected a number of frames from 0 to {MAX_FRAMES}, found {count!r}')
    interval = document.get('keyframe_interval')
    if version == 2 and not (_whole(interval) and interval == _codec.KEYFRAME_INTERVAL):
        raise StateError(
            f'expected a keyframe interval of {_codec.KEYFRAME_INTERVAL}, found {interval!r}'
        )
    for field, kinds in (('title', str), ('scenario', str), ('provenance', dict)):
        if document.get(field) is not None and not isinstance(document[field], kinds):
            raise StateError(f'expected the {field} of the header as {kinds.__name__}')
    speed = document.get('steps_per_second')
    if speed is not None and not (
        isinstance(speed, int | float)
        and not isinstance(speed, bool)
        and math.isfinite(speed)
        and 0 < speed <= 1000
    ):
        raise StateError(f'expected steps per second above 0 and at most 1000, found {speed!r}')
    second = document.get('second_half')
    if second is not None and not (_whole(second) and second >= 0):
        raise StateError(f'expected the step of the second half, found {second!r}')
    teams = document.get('teams')
    if teams is not None and not (
        isinstance(teams, list)
        and all(
            isinstance(team, dict)
            and all(
                team.get(key) is None or isinstance(team[key], kind)
                for key, kind in (('name', str), ('id', str), ('style', dict))
            )
            for team in teams
        )
    ):
        raise StateError('expected the teams of the header, each with a name as text')
    # A label of a message that no recording carries leaves its name as the text beside it.
    for holder, field in [(document, 'title'), *((team, 'name') for team in teams or ())]:
        fields = (f'{field}_id', f'{field}_values')
        if any(key in holder for key in fields) and not _carried(
            {
                'id': holder.get(fields[0]),
                'text': holder.get(field),
                'values': holder.get(fields[1]),
            }
        ):
            for key in fields:
                holder.pop(key, None)
    return document


def _carried(label: Any) -> bool:
    """Returns whether a label names a message of the names of cuju, as each label of its values."""

    def named(value: dict[str, Any]) -> bool:
        return 'kind' in value or (
            value['id'].startswith(_LABEL_PREFIXES)
            and all(isinstance(item, str) or named(item) for item in value['values'].values())
        )

    try:
        return _messages.valid_label(label) and named(label)
    except RecursionError:
        return False


class _Budget:
    """Reads a decompressed recording, counting its bytes against the limit of a recording.

    A read never asks for more than the limit leaves, so a length that a file gives reserves no
    more memory than the limit allows, and a fault of the compression turns into a `StateError`.
    """

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self.left = MAX_BYTES

    def read(self, size: int) -> bytes:
        try:
            data = self._stream.read(min(size, self.left + 1))
        except (EOFError, zlib.error, gzip.BadGzipFile) as error:
            raise StateError(f'expected a whole gzip stream, found {error}') from None
        self.left -= len(data)
        if self.left < 0:
            raise StateError(
                f'expected a recording of at most {MAX_BYTES >> 20} MiB once decompressed'
            )
        return data


def _constant(name: str) -> Any:
    """Refuses NaN and the infinities, which Python reads in JSON and a page does not."""
    raise ValueError(f'expected numbers of JSON, found {name}')


def _parse_header(stream: Any) -> dict[str, Any]:
    """Returns the header at the start of `stream`, after checking the magic and its fields."""
    start = stream.read(len(MAGIC) + 4)
    if start[: len(MAGIC)] != MAGIC:
        raise StateError('expected a recording of cuju, found other bytes')
    if len(start) < len(MAGIC) + 4:
        raise StateError('expected the length of a header, found the recording cut short')
    (length,) = struct.unpack_from('<I', start, len(MAGIC))
    if length > MAX_HEADER_BYTES:
        raise StateError(f'expected a header of at most {MAX_HEADER_BYTES} bytes, found {length}')
    text = stream.read(length)
    if len(text) < length:
        raise StateError('expected a whole header, found the recording cut short')
    try:
        document = json.loads(text, parse_constant=_constant)
    except (ValueError, RecursionError) as error:
        raise StateError(f'expected a header of JSON, found {error}') from None
    return validate_header(document)


def read_header(path: Path) -> dict[str, Any]:
    """Returns the header of a recording file, reading only its start."""
    with gzip.open(path, 'rb') as stream:
        return _parse_header(_Budget(stream))


def _sections(stream: Any, tags: tuple[bytes, ...]) -> dict[bytes, bytes]:
    """Returns the sections of version 2 of `tags` that follow the header in `stream`, by tag.

    The first section of each tag counts, and the reader passes over any other in chunks.
    """
    found = {}
    while head := stream.read(_SECTION.size):
        if len(head) < _SECTION.size:
            raise StateError('expected a whole section of the recording, found it cut short')
        tag, length = _SECTION.unpack(head)
        rest = length + (-length % 4)
        if tag in tags and tag not in found:
            payload = stream.read(length)
            if len(payload) < length:
                raise StateError('expected a whole section of the recording, found it cut short')
            found[tag] = payload
            rest -= length
        while rest > 0:
            skipped = len(stream.read(min(rest, _SKIP_BYTES)))
            if skipped == 0:
                raise StateError('expected a whole section of the recording, found it cut short')
            rest -= skipped
    return found


def _coded_frames(document: dict[str, Any], sections: dict[bytes, bytes]) -> tuple[bytes, int]:
    """Returns the frames section of a recording of version 2 and the number of its players."""
    players = len(document['players'])
    data = sections.get(FRAMES_TAG)
    if (
        not players
        or data is None
        or len(data) != _codec.section_bytes(players, document['frame_count'])
    ):
        raise StateError('expected the frames of a recording of version 2, found them malformed')
    return data, players


def annotations(path: Path) -> list[dict[str, Any]]:
    """Returns the records of the annotations of a recording file, none for version 1."""
    with gzip.open(path, 'rb') as raw:
        stream = _Budget(raw)
        if _parse_header(stream).get('version', 1) == 1:
            return []
        payload = _sections(stream, (_annotations.TAG,)).get(_annotations.TAG)
    return _annotations.decode(payload) if payload is not None else []


def frames(path: Path, start: int = 0, stop: int | None = None) -> Iterator[bytes]:
    """Yields the frames of a recording file one after another, each as version 1 stores it.

    A file of version 2 decodes from the keyframe before `start`, so the last frames come quickly,
    and a thousand frames at a time, so a long recording takes little memory beyond its file.

    Args:
        path: The path of the file.
        start: The first frame to yield.
        stop: The frame after the last to yield, by default the end.

    Raises:
        StateError: If the file is not a recording or reaches past the limits of one.
    """
    with gzip.open(path, 'rb') as raw:
        stream = _Budget(raw)
        document = _parse_header(stream)
        if document.get('version', 1) == 1:
            size = document['frame_bytes']
            index = 0
            # A last frame cut short is left out, as the page leaves it out.
            while (stop is None or index < stop) and len(chunk := stream.read(size)) == size:
                if index >= MAX_FRAMES:
                    raise StateError(f'expected a recording of at most {MAX_FRAMES} frames')
                if index >= start:
                    yield chunk
                index += 1
            return
        data, players = _coded_frames(document, _sections(stream, (FRAMES_TAG,)))
    count = document['frame_count']
    end = count if stop is None else max(0, min(stop, count))
    at = max(0, start)
    while at < end:
        upto = min(end, (at // _DECODE_FRAMES + 1) * _DECODE_FRAMES)
        for row in _codec.decode(data, players, count, _codec.KEYFRAME_INTERVAL, at, upto):
            yield row.tobytes()
        at = upto


def ending(path: Path) -> tuple[int, bytes | None]:
    """Returns the number of frames of a recording file and its last frame, `None` for none.

    A file of version 2 decodes its last frame alone, and one of version 1 reads one frame at a
    time, so neither holds more than its file and a few frames at once.

    Raises:
        StateError: If the file is not a recording or reaches past the limits of one.
    """
    document = read_header(path)
    count, last = 0, None
    if document.get('version', 1) == 2:
        count = document['frame_count']
        for frame in frames(path, start=max(0, count - 1)):
            last = frame
        return count, last
    for frame in frames(path):
        count, last = count + 1, frame
    return count, last


def scenario_timing(state: bytes) -> dict[str, Any]:
    """Returns the scenario timing without changing the state."""
    duration, second, score, possession, out = _state.read(
        state,
        [
            'environment.scenario.gameDuration',
            'environment.scenario.secondHalf',
            'environment.scenario.endEpisodeOnScore',
            'environment.scenario.endEpisodeOnPossessionChange',
            'environment.scenario.endEpisodeOnOutOfPlay',
        ],
    )
    duration, second = int(duration), int(second)
    half_ms = (1800 * second) & 0xFFFFFFFF
    return {
        'duration': duration,
        'second_half': second if 0 < second < duration and half_ms < 0x80000000 else None,
        'full_match': duration >= 3000 and not any((score, possession, out)),
    }
