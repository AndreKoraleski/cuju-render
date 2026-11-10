# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""Text captions of the events of a recording, and their WebVTT file.

A caption is a message id of the table `web/captions.json` with its values, such as `caption.goal`
with the player, the team and the score, so a translation replaces the table alone. The page shows
the same cues on Watch and Play by the same rules, in `web/js/recording/captions.js`, and a test
holds the wording and timing of both to each other.
"""

from __future__ import annotations

import functools
import json
import math
import re
from pathlib import Path
from typing import Any

# Seconds a cue stays at most and at least, as the page keeps them.
CUE_SECONDS = 4.0
MIN_CUE_SECONDS = 1.5
TABLE = Path(__file__).parents[1] / 'web' / 'captions.json'
_RESTARTS = ('corner', 'free_kick', 'penalty', 'throw_in', 'goal_kick')
_PLACE = re.compile(r'\{([A-Za-z]+)\}')


@functools.cache
def messages() -> dict[str, str]:
    """Returns the table of caption messages by id."""
    return dict(json.loads(TABLE.read_text(encoding='utf-8'))['messages'])


def format_message(table: dict[str, str], identifier: str, params: dict[str, Any]) -> str:
    """Returns the text of a message with its values in place of the names in braces."""
    template = table.get(identifier)
    if not isinstance(template, str):
        return identifier

    def value(match: re.Match[str]) -> str:
        name = match.group(1)
        return match.group(0) if name not in params else _text(params[name])

    return _PLACE.sub(value, template)


def _text(value: Any) -> str:
    """Returns a value as JavaScript turns it into text."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def _style_players(style: Any) -> list[Any]:
    players = style.get('players') if isinstance(style, dict) else None
    return players if isinstance(players, list) else []


