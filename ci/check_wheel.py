# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks wheels of cuju-render: the license files, the files of the page and the folder they use.

Usage: `python ci/check_wheel.py <wheel>...`. A wheel of cuju-render holds `cuju/render/` alone,
never `cuju/__init__.py` or another top-level name, and requires a cuju that ships no renderer.
"""

import re
import sys
import zipfile

LICENSES = [
    'LICENSE',
    'NOTICE',
    'LICENSES/MIT.txt',
    'LICENSES/CC0-1.0.txt',
    'LICENSES/Unlicense.txt',
    'LICENSES/CC-BY-4.0.txt',
]
REQUIRED = [
    'cuju/render/__init__.py',
    'cuju/render/__main__.py',
    'cuju/render/_version.py',
    'cuju/render/_http/server.py',
    'cuju/render/web/index.html',
    'cuju/render/web/vendor/three/LICENSE',
    'cuju/render/web/vendor/fabric/LICENSE',
    'cuju/render/samples/sample-5v5.cjr',
    'cuju/render/samples/sample-11v11.cjr',
]
# The first cuju whose wheel holds no renderer of its own.
MIN_CUJU = '0.2.1'
# The requirement of cuju stops before this version.
BELOW_CUJU = '0.3'


def problems(path):
    """Returns what is wrong with the wheel at `path`, or an empty list."""
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        metadata = next(
            (wheel.read(n).decode() for n in names if n.endswith('.dist-info/METADATA')), ''
        )
    found = [
        f'missing {name}'
        for name in LICENSES
        if not any(n.endswith(f'licenses/{name}') for n in names)
    ]
    found += [f'missing {name}' for name in REQUIRED if name not in names]
    if not any(n.startswith('cuju/render/web/vendor/three/build/') for n in names):
        found.append('missing the build of three.js')
    for name in names:
        if '.dist-info/' in name.split('/', 1)[0] + '/':
            continue
        if not name.startswith('cuju/render/'):
            found.append(f'unexpected {name}, the wheel holds cuju/render/ alone')
        elif '__pycache__' in name or name.endswith('.pyc'):
            found.append(f'unexpected {name}')
    requires = re.findall(r'^Requires-Dist: (.*)$', metadata, re.MULTILINE)
    cuju = [r for r in requires if re.match(r'cuju\b(?!-)', r) and 'extra ==' not in r]
    bounds = cuju[0].replace(' ', '') if len(cuju) == 1 else ''
    if f'>={MIN_CUJU}' not in bounds or f'<{BELOW_CUJU}' not in bounds:
        found.append(f'expected one requirement of cuju>={MIN_CUJU},<{BELOW_CUJU}, found {cuju}')
    return found


def main():
    wheels = sys.argv[1:]
    if not wheels:
        sys.exit('usage: python ci/check_wheel.py <wheel>...')
    failed = False
    for path in wheels:
        for problem in problems(path):
            print(f'{path}: {problem}')
            failed = True
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
