# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Writes the bare marks of the cuju logo and renders its PNG pictures through headless Chrome.

Usage:
    python ci/make_logo.py [--chrome PROGRAM] [--check] [--marks]

The mark is src/cuju/render/web/assets/cuju-logo.svg, a dark square with rounded corners and a gray
gradient border that holds the letters. Each PNG is drawn from it at its own size, never scaled from
another PNG, so every size stays sharp. The page's logo, cuju-logo.png at 128 pixels, the larger
cuju-logo-384.png and the app icons icons/cuju-192.png and icons/cuju-512.png keep the border and
are transparent outside the rounded corners. The maskable icon icons/cuju-maskable-512.png fills its
whole square with the dark background and leaves the border out, since a system cuts it to a shape
of its own, and its letters stay inside the round safe zone, whose diameter is four fifths of the
side. Chrome draws the SVG into a canvas of the exact size, and this script writes the pixels as an
8 bit PNG with Python's standard library, so the same SVG and the same build of Chrome give the same
pixels.

The bare marks are SVG files of the letters alone on a clear background, cut to the letters' own
square with a small margin. cuju-mark.svg keeps the light grays of the logo for dark surfaces, and
cuju-mark-light.svg draws the same three stacked copies in dark grays for light surfaces, the front
copy darkest and the copies behind it lighter toward the page, each gray brightening outward from
near the middle of the grid as in the logo. The script writes both from the shapes of the logo, so
the three files never drift apart, and the colors of the light mark live here in LIGHT.

With --check the script writes nothing and exits with status 1 when a shipped bare mark or the
pixels of a shipped picture differ from those it would make. With --marks it writes or checks the
bare marks alone, which needs no Chrome.

