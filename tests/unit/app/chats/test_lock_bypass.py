# -*- coding: utf-8 -*-
"""ChatManager lock behavior per backend (M2 pg lock bypass)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.repo.json_repo import JsonChatRepository


def test_json_repo_keeps_real_locks(tmp_path) -> None:
    repo = JsonChatRepository(tmp_path / "chats.json")
    mgr = ChatManager(repo=repo)
    assert mgr._tx_safe is False  # noqa: SLF001
    # The JSON backend must keep its real write lock.
    assert isinstance(mgr._write_lock, asyncio.Lock)  # noqa: SLF001


def test_pg_repo_bypasses_manager_locks() -> None:
    from qwenpaw.app.chats.repo.pg_repo import PgChatRepository

    repo = PgChatRepository(engine=MagicMock())
    mgr = ChatManager(repo=repo)
    assert mgr._tx_safe is True  # noqa: SLF001
    # Noop lock: acquiring never blocks (no underlying asyncio.Lock).
    assert not isinstance(mgr._write_lock, asyncio.Lock)  # noqa: SLF001
