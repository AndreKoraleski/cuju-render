# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""Challenges, short drills with medals that people on the Play page and agents headless both try.

Every academy scenario of GRF is a challenge, and the one on one scenario is two more, at the
scenario's ability and against a right side at ability 1.0. A challenge plays a fixed number of
attempts, and attempt `i` always plays the seed `seed_i`, for people and agents alike, so every
result is comparable. The measure of a challenge counts the attempts in which the left side
scored, the attempts in which it scored within a limit of seconds, or the goals for minus the goals
against, and its bronze, silver and gold targets read that value, higher being better. The total
seconds to score break ties, lower being better, and then the earlier run.

Each attempt becomes a recording of the library, and one function, `score_attempt`, scores every
attempt from the frames of its recording, so a person's game and an agent's run use the same code.
The recordings of one run form a group, which the Recordings page shows as one row, and a run that
keeps no recordings scores the same frames and then leaves the library as it was. An attempt that
ends before its episode does counts its goals against and no goals for, so quitting never helps.
A full run reaches the leaderboard of its challenge, a JSON file in the folder `challenges` of the
renderer's home that keeps the best run of each competitor, and a run of fewer attempts is
practice, scored and kept as recordings but off the leaderboard.

The server hands its routes under `/api/challenges` to `get`, `post` and `delete`, and plays the
headless runs that the page asks for in a child process each,
`python -m cuju.render._playing.challenges`, one at a time, which reports one JSON line at a time as
a requested match does. A policy that fails in such a run ends its attempt alone, which counts as
failed, and the run goes on. The benchmarks of `bench` play their runs in the same child process.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import json
import logging
import math
import os
import struct
import subprocess
import sys
import threading
import time
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from cuju import __version__

from .._format import recording as _recording
from .._registry import teams as _teams
from .._store import home as _home
from .._store import library as _library
from .._text import languages as _languages
from .._text import messages as _messages
from .._text.messages import MessageError
from . import achievements as _achievements

_LOGGER = logging.getLogger('cuju')
STEPS_PER_SECOND = 10
MEDALS = ('bronze', 'silver', 'gold')
# The medals from the best down, the order in which a challenge lists them as items.
MEDAL_ORDER = ('gold', 'silver', 'bronze')
MEASURES = ('scored', 'within', 'margin')
# The kinds of challenge, which give each card of the Play page its color and symbol, and how hard
# a challenge is for a person, from its targets and the defenders it faces.
CATEGORIES = (
    'finishing',
    'dribbling',
    'combination',
    'set_piece',
    'counterattack',
    'breakthrough',
    'duel',
)
DIFFICULTIES = ('easy', 'medium', 'hard')
# The leaderboard of a challenge keeps the best run of this many competitors.
BOARD_SIZE = 100
# A competitor's name on a leaderboard holds at most this many characters.
NAME_LENGTH = 40
# A policy has this long to load and to answer its first observation, and this long for every
# later answer before the run ends as stuck.
LOAD_SECONDS = 120.0
FIRST_CALL_SECONDS = 120.0
HANG_SECONDS = 60.0
# A headless run on the server ends after this many seconds.
_JOB_SECONDS = 30 * 60
# The server keeps this many ended runs of the page in its list.
_KEPT_JOBS = 20
_SCORE = struct.Struct('<2i')
_FLAGS = struct.Struct('<i')
_ACADEMY = 'academy_'


def __getattr__(name: str) -> Any:
    """Returns `BatchEnvironment` on first use, so listing the challenges leaves PyTorch out."""
    if name == 'BatchEnvironment':
        from cuju import BatchEnvironment

        return BatchEnvironment
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


def _academy(
    identifier: str, title: str, measure: str, targets: tuple[int, int, int], **extra: Any
):
    """Returns the entry of a challenge on an academy scenario of the same name."""
    return {
        'id': identifier,
        'title': title,
        'scenario': _ACADEMY + identifier,
        'ability': [None, None],
        'attempts': 5,
        'measure': measure,
        'targets': list(targets),
        **extra,
    }


# The catalog. Each goal says what counts, and the targets give the value of a bronze, silver and
# gold medal. The targets come from runs of the built-in AI and of trivial agents, as the
# renderer's guide describes under Challenges. The category and the difficulty describe the
# challenge on its card.
CATALOG: tuple[dict[str, Any], ...] = (
    _academy(
        'empty_goal_close',
        'Empty goal from close range',
        'within',
        (3, 4, 5),
        limit=3.0,
        category='finishing',
        difficulty='easy',
        goal='Score into the empty goal within 3 seconds of play in each attempt.',
    ),
    _academy(
        'empty_goal',
        'Empty goal',
        'within',
        (3, 4, 5),
        limit=8.0,
        category='finishing',
        difficulty='easy',
        goal='Run from the middle and score into the empty goal within 8 seconds of play.',
    ),
    _academy(
        'run_to_score',
        'Run to score',
        'within',
        (1, 3, 5),
        limit=6.5,
        category='dribbling',
        difficulty='medium',
        goal='Outrun five defenders and score into the empty goal within 6.5 seconds of play.',
    ),
    _academy(
        'run_to_score_with_keeper',
        'Run to score past a keeper',
        'scored',
        (1, 3, 5),
        category='dribbling',
        difficulty='medium',
        goal='Outrun five defenders and beat the goalkeeper.',
    ),
    _academy(
        'pass_and_shoot_with_keeper',
        'Pass and shoot past a keeper',
        'scored',
        (1, 3, 5),
        category='combination',
        difficulty='medium',
        goal='Free the unmarked attacker with a pass and score past the goalkeeper.',
    ),
    _academy(
        'run_pass_and_shoot_with_keeper',
        'Run, pass and shoot past a keeper',
        'scored',
        (1, 3, 5),
        category='combination',
        difficulty='hard',
        goal='Run with the ball, pass when the defender commits and score past the goalkeeper.',
    ),
    _academy(
        '3_vs_1_with_keeper',
        'Three against one',
        'scored',
        (1, 3, 5),
        category='combination',
        difficulty='medium',
        goal='Combine three attackers against one defender and score past the goalkeeper.',
    ),
    _academy(
        'corner',
        'Corner',
        'scored',
        (1, 2, 4),
        category='set_piece',
        difficulty='hard',
        goal='Score from the corner before the ball goes out or the clock runs down.',
    ),
    _academy(
        'counterattack_easy',
        'Counterattack',
        'scored',
        (1, 3, 5),
        category='counterattack',
        difficulty='medium',
        goal='Finish a counterattack of four attackers against one defender.',
    ),
    _academy(
        'counterattack_hard',
        'Counterattack, hard',
        'scored',
        (1, 2, 4),
        category='counterattack',
        difficulty='hard',
        goal='Finish a counterattack of four attackers against two defenders.',
    ),
    _academy(
        'single_goal_versus_lazy',
        'Single goal against a lazy team',
        'within',
        (2, 4, 5),
        limit=30.0,
        category='breakthrough',
        difficulty='easy',
        goal='Score against outfield players who stand still, within 30 seconds of play.',
    ),
    {
        'id': 'one_on_one',
        'title': 'One on one',
        'scenario': '1_vs_1_easy',
        'ability': [None, None],
        'attempts': 3,
        'measure': 'margin',
        'targets': [1, 3, 6],
        'category': 'duel',
        'difficulty': 'medium',
        'goal': 'Outscore a single opponent over three short matches, goals for minus against.',
    },
    {
        'id': 'one_on_one_hard',
        'title': 'One on one, hard',
        'scenario': '1_vs_1_easy',
        'ability': [None, 1.0],
        'attempts': 3,
        'measure': 'margin',
        'targets': [1, 2, 4],
        'category': 'duel',
        'difficulty': 'hard',
        'goal': 'Outscore a single opponent at ability 1.0 over three short matches.',
    },
)


