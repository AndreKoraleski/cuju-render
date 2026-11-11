# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The command `cuju render tournament`, which makes, lists, shows, runs and changes tournaments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from cuju.errors import ArgumentError

from . import tournament as rules
from . import tournament_runner as _tournament_runner

# How `show` names the state of a match still to play, as the page names it.
_MATCH_STATES = {
    'ready': 'in the queue',
    'running': 'playing',
    'playing': 'a person is playing',
    'person': 'ready for a person',
    'failed': 'failed',
}


def _stage_format(stage: Any, defaults: dict[str, Any]) -> Any:
    if not isinstance(stage, dict):
        return None
    return stage.get('format', defaults.get('format', rules.STAGE_DEFAULTS['format']))


def _config(options: argparse.Namespace) -> dict[str, Any]:
    """Returns the configuration that the options of `new` describe."""
    if options.config:
        try:
            config = json.loads(Path(options.config).read_text(encoding='utf-8'))
        except ValueError as error:
            raise ArgumentError(f'expected JSON in {options.config}, {error}') from error
        if not isinstance(config, dict):
            raise ArgumentError(f'expected a JSON object in {options.config}')
    else:
        config = {'preset': options.preset or 'quick_cup'}
    if options.preset and options.config:
        config['preset'] = options.preset
    if 'stages' not in config and config.get('preset'):
        base = rules.preset_config(config['preset'], _tournament_runner.presets())
        config = {**base, **config}
    entrants: list[dict[str, Any]] = []
    for kind, value in options.entrants or []:
        if kind == 'as':
            # A team entered again takes a free name, such as Rex 2, unless --as gives one.
            if not entrants:
                raise ArgumentError(
                    'expected --as after the --team, --builtin or --person that it names'
                )
            entrants[-1]['name'] = value
        elif kind == 'team':
            entrants.append({'kind': 'team', 'team': value})
        elif kind == 'person':
            entrants.append({'kind': 'person', 'name': value})
        else:
            try:
                ability = None if value in ('', 'any', 'scenario') else float(value)
            except ValueError as error:
                raise ArgumentError(
                    f'expected --builtin with an ability from 0 to 1 or any, found {value!r}'
                ) from error
            entrants.append({'kind': 'builtin', 'ability': ability})
    if entrants:
        config['entrants'] = entrants
    for key in ('name', 'seed', 'seeding', 'concurrency'):
        if getattr(options, key) is not None:
            config[key] = getattr(options, key)
    defaults = dict(config.get('defaults') or {})
    for key in ('scenario', 'length'):
        if getattr(options, key) is not None:
            defaults[key] = getattr(options, key)
    config['defaults'] = defaults
    if options.rounds is not None:
        stages = config.get('stages') if isinstance(config.get('stages'), list) else []
        rounded = [s for s in stages if _stage_format(s, defaults) in ('swiss', 'ladder')]
        if not rounded:
            raise ArgumentError('expected a Swiss or ladder stage for --rounds, found none')
        for stage in rounded:
            stage['rounds'] = options.rounds
    return config


def _check_rounds(config: dict[str, Any], rounds: int) -> None:
    """Refuses `--rounds` beyond what a Swiss stage allows, which a preset would bring down."""
    checked = _tournament_runner.check_config(config)
    for index, stage in enumerate(checked['stages']):
        if stage['format'] == 'swiss' and stage['rounds'] != rounds:
            raise ArgumentError(
                f'expected --rounds from 1 to {stage["rounds"]} for the Swiss stage {index + 1}, '
                f'which pairs {stage["entrants"]} entrants without rematches, found {rounds}'
            )


def _stage_title(stage: dict[str, Any]) -> str:
    """Returns a stage's name with its format, the format left out when the name is the format."""
    title = rules._FORMAT_TITLES.get(stage['format'], stage['format'])
    if stage['name'].casefold() == title.casefold():
        return stage['name']
    return f'{stage["name"]}, {title[0].lower()}{title[1:]}'


