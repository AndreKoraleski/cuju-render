# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The languages of the page, the shipped files and those of the renderer's home folder.

A language file is one JSON object keyed by message id, such as `home.title`, whose values are
texts with placeholders in braces, such as `{count} recordings`, or objects of plural forms keyed
by the categories of Unicode CLDR, `zero`, `one`, `two`, `few`, `many` and `other`, and by exact
counts such as `=0`. The key `@language` holds the code, the name, the English name, the locale of
numbers and dates, the direction of the text and the plural categories of the language.

The page ships English and Brazilian Portuguese in `web/languages`, and a person adds a language
by dropping its file, named after its code, into the folder `languages` of the home folder, or by
importing it on the Settings panel. English is the reference of every other file. `check` reports
the messages a file lacks, those English lacks, and malformed ones, whose placeholders differ from
English or whose plural forms miss a category of the language. `template` writes a new file from
English, and `get`, `post` and `delete` answer `/api/languages`.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .._store import home as _home
from . import messages as _messages
from .messages import MessageError, counted

SHIPPED = Path(__file__).parents[1] / 'web' / 'languages'
HEADER = '@language'
# A language file of the home folder holds at most this many bytes.
MAXIMUM_BYTES = 2 * 1024 * 1024

_CODE = re.compile(r'[a-z]{2,3}(-[a-z0-9]{1,8})*')
_ID = re.compile(r'[A-Za-z0-9_.-]+')
_PLACEHOLDER = re.compile(r'\{([A-Za-z0-9_]+)\}')
_EXACT = re.compile(r'=\d+')
CATEGORIES = ('zero', 'one', 'two', 'few', 'many', 'other')

# The plural categories of the cardinal numbers of common languages, by base language, as
# Intl.PluralRules gives them from Unicode CLDR. A language missing here declares its own.
_GROUPS = {
    ('one', 'other'): (
        'af am az bg bn da de el en et eu fa fi fil gl gu hi hu hy is ka kk kn ky mk ml mn mr nb '
        'ne nl pa ps si sq sv sw ta te tr ur uz zu'
    ),
    ('zero', 'one', 'two', 'few', 'many', 'other'): 'ar cy',
    ('one', 'few', 'many', 'other'): 'be cs lt pl ru sk uk',
    ('one', 'few', 'other'): 'bs hr ro sr',
    ('one', 'many', 'other'): 'ca es fr it pt',
    ('one', 'two', 'few', 'many', 'other'): 'ga',
    ('one', 'two', 'other'): 'he',
    ('other',): 'id ja km ko lo ms my th vi zh',
    ('zero', 'one', 'other'): 'lv',
    ('one', 'two', 'few', 'other'): 'sl',
}
PLURALS = {code: list(group) for group, codes in _GROUPS.items() for code in codes.split()}
# Languages written from right to left.
_RTL = {'ar', 'fa', 'he', 'ps', 'ur', 'yi', 'dv', 'ug'}


def valid_code(code: Any) -> bool:
    """Returns whether `code` names a language file safely, such as `pt` or `pt-br`."""
    return isinstance(code, str) and bool(_CODE.fullmatch(code))


def folder() -> Path:
    """Returns the folder of the languages a person adds, created when missing."""
    return _home.folder('languages')


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def english() -> dict[str, Any]:
    """Returns the shipped English file, the reference of every other."""
    return _read(SHIPPED / 'en.json')


def placeholders(value: Any) -> set[str]:
    """Returns the placeholders of a message, of every form of a plural message."""
    if isinstance(value, str):
        return set(_PLACEHOLDER.findall(value))
    if isinstance(value, dict):
        return {
            name
            for form in value.values()
            if isinstance(form, str)
            for name in _PLACEHOLDER.findall(form)
        }
    return set()


def _problem(name: str, **values: Any) -> dict[str, Any]:
    """Returns a problem of a file as a label of the message `server.language.problem.<name>`."""
    return _messages.label(f'server.language.problem.{name}', **values)


