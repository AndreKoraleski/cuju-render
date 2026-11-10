# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The command line of the renderer, `cuju render`, also `python -m cuju.render`.

`cuju render` serves the page and opens Home, `cuju render open` opens a recording or a live
source, `cuju render team add FOLDER` registers a Kaggle submission folder, `cuju render play`
records a match between two registered teams, `cuju render challenge` lists the challenges or
plays one headless with a team, `cuju render tournament` makes, lists, shows, runs
and cancels tournaments, and `cuju render sample` adds the shipped sample matches and the starter
team again, or brings them back from the Trash. `cuju render search` finds moments across the
library, and `cuju render captions` writes the captions of a recording as WebVTT. `cuju render demo`
streams a live match between the built-in AIs to the page, and `cuju render video` exports a range
of a recording as an MP4 video, drawn by the page in a headless Chrome and encoded by ffmpeg.
`cuju render tutorial` prints the lessons of the page for an agent and checks each one from the
home folder, `cuju render doctor` prints a diagnostic report, and `cuju render feed` prints the
addresses of clean feeds, pictures of fixed size for a streaming program such as OBS.
`cuju render pack check PATH` checks a team's presentation package as the server and the page
read it, `cuju render pack new FOLDER` writes a small working team with a package to start from,
`cuju render pack preview PATH` opens a package on a sample match with the preview panel, and
`cuju render pack sides` shows or sets the registered team whose presentation each side draws.
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
    challenge = commands.add_parser(
        'challenge', help='list the challenges, or play one headless with a registered team'
    )
    challenge.add_argument('name', help='list, or the challenge to play, such as empty_goal_close')
    challenge.add_argument('--team', help='a team identifier, or builtin')
    challenge.add_argument(
        '--attempts', type=int, default=None, help='fewer attempts than the challenge is practice'
    )
    challenge.add_argument('--device', default='cpu', help='cpu or cuda, cpu by default')
    sample = commands.add_parser(
        'sample',
        help='add the sample matches and the starter team again, or restore them from the Trash',
    )
    sample.add_argument(
        'name',
        nargs='?',
        choices=('11v11', '5v5', 'sample-11v11', 'sample-5v5', 'starter-team', 'list'),
        help='one sample, by default every one, or list to show what the library holds of each',
    )
    tutorial = commands.add_parser(
        'tutorial', help='the lessons of the page for an agent, each step checked from the server'
    )
    tutorial.add_argument('lesson', nargs='?', help='one lesson, such as seek_goal, by default all')
    tutorial.add_argument('--json', action='store_true', help='print the lessons as JSON')
    tutorial.add_argument(
        '--check', action='store_true', help='exit with status 2 until the lessons shown are done'
    )
    tutorial.add_argument(
        '--reset', action='store_true', help='forget the lessons that pages reported done'
    )
    from ._guide import doctor as _doctor

    doctor = commands.add_parser(
        'doctor', help='print a diagnostic report of versions, the home folder and the server'
    )
    _doctor.add_arguments(doctor)
    show = commands.add_parser('demo', help='stream a live match between the built-in AIs')
    show.add_argument('--port', type=int, default=8780, help='the port, 8780 by default')
    show.add_argument('--eleven', action='store_true', help='eleven a side, five by default')
    show.add_argument('--scenario', help='another shipped scenario, such as academy_corner')
    show.add_argument('--seed', type=int, default=None, help='the seed, drawn when absent')
    show.add_argument('--no-open', action='store_true', help='leave the browser closed')
    finder = commands.add_parser(
        'search',
        help='find moments of every recording, such as goal team:Greens after:60',
        description='Finds the moments of the library that a query names. ' + _QUERY_HELP,
    )
    finder.add_argument('query', nargs='*', help='words and filters, quoted as one argument or not')
    finder.add_argument('--limit', type=int, default=None, help='the most results, 50 by default')
    finder.add_argument('--json', action='store_true', help='print the results as JSON')
    captions = commands.add_parser(
        'captions', help='write the captions of a recording as a WebVTT file'
    )
    captions.add_argument('recording', help='a recording identifier of the library or a .cjr file')
    captions.add_argument('-o', '--out', help='the WebVTT file, by default printed')
    captions.add_argument('--json', action='store_true', help='print the cues as JSON')
    from ._export import video as _video

    video = commands.add_parser(
        'video',
        help='export a range of a recording as an MP4 video, with Chrome and ffmpeg',
        description='Draws a range of a recording on the page in a headless Chrome, frame by '
        'frame, and encodes it with ffmpeg. The video is silent.',
    )
    _video.add_arguments(video)
    from ._export import feed as _feed

    feed = commands.add_parser(
        'feed',
        help='print the address of a clean feed for OBS, or of every source a feed may follow',
        description='Prints the address of the page at /feed, a picture of fixed size with the '
        'broadcast graphics alone, for a browser source of OBS or another streaming program.',
    )
    _feed.add_arguments(feed)
    pack = commands.add_parser(
        'pack', help="check a team's presentation package, or write a new one to start from"
    )
    pack.add_argument('action', choices=('check', 'new', 'preview', 'sides'))
    pack.add_argument(
        'target',
        nargs='?',
        help='a team folder, cuju-team folder, presentation folder or .zip to check or preview, '
        'or the empty folder of a new team',
    )
    pack.add_argument(
        '--side', choices=('left', 'right'), default='left', help='the side a preview draws'
    )
    for side in ('left', 'right'):
        pack.add_argument(
            f'--{side}', help=f'the team whose presentation the {side} side draws, or none'
        )
    pack.add_argument('--port', type=int, default=8780, help='the port of a preview server')
    pack.add_argument('--json', action='store_true', help='print the result of a check as JSON')
    pack.add_argument(
        '--name', default='My team', help='the name of a new team, by default My team'
    )
    options = parser.parse_args(arguments)
    if options.command == 'pack' and options.action in ('check', 'new'):
        if not options.target:
            parser.error(f'expected the path that pack {options.action} reads or writes')
        return _pack(options)
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
        from ._store import samples as _samples

        if options.name == 'list':
            for entry in _samples.listing():
                print(f'{entry["id"]}  {entry["kind"]}  {entry["state"]}  {entry["title"]}')
            return 0
        names = None
        if options.name is not None:
            names = [options.name if '-' in options.name else f'sample-{options.name}']
        result = _samples.add(names)
        for change in result['changes']:
            target = next(e['target'] for e in result['samples'] if e['id'] == change['id'])
            named = f' as {target}' if target != change['id'] else ''
            print(f'{change["change"]} {change["id"]}{named}')
        if not result['changes']:
            print('the library already holds the samples')
        return 0
    if options.command == 'tutorial':
        from ._guide import tutorial as _tutorial

        return _tutorial.run(options.lesson, options.json, options.reset, options.check)
    if options.command == 'doctor':
        from ._guide import doctor as _doctor

        return _doctor.run(options)
    if options.command == 'search':
        return _find(options)
    if options.command == 'captions':
        return _write_captions(options)
    if options.command == 'tournament':
        from ._tournaments.tournament_cli import run_command

        return run_command(parser, options)
    if options.command == 'video':
        from ._export import video as _video

        return _video.run(options)
    if options.command == 'feed':
        from ._export import feed as _feed

        return _feed.run(options)
    if options.command == 'challenge':
        return _challenge(parser, options)
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
    if options.command == 'pack':
        return _pack_home(options, port)
    return serve_page(port, options)


