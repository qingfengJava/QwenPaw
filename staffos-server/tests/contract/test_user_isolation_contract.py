# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""M1 exit-gate contract: cross-user isolation across every storage plane.

For any two accounts A and B, none of A's chats, session state files,
scroll history rows, or memory vault contents may be visible to B — via
the repository API, the session store, or history/memory recall.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.memoryspace import MemorySpace
from qwenpaw.agents.context.types import LogEntry
from qwenpaw.app.chats.api import get_owned_chat
from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.repo.json_repo import JsonChatRepository
from qwenpaw.app.chats.session import SafeJSONSession


def _request_as(username: str):
    return SimpleNamespace(state=SimpleNamespace(user=username))


class TestChatPlaneIsolation:
    """chats.json rows are owned; another user can never see them."""

    @pytest.fixture
    def mgr(self, tmp_path: Path) -> ChatManager:
        return ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))

    async def test_list_chats_scoped_per_user(self, mgr: ChatManager) -> None:
        await mgr.get_or_create_chat("console:shared", "alice")
        await mgr.get_or_create_chat("console:bob-dm", "bob")

        alice_ids = {c.id for c in await mgr.list_chats(user_id="alice")}
        bob_ids = {c.id for c in await mgr.list_chats(user_id="bob")}

        assert alice_ids
        assert bob_ids
        assert alice_ids.isdisjoint(bob_ids)

    async def test_foreign_access_returns_404(self, mgr: ChatManager) -> None:
        chat = await mgr.get_or_create_chat("console:a", "alice")
        with pytest.raises(HTTPException) as exc_info:
            await get_owned_chat(chat.id, _request_as("bob"), mgr)
        assert exc_info.value.status_code == 404


class TestSessionPlaneIsolation:
    """Session state files are keyed by (owner, session_id)."""

    async def test_same_session_id_writes_separate_files(
        self,
        tmp_path: Path,
    ) -> None:
        session = SafeJSONSession(str(tmp_path / "sessions"))
        await session.update_session_state(
            "console:dm",
            "k",
            "alice-value",
            user_id="alice",
            channel="console",
        )
        await session.update_session_state(
            "console:dm",
            "k",
            "bob-value",
            user_id="bob",
            channel="console",
        )
        alice = await session.get_session_state_dict(
            "console:dm",
            "alice",
            "console",
        )
        bob = await session.get_session_state_dict(
            "console:dm",
            "bob",
            "console",
        )
        assert alice.get("k") == "alice-value"
        assert bob.get("k") == "bob-value"


class TestHistoryPlaneIsolation:
    """Scroll history recall is owner-scoped even inside one session."""

    @pytest.fixture
    def db_path(self, tmp_path: Path) -> Path:
        store = HistoryStore(tmp_path / "history.db")
        try:
            for owner, marker in (("alice", "aaa-secret"), ("bob", "bbb-secret")):
                store.append(
                    session_id="dingtalk:group",
                    agent_id="a1",
                    owner_id=owner,
                    entry=LogEntry(
                        kind="context_msg",
                        role="user",
                        content=f"{marker} from {owner}",
                    ),
                    dedup_key=marker,
                )
        finally:
            store.close()
        return tmp_path / "history.db"

    def _search(self, db_path: Path, owner: str) -> list[str]:
        # Cross-session recall: no live session, so the active-turn
        # exclusion does not apply (the current turn is never searchable
        # by design).
        ms = MemorySpace(
            history_db_path=db_path,
            agent_id="a1",
            owner_id=owner,
        )
        try:
            hits = ms.search("secret", k=20)
            return [h.get("content", "") for h in hits if not h.get("_notice")]
        finally:
            ms._conn.close()

    def test_owner_search_returns_only_own_rows(self, db_path: Path) -> None:
        alice_hits = self._search(db_path, "alice")
        bob_hits = self._search(db_path, "bob")
        assert any("aaa-secret" in c for c in alice_hits)
        assert not any("bbb-secret" in c for c in alice_hits)
        assert any("bbb-secret" in c for c in bob_hits)
        assert not any("aaa-secret" in c for c in bob_hits)

    def test_owner_session_read_returns_only_own_rows(
        self,
        db_path: Path,
    ) -> None:
        ms = MemorySpace(
            history_db_path=db_path,
            session_id="dingtalk:group",
            agent_id="a1",
            owner_id="alice",
        )
        try:
            rows = ms.session("dingtalk:group")
            contents = [r.get("content", "") for r in rows]
            assert any("aaa-secret" in c for c in contents)
            assert not any("bbb-secret" in c for c in contents)
        finally:
            ms._conn.close()


class TestMemoryPlaneIsolation:
    """Per-user memory views map owners to distinct vault directories."""

    def test_distinct_vaults_per_owner(self, tmp_path: Path) -> None:
        from qwenpaw.agents.memory.reme_light_memory_manager import (
            ReMeLightMemoryManager,
        )

        shared = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
        shared.working_dir = str(tmp_path)
        shared.agent_id = "a1"
        shared._owner_id = None
        shared._user_managers = {}
        shared._user_managers_lock = asyncio.Lock()

        dir_a = shared._user_vault_dir("alice")
        dir_b = shared._user_vault_dir("bob")
        assert dir_a != dir_b
        assert "alice" in dir_a and "bob" in dir_b
