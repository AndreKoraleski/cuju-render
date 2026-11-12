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

import page_a11y
import page_challenges
import page_export
import page_feed
import page_grid
import page_groups
import page_help
import page_language
import page_matches
import page_search
import page_tournaments


class CDP:
    """A local CDP connection using the standard library."""

    def __init__(self, url):
        from urllib.parse import urlsplit

        address = urlsplit(url)
        # A check may wait the better part of a minute on a loaded machine before Chrome answers.
        self.socket = socket.create_connection((address.hostname, address.port), timeout=300)
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
        if size < 126:
            header = bytes([129, 128 | size])
        elif size < 65536:
            header = bytes([129, 254]) + struct.pack('!H', size)
        else:
            header = bytes([129, 255]) + struct.pack('!Q', size)
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
            return int(path.read_text(encoding='utf-8').splitlines()[0])
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


def malformed_summary_checks(client):
    """Checks that the lists of recordings show summaries whose fields are of the wrong kinds."""
    result = client.evaluate("""
        (async () => {
            const fetched = window.fetch;
            const real = await (await fetched('/api/matches')).json();
            const odd = JSON.parse('{"toString": 1, "valueOf": 2}');
            const at = Date.now() / 1000;
            const bad = [5, [1], {}, odd, true].map((title, i) => ({
                id: `m-odd-${i}`, title, title_id: i ? odd : 'help.title', title_values: odd,
                scenario: [odd, 5, {}, 'x_y', null][i],
                teams: [[5, odd], odd, null, [odd], 'ab'][i],
                team_labels: [[odd, { id: 'server.names.you', text: odd }], 5, null, [odd], 1][i],
                tags: [odd, [odd], 'tag', null, [5]][i], notes: odd, folder: '', created: at + i,
                steps: 10, bytes: 100, score: [1, 0],
            }));
            const ids = bad.map((m) => m.id);
            // The server's list of recordings holds the malformed summaries first.
            const text = JSON.stringify([...bad, ...real]);
            const headers = { 'Content-Type': 'application/json' };
            window.fetch = (input, init) => (String(input).endsWith('/api/matches')
                ? Promise.resolve(new Response(text, { headers })) : fetched(input, init));
            try {
                cuju.showPage('recordings');
                await cuju.recordings.refresh();
                const row = (id) => document.querySelector(`tr[data-id="${id}"]`);
                const rows = ids.filter(row);
                const shown = ids.map((id) => row(id)?.querySelector('.ellipsis')?.textContent);
                cuju.recordings.query = 'odd';
                cuju.recordings.sortKey = 'title';
                cuju.recordings.render();
                const searched = ids.filter(row);
                cuju.recordings.query = '';
                cuju.recordings.sortKey = 'teams';
                cuju.recordings.render();
                cuju.recordings.sortKey = 'created';
                cuju.recordings.render();
                cuju.showPage('home');
                await cuju.home.refresh();
                const home = document.querySelectorAll('.home-recordings .home-item').length;
                const { api } = await import('./js/core/api.js');
                cuju.palette.recent = await api.matches();
                const palette = cuju.palette.actions()
                    .filter((a) => ids.some((id) => a.keywords.includes(id))).length;
                cuju.showPage('watch');
                cuju.menus.match.open();
                let menu = '';
                for (let i = 0; i < 50 && !menu.includes('m-odd-'); i++) {
                    await new Promise((resolve) => setTimeout(resolve, 50));
                    menu = document.getElementById('match-menu').textContent;
                }
                cuju.menus.match.close(false);
                return { rows, shown, searched, home, palette, menu: menu.includes('m-odd-') };
            } finally {
                window.fetch = fetched;
                cuju.showPage('home');
            }
        })()
    """)
    assert len(result['rows']) == 5, result
    assert result['shown'] == ['5', 'm-odd-1', 'm-odd-2', 'm-odd-3', 'true'], result
    assert result['home'] > 0 and result['palette'] == 5 and result['menu'], result
    print(f'Malformed summaries list as {result["shown"]}.', flush=True)
    return 3


def malformed_index_checks(client):
    """Checks that the show and the restarts skip player indices of a frame beyond the header."""
    result = client.evaluate("""
        (async () => {
            const { findGoals, parseRecording } = await import('./js/recording/format.js');
            const { FrameStore } = await import('./js/recording/timeline.js');
            const { scorerAt } = await import('./js/broadcast/show.js');
            const { scanRestarts } = await import('./js/broadcast/transition.js');
            const response = await fetch('/api/mock/samples/sample-5v5');
            const bytes = new Uint8Array(await response.arrayBuffer());
            const { header, frames } = await parseRecording(bytes);
            const n = header.players.length;
            const goals = findGoals(frames);
            // The engine's scorer bits name player 30, beyond the ten of the header.
            const flagged = { ...header, engine_scorer: true };
            for (const goal of goals) {
                frames[goal.index].flags |= 31 << 8;
            }
            const store = new FrameStore(flagged, frames);
            const scorers = goals.map((g) => scorerAt(store, g.index, g.team, flagged).scorer);
            // A foul whose offender and victim lie beyond the header, on every restart.
            const last = frames.length - 1;
            const clean = scanRestarts(new FrameStore(header, frames), header, 1, last, []);
            for (const restart of clean) {
                if (!restart.decision && frames[restart.index - 1].foul.type === 0) {
                    frames[restart.index].foul = { player: 50, victim: 70, type: 1 };
                }
            }
            const fouled = scanRestarts(new FrameStore(header, frames), header, 1, last, []);
            const named = fouled.filter((r) => r.decision)
                .flatMap((r) => [r.decision.offender, r.decision.victim]);
            return { n, goals: goals.length, scorers, restarts: clean.length, named };
        })()
    """)
    n = result['n']
    assert result['goals'] > 0 and result['restarts'] > 0, result
    assert all(-1 <= k < n for k in result['scorers']), result
    assert all(-1 <= k < n for k in result['named']), result
    return 2


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
            // Each label hangs under the feet of its player, or over the head near the controls.
            const view = cuju.view.renderer.domElement.getBoundingClientRect();
            const clear = [...layer.querySelectorAll('span')].every((node) => {
                const box = node.getBoundingClientRect();
                const point = cuju.playerTools.points.find(
                    (p) => p.index === Number(node.dataset.player));
                return point && (box.top >= cuju.annotationOverlay.feetY(point.index, view)
                    || box.bottom <= point.y);
            });
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
            return { off, shown, clear, match, line, opened, listed, two, none, quiet, closed,
                hidden };
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


