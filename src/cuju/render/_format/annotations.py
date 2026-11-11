# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""Annotations, the numbers and text that a training loop or a policy attaches to steps.

An annotation belongs to a frame and, optionally, to one player of the header. It holds named
numbers such as a value estimate or a reward, a short text, the chosen action and the most likely
actions with their probabilities. A recording of version 2 keeps them in a section of their own,
and a live source streams them beside its frames. Annotating reads nothing of the batch and
changes nothing of it.

A record keeps short keys, as the file stores them. `f` is the frame, `p` the player, `v` the
named numbers, `t` the text, `a` the action and `k` the likely actions, each a pair of an action
and its probability, the most likely first.
"""

from __future__ import annotations

import json
import math
import struct
from collections.abc import Iterable, Mapping
from typing import Any

from cuju.errors import ArgumentError

TAG = b'ANNO'
# The limits of one annotation.
MAX_VALUES = 16
NAME_LENGTH = 40
TEXT_LENGTH = 200
MAX_ACTIONS = 1000
# The likely actions that an annotation keeps.
TOP = 3


def _number(value: Any, what: str) -> float | int:
    """Returns a finite number from a Python, numpy or torch scalar, to six significant digits."""
    if hasattr(value, 'item') and not isinstance(value, int | float):
        value = value.item()
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ArgumentError(f'expected {what} as a finite number, found {value!r}')
    rounded = float(f'{value:.6g}')
    return int(rounded) if rounded.is_integer() and abs(rounded) < 2**53 else rounded


def player_index(lineup: list[dict[str, Any]], player: Any) -> int:
    """Returns the index in the header of a player given by number or as a pair of team and index.

    A number counts the players of the left team first, then those of the right team, each team in
    the order of its indices, as the rewards and observations of a batch count them. The header may
    list the teams in another order, which the returned index follows.
    """
    if isinstance(player, int) and not isinstance(player, bool):
        if 0 <= player < len(lineup):
            order = sorted(
                range(len(lineup)),
                key=lambda k: (lineup[k].get('team', 0), lineup[k].get('index', k), k),
            )
            return order[player]
    elif isinstance(player, tuple | list) and len(player) == 2:
        for index, entry in enumerate(lineup):
            if [entry.get('team'), entry.get('index')] == list(player):
                return index
    raise ArgumentError(
        f'expected a player from 0 to {len(lineup) - 1} or a pair of team and index, '
        f'found {player!r}'
    )


def player_number(lineup: list[dict[str, Any]], index: int) -> int:
    """Returns the number of the player at `index` of the header, the left team's players first.

    The number is the one that `player_index` reads, so a player given by number comes back as
    that number whatever order the header lists the teams in.
    """
    order = sorted(
        range(len(lineup)),
        key=lambda k: (lineup[k].get('team', 0), lineup[k].get('index', k), k),
    )
    return order.index(index) if 0 <= index < len(lineup) else index


def _likely(probabilities: Any) -> list[list[float | int]]:
    """Returns the most likely actions with their probabilities, from a sequence or a mapping."""
    if hasattr(probabilities, 'tolist'):
        probabilities = probabilities.tolist()
    if isinstance(probabilities, Mapping):
        pairs = list(probabilities.items())
    elif isinstance(probabilities, Iterable) and not isinstance(probabilities, str | bytes):
        pairs = list(enumerate(probabilities))
    else:
        raise ArgumentError(
            f'expected probabilities as a sequence or mapping, found {probabilities!r}'
        )
    if len(pairs) > MAX_ACTIONS:
        raise ArgumentError(f'expected at most {MAX_ACTIONS} probabilities, found {len(pairs)}')
    checked = []
    for action, probability in pairs:
        if isinstance(action, bool) or not isinstance(action, int) or action < 0:
            raise ArgumentError(f'expected actions as whole numbers, found {action!r}')
        checked.append((action, _number(probability, 'a probability')))
    checked.sort(key=lambda pair: (-pair[1], pair[0]))
    return [[action, float(f'{probability:.4g}')] for action, probability in checked[:TOP]]


def note(
    lineup: list[dict[str, Any]],
    values: Mapping[str, Any] | None = None,
    text: str | None = None,
    player: Any = None,
    probabilities: Any = None,
    action: Any = None,
) -> dict[str, Any]:
    """Returns the record of one annotation without its frame, after checking every part.

    Raises:
        ArgumentError: If a part is invalid or the annotation holds nothing.
    """
    record: dict[str, Any] = {}
    if player is not None:
        record['p'] = player_index(lineup, player)
    if values is not None:
        if not isinstance(values, Mapping) or len(values) > MAX_VALUES:
            raise ArgumentError(f'expected values as a mapping of at most {MAX_VALUES} names')
        named = {}
        for name, value in values.items():
            if not isinstance(name, str) or not 0 < len(name) <= NAME_LENGTH:
                raise ArgumentError(
                    f'expected names of 1 to {NAME_LENGTH} characters, found {name!r}'
                )
            named[name] = _number(value, f'the value {name!r}')
        if named:
            record['v'] = named
    if text is not None:
        if not isinstance(text, str):
            raise ArgumentError(f'expected text as a string, found {text!r}')
        record['t'] = text[:TEXT_LENGTH]
    if action is not None:
        if hasattr(action, 'item'):
            action = action.item()
        if isinstance(action, bool) or not isinstance(action, int) or action < 0:
            raise ArgumentError(f'expected the action as a whole number, found {action!r}')
        record['a'] = action
    if probabilities is not None:
        record['k'] = _likely(probabilities)
    if not record.keys() - {'p'}:
        raise ArgumentError('expected values, text, an action or probabilities to annotate')
    return record


def merge(
    records: dict[tuple[int, int], dict[str, Any]], frame: int, record: dict[str, Any]
) -> dict[str, Any]:
    """Adds an annotation of `frame` to `records`, merged with an earlier one of the same player.

    Named numbers join those already there, and the text, action and likely actions replace
    theirs. Returns the merged record.

    Raises:
        ArgumentError: If the merged record would hold more than `MAX_VALUES` names.
    """
    key = (frame, record.get('p', -1))
    merged = dict(records.get(key) or {'f': frame})
    for name, value in record.items():
        merged[name] = {**merged.get('v', {}), **value} if name == 'v' else value
    if len(merged.get('v', ())) > MAX_VALUES:
        raise ArgumentError(f'expected at most {MAX_VALUES} named values on a step')
    records[key] = merged
    return merged


def frame_of(frames: list[bytes], step: int | None) -> int:
    """Returns the index of the frame of `step`, the last frame for `None`.

    Raises:
        ArgumentError: If no frame holds the step.
    """
    if step is not None:
        if isinstance(step, bool) or not isinstance(step, int):
            raise ArgumentError(f'expected the step as a whole number, found {step!r}')
        for index in range(len(frames) - 1, -1, -1):
            if struct.unpack_from('<i', frames[index])[0] == step:
                return index
        raise ArgumentError(f'expected a step of the current episode, found {step}')
    return len(frames) - 1


def encode(records: Iterable[dict[str, Any]]) -> bytes:
    """Returns the payload of an annotations section, its records in order of frame and player."""
    ordered = sorted(records, key=lambda record: (record['f'], record.get('p', -1)))
    return json.dumps({'records': ordered}, separators=(',', ':')).encode()


def decode(payload: bytes) -> list[dict[str, Any]]:
    """Returns the records of an annotations section, leaving out any that is malformed."""
    try:
        records = json.loads(payload)['records']
    except (ValueError, KeyError, TypeError):
        return []
    return (
        [
            record
            for record in records
            if isinstance(record, dict) and isinstance(record.get('f'), int)
        ]
        if isinstance(records, list)
        else []
    )


def public(
    record: dict[str, Any], frames: list[bytes], lineup: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Returns a record with long keys and the step of its frame, as a filter reads it.

    With the header's `lineup`, the player is its number with the left team's players first, as
    `annotate` takes it, and without one the index in the header.
    """
    frame = record['f']
    player = record.get('p')
    if lineup is not None and isinstance(player, int):
        player = player_number(lineup, player)
    return {
        'frame': frame,
        'step': struct.unpack_from('<i', frames[frame])[0] if frame < len(frames) else None,
        'player': player,
        'values': dict(record.get('v', {})),
        'text': record.get('t'),
        'action': record.get('a'),
        'probabilities': [list(pair) for pair in record.get('k', ())],
    }
