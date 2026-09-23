# -*- coding: utf-8 -*-
"""Shared fixtures for storage-backend contract tests.

PostgreSQL-backed contract subclasses run only when ``QWENPAW_TEST_PG_DSN``
points at a throwaway database (e.g. a local ``docker run postgres:16``).
Without it they skip, keeping the default test run hermetic.
"""
from __future__ import annotations

import os

import pytest

TEST_PG_DSN_ENV = "QWENPAW_TEST_PG_DSN"


@pytest.fixture
def pg_dsn() -> str:
    """Return a migrated, freshly-cleaned test DSN, or skip.

    Applies migrations and truncates every storage table so each test sees
    the "fresh, empty storage" the contracts assume. Done synchronously so
    both sync stores (PgHistoryStore owns its loop) and async consumers can
    rely on it.
    """
    dsn = os.environ.get(TEST_PG_DSN_ENV, "").strip()
    if not dsn:
        pytest.skip(
            f"{TEST_PG_DSN_ENV} not set; skipping PostgreSQL contract tests",
        )
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from qwenpaw.db.migrate import run_migrations

    async def _prepare() -> None:
        engine = create_async_engine(dsn, pool_pre_ping=True)
        try:
            await run_migrations(engine)
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "TRUNCATE chats, session_states, history_entries, "
                        "agent_runs, agent_run_spans, provider_configs, "
                        "provider_models, model_active_slots",
                    ),
                )
        finally:
            await engine.dispose()

    asyncio.run(_prepare())
    return dsn


@pytest.fixture
async def pg_engine(pg_dsn: str):
    """Yield an async engine over the prepared test database."""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(pg_dsn, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()