def draw_checks(client):
    """Requests a match with both sides Random from the page, and sees the teams that it drew."""
    result = client.evaluate("""
        (async () => {
            const { api } = await import('./js/core/api.js');
            const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            const source = 'def agent(obs):\\n    return [0]\\n';
            const made = [];
            for (const name of ['Draw Alpha', 'Draw Bravo']) {
                made.push(await api.uploadTeam(name, 'main.py', source, '5v5'));
            }
            const page = cuju.matches;
            cuju.showPage('matches');
            await page.refresh();
            for (let i = 0; i < 100 && !page.built; i++) {
                await wait(50);
            }
            // Each side opens its list and picks Random, its first item.
            for (const side of page.sides) {
                side.button.click();
                await wait(50);
                const item = side.dropdown.panel.querySelector('.dd-item');
                const named = item.textContent.includes('Random team');
                item.click();
                await wait(50);
                if (!named) {
                    return 'Random is not the first item';
                }
            }
            const pool = page.pool.root;
            const shown = !pool.hidden;
            // Only the two new teams stay in the pool.
            for (const box of pool.querySelectorAll('.draw-pool-list input')) {
                if (!made.some((x) => x.id === box.value) && box.checked) {
                    box.click();
                }
            }
            const cards = page.sides.map((side) => side.button.textContent);
            const randomCards = cards.every((text) => text.includes('Random team')
                && text.includes('Drawn from 2 teams of the pool'));
            const options = [...page.scenarioSelect.options].map((o) => o.value);
            const randomScenario = options[0] === 'random';
            page.scenarioSelect.value = '5_vs_5';
            page.scenarioSelect.dispatchEvent(new Event('change'));
            const before = new Set(page.requests.map((r) => r.id));
            page.playButton.click();
            let entry = null;
            for (let i = 0; i < 200; i++) {
                await wait(100);
                const items = await api.requests();
                entry = items.find((r) => !before.has(r.id));
                if (entry && entry.state !== 'queued') {
                    break;
                }
            }
            if (!entry) {
                return 'no request was made';
            }
            page.requests = await api.requests();
            page.renderQueue();
            const card = page.queueHost.querySelector(`.req-card[data-id="${entry.id}"]`);
            const names = [...card.querySelectorAll('.req-team-name')].map((x) => x.textContent);
            const marks = card.querySelectorAll('.req-team .req-drawn').length;
            const drawn = names.length === 2 && names[0] !== names[1]
                && names.every((name) => name === 'Draw Alpha' || name === 'Draw Bravo');
            const kept = JSON.stringify(entry.draw.sides) === '[true,true]'
                && entry.draw.pool.length === 2 && entry.scenario === '5_vs_5';
            // A drawn side shows as Random while its match waits.
            const waiting = page.requestCard({ ...entry, state: 'queued' }).textContent
                .includes('Random team');
            for (let i = 0; i < 100; i++) {
                const item = (await api.requests()).find((r) => r.id === entry.id);
                if (item.state !== 'queued' && item.state !== 'running') {
                    break;
                }
                await wait(100);
            }
            for (const team of made) {
                await api.deleteTeam(team.id);
            }
            page.state.left = 'builtin';
            page.state.right = 'builtin';
            page.state.unticked.clear();
            await page.refresh();
            const all = { shown, randomCards, randomScenario, drawn, marks: marks === 2, kept,
                waiting };
            return Object.values(all).every(Boolean) || JSON.stringify({ ...all, names, cards });
        })()
    """)
    assert result is True, f'Requested match drawn at random {result}'
    return 1


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
            // A button by its accessible name, the label of a symbol or the text it shows.
            const button = (text) => [...main().querySelectorAll('button')]
                .find((b) => (b.getAttribute('aria-label') || b.textContent).trim() === text);
            // Adds the built in AI at four rising abilities, one at a time through its field.
            const addFour = () => {
                for (const value of ['0.2', '0.4', '0.6', '0.8']) {
                    main().querySelector('.cup-adder input[type="number"]').value = value;
                    button('Add built-in AI').click();
                }
            };
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
            addFour();
            addFour();
            addFour();
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
                .some((h) => h.textContent === 'Third place match');
            const watch = !!main().querySelector('.cup-watch button');
            const champion = /Champion: /.test(main().querySelector('.cup-champion').textContent);
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
    result = client.evaluate("""
        (async () => {
            const page = cuju.tournaments;
            const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            const config = {
                name: 'Failing cup', seed: 3, seeding: 'manual',
                entrants: [{ kind: 'builtin', ability: 0.1, name: 'Failing bot' },
                    { kind: 'builtin', ability: 0.2 }, { kind: 'builtin', ability: 0.3 },
                    { kind: 'builtin', ability: 0.4 }],
                stages: [{ format: 'knockout', settle: ['lots'] }],
            };
            const made = await fetch('/api/tournaments', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ config }),
            }).then((r) => r.json());
            await page.refresh();
            await page.open(made.id);
            const reach = async (state) => {
                for (let t = 0; t < 8000; t += 100) {
                    await page.load(made.id);
                    if (page.current && page.current.state === state) {
                        return true;
                    }
                    await wait(100);
                }
                return false;
            };
            const stopped = await reach('stopped');
            const main = page.mainHost;
            const fixture = main.querySelector('.cup-fixture.state-failed');
            const awards = fixture ? [...fixture.querySelectorAll('button')]
                .filter((b) => b.textContent.startsWith('Award to')).length === 2 : false;
            const notice = main.querySelector('.notice.error');
            const named = !!notice && /Semi-final 1 failed, the policy of Failing bot/
                .test(notice.textContent);
            const inNotice = main.querySelectorAll('.cup-failed button').length === 2;
            // The other semi-final plays, since it does not depend on the failed one.
            const other = page.current.matches.find((m) => m.key === '0/w4-2/1');
            const independent = !!other && other.state === 'done';
            // The award goes to the other side, since Failing bot would fail its final too.
            // It asks first, Escape leaves the match as it was, and Award confirms it.
            const award = () => main.querySelectorAll('.cup-failed li > .row > button')[1];
            award().click();
            const asked = main.querySelector('.cup-failed .cup-confirm');
            const focused = !!asked && asked.contains(document.activeElement);
            document.activeElement.dispatchEvent(
                new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            const kept = !main.querySelector('.cup-confirm') && page.current.state === 'stopped'
                && document.activeElement === award();
            award().click();
            main.querySelector('.cup-failed .cup-confirm .btn.primary').click();
            const done = await reach('done');
            const all = { stopped, awards, named, inNotice, independent, focused, kept, done };
            return Object.values(all).every(Boolean) || JSON.stringify(all);
        })()
    """)
    assert result is True, f'Award of a failed tournament match {result}'
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
            const main = () => page.mainHost;
            const button = (text) => [...main().querySelectorAll('button')]
                .find((b) => (b.getAttribute('aria-label') || b.textContent.trim()) === text);
            const team = await fetch('/api/teams?name=Derby%20FC&filename=main.py&format=11v11', {
                method: 'POST', body: 'def agent(obs):\\n    return [0]\\n',
            }).then((r) => r.json());
            page.startWizard();
            await until(() => page.teams.some((x) => x.id === team.id));
            page.goStep(1);
            for (let i = 0; i < 2; i++) {
                main().querySelector('.cup-adder select').value = team.id;
                button('Add team').click();
            }
            // The team entered again takes a free name, which its row shows for a person to change.
            const entries = page.draft.entrants;
            const proposed = entries.length === 2 && !entries[0].name
                && entries[1].name === 'Derby FC 2';
            const inputs = () => [...main().querySelectorAll('.cup-entrant-name input')];
            const shown = inputs()[1].value === 'Derby FC 2'
                && document.activeElement === inputs()[1];
            const type = (input, text) => {
                input.value = text;
                input.dispatchEvent(new Event('input', { bubbles: true }));
            };
            type(inputs()[1], ' derby fc ');
            await wait(0);
            const note = main().querySelectorAll('.cup-name-note')[1].textContent;
            const marked = inputs()[1].getAttribute('aria-invalid') === 'true'
                && /already the name of entrant 1/.test(note);
            page.goStep(4);
            const alert = main().querySelector('.cup-review [role="alert"]');
            const refused = !!alert
                && /Entrant 2 is named derby fc, as entrant 1 is/.test(alert.textContent);
            page.goStep(1);
            type(inputs()[1], 'Derby reserves');
            await wait(0);
            const cleared = !inputs()[1].hasAttribute('aria-invalid')
                && !main().querySelectorAll('.cup-name-note')[1].textContent;
            page.goStep(4);
            const reviewed = await until(
                () => main().querySelectorAll('.cup-review-stage').length === 1);
            main().querySelector('.cup-start').click();
            const done = await until(() => page.mode === 'view' && page.current
                && page.current.state === 'done'
                && main().querySelector('.cup-bracket .cup-fixture'), 20000);
            const cup = page.current;
            const names = cup.config.entrants.map((e) => e.name).join('|')
                === 'Derby FC|Derby reserves';
            const sides = [...main().querySelectorAll('.cup-bracket .cup-side-name')];
            const both = sides.map((s) => s.textContent).join('|').replace(/\\d/g, '');
            const apart = sides.length === 2 && both.includes('Derby FC')
                && both.includes('Derby reserves');
            // The away side of a team that meets itself shows its away kit.
            const kits = sides.map((s) => s.querySelector('.kit-shirt-body')
                ?.getAttribute('style'));
            const away = kits.length === 2 && !!kits[0] && kits[0] !== kits[1];
            const champion = ['Derby FC', 'Derby reserves'].includes(cup.champion);
            await fetch(`/api/tournaments/${cup.id}`, { method: 'DELETE' });
            await fetch(`/api/teams/${team.id}`, { method: 'DELETE' });
            page.mode = 'empty';
            page.openId = null;
            await page.refresh();
            const all = { proposed, shown, marked, refused, cleared, reviewed: !!reviewed,
                done: !!done, names, apart, away, champion };
            return Object.values(all).every(Boolean) || JSON.stringify(all);
        })()
    """)
    assert result is True, f'A team entered twice {result}'
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
            const main = () => page.mainHost;
            const button = (text) => [...main().querySelectorAll('button')]
                .find((b) => (b.getAttribute('aria-label') || b.textContent.trim()) === text);
            // Adds the built in AI at four rising abilities, one at a time through its field.
            const addFour = () => {
                for (const value of ['0.2', '0.4', '0.6', '0.8']) {
                    main().querySelector('.cup-adder input[type="number"]').value = value;
                    button('Add built-in AI').click();
                }
            };
            const team = await fetch('/api/teams?name=Able%20FC&filename=main.py&format=11v11', {
                method: 'POST', body: 'def agent(obs):\\n    return [0]\\n',
            }).then((r) => r.json());
            page.startWizard();
            await until(() => main().querySelector('[data-preset="quick_cup"]'));
            main().querySelector('[data-preset="quick_cup"]').click();
            await until(() => page.teams.some((x) => x.id === team.id));
            page.goStep(1);
            main().querySelector('.cup-adder select').value = team.id;
            button('Add team').click();
            addFour();
            // The draw is random by default, and Set the bracket by hand seeds in list order.
            const box = () => main().querySelector('.cup-manual');
            const note = () => main().querySelector('.cup-draw-note').textContent;
            const random = page.draft.seeding === 'random' && !box().checked
                && /random from the tournament seed/.test(note());
            box().click();
            const byHand = page.draft.seeding === 'manual' && /Seed 1 is the first/.test(note());
            box().click();
            const back = page.draft.seeding === 'random';
            // The team's row takes an ability of its own, which follows the standard when empty.
            const own = main().querySelector('.cup-entrants > li .cup-entrant-ability');
            const follows = own.value === '' && own.placeholder === 'Standard';
            own.value = '0.3';
            own.dispatchEvent(new Event('input', { bubbles: true }));
            // The settings set the standard with a slider, its value shown beside it.
            page.goStep(2);
            const set = main().querySelector('.cup-standard-set');
            const range = main().querySelector('.cup-standard-range');
            const unset = !set.checked && range.disabled
                && main().querySelector('.cup-standard output').textContent
                    === "The scenario's own";
            set.click();
            range.value = '0.75';
            range.dispatchEvent(new Event('input', { bubbles: true }));
            const shown = main().querySelector('.cup-standard output').textContent === '0.75';
            // The advanced editor shows the same standard, and the rows name it as followed.
            page.goStep(3);
            const editor = main().querySelector('.cup-standard-set').checked
                && main().querySelector('.cup-standard-range').value === '0.75'
                && JSON.parse(main().querySelector('.cup-json').value).ability === 0.75;
            page.goStep(1);
            const rows = [...main().querySelectorAll('.cup-entrant-ability')];
            const named = rows[0].value === '0.3' && rows[1].placeholder === 'Standard, 0.75';
            page.goStep(4);
            const reviewed = await until(
                () => main().querySelectorAll('.cup-review-stage').length === 1);
            const review = main().querySelector('.cup-review-ability').textContent
                === 'Standard ability 0.75'
                && /Able FC/.test(main().querySelector('.cup-review-abilities').textContent);
            main().querySelector('.cup-start').click();
            const done = await until(() => page.mode === 'view' && page.current
                && page.current.state === 'done'
                && main().querySelector('.cup-bracket .cup-fixture'), 20000);
            const cup = await fetch(`/api/tournaments/${page.current.id}`).then((r) => r.json());
            const config = cup.config.ability === 0.75 && cup.config.entrants[0].ability === 0.3
                && cup.config.entrants.slice(1).map((e) => e.ability).join() === '0.2,0.4,0.6,0.8';
            const played = cup.matches.filter((m) => m.home === 0 || m.away === 0);
            const sides = played.length > 0
                && played.every((m) => m.ability[m.home === 0 ? 0 : 1] === 0.3);
            const badge = [...main().querySelectorAll('.cup-bracket .cup-side-name')]
                .some((s) => /Able FC/.test(s.textContent)
                    && s.querySelector('.cup-ability')?.textContent === 'Ability 0.30');
            const meta = main().querySelector('.cup-view-ability').textContent
                === 'Standard ability 0.75';
            await fetch(`/api/tournaments/${cup.id}`, { method: 'DELETE' });
            await fetch(`/api/teams/${team.id}`, { method: 'DELETE' });
            page.mode = 'empty';
            page.openId = null;
            await page.refresh();
            const drawn = cup.config.seeding === 'random';
            const all = { random, byHand, back, follows, unset, shown, editor, named,
                reviewed: !!reviewed, review, done: !!done, config, sides, badge, meta, drawn };
            return Object.values(all).every(Boolean) || JSON.stringify(all);
        })()
    """)
    assert result is True, f'The draw, the standard and an entrant ability {result}'
    result = client.evaluate(r"""
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
            const main = () => page.mainHost;
            const spoilers = await import('./js/core/spoilers.js');
            const { api } = await import('./js/core/api.js');
            const config = {
                name: 'Quiet cup', seed: 8, seeding: 'manual',
                entrants: [0.2, 0.4, 0.6, 0.8].map((ability) => ({ kind: 'builtin', ability })),
                stages: [{ format: 'knockout', settle: ['lots'] }],
            };
            const made = await fetch('/api/tournaments', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ config }),
            }).then((r) => r.json());
            cuju.showPage('tournaments');
            await page.refresh();
            await page.open(made.id);
            await until(() => page.current && page.current.state === 'done');
            const full = !!main().querySelector('.cup-champion')
                && main().querySelectorAll('.cup-goals').length === 6;
            // Without spoilers, nothing that a played match decided shows.
            main().querySelector('.cup-spoiler-switch').click();
            const masked = await until(() => page.current && page.current.spoilers
                && main().querySelector('.cup-watch-next'));
            const noChampion = !main().querySelector('.cup-champion')
                && !page.root.querySelector('.cup-item.active .cup-item-champion')
                && !!page.root.querySelector('.cup-item.active .cup-item-spoilers')
                && !main().querySelector('[data-focus="act-ceremony"]');
            const noScores = !main().querySelector('.cup-goals');
            const unseen = main().querySelectorAll('.cup-fixture.state-unseen').length === 2
                && page.current.spoilers.unseen.length === 2;
            const recording = page.current.matches[0].unseen.match;
            const listed = (await api.matches()).find((m) => m.id === recording);
            const lists = !!listed && listed.score === null && listed.spoiler === true
                && listed.teams.length === 0;
            // Watch next plays the first semi-final, and its end marks it watched.
            const first = page.current.spoilers.unseen[0];
            main().querySelector('.cup-watch-next').click();
            const opened = await until(() => cuju.page === 'watch' && cuju.source
                && cuju.source.id === recording, 15000);
            cuju.timeline.pause();
            document.dispatchEvent(new CustomEvent('cuju:recording-ended',
                { detail: { id: recording, provenance: cuju.source.header.provenance || null } }));
            const card = await until(() => document.querySelector('#page-watch .cup-intermission'));
            const marked = spoilers.watchedKeys(made.id).includes(first);
            const box = () => document.querySelector('.cup-intermission');
            const named = !!card && /Next match/.test(box().querySelector('h2').textContent)
                && !/\d+ to \d+/.test(box().textContent);
            const focused = !!card && box().contains(document.activeElement);
            document.activeElement.dispatchEvent(
                new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            const closed = !box();
            cuju.showPage('tournaments');
            await page.open(made.id);
            const shown = main().querySelectorAll('.cup-goals').length === 2
                && page.current.spoilers.unseen.length === 1;
            // Reveal shows one result on purpose, and the final comes up next with its own card.
            main().querySelector('[data-focus^="unseen-reveal-"]').click();
            const final = await until(() => main().querySelector('.cup-kickoff.final'));
            main().querySelector('.cup-kickoff.final .cup-predict button').click();
            await until(() => main().querySelector('.cup-kickoff.final [aria-pressed="true"]'));
            // Reveal all asks first, Escape keeps the results hidden, and Reveal shows them.
            main().querySelector('[data-focus="reveal-all"]').click();
            const asked = !!main().querySelector('.cup-spoilers .cup-confirm');
            document.activeElement.dispatchEvent(
                new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            const kept = !main().querySelector('.cup-confirm')
                && !main().querySelector('.cup-champion');
            main().querySelector('[data-focus="reveal-all"]').click();
            main().querySelector('[data-focus="reveal-yes"]').click();
            const revealed = await until(() => main().querySelector('.cup-champion')
                && page.current.spoilers.hidden === 0);
            const score = main().querySelector('.cup-prediction-score');
            const scored = /Predictions: \d of 1 right/.test(score ? score.textContent : '');
            const unhidden = (await api.matches()).find((m) => m.id === recording);
            const back = !!unhidden && Array.isArray(unhidden.score);
            // The Brackets view shows the stage large, zooms and goes back.
            main().querySelector('[data-focus="act-brackets"]').click();
            const big = await until(() => page.mode === 'brackets'
                && main().querySelector('.cup-big .cup-bracket .cup-fixture'));
            const wide = page.root.querySelector('.cup-layout').classList.contains('brackets');
            main().querySelector('[data-focus="zoom-in"]').click();
            const zoomed = /--cup-zoom: 1.1/
                .test(main().querySelector('.cup-big').getAttribute('style'));
            main().querySelector('[data-focus="brackets-back"]').click();
            const left = page.mode === 'view' && !page.root.querySelector('.cup-layout.brackets');
            spoilers.setSpoilerFree(made.id, false);
            await fetch(`/api/tournaments/${made.id}`, { method: 'DELETE' });
            page.mode = 'empty';
            page.openId = null;
            await page.refresh();
            const all = { full, masked, noChampion, noScores, unseen, lists, opened: !!opened,
                card: !!card, marked,
                named, focused, closed, shown, final: !!final, asked, kept, revealed: !!revealed,
                scored, back, big: !!big, wide, zoomed, left };
            return Object.values(all).every(Boolean) || JSON.stringify(all);
        })()
    """)
    assert result is True, f'A tournament without spoilers and its Brackets view {result}'
    return 6


