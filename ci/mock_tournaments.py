# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""The tournaments of the mock server, in memory, with the rules of the renderer's own module.

The rules come from `src/cuju/render/_tournaments/tournament.py`, loaded from its file with the
module it imports, `_text/messages.py`, as a package of their own, and with cuju's errors from the
installed cuju, since all of them use the standard library alone. The ratings, the matrix and the
files of results come the same way from `_tournaments/results.py`. The matches of agents play at
once with made up results whenever the page reads a tournament, one round of ready matches at a
time, so a page check sees brackets and tables fill. Each result names a recording of the mock's
library, so Watch opens it. The matches of people wait, and Play now answers that people play on
the real server. A match of an entrant whose name starts with Failing fails, as a crashing team
does on the real server, so the page shows a failed match, its Award buttons and a tournament that
stops once only failed matches hold it up.

A tournament under strict rules plays the same way, and an entrant whose name starts with Slow
forfeits each match by the rule of a call's time, and one whose name starts with Hungry by the
rule of memory, each with the score at that moment. Its pre-flight, and the check of one team,
are made up too, a registered team whose name starts with Broken failing to load, so the
tournament leaves it out with its reason before the first match, and one whose name starts with
Wobbly answering differently when the same steps play again, a warning unless the rules ask for
deterministic teams.
"""

import hashlib
import importlib.util
import sys
import time
import types
from pathlib import Path

_CUJU = Path(__file__).resolve().parents[1] / 'src' / 'cuju'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


for _name in (
    'cuju_mock_rules',
    'cuju_mock_rules.render',
    'cuju_mock_rules.render._text',
    'cuju_mock_rules.render._tournaments',
):
    _package = types.ModuleType(_name)
    _package.__path__ = []
    sys.modules[_name] = _package
messages = _load(
    'cuju_mock_rules.render._text.messages', _CUJU / 'render' / '_text' / 'messages.py'
)
rules = _load(
    'cuju_mock_rules.render._tournaments.tournament',
    _CUJU / 'render' / '_tournaments' / 'tournament.py',
)
results = _load(
    'cuju_mock_rules.render._tournaments.results',
    _CUJU / 'render' / '_tournaments' / 'results.py',
)

# The seconds that a made up pre-flight runs, so the page sees it run before the first match.
PREFLIGHT_SECONDS = 0.6


class File:
    """A file of a tournament's results, which the server sends to save."""

    def __init__(self, name, text):
        self.name = name
        self.text = text
        kinds = {'.csv': 'text/csv', '.jsonl': 'application/x-ndjson', '.json': 'application/json'}
        self.kind = kinds[name[name.rindex('.') :]]


def _fits(entrant, scenario):
    size = '5v5' if scenario.startswith('5_vs_5') else '11v11'
    if entrant['format'] and scenario[0].isdigit() and entrant['format'] != size:
        return f'expected a scenario of {entrant["format"]}'
    return None


def _digest(*parts):
    return hashlib.sha256('/'.join(str(part) for part in parts).encode()).digest()


def _rule(side, kind, reason, step, at, detail=None):
    """Returns the rule that a side broke, with its reason as the server's label gives it."""
    return {
        'side': side,
        'kind': kind,
        'reason': reason['text'],
        'reason_id': reason['id'],
        'reason_values': reason['values'],
        'detail': detail,
        'step': step,
        'at': at,
    }