def _header_problems(header: Any, code: str | None) -> list[dict[str, Any]]:
    if not isinstance(header, dict):
        return [_problem('header')]
    problems = []
    if not valid_code(header.get('code')):
        problems.append(_problem('code', code=repr(header.get('code'))))
    elif code is not None and header.get('code') != code:
        problems.append(_problem('file_code', code=repr(code), found=repr(header.get('code'))))
    if not isinstance(header.get('name'), str) or not header.get('name').strip():
        problems.append(_problem('name'))
    for key in ('english', 'locale'):
        if key in header and not isinstance(header[key], str):
            problems.append(_problem('text', key=key, value=repr(header[key])))
    if header.get('dir', 'ltr') not in ('ltr', 'rtl'):
        problems.append(_problem('dir', value=repr(header.get('dir'))))
    plurals = header.get('plurals')
    if not isinstance(plurals, list) or not plurals or not all(p in CATEGORIES for p in plurals):
        problems.append(_problem('plurals', categories=', '.join(CATEGORIES), value=repr(plurals)))
    elif 'other' not in plurals:
        problems.append(_problem('other'))
    else:
        base = str(header.get('code', '')).split('-')[0]
        lacking = [p for p in PLURALS.get(base, []) if p not in plurals]
        if lacking:
            problems.append(_problem('categories', language=base, lacking=', '.join(lacking)))
    return problems


def _message_problem(
    key: str, value: Any, reference: Any, plurals: list[str]
) -> dict[str, Any] | None:
    """Returns what is malformed about one message against its English as a label, or None."""
    if isinstance(value, str):
        if isinstance(reference, dict) and plurals != ['other']:
            return _problem('forms_expected')
    elif isinstance(value, dict):
        if not value or not all(isinstance(form, str) for form in value.values()):
            return _problem('form_texts')
        if key.startswith('caption.'):
            return _problem('caption')
        unknown = [form for form in value if form not in CATEGORIES and not _EXACT.fullmatch(form)]
        if unknown:
            return _problem('form_names', unknown=', '.join(unknown))
        lacking = [form for form in plurals if form not in value]
        if lacking:
            return _problem('forms_lacking', lacking=', '.join(lacking))
        # A language may count what English leaves alone, when the English text holds {count}.
        if isinstance(reference, str) and 'count' not in placeholders(reference):
            return _problem('text_expected')
    else:
        return _problem('kind')
    if reference is None:
        return None
    own, theirs = placeholders(value), placeholders(reference)
    extra = sorted(own - theirs)
    if extra:
        return _problem('extra', extra=', '.join('{' + p + '}' for p in extra))
    # A plural form may leave the count out, as in "one recording", every other value stays.
    lost = sorted(theirs - own - ({'count'} if isinstance(value, dict) else set()))
    if lost:
        return _problem('lost', lost=', '.join('{' + p + '}' for p in lost))
    # Commands and shortcuts are code and must survive, while bold words are the translator's
    # choice, since each language stresses its own words.
    if _code_spans(value) != _code_spans(reference):
        return _problem('marks')
    return None


def _code_spans(value: Any) -> int:
    """Returns how many code spans a message holds, its commands, names and shortcuts.

    A plural message counts the spans of its form `other`, which every language has.
    """
    text = value if isinstance(value, str) else (value or {}).get('other', '')
    found = _messages._MARK.findall(text if isinstance(text, str) else '')
    return sum(1 for _, code in found if code)