def tournament_play_checks(client, debug, port):
    """Checks Play now for a person's match of a tournament on a fresh page, and the pause menu.

    A page opened on Tournaments has nothing on Watch, and Play still takes up the game's stream
    once it shows. The pause menu's Controls then takes the focus, Esc closes the card before the
    menu, and a game that ends for the page's silence says so on its end card. The tab is a fresh
    one of its own, and the game's routes answer from the page with a live source of the mock.
    """
    tab = page_feed._Tab(client, debug, CDP, 800, 600)
    try:
        tab.tab.call(
            'Page.addScriptToEvaluateOnNewDocument',
            {
                'source': """
            localStorage.setItem('cuju.muted', 'true');
            localStorage.setItem('cuju.quality', '"low"');
            localStorage.setItem('cuju.tips', '{"off": true}');
            // The offer to install the page stays away unless a check asks for it.
            if (localStorage.getItem('cuju.installOffer') === null) {
                localStorage.setItem('cuju.installOffer', '{"dismissed": true}');
            }
            Element.prototype.requestPointerLock = function () {
                throw new Error('Pointer capture refused by the page check.');
            };
        """
            },
        )
        tab.open(f'http://127.0.0.1:{port}/#page=tournaments')
        deadline = time.monotonic() + 90
        while not tab.evaluate(
            "!!(window.cuju && cuju.tournaments && cuju.page === 'tournaments')"
        ):
            if time.monotonic() > deadline:
                raise RuntimeError('The fresh page did not open Tournaments.')
            time.sleep(0.25)
        result = tab.evaluate("""
            (async () => {
                const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                const until = async (test, ms = 60000) => {
                    for (let t = 0; t < ms; t += 100) {
                        if (test()) {
                            return true;
                        }
                        await wait(100);
                    }
                    return false;
                };
                const { api } = await import('./js/core/api.js');
                const { tournamentsApi } = await import('./js/play/tournament.js');
                const sources = await api.live();
                const empty = !cuju.source;
                let entry = { id: sources[0].id, state: 'ready', score: [0, 0] };
                const streams = [];
                tournamentsApi.action = async () => entry;
                api.gameStream = (id, signal) => {
                    streams.push(id);
                    return api.liveStream(id, signal);
                };
                api.pauseGame = async (id, paused) => {
                    entry = { ...entry, state: paused ? 'paused' : 'playing' };
                    return entry;
                };
                api.gameInput = async () => entry;
                api.game = async () => entry;
                api.quitGame = async () => {
                    entry = { ...entry, state: 'ended', ending: 'timeout' };
                    return entry;
                };
                const page = cuju.tournaments;
                page.current = { id: 'cup-page-check', name: 'Page check cup' };
                await page.playMatch({ key: 'final', persons: [true, false], label: 'Final' });
                const started = await until(() => cuju.play && cuju.play.game
                    && cuju.play.game.started, 40000);
                const streamed = streams.length === 1 && cuju.page === 'play';
                if (!started) {
                    return JSON.stringify({ empty, started, streams: streams.length });
                }
                const play = cuju.play;
                play.pause(true);
                await wait(200);
                play.controlsButton.click();
                const card = play.card;
                const focused = await until(() => card.contains(document.activeElement)
                    && card.getAttribute('role') === 'dialog', 5000);
                const where = (node) => node && `${node.tagName}.${node.className}`;
                const held = { active: where(document.activeElement),
                    role: card.getAttribute('role'), modal: card.getAttribute('aria-modal'),
                    hidden: card.hidden };
                document.activeElement.dispatchEvent(new KeyboardEvent('keydown',
                    { key: 'Escape', code: 'Escape', bubbles: true }));
                await wait(200);
                const closed = card.hidden && !play.menu.hidden
                    && document.activeElement === play.controlsButton;
                await play.quit();
                const silent = await until(() => /heard nothing from this page/
                    .test(play.endPanel.innerText), 10000);
                if (play.game && play.game.source) {
                    play.game.source.live.stop();
                }
                play.showSetup();
                const all = { empty, started, streamed, focused, closed, silent,
                    unlocked: !document.pointerLockElement };
                return Object.values(all).every(Boolean) || JSON.stringify({ ...all, held,
                    after: where(document.activeElement) });
            })()
        """)
    finally:
        errors = tab.close()
    assert result is True, f'Play now of a tournament on a fresh page {result}'
    assert not errors, errors
    return 1


def surprise_checks(client):
    """Checks Surprise me in the team editor, in the form that adds a team and for scripts."""
    result = client.evaluate("""
        (async () => {
            const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            const { api } = await import('./js/core/api.js');
            cuju.showPage('teams');
            const source = 'def agent(obs):\\n    return [0]\\n';
            const team = await api.uploadTeam('Plain', 'main.py', source, '5v5');
            await cuju.library.refresh();
            cuju.library.root.querySelector(`li[data-id="${team.id}"]`).click();
            const editor = cuju.editor;
            for (let i = 0; i < 200 && !(editor.team && editor.team.id === team.id
                && editor.initial !== undefined); i++) {
                await wait(50);
            }
            editor.showSection('kit');
            const panel = editor.formHost.querySelector('.surprise-panel');
            const seedField = panel.querySelector('.surprise-seed');
            const styleField = panel.querySelector('.surprise-style');
            seedField.value = 'harbor';
            seedField.dispatchEvent(new Event('input', { bubbles: true }));
            styleField.value = 'stripes';
            styleField.dispatchEvent(new Event('change', { bubbles: true }));
            panel.querySelector('.surprise-go').click();
            await wait(0);
            const kit = JSON.stringify(editor.style.kit);
            const filled = editor.style.kit.pattern === 'stripes' && editor.name !== 'Plain'
                && /^[A-Z]{1,3}$/.test(editor.style.badge) && editor.style.players.length === 5
                && editor.style.players.every((p) => p.name.length > 1);
            const dirty = editor.dirty && !editor.dirtyNote.hidden;
            const focused = !!document.activeElement
                && document.activeElement.classList.contains('surprise-go');
            const note = editor.formHost.querySelector('.surprise-note').textContent
                .includes('seed harbor');
            editor.showSection('identity');
            const again = editor.formHost.querySelector('.surprise-panel');
            const kept = again.querySelector('.surprise-seed').value === 'harbor'
                && again.querySelector('.surprise-style').value === 'stripes';
            const named = editor.formHost.querySelector('.grid2 input[type=text]').value
                === editor.name;
            editor.style.kit.primary = [1, 2, 3];
            again.querySelector('.surprise-go').click();
            await wait(0);
            const same = JSON.stringify(editor.style.kit) === kit;
            const scripted = cuju.surprise({ seed: 'harbor', style: 'stripes' });
            const matches = JSON.stringify(scripted.style.kit) === kit
                && scripted.name === editor.name && scripted.style.players.length === 5
                && scripted.kitStyle === 'stripes';
            const neon = cuju.surprise({ seed: 'agent', style: 'neon', apply: true });
            await wait(0);
            const applied = editor.style.kit.pattern === 'plain'
                && JSON.stringify(editor.style.kit) === JSON.stringify(neon.style.kit)
                && editor.dirty;
            const closed = editor.close(true) && !editor.isOpen;
            const unsaved = (await api.teams()).find((t) => t.id === team.id).name === 'Plain';
            const refused = (() => {
                try {
                    cuju.surprise({ seed: 1, apply: true });
                    return false;
                } catch (err) {
                    return /editor/.test(err.message);
                }
            })();
            const other = cuju.surprise({ seed: 'script', style: 'sash', format: '5v5' });
            const saved = await api.updateTeam(team.id, { name: other.name, style: other.style });
            const stored = saved.name === other.name
                && JSON.stringify(saved.style.kit) === JSON.stringify(other.style.kit)
                && JSON.stringify(saved.style.goalkeeper) === JSON.stringify(other.style.goalkeeper)
                && saved.style.badge === other.badge && saved.style.number === other.style.number
                && saved.style.players[0].name === other.style.players[0].name;
            const form = cuju.library.upload;
            const name = form.querySelector('input[type=text]');
            name.value = '';
            form.querySelector('.surprise-add .surprise-go').click();
            const told = form.querySelector('.surprise-add .surprise-note').textContent;
            const add = name.value.length > 2 && !!form.querySelector('.surprise-add .kit-shirt')
                && /seed \\d{6}/.test(told);
            const seed = told.match(/seed (\\d{6})/)[1];
            const expected = JSON.stringify(cuju.surprise({ seed }).style.kit);
            const file = form.querySelector('input[type=file][accept]');
            const transfer = new DataTransfer();
            transfer.items.add(new File([source], 'main.py'));
            file.files = transfer.files;
            file.dispatchEvent(new Event('change'));
            const chosen = name.value;
            form.requestSubmit();
            let added = null;
            for (let i = 0; i < 100 && !added; i++) {
                await wait(50);
                added = (await api.teams()).find((t) => t.name === chosen
                    && JSON.stringify(t.style.kit) === expected);
            }
            const reset = !form.querySelector('.surprise-add .kit-shirt') && name.value === '';
            if (added) {
                await api.deleteTeam(added.id);
            }
            await api.deleteTeam(team.id);
            await cuju.library.refresh();
            const all = { filled, dirty, focused, note, kept, named, same, matches, applied, closed,
                unsaved, refused, stored, add, added: !!added, reset };
            return Object.values(all).every(Boolean) || JSON.stringify(all);
        })()
    """)
    assert result is True, f'Surprise me {result}'
    return 1


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


def ui_a11y_checks(client):
    """Checks the names, headings, live regions and status lines that screen readers rely on."""
    result = client.evaluate("""
        (async () => {
            const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            const all = {};
            const seek = ['back-30', 'back-5', 'forward-5', 'forward-30'].map((act) =>
                document.querySelector(`[data-act="${act}"]`).getAttribute('aria-label'));
            all.seek = seek.join() === [
                'Back 30 seconds', 'Back 5 seconds', 'Forward 5 seconds', 'Forward 30 seconds',
            ].join();
            const clock = document.getElementById('clock');
            all.clock = clock.getAttribute('role') === 'timer'
                && clock.getAttribute('aria-live') === 'off';
            const shown = (node) => !node.closest('[hidden]')
                && (node.getClientRects().length > 0 || node.classList.contains('sr-only'));
            const bad = [];
            const pages = ['play', 'challenges', 'recordings', 'matches', 'tournaments', 'teams',
                'field', 'help'];
            for (const page of pages) {
                cuju.showPage(page);
                await wait(700);
                const levels = [...document.querySelectorAll(
                    '#pages h1, #pages h2, #pages h3, #pages h4, #pages h5, #pages h6')]
                    .filter(shown).map((node) => Number(node.tagName[1]));
                const skips = levels.some((level, i) => i > 0 && level > levels[i - 1] + 1);
                const ones = levels.filter((level) => level === 1).length;
                if (levels[0] !== 1 || ones !== 1 || skips) {
                    bad.push(`${page} ${levels.join('')}`);
                }
            }
            all.headings = bad.length === 0 || bad.join(' ');
            const doctor = await import('./js/help/doctor.js');
            const status = doctor.reportStatus({ server: { checks: [
                { name: 'home folder', ok: true, detail: 'fine' },
                { name: 'video export', ok: true, warning: true, detail: 'missing' },
            ] } });
            all.warning = status === 'The report is ready. 1 check warns, video export.' || status;
            // English ships alone, so the palette offers no other language until one is imported.
            all.language = !cuju.palette.actions()
                .some((action) => action.title.startsWith('Language, '));
            cuju.showPage('home');
            return all;
        })()
    """)
    for name, value in result.items():
        assert value is True, (name, value)
    return len(result)


