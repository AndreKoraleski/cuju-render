# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks of team presentation packages and their author tools."""

import json
import struct
import threading
import urllib.request

import numpy as np
import pytest

import cuju
import cuju.errors
import cuju.state
from cuju.render._http import server as _server
from cuju.render._registry import teams as _teams
from cuju.render._store import home as _home
from support.common import _get, _package_team


@pytest.mark.parametrize(
    'spec, message',
    [
        ({'id': 'a', 'type': 'oscillate', 'channel': 'w'}, 'channel'),
        ({'id': 'a', 'type': 'lookAt', 'node': 'b', 'target': 'moon'}, 'follow the ball'),
        ({'id': 'a', 'type': 'curve', 'channel': 'y'}, 'keys'),
        ({'id': 'a', 'type': 'oscillate', 'amp': {'input': 'mood'}}, 'input'),
        ({'id': 'a', 'type': 'spin', 'rate': 1}, 'turn a node, an attachment or a clip'),
        ({'id': 'bad id', 'type': 'bank'}, 'id of a behaviour'),
        ({'id': 'a', 'type': 'warp'}, 'type among'),
    ],
)
def test_presentation_behaviours_are_checked(spec, message):
    from cuju.render._packages import presentation as _presentation

    with pytest.raises(cuju.errors.ArgumentError, match=message):
        _presentation.behaviour(spec)


def test_presentation_contract_versions():
    from cuju.render._packages import presentation as _presentation

    assert _presentation.supported('1.0') and _presentation.supported('1.1')
    assert not _presentation.supported('1.2')
    assert not _presentation.supported('2.0') and not _presentation.supported(1)
    with pytest.raises(cuju.errors.ArgumentError, match='version of the manifest'):
        _presentation.check({'presentation': 1}, {})


def test_presentation_developer_mode_reads_a_trusted_folder(render_home, tmp_path):
    """Developer mode is off until the home's developer.json names a folder, then reads it live."""
    from cuju.render._packages import presentation as _presentation
    from support.package import package_files

    team = _package_team()
    assert _presentation.served(team['id'])['developer'] is False
    folder = tmp_path / 'work' / 'cuju-team'
    for path, data in package_files().items():
        if path.startswith('cuju-team/presentation'):
            target = tmp_path / 'work' / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    settings = render_home / _presentation.DEVELOPER_FILE
    settings.write_text(json.dumps({'presentation': {team['id']: 'relative/folder'}}))
    assert _presentation.served(team['id'])['developer'] is False
    settings.write_text(json.dumps({'presentation': {team['id']: str(folder)}}))
    served = _presentation.served(team['id'])
    assert served['developer'] is True and served['manifest']['name'] == 'Test package'
    manifest = folder / 'presentation' / 'presentation.json'
    document = json.loads(manifest.read_text())
    document['name'] = 'Edited'
    manifest.write_text(json.dumps(document))
    assert _presentation.served(team['id'])['manifest']['name'] == 'Edited'
    assert _presentation.file_path(team['id'], 'worker.js') == folder / 'presentation/worker.js'
    # An imported archive never turns developer mode on, only the home's own file does.
    other = _package_team('Other')
    assert _presentation.served(other['id'])['developer'] is False


# Presentation pack tools.

_HOOK = 'vec3 cujuEmissive(vec3 emissive, vec2 uv) {\n    return emissive;\n}\n'


def _hook(body):
    return f'vec3 cujuEmissive(vec3 emissive, vec2 uv) {{\n{body}\n    return emissive;\n}}\n'


