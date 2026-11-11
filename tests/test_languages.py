# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the languages of the page and the messages of the server."""

import pytest

from cuju.render._http import server as _server
from support.common import _shipped_language


def test_server_messages_match_the_english_file():
    from cuju.render._text import messages as _messages

    assert _messages.MESSAGES and all(key.startswith('server.') for key in _messages.MESSAGES)
    assert _messages.compare(_shipped_language('en')) == []


def test_server_messages_have_portuguese_with_the_same_placeholders():
    from cuju.render._text import messages as _messages

    portuguese = _shipped_language('pt')
    assert _messages.compare(portuguese) == []
    for key, template in _messages.MESSAGES.items():
        assert _messages.placeholders(portuguese[key]) == _messages.placeholders(template), key


def test_shipped_languages_are_complete_and_well_formed():
    from cuju.render._text import languages as _languages

    shipped = sorted(path.stem for path in _languages.SHIPPED.glob('*.json'))
    assert {'en', 'pt'} <= set(shipped)
    for code in shipped:
        report = _languages.check(_shipped_language(code), code)
        assert report['ok'], (
            code,
            report['missing'][:5],
            report['unused'][:5],
            report['malformed'][:5],
        )
        assert report['code'] == code
    header = _shipped_language('pt')['@language']
    assert (header['locale'], header['plurals']) == ('pt-BR', ['one', 'many', 'other'])
    # Portuguese translates nearly every message, the rest are names and symbols.
    assert len(_languages.check(_shipped_language('pt'), 'pt')['untranslated']) < 100


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
        for item in _languages.check({'@language': {'code': 'PT'}}, None, english)['malformed']
    ]
    assert any(problem.startswith('expected a code of lowercase') for problem in header)
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