def context(header: dict[str, Any], registry: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Returns the names of the teams and the number and roster name of every player.

    A team of the header that names a team of the registry takes the registry's current roster,
    as the page does by default, and any other team the roster saved in the header. A player
    without a roster entry wears 1 in goal and one more than the index of the team otherwise.

    Args:
        header: The header of a recording.
        registry: The teams of the registry, as `_teams.teams` returns them, or `None` to read
            them.
    """
    if registry is None:
        try:
            from .._registry import teams as _teams

            registry = _teams.teams()
        except Exception:
            registry = []
    known = {entry.get('id'): entry for entry in registry if isinstance(entry, dict)}
    teams = header.get('teams') or []
    names: list[str | None] = []
    rosters = []
    for side in (0, 1):
        team = teams[side] if side < len(teams) and isinstance(teams[side], dict) else {}
        name = team.get('name')
        names.append(name.strip() if isinstance(name, str) and name.strip() else None)
        entry = known.get(team.get('id')) if team.get('id') is not None else None
        style = entry.get('style') if entry is not None else team.get('style')
        rosters.append(_style_players(style or {}))
    players = []
    for player in header.get('players') or []:
        side, index = player.get('team', 0), player.get('index', 0)
        roster = rosters[side] if side in (0, 1) else []
        entry = (
            roster[index] if 0 <= index < len(roster) and isinstance(roster[index], dict) else None
        )
        number = 1 if player.get('goalkeeper') else index + 1
        name = ''
        if entry is not None:
            value = entry.get('number')
            whole = isinstance(value, int) and not isinstance(value, bool)
            number = value if whole and 0 <= value <= 99 else index + 1
            name = entry['name'][:24].strip() if isinstance(entry.get('name'), str) else ''
        players.append({'team': side, 'number': number, 'name': name})
    return {'teams': names, 'players': players}


def _team(table: dict[str, str], context_: dict[str, Any], side: int) -> str:
    name = context_['teams'][side] if side in (0, 1) else None
    return name or format_message(
        table, 'caption.side.left' if side == 0 else 'caption.side.right', {}
    )


def _player(table: dict[str, str], context_: dict[str, Any], k: int) -> str:
    entry = context_['players'][k]
    if entry['name']:
        return format_message(
            table, 'caption.player.named', {'number': entry['number'], 'name': entry['name']}
        )
    return format_message(table, 'caption.player', {'number': entry['number']})


def caption(
    moment: dict[str, Any], context_: dict[str, Any], table: dict[str, str] | None = None
) -> tuple[str, dict[str, Any]] | None:
    """Returns the message id and values of the caption of a moment, or `None` for none."""
    table = messages() if table is None else table
    data = moment.get('data') or {}
    k = moment.get('player')
    known = k is not None and 0 <= k < len(context_['players'])
    player = _player(table, context_, k) if known else None
    team = _team(table, context_, moment['team']) if moment.get('team') is not None else None
    of = _team(table, context_, context_['players'][k]['team']) if known else None
    score = data.get('score')
    score = {'left': score[0], 'right': score[1]} if isinstance(score, list) else {}
    kind = moment['kind']
    if kind == 'goal':
        if data.get('ownGoal') and known:
            return 'caption.goal.own', {'player': player, 'otherTeam': of, **score}
        if known:
            return 'caption.goal', {'player': player, 'team': team, **score}
        return ('caption.goal.team', {'team': team, **score}) if team else None
    if kind == 'shot':
        if not known:
            return None
        return ('caption.shot.header' if data.get('header') else 'caption.shot'), {
            'player': player,
            'team': of,
        }
    if kind in ('save', 'block', 'tackle', 'foul', 'offside'):
        return (f'caption.{kind}', {'player': player, 'team': of}) if known else None
    if kind == 'card':
        if not known:
            return None
        if data.get('colour') == 'red':
            identifier = 'caption.card.secondYellow' if data.get('second') else 'caption.card.red'
        else:
            identifier = 'caption.card.yellow'
        return identifier, {'player': player, 'team': of}
    if kind == 'woodwork':
        return (
            'caption.woodwork.bar' if data.get('part') == 'bar' else 'caption.woodwork.post'
        ), {}
    if kind == 'nearMiss':
        return (
            'caption.nearMiss.over' if data.get('line') == 'over' else 'caption.nearMiss.wide'
        ), {}
    if kind == 'restart':
        restart = data.get('restart')
        return (
            (f'caption.restart.{restart}', {'team': team})
            if restart in _RESTARTS and team
            else None
        )
    if kind == 'halftime':
        return 'caption.halftime', score
    if kind == 'fulltime':
        winner = data.get('winner')
        if winner in (0, 1):
            return 'caption.fulltime.win', {'team': _team(table, context_, winner), **score}
        return 'caption.fulltime.draw', score
    return None


def cues(
    moments: list[dict[str, Any]], context_: dict[str, Any], table: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """Returns the cues of moments in the order of their starts, as the page times them.

    A cue holds its `start` and `end` in seconds of the recording, its message `id` and `params`,
    its `text`, the `kind` and the id of its `moment`. It lasts four seconds, or until the next
    cue starts, and at least a second and a half.
    """
    table = messages() if table is None else table
    found = []
    for moment in moments:
        made = caption(moment, context_, table)
        if made is None:
            continue
        identifier, params = made
        found.append(
            {
                'start': moment['t'],
                'end': 0.0,
                'id': identifier,
                'params': params,
                'text': format_message(table, identifier, params),
                'kind': moment['kind'],
                'moment': moment['id'],
            }
        )
    found.sort(key=lambda cue: cue['start'])
    for index, cue in enumerate(found):
        following = found[index + 1]['start'] if index + 1 < len(found) else math.inf
        cue['end'] = max(cue['start'] + MIN_CUE_SECONDS, min(cue['start'] + CUE_SECONDS, following))
    return found


def vtt_time(seconds: float) -> str:
    """Returns a time of a WebVTT file, hours, minutes, seconds and milliseconds."""
    ms = math.floor(max(0.0, seconds) * 1000 + 0.5)
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    whole, ms = divmod(ms, 1000)
    return f'{hours:02d}:{minutes:02d}:{whole:02d}.{ms:03d}'


def to_vtt(found: list[dict[str, Any]]) -> str:
    """Returns cues as the text of a WebVTT file."""
    lines = ['WEBVTT', '']
    for index, cue in enumerate(found):
        lines += [
            str(index + 1),
            f'{vtt_time(cue["start"])} --> {vtt_time(cue["end"])}',
            cue['text'],
            '',
        ]
    return '\n'.join(lines)
