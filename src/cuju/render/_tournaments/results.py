# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The ratings, the matrix of goal differences and the files of a tournament's results.

The ratings follow the Bradley and Terry model, in which an entrant of strength p beats one of
strength q with the chance of p over the sum of p and q, fitted to every match a tournament has
played, a draw counting as half a win for each side. They read on the Elo scale, 400 points for
each tenfold of strength, centred so that their mean is 1000. As its prior, each entrant also plays
one draw against a virtual entrant of the fixed strength 1, which keeps the rating of an entrant
that won or lost every match finite and pulls an entrant of few matches toward the middle. The
interval of each rating comes from a bootstrap, the matches drawn again with replacement as many
times as the resamples say, 200 by default, by a generator seeded with the digest of the
tournament seed, so the same results always give the same intervals. The interval runs from the
2.5th to the 97.5th percentile of the ratings of the resamples. The file `ratings_method.json`
states all of it beside the ratings.

The module uses Python's standard library alone, so the page's mock server loads it from its file,
as it loads the rules of the tournaments.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
from typing import Any

# The resamples of the bootstrap of the ratings.
RESAMPLES = 200
# The rating of an entrant of the mean strength.
CENTRE = 1000.0
# The virtual draws that each entrant plays against a virtual entrant of the fixed strength 1.
PRIOR = 1.0
# The files of a tournament's results, in the order the page and the command line list them.
FILES = (
    'standings.csv',
    'ratings.csv',
    'ratings_method.json',
    'pairwise_gd.csv',
    'pairwise_counts.csv',
    'matches.jsonl',
    'entrants.json',
    'excluded.json',
)
STANDINGS_COLUMNS = (
    'position',
    'entrant',
    'id',
    'name',
    'kind',
    'team',
    'played',
    'won',
    'drawn',
    'lost',
    'goals_for',
    'goals_against',
    'goal_difference',
    'points',
    'forfeits',
    'cut_short',
    'rating',
)
RATINGS_COLUMNS = ('rank', 'entrant', 'id', 'name', 'rating', 'low', 'high', 'matches')
PAIRWISE_COLUMNS = (
    'entrant',
    'id',
    'name',
    'opponent',
    'opponent_id',
    'opponent_name',
    'matches',
    'mean_goal_difference',
)
_STEPS = 10000
_TOLERANCE = 1e-10


