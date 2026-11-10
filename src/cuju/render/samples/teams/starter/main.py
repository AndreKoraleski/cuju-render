# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""The starter team, a Kaggle submission that cuju ships as a sample of a team.

`agent(obs)` is written as the agent of a Kaggle `main.py` for the GRF competition. It reads
`obs['players_raw'][0]`, GRF's raw observation of the player it controls, and returns a list of one
action of the default action set. The player runs at the ball, carries it toward the right goal and
shoots from close range. Copy this folder to start a team of your own.
"""

import math

# The directions of GRF's default action set, from the right in steps of 45 degrees toward the
# bottom, since y grows toward the bottom of the pitch.
DIRECTIONS = [5, 6, 7, 8, 1, 2, 3, 4]
SHOT = 12


def direction(dx, dy):
    """Returns the action that runs closest to the direction `(dx, dy)`."""
    return DIRECTIONS[round(math.atan2(dy, dx) / (math.pi / 4)) % 8]


def agent(obs):
    """Returns the action of the player of `obs`, as a Kaggle agent does."""
    raw = obs['players_raw'][0]
    x, y = raw['left_team'][raw['active']]
    ball = raw['ball']
    if raw['ball_owned_team'] == 0 and raw['ball_owned_player'] == raw['active']:
        if x > 0.7 and abs(y) < 0.25:
            return [SHOT]
        return [direction(1.0 - x, -y)]
    return [direction(ball[0] - x, ball[1] - y)]