def seeds(identifier: str, count: int) -> list[int]:
    """Returns the seeds of the first `count` attempts of a challenge.

    Attempt `i` plays `(crc32(identifier) + 7919 * i) % 2**31`, with the identifier in UTF 8.
    """
    base = zlib.crc32(identifier.encode())
    return [(base + 7919 * index) % 2**31 for index in range(count)]


def find(identifier: Any) -> dict[str, Any]:
    """Returns the catalog entry of a challenge, with its seeds and played abilities.

    Raises:
        ArgumentError: If no challenge has that identifier.
    """
    for entry in CATALOG:
        if entry['id'] == identifier:
            return {
                **entry,
                'targets': list(entry['targets']),
                'ability': list(entry['ability']),
                'limit': entry.get('limit'),
                'seeds': seeds(entry['id'], entry['attempts']),
                'played_ability': _played_ability(entry['scenario'], tuple(entry['ability'])),
                'medals': medal_items(entry),
            }
    raise MessageError(
        'server.challenges.unknown',
        challenges=', '.join(entry['id'] for entry in CATALOG),
        identifier=repr(identifier),
    )


def challenges() -> list[dict[str, Any]]:
    """Returns every challenge of the catalog, with its seeds and the abilities it plays."""
    return [find(entry['id']) for entry in CATALOG]


_PLAYED: dict[tuple[str, Any], list[float]] = {}


def _played_ability(scenario: str, ability: tuple[Any, Any]) -> list[float]:
    """Returns the ability of each side that a challenge plays, the scenario's where none is set."""
    key = (scenario, ability)
    if key not in _PLAYED:
        from cuju.scenarios import Builder, load_scenario

        builder = Builder(0)
        load_scenario(_teams.scenario_path(scenario))(builder)
        config = builder.config()
        defaults = (config.left_team_difficulty, config.right_team_difficulty)
        _PLAYED[key] = [
            round(float(default if value is None else value), 4)
            for value, default in zip(ability, defaults, strict=True)
        ]
    return list(_PLAYED[key])


def medal(challenge: dict[str, Any], value: float) -> str | None:
    """Returns the best medal whose target `value` reaches, or `None`."""
    won = None
    for name, target in zip(MEDALS, challenge['targets'], strict=True):
        if value >= target:
            won = name
    return won


def medal_items(challenge: dict[str, Any], value: float | None = None) -> list[dict[str, Any]]:
    """Returns the medals of a challenge as items, gold, silver and bronze in that order.

    Each item names its medal, the value its target asks for, whether that target asks for a goal
    in every attempt, and whether `value` reached that medal, so a run or a competitor's best marks
    the one item of the best medal it won and none when it won no medal.

    Args:
        challenge: The challenge, as `find` returns it.
        value: The value of a run or a best run, or `None` to mark no item.
    """
    won = None if value is None else medal(challenge, value)
    targets = dict(zip(MEDALS, challenge['targets'], strict=True))
    return [
        {
            'medal': name,
            'target': targets[name],
            'every': challenge['measure'] != 'margin' and targets[name] >= challenge['attempts'],
            'reached': won == name,
        }
        for name in MEDAL_ORDER
    ]


def target_words(challenge: dict[str, Any], item: dict[str, Any]) -> str:
    """Returns the target of a medal item in plain English, as the command line prints it."""
    target = item['target']
    if challenge['measure'] == 'margin':
        return f'{_messages.counted(target, "goal")} or more ahead'
    within = '' if challenge['measure'] == 'scored' else f' within {challenge["limit"]:g} seconds'
    if item['every']:
        return f'a goal{within} in all {challenge["attempts"]} attempts'
    return f'a goal{within} in {_messages.counted(target, "attempt")} or more'


def medal_text(challenge: dict[str, Any], value: float | None = None) -> str:
    """Returns the medal items of a challenge in one line, the item that `value` reached marked."""
    items = [
        f'{item["medal"]}, {target_words(challenge, item)}{", reached" if item["reached"] else ""}'
        for item in medal_items(challenge, value)
    ]
    return 'medals ' + '; '.join(items)


def score_attempt(header: dict[str, Any], frames: list[bytes], side: int = 0) -> dict[str, Any]:
    """Scores one attempt from the frames of its recording.

    The seconds of play run from the first frame to the frame of the goal, at ten steps a second,
    whatever the game clock shows. An attempt whose last frame lacks the episode end flag ended
    early, so it counts its goals against and no goals for.

    Args:
        header: The header of the recording.
        frames: Its frames, as `_recording.frames` yields them.
        side: The side that the challenge controls, the left one.

    Returns:
        Whether the episode finished, the goals for and against, whether the side scored and the
        seconds of play to its first goal, or `None` without a goal.
    """
    if not frames:
        return {'finished': False, 'goals': [0, 0], 'scored': False, 'seconds': None}
    steps = float(header.get('steps_per_second') or STEPS_PER_SECOND)
    first = _SCORE.unpack_from(frames[0], 8)
    last = _SCORE.unpack_from(frames[-1], 8)
    finished = bool(_FLAGS.unpack_from(frames[-1], 28)[0] & 1)
    goals_for = max(0, last[side] - first[side]) if finished else 0
    against = max(0, last[1 - side] - first[1 - side])
    seconds = None
    if goals_for:
        for index, frame in enumerate(frames):
            if _SCORE.unpack_from(frame, 8)[side] > first[side]:
                seconds = round(index / steps, 1)
                break
    return {
        'finished': finished,
        'goals': [goals_for, against],
        'scored': goals_for > 0,
        'seconds': seconds,
    }


def _counts(challenge: dict[str, Any], result: dict[str, Any]) -> bool:
    """Returns whether an attempt counts towards the value of a challenge of attempts."""
    if not result['scored']:
        return False
    return challenge['measure'] != 'within' or result['seconds'] <= challenge['limit']


