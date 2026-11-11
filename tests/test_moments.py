# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of the moments of a match, their search and their captions."""

import json
import os
import subprocess
import threading
import urllib.request

import pytest
import torch

import cuju
import cuju.errors
import cuju.state
from cuju.render._format import recording as _recording
from cuju.render._http import server as _server
from cuju.render._store import library as _library
from support.common import _REPOSITORY, _SAMPLE_FOLDER, _get


def _numbers(value):
    """Returns JSON with every number as a float, as JavaScript writes whole floats as integers."""
    return json.loads(json.dumps(value), parse_int=float, parse_float=float)


def _random_recordings(render_home):
    """Records episodes of random actions, which bring shots, saves, blocks, slides and cards."""
    generator = torch.Generator().manual_seed(5)
    paths = []
    for scenario, steps in (('5_vs_5_l1_r0', 500), ('academy_counterattack_hard_l1_r0', 300)):
        batch = cuju.BatchEnvironment(scenario, environment_count=1, device='cpu')
        try:
            recorder = cuju.render.Recorder(batch)
            batch.reset()
            agents = int(batch.left_agents[0] + batch.right_agents[0])
            for _ in range(steps):
                actions = torch.randint(0, 19, (1, agents), generator=generator, dtype=torch.int32)
                batch.step(actions)
            recorder.save()
            recorder.flush()
            paths += recorder.saved
        finally:
            batch.close()
    return paths


def test_moments_and_captions_agree_with_the_page(render_home):
    import shutil

    from cuju.render._moments import captions as _captions
    from cuju.render._moments import events as _events

    node = shutil.which('node')
    if node is None:
        pytest.skip('the page side runs on Node')
    files = [os.path.join(_SAMPLE_FOLDER, name) for name in ('sample-11v11.cjr', 'sample-5v5.cjr')]
    files += [str(path) for path in _random_recordings(render_home)]
    script = os.path.join(_REPOSITORY, 'ci', 'check_moments.mjs')
    page = json.loads(
        subprocess.run([node, script, *files], capture_output=True, check=True).stdout
    )
    cues = json.loads(
        subprocess.run([node, script, '--cues', *files], capture_output=True, check=True).stdout
    )
    kinds = set()
    for file, want, want_cues in zip(files, page, cues, strict=True):
        header = _recording.read_header(file)
        found = _events.moments(header, _recording.frames(file))
        assert _numbers(found) == _numbers(want), file
        kinds |= {moment['kind'] for moment in found}
        made = _captions.cues(found, _captions.context(header, []))
        assert _numbers(made) == _numbers(want_cues), file
    assert {'goal', 'shot', 'pass', 'tackle', 'restart', 'possession', 'foul'} <= kinds


def test_search_query_language(render_home):
    from cuju.render._moments import search as _search

    _library.add_samples()

    def total(query):
        return _search.search(query)['total']

    assert total('goal') == 4
    assert total('goals') == total('kind:goal') == 4
    assert total('goal team:Harbour') == 1
    assert total('goal team:left') == 2
    assert total('goal team:"harbour rovers"') == 1
    assert total('player:10 goal') == 1
    assert total('penalty') == 1
    assert total('kind:penalty,save') == 2
    assert total('set-piece') == 9
    assert total('goal score:level') == 2
    assert total('goal score:1-1') == 2
    # Both equalizers come from behind, and neither goal of the samples puts a leader further on.
    assert total('goal score:trailing') == 2
    assert total('goal score:leading') == 0
    assert total('free-kick scenario:5 vs 5') == 1
    assert total('shot after:45') == 1
    assert total('pass outcome:intercepted') == 16
    assert total('goal source:unknown') == 4
    assert total('goal source:tournament') == 0
    assert total('goal match:sample-5v5') == 2
    # A word matches the recording, its title, scenario and teams, so both goals of its match.
    assert total('goal Harbour') == 2
    assert total('goal -team:left') == 2
    assert total('goal date:2000-01-01') == 0
    assert total('goal since:2000-01-01') == 4
    everything = total('')
    assert everything == total('-zzz') and everything > 100
    assert total('-pass -possession') == everything - total('pass') - total('possession')
    found = _search.search('goal limit:1')
    assert len(found['results']) == 1 and found['total'] == 4
    first = found['results'][0]
    assert first['seek'] == max(0.0, round(first['t'] - 4, 1))
    assert first['url'] == f'#match={first["match"]}&t={first["seek"]:g}'
    assert first['text'].startswith('Goal, number ')
    assert first['minute'] == f'{first["clock"] // 60000}:{first["clock"] // 1000 % 60:02d}'
    for bad in ('foo:1', 'after:x', 'kind:zzz', 'score:huge', 'limit:0', 'source:moon', 'date:x'):
        with pytest.raises(cuju.errors.ArgumentError):
            _search.search(bad)


