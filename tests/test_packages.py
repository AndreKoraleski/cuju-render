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
from support.common import _get, _package_team, _template_variant, _zip_folder


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
    # Developer mode imports its modules by their address, so every module goes out as JavaScript.
    assert _presentation.content_type(team['id'], 'worker.js') == 'text/javascript'
    # An imported archive never turns developer mode on, only the home's own file does.
    other = _package_team('Other')
    assert _presentation.served(other['id'])['developer'] is False
    assert _presentation.content_type(other['id'], 'worker.js') == 'text/plain; charset=utf-8'
    assert _presentation.content_type(other['id'], 'audio/hum.js') == 'text/javascript'
    assert _presentation.content_type(other['id'], 'shaders/blink.glsl') == 'text/plain'


@pytest.mark.parametrize(
    'text',
    [
        # The ways around the line by line rule of 0.2.0, each an import of the page's own module.
        '0;import{Governor as G,Limiter as L}from"/js/presentation/loudness.js";',
        '/**/import x from "y"',
        'a();import x from "y"',
        ';export{a}from"y"',
        'const u = import.meta.url',
        'import("x")',
        'let a = `${import("x")}`',
        'let a = `a${`b${ import("x") }`}`',
        '// a line\u2028import x from "y"',
        '// a line\rimport x from "y"',
        "if (a) /'/.test(b); import('y'); //'",
        'for await (const a of b) /"/; import("y"); "/',
        'a\n++/"/.lastIndex; import("x"); "/',
        'x = {}\n/a/; import("x")',
        'export * from "y"',
        'export * as n from "y"',
        'export { a as b } from "y"',
        'im\\u0070ort("x")',
        '"open',
        '/* open',
        '`open ${',
        'x = /open',
    ],
)
def test_presentation_modules_refuse_every_import(text):
    """The reader of modules finds an import however the text hides it, or refuses the text."""
    from cuju.render._packages import presentation as _presentation

    assert _presentation.module_problem(text), text
    with pytest.raises(cuju.errors.ArgumentError, match='without imports'):
        _presentation.check_file('worker.js', text.encode())


@pytest.mark.parametrize(
    'text',
    [
        'export function frame() {}',
        'export {}\nexport { a }',
        'const s = "import x from \'y\'"',
        '// import x from "y"\n/* import */ let a',
        r'let r = /import\/"/g; let b = a / 2 / c',
        'x.import(); y?.import',
        'let t = `import ${a} import`',
        'a = (b) / 2; c = d[0] / 3; e = f.return / 2',
        '#!/usr/bin/env node\nexport const a = 1',
        'class A { #import = 1; m() { return this.#import } }',
        'x = a ? .5 : 1; y = a?.b',
        'x = typeof /a/; if (a) { b() }\nc()',
        'this.tick-- / (0.05 * r); a = b++ / 2',
    ],
)
def test_presentation_modules_without_imports_pass(text):
    from cuju.render._packages import presentation as _presentation

    assert _presentation.module_problem(text) is None


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


def _loop(n, body, name='i'):
    return f'for (int {name} = 0; {name} < {n}; {name}++) {{ {body} }}'


@pytest.mark.parametrize(
    'text, mode, message',
    [
        (
            _hook(_loop(256, _loop(256, _loop(256, 'emissive.x += 0.0001;', 'k'), 'j'))),
            'chunks',
            'nested loops in the hooks that run their body 16777216 times, at most 1024',
        ),
        (
            'float h(float x) { '
            + _loop(256, 'x += 0.1;')
            + ' return x; }\n'
            + _hook(_loop(256, 'emissive.x += h(emissive.y);')),
            'chunks',
            'run their body 65536 times',
        ),
        (
            ''.join(
                f'float f{n}(float x) {{ return f{n + 1}(x) + f{n + 1}(x) + f{n + 1}(x); }}\n'
                for n in range(20)
            )
            + 'float f20(float x) { return x; }\n'
            + _hook('    emissive.x += f0(emissive.y);'),
            'chunks',
            'words of code in the hooks, at most 65536',
        ),
        (
            '#define A x+x+x+x+x+x+x+x\n#define B A A A A A A A A\n#define C B B B B B B B B\n'
            '#define D C C C C C C C C\n#define E D D D D D D D D\n#define F E E E E E E E E\n'
            + _hook('    float x = 1.0; emissive.x += F;'),
            'chunks',
            'once its macros expand, at most 262144',
        ),
        (
            '#pragma cuju vertex\nvoid main() { '
            + _loop(64, _loop(64, 'gl_Position += vec4(0.0);', 'j'))
            + ' }\n#pragma cuju fragment\nvoid main() { gl_FragColor = vec4(1.0); }\n',
            'material',
            'in the vertex section that run their body 4096 times',
        ),
    ],
)
def test_pack_glsl_bounds_the_work_of_a_shader(text, mode, message):
    """Nested loops, helper calls and macros count together, so no shader runs without end."""
    from cuju.render._packages import glsl as _glsl

    problems = _glsl.check(text, mode)
    assert any(message in problem for problem in problems), problems


