# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the M3-5 governor assembly cache.

``AgentBuilder._init_governor`` runs per request; the started governor
depends only on (workspace_dir, coding_project_dir) + policy.yaml, so it
is cached and validated against the policy file mtime.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from qwenpaw.runtime.builder import (
    AgentBuilder,
    _governor_cache,
    reset_governor_cache,
)


@pytest.fixture(autouse=True)
def _isolate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Redirect the governance dir into tmp and reset the cache."""
    monkeypatch.setattr(
        "qwenpaw.governance.resource_governor.WORKING_DIR",
        tmp_path,
    )
    reset_governor_cache()
    yield
    reset_governor_cache()


def _policy_path(governor) -> Path:
    return governor._policy_path


def test_same_workspace_returns_cached_instance(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    first = AgentBuilder._init_governor(str(ws))
    second = AgentBuilder._init_governor(str(ws))
    assert first is not None
    assert first is second
    assert len(_governor_cache) == 1


def test_policy_mtime_change_rebuilds(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    first = AgentBuilder._init_governor(str(ws))
    assert first is not None

    # Simulate an external policy update (e.g. add_rule persisting).
    policy_path = _policy_path(first)
    assert policy_path.exists()
    with open(policy_path, "a", encoding="utf-8") as f:
        f.write("# touched\n")
    os.utime(policy_path, (1_900_000_000, 1_900_000_000))

    second = AgentBuilder._init_governor(str(ws))
    assert second is not None
    assert second is not first


def test_project_dir_part_of_cache_key(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    plain = AgentBuilder._init_governor(str(ws))
    with_project = AgentBuilder._init_governor(str(ws), str(tmp_path))
    assert plain is not None and with_project is not None
    assert plain is not with_project
    assert len(_governor_cache) == 2


def test_failed_start_is_not_cached(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from qwenpaw.governance.resource_governor import ResourceGovernor

    monkeypatch.setattr(
        ResourceGovernor,
        "start",
        lambda self: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    ws = tmp_path / "ws"
    ws.mkdir()
    assert AgentBuilder._init_governor(str(ws)) is None
    assert not _governor_cache


def test_cache_is_bounded(tmp_path: Path) -> None:
    from qwenpaw.runtime import builder

    monkey = builder._GOVERNOR_CACHE_MAX
    try:
        builder._GOVERNOR_CACHE_MAX = 3
        for i in range(5):
            ws = tmp_path / f"ws{i}"
            ws.mkdir()
            AgentBuilder._init_governor(str(ws))
        assert len(_governor_cache) <= 3
    finally:
        builder._GOVERNOR_CACHE_MAX = monkey
