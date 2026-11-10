# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The static checks of the shaders of team presentation packages.

A shader of a package is a `.glsl` file of UTF-8 text, at most 256 KB. The renderer writes the
`#version`, the precision and every uniform in front of it, so a file declares no uniform of its
own. In the mode `chunks`, the default, the file extends the renderer's standard material with
hook functions, `cujuVertex`, `cujuColor`, `cujuEmissive`, `cujuRoughness` and `cujuMetalness`,
and defines at least one of them. In the mode `material` the file is a whole shader material, a
vertex section after the line `#pragma cuju vertex` and a fragment section after the line
`#pragma cuju fragment`, each with its own `void main()`.

The checks keep a shader cheap and its cost known before it compiles. A loop is a `for` loop of a
fixed count, with integer literals or `const int` names of the file for its bounds and step, of
at most 256 iterations. A fragment fetches textures at most 16 times, counted with the trip counts
of the loops around each fetch and through the helper functions it calls, and every hook of a
chunks file counts as fragment. The only include is `<cuju_noise>`.

The server runs `check` on the shaders of a manifest, `cuju render pack check` runs it for an
author, and the page runs the same rules before it compiles. Each check reads the text with its
comments taken out, with plain regular expressions and no dependency, so it stays fast.
"""

from __future__ import annotations

import bisect
import re
from typing import Any

MODES = ('chunks', 'material')
MAXIMUM_BYTES = 256 * 1024
MAXIMUM_ITERATIONS = 256
MAXIMUM_FETCHES = 16
# The programs a team may compile at each quality, one for each distinct shader file and mode.
BUDGET = {'high': 16, 'medium': 16, 'low': 8}
INCLUDES = ('cuju_noise',)
# The hooks of a chunks file and the type each returns.
HOOKS = {
    'cujuVertex': 'vec3',
    'cujuColor': 'vec4',
    'cujuEmissive': 'vec3',
    'cujuRoughness': 'float',
    'cujuMetalness': 'float',
}
# The built in functions of GLSL that fetch from a texture, those of GLSL ES 3.00 and the older
# names that WebGL still reads.
FETCHES = frozenset(
    (
        'texture',
        'textureProj',
        'textureLod',
        'textureOffset',
        'textureProjOffset',
        'textureLodOffset',
        'textureProjLod',
        'textureProjLodOffset',
        'textureGrad',
        'textureGradOffset',
        'textureProjGrad',
        'textureProjGradOffset',
        'texelFetch',
        'texelFetchOffset',
        'texture2D',
        'texture2DProj',
        'texture2DLod',
        'texture2DProjLod',
        'texture2DLodEXT',
        'texture2DProjLodEXT',
        'texture2DGradEXT',
        'texture2DProjGradEXT',
        'textureCube',
        'textureCubeLod',
        'textureCubeLodEXT',
        'textureCubeGradEXT',
    )
)
# Words of GLSL that a macro may neither name nor hide.
_KEYWORDS = frozenset(
    (
        'for',
        'while',
        'do',
        'if',
        'else',
        'switch',
        'case',
        'default',
        'break',
        'continue',
        'return',
        'discard',
        'uniform',
        'const',
        'int',
        'float',
        'void',
        'in',
        'out',
        'inout',
        'struct',
        'layout',
        'precision',
        'highp',
        'mediump',
        'lowp',
        'main',
    )
)
_DIRECTIVES = frozenset(
    ('define', 'undef', 'if', 'ifdef', 'ifndef', 'elif', 'else', 'endif', 'error', 'line')
)
_VALUE = r'[-+]?\s*(?:0[xX][0-9a-fA-F]+|\d+)[uU]?|[A-Za-z_]\w*'
_INIT = re.compile(rf'(?:(?:lowp|mediump|highp)\s+)?int\s+([A-Za-z_]\w*)\s*=\s*({_VALUE})')
_CONDITION = re.compile(rf'([A-Za-z_]\w*)\s*(<=|>=|<|>)\s*({_VALUE})')
_STEP = re.compile(
    rf'([A-Za-z_]\w*)\s*(\+\+|--)|(\+\+|--)\s*([A-Za-z_]\w*)|([A-Za-z_]\w*)\s*(\+=|-=)\s*({_VALUE})'
)
_CONSTANT = re.compile(r'\bconst\s+(?:(?:lowp|mediump|highp)\s+)?int\s+([^;]*);')
_LITERAL = re.compile(r'\s*([A-Za-z_]\w*)\s*=\s*([-+]?\s*(?:0[xX][0-9a-fA-F]+|\d+)[uU]?)\s*')
_CALL = re.compile(r'\b([A-Za-z_]\w*)\s*\(')
_HEAD = re.compile(
    r'(?:(?:lowp|mediump|highp)\s+)?([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*\(([^()]*)\)\s*$'
)
_RENDERER_NAME = re.compile(r'cuju\w*|u[A-Z]\w*')
_COMMENT = re.compile(r'//[^\n]*|/\*.*?(?:\*/|\Z)|\\\n', re.S)
_WORD = re.compile(r'[A-Za-z_]\w*')
_BRACKETS = {'(': re.compile(r'[()]'), '{': re.compile(r'[{}]')}
_STATEMENT = re.compile(r'[(){};]')


def _blank(match: re.Match[str]) -> str:
    """Returns a comment or a line continuation as spaces, its newlines kept in a comment."""
    text = match.group(0)
    if text == '\\\n':
        return '  '
    return re.sub(r'[^\n]', ' ', text)


def _clean(text: str) -> str:
    """Returns the text with its comments and line continuations as spaces, of the same length.

    Each character keeps its offset, so a problem names the line of the author's own file.
    """
    return _COMMENT.sub(_blank, text)


def _integer(value: str, constants: dict[str, int]) -> int | None:
    """Returns the integer that a literal or a `const int` name gives, or `None` for another."""
    value = value.replace(' ', '').rstrip('uU')
    if value in constants:
        return constants[value]
    sign = -1 if value.startswith('-') else 1
    digits = value.lstrip('+-')
    if re.fullmatch(r'0[xX][0-9a-fA-F]+', digits):
        return sign * int(digits, 16)
    if digits.isdigit():
        return sign * int(digits)
    return None


def _constants(code: str) -> dict[str, int]:
    """Returns the `const int` names of the code declared with an integer literal."""
    found: dict[str, int] = {}
    for match in _CONSTANT.finditer(code):
        for part in match.group(1).split(','):
            item = _LITERAL.fullmatch(part)
            if item and item.group(1) not in found:
                value = _integer(item.group(2), {})
                if value is not None:
                    found[item.group(1)] = value
    return found


def _trips(start: int, op: str, bound: int, step: int) -> int | None:
    """Returns how many times a loop of the checked form runs, or `None` for one that never ends."""
    if op in ('<', '<='):
        last = bound if op == '<=' else bound - 1
        if start > last:
            return 0
        return None if step <= 0 else (last - start) // step + 1
    last = bound if op == '>=' else bound + 1
    if start < last:
        return 0
    return None if step >= 0 else (start - last) // -step + 1


def _match(code: str, start: int, opening: str, closing: str) -> int:
    """Returns the offset of the bracket that closes the one at `start`, or -1 when none does."""
    depth = 0
    for match in _BRACKETS[opening].finditer(code, start):
        if match.group(0) == opening:
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return match.start()
    return -1


def _split(header: str) -> list[str]:
    """Splits the header of a `for` loop at its semicolons outside parentheses."""
    parts, depth, last = [], 0, 0
    for i, c in enumerate(header):
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        elif c == ';' and depth == 0:
            parts.append(header[last:i])
            last = i + 1
    parts.append(header[last:])
    return parts


class _Reader:
    """Reads the structure of one cleaned shader, its loops and functions, and notes problems."""

    def __init__(self, text: str, code: str, problems: list[str]) -> None:
        self.text = text
        self.code = code
        self.problems = problems
        self.constants: dict[str, int] = {}
        # Each loop as the span of its body and its trip count, and the offsets of those read.
        self.loops: list[tuple[int, int, int]] = []
        self.seen: set[int] = set()
        self.starts: list[int] = []

    def line(self, offset: int) -> int:
        return self.text.count('\n', 0, offset) + 1

    def note(self, offset: int, message: str) -> None:
        problem = f'line {self.line(offset)} {message}'
        if problem not in self.problems:
            self.problems.append(problem)

    def statement(self, start: int) -> int:
        """Returns the offset just past the statement that begins at `start`."""
        code = self.code
        i = start
        while i < len(code) and code[i].isspace():
            i += 1
        if i < len(code) and code[i] == '{':
            end = _match(code, i, '{', '}')
            return len(code) if end < 0 else end + 1
        word = _WORD.match(code, i)
        if word and word.group(0) == 'for':
            return self.loop(i)
        if word and word.group(0) in ('if', 'else', 'switch'):
            self.note(i, 'holds a loop whose body branches without braces, put the body in braces')
        depth = 0
        for match in _STATEMENT.finditer(code, i):
            c = match.group(0)
            if c in '({':
                depth += 1
            elif c in ')}':
                depth -= 1
                if depth < 0:
                    return match.start()
            elif depth == 0:
                return match.start() + 1
        return len(code)

    def loop(self, start: int) -> int:
        """Checks the `for` loop at `start`, notes its body and returns the offset past it."""
        code = self.code
        self.seen.add(start)
        opening = code.find('(', start)
        closing = _match(code, opening, '(', ')') if opening >= 0 else -1
        if opening < 0 or code[start + 3 : opening].strip() or closing < 0:
            self.note(start, 'holds a for loop without a header in parentheses')
            return start + 3
        parts = _split(code[opening + 1 : closing])
        body_end = self.statement(closing + 1)
        trips = self.header(start, parts)
        if trips is None:
            trips = MAXIMUM_ITERATIONS
        else:
            self.counter(start, parts, closing + 1, body_end)
        self.loops.append((closing + 1, body_end, trips))
        return body_end

    def header(self, start: int, parts: list[str]) -> int | None:
        """Returns the trip count of a loop's header, or `None` after noting why it has none."""
        form = 'holds a for loop outside the form for (int i = A; i < B; i++)'
        if len(parts) != 3:
            self.note(start, form)
            return None
        init = _INIT.fullmatch(parts[0].strip())
        condition = _CONDITION.fullmatch(parts[1].strip())
        step = _STEP.fullmatch(parts[2].strip())
        if not (init and condition and step):
            self.note(start, form)
            return None
        name = init.group(1)
        if step.group(1):
            counter, amount = step.group(1), 1 if step.group(2) == '++' else -1
        elif step.group(3):
            counter, amount = step.group(4), 1 if step.group(3) == '++' else -1
        else:
            counter, amount = step.group(5), 0
        if condition.group(1) != name or counter != name:
            self.note(start, f'holds a for loop whose condition or step leaves its counter {name}')
            return None
        values = {'start': init.group(2), 'bound': condition.group(3)}
        if step.group(7):
            values['step'] = step.group(7)
        numbers = {}
        for key, value in values.items():
            number = _integer(value, self.constants)
            if number is None:
                self.note(
                    start,
                    f'bounds a loop by {value.strip()}, which is no integer literal or const int '
                    'of the file',
                )
                return None
            numbers[key] = number
        if step.group(7):
            amount = numbers['step'] if step.group(6) == '+=' else -numbers['step']
        trips = _trips(numbers['start'], condition.group(2), numbers['bound'], amount)
        if trips is None:
            self.note(start, 'holds a loop that never ends, its step moves away from its bound')
            return None
        if trips > MAXIMUM_ITERATIONS:
            self.note(start, f'runs a loop {trips} times, at most {MAXIMUM_ITERATIONS}')
        return trips

    def counter(self, start: int, parts: list[str], body: int, end: int) -> None:
        """Notes a loop whose body changes its counter, which would void its trip count."""
        name = _INIT.fullmatch(parts[0].strip()).group(1)
        text = self.code[body:end]
        pattern = re.compile(
            rf'(?<![\w.])(?:{name}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|{name}\s*(?:\+\+|--)'
            rf'|(?:\+\+|--)\s*{name}\b)'
        )
        for match in pattern.finditer(text):
            if re.search(r'\bint\s*$', text[: match.start()]):
                continue
            self.note(body + match.start(), f'changes the counter {name} inside its loop')

    def loops_of(self) -> None:
        """Checks every `for` loop of the code."""
        for match in re.finditer(r'\bfor\b', self.code):
            if match.start() not in self.seen:
                self.loop(match.start())
        self.loops.sort()
        self.starts = [start for start, _, _ in self.loops]

    def weight(self, offset: int, low: int) -> int:
        """Returns how many times the code at an offset runs, the product of its loops' counts.

        Only the loops that begin from `low` on count, the start of the enclosing function.
        """
        product = 1
        for index in range(bisect.bisect_left(self.starts, low), len(self.starts)):
            start, end, trips = self.loops[index]
            if start > offset:
                break
            if offset < end:
                product *= trips
        return product

    def functions(self) -> list[dict[str, Any]]:
        """Returns the functions the code defines, each with its name, type, offset and body."""
        code = self.code
        found = []
        i = code.find('{')
        while i >= 0:
            low = max(0, i - 400)
            head = _HEAD.search(code[low:i])
            end = _match(code, i, '{', '}')
            if head and head.group(1) not in ('struct', 'return', 'else'):
                found.append(
                    {
                        'type': head.group(1),
                        'name': head.group(2),
                        'parameters': head.group(3).strip(),
                        'at': low + head.start(),
                        'body': (i, len(code) if end < 0 else end),
                    }
                )
            if end < 0:
                break
            i = code.find('{', end + 1)
        return found


