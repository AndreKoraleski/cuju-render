# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The rules of the renderer's tournaments, their formats, draws, schedules and standings.

A tournament is a configuration, its entrants, its seed and a chain of stages, together with the
results of the matches played so far. `evaluate` replays the whole tournament from those two
things alone. It draws the groups and seeds, schedules every match whose sides are known, settles
every decided tie and computes the tables, so the same configuration and seed always give the same
draw, the same matches and the same match seeds, and a tournament resumes from its results after
any stop. Each match has a stable key, such as `0/sf1/2` for the second leg of the first
semi-final of the first stage, and its seed comes from the tournament seed and that key.

The module uses Python's standard library alone, so that the page's mock server can load it from
its file. Whatever needs the team registry takes it as an argument, and the server passes it in.
"""

from __future__ import annotations

import copy
import hashlib
import math
import random
from collections.abc import Callable
from typing import Any

from .._text import messages as _messages

# The formats of a stage.
FORMATS = (
    'knockout',
    'double_elimination',
    'league',
    'groups',
    'swiss',
    'ladder',
    'king_of_the_hill',
    'gauntlet',
)
# The criteria that order a table after points, in the order a stage names them.
TIEBREAKERS = (
    'goal_difference',
    'goals_for',
    'goals_against',
    'head_to_head',
    'wins',
    'away_goals',
    'fair_play',
    'buchholz',
    'lots',
)
# The ways of settling a knockout tie whose matches end level, in the order a stage names them.
SETTLEMENTS = ('away_goals', 'replay', 'decider', 'lots')
# How the first stage orders the entrants, and how a later stage orders those who advance.
SEEDINGS = ('random', 'manual', 'rating')
STAGE_SEEDINGS = ('standing', 'random', 'rating')
KINDS = ('team', 'builtin', 'person')
MAX_ENTRANTS = 256
MAX_STAGES = 8
MAX_LEGS = 10
MAX_CONCURRENCY = 8
# The rating of an entrant that has played no tournament match, and how far one match moves it.
BASE_RATING = 1500.0
RATING_STEP = 20.0
# A match lasts at least and at most this many steps when a stage sets its length. A batch keeps
# 512 seconds of history, so 5000 steps of 10 ticks fit within it.
MIN_LENGTH, MAX_LENGTH = 50, 5000

# Every setting of a stage with its default. A tournament's `defaults` and each stage override
# them in turn.
STAGE_DEFAULTS: dict[str, Any] = {
    'format': 'knockout',
    'name': '',
    'scenario': None,
    'length': None,
    'ability': None,
    'legs': 1,
    'final_legs': None,
    'settle': ['replay', 'lots'],
    'replays': 1,
    'decider_scenario': 'academy_run_to_score_with_keeper',
    'decider_length': None,
    'points': {'win': 3, 'draw': 1, 'loss': 0},
    'tiebreakers': ['goal_difference', 'goals_for', 'head_to_head', 'wins', 'fair_play', 'lots'],
    'seeding': 'standing',
    'bracket': 'byes',
    'bracket_size': None,
    'until': 1,
    'third_place': False,
    'grand_final_reset': True,
    'cycles': 1,
    'groups': None,
    'group_size': 4,
    'group_sizes': None,
    'pots': None,
    'qualifiers': 2,
    'best_position': None,
    'best_count': 0,
    'rounds': None,
    'laps': 1,
    'bye_points': 'win',
    'draws': None,
    'advance': None,
}
# The settings of a tournament besides its stages.
TOURNAMENT_KEYS = (
    'name',
    'seed',
    'entrants',
    'seeding',
    'concurrency',
    'forfeit_score',
    'ability',
    'defaults',
    'stages',
    'preset',
)
_ROUND_NAMES = {2: 'final', 4: 'semi_finals', 8: 'quarter_finals'}
_TIE_NAMES = {4: 'semi_final', 8: 'quarter_final'}
# The stage names that the rules and the shipped presets give, by their English text, each with
# the last part of the id of its label, so a stage of a preset shows its name in any language.
STAGE_NAMES = {
    'Knockout': 'knockout',
    'Double elimination': 'double_elimination',
    'League': 'league',
    'Groups': 'groups',
    'Swiss': 'swiss',
    'Ladder': 'ladder',
    'King of the hill': 'king_of_the_hill',
    'Gauntlet': 'gauntlet',
    'Group stage': 'group_stage',
    'Knockout stage': 'knockout_stage',
    'League phase': 'league_phase',
    'Playoffs': 'playoffs',
    'Round robin': 'round_robin',
    'Cup': 'cup',
    'Regular season': 'regular_season',
}


class TournamentError(ValueError):
    """Raised for a configuration that cannot make a tournament, with the reason."""


class TournamentMessageError(_messages.Message, TournamentError):
    """A `TournamentError` whose text is a message of the server, which the page translates."""

    _wrapper = True


# The names and labels that the rules make.


def _label(name: str, /, **values: Any) -> dict[str, Any]:
    """Returns a label of the tournaments, such as a round or a generated entrant name.

    Args:
        name: The id of its message after `server.tournament.label.`, such as `semi_final`.
        values: The values of its placeholders, each text, a number or a label of its own.
    """
    return _messages.label(f'server.tournament.label.{name}', **values)


def text_of(value: Any) -> str:
    """Returns the English text of a name, a label or a plain text."""
    if isinstance(value, dict):
        return str(value.get('text', ''))
    return '' if value is None else str(value)


def label_of(holder: dict[str, Any], field: str = 'name') -> Any:
    """Returns the name that an object holds in `field`, its label when it has a valid one.

    An object keeps a label as `field`, `field_id` and `field_values`, as `_messages.named` gives
    them, and a name that a person gave, or one of a file of before, as the text alone.
    """
    text = holder.get(field)
    if isinstance(text, str) and holder.get(f'{field}_id') is not None:
        found = {'id': holder[f'{field}_id'], 'text': text, 'values': holder.get(f'{field}_values')}
        if _messages.valid_label(found):
            return found
    return text


def set_named(holder: dict[str, Any], field: str, value: Any) -> None:
    """Keeps a name in `field` of an object, a label with its id and values beside the text."""
    holder.pop(f'{field}_id', None)
    holder.pop(f'{field}_values', None)
    holder.update(_messages.named(field, value))


def named_from(field: str, holder: dict[str, Any], source: str = 'name') -> dict[str, Any]:
    """Returns the fields of the name that `holder` keeps in `source`, under the name `field`."""
    return _messages.named(field, label_of(holder, source))


# Presets of formats that ship with the renderer. A preset holds everything but the entrants,
# the seed and the name, and each one adapts to the number of entrants where its format allows.
# Each draws its first stage at random from the tournament seed, so a new tournament's groups and
# bracket come out of a fair draw that the same seed repeats. Seeding by hand or by rating stays a
# choice of the person, and a file of before keeps the seeding it was drawn with.
PRESETS: dict[str, dict[str, Any]] = {
    'world_cup': {
        'title': 'World Cup',
        'description': 'Groups of four play once each, the best two of each group go on to a '
        'knockout of single matches with a third place match.',
        'seeding': 'random',
        'defaults': {'settle': ['decider', 'lots']},
        'stages': [
            {'format': 'groups', 'name': 'Group stage', 'group_size': 4, 'qualifiers': 2},
            {'format': 'knockout', 'name': 'Knockout stage', 'third_place': True},
        ],
    },
    'euro': {
        'title': 'European Championship',
        'description': 'Groups of four, the best two of each group and enough of the best '
        'third places to fill a knockout bracket.',
        'seeding': 'random',
        'defaults': {'settle': ['decider', 'lots']},
        'stages': [
            {
                'format': 'groups',
                'name': 'Group stage',
                'group_size': 4,
                'qualifiers': 2,
                'best_position': 3,
                'best_count': 'fill',
            },
            {'format': 'knockout', 'name': 'Knockout stage'},
        ],
    },
    'champions_league': {
        'title': 'Champions League',
        'description': 'Groups of four play home and away, the best two go on to two legged '
        'ties settled by away goals, with a single match final.',
        'seeding': 'random',
        'defaults': {'settle': ['away_goals', 'decider', 'lots']},
        'stages': [
            {
                'format': 'groups',
                'name': 'Group stage',
                'group_size': 4,
                'qualifiers': 2,
                'cycles': 2,
            },
            {'format': 'knockout', 'name': 'Knockout stage', 'legs': 2, 'final_legs': 1},
        ],
    },
    'league_phase': {
        'title': 'League phase and playoffs',
        'description': 'A Swiss league phase ranks everyone, and the best eight play a '
        'knockout of two legged ties.',
        'seeding': 'random',
        'defaults': {'settle': ['away_goals', 'decider', 'lots']},
        'stages': [
            {'format': 'swiss', 'name': 'League phase', 'advance': 8},
            {'format': 'knockout', 'name': 'Playoffs', 'legs': 2, 'final_legs': 1},
        ],
    },
    'classic_league': {
        'title': 'Classic league',
        'description': 'Everyone plays everyone twice, home and away, for three points a win.',
        'seeding': 'random',
        'stages': [{'format': 'league', 'name': 'League', 'cycles': 2}],
    },
    'round_robin': {
        'title': 'Round robin',
        'description': 'Everyone plays everyone once.',
        'seeding': 'random',
        'stages': [{'format': 'league', 'name': 'Round robin'}],
    },
    'quick_cup': {
        'title': 'Quick 8 team cup',
        'description': 'A knockout of short single matches, made for eight entrants, with '
        'byes for any other number and drawn ties settled by lots.',
        'seeding': 'random',
        'defaults': {'length': 600, 'settle': ['lots']},
        'stages': [{'format': 'knockout', 'name': 'Cup'}],
    },
    'swiss_16': {
        'title': 'Swiss of 16',
        'description': 'Five rounds of the Swiss system, each pairing entrants with the same '
        'score who have not met, ranked by points and Buchholz.',
        'seeding': 'random',
        'defaults': {
            'tiebreakers': ['buchholz', 'goal_difference', 'goals_for', 'head_to_head', 'lots']
        },
        'stages': [{'format': 'swiss', 'name': 'Swiss', 'rounds': 5}],
    },
    'double_elimination': {
        'title': 'Double elimination',
        'description': 'A winners and a losers bracket, so an entrant leaves after a second '
        'defeat, with a deciding match when the losers bracket wins the grand final.',
        'seeding': 'random',
        'stages': [{'format': 'double_elimination', 'name': 'Double elimination'}],
    },
    'league_and_playoffs': {
        'title': 'League and playoffs',
        'description': 'A round robin league, then the best four play semi-finals and a final.',
        'seeding': 'random',
        'stages': [
            {'format': 'league', 'name': 'Regular season', 'advance': 4},
            {'format': 'knockout', 'name': 'Playoffs'},
        ],
    },
    'play_in_cup': {
        'title': 'Cup with a play-in',
        'description': 'A knockout whose lowest seeds first play a play-in round down to a full '
        'bracket, with a third place match.',
        'seeding': 'random',
        'stages': [
            {'format': 'knockout', 'name': 'Cup', 'bracket': 'play_in', 'third_place': True}
        ],
    },
    'ladder': {
        'title': 'Ladder',
        'description': 'Each round, neighbours on the ladder meet, and a challenger who wins '
        'takes the place above.',
        'seeding': 'random',
        'stages': [{'format': 'ladder', 'name': 'Ladder'}],
    },
    'king_of_the_hill': {
        'title': 'King of the hill',
        'description': 'The top seed starts as king, and every challenger in turn tries to '
        'take the crown, which stays with the king on a draw.',
        'seeding': 'random',
        'stages': [{'format': 'king_of_the_hill', 'name': 'King of the hill'}],
    },
    'gauntlet': {
        'title': 'Gauntlet',
        'description': 'The lowest seeds meet first, and the winner climbs to meet each higher '
        'seed in turn, up to the top seed.',
        'seeding': 'random',
        'defaults': {'draws': 'settle'},
        'stages': [{'format': 'gauntlet', 'name': 'Gauntlet'}],
    },
}


# Small helpers.


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _power(value: int) -> bool:
    return value >= 1 and value & (value - 1) == 0


def _next_power(value: int) -> int:
    return 1 << max(0, (value - 1).bit_length())


def _previous_power(value: int) -> int:
    return 1 << (value.bit_length() - 1)


def _rng(seed: int, *parts: Any) -> random.Random:
    """Returns a generator of its own for one purpose, such as the draw of a stage's groups."""
    text = '/'.join([str(seed), *map(str, parts)])
    return random.Random(hashlib.sha256(text.encode()).digest())


