# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The moments of a recording, the events that a search finds and captions read.

The page names what happens in a match with the event catalog of the team presentation contract,
`web/js/presentation/catalog.js`, and takes its moments from it in `web/js/recording/moments.js`.
This module follows the same rules, version 1 of each, for the kinds of moments, so the server's
index and the page agree on every moment, its id, its step, its time and its data. The arithmetic
follows the page's step by step, in double precision over the positions that the page keeps as 32
bit floats, and a test holds the two to each other on the shipped samples.

A moment is a dictionary with the `id`, `kind`, `step` and `t` of its event, the `team` and
`player` where it has them, as indices of the header, and the `data` that `MOMENT_DATA` names for
its kind, with the outcome that later frames settle merged in.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

import numpy as np

# The version of the moments, which `web/js/recording/moments.js` names `MOMENTS_VERSION`.
VERSION = 1

KINDS = (
    'goal',
    'shot',
    'save',
    'block',
    'woodwork',
    'nearMiss',
    'pass',
    'tackle',
    'foul',
    'card',
    'offside',
    'restart',
    'possession',
    'halftime',
    'fulltime',
)
MOMENT_DATA = {
    'goal': (
        'scoringTeam',
        'score',
        'scorer',
        'assist',
        'ownGoal',
        'certain',
        'passes',
        'solo',
        'lastAction',
        'distance',
    ),
    'shot': ('distance', 'angle', 'quality', 'header', 'onTarget', 'outcome', 'keeper', 'stopper'),
    'save': ('style', 'side', 'shooter', 'saved'),
    'block': ('shooter',),
    'woodwork': ('part', 'goalSide', 'shooter'),
    'nearMiss': ('line', 'margin', 'goalSide', 'shooter'),
    'pass': ('type', 'outcome', 'receiver'),
    'tackle': ('won', 'touched'),
    'foul': ('offender', 'victim', 'type'),
    'card': ('colour', 'second'),
    'offside': (),
    'restart': ('restart', 'taker'),
    'possession': ('from', 'to', 'fromTeam', 'toTeam'),
    'halftime': ('score',),
    'fulltime': ('winner', 'draw', 'score'),
}

# GRF's kinds of animation, as the action bytes of a frame hold them.
_NONE, _MOVEMENT, _BALL_CONTROL, _TRAP = 0, 1, 2, 3
_SHORT_PASS, _LONG_PASS, _HIGH_PASS, _HEADER, _SHOT = 4, 5, 6, 7, 8
_DEFLECT, _CATCH, _INTERFERE, _SLIDING = 9, 10, 11, 13
_ACTION_NAMES = (
    'none',
    'movement',
    'ballControl',
    'trap',
    'shortPass',
    'longPass',
    'highPass',
    'header',
    'shot',
    'deflect',
    'catch',
    'interfere',
    'trip',
    'sliding',
    'special',
)
# The touch bytes, one more than GRF's kind of touch.
_KICKED, _NON_KICKED, _ACCIDENTAL = 1, 2, 3
_PASSES = {_SHORT_PASS: 'short', _LONG_PASS: 'long', _HIGH_PASS: 'high'}
_SAVES = (_CATCH, _DEFLECT, _INTERFERE, _BALL_CONTROL, _TRAP)
_CATCHES = (_CATCH, _BALL_CONTROL, _TRAP)
_RESTARTS = (None, 'kickoff', 'goal_kick', 'free_kick', 'corner', 'throw_in', 'penalty')
_FOULS = (None, 'foul', 'yellow', 'red')

# GRF's pitch, the goal lines 55 meters either side of the center, the touch lines at 36, the
# posts 3.66 meters either side of the middle of the goal line and the bar at 2.44.
_HALF_W, _HALF_H, _POST_Y, _BAR_Z = 55.0, 36.0, 3.66, 2.44
_BACK_SECONDS = 15
_EPISODE_END, _EPISODE_START = 1, 2
_MAX_BLEND_GAP = 10
_FRAME_HEAD = 76
_POSITION_UNIT = 1 / 500


def _hash(text: str) -> str:
    """Returns FNV 1a over the UTF 16 code units of `text`, as eight hexadecimal digits."""
    value = 0x811C9DC5
    for unit in memoryview(text.encode('utf-16-le')).cast('H'):
        value ^= unit
        value = (value * 0x01000193) & 0xFFFFFFFF
    return f'{value:08x}'


def _key(part: Any) -> str:
    """Returns one part of an event key as JavaScript joins it into text."""
    if isinstance(part, bool):
        return 'true' if part else 'false'
    return str(part)


def event_id(kind: str, step: int, key: list[Any]) -> str:
    """Returns the id of an event, from its kind, its step and the players or team it names."""
    text = f'{kind}|{step}|{",".join(_key(part) for part in key)}'
    return f'{kind}:{step}:{_hash(text)}'


def _round(value: float, places: int = 3) -> float | int:
    """Rounds as the page does, half up, and gives a whole number as an integer like JSON."""
    scale = 10.0**places
    result = math.floor(value * scale + 0.5) / scale
    return int(result) if result == int(result) else result


def _sign(value: float) -> float:
    return 0.0 if value == 0 else math.copysign(1.0, value)


