# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The messages of the server that the page shows to people, each with an id and English text.

An answer or an entry that the page shows carries the English text in `error`, as it always has,
and beside it the id of its message in `error_id` and the values of its placeholders in
`error_values`, so the page shows the text in its own language. The command line and every
English answer read the same text as before. A template names its placeholders in braces, such
as `{scenario}`, as the language files of the page do, and Python fills it the way the page does,
with every value as text, so both read the same.

`MESSAGES` holds every id with its English template, and the part `server` of the language
files holds the same ids, which `compare` checks.
"""

from __future__ import annotations

import importlib
import re
import sys
from typing import Any

from cuju.errors import ArgumentError

# A placeholder of a template, as the page's own runtime, web/js/core/i18n.js, reads it. Any other
# brace, such as that of `{"colors": [...]}`, is text.
_PLACEHOLDER = re.compile(r'\{([A-Za-z0-9_]+)\}')

MESSAGES: dict[str, str] = {
    'server.body_size': 'expected a request body of at most 110 MB',
    'server.challenges.attempt': 'expected an attempt from 0 to {last}, found {attempt}',
    'server.challenges.attempt_recording': (
        'the recording {match} cannot be attempt {attempt}, {reason}'
    ),
    'server.challenges.attempts': 'expected from 1 to {most} attempts, found {attempts}',
    'server.challenges.distinct': 'expected a distinct recording for each attempt',
    'server.challenges.exit': 'the run ended with exit code {code}',
    'server.challenges.exit_detail': 'the run ended with exit code {code}, {detail}',
    'server.challenges.keep_recordings': 'expected keep_recordings as true or false, found {value}',
    'server.challenges.left_matches': (
        'expected from 1 to {count} recordings of the attempts played, found {matches}'
    ),
    'server.challenges.matches': (
        'expected the {count} recordings of the attempts in order, found {matches}'
    ),
    'server.challenges.name_length': 'expected a name of 1 to {most} characters, found {value}',
    'server.challenges.name_text': 'expected a name as text, found {value}',
    'server.challenges.no_challenge': 'no challenge {identifier}',
    'server.challenges.no_run': 'no such run',
    'server.challenges.person_fields': (
        'expected person, matches and keep_recordings, found {unknown}'
    ),
    'server.challenges.policy': 'expected a policy function, found {policy}',
    'server.challenges.recording': 'expected a recording of the library, found {match}',
    'server.challenges.run_fields': 'expected a person with matches, or a team with attempts',
    'server.challenges.team': 'expected a team of the registry, found {team}',
    'server.challenges.team_or_policy': 'expected either a team of the registry or a policy',
    'server.challenges.unknown': 'expected a challenge, one of {challenges}, found {identifier}',
    'server.clips.animation': 'expected animation {index} to hold channels and samplers',
    'server.clips.animations_count': 'expected at most {most} animations in a clip, found {count}',
    'server.clips.animations_none': 'expected a clip with at least one animation, found none',
    'server.clips.asset_version': 'expected a glTF 2.0 file, whose asset names version 2.0',
    'server.clips.binary': 'expected a binary glTF file, .glb, found other bytes',
    'server.clips.body': 'expected a bone for the joint body, the pelvis, which every rig has',
    'server.clips.buffer': 'expected the binary chunk that the buffer of the file needs',
    'server.clips.buffer_length': 'expected a binary chunk as long as the buffer of the file',
    'server.clips.channels': 'expected the channels of animation {index} to name nodes',
    'server.clips.chunks': 'expected one JSON chunk and at most one binary chunk after it',
    'server.clips.count': 'expected at most {most} clips for a team',
    'server.clips.cut': 'expected whole chunks in the binary glTF file, found a cut one',
    'server.clips.extension': 'expected a clip without {extension}, which the page cannot read',
    'server.clips.joints': 'expected the joints as names of bones by joint, found {joints}',
    'server.clips.json': 'expected the JSON chunk of a glTF file, found {error}',
    'server.clips.json_first': 'expected a binary glTF file with its JSON chunk first',
    'server.clips.json_object': 'expected the JSON chunk of a glTF file to hold an object',
    'server.clips.length': (
        'expected a binary glTF file of the length its header gives, {length} bytes, found {size}'
    ),
    'server.clips.link': 'expected a self-contained clip, found a link to {uri}',
    'server.clips.missing_bones': 'expected bones of the clip, found {bones}',
    'server.clips.name': (
        'expected a clip name of up to 40 lowercase letters, digits and underscores, found {name}'
    ),
    'server.clips.padding': 'expected chunks padded to four bytes inside the file',
    'server.clips.size': 'expected a clip of at most 10 MB, found {size} bytes',
    'server.clips.skin_joints': 'expected a skin with joints, found an empty one',
    'server.clips.skinned': 'expected a skinned skeleton, a glTF file with a skin, found none',
    'server.clips.total': (
        'expected at most 40 MB of clips for a team, found {total} bytes with this one'
    ),
    'server.clips.unknown': 'expected a clip of the team, found {name}',
    'server.clips.unknown_joints': "expected joints of GRF's skeleton, found {joints}",
    'server.clips.version': 'expected a binary glTF file of version 2, found version {version}',
    'server.content_length': 'expected a Content-Length of digits',
    'server.feed.follow.auto': 'a live source while one streams, else the newest recording',
    'server.feed.follow.latest': 'the newest recording of the library',
    'server.feed.follow.live': 'the newest live source',
    'server.feed.follow.live_named': 'the live source {name}',
    'server.feed.follow.queue': 'the newest finished requested match',
    'server.feed.follow.tournament': 'the newest finished match of the newest tournament',
    'server.feed.follow.tournament_named': 'the matches of the tournament {name}',
    'server.feed.no_live': 'No live source streams now',
    'server.feed.no_live_named': 'No live source named {name} streams now',
    'server.feed.no_recording': 'The library holds no recording {name}',
    'server.feed.no_recordings': 'The library holds no recording yet',
    'server.feed.no_request': 'No requested match has finished yet',
    'server.feed.no_tournament': 'No tournament yet',
    'server.feed.no_tournament_named': 'No tournament named {name}',
    'server.feed.nothing_after': 'expected nothing after the source {source}, found {value}',
    'server.feed.recording_name': 'expected the identifier of a recording after recording:',
    'server.feed.source': (
        'expected a source of {sources}, a kind with a name such as live:Evaluation, or the '
        'identifier of a recording, found {value}'
    ),
    'server.feed.tournament_waits': '{name} has no finished match yet',
    'server.feed.tournament_waits_unnamed': 'The tournament has no finished match yet',
    'server.game.answered': 'the game answered {status}',
    'server.game.busy': 'a game already plays, quit it first',
    'server.game.exit': 'the game ended with exit code {code}',
    'server.game.exit_detail': 'the game ended with exit code {code}, {detail}',
    'server.game.humans': (
        'expected two flags for a person on the left and right, one true, found {humans}'
    ),
    'server.game.input_fields': 'expected side, held and pressed, found {unknown}',
    'server.game.input_list': 'expected {key} as a list of {allowed}',
    'server.game.paused': 'expected paused as true or false, found {paused}',
    'server.game.person': 'expected a person on at least one side',
    'server.game.record': 'expected record as true or false, found {record}',
    'server.game.registry_teams': 'expected two registry teams, found {teams}',
    'server.game.side': 'expected a side that a person plays in this game, {sides}, found {side}',
    'server.game.sides_both': '0 for the left or 1 for the right',
    'server.game.sides_left': '0 for the left',
    'server.game.sides_right': '1 for the right',
    'server.game.silent': 'the game did not answer, {error}',
    'server.game.teams': 'expected two registry teams, left and right, found {teams}',
    'server.game.unknown': 'no such game',
    'server.help.sample_names': 'expected names as a list of samples, found {names}',
    'server.json_object': 'expected a JSON object',
    'server.language.code': (
        'expected a language code of lowercase letters and digits, such as pt or pt-br, '
        'found {code}'
    ),
    'server.language.json': 'expected a language file, a JSON object with its header @language',
    'server.language.keep': 'the language {code} ships with cuju and stays',
    'server.language.malformed': 'expected well formed messages, found {first}',
    'server.language.none': 'no language {code}',
    'server.language.shipped': (
        'the language {code} ships with cuju, name your file with another code, '
        'such as {code}-x-mine'
    ),
    'server.language.size': 'expected a language file of at most {most} MB',
    'server.library.favorite': 'expected favorite as true or false, found {favorite}',
    'server.library.folder_size': (
        'expected a folder of at most 8 names of 64 characters, found {folder}'
    ),
    'server.library.folder_text': 'expected a folder as text, found {folder}',
    'server.library.group_trash': 'no such group of recordings in the Trash',
    'server.library.group_unknown': 'no such group of recordings in the library',
    'server.library.notes': 'expected notes as text of at most ten thousand characters',
    'server.library.samples': 'expected a sample from {shipped}, found {unknown}',
    'server.library.tags': 'expected up to twenty tags, each of one to forty characters',
    'server.library.title': 'expected a title with at least one character',
    'server.library.unknown': 'expected a recording of the library, found {identifier}',
    'server.live.answered': 'the live source answered {status}',
    'server.live.environment': 'expected an environment from 0 to {last}, found {environment}',
    'server.live.grid_range': (
        'expected a first environment from 0 to {last} and a count from 1 to {most}, found '
        '{first} and {count}'
    ),
    'server.live.no_grid': 'this live source offers no grid, it comes from an older cuju',
    'server.live.silent': 'the live source did not answer, {error}',
    'server.live.unknown': 'no such live source',
    'server.live.whole_number': 'expected a whole number for {name}, found {text}',
    'server.loopback': 'expected a request to this server by its loopback address',
    # Names and titles that cuju makes, which travel as labels.
    'server.names.against': '{left} against {right}',
    'server.names.builtin': "GRF's built-in AI",
    'server.names.challenge_attempt': '{challenge}, attempt {attempt}, {competitor}',
    'server.names.challenge_run': '{challenge}, {competitor}',
    'server.names.demo': 'Demo, the built-in AI against itself',
    'server.names.left': 'Left',
    'server.names.live': '{scenario}, environment {environment}, process {process}',
    'server.names.medal_bronze': 'bronze',
    'server.names.medal_gold': 'gold',
    'server.names.medal_silver': 'silver',
    'server.names.person_with': '{person} with {team}',
    'server.names.player': 'Player {number}',
    'server.names.python_policy': 'Python policy',
    'server.names.recorder': '{scenario}, environment {environment}',
    'server.names.right': 'Right',
    'server.names.run_attempts': '{value} of {attempts}',
    'server.names.run_left': 'left after {played} of {attempts}',
    'server.names.run_margin': 'goal difference {value}',
    'server.names.run_medal': '{value}, {medal} medal',
    'server.names.run_no_medal': '{value}, no medal',
    'server.names.run_playing': 'under way, {played} of {attempts} played',
    'server.names.run_practice': '{value}, practice',
    'server.names.run_stopped': 'stopped after {played} of {attempts}',
    'server.names.sample_11v11': 'Sample match, 11 vs 11',
    'server.names.sample_5v5': 'Sample match, 5 vs 5',
    'server.names.you': 'You',
    'server.no_clip': 'no such clip',
    'server.no_file': 'no such file',
    'server.no_image': 'no such image',
    'server.no_item': 'no such item',
    'server.no_match': 'no such match',
    'server.no_model': 'no such model',
    'server.no_package_file': 'no such file of the package',
    'server.no_resource': 'no such resource',
    'server.no_sound': 'no such sound',
    'server.origin': 'expected a request from the page of this server',
    'server.play.scenario': 'expected a scenario from the renderer scenario list, found {scenario}',
    'server.policy.action_set': 'expected the v2 action set to hand players to the AI',
    'server.policy.error': 'the policy failed, {reason}',
    'server.policy.error_action': (
        'the policy failed, it answered the action {value}, outside its action set of {count} '
        'actions, 0 to {last}'
    ),
    'server.policy.failed': 'the policy of {player} failed, {reason}',
    'server.policy.failed_action': (
        'the policy of {player} failed, it answered the action {value}, outside its action set '
        'of {count} actions, 0 to {last}'
    ),
    'server.policy.first': (
        'the policy did not answer its first observation within {seconds} seconds'
    ),
    'server.policy.load': 'the policies did not load within {seconds} seconds',
    'server.policy.silent': 'the policy has not answered for {seconds} seconds',
    'server.requests.cancelled': 'cancelled',
    'server.requests.exit': 'the match ended with exit code {code}',
    'server.requests.exit_detail': 'the match ended with exit code {code}, {detail}',
    'server.requests.history': 'could not save the request history, {error}',
    'server.requests.interrupted': 'interrupted by a server restart',
    'server.requests.interrupted_playing': (
        'interrupted by a server restart while playing, its recording may still appear in the '
        'library'
    ),
    'server.requests.timeout': 'the match ran past {minutes} minutes',
    'server.samples.team': 'expected a sample team from {teams}, found {name}',
    'server.samples.unknown': 'expected samples from {every}, found {unknown}',
    'server.scenario': 'expected a shipped scenario, found {scenario}',
    'server.seed': 'expected a seed from 0 to 2**64 - 1, found {value}',
    'server.teams.ability': 'expected an ability from 0 to 1, found {value}',
    'server.teams.ability_pair': 'expected a pair of abilities, left and right, found {ability}',
    'server.teams.agent_function': 'expected an agent function in the submission {identifier}',
    'server.teams.archive.device': (
        'expected archive members whose names open no device on Windows and end in no dot or '
        'space, found {member}'
    ),
    'server.teams.archive.limits': (
        'expected an archive of at most 10,000 files and 500 MB unpacked'
    ),
    'server.teams.archive.outside': 'expected archive members inside the archive, found {member}',
    'server.teams.archive.plain': 'expected plain files in the archive, found {member}',
    'server.teams.archive.tar': 'expected a readable .tar.gz archive, found {error}',
    'server.teams.archive.zip': 'expected a readable .zip archive, found {error}',
    'server.teams.badge': 'expected a badge of at most three characters, found {value}',
    'server.teams.beside_count': (
        '{team} cannot play beside a person in {scenario}, which has {available} controllable '
        'players on that side'
    ),
    'server.teams.beside_dynamic': 'expected dynamic assignment for {team} beside a person',
    'server.teams.cannot_play': '{team} cannot play {scenario}, {reason}',
    'server.teams.celebration': 'expected the name of a celebration, found {value}',
    'server.teams.celebrations': 'expected a list of at most 32 celebrations',
    'server.teams.choice': 'expected {name} as one of {choices}, found {value}',
    'server.teams.color': 'expected {name} as three integers from 0 to 255, found {value}',
    'server.teams.color_pair': 'expected colors as #rrggbb, found {old} and {new}',
    'server.teams.colors': 'expected the colors as a dictionary by model, found {value}',
    'server.teams.colors_count': 'expected at most {count} colors for {model}',
    'server.teams.control.fields': (
        'expected players, assignment, selection, goalkeeper and action_set'
    ),
    'server.teams.control.goalkeeper_builtin': (
        'scenario makes the goalkeeper uncontrollable, choose scenario'
    ),
    'server.teams.control.goalkeeper_fixed': (
        'expected fixed assignment for a goalkeeper handed to the AI'
    ),
    'server.teams.control.goalkeeper_outside': (
        'expected the goalkeeper outside the fixed selection'
    ),
    'server.teams.control.goalkeeper_scenario': (
        'scenario has a controllable goalkeeper, choose agent or builtin'
    ),
    'server.teams.control.goalkeeper_selected': 'expected the goalkeeper in the fixed selection',
    'server.teams.control.goalkeeper_uncontrollable': (
        'scenario makes the goalkeeper uncontrollable'
    ),
    'server.teams.control.legacy_goalkeeper': (
        'expected 10 players for the earlier goalkeeper setting'
    ),
    'server.teams.control.players': 'expected from 1 to {most} controlled players',
    'server.teams.control.select_player': 'scenario cannot select player {player}',
    'server.teams.control.selection_count': 'expected one selection for each controlled player',
    'server.teams.control.selection_distinct': 'expected distinct player indices or GRF role names',
    'server.teams.control.selection_empty': 'expected an empty selection for dynamic assignment',
    'server.teams.control.selection_list': 'expected a list of player indices or roles',
    'server.teams.control.too_few': 'scenario has only {count} controllable players',
    'server.teams.controlled_players': 'expected a number of controlled players, found {players}',
    'server.teams.crowd': 'expected the crowd as {"colors": [...]}, found {value}',
    'server.teams.crowd_colors': 'expected one to four colors of the fans',
    'server.teams.custom_model': 'expected an uploaded model before choosing the custom model',
    'server.teams.duplicate_builtin': (
        'expected a registered submission to duplicate, found the built-in AI'
    ),
    'server.teams.editor': 'expected the JSON document of the editor, found {error}',
    'server.teams.folder.files': 'expected the files that the index of the folder lists',
    'server.teams.folder.index': 'expected the index of a submission folder, found {error}',
    'server.teams.folder.index_list': (
        'expected the index of a submission folder, a list of its files'
    ),
    'server.teams.folder.short': 'expected the files of a submission folder, found too few bytes',
    'server.teams.hidden_numbers': (
        'expected hidden_numbers as a list of model names, found {value}'
    ),
    'server.teams.image_size': 'expected an image of at most 8 MB, found {size} bytes',
    'server.teams.image_type': 'expected a PNG, JPEG or WebP image',
    'server.teams.model.binary': 'expected a binary glTF file, .glb, found other bytes',
    'server.teams.model.body': (
        'expected a bone for the joint body, the pelvis, which every rig has'
    ),
    'server.teams.model.bones': 'expected bones of the model',
    'server.teams.model.joints': 'expected the joints as names of bones by joint, found {joints}',
    'server.teams.model.json': 'expected the JSON chunk of a glTF file, found {error}',
    'server.teams.model.json_first': 'expected a binary glTF 2.0 file with its JSON chunk first',
    'server.teams.model.json_object': 'expected the JSON chunk of a glTF file to hold an object',
    'server.teams.model.limits': 'expected a model of the limits with a joint for body',
    'server.teams.model.link': 'expected a self-contained model, found a link to {uri}',
    'server.teams.model.missing_bones': 'expected bones of the model, found {bones}',
    'server.teams.model.rigged': 'expected a rigged model, a glTF file with a skin, found none',
    'server.teams.model.size': 'expected a model of at most 30 MB, found {size} bytes',
    'server.teams.model.too_large': 'expected a model of at most 30 MB',
    'server.teams.model.unknown_joints': "expected joints of GRF's skeleton, found {joints}",
    'server.teams.name': 'expected a team name with at least one character',
    'server.teams.player': 'expected player {index} as a dictionary, found {value}',
    'server.teams.player_entry': 'expected an entry of a player, found {key}',
    'server.teams.player_name': 'expected a name of at most 24 characters, found {name}',
    'server.teams.players': 'expected at most {count} player entries, found {value}',
    'server.teams.scenario_format': 'expected a scenario of {format} for {team}, found {scenario}',
    'server.teams.shirt_number': 'expected a shirt number from 0 to 99, found {number}',
    'server.teams.sound_size': 'expected a sound of at most 2 MB, found {size} bytes',
    'server.teams.sound_type': 'expected an Ogg, MP3 or WAV sound',
    'server.teams.sound_damaged': (
        'expected a whole {kind} sound, the file ends early or holds no sound'
    ),
    'server.teams.style': 'expected a style as a dictionary, found {value}',
    'server.teams.style_entry': 'expected an entry of a style, found {key}',
    'server.teams.style_part': 'expected a part of {key}, found {part}',
    'server.teams.style_part_object': 'expected {key} as a dictionary, found {value}',
    'server.teams.submission.kind': (
        'expected a submission folder, a .py file or a .tar.gz or .zip archive, found {filename}'
    ),
    'server.teams.submission.main_folder': (
        'expected {main} in the folder {folder}, as Kaggle requires'
    ),
    'server.teams.submission.main_top': (
        'expected {main} at the top of the submission, as Kaggle requires'
    ),
    'server.teams.submission.size': 'expected a submission of at most 100 MB, found {size} bytes',
    'server.teams.submission.unpack': 'expected a submission whose files unpack, found {error}',
    'server.teams.unknown': 'expected a team of the registry, found {identifier}',
    'server.teams.unknown_kaggle': 'expected a Kaggle team of the registry, found {identifier}',
    'server.tournament.ability': 'expected an ability from 0 to 1, found {ability}',
    'server.tournament.best_places': 'stage {stage} names best places without a position',
    'server.tournament.bracket_byes': (
        'a bracket of {size} with byes needs from {lowest} to {size} entrants, and {count} '
        'enter {where}'
    ),
    'server.tournament.bracket_play_in': (
        'a bracket of {size} with a play-in round needs from {size} to {highest} entrants, and '
        '{count} enter {where}'
    ),
    'server.tournament.bracket_power': 'expected a bracket size of {where} that is a power of two',
    'server.tournament.cancel_state': (
        'expected a tournament that runs or stopped, found it {state}'
    ),
    'server.tournament.cannot_play': '{entrant} cannot play {scenario} in stage {stage}, {reason}',
    'server.tournament.cards': 'expected cards as two pairs of counts, found {cards}',
    'server.tournament.choice': 'expected {name} from {choices}, found {value}',
    'server.tournament.count': 'expected {name} from {lowest} to {highest}, found {value}',
    'server.tournament.defaults': 'expected the defaults as an object',
    'server.tournament.description': 'expected a description of at most 400 characters',
    'server.tournament.double_byes': 'a double elimination bracket fills with byes, in {where}',
    'server.tournament.ended': 'expected a tournament that has ended, cancel it first',
    'server.tournament.entrant_fields': 'entrant {entrant} has unknown fields {fields}',
    'server.tournament.entrant_object': 'expected entrant {entrant} as an object, found {value}',
    'server.tournament.entrant_team': (
        'expected a registered team for entrant {entrant}, found {team}, the built-in AI '
        'enters with the kind builtin'
    ),
    'server.tournament.entrants': 'expected from 2 to {most} entrants, found {count}',
    'server.tournament.flag': 'expected {setting} of {where} as true or false',
    'server.tournament.foreign': (
        'stopped, since this install did not write its file, resume it to play its matches'
    ),
    'server.tournament.group_minimum': (
        'every group of {where} needs at least 2 entrants, and {count} entrants make groups of '
        '{sizes}'
    ),
    'server.tournament.group_sizes': 'expected group sizes as a list of counts in {where}',
    'server.tournament.group_total': (
        'the group sizes of {where} hold {total} entrants, and {count} enter it'
    ),
    'server.tournament.groups_advance': (
        'the groups of {where} send {advance} on, by qualifiers and best places'
    ),
    'server.tournament.groups_few': 'the groups of {where} send fewer than 2 entrants on',
    'server.tournament.knockout_advance': (
        'the knockout of {where} stops at {until}, so {until} advance'
    ),
    'server.tournament.knockout_stop': (
        'expected the knockout of {where} to stop at a power of two below {size}'
    ),
    'server.tournament.label.builtin': 'Built-in AI',
    'server.tournament.label.builtin_ability': 'Built-in AI {ability}',
    'server.tournament.label.challenge': 'Challenge {number}',
    'server.tournament.label.challenges': 'Challenges',
    'server.tournament.label.decider': '{match}, decider',
    'server.tournament.label.final': 'Final',
    'server.tournament.label.grand_final': 'Grand final',
    'server.tournament.label.grand_final_reset': 'Grand final, deciding match',
    'server.tournament.label.group': 'Group {group}',
    'server.tournament.label.group_matchday': 'Group {group}, matchday {number}',
    'server.tournament.label.ladder_tie': 'Round {round}, places {upper} and {lower}',
    'server.tournament.label.lap': 'Lap {number}',
    'server.tournament.label.leg': '{match}, leg {number}',
    'server.tournament.label.loser_of': 'Loser of {match}',
    'server.tournament.label.losers_final': 'Losers final',
    'server.tournament.label.losers_round': 'Losers round {number}',
    'server.tournament.label.matchday': 'Matchday {number}',
    'server.tournament.label.numbered': '{name} {number}',
    'server.tournament.label.play_in': 'Play-in {number}',
    'server.tournament.label.play_in_round': 'Play-in round',
    'server.tournament.label.quarter_final': 'Quarter-final {number}',
    'server.tournament.label.quarter_finals': 'Quarter-finals',
    'server.tournament.label.replay': '{match}, replay',
    'server.tournament.label.round': 'Round {number}',
    'server.tournament.label.round_of': 'Round of {count}',
    'server.tournament.label.round_of_tie': 'Round of {count}, tie {number}',
    'server.tournament.label.semi_final': 'Semi-final {number}',
    'server.tournament.label.semi_finals': 'Semi-finals',
    'server.tournament.label.stage.cup': 'Cup',
    'server.tournament.label.stage.double_elimination': 'Double elimination',
    'server.tournament.label.stage.gauntlet': 'Gauntlet',
    'server.tournament.label.stage.group_stage': 'Group stage',
    'server.tournament.label.stage.groups': 'Groups',
    'server.tournament.label.stage.king_of_the_hill': 'King of the hill',
    'server.tournament.label.stage.knockout': 'Knockout',
    'server.tournament.label.stage.knockout_stage': 'Knockout stage',
    'server.tournament.label.stage.ladder': 'Ladder',
    'server.tournament.label.stage.league': 'League',
    'server.tournament.label.stage.league_phase': 'League phase',
    'server.tournament.label.stage.playoffs': 'Playoffs',
    'server.tournament.label.stage.regular_season': 'Regular season',
    'server.tournament.label.stage.round_robin': 'Round robin',
    'server.tournament.label.stage.swiss': 'Swiss',
    'server.tournament.label.step': 'Step {number}',
    'server.tournament.label.third_place': 'Third place match',
    'server.tournament.label.tie': '{round}, tie {number}',
    'server.tournament.label.title': '{tournament}, {match}, {home} against {away}',
    'server.tournament.label.tournament': 'Tournament',
    'server.tournament.label.winner_of': 'Winner of {match}',
    'server.tournament.label.winners_final': 'Winners final',
    'server.tournament.label.winners_round': 'Winners round {number}',
    'server.tournament.length': (
        'expected a length from {lowest} to {highest} steps, found {length}'
    ),
    'server.tournament.list': 'expected {name} as a list without repeats, found {value}',
    'server.tournament.match_failed': '{label} failed, {error}',
    'server.tournament.match_failed_more': (
        '{label} failed, {error}, and {count} more matches failed'
    ),
    'server.tournament.match_failed_one_more': '{label} failed, {error}, and 1 more match failed',
    'server.tournament.match_key': 'expected a match of the tournament still to play, found {key}',
    'server.tournament.no_frame': 'the recording {identifier} holds no frame',
    'server.tournament.no_result': 'the match gave no result',
    'server.tournament.note.early': (
        'The game ended before full time, so the match waits to be played again.'
    ),
    'server.tournament.note.failed': (
        'The game stopped, {error}. Award the match to either side, or play it again.'
    ),
    'server.tournament.note.gone': 'The game of this match ended without a result.',
    'server.tournament.note.unreadable': 'The result could not be read, {error}',
    'server.tournament.object': 'expected the tournament as an object',
    'server.tournament.other_process': 'the tournament belongs to another process',
    'server.tournament.other_process_change': (
        'the tournament runs in another process, {owner}, which can change it'
    ),
    'server.tournament.other_process_runs': 'the tournament runs in another process, {owner}',
    'server.tournament.other_process_silent': (
        'the process {owner} that runs the tournament did not answer, send the change to its '
        'server as {route}'
    ),
    'server.tournament.people_page': 'the matches of people play on the page of the server',
    'server.tournament.person_match': 'expected a match of a person',
    'server.tournament.person_names': 'expected a name for each person',
    'server.tournament.playing': 'the match is playing now',
    'server.tournament.points': 'expected points for a win, draw and loss, found {points}',
    'server.tournament.preset': 'expected a preset from {presets}, found {name}',
    'server.tournament.preset_name': (
        'expected a preset name of small letters, digits, dashes and underscores that names no '
        'shipped preset, found {name}'
    ),
    'server.tournament.preset_object': 'expected a preset as an object',
    'server.tournament.preset_settings': 'the preset has unknown settings {settings}',
    'server.tournament.qualifiers': (
        'expected the qualifiers of stage {stage} as a count or one count a group'
    ),
    'server.tournament.rating': 'expected a rating from 0 to 10000, found {rating}',
    'server.tournament.recording': 'expected the recording of a result as text, found {match}',
    'server.tournament.result': 'expected a result with a score, found {result}',
    'server.tournament.running': 'expected a running tournament, found it {state}',
    'server.tournament.score': 'expected a score of two counts, found {score}',
    'server.tournament.settings': 'the tournament has unknown settings {settings}',
    'server.tournament.stage_ability': 'expected the ability of {where} from 0 to 1',
    'server.tournament.stage_entrants': '{where} needs at least 2 entrants, and {count} reach it',
    'server.tournament.stage_name': 'expected the name of {where} as text',
    'server.tournament.stage_object': 'expected stage {stage} as an object, found {value}',
    'server.tournament.stage_scenario': (
        'expected a shipped scenario for stage {stage}, found {scenario}'
    ),
    'server.tournament.stage_settings': 'stage {stage} has unknown settings {settings}',
    'server.tournament.stages': 'expected from 1 to {most} stages',
    'server.tournament.stopped': 'expected a stopped tournament, found it {state}',
    'server.tournament.swiss': 'no Swiss pairing without a rematch exists for this round',
    'server.tournament.teammates': 'expected registered teammates, found {mates}',
    'server.tournament.text': 'expected {name} as text, found {value}',
    'server.tournament.text_length': 'expected {name} of 1 to {most} characters, found {value}',
    'server.tournament.twice': '{team} is entered twice',
    'server.tournament.unknown': 'no such tournament',
    'server.tournament.unknown_identifier': 'expected a tournament, found {identifier}',
    'server.tournament.waiting': 'waiting for cuju render tournament run',
    'server.tournament.winner': 'expected the winning side as home or away, found {side}',
    'server.trash.unknown': 'no such recording in the Trash',
    'server.tutorial.done': 'expected done as a list of lessons from {known}, found {done}',
    'server.tutorial.lesson': 'expected a lesson from {lessons}, found {identifier}',
    'server.tutorial.unknown': 'expected lessons from {known}, found {unknown}',
    'server.video.annotations': 'expected annotations as true or false, found {annotations}',
    'server.video.busy': 'an export already runs, wait for it or cancel it',
    'server.video.exit': 'the export ended with exit code {code}',
    'server.video.exit_detail': 'the export ended with exit code {code}, {detail}',
    'server.video.fields': 'expected the fields {known}, found {unknown}',
    'server.video.length': 'expected at most {most} seconds of video, found {length} seconds',
    'server.video.range': 'expected an end after the start, found {start} to {end}',
    'server.video.rate': (
        'expected a frame rate of whole frames a second from 1 to {most}, found {fps}'
    ),
    'server.video.safe': 'expected the safe area as text or a percentage, found {safe}',
    'server.video.scale': 'expected the scale of the graphics as a number, found {graphics}',
    'server.video.score': 'expected score as true or false, found {score}',
    'server.video.seconds': 'expected {name} as seconds from 0, found {value}',
    'server.video.unknown': 'no such video',
    'server.video.unknown_match': 'expected a recording of the library, found {match}',
}


def text(message_id: str, /, **values: Any) -> str:
    """Returns the English text of a message with its placeholders filled from `values`.

    A value is text, or a label that `label` returns, which reads as its English text.

    Raises:
        KeyError: If the id is unknown, or a placeholder of its template has no value.
    """
    template = MESSAGES[message_id]
    return _PLACEHOLDER.sub(lambda match: _shown(values[match.group(1)]), template)


def _shown(value: Any) -> str:
    """Returns the English text of a value of a message, a label or anything else as text."""
    if isinstance(value, dict) and isinstance(value.get('text'), str):
        return value['text']
    return str(value)


def _value(value: Any) -> Any:
    """Returns a value of a message as it travels, a label as it is and anything else as text."""
    if isinstance(value, dict) and isinstance(value.get('text'), str):
        return value
    return str(value)


def label(message_id: str, /, **values: Any) -> dict[str, Any]:
    """Returns a name or a label that cuju makes, such as a round or the built-in AI, as data.

    The label holds the message `id`, its English `text` and its `values`, so the page shows it
    in its own language while the command line and the files read the English text. A value may
    itself be a label, such as the name of an entrant inside the title of a match.

    Raises:
        KeyError: If the id is unknown, or a placeholder of its template has no value.
    """
    kept = {key: _value(value) for key, value in values.items()}
    return {'id': message_id, 'text': text(message_id, **kept), 'values': kept}


def scenario(name: str) -> dict[str, Any]:
    """Returns a scenario as a value of a message, which the page shows by its name there."""
    return {'kind': 'scenario', 'name': str(name), 'text': str(name)}


def named(field: str, value: dict[str, Any] | str | None) -> dict[str, Any]:
    """Returns the fields of a name in an answer, `field` with its English text and, for a label,
    `field_id` and `field_values` beside it, as the page's `serverText` reads them.

    A name that a person gave is text and travels alone.
    """
    if isinstance(value, dict) and isinstance(value.get('text'), str):
        return {
            field: value['text'],
            f'{field}_id': value.get('id'),
            f'{field}_values': dict(value.get('values') or {}),
        }
    return {field: value}


# The kinds of value that the page shows by a name of its own, a scenario and a challenge.
_KINDS = ('scenario', 'challenge')


def valid_label(value: Any) -> bool:
    """Returns whether a stored value is a label of a known message, its values text or labels."""
    if not isinstance(value, dict) or not isinstance(value.get('text'), str):
        return False
    if 'kind' in value:
        return value['kind'] in _KINDS and isinstance(value.get('name'), str)
    values = value.get('values')
    return (
        value.get('id') in MESSAGES
        and isinstance(values, dict)
        and all(isinstance(item, str) or valid_label(item) for item in values.values())
        and placeholders(MESSAGES[value['id']]) <= set(values)
    )


def placeholders(template: str) -> set[str]:
    """Returns the names of the placeholders of a template."""
    return set(_PLACEHOLDER.findall(template))


# The classes that only add the id of a message to another exception, by the module and name
# they were defined with.
_WRAPPERS: dict[tuple[str, str], type] = {}


def _stamp(cls: type) -> None:
    """Gives a class that only adds an id the module and name of the exception it stands for."""
    for base in cls.__mro__[1:]:
        if base is Message or base.__dict__.get('_wrapper'):
            continue
        cls.__module__, cls.__qualname__, cls.__name__ = (
            base.__module__,
            base.__qualname__,
            base.__name__,
        )
        return


def public_names() -> None:
    """Stamps every class that only adds an id again, after the public classes took their module.

    `cuju.render` gives its public errors its own name as their module once it has imported
    them, so a class defined before then takes the public name here.
    """
    for cls in _WRAPPERS.values():
        _stamp(cls)


def _rebuild(defined: tuple[str, str], message_id: str, values: dict[str, Any]) -> BaseException:
    """Returns the exception that `Message.__reduce__` pickled, of the class it was defined as."""
    module, name = defined
    importlib.import_module(module)
    cls = _WRAPPERS.get(defined) or getattr(sys.modules[module], name)
    return cls(message_id, **values)


class Message:
    """A mixin of exceptions whose text is a message of `MESSAGES`.

    The exception reads as the English text, and carries the id in `message_id` and the values of
    its placeholders, each as text, in `values`. A class that only adds the id to another
    exception, which sets `_wrapper`, reads as that exception in a traceback and in its `repr`,
    such as `cuju.errors.ArgumentError`, and an `except` of either class catches it.
    """

    # A class that only adds the id to another exception names that exception in an answer.
    _wrapper = True
    message_id: str
    values: dict[str, str]

    def __init_subclass__(cls, **options: Any) -> None:
        super().__init_subclass__(**options)
        if cls.__dict__.get('_wrapper'):
            cls._defined = (cls.__module__, cls.__qualname__)
            _WRAPPERS[cls._defined] = cls
            _stamp(cls)

    def __init__(self, message_id: str, /, **values: Any) -> None:
        self.message_id = message_id
        self.values = {key: _value(value) for key, value in values.items()}
        super().__init__(text(message_id, **self.values))

    def __reduce__(self) -> Any:
        cls = type(self)
        defined = cls.__dict__.get('_defined') or (cls.__module__, cls.__qualname__)
        return (_rebuild, (defined, self.message_id, self.values))


class MessageError(Message, ArgumentError):
    """An `ArgumentError` whose text is a message of `MESSAGES`, which the page translates."""

    _wrapper = True


def argument_error(error: BaseException) -> ArgumentError:
    """Returns an `ArgumentError` with the text of `error`, and its id when it carries one."""
    message_id = getattr(error, 'message_id', None)
    if isinstance(message_id, str) and message_id in MESSAGES:
        return MessageError(message_id, **getattr(error, 'values', {}))
    return ArgumentError(str(error))


def kind(error: BaseException) -> str:
    """Returns the name of the exception that an answer shows, without the classes of ids.

    A `MessageError` reads as the `ArgumentError` it stands for, so an answer of the form
    `ArgumentError: ...` reads as before.
    """
    for cls in type(error).__mro__:
        if cls is Message or cls.__dict__.get('_wrapper'):
            continue
        return cls.__name__
    return type(error).__name__


def described(error: BaseException) -> str:
    """Returns the text `Kind: message` of an error, as answers and reports show it."""
    return f'{kind(error)}: {error}'


def fields(message_id: str, /, **values: Any) -> dict[str, Any]:
    """Returns the error fields of an answer or an entry for a message of `MESSAGES`."""
    shown = {key: _value(value) for key, value in values.items()}
    return {'error': text(message_id, **shown), 'error_id': message_id, 'error_values': shown}


def error_fields(error: BaseException, shown: str | None = None) -> dict[str, Any]:
    """Returns the error fields for an exception, with its id when it carries one.

    Args:
        error: The exception.
        shown: The text of the answer, by default `str(error)`.
    """
    result: dict[str, Any] = {'error': str(error) if shown is None else shown}
    message_id = getattr(error, 'message_id', None)
    if isinstance(message_id, str) and message_id in MESSAGES:
        result['error_id'] = message_id
        result['error_values'] = dict(getattr(error, 'values', {}) or {})
    return result


def id_fields(error: BaseException) -> dict[str, Any]:
    """Returns `error_id` and `error_values` of an exception that carries an id, else nothing."""
    found = error_fields(error)
    found.pop('error')
    return found


def entry_fields(error: BaseException | str | None, shown: str | None = None) -> dict[str, Any]:
    """Returns the error fields of an entry, always all three, `None` where it has none.

    Args:
        error: The exception, or a text without an id, or `None` for no error.
        shown: The text that the entry shows for an exception, by default `str(error)`.
    """
    result: dict[str, Any] = {'error': None, 'error_id': None, 'error_values': None}
    if isinstance(error, BaseException):
        result.update(error_fields(error, shown))
    elif error is not None:
        result['error'] = error
    return result


def exit_fields(message_id: str, code: Any, detail: str = '') -> dict[str, Any]:
    """Returns the error fields of a child process that ended with `code`.

    The message `message_id` names the exit code, and `message_id` with `_detail` added names the
    last lines that the process wrote as well, when it wrote any.
    """
    if detail:
        return fields(f'{message_id}_detail', code=code, detail=detail)
    return fields(message_id, code=code)


def report_fields(report: dict[str, Any]) -> dict[str, Any]:
    """Returns the error fields of an entry from the report of a child process.

    The id and values pass on only when they name a message of `MESSAGES` with a text value for
    each of its placeholders, so a report of another version leaves its error without an id.
    """
    error = report.get('error')
    result: dict[str, Any] = {
        'error': error if isinstance(error, str) else None,
        'error_id': None,
        'error_values': None,
    }
    message_id, values = report.get('error_id'), report.get('error_values')
    if (
        isinstance(error, str)
        and isinstance(message_id, str)
        and message_id in MESSAGES
        and isinstance(values, dict)
        and all(isinstance(value, str) or valid_label(value) for value in values.values())
        and placeholders(MESSAGES[message_id]) <= set(values)
    ):
        result.update(error_id=message_id, error_values=dict(values))
    return result


def compare(messages: dict[str, Any]) -> list[str]:
    """Returns the differences between `MESSAGES` and the `server.` messages of a language file.

    Args:
        messages: The messages of a language file, such as the parsed `web/languages/en.json`.
            For English each text must equal the registry's, and for another language each
            message must hold the same placeholders.

    Returns:
        One line for each id missing from either side, each text that differs from the English,
        and each placeholder that differs, empty when they agree.
    """
    english = messages.get('@language', {}).get('code', 'en') == 'en'
    found = {key: value for key, value in messages.items() if key.startswith('server.')}
    problems = [f'missing {key}' for key in MESSAGES if key not in found]
    problems += [f'unknown {key}' for key in found if key not in MESSAGES]
    for key, template in MESSAGES.items():
        if key not in found:
            continue
        value = found[key]
        if not isinstance(value, str):
            problems.append(f'{key} is not a plain text')
        elif english and value != template:
            problems.append(f'{key} reads {value!r}, the registry {template!r}')
        elif placeholders(value) != placeholders(template):
            problems.append(f'{key} has the placeholders {sorted(placeholders(value))}')
    return problems
