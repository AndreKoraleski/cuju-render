# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""The fixtures of the renderer's tests, which conftest.py hands every test."""

import pytest

from cuju.render._store import home as _home

__all__ = ['render_home']


@pytest.fixture
def render_home(tmp_path, monkeypatch):
    monkeypatch.setenv(_home.HOME_VARIABLE, str(tmp_path / 'render'))
    return tmp_path / 'render'