_QUERY_HELP = (
    'Words name kinds, such as goal, shot, save, pass, tackle, card, corner or penalty, and '
    'filters such as team:, player:, after:, before:, score:, source: and outcome: narrow them.'
)


def _find(options: argparse.Namespace) -> int:
    """Prints the moments that a search finds, one a line or as JSON."""
    import json

    from ._moments import search as _search

    found = _search.search(' '.join(options.query), options.limit)
    if options.json:
        print(json.dumps(found, indent=1))
        return 0
    for result in found['results']:
        print(f'{result["match"]}  {result["minute"]:>6}  t={result["seek"]:g}  {result["text"]}')
    shown = len(found['results'])
    print(f'{shown} of {found["total"]} moments in {found["recordings"]} recordings')
    return 0


def _write_captions(options: argparse.Namespace) -> int:
    """Writes or prints the captions of a recording."""
    import json

    from ._moments import search as _search

    if options.json:
        text = json.dumps(_search.captions(options.recording), indent=1)
    else:
        text = _search.captions_vtt(options.recording)
    if options.out:
        Path(options.out).write_text(text, encoding='utf-8', newline='\n')
        print(f'wrote {options.out}')
    else:
        print(text)
    return 0


def _pack_home(options: argparse.Namespace, port: int) -> int:
    """Runs `cuju render pack preview` and `cuju render pack sides`, which use the home."""
    import json

    from ._http.commands import open_target
    from ._packages import pack
    from ._packages import presentation as _presentation

    try:
        if options.action == 'sides':
            changes = {
                side: (None if value == 'none' else value)
                for side in ('left', 'right')
                if (value := getattr(options, side)) is not None
            }
            print(json.dumps(_presentation.assign(changes) if changes else _presentation.sides()))
            return 0
        if not options.target:
            print('cuju render: expected the package to preview', file=sys.stderr)
            return 1
        place = pack.preview(options.target, options.side)
    except (Error, OSError) as error:
        print(f'cuju render: {error}', file=sys.stderr)
        return 1
    print(f'previewing on the {options.side} side, {place}')
    return open_target(f'http://127.0.0.1:{port}/{place}', port)


