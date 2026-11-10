# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""Codes the frames of a recording of version 2, which decode to the bytes of version 1 exactly.

The frames section stores every field of every frame as a lane, the values of one field across all
frames, and lanes of a kind lie together as planes of bytes, the low bytes of every lane and then
the high bytes. A joint is stored relative to its parent, as the rotation and offset that the
parent carries it by and a small residual, so most lanes change slowly and the whole file's gzip
finds them. The coding starts afresh at every keyframe, so any frame decodes from the keyframe
before it. The layout is in the repository's `docs/rendering.md`, under Recording format.

Speed: the coder works on whole lanes with numpy, every joint of every frame at once, and the
decoder one joint at a time over every frame, so a full match of eleven a side codes in a few
seconds and decodes in about one.
"""

from __future__ import annotations

import numpy as np

# The steps between keyframes, ten seconds of play.
KEYFRAME_INTERVAL = 100
# A rotation component is stored in steps of 1 / UNIT, as version 1 stores it.
UNIT = 32767
HEAD_WORDS = 19
HEAD_BYTES = HEAD_WORDS * 4
JOINTS = 14
PARENTS = (-1, 0, 1, 2, 2, 4, 2, 6, 1, 8, 9, 1, 11, 12)
_CHILDREN = JOINTS - 1
_PARENT_INDEX = np.array(PARENTS[1:])
# The kinds of int16 lanes per player, in the order of the section, with the number of each.
_ROOT_POSITION, _ROOT_ROTATION = 3, 4
_LOCAL_ROTATION, _LOCAL_OFFSET = 3 * _CHILDREN, 3 * _CHILDREN
_ROTATION_RESIDUAL, _POSITION_RESIDUAL = 4 * _CHILDREN, 3 * _CHILDREN
_SIGNS = _CHILDREN
_CONJUGATE = np.array([-1, -1, -1, 1])


def padded(players: int) -> int:
    """Returns the bytes of each of the three byte runs that close a frame of version 1."""
    return -(-players // 4) * 4


def frame_bytes(players: int) -> int:
    """Returns the bytes of one decoded frame, as version 1 stores it."""
    return HEAD_BYTES + players * JOINTS * 14 + 3 * padded(players)


def section_bytes(players: int, count: int) -> int:
    """Returns the bytes of the frames section of `count` frames of `players` players."""
    short = players * (
        _ROOT_POSITION
        + _ROOT_ROTATION
        + _LOCAL_ROTATION
        + _LOCAL_OFFSET
        + _ROTATION_RESIDUAL
        + _POSITION_RESIDUAL
    )
    return count * (HEAD_BYTES + 2 * short + players * _SIGNS + 3 * padded(players))


def _hamilton(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """Returns the Hamilton products of quaternions, x, y, z and w along the first axis."""
    x1, y1, z1, w1 = first
    x2, y2, z2, w2 = second
    return np.stack(
        (
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 + y1 * w2 + z1 * x2 - x1 * z2,
            w1 * z2 + z1 * w2 + x1 * y2 - y1 * x2,
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        )
    )


def _cross(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """Returns the cross products of vectors, x, y and z along the first axis."""
    x1, y1, z1 = first
    x2, y2, z2 = second
    return np.stack((y1 * z2 - z1 * y2, z1 * x2 - x1 * z2, x1 * y2 - y1 * x2))


def _isqrt(values: np.ndarray) -> np.ndarray:
    """Returns the integer square roots of non-negative integers below 2**52."""
    root = np.floor(np.sqrt(values.astype(np.float64))).astype(np.int64)
    root -= root * root > values
    root += (root + 1) * (root + 1) <= values
    return root


def _predict_rotation(parent: np.ndarray, local: np.ndarray, sign: np.ndarray) -> np.ndarray:
    """Returns the rotation that `parent` carries the local rotation `local` to.

    The local rotation gives x, y and z, its w follows from the unit length, negative where `sign`
    is set, and the product rounds half up in steps of 1 / UNIT. Every value is an integer below
    2**53, so a reader in double precision computes the same. Components lie along the first axis.
    """
    w = _isqrt(np.maximum(UNIT * UNIT - (local * local).sum(0), 0))
    w = np.where(sign != 0, -w, w)
    product = _hamilton(parent, np.concatenate((local, w[None]), 0))
    return (2 * product + UNIT) // (2 * UNIT)


def _predict_position(origin: np.ndarray, parent: np.ndarray, offset: np.ndarray) -> np.ndarray:
    """Returns `origin` plus `offset` turned by the rotation `parent`, rounded half up."""
    axis, w = parent[:3], parent[3:]
    turned = _cross(axis, offset)
    total = offset * (UNIT * UNIT) + 2 * w * turned + 2 * _cross(axis, turned)
    return origin + (2 * total + UNIT * UNIT) // (2 * UNIT * UNIT)


def _difference(values: np.ndarray, interval: int) -> np.ndarray:
    """Returns each value less the one before along the last axis, the keyframes as they are."""
    out = values.copy()
    out[..., 1:] -= values[..., :-1]
    out[..., ::interval] = values[..., ::interval]
    return out


def _sum(values: np.ndarray, interval: int) -> np.ndarray:
    """Undoes `_difference`, summing from each keyframe on."""
    out = values.copy()
    for start in range(0, values.shape[-1], interval):
        part = out[..., start : start + interval]
        np.cumsum(part, axis=-1, out=part)
    return out


def _xor(values: np.ndarray, interval: int) -> np.ndarray:
    """Returns each byte XOR the one before along the last axis, the keyframes as they are."""
    out = values.copy()
    out[..., 1:] ^= values[..., :-1]
    out[..., ::interval] = values[..., ::interval]
    return out


def _unxor(values: np.ndarray, interval: int) -> np.ndarray:
    """Undoes `_xor`, from each keyframe on."""
    out = values.copy()
    for start in range(0, values.shape[-1], interval):
        part = out[..., start : start + interval]
        np.bitwise_xor.accumulate(part, axis=-1, out=part)
    return out


def _steady(values: np.ndarray, interval: int, reach: int) -> np.ndarray:
    """Holds each value at the one before while it moves by at most `reach`, from each keyframe.

    A held value costs nothing in its lane, and the residual takes up the difference.
    """
    out = np.moveaxis(values, -1, 0).copy()
    for frame in range(1, len(out)):
        if frame % interval:
            near = np.abs(out[frame] - out[frame - 1]) <= reach
            out[frame] = np.where(near, out[frame - 1], out[frame])
    return np.ascontiguousarray(np.moveaxis(out, 0, -1))


def _planes(values: np.ndarray, width: int) -> bytes:
    """Returns lanes `[..., frames]` of signed integers as zigzag planes, the lowest byte first."""
    signed = np.ascontiguousarray(values).astype(f'<i{width}')
    zigzag = ((signed << 1) ^ (signed >> (8 * width - 1))).view(f'<u{width}')
    split = zigzag.reshape(-1).view(np.uint8).reshape(-1, width)
    return b''.join(split[:, plane].tobytes() for plane in range(width))


def _unplanes(data: np.ndarray, width: int) -> np.ndarray:
    """Undoes `_planes` for planes `[width, lanes, frames]`, returning `[lanes, frames]` int64."""
    joined = np.empty((*data.shape[1:], width), np.uint8)
    for plane in range(width):
        joined[..., plane] = data[plane]
    zigzag = joined.view(f'<u{width}')[..., 0]
    signed = (zigzag >> 1).astype(f'<i{width}') ^ -(zigzag & 1).astype(f'<i{width}')
    return signed.astype(np.int64)


def encode(frames: list[bytes], players: int, interval: int = KEYFRAME_INTERVAL) -> bytes:
    """Returns the frames section of version 2 for frames of version 1.

    Args:
        frames: The frames, each as version 1 stores it.
        players: The number of players.
        interval: The frames from one keyframe to the next.
    """
    count = len(frames)
    size = frame_bytes(players)
    raw = np.frombuffer(b''.join(frames), np.uint8).reshape(count, size)
    nodes_end = HEAD_BYTES + players * JOINTS * 14
    head = raw[:, :HEAD_BYTES].copy().view('<i4').T.astype(np.int64)
    tail = np.ascontiguousarray(raw[:, nodes_end:].T)
    nodes = raw[:, HEAD_BYTES:nodes_end].copy().view('<i2').reshape(count, players, JOINTS, 7)
    # Components, joints, players and frames, so each lane of values is contiguous.
    nodes = np.ascontiguousarray(nodes.transpose(3, 2, 1, 0)).astype(np.int64)
    position, rotation = nodes[:3], nodes[3:]
    parent, child = rotation[:, _PARENT_INDEX], rotation[:, 1:]
    origin, place = position[:, _PARENT_INDEX], position[:, 1:]
    conjugate = parent * _CONJUGATE[:, None, None, None]
    # The local rotation, from the parent's rotation to the child's, in steps of 1 / UNIT.
    local = _hamilton(conjugate, child)
    turn = np.clip(np.rint(local[:3] / UNIT), -UNIT, UNIT).astype(np.int64)
    turn = _steady(turn, interval, 1)
    sign = (local[3] < 0).astype(np.uint8)
    # The offset of the child in the frame of its parent, in the steps of a position.
    unit = conjugate.astype(np.float64)
    unit /= np.maximum(np.sqrt((unit * unit).sum(0)), 1.0)
    gap = (place - origin).astype(np.float64)
    turned = _cross(unit[:3], gap)
    offset = gap + 2 * unit[3:] * turned + 2 * _cross(unit[:3], turned)
    offset = _steady(np.clip(np.rint(offset), -UNIT, UNIT).astype(np.int64), interval, 1)
    rotation_residual = child - _predict_rotation(parent, turn, sign)
    position_residual = place - _predict_position(origin, parent, offset)

    def lanes(values: np.ndarray) -> np.ndarray:
        # Components, joints, players and frames become joints, components, players and frames.
        return values.transpose(1, 0, 2, 3)

    parts = [
        _planes(_difference(head, interval), 4),
        _planes(_difference(_difference(position[:, 0], interval), interval), 2),
        _planes(_difference(rotation[:, 0], interval), 2),
        _planes(lanes(_difference(turn, interval)), 2),
        _xor(sign, interval).tobytes(),
        _planes(lanes(_difference(offset, interval)), 2),
        _planes(lanes(rotation_residual), 2),
        _planes(lanes(position_residual), 2),
        _xor(tail, interval).tobytes(),
    ]
    data = b''.join(parts)
    assert len(data) == section_bytes(players, count)
    return data


def decode(
    data: bytes | memoryview,
    players: int,
    count: int,
    interval: int = KEYFRAME_INTERVAL,
    start: int = 0,
    stop: int | None = None,
) -> np.ndarray:
    """Returns frames `start` to `stop` of a frames section, as `[frames, frame_bytes]` bytes.

    Only the frames from the keyframe before `start` decode, so a reader seeks in constant time.

    Args:
        data: The frames section, at least `section_bytes(players, count)` bytes.
        players: The number of players.
        count: The number of frames of the section.
        interval: The frames from one keyframe to the next.
        start: The first frame to return.
        stop: The frame after the last to return, by default the end.
    """
    stop = count if stop is None else max(0, min(stop, count))
    start = max(0, min(start, stop))
    first = start // interval * interval
    span = stop - first
    if start == stop:
        return np.empty((0, frame_bytes(players)), np.uint8)
    buffer = np.frombuffer(data, np.uint8, section_bytes(players, count))
    at = 0

    def take(lanes: int, width: int = 2) -> np.ndarray:
        nonlocal at
        size = lanes * count * width
        block = buffer[at : at + size].reshape(width, lanes, count)[:, :, first:stop]
        at += size
        return _unplanes(block, width) if width > 1 else block[0]

    def short(values: np.ndarray) -> np.ndarray:
        # A sum of differences holds the value up to whole turns of 2**16.
        return values.astype(np.int16).astype(np.int64)

    head = _sum(take(HEAD_WORDS, 4), interval)
    root_position = short(_sum(_sum(take(3 * players), interval), interval))
    root_rotation = short(_sum(take(4 * players), interval))
    turn = short(_sum(take(_LOCAL_ROTATION * players), interval))
    sign = _unxor(take(_SIGNS * players, 1), interval).reshape(_CHILDREN, players, span)
    offsets = short(_sum(take(_LOCAL_OFFSET * players), interval))
    rotation_residual = take(_ROTATION_RESIDUAL * players).reshape(_CHILDREN, 4, players, span)
    position_residual = take(_POSITION_RESIDUAL * players).reshape(_CHILDREN, 3, players, span)
    tail = _unxor(take(3 * padded(players), 1), interval)
    turn = turn.reshape(_CHILDREN, 3, players, span)
    offsets = offsets.reshape(_CHILDREN, 3, players, span)

    # Components, joints, players and frames, as the encoder holds them.
    nodes = np.empty((7, JOINTS, players, span), np.int64)
    nodes[:3, 0] = root_position.reshape(3, players, span)
    nodes[3:, 0] = root_rotation.reshape(4, players, span)
    for joint in range(1, JOINTS):
        parent = nodes[:, PARENTS[joint]]
        index = joint - 1
        rotation = _predict_rotation(parent[3:], turn[index], sign[index])
        nodes[3:, joint] = short(rotation + rotation_residual[index])
        position = _predict_position(parent[:3], parent[3:], offsets[index])
        nodes[:3, joint] = short(position + position_residual[index])
    out = np.empty((span, frame_bytes(players)), np.uint8)
    out[:, :HEAD_BYTES] = np.ascontiguousarray(head.T).astype('<i4').view(np.uint8)
    nodes_end = HEAD_BYTES + players * JOINTS * 14
    out[:, HEAD_BYTES:nodes_end] = (
        np.ascontiguousarray(nodes.transpose(3, 2, 1, 0))
        .astype('<i2')
        .reshape(span, -1)
        .view(np.uint8)
    )
    out[:, nodes_end:] = tail.T
    return out[start - first :]
