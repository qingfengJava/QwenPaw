# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""M1 per-user memory isolation tests (ReMe Light backend).

The shared workspace manager keeps the legacy vault; ``user_view(owner)``
routes every data operation to ``<workspace>/users/<owner>/``, searches fall
back to the legacy vault only on a miss, and writes never touch it.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents.memory.reme_light_memory_manager import (
    NO_MEMORY_RESULTS,
    ReMeLightMemoryManager,
    UserMemoryView,
    _to_reme_session_id,
)


def _bare_shared(tmp_path: Path) -> ReMeLightMemoryManager:
    """A shared manager without a real ReMe app (construction-free)."""
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.working_dir = str(tmp_path)
    manager.agent_id = "a1"
    manager._owner_id = None
    manager._user_managers = {}
    manager._user_managers_lock = asyncio.Lock()
    manager._start_lock = asyncio.Lock()
    manager._reme = None
    return manager


def test_session_hash_scopes_owner(tmp_path: Path):
    legacy = _to_reme_session_id("session-1")
    assert legacy == _to_reme_session_id("session-1", "")
    alice = _to_reme_session_id("session-1", "alice")
    bob = _to_reme_session_id("session-1", "bob")
    assert alice != bob
    assert alice != legacy


def test_user_vault_dir_is_per_owner(tmp_path: Path):
    shared = _bare_shared(tmp_path)
    assert shared._user_vault_dir("alice").endswith(
        str(Path("users") / "alice"),
    )
    assert shared._user_vault_dir("alice") != shared._user_vault_dir("bob")


def test_user_vault_dir_rejects_traversal(tmp_path: Path):
    shared = _bare_shared(tmp_path)
    for bad in ("..", "", "."):
        with pytest.raises(ValueError):
            shared._user_vault_dir(bad)
    # Slashes are sanitized away, so "../.." degrades to an inert name.
    assert "/" not in shared._user_vault_dir("../..").rsplit("users", 1)[-1]


@pytest.mark.asyncio
async def test_view_summarize_uses_owner_vault(tmp_path: Path):
    """Writes route to a lazily-created per-user manager, never legacy."""
    shared = _bare_shared(tmp_path)
    view = shared.user_view("alice")

    result = await view.summarize([], session_id="s1")

    assert result == ""  # no ReMe app behind the test double
    um = shared._user_managers.get("alice")
    assert um is not None
    assert um._owner_id == "alice"
    assert um.working_dir.endswith(str(Path("users") / "alice"))


@pytest.mark.asyncio
async def test_view_search_falls_back_to_legacy_vault(tmp_path: Path):
    """A miss in the owner vault consults the legacy vault once."""
    shared = _bare_shared(tmp_path)
    view = shared.user_view("alice")

    um = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    um._owner_id = "alice"
    um._memory_search_impl = AsyncMock(return_value=SimpleNamespace(content=[]))
    shared._user_managers["alice"] = um
    shared._memory_search_impl = AsyncMock(return_value=SimpleNamespace(content=[]))

    await view.memory_search("anything")

    um._memory_search_impl.assert_awaited_once()
    shared._memory_search_impl.assert_awaited_once()


@pytest.mark.asyncio
async def test_view_search_skips_fallback_on_hit(tmp_path: Path):
    """A legacy fallback runs only when the owner vault has no answer."""
    from agentscope.message import TextBlock, ToolResultState
    from agentscope.tool import ToolChunk

    hit = ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text="found it")],
    )
    shared = _bare_shared(tmp_path)
    view = shared.user_view("alice")

    um = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    um._owner_id = "alice"
    um._memory_search_impl = AsyncMock(return_value=hit)
    shared._user_managers["alice"] = um
    shared._memory_search_impl = AsyncMock(return_value=hit)

    chunk = await view.memory_search("anything")

    assert chunk is hit
    shared._memory_search_impl.assert_not_awaited()


@pytest.mark.asyncio
async def test_view_search_empty_result_constant_falls_back(tmp_path: Path):
    """NO_MEMORY_RESULTS counts as a miss and triggers the fallback."""
    from agentscope.message import TextBlock, ToolResultState
    from agentscope.tool import ToolChunk

    empty = ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=NO_MEMORY_RESULTS)],
    )
    shared = _bare_shared(tmp_path)
    view = shared.user_view("alice")

    um = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    um._owner_id = "alice"
    um._memory_search_impl = AsyncMock(return_value=empty)
    shared._user_managers["alice"] = um
    shared._memory_search_impl = AsyncMock(return_value=empty)

    await view.memory_search("anything")

    shared._memory_search_impl.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_shuts_down_user_vaults(tmp_path: Path):
    """Closing the shared manager closes every per-user vault."""
    shared = _bare_shared(tmp_path)
    um = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    um._owner_id = "alice"
    um.close = AsyncMock(return_value=True)
    shared._user_managers["alice"] = um
    shared._lifecycle_writer_lock = asyncio.Lock()
    shared._lifecycle_condition = asyncio.Condition()
    shared._active_reme_jobs = 0
    shared._lifecycle_operation = None
    shared._shutdown_summarize_worker = AsyncMock(return_value=True)

    assert await shared.close() is True
    um.close.assert_awaited_once()
    assert shared._user_managers == {}


def test_view_delegates_config_reads(tmp_path: Path):
    """Prompt/config-style reads delegate to the shared manager."""
    shared = _bare_shared(tmp_path)
    shared.get_memory_prompt = lambda: "prompt-text"
    view = shared.user_view("alice")
    assert view.get_memory_prompt() == "prompt-text"
    assert view.agent_id == "a1"
    assert view.enabled is True
