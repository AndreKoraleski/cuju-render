# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks the video export of the renderer, its options, ranges, commands and server endpoints.

The end to end test draws two seconds of a sample match in the browser's own encoder, as MP4 and
as WebM, and once more through ffmpeg where it is installed, when Chrome or Edge and ffprobe are on
this machine. It is skipped otherwise, unless `CUJU_VIDEO_REQUIRED` is set, which fails it instead.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from cuju.render._export import video as _video
from cuju.render._export import video_jobs as _video_jobs
from cuju.render._http import server as _server
from cuju.render._store import home as _home
from cuju.render._store import library as _library
from cuju.render._text import messages as _messages

SAMPLE = Path(_video.__file__).parents[1] / 'samples' / 'sample-5v5.cjr'


@pytest.fixture
def render_home(tmp_path, monkeypatch):
    monkeypatch.setenv(_home.HOME_VARIABLE, str(tmp_path / 'render'))
    return tmp_path / 'render'


def _facts(goals=(9.7, 44.3), frames=3002):
    return _video.Facts('a match', frames, 10.0, tuple(goals))


@pytest.mark.parametrize(
    ('text', 'moment'),
    [
        ('75', _video.Moment(75.0)),
        ('75.5', _video.Moment(75.5)),
        ('1:15', _video.Moment(75.0)),
        ('2:03.5', _video.Moment(123.5)),
        ('goal:2', _video.Moment(0.0, 2)),
        ('goal2', _video.Moment(0.0, 2)),
        ('Goal:1-8', _video.Moment(-8.0, 1)),
        ('goal:3+4.5', _video.Moment(4.5, 3)),
    ],
)
def test_moments(text, moment):
    assert _video.parse_moment(text) == moment


@pytest.mark.parametrize(
    'text', ['', 'abc', '1:75', '-5', 'goal:0', 'goal:-1', '1:2:3', 'goal:1*2']
)
def test_moment_refusals(text):
    with pytest.raises(_video.ArgumentError):
        _video.parse_moment(text)


def test_sizes_and_hours():
    assert _video.parse_size('1920x1080') == (1920, 1080)
    assert _video.parse_size('720p') == (1280, 720)
    assert _video.parse_size(' 640 x 360 ') == (640, 360)
    for text in ('1281x720', '99999x100', '100x50', 'big', '1280'):
        with pytest.raises(_video.ArgumentError):
            _video.parse_size(text)
    assert _video.parse_hour('dusk') == 19.0
    assert _video.parse_hour('21.5') == 21.5
    for text in ('25', '-1', 'noon', 'nan'):
        with pytest.raises(_video.ArgumentError):
            _video.parse_hour(text)


def test_option_checks():
    _video.Options().check()
    for change in (
        {'camera': 'free'},
        {'fps': 0},
        {'fps': 61},
        {'fps': True},
        {'width': 1281},
        {'quality': 'best'},
        {'arena': 'moon'},
        {'hour': 30},
        {'goal': 0},
        {'max_seconds': 0},
        {'max_seconds': 4000},
        {'max_megabytes': 0},
    ):
        with pytest.raises(_video.ArgumentError):
            _video.Options(**change).check()


def test_ranges():
    facts = _facts()
    assert facts.duration == pytest.approx(300.1)

    def resolve(**options):
        return _video.resolve_range(_video.Options(**options), facts)

    assert resolve() == (0.0, pytest.approx(300.1))
    assert resolve(goal=1) == (pytest.approx(1.7), pytest.approx(13.7))
    assert resolve(goal=2, end=_video.Moment(2.0, 2)) == (pytest.approx(36.3), pytest.approx(46.3))
    assert resolve(start=_video.Moment(-5.0, 1), end=_video.Moment(1.0, 1)) == (
        pytest.approx(4.7),
        pytest.approx(10.7),
    )
    # A range is kept within the recording.
    assert resolve(start=_video.Moment(290.0), end=_video.Moment(400.0)) == (
        290.0,
        pytest.approx(300.1),
    )
    assert _video.resolve_range(_video.Options(goal=1), _facts((3.0,))) == (0.0, 7.0)
    with pytest.raises(_video.ArgumentError, match='from 1 to 2'):
        resolve(goal=3)
    with pytest.raises(_video.ArgumentError, match='none in the recording'):
        _video.resolve_range(_video.Options(start=_video.Moment(0.0, 1)), _facts(()))
    for start, end in ((10.0, 10.0), (20.0, 5.0), (400.0, 500.0)):
        with pytest.raises(_video.ArgumentError, match='holds frames'):
            resolve(start=_video.Moment(start), end=_video.Moment(end))
    assert _video.frame_count(0.0, 2.0, 30) == 60
    assert _video.frame_count(1.7, 13.7, 25) == 300
    assert _video.frame_count(0.0, 0.01, 30) == 1


