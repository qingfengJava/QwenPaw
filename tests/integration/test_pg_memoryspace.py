# -*- coding: utf-8 -*-
"""PgMemorySpace integration tests (M2 pg read path).

Exercises structured recall over a real PostgreSQL: tsvector search, LIKE
fallback for CJK, turn expansion, and — critically — owner isolation for
every recall method (M1 semantics carried into the pg backend).

Runs only when ``QWENPAW_TEST_PG_DSN`` points at a throwaway database.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

DSN = os.environ.get("QWENPAW_TEST_PG_DSN", "").strip()


@pytest.fixture
def store_and_space():
    """Seed history rows for two owners; yield (space_factory, dsn)."""
    if not DSN:
        pytest.skip("QWENPAW_TEST_PG_DSN not set")
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from qwenpaw.db.migrate import run_migrations

    async def _prepare() -> None:
        engine = create_async_engine(DSN, pool_pre_ping=True)
        try:
            await run_migrations(engine)
            async with engine.begin() as conn:
                await conn.execute(text("TRUNCATE history_entries"))
        finally:
            await engine.dispose()

    asyncio.run(_prepare())

    from qwenpaw.agents.context.scroll.pg_history import PgHistoryStore
    from qwenpaw.agents.context.types import LogEntry

    store = PgHistoryStore(dsn=DSN, identity="pg:test-ms")
    try:
        # Alice's conversation: a user turn plus an assistant reply.
        store.append(
            session_id="console:dm",
            agent_id="a1",
            owner_id="alice",
            entry=LogEntry(
                kind="context_msg",
                role="user",
                content="deploy the tank report",
            ),
            dedup_key="a-user-1",
        )
        store.append(
            session_id="console:dm",
            agent_id="a1",
            owner_id="alice",
            entry=LogEntry(
                kind="context_msg",
                role="assistant",
                content="tank report deployed to prod",
            ),
            dedup_key="a-asst-1",
        )
        # Bob's row with a distinct keyword.
        store.append(
            session_id="console:dm-bob",
            agent_id="a1",
            owner_id="bob",
            entry=LogEntry(
                kind="context_msg",
                role="user",
                content="my aquarium setup notes",
            ),
            dedup_key="b-user-1",
        )
        yield DSN
    finally:
        store.close()


def _space(dsn: str, owner: str, session_id: str | None = None):
    from qwenpaw.agents.context.scroll.pg_memoryspace import PgMemorySpace

    return PgMemorySpace(
        dsn=dsn,
        session_id=session_id,
        agent_id="a1",
        owner_id=owner,
    )


def test_search_fts_hits_only_own_rows(store_and_space) -> None:
    dsn = store_and_space
    space = _space(dsn, "alice")
    try:
        hits = space.search("tank", k=10)
        assert hits, "expected at least one hit"
        contents = [h.get("content", "") for h in hits if not h.get("_notice")]
        assert any("tank" in c for c in contents)
        assert not any("aquarium" in c for c in contents)
    finally:
        space.close()


def test_search_never_leaks_across_owners(store_and_space) -> None:
    dsn = store_and_space
    space = _space(dsn, "alice")
    try:
        # "aquarium" exists only in bob's rows: alice must see nothing.
        hits = space.search("aquarium", k=10)
        assert hits == []
    finally:
        space.close()


def test_search_cjk_falls_back_to_like(store_and_space) -> None:
    dsn = store_and_space
    from qwenpaw.agents.context.scroll.pg_history import PgHistoryStore
    from qwenpaw.agents.context.types import LogEntry

    store = PgHistoryStore(dsn=dsn, identity="pg:test-ms-cjk")
    try:
        store.append(
            session_id="console:dm",
            agent_id="a1",
            owner_id="alice",
            entry=LogEntry(
                kind="context_msg",
                role="user",
                content="帮我查一下服务器状态",
                created_at="2026-08-01T00:00:00+00:00",
            ),
            dedup_key="a-cjk-1",
        )
    finally:
        store.close()

    space = _space(dsn, "alice")
    try:
        hits = space.search("服务器", k=10)
        assert any("服务器" in h.get("content", "") for h in hits)
    finally:
        space.close()


def test_expand_returns_rows_in_span(store_and_space) -> None:
    dsn = store_and_space
    space = _space(dsn, "alice", session_id="console:dm")
    try:
        sessions = space.sessions()
        dm = [s for s in sessions if s["session_id"] == "console:dm"]
        assert dm, "alice must see her own session"
        rows = space.expand(int(dm[0]["first_seq"]), int(dm[0]["last_seq"]))
        assert len(rows) >= 2
    finally:
        space.close()


def test_session_read_scoped_to_owner(store_and_space) -> None:
    dsn = store_and_space
    alice = _space(dsn, "alice")
    bob = _space(dsn, "bob")
    try:
        a_rows = alice.session("console:dm")
        assert a_rows
        b_rows = bob.session("console:dm")
        assert b_rows == []
    finally:
        alice.close()
        bob.close()


def test_sql_hatches_are_closed(store_and_space) -> None:
    dsn = store_and_space
    space = _space(dsn, "alice")
    try:
        with pytest.raises(NotImplementedError):
            space.sql_query("SELECT 1")
        with pytest.raises(NotImplementedError):
            space.sql_exec("DELETE FROM history_entries")
    finally:
        space.close()


def test_active_turn_is_excluded_from_search(store_and_space) -> None:
    dsn = store_and_space
    from qwenpaw.agents.context.scroll.pg_history import PgHistoryStore
    from qwenpaw.agents.context.types import LogEntry

    store = PgHistoryStore(dsn=dsn, identity="pg:test-ms-active")
    try:
        store.append(
            session_id="console:dm",
            agent_id="a1",
            owner_id="alice",
            entry=LogEntry(
                kind="context_msg",
                role="user",
                content="current in-progress request",
            ),
            dedup_key="a-active-1",
        )
    finally:
        store.close()

    space = _space(dsn, "alice", session_id="console:dm")
    try:
        hits = space.search("in-progress", k=10)
        assert not any("in-progress" in h.get("content", "") for h in hits)
    finally:
        space.close()