def check(
    document: Any, code: str | None = None, reference: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Checks a language file against English.

    Args:
        document: The parsed file.
        code: The code the file must name, that of its file name, or None for any.
        reference: The English file, by default the shipped one.

    Returns:
        A report with `code`, `name`, `messages`, `ok`, and lists `missing` and `unused` of ids,
        `malformed` of objects with `id` and `problem`, the English text of the problem, with its
        message in `problem_id` and `problem_values`, and `untranslated`, the ids whose text is
        the English one, which a template starts with and which is no fault of its own.
    """
    reference = english() if reference is None else reference
    report: dict[str, Any] = {
        'code': None,
        'name': None,
        'messages': 0,
        'missing': [],
        'unused': [],
        'malformed': [],
        'untranslated': [],
    }
    if not isinstance(document, dict):
        problem = _messages.named('problem', _problem('document'))
        report['malformed'].append({'id': HEADER, **problem})
        report['ok'] = False
        return report
    header = document.get(HEADER)
    if isinstance(header, dict):
        report['code'] = header.get('code')
        report['name'] = header.get('name')
    for problem in _header_problems(header, code):
        report['malformed'].append({'id': HEADER, **_messages.named('problem', problem)})
    plurals = (
        header.get('plurals')
        if isinstance(header, dict) and isinstance(header.get('plurals'), list)
        else ['other']
    )
    for key, value in document.items():
        if key == HEADER:
            continue
        if not _ID.fullmatch(key):
            report['malformed'].append({'id': key, **_messages.named('problem', _problem('id'))})
            continue
        report['messages'] += 1
        if key not in reference:
            report['unused'].append(key)
        problem = _message_problem(key, value, reference.get(key), plurals)
        if problem:
            report['malformed'].append({'id': key, **_messages.named('problem', problem)})
        elif report['code'] != 'en' and value == reference.get(key):
            report['untranslated'].append(key)
    report['missing'] = [key for key in reference if key != HEADER and key not in document]
    report['ok'] = not (report['missing'] or report['unused'] or report['malformed'])
    return report


def template(code: str, name: str | None = None) -> dict[str, Any]:
    """Returns a new language file for `code` with every English message, for a translator.

    The plural messages take the categories of the language, each filled with the English text of
    the nearest English form, and the header names the language with its code until it is set.
    """
    if not valid_code(code):
        raise MessageError('server.language.code', code=code)
    base = code.split('-')[0]
    plurals = PLURALS.get(base, ['one', 'other'])
    document: dict[str, Any] = {
        HEADER: {
            'code': code,
            'name': name or code,
            'english': '',
            'locale': code,
            'dir': 'rtl' if base in _RTL else 'ltr',
            'plurals': plurals,
        }
    }
    for key, value in english().items():
        if key == HEADER:
            continue
        if isinstance(value, dict):
            forms = {
                form: value.get(
                    form, value.get('one' if form in ('zero', 'one') else 'other', value['other'])
                )
                for form in plurals
            }
            document[key] = forms if plurals != ['other'] else value['other']
        else:
            document[key] = value
    return document


def _entry(document: Any, code: str, source: str, reference: dict[str, Any]) -> dict[str, Any]:
    report = check(document, code, reference)
    header = document.get(HEADER) if isinstance(document, dict) else None
    header = header if isinstance(header, dict) else {}
    return {
        'code': code,
        'name': header.get('name') if isinstance(header.get('name'), str) else code,
        'english': header.get('english') if isinstance(header.get('english'), str) else '',
        'locale': header.get('locale') if isinstance(header.get('locale'), str) else code,
        'dir': 'rtl' if header.get('dir') == 'rtl' else 'ltr',
        'source': source,
        'usable': not report['malformed'],
        'messages': report['messages'],
        'missing': len(report['missing']),
        'problems': [f'{item["id"]}, {item["problem"]}' for item in report['malformed'][:20]],
    }


def listing() -> list[dict[str, Any]]:
    """Returns the languages, the shipped ones first, English first among them, then the own.

    Each entry names its code, name, English name, locale, direction, source `shipped` or `home`,
    whether the page can use it, the counts of its messages and of the English messages it lacks,
    and the problems that make it unusable.
    """
    reference = english()
    entries = []
    shipped = sorted(SHIPPED.glob('*.json'), key=lambda path: (path.stem != 'en', path.stem))
    for path in shipped:
        entries.append(_entry(_read(path), path.stem, 'shipped', reference))
    names = {entry['code'] for entry in entries}
    for path in sorted(folder().glob('*.json'), key=lambda path: path.stem):
        if path.stem in names or not valid_code(path.stem):
            continue
        try:
            document = _read(path)
        except (OSError, ValueError) as error:
            entries.append(
                {
                    'code': path.stem,
                    'name': path.stem,
                    'english': '',
                    'locale': path.stem,
                    'dir': 'ltr',
                    'source': 'home',
                    'usable': False,
                    'messages': 0,
                    'missing': 0,
                    'problems': [f'the file is not JSON, {error}'],
                }
            )
            continue
        entries.append(_entry(document, path.stem, 'home', reference))
    return entries


_SLOT = b'<script type="application/json" id="cuju-languages"></script>'
_INLINE: dict[str, Any] = {'key': None, 'text': b''}


def inline(page: bytes) -> bytes:
    """Fills the empty language block of a page with every shipped language file.

    The page reads its messages from the block, so it starts without another request. Every `<`
    of the files is escaped, so no text of a message can close the block.
    """
    if _SLOT not in page:
        return page
    paths = sorted(SHIPPED.glob('*.json'))
    key = tuple((path.name, path.stat().st_mtime_ns) for path in paths)
    if _INLINE['key'] != key:
        files = {path.stem: _read(path) for path in paths}
        text = json.dumps(files, ensure_ascii=False, separators=(',', ':')).replace('<', r'\u003c')
        _INLINE.update(key=key, text=text.encode('utf-8'))
    return page.replace(_SLOT, _SLOT.replace(b'></', b'>' + _INLINE['text'] + b'</', 1))


def read(code: str) -> dict[str, Any]:
    """Returns the file of a language, shipped or of the home folder."""
    if not valid_code(code):
        raise MessageError('server.language.code', code=code)
    for path in (SHIPPED / f'{code}.json', folder() / f'{code}.json'):
        if path.is_file():
            return _read(path)
    raise MessageError('server.language.none', code=code)


def add(document: Any) -> dict[str, Any]:
    """Keeps a checked language file in the home folder and returns its entry and report.

    A file whose messages are malformed is refused with the reasons. Missing messages are allowed,
    the page shows them in English, and so are messages English lacks, which the page never reads.

    Raises:
        MessageError: If the file is malformed or names a shipped language.
    """
    if not isinstance(document, dict) or not isinstance(document.get(HEADER), dict):
        raise MessageError('server.language.json')
    code = document[HEADER].get('code')
    if not valid_code(code):
        raise MessageError('server.language.code', code=code)
    if (SHIPPED / f'{code}.json').is_file():
        raise MessageError('server.language.shipped', code=code)
    report = check(document, code)
    if report['malformed']:
        first = report['malformed'][0]
        problem = {
            'id': first.get('problem_id'),
            'text': first['problem'],
            'values': first.get('problem_values') or {},
        }
        place = _messages.label('server.language.problem_at', id=first['id'], problem=problem)
        raise MessageError('server.language.malformed', first=place)
    body = json.dumps(document, ensure_ascii=False, indent=4) + '\n'
    if len(body.encode('utf-8')) > MAXIMUM_BYTES:
        raise MessageError('server.language.size', most=MAXIMUM_BYTES // (1024 * 1024))
    target = folder() / f'{code}.json'
    temporary = target.with_name(f'.{code}.json.tmp')
    temporary.write_text(body, encoding='utf-8', newline='\n')
    os.replace(temporary, target)
    entry = _entry(document, code, 'home', english())
    entry['report'] = {key: report[key] for key in ('missing', 'unused', 'untranslated')}
    return entry


def remove(code: str) -> dict[str, Any]:
    """Removes a language of the home folder and returns its code."""
    if not valid_code(code):
        raise MessageError('server.language.code', code=code)
    if (SHIPPED / f'{code}.json').is_file():
        raise MessageError('server.language.keep', code=code)
    path = folder() / f'{code}.json'
    if not path.is_file():
        raise MessageError('server.language.none', code=code)
    path.unlink()
    return {'code': code, 'removed': True}


def _refusal(error: MessageError, status: int) -> tuple[dict[str, Any], int]:
    return {'error': str(error), 'error_id': error.message_id, 'error_values': error.values}, status


def get(parts: list[str]) -> tuple[Any, int]:
    """Answers `GET /api/languages` and `GET /api/languages/CODE`."""
    if not parts:
        return {'languages': listing()}, 200
    if len(parts) == 1:
        try:
            return read(parts[0]), 200
        except MessageError as error:
            return _refusal(error, 404 if error.message_id == 'server.language.none' else 400)
    return _refusal(MessageError('server.no_resource'), 404)


def post(parts: list[str], body: bytes) -> tuple[Any, int]:
    """Answers `POST /api/languages` with a language file as its body."""
    if parts:
        return _refusal(MessageError('server.no_resource'), 404)
    if len(body) > MAXIMUM_BYTES:
        return _refusal(
            MessageError('server.language.size', most=MAXIMUM_BYTES // (1024 * 1024)), 413
        )
    try:
        document = json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        return _refusal(MessageError('server.language.json'), 400)
    try:
        return add(document), 201
    except MessageError as error:
        return _refusal(error, 400)


def delete(parts: list[str]) -> tuple[Any, int]:
    """Answers `DELETE /api/languages/CODE` for a language of the home folder."""
    if len(parts) != 1:
        return _refusal(MessageError('server.no_resource'), 404)
    try:
        return remove(parts[0]), 200
    except MessageError as error:
        return _refusal(error, 404 if error.message_id == 'server.language.none' else 400)


def add_arguments(parser: Any) -> None:
    """Adds the arguments of `cuju render language` to its parser."""
    parser.add_argument('action', choices=('list', 'new', 'check', 'add', 'remove'))
    parser.add_argument(
        'target',
        nargs='?',
        help='the code of a new or removed language, or the language file to check or add',
    )
    parser.add_argument('-o', '--out', help='the file that new writes, by default CODE.json')
    parser.add_argument('--name', help='the name of a new language in itself, such as Deutsch')
    parser.add_argument('--json', action='store_true', help='print the result as JSON')


def _print_report(report: dict[str, Any], path: str) -> None:
    name = report.get('name') or report.get('code') or path
    print(f'{path}, {name}, {counted(report["messages"], "message")}')
    for key in report['missing']:
        print(f'  missing {key}')
    for key in report['unused']:
        print(f'  unused {key}')
    for item in report['malformed']:
        print(f'  malformed {item["id"]}, {item["problem"]}')
    if report['untranslated']:
        print(f'  {counted(len(report["untranslated"]), "message")} read as in English')
    print('ok' if report['ok'] else 'not ok')


def run(options: Any) -> int:
    """Runs `cuju render language`, and returns the exit status.

    `new CODE` writes a template from English, `check FILE` reports missing, unused and malformed
    messages and exits with 1 when it finds any, `list` prints the languages, `add FILE` keeps a
    checked file in the home folder and `remove CODE` removes one of them.
    """
    action, target = options.action, options.target
    if action != 'list' and not target:
        print(f'cuju render: expected what language {action} reads or writes', file=sys.stderr)
        return 2
    try:
        if action == 'new':
            document = template(target, options.name)
            path = Path(options.out or f'{target}.json')
            path.write_text(
                json.dumps(document, ensure_ascii=False, indent=4) + '\n',
                encoding='utf-8',
                newline='\n',
            )
            if options.json:
                print(
                    json.dumps({'code': target, 'path': str(path), 'messages': len(document) - 1})
                )
            else:
                print(f'wrote {path}, {counted(len(document) - 1, "message")} from English')
            return 0
        if action == 'check':
            path = Path(target)
            try:
                document = json.loads(path.read_text(encoding='utf-8'))
            except ValueError as error:
                report = {
                    'code': None,
                    'name': None,
                    'messages': 0,
                    'missing': [],
                    'unused': [],
                    'malformed': [{'id': HEADER, 'problem': f'the file is not JSON, {error}'}],
                    'untranslated': [],
                    'ok': False,
                }
            else:
                code = path.stem if valid_code(path.stem) else None
                report = check(document, code)
            if options.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                _print_report(report, str(path))
            return 0 if report['ok'] else 1
        if action == 'list':
            entries = listing()
            if options.json:
                print(json.dumps(entries, ensure_ascii=False, indent=2))
            else:
                for entry in entries:
                    state = 'usable' if entry['usable'] else 'refused'
                    print(f'{entry["code"]}  {entry["source"]}  {state}  {entry["name"]}')
            return 0
        if action == 'add':
            entry = add(json.loads(Path(target).read_text(encoding='utf-8')))
            if options.json:
                print(json.dumps(entry, ensure_ascii=False, indent=2))
            else:
                print(
                    f'added {entry["code"]} {entry["name"]}, {entry["missing"]} '
                    f'{"message shows" if entry["missing"] == 1 else "messages show"} in English'
                )
            return 0
        result = remove(target)
        print(json.dumps(result) if options.json else f'removed {result["code"]}')
        return 0
    except ValueError as error:
        if options.json:
            print(json.dumps({'error': str(error), 'error_id': getattr(error, 'message_id', None)}))
        print(f'cuju render: {error}', file=sys.stderr)
        return 1
    except OSError as error:
        print(f'cuju render: {error}', file=sys.stderr)
        return 1