def _fetches(reader: _Reader, functions: list[dict[str, Any]], problems: list[str]) -> dict:
    """Returns the texture fetches of each function, counted through loops and helper calls."""
    code = reader.code
    by_name: dict[str, list[dict[str, Any]]] = {}
    for function in functions:
        by_name.setdefault(function['name'], []).append(function)
    counts: dict[str, int] = {}
    busy: set[str] = set()

    def count(name: str) -> int:
        if name in counts:
            return counts[name]
        if name in busy:
            message = f'calls {name} back from itself, which GLSL refuses'
            if message not in problems:
                problems.append(message)
            return 0
        busy.add(name)
        # Overloads share a name, so a call counts the costliest of them.
        total = 0
        for function in by_name[name]:
            start, end = function['body']
            cost = 0
            for match in _CALL.finditer(code, start, end):
                callee = match.group(1)
                if callee in FETCHES:
                    cost += reader.weight(match.start(), start)
                elif callee in by_name:
                    cost += reader.weight(match.start(), start) * count(callee)
            total = max(total, cost)
        busy.discard(name)
        counts[name] = total
        return total

    for name in by_name:
        count(name)
    return counts


def _directives(
    reader: _Reader, mode: str, sections: list[tuple[str, int]], defines: list[tuple[int, str]]
) -> str:
    """Checks the directive lines of the code and returns the code with them as spaces."""
    code = reader.code
    out = list(code)
    offset = 0
    for line in code.split('\n'):
        stripped = line.lstrip()
        if stripped.startswith('#'):
            at = offset + len(line) - len(stripped)
            match = re.match(r'#\s*([A-Za-z_]\w*)?\s*(.*)', stripped)
            word, rest = (match.group(1) or ''), match.group(2).strip()
            if word == 'version':
                reader.note(at, 'sets the version, which the renderer writes')
            elif word == 'extension':
                reader.note(at, 'enables an extension, which a package leaves to the renderer')
            elif word == 'include':
                name = re.fullmatch(r'<\s*([\w.]+)\s*>', rest)
                if not name or name.group(1) not in INCLUDES:
                    reader.note(at, f'includes {rest}, of which only <cuju_noise> is available')
            elif word == 'pragma' and re.match(r'cuju\b', rest):
                section = re.fullmatch(r'cuju\s+(vertex|fragment)', rest)
                if mode != 'material':
                    reader.note(at, 'starts a section, which only a file of mode material has')
                elif not section:
                    reader.note(at, f'holds the unknown pragma {rest}')
                else:
                    sections.append((section.group(1), offset + len(line)))
            elif word in ('define', 'undef'):
                defines.append((at, rest))
            elif word and word not in _DIRECTIVES and word != 'pragma':
                reader.note(at, f'holds the unknown directive #{word}')
            out[offset : offset + len(line)] = ' ' * len(line)
        offset += len(line) + 1
    return ''.join(out)