def test_pack_glsl_passes_shaders_of_both_modes():
    """Shaders of the allowed forms pass, comments aside, with fetches counted through loops."""
    from cuju.render._packages import glsl as _glsl

    chunks = (
        '// A comment may say while, do and uniform, and #version too.\n'
        '#include <cuju_noise>\n'
        '#define GAIN 0.5\n'
        'const int N = 4;\n'
        'const int M = 3, K = 2;\n'
        'vec3 sample4(vec2 uv) {\n'
        '    return texture(uMap, uv).rgb;\n'
        '}\n'
        'vec4 cujuColor(vec4 color, vec2 uv) {\n'
        '    vec3 sum = vec3(0.0);\n'
        '    for (int i = 0; i < N; i++) {\n'
        '        /* nested, a block comment */\n'
        '        for (int j = M; j >= 0; j -= 1) sum += sample4(uv) * GAIN;\n'
        '    }\n'
        '    for (int k = 0; k < 0x0; ++k) { sum += texture(uMap, uv).rgb; }\n'
        '    return color + vec4(sum, 0.0) * uPulse;\n'
        '}\n'
    )
    assert _glsl.check(chunks) == []
    material = (
        'float glow(vec2 uv) { return texture(uMap, uv).r; }\n'
        '#pragma cuju vertex\n'
        'void main() {\n'
        '    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);\n'
        '}\n'
        '#pragma cuju fragment\n'
        'void main() {\n'
        '    float x = 0.0;\n'
        '    for (int i = 8; i > 0; i--) { x += glow(vec2(float(i))); }\n'
        '    gl_FragColor = vec4(uTeamColor * x, 1.0);\n'
        '}\n'
    )
    assert _glsl.check(material, 'material') == []
    manifest = {
        'materials': {
            'a': {'shader': 'shaders/a.glsl'},
            'b': {'shader': 'shaders/a.glsl', 'mode': 'chunks'},
            'c': {'shader': 'shaders/a.glsl', 'mode': 'material'},
        },
        'effects': {'p': {'type': 'particles', 'shader': 'shaders/a.glsl'}},
        'post': {'layer': {'pass': 'custom', 'shader': 'shaders/b.glsl'}},
    }
    assert _glsl.programs(manifest) == 3
    assert _glsl.programs({}) == 0 and _glsl.programs(None) == 0


@pytest.mark.parametrize(
    'text, mode, message',
    [
        ('#version 300 es\n' + _HOOK, 'chunks', 'line 1 sets the version'),
        ('#extension GL_EXT_x : enable\n' + _HOOK, 'chunks', 'enables an extension'),
        ('#define uTime 1.0\n' + _HOOK, 'chunks', 'defines uTime, a name the renderer owns'),
        ('#define cujuGlow 1.0\n' + _HOOK, 'chunks', 'defines cujuGlow, a name the renderer'),
        ('#define T texture\n' + _HOOK, 'chunks', 'hides texture in a macro'),
        ('uniform float level;\n' + _HOOK, 'chunks', 'line 1 declares a uniform'),
        (_hook('    while (emissive.x < 1.0) { emissive.x += 0.1; }'), 'chunks', 'while loop'),
        (_hook('    do { emissive.x += 0.1; } while (emissive.x < 1.0);'), 'chunks', 'do loop'),
        (_hook('    for (float x = 0.0; x < 3.0; x++) {}'), 'chunks', 'outside the form'),
        (_hook('    for (int i = 0; i < 4; i *= 2) {}'), 'chunks', 'outside the form'),
        (
            'int n = 3;\n' + _hook('    for (int i = 0; i < n; i++) {}'),
            'chunks',
            'bounds a loop by n, which is no integer literal or const int',
        ),
        (_hook('    for (int i = 0; i < 1000; i++) {}'), 'chunks', 'runs a loop 1000 times'),
        (_hook('    for (int i = 0; i < 4; i--) {}'), 'chunks', 'loop that never ends'),
        (_hook('    for (int i = 0; i < 4; i++) { i += 1; }'), 'chunks', 'changes the counter i'),
        (
            _hook('    for (int i = 0; i < 4; i++) if (i > 1) emissive.x += 1.0;'),
            'chunks',
            'branches without braces',
        ),
        (
            _hook('    for (int i = 0; i < 17; i++) { emissive += texture2D(m, uv).rgb; }'),
            'chunks',
            'the hooks fetch textures 17 times, at most 16',
        ),
        (
            _hook(
                '    for (int i = 0; i < 4; i++)\n'
                '        for (int j = 0; j < 5; j++) { emissive += texture(m, uv).rgb; }'
            ),
            'chunks',
            'fetch textures 20 times',
        ),
        (
            'vec3 two(vec2 uv) { return texture(m, uv).rgb + texelFetch(m, ivec2(0), 0).rgb; }\n'
            + _hook('    for (int i = 0; i < 9; i++) { emissive += two(uv); }'),
            'chunks',
            'fetch textures 18 times',
        ),
        ('#include <noise>\n' + _HOOK, 'chunks', 'only <cuju_noise> is available'),
        ('vec3 helper(vec3 e) { return e; }\n', 'chunks', 'defines none of the hooks'),
        ('vec4 cujuEmissive(vec3 e, vec2 uv) { return vec4(e, 1.0); }\n', 'chunks', 'returns vec3'),
        ('#pragma cuju vertex\n' + _HOOK, 'chunks', 'only a file of mode material has'),
        ('void main() {}\n', 'material', 'expected one line #pragma cuju vertex, found 0'),
        (
            '#pragma cuju vertex\nvoid main() {}\n#pragma cuju fragment\nfloat f() {}\n',
            'material',
            'the fragment section defines no void main()',
        ),
        (
            '#pragma cuju vertex\nvoid main() {}\n#pragma cuju fragment\nvoid main() {\n'
            '    for (int i = 0; i < 20; i++) { gl_FragColor += texture(m, vec2(0.0)); }\n}\n',
            'material',
            'the fragment section fetches textures 20 times',
        ),
        (_HOOK, 'points', 'expected the mode chunks or material'),
    ],
)
def test_pack_glsl_refuses_each_case(text, mode, message):
    from cuju.render._packages import glsl as _glsl

    problems = _glsl.check(text, mode)
    assert any(message in problem for problem in problems), problems