def describe(entry: dict[str, Any]) -> list[str]:
    """Returns the lines that `show` prints, the stages with their tables, results and ranking."""
    names = [entrant['name'] for entrant in entry['config']['entrants']]
    awarded = {
        match['key'] for match in entry['matches'] if (match.get('result') or {}).get('forfeit')
    }

    def name(side: Any) -> str:
        if isinstance(side, dict):
            return side.get('from', '')
        return 'a bye' if side is None else names[side]

    lines = [
        f'{entry["name"]}  {entry["id"]}  {entry["state"]}  seed {entry["seed"]}',
        f'{entry["played"]} of {entry["scheduled"]} scheduled matches played',
    ]
    if entry.get('error'):
        lines.append(entry['error'])
    for stage in entry['stages_view']:
        lines.append('')
        lines.append(f'{_stage_title(stage)}, {_STAGE_STATES.get(stage["state"], stage["state"])}')
        swiss = stage['format'] == 'swiss'
        for table in stage['tables']:
            lines.append(f'  {table["name"]}')
            head = f'  {"":>3}  {"":<28} Played  Won Drawn Lost   Goals Points'
            lines.append(head + ('  Buchholz Byes' if swiss else ''))
            for row in table['rows']:
                goals = f'{row["for"]}:{row["against"]}'
                line = (
                    f'  {row["position"]:>3}  {names[row["entrant"]]:<28} {row["played"]:>6} '
                    f'{row["won"]:>4} {row["drawn"]:>5} {row["lost"]:>4} {goals:>7} '
                    f'{row["points"]:>6}'
                )
                if swiss:
                    line += f'  {row["buchholz"]:>8} {row["byes"]:>4}'
                lines.append(line)
        for round_ in stage['rounds']:
            extra = ''
            if round_.get('bye') is not None:
                extra += f', bye for {names[round_["bye"]]}'
            if round_.get('king') is not None:
                extra += f', king {names[round_["king"]]}'
            lines.append(f'  {round_["name"]}{extra}')
            for fixture in round_['fixtures']:
                score = fixture.get('score')
                done = fixture.get('state') == 'done'
                if score is not None:
                    text = f'  {score[0]} to {score[1]}' + ('' if done else ' so far')
                else:
                    text = '' if done else '  not played'
                how = _DECIDED.get(fixture.get('decided_by') or '', '')
                if how:
                    text += f', {how}'
                for key, words in (('replay', 'replay'), ('decider', 'deciding matches')):
                    if fixture.get(key):
                        text += f', {words} {fixture[key][0]} to {fixture[key][1]}'
                if awarded & set(fixture.get('matches', [])):
                    text += ', awarded'
                lines.append(f'    {name(fixture["home"])} against {name(fixture["away"])}{text}')
    waiting = [match for match in entry['matches'] if match.get('state') != 'done']
    if waiting:
        lines += ['', 'Matches to play']
        for match in waiting:
            state = _MATCH_STATES.get(match.get('state'), match.get('state'))
            if match.get('error'):
                state = f'{state}, {match["error"]}'
            lines.append(
                f'  {match["key"]}  {match["label"]}, {names[match["home"]]} against '
                f'{names[match["away"]]}, {state}'
            )
    if entry.get('ranking'):
        lines += ['', 'Final ranking']
        lines += [f'  {place + 1:>3}. {names[e]}' for place, e in enumerate(entry['ranking'])]
    if entry['champion'] is not None:
        lines += ['', f'Champion: {entry["champion"]}']
    return lines


def preview_lines(preview: dict[str, Any]) -> list[str]:
    """Returns the lines that `check` prints, each stage with its entrants and first draw."""
    config = preview['config']
    names = [entrant['name'] for entrant in config['entrants']]

    def name(side: Any) -> str:
        if isinstance(side, dict):
            return side.get('from', '')
        return 'a bye' if side is None else names[side]

    lines = [
        f'{config["name"]}, seed {config["seed"]}, {len(names)} entrants, '
        f'{preview["matches"]} matches known before any result'
    ]
    last = len(config['stages']) - 1
    pairs = zip(config['stages'], preview['stages'], strict=True)
    for index, (settings, stage) in enumerate(pairs):
        parts = [f'{settings["entrants"]} entrants']
        if index < last:
            parts.append(f'{settings["advance"]} advance')
        parts.append(settings['scenario'])
        if settings['length']:
            parts.append(f'{settings["length"]} steps a match')
        lines.append(f'{index + 1}. {_stage_title(settings)}, {", ".join(parts)}')
        if settings['format'] == 'groups':
            for table in stage['tables']:
                members = ', '.join(names[row['entrant']] for row in table['rows'])
                lines.append(f'  {table["name"]}, {members}')
        elif stage['rounds']:
            first = stage['rounds'][0]
            lines.append(f'  {first["name"]}')
            for fixture in first['fixtures']:
                lines.append(f'    {name(fixture["home"])} against {name(fixture["away"])}')
    return lines


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2))


def _plays_it(identifier: str) -> str:
    return f'a running cuju render serve plays it, or cuju render tournament run {identifier}'


def run_command(parser: argparse.ArgumentParser, options: argparse.Namespace) -> int:
    """Runs one action of `cuju render tournament` and returns the exit status."""
    try:
        return _run_command(parser, options)
    except rules.TournamentError as error:
        raise ArgumentError(str(error)) from error


def _run(options: argparse.Namespace) -> int:
    """Runs a tournament in this process and prints how it stopped, or the whole of it as JSON."""
    tournaments = _tournament_runner.Tournaments(only=options.target, start=False)
    try:
        state = tournaments.run(options.target, report=_quiet if options.json else print)
        entry = tournaments.get(options.target)
    finally:
        tournaments.close()
    if options.json:
        _print_json({'outcome': state, 'tournament': entry})
    else:
        print(_RUN_MESSAGES[state])
    return 0 if state in ('done', 'people') else 1


