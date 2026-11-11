# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks the Python sources for text files opened without a named encoding.

Python opens a text file in the encoding of the system when the call names none, which is cp1252
on most Windows machines, so a team name outside that code page fails to save and a file written
on another system reads garbled. Every text mode open, read, write and subprocess pipe in `src`,
`tests` and `ci` therefore names its encoding, most often UTF-8.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ('src', 'tests', 'ci')
# A mode string, as the first argument of `Path.open` or the second of `open`.
MODE = re.compile(r'[rwxabt+U]{1,4}')
COMPRESSED = {'gzip', 'bz2', 'lzma'}
TEMPORARY = {'NamedTemporaryFile', 'TemporaryFile', 'SpooledTemporaryFile'}
SUBPROCESS = {'run', 'Popen', 'check_output', 'check_call', 'call', 'getoutput'}


def keyword(call, name):
    return next((item.value for item in call.keywords if item.arg == name), None)


def has_encoding(call, position=None):
    """Tells whether the call names its encoding, as a keyword or at its place in the arguments."""
    if keyword(call, 'encoding') is not None:
        return True
    return position is not None and len(call.args) > position


def mode_of(call, position, default):
    """Returns the mode of an open call, or None when it is not a literal string."""
    value = call.args[position] if len(call.args) > position else keyword(call, 'mode')
    if value is None:
        return default
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def text_mode(mode):
    return mode is None or 'b' not in mode


def problem(call):
    """Returns what the call misses, or None when it names its encoding or opens bytes."""
    function = call.func
    if isinstance(function, ast.Name):
        name, owner = function.id, 'builtins'
    elif isinstance(function, ast.Attribute):
        name = function.attr
        # A method of anything other than a plain name, as in `(folder / 'a.json').open()`.
        owner = function.value.id if isinstance(function.value, ast.Name) else ''
    else:
        return None
    if name == 'open' and owner in ('builtins', 'io'):
        if text_mode(mode_of(call, 1, 'r')) and not has_encoding(call, 3):
            return 'open in text mode'
    elif name == 'fdopen' and owner == 'os':
        if text_mode(mode_of(call, 1, 'r')) and not has_encoding(call, 3):
            return 'os.fdopen in text mode'
    elif name == 'open' and owner in COMPRESSED:
        mode = mode_of(call, 1, 'rb')
        if (mode is None or 't' in mode) and not has_encoding(call):
            return f'{owner}.open in text mode'
    elif name == 'open' and owner is not None:
        # `Path.open` takes the mode first, and the other methods named open in these sources
        # take a path, a url or a file descriptor, which never reads as a mode.
        first = call.args[0] if call.args else keyword(call, 'mode')
        literal = isinstance(first, ast.Constant) and isinstance(first.value, str)
        if (first is None or (literal and MODE.fullmatch(first.value))) and owner not in (
            'os',
            'tarfile',
            'zipfile',
            'webbrowser',
            'Image',
        ):
            if text_mode(mode_of(call, 0, 'r')) and not has_encoding(call, 2):
                return 'Path.open in text mode'
    elif name == 'read_text':
        if not has_encoding(call, 0):
            return 'read_text'
    elif name == 'write_text':
        if not has_encoding(call, 1):
            return 'write_text'
    elif name in TEMPORARY:
        if text_mode(mode_of(call, 0, 'w+b')) and not has_encoding(call, 2):
            return f'{name} in text mode'
    elif name == 'TextIOWrapper':
        if not has_encoding(call, 1):
            return 'TextIOWrapper'
    elif name in SUBPROCESS and owner == 'subprocess':
        texts = [keyword(call, 'text'), keyword(call, 'universal_newlines')]
        if any(isinstance(item, ast.Constant) and item.value for item in texts):
            if not has_encoding(call):
                return f'subprocess.{name} with a text pipe'
    return None


def problems(path):
    tree = ast.parse(path.read_bytes(), str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            found = problem(node)
            if found is not None:
                yield f'{path.relative_to(ROOT).as_posix()}:{node.lineno}: {found}'


def sources():
    for folder in FOLDERS:
        yield from sorted((ROOT / folder).rglob('*.py'))


def test_every_text_file_names_its_encoding():
    found = [item for path in sources() for item in problems(path)]
    assert not found, 'name an encoding, as in encoding="utf-8":\n' + '\n'.join(found)


def test_the_check_finds_the_calls_it_looks_for():
    code = '\n'.join(
        [
            'open(path)',
            "open(path, 'w')",
            "open(path, 'rb')",
            "open(path, 'w', encoding='utf-8')",
            'path.read_text()',
            "path.read_text('utf-8')",
            "path.write_text(text, encoding='utf-8')",
            "path.open('x')",
            "path.open('rb')",
            "os.fdopen(handle, 'w')",
            "os.fdopen(handle, 'wb')",
            'os.open(path, flags)',
            'webbrowser.open(url)',
            "gzip.open(path, 'rt')",
            "gzip.open(path, 'rb')",
            "tempfile.NamedTemporaryFile('w')",
            'tempfile.NamedTemporaryFile()',
            'subprocess.run(command, text=True)',
            "subprocess.run(command, text=True, encoding='utf-8')",
            'subprocess.run(command, capture_output=True)',
            "(folder / 'a.json').open()",
            "(folder / 'a.plist').open('rb')",
        ]
    )
    calls = [node for node in ast.walk(ast.parse(code)) if isinstance(node, ast.Call)]
    flagged = sorted(node.lineno for node in calls if problem(node) is not None)
    assert flagged == [1, 2, 5, 8, 10, 14, 16, 18, 21]