def _zip_folder(folder, path):
    import zipfile

    with zipfile.ZipFile(path, 'w') as archive:
        for item in sorted(folder.rglob('*')):
            if item.is_file():
                archive.write(item, item.relative_to(folder).as_posix())
    return path


def test_pack_new_writes_a_template_that_checks_and_imports(render_home, tmp_path):
    """The template passes the check as a folder, as its inner folders and as a zip, and imports."""
    from cuju.render._packages import pack as _pack
    from cuju.render._packages import presentation as _presentation

    folder = tmp_path / 'team'
    written = _pack.new(folder, 'Glow team')
    assert sorted(p.relative_to(folder).as_posix() for p in written) == [
        'cuju-team/presentation/audio/tick.wav',
        'cuju-team/presentation/models/ring.glb',
        'cuju-team/presentation/presentation.json',
        'cuju-team/presentation/shaders/glow.glsl',
        'cuju-team/presentation/worker.js',
        'cuju-team/team.json',
        'main.py',
    ]
    for path in (folder, folder / 'cuju-team', folder / 'cuju-team' / 'presentation'):
        result = _pack.check(path)
        assert result['ok'] and result['errors'] == [], result['errors']
    result = _pack.check(_zip_folder(folder, tmp_path / 'team.zip'))
    assert result['ok'] and result['errors'] == [], result['errors']
    assert result['manifest']['name'] == 'Glow team'
    assert result['manifest']['contract'] == '1.1'
    assert result['features']['required'] == ['drivers.grf']
    # Eleven players wear the ring, one draw of 48 triangles each, and one shader program.
    assert result['budgets']['high']['drawCalls'] == [11, 150]
    assert result['budgets']['high']['triangles'] == [11 * 48, 400_000]
    assert result['budgets']['low']['shaders'] == [1, 8]
    assert {f['path']: f['kind'] for f in result['files']}['models/ring.glb'] == 'model'
    (tick,) = result['loudness']
    assert tick['file'] == 'audio/tick.wav' and tick['maxShortTerm'] < _pack.SHORT_TERM_CEILING
    assert tick['truePeak'] < _pack.TRUE_PEAK_CEILING
    # The template imports whole, with its name, and its agent answers every player.
    entry = _teams.add('', 'team.zip', (tmp_path / 'team.zip').read_bytes())
    root = _home.folder('teams') / entry['id']
    assert _presentation.left_out(root) == set()
    assert entry['name'] == 'Glow team' and entry['model'] is None
    assert _teams.load_agent(entry['id'])({'players_raw': [{}, {}]}) == [0, 0]
    with pytest.raises(cuju.errors.ArgumentError, match='empty folder'):
        _pack.new(folder)


