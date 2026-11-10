# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Makes the icons of the installable page from the logo, with Python's standard library alone.

Usage:
    python ci/make_app_icons.py [--check]

The icons go to src/cuju/render/web/assets/icons, a 192 and a 512 pixel square with the logo
inside a margin, and a maskable 512 pixel square whose logo stays inside the round safe zone that
a system may cut the icon to. The logo is drawn as the page's dark theme draws it, inverted on the
page's dark background. The same logo always gives the same pixels, and the same bytes with the
same build of zlib. With --check the script writes nothing and exits with status 1 when the pixels
of a shipped icon differ from those it would make.
"""

import argparse
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'src' / 'cuju' / 'render' / 'web'
LOGO = WEB / 'assets' / 'cuju-logo-384.png'
FOLDER = WEB / 'assets' / 'icons'
# The background of the dark theme, --bg of style.css, and the share of the invert filter that the
# dark theme puts on the logo, --logo-filter.
BACKGROUND = (0x20, 0x21, 0x24)
INVERT = 0.9
# Each icon, its file, its size and the share of its side that the logo fills.
ICONS = (
    ('cuju-192.png', 192, 0.8),
    ('cuju-512.png', 512, 0.8),
    ('cuju-maskable-512.png', 512, 0.6),
)


def read_png(path):
    """Returns the width, height and RGBA rows of a PNG of 8 bit RGBA without interlacing."""
    data = path.read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError(f'expected a PNG, found {path}')
    offset = 8
    chunks = b''
    width = height = None
    while offset < len(data):
        (length,) = struct.unpack('>I', data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        if kind == b'IHDR':
            width, height, depth, color, _, _, interlace = struct.unpack('>IIBBBBB', body)
            if (depth, color, interlace) != (8, 6, 0):
                raise ValueError('expected 8 bit RGBA without interlacing')
        elif kind == b'IDAT':
            chunks += body
        offset += 12 + length
    raw = zlib.decompress(chunks)
    stride = width * 4
    rows = []
    previous = bytearray(stride)
    position = 0
    for _ in range(height):
        kind = raw[position]
        line = bytearray(raw[position + 1 : position + 1 + stride])
        position += 1 + stride
        for i in range(stride):
            left = line[i - 4] if i >= 4 else 0
            up = previous[i]
            corner = previous[i - 4] if i >= 4 else 0
            if kind == 1:
                line[i] = (line[i] + left) & 255
            elif kind == 2:
                line[i] = (line[i] + up) & 255
            elif kind == 3:
                line[i] = (line[i] + (left + up) // 2) & 255
            elif kind == 4:
                estimate = left + up - corner
                distances = (abs(estimate - left), abs(estimate - up), abs(estimate - corner))
                best = (left, up, corner)[distances.index(min(distances))]
                line[i] = (line[i] + best) & 255
        rows.append(line)
        previous = line
    return width, height, rows


def sample(rows, width, height, x, y):
    """Returns the RGBA of the logo at a point, by bilinear sampling with premultiplied alpha."""
    x = min(max(x, 0.0), width - 1.0)
    y = min(max(y, 0.0), height - 1.0)
    x0, y0 = int(x), int(y)
    x1, y1 = min(x0 + 1, width - 1), min(y0 + 1, height - 1)
    fx, fy = x - x0, y - y0
    total = [0.0, 0.0, 0.0, 0.0]
    for px, py, weight in (
        (x0, y0, (1 - fx) * (1 - fy)),
        (x1, y0, fx * (1 - fy)),
        (x0, y1, (1 - fx) * fy),
        (x1, y1, fx * fy),
    ):
        pixel = rows[py][px * 4 : px * 4 + 4]
        alpha = pixel[3] / 255
        for channel in range(3):
            total[channel] += pixel[channel] * alpha * weight
        total[3] += alpha * weight
    return total


def icon(rows, width, height, side, share):
    """Returns the RGB rows of one icon."""
    logo = side * share
    start = (side - logo) / 2
    scale = width / logo
    # Each pixel of the icon averages a grid of samples, which keeps a shrunken logo smooth.
    taps = max(1, round(scale))
    out = []
    for row in range(side):
        line = bytearray()
        for column in range(side):
            color = [0.0, 0.0, 0.0]
            for ty in range(taps):
                for tx in range(taps):
                    lx = (column + (tx + 0.5) / taps - start) * scale - 0.5
                    ly = (row + (ty + 0.5) / taps - start) * scale - 0.5
                    inside = -0.5 <= lx <= width - 0.5 and -0.5 <= ly <= height - 0.5
                    red, green, blue, alpha = (
                        sample(rows, width, height, lx, ly) if inside else (0, 0, 0, 0)
                    )
                    for channel, value in enumerate((red, green, blue)):
                        straight = value / alpha if alpha else 0.0
                        inverted = straight * (1 - INVERT) + (255 - straight) * INVERT
                        color[channel] += inverted * alpha + BACKGROUND[channel] * (1 - alpha)
            line += bytes(min(255, max(0, round(value / (taps * taps)))) for value in color)
        out.append(line)
    return out


def write_png(rows, side):
    """Returns the bytes of an 8 bit RGB PNG, every row filtered by its left neighbor."""
    raw = bytearray()
    for line in rows:
        raw.append(1)
        raw += bytes((line[i] - (line[i - 3] if i >= 3 else 0)) & 255 for i in range(len(line)))

    def chunk(kind, body):
        return (
            struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
        )

    header = struct.pack('>IIBBBBB', side, side, 8, 2, 0, 0, 0)
    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', header)
        + chunk(b'IDAT', zlib.compress(bytes(raw), 9))
        + chunk(b'IEND', b'')
    )


def pixels(data):
    """Returns the header and the filtered rows of a PNG that this script wrote.

    Two builds of zlib may compress the same rows to other bytes, so a check compares the rows.
    """
    offset = 8
    header = rows = b''
    while offset < len(data):
        (length,) = struct.unpack('>I', data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        if kind == b'IHDR':
            header = body
        elif kind == b'IDAT':
            rows += body
        offset += 12 + length
    return header, zlib.decompress(rows)


def icons():
    """Returns each icon's file name and bytes."""
    width, height, rows = read_png(LOGO)
    return [
        (name, write_png(icon(rows, width, height, side, share), side))
        for name, side, share in ICONS
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true', help='compare with the shipped icons')
    options = parser.parse_args()
    differs = []
    for name, data in icons():
        path = FOLDER / name
        if options.check:
            if not path.is_file() or pixels(path.read_bytes()) != pixels(data):
                differs.append(name)
            continue
        FOLDER.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f'wrote {path.relative_to(ROOT).as_posix()}, {len(data)} bytes')
    if differs:
        print(
            f'the icons {", ".join(differs)} differ from the logo, run ci/make_app_icons.py',
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