def _side_stats(seed, side, calls):
    digest = _digest(seed, side, 'stats')
    first = round(30 + digest[0] / 4, 1)
    mean = round(1.5 + digest[1] / 40, 2)
    return {
        'calls': calls,
        'first_ms': first,
        'mean_ms': mean,
        'mean_after_first_ms': round((mean * calls - first) / (calls - 1), 3)
        if calls > 1
        else None,
        'max_ms': round(max(first, mean * 3 + digest[2] / 20), 1),
        'memory_mb': round(150 + digest[5] / 2, 1),
        'actions': {str(digest[3] % 19): calls // 2, str(digest[4] % 19): calls - calls // 2},
    }


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

    @staticmethod
    def _failing(record, match):
        entrants = record['config']['entrants']
        return next(
            (
                entrants[side]['name']
                for side in (match['home'], match['away'])
                if entrants[side]['name'].startswith('Failing')
            ),
            None,
        )

    @staticmethod
    def _playable(record, view):
        return any(m['key'] not in record['failures'] for m in rules.ready(view))

    def _failure_text(self, record, view):
        labels = {m['key']: m['label'] for m in view['matches']}
        first = next(iter(record['failures']))
        return f'{labels.get(first, first)} failed, {record["failures"][first]}'

    # The made up checks of strict rules.

    def _team_name(self, identifier):
        team = next((t for t in self._teams() if t['id'] == identifier), None)
        return team['name'] if team else identifier

    def report(self, identifier, scenario=None, limits=None):
        """Returns a made up check of a team on the left and then on the right.

        A team whose name starts with Broken fails to load on the left, so its right side stays
        unplayed, and a team whose name starts with Steady passes with a warning that one action
        makes up most of its actions. A team whose name starts with Wobbly answers differently
        when the same steps play again, a warning, or a refusal when the rules ask for
        deterministic teams.
        """
        strict = limits is not None
        limits = dict(limits or {**rules.STRICT_DEFAULTS, **rules.STRICT_FLAGS})
        name = self._team_name(identifier)
        rule = None
        sides = {}
        for side in ('left', 'right'):
            digest = _digest(identifier, side, 'check')
            timings = {
                'load_seconds': round(0.3 + digest[0] / 255, 2),
                'reset_seconds': round(0.05 + digest[1] / 2550, 3),
                'calls': 50,
                'first_ms': round(40 + digest[2] / 4, 1),
                'mean_ms': round(2 + digest[3] / 40, 2),
                'max_ms': round(12 + digest[4] / 10, 1),
                'mean_after_first_ms': round(1.8 + digest[3] / 40, 2),
            }
            broken = None
            if name.startswith('Broken'):
                reason = messages.label(
                    'server.strict.load', player=name, reason='ImportError: no module named weights'
                )
                broken = _rule('home', 'load', reason, 0, [0, 0])
                timings = {key: None for key in timings}
                timings['calls'] = 0
            if broken is None and name.startswith('Wobbly') and limits.get('deterministic'):
                reason = messages.label('server.strict.deterministic', player=name)
                broken = _rule('home', 'deterministic', reason, 0, [0, 0])
            sides[side] = {'ok': broken is None, 'rule': broken, 'timings': timings}
            if broken is not None:
                rule = broken
                break
        warnings = []
        if name.startswith('Wobbly') and not limits.get('deterministic'):
            warnings.append(messages.label('server.strict.warning_deterministic', player=name))
        if name.startswith('Steady'):
            warnings.append(
                messages.label('server.strict.warning_action', player=name, action='5', share='95')
            )
        return {
            'team': identifier,
            **messages.named('name', name),
            'scenario': scenario or '5_vs_5',
            'ok': rule is None,
            'rule': rule,
            'timings': sides['left']['timings'],
            'sides': sides,
            'actions': {} if rule else {'5': 95, '0': 5},
            'folder_mb': round(0.01 + _digest(identifier, 'folder')[0] / 100, 3),
            'warnings': warnings,
            'digest': hashlib.sha256(f'{identifier}/files'.encode()).hexdigest(),
            'limits': limits,
            'strict': strict,
        }

    def check_team(self, identifier, document):
        """Answers the check of one team under strict rules, as the Teams page asks for it."""
        if not any(t['id'] == identifier for t in self._teams()):
            raise ValueError(f'expected a team of the registry, found {identifier!r}')
        document = document if isinstance(document, dict) else {}
        limits = rules.check_strict(document.get('strict', True))
        return self.report(identifier, document.get('scenario'), limits)

    def preflight_config(self, config):
        """Answers the pre-flight of a tournament still to start, from the made up checks."""
        checked = self._check(config)
        scenario = checked['stages'][0]['scenario']
        teams = list(dict.fromkeys(e['team'] for e in checked['entrants'] if e['kind'] == 'team'))
        checks = {team: self.report(team, scenario, checked.get('strict')) for team in teams}
        return {
            'scenario': scenario,
            'checks': list(checks.values()),
            'excluded': [
                {
                    **rules.named_from('name', entrant),
                    'team': entrant['team'],
                    **{
                        key: (checks[entrant['team']]['rule'] or {}).get(key)
                        for key in ('reason', 'reason_id', 'reason_values')
                    },
                }
                for entrant in checked['entrants']
                if entrant['kind'] == 'team' and not checks[entrant['team']]['ok']
            ],
        }

    def _preflight_pending(self, record):
        """Runs a tournament's made up pre-flight, and returns whether it still holds matches."""
        config = record['config']
        if not config.get('preflight') or record['preflight'] is not None or record['results']:
            return False
        if record['preflight_started'] is None:
            record['preflight_started'] = time.time()
            return True
        if time.time() - record['preflight_started'] < PREFLIGHT_SECONDS:
            return True
        scenario = config['stages'][0]['scenario']
        teams = list(dict.fromkeys(e['team'] for e in config['entrants'] if e['kind'] == 'team'))
        checks = {team: self.report(team, scenario, config.get('strict')) for team in teams}
        failed = {team for team, report in checks.items() if not report['ok']}
        given = config.get('given_entrants') or []
        excluded, kept = [], []
        for index, entrant in enumerate(config['entrants']):
            if entrant['kind'] == 'team' and entrant['team'] in failed:
                rule = checks[entrant['team']]['rule']
                excluded.append(
                    {
                        **rules.named_from('name', entrant),
                        'kind': entrant['kind'],
                        'team': entrant['team'],
                        'reason': rule['reason'],
                        'reason_id': rule['reason_id'],
                        'reason_values': rule['reason_values'],
                        'rule': rule['kind'],
                        'timings': checks[entrant['team']]['timings'],
                    }
                )
            elif index < len(given):
                kept.append(given[index])
        # A tournament keeps of each check the team, its name, whether it passed and why not.
        kept_checks = [
            {key: report.get(key) for key in ('team', 'name', 'name_id', 'name_values', 'ok')}
            | {'rule': report['rule'], 'timings': report['timings']}
            for report in checks.values()
        ]
        record['preflight'] = {'scenario': scenario, 'checks': kept_checks}
        record['excluded'] = excluded
        if excluded:
            source = {
                key: config[key]
                for key in (
                    'seed',
                    'seeding',
                    'concurrency',
                    'forfeit_score',
                    'ability',
                    'preset',
                    'strict',
                    'preflight',
                )
                if key in config
            }
            if config.get('name_id') is None:
                source['name'] = config['name']
            source.update(
                entrants=kept,
                stages=config['given']['stages'],
                defaults=config['given']['defaults'],
            )
            changed = self._check(source)
            changed['include'] = config.get('include', [])
            changed['given_entrants'] = kept
            record['config'] = changed
        return False

    def _strict_result(self, record, match, score, cards):
        """Returns the result of a match under strict rules, a forfeit by a side that breaks one.

        A side named Slow runs past the time of a call, and a side named Hungry past its memory.
        """
        config = record['config']
        entrants = config['entrants']
        names = [entrants[match['home']]['name'], entrants[match['away']]['name']]
        stats = {
            'steps': config['stages'][match['stage']]['length'] or 3000,
            'cut_short': False,
            'sides': [None, None],
        }
        for side, entrant in enumerate((entrants[match['home']], entrants[match['away']])):
            if entrant['kind'] in ('team', 'random'):
                stats['sides'][side] = _side_stats(match['seed'], side, 300)
        slow = [side for side, name in enumerate(names) if name.startswith(('Slow', 'Hungry'))]
        if not slow:
            return {
                'score': score,
                'cards': cards,
                'match': self._recording(),
                'forfeit': False,
                'stats': stats,
            }
        digest = _digest(match['seed'], 'slow')
        call = 40 + digest[0]
        at = [digest[1] % 2, digest[2] % 2]
        limit = (config.get('strict') or rules.STRICT_DEFAULTS)['memory_mb']
        reasons = [
            messages.label(
                'server.strict.memory',
                player=names[side],
                used=f'{limit + 12:.0f}',
                limit=f'{limit:g}',
            )
            if names[side].startswith('Hungry')
            else messages.label('server.strict.call_time', player=names[side], call=call, count='1')
            for side in slow
        ]
        kind = 'memory' if all(names[side].startswith('Hungry') for side in slow) else 'timeout'
        reason = (
            reasons[0]
            if len(reasons) == 1
            else messages.label('server.strict.both', home=reasons[0], away=reasons[1])
        )
        side = 'both' if len(slow) == 2 else ('home', 'away')[slow[0]]
        goals = config['forfeit_score']
        stats['steps'] = call
        stats['cut_short'] = True
        return {
            'score': {'home': [0, goals], 'away': [goals, 0]}.get(side, [0, 0]),
            'cards': [[0, 0], [0, 0]],
            'match': None,
            'forfeit': True,
            'rule': _rule(side, kind, reason, call, at),
            'stats': stats,
        }

    def _advance(self, record):
        """Plays the ready matches of agents with results made up from their seeds."""
        if record['state'] != 'running' or self._preflight_pending(record):
            return
        view = rules.evaluate(record['config'], record['results'])
        for match in rules.ready(view):
            if match['person'] or match['key'] in record['failures']:
                continue
            failing = self._failing(record, match)
            if failing:
                record['failures'][match['key']] = (
                    f'the policy of {failing} failed, RuntimeError: on purpose'
                )
                continue
            digest = hashlib.sha256(str(match['seed']).encode()).digest()
            score = [digest[0] % 4, digest[1] % 3]
            cards = [[digest[2] % 2, 0], [digest[3] % 2, 0]]
            if record['config'].get('strict'):
                result = self._strict_result(record, match, score, cards)
            else:
                result = {
                    'score': score,
                    'cards': cards,
                    'match': self._recording(),
                    'forfeit': False,
                }
            record['results'][match['key']] = rules.check_result(result)
        view = rules.evaluate(record['config'], record['results'])
        if view['complete']:
            record['state'] = 'done'
        elif record['failures'] and not self._playable(record, view):
            record['state'] = 'stopped'
            record['error'] = self._failure_text(record, view)

    def _preflight_state(self, record):
        if not record['config'].get('preflight'):
            return None
        if record['preflight'] is not None:
            return 'done'
        return 'waiting' if record['preflight_started'] is None else 'running'

    def _summary(self, record):
        view = rules.evaluate(record['config'], record['results'])
        config = record['config']
        champion = view['champion']
        return {
            'id': record['id'],
            'name': config['name'],
            'state': record['state'],
            'error': record['error'],
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
            'expected': view['expected'],
            'running': 0,
            'failed': len(record['failures']),
            'people_waiting': sum(1 for m in rules.ready(view) if m['person']),
            'champion': None if champion is None else config['entrants'][champion]['name'],
            'champion_color': None,
            'owner': None,
            'persistence_error': None,
            'strict': config.get('strict') is not None,
            'preflight': self._preflight_state(record),
            'excluded_count': len(record['excluded']),
        }

    def _full(self, record):
        view = rules.evaluate(record['config'], record['results'])
        matches = []
        for match in view['matches']:
            entry = dict(match)
            if match['result'] is not None:
                entry['state'] = 'done'
            elif match['key'] in record['failures']:
                entry['state'] = 'failed'
                entry['error'] = record['failures'][match['key']]
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
            'checks': (record['preflight'] or {}).get('checks', []),
            'excluded': list(record['excluded']),
        }

    def respond(self, method, rest, document):
        """Answers one request and returns its status and body, a `File` for a file to save."""
        try:
            return self._respond(method, rest, document)
        except rules.TournamentError as error:
            # A refusal of the rules names its message and values, as the server's answers do.
            return 400, messages.error_fields(error, str(error))

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
            record = self._records.get(rest[0])
            if record is None:
                return 404, {'error': 'no such tournament'}
            if len(rest) == 2 and rest[1] == 'analysis':
                return 200, results.analysis(self._full(record))
            if len(rest) == 3 and rest[1] == 'files':
                if rest[2] not in results.FILES:
                    return 404, {'error': 'no such resource'}
                full = self._full(record)
                return 200, File(f'{record["id"]}-{rest[2]}', results.files(full)[rest[2]])
            if len(rest) != 1:
                return 404, {'error': 'no such resource'}
            self._advance(record)
            return 200, self._full(record)
        if method == 'POST':
            config = document.get('config', document)
            if not rest:
                checked = self._check(config)
                self._count += 1
                identifier = f'cup-mock-{self._count}'
                self._records[identifier] = {
                    'id': identifier,
                    'created': time.time(),
                    'config': checked,
                    'results': {},
                    'state': 'running',
                    'error': None,
                    'failures': {},
                    'preflight': None,
                    'preflight_started': None,
                    'excluded': [],
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
            if rest == ['preflight']:
                return 200, self.preflight_config(config)
            if len(rest) == 2 and rest[0] == 'presets':
                preset = rules.check_preset(document.get('preset'))
                self._presets[rest[1]] = preset
                return 201, {**preset, 'shipped': False}
            record = self._records.get(rest[0])
            if record is None:
                return 404, {'error': 'no such tournament'}
            action = rest[1] if len(rest) == 2 else None
            if action == 'cancel':
                state = record['state']
                if state in ('done', 'cancelled'):
                    return 400, {
                        'error': f'expected a tournament that runs or stopped, found it {state}'
                    }
                record['state'] = 'cancelled'
                return 200, self._full(record)
            if action == 'resume':
                record.update(state='running', error=None, failures={})
                return 200, self._summary(record)
            if action == 'legs':
                if record['state'] == 'cancelled':
                    return 400, {'error': 'expected a tournament that was not canceled'}
                record['config'] = rules.add_legs(record['config'], document.get('legs'))
                if record['state'] == 'done':
                    record['state'] = 'running'
                return 200, self._full(record)
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
                record['failures'].pop(key, None)
                view = rules.evaluate(record['config'], record['results'])
                if record['state'] == 'stopped' and view['complete']:
                    record.update(state='done', error=None)
                elif record['state'] == 'stopped' and self._playable(record, view):
                    record.update(state='running', error=None)
                return 200, self._full(record)
            if action == 'spoilers':
                self._advance(record)
                full = self._full(record)
                return 200, rules.without_spoilers(full, record['results'], document.get('watched'))
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


def file_bytes(found):
    """Returns the body and headers of a file of results, as the server sends it to save."""
    body = found.text.encode()
    return body, [
        ('Content-Type', f'{found.kind}; charset=utf-8'),
        ('Content-Disposition', f'attachment; filename="{found.name}"'),
        ('Content-Length', str(len(body))),
        ('Cache-Control', 'no-store'),
    ]
