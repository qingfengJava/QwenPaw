# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""M1 owner-isolation tests for scroll history.

A ``HistoryStore`` row carries ``owner_id``; a ``MemorySpace`` built with an
``owner_id`` must never surface another owner's rows through any structured
recall method (search / session / sessions / expand / recall_tool / agents),
while an owner-less space keeps the legacy unscoped behavior.
"""

import sqlite3
from pathlib import Path

import pytest

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.memoryspace import MemorySpace
from qwenpaw.agents.context.types import LogEntry


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "history.db"


def _entry(content: str, **kw) -> LogEntry:
    kw.setdefault("kind", "context_msg")
    return LogEntry(content=content, **kw)


def _seed(db_path: Path) -> None:
    """Two owners share one store (and one group session)."""
    store = HistoryStore(db_path)
    try:
        store.append(
            session_id="dingtalk:group1",
            agent_id="a1",
            owner_id="alice",
            entry=_entry("alice secret plan", role="user"),
            dedup_key="a1",
        )
        store.append(
            session_id="dingtalk:group1",
            agent_id="a1",
            owner_id="bob",
            entry=_entry("bob confidential note", role="user"),
            dedup_key="b1",
        )
        store.append(
            session_id="console:alice",
            agent_id="a1",
            owner_id="alice",
            entry=_entry("alice private dm", role="user"),
            dedup_key="a2",
        )
    finally:
        store.close()


def _space(db_path: Path, owner_id, session_id=None) -> MemorySpace:
    return MemorySpace(
        history_db_path=db_path,
        session_id=session_id,
        agent_id="a1",
        owner_id=owner_id,
    )


def test_owner_column_created_and_indexed(db_path: Path):
    store = HistoryStore(db_path)
    try:
        cols = {
            row["name"]
            for row in store._conn.execute(
                "PRAGMA table_info(conversation_history)",
            )
        }
        assert "owner_id" in cols
        indexes = {
            row["name"]
            for row in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'",
            )
        }
        assert "ch_owner" in indexes
    finally:
        store.close()


def test_owner_column_migrates_legacy_db(db_path: Path):
    """A pre-M1 database gains the column via idempotent ALTER."""
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(
            "CREATE TABLE conversation_history ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,"
            " agent_id TEXT, kind TEXT NOT NULL, role TEXT, name TEXT,"
            " content TEXT, tool_call_id TEXT, tool_input TEXT,"
            " tool_state TEXT, headline TEXT, blocks TEXT, metadata TEXT,"
            " created_at TEXT, dedup_key TEXT)",
        )
        conn.execute(
            "INSERT INTO conversation_history (session_id, kind, content)"
            " VALUES ('legacy', 'model_turn', 'old row')",
        )
    conn.close()

    store = HistoryStore(db_path)
    try:
        cols = {
            row["name"]
            for row in store._conn.execute(
                "PRAGMA table_info(conversation_history)",
            )
        }
        assert "owner_id" in cols
        # Legacy rows stay NULL until the backfill script assigns them.
        row = store._conn.execute(
            "SELECT owner_id FROM conversation_history WHERE session_id = ?",
            ("legacy",),
        ).fetchone()
        assert row["owner_id"] is None
    finally:
        store.close()
    # Second open is a no-op (idempotent).
    store = HistoryStore(db_path)
    store.close()


def test_append_persists_owner(db_path: Path):
    store = HistoryStore(db_path)
    try:
        store.append(
            session_id="s",
            owner_id="alice",
            entry=_entry("x"),
            dedup_key="k",
        )
        row = store._conn.execute(
            "SELECT owner_id FROM conversation_history WHERE session_id = 's'",
        ).fetchone()
        assert row["owner_id"] == "alice"
    finally:
        store.close()


def test_search_never_crosses_owner(db_path: Path):
    _seed(db_path)
    ms = _space(db_path, "alice", session_id="dingtalk:group1")
    try:
        hits = ms.search("confidential OR secret OR private", k=20)
        contents = [h.get("content", "") for h in hits if not h.get("_notice")]
        assert any("alice" in c for c in contents)
        assert not any("bob" in c for c in contents)
    finally:
        ms._conn.close()


def test_search_all_agents_still_owner_scoped(db_path: Path):
    """all_agents=True widens across agents but never across owners."""
    _seed(db_path)
    ms = _space(db_path, "bob", session_id="dingtalk:group1")
    try:
        hits = ms.search("alice", all_agents=True, k=20)
        contents = [h.get("content", "") for h in hits if not h.get("_notice")]
        assert not any("alice" in c for c in contents)
    finally:
        ms._conn.close()


def test_session_read_is_owner_scoped(db_path: Path):
    """A group session holds both owners' rows; each sees only their own."""
    _seed(db_path)
    ms = _space(db_path, "bob", session_id="dingtalk:group1")
    try:
        rows = ms.session("dingtalk:group1")
        contents = [r.get("content", "") for r in rows]
        assert any("bob" in c for c in contents)
        assert not any("alice" in c for c in contents)
    finally:
        ms._conn.close()


def test_sessions_listing_is_owner_scoped(db_path: Path):
    _seed(db_path)
    ms = _space(db_path, "alice")
    try:
        sessions = {row["session_id"] for row in ms.sessions()}
        assert "console:alice" in sessions
        # The group session contains alice rows, so it shows up — but a
        # bob-only session would not.
        bob_only = _space(db_path, "bob")
        try:
            bob_sessions = {row["session_id"] for row in bob_only.sessions()}
            assert "console:alice" not in bob_sessions
        finally:
            bob_only._conn.close()
    finally:
        ms._conn.close()


def test_ownerless_space_keeps_legacy_behavior(db_path: Path):
    """No owner_id → no owner predicate (single-user deployments)."""
    _seed(db_path)
    ms = _space(db_path, None)
    try:
        hits = ms.search("alice OR bob OR private", k=20)
        contents = [h.get("content", "") for h in hits if not h.get("_notice")]
        assert any("alice" in c for c in contents)
        assert any("bob" in c for c in contents)
    finally:
        ms._conn.close()
