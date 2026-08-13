# -*- coding: utf-8 -*-
"""Chat repository contract tests.

Every ``BaseChatRepository`` implementation must satisfy these contracts so
backends (JSON today, dual/PostgreSQL from the M2 milestone) stay
interchangeable behind ``qwenpaw.app.chats.factory.build_chat_repository``.
"""

from __future__ import annotations

from abc import abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from qwenpaw.app.chats.models import ChatSpec, ChatsFile
from qwenpaw.app.chats.repo.base import BaseChatRepository
from qwenpaw.app.chats.repo.json_repo import JsonChatRepository

from .. import BaseContractTest


def _spec(
    chat_id: str,
    session_id: str,
    user_id: str,
    channel: str = "console",
    **overrides,
) -> ChatSpec:
    """Build a minimal ChatSpec with deterministic identity fields."""
    return ChatSpec(
        id=chat_id,
        session_id=session_id,
        user_id=user_id,
        channel=channel,
        **overrides,
    )


class ChatRepositoryContractTest(BaseContractTest):
    """Contract: every chat repository backend behaves identically."""

    @abstractmethod
    def create_instance(self) -> BaseChatRepository:
        """Provide a repository backed by a fresh, empty storage."""

    # ------------------------------------------------------------------
    # load / save
    # ------------------------------------------------------------------

    async def test_load_returns_empty_chats_file_when_missing(
        self,
        instance: BaseChatRepository,
    ):
        cf = await instance.load()
        assert isinstance(cf, ChatsFile)
        assert cf.chats == []

    async def test_save_and_load_round_trip(
        self,
        instance: BaseChatRepository,
    ):
        spec = _spec("c1", "discord:alice", "alice", "discord")
        await instance.save(ChatsFile(version=1, chats=[spec]))

        loaded = await instance.load()
        assert [c.id for c in loaded.chats] == ["c1"]
        assert loaded.chats[0].user_id == "alice"

    async def test_two_instances_share_storage(
        self,
        instance: BaseChatRepository,
    ):
        # A second instance over the same backend must observe the first
        # instance's writes (no hidden per-instance cache).
        await instance.upsert_chat(_spec("c1", "s1", "alice"))
        other = self.create_instance()
        assert await other.get_chat("c1") is not None

    # ------------------------------------------------------------------
    # convenience operations
    # ------------------------------------------------------------------

    async def test_upsert_inserts_then_updates(
        self,
        instance: BaseChatRepository,
    ):
        await instance.upsert_chat(_spec("c1", "s1", "alice", name="first"))
        await instance.upsert_chat(_spec("c1", "s1", "alice", name="renamed"))

        chats = await instance.list_chats()
        assert len(chats) == 1
        assert chats[0].name == "renamed"

    async def test_get_chat_returns_none_for_missing(
        self,
        instance: BaseChatRepository,
    ):
        assert await instance.get_chat("missing") is None

    async def test_get_chat_by_id_matches_session_user_channel(
        self,
        instance: BaseChatRepository,
    ):
        await instance.upsert_chat(
            _spec("c1", "discord:alice", "alice", "discord"),
        )
        await instance.upsert_chat(
            _spec("c2", "discord:alice", "bob", "discord"),
        )

        hit = await instance.get_chat_by_id("discord:alice", "alice", "discord")
        assert hit is not None
        assert hit.id == "c1"
        # A different user with the same session_id must not match.
        assert (
            await instance.get_chat_by_id("discord:alice", "carol", "discord")
            is None
        )
        # A different channel must not match either.
        assert (
            await instance.get_chat_by_id("discord:alice", "alice", "console")
            is None
        )

    async def test_touch_chat_by_session_picks_most_recent(
        self,
        instance: BaseChatRepository,
    ):
        older = _spec(
            "c1",
            "s1",
            "alice",
            "console",
            updated_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        newer = _spec("c2", "s1", "alice", "console")
        await instance.upsert_chat(older)
        await instance.upsert_chat(newer)

        touched = await instance.touch_chat_by_session("s1", "console", "alice")
        assert touched is not None
        assert touched.id == "c2"
        assert touched.updated_at >= newer.updated_at

    async def test_touch_chat_by_session_without_user_matches_any(
        self,
        instance: BaseChatRepository,
    ):
        # Backward compatibility: None and "" both disable user filtering.
        await instance.upsert_chat(_spec("c1", "s1", "alice", "console"))
        assert await instance.touch_chat_by_session("s1", "console") is not None
        assert (
            await instance.touch_chat_by_session("s1", "console", "") is not None
        )

    async def test_touch_chat_by_session_miss_returns_none(
        self,
        instance: BaseChatRepository,
    ):
        assert await instance.touch_chat_by_session("ghost", "console") is None

    async def test_delete_chats_semantics(self, instance: BaseChatRepository):
        assert await instance.delete_chats([]) is False
        assert await instance.delete_chats(["missing"]) is False

        await instance.upsert_chat(_spec("c1", "s1", "alice"))
        await instance.upsert_chat(_spec("c2", "s2", "alice"))
        assert await instance.delete_chats(["c1"]) is True
        assert [c.id for c in await instance.list_chats()] == ["c2"]

    async def test_filter_chats_by_user_channel_archived(
        self,
        instance: BaseChatRepository,
    ):
        await instance.upsert_chat(_spec("c1", "s1", "alice", "discord"))
        await instance.upsert_chat(_spec("c2", "s2", "bob", "console"))
        await instance.upsert_chat(
            _spec(
                "c3",
                "s3",
                "alice",
                "console",
                archived_at=datetime.now(timezone.utc),
            ),
        )

        assert {c.id for c in await instance.filter_chats(user_id="alice")} == {
            "c1",
            "c3",
        }
        assert {c.id for c in await instance.filter_chats(channel="console")} == {
            "c2",
            "c3",
        }
        assert {c.id for c in await instance.filter_chats(archived=True)} == {
            "c3",
        }
        assert {c.id for c in await instance.filter_chats(archived=False)} == {
            "c1",
            "c2",
        }
        assert len(await instance.filter_chats()) == 3


class TestJsonChatRepositoryContract(ChatRepositoryContractTest):
    """JSON file backend (reference implementation)."""

    @pytest.fixture(autouse=True)
    def _storage(self, tmp_path: Path) -> None:
        self._path = tmp_path / "chats.json"

    def create_instance(self) -> BaseChatRepository:
        return JsonChatRepository(self._path)


# Future backends (M2 milestone): add ``TestDualChatRepositoryContract`` and
# ``TestPgChatRepositoryContract`` subclasses below — every contract test
# above will automatically run against them.
