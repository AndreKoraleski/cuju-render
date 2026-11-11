# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The joints of a team's own model, the bones that stand for GRF's nodes.

A team's `model.glb` in its `cuju-team` folder draws its players through GRF's 14 nodes, so each
node it maps names a skinned bone of the model, and `body`, the pelvis, is the one it needs. The
team editor saves that mapping in `team.json` under `model.joints`. A folder that brings a model
without one gets the mapping the editor would guess from the bone names, Mixamo's first and then a
few other common rigs, as `guessJoints` of `web/js/players/players.js` does, so an import and
`cuju render pack check` read the same model the same way.
"""

from __future__ import annotations

import re
from typing import Any

from cuju.errors import ArgumentError

# GRF's nodes in their order, the player's root first.
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
# Common rig names of each node, as web/js/players/players.js lists them.
RIG_NAMES = {
    'player': ('root', 'Root', 'Armature'),
    'body': ('Hips', 'hips', 'pelvis', 'Pelvis'),
    'middle': ('Spine2', 'Spine1', 'spine_02', 'Chest', 'chest', 'Spine', 'spine'),
    'neck': ('Neck', 'neck', 'neck_01', 'Head', 'head'),
    'left_shoulder': ('LeftArm', 'upperarm_l', 'UpperArm.L', 'upper_arm.L', 'LeftUpperArm'),
    'left_elbow': ('LeftForeArm', 'lowerarm_l', 'LowerArm.L', 'forearm.L', 'LeftLowerArm'),
    'right_shoulder': ('RightArm', 'upperarm_r', 'UpperArm.R', 'upper_arm.R', 'RightUpperArm'),
    'right_elbow': ('RightForeArm', 'lowerarm_r', 'LowerArm.R', 'forearm.R', 'RightLowerArm'),
    'left_thigh': ('LeftUpLeg', 'thigh_l', 'UpperLeg.L', 'thigh.L', 'LeftUpperLeg'),
    'left_knee': ('LeftLeg', 'calf_l', 'LowerLeg.L', 'shin.L', 'LeftLowerLeg'),
    'left_ankle': ('LeftFoot', 'foot_l', 'Foot.L', 'foot.L'),
    'right_thigh': ('RightUpLeg', 'thigh_r', 'UpperLeg.R', 'thigh.R', 'RightUpperLeg'),
    'right_knee': ('RightLeg', 'calf_r', 'LowerLeg.R', 'shin.R', 'RightLowerLeg'),
    'right_ankle': ('RightFoot', 'foot_r', 'Foot.R', 'foot.R'),
}


def _stripped(name: str) -> str:
    """Returns a bone name without the prefix of Mixamo or of a namespace."""
    name = re.sub(r'^mixamorig\d*[:_]?', '', name, flags=re.IGNORECASE)
    return re.sub(r'^.*[:|]', '', name)


def guess(bones: Any) -> dict[str, str]:
    """Returns the mapping of GRF's nodes that the bone names give, exact names first."""
    names = [bone for bone in bones if isinstance(bone, str)]
    exact = set(names)
    stripped: dict[str, str] = {}
    for bone in names:
        stripped.setdefault(_stripped(bone).lower(), bone)
    joints = {}
    for node in NODES:
        if node in exact:
            joints[node] = node
            continue
        for candidate in RIG_NAMES[node]:
            hit = stripped.get(candidate.lower())
            if hit:
                joints[node] = hit
                break
    return joints


def resolve(joints: Any, bones: set[str]) -> tuple[dict[str, str], bool]:
    """Returns the joints a team's model keeps on import and whether they were guessed.

    Args:
        joints: The `model.joints` of `team.json`, or `None` when it gives none.
        bones: The names of the skinned bones of the model.

    Raises:
        ArgumentError: If the joints map no bone to `body` or name bones the model lacks.
    """
    guessed = not isinstance(joints, dict)
    if guessed:
        joints = guess(sorted(bones))
        if 'body' not in joints:
            raise ArgumentError(
                'expected model.joints in team.json with a bone for body, and no bone of the '
                'model has a name the team editor knows, such as Hips'
            )
    if 'body' not in joints:
        raise ArgumentError('expected model.joints in team.json with a bone for body')
    unknown = sorted(
        str(bone) for bone in joints.values() if not isinstance(bone, str) or bone not in bones
    )
    if unknown:
        raise ArgumentError(f'expected model.joints to name skinned bones, found {unknown[0]}')
    return {str(key): value for key, value in joints.items() if key in NODES}, guessed
