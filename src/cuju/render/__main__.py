# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The command line of the renderer, `cuju render`, also `python -m cuju.render`.

`cuju render` serves the page and opens Home, `cuju render open` opens a recording or a live
source, `cuju render team add FOLDER` registers a Kaggle submission folder, `cuju render play`
records a match between two registered teams, `cuju render tournament` makes, lists, shows, runs
and cancels tournaments, and `cuju render sample` adds the shipped sample matches to the library
again, or brings them back from the Trash. `cuju render demo` streams a live match between the
built-in AIs to the page.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from cuju.errors import Error

from ._store import home as _home


def main(arguments: list[str] | None = None) -> int:
    """Runs the command that the arguments name and returns its exit status."""
    parser = argparse.ArgumentParser(
        prog='cuju render', description="Watch cuju's matches in a browser."
    )
    parser.add_argument(
        '--home', help=f'the renderer folder, by default {_home.home()} or ${_home.HOME_VARIABLE}'
    )
    commands = parser.add_subparsers(dest='command')
    server = commands.add_parser(
        'serve', help='serve the page, which a bare cuju render also opens'
    )
    server.add_argument('--port', type=int, default=8780, help='the port, 8780 by default')
    server.add_argument('--open', action='store_true', help='open the page in the browser')
    server.add_argument(
        '--remote',
        action='store_true',
        help='print the SSH command that reaches the page from another computer',
    )
    # A server that `cuju.render.show` starts ends with the process that started it.
    server.add_argument('--parent', type=int, default=None, help=argparse.SUPPRESS)
    server.add_argument('--colab', action='store_true', help=argparse.SUPPRESS)
    opener = commands.add_parser(
        'open', help='open a recording file, a recording or live source, or a URL of the page'
    )
    opener.add_argument('target', help='a .cjr file, a recording or live source identifier, a URL')
    opener.add_argument(
        '--port',
        type=int,
        default=8780,
        help='the port of a server that it starts, 8780 by default',
    )
    team = commands.add_parser('team', help='add, list, export or remove teams of the registry')
    team.add_argument('action', choices=('add', 'list', 'export', 'remove'))
    team.add_argument(
        'target', nargs='?', help='a submission folder or archive to add, or a team identifier'
    )
    team.add_argument('--name', help='the name of an added team, by default the folder name')
    team.add_argument(
        '--format',
        choices=('5v5', '11v11'),
        default='11v11',
        help='the size of an added team, 11v11 by default, unless its folder holds an export',
    )
    team.add_argument('--out', help='the zip file of an export, by default the team name')
    match = commands.add_parser('play', help='record a match between two registered teams')
    match.add_argument('--left', default='builtin', help='a team identifier, or builtin')
    match.add_argument('--right', default='builtin', help='a team identifier, or builtin')
    match.add_argument(
        '--scenario',
        default='11_vs_11_kaggle',
        help='a shipped scenario, 11_vs_11_kaggle by default',
    )
    match.add_argument('--seed', type=int, default=None, help='the seed, drawn when absent')
    match.add_argument('--device', default='cpu', help='cpu or cuda, cpu by default')
    for side in ('left', 'right'):
        match.add_argument(
            f'--{side}-ability',
            type=float,
            default=None,
            help=f"the {side} built-in AI's ability from 0 to 1, the scenario's when absent",
        )
    _tournament_parser(commands)
    sample = commands.add_parser(
        'sample', help='add the sample matches to the library again, or restore them from the Trash'
    )
    sample.add_argument(
        'name', nargs='?', choices=('11v11', '5v5'), help='one sample, by default both'
    )
    show = commands.add_parser('demo', help='stream a live match between the built-in AIs')
    show.add_argument('--port', type=int, default=8780, help='the port, 8780 by default')
    show.add_argument('--eleven', action='store_true', help='eleven a side, five by default')
    show.add_argument('--scenario', help='another shipped scenario, such as academy_corner')
    show.add_argument('--seed', type=int, default=None, help='the seed, drawn when absent')
    show.add_argument('--no-open', action='store_true', help='leave the browser closed')
    options = parser.parse_args(arguments)
    if options.home:
        os.environ[_home.HOME_VARIABLE] = str(Path(options.home).expanduser().resolve())
    try:
        from ._http.launch import check_home

        check_home()
        return _run(parser, options)
    except (Error, OSError) as error:
        print(f'cuju render: {error}', file=sys.stderr)
        return 1