def address_checks(client):
    """Checks that the address of Watch shows a recording by its title, with its id as the tooltip
    and as the text to edit once the field takes the focus."""
    result = client.evaluate("""
        (async () => {
            const { api } = await import('./js/core/api.js');
            const { recordingTitle } = await import('./js/core/names.js');
            const input = document.getElementById('address-input');
            const list = await api.matches();
            const id = list[0].id;
            cuju.showPage('watch');
            await cuju.openMatch(id);
            cuju.timeline.pause();
            input.blur();
            const title = recordingTitle(cuju.source.header, id);
            const shown = !!title && input.value === title && input.title === id;
            // A page without the focus of the system hears no focus events, so they are sent.
            input.focus();
            input.dispatchEvent(new FocusEvent('focus'));
            const editing = input.value === id;
            input.blur();
            input.dispatchEvent(new FocusEvent('blur'));
            const back = input.value === title;
            // Enter on the title opens the recording itself.
            let opened = null;
            const open = cuju.openAddress;
            cuju.openAddress = (value) => {
                opened = value;
            };
            document.getElementById('address').requestSubmit();
            cuju.openAddress = open;
            const all = { shown, editing, back, submit: opened === id };
            return Object.values(all).every(Boolean) || JSON.stringify({ ...all, title,
                value: input.value });
        })()
    """)
    assert result is True, f'The address of Watch {result}'
    return 1


def hash_checks(client):
    """Checks that a page beside Watch keeps its hash still and opens a hash typed into it."""
    result = client.evaluate("""
        (async () => {
            const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            const id = (await (await fetch('/api/matches')).json())[0].id;
            await cuju.openMatch(id);
            await wait(500);
            cuju.showPage('tournaments');
            const replace = history.replaceState;
            let writes = 0;
            history.replaceState = function (...args) {
                writes += 1;
                return replace.apply(this, args);
            };
            try {
                await wait(1000);
                const still = writes <= 1 && location.hash === '#page=tournaments';
                location.hash = `#match=${encodeURIComponent(id)}&t=3`;
                await wait(1500);
                const opened = cuju.page === 'watch' && cuju.source && cuju.source.id === id;
                return { still: still || writes, opened };
            } finally {
                history.replaceState = replace;
                cuju.showPage('home');
            }
        })()
    """)
    for name, value in result.items():
        assert value is True, ('hash', name, value)
    return len(result)


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
            const shown = await wait(() => !tip.hidden && !!tip.querySelector('kbd.chord'));
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


def presentation_checks(client, port):
    """Imports the test package, plays a match of it and checks its sandbox, epochs and bounds."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
    from support.package import package_zip

    address = f'http://127.0.0.1:{port}'
    upload = urllib.request.Request(
        f'{address}/api/teams?name=Test%20package&filename=team.zip&format=5v5',
        data=package_zip(),
        method='POST',
    )
    with urllib.request.urlopen(upload, timeout=30) as response:
        team = json.load(response)
    match = client.evaluate(f"""
        (async () => {{
            const {{ api }} = await import('./js/core/api.js');
            const spec = {{ left: '{team['id']}', right: 'builtin', scenario: '5_vs_5' }};
            const request = await api.requestMatch(spec);
            let match = null;
            for (let i = 0; i < 200 && !match; i++) {{
                await new Promise((resolve) => setTimeout(resolve, 100));
                const items = await (await fetch('/api/requests')).json();
                const item = items.find((r) => r.id === request.id);
                match = item && item.state === 'done' ? (item.match.id || item.match) : null;
            }}
            return match;
        }})()
    """)
    # A slow headless browser loads a package for a while, so the match opens in a call of its own.
    client.evaluate(f"""
        (async () => {{
            // A headless browser draws slowly, so the team's time budget stays out of the check.
            cuju.presentation.settings.metering = false;
            await cuju.openMatch('{match}');
            return true;
        }})()
    """)
    result = client.evaluate(f"""
        (async () => {{
            const served = await (await fetch('/api/teams/{team['id']}/presentation')).json();
            cuju.showPage('watch');
            cuju.director.stop(false);
            cuju.timeline.play(1);
            const status = () => cuju.presentation.status();
            for (let i = 0; i < 300; i++) {{
                const p = status().packages[0];
                if (p && p.lastResponse && p.answered > 3) {{
                    break;
                }}
                await new Promise((resolve) => setTimeout(resolve, 100));
            }}
            const before = status();
            const epoch = before.epoch;
            cuju.timeline.t = cuju.timeline.first + 40;
            cuju.afterSeek();
            await new Promise((resolve) => setTimeout(resolve, 600));
            const after = status();
            const keeper = after.entities.find((e) => e.goalkeeper);
            const field = after.entities.find((e) => !e.goalkeeper);
            const k = Number(field.id.slice(1));
            return {{
                served: !!served.manifest,
                pkg: before.packages[0],
                epochs: [epoch, after.epoch, after.reset.reason],
                drivers: [keeper && keeper.driver, field.driver],
                attachments: field.attachments,
                bounds: field.bounds,
                height: cuju.players.height(k),
                frames: after.packages[0].answered,
                log: after.packages[0].log,
                sandboxes: document.querySelectorAll('iframe[sandbox="allow-scripts"]').length,
                commands: after.dropped.commands,
            }};
        }})()
    """)
    pkg = result['pkg']
    assert result['served'] and pkg and pkg['status'] == 'ready', result
    assert pkg['sealed'] == {'network': 'blocked', 'storage': 'blocked'}, result
    assert pkg['level'] == 'worker' and pkg['lacking'] == ['audio.spatial'], result
    assert result['epochs'][1] > result['epochs'][0] and result['epochs'][2] == 'seek', result
    assert result['drivers'] == ['grf+layers', 'team'], result
    assert result['attachments'] == ['halo'], result
    assert result['bounds'] == {'radius': 0.5, 'height': 2.0}, result
    assert result['frames'] > 3 and result['sandboxes'] == 1, result
    assert any('seek' in line for line in result['log']) or result['log'], result
    extra = effects_checks(client, team)
    # A chunks shader that does not compile is named, and its materials stay standard.
    shader = client.evaluate("""
        (async () => {
            const THREE = await import('three');
            const p = cuju.presentation;
            const pkg = p.packages[0];
            const material = new THREE.MeshStandardMaterial();
            const options = (file, source) => ({ shared: p.uniforms[0], seed: 1, source,
                spec: null, textures: null, key: `0:${file}` });
            const compile = (file, source) => p.chunksCompile(pkg, file, material,
                options(file, source));
            const hook = 'vec3 cujuEmissive(vec3 e, vec2 uv) { return e';
            const good = compile('check/good.glsl', `${hook}; }`);
            const bad = compile('check/bad.glsl', `${hook} + ; }`);
            const { previewSide } = await import('./js/presentation/preview.js');
            return { good, bad, error: pkg.errors.includes('shader check/bad.glsl did not compile'),
                notice: [...p.statusShown].some((t) => t.includes('did not compile')),
                sides: [previewSide('left'), previewSide('right'), previewSide('1')] };
        })()
    """)
    assert shader == {
        'good': True,
        'bad': False,
        'error': True,
        'notice': True,
        'sides': [0, 1, None],
    }, shader
    # The worker gone, the page keeps drawing its manifest's look and says why.
    result = client.evaluate("""
        (async () => {
            const pkg = cuju.presentation.packages[0];
            // A worker that a loaded machine starved may still be restarting, so the check waits
            // for it to answer before it ends it.
            const end = performance.now() + 30000;
            while (pkg.host.status !== 'ready' && performance.now() < end) {
                await new Promise((resolve) => setTimeout(resolve, 100));
            }
            pkg.host.fail('test', true);
            await new Promise((resolve) => setTimeout(resolve, 300));
            const s = cuju.presentation.status();
            return { status: s.packages[0].status, level: s.packages[0].budget.level,
                pkgLevel: s.packages[0].level, detail: s.packages[0].detail,
                notice: [...cuju.presentation.statusShown]
                    .some((t) => t.startsWith('The worker of')),
                entities: s.entities.length,
                sandboxes: document.querySelectorAll('iframe[sandbox="allow-scripts"]').length };
        })()
    """)
    assert result == {
        'status': 'failed',
        'level': 'noWorker',
        'pkgLevel': 'manifest',
        'detail': 'test',
        'notice': True,
        'entities': 5,
        'sandboxes': 0,
    }, result
    return 10 + extra


# Posts a start to a sandbox window `w` with a port and reports whether a worker ever answered.
_SANDBOX_START = """
    (async (w) => {
        const channel = new MessageChannel();
        const answers = [];
        channel.port1.onmessage = (e) => answers.push(e.data && e.data.type);
        const module = 'export function init() {}';
        try {
            w.postMessage({ type: 'start', module, instanceId: 1 }, '*', [channel.port2]);
        } catch (err) {
            answers.push('unreachable');
        }
        channel.port1.postMessage({ type: 'hello', hello: { instanceId: 1 }, probe: 'x:' });
        await new Promise((resolve) => setTimeout(resolve, 2000));
        return answers.filter((type) => type !== 'unreachable');
    })