The program comes from --chrome, then the variable CUJU_CHROME, then google-chrome on the path.
"""

import argparse
import base64
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'src' / 'cuju' / 'render' / 'web' / 'assets'
LOGO = ASSETS / 'cuju-logo.svg'
SVG = 'http://www.w3.org/2000/svg'
# The background of the maskable icon, the dark square of the mark.
BACKGROUND = '#202124'
# The side of the square that the letters fill in the group mark, in units of the SVG.
LETTERS = 384
# The share of the maskable icon's side that the letters fill, which keeps their rounded corners
# inside the safe zone.
MASKABLE_SHARE = 0.5625
# The margin of clear space around the letters in the bare marks, in units of the SVG.
MARGIN = 12
# The gradients of the letters, from the back copy to the front one.
LAYERS = ('back', 'middle', 'front')
# The dark grays of the light mark, the inner and outer stop of each gradient. The front copy
# holds a contrast of more than six and a half to one with each surface of the light theme, as the
# light grays of the logo do with those of the dark one, and the copies behind it fade toward the
# page.
LIGHT = {
    'back': ('#8e8f92', '#c5c6c8'),
    'middle': ('#5f6064', '#a3a4a7'),
    'front': ('#3c3d40', '#545559'),
}
# Each bare mark, its path inside the assets, the colors it takes, or None for the logo's own,
# and the opening of its comment.
MARKS = (
    ('cuju-mark.svg', None, 'light grays for dark surfaces'),
    ('cuju-mark-light.svg', LIGHT, 'dark grays for light surfaces'),
)
# Each picture, its path inside the assets, its side in pixels and whether it is maskable.
PICTURES = (
    ('cuju-logo.png', 128, False),
    ('cuju-logo-384.png', 384, False),
    ('icons/cuju-192.png', 192, False),
    ('icons/cuju-512.png', 512, False),
    ('icons/cuju-maskable-512.png', 512, True),
)
# The page that draws each SVG into a canvas of its size and prints the PNG data addresses.
PAGE = """<!doctype html><meta charset="utf-8"><pre id="out"></pre><script>
const jobs = %s;
(async () => {
    const out = {};
    for (const job of jobs) {
        const image = new Image();
        image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(job.svg);
        await image.decode();
        const canvas = document.createElement('canvas');
        canvas.width = job.size;
        canvas.height = job.size;
        canvas.getContext('2d').drawImage(image, 0, 0, job.size, job.size);
        out[job.name] = canvas.toDataURL('image/png');
    }
    document.getElementById('out').textContent = JSON.stringify(out);
})();
</script>"""


def sized(svg, side):
    """Returns the SVG text with its width and height set to `side` pixels."""
    root = ET.fromstring(svg)
    root.set('width', str(side))
    root.set('height', str(side))
    return ET.tostring(root, encoding='unicode')


def maskable(svg):
    """Returns the SVG of the maskable icon, the letters alone on a full square of the background.

    The frame of the mark, its gray gradient border and dark rounded square, gives way to the
    background, and the letters shrink about the middle to their share of the side.
    """
    root = ET.fromstring(svg)
    frame = root.find(f'{{{SVG}}}g[@id="frame"]')
    mark = root.find(f'{{{SVG}}}g[@id="mark"]')
    if frame is None or mark is None:
        raise ValueError(f'expected the groups frame and mark in {LOGO}')
    side = float(root.get('viewBox').split()[2])
    scale = side * MASKABLE_SHARE / LETTERS
    offset = (side - LETTERS * scale) / 2
    frame.clear()
    frame.set('id', 'frame')
    ET.SubElement(frame, f'{{{SVG}}}rect', width=f'{side:g}', height=f'{side:g}', fill=BACKGROUND)
    mark.set('transform', f'translate({offset:g} {offset:g}) scale({scale:g})')
    return ET.tostring(root, encoding='unicode')


def bare(svg, colors=None, about=''):
    """Returns the text of a bare mark, the letters of the logo alone on a clear background.

    The letters keep their paths and gradients, take the colors of `colors` by gradient when it is
    given, and move to a square of their own side and a margin on each edge.
    """
    root = ET.fromstring(svg)
    mark = root.find(f'{{{SVG}}}g[@id="mark"]')
    if mark is None:
        raise ValueError(f'expected the group mark in {LOGO}')
    side = LETTERS + 2 * MARGIN
    lines = [
        f'<svg xmlns="{SVG}" width="{side}" height="{side}" viewBox="0 0 {side} {side}">',
        f'    <!-- The bare cuju mark in {about}, the letters of the logo alone on a',
        '         clear background. ci/make_logo.py writes this file from the shapes of',
        '         cuju-logo.svg. -->',
        '    <defs>',
    ]
    for name in LAYERS:
        gradient = root.find(f'.//{{{SVG}}}radialGradient[@id="{name}"]')
        if gradient is None:
            raise ValueError(f'expected the gradient {name} in {LOGO}')
        keys = ('gradientUnits', 'cx', 'cy', 'r')
        attributes = ' '.join(f'{key}="{gradient.get(key)}"' for key in keys)
        lines.append(f'        <radialGradient id="{name}" {attributes}>')
        stops = gradient.findall(f'{{{SVG}}}stop')
        for k, stop in enumerate(stops):
            color = colors[name][k] if colors else stop.get('stop-color')
            lines.append(f'            <stop offset="{stop.get("offset")}" stop-color="{color}"/>')
        lines.append('        </radialGradient>')
    lines += ['    </defs>', f'    <g id="mark" transform="translate({MARGIN} {MARGIN})">']
    for path in mark.findall(f'{{{SVG}}}path'):
        parts = re.findall(r'M[^M]*', ' '.join(path.get('d').split()))
        body = '\n            '.join(part.strip() for part in parts)
        lines.append(f'        <path fill="{path.get("fill")}" d="{body}"/>')
    lines += ['    </g>', '</svg>', '']
    return '\n'.join(lines)


def marks():
    """Returns each bare mark's path inside the assets and its text."""
    svg = LOGO.read_text(encoding='utf-8')
    return [(name, bare(svg, colors, about)) for name, colors, about in MARKS]


def find_chrome(named):
    """Returns the Chrome program to run."""
    program = named or os.environ.get('CUJU_CHROME') or 'google-chrome'
    found = program if Path(program).is_file() else shutil.which(program)
    if not found:
        raise SystemExit(f'no Chrome at {program}, name one with --chrome or CUJU_CHROME')
    return found


def render(chrome, jobs):
    """Returns the PNG bytes that Chrome draws for each job, by the job's name."""
    page = PAGE % json.dumps(jobs)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'logo.html'
        path.write_text(page, encoding='utf-8')
        result = subprocess.run(
            [
                chrome,
                '--headless=new',
                '--disable-gpu',
                '--no-first-run',
                '--no-default-browser-check',
                f'--user-data-dir={Path(folder) / "profile"}',
                '--virtual-time-budget=20000',
                '--dump-dom',
                path.as_uri(),
            ],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=180,
        )
    found = re.search(r'<pre id="out">(.*?)</pre>', result.stdout, re.S)
    if not found or not found.group(1):
        raise SystemExit(f'Chrome drew nothing, {result.stderr.strip()[-400:]}')
    text = found.group(1).replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>')
    drawn = json.loads(text.replace('&amp;', '&'))
    return {name: base64.b64decode(url.split(',', 1)[1]) for name, url in drawn.items()}


def chunks(data):
    """Yields the kind and body of each chunk of a PNG."""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('expected a PNG')
    offset = 8
    while offset < len(data):
        (length,) = struct.unpack('>I', data[offset : offset + 4])
        yield data[offset + 4 : offset + 8], data[offset + 8 : offset + 8 + length]
        offset += 12 + length