def test_recording_facts(tmp_path):
    facts = _video.recording_facts(SAMPLE)
    assert (facts.frames, facts.steps_per_second) == (3002, 10.0)
    assert facts.goals == pytest.approx((9.7, 44.3))
    broken = tmp_path / 'broken.cjr'
    broken.write_bytes(b'not a recording')
    with pytest.raises(_video.VideoError, match='not a readable recording'):
        _video.recording_facts(broken)


def test_commands():
    options = _video.Options(width=1920, height=1080, fps=25, quality='high').check()
    chrome = _video.chrome_command('chrome', '/tmp/profile', options)
    assert chrome[0] == 'chrome' and chrome[-1] == 'about:blank'
    for flag in (
        '--headless=new',
        '--mute-audio',
        '--remote-debugging-port=0',
        '--user-data-dir=/tmp/profile',
        '--proxy-server=http://127.0.0.1:9',
        '--window-size=1280,720',
    ):
        assert flag in chrome
    root = hasattr(os, 'geteuid') and os.geteuid() == 0
    assert ('--no-sandbox' in chrome) == root and '--use-angle=swiftshader' not in chrome
    plain = _video.Options(width=640, height=360, software=True, sandbox=False).check()
    chrome = _video.chrome_command('chrome', 'p', plain)
    assert {'--no-sandbox', '--use-angle=swiftshader', '--window-size=640,360'} <= set(chrome)
    assert _video.view(1920, 1080) == (1280, 720, 1.5)
    assert _video.view(640, 360) == (640, 360, 1.0)
    ffmpeg = _video.ffmpeg_command('ffmpeg', Path('out.part.mp4'), options)
    assert ffmpeg[0] == 'ffmpeg' and ffmpeg[-1] == 'out.part.mp4'
    assert ffmpeg[ffmpeg.index('-framerate') + 1] == '25'
    assert ffmpeg[ffmpeg.index('-crf') + 1] == '15'
    assert ffmpeg[ffmpeg.index('-vf') + 1].startswith('scale=1920:1080')
    assert ffmpeg[ffmpeg.index('-fs') + 1] == str(2048 * 1024 * 1024)
    assert ffmpeg[ffmpeg.index('-i') + 1] == '-' and '-an' in ffmpeg


def test_preload_keeps_sound_off_and_follows_the_clock():
    script = _video.preload_script(_video.Options(arena='beach', hour=21.5, camera='ball'))
    settings = {}
    for line in script.splitlines():
        if line.startswith('localStorage.setItem('):
            key, value = json.loads('[' + line[len('localStorage.setItem(') : -2] + ']')
            settings[key] = json.loads(value)
    assert settings['cuju.muted'] is True and settings['cuju.volume'] == 0
    assert settings['cuju.pointerLock'] is False and settings['cuju.tvMode'] is True
    assert settings['cuju.field'] == {'arena': 'beach', 'time': 21.5}
    assert settings['cuju.camera'] == 'broadcast'
    for key in ('lineups', 'celebrations', 'replays', 'decisionReplays', 'transitions'):
        assert settings[f'cuju.{key}'] is False
    assert 'requestPointerLock' in script and 'getGamepads' in script
    broadcast = _video.preload_script(_video.Options(broadcast=True))
    assert '"cuju.replays", "true"' in broadcast and 'cuju.field' not in broadcast


def _preloaded(options):
    settings = {}
    for line in _video.preload_script(options).splitlines():
        if line.startswith('localStorage.setItem('):
            key, value = json.loads('[' + line[len('localStorage.setItem(') : -2] + ']')
            settings[key] = json.loads(value)
    return settings