def test_pack_glsl_counts_many_loops_quickly_and_deep_nesting_safely():
    """A large shader checks in one pass, and nesting past the stack names a problem."""
    import time

    from cuju.render._packages import glsl as _glsl

    assert _glsl.check(_hook(_loop(32, _loop(32, 'emissive.x += 0.001;', 'j')))) == []
    many = _hook('\n'.join(_loop(2, 'emissive.x += 0.0;', f'i{n}') for n in range(4000)))
    start = time.perf_counter()
    _glsl.check(many)
    assert time.perf_counter() - start < 10
    deep = _hook(''.join(f'for (int i{n} = 0; i{n} < 2; i{n}++) ' for n in range(3000)) + ';')
    assert _glsl.check(deep)


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
        ({'rig': {'layers': [{'mask': ['a']}]}}, 'layer 1 left out'),
        ({'reflexes': [{'on': 'goal', 'do': [{'time': {'freeze': 2}}]}]}, 'reflex 1 left out'),
        (
            {'reflexes': [{'on': 'goal', 'do': [{'environment': {'rain': {}}}]}]},
            'reflex 1 left out',
        ),
        ({'reflexes': [{'on': 'goal', 'do': [{'music': 'none'}]}]}, 'reflex 1 left out'),
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
    assert main(['pack', 'sides', '--right', 'none', '--left', team['id'], '--json']) == 0
    assert json.loads(capsys.readouterr().out) == {'left': team['id'], 'right': None}
    from support.package import package_zip

    archive = render_home / 'preview.zip'
    archive.write_bytes(package_zip('Previewed'))
    place = _pack.preview(archive, 'right')
    assert place.startswith('#match=') and place.endswith('&preview=right')
    chosen = _presentation.sides()['right']
    assert chosen and _presentation.served(chosen)['manifest']['name'] == 'Test package'