def test_pack_check_reads_the_test_package_without_errors(tmp_path):
    from cuju.render._packages import pack as _pack
    from support.package import package_zip

    path = tmp_path / 'test-package.zip'
    path.write_bytes(package_zip())
    result = _pack.check(path)
    assert result['ok'] and result['errors'] == [], result['errors']
    assert result['manifest']['name'] == 'Test package'
    assert result['features']['lacking'] == ['audio.spatial']
    # The kick carries its contact marker, and the keeper's model and the five halos count.
    assert not any('clip Kick' in item for item in result['info'])
    assert result['budgets']['high']['drawCalls'] == [7, 150]
    assert [item['file'] for item in result['loudness']] == ['audio/strike.wav']


def test_pack_check_reports_a_broken_package(tmp_path):
    """A bad shader loop, a missing node, an unknown clip and bad files are each an error."""
    from cuju.render._packages import pack as _pack
    from support.package import package_files, package_zip

    folder = 'cuju-team/presentation/'
    manifest = json.loads(package_files()[f'{folder}presentation.json'])
    manifest['materials']['bad'] = {'match': 'Body', 'shader': 'shaders/bad.glsl'}
    manifest['rig']['sockets']['ghost'] = {'node': 'mixamorig:Tail'}
    manifest['clips']['shot'] = 'Volley'
    manifest['clips']['header'] = 'Idle'
    loop = 'vec3 cujuEmissive(vec3 e, vec2 uv) {\n    while (e.x < 1.0) { e.x += 0.1; }\n'
    extra = {
        f'{folder}presentation.json': json.dumps(manifest).encode(),
        f'{folder}shaders/bad.glsl': (loop + '    return e;\n}\n').encode(),
        f'{folder}big.js': b'/' * (3 * 1024 * 1024),
        f'{folder}sound.wav': b'OggS' + bytes(60),
        f'{folder}Upper.js': b'export {}',
    }
    path = tmp_path / 'broken.zip'
    path.write_bytes(package_zip('Broken', extra))
    result = _pack.check(path)
    assert not result['ok']
    errors = ' | '.join(result['errors'])
    for part in (
        'shaders/bad.glsl of mode chunks line 2 holds a while loop',
        'socket ghost names the node mixamorig:Tail',
        'the role shot names the clip Volley',
        'big.js fails its check',
        'sound.wav fails its check',
        'Upper.js fails its check',
    ):
        assert part in errors, errors
    # A clip without a contact marker plays its contact at 40 percent, which the check reports.
    assert any('clip Idle of header has no contact marker' in item for item in result['info'])


def test_pack_command_line(tmp_path, capsys):
    from cuju.render.__main__ import main
    from cuju.render._packages import pack as _pack

    folder = tmp_path / 'team'
    assert main(['pack', 'new', str(folder), '--name', 'Cli team']) == 0
    assert 'wrote' in capsys.readouterr().out
    assert main(['pack', 'check', str(folder), '--json']) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed['ok'] is True and printed['manifest']['name'] == 'Cli team'
    assert set(printed) == {
        'ok',
        'errors',
        'warnings',
        'info',
        'manifest',
        'features',
        'budgets',
        'files',
        'loudness',
    }
    shader = folder / 'cuju-team/presentation/shaders/glow.glsl'
    shader.write_text('uniform float level;\n' + shader.read_text())
    assert main(['pack', 'check', str(folder), '--json']) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed['ok'] is False
    assert any('declares a uniform' in error for error in printed['errors'])
    assert main(['pack', 'check', str(folder)]) == 1
    report = capsys.readouterr().out
    assert 'errors' in report and 'declares a uniform' in report and report.endswith('1 error\n')
    # A new team goes only into an empty folder.
    assert main(['pack', 'new', str(folder)]) == 1
    assert 'expected an empty folder' in capsys.readouterr().err
    assert main(['pack', 'check', str(tmp_path / 'missing')]) == 1
    assert _pack.new(tmp_path / 'other')[0].name == 'main.py'


