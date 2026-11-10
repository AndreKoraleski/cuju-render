# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""The tournaments of the mock server, in memory, with the rules of the renderer's own module.

The rules come from `src/cuju/render/_tournaments/tournament.py`, loaded from its file, since it
uses the standard library alone. The matches of agents play at once with made up results whenever
the page reads a tournament, one round of ready matches at a time, so a page check sees brackets and
tables fill. Each result names a recording of the mock's library, so Watch opens it. The matches of
people wait, and Play now answers that people play on the real server.
"""

import hashlib
import importlib.util
import time
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    'cuju_render_tournament_rules',
    Path(__file__).resolve().parents[1]
    / 'src'
    / 'cuju'
    / 'render'
    / '_tournaments'
    / 'tournament.py',
)
rules = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rules)


def _fits(entrant, scenario):
    size = '5v5' if scenario.startswith('5_vs_5') else '11v11'
    if entrant['format'] and scenario[0].isdigit() and entrant['format'] != size:
        return f'expected a scenario of {entrant["format"]}'
    return None


class MockTournaments:
    """Tournaments held in memory, with the routes of the real server under /api/tournaments."""

    def __init__(self, teams, scenarios, recording):
        self._teams = teams
        self._scenarios = scenarios
        self._recording = recording
        self._records = {}
        self._presets = {}
        self._count = 0

    def _check(self, config):
        if (
            isinstance(config, dict)
            and isinstance(config.get('preset'), str)
            and ('stages' not in config)
        ):
            config = {**rules.preset_config(config['preset'], self.presets()), **config}
        return rules.check(config, self._teams(), _fits, {}, list(self._scenarios))

    def presets(self):
        shipped = {name: {**preset, 'shipped': True} for name, preset in rules.PRESETS.items()}
        shipped.update({name: {**p, 'shipped': False} for name, p in self._presets.items()})
        return shipped

    def _advance(self, record):
        """Plays the ready matches of agents with results made up from their seeds."""
        if record['state'] != 'running':
            return
        view = rules.evaluate(record['config'], record['results'])
        for match in rules.ready(view):
            if match['person']:
                continue
            digest = hashlib.sha256(str(match['seed']).encode()).digest()
            record['results'][match['key']] = {
                'score': [digest[0] % 4, digest[1] % 3],
                'cards': [[digest[2] % 2, 0], [digest[3] % 2, 0]],
                'match': self._recording(),
                'forfeit': False,
            }
        if rules.evaluate(record['config'], record['results'])['complete']:
            record['state'] = 'done'

    def _summary(self, record):
        view = rules.evaluate(record['config'], record['results'])
        config = record['config']
        champion = view['champion']
        return {
            'id': record['id'],
            'name': config['name'],
            'state': record['state'],
            'error': None,
            'created': record['created'],
            'finished': None,
            'seed': config['seed'],
            'entrants': len(config['entrants']),
            'stages': [
                {'name': s['name'], 'format': s['format'], 'scenario': s['scenario']}
                for s in config['stages']
            ],
            'played': view['played'],
            'scheduled': len(view['matches']),
            'running': 0,
            'people_waiting': sum(1 for m in rules.ready(view) if m['person']),
            'champion': None if champion is None else config['entrants'][champion]['name'],
            'champion_color': None,
            'owner': None,
            'persistence_error': None,
        }

    def _full(self, record):
        view = rules.evaluate(record['config'], record['results'])
        matches = []
        for match in view['matches']:
            entry = dict(match)
            if match['result'] is not None:
                entry['state'] = 'done'
            else:
                entry['state'] = 'person' if match['person'] else 'ready'
            matches.append(entry)
        return {
            **self._summary(record),
            'config': record['config'],
            'stages_view': view['stages'],
            'matches': matches,
            'ranking': view['ranking'],
            'champion_index': view['champion'],
        }

    def respond(self, method, rest, document):
        """Answers one request and returns its status and body."""
        try:
            return self._respond(method, rest, document)
        except rules.TournamentError as error:
            return 400, {'error': str(error)}

    def _respond(self, method, rest, document):
        if method == 'GET':
            if not rest:
                for record in self._records.values():
                    self._advance(record)
                records = sorted(self._records.values(), key=lambda r: -r['created'])
                return 200, [self._summary(r) for r in records]
            if rest == ['presets']:
                return 200, self.presets()
            if rest == ['ratings']:
                return 200, {}
            record = self._records.get(rest[0]) if len(rest) == 1 else None
            if record is None:
                return 404, {'error': 'no such tournament'}
            self._advance(record)
            return 200, self._full(record)
        if method == 'POST':
            config = document.get('config', document)
            if not rest:
                checked = self._check(config)
                self._count += 1
                identifier = f't-mock-{self._count}'
                self._records[identifier] = {
                    'id': identifier,
                    'created': time.time(),
                    'config': checked,
                    'results': {},
                    'state': 'running',
                }
                return 201, self._summary(self._records[identifier])
            if rest == ['check']:
                checked = self._check(config)
                view = rules.evaluate(checked, {})
                stages = [
                    {k: s[k] for k in ('name', 'format', 'entrants', 'advance', 'rounds', 'tables')}
                    for s in view['stages']
                ]
                return 200, {'config': checked, 'stages': stages, 'matches': len(view['matches'])}
            if len(rest) == 2 and rest[0] == 'presets':
                preset = rules.check_preset(document.get('preset'))
                self._presets[rest[1]] = preset
                return 201, {**preset, 'shipped': False}
            record = self._records.get(rest[0])
            if record is None:
                return 404, {'error': 'no such tournament'}
            action = rest[1] if len(rest) == 2 else None
            if action == 'cancel':
                record['state'] = 'cancelled'
                return 200, self._full(record)
            if action == 'resume':
                record['state'] = 'running'
                return 200, self._summary(record)
            if action == 'forfeit':
                view = rules.evaluate(record['config'], record['results'])
                key = document.get('key')
                if not any(m['key'] == key and m['result'] is None for m in view['matches']):
                    return 400, {'error': 'expected a match still to play'}
                goals = record['config']['forfeit_score']
                score = [goals, 0] if document.get('winner') == 'home' else [0, goals]
                record['results'][key] = {
                    'score': score,
                    'cards': [[0, 0], [0, 0]],
                    'match': None,
                    'forfeit': True,
                }
                return 200, self._full(record)
            if action == 'play':
                return 400, {'error': 'the matches of people play on the real server'}
            return 404, {'error': 'no such resource'}
        if method == 'DELETE':
            if len(rest) == 2 and rest[0] == 'presets':
                return (204, None) if self._presets.pop(rest[1], None) else (404, {'error': 'no'})
            if len(rest) == 1 and rest[0] in self._records:
                if self._records[rest[0]]['state'] == 'running':
                    return 409, {'error': 'expected a tournament that has ended, cancel it first'}
                del self._records[rest[0]]
                return 204, None
            return 404, {'error': 'no such tournament'}
        return 404, {'error': 'no such resource'}
