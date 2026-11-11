# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The hands-on tutorial for agents, the lessons of the page as steps of the command line, Python
and the page's scripts, each checked from the state of the renderer's home folder.

The page and this module read one catalog, `web/lessons.json`, so a person and an agent learn the
same lessons in the same order. A person's lesson ends when the page sees it done, and an agent's
lesson ends when its check holds.

- `recording` holds when the library keeps a recording outside the Trash.
- `match_played` holds when the library keeps a game of the Play page or a requested match of at
  least 300 steps, 30 seconds of match time.
- `team` holds when the registry keeps a team besides the built-in AI.
- `challenge` holds when the library keeps an attempt of a headless challenge or a leaderboard
  keeps a run.
- `page` holds once a page has reported the lesson done, as the page does for every lesson it
  sees done, so an agent that drives the page through `window.cuju` learns those lessons there.
  The page watches these lessons whether or not one was started, so the printed steps alone do.

The page reports its lessons to `POST /api/help/tutorial`, which keeps them in `tutorial.json` of
the home folder, and the reset of the tutorial clears that file.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from cuju.errors import ArgumentError

from .._registry import teams as _teams
from .._store import home as _home
from .._store import library as _library
from .._text import messages as _messages
from .._text.messages import MessageError

_CATALOG = Path(__file__).parents[1] / 'web' / 'lessons.json'
# The file of the home folder that keeps the lessons a page reported done.
_PROGRESS = 'tutorial.json'
# The steps of a game that count as 30 seconds of match time.
PLAYED_STEPS = 300
CHECKS = ('recording', 'match_played', 'team', 'challenge', 'page')


def lessons() -> list[dict[str, Any]]:
    """Returns the lessons of the catalog in their order."""
    document = json.loads(_CATALOG.read_text(encoding='utf-8'))
    return list(document['lessons'])


def _ids() -> list[str]:
    return [lesson['id'] for lesson in lessons()]


def page_progress() -> dict[str, Any]:
    """Returns the lessons that pages reported done, with the time of each report."""
    try:
        stored = json.loads((_home.home() / _PROGRESS).read_text())
    except (OSError, ValueError):
        return {}
    known = set(_ids())
    if not isinstance(stored, dict) or not isinstance(stored.get('page'), dict):
        return {}
    return {
        key: value
        for key, value in stored['page'].items()
        if key in known and isinstance(value, str)
    }


def _keep(progress: dict[str, Any]) -> None:
    path = _home.home() / _PROGRESS
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.part')
    temporary.write_text(json.dumps({'page': progress}))
    temporary.replace(path)


def report(done: Any) -> dict[str, Any]:
    """Keeps the lessons that a page reports done and returns the state of every lesson.

    Raises:
        ArgumentError: If `done` is not a list of lesson identifiers.
    """
    known = _ids()
    if not isinstance(done, list) or not all(isinstance(item, str) for item in done):
        raise MessageError('server.tutorial.done', known=known, done=repr(done))
    unknown = [item for item in done if item not in known]
    if unknown:
        raise MessageError('server.tutorial.unknown', known=known, unknown=unknown)
    progress = page_progress()
    stamp = time.strftime('%Y-%m-%dT%H:%M:%S')
    for item in done:
        progress.setdefault(item, stamp)
    _keep(progress)
    return state()


def reset() -> dict[str, Any]:
    """Forgets the lessons that pages reported, and returns the state of every lesson.

    The lessons whose checks read the library and the registry stay done while those hold.
    """
    (_home.home() / _PROGRESS).unlink(missing_ok=True)
    return state()


def _facts() -> dict[str, bool]:
    """Returns which of the checks of the home folder hold."""
    recordings = _library.matches()
    played = False
    attempted = False
    for entry in recordings:
        provenance = entry.get('provenance') if isinstance(entry.get('provenance'), dict) else {}
        source = provenance.get('source')
        steps = entry.get('steps') if isinstance(entry.get('steps'), int) else 0
        if source in ('human_game', 'requested_match') and steps >= PLAYED_STEPS:
            played = True
        if source == 'challenge':
            attempted = True
    if not attempted:
        folder = _home.home() / 'challenges'
        for path in folder.glob('*.json') if folder.is_dir() else []:
            try:
                document = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            if isinstance(document, dict) and document.get('entries'):
                attempted = True
                break
    team = any(entry.get('kind') != 'builtin' for entry in _teams.teams())
    return {
        'recording': bool(recordings),
        'match_played': played,
        'team': team,
        'challenge': attempted,
    }