def score_run(challenge: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    """Returns the value, the seconds and the medal of a run of attempts.

    The seconds add up the seconds to score of the attempts that count, every scoring attempt for
    a measure of goals, and break ties between runs of the same value.
    """
    if challenge['measure'] == 'margin':
        value = sum(result['goals'][0] - result['goals'][1] for result in results)
        counted = [result for result in results if result['scored']]
    else:
        counted = [result for result in results if _counts(challenge, result)]
        value = len(counted)
    seconds = round(sum(result['seconds'] for result in counted), 1)
    return {'value': value, 'seconds': seconds, 'medal': medal(challenge, value)}


def _attempt_result(
    challenge: dict[str, Any],
    index: int,
    match: str | None,
    scored: dict[str, Any],
    failure: BaseException | None = None,
) -> dict[str, Any]:
    """Returns the stored result of one attempt, its index, seed and recording with its score.

    An attempt whose policy failed says so in `failed` and carries the policy's error as `error`,
    `error_id` and `error_values`, and its score is that of an attempt that ended early.
    """
    result = {
        'index': index,
        'seed': challenge['seeds'][index],
        'match': match,
        **scored,
        'counts': _counts(challenge, scored),
        'failed': failure is not None,
    }
    if failure is not None:
        result.update(_messages.entry_fields(failure))
    return result


# Leaderboards.


def _number(value: Any) -> bool:
    """Returns whether `value` is a finite JSON number, which excludes true and false."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_attempt(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and _whole(value.get('index'))
        and _whole(value.get('seed'))
        and (value.get('match') is None or isinstance(value.get('match'), str))
        and isinstance(value.get('finished'), bool)
        and isinstance(value.get('goals'), list)
        and len(value['goals']) == 2
        and all(_whole(goal) and goal >= 0 for goal in value['goals'])
        and isinstance(value.get('scored'), bool)
        and (value.get('seconds') is None or (_number(value['seconds']) and value['seconds'] >= 0))
    )


# Every field of a stored entry with its check, so that an entry edited by hand or written by a
# later version is skipped with a warning and the rest of the board stays.
_ENTRY_FIELDS: dict[str, Callable[[Any], bool]] = {
    'kind': lambda value: value in ('person', 'agent'),
    'name': lambda value: isinstance(value, str) and 0 < len(value) <= NAME_LENGTH,
    'team': lambda value: value is None or isinstance(value, str),
    'value': _number,
    'seconds': lambda value: _number(value) and value >= 0,
    'medal': lambda value: value is None or value in MEDALS,
    'attempts': lambda value: isinstance(value, list) and all(map(_valid_attempt, value)),
    'time': _number,
    'cuju_version': lambda value: isinstance(value, str),
}


def _folder() -> Path:
    return _home.folder('challenges')


def _board_path(identifier: str) -> Path:
    return _folder() / f'{identifier}.json'


_THREAD_LOCK = threading.RLock()
# A lock file older than this belongs to a process that stopped while it held the lock.
_STALE_LOCK_SECONDS = 30.0


@contextlib.contextmanager
def _locked() -> Any:
    """Holds the lock of the leaderboards, within this process and across processes.

    The server, a command and a Python call may each write a board, so a lock file created
    exclusively keeps their writes apart, and one left behind by a stopped process expires.
    """
    with _THREAD_LOCK:
        path = _folder() / '.lock'
        deadline = time.monotonic() + 2 * _STALE_LOCK_SECONDS
        while True:
            try:
                handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                with contextlib.suppress(OSError):
                    if time.time() - path.stat().st_mtime > _STALE_LOCK_SECONDS:
                        path.unlink()
                        continue
                if time.monotonic() > deadline:
                    raise OSError(f'expected the lock of the leaderboards {path} to free') from None
                time.sleep(0.05)
        os.close(handle)
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                path.unlink()


def _read_board(identifier: str) -> list[dict[str, Any]]:
    """Returns the valid entries of a challenge's board, best first, warning once of others."""
    path = _board_path(identifier)
    if not path.is_file():
        return []
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        _LOGGER.warning('cuju render skips the leaderboard file %s, %s', path.name, error)
        return []
    if (
        not isinstance(document, dict)
        or document.get('challenge') != identifier
        or not isinstance(document.get('entries'), list)
    ):
        _LOGGER.warning(
            'cuju render skips the leaderboard file %s, which holds no board of %s',
            path.name,
            identifier,
        )
        return []
    entries, skipped = [], 0
    for entry in document['entries']:
        if isinstance(entry, dict) and all(
            key in entry and check(entry[key]) for key, check in _ENTRY_FIELDS.items()
        ):
            kept = {key: entry[key] for key in _ENTRY_FIELDS}
            if isinstance(entry.get('default_name'), bool):
                kept['default_name'] = entry['default_name']
            entries.append(kept)
        else:
            skipped += 1
    if skipped:
        _LOGGER.warning(
            'cuju render skips %d invalid entries of the leaderboard file %s', skipped, path.name
        )
    entries.sort(key=_rank_key)
    # People under default names of two languages are one competitor, whose best run counts.
    seen: set[tuple[str, str]] = set()
    best = []
    for entry in entries:
        if _competitor(entry) not in seen:
            seen.add(_competitor(entry))
            best.append(entry)
    return best


def _write_board(identifier: str, entries: list[dict[str, Any]]) -> None:
    """Writes a board through a temporary file, so no reader ever sees half of it."""
    document = {'challenge': identifier, 'entries': entries}
    _teams._replace(_board_path(identifier), json.dumps(document).encode())


def _rank_key(entry: dict[str, Any]) -> tuple[float, float, float]:
    return (-entry['value'], entry['seconds'], entry['time'])


def default_person(entry: dict[str, Any]) -> bool:
    """Returns whether an entry is a person's under a default name, by its flag or its name.

    A person who types no name plays under the default name of the page's language, and a new
    entry says so in `default_name`. An older one names the default of a language that the
    renderer knows, which counts the same.
    """
    if entry.get('kind') != 'person':
        return False
    return entry.get('default_name') is True or entry.get('name') in _languages.default_names()


def _competitor(entry: dict[str, Any]) -> tuple[str, str]:
    """Returns who an entry belongs to, a person by name, an agent by team or else by name.

    Every person under a default name is the same competitor, whatever the language of the name.
    """
    if entry['kind'] == 'agent' and entry['team'] is not None:
        return ('team', entry['team'])
    if default_person(entry):
        return ('person', '')
    return (entry['kind'], entry['name'])


def challenge_value(spec: dict[str, Any]) -> dict[str, Any]:
    """Returns a challenge as a value of a message, which the page shows by its own title."""
    return {'kind': 'challenge', 'name': spec['id'], 'text': spec['title']}


def competitor_name(entry: dict[str, Any]) -> dict[str, Any] | str:
    """Returns the name of a competitor as a message value, a label for a name that cuju made.

    The built-in AI under its default name, a policy without a name of its own and a person under
    a default name are labels, which the page shows in its language, and any other name stays the
    text it is.
    """
    name = entry.get('name')
    if default_person(entry):
        return _messages.label('server.names.default_person')
    builtin = _messages.label('server.names.builtin')
    made = entry.get('kind') == 'agent' and entry.get('team') == _teams.BUILTIN
    if made and name == builtin['text']:
        return builtin
    if entry.get('kind') == 'agent' and entry.get('team') is None and name == POLICY_NAME:
        return _messages.label('server.names.python_policy')
    return str(name)


def _named(entry: dict[str, Any]) -> dict[str, Any]:
    """Returns an entry of a board or a run with `name_id` and `name_values` for a made name."""
    return {**entry, **_messages.named('name', competitor_name(entry))}


def board(identifier: str) -> list[dict[str, Any]]:
    """Returns the leaderboard of a challenge, best first, each entry with its rank."""
    find(identifier)
    return [
        _named({**entry, 'rank': rank}) for rank, entry in enumerate(_read_board(identifier), 1)
    ]


def record(identifier: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Adds a run to a challenge's board, which keeps each competitor's best run.

    Returns:
        The competitor's best run with its rank, `None` for a rank outside the board, whether
        this run improved on the best one before it, and whether it is the competitor's first run
        on the board, which improves on nothing before it.
    """
    with _locked():
        entries = _read_board(identifier)
        who = _competitor(entry)
        before = next((item for item in entries if _competitor(item) == who), None)
        improved = before is None or _rank_key(entry) < _rank_key(before)
        if improved:
            entries = [item for item in entries if _competitor(item) != who] + [entry]
            entries.sort(key=_rank_key)
            entries = entries[:BOARD_SIZE]
            _write_board(identifier, entries)
        best = next((item for item in entries if _competitor(item) == who), entry)
        rank = next(
            (rank for rank, item in enumerate(entries, 1) if _competitor(item) == who), None
        )
    return {
        'personal_best': _named({**best, 'rank': rank}),
        'rank': rank,
        'improved': improved,
        'first': before is None,
    }


def personal_bests(kind: str, name: str | None = None, team: str | None = None) -> dict[str, Any]:
    """Returns a competitor's best run of every challenge whose board holds one, by challenge."""
    who = _competitor({'kind': kind, 'name': name, 'team': team})
    bests = {}
    for entry in CATALOG:
        for rank, item in enumerate(_read_board(entry['id']), 1):
            if _competitor(item) == who:
                bests[entry['id']] = {**item, 'rank': rank}
                break
    return bests


def _summary(identifier: str, person: str | None) -> dict[str, Any]:
    """Returns the size and leaders of a board, with a person's own best run when named."""
    entries = board(identifier)
    summary = {
        'entries': len(entries),
        'people': sum(entry['kind'] == 'person' for entry in entries),
        'agents': sum(entry['kind'] == 'agent' for entry in entries),
        'top': [_short(entry) for entry in entries[:3]],
        'mine': None,
    }
    if person:
        who = _competitor({'kind': 'person', 'name': person, 'team': None})
        mine = next((entry for entry in entries if _competitor(entry) == who), None)
        summary['mine'] = None if mine is None else _short(mine)
    return summary


def _short(entry: dict[str, Any]) -> dict[str, Any]:
    keys = ('rank', 'kind', 'name', 'team', 'value', 'seconds', 'medal')
    return _named({key: entry[key] for key in keys})


def _entry(
    kind: str,
    name: str,
    team: str | None,
    totals: dict[str, Any],
    results: list[dict[str, Any]],
    default_name: bool = False,
) -> dict[str, Any]:
    entry = {
        'kind': kind,
        'name': name,
        'team': team,
        'value': totals['value'],
        'seconds': totals['seconds'],
        'medal': totals['medal'],
        'attempts': [
            {
                **{
                    key: result[key]
                    for key in ('index', 'seed', 'match', 'finished', 'goals', 'scored', 'seconds')
                },
                'failed': bool(result.get('failed')),
            }
            for result in results
        ],
        'time': time.time(),
        'cuju_version': __version__,
    }
    if kind == 'person':
        entry['default_name'] = default_name
    return entry


def _default_flag(value: Any, name: str) -> bool:
    """Returns whether a person's name is a default one, as the page says or the name shows.

    Raises:
        ArgumentError: If the flag is no boolean.
    """
    if not isinstance(value, bool):
        raise MessageError('server.challenges.default_name', value=repr(value))
    return value or name in _languages.default_names()


# The name of a policy whose function has no name of its own, such as a lambda.
POLICY_NAME = 'Python policy'


def _policy_name(policy: Any) -> str:
    """Returns the default name of a policy, its function's name, or `Python policy` for none."""
    name = getattr(policy, '__name__', None)
    if not isinstance(name, str) or not name.isidentifier():
        return POLICY_NAME
    return name


def _name(value: Any) -> str:
    """Returns a competitor's name, printable and trimmed, or raises `ArgumentError`."""
    if not isinstance(value, str):
        raise MessageError('server.challenges.name_text', value=repr(value))
    name = ''.join(character for character in value if character.isprintable()).strip()
    if not 0 < len(name) <= NAME_LENGTH:
        raise MessageError('server.challenges.name_length', most=NAME_LENGTH, value=repr(value))
    return name


# People.


class UnknownRecordingError(MessageError):
    """Raised for a recording that the library does not hold outside the Trash."""


def _recording_of(match: Any) -> tuple[dict[str, Any], list[bytes]]:
    """Returns the header and frames of a recording of the library.

    Raises:
        UnknownRecordingError: If the library holds no such recording outside the Trash.
    """
    path = _library.path_of(match) if isinstance(match, str) else None
    if path is None:
        raise UnknownRecordingError('server.challenges.recording', match=repr(match))
    return _recording.read_header(path), list(_recording.frames(path))


def _close(first: Any, second: Any) -> bool:
    return _number(first) and _number(second) and abs(first - second) < 1e-3


def check_person(
    challenge: dict[str, Any], index: int, header: dict[str, Any]
) -> dict[str, Any] | None:
    """Returns why a recording cannot be a person's attempt `index` of a challenge, or `None`.

    A person's attempt is a game of the Play page with a person on the left alone, the built-in AI
    everywhere else, the challenge's scenario and abilities and the seed of the attempt. The reason
    is a label of `_messages.label`, which the page shows in its own language.
    """
    provenance = header.get('provenance')
    if not isinstance(provenance, dict):
        return _messages.label('server.challenges.no_provenance')
    expected = {
        'source': 'human_game',
        'scenario': challenge['scenario'],
        'seed': challenge['seeds'][index],
        'humans': [True, False],
        'teams': [_teams.BUILTIN, _teams.BUILTIN],
        'agent_counts': [1, 0],
    }
    for key, value in expected.items():
        found = provenance.get(key)
        if found != value:
            return _messages.label(
                'server.challenges.provenance',
                key=key,
                value=repr(value),
                attempt=index + 1,
                found=repr(found),
            )
    played = provenance.get('ability')
    if not (
        isinstance(played, list)
        and len(played) == 2
        and all(map(_close, played, challenge['played_ability']))
    ):
        return _messages.label(
            'server.challenges.ability',
            ability=repr(challenge['played_ability']),
            found=repr(played),
        )
    return None


def score_recording(identifier: str, match: str, attempt: Any) -> dict[str, Any]:
    """Scores a recording as a person's attempt of a challenge, and says why it may not count.

    Raises:
        ArgumentError: If the challenge, the attempt or the recording is unknown.
    """
    challenge = find(identifier)
    index = _attempt_index(challenge, attempt)
    header, frames = _recording_of(match)
    problem = check_person(challenge, index, header)
    result = _attempt_result(challenge, index, match, score_attempt(header, frames))
    return {'challenge': identifier, 'result': result, **_messages.named('problem', problem)}


def _attempt_index(challenge: dict[str, Any], attempt: Any) -> int:
    if isinstance(attempt, str) and attempt.isdigit():
        attempt = int(attempt)
    if not _whole(attempt) or not 0 <= attempt < challenge['attempts']:
        raise MessageError(
            'server.challenges.attempt', last=challenge['attempts'] - 1, attempt=repr(attempt)
        )
    return attempt


def person_run(
    identifier: str,
    person: Any,
    matches: Any,
    keep_recordings: Any = True,
    default_name: Any = False,
) -> dict[str, Any]:
    """Checks, scores and records a person's run, the recordings of its attempts in order.

    Every recording is scored again from its frames and must match its attempt, as
    `check_person` describes, and each one counts once. An attempt that a person left before its
    first step has no recording, `None`, and counts as missed. The recordings of the run become a
    group, or with `keep_recordings` false leave the library for good once the run is scored, and
    its attempts then name no recording. A person who typed no name plays under the default name
    of the page's language with `default_name` true, and the run's entry keeps that flag, so the
    page shows the default of its own language wherever the name shows.

    Raises:
        ArgumentError: If the name, the number of recordings or any recording does not fit.
    """
    challenge = find(identifier)
    name = _name(person)
    keep = _keep_flag(keep_recordings)
    default = _default_flag(default_name, name)
    if not isinstance(matches, list) or len(matches) != challenge['attempts']:
        raise MessageError(
            'server.challenges.matches', count=challenge['attempts'], matches=repr(matches)
        )
    named = [match for match in matches if match is not None]
    if len(set(named)) != len(named):
        raise MessageError('server.challenges.distinct')
    results, recordings = [], []
    for index, match in enumerate(matches):
        if match is None:
            missed = {'finished': False, 'goals': [0, 0], 'scored': False, 'seconds': None}
            results.append(_attempt_result(challenge, index, None, missed))
            continue
        header, frames = _recording_of(match)
        problem = check_person(challenge, index, header)
        if problem is not None:
            raise MessageError(
                'server.challenges.attempt_recording',
                match=match,
                attempt=index + 1,
                reason=problem,
            )
        results.append(_attempt_result(challenge, index, match, score_attempt(header, frames)))
        recordings.append((header, frames))
    if not keep:
        results = [{**result, 'match': None} for result in results]
    totals = score_run(challenge, results)
    entry = _entry('person', name, None, totals, results, default)
    outcome = {
        'challenge': identifier,
        'kind': 'person',
        **_messages.named('name', competitor_name(entry)),
        'team': None,
        'default_name': default,
        'practice': False,
        'attempts': results,
        **totals,
        'medals': medal_items(challenge, totals['value']),
        **record(identifier, entry),
    }
    outcome['achievements'] = _achievements_of(
        lambda: _achievements.for_person_run(recordings, outcome)
    )
    shown = competitor_name(entry)
    outcome['group'] = _end_person_run(challenge, shown, matches, keep, 'done', outcome)
    return outcome


def leave_run(
    identifier: str,
    person: Any,
    matches: Any,
    keep_recordings: Any = True,
    default_name: Any = False,
) -> dict[str, Any]:
    """Keeps the attempts of a run that a person left as a group, or removes them for good.

    Each recording must match its attempt, as `check_person` describes, so only the attempts of
    the challenge leave the library.

    Args:
        identifier: The challenge.
        person: The person's name.
        matches: The recordings of the attempts played, in order, `None` for a missed one.
        keep_recordings: Whether the library keeps them, as a group of a left run.
        default_name: Whether the person plays under the default name of the page's language.

    Returns:
        The challenge, the group or `None`, and the recordings that left the library.

    Raises:
        ArgumentError: If the name, the recordings or any recording does not fit.
    """
    challenge = find(identifier)
    name = _name(person)
    keep = _keep_flag(keep_recordings)
    default = _default_flag(default_name, name)
    if not isinstance(matches, list) or not 0 < len(matches) <= challenge['attempts']:
        raise MessageError(
            'server.challenges.left_matches', count=challenge['attempts'], matches=repr(matches)
        )
    named = [match for match in matches if match is not None]
    if len(set(named)) != len(named):
        raise MessageError('server.challenges.distinct')
    for index, match in enumerate(matches):
        if match is None:
            continue
        path = _library.path_of(match) if isinstance(match, str) else None
        if path is None:
            raise UnknownRecordingError('server.challenges.recording', match=repr(match))
        problem = check_person(challenge, index, _recording.read_header(path))
        if problem is not None:
            raise MessageError(
                'server.challenges.attempt_recording',
                match=match,
                attempt=index + 1,
                reason=problem,
            )
    shown = competitor_name({'kind': 'person', 'name': name, 'default_name': default})
    group = _end_person_run(challenge, shown, matches, keep, 'left', None)
    return {'challenge': identifier, 'group': group, 'removed': [] if keep else named}


def _end_person_run(
    challenge: dict[str, Any],
    name: dict[str, Any] | str,
    matches: list[Any],
    keep: bool,
    state: str,
    outcome: dict[str, Any] | None,
) -> str | None:
    """Groups the recordings of a person's run, or removes them for good, and returns the group."""
    named = [match for match in matches if match is not None]
    if not keep:
        for match in named:
            _library.remove(match)
        return None
    if not named:
        return None
    group = _home.new_identifier('g')
    count = challenge['attempts']
    _keep_group(_group(challenge, group, name, count, state, len(matches), outcome), matches)
    return group


def _achievements_of(award: Callable[[], list[str]]) -> list[str]:
    """Returns the achievements that `award` finds, and none with a warning if it fails."""
    try:
        return award()
    except Exception as error:
        _LOGGER.warning('cuju render could not read the achievements of a challenge, %s', error)
        return []


# Groups of recordings, one for each run whose attempts the library keeps.


def _keep_flag(value: Any) -> bool:
    """Returns whether a run keeps its recordings, or raises `ArgumentError` for no boolean."""
    if not isinstance(value, bool):
        raise MessageError('server.challenges.keep_recordings', value=repr(value))
    return value


def _result_label(
    spec: dict[str, Any], count: int, state: str, played: int, outcome: dict[str, Any] | None
) -> dict[str, Any]:
    """Returns the result of a run as a label, its value and medal, or how far it went."""
    if outcome is None:
        message = {'playing': 'server.names.run_playing', 'left': 'server.names.run_left'}
        return _messages.label(
            message.get(state, 'server.names.run_stopped'), played=played, attempts=count
        )
    value = outcome['value']
    if spec['measure'] == 'margin':
        shown = _messages.label('server.names.run_margin', value=f'{value:+d}' if value else '0')
    else:
        shown = _messages.label('server.names.run_attempts', value=value, attempts=count)
    if outcome['practice']:
        return _messages.label('server.names.run_practice', value=shown)
    if outcome['medal']:
        medal = _messages.label(f'server.names.medal_{outcome["medal"]}')
        return _messages.label('server.names.run_medal', value=shown, medal=medal)
    return _messages.label('server.names.run_no_medal', value=shown)


def _group(
    spec: dict[str, Any],
    identifier: str,
    competitor: dict[str, Any] | str,
    count: int,
    state: str,
    played: int,
    outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Returns the group of the recordings of a run, as the summaries of the library keep it.

    The state is `playing` while a headless run plays, `done` once it is scored, `left` for a run
    that a person left and `stopped` for a run that ended on a failure.
    """
    title = _messages.label(
        'server.names.challenge_run', challenge=challenge_value(spec), competitor=competitor
    )
    return {
        'id': identifier,
        'kind': 'challenge',
        'challenge': spec['id'],
        **_messages.named('title', title),
        **_messages.named('competitor', competitor),
        **_messages.named('result', _result_label(spec, count, state, played, outcome)),
        'state': state,
        'attempts': count,
        'value': None if outcome is None else outcome['value'],
        'seconds': None if outcome is None else outcome['seconds'],
        'medal': None if outcome is None else outcome['medal'],
        'practice': False if outcome is None else outcome['practice'],
    }


def _keep_group(group: dict[str, Any], matches: list[Any]) -> None:
    """Writes a group into the summaries of the recordings of its attempts, by attempt."""
    members = {match: index for index, match in enumerate(matches) if match is not None}
    if members:
        _library.set_group(group, members)


# Agents.


def run(
    challenge: str,
    team: str | None = None,
    policy: Callable[..., Any] | None = None,
    name: str | None = None,
    control: dict[str, Any] | None = None,
    attempts: int | None = None,
    device: str = 'cpu',
    progress: Callable[[dict[str, Any]], None] | None = None,
    keep_recordings: bool = True,
    fail_attempts: bool = False,
) -> dict[str, Any]:
    """Plays a challenge headless with a team of the registry or a Python policy, and scores it.

    Each attempt plays in a batch of one environment, `{scenario}_l{agents}_r0` with the seed of
    the attempt and the challenge's abilities, as fast as the policy answers. A team of one
    dynamic agent therefore faces the very episode that a person faces on the Play page. Every
    attempt is saved as a recording of the run's group, and a full run reaches the leaderboard.

    Args:
        challenge: The identifier of the challenge, such as `empty_goal_close`.
        team: A team of the registry, `builtin` for GRF's built-in AI on the whole side.
        policy: A Kaggle agent function, `agent(obs)` or `agent(obs, configuration)`, in place of
            a team.
        name: The name of a policy on the leaderboard, by default the function's name, or
            `Python policy` for a function without one, such as a lambda.
        control: The control of a policy, as a team's control settings, by default one player of
            dynamic assignment.
        attempts: The attempts to play, from 1 to the challenge's count, which is the default. A
            run of fewer attempts is practice and stays off the leaderboard.
        device: `cpu` or `cuda`.
        progress: A function called with the result of each attempt as it ends.
        keep_recordings: Whether the library keeps the attempts as recordings. A run without
            them scores, ranks and earns from the same frames, and its attempts name no
            recording.
        fail_attempts: Whether a policy that fails ends its attempt alone, as the page, the
            command line and the benchmarks play. The attempt then ends where the policy failed
            and counts as one that ended early, its goals against and no goals for, it says so in
            `failed` with the policy's error, and the next attempt loads the policy again. A
            policy that cannot load fails every attempt left. By default a failing policy raises.

    Returns:
        The run, its value, seconds, medal, rank and best run on the leaderboard, its medals as
        `medal_items` gives them, the count of its `failed_attempts`, the result and recording of
        each attempt, the `group` of its recordings or `None`, and the achievements that a team of
        the registry keeps, none for the built-in AI and for a Python policy, which keep none.

    Raises:
        ArgumentError: If the challenge, the team, the control or the attempts do not fit.
        PolicyError: If the policy fails, answers with anything but actions, or stops answering,
            unless `fail_attempts` is true. Nothing then reaches the leaderboard.
    """
    from cuju.kaggle import AgentRunner

    from .play import Policies, PolicyRunner, _default_actions

    spec = find(challenge)
    scenario = spec['scenario']
    keep = _keep_flag(keep_recordings)
    if (team is None) == (policy is None):
        raise MessageError('server.challenges.team_or_policy')
    count = spec['attempts'] if attempts is None else attempts
    if not _whole(count) or not 1 <= count <= spec['attempts']:
        raise MessageError(
            'server.challenges.attempts', most=spec['attempts'], attempts=repr(attempts)
        )
    builtin = _teams.entry(_teams.BUILTIN)
    if team is not None:
        side = _teams.entry(team)
        competitor = side['name']
        control = None if side['kind'] == 'builtin' else side.get('control')
    else:
        if not callable(policy):
            raise MessageError('server.challenges.policy', policy=repr(policy))
        competitor = _name(name if name is not None else _policy_name(policy))
        side = {'id': None, 'kind': 'policy', 'name': competitor, 'format': '11v11'}
        side['control'] = _teams.check_control(control, side['format'])
        control = side['control']
    _teams.check_scenario([side, builtin], scenario)
    agents = _teams.agent_count(side, scenario, 0)
    checked = None if side['kind'] == 'builtin' else _teams.check_control(control, side['format'])
    extended = checked is not None and (
        checked['assignment'] == 'fixed' or checked['action_set'] == 'v2'
    )
    ability = tuple(spec['ability'])

    def factory(batch: Any) -> Any:
        if side['kind'] != 'policy':
            return Policies(batch, [side, builtin], scenario, [agents, 0], extended, [0, agents])
        policies = Policies(batch, [builtin, builtin], scenario, [0, 0], extended, [0, 0])
        function = policy
        if extended and checked['action_set'] == 'default':
            function = _default_actions(policy)
        selected = None
        if checked['assignment'] == 'fixed':
            selected = _teams.selected_players(checked, _teams.scenario_players(scenario, 0))
        policies.players.append(
            {
                'side': 0,
                'name': competitor,
                'runner': AgentRunner(function),
                'columns': list(range(agents)),
                'selected': selected,
                'held': {},
                'calls': 0,
            }
        )
        return policies

    runner = PolicyRunner(hang=HANG_SECONDS) if agents else None
    # The failure of policies that could not load, which every attempt left shares.
    unloadable: BaseException | None = None
    kind_team = None if side['kind'] == 'policy' else side['id']
    shown = competitor_name({'kind': 'agent', 'name': competitor, 'team': kind_team})
    group = _home.new_identifier('g') if keep else None
    results: list[dict[str, Any]] = []
    recordings: list[tuple[dict[str, Any], list[bytes]]] = []

    def keep_group(state: str, outcome: dict[str, Any] | None = None) -> None:
        if group is not None:
            entry = _group(spec, group, shown, count, state, len(results), outcome)
            _keep_group(entry, [result['match'] for result in results])

    try:
        for index in range(count):
            failure = unloadable
            if failure is not None:
                match, header, frames = None, {}, []
            else:
                match, header, frames, failure = _play_attempt(
                    spec,
                    index,
                    side,
                    competitor,
                    agents,
                    extended,
                    ability,
                    device,
                    runner,
                    factory,
                    keep,
                    fail_attempts,
                )
                if failure is not None:
                    if runner.policies is None:
                        unloadable = failure
                    # The next attempt loads the policies again on a thread of their own, since
                    # a call that never returned may still hold the old one.
                    runner.close()
                    runner = PolicyRunner(hang=HANG_SECONDS)
            result = _attempt_result(spec, index, match, score_attempt(header, frames), failure)
            results.append(result)
            recordings.append((header, frames))
            keep_group('playing')
            if progress is not None:
                progress(dict(result))
    except BaseException:
        keep_group('stopped')
        raise
    finally:
        if runner is not None:
            runner.close()
    totals = score_run(spec, results)
    practice = count < spec['attempts']
    outcome: dict[str, Any] = {
        'challenge': challenge,
        'kind': 'agent',
        **_messages.named(
            'name', competitor_name({'kind': 'agent', 'name': competitor, 'team': kind_team})
        ),
        'team': kind_team,
        'practice': practice,
        'attempts': results,
        **totals,
        'medals': medal_items(spec, None if practice else totals['value']),
        'failed_attempts': sum(result['failed'] for result in results),
    }
    if practice:
        # Practice keeps its value but wins no medal and stays off the board.
        outcome.update(medal=None, rank=None, personal_best=None, improved=False, first=False)
    else:
        outcome.update(record(challenge, _entry('agent', competitor, kind_team, totals, results)))
    outcome['achievements'] = _achievements_of(
        lambda: _achievements.for_agent_run(outcome, recordings)
    )
    keep_group('done', outcome)
    outcome['group'] = group
    return outcome


def _play_attempt(
    spec: dict[str, Any],
    index: int,
    side: dict[str, Any],
    competitor: str,
    agents: int,
    extended: bool,
    ability: tuple[Any, Any],
    device: str,
    runner: Any,
    factory: Callable[[Any], Any],
    keep: bool = True,
    fail_attempts: bool = False,
) -> tuple[str | None, dict[str, Any], list[bytes], BaseException | None]:
    """Plays one attempt and returns its recording's identifier, header, frames and failure.

    The recording goes to the library when `keep` is true, and its identifier is `None` otherwise.
    With `fail_attempts`, a policy that fails ends the attempt where it failed, which keeps the
    frames played so far and returns the failure, and an attempt that never stepped keeps no
    recording. The failure is `None` otherwise.
    """
    from .play import PolicyError, PolicyMessageError

    scenario, seed = spec['scenario'], spec['seeds'][index]
    # A test may put a batch of its own in the module's place of `BatchEnvironment`.
    make = globals().get('BatchEnvironment') or __getattr__('BatchEnvironment')
    batch = make(
        f'{scenario}_l{agents}_r0',
        agent_counts=[(agents, 0)],
        environment_count=1,
        representation='raw',
        seed=seed,
        auto_reset=False,
        device=device,
        difficulty=None if ability == (None, None) else [ability],
        action_set='v2' if extended else 'default',
    )
    failure = None
    try:
        reader = _recording.StateReader(int(batch.left_players[0] + batch.right_players[0]))
        batch.reset()
        state = batch.get_state(0)
        lineup = reader.lineup(state)
        timing = _recording.scenario_timing(state)
        frames = [reader.frame(state)]
        try:
            first_call = runner is not None and runner.policies is None
            if runner is not None:
                if runner.policies is None:
                    runner.load(lambda: factory(batch), LOAD_SECONDS)
                else:
                    # The same policies play every attempt, and each sees its episode from step 0.
                    runner.policies.batch = batch
                    for player in runner.policies.players:
                        player.update(calls=0, held={})
            done = False
            while not done:
                if runner is not None:
                    runner.request()
                    limit = FIRST_CALL_SECONDS if first_call else HANG_SECONDS
                    first_call = False
                    if not runner.wait(limit):
                        raise PolicyMessageError('server.policy.silent', count=f'{limit:g}')
                    actions = runner.actions(None)
                else:
                    import torch

                    actions = torch.zeros((1, 0), dtype=torch.int32)
                _, _, finished, _ = batch.step(actions)
                done = bool(finished[0])
                frames.append(reader.frame(batch.get_state(0), 1 if done else 0))
        except PolicyError as error:
            if not fail_attempts:
                raise
            # The attempt ends here, so its last frame lacks the end of the episode.
            failure = error
        played = [round(float(value), 4) for value in batch.difficulty[0].tolist()]
    finally:
        batch.close()
    shown = competitor_name({'kind': 'agent', 'name': competitor, 'team': side['id']})
    if side['kind'] == 'policy':
        teams = [
            {'id': None, 'name': shown, 'ability': played[0]},
            {**_teams.header_team(_teams.BUILTIN), 'ability': played[1]},
        ]
    else:
        teams = [
            {**team, 'ability': played[number]}
            for number, team in enumerate(_teams.match_teams(side['id'], _teams.BUILTIN))
        ]
    provenance = {
        'source': 'challenge',
        'challenge': spec['id'],
        'attempt': index,
        'seed': seed,
        'scenario': scenario,
        'teams': [side['id'], _teams.BUILTIN],
        'competitor': competitor,
        'agent_counts': [agents, 0],
        'action_set': 'v2' if extended else 'default',
        'ability': played,
    }
    if side['kind'] == 'policy':
        provenance['policy'] = competitor
    title = _messages.label(
        'server.names.challenge_attempt',
        challenge=challenge_value(spec),
        attempt=index + 1,
        competitor=shown,
    )
    if failure is not None:
        provenance['failed'] = True
    head = _recording.header(title, scenario, lineup, teams, len(frames), timing, provenance)
    stepped = failure is None or len(frames) > 1
    match = _library.save(head, frames).stem if keep and stepped else None
    return match, json.loads(head[len(_recording.MAGIC) + 4 :]), frames, failure


# The runs that the page asks for, played one at a time in child processes.


class _Jobs:
    """The headless runs of the page, queued and played one at a time, each in a child process.

    The list lives in memory, the newest 20 ended runs with every waiting or playing one, and a
    run that the page cancels ends its process, so nothing of it reaches the leaderboard.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []
        self._processes: dict[str, subprocess.Popen] = {}
        self._wake = threading.Event()
        threading.Thread(target=self._run, daemon=True, name='cuju-challenges').start()

    def add(
        self, identifier: str, team: Any, attempts: Any, keep_recordings: Any = True
    ) -> dict[str, Any]:
        """Queues a run of a team and returns its entry.

        Raises:
            ArgumentError: If the challenge, the team, the attempts or the keeping do not fit.
        """
        challenge = find(identifier)
        keep = _keep_flag(keep_recordings)
        if not isinstance(team, str):
            raise MessageError('server.challenges.team', team=repr(team))
        entry = _teams.entry(team)
        _teams.check_scenario([entry, _teams.entry(_teams.BUILTIN)], challenge['scenario'])
        if attempts is not None and (
            not _whole(attempts) or not 1 <= attempts <= challenge['attempts']
        ):
            raise MessageError(
                'server.challenges.attempts', most=challenge['attempts'], attempts=repr(attempts)
            )
        job = {
            'id': _home.new_identifier('j'),
            'challenge': identifier,
            'team': team,
            **_messages.named('name', _teams.shown_name(entry)),
            'attempts': challenge['attempts'] if attempts is None else attempts,
            'keep_recordings': keep,
            'state': 'queued',
            'progress': 0.0,
            'results': [],
            'result': None,
            'error': None,
            'error_id': None,
            'error_values': None,
            'created': time.time(),
        }
        with self._lock:
            self._entries.append(job)
            ended = [item for item in self._entries if item['state'] in ('done', 'failed')]
            for item in ended[: max(0, len(ended) - _KEPT_JOBS)]:
                self._entries.remove(item)
        self._wake.set()
        return dict(job)

    def entries(self) -> list[dict[str, Any]]:
        """Returns a copy of every run, newest first."""
        with self._lock:
            return [dict(job) for job in reversed(self._entries)]

    def cancel(self, identifier: str) -> bool:
        """Cancels a waiting run or ends a playing one, and returns whether there was one."""
        with self._lock:
            job = next((item for item in self._entries if item['id'] == identifier), None)
            if job is None or job['state'] not in ('queued', 'running'):
                return False
            job.update(state='failed', **_messages.fields('server.requests.cancelled'))
            process = self._processes.get(identifier)
        if process is not None:
            process.kill()
        return True

    def _run(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            while True:
                with self._lock:
                    job = next((item for item in self._entries if item['state'] == 'queued'), None)
                if job is None:
                    break
                try:
                    self._play(job)
                except Exception as error:
                    with self._lock:
                        job['state'] = 'failed'
                        job.update(_messages.entry_fields(error, _messages.described(error)))

    def _play(self, job: dict[str, Any]) -> None:
        command = child_command(
            job['challenge'], job['team'], job['attempts'], job['keep_recordings']
        )
        with self._lock:
            if job['state'] != 'queued':
                return
            job['state'] = 'running'

        def started(process: subprocess.Popen) -> None:
            with self._lock:
                self._processes[job['id']] = process
                cancelled = job['state'] != 'running'
            if cancelled:
                process.kill()

        def report(line: dict[str, Any]) -> None:
            with self._lock:
                if isinstance(line.get('attempt'), dict):
                    job['results'] = [*job['results'], line['attempt']]
                    job['progress'] = len(job['results']) / job['attempts']
                if isinstance(line.get('result'), dict):
                    job['result'] = line['result']
                if isinstance(line.get('error'), str):
                    job.update(_messages.report_fields(line))

        try:
            code, tail = play_child(command, report, started)
        finally:
            with self._lock:
                self._processes.pop(job['id'], None)
        with self._lock:
            if job['state'] != 'running':
                return
            if code == 0 and job['result'] is not None:
                job.update(state='done', progress=1.0)
            else:
                job['state'] = 'failed'
                if not job['error']:
                    job.update(_messages.exit_fields('server.challenges.exit', code, tail))

    def get(self, identifier: str) -> dict[str, Any] | None:
        """Returns a copy of one run, or `None` for a run that the list no longer holds."""
        with self._lock:
            job = next((item for item in self._entries if item['id'] == identifier), None)
            return None if job is None else dict(job)


def child_command(
    identifier: str,
    team: str,
    attempts: int | None = None,
    keep: bool = True,
    device: str = 'cpu',
) -> list[str]:
    """Returns the command of the child process that plays one headless run of a team."""
    command = [
        *_home.python_command(),
        '-m',
        'cuju.render._playing.challenges',
        identifier,
        '--team',
        team,
    ]
    if attempts is not None:
        command += ['--attempts', str(attempts)]
    if device != 'cpu':
        command += ['--device', device]
    if not keep:
        command.append('--no-recordings')
    return command


def play_child(
    command: list[str],
    report: Callable[[dict[str, Any]], None],
    started: Callable[[subprocess.Popen], None] | None = None,
    seconds: float = _JOB_SECONDS,
) -> tuple[int, str]:
    """Plays a headless run in a child process and hands each of its reports to `report`.

    The child runs in the renderer's folder, as a requested match does, and ends after `seconds`.
    Every run of the page, of a benchmark and of a benchmark on the command line plays this way,
    so a submission runs in a process of its own and no run sees another.

    Args:
        command: The command, as `child_command` returns it.
        report: A function called with each report of the child, a JSON object.
        started: A function called with the process once it has started, which may end it.
        seconds: The seconds after which the run ends.

    Returns:
        The exit code of the child and the last lines it wrote to standard error.
    """
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        errors='replace',
        cwd=_home.process_folder(),
        env=_home.process_environment(),
    )
    if started is not None:
        started(process)
    stderr: collections.deque[str] = collections.deque(maxlen=20)
    reader = threading.Thread(target=lambda: stderr.extend(process.stderr), daemon=True)
    reader.start()
    timer = threading.Timer(seconds, process.kill)
    timer.daemon = True
    timer.start()
    try:
        for line in process.stdout:
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                report(parsed)
        code = process.wait()
    finally:
        timer.cancel()
    reader.join(1.0)
    return code, ''.join(stderr).strip()


_JOBS: _Jobs | None = None
_JOBS_LOCK = threading.Lock()


def jobs() -> _Jobs:
    """Returns the server's queue of headless runs, started on first use."""
    global _JOBS
    with _JOBS_LOCK:
        if _JOBS is None:
            _JOBS = _Jobs()
        return _JOBS


# The routes of the server under /api/challenges, each returning a status and a JSON value.


def get(parts: list[str], query: dict[str, str]) -> tuple[Any, int]:
    """Answers `GET /api/challenges/...`, the catalog, a board, a score, the runs or benchmarks."""
    if not parts:
        person = query.get('person') or None
        return [{**entry, 'board': _summary(entry['id'], person)} for entry in challenges()], 200
    if parts == ['jobs']:
        return jobs().entries(), 200
    if parts == ['names']:
        return {'default_names': sorted(_languages.default_names())}, 200
    if len(parts) == 2 and parts[0] == 'jobs':
        job = jobs().get(parts[1])
        if job is None:
            return _messages.fields('server.challenges.no_run'), 404
        return job, 200
    if parts[0] == 'benches':
        from . import bench as _bench

        return _bench.get(parts[1:])
    identifier = parts[0]
    if identifier not in {entry['id'] for entry in CATALOG}:
        return _messages.fields('server.challenges.no_challenge', identifier=repr(identifier)), 404
    if len(parts) == 1:
        return {'challenge': find(identifier), 'entries': board(identifier)}, 200
    if parts[1:] == ['score']:
        try:
            return score_recording(identifier, query.get('match', ''), query.get('attempt')), 200
        except UnknownRecordingError as error:
            return _messages.error_fields(error), 404
    return _messages.fields('server.no_resource'), 404


def post(parts: list[str], document: dict[str, Any]) -> tuple[Any, int]:
    """Answers `POST /api/challenges/<id>/runs`, `POST /api/challenges/<id>/leave` and
    `POST /api/challenges/benches`.

    A run is a person's run to record or a team's to play, leave takes the attempts of a run that
    a person left, to keep as a group or to remove, and benches starts a benchmark of models.
    """
    if parts == ['benches']:
        from . import bench as _bench

        return _bench.post(document)
    if len(parts) != 2 or parts[1] not in ('runs', 'leave'):
        return _messages.fields('server.no_resource'), 404
    if parts[0] not in {entry['id'] for entry in CATALOG}:
        return _messages.fields('server.challenges.no_challenge', identifier=repr(parts[0])), 404
    keep = document.get('keep_recordings', True)
    if 'person' in document or parts[1] == 'leave':
        unknown = set(document) - {'person', 'matches', 'keep_recordings', 'default_name'}
        if unknown:
            raise MessageError('server.challenges.person_fields', unknown=repr(sorted(unknown)))
        default = document.get('default_name', False)
        person, matches = document.get('person'), document.get('matches')
        if parts[1] == 'leave':
            return leave_run(parts[0], person, matches, keep, default), 200
        return person_run(parts[0], person, matches, keep, default), 201
    unknown = set(document) - {'team', 'attempts', 'keep_recordings'}
    if unknown or 'team' not in document:
        raise MessageError('server.challenges.run_fields')
    return jobs().add(parts[0], document['team'], document.get('attempts'), keep), 201


def delete(parts: list[str]) -> tuple[Any, int]:
    """Answers `DELETE /api/challenges/jobs/<job>` and `DELETE /api/challenges/benches/<bench>`,
    which cancel a run or a benchmark of the page."""
    if len(parts) == 2 and parts[0] == 'benches':
        from . import bench as _bench

        return _bench.delete(parts[1])
    if len(parts) == 2 and parts[0] == 'jobs' and jobs().cancel(parts[1]):
        return {'cancelled': parts[1]}, 200
    return _messages.fields('server.challenges.no_run'), 404


# The child process of a headless run, and the command line.

# The channel of the reports, standard output until `main` moves everything else away.
_reports: TextIO = sys.stdout


def _report(**entries: Any) -> None:
    _reports.write(json.dumps(entries) + '\n')
    _reports.flush()


def main(arguments: list[str] | None = None) -> None:
    """Plays the run that the command line names and reports each attempt and the result.

    A policy that fails ends its attempt alone, which counts as failed, so the run always ends
    with a result unless its challenge, team or attempts do not fit.
    """
    global _reports
    from .play import PolicyError

    parser = argparse.ArgumentParser(prog='python -m cuju.render._playing.challenges')
    parser.add_argument('challenge')
    parser.add_argument('--team', required=True)
    parser.add_argument('--attempts', type=int, default=None)
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--no-recordings', action='store_true')
    options = parser.parse_args(arguments)
    sys.stdout.flush()
    _reports = os.fdopen(os.dup(1), 'w', encoding='utf-8')
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    try:
        outcome = run(
            options.challenge,
            team=options.team,
            attempts=options.attempts,
            device=options.device,
            progress=lambda result: _report(attempt=result),
            keep_recordings=not options.no_recordings,
            fail_attempts=True,
        )
    except PolicyError as error:
        _report(error=str(error), **_messages.id_fields(error))
        sys.exit(1)
    except Exception as error:
        _report(error=_messages.described(error), **_messages.id_fields(error))
        sys.exit(1)
    _report(result=outcome)


if __name__ == '__main__':
    main()