def test_annotations_show_in_a_video_only_when_asked():
    """An export shows the clean picture, and the labels and box of annotations on request."""
    hidden = {'players': False, 'actions': False, 'text': False}
    assert _preloaded(_video.Options())['cuju.annotations'] == hidden
    assert _preloaded(_video.Options(broadcast=True))['cuju.annotations'] == hidden
    shown = _preloaded(_video.Options(annotations=True))['cuju.annotations']
    assert shown == {'players': True, 'actions': True, 'text': True}
    with pytest.raises(_video.ArgumentError, match='annotations'):
        _video.Options(annotations='yes').check()
    parser = argparse.ArgumentParser()
    _video.add_arguments(parser)
    assert not _video.options_from(parser.parse_args([str(SAMPLE)])).annotations
    assert _video.options_from(parser.parse_args([str(SAMPLE), '--annotations'])).annotations
    arguments, options = _video_jobs.options_from({'end': 5, 'annotations': True})
    assert options.annotations and arguments[-1] == '--annotations'
    arguments, options = _video_jobs.options_from({'end': 5})
    assert not options.annotations and '--annotations' not in arguments
    with pytest.raises(_video.ArgumentError, match='annotations'):
        _video_jobs.options_from({'end': 5, 'annotations': 1})


def test_missing_tools(monkeypatch, tmp_path):
    monkeypatch.delenv('CUJU_CHROME', raising=False)
    monkeypatch.delenv('CUJU_FFMPEG', raising=False)
    monkeypatch.setattr(_video.shutil, 'which', lambda name: None)
    monkeypatch.setattr(_video, '_chrome_locations', lambda: [])
    chrome, ffmpeg, missing = _video.tools(_video.Options())
    assert chrome is None and ffmpeg is None
    assert 'Install Google Chrome or Chromium' in missing[0]['text']
    assert 'Install ffmpeg' in missing[1]['text']
    # The export needs the browser alone, so a missing ffmpeg never stops it.
    with pytest.raises(_video.VideoError, match='Install Google Chrome or Chromium') as stopped:
        _video.export(SAMPLE, tmp_path / 'out.mp4', _video.Options(end=_video.Moment(1.0)))
    assert 'ffmpeg' not in str(stopped.value)
    with pytest.raises(_video.VideoError, match='expected a program'):
        _video.find_ffmpeg(str(tmp_path / 'no-ffmpeg'))
    program = tmp_path / 'ffmpeg-here'
    program.write_text('', encoding='utf-8')
    monkeypatch.setenv('CUJU_FFMPEG', str(program))
    assert _video.find_ffmpeg() == str(program)
    assert not list(tmp_path.glob('*.mp4'))


def test_export_checks_the_range_before_the_programs(monkeypatch, tmp_path):
    """A mistake in the range shows at once, before the export looks for the browser."""
    looked = []

    def find_chrome(explicit=None):
        looked.append(explicit)
        return None

    monkeypatch.setattr(_video, 'find_chrome', find_chrome)
    output = tmp_path / 'out.mp4'
    for options, message in (
        (_video.Options(start=_video.Moment(70.0), end=_video.Moment(65.0)), 'holds frames'),
        (_video.Options(goal=99), 'expected a goal'),
        (_video.Options(max_seconds=60), 'at most 60 seconds'),
    ):
        with pytest.raises(_video.ArgumentError, match=message):
            _video.export(SAMPLE, output, options)
    assert not looked
    with pytest.raises(_video.VideoError, match='needs Chrome or Chromium'):
        _video.export(SAMPLE, output, _video.Options(end=_video.Moment(1.0)))
    assert len(looked) == 1 and not list(tmp_path.iterdir())


def test_the_output_and_the_format_name_the_container(tmp_path):
    options = _video.Options()
    assert _video.requested_format(Path('a.mp4'), options) == 'mp4'
    assert _video.requested_format(Path('a.WEBM'), options) == 'webm'
    assert _video.requested_format(Path('a.mp4'), _video.Options(format='auto')) is None
    assert _video.requested_format(Path('a.webm'), _video.Options(format='webm')) == 'webm'
    with pytest.raises(_video.ArgumentError, match=r'ending in \.webm for the format webm'):
        _video.requested_format(Path('a.mp4'), _video.Options(format='webm'))
    with pytest.raises(_video.ArgumentError, match=r'ending in \.mp4 or \.webm'):
        _video.requested_format(Path('a.mkv'), options)
    with pytest.raises(_video.ArgumentError, match='expected a format'):
        _video.Options(format='avi').check()