def _macros(reader: _Reader, defines: list[tuple[int, str]], helpers: set[str]) -> None:
    """Checks the names and bodies of the macros, which may hide neither loops nor fetches."""
    for at, rest in defines:
        match = re.match(r'([A-Za-z_]\w*)(.*)', rest)
        if not match:
            reader.note(at, 'defines a macro without a name')
            continue
        name, body = match.group(1), match.group(2)
        if _RENDERER_NAME.fullmatch(name) or name in HOOKS:
            reader.note(at, f'defines {name}, a name the renderer owns')
        elif name in _KEYWORDS or name in FETCHES:
            reader.note(at, f'defines {name}, a word of GLSL')
        if '##' in body:
            reader.note(at, 'pastes tokens in a macro, which a package may not')
        words = set(re.findall(r'[A-Za-z_]\w*', body))
        hidden = sorted(words & ({'for', 'while', 'do', 'uniform'} | FETCHES | helpers))
        if hidden:
            reader.note(at, f'hides {hidden[0]} in a macro, write it out in the code')


def check(text: str, mode: str = 'chunks') -> list[str]:
    """Checks the text of a shader of a package and returns its problems.

    Args:
        text: The text of the `.glsl` file.
        mode: `chunks`, hooks into the renderer's standard material, or `material`, a whole
            shader material of a vertex and a fragment section.

    Returns:
        The problems as short sentences, each naming its line where it has one, empty when the
        shader passes.
    """
    if mode not in MODES:
        return [f'expected the mode chunks or material, found {mode!r}']
    problems: list[str] = []
    if len(text.encode('utf-8', 'surrogatepass')) > MAXIMUM_BYTES:
        problems.append(f'holds more than {MAXIMUM_BYTES // 1024} KB')
    reader = _Reader(text, _clean(text), problems)
    sections: list[tuple[str, int]] = []
    defines: list[tuple[int, str]] = []
    reader.code = _directives(reader, mode, sections, defines)
    code = reader.code
    reader.constants = _constants(code)
    closes = re.search(r'\bdo\b', code) is not None
    for word, message in (
        ('uniform', 'declares a uniform, the renderer declares every uniform from the manifest'),
        ('while', 'holds a while loop, use a for loop of a fixed count'),
        ('do', 'holds a do loop, use a for loop of a fixed count'),
    ):
        for match in re.finditer(rf'\b{word}\b', code):
            # The while that closes a do loop belongs to the do loop's own problem.
            if word == 'while' and closes and code[: match.start()].rstrip().endswith('}'):
                continue
            reader.note(match.start(), message)
    if code.count('{') != code.count('}') or code.count('(') != code.count(')'):
        problems.append('holds braces or parentheses that do not pair up')
    reader.loops_of()
    functions = reader.functions()
    _macros(reader, defines, {f['name'] for f in functions})
    if mode == 'chunks':
        counts = _fetches(reader, functions, problems)
        names = {f['name']: f for f in functions}
        hooks = [name for name in HOOKS if name in names]
        if not hooks:
            problems.append(
                'defines none of the hooks cujuVertex, cujuColor, cujuEmissive, cujuRoughness '
                'and cujuMetalness'
            )
        for name in hooks:
            if names[name]['type'] != HOOKS[name]:
                reader.note(
                    names[name]['at'],
                    f'defines {name} returning {names[name]["type"]}, the hook returns '
                    f'{HOOKS[name]}',
                )
        if 'main' in names:
            reader.note(names['main']['at'], 'defines main, which the standard material holds')
        fetches = sum(counts.get(name, 0) for name in hooks)
        where = 'the hooks fetch'
    else:
        fetches = _material(reader, functions, sections, problems)
        where = 'the fragment section fetches'
    if fetches > MAXIMUM_FETCHES:
        problems.append(f'{where} textures {fetches} times, at most {MAXIMUM_FETCHES}')
    return problems


