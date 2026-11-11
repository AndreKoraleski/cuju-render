# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks the renderer's tournaments, their formats, draws, tiebreaks, runner, server and CLI."""

import itertools
import json
import os
import random
import threading
import time
import urllib.request

import pytest

from cuju.render._format import recording as _recording
from cuju.render._http import server as _server
from cuju.render._store import home as _home
from cuju.render._store import library as _library
from cuju.render._tournaments import tournament as rules
from cuju.render._tournaments import tournament_runner as runner
from support.common import _shipped_language, _translation

_BUILTIN = {
    'id': 'builtin',
    'kind': 'builtin',
    'name': 'Built-in AI',
    'style': {'kit': {'primary': [255, 111, 0], 'secondary': [255, 255, 255]}},
}


def _team(identifier, format='11v11'):
    return {
        'id': identifier,
        'kind': 'submission',
        'name': identifier.title(),
        'format': format,
        'style': {'kit': {'primary': [10, 20, 30], 'secondary': [40, 50, 60]}},
    }


_TEAMS = [_BUILTIN, _team('reds'), _team('blues'), _team('minis', '5v5')]


def _fits(entrant, scenario):
    """Rejects a team of one format in a full match of the other, as the registry check does."""
    size = '5v5' if scenario.startswith('5_vs_5') else '11v11'
    if entrant['format'] and scenario[0].isdigit() and entrant['format'] != size:
        return f'expected a scenario of {entrant["format"]}'
    return None


def _builtins(count):
    return [
        {'kind': 'builtin', 'ability': round(index / max(1, count), 4)} for index in range(count)
    ]


def _config(stages, count=8, seed=11, **options):
    return rules.check(
        {'name': 'Cup', 'seed': seed, 'entrants': _builtins(count), 'stages': stages, **options},
        _TEAMS,
        _fits,
    )


def _play_out(config, score=None, seed=0, limit=100000):
    """Plays a tournament to its end with made up results, and returns its last evaluation."""
    draw = random.Random(seed)
    results = {}
    for _ in range(limit):
        view = rules.evaluate(config, results)
        if view['complete']:
            return view, results
        ready = rules.ready(view)
        assert ready, 'the tournament stopped with nothing to play'
        for match in ready:
            goals = score(match) if score else [draw.randrange(4), draw.randrange(4)]
            results[match['key']] = {'score': goals, 'cards': [[0, 0], [0, 0]]}
    raise AssertionError('the tournament never ended')


_FORMATS = [
    {'format': 'knockout'},
    {'format': 'knockout', 'third_place': True, 'legs': 2, 'settle': ['away_goals', 'lots']},
    {'format': 'knockout', 'bracket': 'play_in'},
    {'format': 'double_elimination'},
    {'format': 'double_elimination', 'grand_final_reset': False},
    {'format': 'league'},
    {'format': 'league', 'cycles': 2, 'legs': 2},
    {'format': 'swiss'},
    {'format': 'ladder'},
    {'format': 'king_of_the_hill', 'laps': 2},
    {'format': 'gauntlet'},
    {'format': 'gauntlet', 'draws': 'holder'},
]


@pytest.mark.parametrize('stage', _FORMATS, ids=lambda stage: '-'.join(map(str, stage.values())))
@pytest.mark.parametrize('count', [2, 3, 5, 7, 8, 13, 16, 17, 31])
def test_every_format_ends_with_a_full_ranking(stage, count):
    config = _config([stage], count)
    view, _ = _play_out(config, seed=count)
    assert sorted(view['ranking']) == list(range(count))
    assert view['champion'] == view['ranking'][0]
    keys = [match['key'] for match in view['matches']]
    assert len(keys) == len(set(keys))
    assert all(match['home'] != match['away'] for match in view['matches'])


@pytest.mark.parametrize(
    'stage',
    [
        {'format': 'knockout'},
        {'format': 'knockout', 'bracket': 'play_in'},
        {'format': 'double_elimination'},
        {'format': 'league'},
        {'format': 'groups', 'group_size': 8, 'qualifiers': 1},
        {'format': 'swiss'},
        {'format': 'ladder', 'rounds': 3},
        {'format': 'king_of_the_hill'},
        {'format': 'gauntlet'},
    ],
    ids=lambda stage: stage['format'],
)
def test_formats_take_256_entrants(stage):
    config = _config([stage], 256)
    view, _ = _play_out(config, seed=3)
    assert sorted(view['ranking']) == list(range(256))


@pytest.mark.parametrize('count', [4, 5, 6, 7, 11, 13, 23, 24, 37])
def test_groups_then_knockout_chain(count):
    config = _config(
        [
            {
                'format': 'groups',
                'group_size': 4,
                'qualifiers': 2,
                'best_position': 3,
                'best_count': 'fill',
            },
            {'format': 'knockout', 'third_place': True},
        ],
        count,
    )
    first = config['stages'][0]
    assert sum(first['group_sizes']) == count
    assert max(first['group_sizes']) - min(first['group_sizes']) <= 1
    view, _ = _play_out(config, seed=count)
    groups, knockout = view['stages']
    assert knockout['entrants'] == groups['ranking'][: first['advance']]
    assert sorted(view['ranking']) == list(range(count))
    # The final ranking keeps the order of the knockout first, then of the groups.
    assert view['ranking'][: len(knockout['ranking'])] == knockout['ranking']


def test_group_stage_with_uneven_sizes_pots_and_best_places():
    config = _config(
        [
            {
                'format': 'groups',
                'group_sizes': [5, 4, 3],
                'pots': 3,
                'qualifiers': [2, 2, 1],
                'best_position': 3,
                'best_count': 1,
            },
            {'format': 'league'},
        ],
        12,
    )
    stage = config['stages'][0]
    assert stage['advance'] == 6
    groups = rules.draw_groups(rules.seeding(config), stage, config['seed'], 0)
    assert [len(group) for group in groups] == [5, 4, 3]
    assert sorted(itertools.chain(*groups)) == list(range(12))
    # The first pot holds the four best seeds, dealt one to each group before any repeats.
    seeds = rules.seeding(config)
    top = set(seeds[:4])
    assert all(top & set(group) for group in groups)
    view, _ = _play_out(config, seed=1)
    tables = view['stages'][0]['tables']
    assert [table['qualify'] for table in tables] == [2, 2, 1]
    best = view['stages'][0]['best']
    assert len(best) == 1
    third = [table['rows'][2]['entrant'] for table in tables if table['qualify'] < 3]
    assert best[0] in third
    assert len(view['stages'][1]['entrants']) == 6


def test_knockout_byes_go_to_the_top_seeds():
    config = _config([{'format': 'knockout'}], 5, seeding='manual')
    view = rules.evaluate(config, {})
    first = view['stages'][0]['rounds'][0]['fixtures']
    byes = [fixture for fixture in first if fixture['decided_by'] == 'bye']
    assert sorted(fixture['winner'] for fixture in byes) == [0, 1, 2]
    played = [fixture for fixture in first if fixture['decided_by'] != 'bye']
    assert [(fixture['home'], fixture['away']) for fixture in played] == [(3, 4)]


def test_play_in_round_brings_a_bracket_to_a_power_of_two():
    config = _config([{'format': 'knockout', 'bracket': 'play_in'}], 6, seeding='manual')
    assert config['stages'][0]['bracket_size'] == 4
    view = rules.evaluate(config, {})
    play_in = view['stages'][0]['rounds'][0]
    assert play_in['name'] == 'Play-in round'
    assert [(f['home'], f['away']) for f in play_in['fixtures']] == [(2, 5), (3, 4)]
    semi = view['stages'][0]['rounds'][1]['fixtures']
    assert semi[0]['home'] == 0 and semi[0]['away']['from'] == 'Winner of Play-in 2'
    assert semi[0]['away']['from_id'] == 'server.tournament.label.winner_of'


def test_two_legged_ties_add_up_and_settle_by_away_goals():
    config = _config(
        [{'format': 'knockout', 'legs': 2, 'settle': ['away_goals', 'lots']}], 2, seeding='manual'
    )
    view = rules.evaluate(config, {})
    first, second = view['matches']
    # The higher seed plays the second leg at home.
    assert (first['home'], first['away'], second['home'], second['away']) == (1, 0, 0, 1)
    results = {first['key']: {'score': [1, 2]}, second['key']: {'score': [0, 1]}}
    tie = rules.evaluate(config, results)['stages'][0]['rounds'][0]['fixtures'][0]
    assert tie['score'] == [2, 2]
    # Seed 0 scored two away goals in the first leg, seed 1 one in the second.
    assert (tie['winner'], tie['decided_by']) == (0, 'away goals')
    results = {first['key']: {'score': [1, 0]}, second['key']: {'score': [3, 0]}}
    tie = rules.evaluate(config, results)['stages'][0]['rounds'][0]['fixtures'][0]
    assert (tie['score'], tie['winner'], tie['decided_by']) == ([3, 1], 0, 'aggregate')


def test_drawn_ties_settle_by_replay_then_decider_then_lots():
    stage = {
        'format': 'knockout',
        'settle': ['replay', 'decider', 'lots'],
        'replays': 2,
        'decider_scenario': 'academy_empty_goal_close',
    }
    config = _config([stage], 2, seeding='manual')
    results = {}
    view = rules.evaluate(config, results)
    results[view['matches'][0]['key']] = {'score': [1, 1]}
    view = rules.evaluate(config, results)
    replays = [m for m in view['matches'] if m['result'] is None]
    assert [m['key'] for m in replays] == ['0/w2-1/r1']
    results['0/w2-1/r1'] = {'score': [0, 0]}
    results['0/w2-1/r2'] = {'score': [2, 2]}
    view = rules.evaluate(config, results)
    deciders = [m for m in view['matches'] if m['result'] is None]
    assert [m['key'] for m in deciders] == ['0/w2-1/d1', '0/w2-1/d2']
    assert all(m['scenario'] == 'academy_empty_goal_close' and m['decider'] for m in deciders)
    # Each side attacks from the left once, and the goals of both add up.
    assert (deciders[0]['home'], deciders[1]['home']) == (0, 1)
    results['0/w2-1/d1'] = {'score': [1, 0]}
    results['0/w2-1/d2'] = {'score': [1, 0]}
    tie = rules.evaluate(config, results)['stages'][0]['rounds'][0]['fixtures'][0]
    assert tie['decider'] == [1, 1] and tie['decided_by'] == 'lots'
    lots = tie['winner']
    again = rules.evaluate(config, results)['stages'][0]['rounds'][0]['fixtures'][0]
    assert again['winner'] == lots
    results['0/w2-1/d2'] = {'score': [2, 0]}
    tie = rules.evaluate(config, results)['stages'][0]['rounds'][0]['fixtures'][0]
    assert (tie['winner'], tie['decided_by']) == (1, 'decider')


def _league_with(results_by_pair, tiebreakers, count=4, points=None):
    stage = {'format': 'league', 'tiebreakers': tiebreakers}
    if points:
        stage['points'] = points
    config = _config([stage], count, seeding='manual')
    view = rules.evaluate(config, {})
    results = {}
    for match in view['matches']:
        pair = (match['home'], match['away'])
        if pair in results_by_pair:
            results[match['key']] = {'score': results_by_pair[pair]}
        else:
            home, away = results_by_pair[pair[::-1]]
            results[match['key']] = {'score': [away, home]}
        cards = results_by_pair.get(('cards', pair))
        if cards is None and ('cards', pair[::-1]) in results_by_pair:
            cards = results_by_pair[('cards', pair[::-1])][::-1]
        if cards:
            results[match['key']]['cards'] = cards
    return rules.evaluate(config, results)['stages'][0]['tables'][0]['rows']


def test_tiebreakers_follow_the_order_of_the_stage_and_name_their_reason():
    # Entrants 0 and 1 both win twice and lose once. Entrant 0 has the better goal difference,
    # entrant 1 scored more goals, and entrant 1 won the match between them.
    games = {
        (0, 1): [0, 1],
        (0, 2): [3, 0],
        (0, 3): [3, 0],
        (1, 2): [5, 4],
        (1, 3): [2, 3],
        (2, 3): [0, 0],
    }
    rows = _league_with(games, ['goal_difference', 'goals_for'])
    assert [row['entrant'] for row in rows[:2]] == [0, 1]
    assert rows[0]['tiebreak'] == 'goal_difference'
    rows = _league_with(games, ['goals_for', 'goal_difference'])
    assert [row['entrant'] for row in rows[:2]] == [1, 0]
    assert rows[0]['tiebreak'] == 'goals_for'
    rows = _league_with(games, ['head_to_head', 'goal_difference'])
    assert [row['entrant'] for row in rows[:2]] == [1, 0]
    assert rows[0]['tiebreak'] == 'head_to_head'
    # Rows that differ in points carry no tiebreak.
    assert rows[1]['tiebreak'] is None


def test_fair_play_and_lots_decide_level_rows():
    games = {
        (0, 1): [1, 1],
        (0, 2): [1, 0],
        (0, 3): [0, 1],
        (1, 2): [1, 0],
        (1, 3): [0, 1],
        (2, 3): [0, 0],
        ('cards', (0, 2)): [[2, 0], [0, 0]],
    }
    rows = _league_with(games, ['goal_difference', 'fair_play'])
    order = [row['entrant'] for row in rows]
    assert order.index(1) < order.index(0)
    assert rows[order.index(1)]['tiebreak'] == 'fair_play'
    first = _league_with(games, ['goal_difference'])
    again = _league_with(games, ['goal_difference'])
    assert [row['entrant'] for row in first] == [row['entrant'] for row in again]
    assert 'lots' in [row['tiebreak'] for row in first]


