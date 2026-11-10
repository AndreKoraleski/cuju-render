# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of video jobs, the clean feed and picture sizes."""

import re

import pytest

import cuju
import cuju.errors
import cuju.state
from cuju.render._http import server as _server


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