"""


def sandbox_top_checks(client, port, debug):
    """Opens the sandbox of team workers as a whole window, as another site could.

    It has an opaque origin there, holds no cache or storage of the server, and starts no worker
    for a message of its own window or of the page that opened it.
    """
    address = f'http://127.0.0.1:{port}'
    created = client.call('Target.createTarget', {'url': f'{address}/sandbox/presentation'})
    tab = CDP(f'ws://127.0.0.1:{debug}/devtools/page/{created["targetId"]}')
    try:
        tab.call('Runtime.enable')
        for _ in range(100):
            if tab.evaluate("document.readyState === 'complete'"):
                break
            time.sleep(0.1)
        alone = tab.evaluate(f"""
            (async () => {{
                let caches = 'blocked';
                try {{
                    await self.caches.keys();
                    caches = 'open';
                }} catch (err) {{
                    caches = 'blocked';
                }}
                let storage = 'blocked';
                try {{
                    localStorage.length;
                    storage = 'open';
                }} catch (err) {{
                    storage = 'blocked';
                }}
                const answers = await ({_SANDBOX_START})(window);
                return {{ origin: self.origin, top: window.parent === window, caches, storage,
                    answers }};
            }})()
        """)
    finally:
        tab.socket.close()
        client.call('Target.closeTarget', {'targetId': created['targetId']})
    assert alone == {
        'origin': 'null',
        'top': True,
        'caches': 'blocked',
        'storage': 'blocked',
        'answers': [],
    }, alone
    # The page opens the route in a window of its own and posts a start, as another site would.
    before = {t['targetId'] for t in client.call('Target.getTargets')['targetInfos']}
    opened = client.call(
        'Runtime.evaluate',
        {
            'expression': f"""
                (async () => {{
                    const w = window.open('/sandbox/presentation', '_blank');
                    // The window parts from the page once the sandbox's answer arrives.
                    for (let i = 0; i < 100 && w && !w.closed; i++) {{
                        await new Promise((resolve) => setTimeout(resolve, 100));
                    }}
                    const answers = w ? await ({_SANDBOX_START})(w) : [];
                    return {{ opened: !!w, severed: !w || w.closed, answers }};
                }})()
            """,
            'returnByValue': True,
            'awaitPromise': True,
            'userGesture': True,
        },
    )['result']['value']
    for target in client.call('Target.getTargets')['targetInfos']:
        if target['targetId'] not in before and target['type'] == 'page':
            client.call('Target.closeTarget', {'targetId': target['targetId']})
    # The page's own tab comes back to the front, since a tab behind another starts its frames late.
    client.call('Page.bringToFront')
    assert opened['answers'] == [] and opened['severed'], opened
    return 2


# A worker module that reports what it reaches of the GPU and of the wrapper around it.
_WORKER_PROBE = """
let hello = null;
export function init(h) { hello = h; }
export function frame(f) {
    const kind = (canvas, name) => {
        const context = canvas.getContext(name);
        return context && Object.prototype.toString.call(context).slice(8, -1);
    };
    const slot = hello.canvases && hello.canvases.badge;
    const seen = {
        webgl2: kind(new OffscreenCanvas(8, 8), 'webgl2'),
        webgl: kind(new OffscreenCanvas(8, 8), 'webgl'),
        bitmap: kind(new OffscreenCanvas(8, 8), 'bitmaprenderer'),
        webgpu: kind(new OffscreenCanvas(8, 8), 'webgpu'),
        slotWebgl2: slot ? kind(slot, 'webgl2') : 'no slot',
        twoD: kind(new OffscreenCanvas(8, 8), '2d'),
        gpu: typeof navigator.gpu, worker: typeof Worker,
        wrapper: [typeof port, typeof canvases, typeof instanceId, typeof reply, typeof listen],
    };
    const before = OffscreenCanvas.prototype.getContext;
    try { OffscreenCanvas.prototype.getContext = () => 'mine'; } catch (err) { /* refused */ }
    try { Object.defineProperty(OffscreenCanvas.prototype, 'getContext', { value: () => 'mine' }); }
    catch (err) { /* refused */ }
    seen.replaced = OffscreenCanvas.prototype.getContext !== before;
    return { log: [JSON.stringify(seen)] };
}
"""
# Worker modules that answer with a bitmap the host refuses, a slot's canvas grown past its size
# and a large bitmap outside any slot.
_WORKER_GROWN = """
let hello = null;
export function init(h) { hello = h; }
export function frame(f) {
    const slot = hello.canvases.badge;
    slot.width = 2000;
    slot.getContext('2d').fillRect(0, 0, 2000, 96);
    return { overlays: [{ slot: 'badge', op: 'draw' }] };
}
"""
_WORKER_LOOSE = """
export function frame(f) {
    const canvas = new OffscreenCanvas(3000, 3000);
    canvas.getContext('2d').fillRect(0, 0, 3000, 3000);
    return { log: [], extra: { picture: canvas.transferToImageBitmap() } };
}
"""
# Runs a module in a ModuleHost of the page for one Frame and reports the answer and the statuses.
# A page that has drawn for the whole check starts a sandbox slowly, so each wait lasts 30 seconds.
_RUN_WORKER = """
    (async (source) => {
        const { ModuleHost } = await import('./js/presentation/host.js');
        let answer = null;
        const statuses = [];
        const host = new ModuleHost({
            source, instanceId: 'probe.1',
            hello: { type: 'hello', instanceId: 'probe.1', slots: ['badge'] },
            onResponse: (m) => { answer = m; },
            onStatus: (status, detail) => statuses.push([status, detail]),
        });
        for (let i = 0; i < 300 && host.status !== 'ready'; i++) {
            await new Promise((resolve) => setTimeout(resolve, 100));
        }
        const ready = host.status;
        const seen = { hidden: document.hidden, frames: document.querySelectorAll('iframe').length,
            frame: !!host.frame, port: !!host.port };
        host.send({ epoch: 0, frameId: 1, events: [], players: [] });
        for (let i = 0; i < 300 && !answer && host.status === 'ready'; i++) {
            await new Promise((resolve) => setTimeout(resolve, 100));
        }
        host.dispose();
        return ready === 'ready' ? { ready, log: answer && answer.log, statuses }
            : { ready, log: answer && answer.log, statuses, seen };
    })
"""


def worker_checks(client):
    """Runs worker modules in the page's sandbox and checks what they reach and what they send.

    A module's own canvases and its slot's canvas give no WebGL, WebGPU or bitmap context, only 2d,
    it cannot put back the canvas's getContext, and it finds neither navigator.gpu, Worker nor any
    binding of the wrapper around it. A bitmap of a slot grown past the slot's size, or a bitmap
    outside the overlays, ends the worker as a failure.
    """

    def run(source):
        # A loaded machine may leave a sandbox without its answer for a while, so a run that
        # heard nothing and saw no failure runs once more.
        for _ in range(2):
            result = client.evaluate(f'({_RUN_WORKER})({json.dumps(source)})')
            if result['log'] is not None or len(result['statuses']) > 2:
                break
        return result

    result = run(_WORKER_PROBE)
    assert result['ready'] == 'ready' and result['log'], result
    assert json.loads(result['log'][0]) == {
        'webgl2': None,
        'webgl': None,
        'bitmap': None,
        'webgpu': None,
        'slotWebgl2': None,
        'twoD': 'OffscreenCanvasRenderingContext2D',
        'gpu': 'undefined',
        'worker': 'undefined',
        'wrapper': ['undefined'] * 5,
        'replaced': False,
    }, result
    for source, reason in (
        (_WORKER_GROWN, 'a bitmap of 2000 by 96 pixels for the slot badge'),
        (_WORKER_LOOSE, 'a bitmap outside its slot'),
    ):
        result = run(source)
        assert result['ready'] == 'ready' and result['log'] is None, result
        assert ['restarting', f'the worker answered with {reason}'] in result['statuses'], result
    return 3


# A package worklet that imports the renderer's loudness module and turns its governor and its
# limiter off, as a module past the server's check could.
_WORKLET_ATTACK = b"""
import { Governor, Limiter } from '/js/presentation/loudness.js';
Governor.prototype.update = function () { return 0; };
Limiter.prototype.process = function (inputs, outputs) {
    for (let c = 0; c < outputs.length; c++) outputs[c].set(inputs[Math.min(c, inputs.length - 1)]);
};
class TestHum extends AudioWorkletProcessor { process() { return true; } }
registerProcessor('test-hum', TestHum);
"""


def worklet_checks(client, port):
    """Loads a package worklet that turns the governor off, apart from the page's processors.

    In a context of its own, as the page loads a team's worklet, the module leaves the renderer's
    governor and limiter as they are, and a loud square wave comes out governed. Loaded into the
    renderer's own scope, the same module turns them off, which the check also shows, so it proves
    the separation and not a module that does nothing. Both render offline, so nothing sounds.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
    from support.package import package_zip

    upload = urllib.request.Request(
        f'http://127.0.0.1:{port}/api/teams?name=Loud%20package&filename=team.zip&format=5v5',
        data=package_zip('Loud package', {'cuju-team/presentation/audio/hum.js': _WORKLET_ATTACK}),
        method='POST',
    )
    with urllib.request.urlopen(upload, timeout=30) as response:
        team = json.load(response)
    result = client.evaluate(f"""
        (async () => {{
            const {{ WORKLET, FREEZE }} = await import('./js/presentation/teamaudio.js');
            const {{ SAFETY }} = await import('./js/presentation/commands.js');
            const L = SAFETY.loudness;
            const url = '/api/teams/{team['id']}/presentation/audio/hum.js';
            const type = (await fetch(url)).headers.get('Content-Type');
            const rate = 48000;
            const render = async (shared) => {{
                const ctx = new OfflineAudioContext(2, rate * 4, rate);
                await ctx.audioWorklet.addModule(WORKLET);
                await ctx.audioWorklet.addModule(FREEZE);
                if (shared) {{
                    await ctx.audioWorklet.addModule(url);
                }} else {{
                    const own = new OfflineAudioContext(2, 128, rate);
                    await own.audioWorklet.addModule(url);
                }}
                const square = ctx.createOscillator();
                square.type = 'square';
                square.frequency.value = 220;
                const level = ctx.createGain();
                level.gain.value = 0.5;
                const governor = new AudioWorkletNode(ctx, 'cuju-loudness', {{
                    processorOptions: {{ govern: true, shortTermCeiling: L.teamShortTerm,
                        momentaryCeiling: L.teamMomentary, channels: 2 }},
                    outputChannelCount: [2] }});
                const limiter = new AudioWorkletNode(ctx, 'cuju-limiter', {{
                    processorOptions: {{ ceiling: L.teamTruePeak }}, outputChannelCount: [2] }});
                square.connect(level).connect(governor).connect(limiter).connect(ctx.destination);
                square.start();
                const out = (await ctx.startRendering()).getChannelData(0);
                let peak = 0;
                for (let i = rate * 3; i < out.length; i++) {{
                    peak = Math.max(peak, Math.abs(out[i]));
                }}
                return Math.round(peak * 1000) / 1000;
            }};
            return {{ type, apart: await render(false), shared: await render(true) }};
        }})()
    """)
    assert result['type'] == 'text/javascript', result
    # Governed, the square's last second sits under half its level, about 10 dB down by then.
    # Ungoverned it keeps its level of 0.5.
    assert result['shared'] > 0.45 and result['apart'] < result['shared'] / 2, result
    return 1


def effects_checks(client, team):
    """Plays the effects, passes, moments, reach, slots and sides of contract 1.1 on the page.

    Each step is a call of its own, since a headless browser draws a frame in a second or more.
    """
    wait = 'const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));'
    first = client.evaluate(f"""
        (async () => {{
            {wait}
            const p = cuju.presentation;
            cuju.timeline.play(1);
            let s = p.status();
            for (let i = 0; i < 100 && !(s.geometries.length && s.moments.slots.length); i++) {{
                await wait(100);
                s = p.status();
            }}
            return {{ geometries: s.geometries, slots: s.moments.slots, layer: s.post.layers[0],
                keeper: s.entities.find((e) => e.goalkeeper).driver }};
        }})()
    """)
    assert first['geometries'] == ['0:shard'] and first['layer'] == 'outline', first
    assert first['keeper'] == 'grf+layers', first
    assert any(slot['slot'] == 'badge' for slot in first['slots']), first
    # The badge drawn white and black in turn at 30 Hz hides at its third flash, its sixth
    # drawing, as the worker's bitmaps reach it, while a steady badge shows.
    flashing = client.evaluate("""
        (async () => {
            const { SlotGuard } = await import('./js/presentation/flash.js');
            const p = cuju.presentation;
            const pkg = p.packages[0];
            const s = p.moments.slot(pkg, 'badge');
            s.guard = new SlotGuard();
            const draw = (colour) => {
                const canvas = new OffscreenCanvas(96, 96);
                const g = canvas.getContext('2d');
                g.fillStyle = colour;
                g.fillRect(0, 0, 96, 96);
                const bitmap = canvas.transferToImageBitmap();
                p.moments.overlay(pkg, { slot: 'badge', op: 'draw' }, bitmap);
                p.clocks.cosmetic += 1 / 30;
                p.moments.updateSlots();
                return !s.canvas.hidden;
            };
            const steady = [0, 1, 2, 3, 4, 5].map(() => draw('#808080')).every(Boolean);
            const shown = [];
            for (let i = 0; i < 30; i++) {
                shown.push(draw(i % 2 ? '#000000' : '#ffffff'));
            }
            const at = shown.indexOf(false);
            const after = p.status().moments;
            return { steady, at, stays: at > 0 && !shown.slice(at).some(Boolean),
                trips: after.slots.find((x) => x.team === 0 && x.slot === 'badge').trips,
                refused: after.refused.some((r) => r.includes('badge flashed past the limit')) };
        })()
    """)
    assert flashing['steady'] and flashing['at'] == 5, flashing
    assert flashing['stays'] and flashing['trips'] == 1 and flashing['refused'], flashing
    touch = client.evaluate(f"""
        (async () => {{
            {wait}
            const p = cuju.presentation;
            p.inject(0, 'touch');
            let s = p.status();
            for (let i = 0; i < 50 && !s.effects[0].particles; i++) {{
                await wait(100);
                s = p.status();
            }}
            return {{ particles: s.effects[0].particles, kinds: s.effects[0].kinds }};
        }})()
    """)
    assert touch['particles'] > 0 and {'particles', 'trail'} <= set(touch['kinds']), touch
    goal = client.evaluate(f"""
        (async () => {{
            {wait}
            const p = cuju.presentation;
            p.inject(0, 'goal');
            let s = p.status();
            for (let i = 0; i < 50 && !(s.effects[0].localLights && s.moments.environment); i++) {{
                await wait(100);
                s = p.status();
            }}
            const out = {{ kinds: s.effects[0].kinds, moments: s.post.moments.length,
                postRefused: s.post.refused,
                quality: s.packages[0].budget.quality,
                environment: s.moments.environment, accepted: s.moments.accepted,
                refused: s.moments.refused, local: s.effects[0].localLights }};
            // An opponent's goal starts nothing of the team's own moments.
            const before = s.moments.accepted.environment;
            p.inject(1, 'goal');
            out.foreign = p.status().moments.accepted.environment === before;
            // Reduced motion refuses camera and time suggestions.
            cuju.reducedMotion = true;
            p.moments.lastTime = [-Infinity, -Infinity];
            const shot = p.inject(0, 'shot');
            const time = {{ event: shot.id, freeze: 0.2 }};
            out.refusedMotion = p.moments.suggestTime(p.packages[0], time) === false;
            cuju.reducedMotion = false;
            out.flash = p.status().flash;
            out.safety = p.status().safety.version;
            return out;
        }})()
    """)
    assert {'light', 'mesh'} <= set(goal['kinds']), goal
    # A pass plays from medium quality up, and low quality records why it refused one.
    assert goal['moments'] >= 1 or (goal['quality'] == 'low' and goal['postRefused']), goal
    assert goal['accepted']['environment'] >= 1 and goal['environment'], goal
    assert goal['local'] >= 1 and goal['foreign'] and goal['refusedMotion'], goal
    assert goal['flash']['factor'] <= 1 and 'counts' in goal['flash'] and goal['safety'] == 2, goal
    bent = client.evaluate(f"""
        (async () => {{
            {wait}
            const p = cuju.presentation;
            cuju.timeline.play(1);
            for (let i = 0; i < 200; i++) {{
                if (p.status().bent) {{
                    return true;
                }}
                await wait(100);
            }}
            return false;
        }})()
    """)
    assert bent, 'the drawn ball bends through a contact'
    preview = client.evaluate(f"""
        (async () => {{
            {wait}
            const p = cuju.presentation;
            p.preview.open(0);
            const panel = !!document.getElementById('presentation-preview');
            document.querySelector('#presentation-preview [data-event="touch"]').click();
            await wait(600);
            const lines = document.querySelectorAll('#presentation-preview .preview-line').length;
            p.preview.close();
            return {{ panel, lines, closed: !document.getElementById('presentation-preview') }};
        }})()
    """)
    assert preview['panel'] and preview['lines'] > 5 and preview['closed'], preview
    sides = []
    for chosen in (team['id'], None):
        value = 'null' if chosen is None else f"'{chosen}'"
        sides.append(
            client.evaluate(f"""
            (async () => {{
                await fetch('/api/presentation/sides', {{ method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ right: {value} }}) }});
                await cuju.rebuildPlayers();
                const pkg = cuju.presentation.packages[1];
                const s = cuju.presentation.status();
                const right = s.entities.filter((e) => e.side === 1);
                const entry = (e) => cuju.players.packageEntry(Number(e.id.slice(1))) || {{}};
                const grf = right.filter((e) => entry(e).grf);
                const drivers = grf.every((e) => e.driver === 'grf');
                return [pkg ? pkg.teamId : null, right.length, grf.length, drivers];
            }})()
        """)
        )
    assert [side[0] for side in sides] == [team['id'], None], sides
    # The built-in AI draws GRF's figure, which carries the package chosen for its side.
    assert sides[0][1] == 5 and sides[0][2] >= 1 and sides[0][3], sides
    assert sides[1][1] == 0, sides
    assert client.evaluate("localStorage.getItem('cuju.muted')") == 'true'
    return 10


