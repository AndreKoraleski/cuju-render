# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Checks how cuju-render joins cuju, its version, its requirement of cuju and the files it owns."""

import importlib.metadata
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import cuju
import cuju.render
from cuju.render import _version

ROOT = Path(__file__).resolve().parents[1]
MIN_CUJU = '0.2.1'


def numbers(version):
    return tuple(int(part) for part in re.match(r'(\d+)\.(\d+)\.(\d+)', version).groups())


def installed():
    """Returns the distribution of cuju-render, or None when the tests run from the source."""
    try:
        distribution = importlib.metadata.distribution('cuju-render')
    except importlib.metadata.PackageNotFoundError:
        return None
    if os.path.abspath(cuju.render.__file__).startswith(str(ROOT)):
        return None
    return distribution


def test_the_renderer_is_a_module_of_the_package_cuju():
    folder = Path(cuju.render.__file__).resolve().parent.parent
    assert folder in [Path(path).resolve() for path in cuju.__path__]
    assert (Path(cuju.render.__file__).parent / 'web' / 'index.html').is_file()


def test_the_version_has_one_source():
    assert re.fullmatch(r'\d+\.\d+\.\d+([a-z]+\d+)?', _version.__version__)
    pyproject = ROOT / 'pyproject.toml'
    if pyproject.is_file():
        text = pyproject.read_text(encoding='utf-8')
        assert 'dynamic = ["version"]' in text
        assert 'path = "src/cuju/render/_version.py"' in text
        assert not re.search(r'^version = ', text, re.MULTILINE)
    distribution = installed()
    if distribution is not None:
        assert distribution.version == _version.__version__


def test_the_installed_cuju_fits_the_requirement():
    assert numbers(cuju.__version__) >= numbers(MIN_CUJU)
    distribution = installed()
    if distribution is None:
        pytest.skip('the renderer runs from its source')
    requires = [r for r in distribution.requires or [] if re.match(r'cuju\b(?!-)', r)]
    assert len(requires) == 1 and f'>={MIN_CUJU}' in requires[0].replace(' ', '')


def test_the_distribution_owns_the_folder_of_the_renderer_alone():
    distribution = installed()
    if distribution is None:
        pytest.skip('the renderer runs from its source')
    names = [str(file).replace('\\', '/') for file in distribution.files or []]
    owned = [name for name in names if '.dist-info/' not in name and not name.startswith('..')]
    assert owned and all(name.startswith('cuju/render/') for name in owned)
    assert 'cuju/__init__.py' not in names


def test_commands_that_step_no_batch_start_without_pytorch():
    # The check that cuju's own test_import made of the renderer's commands before the split.
    code = "import sys, cuju, cuju.render.__main__, cuju.state; print('torch' in sys.modules)"
    result = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=True,
        timeout=120,
    )
    assert result.stdout.split() == ['False']