def test_captions_from_the_command_line_and_the_server(render_home, tmp_path, capsys):
    from cuju.render.__main__ import main
    from cuju.render._moments import captions as _captions
    from cuju.render._moments import search as _search

    _library.add_samples()
    out = tmp_path / 'five.vtt'
    assert main(['captions', 'sample-5v5', '-o', str(out)]) == 0
    text = out.read_text()
    assert text.startswith('WEBVTT\n\n1\n00:00:09.148 --> 00:00:10.648\nShot, number 3 of Lake')
    assert 'Full time, a draw, 1 to 1' in text
    cues = cuju.render.captions(
        os.path.join(_SAMPLE_FOLDER, 'sample-5v5.cjr'), tmp_path / 'file.vtt'
    )
    assert cues[-1]['text'].startswith('Full time')
    # The cues keep their times to the millisecond, as the file writes them.
    assert all(cue['start'] == round(cue['start'], 3) for cue in cues)
    assert (cues[0]['start'], cues[0]['end']) == (9.148, 10.648)
    assert (tmp_path / 'file.vtt').read_text() == text
    capsys.readouterr()
    assert main(['search', 'goal', 'team:left', '--json']) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed['total'] == 2
    assert main(['search', 'goal']) == 0
    assert '4 of 4 moments in 2 recordings' in capsys.readouterr().out
    assert main(['search', 'nope:1']) == 1
    assert main(['captions', 'no-such-recording']) == 1
    assert cuju.render.search('goal team:right')['total'] == 2
    assert _captions.vtt_time(3725.0005) == '01:02:05.001'
    assert set(_captions.messages()) >= {'caption.goal', 'caption.card.red', 'describe.pass'}
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        status, body = _get(address, '/api/search?q=goal%20team%3Aright&limit=1')
        found = json.loads(body)
        assert status == 200 and found['total'] == 2 and len(found['results']) == 1
        status, body = _get(address, '/api/matches/sample-5v5/moments')
        listed = json.loads(body)
        assert [m['kind'] for m in listed['moments']].count('goal') == 2
        with urllib.request.urlopen(address + '/api/matches/sample-5v5/captions.vtt') as response:
            assert response.headers['Content-Type'].startswith('text/vtt')
            assert response.read().decode() == _search.captions_vtt('sample-5v5')
        for path in ('/api/search?q=foo%3A1', '/api/search?limit=x'):
            with pytest.raises(urllib.error.HTTPError) as refused:
                _get(address, path)
            assert refused.value.code == 400
        with pytest.raises(urllib.error.HTTPError) as missing:
            _get(address, '/api/matches/nothing/captions.vtt')
        assert missing.value.code == 404
        request = urllib.request.Request(address + '/api/search?q=goal', headers={'Host': 'x.com'})
        with pytest.raises(urllib.error.HTTPError) as foreign:
            urllib.request.urlopen(request, timeout=10)
        assert foreign.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_a_name_never_adds_or_styles_a_cue_of_the_captions_file():
    from cuju.render._moments import captions as _captions

    name = 'Reds\n\n00:00:00.000 --> 99:00:00.000\r\n<b>Fake</b> & co\u2028end'
    header = {
        'teams': [{'name': name}, {'name': 'Blues'}],
        'players': [{'team': 0, 'index': 0, 'goalkeeper': False}],
    }
    moments = [{'id': 'g', 'kind': 'goal', 'step': 10, 't': 1.0, 'team': 0, 'data': {}}]
    found = _captions.cues(moments, _captions.context(header, []))
    text = _captions.to_vtt(found)
    lines = text.split('\n')
    assert lines[:3] == ['WEBVTT', '', '1'] and lines[3].count('-->') == 1
    assert len(lines) == 6 and lines[5] == ''
    assert '<' not in lines[4] and '-->' not in lines[4] and '\r' not in text
    assert '&lt;b&gt;Fake&lt;/b&gt; &amp; co end' in lines[4]
    assert '00:00:00.000 --&gt; 99:00:00.000' in lines[4]
    # The cues themselves keep the name as the page shows it.
    assert name in found[0]['text']