def _sine_wav(seconds, level, rate=48000, channels=2, frequency=1000.0, floats=False):
    """Returns a sine of a peak level in dBFS in every channel as a WAV file."""
    t = np.arange(int(seconds * rate)) / rate
    wave = 10 ** (level / 20) * np.sin(2 * np.pi * frequency * t)
    if floats:
        form, width, samples = 3, 4, np.repeat(wave, channels).astype('<f4').tobytes()
    else:
        width = 2
        form, samples = 1, np.repeat(np.round(wave * 32767), channels).astype('<i2').tobytes()
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',
        36 + len(samples),
        b'WAVE',
        b'fmt ',
        16,
        form,
        channels,
        rate,
        rate * width * channels,
        width * channels,
        8 * width,
        b'data',
        len(samples),
    )
    return header + samples


def test_pack_loudness_of_a_sine_follows_bs1770():
    """A stereo 1 kHz sine at -23 dBFS reads -23 LUFS and -23 dBTP, with numpy and without."""
    from cuju.render._packages import pack as _pack

    measured = _pack.loudness(_sine_wav(3, -23))
    for key in ('integrated', 'maxMomentary', 'maxShortTerm'):
        assert abs(measured[key] + 23) <= 0.2, measured
    assert abs(measured['truePeak'] + 23) <= 0.2, measured
    assert measured['channels'] == 2 and measured['rate'] == 48000
    pure = _pack.loudness(_sine_wav(1, -23), use_numpy=False)
    assert abs(pure['integrated'] + 23) <= 0.2 and abs(pure['truePeak'] + 23) <= 0.2, pure
    assert abs(pure['maxMomentary'] - measured['maxMomentary']) <= 0.01
    floats = _pack.loudness(_sine_wav(1, -23, rate=44100, floats=True))
    assert abs(floats['integrated'] + 23) <= 0.2 and abs(floats['truePeak'] + 23) <= 0.2
    # The short-term loudness of one second counts the two seconds before it as silence.
    assert abs(pure['maxShortTerm'] - (-23 + 10 * np.log10(1 / 3))) <= 0.2
    silent = _pack.loudness(_sine_wav(0.5, -200))
    assert silent['integrated'] is None and silent['truePeak'] is None


# Presentation contract 1.1.


def test_presentation_contract_1_1_sections_are_checked(render_home):
    """Effects, lights, passes, slots, shaders, reach and layers of 1.1 arrive checked."""
    from cuju.render._packages import presentation as _presentation

    team = _package_team()
    served = _presentation.served(team['id'])
    assert served['warnings'] == [], served['warnings']
    m = served['manifest']
    assert set(m['effects']) == {'spark', 'streak', 'scorch', 'flare', 'ring', 'pulse', 'grade'}
    assert m['effects']['spark']['life'] == [0.3, 0.8]
    assert m['effects']['grade']['scope'] == 'fullscreen' and m['effects']['grade']['duration'] <= 3
    assert m['lights']['core']['kind'] == 'local' and m['post']['layer']['pass'] == 'outline'
    assert m['overlays'] == {'badge': {}}
    assert m['materials']['eyes']['mode'] == 'chunks'
    assert m['materials']['eyes']['uniforms']['blinkSeed'] == {'seed': 'entity'}
    assert m['rig']['ik']['kick']['chain'][-1] == 'mixamorig:RightFoot'
    assert m['rig']['layers'][0]['role'] == 'celebration'
    assert m['audio']['processors']['hum']['processor'] == 'test-hum'
    assert m['audio']['music']['anthem']['bpm'] == 120.0
    goal = next(r for r in m['reflexes'] if r['on'] == 'goal')
    environment = next(a['environment'] for a in goal['do'] if 'environment' in a)
    assert environment['tifo'] == 'textures/tifo.png' and environment['duration'] == 4
    assert next(a['time'] for a in goal['do'] if 'time' in a) == {'freeze': 0.2}
    for feature in (
        'shader.custom',
        'post.fullscreen',
        'bend.ball',
        'fans.tifo',
        'geometry.worker',
    ):
        assert feature in served['features']


