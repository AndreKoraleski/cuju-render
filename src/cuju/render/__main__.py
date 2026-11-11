# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The command line of the renderer, `cuju render`, also `python -m cuju.render`.

`cuju render` serves the page and opens Home, `cuju render open` opens a recording or a live
source, `cuju render app` opens the page in a window of its own and with `--install` adds it to
the computer's apps, `cuju render team add FOLDER` registers a Kaggle submission folder,
`cuju render play` records a match between two registered teams, `cuju render challenge` lists
the challenges or plays one headless with a team, `cuju render tournament` makes, lists, shows, runs
and cancels tournaments, and `cuju render sample` adds the shipped sample matches and the starter
team again, or brings them back from the Trash. `cuju render recordings` lists the
library with the group of each challenge run, `cuju render search` finds moments across the
library, and `cuju render captions` writes the captions of a recording as WebVTT. `cuju render demo`
streams a live match between the built-in AIs to the page, and `cuju render video` exports a range
of a recording as an MP4 or WebM video, drawn and encoded by the page in a headless Chrome, Edge or
Chromium.
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
import json
import os
import sys
from pathlib import Path
from typing import Any

from cuju.errors import Error

from ._store import home as _home
from ._text.messages import counted


def main(arguments: list[str] | None = None) -> int:
    """Runs the command that the arguments name and returns its exit status."""
    parser = argparse.ArgumentParser(
        prog='cuju render', description="Watch cuju's matches in a browser."
    )
    parser.add_argument(
        '--home',
        help=f'the renderer folder, by default the folder of ${_home.HOME_VARIABLE} when set, '
        'else ~/.cuju/render',
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
    _app_parser(commands)
    team = commands.add_parser(
        'team', help='add, list, show, set, export, remove or give sounds to teams of the registry'
    )
    team.add_argument('action', choices=('add', 'list', 'show', 'set', 'export', 'remove', 'sound'))
    team.add_argument(
        'target', nargs='?', help='a submission folder or archive to add, or a team identifier'
    )
    team.add_argument(
        'sound',
        nargs='*',
        metavar='KIND [FILE]',
        help='for team sound, the moment, goal, shot, pass, tackle, save, kick, celebration or '
        'chant, and the Ogg, MP3 or WAV file of at most 2 MB that it plays',
    )
    team.add_argument(
        '--remove', action='store_true', help='for team sound, remove the sound of the moment'
    )
    team.add_argument(
        '--name', help='the name of the team, by default the folder name of an added one'
    )
    team.add_argument(
        '--format',
        choices=('5v5', '11v11'),
        default=None,
        help='the size of the team, 11v11 by default for an added team, unless its folder holds '
        'an export',
    )
    _team_control_arguments(team)
    team.add_argument('--out', help='the zip file of an export, by default the team name')
    team.add_argument(
        '--json', action='store_true', help='print the team, or the list of teams, as JSON'
    )
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
    match.add_argument('--json', action='store_true', help='print the saved recording as JSON')
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
    challenge.add_argument(
        '--no-recordings',
        action='store_true',
        help='score the run without keeping its attempts as recordings',
    )
    challenge.add_argument(
        '--json', action='store_true', help='print the catalog or the result of a run as JSON'
    )
    listing = commands.add_parser(
        'recordings', help='list the recordings with the group of each challenge run'
    )
    listing.add_argument('--group', help='list the recordings of one group alone')
    listing.add_argument('--trash', action='store_true', help='list the Trash')
    moves = listing.add_mutually_exclusive_group()
    moves.add_argument(
        '--delete-group', metavar='GROUP', help='move every recording of a group to the Trash'
    )
    moves.add_argument(
        '--restore-group', metavar='GROUP', help='restore every recording of a group'
    )
    listing.add_argument('--json', action='store_true', help='print the recordings as JSON')
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
    sample.add_argument(
        '--json', action='store_true', help='print the list, or the changes, as JSON'
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
    show = commands.add_parser(
        'demo',
        help='stream a live match between the built-in AIs',
        description='Starts the server unless one answers on the port, streams a live match '
        'between the built-in AIs at real time and opens the page on it, until Ctrl+C.',
    )
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
        help='export a range of a recording as an MP4 or WebM video, with Chrome or Edge',
        description='Draws a range of a recording on the page in a headless Chrome, Edge or '
        'Chromium, frame by frame, and encodes it in the browser, MP4 with H.264 where the browser '
        'encodes it and WebM otherwise. ffmpeg, when installed, encodes an MP4 that the browser '
        'cannot. The video is silent.',
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
    pack.add_argument(
        '--json',
        action='store_true',
        help='print the result of a check, or the address and team of a preview, as JSON',
    )
    pack.add_argument(
        '--no-open', action='store_true', help='open no browser for a preview, print its address'
    )
    pack.add_argument(
        '--name', default='My team', help='the name of a new team, by default My team'
    )
    from ._text import languages as _languages

    _languages.add_arguments(
        commands.add_parser(
            'language',
            help='write, check, list, add or remove a language of the page',
            description='Writes a new language file from English, checks a file against English, '
            'and lists, adds or removes the languages of the home folder.',
        )
    )
    options = parser.parse_args(arguments)
    as_json = bool(getattr(options, 'json', False))
    if as_json:
        # A command that fails under --json answers with JSON on standard output alone.
        parser.error = _json_usage  # type: ignore[method-assign]
    if options.command == 'language' and options.action in ('check', 'new'):
        return _languages.run(options)
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
        return _failed(error, as_json)


def _app_parser(commands: Any) -> None:
    """Adds `cuju render app`, the page in a window of its own, and its launchers."""
    app = commands.add_parser(
        'app',
        help="open the page in a window of its own, or add it to the computer's apps",
        description='Opens the page in a window of its own, through the system web view of '
        "pywebview, from the extra cuju-render[app], else a Chromium browser's app mode, else "
        'the default browser. A server of the home folder is reused, and one that this command '
        'starts ends with the window. --install adds a launcher to the Start menu and the desktop '
        'on Windows, the applications menu on Linux or ~/Applications on macOS, and --uninstall '
        'removes exactly what --install made.',
    )
    app.add_argument(
        '--port', type=int, default=None, help='the port of a server that it starts, 8780 when free'
    )
    app.add_argument(
        '--route',
        choices=['auto', 'webview', 'chromium', 'browser'],
        default='auto',
        help='the system web view, a Chromium app window or the default browser, the first that '
        'the computer has by default',
    )
    app.add_argument('--browser', help='the Chromium browser for the route chromium, its program')
    launcher = app.add_mutually_exclusive_group()
    launcher.add_argument(
        '--install', action='store_true', help="add a launcher of the app to the computer's apps"
    )
    launcher.add_argument(
        '--uninstall', action='store_true', help='remove the launchers that --install made'
    )


def _app(parser: argparse.ArgumentParser, options: argparse.Namespace) -> int:
    """Runs `cuju render app`."""
    if options.install or options.uninstall:
        from ._http import launchers as _launchers

        return _launchers.run(options.install, options.route, options.browser)
    if options.port is not None and not 0 <= options.port <= 65535:
        parser.error('expected a port from 0 to 65535')
    from ._http import window as _window

    return _window.run(options.port, options.route, options.browser)


def _failed(error: BaseException, as_json: bool) -> int:
    """Prints the error of a command that failed and returns the exit status 1.

    Under --json the error goes to standard output alone, as a JSON object of `error`, its text,
    and `error_id` and `error_values`, the message that the error carries or null, so a script
    reads one answer whatever happens. Otherwise a line goes to standard error.
    """
    if not as_json:
        print(f'cuju render: {error}', file=sys.stderr)
        return 1
    from ._text import messages as _messages

    # An error raised again with the same text keeps the message of its cause.
    cause = error.__cause__
    if getattr(error, 'message_id', None) is None and isinstance(cause, _messages.Message):
        error, shown = cause, str(error)
    else:
        shown = str(error)
    print(json.dumps(_messages.entry_fields(error, shown), indent=1))
    return 1


def _json_usage(message: str) -> None:
    """Ends a command whose arguments do not fit, under --json, with the error as JSON."""
    print(json.dumps({'error': message, 'error_id': None, 'error_values': None}, indent=1))
    sys.exit(2)


def _run(parser: argparse.ArgumentParser, options: argparse.Namespace) -> int:
    """Runs one command of the parsed command line."""
    if options.command == 'app':
        return _app(parser, options)
    if options.command == 'team':
        from ._registry import teams as _teams

        if options.action in ('show', 'set', 'export', 'remove', 'sound') and not options.target:
            parser.error(f'team {options.action} needs the identifier of a team')
        if options.action == 'add' and not options.target:
            parser.error('team add needs a submission folder or archive')
        control = _team_control(options)
        if options.action == 'add':
            entry = _teams.add_folder(
                options.target, options.name, options.format or '11v11', control
            )
            _print_team(entry, options.json, 'added')
        elif options.action == 'show':
            _print_team(_teams.entry(options.target), options.json, None)
        elif options.action == 'sound':
            _team_sound(_teams, options)
        elif options.action == 'set':
            if control is not None:
                control = _changed_control(_teams, options, control)
            entry = _teams.update(options.target, options.name, None, options.format, control)
            _print_team(entry, options.json, 'changed')
        elif options.action == 'export':
            filename, data = _teams.export(options.target)
            path = options.out or filename
            with open(path, 'wb') as stream:
                stream.write(data)
            print(f'exported {path}')
        elif options.action == 'remove':
            if not _teams.remove(options.target):
                parser.error(f'no team {options.target!r} to remove')
            print(f'removed {options.target}')
        elif options.json:
            print(json.dumps(_teams.teams(), indent=1))
        else:
            for entry in _teams.teams():
                print(f'{entry["id"]}  {entry["format"]}  {entry["name"]}')
        return 0
    if options.command == 'sample':
        from ._store import samples as _samples

        if options.name == 'list':
            if options.json:
                print(json.dumps(_samples.listing(), indent=1))
                return 0
            for entry in _samples.listing():
                print(f'{entry["id"]}  {entry["kind"]}  {entry["state"]}  {entry["title"]}')
            return 0
        names = None
        if options.name is not None:
            names = [options.name if '-' in options.name else f'sample-{options.name}']
        result = _samples.add(names)
        if options.json:
            print(json.dumps(result, indent=1))
            return 0
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
    if options.command == 'language':
        from ._text import languages as _languages

        return _languages.run(options)
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
    if options.command == 'recordings':
        return _recordings(options)
    if options.command == 'play':
        return _play_match(options)
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


def _team_sound(teams: Any, options: argparse.Namespace) -> None:
    """Runs `cuju render team sound ID [KIND [FILE]]`, which lists, gives or removes sounds.

    A sound is checked as the page's upload is, `PUT /api/teams/ID/sounds/KIND`.
    """
    from cuju.errors import ArgumentError

    kind, *rest = options.sound or [None]
    if kind is not None and kind not in teams.SOUND_SLOTS:
        raise ArgumentError(
            f'expected the moment of a sound among {", ".join(teams.SOUND_SLOTS)}, found {kind}'
        )
    if kind is not None and options.remove:
        teams.entry(options.target)
        teams.remove_sound(options.target, kind)
    elif kind is not None and rest:
        teams.set_sound(options.target, kind, Path(rest[0]).expanduser().read_bytes())
    elif kind is not None:
        raise ArgumentError('expected the sound file of the moment, or --remove')
    entry = teams.entry(options.target)
    if options.json:
        print(json.dumps({'team': entry['id'], 'sounds': entry['sounds']}))
    else:
        print(f'{entry["name"]}, sounds {", ".join(entry["sounds"]) or "none"}')


def _team_control_arguments(team: Any) -> None:
    """Adds the options of `cuju render team` that set the players a submission controls."""
    team.add_argument(
        '--players', type=int, help='the players that the submission controls, 1 by default'
    )
    team.add_argument(
        '--assignment',
        choices=('dynamic', 'fixed'),
        help='dynamic for the players nearest the ball, fixed for those of --selection',
    )
    team.add_argument(
        '--selection',
        help='the fixed players, as indices of the formation or GRF roles, such as 1,2,3 or CB,CM',
    )
    team.add_argument(
        '--goalkeeper',
        choices=('agent', 'builtin', 'scenario'),
        help='who plays the goalkeeper, the submission, the built-in AI or as the scenario says',
    )
    team.add_argument(
        '--action-set',
        choices=('default', 'v2'),
        help="the submission's action set, GRF's default or v2",
    )


def _team_control(options: argparse.Namespace) -> dict[str, Any] | None:
    """Returns the control that the options of `cuju render team` name, or `None` for none."""
    control: dict[str, Any] = {}
    if options.players is not None:
        control['players'] = options.players
    if options.selection is not None:
        parts = [part.strip() for part in options.selection.split(',') if part.strip()]
        control['selection'] = [int(part) if part.isdigit() else part for part in parts]
        control['assignment'] = 'fixed'
        control.setdefault('players', len(parts))
    if options.assignment is not None:
        control['assignment'] = options.assignment
    if options.goalkeeper is not None:
        control['goalkeeper'] = options.goalkeeper
    if options.action_set is not None:
        control['action_set'] = options.action_set
    return control or None


def _changed_control(teams: Any, options: argparse.Namespace, control: dict[str, Any]) -> Any:
    """Returns a team's control with the changes of `cuju render team set` applied to it."""
    current = teams.entry(options.target)
    try:
        known = teams.check_control(current.get('control'), options.format or current['format'])
    except Error:
        known = dict(teams.DEFAULT_CONTROL)
    if control.get('assignment', known['assignment']) == 'dynamic':
        # Dynamic assignment keeps no selection, and the goalkeeper goes back to the scenario.
        known['selection'] = []
        if known['goalkeeper'] == 'builtin':
            known['goalkeeper'] = 'scenario'
    return {**known, **control}


def _print_team(entry: dict[str, Any], as_json: bool, change: str | None) -> None:
    """Prints a team of the registry, as JSON or as lines of its name, format and control."""
    if as_json:
        print(json.dumps(entry, indent=1))
        return
    head = f'{change} ' if change else ''
    print(f'{head}{entry["id"]} {entry["name"]}')
    control = entry.get('control')
    if entry.get('kind') != 'builtin' and isinstance(control, dict):
        selection = ','.join(str(item) for item in control.get('selection') or []) or 'none'
        print(
            f'  format {entry["format"]}, {control["players"]} controlled, assignment '
            f'{control["assignment"]}, selection {selection}, goalkeeper '
            f'{control["goalkeeper"]}, action set {control["action_set"]}'
        )


_QUERY_HELP = (
    'Words name kinds, such as goal, shot, save, pass, tackle, card, corner or penalty, and '
    'filters such as team:, player:, after:, before:, score:, source: and outcome: narrow them.'
)


def _find(options: argparse.Namespace) -> int:
    """Prints the moments that a search finds, under the identifier and title of each recording,
    or as JSON.

    Each moment shows its clock, its time `t` in seconds of the recording, its line of text and the
    whole address that opens Watch a few seconds before it, on the running server or, when none
    runs, on the port that `cuju render serve` takes by default.
    """
    import json

    from ._http import launch as _launch
    from ._moments import search as _search

    found = _search.search(' '.join(options.query), options.limit)
    if options.json:
        print(json.dumps(found, indent=1))
        return 0
    server = _launch.running()
    base = server.url if server is not None else 'http://127.0.0.1:8780/'
    match = None
    for result in found['results']:
        if result['match'] != match:
            match = result['match']
            print(f'{match}  {result["title"]}')
        print(f'  {result["minute"]:>6}  t={result["t"]:g}  {result["text"]}')
        print(f'          {base}{result["url"]}')
    shown = len(found['results'])
    moments = counted(found['total'], 'moment')
    print(f'{shown} of {moments} in {counted(found["recordings"], "recording")}')
    if shown and server is None:
        print('No server runs, and cuju render open with an address above in quotes starts one.')
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

    from ._packages import pack
    from ._packages import presentation as _presentation

    try:
        if options.action == 'sides':
            changes = {
                side: (None if value == 'none' else value)
                for side in ('left', 'right')
                if (value := getattr(options, side)) is not None
            }
            sides = _presentation.assign(changes) if changes else _presentation.sides()
            print(json.dumps(sides) if options.json else '\n'.join(pack.sides_lines(sides)))
            return 0
        if not options.target:
            return _failed(Error('expected the package to preview'), options.json)
        return pack.run_preview(
            options.target, options.side, port, not options.no_open, options.json
        )
    except (Error, OSError) as error:
        return _failed(error, options.json)


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
            print('\n'.join(pack.next_steps(options.target)))
            return 0
        result = pack.check(options.target)
    except (Error, OSError) as error:
        return _failed(error, options.json)
    if options.json:
        print(json.dumps(result, indent=2))
    else:
        print(pack.text_report(result, options.target))
    return 0 if result['ok'] else 1


def _tournament_parser(commands: Any) -> None:
    """Adds `cuju render tournament` with its actions and options."""

    class Entrant(argparse.Action):
        """Keeps the entrants of every kind in the order the command line names them.

        `--as` names the entrant just before it, so a team entered twice reads apart.
        """

        def __call__(self, parser: Any, namespace: Any, value: Any, flag: Any = None) -> None:
            kinds = {'--team': 'team', '--builtin': 'builtin', '--person': 'person', '--as': 'as'}
            kind = kinds[flag]
            entrants = getattr(namespace, 'entrants', None) or []
            entrants.append((kind, value))
            namespace.entrants = entrants

    cup = commands.add_parser(
        'tournament', help='make, check, list, show, run, change or delete tournaments'
    )
    cup.add_argument(
        'action',
        choices=(
            'new',
            'check',
            'list',
            'show',
            'run',
            'cancel',
            'delete',
            'presets',
            'ratings',
            'forfeit',
            'award',
            'resume',
        ),
    )
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
    cup.add_argument(
        '--as',
        action=Entrant,
        dest='entrants',
        metavar='NAME',
        help='the name of the entrant just before it, such as a team entered twice',
    )
    cup.add_argument('--seeding', choices=('random', 'manual', 'rating'))
    cup.add_argument('--scenario', help='the scenario of every stage')
    cup.add_argument('--length', type=int, help='the steps of every match')
    cup.add_argument('--concurrency', type=int, help='the matches of agents at once, 1 by default')
    cup.add_argument('--run', action='store_true', help='run the new tournament at once')
    cup.add_argument('--rounds', type=int, help='the rounds of every Swiss or ladder stage')
    cup.add_argument('--match', help='the key of the match that forfeit or award gives')
    cup.add_argument(
        '--winner', choices=('home', 'away'), help='the side that forfeit or award gives it to'
    )
    cup.add_argument('--json', action='store_true', help='print what the action prints as JSON')


def _progress_line() -> Any:
    """Returns a function that shows the progress of a match on one line of a terminal.

    The line goes to standard error and only to a terminal, so the output of a script or a pipe
    holds the result alone.
    """
    if not sys.stderr.isatty():
        return None

    def show(share: float) -> None:
        print(f'\rplaying, {share:.0%}', end='', file=sys.stderr, flush=True)

    return show


def _play_match(options: argparse.Namespace) -> int:
    """Plays a match between two registered teams and prints the recording it saved.

    What the submissions print goes to standard error, so standard output holds the result alone.
    """
    import contextlib
    import json

    from ._playing.play import play

    progress = None if options.json else _progress_line()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            path = play(
                options.left,
                options.right,
                options.scenario,
                options.seed,
                None,
                options.device,
                (options.left_ability, options.right_ability),
                progress=progress,
                policy_errors=True,
            )
    finally:
        if progress is not None:
            print('\r\033[K', end='', file=sys.stderr, flush=True)
    if options.json:
        print(json.dumps({'match': path.stem, 'path': str(path)}))
    else:
        print(f'saved {path}')
    return 0


def _challenge(parser: argparse.ArgumentParser, options: argparse.Namespace) -> int:
    """Lists the challenges, or plays one headless and prints each attempt and the result."""
    import contextlib
    import json

    from ._playing import challenges as _challenges

    if options.name == 'list' and options.json:
        print(json.dumps(_challenges.challenges(), indent=1))
        return 0
    if options.name == 'list':
        for entry in _challenges.challenges():
            targets = ', '.join(
                f'{medal} {target}'
                for medal, target in zip(_challenges.MEDALS, entry['targets'], strict=True)
            )
            attempts = counted(entry['attempts'], 'attempt')
            print(f'{entry["id"]}  {entry["title"]}, {attempts}, {targets}')
            print(f'    {entry["goal"]}')
        return 0
    if not options.team:
        parser.error('challenge needs --team, a team identifier or builtin')
    from ._playing.play import PolicyError

    spec = _challenges.find(options.name)

    def show(result: dict) -> None:
        if result['scored']:
            seconds = f'scored after {counted(result["seconds"], "second")}'
            if not result['counts'] and spec['limit'] is not None:
                seconds += f', past the limit of {counted(spec["limit"], "second")}'
        else:
            seconds = 'no goal'
        goals = f'{result["goals"][0]} for, {result["goals"][1]} against'
        kept = f'recording {result["match"]}' if result['match'] else 'no recording kept'
        print(
            f'attempt {result["index"] + 1}, seed {result["seed"]}, {seconds}, {goals}, {kept}',
            flush=True,
        )

    try:
        # What a team prints goes to standard error, so standard output holds the result alone.
        with contextlib.redirect_stdout(sys.stderr if options.json else sys.stdout):
            outcome = _challenges.run(
                options.name,
                team=options.team,
                attempts=options.attempts,
                device=options.device,
                progress=None if options.json else show,
                keep_recordings=not options.no_recordings,
            )
    except PolicyError as error:
        return _failed(error, options.json)
    if options.json:
        print(json.dumps(outcome, indent=1))
        return 0
    if any(result['counts'] for result in outcome['attempts']):
        print(f'value {outcome["value"]:g}, {counted(outcome["seconds"], "second")} to score')
    elif spec['measure'] == 'margin':
        print(f'value {outcome["value"]:g}, no goal scored')
    else:
        print(f'value {outcome["value"]:g}, no attempt counts towards it')
    if outcome['practice']:
        print('practice, fewer attempts than the challenge, so no medal and no leaderboard')
    else:
        print(f'medal {outcome["medal"] or "none"}, rank {outcome["rank"] or "outside the board"}')
        best = outcome['personal_best']
        print(f'personal best {best["value"]:g} in {counted(best["seconds"], "second")}')
    if outcome['group']:
        print(f'group {outcome["group"]}, list it with cuju render recordings --group')
    return 0


def _recordings(options: argparse.Namespace) -> int:
    """Lists the library by group, or one group, or moves a group to the Trash or back."""
    from ._store import library as _library

    moved = options.delete_group or options.restore_group
    if moved:
        restore = bool(options.restore_group)
        changed = _library.trash_group(moved, restore=restore)
        if options.json:
            print(json.dumps({'group': moved, 'restored' if restore else 'trashed': changed}))
        elif changed:
            where = 'from the Trash' if restore else 'to the Trash'
            print(f'moved {counted(len(changed), "recording")} of {moved} {where}')
        if not changed:
            place = 'the Trash' if restore else 'the library'
            print(f'cuju render: no group {moved} in {place}', file=sys.stderr)
            return 1
        return 0
    entries = _library.matches(options.trash, options.group)
    if options.json:
        print(json.dumps(entries, indent=1))
        return 0
    if options.group and not entries:
        print(f'cuju render: no group {options.group}', file=sys.stderr)
        return 1
    listed = set()
    for entry in entries:
        group = entry.get('group')
        if group is None:
            print(f'{entry["id"]}  {entry["title"]}')
            continue
        if group['id'] in listed:
            continue
        listed.add(group['id'])
        members = [item for item in entries if (item.get('group') or {}).get('id') == group['id']]
        members.sort(key=lambda item: item['group'].get('attempt', 0))
        shown = counted(len(members), 'recording')
        print(f'{group["id"]}  {group["title"]}, {group["result"]}, {shown}')
        for member in members:
            print(f'    {member["id"]}  attempt {member["group"].get("attempt", 0) + 1}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
