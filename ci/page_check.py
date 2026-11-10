# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks renderer pages through Chrome and CDP against the local mock server.

Usage:
    python ci/page_check.py [--port 8790] [--debug-port 8791] [--chrome google-chrome]

Options:
    --port          The port of the mock server, by default `CUJU_PAGE_CHECK_PORT` or 8790.
    --debug-port    The port of Chrome's debugging connection, by default
                    `CUJU_PAGE_CHECK_DEBUG_PORT` or 8791. With 0, Chrome picks a free port.
    --chrome        The Chrome to drive, by default `google-chrome`.

Checks that run side by side give each its own pair of ports, so they never meet.
"""

import argparse
import base64
import contextlib
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import page_grid


class CDP:
    """A local CDP connection using the standard library."""

    def __init__(self, url):
        from urllib.parse import urlsplit

        address = urlsplit(url)
        self.socket = socket.create_connection((address.hostname, address.port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f'GET {address.path} HTTP/1.1\r\nHost: {address.netloc}\r\n'
            f'Upgrade: websocket\r\nConnection: Upgrade\r\n'
            f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n'
        )
        self.socket.sendall(request.encode())
        header = b''
        while not header.endswith(b'\r\n\r\n'):
            header += self.socket.recv(1)
        assert b'101' in header, header
        self.sequence = 0
        self.errors = []

    def read(self, size):
        data = b''
        while len(data) < size:
            chunk = self.socket.recv(size - len(data))
            if not chunk:
                raise RuntimeError('Chrome connection closed.')
            data += chunk
        return data

    def call(self, method, params=None):
        self.sequence += 1
        data = json.dumps({'id': self.sequence, 'method': method, 'params': params or {}}).encode()
        mask = os.urandom(4)
        size = len(data)
        header = (
            bytes([129, 128 | size]) if size < 126 else bytes([129, 254]) + struct.pack('!H', size)
        )
        self.socket.sendall(
            header + mask + bytes(value ^ mask[index % 4] for index, value in enumerate(data))
        )
        while True:
            first, second = self.read(2)
            size = second & 127
            if size == 126:
                size = struct.unpack('!H', self.read(2))[0]
            elif size == 127:
                size = struct.unpack('!Q', self.read(8))[0]
            payload = self.read(size)
            if first & 15 != 1:
                continue
            message = json.loads(payload)
            if message.get('method') == 'Runtime.exceptionThrown':
                self.errors.append(message['params'])
            if message.get('id') == self.sequence:
                if 'error' in message:
                    raise RuntimeError(message['error'])
                return message.get('result', {})

    def evaluate(self, expression):
        result = self.call(
            'Runtime.evaluate',
            {
                'expression': expression,
                'returnByValue': True,
                'awaitPromise': True,
            },
        )
        if 'exceptionDetails' in result:
            raise RuntimeError(result['exceptionDetails'])
        return result.get('result', {}).get('value')


def wait_json(url):
    for _ in range(150):
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                return json.load(response)
        except (OSError, ValueError):
            time.sleep(0.2)
    raise RuntimeError(f'Server startup failed at {url}')


def debugging_port(profile, port):
    """Returns the debugging port, or for 0 the port that Chrome chose and wrote to its profile."""
    if port:
        return port
    path = Path(profile) / 'DevToolsActivePort'
    for _ in range(150):
        with contextlib.suppress(OSError, ValueError, IndexError):
            return int(path.read_text().splitlines()[0])
        time.sleep(0.2)
    raise RuntimeError('Chrome startup failed.')


# The SHA-256 of the frames of the shipped sample of five a side as version 1 stores them.
SAMPLE_5V5_DIGEST = 'b41e32efb5decbece8ea3a1ab949e2f1e62c8052e4929f7a1f429a938e6b0d27'


def format_checks(client):
    """Checks that the page reads a recording of version 2 as the frames of version 1."""
    result = client.evaluate("""
        (async () => {
            const format = await import('./js/recording/format.js');
            const { gunzip, parseHeader, parseRecording, readSections } = format;
            const { decodeFrames } = await import('./js/recording/codec.js');
            const response = await fetch('/api/mock/samples/sample-5v5');
            const bytes = new Uint8Array(await response.arrayBuffer());
            const started = performance.now();
            const recording = await parseRecording(bytes);
            const seconds = (performance.now() - started) / 1000;
            const plain = await gunzip(bytes);
            const { header, offset } = parseHeader(plain);
            const raw = decodeFrames(readSections(plain, offset).get('FRMS'), header.players.length,
                header.frame_count, header.keyframe_interval);
            const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', raw)),
                (b) => b.toString(16).padStart(2, '0')).join('');
            await cuju.openFile(new File([bytes], 'sample-5v5.cjr'));
            const opened = cuju.source.store.size;
            cuju.act('pause');
            const { version } = recording.header;
            return { version, frames: recording.frames.length, digest, opened, seconds };
        })()
    """)
    assert result['version'] == 2 and result['frames'] == result['opened'] == 3002, result
    assert result['digest'] == SAMPLE_5V5_DIGEST, result
    print(f'A sample of version 2 parses in {result["seconds"]:.2f} s in Chrome.', flush=True)
    return 1


def annotation_checks(client):
    """Checks the overlay of annotations, hidden without them, its labels, lines and panel."""
    result = client.evaluate("""
        (async () => {
            const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            const settle = async (test) => {
                for (let i = 0; i < 60 && !test(); i++) {
                    await wait(50);
                }
                return test();
            };
            const open = async (bytes, name) => {
                await cuju.openFile(new File([bytes], name));
                cuju.director.stop(true);
                if (cuju.postMatch.running) cuju.postMatch.end({ home: false });
                cuju.timeline.seek(cuju.timeline.first + 50);
                cuju.timeline.pause();
                cuju.setCamera('tactical');
                cuju.cameras.jump();
            };
            const { gunzip } = await import('./js/recording/format.js');
            const response = await fetch('/api/mock/samples/sample-5v5');
            const plain = await gunzip(new Uint8Array(await response.arrayBuffer()));
            const button = document.getElementById('annotations-button');
            const layer = document.querySelector('.annotation-labels');
            const paths = () => document.querySelectorAll('.timeline-series path').length;
            await open(plain, 'plain.cjr');
            await wait(300);
            const off = button.hidden && layer.hidden && paths() === 0;
            const records = [];
            for (let f = 0; f < 3002; f++) {
                for (let p = 0; p < 10; p++) {
                    records.push({ f, p, v: { value: Math.sin(f / 50 + p) }, a: 12,
                        k: [[12, 0.6], [11, 0.3], [0, 0.1]] });
                }
                records.push({ f, v: { pressure: f / 3002 }, t: `minute ${Math.floor(f / 600)}` });
            }
            const json = new TextEncoder().encode(JSON.stringify({ records }));
            const padding = (4 - (json.length % 4)) % 4;
            const bytes = new Uint8Array(plain.length + 8 + json.length + padding);
            bytes.set(plain);
            bytes.set(new TextEncoder().encode('ANNO'), plain.length);
            new DataView(bytes.buffer).setUint32(plain.length + 4, json.length, true);
            bytes.set(json, plain.length + 8);
            await open(bytes, 'annotated.cjr');
            const labelled = await settle(() => layer.querySelector('span'));
            const label = labelled ? labelled.textContent : '';
            const shown = !button.hidden && label.includes('value')
                && label.includes('Shot chosen');
            const box = document.querySelector('.annotation-match');
            const match = !box.hidden && box.textContent.includes('minute 0');
            const line = await settle(() => paths() === 1);
            button.click();
            const panel = document.getElementById('annotations-panel');
            const opened = panel.classList.contains('open')
                && button.getAttribute('aria-expanded') === 'true';
            const boxes = [...panel.querySelectorAll('[data-series]')];
            const listed = boxes.length === 11 && boxes[0].checked;
            boxes[1].click();
            const two = await settle(() => paths() === 2);
            boxes[0].click();
            boxes[1].click();
            const none = await settle(() => paths() === 0);
            const toggles = ['annotation-players', 'annotation-actions', 'annotation-text'];
            for (const id of toggles) {
                document.getElementById(id).click();
            }
            const quiet = await settle(() => layer.hidden && box.hidden);
            for (const id of toggles) {
                document.getElementById(id).click();
            }
            panel.querySelector('input').focus();
            panel.querySelector('input').dispatchEvent(
                new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            const closed = !panel.classList.contains('open') && document.activeElement === button;
            await open(plain, 'plain.cjr');
            const hidden = await settle(() => button.hidden && layer.hidden && paths() === 0);
            return { off, shown, match, line, opened, listed, two, none, quiet, closed, hidden };
        })()
    """)
    assert all(result.values()), f'Annotations {result}'
    return 1


def library_checks(client):
    """Checks the Trash, the details of a recording, duplicated teams and request pages."""
    result = client.evaluate("""
        (async () => {
            const { api } = await import('./js/core/api.js');
            const [entry] = await api.matches();
            const id = entry.id;
            const details = await api.matchDetails(id);
            await api.patchMatch(id, { tags: ['final'], favorite: true, notes: 'Goal' });
            await api.deleteMatch(id);
            const trashed = (await api.trash()).some((item) => item.id === id)
                && !(await api.matches()).some((item) => item.id === id);
            const missing = (err) => err.status === 404;
            const hidden = await api.matchDetails(id).then(() => false, missing);
            cuju.showPage('recordings');
            cuju.recordings.trash = true;
            await cuju.recordings.refresh();
            const listed = cuju.recordings.list.some((item) => item.id === id);
            const restored = await api.restoreMatch(id);
            const kept = restored.id === id && restored.tags.join() === 'final' && restored.favorite
                && restored.notes === 'Goal' && !('deleted_at' in restored);
            cuju.recordings.trash = false;
            await cuju.recordings.refresh();
            const back = cuju.recordings.list.some((item) => item.id === id)
                && (await api.trash()).length === 0;
            const source = 'def agent(obs):\\n    return [0]\\n';
            const team = await api.uploadTeam('Twin', 'main.py', source, '11v11');
            const copy = await api.duplicateTeam(team.id);
            const twins = copy.id !== team.id && copy.name === 'Twin copy'
                && copy.format === team.format;
            const builtin = await api.duplicateTeam('builtin').then(() => false,
                (err) => err.status === 400);
            await api.deleteTeam(copy.id);
            await api.deleteTeam(team.id);
            await cuju.library.refresh();
            const all = { details: details.id === id, trashed, hidden, listed, kept, back, twins,
                builtin };
            return Object.values(all).every(Boolean) || JSON.stringify(all);
        })()
    """)
    assert result is True, f'Trash, details and duplicate {result}'
    result = client.evaluate("""
        (async () => {
            const { REQUEST_PAGE } = await import('./js/pages/matches.js');
            const page = cuju.matches;
            cuju.showPage('matches');
            for (let i = 0; i < 100 && !page.built; i++) {
                await new Promise((resolve) => setTimeout(resolve, 50));
            }
            const saved = page.requests;
            const now = Date.now() / 1000;
            page.requests = Array.from({ length: REQUEST_PAGE + 10 }, (_, k) => ({
                id: `r-20261109-120000-${String(k).padStart(4, '0')}`, left: 'builtin',
                right: 'builtin', scenario: '5_vs_5', seed: k, ability: [null, null],
                state: 'done', progress: 1, match: null, error: null, created: now - k,
                started: now - k, finished: now - k,
            }));
            page.limit = REQUEST_PAGE;
            page.renderQueue();
            const cards = () => page.queueHost.querySelectorAll('.req-card').length;
            const first = cards();
            const button = page.queueHost.querySelector('.req-more');
            const label = button && button.textContent;
            button.focus();
            button.click();
            const all = cards();
            const gone = !page.queueHost.querySelector('.req-more');
            const focused = page.queueHost.contains(document.activeElement);
            page.requests = saved;
            page.limit = REQUEST_PAGE;
            page.renderQueue();
            const result = { first: first === REQUEST_PAGE, label: label === 'Show 10 more of 10',
                all: all === REQUEST_PAGE + 10, gone, focused };
            return Object.values(result).every(Boolean) || JSON.stringify(result);
        })()
    """)
    assert result is True, f'Requested matches page by page {result}'
    return 2


def tournament_checks(client):
    """Checks the tournament wizard, its refusal of an impossible setup, the bracket and tables."""
    result = client.evaluate("""
        (async () => {
            const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            const until = async (test, ms = 8000) => {
                for (let t = 0; t < ms; t += 50) {
                    if (test()) {
                        return true;
                    }
                    await wait(50);
                }
                return false;
            };
            const page = cuju.tournaments;
            document.querySelector('[data-page="tournaments"]').click();
            await until(() => page.built);
            const main = () => page.mainHost;
            const button = (text) => [...main().querySelectorAll('button')]
                .find((b) => b.textContent.trim() === text);
            page.root.querySelector('.cup-side-head button').click();
            const tabs = [...main().querySelectorAll('[role="tab"]')].map((t) => t.textContent);
            const steps = tabs.length === 5 && tabs[0].endsWith('Format');
            await until(() => main().querySelector('[data-preset="world_cup"]'));
            main().querySelector('[data-preset="world_cup"]').click();
            const picked = main().querySelector('[data-preset="world_cup"]')
                .getAttribute('aria-checked') === 'true';
            // The arrow keys move between the steps of the wizard.
            const first = document.getElementById('cup-step-0');
            first.focus();
            first.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
            const keys = page.step === 1 && document.activeElement.id === 'cup-step-1';
            button('Add built-in AI').click();
            page.goStep(4);
            const refused = await until(() => main().querySelector('.cup-review [role="alert"]'));
            const reason = refused && /entrants/.test(
                main().querySelector('.cup-review [role="alert"]').textContent);
            page.goStep(1);
            button('Add four of rising ability').click();
            button('Add four of rising ability').click();
            button('Add four of rising ability').click();
            const entrants = main().querySelectorAll('.cup-entrants > li').length === 13;
            page.goStep(3);
            const stages = main().querySelectorAll('.cup-stage').length === 2;
            page.goStep(4);
            const reviewed = await until(
                () => main().querySelectorAll('.cup-review-stage').length === 2);
            const groups = main().querySelectorAll('.cup-review-groups h4').length === 3;
            main().querySelector('.cup-start').click();
            const opened = await until(() => page.mode === 'view' && page.current
                && document.getElementById('cup-tab-0'));
            const listed = page.root.querySelectorAll('.cup-item').length === 1;
            const done = await until(() => page.current && page.current.state === 'done', 20000);
            const tab = document.getElementById('cup-tab-0');
            tab.click();
            const rows = main().querySelectorAll('.cup-table tbody tr').length === 13;
            const tab0 = document.getElementById('cup-tab-0');
            tab0.focus();
            tab0.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
            const bracket = await until(() => main().querySelector('.cup-bracket .cup-fixture'));
            const cells = main().querySelectorAll('.cup-bracket-cell').length >= 7;
            const third = [...main().querySelectorAll('.cup-bracket-section h3')]
                .some((h) => h.textContent === 'Third place');
            const watch = !!main().querySelector('.cup-watch button');
            const champion = /Champion, /.test(main().querySelector('.cup-champion').textContent);
            const text = page.root.textContent;
            const names = !/_vs_|academy_|11_vs|5_vs/.test(text);
            const all = { steps, picked, keys, refused: !!refused, reason, entrants, stages,
                reviewed, groups, opened: !!opened, rows, listed, done, bracket: !!bracket, cells,
                third, watch, champion, names };
            return Object.values(all).every(Boolean) || JSON.stringify(all);
        })()
    """)
    assert result is True, f'Tournament wizard, tables and bracket {result}'
    result = client.evaluate("""
        (async () => {
            const page = cuju.tournaments;
            page.current.config.stages.length;
            page.mainHost.querySelector('.cup-actions .btn.primary').click();
            for (let t = 0; t < 8000 && !cuju.podium.showing; t += 50) {
                await new Promise((resolve) => setTimeout(resolve, 50));
            }
            const shown = cuju.podium.showing && cuju.page === 'watch';
            const title = document.querySelector('#victory .victory-title').textContent;
            const named = title.startsWith(page.current.champion);
            const locked = !!document.pointerLockElement;
            cuju.postMatch.end();
            cuju.showPage('tournaments');
            return (shown && named && !locked) || JSON.stringify({ shown, title, locked });
        })()
    """)
    assert result is True, f'Trophy ceremony {result}'
    return 2


def reconnection_checks(client):
    """Checks that a live stream reconnects after a drop, marks the gap and tells the end."""
    # Each stage waits in its own call, within the time that a call to Chrome may take.
    wait = """
        window.pageCheckWait = async (test) => {
            const end = performance.now() + 12000;
            while (!test() && performance.now() < end) {
                await new Promise((resolve) => setTimeout(resolve, 50));
            }
            return test();
        };
        window.pageCheckLive = () => cuju.source?.kind === 'live' ? cuju.source.live : null;
    """
    result = client.evaluate(
        wait
        + """
        (async () => {
            const { api } = await import('./js/core/api.js');
            const [source] = await api.live();
            // A stream of an earlier check may still be the source until the new one connects.
            const before = pageCheckLive();
            cuju.openLive(source.id);
            const ready = await pageCheckWait(() => pageCheckLive() !== before
                && pageCheckLive()?.state === 'connected' && pageCheckLive().lastSequence > 0);
            if (!ready) return 'no live stream';
            const stream = pageCheckLive();
            window.pageCheckStream = stream;
            window.pageCheckStates = [];
            const hear = stream.callbacks.onState;
            stream.callbacks.onState = (state) => {
                pageCheckStates.push(state);
                hear?.(state);
            };
            const answer = await fetch(`/api/mock/live/${source.id}/drop`, { method: 'POST' });
            return answer.status === 204 || `drop answered ${answer.status}`;
        })()
    """
    )
    assert result is True, f'Live stream before a drop {result}'
    result = client.evaluate("""
        (async () => {
            const stream = pageCheckStream;
            const resumed = await pageCheckWait(() => pageCheckStates.includes('reconnecting')
                && stream.state === 'connected' && stream.gaps > 0);
            const store = stream.store;
            let marked = 0;
            let repeated = false;
            for (let i = store.first + 1; i <= store.last; i++) {
                marked += store.get(i).gap ? 1 : 0;
                repeated ||= store.get(i).sequence <= store.get(i - 1).sequence;
            }
            const all = { resumed, gaps: stream.gaps === 10, marked: marked === 1,
                once: !repeated };
            return Object.values(all).every(Boolean)
                || JSON.stringify({ ...all, states: pageCheckStates, count: stream.gaps });
        })()
    """)
    assert result is True, f'Live reconnection {result}'
    result = client.evaluate("""
        (async () => {
            const stream = pageCheckStream;
            const answer = await fetch(`/api/mock/live/${stream.id}/end`, { method: 'POST' });
            // The source leaves the list before its stream ends, so the page keeps the stream.
            const ended = await pageCheckWait(() => stream.state === 'ended' && stream.ended);
            await new Promise((resolve) => setTimeout(resolve, 500));
            const answered = answer.status === 204;
            const all = { answered, ended, same: pageCheckLive() === stream };
            stream.stop();
            return Object.values(all).every(Boolean) || JSON.stringify(all);
        })()
    """)
    assert result is True, f'Live stream end {result}'
    return 2


def press(client, key, code, modifiers=0, text=None):
    """Presses and releases one key, with the CDP modifier bits, 2 for Ctrl and 8 for Shift."""
    for kind in ('keyDown', 'keyUp'):
        event = {'type': kind, 'key': key, 'code': code, 'modifiers': modifiers}
        if text and kind == 'keyDown':
            event['text'] = text
        client.call('Input.dispatchKeyEvent', event)


def palette_checks(client):
    """Checks that the command palette opens, searches, runs an action and gives focus back."""
    client.evaluate("""
        cuju.showPage('recordings');
        document.getElementById('open-settings').focus();
    """)
    press(client, 'k', 'KeyK', 2)
    result = client.evaluate("""
        ({
            open: !cuju.palette.root.hidden,
            focus: document.activeElement === cuju.palette.input,
            modal: cuju.palette.root.getAttribute('role') === 'dialog',
            listed: cuju.palette.list.children.length > 10,
        })
    """)
    assert all(result.values()), f'Ctrl K opens the palette {result}'
    client.call('Input.insertText', {'text': 'go teams'})
    result = client.evaluate("""
        (() => {
            const first = cuju.palette.list.querySelector('[aria-selected="true"]');
            return first && first.textContent.startsWith('Go to Teams')
                && cuju.palette.input.getAttribute('aria-activedescendant') === first.id;
        })()
    """)
    assert result, 'The palette finds a page'
    press(client, 'Enter', 'Enter')
    result = client.evaluate("""
        ({ page: cuju.page, closed: cuju.palette.root.hidden,
           focus: document.activeElement && document.activeElement.id })
    """)
    assert result['page'] == 'teams' and result['closed'], f'Enter runs the action {result}'
    client.evaluate("document.getElementById('open-settings').focus()")
    press(client, 'k', 'KeyK', 2)
    press(client, 'ArrowDown', 'ArrowDown')
    moved = client.evaluate(
        "cuju.palette.input.getAttribute('aria-activedescendant') === 'palette-item-1'"
    )
    press(client, 'Escape', 'Escape')
    result = client.evaluate("""
        ({ closed: cuju.palette.root.hidden, page: cuju.page,
           focus: document.activeElement === document.getElementById('open-settings') })
    """)
    assert moved and all([result['closed'], result['focus']]), f'Esc gives focus back {result}'
    assert result['page'] == 'teams', 'Esc runs nothing'
    # A text field keeps its keys, Ctrl K among them.
    client.evaluate("""
        cuju.showPage('watch');
        document.getElementById('address-input').focus();
    """)
    press(client, 'k', 'KeyK', 2)
    assert client.evaluate('cuju.palette.root.hidden'), 'A text field keeps Ctrl K'
    # The button of the top bar opens it too, and a settings action applies at once.
    result = client.evaluate("""
        (async () => {
            document.getElementById('address-input').blur();
            document.getElementById('open-palette').click();
            const opened = !cuju.palette.root.hidden;
            cuju.palette.input.value = 'light theme';
            cuju.palette.render();
            cuju.palette.run(cuju.palette.active);
            const light = document.documentElement.dataset.theme === 'light';
            cuju.palette.open('theme follows');
            cuju.palette.run(cuju.palette.active);
            return { opened, light, system: !document.documentElement.dataset.theme,
                     closed: cuju.palette.root.hidden };
        })()
    """)
    assert all(result.values()), f'The top bar button and a settings action {result}'
    return 4


def presets_checks(client):
    """Checks that the presets of the settings switch every part and that Custom comes back."""
    result = client.evaluate("""
        (() => {
            const $ = (id) => document.getElementById(id);
            const boxes = ['lineups-on', 'celebrations-on', 'replays', 'decision-replays',
                'restart-transitions', 'podium-on'];
            const preset = (name) => document.querySelector(`#presets [data-preset="${name}"]`);
            const chosen = () => document.querySelector('#presets [aria-checked="true"]')
                .dataset.preset;
            const on = () => boxes.map((id) => $(id).checked);
            const start = chosen();
            // One change of the defaults makes a mix of the person's own.
            $('replays').click();
            const custom = chosen() === 'custom' && cuju.settings.replays === false;
            preset('quick').click();
            const quick = chosen() === 'quick' && on().every((value) => !value)
                && !cuju.settings.podium && !cuju.settings.lineups
                && localStorage.getItem('cuju.replays') === 'false';
            preset('broadcast').click();
            const broadcast = chosen() === 'broadcast' && on().every(Boolean)
                && cuju.settings.replays && cuju.settings.transitions;
            preset('custom').click();
            const back = chosen() === 'custom' && !$('replays').checked && !cuju.settings.replays
                && on().filter(Boolean).length === 5;
            $('replays').click();
            return { start: start === 'broadcast', custom, quick, broadcast, back,
                     end: chosen() === 'broadcast' && cuju.settings.replays };
        })()
    """)
    assert all(result.values()), f'Presets round trip {result}'
    return 1


def first_run_checks(client):
    """Checks the empty states, the tips and their dismissal, and the help of the controls."""
    result = client.evaluate("""
        (async () => {
            const wait = async (test) => {
                for (let i = 0; i < 100 && !test(); i++) {
                    await new Promise((resolve) => setTimeout(resolve, 50));
                }
                return test();
            };
            // Recordings without a recording point to the samples and to the recorder.
            const page = cuju.recordings;
            cuju.showPage('recordings');
            const kept = page.list;
            page.list = [];
            page.render();
            const empty = document.querySelector('#page-recordings .empty-state');
            const recordings = !!empty && empty.textContent.includes('cuju render sample')
                && empty.textContent.includes('cuju.render.Recorder');
            page.list = kept;
            page.render();
            // Teams with the built-in AI alone points to the topic of the Help page.
            cuju.showPage('teams');
            await cuju.library.refresh();
            const own = cuju.library.teams.some((team) => team.kind !== 'builtin');
            const first = document.querySelector('#page-teams .teams-first');
            let teams = own === !first;
            if (first) {
                first.querySelector('button').click();
                teams = teams && cuju.page === 'help'
                    && document.activeElement === document.getElementById('help-teams');
            }
            // The empty Watch page offers a sample match, which opens at once.
            cuju.showPage('watch');
            const next = document.querySelector('#watch-empty .watch-next button');
            next.click();
            const watch = await wait(() => cuju.source && cuju.source.kind === 'match');
            // A tip shows on Home once tips are on, and Got it keeps it away.
            const box = document.getElementById('tips-on');
            const off = !box.checked && JSON.parse(localStorage.getItem('cuju.tips')).off;
            box.click();
            cuju.showPage('home');
            const tip = document.getElementById('tip');
            const shown = await wait(() => !tip.hidden && tip.textContent.includes('Ctrl K'));
            tip.querySelector('button').click();
            const dismissed = tip.hidden
                && JSON.parse(localStorage.getItem('cuju.tips')).dismissed.includes('home');
            cuju.showPage('field');
            const field = await wait(() => !tip.hidden && tip.textContent.includes('preset'));
            box.click();
            const gone = tip.hidden && JSON.parse(localStorage.getItem('cuju.tips')).off === true;
            // The help of a control shows on keyboard focus and leaves with it.
            const button = document.getElementById('open-palette');
            button.focus({ focusVisible: true });
            const help = document.getElementById('help-tip');
            const helped = !help.hidden && help.textContent.includes('Ctrl K')
                && button.getAttribute('aria-describedby') === 'help-tip';
            button.blur();
            const left = help.hidden && !button.hasAttribute('aria-describedby');
            return { recordings, teams, watch, off, shown, dismissed, field, gone, helped, left };
        })()
    """)
    assert all(result.values()), f'First run {result}'
    return 3


def touch(client, kind, points=()):
    """Sends one touch event, with each point as an id and the x and y of the window."""
    client.call(
        'Input.dispatchTouchEvent',
        {'type': kind, 'touchPoints': [{'id': i, 'x': x, 'y': y} for i, x, y in points]},
    )


def touch_checks(client):
    """Checks the touch pad of Play with several fingers, and swipes and taps on the timeline."""
    client.call('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 5})
    try:
        result = client.evaluate("""
            (async () => {
                const { api } = await import('./js/core/api.js');
                const sources = await api.live();
                window.pageCheckApi = Object.fromEntries(
                    ['startGame', 'gameStream', 'pauseGame', 'gameInput', 'quitGame', 'game']
                        .map((name) => [name, api[name]]));
                let entry = { id: sources[0].id, state: 'playing', score: [0, 0] };
                window.pageCheckInputs = [];
                api.startGame = async () => entry;
                api.gameStream = (id, signal) => api.liveStream(id, signal);
                api.pauseGame = async (id, paused) => {
                    entry = { ...entry, state: paused ? 'paused' : 'playing' };
                    return entry;
                };
                api.gameInput = async (id, input) => {
                    pageCheckInputs.push(input);
                    return entry;
                };
                api.game = async () => entry;
                api.quitGame = async () => {
                    entry = { ...entry, state: 'ended', ending: 'quit' };
                    return entry;
                };
                cuju.showPage('play');
                await new Promise((resolve) => setTimeout(resolve, 100));
                await cuju.play.start();
                for (let i = 0; i < 100 && !cuju.play.game.started; i++) {
                    await new Promise((resolve) => setTimeout(resolve, 100));
                }
                const pad = cuju.touch.pad;
                const status = cuju.play.status.getBoundingClientRect();
                return {
                    started: cuju.play.game.started, hiddenBefore: !!pad && pad.hidden,
                    status: [status.left + 4, status.top + 4],
                };
            })()
        """)
        assert result['started'] and result['hiddenBefore'], f'Touch pad before a touch {result}'
        # The first touch shows the pad.
        touch(client, 'touchStart', [(0, *result['status'])])
        touch(client, 'touchEnd')
        shown = client.evaluate("""
            (async () => {
                for (let i = 0; i < 40 && cuju.touch.pad.hidden; i++) {
                    await new Promise((resolve) => setTimeout(resolve, 50));
                }
                return !cuju.touch.pad.hidden
                    && document.getElementById('app').classList.contains('touch');
            })()
        """)
        assert shown, 'A touch shows the pad'
        result = client.evaluate("""
            (() => {
                const stick = cuju.touch.stick.getBoundingClientRect();
                const shot = cuju.touch.pad.querySelector('[data-action="shot"]')
                    .getBoundingClientRect();
                return {
                    stick: [stick.left + stick.width / 2, stick.top + stick.height / 2,
                        stick.width / 2],
                    shot: [shot.left + shot.width / 2, shot.top + shot.height / 2],
                };
            })()
        """)
        x, y, radius = result['stick']
        # The stick is round, so its fingers press inside the circle.
        radius *= 0.8
        held = """
            (async () => {
                await new Promise((resolve) => setTimeout(resolve, 60));
                const last = pageCheckInputs.at(-1);
                return last ? last.held : null;
            })()
        """
        touch(client, 'touchStart', [(0, x + radius, y)])
        right = client.evaluate(held)
        touch(client, 'touchStart', [(0, x + radius, y), (1, *result['shot'])])
        both = client.evaluate(held)
        touch(client, 'touchMove', [(0, x + radius, y - radius), (1, *result['shot'])])
        diagonal = client.evaluate(held)
        touch(client, 'touchEnd')
        released = client.evaluate(held)
        result = {
            'right': right == ['right'],
            'both': sorted(both or []) == ['right', 'shot'],
            'diagonal': sorted(diagonal or []) == ['right', 'shot', 'up'],
            'released': released == [],
        }
        assert all(result.values()), f'Touch pad fingers {result} {both} {diagonal}'
        result = client.evaluate("""
            (async () => {
                const play = cuju.play;
                const device = play.activeOf(0);
                cuju.touch.pause.click();
                await new Promise((resolve) => setTimeout(resolve, 300));
                const paused = !play.menu.hidden && cuju.touch.pad.hidden;
                await play.quit();
                for (let i = 0; i < 40 && play.game && !play.game.ended; i++) {
                    await new Promise((resolve) => setTimeout(resolve, 50));
                }
                if (play.game?.source) play.game.source.live.stop();
                const { api } = await import('./js/core/api.js');
                Object.assign(api, pageCheckApi);
                play.showSetup();
                // The setting hides the pad, and Never stays in the browser.
                const select = document.getElementById('touch-controls');
                select.value = 'off';
                select.dispatchEvent(new Event('change'));
                const never = localStorage.getItem('cuju.touchControls') === '"off"';
                select.value = 'auto';
                select.dispatchEvent(new Event('change'));
                return {
                    device: device === cuju.touch.device && device.label === 'Touch screen',
                    paused, never,
                };
            })()
        """)
        assert all(result.values()), f'Touch pad pause and setting {result}'
        result = client.evaluate("""
            (async () => {
                const { api } = await import('./js/core/api.js');
                const entries = await api.matches();
                cuju.showPage('watch');
                await cuju.openMatch(entries[0].id);
                cuju.director.stop(true);
                if (cuju.postMatch.running) cuju.postMatch.end({ home: false });
                const tl = cuju.timeline;
                tl.pause();
                tl.seek(tl.first + (tl.last - tl.first) / 2);
                const r = document.getElementById('timeline').getBoundingClientRect();
                return {
                    left: r.left, width: r.width, y: r.top + r.height / 2, from: tl.t,
                    first: tl.first, last: tl.last, height: r.height,
                };
            })()
        """)
        start = result['left'] + result['width'] / 2
        touch(client, 'touchStart', [(0, start, result['y'])])
        for step in range(1, 6):
            touch(client, 'touchMove', [(0, start + step * result['width'] * 0.04, result['y'])])
        touch(client, 'touchEnd')
        span = result['last'] - result['first']
        swiped = client.evaluate('cuju.timeline.t')
        expected = result['from'] + 0.2 * span
        tap = result['left'] + result['width'] * 0.25
        touch(client, 'touchStart', [(0, tap, result['y'])])
        touch(client, 'touchEnd')
        tapped = client.evaluate('cuju.timeline.t')
        assert abs(swiped - expected) <= span * 0.02 + 1, f'Timeline swipe {swiped} {expected}'
        assert abs(tapped - (result['first'] + 0.25 * span)) <= span * 0.02 + 1, 'Timeline tap'
        assert result['height'] >= 36, f'Timeline height on a touch screen {result}'
    finally:
        client.call('Emulation.setTouchEmulationEnabled', {'enabled': False})
        client.evaluate("""
            cuju.touch.touched = false;
            cuju.touch.update();
        """)
    return 4


def loading_checks(client, port):
    """Checks decoding in a worker, the progress of loading and opening a match by its address."""
    result = client.evaluate("""
        (async () => {
            const { api } = await import('./js/core/api.js');
            const decode = await import('./js/recording/decode.js');
            const [entry] = await api.matches();
            const bytes = await api.matchBytes(entry.id);
            const inWorker = await decode.decodeRecording(bytes);
            const worker = decode.lastDecoder;
            const onPage = await decode.decodeRecording(bytes, { makeWorker: null });
            const page = decode.lastDecoder;
            const sum = (rec) => rec.frames.reduce((total, frame) => total
                + frame.data.reduce((a, b) => a + b, 0) + frame.step + frame.actions.length, 0);
            const same = JSON.stringify(inWorker.header) === JSON.stringify(onPage.header)
                && inWorker.frames.length === onPage.frames.length
                && sum(inWorker) === sum(onPage);
            const all = { worker: worker === 'worker', page: page === 'page', same };
            return Object.values(all).every(Boolean) || JSON.stringify(all);
        })()
    """)
    assert result is True, f'Recordings decode in a worker {result}'
    result = client.evaluate("""
        (async () => {
            const saved = cuju.assetsReady;
            const savedShare = cuju.assetProgress;
            let finish;
            cuju.assetsReady = new Promise((resolve) => { finish = resolve; });
            cuju.assetProgress = 0.5;
            const waiting = cuju.waitForAssets(cuju.loadToken);
            await new Promise((resolve) => setTimeout(resolve, 150));
            const box = document.getElementById('loading');
            const shown = !box.hidden
                && document.getElementById('loading-text').textContent
                    === 'Loading the players and the stadium'
                && document.getElementById('loading-bar').style.width === '50%';
            finish();
            const goes = await waiting;
            cuju.assetsReady = saved;
            cuju.assetProgress = savedShare;
            cuju.hideLoading();
            // A muted page fetches no sound file, and Home asks for the montage's poster.
            cuju.showPage('home');
            for (let i = 0; i < 100 && !cuju.home; i++) {
                await new Promise((resolve) => setTimeout(resolve, 50));
            }
            cuju.home?.show();
            const sounds = performance.getEntriesByType('resource')
                .some((item) => item.name.includes('/assets/sounds/'));
            const poster = document.querySelector('.home-reel-video')?.getAttribute('poster');
            const all = {
                shown, goes, silent: !sounds, poster: poster === 'assets/promo-poster.jpg',
            };
            return Object.values(all).every(Boolean) || JSON.stringify(all);
        })()
    """)
    assert result is True, f'Loading progress and lazy files {result}'
    identifier = client.evaluate("""
        (async () => (await (await import('./js/core/api.js')).api.matches())[0].id)()
    """)
    client.call(
        'Page.navigate',
        {'url': f'http://127.0.0.1:{port}/index.html#match={identifier}'},
    )
    opened = None
    for _ in range(300):
        with contextlib.suppress(RuntimeError):
            opened = client.evaluate(f"""
                (async () => {{
                    const wanted = {json.dumps(identifier)};
                    if (!window.cuju || !cuju.source || cuju.source.id !== wanted) {{
                        return null;
                    }}
                    const decode = await import('./js/recording/decode.js');
                    return {{ page: cuju.page, decoder: decode.lastDecoder,
                        loading: !document.getElementById('loading').hidden,
                        players: !!cuju.players, frames: cuju.source.store.size }};
                }})()
            """)
        if opened and not opened['loading']:
            break
        time.sleep(0.2)
    assert opened and opened['page'] == 'watch' and opened['decoder'] == 'worker', opened
    assert opened['players'] and opened['frames'] > 0, opened
    return 3


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        '--port',
        type=int,
        default=int(os.environ.get('CUJU_PAGE_CHECK_PORT') or 8790),
        help='the port of the mock server',
    )
    parser.add_argument(
        '--debug-port',
        type=int,
        default=int(os.environ.get('CUJU_PAGE_CHECK_DEBUG_PORT') or 8791),
        help="the port of Chrome's debugging connection, 0 for a free one",
    )
    parser.add_argument('--chrome', default='google-chrome', help='the Chrome to drive')
    options = parser.parse_args()
    port = options.port
    root = Path(__file__).resolve().parents[1]
    processes = []
    client = None
    checks = 0
    try:
        with tempfile.TemporaryDirectory(prefix='cuju-page-') as profile:
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(root / 'ci/mock_server.py'),
                        '--port',
                        str(port),
                        '--short',
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            print('Starting mock server.', flush=True)
            wait_json(f'http://127.0.0.1:{port}/api/scenarios')
            print('Starting Chrome.', flush=True)
            processes.append(
                subprocess.Popen(
                    [
                        options.chrome,
                        '--headless=new',
                        '--mute-audio',
                        '--no-sandbox',
                        '--disable-background-networking',
                        '--proxy-server=http://127.0.0.1:9',
                        '--proxy-bypass-list=127.0.0.1',
                        '--disable-component-update',
                        '--disable-sync',
                        '--no-first-run',
                        '--disable-default-apps',
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
            debug = debugging_port(profile, options.debug_port)
            targets = wait_json(f'http://127.0.0.1:{debug}/json')
            target = next(item for item in targets if item['type'] == 'page')
            print('Connecting to Chrome.', flush=True)
            client = CDP(target['webSocketDebuggerUrl'])
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
            client.call('Page.navigate', {'url': f'http://127.0.0.1:{port}/'})
            for _ in range(150):
                if client.evaluate('!!(window.cuju && window.cuju.menus)'):
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError('Renderer startup failed.')
            for page in [
                'home',
                'watch',
                'recordings',
                'matches',
                'tournaments',
                'teams',
                'field',
                'play',
                'help',
            ]:
                result = client.evaluate(f"""
                    document.querySelector('[data-page="{page}"]').click();
                    ({{
                        page: cuju.page,
                        visible: !document.getElementById('page-{page}').hidden,
                        hash: location.hash
                    }})
                """)
                assert result['page'] == page and result['visible'], result
                assert result['hash'] == f'#page={page}', result
                checks += 1
            for page in ['home', 'teams', 'field', 'play']:
                client.evaluate(f"cuju.showPage('{page}'); document.activeElement.blur()")
                client.call(
                    'Input.dispatchKeyEvent',
                    {
                        'type': 'keyDown',
                        'key': 'h',
                        'code': 'KeyH',
                    },
                )
                assert client.evaluate('cuju.page') == 'help'
                checks += 1
                client.call(
                    'Input.dispatchKeyEvent',
                    {
                        'type': 'keyDown',
                        'key': 'Escape',
                        'code': 'Escape',
                    },
                )
                assert client.evaluate('cuju.page') == page
                checks += 1
            result = client.evaluate("""
                (async () => {
                    const { api } = await import('./js/core/api.js');
                    const entries = await api.matches();
                    await cuju.openMatch(entries[0].id);
                    cuju.updateHash(true);
                    const sourceHash = location.hash;
                    cuju.showPage('teams');
                    const teamsHash = location.hash;
                    cuju.showPage('watch');
                    cuju.updateHash(true);
                    return sourceHash.startsWith('#match=' + entries[0].id)
                        && teamsHash === '#page=teams'
                        && location.hash.startsWith('#match=' + entries[0].id);
                })()
            """)
            assert result, 'Source addresses'
            checks += 1
            result = client.evaluate("""
                (async () => {
                    cuju.director.stop(true);
                    cuju.timeline.pause();
                    cuju.postMatch.openStats();
                    const card = () => cuju.postMatch.statsCard;
                    for (let i = 0; i < 50 && (!card() || document.activeElement !== card()); i++) {
                        await new Promise((resolve) => setTimeout(resolve, 20));
                    }
                    return !!card() && document.activeElement === card();
                })()
            """)
            assert result, 'Statistics screen takes focus'
            for kind in ('keyDown', 'keyUp'):
                client.call(
                    'Input.dispatchKeyEvent', {'type': kind, 'key': 'Enter', 'code': 'Enter'}
                )
            assert client.evaluate('cuju.postMatch.statsCard === null'), 'Enter closes statistics'
            checks += 1
            client.evaluate(
                "cuju.director.stop(true); cuju.timeline.pause(); cuju.showPage('watch')"
            )
            for key, code in [
                (' ', 'Space'),
                ('k', 'KeyK'),
                ('.', 'Period'),
                (',', 'Comma'),
                ('Home', 'Home'),
                ('End', 'End'),
                ('v', 'KeyV'),
                ('b', 'KeyB'),
                ('p', 'KeyP'),
                ('g', 'KeyG'),
            ]:
                client.evaluate('document.activeElement.blur()')
                client.call('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': key, 'code': code})
                client.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': key, 'code': code})
                assert client.evaluate("cuju.page === 'watch'")
                if code == 'Space':
                    assert client.evaluate('cuju.timeline.playing')
                elif code == 'KeyK':
                    assert not client.evaluate('cuju.timeline.playing')
                checks += 1
            # Export video opens a dialog over Watch, which says what this server lacks and
            # closes with Escape.
            result = client.evaluate("""
                (async () => {
                    document.getElementById('video-export-btn').click();
                    const d = document.querySelector('dialog.video-export');
                    for (let i = 0; i < 50 && !d.querySelector('.ve-actions'); i++) {
                        await new Promise((r) => setTimeout(r, 100));
                    }
                    return { open: d.open, text: d.textContent, paused: !cuju.timeline.playing };
                })()
            """)
            assert result['open'] and result['paused'], result
            assert 'video export' in result['text'].lower(), result
            escape = {'key': 'Escape', 'code': 'Escape', 'windowsVirtualKeyCode': 27}
            client.call('Input.dispatchKeyEvent', {'type': 'keyDown', **escape})
            client.call('Input.dispatchKeyEvent', {'type': 'keyUp', **escape})
            closed = client.evaluate("!document.querySelector('dialog.video-export').open")
            assert closed, 'Escape closes Export video'
            assert client.evaluate('!document.pointerLockElement'), 'Export video frees the pointer'
            checks += 1
            result = client.evaluate("""
                (async () => {
                    const { api } = await import('./js/core/api.js');
                    cuju.showPage('teams');
                    await cuju.library.refresh();
                    const form = cuju.library.upload;
                    const fileInput = form.querySelector('input[type=file]:not([webkitdirectory])');
                    const name = form.querySelector('input[type=text]');
                    const original = api.uploadTeam;
                    let sent = null;
                    api.uploadTeam = async (...args) => { sent = args; return {}; };
                    try {
                        const choose = () => {
                            const data = new DataTransfer();
                            data.items.add(new File(['archive'], 'export.zip'));
                            fileInput.files = data.files;
                            fileInput.dispatchEvent(new Event('change'));
                            name.value = 'Imported';
                        };
                        choose();
                        form.dispatchEvent(new Event('submit', { cancelable: true }));
                        await new Promise((resolve) => setTimeout(resolve, 20));
                        const untouched = sent && sent[4] === null;
                        choose();
                        const count = form.querySelector('input[type=number]');
                        count.value = '2';
                        count.dispatchEvent(new Event('change', { bubbles: true }));
                        form.dispatchEvent(new Event('submit', { cancelable: true }));
                        await new Promise((resolve) => setTimeout(resolve, 20));
                        return untouched && sent[4].players === 2;
                    } finally {
                        api.uploadTeam = original;
                    }
                })()
            """)
            assert result, 'Import form preserves archive controls until edited'
            checks += 1
            result = client.evaluate("""
                (async () => {
                    const { controlForm } = await import('./js/core/api.js');
                    const form = controlForm('11v11', {
                        players: 1, assignment: 'fixed', selection: ['CB'],
                        goalkeeper: 'scenario', action_set: 'default',
                    });
                    const buttons = form.querySelectorAll('button');
                    if (form.querySelectorAll('[aria-pressed=true]').length !== 1) return false;
                    buttons[3].click();
                    let value = JSON.parse(form.value);
                    if (value.selection.join(',') !== '2,3' || value.players !== 2) return false;
                    buttons[2].click();
                    buttons[3].click();
                    value = JSON.parse(form.value);
                    return value.assignment === 'dynamic' && value.selection.length === 0;
                })()
            """)
            assert result, 'Lineup selection and repeated roles'
            checks += 1
            client.evaluate("""
                (async () => {
                    cuju.showPage('teams');
                    await cuju.library.refresh();
                    cuju.library.root.querySelector('li').click();
                    for (let i = 0; i < 100 && !cuju.editor.sectionLabel; i++) {
                        await new Promise((resolve) => setTimeout(resolve, 50));
                    }
                })()
            """)
            for section in [
                'identity',
                'kit',
                'roster',
                'model',
                'fans',
                'celebrations',
                'sounds',
                'sponsors',
                'export',
            ]:
                assert client.evaluate(f"""
                    cuju.editor.showSection('{section}');
                    cuju.editor.section === '{section}' && !!cuju.editor.formHost.children.length
                """)
                checks += 1
            # A celebration clip uploads through the editor's file input, its animations join the
            # moves, play in the preview on the nodes, retarget exactly onto a rig of the clip's own
            # skeleton, and leave with the clip.
            result = client.evaluate("""
                (async () => {
                    const wait = async (test) => {
                        for (let i = 0; i < 200 && !test(); i++) {
                            await new Promise((resolve) => setTimeout(resolve, 50));
                        }
                        return test();
                    };
                    const THREE = await import('three');
                    const clips = await import('./js/players/clips.js');
                    const retarget = await import('./js/players/retarget.js');
                    const players = await import('./js/players/players.js');
                    const celebrate = await import('./js/broadcast/celebrate.js');
                    const editor = cuju.editor;
                    editor.showSection('celebrations');
                    const url = 'assets/animations/kaykit-rig-medium-general.glb';
                    const bytes = await (await fetch(url)).arrayBuffer();
                    const file = new File([bytes], 'KayKit General.glb', {
                        type: 'model/gltf-binary',
                    });
                    const input = editor.formHost.querySelector('.clip-file');
                    const transfer = new DataTransfer();
                    transfer.items.add(file);
                    input.files = transfer.files;
                    input.dispatchEvent(new Event('change'));
                    const uploaded = await wait(() => (editor.team.clips || []).length === 1
                        && !!editor.formHost.querySelector('[data-clip="kaykit_general"]'));
                    const clip = editor.team.clips[0];
                    const idle = clip.animations.indexOf('Idle_A');
                    const value = `upload:kaykit_general.${idle}`;
                    const listed = [...editor.formHost.querySelectorAll('.move label')]
                        .some((label) => label.textContent === 'Idle_A clip of the team');
                    editor.playCelebration(value);
                    const key = editor.playing.pose;
                    const loaded = key !== value && retarget.hasUpload(key);
                    await new Promise((resolve) => setTimeout(resolve, 400));
                    const expected = new Float32Array(98);
                    const pt = (performance.now() - editor.playing.start) / 1000;
                    retarget.poseUpload(key, pt, expected, 0, {});
                    const nodes = editor.pose.nodes;
                    const previewed = nodes.every(Number.isFinite)
                        && Math.abs(nodes[7 + 2] - expected[7 + 2]) < 0.05;
                    // The roster offers the clip, and a goal plays it under its tag.
                    editor.showSection('roster');
                    const roster = [...editor.formHost.querySelectorAll('option')]
                        .some((option) => option.value === value);
                    const style = { celebrations: [key], players: [] };
                    const picked = celebrate.celebrationFor(style, 0, Math.random) === key;
                    const out = new Float32Array(98);
                    celebrate.posePlayer(key, 0.3, out, 0, 54.9, 0, 0, '');
                    const onPitch = out.every(Number.isFinite) && out[0] <= 55 + 1e-6;
                    // Posing a rig of the clip's skeleton from the nodes gives back the bones'
                    // turns of the clip.
                    const gltf = await players.parseModel(bytes);
                    const joints = players.guessJoints(players.fileBoneNames(gltf));
                    const animation = gltf.animations[idle];
                    const made = clips.retargetAnimation(gltf, animation, joints);
                    const rig = new players.Rig(gltf.scene, joints, {});
                    const posed = rig.instantiate();
                    const played = rig.instantiate();
                    for (const b of played.bones) {
                        if (b) {
                            b.matrixAutoUpdate = true;
                            b.matrixWorldAutoUpdate = true;
                        }
                    }
                    const mixer = new THREE.AnimationMixer(played.root);
                    const action = mixer.clipAction(animation);
                    action.play();
                    let worst = 0;
                    const m = new THREE.Matrix4();
                    const p = new THREE.Vector3();
                    const q = new THREE.Quaternion();
                    const s = new THREE.Vector3();
                    for (const i of [0, Math.floor(made.count / 2), made.count - 1]) {
                        const t = (i / (made.count - 1)) * made.duration;
                        action.time = Math.min(t, animation.duration - 1e-4);
                        mixer.update(0);
                        played.root.updateMatrixWorld(true);
                        rig.pose(posed, made.frames, i * 98);
                        rig.bones.forEach((info, j) => {
                            if (info.node < 1 || !played.bones[j]) return;
                            m.multiplyMatrices(rig.placement, played.bones[j].matrixWorld)
                                .decompose(p, q, s);
                            const r = new THREE.Quaternion();
                            posed.world[j].decompose(p, r, s);
                            worst = Math.max(worst, 1 - Math.abs(q.dot(r)));
                        });
                    }
                    mixer.stopAllAction();
                    rig.release(posed);
                    rig.release(played);
                    const exact = worst < 1e-5;
                    // The mapping of the clip lists the bones, and removal takes its moves.
                    editor.showSection('celebrations');
                    const box = editor.formHost.querySelector('[data-clip] details');
                    box.open = true;
                    box.dispatchEvent(new Event('toggle'));
                    const mapped = await wait(() => box.querySelectorAll('select').length === 14);
                    const body = box.querySelectorAll('select')[1].value === 'hips';
                    editor.style.celebrations = [value];
                    const confirmBox = window.confirm;
                    window.confirm = () => true;
                    try {
                        const editing = await import('./js/teams/clip-editor.js');
                        await editing.removeClip(editor, 'kaykit_general');
                    } finally {
                        window.confirm = confirmBox;
                    }
                    const removed = !(editor.team.clips || []).length && !retarget.hasUpload(key)
                        && !editor.style.celebrations.length
                        && !editor.formHost.querySelector('[data-clip]');
                    return {
                        uploaded, listed, loaded, previewed, roster, picked, onPitch, exact,
                        mapped, body, removed, worst,
                    };
                })()
            """)
            assert all(value for name, value in result.items() if name != 'worst'), result
            checks += 1
            client.evaluate("cuju.editor.close(true); cuju.showPage('help')")
            assert client.evaluate(
                "document.getElementById('page-help').contains(document.getElementById('help'))"
            )
            checks += 1
            result = client.evaluate("""
                (async () => {
                    const { api } = await import('./js/core/api.js');
                    const sources = await api.live();
                    cuju.openLive(sources[0].id);
                    for (let i = 0; i < 100 && cuju.source?.kind !== 'live'; i++) {
                        await new Promise((resolve) => setTimeout(resolve, 100));
                    }
                    if (cuju.source?.kind !== 'live') return 'no live source';
                    const form = document.getElementById('live-env');
                    const input = document.getElementById('live-env-index');
                    const single = form.hidden;
                    // A source of a batch with three environments offers the field.
                    cuju.source.header.environment_count = 3;
                    cuju.updateLiveUi();
                    const shown = !form.hidden && input.value === '0' && input.max === '2';
                    const original = api.selectEnvironment;
                    let sent = null;
                    api.selectEnvironment = async (...args) => { sent = args; return {}; };
                    try {
                        input.focus();
                        input.value = '2';
                        form.requestSubmit();
                        await new Promise((resolve) => setTimeout(resolve, 20));
                    } finally {
                        api.selectEnvironment = original;
                    }
                    const asked = !!sent && sent[0] === sources[0].id && sent[1] === 2;
                    const kept = document.activeElement === input;
                    cuju.source.live.stop();
                    const all = { single, shown, asked, kept };
                    return Object.values(all).every(Boolean) || JSON.stringify(all);
                })()
            """)
            assert result is True, f'Live environment field {result}'
            checks += 1

            result = client.evaluate("""
                (async () => {
                    const { api } = await import('./js/core/api.js');
                    const sources = await api.live();
                    const original = Object.fromEntries(
                        ['startGame', 'gameStream', 'pauseGame', 'gameInput', 'quitGame', 'game']
                            .map((name) => [name, api[name]])
                    );
                    let quitCount = 0;
                    let entry = { id: sources[0].id, state: 'paused', score: [0, 0] };
                    let startSpec = null;
                    api.startGame = async (spec) => {
                        startSpec = spec;
                        return entry;
                    };
                    api.gameStream = (id, signal) => api.liveStream(id, signal);
                    api.pauseGame = async (id, paused) => {
                        entry = { ...entry, state: paused ? 'paused' : 'playing' };
                        return entry;
                    };
                    const inputs = [];
                    const readPads = navigator.getGamepads;
                    api.gameInput = async (id, input) => { inputs.push(input); return entry; };
                    api.game = async () => entry;
                    api.quitGame = async () => {
                        quitCount++;
                        entry = { ...entry, state: 'ended', ending: 'quit' };
                        return entry;
                    };
                    try {
                        cuju.showPage('play');
                        await new Promise((resolve) => setTimeout(resolve, 100));
                        const teamLists = cuju.play.teamSelects.length === 2
                            && cuju.play.teamSelects.every((select) => select.value === 'builtin');
                        await cuju.play.start();
                        const sent = startSpec && startSpec.teams.join();
                        if (!teamLists || sent !== 'builtin,builtin') {
                            throw new Error('Play team lists');
                        }
                        for (let i = 0; i < 100 && !cuju.play.game.started; i++) {
                            await new Promise((resolve) => setTimeout(resolve, 100));
                        }
                        if (!cuju.play.game.started) throw new Error('Play stream startup');
                        const keys = [
                            ['ArrowLeft', 'ArrowLeft', ['left']],
                            ['ArrowRight', 'ArrowRight', ['right']],
                            ['ArrowUp', 'ArrowUp', ['up']],
                            ['ArrowDown', 'ArrowDown', ['down']],
                            ['w', 'KeyW', ['long_pass']], ['a', 'KeyA', ['high_pass', 'sliding']],
                            ['s', 'KeyS', ['short_pass']], ['d', 'KeyD', ['shot']],
                            ['e', 'KeyE', ['sprint']], ['c', 'KeyC', ['dribble']],
                        ];
                        for (const [key, code, actions] of keys) {
                            cuju.play.view.focus();
                            cuju.play.view.dispatchEvent(new KeyboardEvent('keydown', {
                                key, code, bubbles: true,
                            }));
                            await new Promise((resolve) => setTimeout(resolve, 20));
                            if (!actions.every((action) => inputs.at(-1).held.includes(action))) {
                                throw new Error('Play input ' + code);
                            }
                            cuju.play.view.dispatchEvent(new KeyboardEvent('keyup', {
                                key, code, bubbles: true,
                            }));
                            await new Promise((resolve) => setTimeout(resolve, 20));
                            if (inputs.at(-1).held.length) throw new Error('Play release ' + code);
                        }
                        const pad = {
                            index: 0, connected: true, mapping: 'standard', axes: [0, 0],
                            buttons: Array.from({ length: 16 }, () => ({ pressed: false })),
                        };
                        Object.defineProperty(navigator, 'getGamepads', {
                            configurable: true, value: () => [pad],
                        });
                        cuju.play.pollPads();
                        for (const [index, actions] of [
                            [0, ['short_pass']], [1, ['shot']], [2, ['high_pass', 'sliding']],
                            [3, ['long_pass']], [7, ['sprint']], [5, ['dribble']],
                            [12, ['up']], [13, ['down']], [14, ['left']], [15, ['right']],
                        ]) {
                            pad.buttons[index].pressed = true;
                            cuju.play.pollPads();
                            await new Promise((resolve) => setTimeout(resolve, 20));
                            if (!actions.every((action) => inputs.at(-1).held.includes(action))) {
                                throw new Error('Controller button ' + index);
                            }
                            pad.buttons[index].pressed = false;
                            cuju.play.pollPads();
                            await new Promise((resolve) => setTimeout(resolve, 20));
                        }
                        pad.buttons[9].pressed = true;
                        cuju.play.pollPads();
                        if (cuju.play.menu.hidden) throw new Error('Controller pause');
                        pad.buttons[9].pressed = false;
                        cuju.play.pollPads();
                        pad.buttons[9].pressed = true;
                        cuju.play.pollPads();
                        if (!cuju.play.menu.hidden) throw new Error('Controller resume');
                        pad.buttons[9].pressed = false;
                        cuju.play.pause(true);
                        const sameGame = cuju.play.game;
                        const pick = (text) => [...cuju.play.menu.querySelectorAll('button')]
                            .find((button) => button.textContent === text).click();
                        pick('Home');
                        await new Promise((resolve) => setTimeout(resolve, 50));
                        const home = cuju.page === 'home' && quitCount === 0
                            && cuju.play.game === sameGame && sameGame.paused;
                        cuju.showPage('play');
                        await new Promise((resolve) => setTimeout(resolve, 50));
                        const resumeAvailable = !cuju.play.menu.hidden;
                        pick('Resume');
                        await new Promise((resolve) => setTimeout(resolve, 50));
                        const resumed = !sameGame.paused && cuju.play.menu.hidden;
                        cuju.play.pause(true);
                        pick('Quit to Home');
                        for (let i = 0; i < 100 && cuju.page !== 'home'; i++) {
                            await new Promise((resolve) => setTimeout(resolve, 50));
                        }
                        return home && resumeAvailable && resumed && quitCount === 1
                            && cuju.page === 'home' && cuju.play.game === null;
                    } finally {
                        Object.defineProperty(navigator, 'getGamepads', {
                            configurable: true, value: readPads,
                        });
                        if (cuju.play.game?.source) cuju.play.game.source.live.stop();
                        Object.assign(api, original);
                    }
                })()
            """)
            assert result, 'Play Home, Resume and Quit to Home'
            checks += 1

            result = client.evaluate("""
                (async () => {
                    cuju.showPage('play');
                    await new Promise((resolve) => setTimeout(resolve, 50));
                    const play = cuju.play;
                    play.inputPanel.open = true;
                    const button = play.keyButtons.shot;
                    button.focus();
                    button.click();
                    const press = (code) => button.dispatchEvent(new KeyboardEvent('keydown', {
                        code, key: code, bubbles: true, cancelable: true,
                    }));
                    press('KeyH');
                    const reserved = play.input.keys.shot === 'KeyD'
                        && /H, M and F/.test(play.inputNote.textContent);
                    press('KeyW');
                    const taken = play.input.keys.shot === 'KeyD'
                        && /already/.test(play.inputNote.textContent);
                    press('KeyX');
                    const stored = JSON.parse(localStorage.getItem('cuju.input'));
                    const bound = play.input.keys.shot === 'KeyX' && stored.keys.shot === 'KeyX'
                        && play.keys.KeyX[0] === 'shot' && !play.keys.KeyD
                        && play.keyTable.textContent.includes('X');
                    play.deadZone.value = '0.3';
                    play.deadZone.dispatchEvent(new Event('input'));
                    const stick = { stickX: { a: 0, s: 1 }, stickY: { a: 1, s: 1 } };
                    const zone = play.input.deadZone === 0.3
                        && play.padHeld({ axes: [0.4, 0], buttons: [] }, stick).held.has('right')
                        && !play.padHeld({ axes: [0.2, 0], buttons: [] }, stick).held.has('right');
                    const pick = (select, value) => {
                        select.value = value;
                        select.dispatchEvent(new Event('change'));
                    };
                    pick(play.deviceSelects[0], 'keyboard');
                    pick(play.deviceSelects[1], 'keyboard');
                    const devices = play.input.devices.join() === 'keyboard,auto'
                        && play.deviceSelects[1].value === 'auto';
                    play.tester.focus();
                    play.tester.dispatchEvent(new KeyboardEvent('keydown', {
                        code: 'KeyX', key: 'x', bubbles: true, cancelable: true,
                    }));
                    const tested = /shot/.test(play.testerLines.textContent);
                    play.tester.dispatchEvent(new KeyboardEvent('keyup', {
                        code: 'KeyX', key: 'x', bubbles: true, cancelable: true,
                    }));
                    const targets = play.navTargets([play.setupView]);
                    const navigable = targets.includes(play.inputPanel.querySelector('summary'))
                        && targets.includes(play.deadZone) && targets.includes(button);
                    [...play.inputPanel.querySelectorAll('button')]
                        .find((item) => item.textContent === 'Reset input settings').click();
                    const reset = play.input.keys.shot === 'KeyD' && play.input.deadZone === 0.5
                        && play.input.devices.join() === 'auto,auto';
                    play.inputPanel.open = false;
                    return { reserved, taken, bound, zone, devices, tested, navigable, reset };
                })()
            """)
            assert all(result.values()), f'Play input settings {result}'
            checks += 1

            client.evaluate("""
                (async () => {
                    const { api } = await import('./js/core/api.js');
                    const entries = await api.matches();
                    cuju.showPage('watch');
                    await cuju.openMatch(entries[0].id);
                    cuju.director.stop(true);
                    if (cuju.postMatch.running) cuju.postMatch.end({ home: false });
                    cuju.timeline.seek(cuju.timeline.first + 40);
                    cuju.timeline.pause();
                    cuju.setCamera('tactical');
                    cuju.cameras.jump();
                    document.getElementById('labels-on').click();
                    for (let i = 0; i < 60 && !cuju.playerTools.layer.childElementCount; i++) {
                        await new Promise((resolve) => setTimeout(resolve, 50));
                    }
                })()
            """)
            result = client.evaluate("""
                (() => {
                    const tools = cuju.playerTools;
                    const point = tools.points[0];
                    const labels = tools.layer.childElementCount;
                    return {
                        shown: !tools.layer.hidden && labels > 0
                            && labels <= cuju.source.header.players.length,
                        named: !!point
                            && tools.layer.textContent.includes(cuju.playerLabel(point.index)),
                        stored: localStorage.getItem('cuju.playerLabels') === 'true',
                        point: point ? [point.x, point.y, point.index] : null,
                    };
                })()
            """)
            point = result.pop('point')
            assert all(result.values()) and point, f'Player labels {result}'
            checks += 1
            client.evaluate("document.getElementById('click-follow').click()")
            # A click lasts at most half a second, and Chrome hands the button's release to the
            # page only after the frame it is drawing, which takes longer than that in software
            # on a busy machine. The page holds its frames while the button goes down and up, so
            # the click reaches it as quick as it was sent.
            client.evaluate("""
                (async () => {
                    const real = window.requestAnimationFrame;
                    window.__heldFrames = [];
                    window.__realFrame = real;
                    await new Promise((resolve) => {
                        window.requestAnimationFrame = (fn) => {
                            window.__heldFrames.push(fn);
                            resolve();
                            return 0;
                        };
                        setTimeout(resolve, 2000);
                    });
                    return true;
                })()
            """)
            for kind in ['mousePressed', 'mouseReleased']:
                client.call(
                    'Input.dispatchMouseEvent',
                    {'type': kind, 'x': point[0], 'y': point[1], 'button': 'left', 'clickCount': 1},
                )
            client.evaluate("""
                window.requestAnimationFrame = window.__realFrame;
                for (const fn of window.__heldFrames.splice(0)) window.requestAnimationFrame(fn);
                true
            """)
            result = client.evaluate(f"""
                (async () => {{
                    const tools = cuju.playerTools;
                    const followed = cuju.cameras.mode === 'player'
                        && cuju.cameras.followIndex === {point[2]};
                    cuju.showPage('teams');
                    tools.update(true);
                    const away = tools.layer.hidden && !tools.layer.childElementCount;
                    cuju.showPage('watch');
                    document.getElementById('labels-on').click();
                    document.getElementById('click-follow').click();
                    tools.update(true);
                    const off = tools.layer.hidden && !tools.picking
                        && localStorage.getItem('cuju.clickFollow') === 'false';
                    cuju.setCamera('broadcast');
                    return {{ followed, away, off }};
                }})()
            """)
            assert all(result.values()), f'Click to follow {result}'
            checks += 1

            result = client.evaluate("""
                (async () => {
                    const motion = document.getElementById('motion');
                    const choose = (value) => {
                        motion.value = value;
                        motion.dispatchEvent(new Event('change'));
                    };
                    const root = document.documentElement.classList;
                    const start = motion.value === 'system' && !cuju.reducedMotion
                        && !root.contains('reduced-motion');
                    choose('reduce');
                    const tl = cuju.timeline;
                    const goal = tl.first + 80;
                    tl.pause();
                    cuju.director.play([{ goal: { index: goal, team: 0 }, shot: 'auto' }]);
                    const reduced = cuju.reducedMotion && root.contains('reduced-motion')
                        && cuju.cameras.reducedMotion && !cuju.ball.trailOn
                        && !cuju.transition.enabled()
                        && JSON.parse(localStorage.getItem('cuju.motion')) === 'reduce';
                    const replay = !cuju.director.running && tl.playing
                        && Math.abs(tl.t - (goal - 3 * tl.sps)) < 2;
                    tl.pause();
                    choose('full');
                    const full = !cuju.reducedMotion && root.contains('full-motion')
                        && cuju.ball.trailOn === cuju.settings.trail;
                    choose('system');
                    return { start, reduced, replay, full };
                })()
            """)
            assert all(result.values()), f'Motion preference {result}'
            checks += 1
            # The page hears of a change of the media features in a task of its own, so each
            # change is waited for, up to five seconds.
            wait_motion = """
                (async () => {
                    for (let i = 0; i < 100 && cuju.reducedMotion !== %s; i++) {
                        await new Promise((resolve) => setTimeout(resolve, 50));
                    }
                    return cuju.reducedMotion;
                })()
            """
            client.call(
                'Emulation.setEmulatedMedia',
                {'features': [{'name': 'prefers-reduced-motion', 'value': 'reduce'}]},
            )
            followed = client.evaluate(wait_motion % 'true')
            client.call('Emulation.setEmulatedMedia', {'features': []})
            restored = not client.evaluate(wait_motion % 'false')
            assert followed and restored, f'System motion {followed} {restored}'
            checks += 1
            result = client.evaluate("""
                (async () => {
                    const sound = cuju.sound;
                    const start = ['crowd', 'ambience', 'effects'].every((name) =>
                        sound.levels[name] === 1
                        && document.getElementById('level-' + name).value === '1');
                    const slider = document.getElementById('level-crowd');
                    slider.value = '0.4';
                    slider.dispatchEvent(new Event('input'));
                    const lowered = sound.levels.crowd === 0.4
                        && JSON.parse(localStorage.getItem('cuju.soundLevels')).crowd === 0.4;
                    sound.setChannel('effects', 3);
                    sound.setChannel('ambience', -1);
                    const bounded = sound.levels.effects === 1 && sound.levels.ambience === 0;
                    await new Promise((resolve) => setTimeout(resolve, 400));
                    // A suspended context holds its gains, so the level shows once it runs.
                    const mixed = !sound.mix || (sound.master.gain.value === 0
                        && (sound.ctx.state !== 'running'
                            || Math.abs(sound.mix.crowd.dry.gain.value - 0.4) < 0.01));
                    for (const name of ['crowd', 'ambience', 'effects']) {
                        const input = document.getElementById('level-' + name);
                        input.value = '1';
                        input.dispatchEvent(new Event('input'));
                    }
                    const muted = cuju.settings.muted
                        && localStorage.getItem('cuju.muted') === 'true';
                    return { start, lowered, bounded, mixed, muted };
                })()
            """)
            assert all(result.values()), f'Sound levels {result}'
            checks += 1

            # The pointer is never captured here. A stand-in for the captured state lets the
            # page's own release rule run as it would.
            result = client.evaluate("""
                (async () => {
                    const { openPanel } = await import('./js/core/comfort.js');
                    const wait = (ms = 60) => new Promise((resolve) => setTimeout(resolve, ms));
                    const name = (node) => node && (node.id || node.className || node.tagName);
                    const $ = (id) => document.getElementById(id);
                    for (const menu of Object.values(cuju.menus)) menu.close();
                    document.activeElement.blur();
                    const resting = {};
                    for (const page of ['watch', 'field', 'play', 'recordings']) {
                        cuju.showPage(page);
                        await wait();
                        resting[page] = name(openPanel());
                    }
                    cuju.showPage('watch');
                    await wait();
                    let released = 0;
                    const original = {
                        release: cuju.releasePointer, lock: cuju.settings.pointerLock,
                    };
                    cuju.releasePointer = () => { released++; };
                    cuju.settings.pointerLock = true;
                    document.hasFocus = () => true;
                    const canvas = cuju.view.renderer.domElement;
                    Object.defineProperty(document, 'pointerLockElement', {
                        configurable: true, get: () => canvas,
                    });
                    const opened = {};
                    const step = async (label, page, open, close) => {
                        cuju.showPage(page);
                        await wait();
                        const before = openPanel();
                        released = 0;
                        await open();
                        await wait();
                        opened[label] = !before && released > 0;
                        await close();
                        await wait();
                    };
                    try {
                        released = 0;
                        $('watch').classList.add('page-check');
                        await wait();
                        $('watch').classList.remove('page-check');
                        opened.quiet = released === 0;
                        await step('settings', 'watch', () => $('open-settings').click(),
                            () => cuju.menus.settings.close());
                        await step('dialog', 'watch', () => {
                            const dialog = document.createElement('dialog');
                            dialog.id = 'check-dialog';
                            document.body.append(dialog);
                            dialog.showModal();
                        }, () => $('check-dialog').remove());
                        await step('details', 'watch', () => {
                            const details = document.createElement('details');
                            details.id = 'check-details';
                            details.innerHTML = '<summary>More</summary><p>Text</p>';
                            $('watch').append(details);
                            details.open = true;
                        }, () => $('check-details').remove());
                        await step('environment', 'watch', () => {
                            $('live-box').hidden = false;
                            $('live-env').hidden = false;
                            $('live-env-index').focus();
                        }, () => {
                            document.activeElement.blur();
                            $('live-env').hidden = true;
                            $('live-box').hidden = true;
                        });
                        await step('input', 'play', () => { cuju.play.inputPanel.open = true; },
                            () => { cuju.play.inputPanel.open = false; });
                        await cuju.recordings.refresh();
                        const recordings = cuju.recordings;
                        await step('recording', 'recordings', () => {
                            recordings.selected = new Set([recordings.list[0].id]);
                            recordings.toggleDetails();
                        }, () => recordings.toggleDetails());
                    } finally {
                        delete document.pointerLockElement;
                        delete document.hasFocus;
                        cuju.releasePointer = original.release;
                        cuju.settings.pointerLock = original.lock;
                        cuju.showPage('watch');
                    }
                    const rest = Object.values(resting).every((value) => !value);
                    return { rest: rest || JSON.stringify(resting), ...opened };
                })()
            """)
            assert all(value is True for value in result.values()), f'Pointer release {result}'
            checks += 1
            client.evaluate("""
                (() => {
                    cuju.timeline.pause();
                    const details = document.createElement('details');
                    details.id = 'check-summary';
                    details.innerHTML = '<summary>More</summary><p>Text</p>';
                    document.getElementById('watch').append(details);
                    details.querySelector('summary').focus();
                })()
            """)
            for kind in ['keyDown', 'keyUp']:
                client.call('Input.dispatchKeyEvent', {'type': kind, 'key': ' ', 'code': 'Space'})
            result = client.evaluate("""
                (() => {
                    const kept = !cuju.timeline.playing && cuju.page === 'watch';
                    document.getElementById('check-summary').remove();
                    return kept;
                })()
            """)
            assert result, 'Space on a summary'
            checks += 1
            client.evaluate("""
                (() => {
                    cuju.settings.savedCelebrations = cuju.settings.celebrations;
                    cuju.settings.celebrations = false;
                    cuju.timeline.seek(cuju.timeline.first + 10);
                    cuju.act('play');
                    // The short recordings of the mock server last 12 seconds, so play runs at a
                    // quarter of its speed and stays clear of the end and the show after it
                    // however slowly a busy machine draws.
                    cuju.timeline.speed = 0.25;
                })()
            """)
            for kind in ['keyDown', 'keyUp']:
                client.call(
                    'Input.dispatchKeyEvent', {'type': kind, 'key': 'Shift', 'code': 'ShiftLeft'}
                )
            result = client.evaluate("""
                (async () => {
                    const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                    const app = document.getElementById('app');
                    const button = document.getElementById('btn-pause');
                    button.focus();
                    const visible = button.matches(':focus-visible');
                    cuju.poke();
                    await wait(2900);
                    const kept = !app.classList.contains('idle');
                    button.blur();
                    cuju.poke();
                    await wait(2900);
                    const faded = app.classList.contains('idle');
                    cuju.act('pause');
                    cuju.timeline.speed = 1;
                    cuju.settings.celebrations = cuju.settings.savedCelebrations;
                    cuju.poke();
                    return { visible, kept, faded };
                })()
            """)
            assert all(result.values()), f'Controls with keyboard focus {result}'
            checks += 1
            result = client.evaluate("""
                (() => {
                    const motion = document.getElementById('motion');
                    const choose = (value) => {
                        motion.value = value;
                        motion.dispatchEvent(new Event('change'));
                    };
                    choose('reduce');
                    const tl = cuju.timeline;
                    cuju.act('pause');
                    const paused = cuju.userPaused;
                    cuju.replayGoal({ index: tl.first + 80, team: 0 });
                    const playing = tl.playing && !cuju.userPaused;
                    cuju.act('pause');
                    choose('system');
                    return { paused, playing };
                })()
            """)
            assert all(result.values()), f'Reduced motion replay {result}'
            checks += 1
            checks += library_checks(client)
            checks += tournament_checks(client)
            checks += reconnection_checks(client)
            checks += palette_checks(client)
            checks += presets_checks(client)
            checks += first_run_checks(client)
            checks += touch_checks(client)
            checks += page_grid.check_grid(client)
            checks += page_grid.check_flat(client, f'http://127.0.0.1:{port}/')
            checks += loading_checks(client, port)
            checks += format_checks(client)
            checks += annotation_checks(client)
            assert client.evaluate("localStorage.getItem('cuju.muted')") == 'true'
            assert not client.evaluate('!!document.pointerLockElement')
            assert not client.errors, client.errors
            print(
                f'PASS. {checks} page, source, key, import, editor, library and stream checks. '
                'Chrome stayed muted.'
            )
    except Exception as error:
        print(f'FAIL. {checks} checks passed. {error}', file=sys.stderr)
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
                process.wait()
    return 0


if __name__ == '__main__':
    sys.exit(main())