def test_pack_check_names_what_it_finds(tmp_path):
    """Each message names the value it refuses, counts from 1 and skips refused budgets."""
    import shutil

    from cuju.render._packages import pack as _pack

    def deep(package, manifest):
        (package / 'a/b/c/d').mkdir(parents=True)
        shutil.copy(package / 'audio/tick.wav', package / 'a/b/c/d/t.wav')

    cases = {
        'event': (
            lambda p, m: m['reflexes'][0].__setitem__('on', 'goal_scored'),
            'reflex 1 left out, expected reflex 1 on an event of the catalog, found '
            "'goal_scored', the nearest is goal",
        ),
        'cue': (
            lambda p, m: m['reflexes'][0]['do'][0].__setitem__('audio', 'nosuchcue'),
            "expected action 1 to play a cue of the audio, found 'nosuchcue', the cues are tick",
        ),
        'stems': (
            lambda p, m: m['audio'].__setitem__(
                'music', {'anthem': {'stems': {'bass': 'audio/tick.wav'}}}
            ),
            'expected the stems of music anthem as a list of files, found a mapping',
        ),
        'behaviour': (
            lambda p, m: m['behaviours'].append({'type': 'wobble'}),
            'behaviour 2 left out, expected behaviour 2 of a type among',
        ),
        'deep': (
            deep,
            "expected a file in at most 3 folders of the package, found 'a/b/c/d/t.wav'",
        ),
        'feature': (
            lambda p, m: m['requires'].append('nonexistent.feature'),
            'the package requires nonexistent.feature, a feature no renderer names, so the page '
            'draws the team in its stock look',
        ),
        'shader': (
            lambda p, m: (p / 'shaders/glow.glsl').write_text(
                'vec3 cujuEmissive(vec3 e, vec2 uv) { return e + ; }\n'
            ),
            'shaders/glow.glsl of mode chunks line 1 holds the operator + with nothing after it',
        ),
    }
    for name, (change, message) in cases.items():
        result = _pack.check(_template_variant(tmp_path, name, change))
        assert not result['ok'], name
        assert any(message in error for error in result['errors']), (name, result['errors'])
    # A refused count of particles is an error alone, with no budget warning of its own.
    count = _template_variant(
        tmp_path, 'count', lambda p, m: m['effects']['spark'].__setitem__('count', 100000)
    )
    result = _pack.check(count)
    assert any('effect spark left out' in error for error in result['errors'])
    assert not any('particles' in warning for warning in result['warnings']), result['warnings']
    assert result['budgets']['low']['particles'][0] == 0
    # The manifest itself is a path the check reads, and a file of another kind says so.
    plain = _template_variant(tmp_path, 'plain', lambda p, m: None)
    assert _pack.check(plain / 'cuju-team/presentation/presentation.json')['ok']
    (tmp_path / 'notes.txt').write_text('hello')
    with pytest.raises(cuju.errors.ArgumentError, match=r'presentation.json or a .zip export'):
        _pack.check(tmp_path / 'notes.txt')
    # A sample shorter than one block of 400 ms says why its integrated loudness reads higher.
    info = ' | '.join(_pack.check(plain)['info'])
    assert 'audio/tick.wav lasts 0.15 seconds, less than one block of 400 ms' in info


def test_pack_check_parses_the_worker_with_node(tmp_path):
    """A worker that does not parse is an error when Node.js is at hand, information otherwise."""
    import shutil

    from cuju.render._packages import pack as _pack

    folder = _template_variant(
        tmp_path,
        'worker',
        lambda p, m: (p / 'worker.js').write_text('export function frame(f) { return { ; }\n'),
    )
    result = _pack.check(folder)
    if shutil.which('node') is None:
        assert result['ok'] and any('Node.js is not installed' in i for i in result['info'])
    else:
        assert not result['ok']
        assert any(
            'the worker worker.js does not parse, SyntaxError' in e and 'at line 1' in e
            for e in result['errors']
        ), result['errors']
        assert _pack.check(_template_variant(tmp_path, 'fine', lambda p, m: None))['ok']


def test_pack_check_names_the_figures_of_the_team(tmp_path):
    """The check says which players draw GRF's figure and what of a package shows on it."""
    from cuju.render._packages import pack as _pack

    plain = _pack.check(_template_variant(tmp_path, 'plain', lambda p, m: None))
    assert plain['ok'] and plain['warnings'] == [], plain['warnings']
    info = ' | '.join(plain['info'])
    assert "11 players draw GRF's figure, which carries the sockets, attachments" in info
    assert 'the check read 1 shader by the static rules of the section Shaders' in info
    assert 'compiled none, and the page compiles each before it draws' in info

    def tail(package, manifest):
        manifest['rig']['sockets']['crown']['node'] = 'tail'
        manifest['rig']['driver'] = 'team'
        manifest['clips'] = {'idle.calm': 'Idle'}

    result = _pack.check(_template_variant(tmp_path, 'tail', tail))
    assert result['ok'], result['errors']
    warnings = ' | '.join(result['warnings'])
    assert "socket crown names the node tail, which GRF's figure lacks" in warnings
    assert 'player, body, middle, neck, ' in warnings and 'right_knee and right_ankle' in warnings
    assert "the role idle.calm shows only on a model of the package or the team's own model" in (
        warnings
    )
    assert "GRF's figure keeps the grf driver, so the team driver of the rig" in warnings
    # A node of GRF's figure passes, and the test package's own model checks its own nodes.
    body = _template_variant(
        tmp_path, 'body', lambda p, m: m['rig']['sockets']['crown'].__setitem__('node', 'neck')
    )
    assert _pack.check(body)['warnings'] == []