def test_the_browser_encodes_and_ffmpeg_only_adds_an_mp4():
    both = {'mp4': 'avc1.64001F', 'webm': 'vp09.00.31.08', 'pictures': True}
    webm = {'mp4': None, 'webm': 'vp8', 'pictures': True}
    none = {'mp4': None, 'webm': None, 'pictures': True}
    choose = _video.choose_encoding
    assert choose(None, both, None) == ('browser', 'mp4')
    assert choose(None, both, 'ffmpeg') == ('browser', 'mp4')
    assert choose('webm', both, 'ffmpeg') == ('browser', 'webm')
    # Without H.264 the best is an MP4 of ffmpeg where it is installed, else a WebM.
    assert choose(None, webm, 'ffmpeg') == ('ffmpeg', 'mp4')
    assert choose(None, webm, None) == ('browser', 'webm')
    assert choose('mp4', webm, 'ffmpeg') == ('ffmpeg', 'mp4')
    with pytest.raises(_video.VideoError, match='--format webm') as refused:
        choose('mp4', webm, None, 'chromium')
    assert 'H.264' in str(refused.value) and 'chromium' in str(refused.value)
    with pytest.raises(_video.VideoError, match='VP9 or VP8'):
        choose('webm', none, 'ffmpeg')
    assert choose(None, none, 'ffmpeg') == ('ffmpeg', 'mp4')
    with pytest.raises(_video.VideoError, match='encodes video'):
        choose(None, none, None)
    # A browser that cannot read back the page's graphics leaves the MP4 to ffmpeg.
    assert choose(None, {**both, 'pictures': False}, 'ffmpeg') == ('ffmpeg', 'mp4')


def test_missing_tools_name_what_the_server_takes(render_home, monkeypatch):
    """The page's server takes the variables alone, so its message names no option."""
    from cuju.render._guide import doctor as _doctor

    monkeypatch.delenv('CUJU_CHROME', raising=False)
    monkeypatch.delenv('CUJU_FFMPEG', raising=False)
    monkeypatch.setattr(_video.shutil, 'which', lambda name: None)
    monkeypatch.setattr(_video, '_chrome_locations', lambda: [])
    command = ' '.join(label['text'] for label in _video.tools(_video.Options())[2])
    assert '--chrome or $CUJU_CHROME' in command and '--ffmpeg or $CUJU_FFMPEG' in command
    status = _video_jobs.availability()
    served = ' '.join(status['missing'])
    assert not status['available'] and '--' not in served
    # The server needs the browser alone, so ffmpeg is never missing.
    assert '$CUJU_CHROME in the environment of cuju render serve' in served
    assert 'ffmpeg' not in served
    # The page shows the missing browser by the id of its message, in its own language.
    assert [label['id'] for label in status['missing_labels']] == ['server.video.missing_chrome']
    assert [label['text'] for label in status['missing_labels']] == status['missing']
    # The doctor warns of a missing program, which video export alone needs, and still passes.
    checks = _doctor.server_report()['checks']
    check = next(c for c in checks if c['name'] == 'video export')
    assert check['ok'] and check['warning']
    assert check['detail_id'] == 'server.video.missing_chrome'
    # Every check names itself and its detail by id as well.
    for found in checks:
        assert found['name_id'] in _messages.MESSAGES and found['detail_id'] in _messages.MESSAGES
    lines = _doctor.text({'checks': [check]}).splitlines()
    assert any(line.startswith('  warn  video export, Video export needs') for line in lines)


def test_the_server_exports_with_a_browser_alone(render_home, monkeypatch, tmp_path):
    from cuju.render._guide import doctor as _doctor

    program = tmp_path / 'chrome-here'
    program.write_text('', encoding='utf-8')
    monkeypatch.setenv('CUJU_CHROME', str(program))
    monkeypatch.delenv('CUJU_FFMPEG', raising=False)
    monkeypatch.setattr(_video.shutil, 'which', lambda name: None)
    assert _video.find_ffmpeg() is None
    assert _video_jobs.availability() == {'available': True, 'missing': [], 'missing_labels': []}
    # The doctor names the browser it found.
    checks = _doctor.server_report()['checks']
    check = next(c for c in checks if c['name'] == 'video export')
    assert check['ok'] and not check['warning']
    assert check['detail_id'] == 'server.doctor.video.found'
    assert check['detail'] == 'a browser is found, chrome-here'