def motion_follows(client, reduced):
    """Waits a moment for the page to take up the system's motion preference and returns it."""
    want = 'true' if reduced else 'false'
    return client.evaluate(f"""
        (async () => {{
            for (let i = 0; i < 100 && cuju.reducedMotion !== {want}; i++) {{
                await new Promise((resolve) => setTimeout(resolve, 50));
            }}
            return cuju.reducedMotion;
        }})()
    """)


def motion_checks(client):
    """Checks that reduced motion keeps every show of a match with still cameras and fades."""
    import mock_sample

    # The waits are long because a loaded machine draws few frames a second and the shows move on
    # by their frames, and they end as soon as what they wait for happens.
    # A short 5 on 5 match with one goal near its end, so the lineups, the celebration and the
    # replays of the goal and the show after the match all play within a few seconds each. Where
    # the page draws few frames a second, the checks move the clock of a show on to its next shot.
    data = mock_sample.build_cjr(5, 300, 1, ('Greens', 'Golds'))[0]
    client.call(
        'Emulation.setEmulatedMedia',
        {'features': [{'name': 'prefers-reduced-motion', 'value': 'reduce'}]},
    )
    assert motion_follows(client, True), 'Reduced motion from the system'
    # Every frame of reduced motion, the log counts the frames of scripted shots, those that show
    # anything but the still the camera holds, and the stills, the frames of wipes and of fades,
    # and any flash, trail or confetti in sight.
    result = client.evaluate(
        f"const motionBytes = '{base64.b64encode(data).decode()}';"
        + """
        // A stinger moves on by the page's frames, so on a page that draws few frames a second
        // the checks move its clock on to the moment it covers the view.
        window.motionCover = () => {
            const sting = cuju.director.stingState;
            if (sting) sting.clock = Math.max(sting.clock, sting.seconds * 0.5);
            return false;
        };
        window.motionWait = async (test, ms = 30000) => {
            const end = performance.now() + ms;
            while (!test() && performance.now() < end) {
                await new Promise((resolve) => setTimeout(resolve, 50));
            }
            return !!test();
        };
        (async () => {
            const system = cuju.reducedMotion
                && document.getElementById('motion').value === 'system';
            const log = window.motionLog = {
                frames: 0, scripted: 0, eased: 0, stills: 0, sweeps: 0, fades: 0, flashes: 0,
                trails: 0, confetti: 0,
            };
            let held = null;
            const cams = cuju.cameras;
            const update = cams.update;
            cams.update = function (...args) {
                update.apply(this, args);
                // The frames between the two ways of reducing motion move in full.
                if (!cuju.reducedMotion) return;
                log.frames++;
                if (this.mode === 'scripted') {
                    log.scripted++;
                    const still = this.still;
                    if (!still || this.camera.position.distanceToSquared(still.pos) > 1e-8) {
                        log.eased++;
                    }
                    if (still !== held) {
                        log.stills++;
                        held = still;
                    }
                }
                const wipe = cuju.transition.wipe;
                if (wipe.shown) {
                    const fade = wipe.bands[1].style.transform === 'none'
                        && wipe.root.style.opacity !== '';
                    log[fade ? 'fades' : 'sweeps']++;
                }
                if (Number(cuju.decisions.flash.style.opacity || 0) > 0) log.flashes++;
                if (cuju.ball.trail.visible) log.trails++;
                const bits = cuju.podium.confettiMesh;
                if (bits && bits.visible) log.confetti++;
            };
            const bytes = Uint8Array.from(atob(motionBytes), (c) => c.charCodeAt(0));
            await cuju.openFile(new File([bytes], 'motion.cjr'));
            const lineups = await motionWait(() => !!cuju.director.lineup
                && !!document.getElementById('lineups') && cuju.cameras.mode === 'scripted');
            const frames = log.frames;
            await motionWait(() => log.frames > frames + 2, 5000);
            cuju.director.skip();
            return { system, lineups };
        })()
    """
    )
    assert all(result.values()), f'Reduced motion lineups {result}'
    result = client.evaluate("""
        (async () => {
            const director = cuju.director;
            const played = await motionWait(() => !director.running && cuju.timeline.playing,
                45000);
            const tl = cuju.timeline;
            const goal = window.motionGoal = tl.store.goals[0];
            if (!goal) return { played, goal: false };
            tl.seek(goal.index - 25);
            cuju.afterSeek();
            cuju.act('play');
            const scored = await motionWait(() => !!director.cel, 45000);
            return { played, goal: true, scored };
        })()
    """)
    assert all(result.values()), f'Reduced motion goal {result}'
    result = client.evaluate("""
        (async () => {
            const director = cuju.director;
            const shot = async (clock, stage) => {
                if (!director.cel) return false;
                director.cel.clock = Math.max(director.cel.clock, clock);
                return motionWait(() => !!director.cel && director.cel.stage >= stage
                    && cuju.cameras.mode === 'scripted');
            };
            // The close shot of the scorer and the orbit, each a still of its own.
            const close = await shot(1.35, 1);
            const seen = JSON.stringify({
                cel: director.cel ? [director.cel.stage, director.cel.clock] : null,
                mode: cuju.cameras.mode, seq: !!cuju.transition.seq, frames: motionLog.frames,
                t: cuju.timeline.t, speed: cuju.timeline.speed, playing: cuju.timeline.playing,
            });
            const stills = motionLog.stills;
            const orbit = await shot(3.95, 2);
            // The camera takes up the new still on its next frame, which comes late when slow.
            const cut = await motionWait(() => motionLog.stills > stills);
            return close ? { close, orbit, cut } : { close, orbit, cut, seen };
        })()
    """)
    assert all(result.values()), f'Reduced motion celebration {result}'
    result = client.evaluate("""
        (async () => {
            const director = cuju.director;
            director.skip();
            const replay = await motionWait(() => window.motionCover() || !!director.active
                && !!director.active.plan
                && director.active.phase === 'play' && cuju.timeline.playing, 100000);
            const frames = motionLog.frames;
            await motionWait(() => motionLog.frames > frames + 2, 5000);
            director.skip();
            return { replay };
        })()
    """)
    assert all(result.values()), f'Reduced motion replay {result}'
    result = client.evaluate("""
        (async () => {
            const show = cuju.postMatch;
            const running = await motionWait(() => show.running && !!show.react, 45000);
            return { running };
        })()
    """)
    assert all(result.values()), f'Reduced motion show {result}'
    result = client.evaluate("""
        (async () => {
            const show = cuju.postMatch;
            const r = show.react;
            if (!r) return { reactions: false };
            r.clock = Math.max(r.clock, r.titleAt + 0.7);
            const reactions = await motionWait(() => !!show.react && show.react.stage >= 1
                && cuju.cameras.mode === 'scripted');
            show.advance();
            const facts = await motionWait(() => show.steps[show.step] === 'facts'
                && !show.wiping, 15000);
            return { reactions, facts };
        })()
    """)
    assert all(result.values()), f'Reduced motion reactions and facts {result}'
    result = client.evaluate("""
        (async () => {
            const show = cuju.postMatch;
            show.advance();
            const reel = await motionWait(() => !!cuju.director.active
                && !!cuju.director.active.plan && cuju.timeline.playing, 45000);
            show.skip();
            return { reel };
        })()
    """)
    assert all(result.values()), f'Reduced motion reel {result}'
    result = client.evaluate("""
        (async () => {
            const show = cuju.postMatch;
            const spotlight = await motionWait(() => cuju.spotlight.showing && !show.wiping,
                45000);
            const flash = document.querySelector('#spotlight .mvp-flash');
            const unlit = !!flash && getComputedStyle(flash).display === 'none';
            show.skip();
            return { spotlight, unlit };
        })()
    """)
    assert all(result.values()), f'Reduced motion spotlight {result}'
    result = client.evaluate("""
        (async () => {
            const show = cuju.postMatch;
            const podium = await motionWait(() => cuju.podium.showing
                && !!cuju.podium.confettiMesh && !show.wiping, 45000);
            const frames = motionLog.frames;
            await motionWait(() => motionLog.frames > frames + 2, 5000);
            const still = !!cuju.podium.confettiMesh && !cuju.podium.confettiMesh.visible;
            show.end({ home: false, restore: false });
            return { podium, still, ended: !show.running };
        })()
    """)
    assert all(result.values()), f'Reduced motion podium {result}'
    client.call('Emulation.setEmulatedMedia', {'features': []})
    assert not motion_follows(client, False), 'Full motion from the system'
    result = client.evaluate("""
        (async () => {
            const motion = document.getElementById('motion');
            const choose = (value) => {
                motion.value = value;
                motion.dispatchEvent(new Event('change'));
            };
            choose('reduce');
            const tl = cuju.timeline;
            cuju.act('pause');
            const paused = cuju.userPaused;
            // R plays the last goal again as a replay with its still angles.
            cuju.replayGoal(window.motionGoal);
            const playing = cuju.director.running && !cuju.userPaused;
            const replay = await motionWait(() => window.motionCover() || !!cuju.director.active
                && !!cuju.director.active.plan && tl.playing, 100000);
            cuju.director.stop(true);
            cuju.act('pause');
            choose('system');
            delete cuju.cameras.update;
            const log = window.motionLog;
            const all = {
                paused, playing, replay, system: !cuju.reducedMotion,
                shots: log.scripted >= 5 && log.stills >= 4, still: log.eased === 0,
                fades: log.fades > 0 && log.sweeps === 0,
                plain: log.flashes === 0 && log.trails === 0 && log.confetti === 0,
                muted: localStorage.getItem('cuju.muted') === 'true',
            };
            return Object.values(all).every(Boolean) || JSON.stringify({ ...all, log });
        })()
    """)
    assert result is True, f'Reduced motion replay on R and the log {result}'
    return 10