def _run(parser: argparse.ArgumentParser, options: argparse.Namespace) -> int:
    """Runs one command of the parsed command line."""
    if options.command == 'team':
        from ._registry import teams as _teams

        if options.action in ('export', 'remove') and not options.target:
            parser.error(f'team {options.action} needs the identifier of a team')
        if options.action == 'add' and not options.target:
            parser.error('team add needs a submission folder or archive')
        if options.action == 'add':
            entry = _teams.add_folder(options.target, options.name, options.format)
            print(f'added {entry["id"]} {entry["name"]}')
        elif options.action == 'export':
            filename, data = _teams.export(options.target)
            path = options.out or filename
            with open(path, 'wb') as stream:
                stream.write(data)
            print(f'exported {path}')
        elif options.action == 'remove':
            if not _teams.remove(options.target):
                parser.error(f'no team {options.target!r} to remove')
        else:
            for entry in _teams.teams():
                print(f'{entry["id"]}  {entry["format"]}  {entry["name"]}')
        return 0
    if options.command == 'sample':
        from ._store import library as _library

        names = None if options.name is None else [f'sample-{options.name}']
        trashed = {entry['id'] for entry in _library.matches(trash=True)}
        added = _library.add_samples(names)
        for path in added:
            print(f'{"restored" if path.stem in trashed else "added"} {path.stem}')
        if not added:
            print('the library already holds the samples')
        return 0
    if options.command == 'tournament':
        from ._tournaments.tournament_cli import run_command

        return run_command(parser, options)
    if options.command == 'play':
        from ._playing.play import play

        path = play(
            options.left,
            options.right,
            options.scenario,
            options.seed,
            None,
            options.device,
            (options.left_ability, options.right_ability),
        )
        print(f'saved {path}')
        return 0
    if options.command == 'demo':
        from ._playing import demo as _demo

        if not 0 <= options.port <= 65535:
            parser.error('expected a port from 0 to 65535')
        from cuju import bundled_scenarios

        scenario = options.scenario or _demo.SCENARIOS['11v11' if options.eleven else '5v5']
        if scenario not in bundled_scenarios():
            parser.error(f'expected a shipped scenario, found {scenario!r}')
        return _demo.demo(options.port, scenario, not options.no_open, options.seed)
    port = getattr(options, 'port', 8780)
    if not 0 <= port <= 65535:
        parser.error('expected a port from 0 to 65535')
    from ._http.commands import open_target, serve_page

    if options.command == 'open':
        return open_target(options.target, port)
    return serve_page(port, options)


def _tournament_parser(commands: Any) -> None:
    """Adds `cuju render tournament` with its actions and options."""

    class Entrant(argparse.Action):
        """Keeps the entrants of every kind in the order the command line names them."""

        def __call__(self, parser: Any, namespace: Any, value: Any, flag: Any = None) -> None:
            kind = {'--team': 'team', '--builtin': 'builtin', '--person': 'person'}[flag]
            entrants = getattr(namespace, 'entrants', None) or []
            entrants.append((kind, value))
            namespace.entrants = entrants

    cup = commands.add_parser('tournament', help='make, list, show, run or cancel tournaments')
    cup.add_argument('action', choices=('new', 'list', 'show', 'run', 'cancel', 'presets'))
    cup.add_argument('target', nargs='?', help='the identifier of a tournament')
    cup.add_argument('--preset', help='a preset of formats, quick_cup when neither it nor --config')
    cup.add_argument('--config', help='a JSON file with the whole configuration of a tournament')
    cup.add_argument('--name', help='the name of the tournament')
    cup.add_argument('--seed', type=int, help='the tournament seed, drawn when absent')
    cup.add_argument('--team', action=Entrant, dest='entrants', help='a registered team')
    cup.add_argument(
        '--builtin', action=Entrant, dest='entrants', help='the built-in AI at an ability, or any'
    )
    cup.add_argument('--person', action=Entrant, dest='entrants', help='a person, by name')
    cup.add_argument('--seeding', choices=('random', 'manual', 'rating'))
    cup.add_argument('--scenario', help='the scenario of every stage')
    cup.add_argument('--length', type=int, help='the steps of every match')
    cup.add_argument('--concurrency', type=int, help='the matches of agents at once, 1 by default')
    cup.add_argument('--run', action='store_true', help='run the new tournament at once')


if __name__ == '__main__':
    sys.exit(main())