def test_file_sizes_read_in_kilobytes_below_a_megabyte():
    assert _video.file_size(22_000) == '22 KB'
    assert _video.file_size(300) == '1 KB'
    assert _video.file_size(2_500_000) == '2.5 MB'


def test_export_refuses_long_ranges_and_other_files(monkeypatch, tmp_path):
    monkeypatch.setattr(_video, 'tools', lambda options: ('chrome', 'ffmpeg', []))
    with pytest.raises(_video.ArgumentError, match='at most 60 seconds'):
        _video.export(SAMPLE, tmp_path / 'out.mp4', _video.Options(max_seconds=60).check())
    with pytest.raises(_video.ArgumentError, match=r'ending in \.mp4'):
        _video.export(SAMPLE, tmp_path / 'out.avi', _video.Options())


def test_cli_options(render_home, monkeypatch, tmp_path, capsys):
    from cuju.render.__main__ import main

    calls = []

    def export(path, output, options, identifier=None, report=None, cancelled=None, **more):
        calls.append((path, output, options, identifier, more))
        summary = {'title': 't', 'start': 1.7, 'end': 13.7, 'frames': 300, 'width': 1920}
        report({'stage': 'starting', 'height': 1080, 'fps': 25, **summary})
        report({'stage': 'drawing', 'frame': 0, 'progress': 0.0})
        report({'stage': 'drawing', 'frame': 150, 'progress': 0.5})
        return {
            'frames': 300, 'seconds': 12.0, 'bytes': 1000, 'page_errors': [], 'path': str(output),
        }  # fmt: skip

    monkeypatch.setattr(_video, 'export', export)
    output = tmp_path / 'goal.mp4'
    arguments = [
        'video',
        str(SAMPLE),
        '-o',
        str(output),
        '--goal',
        '1',
        '--size',
        '1080p',
        '--fps',
        '25',
        '--no-score',
        '--arena',
        'beach',
        '--time',
        'night',
        '--camera',
        'tactical',
        '--quality',
        'draft',
        '--no-sandbox',
    ]
    assert main(arguments) == 0
    path, written, options, identifier, more = calls[0]
    assert (path, written, identifier, more) == (SAMPLE, output, None, {'overwrite': False})
    assert options.format is None
    assert (options.goal, options.width, options.height, options.fps) == (1, 1920, 1080, 25)
    assert (options.score, options.arena, options.hour) == (False, 'beach', 22)
    assert options.camera == 'tactical'
    assert (options.quality, options.sandbox, options.broadcast) == ('draft', False, False)
    out = capsys.readouterr()
    assert f'saved {output}' in out.out and 'frame 150, 50%' in out.err
    # A library identifier names its recording, and an output that exists stays unless replaced.
    _library.add_samples()
    output.write_bytes(b'kept')
    assert main(['video', 'sample-5v5', '-o', str(output), '--start', 'goal:2-3']) == 1
    assert 'add --overwrite' in capsys.readouterr().err and output.read_bytes() == b'kept'
    assert main(['video', 'sample-5v5', '-o', str(output), '--overwrite', '--end', '1:00']) == 0
    assert calls[-1][3] == 'sample-5v5' and calls[-1][2].end == _video.Moment(60.0)
    assert main(['video', 'no-such-match']) == 1
    assert 'expected a .cjr file' in capsys.readouterr().err
    for wrong in (['--start', 'soon'], ['--size', '7x7'], ['--time', 'noon'], ['--camera', 'free']):
        with pytest.raises(SystemExit):
            main(['video', str(SAMPLE), *wrong])
    assert main(['video', str(SAMPLE), '--fps', '0', '-o', str(tmp_path / 'a.mp4')]) == 1
    # Without a file the name follows the source and the format, auto unless one is asked for.
    monkeypatch.chdir(tmp_path)
    assert main(['video', str(SAMPLE)]) == 0
    assert calls[-1][1] == Path('sample-5v5.mp4') and calls[-1][2].format == 'auto'
    assert main(['video', str(SAMPLE), '--format', 'webm']) == 0
    assert calls[-1][1] == Path('sample-5v5.webm') and calls[-1][2].format == 'webm'
    with pytest.raises(SystemExit):
        main(['video', str(SAMPLE), '--format', 'avi'])