def photo_checks(client):
    """Checks photo mode, its keys, settings, guides, saved photos and the return from it."""

    def key(name, code, kinds=('keyDown', 'keyUp'), shift=False):
        for kind in kinds:
            client.call(
                'Input.dispatchKeyEvent',
                {'type': kind, 'key': name, 'code': code, 'modifiers': 8 if shift else 0},
            )

    checks = 0
    result = client.evaluate("""
        (async () => {
            const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            const { api } = await import('./js/core/api.js');
            const entries = await api.matches();
            await cuju.openMatch(entries[0].id);
            for (let i = 0; i < 100 && !cuju.photo; i++) {
                await wait(20);
            }
            cuju.director.stop(true);
            cuju.timeline.seek(cuju.timeline.first + 30);
            cuju.act('play');
            await wait(300);
            if (document.activeElement) {
                document.activeElement.blur();
            }
            // The state just after photo mode opens and just after it closes, read inside the
            // same key press, before any frame moves the camera on.
            window.photoSeen = {};
            window.addEventListener('keydown', () => {
                const p = cuju.photo;
                const camera = cuju.view.camera;
                if (p.isOpen && !window.photoSeen.opened) {
                    window.photoSeen.opened = {
                        position: p.saved.position.toArray(), fov: p.saved.fov, mode: p.saved.mode,
                        playing: p.saved.playing,
                    };
                } else if (!p.isOpen && window.photoSeen.opened && !window.photoSeen.closed) {
                    window.photoSeen.closed = {
                        position: camera.position.toArray(), fov: camera.fov,
                        mode: cuju.cameras.mode, playing: cuju.timeline.playing,
                        material: p.material, panel: !!document.getElementById('photo-panel'),
                    };
                }
            }, true);
            return {
                ready: !!cuju.photo && !cuju.photo.isOpen,
                item: !!document.querySelector('#view-photo [role="menuitem"]'),
                playing: cuju.timeline.playing,
            };
        })()
    """)
    assert all(result.values()), f'Photo mode ready {result}'
    checks += 1
    key('o', 'KeyO')
    result = client.evaluate("""
        (() => {
            const panel = document.getElementById('photo-panel');
            const topbar = document.getElementById('topbar');
            return {
                open: cuju.photo.isOpen,
                paused: !cuju.timeline.playing,
                free: cuju.cameras.mode === 'free',
                panel: !!panel && !panel.hidden && panel.getClientRects().length > 0,
                bars: topbar.getClientRects().length === 0
                    && document.getElementById('controls').getClientRects().length === 0,
                saved: !!window.photoSeen.opened && window.photoSeen.opened.playing === true,
            };
        })()
    """)
    assert all(result.values()), f'Photo mode opens by key {result}'
    checks += 1
    key('l', 'KeyL')
    key('l', 'KeyL')
    key('g', 'KeyG')
    result = client.evaluate("""
        (() => {
            const p = cuju.photo;
            const vignette = document.getElementById('photo-vignette');
            vignette.value = '0.6';
            vignette.dispatchEvent(new Event('input', { bubbles: true }));
            const after = p.set({ grain: 0.3 });
            let refused = '';
            try {
                p.set({ look: 'sepia' });
            } catch (err) {
                refused = err.message;
            }
            const layer = document.querySelector('.photo-guides');
            return {
                look: after.look === 'cold'
                    && document.getElementById('photo-look').value === 'cold',
                vignette: after.vignette === 0.6,
                grain: after.grain === 0.3
                    && document.getElementById('photo-grain').value === '0.3',
                guide: after.guide === 'thirds' && layer.dataset.lines === '4'
                    && layer.querySelectorAll('line').length === 8,
                refused: refused.startsWith('Unknown look') && p.state().look === 'cold',
            };
        })()
    """)
    assert all(result.values()), f'Photo looks and guides {result}'
    checks += 1
    key('u', 'KeyU')
    hidden = client.evaluate("""
        ({
            hidden: document.getElementById('photo-panel').hidden
                && cuju.photo.state().interface === false,
            open: cuju.photo.isOpen,
        })
    """)
    key('u', 'KeyU')
    shown = client.evaluate("!document.getElementById('photo-panel').hidden")
    key('u', 'KeyU')
    key('Escape', 'Escape')
    again = client.evaluate("cuju.photo.isOpen && !document.getElementById('photo-panel').hidden")
    assert all(hidden.values()) and shown and again, f'Photo interface {hidden} {shown} {again}'
    checks += 1
    start = client.evaluate('cuju.photo.camera().position')
    key('w', 'KeyW', ('keyDown',))
    client.evaluate('new Promise((resolve) => setTimeout(resolve, 600))')
    key('w', 'KeyW', ('keyUp',))
    key('ArrowLeft', 'ArrowLeft', ('keyDown',))
    client.evaluate('new Promise((resolve) => setTimeout(resolve, 300))')
    key('ArrowLeft', 'ArrowLeft', ('keyUp',))
    result = client.evaluate(f"""
        (() => {{
            const start = {start};
            const now = cuju.photo.camera();
            const moved = Math.hypot(...now.position.map((v, i) => v - start[i]));
            return {{
                moved: moved > 0.5,
                paused: !cuju.timeline.playing,
                free: cuju.cameras.mode === 'free',
            }};
        }})()
    """)
    assert all(result.values()), f'Photo camera by key {result}'
    checks += 1
    client.evaluate("""
        (() => {
            const p = cuju.photo;
            window.photoSize = (url) => {
                const b = atob(url.split(',')[1].slice(0, 44));
                const n = (i) => ((b.charCodeAt(i) << 24) | (b.charCodeAt(i + 1) << 16)
                    | (b.charCodeAt(i + 2) << 8) | b.charCodeAt(i + 3)) >>> 0;
                return [n(16), n(20)];
            };
            p.set({ aperture: 0 });
            p.camera({ position: [0, 12, 40], target: [0, 0, 0], fov: 40, roll: 0 });
        })()
    """)
    full = client.evaluate("""
        (async () => {
            const win = cuju.photo.state().windowSize;
            const url = await cuju.photo.capture();
            const stage = document.getElementById('stage');
            return url.startsWith('data:image/png;base64,')
                && JSON.stringify(photoSize(url)) === JSON.stringify([win.width, win.height])
                && win.width === stage.clientWidth * devicePixelRatio;
        })()
    """)
    small = client.evaluate("""
        (async () => {
            const url = await cuju.photo.capture({ width: 320, height: 200 });
            return JSON.stringify(photoSize(url));
        })()
    """)
    chosen = client.evaluate("""
        (async () => {
            const p = cuju.photo;
            p.set({ resolution: { width: 240, height: 300 } });
            const blob = await p.capture({ as: 'blob' });
            const c = p.state().lastCapture;
            p.set({ resolution: 'window' });
            return blob instanceof Blob && blob.type === 'image/png' && c.width === 240
                && c.height === 300 && c.bytes === blob.size;
        })()
    """)
    assert full and small == '[320,200]' and chosen, f'Photo capture {full} {small} {chosen}'
    checks += 1
    result = client.evaluate("""
        (async () => {
            const p = cuju.photo;
            // The same photo with and without a guide, with grain off, is the same picture.
            p.set({ grain: 0, guide: 'off', aperture: 0.3, look: 'noir' });
            const plain = await p.capture({ width: 320, height: 200 });
            p.set({ guide: 'center' });
            const guided = await p.capture({ width: 320, height: 200 });
            p.set({ guide: 'crop-4-5' });
            const cropped = await p.capture({ width: 320, height: 200 });
            return {
                guides: plain === guided && plain === cropped
                    && document.querySelectorAll('.photo-guides line').length === 0
                    && document.querySelectorAll('.photo-guides rect').length === 2,
                still: p.isOpen && !cuju.timeline.playing,
            };
        })()
    """)
    assert all(result.values()), f'Photo guides stay out of photos {result}'
    checks += 1
    result = client.evaluate("""
        (async () => {
            window.photoLinks = [];
            const click = HTMLAnchorElement.prototype.click;
            HTMLAnchorElement.prototype.click = function () {
                window.photoLinks.push(this.download);
            };
            window.restoreLinkClick = () => {
                HTMLAnchorElement.prototype.click = click;
            };
            return cuju.photo.fileName();
        })()
    """)
    key('p', 'KeyP')
    result = client.evaluate(f"""
        (async () => {{
            for (let i = 0; i < 100 && !window.photoLinks.length; i++) {{
                await new Promise((resolve) => setTimeout(resolve, 50));
            }}
            window.restoreLinkClick();
            const name = window.photoLinks[0] || '';
            return {{
                name: name === {result!r} && /^cuju-photo-[a-z0-9._-]+-[0-9]+\\.png$/.test(name),
                status: document.querySelector('#photo-panel .photo-status')
                    .textContent.startsWith('Saved'),
            }};
        }})()
    """)
    assert all(result.values()), f'Photo saves by key {result}'
    checks += 1
    key('o', 'KeyO')
    result = client.evaluate("""
        (async () => {
            await new Promise((resolve) => setTimeout(resolve, 100));
            const seen = window.photoSeen;
            const o = seen.opened;
            const c = seen.closed;
            const same = !!c && o.position.every((v, i) => Math.abs(v - c.position[i]) < 1e-6);
            const result = {
                camera: same && Math.abs(o.fov - c.fov) < 1e-6 && c.mode === o.mode,
                playback: !!c && c.playing === true && cuju.timeline.playing && !cuju.userPaused,
                freed: !!c && c.material === null && !c.panel && !cuju.photo.isOpen,
                page: !document.documentElement.classList.contains('cuju-photo')
                    && document.getElementById('topbar').getClientRects().length > 0
                    && !document.querySelector('.photo-guides'),
                lock: !document.pointerLockElement,
            };
            cuju.act('pause');
            return result;
        })()
    """)
    assert all(result.values()), f'Photo mode leaves {result}'
    checks += 1
    return checks


