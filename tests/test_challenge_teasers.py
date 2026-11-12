# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks the teasers and stills of the challenge cards and the manifest that lists them."""

import hashlib
import json
from pathlib import Path

import cuju.render
from cuju.render._playing import challenges as _challenges
from support.common import _shipped_language, _translation

FOLDER = Path(cuju.render.__file__).parent / 'web' / 'assets' / 'challenges'
# The size aimed at for one teaser, and for the whole folder.
TEASER_BYTES = 250_000
FOLDER_BYTES = 4_000_000


def manifest():
    return json.loads((FOLDER / 'manifest.json').read_text(encoding='utf-8'))


def test_the_manifest_lists_every_challenge_in_the_catalog_order():
    document = manifest()
    assert document['version'] == 1
    assert document['generator'] == 'ci/make_challenge_teasers.py'
    assert document['size'] == [480, 270]
    assert list(document['challenges']) == [entry['id'] for entry in _challenges.CATALOG]


def test_every_file_of_the_manifest_exists_with_its_hash_and_size():
    total = 0
    for identifier, entry in manifest()['challenges'].items():
        for kind, suffix in (('teaser', '.mp4'), ('still', '.webp')):
            name = entry[kind]
            assert name == f'{identifier}{suffix}', name
            path = FOLDER / name
            data = path.read_bytes()
            assert hashlib.sha256(data).hexdigest() == entry[f'{kind}_sha256'], name
            assert len(data) == entry[f'{kind}_bytes'], name
            total += len(data)
        assert entry['teaser_bytes'] <= TEASER_BYTES, identifier
    assert total <= FOLDER_BYTES
    entries = manifest()['challenges'].values()
    listed = {entry[kind] for entry in entries for kind in ('teaser', 'still')}
    assert {path.name for path in FOLDER.iterdir()} == listed | {'manifest.json'}


def test_the_manifest_records_how_each_teaser_was_chosen():
    for identifier, entry in manifest()['challenges'].items():
        seeds = _challenges.seeds(identifier, manifest()['search'])
        assert entry['attempts'], identifier
        for attempt in entry['attempts']:
            assert attempt['policy'] in ('builtin', 'scripted')
            assert seeds[attempt['search_index']] == attempt['seed']
            assert attempt['start'] <= attempt['goal_seconds'] <= attempt['end']
        assert 0 < entry['seconds'] <= 5.0


def test_every_kind_and_difficulty_has_words_in_english_and_the_portuguese_draft():
    for code, words in (('en', _shipped_language('en')), ('pt-BR', _translation('pt-BR'))):
        for entry in _challenges.CATALOG:
            assert entry['category'] in _challenges.CATEGORIES
            assert entry['difficulty'] in _challenges.DIFFICULTIES
            assert f'challenges.category.{entry["category"]}' in words, code
            assert f'challenges.difficulty.{entry["difficulty"]}' in words, code