def state() -> dict[str, Any]:
    """Returns every lesson with its agent's goal and steps and whether its check holds.

    Returns:
        A dictionary with `lessons`, each with `id`, `title`, `check`, `goal`, `steps` and `done`,
        `next`, the first lesson not done or `None`, and `page`, the lessons that pages reported.
    """
    facts = _facts()
    reported = page_progress()
    entries = []
    for lesson in lessons():
        agent = lesson['agent']
        check = agent['check']
        done = lesson['id'] in reported or facts.get(check, False)
        entries.append(
            {
                'id': lesson['id'],
                'title': lesson['title'],
                'page': lesson['page'],
                'check': check,
                'goal': agent['goal'],
                'steps': agent['steps'],
                'done': bool(done),
            }
        )
    upcoming = next((entry['id'] for entry in entries if not entry['done']), None)
    return {'lessons': entries, 'next': upcoming, 'page': sorted(reported)}


def lesson_state(identifier: str) -> dict[str, Any]:
    """Returns the state of one lesson.

    Raises:
        ArgumentError: If no lesson has that identifier.
    """
    for entry in state()['lessons']:
        if entry['id'] == identifier:
            return entry
    raise MessageError('server.tutorial.lesson', lessons=_ids(), identifier=repr(identifier))


def _step_line(step: dict[str, Any]) -> str:
    for kind, label in (('run', 'run'), ('python', 'python'), ('http', 'http'), ('script', 'page')):
        if kind in step:
            return f'      {label}  {step[kind]}'
    return ''


def text(document: dict[str, Any]) -> str:
    """Returns the tutorial, or one lesson of it, as lines for a terminal."""
    entries = document['lessons'] if 'lessons' in document else [document]
    lines = []
    for number, entry in enumerate(entries, 1):
        mark = 'done' if entry['done'] else 'to do'
        lines.append(f'{number}. {entry["title"]}, {mark}, lesson {entry["id"]}')
        lines.append(f'   {entry["goal"]}')
        for step in entry['steps']:
            lines.append(f'   - {step["say"]}')
            line = _step_line(step)
            if line:
                lines.append(line)
        if entry['check'] == 'page' and not entry['done']:
            lines.append(
                '   The page reports this lesson once a person or a script does it there, '
                'with the page open on the server.'
            )
    if 'lessons' in document:
        upcoming = document.get('next')
        if upcoming is None:
            lines.append('Every lesson is done.')
        else:
            title = next(entry['title'] for entry in entries if entry['id'] == upcoming)
            lines.append(f'Next, {title}, cuju render tutorial {upcoming}')
    return '\n'.join(lines)


def get(parts: list[str], query: dict[str, str]) -> tuple[Any, int]:
    """Answers `GET /api/help/tutorial` and `GET /api/help/tutorial/<lesson>`."""
    if not parts:
        return state(), 200
    if len(parts) == 1:
        try:
            return lesson_state(parts[0]), 200
        except ArgumentError as error:
            return _messages.error_fields(error), 404
    return _messages.fields('server.no_resource'), 404


def post(parts: list[str], document: dict[str, Any]) -> tuple[Any, int]:
    """Answers `POST /api/help/tutorial`, with `done` to report lessons or `reset` to clear them."""
    if parts:
        return _messages.fields('server.no_resource'), 404
    if document.get('reset') is True:
        return reset(), 200
    return report(document.get('done')), 200


def run(lesson: str | None, as_json: bool, clear: bool, check: bool) -> int:
    """Runs `cuju render tutorial`, printing the lessons or one lesson, and returns the status.

    With `check`, the status is 0 when the lessons shown are done and 2 otherwise.
    """
    document = reset() if clear else state()
    shown: dict[str, Any] = lesson_state(lesson) if lesson else document
    if as_json:
        print(json.dumps(shown, indent=2))
    else:
        if clear:
            print('cleared the lessons that pages reported')
        print(text(shown))
    done = shown['done'] if lesson else shown['next'] is None
    return 0 if done or not check else 2
