# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""The routes of the languages under /api/languages for the mock server, as cuju.render has them.

The shipped languages are the files of web/languages, and the languages a page imports stay in
memory. An import is checked as the real server checks it, by its header and by the placeholders
and plural forms of each message against English, and a malformed file is refused with the id of
its message.
"""

import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / 'src' / 'cuju' / 'render' / 'web'
SHIPPED = WEB / 'languages'
CODE = re.compile(r'[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*')
PLACEHOLDER = re.compile(r'\{([A-Za-z0-9_]+)\}')
OWN = {}


def _own(code):
    """Returns the code of an imported language that `code` names, whatever its case."""
    return next((key for key in OWN if key.lower() == str(code).lower()), None)


def _shipped(code):
    """Returns the file of a shipped language that `code` names, whatever its case."""
    if not isinstance(code, str) or not CODE.fullmatch(code):
        return None
    return next(
        (path for path in SHIPPED.glob('*.json') if path.stem.lower() == code.lower()), None
    )


def _english():
    return json.loads((SHIPPED / 'en.json').read_text(encoding='utf-8'))


def _refuse(status, message_id, text, **values):
    values = {key: str(value) for key, value in values.items()}
    filled = PLACEHOLDER.sub(lambda match: values[match.group(1)], text)
    return {'error': filled, 'error_id': message_id, 'error_values': values}, status


def _entry(code, document, source):
    header = document.get('@language', {})
    english = _english()
    return {
        'code': code,
        'name': header.get('name', code),
        'english': header.get('english', ''),
        'locale': header.get('locale', code),
        'dir': header.get('dir', 'ltr'),
        'source': source,
        'usable': True,
        'messages': len(document) - 1,
        'missing': len([key for key in english if key not in document]),
        'problems': [],
    }


def _places(value):
    forms = value.values() if isinstance(value, dict) else [value]
    return {name for form in forms if isinstance(form, str) for name in PLACEHOLDER.findall(form)}


def _problem(document):
    english = _english()
    plurals = document['@language'].get('plurals', ['other'])
    for key, value in document.items():
        if key == '@language':
            continue
        if isinstance(value, dict):
            if not all(isinstance(form, str) for form in value.values()):
                return f'{key}, expected plural forms as texts'
            lacking = [form for form in plurals if form not in value]
            if lacking:
                return f'{key}, expected the plural forms {", ".join(lacking)} of the language'
        elif not isinstance(value, str):
            return f'{key}, expected a text or an object of plural forms'
        if key in english:
            extra = sorted(_places(value) - _places(english[key]))
            if extra:
                found = ', '.join('{' + name + '}' for name in extra)
                return f'{key}, expected the placeholders of English, found {found}'
    return None


def get(parts):
    """Answers GET /api/languages and GET /api/languages/CODE."""
    if not parts:
        shipped = sorted(SHIPPED.glob('*.json'), key=lambda path: (path.stem != 'en', path.stem))
        entries = [
            _entry(path.stem, json.loads(path.read_text(encoding='utf-8')), 'shipped')
            for path in shipped
        ]
        entries += [_entry(code, document, 'home') for code, document in sorted(OWN.items())]
        return {'languages': entries}, 200
    code = parts[0]
    if len(parts) == 1 and _shipped(code) is not None:
        return json.loads(_shipped(code).read_text(encoding='utf-8')), 200
    if len(parts) == 1 and _own(code) is not None:
        return OWN[_own(code)], 200
    return _refuse(404, 'server.language.none', 'no language {code}', code=code)


def post(parts, body):
    """Answers POST /api/languages with a language file as its body."""
    if parts:
        return _refuse(404, 'server.no_resource', 'no such resource')
    try:
        document = json.loads(body.decode('utf-8'))
    except ValueError:
        document = None
    if not isinstance(document, dict) or not isinstance(document.get('@language'), dict):
        return _refuse(
            400,
            'server.language.json',
            'expected a language file, a JSON object with its header @language',
        )
    code = document['@language'].get('code')
    if not isinstance(code, str) or not CODE.fullmatch(code):
        return _refuse(
            400,
            'server.language.code',
            'expected a language code of letters and digits in parts joined by hyphens, such as pt '
            'or pt-BR, found {code}',
            code=code,
        )
    if _shipped(code) is not None:
        return _refuse(
            400,
            'server.language.shipped',
            'the language {code} ships with cuju, name your file with another code, such as '
            '{code}-x-mine',
            code=code,
        )
    problem = _problem(document)
    if problem:
        return _refuse(
            400,
            'server.language.malformed',
            'expected well formed messages, found {first}',
            first=problem,
        )
    # A language whose code differs in case alone gives way to the new file.
    OWN.pop(_own(code), None)
    OWN[code] = document
    return _entry(code, document, 'home'), 201


def delete(parts):
    """Answers DELETE /api/languages/CODE for a language the page imported."""
    if len(parts) == 1 and _own(parts[0]) is not None:
        code = _own(parts[0])
        del OWN[code]
        return {'code': code, 'removed': True}, 200
    code = parts[0] if parts else ''
    return _refuse(404, 'server.language.none', 'no language {code}', code=code)


SLOT = b'<script type="application/json" id="cuju-languages"></script>'


def inline(page):
    """Fills the empty language block of a page with the shipped languages, as the server does."""
    if SLOT not in page:
        return page
    files = {
        path.stem: json.loads(path.read_text(encoding='utf-8'))
        for path in sorted(SHIPPED.glob('*.json'))
    }
    text = json.dumps(files, ensure_ascii=False, separators=(',', ':')).replace('<', r'\u003c')
    return page.replace(SLOT, SLOT.replace(b'></', b'>' + text.encode('utf-8') + b'</', 1))