def test_cli_cancel(monkeypatch, tmp_path, capsys):
    def export(*arguments, **options):
        raise _video.CancelledError('the export was cancelled')

    monkeypatch.setattr(_video, 'export', export)
    from cuju.render.__main__ import main

    assert main(['video', str(SAMPLE), '-o', str(tmp_path / 'c.mp4')]) == 130
    assert 'nothing was written' in capsys.readouterr().err


def test_page_request_options():
    arguments, options = _video_jobs.options_from(
        {
            'start': 1.5,
            'end': 9,
            'width': 1920,
            'height': 1080,
            'fps': 60,
            'score': False,
            'arena': 'space',
            'time': 6.5,
            'camera': 'goal',
            'quality': 'high',
        }
    )
    assert arguments == [
        '--start', '1.500', '--end', '9.000', '--camera', 'goal', '--size', '1920x1080',
        '--fps', '60', '--quality', 'high', '--no-score', '--arena', 'space', '--time', '6.5',
    ]  # fmt: skip
    assert (options.start, options.end) == (_video.Moment(1.5), _video.Moment(9.0))
    # The page offers common rates, and a request takes any whole rate from 1 to 60, as the command
    # line does.
    for fps in (1, 10, 29, 60):
        arguments, options = _video_jobs.options_from({'end': 5, 'fps': fps})
        assert options.fps == fps and arguments[arguments.index('--fps') + 1] == str(fps)
    for wrong in (
        {'end': 5, 'start': 5},
        {'end': 'soon'},
        {'end': 5, 'width': 1001, 'height': 500},
        {'end': 5, 'width': 3840, 'height': 3840},
        {'end': 5, 'scale': 3},
        {'end': 5, 'safe': 'wide'},
        {'end': 5, 'fps': 0},
        {'end': 5, 'fps': 61},
        {'end': 5, 'fps': 29.5},
        {'end': 5, 'fps': True},
        {'end': 5, 'score': 'yes'},
        {'end': 5, 'camera': 'free'},
        {'end': 5, 'arena': 'moon'},
        {'end': 5, 'time': 30},
        {'end': 5, 'sound': True},
    ):
        with pytest.raises(_video.ArgumentError):
            _video_jobs.options_from(wrong)


# A stand in for an export's process, which reports progress, writes the file and exits, or
# waits for a cancellation.
_FAKE = """
import json, sys, time
output = sys.argv[sys.argv.index('-o') + 1]
if '--quality' in sys.argv and sys.argv[sys.argv.index('--quality') + 1] == 'draft':
    print(json.dumps({'stage': 'drawing', 'frame': 1, 'progress': 0.1}), flush=True)
    sys.stdin.readline()
    print(json.dumps({'stage': 'cancelled'}), flush=True)
    sys.exit(130)
for frame in (10, 20):
    print(json.dumps({'stage': 'drawing', 'frame': frame, 'progress': frame / 20}), flush=True)
done = {'stage': 'done', 'bytes': 5}
# A browser without H.264 writes WebM, and the export names the file it wrote.
if '--quality' in sys.argv and sys.argv[sys.argv.index('--quality') + 1] == 'high':
    output = output[: -len('.mp4')] + '.webm'
    done['path'] = output
open(output, 'wb').write(b'video')
print(json.dumps(done), flush=True)
"""


def _request(address, path, document=None, method='GET'):
    data = None if document is None else json.dumps(document).encode()
    request = urllib.request.Request(address + path, data=data, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read()
        return response.status, dict(response.headers), body


def test_a_request_that_is_no_json_names_its_mistake(render_home):
    """A body or a parameter that is no JSON, and any other error of the request, answers by id."""
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests(), videos=_video_jobs.VideoJobs())
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_address[1]}'

    def refused(path, data=None, method='GET'):
        request = urllib.request.Request(address + path, data=data, method=method)
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=10)
        assert caught.value.code == 400
        return json.loads(caught.value.read())

    try:
        body = refused('/api/matches/sample-5v5/video', b'{"start": 0,', 'POST')
        assert (body['error_id'], body['error_values']) == (
            'server.json',
            {'line': '1', 'column': '13'},
        )
        assert refused('/api/matches/sample-5v5/video', b'\xff', 'POST')['error_id'] == (
            'server.json_text'
        )
        assert refused('/api/search?limit=x')['error_id'] == 'server.search.limit'
        found = refused('/api/search?q=kind:nothing')
        assert (found['error_id'], found['error_values']) == (
            'server.search.kind',
            {'name': "'nothing'"},
        )
    finally:
        server.shutdown()
        server.server_close()


