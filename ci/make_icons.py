# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Makes the page's copy of the Lucide icons it uses, with Python's standard library alone.

Usage:
    python ci/make_icons.py <folder> [--check]

The folder holds the SVG files of lucide-static 1.72.0, one file per icon as
https://unpkg.com/lucide-static@1.72.0/icons/<name>.svg serves it, and the package's LICENSE.
The script reads the Lucide names that web/js/core/icons.js gives its symbols, and the icons of
the keys of the keyboard, takes the shapes of each icon and writes them as data to
src/cuju/render/web/vendor/lucide/icons.js, with the license beside it. An icon whose file holds
anything other than plain shapes stops the script. With --check the script writes nothing and
exits with status 1 when the shipped copy differs from the one it would make.
"""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'src' / 'cuju' / 'render' / 'web'
SYMBOLS = WEB / 'js' / 'core' / 'icons.js'
FOLDER = WEB / 'vendor' / 'lucide'
VERSION = '1.72.0'
# The icons of the keys of the keyboard, which the page draws on its keycaps.
KEYS = (
    'space',
    'corner-down-left',
    'arrow-big-up',
    'delete',
    'arrow-right-to-line',
    'command',
    'option',
    'chevron-up',
    'arrow-left',
    'arrow-right',
    'arrow-up',
    'arrow-down',
    'arrow-big-left',
)
# The shapes an icon may hold and the attributes each shape may carry.
SHAPES = {
    'path': ('d',),
    'line': ('x1', 'y1', 'x2', 'y2'),
    'circle': ('cx', 'cy', 'r'),
    'ellipse': ('cx', 'cy', 'rx', 'ry'),
    'rect': ('x', 'y', 'width', 'height', 'rx', 'ry'),
    'polyline': ('points',),
    'polygon': ('points',),
}
ROOT_ATTRIBUTES = {
    'class',
    'xmlns',
    'width',
    'height',
    'viewBox',
    'fill',
    'stroke',
    'stroke-width',
    'stroke-linecap',
    'stroke-linejoin',
}


def names():
    """Returns the Lucide names that the symbols of the page use, then those of the keys."""
    text = SYMBOLS.read_text(encoding='utf-8')
    block = text[text.index('export const SYMBOLS = {') : text.index('\n};', text.index('SYMBOLS'))]
    found = re.findall(r":\s*'([a-z0-9-]+)'", block)
    return sorted(set(found) | set(KEYS))


def shapes(path):
    """Returns the shapes of one icon as pairs of a tag and its attributes."""
    text = path.read_text(encoding='utf-8')
    if '<!DOCTYPE' in text or '<!ENTITY' in text:
        raise ValueError(f'{path.name} declares a document type')
    root = ET.fromstring(text[text.index('<svg') :])
    if root.tag.split('}')[-1] != 'svg' or set(root.attrib) - ROOT_ATTRIBUTES:
        raise ValueError(f'{path.name} is not a plain icon')
    if root.get('viewBox') != '0 0 24 24':
        raise ValueError(f'{path.name} has another box')
    out = []
    for child in root:
        tag = child.tag.split('}')[-1]
        allowed = SHAPES.get(tag, ())
        # A shape may fill itself with the color of the text, as the dots of an icon do.
        own = set(child.attrib) - set(allowed)
        filled = child.get('fill', 'currentColor') == 'currentColor'
        if not allowed or len(child) or own - {'fill'} or not filled:
            raise ValueError(f'{path.name} holds {tag} {sorted(child.attrib)}')
        keys = (*allowed, 'fill')
        out.append([tag, {key: child.get(key) for key in keys if child.get(key) is not None}])
    return out


def module(folder):
    """Returns the text of vendor/lucide/icons.js made from the icons of the folder."""
    lines = [
        f'// lucide-static {VERSION}, https://lucide.dev, under the ISC License, the icons derived',
        '// from Feather under the MIT License, see LICENSE beside this file. Made by',
        '// ci/make_icons.py from the SVG files of the icons that the page uses. Each icon is a',
        '// list of shapes in a box of 24 by 24, stroked two units wide in the color of the text.',
        '',
        f"export const VERSION = '{VERSION}';",
        '',
        'export const LUCIDE = {',
    ]
    for name in names():
        data = json.dumps(shapes(folder / f'{name}.svg'), separators=(', ', ': '))
        lines.append(f"    '{name}': {data.replace(chr(34), chr(39))},")
    lines += ['};', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('folder', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    text = module(args.folder)
    license_text = (args.folder / 'LICENSE').read_text(encoding='utf-8')
    target = FOLDER / 'icons.js'
    if args.check:
        same = target.exists() and target.read_text(encoding='utf-8') == text
        same = same and (FOLDER / 'LICENSE').read_text(encoding='utf-8') == license_text
        print('the copy of the icons is current' if same else 'the copy of the icons differs')
        sys.exit(0 if same else 1)
    FOLDER.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8', newline='\n')
    (FOLDER / 'LICENSE').write_text(license_text, encoding='utf-8', newline='\n')
    print(f'wrote {len(names())} icons to {target.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
