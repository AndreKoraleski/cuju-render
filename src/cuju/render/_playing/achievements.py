# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""Achievements, earned by people on the Play page and by teams of the registry, from the frames.

One set of rules reads the frames of a recording, so a person and an agent earn by exactly the
same rules. `detect` returns the achievements that one side earned in one recording, from the
score, the clock, the game mode, the ball, the touches and the engine's scorer that every frame
holds. Teams of the registry keep what they earned in a JSON file each, in the folder
`achievements` of the renderer's home, with the first time, the count and the recording of the
first time of each one. People keep theirs in the browser.

Requested matches, challenges and anything else that plays registered teams, such as a
tournament, award a finished recording through `award_match`.
"""

from __future__ import annotations

import json
import logging
import math
import struct
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .._format import recording as _recording
from .._registry import teams as _teams
from .._store import home as _home

_LOGGER = logging.getLogger('cuju')
# GRF: the goal lines lie 55 meters either way of the center spot, along x.
_GOAL_X = 55.0
_SCREAMER_METERS = 25.0
_SET_PIECE_SECONDS = 10.0
# GRF: the game modes of a corner and of a penalty.
_CORNER, _PENALTY = 4, 6
_ROUT = 5
_HEAD = struct.Struct('<8i7f4i')

# The catalog, in the order the page lists it. Each glyph is two letters that a badge may show.
CATALOG: tuple[dict[str, str], ...] = (
    {'id': 'off_the_mark', 'name': 'Off the mark', 'glyph': 'OM', 'description': 'Score a goal.'},
    {
        'id': 'hat_trick',
        'name': 'Hat trick',
        'glyph': 'HT',
        'description': 'One player scores three goals or more in one recording.',
    },
    {
        'id': 'corner_goal',
        'name': 'Straight from the corner',
        'glyph': 'CK',
        'description': 'Score within ten seconds of your own corner, with play running on.',
    },
    {
        'id': 'penalty_goal',
        'name': 'From the spot',
        'glyph': 'PK',
        'description': 'Score within ten seconds of your own penalty, with play running on.',
    },
    {
        'id': 'keeper_goal',
        'name': 'Goalkeeper goal',
        'glyph': 'GK',
        'description': 'Your goalkeeper scores.',
    },
    {
        'id': 'screamer',
        'name': 'Screamer',
        'glyph': 'SC',
        'description': "Score with the scorer's last touch 25 meters or more from the goal.",
    },
    {
        'id': 'giant_slayer',
        'name': 'Giant slayer',
        'glyph': 'GS',
        'description': 'Win against the built-in AI at ability 1.0, outside the academy.',
    },
    {
        'id': 'comeback',
        'name': 'Comeback',
        'glyph': 'CB',
        'description': 'Win after trailing.',
    },
    {
        'id': 'clean_sheet',
        'name': 'Clean sheet',
        'glyph': 'CS',
        'description': 'Finish a full match without conceding.',
    },
    {
        'id': 'rout',
        'name': 'Rout',
        'glyph': 'RT',
        'description': 'Win by five goals or more.',
    },
    {
        'id': 'last_gasp',
        'name': 'Last gasp',
        'glyph': 'LG',
        'description': (
            'Win with the decisive goal in the last tenth of a match of a minute or more.'
        ),
    },
    {
        'id': 'podium',
        'name': 'On the podium',
        'glyph': 'MD',
        'description': 'Win a medal in a challenge.',
    },
    {
        'id': 'gold_standard',
        'name': 'Gold standard',
        'glyph': 'AU',
        'description': 'Win a gold medal in a challenge.',
    },
    {
        'id': 'academy_graduate',
        'name': 'Academy graduate',
        'glyph': 'AG',
        'description': 'Hold a gold medal in every challenge.',
    },
)
IDENTIFIERS = tuple(entry['id'] for entry in CATALOG)


def _frame(header: dict[str, Any], frame: bytes) -> dict[str, Any]:
    """Returns what the rules read of one frame, as the guide's Recording format lays it out."""
    values = _HEAD.unpack_from(frame, 0)
    players = len(header.get('players') or ())
    padded = -(-players // 4) * 4
    start = _HEAD.size + players * len(_recording.NODES) * 14 + 2 * padded
    return {
        'mode': values[1],
        'score': (values[2], values[3]),
        'clock': values[6],
        'flags': values[7],
        'ball': (values[8], values[9]),
        'touches': frame[start : start + players],
    }


def _goals(header: dict[str, Any], frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Returns every goal of the frames, its frame, team and scorer, an own goal named as such.

    The scorer comes from the engine's scorer bits of the frame flags, its index in the header's
    players plus one, and a scorer of the other team scored an own goal. A recording without the
    engine's scorer names none.
    """
    goals = []
    engine = bool(header.get('engine_scorer'))
    for index in range(1, len(frames)):
        before, now = frames[index - 1]['score'], frames[index]['score']
        for team in (0, 1):
            for _ in range(max(0, now[team] - before[team])):
                scorer = ((frames[index]['flags'] >> 8) & 31) - 1 if engine else -1
                goals.append({'index': index, 'team': team, 'scorer': scorer})
    return goals


def _restart_before(frames: list[dict[str, Any]], index: int, side: int) -> int | None:
    """Returns the game mode of the restart of `side` that play ran on from into frame `index`.

    The restart is the last frame of a set piece before the goal, within ten seconds of it, with
    the ball at the side's attacking end and only open play between it and the goal.
    """
    span = int(_SET_PIECE_SECONDS * 10)
    for at in range(index - 1, max(-1, index - span - 1), -1):
        mode = frames[at]['mode']
        if mode == 0:
            continue
        x = frames[at]['ball'][0]
        attacking = x > 0 if side == 0 else x < 0
        return mode if attacking else None
    return None


def detect(header: dict[str, Any], frames: Iterable[bytes], side: int) -> list[str]:
    """Returns the achievements that one side earned in one recording, in catalog order.

    Wins count only for a finished episode, one whose last frame has the episode end flag, of a
    scenario outside the academy.

    Args:
        header: The header of the recording.
        frames: Its frames, as `_recording.frames` yields them.
        side: 0 for the left team and 1 for the right.
    """
    parsed = [_frame(header, frame) for frame in frames]
    if not parsed:
        return []
    players = header.get('players') or []
    goals = _goals(header, parsed)
    ours = [goal for goal in goals if goal['team'] == side]
    earned = set()
    if ours:
        earned.add('off_the_mark')
    scorers: dict[int, int] = {}
    for goal in ours:
        scorer = goal['scorer']
        own = 0 <= scorer < len(players) and players[scorer].get('team') == side
        if own:
            scorers[scorer] = scorers.get(scorer, 0) + 1
            if players[scorer].get('goalkeeper'):
                earned.add('keeper_goal')
            last = _last_touch(parsed, goal['index'], scorer)
            if last is not None:
                x, y = parsed[last]['ball']
                target = _GOAL_X if side == 0 else -_GOAL_X
                if math.hypot(target - x, y) >= _SCREAMER_METERS:
                    earned.add('screamer')
        restart = _restart_before(parsed, goal['index'], side)
        if restart == _CORNER:
            earned.add('corner_goal')
        elif restart == _PENALTY:
            earned.add('penalty_goal')
    if any(count >= 3 for count in scorers.values()):
        earned.add('hat_trick')
    first, last = parsed[0], parsed[-1]
    finished = bool(last['flags'] & 1)
    conceded = last['score'][1 - side] - first['score'][1 - side]
    if finished and header.get('full_match') and conceded == 0 and first['score'][1 - side] == 0:
        earned.add('clean_sheet')
    academy = str(header.get('scenario', '')).startswith('academy_')
    final = last['score']
    if finished and not academy and final[side] > final[1 - side]:
        teams = header.get('teams') or [{}, {}]
        other = teams[1 - side] if len(teams) == 2 and isinstance(teams[1 - side], dict) else {}
        ability = other.get('ability')
        if (
            other.get('id') == _teams.BUILTIN
            and isinstance(ability, (int, float))
            and (ability >= 0.999)
        ):
            earned.add('giant_slayer')
        if any(frame['score'][side] < frame['score'][1 - side] for frame in parsed):
            earned.add('comeback')
        if final[side] - final[1 - side] >= _ROUT:
            earned.add('rout')
        duration = last['clock'] - first['clock']
        decisive = next(
            (goal for goal in ours if parsed[goal['index']]['score'][side] == final[1 - side] + 1),
            None,
        )
        if (
            decisive is not None
            and duration >= 60000
            and parsed[decisive['index']]['clock'] >= first['clock'] + 0.9 * duration
        ):
            earned.add('last_gasp')
    return [identifier for identifier in IDENTIFIERS if identifier in earned]


def _last_touch(frames: list[dict[str, Any]], index: int, player: int) -> int | None:
    """Returns the last frame up to `index` in which `player` touched the ball, or `None`."""
    for at in range(index, max(-1, index - 300), -1):
        touches = frames[at]['touches']
        if player < len(touches) and touches[player]:
            return at
    return None


# The achievements of challenges, which read the leaderboards.


def challenge_awards(medals: dict[str, str | None], won: str | None) -> list[str]:
    """Returns the achievements of a run of a challenge that won `won`.

    Args:
        medals: The medal of the competitor's best run of every challenge, after this run.
        won: The medal of this run, or `None`.
    """
    from . import challenges as _challenges

    earned = []
    if won is not None:
        earned.append('podium')
    if won == 'gold':
        earned.append('gold_standard')
    if won is not None and all(medals.get(entry['id']) == 'gold' for entry in _challenges.CATALOG):
        earned.append('academy_graduate')
    return earned


def _medals(kind: str, name: str | None, team: str | None) -> dict[str, str | None]:
    from . import challenges as _challenges

    bests = _challenges.personal_bests(kind, name, team)
    return {identifier: entry['medal'] for identifier, entry in bests.items()}


def for_person_run(recordings: list[tuple[dict[str, Any], list[bytes]]], outcome: dict[str, Any]):
    """Returns the achievements of a person's run of a challenge, from its recordings and medal."""
    earned = set()
    for header, frames in recordings:
        earned.update(detect(header, frames, 0))
    earned.update(challenge_awards(_medals('person', outcome['name'], None), outcome['medal']))
    return [identifier for identifier in IDENTIFIERS if identifier in earned]


def for_agent_run(outcome: dict[str, Any]) -> list[str]:
    """Records and returns the achievements of an agent's run of a challenge.

    A team of the registry, the built-in AI aside, keeps what each attempt's recording and the
    medal earned. A Python policy keeps nothing on disk, and the run names its achievements.
    """
    earned: dict[str, str | None] = {}
    for result in outcome['attempts']:
        path = _home.folder('matches') / f'{result["match"]}.cjr'
        header = _recording.read_header(path)
        for identifier in detect(header, list(_recording.frames(path)), 0):
            earned.setdefault(identifier, result['match'])
    medals = _medals('agent', outcome['name'], outcome['team']) if not outcome['practice'] else {}
    first = outcome['attempts'][0]['match'] if outcome['attempts'] else None
    for identifier in challenge_awards(medals, outcome['medal']):
        earned.setdefault(identifier, first)
    team = outcome['team']
    if team is not None and team != _teams.BUILTIN:
        _award(team, earned)
    return [identifier for identifier in IDENTIFIERS if identifier in earned]


# What teams of the registry earned, on disk.


def _path(team: str) -> Path:
    return _home.folder('achievements') / f'{team}.json'


def _valid(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get('first'), (int, float))
        and not isinstance(value.get('first'), bool)
        and isinstance(value.get('count'), int)
        and not isinstance(value.get('count'), bool)
        and value['count'] >= 1
        and (value.get('match') is None or isinstance(value.get('match'), str))
    )


def earned(team: str) -> dict[str, dict[str, Any]]:
    """Returns what a team earned, by achievement, each with its first time, count and recording.

    A file that does not read, or an entry of the wrong form, is skipped with one warning through
    the logger `cuju`.
    """
    if not _home.valid_identifier(team):
        return {}
    path = _path(team)
    if not path.is_file():
        return {}
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        _LOGGER.warning('cuju render skips the achievements file %s, %s', path.name, error)
        return {}
    entries = document.get('earned') if isinstance(document, dict) else None
    if not isinstance(entries, dict) or document.get('team') != team:
        _LOGGER.warning(
            'cuju render skips the achievements file %s, which holds none of %s', path.name, team
        )
        return {}
    kept = {
        key: {'first': value['first'], 'count': value['count'], 'match': value.get('match')}
        for key, value in entries.items()
        if key in IDENTIFIERS and _valid(value)
    }
    if len(kept) != len(entries):
        _LOGGER.warning(
            'cuju render skips %d invalid entries of the achievements file %s',
            len(entries) - len(kept),
            path.name,
        )
    return kept


def _award(team: str, achievements: dict[str, str | None]) -> list[str]:
    """Adds achievements to a team's file and returns those the team earned for the first time.

    Args:
        team: The registry identifier of the team.
        achievements: The recording of each achievement earned, or `None`.
    """
    if not achievements or not _home.valid_identifier(team):
        return []
    from .challenges import _locked

    with _locked():
        current = earned(team)
        new = [identifier for identifier in achievements if identifier not in current]
        now = time.time()
        for identifier, match in achievements.items():
            if identifier in current:
                current[identifier]['count'] += 1
            else:
                current[identifier] = {'first': now, 'count': 1, 'match': match}
        document = {'team': team, 'earned': current}
        _teams._replace(_path(team), json.dumps(document).encode())
    return [identifier for identifier in IDENTIFIERS if identifier in new]


def award_match(
    header: dict[str, Any] | bytes, frames: list[bytes], team_ids: list[str | None], match=None
) -> dict[str, list[str]]:
    """Awards the teams of the registry what they earned in one recording, and returns it.

    Requested matches call this once their recording is saved, and so may anything else that
    plays registered teams, such as a tournament. The built-in AI and a side without a team of the
    registry earn nothing.

    Args:
        header: The header of the recording, as a dictionary or as `_recording.header` returns
            its bytes.
        frames: The frames of the recording.
        team_ids: The registry identifier of the left and the right team, or `None`.
        match: The identifier of the recording in the library, which the file names as the first
            time of an achievement, or `None`.

    Returns:
        The achievements that each team earned in the recording, by team.
    """
    if isinstance(header, (bytes, bytearray)):
        header = json.loads(bytes(header[len(_recording.MAGIC) + 4 :]))
    awarded: dict[str, list[str]] = {}
    for side, team in enumerate(team_ids[:2]):
        if not isinstance(team, str) or team == _teams.BUILTIN:
            continue
        found = detect(header, frames, side)
        _award(team, dict.fromkeys(found, match))
        awarded[team] = found
    return awarded


def public() -> dict[str, Any]:
    """Returns the catalog and what every team of the registry earned, for the page."""
    teams = {}
    folder = _home.folder('achievements')
    for path in sorted(folder.glob('*.json')):
        kept = earned(path.stem)
        if kept:
            teams[path.stem] = kept
    return {'catalog': list(CATALOG), 'teams': teams}


def for_game(head: bytes, frames: list[bytes], sides: list[int]) -> list[list[str] | None]:
    """Returns the achievements of each person's side of a game on the Play page, else `None`."""
    header = json.loads(head[len(_recording.MAGIC) + 4 :])
    return [detect(header, frames, side) if side in sides else None for side in (0, 1)]
