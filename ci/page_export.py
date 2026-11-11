# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks the video export that the page draws and encodes in the browser itself.

The checks open a recording in Watch, export one second of it from the Export video dialog and
read the file back, its container, its picture size, its frames and its length. A second export
refuses H.264, so the file falls back to WebM, a third one is cancelled, and a browser without a
video encoder hears in short what would make export work. ci/page_check.py runs export_checks
with the other checks of the page. Run alone, this file starts the mock server and Chrome itself.

Usage:
    python ci/page_export.py [--port 8790] [--debug-port 8791] [--chrome google-chrome]
"""

import argparse
import base64
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# The range of each export, in seconds, and its frame rate and size.
START, END, FPS, SIZE = 1.0, 2.0, 24, (854, 480)

WAIT = """
    const wait = async (test, ms = 30000) => {
        const end = performance.now() + ms;
        while (performance.now() < end) {
            let value = null;
            try {
                value = await test();
            } catch {
                value = null;
            }
            if (value) {
                return value;
            }
            await new Promise((resolve) => setTimeout(resolve, 100));
        }
        return null;
    };
"""

# Opens a recording of the library in Watch and the Export video dialog over it.
OPEN = """
    if (!(cuju.source && cuju.source.kind === 'match' && cuju.timeline)) {
        const list = await (await fetch('/api/matches')).json();
        const items = Array.isArray(list) ? list : list.items;
        cuju.openMatch(items[0].id);
        await wait(() => cuju.source && cuju.source.kind === 'match' && cuju.timeline, 60000);
    }
    cuju.showPage('watch');
    const d = document.querySelector('dialog.video-export');
    if (d.open) {
        d.close();
    }
    document.getElementById('video-export-btn').click();
    await wait(() => d.querySelector('.ve-actions'));
"""

# Sets the range, the size and the frame rate of the dialog and starts the export.
START_EXPORT = f"""
    d.querySelector('#ve-start').value = '{START}';
    d.querySelector('#ve-end').value = '{END}';
    const size = d.querySelector('#ve-size');
    size.value = '480p';
    size.dispatchEvent(new Event('change', {{ bubbles: true }}));
    d.querySelector('#ve-fps').value = '{FPS}';
    cuju.videoExport.exportButton.click();
"""

# Waits for the export to finish and returns the file as base64 with what the dialog shows.
FINISH = """
    const done = await wait(() => {
        const link = d.querySelector('.ve-actions a');
        const status = d.querySelector('.ve-status').textContent;
        return (link && !link.hidden) || /failed|cancelled/i.test(status) ? true : null;
    }, 240000);
    const link = d.querySelector('.ve-actions a');
    const result = cuju.videoExport.result;
    const out = {
        done: !!done,
        status: d.querySelector('.ve-status').textContent,
        download: link && !link.hidden ? link.getAttribute('download') : null,
        blobLink: !!(link && link.href.startsWith('blob:')),
        host: !!document.querySelector('.ve-drawing'),
    };
    if (result && link && !link.hidden) {
        const bytes = new Uint8Array(await result.blob.arrayBuffer());
        let text = '';
        for (let i = 0; i < bytes.length; i += 32768) {
            text += String.fromCharCode(...bytes.subarray(i, i + 32768));
        }
        out.file = btoa(text);
        out.container = result.container;
        out.codec = result.codec;
        out.type = result.blob.type;
    }
    return out;