def _played(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Returns the matches that have a result, in the order of the schedule."""
    return [match for match in matches if isinstance(match.get('result'), dict)]


def _outcome(score: list[int]) -> float:
    """Returns the share of a win of the home side, 1 for a win, a half for a draw, else 0."""
    return 1.0 if score[0] > score[1] else 0.5 if score[0] == score[1] else 0.0


def _common_scale(strength: list[float]) -> float:
    """Returns the factor of every strength at which the virtual draws are most likely.

    The matches between entrants tell only how their strengths compare, so the scale of all of
    them together comes from the virtual draws alone, the factor c at which the sum of the shares
    c p over c p plus 1 is half the entrants, which Newton's method finds.
    """
    shift = 0.0
    half = len(strength) / 2
    for _ in range(100):
        factor = math.exp(shift)
        shares = [factor * value / (factor * value + 1) for value in strength]
        slope = sum(share * (1 - share) for share in shares)
        if slope <= 0:
            break
        step = (sum(shares) - half) / slope
        shift -= step
        if abs(step) < 1e-14:
            break
    return math.exp(shift)


def bradley_terry(count: int, games: list[tuple[int, int, float]], prior: float = PRIOR) -> list:
    """Returns the rating of each of `count` entrants from games, on the Elo scale about 1000.

    The strengths come from the iteration of Newman, 2023, each entrant's strength its wins
    weighed by the strengths of those it beat over its losses weighed alike, taken in turn, with
    the common scale set after each step by the virtual draws, until no strength moves by more
    than a ten billionth of itself. An entrant that has won nothing, or lost nothing, with no
    virtual draws keeps the strength it had, which only a test of the model asks for.

    Args:
        count: The entrants.
        games: Each game as the two entrants and the share of a win of the first, 1, a half or 0.
        prior: The draws that each entrant plays against a virtual entrant of strength 1.
    """
    if count == 0:
        return []
    wins: dict[tuple[int, int], float] = {}
    for first, second, share in games:
        if first == second:
            continue
        wins[(first, second)] = wins.get((first, second), 0.0) + share
        wins[(second, first)] = wins.get((second, first), 0.0) + 1 - share
    met: list[list[tuple[int, float, float]]] = [[] for _ in range(count)]
    for (first, second), won in wins.items():
        met[first].append((second, won, wins[(second, first)]))
    strength = [1.0] * count
    half = prior / 2
    for _ in range(_STEPS):
        old = list(strength)
        # Each strength takes the new values of those before it, which keeps two entrants from
        # trading places step after step.
        for index in range(count):
            own = strength[index]
            above = below = half / (own + 1)
            for other, won, lost in met[index]:
                total = own + strength[other]
                above += won * strength[other] / total
                below += lost / total
            if below > 0 and above > 0:
                strength[index] = max(above / below, 1e-300)
        factor = _common_scale(strength) if prior > 0 else 1.0
        strength = [value * factor for value in strength]
        moved = max(abs(math.log(value / was)) for value, was in zip(strength, old, strict=True))
        if moved < _TOLERANCE:
            break
    logs = [400 * math.log10(value) for value in strength]
    mean = sum(logs) / count
    return [CENTRE + value - mean for value in logs]


def _percentile(values: list[float], share: float) -> float:
    """Returns a percentile of values, between the two nearest of them in sorted order."""
    ordered = sorted(values)
    position = share * (len(ordered) - 1)
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _generator(seed: int) -> random.Random:
    return random.Random(hashlib.sha256(f'{seed}/bootstrap'.encode()).digest())


def ratings(
    count: int, matches: list[dict[str, Any]], seed: int, resamples: int = RESAMPLES
) -> list[dict[str, Any]]:
    """Returns the rating of every entrant with its 95 percent interval and matches, best first.

    Args:
        count: The entrants of the tournament.
        matches: The matches, each with `home`, `away` and a `result` with its `score` once
            played, as an evaluation or the runner's `get` gives them.
        seed: The tournament seed, which seeds the bootstrap.
        resamples: The resamples of the bootstrap.
    """
    played = _played(matches)
    games = [(m['home'], m['away'], _outcome(m['result']['score'])) for m in played]
    fitted = bradley_terry(count, games)
    samples: list[list[float]] = [[] for _ in range(count)]
    if games and resamples > 0:
        draw = _generator(seed)
        for _ in range(resamples):
            again = [games[draw.randrange(len(games))] for _ in games]
            for index, value in enumerate(bradley_terry(count, again)):
                samples[index].append(value)
    counts = [0] * count
    for first, second, _ in games:
        counts[first] += 1
        counts[second] += 1
    rows = []
    for index in range(count):
        low = _percentile(samples[index], 0.025) if samples[index] else fitted[index]
        high = _percentile(samples[index], 0.975) if samples[index] else fitted[index]
        rows.append(
            {
                'entrant': index,
                'rating': round(fitted[index], 2),
                'low': round(min(low, fitted[index]), 2),
                'high': round(max(high, fitted[index]), 2),
                'matches': counts[index],
            }
        )
    rows.sort(key=lambda row: (-row['rating'], row['entrant']))
    return rows


def goal_matrix(count: int, matches: list[dict[str, Any]]) -> dict[str, Any]:
    """Returns the mean goal difference of every pair, row against column, with match counts.

    `mean[row][column]` is the mean of the row entrant's goals less the column entrant's over
    their matches, whichever side was at home, `None` for a pair that has not met, and
    `matches[row][column]` the number of those matches.
    """
    totals = [[0] * count for _ in range(count)]
    counts = [[0] * count for _ in range(count)]
    for match in _played(matches):
        home, away = match['home'], match['away']
        if home == away:
            continue
        score = match['result']['score']
        totals[home][away] += score[0] - score[1]
        totals[away][home] += score[1] - score[0]
        counts[home][away] += 1
        counts[away][home] += 1
    mean = [
        [
            round(totals[row][column] / counts[row][column], 4) if counts[row][column] else None
            for column in range(count)
        ]
        for row in range(count)
    ]
    return {'mean': mean, 'matches': counts}


def _side_of(rule: dict[str, Any] | None, side: int) -> bool:
    """Returns whether the rule that ended a match was broken by the side of index `side`."""
    if not rule:
        return False
    return rule['side'] == 'both' or rule['side'] == ('home', 'away')[side]


def standings(
    config: dict[str, Any],
    matches: list[dict[str, Any]],
    ranking: list[int] | None,
    rated: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Returns a row of every entrant over all the matches it played, in order.

    The points of a match follow its stage, and deciding matches count as the tables count them,
    not at all. A forfeit counts against the side that broke a rule, or that lost a match
    awarded by hand. The order is the tournament's final ranking once it has one, and before that
    points, goal difference, goals scored and rating.
    """
    count = len(config['entrants'])
    rows = [
        {
            'entrant': index,
            'played': 0,
            'won': 0,
            'drawn': 0,
            'lost': 0,
            'goals_for': 0,
            'goals_against': 0,
            'goal_difference': 0,
            'points': 0,
            'forfeits': 0,
            'cut_short': 0,
        }
        for index in range(count)
    ]
    for match in _played(matches):
        if match.get('decider'):
            continue
        result = match['result']
        score = result['score']
        points = config['stages'][match['stage']]['points']
        for side, entrant in enumerate((match['home'], match['away'])):
            row = rows[entrant]
            own, other = score[side], score[1 - side]
            row['played'] += 1
            row['goals_for'] += own
            row['goals_against'] += other
            outcome = 'win' if own > other else 'draw' if own == other else 'loss'
            row[{'win': 'won', 'draw': 'drawn', 'loss': 'lost'}[outcome]] += 1
            row['points'] += points[outcome]
            rule = result.get('rule')
            if result.get('forfeit') and (_side_of(rule, side) or (not rule and own < other)):
                row['forfeits'] += 1
            if _cut_short(result):
                row['cut_short'] += 1
    by_rating = {row['entrant']: row['rating'] for row in rated}
    for row in rows:
        row['goal_difference'] = row['goals_for'] - row['goals_against']
        row['rating'] = by_rating.get(row['entrant'], CENTRE)
    if ranking is not None and sorted(ranking) == list(range(count)):
        place = {entrant: position for position, entrant in enumerate(ranking)}
        rows.sort(key=lambda row: place[row['entrant']])
    else:
        rows.sort(
            key=lambda row: (
                -row['points'],
                -row['goal_difference'],
                -row['goals_for'],
                -row['rating'],
                row['entrant'],
            )
        )
    for position, row in enumerate(rows):
        row['position'] = position + 1
    return rows


def _cut_short(result: dict[str, Any]) -> bool:
    """Returns whether a match ended before its own end, by a rule that a side broke."""
    stats = result.get('stats') or {}
    return bool(stats.get('cut_short')) or bool(result.get('rule'))


def entrant_ids(entrants: list[dict[str, Any]]) -> list[str]:
    """Returns an identifier of each entrant that no other entrant and no team name shares.

    It is the entrant's key, the team's identifier for a team, `builtin:0.50` for the built-in AI
    at an ability, `random:uniform` for the random entrant and `person:Ana` for a person, with
    `#2`, `#3` and so on after a key that an earlier entrant holds, as two entrants of one team
    do. A colon or a hash never stands in a team's identifier, so the built-in AI and the random
    entrant never read as a team.
    """
    seen: dict[str, int] = {}
    found = []
    for index, entrant in enumerate(entrants):
        key = str(entrant.get('key') or f'entrant:{index}')
        seen[key] = seen.get(key, 0) + 1
        found.append(key if seen[key] == 1 else f'{key}#{seen[key]}')
    return found


def method(seed: int, resamples: int = RESAMPLES) -> dict[str, Any]:
    """Returns how the ratings are made, the model, its prior, its scale and its bootstrap."""
    return {
        'model': 'Bradley and Terry, a draw counting as half a win for each side',
        'fit': 'the iteration of Newman, 2023, to a change of strength below 1e-10',
        'scale': 'Elo, 400 points for each tenfold of strength, the mean of the ratings at 1000',
        'centre': CENTRE,
        'prior': {
            'virtual_draws': PRIOR,
            'opponent': 'a virtual entrant of the fixed strength 1, before the ratings are centred',
        },
        'bootstrap': {
            'resamples': resamples,
            'tournament_seed': seed,
            'generator': (
                "Python's random.Random seeded with the SHA-256 digest of '<seed>/bootstrap'"
            ),
            'draw': 'the played matches drawn again with replacement, as many as were played',
            'interval': 'the 2.5th and 97.5th percentiles, between the nearest resamples',
        },
        'matches': 'every played match, forfeits and deciding matches included',
    }


def match_rows(config: dict[str, Any], matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Returns every played match as a line of `matches.jsonl`, in the order of the schedule.

    Each line holds the key, stage, label and scenario of the match, its two sides by index and
    name, its seed, score and steps, whether it was a forfeit with the rule a side broke, the
    reason and the score at that moment, and for each side the calls of its policy, the mean, the
    largest and the first compute time of a call in milliseconds, and the count of each action
    it answered, `null` for a side without a policy of its own, such as the built-in AI.
    """
    entrants = config['entrants']
    lines = []
    for match in _played(matches):
        result = match['result']
        stats = result.get('stats') or {}
        sides = stats.get('sides') or [None, None]
        rule = result.get('rule')
        lines.append(
            {
                'key': match['key'],
                'stage': match['stage'],
                'label': match.get('label'),
                'scenario': match.get('scenario'),
                'home': match['home'],
                'away': match['away'],
                'home_name': entrants[match['home']]['name'],
                'away_name': entrants[match['away']]['name'],
                'seed': match.get('seed'),
                'score': list(result['score']),
                'steps': stats.get('steps'),
                'cut_short': _cut_short(result),
                'forfeit': bool(result.get('forfeit')),
                'rule': None
                if not rule
                else {
                    'side': rule['side'],
                    'kind': rule['kind'],
                    'detail': rule.get('detail'),
                    'reason': rule['reason'],
                    'step': rule['step'],
                    'score': list(rule['at']),
                },
                'timings': [
                    None
                    if not side
                    else {
                        key: side.get(key)
                        for key in ('calls', 'mean_ms', 'mean_after_first_ms', 'max_ms', 'first_ms')
                    }
                    for side in sides
                ],
                'actions': [
                    None if not side else dict(side.get('actions') or {}) for side in sides
                ],
                'recording': result.get('match'),
            }
        )
    return lines


def analysis(entry: dict[str, Any], resamples: int = RESAMPLES) -> dict[str, Any]:
    """Returns the ratings, the matrix, the standings and the matches of a tournament.

    Args:
        entry: The tournament in full, as the runner's `get` gives it, with its configuration,
            matches, ranking and the entrants that the pre-flight left out.
        resamples: The resamples of the bootstrap.
    """
    config = entry['config']
    count = len(config['entrants'])
    matches = entry['matches']
    rated = ratings(count, matches, config['seed'], resamples)
    rows = match_rows(config, matches)
    return {
        'ratings': rated,
        'resamples': resamples,
        'method': method(config['seed'], resamples),
        'ids': entrant_ids(config['entrants']),
        'played': len(rows),
        'cut_short': sum(1 for row in rows if row['cut_short']),
        'matrix': goal_matrix(count, matches),
        'standings': standings(config, matches, entry.get('ranking'), rated),
        'matches': rows,
        'excluded': list(entry.get('excluded') or []),
    }


def _csv(columns: tuple[str, ...], rows: list[dict[str, Any]]) -> str:
    stream = io.StringIO()
    writer = csv.DictWriter(stream, columns, lineterminator='\n', extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow({key: '' if row.get(key) is None else row[key] for key in columns})
    return stream.getvalue()


def files(entry: dict[str, Any], found: dict[str, Any] | None = None) -> dict[str, str]:
    """Returns the text of each file of a tournament's results, by its name in `FILES`.

    Args:
        entry: The tournament in full, as the runner's `get` gives it.
        found: Its analysis, as `analysis` gives it, or `None` to make it.
    """
    found = analysis(entry) if found is None else found
    config = entry['config']
    entrants = config['entrants']
    ids = entrant_ids(entrants)

    def named(row: dict[str, Any]) -> dict[str, Any]:
        entrant = entrants[row['entrant']]
        return {
            **row,
            'id': ids[row['entrant']],
            'name': entrant['name'],
            'kind': entrant['kind'],
            'team': entrant.get('team'),
        }

    rated = [{**named(row), 'rank': rank + 1} for rank, row in enumerate(found['ratings'])]
    pairs = []
    matrix = found['matrix']
    for row in range(len(entrants)):
        for column in range(len(entrants)):
            if row == column:
                continue
            pairs.append(
                {
                    'entrant': row,
                    'id': ids[row],
                    'name': entrants[row]['name'],
                    'opponent': column,
                    'opponent_id': ids[column],
                    'opponent_name': entrants[column]['name'],
                    'matches': matrix['matches'][row][column],
                    'mean_goal_difference': matrix['mean'][row][column],
                }
            )
    by_entrant = {row['entrant']: row for row in found['ratings']}
    listed = [
        {
            'entrant': index,
            'id': ids[index],
            'name': entrant['name'],
            'kind': entrant['kind'],
            'team': entrant.get('team'),
            'key': entrant.get('key'),
            'ability': entrant.get('ability'),
            'rating': by_entrant[index]['rating'],
            'low': by_entrant[index]['low'],
            'high': by_entrant[index]['high'],
        }
        for index, entrant in enumerate(entrants)
    ]
    counts = io.StringIO()
    writer = csv.writer(counts, lineterminator='\n')
    writer.writerow(['id', *ids])
    for row in range(len(entrants)):
        writer.writerow([ids[row], *matrix['matches'][row]])
    sidecar = {
        **found.get('method', method(config['seed'])),
        'played': found.get('played'),
        'cut_short': found.get('cut_short'),
    }
    return {
        'standings.csv': _csv(STANDINGS_COLUMNS, [named(row) for row in found['standings']]),
        'ratings.csv': _csv(RATINGS_COLUMNS, rated),
        'ratings_method.json': json.dumps(sidecar, indent=2) + '\n',
        'pairwise_gd.csv': _csv(PAIRWISE_COLUMNS, pairs),
        'pairwise_counts.csv': counts.getvalue(),
        'matches.jsonl': ''.join(json.dumps(line) + '\n' for line in found['matches']),
        'entrants.json': json.dumps(listed, indent=2) + '\n',
        'excluded.json': json.dumps(found['excluded'], indent=2) + '\n',
    }