@pytest.mark.parametrize(
    'changes, message',
    [
        ({'effects': {'x': {'type': 'particles', 'count': 99999}}}, 'effect x left out'),
        ({'effects': {'x': {'type': 'decal', 'opacity': 0.9}}}, 'effect x left out'),
        ({'effects': {'x': {'type': 'post', 'pass': 'warp'}}}, 'effect x left out'),
        ({'effects': {'x': {'type': 'post', 'pass': 'custom'}}}, 'effect x left out'),
        ({'effects': {'x': {'type': 'hologram'}}}, 'waits for a later renderer'),
        ({'lights': {'x': {'socket': 'nowhere'}}}, 'light x left out'),
        ({'lights': {'x': {'kind': 'sun'}}}, 'light x left out'),
        ({'post': {'layer': {'pass': 'warp'}}}, 'post left out'),
        ({'overlays': {'scorebug': {}}}, 'overlays left out'),
        ({'rig': {'ik': {'x': {'chain': ['a']}}}}, 'ik chain x left out'),
        ({'rig': {'layers': [{'mask': ['a']}]}}, 'layer 0 left out'),
        ({'reflexes': [{'on': 'goal', 'do': [{'time': {'freeze': 2}}]}]}, 'reflex 0 left out'),
        (
            {'reflexes': [{'on': 'goal', 'do': [{'environment': {'rain': {}}}]}]},
            'reflex 0 left out',
        ),
        ({'reflexes': [{'on': 'goal', 'do': [{'music': 'none'}]}]}, 'reflex 0 left out'),
        (
            {'materials': {'x': {'match': '*', 'shader': 'shaders/bad.glsl'}}},
            'material x left out, shaders/bad.glsl',
        ),
        ({'materials': {'x': {'match': '*', 'shader': 'shaders/ok.glsl', 'mode': 'x'}}}, 'x'),
    ],
)
def test_presentation_contract_1_1_refuses_bad_parts(tmp_path, changes, message):
    from cuju.render._packages import presentation as _presentation

    (tmp_path / 'bad.glsl').write_text('vec4 cujuColor(vec4 c, vec2 uv) { while (true) {} }')
    (tmp_path / 'ok.glsl').write_text('vec4 cujuColor(vec4 c, vec2 uv) { return c; }')
    assets = {
        'shaders/bad.glsl': str(tmp_path / 'bad.glsl'),
        'shaders/ok.glsl': str(tmp_path / 'ok.glsl'),
    }
    document = {'contract': '1.1', 'rig': {'sockets': {}}, **changes}
    if 'rig' in changes:
        document['rig'] = {'sockets': {}, **changes['rig']}
    warnings: list[str] = []
    _presentation.check(document, assets, warnings)
    assert any(message in w for w in warnings), warnings


def test_presentation_sides_through_the_server_and_the_command_line(render_home, capsys):
    """A side draws a chosen team's package, set by the route, the command line or a preview."""
    from cuju.render.__main__ import main
    from cuju.render._packages import pack as _pack
    from cuju.render._packages import presentation as _presentation

    team = _package_team()
    assert _presentation.sides() == {'left': None, 'right': None}
    with pytest.raises(cuju.errors.ArgumentError):
        _presentation.assign({'left': 't-19990101-000000-dead'})
    with pytest.raises(cuju.errors.ArgumentError):
        _presentation.assign({'middle': team['id']})
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        request = urllib.request.Request(
            f'{address}/api/presentation/sides',
            data=json.dumps({'right': team['id']}).encode(),
            headers={'Content-Type': 'application/json', 'Origin': address},
            method='POST',
        )
        with urllib.request.urlopen(request, timeout=10) as reply:
            assert json.load(reply) == {'left': None, 'right': team['id']}
        status, body = _get(address, '/api/presentation/sides')
        assert status == 200 and json.loads(body)['right'] == team['id']
        foreign = urllib.request.Request(
            f'{address}/api/presentation/sides',
            data=b'{"left": null}',
            headers={'Origin': 'http://example.com'},
            method='POST',
        )
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(foreign, timeout=10)
    finally:
        server.shutdown()
        server.server_close()
    assert main(['pack', 'sides', '--right', 'none', '--left', team['id']]) == 0
    assert json.loads(capsys.readouterr().out) == {'left': team['id'], 'right': None}
    from support.package import package_zip

    archive = render_home / 'preview.zip'
    archive.write_bytes(package_zip('Previewed'))
    place = _pack.preview(archive, 'right')
    assert place.startswith('#match=') and place.endswith('&preview=1')
    chosen = _presentation.sides()['right']
    assert chosen and _presentation.served(chosen)['manifest']['name'] == 'Test package'