class _Frame:
    """The fields of one frame that the rules read, as the page's reader gives them."""

    __slots__ = (
        'actions',
        'ball',
        'clock',
        'flags',
        'foul',
        'left',
        'mode',
        'offside',
        'owned_player',
        'owned_team',
        'player_flags',
        'right',
        'roots',
        'step',
        'touches',
    )


def _frames(header: dict[str, Any], frames: Iterable[bytes]) -> list[_Frame]:
    """Returns the frames of a recording as the rules read them, a thousand at a time."""
    out: list[_Frame] = []
    chunk: list[bytes] = []
    for frame in frames:
        chunk.append(frame)
        if len(chunk) == _CHUNK_FRAMES:
            out += _parse(header, chunk)
            chunk = []
    return out + _parse(header, chunk)


# The frames that `_frames` turns into lists at once.
_CHUNK_FRAMES = 1000


def _parse(header: dict[str, Any], frames: list[bytes]) -> list[_Frame]:
    """Returns frames of a recording as the rules read them, a whole frame alone for each."""
    players = len(header['players'])
    size = _FRAME_HEAD + players * 196 + 3 * (-(-players // 4) * 4)
    data = b''.join(frame for frame in frames if len(frame) == size)
    count = len(data) // size
    raw = np.frombuffer(data, dtype=np.uint8, count=count * size).reshape(count, size)
    ints = raw[:, :32].copy().view('<i4').tolist()
    ball = raw[:, 32:44].copy().view('<f4').astype(np.float64).tolist()
    referee = raw[:, 60:76].copy().view('<i4').tolist()
    nodes = raw[:, _FRAME_HEAD : _FRAME_HEAD + players * 196].copy().view('<i2')
    roots = nodes.reshape(count, players, 98)[:, :, :3].astype(np.float64) * _POSITION_UNIT
    roots = roots.astype(np.float32).astype(np.float64).tolist()
    padded = -(-players // 4) * 4
    at = _FRAME_HEAD + players * 196
    flags = raw[:, at : at + players].tolist()
    actions = raw[:, at + padded : at + padded + players].tolist()
    touches = raw[:, at + 2 * padded : at + 2 * padded + players].tolist()
    out = []
    for index in range(count):
        frame = _Frame()
        (
            frame.step,
            frame.mode,
            frame.left,
            frame.right,
            frame.owned_team,
            frame.owned_player,
            frame.clock,
            frame.flags,
        ) = ints[index]
        frame.ball = ball[index][:3]
        frame.foul = referee[index][:3]
        frame.offside = referee[index][3]
        frame.roots = roots[index]
        frame.player_flags = flags[index]
        frame.actions = actions[index]
        frame.touches = touches[index]
        out.append(frame)
    return out


def _boundary(a: _Frame, b: _Frame) -> bool:
    return bool(a.flags & _EPISODE_END) or bool(b.flags & _EPISODE_START) or b.step <= a.step


def _cut(a: _Frame, b: _Frame) -> bool:
    return _boundary(a, b) or b.step - a.step > _MAX_BLEND_GAP


def _intentional(touch: int) -> bool:
    return touch in (_KICKED, _NON_KICKED)


class _Event(dict):
    """An event of the catalog, as a dictionary, with the resolves that settle it later."""


class _Analysis:
    """The rules of the catalog over the frames of one recording, a step at a time.

    Each method follows the method of the same purpose of the page's `Analysis`, named in its
    docstring, and reads the frames in the same order.
    """

    def __init__(self, header: dict[str, Any], frames: list[_Frame]) -> None:
        self.header = header
        self.frames = frames
        self.players = header['players']
        self.n = len(self.players)
        self.sps = header.get('steps_per_second') or 10
        self.last = len(frames) - 1
        self.shot_cache: dict[int, list[dict[str, Any]]] = {}
        self.ring_cache: dict[int, bool] = {}

    def get(self, j: int) -> _Frame | None:
        return self.frames[j] if 0 <= j <= self.last else None

    def team_of(self, k: int) -> int:
        return self.players[k]['team']

    def event(self, kind: str, i: int, **fields: Any) -> _Event:
        """Returns an event in the shape of the page's `event`."""
        player = fields.get('player')
        team = fields.get('team')
        key = fields.get('key')
        if key is None:
            key = [player] if player is not None and player >= 0 else [f'team{_key_team(team)}']
        event = _Event(id=event_id(kind, i, key), kind=kind, step=i)
        event['t'] = fields['t'] if fields.get('t') is not None else i / self.sps
        if team is not None and team >= 0:
            event['team'] = team
        if player is not None and player >= 0:
            event['player'] = player
        event['data'] = dict(fields.get('data') or {})
        event['later'] = []
        return event

    def resolve(self, event: _Event, due: int, data: dict[str, Any], player: int = -1) -> None:
        """Keeps a resolve of `event` that the frames settle at step `due`."""
        event['later'].append((due, data, player))

    # The contact moment, `contactEstimate`.

    def contact(self, i: int) -> tuple[float, list[float]]:
        """Returns the estimated contact time of a touch flagged on step `i`, and its point."""
        sps = self.sps
        c = self.get(i)
        b = self.get(i - 1)
        if b is None or _cut(b, c):
            return i / sps, c.ball
        a = self.get(i - 2)
        d = self.get(i + 1)
        joined_in = a is not None and not _cut(a, b)
        joined_out = d is not None and not _cut(c, d)
        pb, pc = b.ball, c.ball
        if joined_in and joined_out:
            pa, pd = a.ball, d.ball
            vin = [pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]]
            vout = [pd[0] - pc[0], pd[1] - pc[1], pd[2] - pc[2]]
            offset = [pb[n] - pc[n] + vout[n] for n in range(3)]
            slope = [vin[n] - vout[n] for n in range(3)]
            denom = slope[0] ** 2 + slope[1] ** 2 + slope[2] ** 2
            if denom > 1e-8:
                u = -(offset[0] * slope[0] + offset[1] * slope[1] + offset[2] * slope[2]) / denom
                fraction = min(1.0, max(0.0, u))
                point = [
                    (pb[n] + vin[n] * fraction + pc[n] + vout[n] * (fraction - 1)) / 2
                    for n in range(3)
                ]
                return self.contact_result(i, fraction, point)

        def bend(p: list[float], q: list[float], r: list[float]) -> float:
            return math.hypot(*(q[n] - p[n] - (r[n] - q[n]) for n in range(3)))

        bend_b = bend(a.ball, pb, pc) if joined_in else -1
        bend_c = bend(pb, pc, d.ball) if joined_out else -1
        fraction = 0 if bend_b > bend_c else 1
        return self.contact_result(i, fraction, pc if fraction else pb)

    def contact_result(self, i: int, fraction: float, point: list[float]) -> tuple[float, Any]:
        return (i - 1 + fraction) / self.sps, [_round(x, 4) for x in point]

    def velocity(self, a: _Frame, b: _Frame) -> list[float]:
        return [(b.ball[n] - a.ball[n]) * self.sps for n in range(3)]

    def touch(self, i: int, k: int) -> dict[str, Any]:
        """Returns what the rules read of a touch by player `k` at step `i`, `touchEvent`."""
        f = self.frames[i]
        a, b, d = self.get(i - 2), self.get(i - 1), self.get(i + 1)
        joined_in = a is not None and b is not None and not _cut(a, b) and not _cut(b, f)
        joined_out = d is not None and not _cut(f, d)
        t, point = self.contact(i)
        return {
            't': t,
            'point': point,
            'velocity_in': [_round(x) for x in self.velocity(a, b)] if joined_in else None,
            'velocity_out': [_round(x) for x in self.velocity(f, d)] if joined_out else None,
        }

    # Section 4.1, `frameStep`, for the kinds of moments.

    def frame_step(self, i: int, f: _Frame, p: _Frame | None, joined: bool) -> list[_Event]:
        out = []
        n = self.n
        header = self.header
        score = [f.left, f.right]
        if joined and header.get('second_half') is not None:
            threshold = header['second_half'] * 1800
            if p.clock < threshold <= f.clock:
                out.append(self.event('halftime', i, data={'score': score}))
        if joined:
            if f.owned_player != p.owned_player or f.owned_team != p.owned_team:
                out.append(
                    self.event(
                        'possession',
                        i,
                        key=[p.owned_player, f.owned_player],
                        player=f.owned_player,
                        team=f.owned_team,
                        data={
                            'from': p.owned_player,
                            'to': f.owned_player,
                            'fromTeam': p.owned_team,
                            'toTeam': f.owned_team,
                        },
                    )
                )
            if f.left > p.left or f.right > p.right:
                team = 0 if f.left > p.left else 1
                bits = (f.flags >> 8) & 31 if header.get('engine_scorer') else 0
                scorer = bits - 1 if 0 < bits <= n else -1
                data: dict[str, Any] = {'scoringTeam': team, 'score': score}
                if scorer >= 0:
                    data['scorer'] = scorer
                out.append(
                    self.event('goal', i, key=[f'team{team}'], team=team, player=scorer, data=data)
                )
            kind, offender, victim = f.foul[2], f.foul[0], f.foul[1]
            if kind > 0 and (p.foul[2] == 0 or p.foul[0] != offender or p.foul[2] != kind):
                out.append(
                    self.event(
                        'foul',
                        i,
                        key=[offender, victim],
                        player=offender,
                        team=self.team_of(offender) if 0 <= offender < n else -1,
                        data={
                            'offender': offender,
                            'victim': victim,
                            'type': (_FOULS[kind] if 0 <= kind < len(_FOULS) else None) or 'foul',
                        },
                    )
                )
            for k in range(n):
                was, now = p.player_flags[k], f.player_flags[k]
                if was == now:
                    continue
                if (now & 4) and not (was & 4):
                    data = {'colour': 'red', 'second': bool(was & 2)}
                    out.append(self.event('card', i, player=k, team=self.team_of(k), data=data))
                elif (now & 2) and not (was & 2):
                    data = {'colour': 'yellow', 'second': False}
                    out.append(self.event('card', i, player=k, team=self.team_of(k), data=data))
            if (
                header.get('offside_called')
                and (f.flags & 4)
                and not (p.flags & 4)
                and 0 <= f.offside < n
            ):
                out.append(self.event('offside', i, player=f.offside, team=self.team_of(f.offside)))
            if f.mode > 0 and f.mode != p.mode:
                taker = self.taker_of(i)
                out.append(
                    self.event(
                        'restart.begin',
                        i,
                        key=[f'mode{f.mode}'],
                        player=taker,
                        team=self.team_of(taker) if taker >= 0 else -1,
                        data={
                            'restart': (_RESTARTS[f.mode] if f.mode < len(_RESTARTS) else None)
                            or 'kickoff',
                            'taker': taker,
                        },
                    )
                )
        flagged = bool(f.flags & _EPISODE_END)
        if flagged and header.get('full_match') is True:
            winner = None if f.left == f.right else (0 if f.left > f.right else 1)
            out.append(
                self.event(
                    'fulltime',
                    i,
                    team=-1 if winner is None else winner,
                    data={'winner': winner, 'draw': winner is None, 'score': score},
                )
            )
        return out

    def taker_of(self, i: int) -> int:
        """Returns the first owner or toucher after a restart begins at step `i`, `takerOf`."""
        for j in range(i, i + 26):
            f = self.get(j)
            if f is None:
                break
            if 0 <= f.owned_player < self.n:
                return f.owned_player
            for k in range(self.n):
                if f.touches[k]:
                    return k
        return -1

    # Section 4.2, `inferStep`, for the kinds of moments.

    def infer_step(
        self, i: int, f: _Frame, p: _Frame | None, joined: bool, frame: list[_Event]
    ) -> list[_Event]:
        out: list[_Event] = []
        touches = [k for k in range(self.n) if f.touches[k]]
        details = {k: self.touch(i, k) for k in touches}
        for k in touches:
            if joined and p.touches[k] and p.actions[k] == f.actions[k]:
                continue
            self.infer_touch(i, k, f, details[k], out)
        if joined:
            for k in range(self.n):
                sliding = f.actions[k] == _SLIDING and p.actions[k] != _SLIDING
                if sliding and (f.player_flags[k] & 1):
                    self.infer_slide(i, k, out)
        if self.rings_at(i) and not self.rings_at(i - 1):
            self.infer_woodwork(i, f, out)
        if joined:
            self.infer_near_miss(i, p, f, out)
            goal = next((event for event in frame if event['kind'] == 'goal'), None)
            if goal is not None:
                self.enrich_goal(i, goal)
        for k in touches:
            self.infer_stop(i, k, details[k], out)
        return out

    def infer_touch(
        self, i: int, k: int, f: _Frame, touch: dict[str, Any], out: list[_Event]
    ) -> None:
        team = self.team_of(k)
        action = f.actions[k]
        if _intentional(f.touches[k]) and action in _PASSES:
            event = self.event(
                'pass',
                i,
                player=k,
                team=team,
                t=touch['t'],
                data={'type': _PASSES[action], 'outcome': 'pending'},
            )
            out.append(event)
            settled = self.follow_pass(i, k, team)
            if settled is not None:
                due, outcome, receiver = settled
                self.resolve(event, due, {'outcome': outcome, 'receiver': receiver})
        shot = next((item for item in self.shots_at(i) if item['k'] == k), None)
        if shot is not None:
            out.append(shot['event'])
            follow = shot['follow']
            if follow['due'] is not None:
                keeper = follow['keeper']
                self.resolve(
                    shot['event'],
                    follow['due'],
                    {
                        'onTarget': follow['onTarget'],
                        'outcome': follow['outcome'],
                        'keeper': keeper['k'] if keeper else -1,
                        'stopper': follow['stopper'],
                    },
                )

    def follow_pass(self, i: int, k: int, team: int) -> tuple[int, str, int] | None:
        """Returns the step, outcome and receiver that settle a pass, `followPass`."""
        prev = self.get(i)
        for j in range(i + 1, i + 10 * self.sps + 1):
            f = self.get(j)
            if f is None or _cut(prev, f):
                return (j, 'stopped', -1) if f is not None else None
            for m in range(self.n):
                if f.touches[m] and m != k:
                    return j, 'complete' if self.team_of(m) == team else 'intercepted', m
            stops = (
                (f.mode != 0 and prev.mode == 0)
                or (f.foul[2] > 0 and prev.foul[2] == 0)
                or f.left != prev.left
                or f.right != prev.right
            )
            if stops:
                b, c = prev.ball, f.ball
                gone = (
                    abs(b[0]) > _HALF_W
                    or abs(b[1]) > _HALF_H
                    or abs(c[0]) > _HALF_W
                    or abs(c[1]) > _HALF_H
                )
                return j, 'out' if gone else 'stopped', -1
            prev = f
        return None

    def headed_at_goal(self, i: int, team: int) -> bool:
        """Whether a header at step `i` sends the ball at the goal, `headedAtGoal`."""
        a, m, b = self.get(i), self.get(i + 1), self.get(i + 2)
        if a is None or m is None or b is None or _cut(a, m) or _cut(m, b):
            return False
        goal_x = _HALF_W if team == 0 else -_HALF_W
        vx = (b.ball[0] - a.ball[0]) * self.sps / 2
        return _sign(vx) == _sign(goal_x) and abs(vx) > 3 and abs(goal_x - a.ball[0]) < 30

    def shots_at(self, i: int) -> list[dict[str, Any]]:
        """Returns the shots of step `i`, `findShots`, computed once."""
        if i in self.shot_cache:
            return self.shot_cache[i]
        found: list[dict[str, Any]] = []
        f, p = self.get(i), self.get(i - 1)
        if f is not None:
            joined = p is not None and not _cut(p, f)
            for k in range(self.n):
                kind, action = f.touches[k], f.actions[k]
                if not _intentional(kind) or (joined and p.touches[k] and p.actions[k] == action):
                    continue
                team = self.team_of(k)
                if action == _SHOT or (action == _HEADER and self.headed_at_goal(i, team)):
                    found.append(self.make_shot(i, k, team, action, self.touch(i, k)))
        self.shot_cache[i] = found
        return found

    def make_shot(
        self, i: int, k: int, team: int, action: int, touch: dict[str, Any]
    ) -> dict[str, Any]:
        goal_x = _HALF_W if team == 0 else -_HALF_W
        cp = touch['point']
        dx = abs(goal_x - cp[0])
        distance = math.hypot(dx, cp[1])
        angle = math.atan2(abs(cp[1]), dx) * 180 / math.pi
        left = math.atan2(_POST_Y - cp[1], dx)
        right = math.atan2(-_POST_Y - cp[1], dx)
        mouth = abs(left - right)
        quality = 1 / (1 + math.exp(-(-1.1 + 1.6 * mouth - 0.1 * distance)))
        if action == _HEADER:
            quality *= 0.6
        event = self.event(
            'shot',
            i,
            player=k,
            team=team,
            t=touch['t'],
            data={
                'distance': _round(distance, 2),
                'angle': _round(angle, 1),
                'quality': _round(quality, 3),
                'header': action == _HEADER,
                'onTarget': None,
                'outcome': 'pending',
            },
        )
        return {
            'i': i,
            'k': k,
            'team': team,
            'event': event,
            'follow': self.follow_shot(i, k, team),
        }

    def heads_in_goal(self, a: _Frame, b: _Frame, goal_x: float, margin: float) -> bool:
        """Whether the ball from `a` to `b` would go in within two seconds, `headsInGoal`."""
        sps = self.sps
        vx = (b.ball[0] - a.ball[0]) * sps
        if _sign(vx) != _sign(goal_x) or abs(vx) < 1:
            return False
        t = (goal_x - b.ball[0]) / vx
        if t < 0 or t > 2:
            return False
        y = b.ball[1] + (b.ball[1] - a.ball[1]) * sps * t
        z = b.ball[2] + (b.ball[2] - a.ball[2]) * sps * t - 4.9 * t * t
        return abs(y) < _POST_Y + margin and z < _BAR_Z + margin

    def score_of(self, f: _Frame, team: int) -> int:
        return f.left if team == 0 else f.right

    def follow_shot(self, i: int, k: int, team: int) -> dict[str, Any]:
        """Returns how a shot from step `i` ends and the step that settles it, `followShot`."""
        goal_x = _HALF_W if team == 0 else -_HALF_W
        end = i + 4 * self.sps
        out: dict[str, Any] = {
            'onTarget': False,
            'outcome': 'none',
            'due': None,
            'keeper': None,
            'stopper': -1,
            'woodwork': False,
        }
        prev = self.get(i)
        for j in range(i + 1, end + 1):
            f = self.get(j)
            if f is None or _cut(prev, f):
                if f is not None:
                    out.update(outcome='woodwork' if out['woodwork'] else 'stopped', due=j)
                return out
            if self.rings_at(j):
                out['woodwork'] = True
            if self.score_of(f, team) > self.score_of(prev, team):
                out.update(onTarget=True, outcome='goal', due=j)
                return out
            x0, x1 = prev.ball[0], f.ball[0]
            if abs(x1) >= _HALF_W and _sign(x1) == _sign(goal_x) and abs(x0) < _HALF_W:
                w = (abs(goal_x) - abs(x0)) / max(1e-6, abs(x1 - x0))
                y = prev.ball[1] + (f.ball[1] - prev.ball[1]) * w
                z = prev.ball[2] + (f.ball[2] - prev.ball[2]) * w
                out['onTarget'] = abs(y) < _POST_Y and z < _BAR_Z
                for g in range(j, j + 4):
                    gf = self.get(g)
                    if gf is not None and self.score_of(gf, team) > self.score_of(prev, team):
                        out.update(onTarget=True, outcome='goal', due=g)
                        return out
                missed = 'wide' if abs(y) >= _POST_Y else 'over'
                out.update(outcome='woodwork' if out['woodwork'] else missed, due=j)
                return out
            for m in range(self.n):
                if not f.touches[m] or (
                    m == k and prev.touches[m] and prev.actions[m] == f.actions[m]
                ):
                    continue
                player = self.players[m]
                if player.get('goalkeeper') and player['team'] != team:
                    a = self.get(max(i, j - 2))
                    b = prev if j - 1 > i else f
                    out['onTarget'] = self.heads_in_goal(a, b, goal_x, 0.5)
                    out['keeper'] = {
                        'i': j,
                        'k': m,
                        'action': f.actions[m],
                        'heading': out['onTarget'],
                    }
                    goal, due = self.after_keeper(j, m, team)
                    if goal >= 0:
                        out.update(onTarget=True, outcome='goal', due=goal)
                        return out
                    saved = out['onTarget'] and j - i <= 2 * self.sps and f.actions[m] in _SAVES
                    outcome = 'saved' if saved else ('woodwork' if out['woodwork'] else 'keeper')
                    out.update(outcome=outcome, due=due if saved else j, stopper=m)
                    return out
                blocked = 'blocked' if player['team'] != team else 'redirected'
                out.update(outcome='woodwork' if out['woodwork'] else blocked, due=j, stopper=m)
                return out
            if f.mode != 0 and prev.mode == 0:
                out.update(outcome='woodwork' if out['woodwork'] else 'stopped', due=j)
                return out
            prev = f
        if self.get(end) is not None:
            out.update(outcome='woodwork' if out['woodwork'] else 'none', due=end)
        return out

    def after_keeper(self, i: int, keeper: int, team: int) -> tuple[int, int]:
        """Returns the step of a goal after a keeper's touch, or -1, and the step that settles it,
        `afterKeeper`."""
        before = self.score_of(self.get(i - 1) or self.get(i), team)
        prev = self.get(i)
        end = i + 3 * self.sps
        for j in range(i + 1, end + 1):
            f = self.get(j)
            if f is None or _cut(prev, f):
                return -1, j if f is not None else i
            if self.score_of(f, team) > before:
                return j, j
            for m in range(self.n):
                if f.touches[m] and m != keeper:
                    return -1, j
            prev = f
        return -1, end

    def infer_stop(self, i: int, k: int, touch: dict[str, Any], out: list[_Event]) -> None:
        """Finds the save or block of an earlier shot that a touch at step `i` makes,
        `inferStop`."""
        for s in range(i - 1, max(0, i - 4 * self.sps) - 1, -1):
            for shot in self.shots_at(s):
                follow = shot['follow']
                keeper = follow['keeper']
                if keeper and keeper['i'] == i and keeper['k'] == k:
                    if keeper['heading'] and keeper['action'] in _SAVES and i - s <= 2 * self.sps:
                        out.append(self.save_event(i, k, shot, touch))
                    return
                if follow['stopper'] == k and follow['outcome'] == 'blocked' and follow['due'] == i:
                    out.append(
                        self.event(
                            'block',
                            i,
                            player=k,
                            team=self.team_of(k),
                            t=touch['t'],
                            data={'shooter': shot['k']},
                        )
                    )
                    return

    def save_event(self, i: int, k: int, shot: dict[str, Any], touch: dict[str, Any]) -> _Event:
        """Returns a save by the keeper `k` at step `i`, `saveEvent`."""
        f = self.get(i)
        before = self.get(shot['i']) or f
        team = self.team_of(k)
        dive = touch['point'][1] - before.roots[k][1]
        facing = 1 if team == 0 else -1
        side = 'centre' if abs(dive) < 0.3 else ('left' if dive * facing > 0 else 'right')
        event = self.event(
            'save',
            i,
            player=k,
            team=team,
            t=touch['t'],
            data={
                'style': 'catch' if f.actions[k] in _CATCHES else 'parry',
                'side': side,
                'shooter': shot['k'],
                'saved': 'pending',
            },
        )
        goal, due = self.after_keeper(i, k, shot['team'])
        self.resolve(event, due, {'saved': goal < 0})
        return event

    def infer_slide(self, i: int, k: int, out: list[_Event]) -> None:
        """Adds a slide that player `k` begins at step `i` and whether it won the ball,
        `inferSlide`."""
        team = self.team_of(k)
        event = self.event('slide', i, player=k, team=team, data={'won': 'pending'})
        out.append(event)
        prev = self.get(i)
        touched = ended = -1
        for j in range(i, i + 3 * self.sps + 1):
            f = self.get(j)
            if f is None or (j > i and _cut(prev, f)):
                ended = j if f is not None else -1
                break
            if f.touches[k]:
                touched = j
                break
            if f.actions[k] != _SLIDING:
                ended = j
                break
            prev = f
        if touched < 0:
            if ended >= 0:
                self.resolve(event, ended, {'won': False, 'touched': False})
            return
        prev = self.get(touched)
        for j in range(touched, touched + 3 * self.sps + 1):
            f = self.get(j)
            if f is None:
                return
            if j > touched and _cut(prev, f):
                self.resolve(event, j, {'won': False, 'touched': True})
                return
            won = None
            if j > touched and f.owned_team >= 0:
                won = f.owned_team == team
            elif j > touched:
                for m in range(self.n):
                    if f.touches[m] and m != k:
                        won = self.team_of(m) == team
                        break
            if won is not None:
                self.resolve(event, j, {'won': won, 'touched': True})
                return
            prev = f
        self.resolve(event, touched + 3 * self.sps, {'won': False, 'touched': True})

    def rings_at(self, i: int) -> bool:
        """Whether the ball rings off the frame of a goal at step `i`, `ringsAt`."""
        if i in self.ring_cache:
            return self.ring_cache[i]
        self.ring_cache[i] = result = self._rings(i)
        return result

    def _rings(self, i: int) -> bool:
        a, b, c = self.get(i - 1), self.get(i), self.get(i + 1)
        if a is None or b is None or c is None or _cut(a, b) or _cut(b, c):
            return False
        if any(b.touches[m] or c.touches[m] for m in range(self.n)):
            return False
        sps = self.sps
        v1x = (b.ball[0] - a.ball[0]) * sps
        v1y = (b.ball[1] - a.ball[1]) * sps
        v2x = (c.ball[0] - b.ball[0]) * sps
        v2y = (c.ball[1] - b.ball[1]) * sps
        jump = math.hypot(v2x - v1x, v2y - v1y)
        bx, by, bz = abs(b.ball[0]), abs(b.ball[1]), b.ball[2]
        near = (
            abs(bx - _HALF_W) < 0.6
            and bz < 2.7
            and (abs(by - 3.7) < 0.6 or (by < 3.9 and bz > 2.1))
        )
        return jump > 4.5 and near

    def last_toucher(self, i: int) -> int:
        """Returns the last player to touch the ball up to step `i`, `lastToucher`."""
        for j in range(i, max(0, i - 4 * self.sps) - 1, -1):
            f = self.get(j)
            if f is None:
                break
            for m in range(self.n):
                if f.touches[m]:
                    return m
        return -1

    def infer_woodwork(self, i: int, f: _Frame, out: list[_Event]) -> None:
        b = f.ball
        side = _sign(b[0]) or 1.0
        part = (
            'bar'
            if abs(b[1]) < 3.9 and b[2] > 2.1
            else ('leftPost' if b[1] * side > 0 else 'rightPost')
        )
        shooter = self.last_toucher(i)
        team = self.team_of(shooter) if shooter >= 0 else (0 if side > 0 else 1)
        out.append(
            self.event(
                'woodwork',
                i,
                key=[f'side{int(side)}'],
                player=shooter,
                team=team,
                data={'part': part, 'goalSide': int(side), 'shooter': shooter},
            )
        )

    def infer_near_miss(self, i: int, a: _Frame, b: _Frame, out: list[_Event]) -> None:
        ax, bx = abs(a.ball[0]), abs(b.ball[0])
        speed = abs(b.ball[0] - a.ball[0]) * self.sps
        if (
            ax > _HALF_W
            or bx <= _HALF_W
            or speed < 8
            or speed > 60
            or _sign(a.ball[0]) != _sign(b.ball[0])
        ):
            return
        w = (_HALF_W - ax) / max(1e-6, bx - ax)
        y = abs(a.ball[1] + (b.ball[1] - a.ball[1]) * w)
        z = a.ball[2] + (b.ball[2] - a.ball[2]) * w
        wide = 3.9 < y < 7 and z < 3.5
        over = y <= 3.9 and 2.6 < z < 4.5
        if not wide and not over:
            return
        side = int(_sign(b.ball[0]))
        shooter = self.last_toucher(i)
        team = self.team_of(shooter) if shooter >= 0 else (0 if side > 0 else 1)
        out.append(
            self.event(
                'nearMiss',
                i,
                key=[f'side{side}'],
                player=shooter,
                team=team,
                data={
                    'line': 'wide' if wide else 'over',
                    'margin': _round(y - _POST_Y if wide else z - _BAR_Z, 2),
                    'goalSide': side,
                    'shooter': shooter,
                },
            )
        )

    def touch_starts(self, start: int, stop: int) -> list[dict[str, int]]:
        """Returns the touches that start a run of one player and action, `touchStarts`."""
        found = []
        prev = None
        for i in range(start, stop + 1):
            f = self.get(i)
            if f is None:
                prev = None
                continue
            joined = prev is not None and not _cut(prev, f)
            for k in range(self.n):
                touch = f.touches[k]
                if not touch or (joined and prev.touches[k] and prev.actions[k] == f.actions[k]):
                    continue
                found.append(
                    {
                        'i': i,
                        'k': k,
                        'team': self.team_of(k),
                        'action': f.actions[k],
                        'touch': touch,
                    }
                )
            prev = f
        return found

    def enrich_goal(self, i: int, goal: _Event) -> None:
        """Keeps the resolve of a goal with its scorer, assist and manner, `enrichGoal`."""
        team = goal['team']
        sps = self.sps
        start = max(0, i - 20 * sps)
        events = self.touch_starts(start, i)
        scorer = at = -1
        s = i - 1
        while s >= max(0, i - 8 * sps) and at < 0:
            for shot in self.shots_at(s):
                if shot['follow']['outcome'] == 'goal' and shot['follow']['due'] == i:
                    scorer = shot['k']
                    at = next(
                        (
                            n
                            for n, e in enumerate(events)
                            if e['i'] == shot['i'] and e['k'] == scorer
                        ),
                        -1,
                    )
            s -= 1
        if scorer < 0:
            last = len(events) - 1
            while last >= 0 and events[last]['touch'] == _ACCIDENTAL:
                last -= 1
            if last >= 0 and events[last]['i'] >= i - 15 * sps:
                at = last
                e = last
                while e >= 0 and events[e]['i'] == events[last]['i']:
                    if events[e]['team'] == team and events[e]['touch'] != _ACCIDENTAL:
                        at = e
                        break
                    e -= 1
                scorer = events[at]['k']
        if scorer < 0:
            for j in range(i - 1, start - 1, -1):
                f = self.get(j)
                if f is not None and 0 <= f.owned_player < self.n:
                    scorer = f.owned_player
                    break
        certain = 'scorer' in goal['data']
        if certain:
            scorer = goal['data']['scorer']
            at = next((n for n in range(len(events) - 1, -1, -1) if events[n]['k'] == scorer), -1)
        own_goal = scorer >= 0 and self.team_of(scorer) != team
        assist = -1
        passes = 0
        solo = False
        if scorer >= 0 and not own_goal and at >= 0:
            t0 = events[at]['i']
            e = at - 1
            while e >= 0 and events[e]['i'] >= t0 - 10 * sps:
                event = events[e]
                e -= 1
                if event['k'] == scorer:
                    continue
                if event['team'] != team:
                    if event['touch'] == _ACCIDENTAL:
                        continue
                    break
                assist = event['k']
                break
            for e in range(at - 1, -1, -1):
                event = events[e]
                if event['team'] != team and event['touch'] != _ACCIDENTAL:
                    break
                if (
                    event['team'] == team
                    and _intentional(event['touch'])
                    and event['action'] in _PASSES
                ):
                    passes += 1
            own = 0
            e = at - 1
            while (
                e >= 0 and events[e]['k'] == scorer and events[e]['i'] >= t0 - _BACK_SECONDS * sps
            ):
                own += 1
                e -= 1
            solo = own >= 2
        data: dict[str, Any] = {
            'scorer': scorer,
            'assist': assist,
            'ownGoal': own_goal,
            'certain': certain,
            'passes': passes,
            'solo': solo,
        }
        if at >= 0:
            e = events[at]
            touch = self.touch(e['i'], e['k'])
            cp = touch['point']
            vin = touch['velocity_in']
            distance = math.hypot((_HALF_W if team == 0 else -_HALF_W) - cp[0], cp[1])
            last_action = _ACTION_NAMES[e['action']] if e['action'] < len(_ACTION_NAMES) else None
            if e['action'] == _HEADER:
                last_action = 'header'
            elif e['touch'] == _KICKED and cp[2] > 0.3 and vin and vin[2] < 0:
                last_action = 'volley'
            elif e['action'] == _SHOT:
                last_action = 'shot'
            data.update(lastAction=last_action, distance=_round(distance, 2))
        self.resolve(goal, i, data, scorer)


def _key_team(team: Any) -> str:
    return '' if team is None else str(team)


def _last_owner(frames: list[_Frame], i: int) -> tuple[int, int] | None:
    """Returns the team and player that last owned the ball before step `i` in its episode."""
    after = frames[i]
    for j in range(i - 1, -1, -1):
        f = frames[j]
        if _cut(f, after):
            return None
        if f.owned_team >= 0:
            return f.owned_team, f.owned_player
        after = f
    return None


_FROM_CATALOG = {'slide': 'tackle', 'restart.begin': 'restart'}


def moments(
    header: dict[str, Any], frames: Iterable[bytes], timing: bool = False
) -> list[dict[str, Any]]:
    """Returns the moments of a recording in the order of their steps, as the page finds them.

    Args:
        header: The header of the recording.
        frames: Its frames, as `_recording.frames` yields them.
        timing: Whether each moment also holds the `clock` of its step in milliseconds and the
            `score` of the left and the right team at that step.
    """
    parsed = _frames(header, frames)
    analysis = _Analysis(header, parsed)
    found: list[dict[str, Any]] = []
    for i, f in enumerate(parsed):
        p = parsed[i - 1] if i > 0 else None
        joined = p is not None and not _cut(p, f)
        frame = analysis.frame_step(i, f, p, joined)
        inferred = analysis.infer_step(i, f, p, joined, frame)
        for event in frame + inferred:
            moment = _moment(parsed, event)
            if moment is not None:
                if timing:
                    moment['clock'] = f.clock
                    moment['score'] = [f.left, f.right]
                found.append(moment)
    return found


def _moment(frames: list[_Frame], event: _Event) -> dict[str, Any] | None:
    """Returns the moment of an event, with the data of its last resolve, or `None`."""
    kind = _FROM_CATALOG.get(event['kind'], event['kind'])
    data = event['data']
    if kind == 'possession':
        if data['toTeam'] < 0 or data['fromTeam'] == data['toTeam']:
            return None
        if data['fromTeam'] >= 0:
            before: tuple[int, int] | None = (data['fromTeam'], data['from'])
        else:
            before = _last_owner(frames, event['step'])
        if before is None or before[0] == data['toTeam']:
            return None
        data = {
            'from': before[1],
            'to': data['to'],
            'fromTeam': before[0],
            'toTeam': data['toTeam'],
        }
    moment = {
        key: event[key] for key in ('id', 'kind', 'step', 't', 'team', 'player') if key in event
    }
    moment['kind'] = kind
    merged = dict(data)
    last = len(frames) - 1
    for due, resolved, player in sorted(event['later'], key=lambda item: item[0]):
        if due <= last:
            merged.update(resolved)
            if player >= 0:
                moment['player'] = player
    moment['data'] = {key: merged[key] for key in MOMENT_DATA[kind] if key in merged}
    return moment
