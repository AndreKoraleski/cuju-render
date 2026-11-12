# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the languages of the page and the messages of the server."""

import re
from pathlib import Path

import pytest

from cuju.render._http import server as _server
from support.common import TRANSLATIONS, _shipped_language, _translation


def test_server_messages_match_the_english_file():
    from cuju.render._text import messages as _messages

    assert _messages.MESSAGES and all(key.startswith('server.') for key in _messages.MESSAGES)
    assert _messages.compare(_shipped_language('en')) == []


def test_server_messages_have_portuguese_with_the_same_placeholders():
    from cuju.render._text import messages as _messages

    portuguese = _translation('pt-BR')
    assert _messages.compare(portuguese) == []
    for key, template in _messages.MESSAGES.items():
        if key in portuguese:
            assert _messages.placeholders(portuguese[key]) == _messages.placeholders(template), key
    # A draft may lack a message, which the page then shows in English.
    draft = {key: value for key, value in portuguese.items() if key != 'server.body_size'}
    assert _messages.compare(draft) == []


# A message id of the server as Python names it, whole or as the start of an f-string, and one
# that ends in a period starts the ids of a kind. A file name such as server.json is no id.
_ID = re.compile(r"""(f?)['"](server\.[A-Za-z0-9_.]*)(\{?)""")
_FILES = ('.json', '.log')


def test_every_server_message_that_the_source_names_is_known():
    """An id that Python names, in a MessageError, a label or the fields of an answer, is a message
    of the registry, so the page finds it in both language files with the same placeholders."""
    from cuju.render._text import messages as _messages

    root = Path(_messages.__file__).parents[1]
    unknown = []
    for path in sorted(root.rglob('*.py')):
        for formatted, found, brace in _ID.findall(path.read_text(encoding='utf-8')):
            if (formatted and brace) or found.endswith('.'):
                if not any(key.startswith(found) for key in _messages.MESSAGES):
                    unknown.append(f'{path.name}: {found}...')
            elif not found.endswith(_FILES) and found not in _messages.MESSAGES:
                unknown.append(f'{path.name}: {found}')
    assert not unknown


def test_english_ships_alone_and_the_portuguese_draft_is_well_formed():
    from cuju.render._text import languages as _languages

    shipped = sorted(path.stem for path in _languages.SHIPPED.glob('*.json'))
    assert shipped == ['en']
    report = _languages.check(_shipped_language('en'), 'en')
    assert report['ok'] and report['code'] == 'en', report['malformed'][:5]
    # The draft may lack messages, and each one it has matches English, its placeholders, its
    # plural forms and its marks. Its file is named after its code, as the check of a file asks.
    path = Path(TRANSLATIONS) / 'pt-BR' / 'pt-BR.json'
    assert sorted(item.name for item in path.parent.iterdir()) == [
        'glossary.json',
        'pt-BR.json',
        'style.md',
    ]
    assert _languages.valid_code(path.stem)
    report = _languages.check(_translation('pt-BR'), path.stem)
    assert not report['unused'] and not report['malformed'], report['malformed'][:5]
    assert report['code'] == 'pt-BR'
    header = _translation('pt-BR')['@language']
    assert (header['locale'], header['plurals']) == ('pt-BR', ['one', 'many', 'other'])
    # The plural categories come from the base language, pt.
    lacking = dict(_translation('pt-BR'), **{'@language': dict(header, plurals=['one', 'other'])})
    problems = [item['problem'] for item in _languages.check(lacking, 'pt-BR')['malformed']]
    assert 'expected the plural categories of pt, the file lacks many' in problems
    # Portuguese translates nearly every message, the rest are names and symbols.
    assert len(report['untranslated']) < 100


def test_codes_differ_in_case_alone_as_bcp_47_has_them(render_home):
    from cuju.render._text import languages as _languages

    assert _languages.valid_code('pt-BR') and _languages.valid_code('zh-Hant-TW')
    assert not _languages.valid_code('pt_BR') and not _languages.valid_code('../en')
    entry = _languages.add(_translation('pt-BR'))
    assert entry['code'] == 'pt-BR'
    assert [path.name for path in _languages.folder().glob('*.json')] == ['pt-BR.json']
    assert _languages.read('pt-br')['@language']['code'] == 'pt-BR'
    # A file of the same language whose code differs in case alone takes the place of the first.
    lower = dict(_translation('pt-BR'))
    lower['@language'] = dict(lower['@language'], code='pt-br')
    assert _languages.add(lower)['code'] == 'pt-br'
    assert [path.name for path in _languages.folder().glob('*.json')] == ['pt-br.json']
    with pytest.raises(ValueError):
        _languages.add(dict(lower, **{'@language': dict(lower['@language'], code='EN')}))
    assert _languages.remove('PT-BR') == {'code': 'PT-BR', 'removed': True}
    assert list(_languages.folder().glob('*.json')) == []


