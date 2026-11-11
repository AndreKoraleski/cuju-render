# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of video jobs, the clean feed and picture sizes."""

import json
import re
import threading
import urllib.request

import pytest

import cuju
import cuju.errors
import cuju.state
from cuju.render._http import server as _server
from support.common import _FeedRequests, _FeedTournaments, _get


def test_sizes_match_the_page():
    from cuju.render._export import sizes as _sizes

    source = (_server._WEB / 'js' / 'export/sizes.js').read_text(encoding='utf-8')
    presets = re.findall(r"\{ id: '([^']+)', width: (\d+), height: (\d+),", source)
    assert {name: (int(w), int(h)) for name, w, h in presets} == _sizes.PRESETS
    assert list(_sizes.PRESETS) == [name for name, _, _ in presets]
    start = source.index('SIZE_ALIASES')
    block = source[start : source.index('});', start)]
    aliases = dict(re.findall(r"'?(\w+)'?: '([^']+)'", block))
    assert aliases == _sizes.ALIASES
    for name in ('MIN_SIDE', 'MAX_SIDE', 'LAYOUT_SHORT', 'MAX_SAFE_PERCENT'):
        assert re.search(rf'export const {name} = (\d+);', source)[1] == str(getattr(_sizes, name))
    assert f"DEFAULT_SIZE = '{_sizes.DEFAULT_SIZE}'" in source
    assert _sizes.parse_size('vertical') == (1080, 1920)
    assert _sizes.parse_size(' 2160P ') == (3840, 2160)
    assert _sizes.parse_size('1000 x 1000') == (1000, 1000)
    assert _sizes.size_name(1080, 1080) == 'square'
    assert _sizes.size_name(1000, 1000) == '1000x1000'
    for text in ('', 'big', '1280', '89x720', '3841x100', '3840x3840', '12.5x100'):
        with pytest.raises(cuju.errors.ArgumentError):
            _sizes.parse_size(text)
    with pytest.raises(cuju.errors.ArgumentError, match='even'):
        _sizes.parse_size('1281x720', even=True)
    # The same layouts as the page's layoutFor, which tests/web/feed.mjs checks.
    assert _sizes.layout(1920, 1080) == (1280, 720, 1.5)
    assert _sizes.layout(1080, 1920) == (720, 1280, 1.5)
    assert _sizes.layout(1080, 1080) == (720, 720, 1.5)
    assert _sizes.layout(854, 480) == (854, 480, 1.0)
    assert _sizes.layout(1920, 1080, 1.5) == (853, 480, 2.25)
    assert _sizes.parse_safe('7.5%') == 7.5 and _sizes.parse_safe('Social') == 'social'
    for text in ('wide', '-1', '30'):
        with pytest.raises(cuju.errors.ArgumentError):
            _sizes.parse_safe(text)
    with pytest.raises(cuju.errors.ArgumentError):
        _sizes.parse_graphics('2.5')


def test_feed_address_matches_the_page():
    from cuju.render._export import feed as _feed

    # The same addresses as feedQuery of the page writes, which tests/web/feed.mjs checks.
    assert _feed.query() == 'source=auto&size=1080p'
    vertical = _feed.query(
        source='live:Evaluation', width=1080, height=1920, bg='transparent', audio=True, fps=30
    )
    assert vertical == 'source=live:Evaluation&size=vertical&bg=transparent&audio=1&fps=30'
    assert (
        _feed.address(
            'http://127.0.0.1:8780/', source='queue', size='4k', scale=0.75, safe='none', loop=True
        )
        == 'http://127.0.0.1:8780/feed?source=queue&size=4k&scale=0.75&safe=none&loop=1'
    )
    assert _feed.query(source='tournament:t-1', width=1000, height=1000, safe=5, time='dusk') == (
        'source=tournament:t-1&size=1000x1000&safe=5&time=19'
    )
    assert _feed.parse_source('m-20261106-105640-3a3f') == ('recording', 'm-20261106-105640-3a3f')
    assert _feed.parse_source('Tournament:t-1') == ('tournament', 't-1')
    assert _feed.parse_background('#ABC') == '#aabbcc'
    for wrong in (
        {'source': '../up'},
        {'source': 'queue:x'},
        {'size': 'huge'},
        {'scale': 7},
        {'bg': 'chartreuse'},
        {'fps': 61},
        {'camera': 'free'},
        {'volume': 2},
        {'audio': 'maybe'},
        {'colour': 'red'},
    ):
        with pytest.raises(cuju.errors.ArgumentError):
            _feed.query(**wrong)


def test_feed_lists_live_sources_by_title_and_errors_without_class_names(render_home):
    """A live source goes by its title, and the server's errors read as cuju words them."""
    from cuju.render._export import feed as _feed

    live = [
        {'id': 'live-20261110-101500-aaaa', 'title': 'Evaluation'},
        {'id': 'live-20261110-111500-bbbb', 'title': 'evaluation'},
        {'id': 'live-20261110-121500-cccc', 'title': ''},
    ]
    rows = _feed.targets('http://127.0.0.1:8780/', live, [])
    named = [row['source'] for row in rows if row['source'].startswith('live:')]
    assert named == ['live:live-20261110-121500-cccc', 'live:evaluation']
    cup = {'id': 'cup-1', 'name': 'Cup', 'matches': []}
    handler = _server.make_handler(_FeedRequests([]), tournaments=_FeedTournaments(cup))
    server = _server.http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(urllib.error.HTTPError) as refused:
            _get(f'http://127.0.0.1:{server.server_address[1]}', '/api/feed/resolve?source=../up')
        message = json.loads(refused.value.read())['error']
        assert message.startswith('expected a source of') and 'Error' not in message
    finally:
        server.shutdown()
        server.server_close()


def test_names_of_the_feed_travel_with_their_messages():
    from cuju.render._export import feed as _feed
    from cuju.render._text import messages as _messages

    def resolve(source, live=(), recordings=(), requests=(), tournaments=()):
        return _feed.resolve(
            source,
            live=lambda: list(live),
            recordings=lambda: list(recordings),
            recording=lambda identifier: next(
                (entry for entry in recordings if entry['id'] == identifier), None
            ),
            requests=lambda: list(requests),
            tournaments=lambda: list(tournaments),
            tournament=lambda identifier: None,
        )

    waiting = resolve('queue')
    assert waiting['message'] == 'No requested match has finished yet'
    assert waiting['message_id'] == 'server.feed.no_request'
    assert resolve('live:Evaluation')['message_values'] == {'name': 'Evaluation'}
    summary = {
        'id': 'm-1',
        'title': 'Demo, the built-in AI against itself',
        'title_id': 'server.names.demo',
        'title_values': {},
    }
    found = resolve('latest', recordings=[summary])
    assert found['title'] == summary['title'] and found['title_id'] == 'server.names.demo'
    rows = _feed.targets('http://127.0.0.1:8000', [summary | {'id': 'live-1'}], [])
    assert rows[0]['label'] == 'a live source while one streams, else the newest recording'
    assert all(row['label_id'].startswith('server.feed.follow.') for row in rows)
    assert rows[-1]['label_values']['name']['id'] == 'server.names.demo'
    with pytest.raises(_messages.MessageError) as raised:
        _feed.parse_source('nowhere at all')
    assert raised.value.message_id == 'server.feed.source'