def decode(data):
    """Returns the width, height, channels and unfiltered rows of an 8 bit PNG.

    The PNG holds gray, gray with alpha, RGB or RGBA, without a palette or interlacing.
    """
    stream = b''
    width = height = channels = None
    for kind, body in chunks(data):
        if kind == b'IHDR':
            width, height, depth, color, _, _, interlace = struct.unpack('>IIBBBBB', body)
            channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color)
            if depth != 8 or channels is None or interlace:
                raise ValueError('expected an 8 bit PNG without a palette or interlacing')
        elif kind == b'IDAT':
            stream += body
    raw = zlib.decompress(stream)
    stride = width * channels
    rows = []
    previous = bytearray(stride)
    position = 0
    for _ in range(height):
        kind = raw[position]
        line = bytearray(raw[position + 1 : position + 1 + stride])
        position += 1 + stride
        if kind == 2:
            line = bytearray((a + b) & 255 for a, b in zip(line, previous, strict=True))
        elif kind:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                up = previous[i]
                corner = previous[i - channels] if i >= channels else 0
                if kind == 1:
                    line[i] = (line[i] + left) & 255
                elif kind == 3:
                    line[i] = (line[i] + (left + up) // 2) & 255
                else:
                    estimate = left + up - corner
                    distances = (abs(estimate - left), abs(estimate - up), abs(estimate - corner))
                    best = (left, up, corner)[distances.index(min(distances))]
                    line[i] = (line[i] + best) & 255
        rows.append(bytes(line))
        previous = line
    return width, height, channels, rows


def rgba(data):
    """Returns the width, height and RGBA rows of a PNG."""
    width, height, channels, rows = decode(data)
    if channels == 4:
        return width, height, rows
    out = []
    for line in rows:
        pixels = bytearray()
        for i in range(0, len(line), channels):
            pixel = line[i : i + channels]
            color = pixel[:3] if channels >= 3 else pixel[:1] * 3
            pixels += bytes(color) + bytes([pixel[-1] if channels in (2, 4) else 255])
        out.append(bytes(pixels))
    return width, height, out


def encode(width, height, rows):
    """Returns the bytes of an 8 bit PNG of RGBA rows, or of RGB rows when every pixel is opaque.

    Each row is filtered by the row above it, which suits the gradients of the mark.
    """
    opaque = all(line[i] == 255 for line in rows for i in range(3, len(line), 4))
    channels = 3 if opaque else 4
    if opaque:
        rows = [bytes(b for i, b in enumerate(line) if i % 4 != 3) for line in rows]
    raw = bytearray()
    previous = bytes(width * channels)
    for line in rows:
        raw.append(2)
        raw += bytes((a - b) & 255 for a, b in zip(line, previous, strict=True))
        previous = line

    def chunk(kind, body):
        return (
            struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
        )

    header = struct.pack('>IIBBBBB', width, height, 8, 2 if opaque else 6, 0, 0, 0)
    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', header)
        + chunk(b'IDAT', zlib.compress(bytes(raw), 9))
        + chunk(b'IEND', b'')
    )


def pictures(chrome):
    """Returns each picture's path inside the assets and its PNG bytes."""
    ET.register_namespace('', SVG)
    svg = LOGO.read_text(encoding='utf-8')
    jobs = [
        {'name': name, 'size': side, 'svg': sized(maskable(svg) if mask else svg, side)}
        for name, side, mask in PICTURES
    ]
    drawn = render(chrome, jobs)
    out = []
    for name, side, _ in PICTURES:
        width, height, rows = rgba(drawn[name])
        if (width, height) != (side, side):
            raise SystemExit(f'Chrome drew {name} at {width} by {height}, expected {side}')
        out.append((name, encode(width, height, rows)))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--chrome', help='the Chrome to run')
    parser.add_argument('--check', action='store_true', help='compare with the shipped pictures')
    parser.add_argument('--marks', action='store_true', help='the bare marks alone, without Chrome')
    options = parser.parse_args()
    differs = []
    for name, text in marks():
        path = ASSETS / name
        if options.check:
            if not path.is_file() or path.read_text(encoding='utf-8') != text:
                differs.append(name)
            continue
        path.write_bytes(text.encode('utf-8'))
        print(f'wrote {path.relative_to(ROOT).as_posix()}, {len(text)} bytes')
    drawn = [] if options.marks else pictures(find_chrome(options.chrome))
    for name, data in drawn:
        path = ASSETS / name
        if options.check:
            if not path.is_file() or rgba(path.read_bytes()) != rgba(data):
                differs.append(name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f'wrote {path.relative_to(ROOT).as_posix()}, {len(data)} bytes')
    if differs:
        print(
            f'the files {", ".join(differs)} differ from the logo, run ci/make_logo.py',
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