def test_points_for_a_win_draw_and_loss_are_configurable():
    games = {(0, 1): [1, 0], (0, 2): [0, 0], (1, 2): [0, 0]}
    rows = _league_with(games, ['goal_difference'], 3, {'win': 2, 'draw': 1, 'loss': -1})
    points = {row['entrant']: row['points'] for row in rows}
    assert points == {0: 3, 1: 0, 2: 2}


@pytest.mark.parametrize('count', range(2, 21))
def test_swiss_pairs_by_score_without_rematches_and_one_bye_each(count):
    rounds = max(1, -(-count // 2))
    config = _config([{'format': 'swiss', 'rounds': rounds}], count)
    view, _ = _play_out(config, seed=count)
    stage = view['stages'][0]
    pairs = [
        frozenset((fixture['home'], fixture['away']))
        for round_ in stage['rounds']
        for fixture in round_['fixtures']
    ]
    assert len(pairs) == len(set(pairs))
    byes = [round_['bye'] for round_ in stage['rounds'] if round_['bye'] is not None]
    assert len(byes) == len(set(byes)) == (rounds if count % 2 else 0)
    for round_ in stage['rounds']:
        seen = [e for f in round_['fixtures'] for e in (f['home'], f['away'])]
        assert len(seen) == len(set(seen)) == count - (count % 2)


def test_swiss_rounds_default_from_the_entrants_and_refuse_too_many():
    assert _config([{'format': 'swiss'}], 16)['stages'][0]['rounds'] == 4
    assert _config([{'format': 'swiss'}], 3)['stages'][0]['rounds'] == 2
    with pytest.raises(rules.TournamentError, match='without rematches'):
        _config([{'format': 'swiss', 'rounds': 9}], 16)


def test_swiss_pairing_falls_back_to_palmer_when_the_search_runs_out():
    order = list(range(12))
    met = {frozenset((a, b)) for a in range(12) for b in range(12) if a != b and abs(a - b) == 1}
    pairs, bye = rules.swiss_pairs(order, met, set(), budget=0)
    assert bye is None and len(pairs) == 6
    assert not {frozenset(pair) for pair in pairs} & met
    assert sorted(itertools.chain(*pairs)) == order


def test_swiss_second_round_pairs_winners_with_winners():
    config = _config([{'format': 'swiss', 'rounds': 2}], 8, seeding='manual')
    view = rules.evaluate(config, {})
    first = [m for m in view['matches']]
    results = {m['key']: {'score': [1, 0]} for m in first}
    view = rules.evaluate(config, results)
    winners = {m['home'] for m in first}
    second = [m for m in view['matches'] if m['result'] is None]
    assert len(second) == 4
    for match in second:
        assert (match['home'] in winners) == (match['away'] in winners)


def test_double_elimination_resets_the_grand_final():
    config = _config([{'format': 'double_elimination'}], 4, seeding='manual')

    def lower_seed_wins_grand_final(match):
        if match['label'].startswith('Grand final'):
            return [0, 1] if match['label'] == 'Grand final' else [2, 0]
        return [1, 0]

    view, _ = _play_out(config, lower_seed_wins_grand_final)
    rounds = view['stages'][0]['rounds']
    assert [r['name'] for r in rounds][-2:] == ['Grand final', 'Grand final, deciding match']
    assert view['champion'] == 0
    config = _config(
        [{'format': 'double_elimination', 'grand_final_reset': False}], 4, seeding='manual'
    )
    view, _ = _play_out(config, lower_seed_wins_grand_final)
    assert [r['name'] for r in view['stages'][0]['rounds']][-1] == 'Grand final'
    assert view['champion'] != 0


def test_knockout_ranks_by_round_and_third_place():
    config = _config([{'format': 'knockout', 'third_place': True}], 8, seeding='manual')
    view, _ = _play_out(config, lambda match: [1, 0])
    ranking = view['ranking']
    assert ranking[0] == 0
    final = view['stages'][0]['rounds'][2]['fixtures'][0]
    third = view['stages'][0]['rounds'][3]['fixtures'][0]
    assert ranking[1] == final['loser']
    assert ranking[2:4] == [third['winner'], third['loser']]


def test_ladder_king_and_gauntlet_follow_their_rules():
    higher_wins = lambda match: [1, 0]  # noqa: E731
    config = _config([{'format': 'ladder', 'rounds': 5}], 5, seeding='manual')
    view, _ = _play_out(config, higher_wins)
    assert view['ranking'] == [0, 1, 2, 3, 4]
    config = _config([{'format': 'ladder', 'rounds': 5}], 5, seeding='manual')
    view, _ = _play_out(config, lambda match: [0, 1])
    # Challengers always winning reverse a ladder of five in five rounds.
    assert view['ranking'] == [4, 3, 2, 1, 0]
    config = _config([{'format': 'king_of_the_hill'}], 4, seeding='manual')
    view, _ = _play_out(config, lambda match: [0, 0])
    assert view['champion'] == 0
    config = _config([{'format': 'gauntlet'}], 4, seeding='manual')
    view, _ = _play_out(config, lambda match: [0, 1])
    # The climber wins every step, so the lowest seed climbs to the top.
    assert view['champion'] == 3
    assert view['ranking'] == [3, 0, 1, 2]


def test_the_same_seed_gives_the_same_draw_and_match_seeds():
    stages = [{'format': 'groups', 'group_size': 4}, {'format': 'knockout'}]
    first = _config(stages, 16, seed=5)
    second = _config(stages, 16, seed=5)
    other = _config(stages, 16, seed=6)
    a, _ = _play_out(first, seed=1)
    b, _ = _play_out(second, seed=1)
    c, _ = _play_out(other, seed=1)
    seeds = lambda view: [(m['key'], m['seed'], m['home'], m['away']) for m in view['matches']]  # noqa: E731
    assert seeds(a) == seeds(b)
    assert seeds(a) != seeds(c)
    assert rules.match_seed(5, '0/A/1-1') == rules.match_seed(5, '0/A/1-1')
    assert 0 <= rules.match_seed(5, 'x') < 2**31


def test_seeding_by_rating_and_manual_order():
    entrants = [
        {'kind': 'builtin', 'ability': 0.1, 'rating': 1400},
        {'kind': 'builtin', 'ability': 0.2, 'rating': 1700},
        {'kind': 'builtin', 'ability': 0.3},
    ]
    config = rules.check(
        {
            'name': 'R',
            'seed': 1,
            'entrants': entrants,
            'seeding': 'rating',
            'stages': [{'format': 'league'}],
        },
        _TEAMS,
        ratings={'builtin:0.30': 1600},
    )
    assert rules.seeding(config) == [1, 2, 0]
    config['seeding'] = 'manual'
    assert rules.seeding(config) == [0, 1, 2]


def test_ratings_move_by_elo():
    table = {}
    home = {'key': 'a', 'name': 'A'}
    away = {'key': 'b', 'name': 'B'}
    rules.update_ratings(table, home, away, [2, 0])
    assert table['a']['rating'] == 1510 and table['b']['rating'] == 1490
    rules.update_ratings(table, home, away, [1, 1])
    assert table['a']['rating'] < 1510 and table['a']['matches'] == 2


def test_stages_take_their_own_scenarios_within_what_entrants_play():
    entrants = [
        {'kind': 'builtin', 'ability': 0.5},
        {'kind': 'person', 'name': 'Ana'},
        {'kind': 'builtin'},
        {'kind': 'builtin', 'ability': 1.0},
    ]
    stages = [
        {'format': 'league', 'scenario': '5_vs_5', 'advance': 2, 'length': 600},
        {'format': 'knockout', 'scenario': '11_vs_11_kaggle'},
    ]
    config = rules.check(
        {'name': 'Mixed', 'seed': 2, 'entrants': entrants, 'stages': stages}, _TEAMS, _fits
    )
    assert [stage['scenario'] for stage in config['stages']] == ['5_vs_5', '11_vs_11_kaggle']
    assert config['entrants'][1]['kind'] == 'person'
    view = rules.evaluate(config, {})
    assert all(match['length'] == 600 for match in view['matches'])
    assert any(match['person'] for match in view['matches'])
    with pytest.raises(rules.TournamentError, match='Minis cannot play 11_vs_11_kaggle'):
        rules.check(
            {
                'name': 'Mixed',
                'seed': 2,
                'entrants': [*entrants[:3], {'kind': 'team', 'team': 'minis'}],
                'stages': stages,
            },
            _TEAMS,
            _fits,
        )


@pytest.mark.parametrize(
    ('change', 'message'),
    [
        ({'entrants': _builtins(1)}, 'from 2 to 256 entrants'),
        ({'entrants': _builtins(257)}, 'from 2 to 256 entrants'),
        ({'stages': [{'format': 'cup'}]}, 'format of stage 1'),
        ({'stages': [{'format': 'knockout', 'bracket_size': 4}]}, 'needs from 3 to 4 entrants'),
        (
            {'stages': [{'format': 'knockout', 'bracket': 'play_in', 'bracket_size': 16}]},
            'needs from 16 to 31',
        ),
        ({'stages': [{'format': 'knockout', 'until': 3}]}, 'power of two below'),
        ({'stages': [{'format': 'groups', 'groups': 5}]}, 'at least 2 entrants'),
        ({'stages': [{'format': 'groups', 'group_sizes': [4, 3]}]}, 'hold 7 entrants'),
        ({'stages': [{'format': 'groups', 'qualifiers': 5}]}, 'qualifiers of group A'),
        ({'stages': [{'format': 'swiss', 'rounds': 5}]}, 'without rematches'),
        (
            {
                'stages': [
                    {'format': 'league', 'advance': 2},
                    {'format': 'league', 'advance': 1},
                    {'format': 'league'},
                ]
            },
            'advance from stage 2',
        ),
        ({'stages': [{'format': 'knockout', 'legs': 11}]}, 'legs of stage 1'),
        (
            {
                'stages': [
                    {'format': 'league', 'tiebreakers': ['goal_difference', 'goal_difference']}
                ]
            },
            'without repeats',
        ),
        ({'stages': [{'format': 'league', 'points': {'win': 3}}]}, 'points for a win'),
        ({'stages': [{'format': 'league', 'cup': 1}]}, 'unknown settings'),
        ({'stages': [{'format': 'league', 'length': 10}]}, 'length of stage 1'),
        ({'concurrency': 9}, 'matches at once'),
        (
            {
                'entrants': [
                    {'kind': 'team', 'team': 'reds', 'name': 'Rex'},
                    {'kind': 'team', 'team': 'reds', 'name': ' rex '},
                ]
            },
            'a name of its own for entrant 2, found rex, the name of entrant 1',
        ),
        ({'entrants': [{'kind': 'person'}, {'kind': 'builtin'}]}, 'name for each person'),
        ({'stages': [{'format': 'double_elimination', 'bracket': 'play_in'}]}, 'fills with byes'),
    ],
)
def test_impossible_configurations_name_the_reason(change, message):
    config = {
        'name': 'Bad',
        'seed': 1,
        'entrants': _builtins(8),
        'stages': [{'format': 'knockout'}],
        **change,
    }
    with pytest.raises(rules.TournamentError, match=message):
        rules.check(config, _TEAMS, _fits)


@pytest.mark.parametrize('name', sorted(rules.PRESETS))
def test_shipped_presets_fit_every_number_of_entrants(name):
    for count in (2, 3, 4, 5, 6, 7, 8, 9, 12, 16, 17, 24, 33):
        preset = rules.preset_config(name)
        config = rules.check(
            {**preset, 'name': name, 'seed': 1, 'entrants': _builtins(count)}, _TEAMS
        )
        view, _ = _play_out(config, seed=count)
        assert sorted(view['ranking']) == list(range(count))


def test_a_shipped_preset_fits_its_rounds_and_an_edited_one_refuses():
    preset = rules.preset_config('swiss_16')
    config = {**preset, 'name': 'Tiny', 'seed': 1, 'entrants': _builtins(3)}
    assert rules.check(config, _TEAMS)['stages'][0]['rounds'] == 2
    assert rules.check({**config, 'entrants': _builtins(16)}, _TEAMS)['stages'][0]['rounds'] == 5
    # Stages that differ from the preset are the user's own, and too many rounds name the reason.
    edited = {**config, 'stages': [{'format': 'swiss', 'name': 'Swiss', 'rounds': 4}]}
    with pytest.raises(rules.TournamentError, match='without rematches'):
        rules.check(edited, _TEAMS)
    phase = rules.check(
        {**rules.preset_config('league_phase'), 'name': 'x', 'seed': 1, 'entrants': _builtins(5)},
        _TEAMS,
    )
    assert phase['stages'][0]['advance'] == 4
    euro = rules.check(
        {**rules.preset_config('euro'), 'name': 'x', 'seed': 1, 'entrants': _builtins(2)}, _TEAMS
    )
    assert euro['stages'][0]['group_size'] == 2 and euro['stages'][0]['best_position'] is None


def test_a_tie_without_a_played_match_has_no_score():
    config = _config([{'format': 'knockout', 'legs': 2, 'settle': ['lots']}], 4)
    tie = rules.evaluate(config, {})['stages'][0]['rounds'][0]['fixtures'][0]
    assert tie['state'] == 'ready' and tie['score'] is None
    first = tie['matches'][0]
    results = {first: {'score': [2, 1]}}
    tie = rules.evaluate(config, results)['stages'][0]['rounds'][0]['fixtures'][0]
    assert tie['state'] == 'ready' and sorted(tie['score']) == [1, 2]


def test_entrant_names_repeat_with_a_number():
    config = _config([{'format': 'league'}], 2)
    assert [e['name'] for e in config['entrants']] == ['Built-in AI 0.00', 'Built-in AI 0.50']
    entrants = rules.check_entrants([{'kind': 'builtin'}, {'kind': 'builtin'}], _TEAMS)
    assert [e['name'] for e in entrants] == ['Built-in AI', 'Built-in AI 2']


def test_a_team_enters_more_than_once_under_names_of_its_own():
    entrants = rules.check_entrants(
        [
            {'kind': 'team', 'team': 'reds'},
            {'kind': 'team', 'team': 'reds'},
            {'kind': 'team', 'team': 'reds', 'name': 'Reds B'},
            {'kind': 'team', 'team': 'blues'},
        ],
        _TEAMS,
        {'reds': 1620.0},
    )
    assert [e['name'] for e in entrants] == ['Reds', 'Reds 2', 'Reds B', 'Blues']
    # Every entrant of the team plays the team and shares its rating.
    assert [e['team'] for e in entrants[:3]] == ['reds'] * 3
    assert [e['key'] for e in entrants[:3]] == ['reds'] * 3
    assert [e['rating'] for e in entrants] == [1620.0, 1620.0, 1620.0, rules.BASE_RATING]
    # A made name steps around a given one, wherever the given one stands.
    entrants = rules.check_entrants(
        [
            {'kind': 'team', 'team': 'reds'},
            {'kind': 'team', 'team': 'reds'},
            {'kind': 'person', 'name': 'REDS 2'},
        ],
        _TEAMS,
    )
    assert [e['name'] for e in entrants] == ['Reds', 'Reds 3', 'REDS 2']
    # The free name that the page proposes is the name that the rules would make.
    taken = {rules.name_key(name) for name in ('Reds', 'REDS 2')}
    assert rules.free_name('Reds', taken) == 'Reds 3'


def test_given_names_that_read_as_one_are_refused_in_both_languages():
    from cuju.render._text import messages as _messages

    with pytest.raises(rules.TournamentError) as caught:
        rules.check_entrants(
            [
                {'kind': 'team', 'team': 'reds', 'name': 'Rex  FC'},
                {'kind': 'builtin'},
                {'kind': 'person', 'name': '  rex fc '},
            ],
            _TEAMS,
        )
    error = caught.value
    assert str(error) == (
        'expected a name of its own for entrant 3, found rex fc, the name of entrant 1'
    )
    fields = _messages.error_fields(error)
    assert fields['error_id'] == 'server.tournament.name_taken'
    assert {key: str(value) for key, value in fields['error_values'].items()} == {
        'entrant': '3',
        'name': 'rex fc',
        'other': '1',
    }
    for code in ('en', 'pt'):
        messages = _shipped_language(code) if code == 'en' else _translation(code)
        text = messages['server.tournament.name_taken']
        assert _messages.placeholders(text) == {'entrant', 'name', 'other'}
    assert 'server.tournament.twice' not in _messages.MESSAGES


def test_entrant_names_agree_with_the_page():
    """The page's nameKey and freeName hold the same cases, in tests/web/tournament.mjs."""
    from pathlib import Path

    path = Path(__file__).parent / 'support' / 'entrant_names.json'
    cases = json.loads(path.read_text(encoding='utf-8'))
    for name, key in cases['keys']:
        assert rules.name_key(name) == key
    for base, taken, longest, name in cases['free']:
        assert rules.free_name(base, {rules.name_key(t) for t in taken}, longest) == name
    source = Path(rules.__file__).parents[1] / 'web' / 'js' / 'play/tournament-layout.js'
    assert 'export const NAME_LONGEST = 40;' in source.read_text(encoding='utf-8')
    with pytest.raises(rules.TournamentError, match='1 to 40 characters'):
        rules.check_entrants([{'kind': 'person', 'name': 'x' * 41}, {'kind': 'builtin'}], _TEAMS)


def test_two_entrants_of_one_team_meet_and_leave_its_rating():
    config = rules.check(
        {
            'seed': 3,
            'seeding': 'manual',
            'entrants': [
                {'kind': 'team', 'team': 'reds'},
                {'kind': 'team', 'team': 'reds'},
                {'kind': 'team', 'team': 'blues'},
            ],
            'stages': [{'format': 'league', 'scenario': '11_vs_11_kaggle'}],
        },
        _TEAMS,
        _fits,
    )
    view, _ = _play_out(config, score=lambda match: [2, 1])
    derby = [m for m in view['matches'] if {m['home'], m['away']} == {0, 1}]
    assert len(derby) == 1
    rows = {row['entrant']: row for row in view['stages'][0]['tables'][0]['rows']}
    # The table keeps the two entrants of one team apart, each with its own record.
    assert len(rows) == 3 and sum(row['played'] for row in rows.values()) == 6
    assert sorted(view['ranking']) == [0, 1, 2]
    table = {}
    rules.update_ratings(table, config['entrants'][0], config['entrants'][1], [2, 1])
    assert table == {}
    rules.update_ratings(table, config['entrants'][0], config['entrants'][2], [2, 1])
    assert table['reds']['rating'] > rules.BASE_RATING > table['blues']['rating']


def test_bracket_order_and_round_robin():
    assert rules.bracket_order(8) == [0, 7, 3, 4, 1, 6, 2, 5]
    for count in (2, 3, 6, 7):
        rounds = rules.round_robin(list(range(count)))
        pairs = [frozenset(p) for r in rounds for p in r if None not in p]
        assert len(pairs) == len(set(pairs)) == count * (count - 1) // 2
    assert rules.group_name(0) == 'A' and rules.group_name(26) == 'AA'


# The runner, with made up matches.


@pytest.fixture
def render_home(tmp_path, monkeypatch):
    monkeypatch.setenv(_home.HOME_VARIABLE, str(tmp_path / 'render'))
    return tmp_path / 'render'


def _fake_player(calls=None, fail=None):
    def player(match, teams, provenance, progress):
        if calls is not None:
            calls.append(match['key'])
        if fail and match['key'] in fail:
            raise RuntimeError('the policy of Reds failed, ValueError: no')
        progress(0.5)
        seed = match['seed']
        return {'score': [seed % 3, seed // 3 % 3], 'cards': [[0, 0], [0, 0]], 'match': None}

    return player


def _wait(predicate, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _builtin_config(count=4, **options):
    return {
        'name': 'Spring cup',
        'seed': 9,
        'entrants': _builtins(count),
        'stages': [
            {'format': 'knockout', 'scenario': 'academy_empty_goal_close', 'settle': ['lots']}
        ],
        **options,
    }


def test_runner_plays_a_tournament_and_resumes_after_a_restart(render_home):
    calls = []
    first = runner.Tournaments(player=_fake_player(calls), start=False)
    entry = first.create(_builtin_config(8))
    identifier = entry['id']
    # One tick starts the matches it may, one at a time by default.
    first.tick()
    assert _wait(lambda: first.get(identifier)['played'] == 1)
    first.close()
    stored = json.loads((runner.folder() / f'{identifier}.json').read_text(encoding='utf-8'))
    assert len(stored['results']) == 1
    # A half written file is left from a stop, and the next start removes it.
    (runner.folder() / f'{identifier}.json.part').write_text('{', encoding='utf-8')
    calls.clear()
    second = runner.Tournaments(player=_fake_player(calls), start=False, interval=0.01)
    assert not (runner.folder() / f'{identifier}.json.part').exists()
    assert second.run(identifier, report=lambda line: None) == 'done'
    done = second.get(identifier)
    assert done['state'] == 'done' and done['champion']
    assert len(calls) == 6 and done['played'] == 7
    view = rules.evaluate(stored['config'], {})
    expected = {m['key']: m['seed'] for m in view['matches']}
    assert all(expected[m['key']] == m['seed'] for m in done['matches'] if m['key'] in expected)
    second.close()
    assert runner.ratings()


def test_runner_runs_several_matches_at_once(render_home):
    gate = threading.Event()
    active, peak = [0], [0]
    lock = threading.Lock()

    def player(match, teams, provenance, progress):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        gate.wait(5)
        with lock:
            active[0] -= 1
        return {'score': [1, 0]}

    cups = runner.Tournaments(player=player, start=False)
    entry = cups.create(_builtin_config(8, concurrency=3))
    cups.tick()
    assert _wait(lambda: peak[0] == 3)
    cups.tick()
    assert peak[0] == 3
    gate.set()
    assert _wait(lambda: cups.get(entry['id'])['played'] >= 3)
    cups.close()


def test_runner_plays_on_past_a_failed_match_and_resumes(render_home):
    cups = runner.Tournaments(player=_fake_player(fail={'0/w4-1/1'}), start=False)
    entry = cups.create(_builtin_config(4))
    # The other semi-final does not depend on the failed one, so it plays before the stop.
    assert cups.run(entry['id'], report=lambda line: None) == 'stopped'
    view = cups.get(entry['id'])
    assert view['error'].startswith('Semi-final 1 failed, the policy of Reds failed')
    assert view['failed'] == 1
    states = {m['key']: m['state'] for m in view['matches']}
    assert states == {'0/w4-1/1': 'failed', '0/w4-2/1': 'done'}
    # A stopped tournament is free for another process, such as the command line.
    assert not (runner.folder() / f'{entry["id"]}.lock').exists()
    cups._player = _fake_player()
    cups.resume(entry['id'])
    assert cups.get(entry['id'])['failed'] == 0
    assert cups.run(entry['id'], report=lambda line: None) == 'done'
    cups.close()


def test_an_award_after_a_failure_runs_the_tournament_on(render_home):
    cups = runner.Tournaments(player=_fake_player(fail={'0/w4-1/1'}), start=False)
    entry = cups.create(_builtin_config(4))
    assert cups.run(entry['id'], report=lambda line: None) == 'stopped'
    view = cups.forfeit(entry['id'], '0/w4-1/1', 'away')
    assert view['state'] == 'running' and view['error'] is None and view['failed'] == 0
    assert cups.run(entry['id'], report=lambda line: None) == 'done'
    cups.close()


def test_failed_matches_wait_while_people_play_theirs(render_home):
    config = _builtin_config(4, seeding='manual')
    config['entrants'] = [{'kind': 'person', 'name': 'Ana'}, *_builtins(3)]
    cups = runner.Tournaments(player=_fake_player(fail={'0/w4-2/1'}), start=False)
    entry = cups.create(config)
    lines = []
    assert cups.run(entry['id'], report=lines.append) == 'people'
    assert 'Semi-final 2 failed' in lines[-1]
    view = cups.get(entry['id'])
    assert view['state'] == 'running' and view['people_waiting'] == 1 and view['failed'] == 1
    # Resume retries a failed match of a running tournament too.
    cups._player = _fake_player()
    cups.resume(entry['id'])
    assert cups.run(entry['id'], report=lambda line: None) == 'people'
    assert cups.get(entry['id'])['failed'] == 0
    cups.close()


def test_tournament_identifiers_differ_from_team_identifiers(render_home):
    cups = runner.Tournaments(player=_fake_player(), start=False)
    entry = cups.create(_builtin_config(2))
    assert entry['id'].startswith('cup-')
    cups.close()
    # A tournament saved before, with the prefix that teams also use, still loads and plays.
    stored = json.loads((runner.folder() / f'{entry["id"]}.json').read_text(encoding='utf-8'))
    stored['id'] = 't-20261101-120000-ab12'
    (runner.folder() / f'{stored["id"]}.json').write_text(json.dumps(stored), encoding='utf-8')
    again = runner.Tournaments(player=_fake_player(), start=False, interval=0.01)
    assert stored['id'] in [item['id'] for item in again.entries()]
    assert again.run(stored['id'], report=lambda line: None) == 'done'
    again.close()


def test_agent_matches_carry_the_names_of_their_entrants(render_home):
    seen = []

    def player(match, teams, provenance, progress):
        seen.append(provenance)
        return {'score': [1, 0]}

    cups = runner.Tournaments(player=player, start=False, interval=0.01)
    config = _builtin_config(2)
    config['entrants'] = [{'kind': 'builtin', 'ability': 0.8}, {'kind': 'builtin', 'name': 'Rex'}]
    entry = cups.create(config)
    assert cups.run(entry['id'], report=lambda line: None) == 'done'
    cups.close()
    assert sorted(seen[0]['names']) == ['Built-in AI 0.80', 'Rex']


def test_cancel_refuses_a_tournament_that_has_ended(render_home):
    cups = runner.Tournaments(player=_fake_player(), start=False, interval=0.01)
    entry = cups.create(_builtin_config(2))
    assert cups.run(entry['id'], report=lambda line: None) == 'done'
    with pytest.raises(cuju_errors().ArgumentError, match='found it done'):
        cups.cancel(entry['id'])
    cups.close()


def test_tables_name_no_tiebreak_before_any_match():
    config = _config([{'format': 'league'}], 4)
    table = rules.evaluate(config, {})['stages'][0]['tables'][0]['rows']
    assert all(row['tiebreak'] is None for row in table)
    view = rules.evaluate(config, {'0/1-1': {'score': [0, 0]}})
    rows = view['stages'][0]['tables'][0]['rows']
    assert any(row['tiebreak'] for row in rows)


def test_runner_skips_invalid_files_and_keeps_others(render_home):
    folder = runner.folder()
    (folder / 't-bad.json').write_text('[]', encoding='utf-8')
    (folder / 't-worse.json').write_text('{"id": "t-worse", "state": "running"}', encoding='utf-8')
    cups = runner.Tournaments(player=_fake_player(), start=False)
    good = cups.create(_builtin_config(2))
    cups.close()
    again = runner.Tournaments(player=_fake_player(), start=False)
    assert [entry['id'] for entry in again.entries()] == [good['id']]
    again.close()


def test_a_tournament_file_dropped_into_the_folder_waits_stopped(render_home):
    """A running file that this install did not write plays nothing until a person resumes it."""
    calls = []
    cups = runner.Tournaments(player=_fake_player(calls), start=False)
    own = cups.create(_builtin_config(4))
    cups.close()
    folder = runner.folder()
    stored = json.loads((folder / f'{own["id"]}.json').read_text(encoding='utf-8'))
    assert isinstance(stored.pop('seal'), str)
    dropped = {**stored, 'id': 'cup-20261111-000000-beef'}
    dropped['config'] = {**stored['config'], 'concurrency': 1000}
    (folder / f'{dropped["id"]}.json').write_text(json.dumps(dropped), encoding='utf-8')
    # A file of this install that someone edited by hand counts as dropped as well.
    edited = {**stored, 'id': 'cup-20261111-000000-cafe', 'seal': '0' * 64}
    (folder / f'{edited["id"]}.json').write_text(json.dumps(edited), encoding='utf-8')
    again = runner.Tournaments(player=_fake_player(calls), start=False, interval=0.01)
    states = {entry['id']: entry for entry in again.entries()}
    assert states[own['id']]['state'] == 'running'
    for identifier in (dropped['id'], edited['id']):
        assert states[identifier]['state'] == 'stopped'
        assert states[identifier]['error_id'] == 'server.tournament.foreign'
    assert again.get(dropped['id'])['config']['concurrency'] == rules.MAX_CONCURRENCY
    again.tick()
    assert _wait(lambda: again.get(own['id'])['played'] >= 1)
    time.sleep(0.2)
    assert all(again.get(i)['played'] == 0 for i in (dropped['id'], edited['id']))
    # Resuming it is the person's choice, and the file it writes then carries the seal.
    assert again.resume(dropped['id'])['state'] == 'running'
    again.close()
    third = runner.Tournaments(player=_fake_player(calls), start=False, interval=0.01)
    assert third.get(dropped['id'])['state'] == 'running'
    assert third.run(dropped['id'], report=lambda line: None) == 'done'
    third.close()


def test_cancel_forfeit_and_remove(render_home):
    cups = runner.Tournaments(player=_fake_player(), start=False)
    entry = cups.create(_builtin_config(4))
    view = cups.forfeit(entry['id'], '0/w4-1/1', 'away')
    match = next(m for m in view['matches'] if m['key'] == '0/w4-1/1')
    assert match['result']['score'] == [0, 3] and match['result']['forfeit']
    # An awarded match was never played, so the ratings stay as they are.
    assert runner.ratings() == {}
    assert not (runner.folder() / 'ratings.json').exists()
    with pytest.raises(cuju_errors().ArgumentError):
        cups.remove(entry['id'])
    assert cups.cancel(entry['id'])
    assert cups.get(entry['id'])['state'] == 'cancelled'
    assert cups.remove(entry['id'])
    assert cups.get(entry['id']) is None
    cups.close()


def cuju_errors():
    import cuju.errors

    return cuju.errors


def test_a_second_process_cannot_run_a_claimed_tournament(render_home):
    cups = runner.Tournaments(player=_fake_player(), start=False)
    entry = cups.create(_builtin_config(4))
    lock = runner.folder() / f'{entry["id"]}.lock'
    # The parent of the test process stays alive while the test runs.
    lock.write_text(str(os.getppid()), encoding='utf-8')
    cups.tick()
    assert cups.get(entry['id'])['played'] == 0
    assert cups.get(entry['id'])['owner'] == os.getppid()
    # A cancel from here leaves a marker for the process that runs it.
    assert cups.cancel(entry['id'])
    assert (runner.folder() / f'{entry["id"]}.cancel').exists()
    lock.write_text('999999999', encoding='utf-8')
    cups.tick()
    assert cups.get(entry['id'])['state'] == 'cancelled'
    cups.close()


def test_awards_and_resumes_reach_the_process_that_runs_the_tournament(render_home, monkeypatch):
    cups = runner.Tournaments(player=_fake_player(fail={'0/w4-1/1'}), start=False)
    identifier = cups.create(_builtin_config(4))['id']
    assert cups.run(identifier, report=lambda line: None) == 'stopped'
    cups.close()
    # Another live process holds the tournament, which a second instance stands in for here.
    (runner.folder() / f'{identifier}.lock').write_text(str(os.getppid()), encoding='utf-8')
    owner = runner.Tournaments(player=_fake_player(), start=False)
    owner._owned.add(identifier)
    asker = runner.Tournaments(start=False)
    # A wrong key reads as such at once, before the other process is asked.
    with pytest.raises(cuju_errors().ArgumentError, match='still to play'):
        asker.forfeit(identifier, 'nothing', 'home')
    stop = threading.Event()

    def answer():
        while not stop.is_set():
            owner._scan()
            time.sleep(0.02)

    thread = threading.Thread(target=answer)
    thread.start()
    try:
        assert asker.resume(identifier)['state'] == 'running'
        view = asker.forfeit(identifier, '0/w4-1/1', 'away')
        match = next(m for m in view['matches'] if m['key'] == '0/w4-1/1')
        assert match['result']['forfeit'] and match['result']['score'] == [0, 3]
        assert owner.get(identifier)['played'] == 2
    finally:
        stop.set()
        thread.join()
    # A process that never answers leaves the change undone and names the route to use.
    monkeypatch.setattr(runner, '_ASK_SECONDS', 0.2)
    final = next(m for m in asker.get(identifier)['matches'] if m['state'] == 'ready')
    with pytest.raises(cuju_errors().ArgumentError, match='did not answer') as caught:
        asker.forfeit(identifier, final['key'], 'home')
    assert f'POST /api/tournaments/{identifier}/forfeit' in str(caught.value)
    assert not list(runner.folder().glob('*.request'))
    owner.close()
    asker.close()


class _FakeGames:
    def __init__(self):
        self.started = []
        self.entry = None

    def start(self, scenario, humans, ability, seed, record, teams, length=None, tournament=None):
        self.started.append((scenario, list(humans), list(teams), seed, length, tournament))
        self.entry = {'id': f'g-{len(self.started)}', 'state': 'playing', 'score': [0, 0]}
        return dict(self.entry)

    def current(self):
        return None if self.entry is None else dict(self.entry)


def test_people_play_their_matches_as_games(render_home, monkeypatch):
    games = _FakeGames()
    cups = runner.Tournaments(games, player=_fake_player(), start=False)
    config = _builtin_config(2)
    config['entrants'] = [{'kind': 'person', 'name': 'Ana'}, {'kind': 'builtin', 'ability': 0.3}]
    entry = cups.create(config)
    cups.tick()
    view = cups.get(entry['id'])
    match = view['matches'][0]
    assert match['state'] == 'person' and match['persons'] == [True, False]
    game = cups.play(entry['id'], match['key'])
    assert game['id'] == 'g-1'
    scenario, humans, teams, seed, _, tournament = games.started[0]
    assert (scenario, humans, teams, seed) == (
        'academy_empty_goal_close',
        [True, False],
        ['builtin', 'builtin'],
        match['seed'],
    )
    assert tournament['names'] == ['Ana', 'Built-in AI 0.30'] and tournament['key'] == match['key']
    assert cups.get(entry['id'])['matches'][0]['state'] == 'playing'
    # A game quit before its end leaves the match to be played again.
    games.entry.update(state='ended', ending='quit', match='m-x')
    cups.tick()
    after = cups.get(entry['id'])['matches'][0]
    assert after['state'] == 'person' and 'before full time' in after['note']
    cups.play(entry['id'], match['key'])
    games.entry.update(state='ended', ending='episode', match='m-y')
    monkeypatch.setattr(
        runner,
        'recording_result',
        lambda m: {'score': [1, 0], 'cards': [[0, 0], [0, 0]], 'match': m},
    )
    cups.tick()
    done = cups.get(entry['id'])
    assert done['state'] == 'done' and done['champion'] == 'Ana'
    assert done['matches'][0]['result']['match'] == 'm-y'
    cups.close()


def test_presets_of_the_user_are_saved_and_removed(render_home):
    preset = {'title': 'Mine', 'stages': [{'format': 'swiss', 'rounds': 3}]}
    saved = runner.save_preset('mine', preset)
    assert saved['title'] == 'Mine' and not saved['shipped']
    assert runner.presets()['mine']['stages'] == preset['stages']
    assert runner.presets()['world_cup']['shipped']
    with pytest.raises(cuju_errors().ArgumentError):
        runner.save_preset('world_cup', preset)
    with pytest.raises(cuju_errors().ArgumentError):
        runner.save_preset('bad', {'title': 'x', 'stages': [{'format': 'knockout', 'cup': 1}]})
    assert runner.remove_preset('mine') and not runner.remove_preset('mine')


# The server and the command line.


def _request(address, method, path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        address + path,
        data=data,
        method=method,
        headers={'Content-Type': 'application/json', **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read()
            return response.status, json.loads(text) if text else None
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b'null')


def test_server_routes_create_list_show_and_check(render_home):
    import http.server

    cups = runner.Tournaments(player=_fake_player(), start=False)
    server = http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests(), None, cups)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        status, presets = _request(address, 'GET', '/api/tournaments/presets')
        assert status == 200 and 'world_cup' in presets and 'swiss_16' in presets
        status, preview = _request(address, 'POST', '/api/tournaments/check', _builtin_config(4))
        assert status == 200 and preview['matches'] == 2
        assert preview['config']['stages'][0]['bracket_size'] == 4
        status, error = _request(
            address,
            'POST',
            '/api/tournaments/check',
            {**_builtin_config(4), 'stages': [{'format': 'swiss', 'rounds': 9}]},
        )
        assert status == 400 and 'rematches' in error['error']
        status, entry = _request(
            address, 'POST', '/api/tournaments', {'config': _builtin_config(4)}
        )
        assert status == 201 and entry['state'] == 'running'
        status, listed = _request(address, 'GET', '/api/tournaments')
        assert [item['id'] for item in listed] == [entry['id']]
        status, full = _request(address, 'GET', f'/api/tournaments/{entry["id"]}')
        assert status == 200 and len(full['matches']) == 2
        assert full['stages_view'][0]['rounds'][0]['name'] == 'Semi-finals'
        # Another site's page cannot create or cancel a tournament.
        status, _ = _request(
            address,
            'POST',
            '/api/tournaments',
            {'config': _builtin_config(4)},
            {'Origin': 'http://example.com'},
        )
        assert status == 403
        status, _ = _request(address, 'GET', '/api/tournaments', headers={'Host': 'example.com'})
        assert status == 403
        status, awarded = _request(
            address,
            'POST',
            f'/api/tournaments/{entry["id"]}/forfeit',
            {'key': '0/w4-1/1', 'winner': 'home'},
        )
        assert status == 200
        match = next(m for m in awarded['matches'] if m['key'] == '0/w4-1/1')
        assert match['result']['forfeit'] and match['result']['score'] == [3, 0]
        status, error = _request(address, 'POST', f'/api/tournaments/{entry["id"]}/resume', {})
        assert status == 400 and 'stopped tournament' in error['error']
        status, _ = _request(address, 'POST', f'/api/tournaments/{entry["id"]}/cancel', {})
        assert status == 200
        status, _ = _request(address, 'POST', '/api/tournaments/t-none/cancel', {})
        assert status == 404
        status, _ = _request(
            address,
            'POST',
            '/api/tournaments/presets/mine',
            {'preset': {'title': 'Mine', 'stages': [{'format': 'league'}]}},
        )
        assert status == 201
        status, _ = _request(address, 'DELETE', '/api/tournaments/presets/mine')
        assert status == 204
        status, _ = _request(address, 'DELETE', f'/api/tournaments/{entry["id"]}')
        assert status == 204
    finally:
        server.shutdown()
        server.server_close()
        cups.close()


def test_command_line_makes_lists_shows_and_cancels(render_home, capsys, monkeypatch):
    from cuju.render.__main__ import main

    assert (
        main(
            [
                'tournament',
                'new',
                '--preset',
                'quick_cup',
                '--name',
                'Friday cup',
                '--seed',
                '4',
                '--builtin',
                '0.2',
                '--builtin',
                '0.9',
                '--person',
                'Ana',
                '--builtin',
                'any',
                '--scenario',
                'academy_empty_goal_close',
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    identifier = output.split()[1]
    assert main(['tournament', 'list']) == 0
    assert 'Friday cup' in capsys.readouterr().out
    assert main(['tournament', 'show', identifier]) == 0
    shown = capsys.readouterr().out
    assert 'Semi-finals' in shown and 'Ana' in shown
    stored = json.loads((runner.folder() / f'{identifier}.json').read_text(encoding='utf-8'))
    assert [e['kind'] for e in stored['config']['entrants']] == [
        'builtin',
        'builtin',
        'person',
        'builtin',
    ]
    assert stored['config']['stages'][0]['length'] == 600
    monkeypatch.setattr(runner.Tournaments, '_play_process', lambda self, *a: {'score': [2, 1]})
    assert main(['tournament', 'run', identifier]) == 0
    assert 'waits for people' in capsys.readouterr().out
    assert main(['tournament', 'cancel', identifier]) == 0
    assert main(['tournament', 'presets']) == 0
    assert 'world_cup' in capsys.readouterr().out
    # A shipped preset fits its rounds to two entrants.
    assert (
        main(['tournament', 'new', '--preset', 'swiss_16', '--builtin', '0.1', '--builtin', '0.2'])
        == 0
    )
    capsys.readouterr()


def test_command_line_refuses_with_one_line(render_home, capsys):
    from cuju.render.__main__ import main

    three = ['--builtin', '0.1', '--builtin', '0.2', '--builtin', '0.3']
    for arguments, message in (
        (['--preset', 'nonexistent', *three], 'expected a preset from'),
        (['--preset', 'swiss_16', '--rounds', '5', *three], 'expected --rounds from 1 to 2'),
        (['--preset', 'quick_cup', '--rounds', '3', *three], 'expected a Swiss or ladder stage'),
        (['--preset', 'quick_cup', '--builtin', 'strong', *three], 'expected --builtin'),
    ):
        assert main(['tournament', 'new', *arguments]) == 1
        error = capsys.readouterr().err
        assert error.startswith(f'cuju render: {message}') and error.count('\n') == 1, error
    assert main(['tournament', 'new', '--preset', 'swiss_16', '--rounds', '2', *three]) == 0
    assert 'created cup-' in capsys.readouterr().out


def test_command_line_checks_deletes_rates_and_prints_json(render_home, capsys, monkeypatch):
    from cuju.render.__main__ import main

    monkeypatch.setattr(runner.Tournaments, '_play_process', lambda self, *a: {'score': [2, 1]})
    four = ['--builtin', '0.1', '--builtin', '0.2', '--builtin', '0.3', '--builtin', '0.4']
    scenario = ['--scenario', 'academy_empty_goal_close']
    assert main(['tournament', 'check', '--preset', 'world_cup', *four, *scenario]) == 0
    checked = capsys.readouterr().out
    assert '4 entrants' in checked and '1. Group stage, groups' in checked
    assert 'Group A, Built-in AI' in checked
    assert main(['tournament', 'check', '--preset', 'quick_cup', '--json', *four]) == 0
    assert json.loads(capsys.readouterr().out)['matches'] == 2
    assert main(['tournament', 'list']) == 0
    assert capsys.readouterr().out == ''
    assert main(['tournament', 'ratings']) == 0
    assert 'no ratings yet' in capsys.readouterr().out
    arguments = ['tournament', 'new', '--preset', 'swiss_16', '--seed', '2', *four, *scenario]
    assert main([*arguments, '--json', '--run']) == 0
    ran = json.loads(capsys.readouterr().out)
    assert ran['outcome'] == 'done' and ran['tournament']['state'] == 'done'
    identifier = ran['tournament']['id']
    assert main(['tournament', 'show', identifier]) == 0
    shown = capsys.readouterr().out
    assert 'Swiss, finished' in shown and 'Swiss, swiss' not in shown
    assert 'Buchholz Byes' in shown and 'Final ranking' in shown and '  1. ' in shown
    assert main(['tournament', 'ratings', '--json']) == 0
    assert len(json.loads(capsys.readouterr().out)) == 4
    assert main(['tournament', 'ratings']) == 0
    assert 'Built-in AI 0.10' in capsys.readouterr().out
    assert main(['tournament', 'cancel', identifier]) == 1
    assert 'found it done' in capsys.readouterr().err
    assert main(['tournament', 'presets', '--json']) == 0
    assert 'world_cup' in json.loads(capsys.readouterr().out)
    assert main(['tournament', 'delete', identifier]) == 0
    assert f'deleted {identifier}' in capsys.readouterr().out
    assert main(['tournament', 'list', '--json']) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_show_names_byes_replays_and_deciders():
    from cuju.render._tournaments.tournament_cli import describe

    config = _config(
        [{'format': 'knockout', 'settle': ['replay', 'decider', 'lots']}], 2, seeding='manual'
    )
    results = {'0/w2-1/1': {'score': [1, 1]}, '0/w2-1/r1': {'score': [0, 0]}}
    results['0/w2-1/d1'] = {'score': [2, 0]}
    results['0/w2-1/d2'] = {'score': [1, 0]}
    view = rules.evaluate(config, results)
    entry = {
        'name': 'Cup',
        'id': 'cup-x',
        'state': 'done',
        'seed': 11,
        'played': 4,
        'scheduled': 4,
        'error': None,
        'config': config,
        'stages_view': view['stages'],
        'champion': 'x',
        'matches': [{**m, 'state': 'done'} for m in view['matches']],
        'ranking': view['ranking'],
    }
    text = '\n'.join(describe(entry))
    assert '1 to 1, after deciding matches, replay 0 to 0, deciding matches 2 to 1' in text
    swiss = _config([{'format': 'swiss', 'rounds': 1}], 3)
    view = rules.evaluate(swiss, {})
    entry.update(config=swiss, stages_view=view['stages'], matches=[], ranking=None)
    text = '\n'.join(describe(entry))
    bye = swiss['entrants'][view['stages'][0]['rounds'][0]['bye']]['name']
    assert f'Round 1, bye for {bye}' in text


def test_command_line_awards_resumes_and_prints_json(render_home, capsys, monkeypatch):
    from cuju.render.__main__ import main

    failing = [True]

    def play(self, match, *rest):
        if failing[0] and match['key'] == '0/w4-1/1':
            raise RuntimeError('the policy of Reds failed')
        return {'score': [2, 1]}

    monkeypatch.setattr(runner.Tournaments, '_play_process', play)
    arguments = ['tournament', 'new', '--preset', 'quick_cup', '--seed', '4']
    arguments += ['--builtin', '0.1', '--builtin', '0.2', '--builtin', '0.3', '--builtin', '0.4']
    assert main([*arguments, '--scenario', 'academy_empty_goal_close']) == 0
    identifier = capsys.readouterr().out.split()[1]
    assert main(['tournament', 'show', identifier]) == 0
    shown = capsys.readouterr().out
    assert 'not played' in shown and ' to ' not in shown.split('Matches to play')[0]
    assert '0/w4-1/1  Semi-final 1' in shown and 'in the queue' in shown
    # The second semi-final plays although the first fails.
    assert main(['tournament', 'run', identifier]) == 1
    assert 'award the failed matches' in capsys.readouterr().out
    assert main(['tournament', 'show', identifier, '--json']) == 0
    view = json.loads(capsys.readouterr().out)
    assert view['state'] == 'stopped' and view['failed'] == 1 and view['played'] == 1
    assert main(['tournament', 'show', identifier]) == 0
    assert 'failed, the policy of Reds failed' in capsys.readouterr().out
    # Resume retries the failed match, which fails again.
    assert main(['tournament', 'resume', identifier]) == 0
    assert f'resumed {identifier}' in capsys.readouterr().out
    assert main(['tournament', 'run', identifier]) == 1
    capsys.readouterr()
    with pytest.raises(SystemExit):
        main(['tournament', 'forfeit', identifier, '--winner', 'away'])
    capsys.readouterr()
    assert main(['tournament', 'award', identifier, '--match', '0/w4-1/1', '--winner', 'away']) == 0
    output = capsys.readouterr().out
    assert 'awarded Semi-final 1 to' in output and 'the tournament runs' in output
    failing[0] = False
    assert main(['tournament', 'run', identifier]) == 0
    capsys.readouterr()
    assert main(['tournament', 'show', identifier]) == 0
    assert '0 to 3, awarded' in capsys.readouterr().out
    assert main(['tournament', 'list', '--json']) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]['id'] == identifier and listed[0]['state'] == 'done'
    assert main(['tournament', 'resume', identifier]) == 1
    assert 'expected a stopped tournament' in capsys.readouterr().err


# Real matches.


def test_length_scenario_shortens_a_match(render_home):
    from cuju.render._playing import play as _play

    path = _play.play('builtin', 'builtin', '5_vs_5', seed=3, length=60)
    header = _recording.read_header(path)
    # GRF: a match of 60 steps takes 61 calls of step, so it has 62 frames with the first.
    assert header['frame_count'] == 62
    assert header['provenance']['length'] == 60
    assert header['scenario'] == '5_vs_5'
    result = runner.recording_result(path.stem)
    assert result['score'] == _library.details(path.stem)['score']
    assert runner.scenario_duration('5_vs_5') == 3000


def test_a_tiny_knockout_of_real_academy_matches(render_home):
    cups = runner.Tournaments(start=False, interval=0.1)
    config = _builtin_config(4, concurrency=2)
    config['entrants'] = [
        {'kind': 'builtin', 'ability': 1.0},
        {'kind': 'builtin', 'ability': 0.6},
        {'kind': 'builtin', 'ability': 0.3},
        {'kind': 'builtin', 'ability': 0.05},
    ]
    entry = cups.create(config)
    assert cups.run(entry['id'], report=lambda line: None) == 'done'
    done = cups.get(entry['id'])
    cups.close()
    assert done['state'] == 'done' and done['champion']
    played = [m for m in done['matches'] if m['result']['match']]
    assert len(played) == 3
    for match in played:
        header = _recording.read_header(_library.path_of(match['result']['match']))
        provenance = header['provenance']
        assert provenance['seed'] == match['seed']
        assert provenance['tournament']['key'] == match['key']
        assert header['title'].startswith('Spring cup, ')
        assert provenance['ability'] == match['ability']
        assert _library.details(match['result']['match'])['score'] == match['result']['score']
        # The recording names its sides as the tournament's entrants, Built-in AI 0.60 and so on.
        names = [done['config']['entrants'][match[side]]['name'] for side in ('home', 'away')]
        assert provenance['tournament']['names'] == names
        assert [team['name'] for team in header['teams']] == names
        assert header['title'].endswith(f'{names[0]} against {names[1]}')


def test_a_failing_team_is_named_in_the_tournament_error(render_home, tmp_path):
    from cuju.render._registry import teams as _teams

    folder = tmp_path / 'crash'
    folder.mkdir()
    (folder / 'main.py').write_text(
        'def agent(obs):\n    raise RuntimeError("crash on purpose")\n', encoding='utf-8'
    )
    team = _teams.add_folder(folder, 'Crasher', '5v5')
    cups = runner.Tournaments(start=False, interval=0.1)
    config = _builtin_config(2, seeding='manual')
    config['entrants'] = [{'kind': 'team', 'team': team['id'], 'name': 'Red crash'}, *_builtins(1)]
    config['stages'] = [{'format': 'knockout', 'scenario': '5_vs_5', 'length': 50}]
    entry = cups.create(config)
    assert cups.run(entry['id'], report=lambda line: None) == 'stopped'
    error = cups.get(entry['id'])['error']
    cups.close()
    # The failure names the team as its entrant, Red crash, and not by its name in the registry.
    assert error.startswith('Final failed, the policy of Red crash failed, RuntimeError: crash')


# The names and labels that the rules make, which the page shows in its own language.


def _label_ids(value):
    """Returns the ids of a label and of the labels among its values, outermost first."""
    if not isinstance(value, dict) or 'id' not in value:
        return []
    found = [value['id']]
    for inner in value['values'].values():
        found += _label_ids(inner)
    return found


def test_generated_names_travel_as_labels_and_given_names_as_text():
    from cuju.render._text import messages as _messages

    config = rules.check(
        {
            'seed': 4,
            'entrants': [
                {'kind': 'builtin', 'ability': 0.5},
                {'kind': 'builtin', 'ability': 0.5},
                {'kind': 'builtin'},
                {'kind': 'builtin', 'name': 'Rex'},
                {'kind': 'team', 'team': 'reds'},
            ],
            'stages': [
                {'format': 'groups', 'name': 'Group stage', 'group_size': 3, 'qualifiers': 1},
                {'format': 'knockout', 'name': 'Our final'},
            ],
        },
        _TEAMS,
    )
    # The English text stays as it was, for the command line and for older readers.
    assert config['name'] == 'Tournament'
    assert config['name_id'] == 'server.tournament.label.tournament'
    entrants = config['entrants']
    assert [e['name'] for e in entrants] == [
        'Built-in AI 0.50',
        'Built-in AI 0.50 2',
        'Built-in AI',
        'Rex',
        'Reds',
    ]
    assert entrants[0]['name_id'] == 'server.tournament.label.builtin_ability'
    assert entrants[0]['name_values'] == {'ability': '0.50'}
    assert _label_ids(rules.label_of(entrants[1])) == [
        'server.tournament.label.numbered',
        'server.tournament.label.builtin_ability',
    ]
    # A name that a person gave, and the name of a registered team, stay plain text.
    assert 'name_id' not in entrants[3] and 'name_id' not in entrants[4]
    stages = config['stages']
    assert stages[0]['name_id'] == 'server.tournament.label.stage.group_stage'
    assert stages[1]['name'] == 'Our final' and 'name_id' not in stages[1]
    view = rules.evaluate(config, {})
    groups, knockout = view['stages']
    assert groups['name_id'] == 'server.tournament.label.stage.group_stage'
    table = groups['tables'][0]
    assert (table['name'], table['name_id'], table['name_values']) == (
        'Group A',
        'server.tournament.label.group',
        {'group': 'A'},
    )
    first = groups['rounds'][0]
    assert (first['name'], first['name_id']) == ('Matchday 1', 'server.tournament.label.matchday')
    match = view['matches'][0]
    assert match['label'] == 'Group A, matchday 1'
    assert match['label_id'] == 'server.tournament.label.group_matchday'
    assert 'name_id' not in knockout
    # Every label is a known message whose text its values give.
    for holder, field in [(entrants[1], 'name'), (table, 'name'), (match, 'label')]:
        found = rules.label_of(holder, field)
        assert _messages.valid_label(found)
        assert _messages.text(found['id'], **found['values']) == holder[field]


def test_knockout_labels_name_rounds_ties_legs_and_sides_still_to_come():
    config = _config(
        [{'format': 'knockout', 'third_place': True, 'legs': 2, 'settle': ['lots']}], 8
    )
    view = rules.evaluate(config, {})
    rounds = view['stages'][0]['rounds']
    assert [r['name'] for r in rounds] == [
        'Quarter-finals',
        'Semi-finals',
        'Final',
        'Third place match',
    ]
    assert [r['name_id'].rsplit('.', 1)[1] for r in rounds] == [
        'quarter_finals',
        'semi_finals',
        'final',
        'third_place',
    ]
    semi = rounds[1]['fixtures'][0]
    assert semi['label'] == 'Semi-final 1' and semi['label_values'] == {'number': '1'}
    side = semi['home']
    assert side['from'] == 'Winner of Quarter-final 1'
    assert _label_ids(rules.label_of(side, 'from')) == [
        'server.tournament.label.winner_of',
        'server.tournament.label.quarter_final',
    ]
    third = rounds[3]['fixtures'][0]
    assert third['home']['from_id'] == 'server.tournament.label.loser_of'
    leg = view['matches'][0]
    assert leg['label'] == 'Quarter-final 1, leg 1'
    assert _label_ids(rules.label_of(leg, 'label')) == [
        'server.tournament.label.leg',
        'server.tournament.label.quarter_final',
    ]


@pytest.mark.parametrize('stage', _FORMATS, ids=lambda stage: '-'.join(map(str, stage.values())))
def test_every_name_of_every_format_is_a_label_of_its_text(stage):
    from cuju.render._text import messages as _messages

    def same(holder, field):
        found = rules.label_of(holder, field)
        assert _messages.valid_label(found), holder[field]
        assert _messages.text(found['id'], **found['values']) == holder[field]

    config = _config([stage], 7)
    view, _ = _play_out(config)
    for part in view['stages']:
        same(part, 'name')
        for table in part['tables']:
            same(table, 'name')
        for round_ in part['rounds']:
            same(round_, 'name')
            for fixture in round_['fixtures']:
                if 'label' in fixture:
                    same(fixture, 'label')
    for match in view['matches']:
        same(match, 'label')


def test_a_refused_entrant_names_the_scenario_and_reason_as_values():
    def fits(entrant, scenario):
        if entrant['format'] == '5v5':
            return {
                'id': 'server.teams.scenario_format',
                'text': 'unused',
                'values': {'format': '5v5'},
            }
        return None

    with pytest.raises(rules.TournamentError) as caught:
        rules.check(
            {
                'name': 'Mixed',
                'seed': 1,
                'entrants': [{'kind': 'team', 'team': 'minis'}, {'kind': 'builtin'}],
                'stages': [{'format': 'knockout', 'scenario': '11_vs_11_kaggle'}],
            },
            _TEAMS,
            fits,
        )
    values = caught.value.values
    # The scenario travels as a scenario value, which the page names, and the text stays English.
    assert values['scenario'] == {
        'kind': 'scenario',
        'name': '11_vs_11_kaggle',
        'text': '11_vs_11_kaggle',
    }
    assert values['reason']['id'] == 'server.teams.scenario_format'
    assert str(caught.value).startswith('Minis cannot play 11_vs_11_kaggle in stage 1, unused')


def _labelled_failure(player='Built-in AI'):
    """A player whose first semi-final fails with a message of the server, as a policy's does."""

    def play(match, teams, provenance, progress):
        if match['key'] == '0/w4-1/1':
            error = RuntimeError(f'the policy of {player} failed, ValueError: no')
            error.message_id = 'server.policy.failed'
            error.values = {'player': player, 'reason': 'ValueError: no'}
            raise error
        return {'score': [1, 0], 'cards': [[0, 0], [0, 0]], 'match': None}

    return play


def test_the_error_of_a_stopped_tournament_carries_its_inner_message(render_home):
    cups = runner.Tournaments(player=_labelled_failure(), start=False)
    entry = cups.create(_builtin_config(4))
    assert cups.run(entry['id'], report=lambda line: None) == 'stopped'
    view = cups.get(entry['id'])
    cups.close()
    assert view['error'] == 'Semi-final 1 failed, the policy of Built-in AI failed, ValueError: no'
    assert view['error_id'] == 'server.tournament.match_failed'
    values = view['error_values']
    assert values['label']['id'] == 'server.tournament.label.semi_final'
    assert values['error']['id'] == 'server.policy.failed'
    assert values['error']['values']['player'] == 'Built-in AI'
    # The failed match keeps its own error with its id too.
    failed = next(m for m in view['matches'] if m['state'] == 'failed')
    assert failed['error_id'] == 'server.policy.failed'


def test_a_failure_names_the_team_as_its_entrant(monkeypatch):
    monkeypatch.setattr(runner._teams, 'entry', lambda identifier: {'name': identifier.title()})
    record = {
        'config': {
            'entrants': [
                {'kind': 'team', 'team': 'crashers', 'name': 'Crash FC'},
                {'kind': 'team', 'team': 'reds', 'name': 'Reds'},
            ]
        }
    }
    match = {'home': 0, 'away': 1}
    ids = {
        'error_id': 'server.policy.failed',
        'error_values': {'player': 'Crashers', 'reason': 'TypeError: no'},
    }
    error, found = runner.Tournaments._entrant_failure(
        record, match, 'the policy of Crashers failed, TypeError: no', ids
    )
    assert error == 'the policy of Crash FC failed, TypeError: no'
    assert found['error_values']['player'] == 'Crash FC'
    # A team that plays under its own name, and an error without a player, stay as they are.
    ids['error_values']['player'] = 'Reds'
    assert runner.Tournaments._entrant_failure(record, match, 'x', ids) == ('x', ids)
    assert runner.Tournaments._entrant_failure(record, match, 'y', {}) == ('y', {})
    # Two entrants of one team leave a failure that names the team as it is, since either side
    # may have failed. A match of agents names its entrant itself, from the tournament's names.
    record['config']['entrants'][1] = {'kind': 'team', 'team': 'crashers', 'name': 'Crash B'}
    ids['error_values']['player'] = 'Crashers'
    assert runner.Tournaments._entrant_failure(record, match, 'z', ids) == ('z', ids)


def test_a_team_entered_twice_names_the_entrant_that_failed(render_home, tmp_path):
    from cuju.render._registry import teams as _teams

    folder = tmp_path / 'crash'
    folder.mkdir()
    (folder / 'main.py').write_text(
        'def agent(obs):\n    raise RuntimeError("crash on purpose")\n', encoding='utf-8'
    )
    team = _teams.add_folder(folder, 'Crasher', '5v5')
    cups = runner.Tournaments(start=False, interval=0.1)
    config = _builtin_config(2, seeding='manual')
    config['entrants'] = [
        {'kind': 'team', 'team': team['id'], 'name': 'Red crash'},
        {'kind': 'team', 'team': team['id'], 'name': 'Blue crash'},
    ]
    config['stages'] = [{'format': 'knockout', 'scenario': '5_vs_5', 'length': 50}]
    entry = cups.create(config)
    assert cups.run(entry['id'], report=lambda line: None) == 'stopped'
    error = cups.get(entry['id'])['error']
    cups.close()
    # The left side plays first, so its entrant is the one whose policy failed.
    assert error.startswith('Final failed, the policy of Red crash failed, RuntimeError: crash')


def test_files_keep_labels_and_files_of_before_show_their_text(render_home):
    cups = runner.Tournaments(player=_fake_player(), start=False, interval=0.01)
    config = _builtin_config(2)
    del config['name']
    config['entrants'] = [{'kind': 'builtin', 'ability': 0.3}, {'kind': 'person', 'name': 'Ana'}]
    entry = cups.create(config)
    assert (entry['name'], entry['name_id']) == ('Tournament', 'server.tournament.label.tournament')
    cups.close()
    path = runner.folder() / f'{entry["id"]}.json'
    stored = json.loads(path.read_text(encoding='utf-8'))
    first, second = stored['config']['entrants']
    assert first['name_id'] == 'server.tournament.label.builtin_ability'
    assert first['name_values'] == {'ability': '0.30'}
    assert second['name'] == 'Ana' and 'name_id' not in second
    assert stored['config']['stages'][0]['name_id'] == 'server.tournament.label.stage.knockout'
    # A file of before holds the English text alone, which shows as it is.
    for holder in (stored['config'], first, stored['config']['stages'][0]):
        holder.pop('name_id')
        holder.pop('name_values')
    path.write_text(json.dumps(stored), encoding='utf-8')
    again = runner.Tournaments(player=_fake_player(), start=False, interval=0.01)
    summary = again.get(entry['id'])
    again.close()
    assert summary['name'] == 'Tournament' and 'name_id' not in summary
    assert summary['stages'][0] == {
        'name': 'Knockout',
        'format': 'knockout',
        'scenario': 'academy_empty_goal_close',
    }
    assert summary['config']['entrants'][0]['name'] == 'Built-in AI 0.30'


def test_ratings_and_recordings_keep_the_labels_of_entrants(render_home):
    seen = []

    def player(match, teams, provenance, progress):
        seen.append(provenance)
        return {'score': [1, 0]}

    cups = runner.Tournaments(player=player, start=False, interval=0.01)
    config = _builtin_config(2)
    config['entrants'] = [{'kind': 'builtin', 'ability': 0.8}, {'kind': 'builtin', 'name': 'Rex'}]
    entry = cups.create(config)
    assert cups.run(entry['id'], report=lambda line: None) == 'done'
    done = cups.get(entry['id'])
    cups.close()
    provenance = seen[0]
    assert provenance['name'] == 'Spring cup' and 'name_id' not in provenance
    assert provenance['label'] == 'Final'
    assert provenance['label_id'] == 'server.tournament.label.final'
    assert provenance['stage_id'] == 'server.tournament.label.stage.knockout'
    labels = provenance['labels']
    assert sorted(provenance['names']) == ['Built-in AI 0.80', 'Rex']
    assert sorted(rules.text_of(name) for name in labels) == ['Built-in AI 0.80', 'Rex']
    assert any(isinstance(name, dict) for name in labels) and 'Rex' in labels
    # The champion carries the label of its name, a name a person gave the text alone.
    assert done['champion'] in ('Built-in AI 0.80', 'Rex')
    assert ('champion_id' in done) == (done['champion'] != 'Rex')
    table = runner.ratings()
    assert table['builtin:0.80']['name_id'] == 'server.tournament.label.builtin_ability'
    # The title of the recording is a label of the tournament, the match and its sides.
    title = rules.match_title(provenance, labels[0], labels[1])
    home, away = (rules.text_of(name) for name in labels)
    assert title['text'] == f'Spring cup, Final, {home} against {away}'
    assert title['values']['match']['id'] == 'server.tournament.label.final'


def test_notes_of_person_games_are_labels_and_name_a_failure(render_home):
    games = _FakeGames()
    cups = runner.Tournaments(games, player=_fake_player(), start=False)
    config = _builtin_config(2)
    config['entrants'] = [{'kind': 'person', 'name': 'Ana'}, {'kind': 'builtin', 'ability': 0.3}]
    entry = cups.create(config)
    cups.tick()
    key = cups.get(entry['id'])['matches'][0]['key']
    cups.play(entry['id'], key)
    games.entry.update(state='ended', ending='quit', match='m-x')
    cups.tick()
    after = cups.get(entry['id'])['matches'][0]
    assert after['note'].startswith('The game ended before full time')
    assert after['note_id'] == 'server.tournament.note.early'
    # The opponent's policy ends the game, and the note names the failure and the award.
    cups.play(entry['id'], key)
    games.entry.update(
        state='ended',
        ending='policy',
        match=None,
        error='the policy of Rule bot failed, ValueError: no',
        error_id='server.policy.failed',
        error_values={'player': 'Rule bot', 'reason': 'ValueError: no'},
    )
    cups.tick()
    after = cups.get(entry['id'])['matches'][0]
    assert after['state'] == 'person' and after['note_id'] == 'server.tournament.note.failed'
    assert after['note'] == (
        'The game stopped, the policy of Rule bot failed, ValueError: no. Award the match to '
        'either side, or play it again.'
    )
    assert after['note_values']['error']['id'] == 'server.policy.failed'
    # A game that the process of before followed is gone, with a note of its own.
    cups.play(entry['id'], key)
    cups.close()
    games.entry = None
    again = runner.Tournaments(games, player=_fake_player(), start=False)
    again.tick()
    gone = again.get(entry['id'])['matches'][0]
    again.close()
    assert gone['note_id'] == 'server.tournament.note.gone'


def test_stage_names_of_the_page_agree_with_the_rules():
    import re
    from pathlib import Path

    source = (
        Path(rules.__file__).parents[1] / 'web' / 'js' / 'play/tournament-layout.js'
    ).read_text(encoding='utf-8')
    block = source.split('export const STAGE_NAME_IDS = {', 1)[1].split('};', 1)[0]
    pairs = re.findall(r"^\s*'?([^':]+?)'?: '([a-z_]+)',$", block, re.MULTILINE)
    assert dict(pairs) == rules.STAGE_NAMES
    for name, key in rules.STAGE_NAMES.items():
        assert rules._label(f'stage.{key}')['text'] == name
    for preset in rules.PRESETS.values():
        for stage in preset['stages']:
            assert stage['name'] in rules.STAGE_NAMES


# A team entered more than once.

_IDLE = 'def agent(obs):\n    return [0]\n'


def _rex(tmp_path):
    from cuju.render._registry import teams as _teams

    folder = tmp_path / 'rex'
    folder.mkdir()
    (folder / 'main.py').write_text(_IDLE, encoding='utf-8')
    return _teams.add_folder(folder, 'Rex', '5v5')


def test_a_team_entered_twice_plays_a_whole_tournament(render_home, tmp_path):
    from cuju.render._tournaments.tournament_cli import describe

    team = _rex(tmp_path)
    seen = []

    def player(match, teams, provenance, progress):
        seen.append((teams, provenance['names']))
        seed = match['seed']
        return {'score': [seed % 3, seed // 3 % 3], 'cards': [[0, 0], [0, 0]], 'match': None}

    cups = runner.Tournaments(player=player, start=False, interval=0.01)
    config = {
        'name': 'Derby cup',
        'seed': 5,
        'seeding': 'manual',
        'entrants': [
            {'kind': 'team', 'team': team['id']},
            {'kind': 'team', 'team': team['id']},
            {'kind': 'team', 'team': team['id'], 'name': 'Rex reserves'},
            {'kind': 'builtin', 'ability': 0.5},
        ],
        'stages': [
            {'format': 'league', 'scenario': '5_vs_5', 'length': 50},
            {'format': 'knockout', 'scenario': '5_vs_5', 'length': 50, 'settle': ['lots']},
        ],
    }
    entry = cups.create(config)
    assert cups.run(entry['id'], report=lambda line: None) == 'done'
    done = cups.get(entry['id'])
    cups.close()
    names = [e['name'] for e in done['config']['entrants']]
    assert names == ['Rex', 'Rex 2', 'Rex reserves', 'Built-in AI 0.50']
    assert done['state'] == 'done' and done['champion'] in names
    assert sorted(done['ranking']) == [0, 1, 2, 3]
    # The entrants of one team meet as two sides of one match, each under its own name.
    derbies = [sides for teams, sides in seen if teams == [team['id'], team['id']]]
    assert len(derbies) >= 3
    assert all(len(set(sides)) == 2 for sides in derbies)
    rows = done['stages_view'][0]['tables'][0]['rows']
    assert sorted(row['entrant'] for row in rows) == [0, 1, 2, 3]
    assert all(row['played'] == 3 for row in rows)
    shown = '\n'.join(describe(done))
    assert 'Rex against Rex 2' in shown or 'Rex 2 against Rex' in shown
    # The ratings keep the team once, and its matches against itself leave its rating.
    assert set(runner.ratings()) == {team['id'], 'builtin:0.50'}


def test_a_match_of_a_team_against_itself_records_two_sides_apart(render_home, tmp_path):
    team = _rex(tmp_path)
    cups = runner.Tournaments(start=False, interval=0.1)
    config = _builtin_config(2, seeding='manual')
    config['entrants'] = [
        {'kind': 'team', 'team': team['id']},
        {'kind': 'team', 'team': team['id']},
    ]
    config['stages'] = [
        {'format': 'knockout', 'scenario': '5_vs_5', 'length': 50, 'settle': ['lots']}
    ]
    entry = cups.create(config)
    assert cups.run(entry['id'], report=lambda line: None) == 'done'
    done = cups.get(entry['id'])
    cups.close()
    played = [m for m in done['matches'] if m['result']['match']]
    assert played
    header = _recording.read_header(_library.path_of(played[0]['result']['match']))
    names = [done['config']['entrants'][played[0][side]]['name'] for side in ('home', 'away')]
    assert sorted(names) == ['Rex', 'Rex 2']
    assert [side['name'] for side in header['teams']] == names
    assert [side['id'] for side in header['teams']] == [team['id'], team['id']]
    assert header['title'].endswith(f'{names[0]} against {names[1]}')
    # The right side wears the away kit, so the two sides of one team look apart.
    home, away = (side['style']['kit'] for side in header['teams'])
    assert header['teams'][1].get('away') and away['primary'] != home['primary']
    assert header['provenance']['tournament']['names'] == names


def test_the_command_line_enters_a_team_twice_and_names_it(render_home, tmp_path, capsys):
    from cuju.render.__main__ import main

    team = _rex(tmp_path)
    rex = ['--team', team['id']]
    shape = ['--preset', 'round_robin', '--scenario', '5_vs_5', '--seed', '3']
    assert main(['tournament', 'check', *shape, *rex, *rex, *rex, '--as', 'Rex B', '--json']) == 0
    preview = json.loads(capsys.readouterr().out)
    assert [e['name'] for e in preview['config']['entrants']] == ['Rex', 'Rex 2', 'Rex B']
    assert main(['tournament', 'check', *shape, *rex, *rex]) == 0
    checked = capsys.readouterr().out
    assert 'Rex against Rex 2' in checked or 'Rex 2 against Rex' in checked
    for arguments, message in (
        (['--as', 'Rex', *rex, *rex], 'expected --as after the --team'),
        (
            [*rex, '--as', 'Rex', *rex, '--as', ' REX '],
            'expected a name of its own for entrant 2, found REX, the name of entrant 1',
        ),
    ):
        assert main(['tournament', 'new', *shape, *arguments]) == 1
        error = capsys.readouterr().err
        assert error.startswith(f'cuju render: {message}') and error.count('\n') == 1, error


def test_files_of_before_load_and_resume_as_before(render_home):
    """Files written before a team could enter twice load, sealed or not, and play to the end."""
    cups = runner.Tournaments(player=_fake_player(), start=False, interval=0.01)
    entry = cups.create(_builtin_config(4))
    cups.close()
    folder = runner.folder()
    path = folder / f'{entry["id"]}.json'
    stored = json.loads(path.read_text(encoding='utf-8'))
    assert isinstance(stored.pop('seal'), str)
    # The rules of before gave two given names that read as one a number, Bot and Bot 2, which
    # the rules of now refuse, and a file keeps the names that its rules gave.
    first, second = stored['config']['entrants'][:2]
    for holder, name in ((first, 'Bot'), (second, 'Bot 2')):
        holder.pop('name_id', None)
        holder.pop('name_values', None)
        holder['name'] = name
    with pytest.raises(rules.TournamentError, match='a name of its own'):
        rules.check_entrants([{'kind': 'builtin', 'name': n} for n in ('Bot', 'bot')], _TEAMS)
    runner._write_record(path, stored)
    # The same file dropped in without a seal loads stopped, as any foreign file does.
    foreign = {**stored, 'id': 'cup-20261020-101010-abcd'}
    (folder / f'{foreign["id"]}.json').write_text(json.dumps(foreign), encoding='utf-8')
    again = runner.Tournaments(player=_fake_player(), start=False, interval=0.01)
    assert again.get(entry['id'])['state'] == 'running'
    assert again.get(foreign['id'])['state'] == 'stopped'
    assert again.run(entry['id'], report=lambda line: None) == 'done'
    assert again.resume(foreign['id'])['state'] == 'running'
    assert again.run(foreign['id'], report=lambda line: None) == 'done'
    for identifier in (entry['id'], foreign['id']):
        done = again.get(identifier)
        assert [e['name'] for e in done['config']['entrants']][:2] == ['Bot', 'Bot 2']
        assert done['champion']
    again.close()


# The abilities of the entrants, the stages and the tournament's standard.


def _abilities(config):
    """Returns the abilities of every first stage match by its sides' names, home first."""
    names = [e['name'] for e in config['entrants']]
    view = rules.evaluate(config, {})
    return {(names[m['home']], names[m['away']]): m['ability'] for m in view['matches']}


def test_an_entrant_then_the_stage_then_the_standard_then_the_scenario_set_the_ability():
    entrants = [
        {'kind': 'team', 'team': 'reds', 'ability': 0.2},
        {'kind': 'team', 'team': 'blues'},
        {'kind': 'builtin'},
        {'kind': 'person', 'name': 'Ana', 'ability': 0.0},
    ]
    stage = {'format': 'league', 'scenario': '11_vs_11_kaggle'}
    base = {'seed': 2, 'entrants': entrants, 'stages': [stage]}
    config = rules.check({**base, 'ability': 0.8}, _TEAMS, _fits)
    assert config['ability'] == 0.8
    assert [e['ability'] for e in config['entrants']] == [0.2, None, None, 0.0]
    # Every kind keeps its name and key, and a built-in AI without an ability stays as it was.
    assert [e['key'] for e in config['entrants']] == [
        'reds',
        'blues',
        'builtin:scenario',
        'person:Ana',
    ]
    own = {'Reds': 0.2, 'Blues': 0.8, 'Built-in AI': 0.8, 'Ana': 0.0}
    for (home, away), ability in _abilities(config).items():
        assert ability == [own[home], own[away]]
    # A stage's ability comes before the standard, and an entrant's own before both.
    config = rules.check(
        {**base, 'ability': 0.8, 'stages': [{**stage, 'ability': 0.5}]}, _TEAMS, _fits
    )
    own = {'Reds': 0.2, 'Blues': 0.5, 'Built-in AI': 0.5, 'Ana': 0.0}
    for (home, away), ability in _abilities(config).items():
        assert ability == [own[home], own[away]]
    # Without a standard or a stage's ability the scenario's own plays, as `None`.
    config = rules.check(base, _TEAMS, _fits)
    assert config['ability'] is None
    own = {'Reds': 0.2, 'Blues': None, 'Built-in AI': None, 'Ana': 0.0}
    for (home, away), ability in _abilities(config).items():
        assert ability == [own[home], own[away]]
    for wrong in (1.5, -0.1, 'high', True):
        with pytest.raises(rules.TournamentError, match='expected the standard ability from 0'):
            rules.check({**base, 'ability': wrong}, _TEAMS)
        with pytest.raises(rules.TournamentError, match='ability of entrant 2 from 0 to 1'):
            rules.check(
                {**base, 'entrants': [entrants[0], {**entrants[1], 'ability': wrong}]}, _TEAMS
            )


def test_two_entrants_of_one_team_play_at_their_own_abilities():
    config = rules.check(
        {
            'seed': 5,
            'ability': 0.4,
            'entrants': [
                {'kind': 'team', 'team': 'reds', 'ability': 0.9},
                {'kind': 'team', 'team': 'reds', 'ability': 0.1},
            ],
            'stages': [{'format': 'league', 'scenario': '11_vs_11_kaggle'}],
        },
        _TEAMS,
        _fits,
    )
    assert [e['name'] for e in config['entrants']] == ['Reds', 'Reds 2']
    assert [e['key'] for e in config['entrants']] == ['reds', 'reds']
    assert _abilities(config) in (
        {('Reds', 'Reds 2'): [0.9, 0.1]},
        {('Reds 2', 'Reds'): [0.1, 0.9]},
    )


def test_entrant_abilities_agree_with_the_page():
    """The page's matchAbility and shownAbility hold the same cases, in tests/web/tournament.mjs."""
    from pathlib import Path

    path = Path(__file__).parent / 'support' / 'entrant_abilities.json'
    cases = json.loads(path.read_text(encoding='utf-8'))
    for entrant, stage, standard, ability in cases['match']:
        assert rules.match_ability(entrant, stage, standard) == ability
    for entrant, standard, ability in cases['shown']:
        assert rules.shown_ability(entrant, standard) == ability
    # A built-in AI whose name the rules made holds its ability in its name already.
    config = rules.check(
        {
            'seed': 1,
            'ability': 0.5,
            'entrants': [
                {'kind': 'builtin', 'ability': 0.3},
                {'kind': 'team', 'team': 'reds', 'ability': 0.3},
            ],
            'stages': [{'format': 'league', 'scenario': '11_vs_11_kaggle'}],
        },
        _TEAMS,
    )
    assert [rules.shown_ability(e, config['ability']) for e in config['entrants']] == [None, 0.3]


def test_a_preset_keeps_its_standard_ability():
    preset = rules.check_preset(
        {'title': 'Strong cup', 'ability': 0.9, 'stages': [{'format': 'knockout'}]}
    )
    assert preset['ability'] == 0.9
    config = rules.preset_config('mine', {'mine': preset})
    assert config['ability'] == 0.9
    with pytest.raises(rules.TournamentError, match='standard ability'):
        rules.check_preset({'title': 'x', 'ability': 2, 'stages': [{'format': 'knockout'}]})


def test_files_without_a_standard_ability_resume_with_the_abilities_they_had(render_home):
    """A sealed file of before, without a standard, plays every match at the abilities it had."""
    calls = []

    def player(match, teams, provenance, progress):
        calls.append((match['key'], list(match['ability']), provenance['ability']))
        return {'score': [1, 0], 'cards': [[0, 0], [0, 0]], 'match': None}

    cups = runner.Tournaments(player=_fake_player(), start=False, interval=0.01)
    config = _builtin_config(4)
    config['entrants'] = [
        {'kind': 'builtin', 'ability': 0.3},
        {'kind': 'builtin'},
        {'kind': 'builtin', 'ability': 0.9},
        {'kind': 'person', 'name': 'Ana'},
    ]
    config['stages'][0]['ability'] = 0.6
    entry = cups.create(config, run=False)
    cups.close()
    path = runner.folder() / f'{entry["id"]}.json'
    stored = json.loads(path.read_text(encoding='utf-8'))
    stored.pop('seal')
    # A file of before holds no standard, and its entrants keep the keys they were rated by.
    del stored['config']['ability']
    runner._write_record(path, stored)
    again = runner.Tournaments(player=player, start=False, interval=0.01)
    loaded = again.get(entry['id'])
    assert loaded['state'] == 'stopped' and 'ability' not in loaded['config']
    assert [e['key'] for e in loaded['config']['entrants']] == [
        'builtin:0.30',
        'builtin:scenario',
        'builtin:0.90',
        'person:Ana',
    ]
    abilities = {m['key']: m['ability'] for m in loaded['matches']}
    names = [e['name'] for e in loaded['config']['entrants']]
    own = {names[0]: 0.3, names[1]: 0.6, names[2]: 0.9, names[3]: 0.6}
    for match in loaded['matches']:
        assert match['ability'] == [own[names[match['home']]], own[names[match['away']]]]
    again.resume(entry['id'])
    again.tick()
    assert _wait(lambda: calls)
    again.close()
    key, ability, provenance = calls[0]
    assert ability == abilities[key] == provenance


def test_each_side_of_a_real_match_plays_its_entrant_ability(render_home, tmp_path):
    """A registered team leaves players to the built-in AI, which plays at the entrant's ability."""
    team = _rex(tmp_path)
    cups = runner.Tournaments(start=False, interval=0.1)
    config = _builtin_config(2, seeding='manual', ability=0.7)
    config['entrants'] = [
        {'kind': 'team', 'team': team['id'], 'ability': 0.2},
        {'kind': 'builtin'},
    ]
    config['stages'] = [{'format': 'league', 'scenario': '5_vs_5', 'length': 50, 'cycles': 2}]
    entry = cups.create(config)
    assert cups.run(entry['id'], report=lambda line: None) == 'done'
    done = cups.get(entry['id'])
    cups.close()
    matches = [m for m in done['matches'] if m['result']['match']]
    assert len(matches) == 2
    homes = set()
    for match in matches:
        header = _recording.read_header(_library.path_of(match['result']['match']))
        provenance = header['provenance']
        rex = 0 if match['home'] == 0 else 1
        expected = [0.2, 0.7] if rex == 0 else [0.7, 0.2]
        homes.add(rex)
        # The tournament asks for each side's ability, and the engine plays it on that side.
        assert match['ability'] == expected
        assert provenance['tournament']['ability'] == expected
        assert provenance['ability'] == expected
        assert [t['ability'] for t in header['teams']] == expected
    # Over home and away, Rex played its ability from both sides of the pitch.
    assert homes == {0, 1}


def test_the_command_line_sets_the_standard_and_entrant_abilities(render_home, tmp_path, capsys):
    from cuju.render.__main__ import main

    team = _rex(tmp_path)
    shape = ['--preset', 'round_robin', '--scenario', '5_vs_5', '--seed', '3']
    entrants = ['--team', team['id'], '--ability', '0.25', '--team', team['id'], '--builtin', 'any']
    assert main(['tournament', 'check', *shape, '--ability', '0.8', *entrants, '--json']) == 0
    config = json.loads(capsys.readouterr().out)['config']
    assert config['ability'] == 0.8
    assert [e['ability'] for e in config['entrants']] == [0.25, None, None]
    assert main(['tournament', 'check', *shape, '--ability', '0.8', *entrants]) == 0
    printed = capsys.readouterr().out
    assert printed.splitlines()[0].endswith(', standard ability 0.80')
    # After an entrant, standard leaves it to the standard, and scenario unsets the standard.
    follow = ['--team', team['id'], '--ability', 'standard', '--builtin', '0.4', '--ability', '0.6']
    assert main(['tournament', 'check', *shape, '--ability', 'scenario', *follow, '--json']) == 0
    config = json.loads(capsys.readouterr().out)['config']
    assert config['ability'] is None
    assert [e['ability'] for e in config['entrants']] == [None, 0.6]
    assert config['entrants'][1]['key'] == 'builtin:0.60'
    for arguments, message in (
        (
            ['--ability', 'strong', *entrants],
            'expected --ability with an ability from 0 to 1 or scenario',
        ),
        (
            [*entrants, '--ability', 'strong'],
            'expected --ability with an ability from 0 to 1 or standard',
        ),
        (['--ability', '2', *entrants], 'expected the standard ability from 0 to 1'),
        ([*entrants, '--ability', '-1'], 'expected the ability of entrant 3 from 0 to 1'),
    ):
        assert main(['tournament', 'new', *shape, *arguments]) == 1
        error = capsys.readouterr().err
        assert error.startswith(f'cuju render: {message}') and error.count('\n') == 1, error


def test_a_configuration_file_takes_both_abilities(render_home, tmp_path, capsys):
    from cuju.render.__main__ import main

    team = _rex(tmp_path)
    path = tmp_path / 'cup.json'
    path.write_text(
        json.dumps(
            {
                'name': 'Ability cup',
                'seed': 4,
                'ability': 0.35,
                'entrants': [
                    {'kind': 'team', 'team': team['id'], 'ability': 0.9},
                    {'kind': 'person', 'name': 'Ana', 'ability': 0.1},
                    {'kind': 'builtin'},
                ],
                'stages': [{'format': 'league', 'scenario': '5_vs_5'}],
            }
        ),
        encoding='utf-8',
    )
    assert main(['tournament', 'new', '--config', str(path), '--json']) == 0
    identifier = json.loads(capsys.readouterr().out)['id']
    stored = json.loads((runner.folder() / f'{identifier}.json').read_text(encoding='utf-8'))
    assert stored['config']['ability'] == 0.35
    assert [e['ability'] for e in stored['config']['entrants']] == [0.9, 0.1, None]
    assert main(['tournament', 'show', identifier]) == 0
    shown = capsys.readouterr().out
    assert 'Rex at 0.90' in shown and 'Ana at 0.10' in shown and 'standard ability 0.35' in shown


# The draw of a new tournament.


def _first_round(seed, preset='quick_cup', count=8, **options):
    config = rules.check(
        {**rules.preset_config(preset), 'seed': seed, 'entrants': _builtins(count), **options},
        _TEAMS,
    )
    stage = rules.evaluate(config, {})['stages'][0]
    if stage['tables'] and stage['format'] == 'groups':
        return [tuple(row['entrant'] for row in table['rows']) for table in stage['tables']]
    return [(fixture['home'], fixture['away']) for fixture in stage['rounds'][0]['fixtures']]


def test_a_new_tournament_draws_at_random_from_its_seed():
    assert {preset['seeding'] for preset in rules.PRESETS.values()} == {'random'}
    for preset in ('quick_cup', 'world_cup', 'double_elimination', 'swiss_16'):
        draws = {tuple(_first_round(seed, preset)) for seed in range(8)}
        assert len(draws) > 1, preset
        # The same seed draws the same again.
        assert _first_round(5, preset) == _first_round(5, preset)
    # By hand, the order of the entrants is the order of the seeds, seed 1 against the last.
    assert _first_round(5, seeding='manual')[0] == (0, 7)
    assert {tuple(_first_round(seed, seeding='manual')) for seed in range(4)} == {
        tuple(_first_round(0, seeding='manual'))
    }


def test_a_file_seeded_by_rating_keeps_its_draw(render_home):
    """A tournament of a preset that seeded by rating resumes with the draw it was made with."""
    cups = runner.Tournaments(player=_fake_player(), start=False, interval=0.01)
    entry = cups.create({**_builtin_config(8), 'seeding': 'rating'}, run=False)
    before = cups.get(entry['id'])
    cups.close()
    # Equal ratings keep the order of the entrants, as they always did.
    first = [(f['home'], f['away']) for f in before['stages_view'][0]['rounds'][0]['fixtures']]
    assert first == [(0, 7), (3, 4), (1, 6), (2, 5)]
    again = runner.Tournaments(player=_fake_player(), start=False, interval=0.01)
    after = again.get(entry['id'])
    assert after['config']['seeding'] == 'rating'
    assert after['stages_view'] == before['stages_view']
    assert again.resume(entry['id'])['state'] == 'running'
    assert again.run(entry['id'], report=lambda line: None) == 'done'
    again.close()


def test_the_command_line_draws_at_random_unless_seeded_by_hand(render_home, capsys):
    from cuju.render.__main__ import main

    four = ['--builtin', '0.1', '--builtin', '0.2', '--builtin', '0.3', '--builtin', '0.4']
    for options, seeding in (([], 'random'), (['--seeding', 'manual'], 'manual')):
        arguments = ['tournament', 'check', '--preset', 'world_cup', '--seed', '2', *four]
        assert main([*arguments, *options, '--json']) == 0
        assert json.loads(capsys.readouterr().out)['config']['seeding'] == seeding


# Watching a tournament without spoilers.


def test_a_tournament_without_spoilers_tells_only_what_was_watched(render_home):
    from cuju.errors import ArgumentError

    cups = runner.Tournaments(player=_fake_player(), start=False, interval=0.01)
    entry = cups.create({**_builtin_config(4), 'seeding': 'manual'})
    assert cups.run(entry['id'], report=lambda line: None) == 'done'
    full = cups.get(entry['id'])
    assert full['champion_index'] is not None
    semis = [m['key'] for m in full['matches'] if m['key'].startswith('0/w4-')]
    final = next(m['key'] for m in full['matches'] if m['key'] not in semis)
    # Nothing watched, nothing told, the semi-finals wait in order and the final has no sides.
    hidden = cups.without_spoilers(entry['id'], [])
    assert hidden['champion'] is None and hidden['champion_index'] is None
    assert hidden['ranking'] is None
    assert hidden['spoilers']['unseen'] == semis
    assert hidden['spoilers']['hidden'] == 3 and hidden['spoilers']['watched'] == 0
    assert sorted(hidden['spoilers']['played']) == sorted([*semis, final])
    for match in hidden['matches']:
        assert match['state'] == 'unseen' and match['result'] is None
        assert set(match['unseen']) == {'match', 'forfeit'}
    assert final not in {m['key'] for m in hidden['matches']}
    rounds = hidden['stages_view'][0]['rounds']
    assert all(f['score'] is None and f['winner'] is None for f in rounds[0]['fixtures'])
    assert all(
        isinstance(side, dict) for side in (rounds[1]['fixtures'][0][s] for s in ('home', 'away'))
    )
    # One semi-final watched tells its winner, who stands in the final, and nothing else.
    one = cups.without_spoilers(entry['id'], [semis[0]])
    first = one['stages_view'][0]['rounds'][0]['fixtures'][0]
    assert first['winner'] == full['stages_view'][0]['rounds'][0]['fixtures'][0]['winner']
    assert one['spoilers']['unseen'] == [semis[1]]
    assert one['stages_view'][0]['rounds'][1]['fixtures'][0]['home'] == first['winner']
    # Every match watched, the tournament reads as it is.
    every = cups.without_spoilers(entry['id'], [*semis, final])
    assert every['champion'] == full['champion'] and every['ranking'] == full['ranking']
    assert every['spoilers']['unseen'] == [] and every['spoilers']['hidden'] == 0
    assert every['stages_view'] == full['stages_view']
    with pytest.raises(ArgumentError, match='watched matches as a list'):
        cups.without_spoilers(entry['id'], 'all')
    assert cups.without_spoilers('cup-none', []) is None
    cups.close()


def test_the_server_answers_a_tournament_without_spoilers(render_home):
    import http.server

    cups = runner.Tournaments(player=_fake_player(), start=False, interval=0.01)
    entry = cups.create(_builtin_config(4))
    assert cups.run(entry['id'], report=lambda line: None) == 'done'
    server = http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _server.make_handler(_server._Requests(), None, cups)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_address[1]}'
    path = f'/api/tournaments/{entry["id"]}/spoilers'
    try:
        status, hidden = _request(address, 'POST', path, {'watched': []})
        assert status == 200 and hidden['champion'] is None
        assert len(hidden['spoilers']['unseen']) == 2
        status, refused = _request(address, 'POST', path, {'watched': 7})
        assert status == 400 and refused['error_id'] == 'server.tournament.watched'
        status, _ = _request(address, 'POST', '/api/tournaments/cup-none/spoilers', {'watched': []})
        assert status == 404
    finally:
        server.shutdown()
        server.server_close()
        cups.close()
