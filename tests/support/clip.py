# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Writes a small celebration clip, a binary glTF file with a skinned skeleton and animations.

The skeleton names its bones as Mixamo does, `mixamorig:Hips` and so on, stands 1.75 meters tall
in glTF's frame, y up and facing z, and its mesh is a handful of triangles between the joints.
The animations wave the right arm and bounce the hips, which also travel a little, so a test sees
both rotation and root motion. Run it as a script to write the clip to a file.
"""

import json
import struct
import sys

# The bones, each its name without the prefix, its parent and its position in meters.
BONES = [
    ('Hips', -1, (0.0, 1.0, 0.0)),
    ('Spine', 0, (0.0, 1.2, 0.0)),
    ('Neck', 1, (0.0, 1.5, 0.0)),
    ('Head', 2, (0.0, 1.62, 0.0)),
    ('LeftArm', 1, (0.18, 1.45, 0.0)),
    ('LeftForeArm', 4, (0.18, 1.15, 0.0)),
    ('RightArm', 1, (-0.18, 1.45, 0.0)),
    ('RightForeArm', 6, (-0.18, 1.15, 0.0)),
    ('LeftUpLeg', 0, (0.09, 0.95, 0.0)),
    ('LeftLeg', 8, (0.09, 0.52, 0.0)),
    ('LeftFoot', 9, (0.09, 0.08, 0.0)),
    ('RightUpLeg', 0, (-0.09, 0.95, 0.0)),
    ('RightLeg', 11, (-0.09, 0.52, 0.0)),
    ('RightFoot', 12, (-0.09, 0.08, 0.0)),
]


def _pad(data, fill=b'\0'):
    return data + fill * (-len(data) % 4)


def clip_bytes(animations=True, skin=True, uri=None, prefix='mixamorig:', names=('Wave', 'Bounce')):
    """Returns the bytes of the clip, with the parts a test may leave out or change.

    Args:
        animations: Whether the file holds its animations.
        skin: Whether the mesh is skinned to the skeleton.
        uri: A link to an outside file that the buffer names, for a test that refuses one.
        prefix: The prefix of every bone name.
        names: The names of the two animations.
    """
    binary = bytearray()
    views = []
    accessors = []

    def add(data, count, kind, component=5126, target=None, minimum=None, maximum=None):
        offset = len(binary)
        binary.extend(_pad(data))
        view = {'buffer': 0, 'byteOffset': offset, 'byteLength': len(data)}
        if target:
            view['target'] = target
        views.append(view)
        accessor = {
            'bufferView': len(views) - 1,
            'componentType': component,
            'count': count,
            'type': kind,
        }
        if minimum is not None:
            accessor['min'], accessor['max'] = minimum, maximum
        accessors.append(accessor)
        return len(accessors) - 1

    # A vertex at every joint and one at each heel on the ground, each following its bone.
    points = [position for _, _, position in BONES]
    owners = list(range(len(BONES)))
    points += [(0.09, 0.0, 0.05), (-0.09, 0.0, 0.05)]
    owners += [10, 13]
    triangles = [
        (0, 1, 2),
        (1, 4, 5),
        (1, 6, 7),
        (0, 8, 9),
        (8, 9, 10),
        (9, 10, 14),
        (0, 11, 12),
        (11, 12, 13),
        (12, 13, 15),
        (2, 3, 1),
    ]
    flat = [value for point in points for value in point]
    position = add(
        struct.pack(f'<{len(flat)}f', *flat),
        len(points),
        'VEC3',
        target=34962,
        minimum=[min(p[i] for p in points) for i in range(3)],
        maximum=[max(p[i] for p in points) for i in range(3)],
    )
    indices = add(
        struct.pack(f'<{3 * len(triangles)}H', *[i for t in triangles for i in t]),
        3 * len(triangles),
        'SCALAR',
        component=5123,
        target=34963,
    )
    attributes = {'POSITION': position}
    if skin:
        joints = add(
            b''.join(struct.pack('<4B', owner, 0, 0, 0) for owner in owners),
            len(points),
            'VEC4',
            component=5121,
            target=34962,
        )
        weights = add(
            struct.pack(f'<{4 * len(points)}f', *([1, 0, 0, 0] * len(points))),
            len(points),
            'VEC4',
            target=34962,
        )
        attributes.update({'JOINTS_0': joints, 'WEIGHTS_0': weights})
        inverse = []
        for _, _, (x, y, z) in BONES:
            inverse += [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -x, -y, -z, 1]
        binds = add(struct.pack(f'<{len(inverse)}f', *inverse), len(BONES), 'MAT4')
    nodes = []
    for index, (name, parent, (x, y, z)) in enumerate(BONES):
        if parent >= 0:
            px, py, pz = BONES[parent][2]
            x, y, z = x - px, y - py, z - pz
        node = {'name': f'{prefix}{name}', 'translation': [x, y, z]}
        children = [child for child, (_, up, _) in enumerate(BONES) if up == index]
        if children:
            node['children'] = children
        nodes.append(node)
    mesh_node = {'name': 'Body', 'mesh': 0}
    if skin:
        mesh_node['skin'] = 0
    nodes.append(mesh_node)
    document = {
        'asset': {'version': '2.0', 'generator': 'cuju tests'},
        'scene': 0,
        'scenes': [{'nodes': [0, len(BONES)]}],
        'nodes': nodes,
        'meshes': [
            {'name': 'Body', 'primitives': [{'attributes': attributes, 'indices': indices}]}
        ],
    }
    if skin:
        document['skins'] = [{'joints': list(range(len(BONES))), 'inverseBindMatrices': binds}]
    if animations:
        times = add(struct.pack('<3f', 0, 0.5, 1), 3, 'SCALAR', minimum=[0], maximum=[1])
        # The right arm swings up to the side and back, a turn about z of the glTF frame.
        raised = struct.pack('<12f', 0, 0, 0, 1, 0, 0, -0.8, 0.6, 0, 0, 0, 1)
        arm = add(raised, 3, 'VEC4')
        # The hips bounce and move forwards by 0.6 meters over the second.
        hips = add(struct.pack('<9f', 0, 1.0, 0, 0, 1.15, 0.3, 0, 1.0, 0.6), 3, 'VEC3')
        document['animations'] = [
            {
                'name': names[0],
                'samplers': [{'input': times, 'output': arm}],
                'channels': [{'sampler': 0, 'target': {'node': 6, 'path': 'rotation'}}],
            },
            {
                'name': names[1],
                'samplers': [{'input': times, 'output': hips}],
                'channels': [{'sampler': 0, 'target': {'node': 0, 'path': 'translation'}}],
            },
        ]
    buffer = {'byteLength': len(binary)}
    if uri:
        buffer['uri'] = uri
    document['buffers'] = [buffer]
    document['bufferViews'] = views
    document['accessors'] = accessors
    text = _pad(json.dumps(document).encode(), b' ')
    chunks = struct.pack('<II', len(text), 0x4E4F534A) + text
    if not uri:
        chunks += struct.pack('<II', len(binary), 0x004E4942) + bytes(binary)
    return b'glTF' + struct.pack('<II', 2, 12 + len(chunks)) + chunks


if __name__ == '__main__':
    with open(sys.argv[1] if len(sys.argv) > 1 else 'clip.glb', 'wb') as stream:
        stream.write(clip_bytes())