def test_language_check_holds_a_translation_to_the_marks_of_english():
    from cuju.render._text import languages as _languages

    english = {
        '@language': {'code': 'en', 'name': 'English', 'plurals': ['one', 'other']},
        'a.run': 'Run `cuju render serve` **now**',
    }
    header = {'code': 'xx', 'name': 'Test', 'plurals': ['other']}
    good = {'@language': header, 'a.run': 'Rode `cuju render serve` **agora**'}
    assert _languages.check(good, 'xx', english)['malformed'] == []
    # Bold words are the translator's choice, so a message may stress other words or none.
    for text in ('Rode `cuju render serve` agora', '**Rode** `cuju render serve` agora'):
        fine = {'@language': header, 'a.run': text}
        assert _languages.check(fine, 'xx', english)['malformed'] == []
    bad = {'@language': header, 'a.run': 'Rode cuju render serve **agora**'}
    problems = _languages.check(bad, 'xx', english)['malformed']
    assert [item['problem_id'] for item in problems] == ['server.language.problem.marks']


def test_language_check_names_missing_unused_and_malformed_messages():
    from cuju.render._text import languages as _languages

    english = {
        '@language': {'code': 'en', 'name': 'English', 'plurals': ['one', 'other']},
        'a.text': 'Hello {name}',
        'a.count': {'one': '{count} goal', 'other': '{count} goals'},
        'a.left': 'Left',
        'caption.goal': 'Goal, {player}',
        'a.saved': 'Saved {count} files',
    }
    document = {
        '@language': {'code': 'xx', 'name': 'Test', 'plurals': ['one', 'few', 'other']},
        'a.text': 'Hi {person}',
        'a.count': {'one': 'one goal', 'other': '{count} goals'},
        'a.extra': 'Not in English',
        'caption.goal': {'one': 'Goal', 'other': 'Goal, {player}'},
        'a.saved': {'one': '{count} file', 'few': '{count} files', 'other': '{count} files'},
    }
    report = _languages.check(document, 'xx', english)
    assert not report['ok']
    assert report['missing'] == ['a.left'] and report['unused'] == ['a.extra']
    problems = {item['id']: item['problem'] for item in report['malformed']}
    assert problems['a.text'] == 'expected the placeholders of English, found {person}'
    assert problems['a.count'] == 'expected the plural forms few of the language'
    assert 'captions have no plural forms' in problems['caption.goal']
    # A language may count what English leaves alone, when the English text holds {count}.
    assert 'a.saved' not in problems
    # The plural categories of a known language must all be there.
    polish = dict(
        document, **{'@language': {'code': 'pl', 'name': 'Polski', 'plurals': ['one', 'other']}}
    )
    problems = [item['problem'] for item in _languages.check(polish, 'pl', english)['malformed']]
    assert 'expected the plural categories of pl, the file lacks few, many' in problems
    header = [
        item['problem']
        for item in _languages.check({'@language': {'code': 'pt_BR'}}, None, english)['malformed']
    ]
    assert any(problem.startswith('expected a code of letters and digits') for problem in header)
    assert _languages.check([], None, english)['malformed'][0]['id'] == '@language'


def test_game_input_names_the_sides_a_person_plays():
    from cuju.render._text.messages import MessageError

    games = _server._Games()
    with pytest.raises(_server.NoGameError):
        games.input('g-1', {'side': 0})
    for humans, side, sides in (
        ([True, False], 1, '0 for the left'),
        ([False, True], 0, '1 for the right'),
        ([True, True], 2, '0 for the left or 1 for the right'),
    ):
        games._entry = {'id': 'g-1', 'humans': humans, 'state': 'playing'}
        with pytest.raises(MessageError) as refused:
            games.input('g-1', {'side': side})
        assert refused.value.message_id == 'server.game.side'
        assert refused.value.values['sides']['text'] == sides
        assert str(refused.value) == (
            f'expected a side that a person plays in this game, {sides}, found {side}'
        )
