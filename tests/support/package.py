# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Builds the small test package of team presentation, a team with a model, clips and a package.

The manifest and the worker are files of `tests/support/team`, which an author may read as an
example. This module adds what is binary, the team's rigged model with four clips named for their
roles and a contact marker on the kick, the same model as the package's keeper model, a small ring
to attach, a short sound and a small striped image for its tifo, and packs it all with a
submission as a zip, as a team is exported.
Run it as a script to write the zip to a file.
"""

import io
import json
import math
import struct
import sys
import zipfile
import zlib
from pathlib import Path

from support.clip import BONES, _pad

FOLDER = Path(__file__).with_name('team')
# The bones of the figure, those of the clip and a halo above the head that a behaviour spins.
FIGURE = [*BONES, ('Halo', 3, (0.0, 1.95, 0.0))]
JOINTS = {
    'body': 'mixamorig:Hips',
    'neck': 'mixamorig:Neck',
    'left_shoulder': 'mixamorig:LeftArm',
    'left_elbow': 'mixamorig:LeftForeArm',
    'right_shoulder': 'mixamorig:RightArm',
    'right_elbow': 'mixamorig:RightForeArm',
    'left_thigh': 'mixamorig:LeftUpLeg',
    'left_knee': 'mixamorig:LeftLeg',
    'left_ankle': 'mixamorig:LeftFoot',
    'right_thigh': 'mixamorig:RightUpLeg',
    'right_knee': 'mixamorig:RightLeg',
    'right_ankle': 'mixamorig:RightFoot',
}


class _Writer:
    """Collects the binary buffer, views and accessors of one glTF file."""

    def __init__(self):
        self.binary = bytearray()
        self.views = []
        self.accessors = []

    def add(self, data, count, kind, component=5126, target=None, minimum=None, maximum=None):
        offset = len(self.binary)
        self.binary.extend(_pad(data))
        view = {'buffer': 0, 'byteOffset': offset, 'byteLength': len(data)}
        if target:
            view['target'] = target
        self.views.append(view)
        accessor = {
            'bufferView': len(self.views) - 1,
            'componentType': component,
            'count': count,
            'type': kind,
        }
        if minimum is not None:
            accessor['min'], accessor['max'] = minimum, maximum
        self.accessors.append(accessor)
        return len(self.accessors) - 1

    def floats(self, values, kind, count, **options):
        return self.add(struct.pack(f'<{len(values)}f', *values), count, kind, **options)

    def glb(self, document):
        document['buffers'] = [{'byteLength': len(self.binary)}]
        document['bufferViews'] = self.views
        document['accessors'] = self.accessors
        text = _pad(json.dumps(document).encode(), b' ')
        chunks = struct.pack('<II', len(text), 0x4E4F534A) + text
        chunks += struct.pack('<II', len(self.binary), 0x004E4942) + bytes(self.binary)
        return b'glTF' + struct.pack('<II', 2, 12 + len(chunks)) + chunks


def _quaternion(axis, angle):
    s = math.sin(angle / 2)
    return [axis[0] * s, axis[1] * s, axis[2] * s, math.cos(angle / 2)]


def model_bytes():
    """Returns the rigged figure with the clips Idle, Run, Kick and Cheer."""
    w = _Writer()
    points = [position for _, _, position in FIGURE[:-1]]
    owners = list(range(len(points)))
    triangles = [(0, 1, 2), (1, 4, 5), (1, 6, 7), (0, 8, 9), (8, 9, 10), (0, 11, 12), (11, 12, 13)]
    triangles.append((2, 3, 1))
    flat = [value for point in points for value in point]
    position = w.floats(
        flat,
        'VEC3',
        len(points),
        target=34962,
        minimum=[min(p[i] for p in points) for i in range(3)],
        maximum=[max(p[i] for p in points) for i in range(3)],
    )
    indices = w.add(
        struct.pack(f'<{3 * len(triangles)}H', *[i for t in triangles for i in t]),
        3 * len(triangles),
        'SCALAR',
        component=5123,
        target=34963,
    )
    joints = w.add(
        b''.join(struct.pack('<4B', owner, 0, 0, 0) for owner in owners),
        len(points),
        'VEC4',
        component=5121,
        target=34962,
    )
    weights = w.floats([1, 0, 0, 0] * len(points), 'VEC4', len(points), target=34962)
    inverse = []
    for _, _, (x, y, z) in FIGURE:
        inverse += [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -x, -y, -z, 1]
    binds = w.floats(inverse, 'MAT4', len(FIGURE))
    nodes = []
    for index, (name, parent, (x, y, z)) in enumerate(FIGURE):
        if parent >= 0:
            px, py, pz = FIGURE[parent][2]
            x, y, z = x - px, y - py, z - pz
        node = {'name': f'mixamorig:{name}', 'translation': [x, y, z]}
        children = [child for child, (_, up, _) in enumerate(FIGURE) if up == index]
        if children:
            node['children'] = children
        nodes.append(node)
    nodes.append({'name': 'Body', 'mesh': 0, 'skin': 0})
    times = w.floats([0, 0.5, 1], 'SCALAR', 3, minimum=[0], maximum=[1])

    def turn(axis, angle):
        rest = [0, 0, 0, 1]
        return w.floats(rest + _quaternion(axis, angle) + rest, 'VEC4', 3)

    def animation(name, channels):
        samplers = [{'input': times, 'output': output} for _, _, output in channels]
        targets = [
            {'sampler': i, 'target': {'node': node, 'path': path}}
            for i, (node, path, _) in enumerate(channels)
        ]
        return {'name': name, 'samplers': samplers, 'channels': targets}

    # The hips of Run travel forwards, root motion that the manifest's rootMotion strips.
    travel = w.floats([0, 1.0, 0, 0, 1.05, 0.3, 0, 1.0, 0.6], 'VEC3', 3)
    kick = animation('Kick', [(11, 'rotation', turn((1, 0, 0), -1.1))])
    # The foot meets the ball half way through the kick, a marker the renderer schedules by.
    kick['extras'] = {'cuju': {'markers': {'contact': 0.5}}}
    animations = [
        animation('Idle', [(1, 'rotation', turn((1, 0, 0), 0.08))]),
        animation(
            'Run',
            [(0, 'translation', travel), (6, 'rotation', turn((1, 0, 0), 0.9))],
        ),
        kick,
        animation(
            'Cheer',
            [(4, 'rotation', turn((0, 0, 1), 2.4)), (6, 'rotation', turn((0, 0, 1), -2.4))],
        ),
    ]
    document = {
        'asset': {'version': '2.0', 'generator': 'cuju tests'},
        'scene': 0,
        'scenes': [{'nodes': [0, len(FIGURE)]}],
        'nodes': nodes,
        'materials': [
            {'name': 'Body', 'pbrMetallicRoughness': {'baseColorFactor': [0.8] * 3 + [1]}}
        ],
        'meshes': [
            {
                'name': 'Body',
                'primitives': [
                    {
                        'attributes': {
                            'POSITION': position,
                            'JOINTS_0': joints,
                            'WEIGHTS_0': weights,
                        },
                        'indices': indices,
                        'material': 0,
                    }
                ],
            }
        ],
        'skins': [{'joints': list(range(len(FIGURE))), 'inverseBindMatrices': binds}],
        'animations': animations,
    }
    return w.glb(document)


def halo_bytes(segments=24):
    """Returns a flat ring of quads, 0.25 meters across, without a skin, to attach."""
    w = _Writer()
    points = []
    for i in range(segments):
        angle = 2 * math.pi * i / segments
        for radius in (0.2, 0.25):
            points += [radius * math.cos(angle), 0.0, radius * math.sin(angle)]
    indices = []
    for i in range(segments):
        a, b = 2 * i, 2 * ((i + 1) % segments)
        indices += [a, b, a + 1, b, b + 1, a + 1]
    position = w.floats(
        points,
        'VEC3',
        len(points) // 3,
        target=34962,
        minimum=[-0.25, 0, -0.25],
        maximum=[0.25, 0, 0.25],
    )
    index = w.add(
        struct.pack(f'<{len(indices)}H', *indices),
        len(indices),
        'SCALAR',
        component=5123,
        target=34963,
    )
    material = {
        'name': 'Halo',
        'doubleSided': True,
        'emissiveFactor': [1.0, 0.8, 0.4],
        'pbrMetallicRoughness': {'baseColorFactor': [1.0, 0.85, 0.5, 1]},
    }
    document = {
        'asset': {'version': '2.0', 'generator': 'cuju tests'},
        'scene': 0,
        'scenes': [{'nodes': [0]}],
        'nodes': [{'name': 'Halo', 'mesh': 0}],
        'materials': [material],
        'meshes': [
            {
                'primitives': [
                    {'attributes': {'POSITION': position}, 'indices': index, 'material': 0}
                ]
            }
        ],
    }
    return w.glb(document)


def wav_bytes(seconds=0.2, rate=22050):
    """Returns a short sine tone as a 16 bit mono WAV file."""
    count = int(seconds * rate)
    samples = b''.join(
        struct.pack('<h', int(12000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(count)
    )
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',
        36 + len(samples),
        b'WAVE',
        b'fmt ',
        16,
        1,
        1,
        rate,
        rate * 2,
        2,
        16,
        b'data',
        len(samples),
    )
    return header + samples


def png_bytes(width=64, height=24):
    """Returns a small PNG of stripes in two colours, the tifo of the test package."""
    rows = b''
    for y in range(height):
        color = (230, 120, 40) if (y // 4) % 2 else (250, 230, 200)
        rows += bytes([0]) + bytes(color) * width

    def chunk(kind, data):
        body = kind + data
        return (
            struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF)
        )

    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    signature = bytes([137, 80, 78, 71, 13, 10, 26, 10])
    return (
        signature
        + chunk(b'IHDR', header)
        + chunk(b'IDAT', zlib.compress(rows))
        + chunk(b'IEND', b'')
    )


def package_files(name='Test package'):
    """Returns every file of the test team by its path in the archive."""
    model = model_bytes()
    team = {
        'name': name,
        'format': '5v5',
        'style': {'model': 'custom'},
        'model': {'joints': JOINTS},
    }
    files = {
        'main.py': b'def agent(obs):\n    return [0]\n',
        'cuju-team/team.json': json.dumps(team).encode(),
        'cuju-team/model.glb': model,
        'cuju-team/presentation/models/keeper.glb': model,
        'cuju-team/presentation/models/halo.glb': halo_bytes(),
        'cuju-team/presentation/audio/strike.wav': wav_bytes(),
        'cuju-team/presentation/textures/tifo.png': png_bytes(),
    }
    for path in sorted(FOLDER.rglob('*')):
        if path.is_file():
            files[path.relative_to(FOLDER).as_posix()] = path.read_bytes()
    return files


def package_zip(name='Test package', extra=None):
    """Returns the test team as a zip, with extra files of a test added or replaced."""
    buffer = io.BytesIO()
    files = {**package_files(name), **(extra or {})}
    with zipfile.ZipFile(buffer, 'w') as archive:
        for path, data in files.items():
            archive.writestr(path, data)
    return buffer.getvalue()


if __name__ == '__main__':
    Path(sys.argv[1] if len(sys.argv) > 1 else 'test-package.zip').write_bytes(package_zip())