def challenge_checks(client):
    """Checks the Challenges page, a person's run on Play and its way back, a headless run and
    achievements."""
    key = {'key': 'Enter', 'code': 'Enter', 'windowsVirtualKeyCode': 13}
    result = client.evaluate("""
        (async () => {
            const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            const { api } = await import('./js/core/api.js');
            localStorage.removeItem('cuju.achievements');
            localStorage.setItem('cuju.challengeName', 'Page check');
            const sources = await api.live();
            const ids = (await api.matches()).map((m) => m.id);
            window.pageCheckApi = Object.fromEntries(
                ['startGame', 'gameStream', 'pauseGame', 'gameInput', 'quitGame', 'game']
                    .map((name) => [name, api[name]])
            );
            const state = { specs: [], entry: null, ends: [
                { match: ids[0], score: [1, 0], achievements: [['off_the_mark'], null] },
                { match: null, score: [0, 0], achievements: [[], null] },
                { match: ids[1], score: [0, 0], achievements: [['off_the_mark'], null] },
            ] };
            window.pageCheckChallenge = state;
            api.startGame = async (spec) => {
                state.specs.push(spec);
                state.entry = { id: sources[0].id, state: 'paused', score: [0, 0] };
                return state.entry;
            };
            api.gameStream = (id, signal) => api.liveStream(id, signal);
            api.pauseGame = async (id, paused) => {
                state.entry = { ...state.entry, state: paused ? 'paused' : 'playing' };
                return state.entry;
            };
            api.gameInput = async () => state.entry;
            api.game = async () => state.entry;
            api.quitGame = async () => {
                state.entry = { ...state.entry, state: 'ended', ending: 'episode',
                    ...state.ends[state.specs.length - 1] };
                return state.entry;
            };
            cuju.showPage('challenges');
            for (let i = 0; i < 100 && !document.querySelector('.challenge-item'); i++) {
                await wait(50);
            }
            const items = [...document.querySelectorAll('.challenge-item')];
            const titles = items.map((item) => item.querySelector('h2').textContent);
            const named = titles.join() === 'Empty goal from close range,Corner,One on one'
                && !/_/.test(document.querySelector('.challenges').innerText);
            const start = document.querySelector(
                '.challenge-item[data-id="one_on_one"] [data-action="start"]');
            start.focus();
            // Every challenge has the same buttons, and each names its challenge.
            const labelled = start.getAttribute('aria-label')
                === 'Play it yourself, One on one';
            return { named, labelled, focused: document.activeElement === start,
                scripted: typeof cuju.challenges.start === 'function' };
        })()
    """)
    assert all(result.values()), f'Challenges list {result}'
    client.call('Input.dispatchKeyEvent', {'type': 'keyDown', 'text': '\r', **key})
    client.call('Input.dispatchKeyEvent', {'type': 'keyUp', **key})
    result = client.evaluate("""
        (async () => {
            const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            const state = window.pageCheckChallenge;
            for (let i = 0; i < 100 && !(cuju.play.game && cuju.play.game.started); i++) {
                await wait(100);
            }
            const spec = state.specs[0];
            const seeds = cuju.challenges.state().run && (await cuju.challenges.list())
                .find((c) => c.id === 'one_on_one').seeds;
            const started = !!spec && spec.seed === seeds[0] && spec.record === true
                && spec.teams.join() === 'builtin,builtin' && spec.humans.join() === 'true,false'
                && spec.scenario === '1_vs_1_easy';
            await cuju.play.quit();
            for (let i = 0; i < 50 && !/Scored|No goal/.test(cuju.play.endPanel.innerText); i++) {
                await wait(50);
            }
            const card = cuju.play.endPanel.innerText;
            const ended = /attempt 1 of 3/.test(card) && /No goal|Scored/.test(card)
                && /New achievement, Off the mark/.test(card) && /Next attempt/.test(card);
            // The attempt plays on the game view of Play.
            return { started, ended, live: !cuju.play.end.hidden, play: cuju.page === 'play' };
        })()
    """)
    assert all(result.values()), f'Challenge attempt {result}'
    # With the focus outside the end card, one controller press focuses its main action, Next
    # attempt, and the next one picks it.
    result = client.evaluate("""
        (async () => {
            const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            const state = window.pageCheckChallenge;
            const readPads = navigator.getGamepads;
            const pad = { index: 0, connected: true, mapping: 'standard', axes: [0, 0],
                buttons: Array.from({ length: 16 }, () => ({ pressed: false })) };
            Object.defineProperty(navigator, 'getGamepads', { configurable: true,
                value: () => [pad] });
            try {
                const press = async () => {
                    pad.buttons[0].pressed = true;
                    cuju.play.pollPads();
                    await wait(30);
                    pad.buttons[0].pressed = false;
                    cuju.play.pollPads();
                    await wait(30);
                };
                cuju.play.pollPads();
                document.activeElement.blur();
                await press();
                const focused = document.activeElement.textContent === 'Next attempt';
                await press();
                for (let i = 0; i < 100 && state.specs.length < 2; i++) await wait(50);
                for (let i = 0; i < 100 && !cuju.play.game.started; i++) await wait(100);
                const second = state.specs.length === 2
                    && state.specs[1].seed !== state.specs[0].seed;
                await cuju.play.quit();
                await wait(300);
                const missed = /counts as missed/.test(cuju.play.endPanel.innerText);
                await cuju.challenges.next();
                for (let i = 0; i < 100 && !cuju.play.game.started; i++) await wait(100);
                await cuju.play.quit();
                for (let i = 0; i < 100
                    && !/personal best|first run/i.test(cuju.play.endPanel.innerText);
                    i++) {
                    await wait(50);
                }
                const card = cuju.play.endPanel.innerText;
                const run = cuju.challenges.state().run;
                const finished = /attempt 3 of 3/.test(card) && /rank 1/.test(card)
                    && /Try again/.test(card) && run.outcome && run.outcome.kind === 'person'
                    && run.matches.length === 3 && run.matches[1] === null;
                return { focused, second, missed, finished };
            } finally {
                Object.defineProperty(navigator, 'getGamepads', { configurable: true,
                    value: readPads });
            }
        })()
    """)
    assert all(result.values()), f'Challenge run by controller {result}'
    # Esc on the end card of the run leads back to the Challenges page, at the challenge's card.
    for kind in ('keyDown', 'keyUp'):
        client.call(
            'Input.dispatchKeyEvent',
            {'type': kind, 'key': 'Escape', 'code': 'Escape', 'windowsVirtualKeyCode': 27},
        )
    result = client.evaluate("""
        (async () => {
            const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            const start = () => document.querySelector(
                '.challenge-item[data-id="one_on_one"] [data-action="start"]');
            for (let i = 0; i < 100 && document.activeElement !== start(); i++) await wait(50);
            return { page: cuju.page === 'challenges', focus: document.activeElement === start(),
                hash: location.hash === '#page=challenges', setup: !cuju.play.game
                    && !cuju.play.setupView.hidden };
        })()
    """)
    assert all(result.values()), f'Challenge run returns to its page {result}'
    result = client.evaluate("""
        (async () => {
            const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            const { api } = await import('./js/core/api.js');
            try {
                if (cuju.play.game?.source) cuju.play.game.source.live.stop();
                await cuju.challenges.leave();
                const back = cuju.page === 'challenges' && document.activeElement === document
                    .querySelector('.challenge-item[data-id="one_on_one"] [data-action="start"]');
                const job = await cuju.challenges.run('one_on_one', { team: 'builtin' });
                const line = () => document.querySelector(
                    '.challenge-item[data-id="one_on_one"] .challenge-job').innerText;
                for (let i = 0; i < 100 && !/finished/.test(line()); i++) await wait(100);
                const headless = job.state === 'queued' && /finished One on one/.test(line());
                for (let i = 0; i < 50 && !document.querySelector(
                    '.challenge-item[data-id="one_on_one"] [data-action="board"]'); i++) {
                    await wait(50);
                }
                await wait(300);
                const toggle = document.querySelector(
                    '.challenge-item[data-id="one_on_one"] [data-action="board"]');
                toggle.click();
                const board = () => document.querySelector(
                    '.challenge-item[data-id="one_on_one"] .challenge-board');
                for (let i = 0; i < 50 && !board().querySelector('table'); i++) await wait(50);
                const kinds = [...board().querySelectorAll('.challenge-kind')]
                    .map((mark) => mark.textContent);
                // A team and a policy each read as their own kind of competitor.
                const marked = kinds.includes('Person')
                    && (kinds.includes('Team') || kinds.includes('Python policy'))
                    && toggle.getAttribute('aria-expanded') === 'true';
                const entries = await cuju.challenges.board('one_on_one');
                const ranked = entries.map((e) => e.kind).join() === 'agent,person';
                const listed = [...document.querySelectorAll('.achievement-list li')];
                const earned = listed.filter((li) => li.classList.contains('earned'))
                    .map((li) => li.dataset.id);
                const scripted = await cuju.challenges.achievements();
                const achievements = earned.join() === 'off_the_mark'
                    && scripted.person.off_the_mark.count === 2 && scripted.catalog.length > 3
                    && listed.length === scripted.catalog.length;
                return { back, headless, marked, ranked, achievements };
            } finally {
                Object.assign(api, window.pageCheckApi);
                localStorage.removeItem('cuju.achievements');
                localStorage.removeItem('cuju.challengeName');
                cuju.play.showSetup();
            }
        })()
    """)
    assert all(result.values()), f'Challenges headless run and achievements {result}'
    return 5


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
        with tempfile.TemporaryDirectory(
            prefix='cuju-page-', ignore_cleanup_errors=True
        ) as profile:
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
                        # The checks read the English page, whatever the language of the machine.
                        '--lang=en-US',
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
                // The offer to install the page stays away unless a check asks for it.
                if (localStorage.getItem('cuju.installOffer') === null) {
                    localStorage.setItem('cuju.installOffer', '{"dismissed": true}');
                }
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
                'challenges',
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
            # Export video opens a dialog over Watch, which offers the export of the browser, or
            # says what would make export work, and closes with Escape.
            result = client.evaluate("""
                (async () => {
                    document.getElementById('video-export-btn').click();
                    const d = document.querySelector('dialog.video-export');
                    for (let i = 0; i < 50 && !d.querySelector('.ve-actions'); i++) {
                        await new Promise((r) => setTimeout(r, 100));
                    }
                    return { open: d.open, text: d.textContent, paused: !cuju.timeline.playing,
                             form: !!d.querySelector('#ve-start') };
                })()
            """)
            assert result['open'] and result['paused'], result
            assert result['form'] or 'video encoder' in result['text'], result
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
                            .find((b) => (b.getAttribute('aria-label') || b.textContent.trim())
                                === text).click();
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
                    // The note names H, M and F, each drawn as a keycap.
                    const reserved = play.input.keys.shot === 'KeyD'
                        && play.inputNote.querySelectorAll('kbd.chord').length === 3;
                    press('KeyW');
                    const taken = play.input.keys.shot === 'KeyD'
                        && /already/.test(play.inputNote.textContent);
                    press('KeyX');
                    const stored = JSON.parse(localStorage.getItem('cuju.input'));
                    const bound = play.input.keys.shot === 'KeyX' && stored.keys.shot === 'KeyX'
                        && play.keys.KeyX[0] === 'shot' && !play.keys.KeyD
                        && play.keyTable.textContent.includes('X');
                    // The slider sits right under its label, never at the foot of a tall field.
                    const field = play.deadZone.closest('.field').getBoundingClientRect();
                    const near = play.deadZone.getBoundingClientRect().top - field.top < 60;
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
                    const named = 'button[aria-label="Reset input settings"]';
                    play.inputPanel.querySelector(named).click();
                    const reset = play.input.keys.shot === 'KeyD' && play.input.deadZone === 0.5
                        && play.input.devices.join() === 'auto,auto';
                    play.inputPanel.open = false;
                    return {
                        reserved, taken, bound, near, zone, devices, tested, navigable, reset,
                    };
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
                    cuju.timeline.pause();
                    const reduced = cuju.reducedMotion && root.contains('reduced-motion')
                        && cuju.cameras.reducedMotion && !cuju.ball.trailOn
                        && JSON.parse(localStorage.getItem('cuju.motion')) === 'reduce';
                    // Reduced motion keeps the restart transitions under their own setting.
                    const kept = cuju.transition.enabled()
                        === (cuju.settings.transitions !== false);
                    choose('full');
                    const full = !cuju.reducedMotion && root.contains('full-motion')
                        && cuju.ball.trailOn === cuju.settings.trail;
                    choose('system');
                    return { start, reduced, kept, full };
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
            checks += motion_checks(client)
            checks += library_checks(client)
            checks += page_groups.check_groups(client)
            checks += tournament_checks(client)
            checks += tournament_play_checks(client, debug, port)
            checks += page_tournaments.wizard_checks(client)
            checks += page_tournaments.phone_checks(client)
            checks += page_tournaments.view_checks(client)
            checks += page_tournaments.clunky_checks(client)
            checks += page_tournaments.phone_view_checks(client)
            checks += page_tournaments.desktop_checks(client)
            checks += surprise_checks(client)
            checks += reconnection_checks(client)
            checks += palette_checks(client)
            checks += ui_a11y_checks(client)
            checks += presets_checks(client)
            checks += first_run_checks(client)
            checks += touch_checks(client)
            checks += page_grid.check_grid(client)
            checks += page_grid.check_flat(client, f'http://127.0.0.1:{port}/')
            checks += loading_checks(client, port)
            checks += format_checks(client)
            checks += malformed_index_checks(client)
            checks += malformed_summary_checks(client)
            checks += annotation_checks(client)
            checks += presentation_checks(client, port)
            checks += sandbox_top_checks(client, port, debug)
            checks += worklet_checks(client, port)
            checks += worker_checks(client)
            checks += photo_checks(client)
            checks += page_challenges.reach_checks(client)
            checks += page_challenges.card_checks(client)
            checks += challenge_checks(client)
            checks += page_challenges.bench_checks(client)
            checks += page_challenges.model_checks(client)
            checks += page_help.help_checks(client, port)
            checks += page_a11y.a11y_checks(client)
            checks += page_search.check_search(client)
            checks += page_search.check_captions(client)
            checks += page_export.export_checks(client)
            checks += page_feed.check_feed(client, f'http://127.0.0.1:{port}/', debug, CDP)
            checks += page_language.check_languages(client)
            checks += draw_checks(client)
            checks += page_matches.check_matches(client)
            checks += hash_checks(client)
            checks += address_checks(client)
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