def _quiet(line: str) -> None:
    del line


def _run_command(parser: argparse.ArgumentParser, options: argparse.Namespace) -> int:
    action = options.action
    if action == 'award':
        action = 'forfeit'
    if action in _NEEDS_TARGET and not options.target:
        parser.error(f'tournament {options.action} needs the identifier of a tournament')
    if action == 'forfeit' and (not options.match or not options.winner):
        parser.error(
            f'tournament {options.action} needs --match, the key of a match that tournament '
            'show lists, and --winner, home or away'
        )
    if action == 'presets':
        presets = _tournament_runner.presets()
        if options.json:
            _print_json(presets)
        else:
            for key, preset in presets.items():
                print(f'{key}  {preset["title"]}')
        return 0
    if action == 'ratings':
        table = _tournament_runner.ratings()
        if options.json:
            _print_json(table)
        else:
            ordered = sorted(table.items(), key=lambda item: -item[1]['rating'])
            for key, value in ordered:
                matches = value.get('matches', 0)
                plural = 'match' if matches == 1 else 'matches'
                print(f'{value["rating"]:>8.1f}  {matches:>4} {plural:<7}  {value["name"]}  {key}')
            if not ordered:
                print('no ratings yet, every match a tournament plays moves the ratings')
        return 0
    if action == 'check':
        config = _config(options)
        if options.rounds is not None:
            _check_rounds(config, options.rounds)
        preview = _tournament_runner.preview(config)
        if options.json:
            _print_json(preview)
        else:
            print('\n'.join(preview_lines(preview)))
        return 0
    if action == 'run':
        return _run(options)
    tournaments = _tournament_runner.Tournaments(start=False)
    try:
        if action == 'new':
            config = _config(options)
            if options.rounds is not None:
                _check_rounds(config, options.rounds)
            entry = tournaments.create(config)
            if options.run:
                if not options.json:
                    print(f'created {entry["id"]} {entry["name"]}')
                tournaments.close()
                options.target = entry['id']
                return _run(options)
            if options.json:
                _print_json(entry)
            else:
                print(f'created {entry["id"]} {entry["name"]}')
                print(_plays_it(entry['id']))
        elif action == 'list':
            entries = tournaments.entries()
            if options.json:
                _print_json(entries)
            else:
                for entry in entries:
                    champion = f'  won by {entry["champion"]}' if entry['champion'] else ''
                    print(
                        f'{entry["id"]}  {entry["state"]:<9}  {entry["played"]:>4} played  '
                        f'{entry["name"]}{champion}'
                    )
        else:
            if tournaments.get(options.target) is None:
                parser.error(f'no tournament {options.target!r}')
            if action == 'show':
                entry = tournaments.get(options.target)
                if options.json:
                    _print_json(entry)
                else:
                    print('\n'.join(describe(entry)))
            elif action == 'forfeit':
                entry = tournaments.forfeit(options.target, options.match, options.winner)
                if options.json:
                    _print_json(entry)
                    return 0
                match = next(m for m in entry['matches'] if m['key'] == options.match)
                side = match['home'] if options.winner == 'home' else match['away']
                print(f'awarded {match["label"]} to {entry["config"]["entrants"][side]["name"]}')
                if entry['state'] == 'running':
                    print(f'the tournament runs, {_plays_it(entry["id"])}')
                elif entry['error']:
                    print(f'the tournament stays {entry["state"]}, {entry["error"]}')
            elif action == 'resume':
                entry = tournaments.resume(options.target)
                if options.json:
                    _print_json(entry)
                    return 0
                print(f'resumed {entry["id"]}, {_plays_it(entry["id"])}')
            elif action == 'delete':
                tournaments.remove(options.target)
                if options.json:
                    _print_json({'id': options.target, 'deleted': True})
                else:
                    print(f'deleted {options.target}, its recordings stay in the library')
            else:
                tournaments.cancel(options.target)
                if options.json:
                    _print_json(tournaments.get(options.target))
                else:
                    print(f'cancelled {options.target}')
    finally:
        tournaments.close()
    return 0


_NEEDS_TARGET = ('show', 'run', 'cancel', 'forfeit', 'resume', 'delete')
_RUN_MESSAGES = {
    'done': 'the tournament is complete',
    'cancelled': 'the tournament was cancelled',
    'stopped': 'the tournament stopped, award the failed matches with cuju render '
    'tournament forfeit, or run it again to retry them',
    'people': 'the tournament waits for people, who play their matches on the Play page',
}
# How `show` names the state of a stage and how a tie was decided.
_STAGE_STATES = {
    'waiting': 'waiting for the stage before it',
    'ready': 'ready',
    'playing': 'playing',
    'done': 'finished',
}
_DECIDED = {
    'away goals': 'on away goals',
    'replay': 'after a replay',
    'decider': 'after deciding matches',
    'lots': 'by lots',
    'holder': 'the holder keeps it on a draw',
    'bye': 'a bye',
}