def test_presentation_messages_list_their_choices_in_words():
    from cuju.render._packages import presentation as _presentation

    with pytest.raises(cuju.errors.ArgumentError) as caught:
        _presentation.behaviour({'type': 'twirl'})
    message = str(caught.value)
    assert 'among spin, oscillate, spring, lookAt, bank, follow, curve, materialParam, ' in message
    assert 'audioParam or lightParam' in message and "('" not in message
    with pytest.raises(cuju.errors.ArgumentError, match=r'channel of behaviour 1 among x, y, z'):
        _presentation.behaviour({'type': 'oscillate', 'channel': 'w'})
    assert _presentation.words(['a']) == 'a' and _presentation.words('ab', 'and') == 'a and b'


def test_pack_examples_agree_and_spell_color():
    """The template and the test package call themselves the small and the full example."""
    from pathlib import Path

    from cuju.render._packages import pack as _pack

    docs = (Path(__file__).resolve().parents[1] / 'docs/presentation.md').read_text()
    tests = (Path(__file__).resolve().parent / 'support' / 'package.py').read_text()
    assert 'the test package in\n`tests/support/team` is the full example' in docs
    assert 'full example' in tests and 'small test package' not in tests
    assert 'colour' not in _pack._GLOW and 'color' in _pack._GLOW


def test_pack_sides_prints_lines_and_a_preview_moves_its_side(render_home, tmp_path, capsys):
    from cuju.render.__main__ import main
    from cuju.render._packages import pack as _pack
    from cuju.render._packages import presentation as _presentation

    folder = _template_variant(tmp_path, 'team', lambda p, m: m.__setitem__('name', 'Lanterns'))
    left = _pack.register_preview(folder, 'left')
    assert _presentation.sides() == {'left': left['team'], 'right': None}
    right = _pack.register_preview(folder, 'right')
    assert right['team'] == left['team']
    assert _presentation.sides() == {'left': None, 'right': left['team']}
    assert main(['pack', 'sides']) == 0
    printed = capsys.readouterr().out.splitlines()
    assert printed == [
        'left  draws the package of the team that plays it',
        f'right  draws the package of Lanterns, team {left["team"]}',
    ]
    assert main(['pack', 'sides', '--json']) == 0
    assert json.loads(capsys.readouterr().out) == {'left': None, 'right': left['team']}
    assert main(['pack', 'sides', '--left', left['team'], '--right', 'none', '--json']) == 0
    assert json.loads(capsys.readouterr().out) == {'left': left['team'], 'right': None}


def test_team_sound_command_line(render_home, tmp_path, capsys):
    from cuju.render.__main__ import main
    from cuju.render._packages import pack as _pack

    team = _teams.add('Singers', 'main.py', b'def agent(obs):\n    return 0\n')
    sound = tmp_path / 'shot.wav'
    sound.write_bytes(_pack.tone_bytes())
    assert main(['team', 'sound', team['id'], 'shot', str(sound)]) == 0
    assert capsys.readouterr().out.strip() == 'Singers, sounds shot'
    assert main(['team', 'sound', team['id'], '--json']) == 0
    assert json.loads(capsys.readouterr().out) == {'team': team['id'], 'sounds': ['shot']}
    (tmp_path / 'bad.wav').write_bytes(b'RIFF\x08\x00\x00\x00WAVEfmt ')
    assert main(['team', 'sound', team['id'], 'goal', str(tmp_path / 'bad.wav')]) == 1
    assert 'expected a whole WAV sound' in capsys.readouterr().err
    assert main(['team', 'sound', team['id'], 'cheer', str(sound)]) == 1
    assert 'expected the moment of a sound among goal, shot, pass' in capsys.readouterr().err
    assert main(['team', 'sound', team['id'], 'shot', '--remove']) == 0
    assert capsys.readouterr().out.strip() == 'Singers, sounds none'