def _wait(address, identifier, state):
    for _ in range(200):
        entry = json.loads(_request(address, f'/api/videos/{identifier}')[2])
        if entry['state'] == state:
            return entry
        time.sleep(0.05)
    raise AssertionError(f'the export stayed {entry["state"]}')


def test_server_exports(render_home, monkeypatch):
    _library.add_samples(['sample-5v5'])
    popen = subprocess.Popen

    def fake(command, **options):
        rest = command[command.index('cuju.render._export.video') + 1 :]
        return popen([sys.executable, '-c', _FAKE, *rest], **options)

    monkeypatch.setattr(_video_jobs.subprocess, 'Popen', fake)
    available = {'available': True, 'missing': []}
    monkeypatch.setattr(_video_jobs, 'availability', lambda: available)
    videos = _video_jobs.VideoJobs()
    server = _server.http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests(), videos=videos)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        stale = _home.folder('videos') / 'v-old.mp4'
        stale.write_bytes(b'old')
        assert json.loads(_request(address, '/api/video')[2]) == available
        assert json.loads(_request(address, '/api/videos')[2]) == []
        status, _, body = _request(
            address, '/api/matches/sample-5v5/video', {'start': 9, 'end': 12, 'fps': 25}, 'POST'
        )
        entry = json.loads(body)
        assert status == 201 and entry['frames'] == 75 and entry['state'] == 'running'
        assert entry['filename'] == 'Sample match, 5 vs 5 0m09-0m12.mp4'
        assert not stale.exists()
        done = _wait(address, entry['id'], 'done')
        assert (done['progress'], done['frame'], done['bytes']) == (1.0, 20, 5)
        status, headers, body = _request(address, f'/api/videos/{entry["id"]}/file')
        assert (status, body, headers['Content-Type']) == (200, b'video', 'video/mp4')
        assert 'attachment' in headers['Content-Disposition']
        # The export asks for the browser's best container and follows the file it wrote.
        _, _, body = _request(
            address,
            '/api/matches/sample-5v5/video',
            {'start': 9, 'end': 12, 'quality': 'high'},
            'POST',
        )
        webm = _wait(address, json.loads(body)['id'], 'done')
        assert webm['filename'] == 'Sample match, 5 vs 5 0m09-0m12.webm'
        status, headers, body = _request(address, f'/api/videos/{webm["id"]}/file')
        assert (status, body, headers['Content-Type']) == (200, b'video', 'video/webm')
        assert (_home.folder('videos') / f'{webm["id"]}.webm').is_file()
        # A running export is cancelled through its process, which then ends.
        _, _, body = _request(
            address,
            '/api/matches/sample-5v5/video',
            {'start': 0, 'end': 2, 'quality': 'draft'},
            'POST',
        )
        running = json.loads(body)
        with pytest.raises(urllib.error.HTTPError) as busy:
            _request(address, '/api/matches/sample-5v5/video', {'start': 0, 'end': 2}, 'POST')
        assert busy.value.code == 409
        assert _request(address, f'/api/videos/{running["id"]}', method='DELETE')[0] == 204
        assert _wait(address, running['id'], 'cancelled')['error'] is None
        # A finished export goes with its file.
        assert _request(address, f'/api/videos/{entry["id"]}', method='DELETE')[0] == 204
        assert not list(_home.folder('videos').glob(f'{entry["id"]}*'))
        for path, document, code in (
            ('/api/matches/no-match/video', {'start': 0, 'end': 2}, 400),
            ('/api/matches/sample-5v5/video', {'start': 0, 'end': 2, 'width': 641}, 400),
            ('/api/matches/sample-5v5/video', {'start': 0, 'end': 2, 'fps': 61}, 400),
            ('/api/matches/sample-5v5/video', {'start': 400, 'end': 500}, 400),
        ):
            with pytest.raises(urllib.error.HTTPError) as refused:
                _request(address, path, document, 'POST')
            assert refused.value.code == code
        for path in (f'/api/videos/{entry["id"]}', '/api/videos/v-none/file'):
            with pytest.raises(urllib.error.HTTPError) as missing:
                _request(address, path)
            assert missing.value.code == 404
        # A page of another site cannot start an export.
        request = urllib.request.Request(
            address + '/api/matches/sample-5v5/video',
            data=b'{"start": 0, "end": 2}',
            headers={'Origin': 'http://example.com'},
            method='POST',
        )
        with pytest.raises(urllib.error.HTTPError) as foreign:
            urllib.request.urlopen(request, timeout=10)
        assert foreign.value.code == 403
        available.update(available=False, missing=['Video export needs ffmpeg, found none.'])
        with pytest.raises(urllib.error.HTTPError) as unavailable:
            _request(address, '/api/matches/sample-5v5/video', {'start': 0, 'end': 2}, 'POST')
        assert b'needs ffmpeg' in unavailable.value.read()
    finally:
        server.shutdown()
        server.server_close()