def _material(
    reader: _Reader,
    functions: list[dict[str, Any]],
    sections: list[tuple[str, int]],
    problems: list[str],
) -> int:
    """Checks the two sections of a file of mode material and returns the fragment's fetches."""
    kinds = [kind for kind, _ in sections]
    for kind in ('vertex', 'fragment'):
        if kinds.count(kind) != 1:
            problems.append(f'expected one line #pragma cuju {kind}, found {kinds.count(kind)}')
    if kinds.count('vertex') != 1 or kinds.count('fragment') != 1:
        return 0
    vertex = dict(sections)['vertex']
    fragment = dict(sections)['fragment']
    if vertex > fragment:
        problems.append('expected #pragma cuju vertex before #pragma cuju fragment')
        return 0
    shared = [f for f in functions if f['at'] < vertex]
    fetches = 0
    for kind, low, high in (('vertex', vertex, fragment), ('fragment', fragment, len(reader.code))):
        own = [f for f in functions if low <= f['at'] < high]
        main = [f for f in own if f['name'] == 'main']
        if not main or main[0]['type'] != 'void' or main[0]['parameters'] not in ('', 'void'):
            problems.append(f'the {kind} section defines no void main()')
            continue
        names = {f['name'] for f in own}
        visible = [f for f in shared if f['name'] not in names] + own
        counts = _fetches(reader, visible, problems)
        if kind == 'fragment':
            fetches = counts.get('main', 0)
    return fetches


def shaders(manifest: Any) -> list[tuple[str, str]]:
    """Returns the distinct shader files and modes that the materials, effects and post name.

    A material's shader is of mode chunks unless it names material, and the shaders of effects
    and post passes, which draw the package's own objects, are of mode material unless they name
    chunks.
    """
    found: set[tuple[str, str]] = set()
    if not isinstance(manifest, dict):
        return []

    def add(entry: Any, default: str) -> None:
        if isinstance(entry, dict) and isinstance(entry.get('shader'), str):
            mode = entry.get('mode', default)
            found.add((entry['shader'], mode if mode in MODES else default))
        if isinstance(entry, dict) and isinstance(entry.get('rules'), list):
            for rule in entry['rules']:
                add(rule, default)

    for key, default in (('materials', 'chunks'), ('effects', 'material'), ('post', 'material')):
        section = manifest.get(key)
        if isinstance(section, dict):
            section = list(section.values())
        for entry in section if isinstance(section, list) else []:
            add(entry, default)
    return sorted(found)


def programs(manifest: Any) -> int:
    """Returns the shader programs a manifest costs, one for each distinct shader file and mode."""
    return len(shaders(manifest))
