# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The filters of a recorder, which decide at the end of each episode whether to save it.

A filter reads the summary of the episode, its score, goals, length, rewards and annotations, so it
never touches the batch, and the frames of an episode that it drops are discarded unwritten.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Callable
from typing import Any

from cuju.errors import ArgumentError

# The names that `keep` takes besides a function.
KEEP = ('all', 'goals')


class Filter:
    """Decides from the summary of an ended episode whether a recorder saves it.

    Every condition must hold, the choice or function of `keep`, every `every`-th episode from the
    first, and a return of at least `min_reward`.
    """

    def __init__(
        self,
        keep: str | Callable[[dict[str, Any]], Any] | None = None,
        every: int = 1,
        min_reward: float | None = None,
    ) -> None:
        """Checks and keeps the conditions.

        Raises:
            ArgumentError: If `keep` is neither a function nor one of `KEEP`, `every` is not a
                whole number of at least 1, or `min_reward` is not a finite number.
        """
        if keep is None:
            keep = 'all'
        if not callable(keep) and keep not in KEEP:
            raise ArgumentError(f'expected keep as a function or one of {KEEP}, found {keep!r}')
        if isinstance(every, bool) or not isinstance(every, int) or every < 1:
            raise ArgumentError(f'expected every as a whole number of at least 1, found {every!r}')
        if min_reward is not None and (
            isinstance(min_reward, bool)
            or not isinstance(min_reward, int | float)
            or not math.isfinite(min_reward)
        ):
            raise ArgumentError(f'expected min_reward as a finite number, found {min_reward!r}')
        self.keep = keep
        self.every = every
        self.min_reward = min_reward

    def __call__(self, summary: dict[str, Any]) -> bool:
        """Returns whether to save the episode of `summary`, as `episode_summary` returns it."""
        if summary['episode'] % self.every:
            return False
        if self.min_reward is not None and summary['reward'] < self.min_reward:
            return False
        if self.keep == 'goals':
            return summary['goals'] > 0
        if callable(self.keep):
            return bool(self.keep(summary))
        return True


def step_rewards(batch: Any, environment: int, information: dict[str, Any]) -> list[float]:
    """Returns the reward of each agent of an environment on a step, none when it is not known.

    The rewards are those that the batch hands its step observers, read without a change, and the
    agents count in the batch's order, those of the left team first.

    Args:
        batch: The batch.
        environment: The environment.
        information: What the batch handed its observers for the step.
    """
    rewards = information.get('reward')
    if rewards is None:
        return []
    reward = rewards[environment].reshape(-1)
    mask = batch.agent_mask[environment].reshape(-1)
    return [
        float(value) for value, kept in zip(reward.tolist(), mask.tolist(), strict=True) if kept
    ]


def episode_summary(
    episode: int,
    frames: list[bytes],
    rewards: list[float],
    environment: int,
    annotations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Returns the summary of an episode that a filter reads.

    Args:
        episode: The number of episodes that the recorder ended before this one.
        frames: The frames of the episode.
        rewards: The return of each agent over the captured steps.
        environment: The environment of the recorder.
        annotations: The annotations of the episode, with long keys.
    """
    last = frames[-1]
    score = list(struct.unpack_from('<2i', last, 8))
    (step,) = struct.unpack_from('<i', last, 0)
    return {
        'episode': episode,
        'environment': environment,
        'score': score,
        'goals': sum(score),
        'length': len(frames),
        'steps': step,
        'rewards': list(rewards),
        'reward': sum(rewards),
        'annotations': list(annotations or ()),
    }
