# -*- coding: utf-8 -*-
"""RLS policy behavior tests (M2).

Verify the PERMISSIVE owner-isolation policies against a real PostgreSQL:
- no GUC set -> everything visible (application-layer filtering phase)
- GUC set    -> only own + legacy NULL-owner rows visible; cross-owner
                writes rejected by WITH CHECK

Runs only when ``QWENPAW_TEST_PG_DSN`` points at a throwaway database.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

DSN = os.environ.get("QWENPAW_TEST_PG_DSN", "").strip()


@pytest.fixture
async def engine():
    if not DSN:
        pytest.skip("QWENPAW_TEST_PG_DSN not set")
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from qwenpaw.db.migrate import run_migrations

    eng = create_async_engine(DSN, pool_pre_ping=True)
    try:
        await run_migrations(eng)
        async with eng.begin() as conn:
            # RLS never constrains superusers: verify policies through a
            # downgraded non-owner role, like the production app role.
            await conn.execute(
                text(
                    "DO $$ BEGIN "
                    "IF NOT EXISTS (SELECT FROM pg_roles "
                    "WHERE rolname = 'rls_probe') THEN "
                    "CREATE ROLE rls_probe NOLOGIN; "
                    "END IF; END $$",
                ),
            )
            await conn.execute(
                text(
                    "GRANT SELECT, INSERT, UPDATE, DELETE "
                    "ON chats TO rls_probe",
                ),
            )
            await conn.execute(text("TRUNCATE chats"))
            await conn.execute(
                text(
                    "INSERT INTO chats (tenant_id, id, session_id, user_id, "
                    "owner_id, channel, name, created_at, updated_at) VALUES "
                    "('default', 'c-alice', 's1', 'alice', 'alice', 'console',"
                    " 'A', now(), now()), "
                    "('default', 'c-bob', 's2', 'bob', 'bob', 'console', "
                    "'B', now(), now()), "
                    "('default', 'c-legacy', 's3', 'carol', NULL, 'console', "
                    "'L', now(), now())",
                ),
            )
        yield eng
    finally:
        await eng.dispose()


async def _visible_ids(conn) -> set[str]:
    from sqlalchemy import text

    result = await conn.execute(
        text("SELECT id FROM chats WHERE tenant_id = 'default'"),
    )
    return {row[0] for row in result}


async def _set_probe_role(conn) -> None:
    """Downgrade the connection to a non-owner, non-superuser role."""
    from sqlalchemy import text

    await conn.execute(text("SET LOCAL ROLE rls_probe"))


async def test_without_guc_all_rows_visible(engine) -> None:
    """Gray phase: no GUC means application-layer filtering governs."""
    from sqlalchemy import text

    async with engine.begin() as conn:
        await _set_probe_role(conn)
        # Explicitly clear any inherited setting.
        await conn.execute(
            text("SELECT set_config('app.current_owner', '', true)"),
        )
        assert await _visible_ids(conn) == {"c-alice", "c-bob", "c-legacy"}


async def test_guc_scopes_reads_to_owner_plus_legacy(engine) -> None:
    from sqlalchemy import text

    async with engine.begin() as conn:
        await _set_probe_role(conn)
        await conn.execute(
            text("SELECT set_config('app.current_owner', :owner, true)"),
            {"owner": "alice"},
        )
        assert await _visible_ids(conn) == {"c-alice", "c-legacy"}


async def test_guc_rejects_cross_owner_insert(engine) -> None:
    from sqlalchemy import text

    async with engine.begin() as conn:
        await _set_probe_role(conn)
        await conn.execute(
            text("SELECT set_config('app.current_owner', :owner, true)"),
            {"owner": "alice"},
        )
        with pytest.raises(Exception) as exc_info:  # InsufficientPrivilege
            await conn.execute(
                text(
                    "INSERT INTO chats (tenant_id, id, session_id, user_id, "
                    "owner_id, channel, name, created_at, updated_at) VALUES "
                    "('default', 'c-evil', 's9', 'alice', 'bob', 'console', "
                    "'X', now(), now())",
                ),
            )
        assert "row-level security" in str(exc_info.value).lower()


async def test_guc_allows_own_insert(engine) -> None:
    from sqlalchemy import text

    async with engine.begin() as conn:
        await _set_probe_role(conn)
        await conn.execute(
            text("SELECT set_config('app.current_owner', :owner, true)"),
            {"owner": "alice"},
        )
        await conn.execute(
            text(
                "INSERT INTO chats (tenant_id, id, session_id, user_id, "
                "owner_id, channel, name, created_at, updated_at) VALUES "
                "('default', 'c-new', 's9', 'alice', 'alice', 'console', "
                "'X', now(), now())",
            ),
        )
        assert "c-new" in await _visible_ids(conn)