def _pack(options: argparse.Namespace) -> int:
    """Checks a presentation package or writes a new team, and returns the exit status.

    A check exits with 0 when the package holds no error and 1 otherwise. Both run without the
    renderer's home, which they never read.
    """
    import json

    from ._packages import pack

    try:
        if options.action == 'new':
            for path in pack.new(options.target, options.name):
                print(f'wrote {path}')
            return 0
        result = pack.check(options.target)
    except (Error, OSError) as error:
        print(f'cuju render: {error}', file=sys.stderr)
        return 1
    if options.json:
        print(json.dumps(result, indent=2))
    else:
        print(pack.text_report(result, options.target))
    return 0 if result['ok'] else 1


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


def _challenge(parser: argparse.ArgumentParser, options: argparse.Namespace) -> int:
    """Lists the challenges, or plays one headless and prints each attempt and the result."""
    from ._playing import challenges as _challenges

    if options.name == 'list':
        for entry in _challenges.challenges():
            targets = ', '.join(
                f'{medal} {target}'
                for medal, target in zip(_challenges.MEDALS, entry['targets'], strict=True)
            )
            print(f'{entry["id"]}  {entry["title"]}, {entry["attempts"]} attempts, {targets}')
            print(f'    {entry["goal"]}')
        return 0
    if not options.team:
        parser.error('challenge needs --team, a team identifier or builtin')
    from ._playing.play import PolicyError

    def show(result: dict) -> None:
        if result['scored']:
            seconds = f'scored after {result["seconds"]:g} seconds'
        else:
            seconds = 'no goal'
        goals = f'{result["goals"][0]} for, {result["goals"][1]} against'
        print(
            f'attempt {result["index"] + 1}, seed {result["seed"]}, {seconds}, {goals}, '
            f'recording {result["match"]}',
            flush=True,
        )

    try:
        outcome = _challenges.run(
            options.name,
            team=options.team,
            attempts=options.attempts,
            device=options.device,
            progress=show,
        )
    except PolicyError as error:
        print(f'cuju render: {error}', file=sys.stderr)
        return 1
    print(f'value {outcome["value"]:g}, {outcome["seconds"]:g} seconds to score')
    if outcome['practice']:
        print('practice, fewer attempts than the challenge, so no medal and no leaderboard')
    else:
        print(f'medal {outcome["medal"] or "none"}, rank {outcome["rank"] or "outside the board"}')
        best = outcome['personal_best']
        print(f'personal best {best["value"]:g} in {best["seconds"]:g} seconds')
    return 0


if __name__ == '__main__':
    sys.exit(main())
