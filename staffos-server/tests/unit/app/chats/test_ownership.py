# -*- coding: utf-8 -*-
"""Unit tests for chat ownership enforcement (M1)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.chats.api import get_owned_chat
from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo.json_repo import JsonChatRepository


def _request_with_user(username: str | None):
    """Minimal stand-in for a FastAPI request carrying state.user."""
    return SimpleNamespace(state=SimpleNamespace(user=username))


@pytest.fixture
def mgr(tmp_path: Path) -> ChatManager:
    return ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))


class TestEffectiveOwner:
    def test_owner_id_wins(self) -> None:
        spec = ChatSpec(session_id="s", user_id="u", owner_id="alice")
        assert spec.effective_owner == "alice"

    def test_legacy_row_falls_back_to_user_id(self) -> None:
        spec = ChatSpec(session_id="s", user_id="bob")
        assert spec.effective_owner == "bob"

    def test_system_fallback(self) -> None:
        spec = ChatSpec.model_construct(session_id="s", user_id="")
        assert spec.effective_owner == "system"

    def test_effective_owner_not_serialized(self) -> None:
        # Plain property: the API response contract stays unchanged.
        spec = ChatSpec(session_id="s", user_id="u", owner_id="alice")
        assert "effective_owner" not in spec.model_dump()


class TestGetOwnedChat:
    async def test_missing_chat_returns_404(self, mgr: ChatManager) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await get_owned_chat(
                "missing",
                _request_with_user("alice"),
                mgr,
            )
        assert exc_info.value.status_code == 404

    async def test_owner_can_access(self, mgr: ChatManager) -> None:
        chat = await mgr.get_or_create_chat("s1", "alice")
        result = await get_owned_chat(
            chat.id,
            _request_with_user("alice"),
            mgr,
        )
        assert result.id == chat.id

    async def test_foreign_user_gets_404_not_403(self, mgr: ChatManager) -> None:
        chat = await mgr.get_or_create_chat("s1", "alice")
        with pytest.raises(HTTPException) as exc_info:
            await get_owned_chat(
                chat.id,
                _request_with_user("mallory"),
                mgr,
            )
        # 404 (not 403): existence of other users' chats is undisclosed.
        assert exc_info.value.status_code == 404

    async def test_no_auth_identity_skips_check(self, mgr: ChatManager) -> None:
        chat = await mgr.get_or_create_chat("s1", "alice")
        result = await get_owned_chat(
            chat.id,
            _request_with_user(None),
            mgr,
        )
        assert result.id == chat.id

    async def test_legacy_chat_owned_via_user_id_fallback(
        self,
        mgr: ChatManager,
    ) -> None:
        # Pre-M1 rows have owner_id=None; user_id anchors ownership.
        legacy = ChatSpec(session_id="s1", user_id="alice")
        await mgr.create_chat(legacy)
        result = await get_owned_chat(
            legacy.id,
            _request_with_user("alice"),
            mgr,
        )
        assert result.id == legacy.id
        with pytest.raises(HTTPException):
            await get_owned_chat(
                legacy.id,
                _request_with_user("mallory"),
                mgr,
            )


class TestOwnerTagging:
    async def test_get_or_create_chat_tags_owner(self, mgr: ChatManager) -> None:
        chat = await mgr.get_or_create_chat("s1", "alice")
        assert chat.owner_id == "alice"