"""


def _run(client, body):
    return client.evaluate(f'(async () => {{ {WAIT} {body} }})()')


def mp4_facts(data):
    """Returns the picture size, the frames and the seconds of an MP4 file of one video track."""

    def walk(start, end):
        at = start
        while at < end:
            size, kind = struct.unpack('>I4s', data[at : at + 8])
            head = 8
            if size == 1:
                size = struct.unpack('>Q', data[at + 8 : at + 16])[0]
                head = 16
            assert size >= head and at + size <= end, f'the box {kind} fits its parent'
            yield kind.decode('latin-1'), at, head, size
            at += size

    top = {kind: (at, head, size) for kind, at, head, size in walk(0, len(data))}
    assert list(top)[:3] == ['ftyp', 'moov', 'mdat'], list(top)

    def find(path):
        start, end = 0, len(data)
        found = None
        for name in path.split('/'):
            found = next(((a, h, s) for k, a, h, s in walk(start, end) if k == name), None)
            assert found, f'the file holds {path}'
            start, end = found[0] + found[1], found[0] + found[2]
        return found

    stbl = 'moov/trak/mdia/minf/stbl'
    stsd = find(f'{stbl}/stsd')
    entry = stsd[0] + stsd[1] + 8
    width, height = struct.unpack('>HH', data[entry + 32 : entry + 36])
    stsz = find(f'{stbl}/stsz')
    frames = struct.unpack('>I', data[stsz[0] + 16 : stsz[0] + 20])[0]
    mdhd = find('moov/trak/mdia/mdhd')
    scale, length = struct.unpack('>II', data[mdhd[0] + 20 : mdhd[0] + 28])
    return {
        'codec': data[entry + 4 : entry + 8].decode('latin-1'),
        'width': width,
        'height': height,
        'frames': frames,
        'seconds': length / scale,
    }


def _vint(data, at, marker):
    first = data[at]
    length = 1
    while length <= 8 and not first & (0x80 >> (length - 1)):
        length += 1
    value = first if marker else first & (0xFF >> length)
    for byte in data[at + 1 : at + length]:
        value = value << 8 | byte
    return value, length


def webm_facts(data):
    """Returns the picture size, the frames and the seconds of a WebM file of one video track."""
    masters = {0x18538067, 0x1654AE6B, 0xAE, 0xE0, 0x1F43B675, 0x1549A966}
    facts = {'frames': 0}

    def walk(start, end):
        at = start
        while at < end:
            ident, a = _vint(data, at, True)
            size, b = _vint(data, at + a, False)
            body = at + a + b
            assert body + size <= end, f'the element {ident:x} fits its parent'
            if ident in masters:
                walk(body, body + size)
            elif ident == 0xA3:
                facts['frames'] += 1
            elif ident in (0xB0, 0xBA):
                facts['width' if ident == 0xB0 else 'height'] = int.from_bytes(
                    data[body : body + size], 'big'
                )
            elif ident == 0x86:
                facts['codec'] = data[body : body + size].decode('latin-1')
            elif ident == 0x4489:
                facts['seconds'] = struct.unpack('>d', data[body : body + size])[0] / 1000
            at = body + size

    assert data[:4] == b'\x1a\x45\xdf\xa3', data[:4]
    walk(0, len(data))
    return facts


def _decoded_frames(data, suffix):
    """Returns the frames that ffprobe decodes from the file, or None without ffprobe."""
    probe = shutil.which('ffprobe')
    if not probe:
        return None
    with tempfile.TemporaryDirectory(prefix='cuju-export-') as folder:
        path = Path(folder) / f'video.{suffix}'
        path.write_bytes(data)
        result = subprocess.run(
            [
                probe,
                '-v',
                'error',
                '-count_frames',
                '-select_streams',
                'v:0',
                '-show_entries',
                'stream=nb_read_frames',
                '-of',
                'csv=p=0',
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    return int(result.stdout.strip()) if result.stdout.strip().isdigit() else result.stdout


def _check_file(result, container):
    """Checks one finished export, its file and what the dialog shows of it."""
    assert result['done'] and result.get('file'), result.get('status')
    assert result['blobLink'] and not result['host'], result
    data = base64.b64decode(result['file'])
    expected = round((END - START) * FPS)
    assert result['container'] == container, (result['container'], result['codec'])
    assert result['download'].endswith(f'.{container}'), result['download']
    facts = mp4_facts(data) if container == 'mp4' else webm_facts(data)
    assert (facts['width'], facts['height']) == SIZE, facts
    assert facts['frames'] == expected, facts
    assert abs(facts['seconds'] - expected / FPS) < 0.05, facts
    # One second of a small picture, larger than a few empty frames and far below a megabyte a
    # frame.
    assert 2000 < len(data) < expected * 1_000_000, len(data)
    decoded = _decoded_frames(data, container)
    assert decoded is None or decoded == expected, decoded
    return facts


def export_checks(client):
    """Checks the export of the browser, its fallback to WebM, its cancel and its explanation."""
    checks = 0
    result = _run(
        client,
        OPEN
        + """
        return {
            form: !!d.querySelector('#ve-start'),
            note: d.textContent.includes('draws and encodes the video itself'),
        };
    """,
    )
    assert result == {'form': True, 'note': True}, result
    checks += 1
    result = _run(client, OPEN + START_EXPORT + FINISH)
    mp4_or_webm = result.get('container')
    _check_file(result, mp4_or_webm or 'mp4')
    checks += 1
    # A browser without H.264 writes WebM.
    result = _run(
        client,
        """
        const real = VideoEncoder.isConfigSupported;
        VideoEncoder.isConfigSupported = (config) => (config.codec.startsWith('avc1')
            ? Promise.resolve({ supported: false }) : real.call(VideoEncoder, config));
        try {
        """
        + OPEN
        + START_EXPORT
        + FINISH
        + """
        } finally {
            VideoEncoder.isConfigSupported = real;
        }
    """,
    )
    _check_file(result, 'webm')
    checks += 1
    # Cancel stops the export and removes the page that draws.
    result = _run(
        client,
        OPEN
        + START_EXPORT
        + """
        await wait(() => document.querySelector('.ve-drawing'));
        const cancel = cuju.videoExport.cancelButton;
        const shown = !cancel.hidden;
        cancel.click();
        const status = await wait(() => {
            const text = d.querySelector('.ve-status').textContent;
            return /cancelled/.test(text) ? text : null;
        }, 60000);
        const host = !!document.querySelector('.ve-drawing');
        return { status, shown, host, job: !!cuju.videoExport.job };
    """,
    )
    assert result['status'] and result['shown'] and not result['host'] and not result['job'], result
    checks += 1
    # A browser without WebCodecs, against a server that offers no export, hears what would help.
    result = _run(
        client,
        """
        const real = window.VideoEncoder;
        delete window.VideoEncoder;
        try {
        """
        + OPEN
        + """
            return { form: !!d.querySelector('#ve-start'), text: d.textContent };
        } finally {
            window.VideoEncoder = real;
            document.querySelector('dialog.video-export').close();
        }
    """,
    )
    assert not result['form'], result
    assert 'video encoder' in result['text'] and 'Chrome, Edge or Firefox' in result['text'], result
    checks += 1
    return checks


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import page_check as page

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--port', type=int, default=8790)
    parser.add_argument('--debug-port', type=int, default=8791)
    parser.add_argument('--chrome', default='google-chrome')
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    processes = []
    client = None
    checks = 0
    try:
        with tempfile.TemporaryDirectory(
            prefix='cuju-page-export-', ignore_cleanup_errors=True
        ) as profile:
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(root / 'ci/mock_server.py'),
                        '--port',
                        str(options.port),
                        '--short',
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            page.wait_json(f'http://127.0.0.1:{options.port}/api/scenarios')
            processes.append(
                subprocess.Popen(
                    [
                        options.chrome,
                        '--headless=new',
                        '--mute-audio',
                        # The checks read the English page, whatever the language of the machine.
                        '--lang=en-US',
                        '--no-sandbox',
                        '--disable-background-networking',
                        '--proxy-server=http://127.0.0.1:9',
                        '--proxy-bypass-list=127.0.0.1',
                        '--no-first-run',
                        f'--remote-debugging-port={options.debug_port}',
                        f'--user-data-dir={profile}',
                        '--window-size=800,600',
                        'about:blank',
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env={**os.environ, 'XDG_CONFIG_HOME': profile, 'XDG_DATA_HOME': profile},
                )
            )
            debug = page.debugging_port(profile, options.debug_port)
            targets = page.wait_json(f'http://127.0.0.1:{debug}/json')
            target = next(item for item in targets if item['type'] == 'page')
            client = page.CDP(target['webSocketDebuggerUrl'])
            client.call('Runtime.enable')
            client.call('Page.enable')
            client.call(
                'Page.addScriptToEvaluateOnNewDocument',
                {
                    'source': """
                localStorage.setItem('cuju.muted', 'true');
                localStorage.setItem('cuju.quality', '"low"');
                localStorage.setItem('cuju.tips', '{"off": true}');
                Element.prototype.requestPointerLock = function () {
                    throw new Error('Pointer capture refused by the page check.');
                };
            """
                },
            )
            client.call('Page.navigate', {'url': f'http://127.0.0.1:{options.port}/'})
            for _ in range(150):
                if client.evaluate('!!(window.cuju && window.cuju.menus)'):
                    break
                time.sleep(0.2)
            checks = export_checks(client)
            assert not client.errors, client.errors
            print(f'PASS. {checks} video export checks.')
    except Exception as error:
        detail = json.dumps(client.errors)[:2000] if client else ''
        print(f'FAIL. {checks} checks passed. {error} {detail}', file=sys.stderr)
        return 1
    finally:
        if client:
            client.socket.close()
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    return 0


if __name__ == '__main__':
    sys.exit(main())
