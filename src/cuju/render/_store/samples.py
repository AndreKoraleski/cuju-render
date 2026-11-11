# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The samples that cuju ships, two recordings and a starter team, with what the library holds of
each.

The Help page lists them, `cuju render sample` adds them, and the tutorial offers them before a
lesson that needs a recording or a team. A recording sample is in the library, in the Trash or
missing, and adding it copies it in again or restores it, as `cuju render sample` always did. The
starter team is a small Kaggle submission, and adding it registers it as a team of its own, whose
identifier the home folder keeps in `sample-teams.json`, so the list knows it again.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .._registry import teams as _teams
from .._text.messages import MessageError
from . import home as _home
from . import library as _library

_FOLDER = Path(__file__).parents[1] / 'samples'
# The file of the home folder that names the teams the samples added.
_TEAMS_FILE = 'sample-teams.json'
# The sample teams, each a folder of `samples/teams`, with the name and format it registers under.
TEAMS = {
    'starter-team': {
        'folder': 'starter',
        'name': 'Starter team',
        'format': '11v11',
        'about': 'A Kaggle submission that runs at the ball, carries it to goal and shoots',
    },
}
# The titles of the recording samples.
_TITLES = {
    'sample-5v5': ('Five a side sample', 'A whole match of five a side between built in AIs'),
    'sample-11v11': ('Eleven a side sample', 'A whole match of eleven a side between built in AIs'),
}


def _added_teams() -> dict[str, str]:
    """Returns the teams that the samples added, by sample name."""
    try:
        stored = json.loads((_home.home() / _TEAMS_FILE).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(stored, dict):
        return {}
    return {key: value for key, value in stored.items() if key in TEAMS and isinstance(value, str)}


def _keep_teams(added: dict[str, str]) -> None:
    path = _home.home() / _TEAMS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.part')
    temporary.write_text(json.dumps(added))
    temporary.replace(path)


def _team_state(name: str, added: dict[str, str], known: set[str]) -> tuple[str, str | None]:
    """Returns whether a sample team is registered, and its identifier when it is."""
    identifier = added.get(name)
    if identifier and identifier in known:
        return 'library', identifier
    return 'missing', None


def names() -> list[str]:
    """Returns the names of every sample, the recordings first."""
    return [*_library.samples(), *TEAMS]


def listing() -> list[dict[str, Any]]:
    """Returns every sample with its kind, title, description and state.

    The state is `library` for a sample that the library or the registry holds, `trash` for a
    recording in the Trash and `missing` otherwise. A held sample carries the identifier to open.
    """
    entries = []
    for name in _library.samples():
        title, about = _TITLES.get(name, (name, 'A recording that cuju ships'))
        if _library.path_of(name) is not None:
            state = 'library'
        elif _library.path_of(name, include_trash=True) is not None:
            state = 'trash'
        else:
            state = 'missing'
        entries.append(
            {
                'id': name,
                'kind': 'recording',
                'title': title,
                'about': about,
                'state': state,
                'target': name if state == 'library' else None,
            }
        )
    added = _added_teams()
    known = {entry['id'] for entry in _teams.teams()}
    for name, team in TEAMS.items():
        state, identifier = _team_state(name, added, known)
        entries.append(
            {
                'id': name,
                'kind': 'team',
                'title': team['name'],
                'about': team['about'],
                'format': team['format'],
                'state': state,
                'target': identifier,
            }
        )
    return entries


def add(wanted: list[str] | None = None) -> dict[str, Any]:
    """Adds or restores samples, by default every one, and returns what changed and the listing.

    A recording in the Trash comes back with its details, a missing one is copied in again, and a
    missing team is registered again. A sample that the library already holds stays as it is.

    Raises:
        ArgumentError: If a name is not a shipped sample.
    """
    every = names()
    wanted = every if wanted is None else list(wanted)
    unknown = [name for name in wanted if name not in every]
    if unknown:
        raise MessageError('server.samples.unknown', every=every, unknown=unknown)
    before = {entry['id']: entry['state'] for entry in listing()}
    recordings = [name for name in wanted if name in _library.samples()]
    if recordings:
        _library.add_samples(recordings)
    added = _added_teams()
    for name in wanted:
        if name in TEAMS and before.get(name) == 'missing':
            team = TEAMS[name]
            entry = _teams.add_folder(
                _FOLDER / 'teams' / team['folder'], team['name'], team['format']
            )
            added[name] = entry['id']
            _keep_teams(added)
    after = listing()
    changes = []
    for entry in after:
        was = before.get(entry['id'])
        if entry['id'] in wanted and was != entry['state'] and entry['state'] == 'library':
            changes.append({'id': entry['id'], 'change': 'restored' if was == 'trash' else 'added'})
    return {'changes': changes, 'samples': after}


def team_folder(name: str) -> Path:
    """Returns the folder of a sample team, which a person may copy to start a team.

    Raises:
        ArgumentError: If the name is not a sample team.
    """
    if name not in TEAMS:
        raise MessageError('server.samples.team', teams=list(TEAMS), name=repr(name))
    return _FOLDER / 'teams' / TEAMS[name]['folder']
