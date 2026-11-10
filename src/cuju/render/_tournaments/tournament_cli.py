# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The command `cuju render tournament`, which makes, lists, shows, runs and cancels tournaments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from cuju.errors import ArgumentError

from . import tournament as rules
from . import tournament_runner as _tournament_runner


def _config(options: argparse.Namespace) -> dict[str, Any]:
    """Returns the configuration that the options of `new` describe."""
    if options.config:
        config = json.loads(Path(options.config).read_text(encoding='utf-8'))
        if not isinstance(config, dict):
            raise ArgumentError(f'expected a JSON object in {options.config}')
    else:
        config = {'preset': options.preset or 'quick_cup'}
    if options.preset and options.config:
        config['preset'] = options.preset
    if 'stages' not in config and config.get('preset'):
        base = rules.preset_config(config['preset'], _tournament_runner.presets())
        config = {**base, **config}
    entrants = []
    for kind, value in options.entrants or []:
        if kind == 'team':
            entrants.append({'kind': 'team', 'team': value})
        elif kind == 'person':
            entrants.append({'kind': 'person', 'name': value})
        else:
            ability = None if value in ('', 'any', 'scenario') else float(value)
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
    return config


def describe(entry: dict[str, Any]) -> list[str]:
    """Returns the lines that `show` prints, the stages with their tables and results."""
    names = [entrant['name'] for entrant in entry['config']['entrants']]

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
        lines.append(f'{stage["name"]}, {stage["format"].replace("_", " ")}, {stage["state"]}')
        for table in stage['tables']:
            lines.append(f'  {table["name"]}')
            for row in table['rows']:
                lines.append(
                    f'  {row["position"]:>3}  {names[row["entrant"]]:<28} {row["played"]:>3} '
                    f'{row["won"]:>3} {row["drawn"]:>3} {row["lost"]:>3} '
                    f'{row["for"]:>3}:{row["against"]:<3} {row["points"]:>4}'
                )
        for round_ in stage['rounds']:
            lines.append(f'  {round_["name"]}')
            for fixture in round_['fixtures']:
                score = fixture.get('score')
                text = '' if score is None else f'  {score[0]} to {score[1]}'
                how = fixture.get('decided_by')
                lines.append(
                    f'    {name(fixture["home"])} against {name(fixture["away"])}{text}'
                    + (f', {how}' if how and how not in ('score', 'aggregate') else '')
                )
    if entry['champion'] is not None:
        lines += ['', f'Champion: {entry["champion"]}']
    return lines


def run_command(parser: argparse.ArgumentParser, options: argparse.Namespace) -> int:
    """Runs one action of `cuju render tournament` and returns the exit status."""
    action = options.action
    if action in ('show', 'run', 'cancel') and not options.target:
        parser.error(f'tournament {action} needs the identifier of a tournament')
    if action == 'presets':
        for key, preset in _tournament_runner.presets().items():
            print(f'{key}  {preset["title"]}')
        return 0
    if action == 'run':
        tournaments = _tournament_runner.Tournaments(only=options.target, start=False)
        try:
            state = tournaments.run(options.target)
        finally:
            tournaments.close()
        messages = {
            'done': 'the tournament is complete',
            'cancelled': 'the tournament was cancelled',
            'stopped': 'the tournament stopped, run it again to retry',
            'people': 'the tournament waits for people, who play their matches on the Play page',
        }
        print(messages[state])
        return 0 if state in ('done', 'people') else 1
    tournaments = _tournament_runner.Tournaments(start=False)
    try:
        if action == 'new':
            entry = tournaments.create(_config(options))
            print(f'created {entry["id"]} {entry["name"]}')
            if options.run:
                tournaments.close()
                options.target = entry['id']
                options.action = 'run'
                return run_command(parser, options)
            print(
                f'a running cuju render serve plays it, or cuju render tournament run {entry["id"]}'
            )
        elif action == 'list':
            for entry in tournaments.entries():
                champion = f'  won by {entry["champion"]}' if entry['champion'] else ''
                print(
                    f'{entry["id"]}  {entry["state"]:<9}  {entry["played"]:>4} played  '
                    f'{entry["name"]}{champion}'
                )
        elif action == 'show':
            entry = tournaments.get(options.target)
            if entry is None:
                parser.error(f'no tournament {options.target!r}')
            print('\n'.join(describe(entry)))
        else:
            if not tournaments.cancel(options.target):
                parser.error(f'no tournament {options.target!r} to cancel')
            print(f'cancelled {options.target}')
    finally:
        tournaments.close()
    return 0