def _ffprobe():
    return shutil.which(os.environ.get('CUJU_FFPROBE') or 'ffprobe')


def _probe(output):
    probe = subprocess.run(
        [
            _ffprobe(),
            '-v',
            'error',
            '-count_frames',
            '-select_streams',
            'v:0',
            '-show_entries',
            'stream=nb_read_frames,width,height,r_frame_rate,codec_name',
            '-show_entries',
            'format=duration',
            '-of',
            'json',
            str(output),
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=True,
    )
    assert 'audio' not in probe.stdout
    return json.loads(probe.stdout)


def test_export_end_to_end(tmp_path, monkeypatch):
    """Draws two seconds of the 5 v 5 sample and checks the frames and length of each file."""
    try:
        missing = [] if _video.find_chrome() else ['Chrome, Edge or Chromium is missing']
    except _video.VideoError as error:
        missing = [str(error)]
    if not missing and _ffprobe() is None:
        missing = ['ffprobe is missing']
    if missing:
        if os.environ.get('CUJU_VIDEO_REQUIRED'):
            pytest.fail(' '.join(missing))
        pytest.skip(' '.join(missing))
    options = _video.Options(
        start=_video.Moment(8.0), end=_video.Moment(10.0), width=640, height=360, fps=15,
        quality='draft', sandbox=False, format='auto',
    ).check()  # fmt: skip
    host = _video._wait_host
    seen = {}

    def wait_host(client, options):
        seen.update(host(client, options))
        return seen

    monkeypatch.setattr(_video, '_wait_host', wait_host)
    reports = []
    result = _video.export(SAMPLE, tmp_path / 'two seconds.mp4', options, report=reports.append)
    output = Path(result['path'])
    assert result['frames'] == 30 and output.stat().st_size == result['bytes']
    assert result['encoder'] == 'browser'
    assert reports[0]['stage'] == 'starting' and reports[-1]['stage'] == 'done'
    assert output.suffix == ('.mp4' if seen['mp4'] else '.webm') == f'.{result["format"]}'
    codecs = {'mp4': {'h264'}, 'webm': {'vp9', 'vp8'}}
    found = _probe(output)
    stream = found['streams'][0]
    assert stream['codec_name'] in codecs[result['format']]
    assert (stream['width'], stream['height']) == (640, 360)
    assert (int(stream['nb_read_frames']), stream['r_frame_rate']) == (30, '15/1')
    assert float(found['format']['duration']) == pytest.approx(2.0, abs=0.05)
    # WebM, which every Chrome encodes.
    options.format = 'webm'
    webm = _video.export(SAMPLE, tmp_path / 'two seconds.webm', options)
    found = _probe(Path(webm['path']))
    assert found['streams'][0]['codec_name'] in codecs['webm']
    assert int(found['streams'][0]['nb_read_frames']) == 30
    # A browser without H.264 leaves an MP4 to ffmpeg, where it is installed.
    if _video.find_ffmpeg():
        monkeypatch.setattr(
            _video, '_wait_host', lambda client, options: {**host(client, options), 'mp4': None}
        )
        options.format = 'mp4'
        drawn = _video.export(SAMPLE, tmp_path / 'ffmpeg.mp4', options)
        assert drawn['encoder'] == 'ffmpeg'
        found = _probe(Path(drawn['path']))
        assert found['streams'][0]['codec_name'] == 'h264'
        assert int(found['streams'][0]['nb_read_frames']) == 30
    assert not list(tmp_path.glob('.*part*'))