def match_seed(seed: int, key: str) -> int:
    """Returns the seed of the match `key` of a tournament, from 0 to 2**31 - 1."""
    digest = hashlib.sha256(f'{seed}/match/{key}'.encode()).digest()
    return int.from_bytes(digest[:4], 'little') % 2**31


def group_name(index: int) -> str:
    """Returns the letter of a group, A to Z, then AA, AB and so on."""
    letters = ''
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def bracket_order(size: int) -> list[int]:
    """Returns the seed of each position of a bracket of `size`, so seed 1 meets seed `size`."""
    order = [0]
    while len(order) < size:
        width = len(order) * 2
        order = [seed for first in order for seed in (first, width - 1 - first)]
    return order


def round_robin(members: list[Any]) -> list[list[tuple[Any, Any]]]:
    """Returns the rounds of a round robin by the circle method, with `None` as the rest.

    Each member meets every other once, plays once a round, and the home side alternates.
    """
    players = list(members) + ([None] if len(members) % 2 else [])
    count = len(players)
    rounds = []
    for index in range(count - 1):
        pairs = []
        for slot in range(count // 2):
            first, second = players[slot], players[count - 1 - slot]
            if (index + slot) % 2:
                first, second = second, first
            pairs.append((first, second))
        rounds.append(pairs)
        players = [players[0], players[-1], *players[1:-1]]
    return rounds


class Unknown:
    """A side of a tie that an earlier tie decides, such as the winner of the first semi-final."""

    def __init__(self, label: dict[str, Any]) -> None:
        self.label = label

    def __repr__(self) -> str:
        return f'Unknown({text_of(self.label)!r})'


def _side(value: Any) -> Any:
    """Returns a side as the view holds it, an entrant, `None` for a bye, or where it comes from.

    A side still to come holds the English text in `from`, with the id and values of its label
    beside it, so the page names it in its own language.
    """
    return _messages.named('from', value.label) if isinstance(value, Unknown) else value


# The configuration.


def _field(name: str, /, **values: Any) -> dict[str, Any]:
    """Returns the name of a setting in a message, the label `server.tournament.field.<name>`."""
    return _messages.label(f'server.tournament.field.{name}', **values)


def _where(index: int) -> dict[str, Any]:
    """Returns the stage of index `index` as it reads in a message, `stage 1` for the first."""
    return _messages.label('server.tournament.where', number=index + 1)


def _plain_text(value: Any, name: Any, longest: int = 80) -> str:
    if not isinstance(value, str):
        raise TournamentMessageError('server.tournament.text', name=name, value=repr(value))
    text = ' '.join(''.join(ch for ch in value if ch.isprintable()).split())
    if not text or len(text) > longest:
        raise TournamentMessageError(
            'server.tournament.text_length', name=name, most=longest, value=repr(value)
        )
    return text


def _choice(value: Any, choices: tuple[str, ...], name: Any) -> str:
    if value not in choices:
        raise TournamentMessageError(
            'server.tournament.choice', name=name, choices=', '.join(choices), value=repr(value)
        )
    return value


def _count(value: Any, name: Any, lowest: int, highest: int) -> int:
    if not _integer(value) or not lowest <= value <= highest:
        # A range of one value reads as that value.
        if lowest == highest:
            raise TournamentMessageError(
                'server.tournament.count_exact', name=name, lowest=lowest, value=repr(value)
            )
        raise TournamentMessageError(
            'server.tournament.count', name=name, lowest=lowest, highest=highest, value=repr(value)
        )
    return value


def name_key(name: Any) -> str:
    """Returns what two entrant names share when they read as one, trimmed and without case.

    Each character is lowered, raised and lowered again, which folds such letters as the German
    sharp s, and which the page's `nameKey` in `web/js/play/tournament-layout.js` does alike,
    character by character, so both give the same key.
    """
    text = ' '.join(text_of(name).split())
    return ''.join(character.lower().upper().lower() for character in text)


def free_name(base: str, taken: set[str] | list[str], longest: int | None = 40) -> str:
    """Returns `base`, or `base` with the first number from 2 whose name no entrant holds.

    `taken` holds the keys of the names in use, as `name_key` gives them. A name keeps to
    `longest` characters, the most a given name holds, by shortening `base` before its number.
    The page's `freeName` proposes the same name when a person adds a team that is already an
    entrant.
    """
    base = ' '.join(base.split())
    if longest is not None:
        base = base[:longest].rstrip()
    number = 2
    name = base
    while name_key(name) in taken:
        suffix = f' {number}'
        cut = base if longest is None else base[: longest - len(suffix)].rstrip()
        name = f'{cut}{suffix}'
        number += 1
    return name


def check_ability(value: Any, message: str, /, **values: Any) -> float | None:
    """Returns an ability from 0 to 1 to four decimals, or `None` when it is unset.

    Args:
        value: The ability, a number or `None`.
        message: The id of the message that refuses any other value, which names it `ability`.
        values: The other values of that message, such as the number of the entrant.
    """
    if value is None:
        return None
    if not _number(value) or not 0 <= value <= 1:
        raise TournamentMessageError(message, ability=repr(value), **values)
    return round(float(value), 4)


def match_ability(
    entrant: dict[str, Any], stage: dict[str, Any], standard: float | None
) -> float | None:
    """Returns the ability that the built-in AI plays with on an entrant's side in a stage.

    The entrant's own ability comes first, then the stage's, then the tournament's standard, and
    `None` leaves the scenario's own. It steers every player of the side that the built-in AI
    controls, the whole side of a built-in AI entrant and the teammates of a team or a person.
    The page's `matchAbility` in `web/js/play/tournament-layout.js` gives the same.
    """
    for value in (entrant.get('ability'), stage.get('ability'), standard):
        if value is not None:
            return value
    return None


def shown_ability(entrant: dict[str, Any], standard: float | None) -> float | None:
    """Returns the ability to show beside an entrant's name, or `None` when there is none.

    An entrant shows its own ability where it differs from the tournament's standard, except a
    built-in AI whose name the rules made, which already holds it, as in Built-in AI 0.80. The
    page's `shownAbility` gives the same.
    """
    own = entrant.get('ability')
    if own is None or own == standard:
        return None
    if entrant.get('kind') == 'builtin' and entrant.get('name_id') is not None:
        return None
    return own


def _given_name(entrant: dict[str, Any]) -> str | None:
    """Returns the name that a person gave an entrant, trimmed, or `None` when it has none."""
    if entrant.get('name') in (None, ''):
        return None
    return _plain_text(entrant['name'], _field('entrant_name'), 40)


def _entrant_name(entrant: dict[str, Any], team: dict[str, Any] | None) -> Any:
    """Returns the name of an entrant, the one a person gave as text, else a label or the team's."""
    given = _given_name(entrant)
    if given is not None:
        return given
    if entrant['kind'] == 'team':
        return label_of(team)
    if entrant['kind'] == 'builtin':
        ability = entrant.get('ability')
        return (
            _label('builtin')
            if ability is None
            else _label('builtin_ability', ability=f'{ability:.2f}')
        )
    raise TournamentMessageError('server.tournament.person_names')


def _name_entrants(entrants: list[dict[str, Any]], bases: list[tuple[Any, bool]]) -> None:
    """Gives each entrant its name, the one a person gave or one that the rules make.

    Two given names that read as one refuse the tournament. A made name, such as that of a team
    or of the built-in AI at an ability, takes the first free number from 2 when a given name or
    an earlier made one holds it, as part of its label when the rules made it.
    """
    given: dict[str, int] = {}
    for index, (base, own) in enumerate(bases):
        if not own:
            continue
        key = name_key(base)
        if key in given:
            raise TournamentMessageError(
                'server.tournament.name_taken', entrant=index + 1, name=base, other=given[key] + 1
            )
        given[key] = index
    names = set(given)
    for entrant, (base, own) in zip(entrants, bases, strict=True):
        name = base
        if not own:
            if isinstance(base, dict):
                suffix = 2
                while name_key(name) in names:
                    name = _label('numbered', name=base, number=suffix)
                    suffix += 1
            elif name_key(name) in names:
                name = free_name(base, names, None)
            names.add(name_key(name))
        set_named(entrant, 'name', name)


def check_entrants(
    entrants: Any, teams: list[dict[str, Any]], ratings: dict[str, float] | None = None
) -> list[dict[str, Any]]:
    """Returns the entrants of a tournament in full, each with its kind, team, name and rating.

    A team of the registry may enter more than once, each entrant under a name of its own. The
    names that people give are unique within the tournament, compared trimmed and without case,
    and each keeps its name as given. An entrant without a given name takes the name of its team
    or kind, with the first free number from 2 when a given name or an earlier entrant already
    holds it, so a team entered twice plays as Rex and Rex 2.

    Args:
        entrants: A list of entrants, each `{'kind': 'team', 'team': identifier}`, `{'kind':
            'builtin', 'ability': 0.5}` or `{'kind': 'person', 'name': 'Ana'}`, with an optional
            `name`, `rating` and, for a person, `teammates`, a registry team of dynamic assignment
            or `builtin`.
        teams: The registry, as `_teams.teams` returns it.
        ratings: The ratings that earlier tournaments gave, by entrant key. The entrants of one
            team share its key, and so its rating.

    Raises:
        TournamentError: If an entrant is unknown or invalid, two given names are the same, or
            there are fewer than 2 or more than 256.
    """
    if not isinstance(entrants, list) or not 2 <= len(entrants) <= MAX_ENTRANTS:
        count = len(entrants) if isinstance(entrants, list) else entrants
        raise TournamentMessageError(
            'server.tournament.entrants', most=MAX_ENTRANTS, count=repr(count)
        )
    registry = {team['id']: team for team in teams}
    builtin = next((team for team in teams if team.get('kind') == 'builtin'), None)
    ratings = ratings or {}
    result: list[dict[str, Any]] = []
    bases: list[tuple[Any, bool]] = []
    for index, raw in enumerate(entrants):
        if not isinstance(raw, dict):
            raise TournamentMessageError(
                'server.tournament.entrant_object', entrant=index + 1, value=repr(raw)
            )
        unknown = set(raw) - {'kind', 'team', 'name', 'ability', 'rating', 'teammates'}
        if unknown:
            raise TournamentMessageError(
                'server.tournament.entrant_fields', entrant=index + 1, fields=sorted(unknown)
            )
        kind = _choice(raw.get('kind', 'team'), KINDS, _field('entrant_kind', number=index + 1))
        entrant: dict[str, Any] = {'kind': kind}
        # Every kind may carry an ability, which the built-in AI players of its side play with.
        ability = check_ability(raw.get('ability'), 'server.tournament.ability', entrant=index + 1)
        if kind == 'team':
            team = registry.get(raw.get('team'))
            if team is None or team.get('kind') == 'builtin':
                raise TournamentMessageError(
                    'server.tournament.entrant_team', entrant=index + 1, team=repr(raw.get('team'))
                )
            entrant.update(team=team['id'], format=team.get('format'), key=team['id'])
        elif kind == 'builtin':
            team = builtin
            entrant.update(team='builtin', format=None)
            entrant['key'] = f'builtin:{"scenario" if ability is None else f"{ability:.2f}"}'
        else:
            mates = raw.get('teammates', 'builtin')
            team = registry.get(mates) if mates != 'builtin' else builtin
            if mates != 'builtin' and (team is None or team.get('kind') == 'builtin'):
                raise TournamentMessageError('server.tournament.teammates', mates=repr(mates))
            entrant.update(team=mates, format=None if mates == 'builtin' else team.get('format'))
        base = _entrant_name({**raw, 'kind': kind, 'ability': ability}, team)
        if kind == 'person':
            entrant['key'] = f'person:{base}'
        # The name comes once every entrant is known, since a made name avoids every given one.
        entrant['name'] = None
        bases.append((base, _given_name(raw) is not None))
        rating = raw.get('rating')
        if rating is not None and (not _number(rating) or not 0 <= rating <= 10000):
            raise TournamentMessageError('server.tournament.rating', rating=repr(rating))
        entrant['rating'] = float(
            rating if rating is not None else ratings.get(entrant['key'], BASE_RATING)
        )
        entrant['rated'] = rating is not None
        kit = (team or {}).get('style', {}).get('kit', {})
        entrant['color'] = list(kit.get('primary') or (team or {}).get('color') or [255, 111, 0])
        entrant['secondary'] = list(
            kit.get('secondary') or (team or {}).get('secondary') or [255, 255, 255]
        )
        entrant['ability'] = ability
        result.append(entrant)
    _name_entrants(result, bases)
    return result


def _merge(stage: dict[str, Any], defaults: dict[str, Any], index: int) -> dict[str, Any]:
    if not isinstance(stage, dict):
        raise TournamentMessageError(
            'server.tournament.stage_object', stage=index + 1, value=repr(stage)
        )
    unknown = (set(stage) | set(defaults)) - set(STAGE_DEFAULTS)
    if unknown:
        raise TournamentMessageError(
            'server.tournament.stage_settings', stage=index + 1, settings=sorted(unknown)
        )
    return {**copy.deepcopy(STAGE_DEFAULTS), **copy.deepcopy(defaults), **copy.deepcopy(stage)}


def _check_points(points: Any, where: dict[str, Any]) -> dict[str, int]:
    if not isinstance(points, dict) or set(points) != {'win', 'draw', 'loss'}:
        raise TournamentMessageError('server.tournament.points', where=where, points=repr(points))
    for name, value in points.items():
        _count(value, _field(f'points_{name}', where=where), -100, 100)
    return dict(points)


def _ordered_names(value: Any, allowed: tuple[str, ...], name: Any) -> list[str]:
    if not isinstance(value, list) or len(set(value)) != len(value):
        raise TournamentMessageError('server.tournament.list', name=name, value=repr(value))
    for item in value:
        _choice(item, allowed, _field('each', name=name))
    # Lots always come last, so every order ends in a decision.
    return [item for item in value if item != 'lots'] + ['lots']


def _group_sizes(stage: dict[str, Any], count: int, index: int, fit: bool) -> list[int]:
    where = _where(index)
    if fit and _integer(stage['group_size']):
        stage['group_size'] = min(stage['group_size'], count)
    if stage['group_sizes'] is not None:
        sizes = stage['group_sizes']
        if not isinstance(sizes, list) or not sizes or not all(_integer(s) for s in sizes):
            raise TournamentMessageError('server.tournament.group_sizes', where=where)
        if sum(sizes) != count:
            raise TournamentMessageError(
                'server.tournament.group_total', where=where, total=sum(sizes), count=count
            )
    else:
        if stage['groups'] is not None:
            groups = _count(stage['groups'], _field('groups', where=where), 1, count)
        else:
            size = _count(stage['group_size'], _field('group_size', where=where), 2, count)
            groups = max(1, round(count / size))
        base, extra = divmod(count, groups)
        sizes = [base + (1 if group < extra else 0) for group in range(groups)]
    if min(sizes) < 2:
        raise TournamentMessageError(
            'server.tournament.group_minimum', where=where, count=count, sizes=sorted(set(sizes))
        )
    return sizes


def _qualifiers(stage: dict[str, Any], sizes: list[int], index: int) -> list[int]:
    value = stage['qualifiers']
    if _integer(value):
        value = [value] * len(sizes)
    if not isinstance(value, list) or len(value) != len(sizes):
        raise TournamentMessageError('server.tournament.qualifiers', stage=index + 1)
    for group, (size, qualified) in enumerate(zip(sizes, value, strict=True)):
        name = _field('qualifiers', group=group_name(group), where=_where(index))
        _count(qualified, name, 0, size)
    return list(value)


def _best(stage: dict[str, Any], sizes: list[int], qualified: list[int], index: int) -> int:
    position, count = stage['best_position'], stage['best_count']
    if position is None:
        if count not in (0, None):
            raise TournamentMessageError('server.tournament.best_places', stage=index + 1)
        return 0
    _count(position, _field('best_position', where=_where(index)), 1, max(sizes))
    eligible = sum(
        1
        for size, group in zip(sizes, qualified, strict=True)
        if size >= position and group < position
    )
    if count == 'fill':
        total = sum(qualified)
        count = min(eligible, max(0, _next_power(max(total, 2)) - total))
    return _count(count, _field('best_count', position=position, where=_where(index)), 0, eligible)


def _resolve_stage(
    stage: dict[str, Any], count: int, index: int, last: bool, fit: bool = False
) -> dict[str, Any]:
    """Checks one stage for `count` entrants and fills in its sizes, rounds and advance.

    With `fit`, for the stages of a preset that ships, a group size, a best place, a number of
    Swiss rounds or of entrants that advance beyond what `count` entrants allow comes down to the
    most they allow, so the preset makes a tournament for any number of entrants.
    """
    where = _where(index)
    fmt = _choice(stage['format'], FORMATS, _field('format', where=where))
    if not isinstance(stage['name'], str):
        raise TournamentMessageError('server.tournament.stage_name', where=where)
    # A name that the rules or a shipped preset give keeps its label, any other stays as given.
    name = stage['name'].strip()[:60] or _FORMAT_TITLES[fmt]
    set_named(stage, 'name', _label(f'stage.{STAGE_NAMES[name]}') if name in STAGE_NAMES else name)
    if count < 2:
        raise TournamentMessageError('server.tournament.stage_entrants', where=where, count=count)
    stage['entrants'] = count
    stage['legs'] = _count(stage['legs'], _field('legs', where=where), 1, MAX_LEGS)
    if stage['final_legs'] is not None:
        _count(stage['final_legs'], _field('final_legs', where=where), 1, MAX_LEGS)
    stage['settle'] = _ordered_names(stage['settle'], SETTLEMENTS, _field('settle', where=where))
    _count(stage['replays'], _field('replays', where=where), 1, 5)
    stage['points'] = _check_points(stage['points'], where)
    stage['tiebreakers'] = _ordered_names(
        stage['tiebreakers'], TIEBREAKERS, _field('tiebreakers', where=where)
    )
    _choice(stage['seeding'], STAGE_SEEDINGS, _field('seeding', where=where))
    for key in ('length', 'decider_length'):
        if stage[key] is not None:
            _count(stage[key], _field(key, where=where), MIN_LENGTH, MAX_LENGTH)
    if stage['ability'] is not None and (
        not _number(stage['ability']) or not 0 <= stage['ability'] <= 1
    ):
        raise TournamentMessageError('server.tournament.stage_ability', where=where)
    if stage['draws'] is None:
        stage['draws'] = 'settle' if fmt == 'gauntlet' else 'holder'
    _choice(stage['draws'], ('holder', 'settle'), _field('draws', where=where))
    _choice(stage['bye_points'], ('win', 'draw', 'none'), _field('bye_points', where=where))
    for key in ('third_place', 'grand_final_reset'):
        if not isinstance(stage[key], bool):
            raise TournamentMessageError('server.tournament.flag', setting=_field(key), where=where)
    advance = None
    if fmt in ('knockout', 'double_elimination'):
        mode = _choice(stage['bracket'], ('byes', 'play_in'), _field('bracket', where=where))
        if fmt == 'double_elimination' and mode != 'byes':
            raise TournamentMessageError('server.tournament.double_byes', where=where)
        size = stage['bracket_size']
        if size is None:
            size = _previous_power(count) if mode == 'play_in' else _next_power(count)
        if not _integer(size) or not _power(size) or size < 2:
            raise TournamentMessageError('server.tournament.bracket_power', where=where)
        if mode == 'byes' and not count <= size < 2 * count:
            # A bracket of 2 takes exactly 2, which reads better than a range of one value.
            exact = size == 2
            raise TournamentMessageError(
                'server.tournament.bracket_exact' if exact else 'server.tournament.bracket_byes',
                size=size,
                lowest=size // 2 + 1,
                count=count,
                where=where,
            )
        if mode == 'play_in' and not size <= count < 2 * size:
            raise TournamentMessageError(
                'server.tournament.bracket_play_in',
                size=size,
                highest=2 * size - 1,
                count=count,
                where=where,
            )
        stage['bracket_size'] = size
        if fmt == 'knockout':
            until = stage['until']
            if not _integer(until) or not _power(until) or until >= size:
                raise TournamentMessageError(
                    'server.tournament.knockout_stop', where=where, size=size
                )
            advance = until
            if not last and stage['advance'] not in (None, until):
                raise TournamentMessageError(
                    'server.tournament.knockout_advance', where=where, count=until
                )
    elif fmt in ('league', 'groups'):
        _count(stage['cycles'], _field('cycles', where=where), 1, 10)
        if fmt == 'groups':
            sizes = _group_sizes(stage, count, index, fit)
            qualified = _qualifiers(stage, sizes, index)
            position = stage['best_position']
            if fit and _integer(position) and position > max(sizes):
                stage.update(best_position=None, best_count=0)
            best = _best(stage, sizes, qualified, index)
            stage.update(group_sizes=sizes, qualifiers=qualified, best_count=best)
            stage['groups'] = len(sizes)
            advance = sum(qualified) + best
            if not last and stage['advance'] not in (None, advance):
                raise TournamentMessageError(
                    'server.tournament.groups_advance', where=where, advance=advance
                )
            if not last and advance < 2:
                raise TournamentMessageError('server.tournament.groups_few', where=where)
            _pots(stage, count, index)
    elif fmt == 'swiss':
        most = max(1, math.ceil(count / 2))
        if stage['rounds'] is None:
            stage['rounds'] = min(most, max(1, math.ceil(math.log2(count))))
        elif fit and _integer(stage['rounds']):
            stage['rounds'] = min(stage['rounds'], most)
        _count(
            stage['rounds'],
            _field('swiss_rounds', where=where, entrants=count),
            1,
            most,
        )
    elif fmt == 'ladder':
        if stage['rounds'] is None:
            stage['rounds'] = count
        _count(stage['rounds'], _field('ladder_rounds', where=where), 1, 1000)
    elif fmt == 'king_of_the_hill':
        _count(stage['laps'], _field('laps', where=where), 1, 10)
    if advance is None:
        advance = stage['advance']
        if advance is None:
            advance = count if last else max(2, _previous_power(max(2, count // 2)))
        elif fit and _integer(advance) and advance > count:
            advance = count if last else max(2, _previous_power(count))
        _count(advance, _field('advance', where=where), 1 if last else 2, count)
    stage['advance'] = advance
    return stage


def _pots(stage: dict[str, Any], count: int, index: int) -> None:
    pots = stage['pots']
    if pots is None:
        pots = max(stage['group_sizes'])
    stage['pots'] = _count(pots, _field('pots', where=_where(index)), 1, count)


_FORMAT_TITLES = {
    'knockout': 'Knockout',
    'double_elimination': 'Double elimination',
    'league': 'League',
    'groups': 'Groups',
    'swiss': 'Swiss',
    'ladder': 'Ladder',
    'king_of_the_hill': 'King of the hill',
    'gauntlet': 'Gauntlet',
}

# Checks whether an entrant can play a scenario, and returns the reason when it cannot, as text
# or as a label of a server message, which the page shows in its own language.
Fits = Callable[[dict[str, Any], str], 'str | dict[str, Any] | None']


def _refuse_sizes(entrants: list[dict[str, Any]], scenario: str, index: int, reason: Any) -> None:
    """Refuses entrants of both sizes for a scenario that fits one size, before any one team."""
    if not isinstance(reason, dict) or reason.get('id') != 'server.tournament.team_format':
        return
    sizes = {entrant['format']: entrant for entrant in reversed(entrants) if entrant['format']}
    if '5v5' in sizes and '11v11' in sizes:
        raise TournamentMessageError(
            'server.tournament.mixed_sizes',
            five=label_of(sizes['5v5']),
            eleven=label_of(sizes['11v11']),
            scenario=_messages.scenario(scenario),
            stage=index + 1,
        )


def default_scenario(entrants: list[dict[str, Any]]) -> str:
    """Returns the scenario of a stage that names none, the Kaggle match or 5 against 5."""
    formats = {entrant['format'] for entrant in entrants if entrant['format']}
    return '5_vs_5' if formats == {'5v5'} else '11_vs_11_kaggle'


def check(
    config: Any,
    teams: list[dict[str, Any]],
    fits: Fits | None = None,
    ratings: dict[str, float] | None = None,
    scenarios: list[str] | None = None,
) -> dict[str, Any]:
    """Returns a tournament's configuration in full, every setting of every stage resolved.

    Args:
        config: The configuration, with its name, seed, entrants and stages, and optional
            `defaults`, `seeding`, `concurrency` and `forfeit_score`.
        teams: The team registry.
        fits: A check of an entrant against a scenario, which returns why it cannot play it, or
            `None` to skip that check.
        ratings: The ratings of earlier tournaments, by entrant key.
        scenarios: The scenarios a stage may name, or `None` for any.

    Raises:
        TournamentError: With the reason, for any setting that cannot make a tournament.
    """
    if not isinstance(config, dict):
        raise TournamentMessageError('server.tournament.object')
    unknown = set(config) - set(TOURNAMENT_KEYS)
    if unknown:
        raise TournamentMessageError('server.tournament.settings', settings=sorted(unknown))
    # A tournament without a name takes the label Tournament, which reads in any language.
    result: dict[str, Any] = _messages.named(
        'name',
        _plain_text(config['name'], _field('name')) if 'name' in config else _label('tournament'),
    )
    seed = config.get('seed')
    if seed is None:
        seed = random.SystemRandom().randrange(2**31)
    if isinstance(seed, str) and seed.strip().isdigit():
        seed = int(seed)
    result['seed'] = _count(seed, _field('seed'), 0, 2**63 - 1)
    entrants = check_entrants(config.get('entrants'), teams, ratings)
    result['entrants'] = entrants
    seeding = _field('tournament_seeding')
    result['seeding'] = _choice(config.get('seeding', 'random'), SEEDINGS, seeding)
    result['concurrency'] = _count(
        config.get('concurrency', 1), _field('concurrency'), 1, MAX_CONCURRENCY
    )
    forfeit = _field('forfeit_score')
    result['forfeit_score'] = _count(config.get('forfeit_score', 3), forfeit, 1, 10)
    # The standard ability of every entrant and stage that sets none, `None` for the scenario's.
    result['ability'] = check_ability(config.get('ability'), 'server.tournament.standard_ability')
    result['preset'] = config.get('preset') if isinstance(config.get('preset'), str) else None
    defaults = config.get('defaults', {})
    if not isinstance(defaults, dict):
        raise TournamentMessageError('server.tournament.defaults')
    stages = config.get('stages')
    if not isinstance(stages, list) or not 1 <= len(stages) <= MAX_STAGES:
        raise TournamentMessageError('server.tournament.stages', most=MAX_STAGES)
    count = len(entrants)
    # The stages of a preset that ships, as it ships them, fit the number of entrants.
    shipped = PRESETS.get(result['preset'])
    fit = shipped is not None and stages == shipped['stages']
    resolved = []
    for index, raw in enumerate(stages):
        stage = _merge(raw, defaults, index)
        last = index == len(stages) - 1
        stage = _resolve_stage(stage, count, index, last, fit)
        for key in ('scenario', 'decider_scenario'):
            if key == 'scenario' and stage[key] is None:
                stage[key] = default_scenario(entrants)
            if not isinstance(stage[key], str) or (
                scenarios is not None and stage[key] not in scenarios
            ):
                raise TournamentMessageError(
                    'server.tournament.stage_scenario', stage=index + 1, scenario=repr(stage[key])
                )
        if fits is not None:
            wanted = [(stage['scenario'], 'server.tournament.cannot_play')]
            if 'decider' in stage['settle'] and stage['format'] not in (
                'league',
                'groups',
                'swiss',
            ):
                # A deciding match plays a scenario of its own, which the refusal names apart.
                wanted.append((stage['decider_scenario'], 'server.tournament.cannot_play_decider'))
            for scenario, message in wanted:
                for entrant in entrants:
                    reason = fits(entrant, scenario)
                    if reason:
                        _refuse_sizes(entrants, scenario, index, reason)
                        raise TournamentMessageError(
                            message,
                            entrant=label_of(entrant),
                            scenario=_messages.scenario(scenario),
                            stage=index + 1,
                            reason=reason,
                        )
        resolved.append(stage)
        count = stage['advance']
    result['stages'] = resolved
    # The stages and defaults as given, before the entrants resolved them, so a tournament run
    # again with other entrants resolves them anew.
    result['given'] = {'stages': copy.deepcopy(stages), 'defaults': copy.deepcopy(defaults)}
    return result


# The evaluation.


class _Run:
    """The matches that an evaluation needs, registered as the stages ask for them."""

    def __init__(self, config: dict[str, Any], results: dict[str, Any]) -> None:
        self.config = config
        self.results = results
        self.matches: dict[str, dict[str, Any]] = {}
        self.entrants = config['entrants']

    def ability(self, entrant: int, stage: dict[str, Any]) -> float | None:
        # A file of before holds no standard, which leaves the scenario's as it did.
        return match_ability(self.entrants[entrant], stage, self.config.get('ability'))

    def match(
        self,
        key: str,
        stage: int,
        settings: dict[str, Any],
        label: dict[str, Any],
        home: int,
        away: int,
        decider: bool = False,
    ) -> dict[str, Any] | None:
        """Registers a match whose sides are known and returns its result, or `None`.

        The match keeps the English text of its label in `label`, with its id and values beside.
        """
        entry = self.matches.get(key)
        if entry is None:
            persons = [self.entrants[side]['kind'] == 'person' for side in (home, away)]
            entry = {
                'key': key,
                'stage': stage,
                **_messages.named('label', label),
                'home': home,
                'away': away,
                'scenario': settings['decider_scenario' if decider else 'scenario'],
                'length': settings['decider_length' if decider else 'length'],
                'ability': [self.ability(home, settings), self.ability(away, settings)],
                'seed': match_seed(self.config['seed'], key),
                'person': any(persons),
                'persons': persons,
                'decider': decider,
                'result': self.results.get(key),
            }
            self.matches[key] = entry
        return entry['result']


def _score(result: dict[str, Any]) -> list[int]:
    return list(result['score'])


def _tie(
    run: _Run,
    stage: int,
    settings: dict[str, Any],
    key: str,
    label: dict[str, Any],
    first: Any,
    second: Any,
    legs: int,
    holder: Any = None,
    section: str | None = None,
) -> dict[str, Any]:
    """Plays a tie of `legs` matches between two sides and settles it, as far as results allow.

    The first side is the higher seed, which plays the last leg at home and any replay too. A
    tie with a bye goes to the other side unplayed.
    """
    view: dict[str, Any] = {
        'id': key,
        **_messages.named('label', label),
        'home': _side(first),
        'away': _side(second),
        'matches': [],
        'score': None,
        'winner': None,
        'loser': None,
        'decided_by': None,
        'state': 'waiting',
        'section': section,
    }
    if isinstance(first, Unknown) or isinstance(second, Unknown):
        return view
    if first is None or second is None:
        view.update(winner=second if first is None else first, state='done', decided_by='bye')
        return view
    totals = {first: 0, second: 0}
    away = {first: 0, second: 0}
    pending = False
    played = False
    for leg in range(legs):
        home, guest = (first, second) if (legs - 1 - leg) % 2 == 0 else (second, first)
        name = label if legs == 1 else _label('leg', match=label, number=leg + 1)
        match_key = f'{key}/{leg + 1}'
        result = run.match(match_key, stage, settings, name, home, guest)
        view['matches'].append(match_key)
        if result is None:
            pending = True
            continue
        played = True
        score = _score(result)
        totals[home] += score[0]
        totals[guest] += score[1]
        away[guest] += score[1]
    # A tie that has played none of its matches has no score yet.
    view['score'] = [totals[first], totals[second]] if played else None
    if pending:
        view['state'] = 'ready'
        return view

    def decide(winner: int, how: str) -> dict[str, Any]:
        view.update(
            winner=winner,
            loser=second if winner == first else first,
            decided_by=how,
            state='done',
        )
        return view

    if totals[first] != totals[second]:
        return decide(
            first if totals[first] > totals[second] else second,
            'aggregate' if legs > 1 else 'score',
        )
    if holder is not None:
        return decide(holder, 'holder')
    for method in settings['settle']:
        if method == 'away_goals':
            if legs % 2 == 0 and away[first] != away[second]:
                return decide(first if away[first] > away[second] else second, 'away goals')
        elif method == 'replay':
            for replay in range(settings['replays']):
                match_key = f'{key}/r{replay + 1}'
                result = run.match(
                    match_key, stage, settings, _label('replay', match=label), first, second
                )
                view['matches'].append(match_key)
                if result is None:
                    view['state'] = 'ready'
                    return view
                score = _score(result)
                view['replay'] = score
                if score[0] != score[1]:
                    return decide(first if score[0] > score[1] else second, 'replay')
        elif method == 'decider':
            keys = [f'{key}/d1', f'{key}/d2']
            decider = _label('decider', match=label)
            results = [
                run.match(keys[0], stage, settings, decider, first, second, True),
                run.match(keys[1], stage, settings, decider, second, first, True),
            ]
            view['matches'] += keys
            if None in results:
                view['state'] = 'ready'
                return view
            goals = [
                results[0]['score'][0] + results[1]['score'][1],
                results[0]['score'][1] + results[1]['score'][0],
            ]
            view['decider'] = goals
            if goals[0] != goals[1]:
                return decide(first if goals[0] > goals[1] else second, 'decider')
        else:
            draw = _rng(run.config['seed'], 'lots', key)
            return decide(draw.choice([first, second]), 'lots')
    raise AssertionError('the settlements end in lots')


def _empty_row(entrant: int) -> dict[str, Any]:
    return {
        'entrant': entrant,
        'played': 0,
        'won': 0,
        'drawn': 0,
        'lost': 0,
        'for': 0,
        'against': 0,
        'difference': 0,
        'points': 0,
        'away_goals': 0,
        'yellow': 0,
        'red': 0,
        'fair_play': 0,
        'byes': 0,
        'buchholz': 0,
    }


def _add(rows: dict[int, dict[str, Any]], entry: dict[str, Any], points: dict[str, int]) -> None:
    """Adds one played match to the rows of its two sides."""
    result = entry['result']
    score = _score(result)
    cards = result.get('cards') or [[0, 0], [0, 0]]
    for side, entrant in enumerate((entry['home'], entry['away'])):
        row = rows.get(entrant)
        if row is None:
            continue
        own, other = score[side], score[1 - side]
        row['played'] += 1
        row['for'] += own
        row['against'] += other
        row['difference'] = row['for'] - row['against']
        if side == 1:
            row['away_goals'] += own
        outcome = 'win' if own > other else 'draw' if own == other else 'loss'
        row[{'win': 'won', 'draw': 'drawn', 'loss': 'lost'}[outcome]] += 1
        row['points'] += points[outcome]
        yellow, red = cards[side]
        row['yellow'] += yellow
        row['red'] += red
        row['fair_play'] = -(row['yellow'] + 3 * row['red'])


def _rows(
    members: list[int], entries: list[dict[str, Any]], points: dict[str, int]
) -> dict[int, dict[str, Any]]:
    rows = {member: _empty_row(member) for member in members}
    for entry in entries:
        if entry['result'] is not None and not entry['decider']:
            _add(rows, entry, points)
    return rows


def _order(
    members: list[int],
    rows: dict[int, dict[str, Any]],
    entries: list[dict[str, Any]],
    settings: dict[str, Any],
    seed: int,
    purpose: str,
) -> tuple[list[int], list[str | None]]:
    """Orders entrants by points, then by the tiebreakers, and returns why each stands above.

    The second list holds, for each entrant but the last, the criterion that put it above the
    next one, or `None` when it has more points.
    """
    criteria = settings['tiebreakers']

    def value(member: int, criterion: str) -> Any:
        row = rows[member]
        if criterion == 'goal_difference':
            return row['difference']
        if criterion == 'goals_for':
            return row['for']
        if criterion == 'goals_against':
            return -row['against']
        if criterion == 'wins':
            return row['won']
        return row[criterion]

    def split(group: list[int], level: int) -> tuple[list[int], list[str | None]]:
        if len(group) == 1:
            return group, []
        criterion = criteria[level]
        if criterion == 'lots':
            order = sorted(group)
            _rng(seed, 'lots', purpose, *order).shuffle(order)
            return order, ['lots'] * (len(order) - 1)
        if criterion == 'head_to_head':
            inside = set(group)
            mini = _rows(
                group,
                [e for e in entries if e['home'] in inside and e['away'] in inside],
                settings['points'],
            )
            keys = {m: (mini[m]['points'], mini[m]['difference'], mini[m]['for']) for m in group}
        else:
            keys = {member: value(member, criterion) for member in group}
        order: list[int] = []
        reasons: list[str | None] = []
        for key in sorted(set(keys.values()), reverse=True):
            part = [member for member in group if keys[member] == key]
            sub, why = split(part, level + 1)
            if order:
                reasons.append(criterion)
            order += sub
            reasons += why
        return order, reasons

    order: list[int] = []
    reasons: list[str | None] = []
    for points in sorted({rows[m]['points'] for m in members}, reverse=True):
        part = sorted(m for m in members if rows[m]['points'] == points)
        sub, why = split(part, 0)
        if order:
            reasons.append(None)
        order += sub
        reasons += why
    return order, reasons


def _table(
    members: list[int],
    entries: list[dict[str, Any]],
    settings: dict[str, Any],
    seed: int,
    purpose: str,
    extra: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Returns the table of `members` from their matches, ordered, each row with its reason."""
    rows = _rows(members, entries, settings['points'])
    for member, changes in (extra or {}).items():
        for key, amount in changes.items():
            rows[member][key] += amount
    played = {member: set() for member in members}
    for entry in entries:
        if entry['result'] is not None and entry['home'] in played and entry['away'] in played:
            played[entry['home']].add(entry['away'])
            played[entry['away']].add(entry['home'])
    for member in members:
        rows[member]['buchholz'] = sum(rows[other]['points'] for other in played[member])
    order, reasons = _order(members, rows, entries, settings, seed, purpose)
    # Before any match the order comes from lots alone, which is no tiebreak worth naming.
    begun = any(entry['result'] is not None and not entry['decider'] for entry in entries)
    table = []
    for position, member in enumerate(order):
        row = dict(rows[member], position=position + 1)
        row['tiebreak'] = reasons[position] if begun and position < len(reasons) else None
        table.append(row)
    return table


def _stage_rows(
    run: _Run, index: int, members: list[int], settings: dict[str, Any]
) -> dict[int, dict[str, Any]]:
    entries = [entry for entry in run.matches.values() if entry['stage'] == index]
    return _rows(members, entries, settings['points'])


def _strength(row: dict[str, Any]) -> tuple[int, int, int]:
    return (row['points'], row['difference'], row['for'])


def _round_name(count: int) -> dict[str, Any]:
    name = _ROUND_NAMES.get(count)
    return _label(name) if name else _label('round_of', count=count)


def _tie_name(count: int, number: int) -> dict[str, Any]:
    if count == 2:
        return _label('final')
    name = _TIE_NAMES.get(count)
    if name:
        return _label(name, number=number)
    return _label('round_of_tie', count=count, number=number)


def _knockout(run: _Run, index: int, s: dict[str, Any], seeds: list[int]) -> dict[str, Any]:
    count = len(seeds)
    size = s['bracket_size']
    rounds: list[dict[str, Any]] = []
    eliminated: dict[int, float] = {}
    if s['bracket'] == 'play_in' and count > size:
        excess = count - size
        direct = seeds[: size - excess]
        playing = seeds[size - excess :]
        ties = []
        slots: list[Any] = list(direct)
        for number in range(excess):
            label = _label('play_in', number=number + 1)
            tie = _tie(
                run,
                index,
                s,
                f'{index}/p{number + 1}',
                label,
                playing[number],
                playing[-1 - number],
                s['legs'],
                section='play_in',
            )
            ties.append(tie)
            done = tie['state'] == 'done'
            slots.append(tie['winner'] if done else Unknown(_label('winner_of', match=label)))
            if tie['state'] == 'done':
                eliminated[tie['loser']] = -1
        named = _messages.named('name', _label('play_in_round'))
        rounds.append({**named, 'fixtures': ties, 'section': 'play_in'})
    else:
        slots = list(seeds) + [None] * (size - count)
    current = [slots[position] for position in bracket_order(size)]
    level = 0
    semi_losers: list[Any] = []
    while len(current) > s['until']:
        width = len(current)
        legs = s['final_legs'] if width == 2 and s['final_legs'] else s['legs']
        ties, following = [], []
        for number in range(width // 2):
            label = _tie_name(width, number + 1)
            tie = _tie(
                run,
                index,
                s,
                f'{index}/w{width}-{number + 1}',
                label,
                current[2 * number],
                current[2 * number + 1],
                legs,
            )
            ties.append(tie)
            done = tie['state'] == 'done'
            following.append(tie['winner'] if done else Unknown(_label('winner_of', match=label)))
            if done and tie['loser'] is not None:
                eliminated[tie['loser']] = level
            if width == 4:
                loser = tie['loser'] if done else Unknown(_label('loser_of', match=label))
                semi_losers.append(loser)
        named = _messages.named('name', _round_name(width))
        rounds.append({**named, 'fixtures': ties, 'section': 'main'})
        current = following
        level += 1
    if s['third_place'] and s['until'] == 1 and size >= 4:
        tie = _tie(
            run,
            index,
            s,
            f'{index}/third',
            _label('third_place'),
            semi_losers[0],
            semi_losers[1],
            s['legs'],
            section='third',
        )
        named = _messages.named('name', _label('third_place'))
        rounds.append({**named, 'fixtures': [tie], 'section': 'third'})
        if tie['state'] == 'done' and tie['winner'] is not None:
            eliminated[tie['winner']] = level - 2 + 0.5
    done = all(fixture['state'] == 'done' for r in rounds for fixture in r['fixtures'])
    ranking = None
    if done:
        for survivor in current:
            if survivor is not None:
                eliminated[survivor] = level + 1
        rows = _stage_rows(run, index, seeds, s)
        place = {entrant: position for position, entrant in enumerate(seeds)}
        ranking = sorted(
            seeds,
            key=lambda e: (-eliminated.get(e, -2), *(-v for v in _strength(rows[e])), place[e]),
        )
    return {'rounds': rounds, 'ranking': ranking, 'bracket': 'knockout'}


def _double_elimination(
    run: _Run, index: int, s: dict[str, Any], seeds: list[int]
) -> dict[str, Any]:
    size = s['bracket_size']
    depth = size.bit_length() - 1
    slots = list(seeds) + [None] * (size - len(seeds))
    current: list[Any] = [slots[position] for position in bracket_order(size)]
    rounds: list[dict[str, Any]] = []
    losers_by_round: list[list[Any]] = []
    out: dict[int, float] = {}

    def play(pairs: list[tuple[Any, Any]], name: dict[str, Any], section: str, legs: int):
        ties, winners, losers = [], [], []
        for number, (first, second) in enumerate(pairs):
            label = _label('tie', round=name, number=number + 1) if len(pairs) > 1 else name
            tie = _tie(
                run,
                index,
                s,
                f'{index}/{section[0]}{len(rounds) + 1}-{number + 1}',
                label,
                first,
                second,
                legs,
                section=section,
            )
            ties.append(tie)
            done = tie['state'] == 'done'
            winners.append(tie['winner'] if done else Unknown(_label('winner_of', match=label)))
            losers.append(tie['loser'] if done else Unknown(_label('loser_of', match=label)))
        rounds.append({**_messages.named('name', name), 'fixtures': ties, 'section': section})
        return winners, losers

    for number in range(depth):
        width = len(current)
        final = width == 2
        name = _label('winners_final') if final else _label('winners_round', number=number + 1)
        pairs = [(current[2 * i], current[2 * i + 1]) for i in range(width // 2)]
        current, losers = play(pairs, name, 'winners', s['legs'])
        losers_by_round.append(losers)
    champion_side = current[0]
    if depth == 1:
        survivor = losers_by_round[0][0]
    else:
        level = 0
        first = losers_by_round[0]
        pairs = [(first[2 * i], first[2 * i + 1]) for i in range(len(first) // 2)]
        lb_round = 1
        survivors, beaten = play(
            pairs, _label('losers_round', number=lb_round), 'losers', s['legs']
        )
        for loser in beaten:
            if isinstance(loser, int):
                out[loser] = level
        for number in range(1, depth):
            level += 1
            lb_round += 1
            drop = losers_by_round[number]
            if number % 2 == 1:
                drop = list(reversed(drop))
            last = number == depth - 1
            name = _label('losers_final') if last else _label('losers_round', number=lb_round)
            survivors, beaten = play(
                list(zip(survivors, drop, strict=True)), name, 'losers', s['legs']
            )
            for loser in beaten:
                if isinstance(loser, int):
                    out[loser] = level
            if not last:
                level += 1
                lb_round += 1
                pairs = [
                    (survivors[2 * i], survivors[2 * i + 1]) for i in range(len(survivors) // 2)
                ]
                survivors, beaten = play(
                    pairs, _label('losers_round', number=lb_round), 'losers', s['legs']
                )
                for loser in beaten:
                    if isinstance(loser, int):
                        out[loser] = level
        survivor = survivors[0]
    final_legs = s['final_legs'] or s['legs']
    winners, losers = play([(champion_side, survivor)], _label('grand_final'), 'final', final_legs)
    champion, runner_up = winners[0], losers[0]
    grand = rounds[-1]['fixtures'][0]
    if (
        s['grand_final_reset']
        and grand['state'] == 'done'
        and isinstance(survivor, int)
        and isinstance(champion_side, int)
        and grand['winner'] == survivor
    ):
        winners, losers = play(
            [(champion_side, survivor)], _label('grand_final_reset'), 'final', final_legs
        )
        champion, runner_up = winners[0], losers[0]
    done = all(f['state'] == 'done' for r in rounds for f in r['fixtures'])
    ranking = None
    if done:
        top = 10**6
        if isinstance(champion, int):
            out[champion] = top + 1
        if isinstance(runner_up, int):
            out[runner_up] = top
        rows = _stage_rows(run, index, seeds, s)
        place = {entrant: position for position, entrant in enumerate(seeds)}
        ranking = sorted(
            seeds, key=lambda e: (-out.get(e, -1), *(-v for v in _strength(rows[e])), place[e])
        )
    return {'rounds': rounds, 'ranking': ranking, 'bracket': 'double'}


def _league_rounds(
    run: _Run, index: int, s: dict[str, Any], members: list[int], prefix: str, group: str | None
) -> list[list[dict[str, Any]]]:
    """Registers the matches of a round robin and returns the fixtures of each matchday."""
    schedule = round_robin(members)
    days = []
    for cycle in range(s['cycles']):
        for pairs in schedule:
            for leg in range(s['legs']):
                flip = (cycle + leg) % 2 == 1
                day = len(days) + 1
                fixtures = []
                for slot, (first, second) in enumerate(pairs):
                    if first is None or second is None:
                        continue
                    home, away = (second, first) if flip else (first, second)
                    key = f'{prefix}/{day}-{slot + 1}'
                    label = (
                        _label('matchday', number=day)
                        if group is None
                        else _label('group_matchday', group=group, number=day)
                    )
                    result = run.match(key, index, s, label, home, away)
                    fixtures.append(_fixture(key, home, away, result, group))
                days.append(fixtures)
    return days


def _fixture(
    key: str, home: int, away: int, result: Any, group: str | None = None
) -> dict[str, Any]:
    score = None if result is None else _score(result)
    winner = None
    if score is not None and score[0] != score[1]:
        winner = home if score[0] > score[1] else away
    return {
        'id': key,
        'home': home,
        'away': away,
        'matches': [key],
        'score': score,
        'winner': winner,
        'state': 'ready' if result is None else 'done',
        'group': group,
    }


def _league(run: _Run, index: int, s: dict[str, Any], seeds: list[int]) -> dict[str, Any]:
    days = _league_rounds(run, index, s, seeds, f'{index}', None)
    rounds = [
        {**_messages.named('name', _label('matchday', number=day + 1)), 'fixtures': fixtures}
        for day, fixtures in enumerate(days)
    ]
    entries = [entry for entry in run.matches.values() if entry['stage'] == index]
    table = _table(seeds, entries, s, run.config['seed'], f'{index}/table')
    done = all(f['state'] == 'done' for r in rounds for f in r['fixtures'])
    return {
        'rounds': rounds,
        'tables': [{**named_from('name', s), 'rows': table, 'qualify': s['advance']}],
        'ranking': [row['entrant'] for row in table] if done else None,
    }


def draw_groups(seeds: list[int], s: dict[str, Any], seed: int, index: int) -> list[list[int]]:
    """Draws the groups of a stage from its pots, and returns the members of each group.

    The seeded entrants fill the pots in order, the pots as even as their count allows. Each pot
    is shuffled by the tournament seed and dealt one entrant at a time to the next group with
    room, continuing around the groups from pot to pot.
    """
    sizes = s['group_sizes']
    pots = s['pots']
    base, extra = divmod(len(seeds), pots)
    groups: list[list[int]] = [[] for _ in sizes]
    start = 0
    turn = 0
    for pot in range(pots):
        width = base + (1 if pot < extra else 0)
        members = seeds[start : start + width]
        start += width
        _rng(seed, 'pots', index, pot).shuffle(members)
        for member in members:
            while len(groups[turn % len(sizes)]) >= sizes[turn % len(sizes)]:
                turn += 1
            groups[turn % len(sizes)].append(member)
            turn += 1
    return groups


def _groups(run: _Run, index: int, s: dict[str, Any], seeds: list[int]) -> dict[str, Any]:
    seed = run.config['seed']
    members = draw_groups(seeds, s, seed, index)
    days: list[list[dict[str, Any]]] = []
    tables = []
    for number, group in enumerate(members):
        letter = group_name(number)
        group_days = _league_rounds(run, index, s, group, f'{index}/{letter}', letter)
        for day, fixtures in enumerate(group_days):
            while len(days) <= day:
                days.append([])
            days[day] += fixtures
        keys = {fixture['id'] for fixtures in group_days for fixture in fixtures}
        entries = [run.matches[key] for key in keys]
        rows = _table(group, entries, s, seed, f'{index}/{letter}')
        tables.append(
            {
                **_messages.named('name', _label('group', group=letter)),
                'rows': rows,
                'qualify': s['qualifiers'][number],
            }
        )
    rounds = [
        {**_messages.named('name', _label('matchday', number=day + 1)), 'fixtures': fixtures}
        for day, fixtures in enumerate(days)
    ]
    done = all(f['state'] == 'done' for r in rounds for f in r['fixtures'])
    ranking = None
    best: list[int] = []
    if done:
        ranking, best = _group_ranking(tables, s, seed, index)
        for table in tables:
            for row in table['rows']:
                row['best'] = row['entrant'] in best
    return {'rounds': rounds, 'tables': tables, 'ranking': ranking, 'best': best}


def _group_ranking(
    tables: list[dict[str, Any]], s: dict[str, Any], seed: int, index: int
) -> tuple[list[int], list[int]]:
    """Ranks every entrant of a group stage across the groups, the qualifiers first.

    Entrants of the same position compare by points, goal difference, goals and wins for each
    match played, which keeps groups of different sizes fair, and then by lots.
    """

    def across(rows: list[dict[str, Any]], purpose: str) -> list[dict[str, Any]]:
        def key(row: dict[str, Any]) -> tuple[float, ...]:
            played = max(1, row['played'])
            return tuple(-row[name] / played for name in ('points', 'difference', 'for', 'won'))

        order = sorted(rows, key=lambda row: row['entrant'])
        _rng(seed, 'across', index, purpose).shuffle(order)
        return sorted(order, key=key)

    deepest = max(len(table['rows']) for table in tables)
    qualified: list[int] = []
    for position in range(deepest):
        rows = [
            table['rows'][position]
            for table in tables
            if position < table['qualify'] and position < len(table['rows'])
        ]
        qualified += [row['entrant'] for row in across(rows, f'q{position}')]
    best: list[int] = []
    if s['best_position'] is not None and s['best_count']:
        position = s['best_position'] - 1
        rows = [
            table['rows'][position]
            for table in tables
            if position < len(table['rows']) and position >= table['qualify']
        ]
        best = [row['entrant'] for row in across(rows, 'best')[: s['best_count']]]
    chosen = set(qualified) | set(best)
    rest: list[int] = []
    for position in range(deepest):
        rows = [
            table['rows'][position]
            for table in tables
            if position < len(table['rows']) and table['rows'][position]['entrant'] not in chosen
        ]
        rest += [row['entrant'] for row in across(rows, f'r{position}')]
    return qualified + best + rest, best


def _palmer(count: int, adjacent: Callable[[int, int], bool]) -> list[int] | None:
    """Finds a Hamiltonian cycle by Palmer's algorithm, in a graph where Dirac's bound holds."""
    cycle = list(range(count))
    for _ in range(count * count + 10):
        gap = next(
            (i for i in range(count) if not adjacent(cycle[i], cycle[(i + 1) % count])), None
        )
        if gap is None:
            return cycle
        cycle = cycle[gap + 1 :] + cycle[: gap + 1]
        # The gap now lies between the last and the first vertex of the list.
        first, last = cycle[0], cycle[-1]
        for j in range(1, count - 2):
            if adjacent(first, cycle[j + 1]) and adjacent(last, cycle[j]):
                cycle = cycle[: j + 1] + list(reversed(cycle[j + 1 :]))
                break
        else:
            return None
    return None


def swiss_pairs(
    order: list[int], met: set[frozenset[int]], byes: set[int], budget: int = 20000
) -> tuple[list[tuple[int, int]], int | None]:
    """Pairs a Swiss round in standing order, each pair new, with a bye for an odd count.

    The bye goes to the lowest entrant who has had none. A search pairs the best placed entrant
    with the next one it has not met, and backs up when the rest cannot pair. When the search runs
    past its budget, Palmer's algorithm on the graph of pairs not yet played finds the pairing,
    which exists while each entrant has met fewer than half the field.

    Returns:
        The pairs, the better placed first, and the entrant with the bye, or `None`.
    """
    players = list(order)
    candidates: list[int | None] = [None]
    if len(players) % 2:
        candidates = [p for p in reversed(players) if p not in byes] or list(reversed(players))
    nodes = [0]

    def search(rest: list[int]) -> list[tuple[int, int]] | None:
        if not rest:
            return []
        nodes[0] += 1
        if nodes[0] > budget:
            return None
        first = rest[0]
        for j in range(1, len(rest)):
            second = rest[j]
            if frozenset((first, second)) in met:
                continue
            tail = search(rest[1:j] + rest[j + 1 :])
            if tail is not None:
                return [(first, second), *tail]
        return None

    for bye in candidates:
        rest = [p for p in players if p != bye]
        found = search(rest)
        if found is not None:
            return found, bye
    # A fallback for large rounds near the limit, with the bye as a vertex of its own.
    phantom = -1
    vertices = list(players) + ([phantom] if len(players) % 2 else [])

    def adjacent(a: int, b: int) -> bool:
        x, y = vertices[a], vertices[b]
        if x == phantom or y == phantom:
            return (y if x == phantom else x) not in byes
        return frozenset((x, y)) not in met

    cycle = _palmer(len(vertices), adjacent)
    if cycle is None:
        raise TournamentMessageError('server.tournament.swiss')
    pairs, bye = [], None
    place = {entrant: position for position, entrant in enumerate(order)}
    for i in range(0, len(cycle), 2):
        x, y = vertices[cycle[i]], vertices[cycle[i + 1]]
        if phantom in (x, y):
            bye = y if x == phantom else x
            continue
        pairs.append((x, y) if place[x] < place[y] else (y, x))
    pairs.sort(key=lambda pair: place[pair[0]])
    return pairs, bye


def _swiss(run: _Run, index: int, s: dict[str, Any], seeds: list[int]) -> dict[str, Any]:
    seed = run.config['seed']
    met: set[frozenset[int]] = set()
    byes: set[int] = set()
    extra: dict[int, dict[str, int]] = {}
    homes = dict.fromkeys(seeds, 0)
    rounds = []
    entries: list[dict[str, Any]] = []
    complete = True
    for number in range(s['rounds']):
        if number == 0:
            order = list(seeds)
        else:
            table = _table(seeds, entries, s, seed, f'{index}/s{number}', extra)
            order = [row['entrant'] for row in table]
        pairs, bye = swiss_pairs(order, met, byes)
        fixtures = []
        for slot, (first, second) in enumerate(pairs):
            met.add(frozenset((first, second)))
            # The side with fewer home matches plays at home, the better placed when equal.
            if homes[second] < homes[first]:
                first, second = second, first
            for leg in range(s['legs']):
                home, away = (first, second) if leg % 2 == 0 else (second, first)
                homes[home] += 1
                key = f'{index}/s{number + 1}-{slot + 1}' + (f'-{leg + 1}' if s['legs'] > 1 else '')
                result = run.match(key, index, s, _label('round', number=number + 1), home, away)
                entries.append(run.matches[key])
                fixtures.append(_fixture(key, home, away, result))
        if bye is not None:
            byes.add(bye)
            points = {'win': s['points']['win'], 'draw': s['points']['draw'], 'none': 0}
            change = extra.setdefault(bye, {'points': 0, 'byes': 0})
            change['points'] += points[s['bye_points']]
            change['byes'] += 1
        named = _messages.named('name', _label('round', number=number + 1))
        rounds.append({**named, 'fixtures': fixtures, 'bye': bye})
        if any(fixture['state'] != 'done' for fixture in fixtures):
            complete = False
            break
    table = _table(seeds, entries, s, seed, f'{index}/table', extra)
    return {
        'rounds': rounds,
        'tables': [{**named_from('name', s), 'rows': table, 'qualify': s['advance']}],
        'ranking': [row['entrant'] for row in table] if complete else None,
    }


def _ladder(run: _Run, index: int, s: dict[str, Any], seeds: list[int]) -> dict[str, Any]:
    positions = list(seeds)
    count = len(positions)
    rounds = []
    complete = True
    for number in range(s['rounds']):
        start = number % 2 if count > 2 else 0
        ties = []
        for upper in range(start, count - 1, 2):
            first, second = positions[upper], positions[upper + 1]
            tie = _tie(
                run,
                index,
                s,
                f'{index}/l{number + 1}-{upper + 1}',
                _label('ladder_tie', round=number + 1, upper=upper + 1, lower=upper + 2),
                first,
                second,
                s['legs'],
                holder=first if s['draws'] == 'holder' else None,
            )
            ties.append(tie)
        rounds.append(
            {**_messages.named('name', _label('round', number=number + 1)), 'fixtures': ties}
        )
        if any(tie['state'] != 'done' for tie in ties):
            complete = False
            break
        for tie in ties:
            upper = positions.index(tie['home'])
            if tie['winner'] == tie['away']:
                positions[upper], positions[upper + 1] = positions[upper + 1], positions[upper]
    rows = _stage_rows(run, index, seeds, s)
    table = [dict(rows[e], position=p + 1, tiebreak=None) for p, e in enumerate(positions)]
    return {
        'rounds': rounds,
        'tables': [
            {
                **_messages.named('name', _label('stage.ladder')),
                'rows': table,
                'qualify': s['advance'],
            }
        ],
        'ranking': positions if complete else None,
    }


def _king(run: _Run, index: int, s: dict[str, Any], seeds: list[int]) -> dict[str, Any]:
    king = seeds[0]
    wins = dict.fromkeys(seeds, 0)
    reigns = dict.fromkeys(seeds, 0)
    reigns[king] = 1
    rounds = []
    complete = True
    number = 0
    for lap in range(s['laps']):
        challengers = seeds[1:] if lap == 0 else list(seeds)
        ties = []
        stop = False
        for challenger in challengers:
            if challenger == king:
                continue
            number += 1
            tie = _tie(
                run,
                index,
                s,
                f'{index}/k{number}',
                _label('challenge', number=number),
                king,
                challenger,
                s['legs'],
                holder=king if s['draws'] == 'holder' else None,
            )
            ties.append(tie)
            if tie['state'] != 'done':
                stop = True
                break
            wins[tie['winner']] += 1
            if tie['winner'] != king:
                king = tie['winner']
                reigns[king] += 1
        named = _messages.named('name', _label('lap', number=lap + 1))
        rounds.append({**named, 'fixtures': ties, 'king': king})
        if stop:
            complete = False
            break
    rows = _stage_rows(run, index, seeds, s)
    place = {entrant: position for position, entrant in enumerate(seeds)}
    order = sorted(
        seeds,
        key=lambda e: (e != king, -wins[e], *(-v for v in _strength(rows[e])), place[e]),
    )
    table = [
        dict(rows[e], position=p + 1, tiebreak=None, titles=wins[e], reigns=reigns[e])
        for p, e in enumerate(order)
    ]
    return {
        'rounds': rounds,
        'tables': [
            {
                **_messages.named('name', _label('challenges')),
                'rows': table,
                'qualify': s['advance'],
            }
        ],
        'ranking': order if complete else None,
        'king': king,
    }


def _gauntlet(run: _Run, index: int, s: dict[str, Any], seeds: list[int]) -> dict[str, Any]:
    climber: Any = seeds[-1]
    out: list[int] = []
    rounds = []
    complete = True
    count = len(seeds)
    for step, waiting in enumerate(reversed(seeds[:-1])):
        final = step == count - 2
        label = _label('final') if final else _label('step', number=step + 1)
        tie = _tie(
            run,
            index,
            s,
            f'{index}/g{step + 1}',
            label,
            waiting,
            climber,
            s['legs'],
            holder=waiting if s['draws'] == 'holder' else None,
        )
        rounds.append({**_messages.named('name', label), 'fixtures': [tie]})
        if tie['state'] != 'done':
            complete = False
            break
        out.append(tie['loser'])
        climber = tie['winner']
    return {'rounds': rounds, 'ranking': [climber, *reversed(out)] if complete else None}


_STAGES = {
    'knockout': _knockout,
    'double_elimination': _double_elimination,
    'league': _league,
    'groups': _groups,
    'swiss': _swiss,
    'ladder': _ladder,
    'king_of_the_hill': _king,
    'gauntlet': _gauntlet,
}


def seeding(config: dict[str, Any]) -> list[int]:
    """Returns the entrants of the first stage in seed order, by the tournament's seeding."""
    entrants = list(range(len(config['entrants'])))
    if config['seeding'] == 'random':
        _rng(config['seed'], 'seeding', 0).shuffle(entrants)
    elif config['seeding'] == 'rating':
        entrants.sort(key=lambda e: -config['entrants'][e]['rating'])
    return entrants


def _reseed(config: dict[str, Any], stage: dict[str, Any], index: int, ranked: list[int]):
    entrants = list(ranked)
    if stage['seeding'] == 'random':
        _rng(config['seed'], 'seeding', index).shuffle(entrants)
    elif stage['seeding'] == 'rating':
        entrants.sort(key=lambda e: -config['entrants'][e]['rating'])
    return entrants


def _planned(settings: dict[str, Any], count: int) -> int:
    """Returns the matches that a stage of `count` entrants plays by its plan.

    The plan counts every tie that two entrants play, and leaves out the replays, deciding
    matches and the reset of a grand final, which only results bring.
    """
    legs = settings['legs']
    final_legs = settings.get('final_legs') or legs
    form = settings['format']
    if count < 2:
        return 0
    if form == 'knockout':
        until = settings['until']
        ties = count - until
        if until > 1:
            return ties * legs
        third = 1 if settings['third_place'] and count >= 4 else 0
        return (ties - 1) * legs + final_legs + third * legs
    if form == 'double_elimination':
        return (2 * count - 3) * legs + final_legs
    if form in ('league', 'groups'):
        sizes = settings['group_sizes'] if form == 'groups' else [count]
        return sum(size * (size - 1) // 2 for size in sizes) * settings['cycles'] * legs
    if form == 'swiss':
        return settings['rounds'] * (count // 2) * legs
    if form == 'ladder':
        ties = 0
        for number in range(settings['rounds']):
            start = number % 2 if count > 2 else 0
            ties += len(range(start, count - 1, 2))
        return ties * legs
    if form == 'king_of_the_hill':
        return settings['laps'] * (count - 1) * legs
    return (count - 1) * legs


def expected_matches(config: dict[str, Any], matches: list[dict[str, Any]]) -> int:
    """Returns the matches that a tournament plays by its plan and by its results so far.

    The replays and deciding matches that results have brought add to the plan, and the count is
    never below the matches already scheduled.
    """
    count = len(config['entrants'])
    planned = 0
    for settings in config['stages']:
        planned += _planned(settings, count)
        count = settings['advance']
    # A replay ends its key in r and a deciding match in d, each followed by its number.
    extra = sum(1 for match in matches if match['key'].rsplit('/', 1)[-1][:1] in ('r', 'd'))
    return max(planned + extra, len(matches))


def evaluate(config: dict[str, Any], results: dict[str, Any]) -> dict[str, Any]:
    """Replays a tournament from its configuration and results, as far as the results reach.

    Args:
        config: The configuration, as `check` returns it.
        results: The result of each played match by key, each `{'score': [home, away]}` with
            optional `cards`, `[[yellow, red], [yellow, red]]`, and `match`, its recording.

    Returns:
        The stages with their rounds, fixtures, tables and rankings, every match that the known
        sides allow with its seed and result, the final ranking and the champion once decided.
    """
    run = _Run(config, results)
    stages = []
    entrants: list[int] | None = seeding(config)
    for index, settings in enumerate(config['stages']):
        view: dict[str, Any] = {
            'index': index,
            **named_from('name', settings),
            'format': settings['format'],
            'scenario': settings['scenario'],
            'advance': settings['advance'],
            'entrants': entrants,
            'rounds': [],
            'tables': [],
            'ranking': None,
        }
        if entrants is not None:
            if index > 0:
                entrants = _reseed(config, settings, index, entrants)
                view['entrants'] = entrants
            view.update(_STAGES[settings['format']](run, index, settings, entrants))
        fixtures = [f for r in view['rounds'] for f in r['fixtures']]
        if view['ranking'] is not None:
            view['state'] = 'done'
        elif entrants is None:
            view['state'] = 'waiting'
        else:
            view['state'] = 'playing' if any(f['state'] == 'done' for f in fixtures) else 'ready'
        stages.append(view)
        last = index == len(config['stages']) - 1
        if view['ranking'] is None:
            entrants = None
        elif not last:
            entrants = view['ranking'][: settings['advance']]
    ranking = None
    if stages[-1]['ranking'] is not None:
        ranking = list(stages[-1]['ranking'])
        for view in reversed(stages[:-1]):
            ranking += [e for e in view['ranking'] if e not in ranking]
    matches = list(run.matches.values())
    played = sum(1 for match in matches if match['result'] is not None)
    complete = ranking is not None
    return {
        'stages': stages,
        'matches': matches,
        'ranking': ranking,
        'champion': ranking[0] if ranking else None,
        'complete': complete,
        'played': played,
        # A finished tournament played what it expected, and one still to play counts its plan.
        'expected': played if complete else expected_matches(config, matches),
    }


def without_spoilers(
    entry: dict[str, Any], results: dict[str, Any], watched: Any
) -> dict[str, Any]:
    """Returns a tournament as a person sees it who has watched only some of its matches.

    The tournament is evaluated again from the results of the watched matches alone, so its
    brackets, tables, ranking and champion tell nothing that an unwatched match decided, and a
    side that such a match decides reads as where it comes from. A played match that waits to be
    watched keeps its recording in `unseen` and loses its result, and `spoilers` lists the keys of
    those that can be watched now in the order of the schedule, as Watch next takes them, beside
    the keys of every played match and the counts of the hidden and the watched ones.

    Args:
        entry: The tournament in full, as the runner's `get` or the mock server gives it.
        results: The result of every played match by key.
        watched: The keys of the matches that the person has watched or revealed.

    Raises:
        TournamentError: If `watched` is no list of up to 10000 keys.
    """
    if (
        not isinstance(watched, list)
        or len(watched) > 10000
        or not all(isinstance(key, str) for key in watched)
    ):
        raise TournamentMessageError('server.tournament.watched')
    seen = set(watched)
    config = entry['config']
    view = evaluate(config, {key: value for key, value in results.items() if key in seen})
    full = {match['key']: match for match in entry['matches']}
    matches, unseen = [], []
    for match in view['matches']:
        shown = dict(full.get(match['key'], {**match, 'state': 'ready'}))
        result = results.get(match['key'])
        if result is not None and match['key'] not in seen:
            shown.update(
                result=None,
                state='unseen',
                unseen={'match': result.get('match'), 'forfeit': bool(result.get('forfeit'))},
            )
            unseen.append(match['key'])
        matches.append(shown)
    champion = view['champion']
    return {
        **entry,
        # The label of a champion still to watch goes with its text.
        'champion_id': None,
        'champion_values': None,
        **_messages.named(
            'champion', None if champion is None else label_of(config['entrants'][champion])
        ),
        'champion_color': None if champion is None else config['entrants'][champion]['color'],
        'stages_view': view['stages'],
        'matches': matches,
        'ranking': view['ranking'],
        'champion_index': champion,
        # The keys of the played matches tell no outcome, and let Reveal all reveal them.
        'spoilers': {
            'unseen': unseen,
            'played': sorted(results),
            'hidden': sum(1 for key in results if key not in seen),
            'watched': sum(1 for key in results if key in seen),
        },
    }


def ready(view: dict[str, Any]) -> list[dict[str, Any]]:
    """Returns the matches of an evaluation that can play now, in the order of the schedule."""
    return [match for match in view['matches'] if match['result'] is None]


def check_result(result: Any) -> dict[str, Any]:
    """Returns a match result in canonical form, or raises `TournamentError`."""
    if not isinstance(result, dict) or set(result) - {'score', 'cards', 'match', 'forfeit'}:
        raise TournamentMessageError('server.tournament.result', result=repr(result))
    score = result.get('score')
    if not (
        isinstance(score, list) and len(score) == 2 and all(_integer(v) and v >= 0 for v in score)
    ):
        raise TournamentMessageError('server.tournament.score', score=repr(score))
    cards = result.get('cards', [[0, 0], [0, 0]])
    if not (
        isinstance(cards, list)
        and len(cards) == 2
        and all(
            isinstance(side, list) and len(side) == 2 and all(_integer(v) and v >= 0 for v in side)
            for side in cards
        )
    ):
        raise TournamentMessageError('server.tournament.cards', cards=repr(cards))
    match = result.get('match')
    if match is not None and not isinstance(match, str):
        raise TournamentMessageError('server.tournament.recording', match=repr(match))
    return {
        'score': list(score),
        'cards': [list(side) for side in cards],
        'match': match,
        'forfeit': bool(result.get('forfeit', False)),
    }


def update_ratings(
    ratings: dict[str, dict[str, Any]], home: dict[str, Any], away: dict[str, Any], score: list[int]
) -> None:
    """Moves the ratings of two entrants after a match, by the Elo formula.

    Two entrants of one team share its rating, so a match between them leaves it as it is.
    """
    if home['key'] == away['key']:
        return
    first = ratings.setdefault(
        home['key'], {'name': home['name'], 'rating': BASE_RATING, 'matches': 0}
    )
    second = ratings.setdefault(
        away['key'], {'name': away['name'], 'rating': BASE_RATING, 'matches': 0}
    )
    expected = 1 / (1 + 10 ** ((second['rating'] - first['rating']) / 400))
    actual = 1.0 if score[0] > score[1] else 0.5 if score[0] == score[1] else 0.0
    change = RATING_STEP * (actual - expected)
    first['rating'] = round(first['rating'] + change, 2)
    second['rating'] = round(second['rating'] - change, 2)
    first['matches'] += 1
    second['matches'] += 1
    # The ratings keep the name of each entrant as the tournament does, a label when made.
    set_named(first, 'name', label_of(home))
    set_named(second, 'name', label_of(away))


def match_title(tournament: dict[str, Any], home: Any, away: Any) -> dict[str, Any]:
    """Returns the title of the recording of a tournament match, as a label.

    The title reads as the tournament, the match and its two sides, such as Spring cup, Final,
    Built-in AI 0.80 against Rex, and the page shows each part in its own language.

    Args:
        tournament: What the recording keeps of its tournament, as the runner gives it, whose
            name and match label may be labels or, in a recording of before, text.
        home: The name of the home side, a label or text.
        away: The name of the away side, a label or text.
    """
    return _label(
        'title',
        tournament=label_of(tournament, 'name') or '',
        match=label_of(tournament, 'label') or '',
        home=home,
        away=away,
    )


def preset_config(name: str, presets: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Returns the format part of a preset, its seeding, defaults and stages, as a copy."""
    table = PRESETS if presets is None else presets
    if name not in table:
        raise TournamentMessageError(
            'server.tournament.preset', presets=', '.join(sorted(table)), name=repr(name)
        )
    preset = table[name]
    config = {
        key: copy.deepcopy(preset[key])
        for key in ('seeding', 'concurrency', 'forfeit_score', 'ability', 'defaults', 'stages')
        if key in preset
    }
    config['preset'] = name
    return config


def check_preset(preset: Any) -> dict[str, Any]:
    """Returns a preset that the user saves, the format part of a configuration with a title."""
    if not isinstance(preset, dict):
        raise TournamentMessageError('server.tournament.preset_object')
    allowed = {
        'title',
        'description',
        'seeding',
        'concurrency',
        'forfeit_score',
        'ability',
        'defaults',
        'stages',
    }
    unknown = set(preset) - allowed
    if unknown:
        raise TournamentMessageError('server.tournament.preset_settings', settings=sorted(unknown))
    result = {'title': _plain_text(preset.get('title'), _field('preset_title'), 60)}
    description = preset.get('description', '')
    if not isinstance(description, str) or len(description) > 400:
        raise TournamentMessageError('server.tournament.description')
    result['description'] = description
    stages = preset.get('stages')
    if not isinstance(stages, list) or not 1 <= len(stages) <= MAX_STAGES:
        raise TournamentMessageError('server.tournament.stages', most=MAX_STAGES)
    defaults = preset.get('defaults', {})
    for index, stage in enumerate(stages):
        _merge(stage, defaults if isinstance(defaults, dict) else {}, index)
    check_ability(preset.get('ability'), 'server.tournament.standard_ability')
    for key in ('seeding', 'concurrency', 'forfeit_score', 'ability', 'defaults', 'stages'):
        if key in preset:
            result[key] = copy.deepcopy(preset[key])
    return result
