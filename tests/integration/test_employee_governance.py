# -*- coding: utf-8 -*-
"""Integration tests for the digital-employee governance plane.

Covers the ``employee_governance`` table (shape, idempotent DDL, check
constraints), the store's upsert / batch-upsert semantics against a real
PostgreSQL, and the one-off backfill from ``experts``. Runs only when
``QWENPAW_TEST_PG_DSN`` is set.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

DSN = os.environ.get("QWENPAW_TEST_PG_DSN", "").strip()

_TRUNCATE_SQL = (
    "TRUNCATE project_members, tasks, feed_events, projects, "
    "department_members, departments, orgs, employee_governance, "
    "expert_team_members, expert_skills, published_experts, expert_teams, "
    "experts, token_usage_events RESTART IDENTITY"
)


@pytest.fixture
async def enterprise_env(monkeypatch):
    if not DSN:
        pytest.skip("QWENPAW_TEST_PG_DSN not set")
    monkeypatch.setenv("QWENPAW_PG_DSN", DSN)

    from qwenpaw.app import enterprise as ent_mod
    from qwenpaw.db import engine as engine_mod

    engine_mod._engines.clear()
    ent_mod._schema_ready = False
    ok = await ent_mod.bootstrap_enterprise()
    assert ok, "enterprise bootstrap failed against the test database"
    engine = engine_mod.create_pg_engine(DSN)
    async with engine.begin() as conn:
        await conn.execute(text(_TRUNCATE_SQL))
    try:
        yield engine
    finally:
        # dispose (not just drop the reference): release pooled asyncpg
        # connections so they are not tied to the per-test closed loop
        await engine_mod.dispose_engines()
        ent_mod._schema_ready = False


@pytest.fixture
def store():
    from qwenpaw.app.employees.store import get_employee_governance_store

    return get_employee_governance_store()


async def _exec(engine, sql, **params):
    async with engine.begin() as conn:
        return await conn.execute(text(sql), params)


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------


async def test_table_shape_and_constraints(enterprise_env):
    engine = enterprise_env

    columns = await _exec(
        engine,
        "SELECT column_name, is_nullable FROM information_schema.columns "
        "WHERE table_name = 'employee_governance' ORDER BY column_name",
    )
    names = {row.column_name: row.is_nullable for row in columns}
    assert set(names) >= {
        "tenant_id",
        "agent_id",
        "entity_kind",
        "entity_id",
        "department_id",
        "visibility",
        "granted_departments",
        "owner_id",
        "updated_by",
        "created_at",
        "updated_at",
    }
    # Only the owning department may stay NULL (platform-wide employee).
    assert names["department_id"] == "YES"
    assert names["visibility"] == "NO"

    pk = await _exec(
        engine,
        "SELECT a.attname FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indrelid "
        "JOIN pg_attribute a ON a.attrelid = c.oid "
        "AND a.attnum = ANY(i.indkey) "
        "WHERE c.relname = 'employee_governance' AND i.indisprimary",
    )
    assert {row.attname for row in pk} == {"tenant_id", "agent_id"}

    # CHECK constraints must exist and enumerate exactly the legal codes.
    # （不去触发违反约束：失败语句会把连接带进 aborted 状态，池内收尾会挂）
    constraints = await _exec(
        engine,
        "SELECT conname, pg_get_constraintdef(oid) AS cdef "
        "FROM pg_constraint "
        "WHERE conrelid = 'employee_governance'::regclass AND contype = 'c'",
    )
    definitions = {row.conname: row.cdef for row in constraints}
    assert set(definitions) >= {
        "ck_employee_governance_visibility",
        "ck_employee_governance_kind",
    }
    for value in ("org", "department", "private"):
        assert value in definitions["ck_employee_governance_visibility"]
    for value in ("agent", "expert", "team", "workflow"):
        assert value in definitions["ck_employee_governance_kind"]


async def test_ddl_is_idempotent(enterprise_env):
    """Re-running the migration statements must not raise (psql twin)."""
    mod = _load_revision()
    engine = enterprise_env
    for _ in range(2):
        await _exec(engine, mod._CREATE_TABLE)
        await _exec(engine, mod._ADD_VISIBILITY_CHECK)
        await _exec(engine, mod._ADD_KIND_CHECK)
        for statement in mod._CREATE_INDEXES:
            await _exec(engine, statement)
    indexed = await _exec(
        engine,
        "SELECT indexname FROM pg_indexes WHERE tablename = "
        "'employee_governance'",
    )
    assert {row.indexname for row in indexed} >= {
        "pk_employee_governance",
        "ix_employee_governance_department",
        "ix_employee_governance_visibility",
        "ix_employee_governance_kind",
    }


def _load_revision():
    """Import the 0031 revision module straight from its file path."""
    import importlib.util
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src/qwenpaw/db/alembic/versions/0031_employee_governance.py"
    )
    spec = importlib.util.spec_from_file_location("rev0031", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------


async def test_upsert_round_trip_and_overwrite(enterprise_env, store):
    from qwenpaw.app.employees.models import (
        EMPLOYEE_KIND_EXPERT,
        VISIBILITY_DEPARTMENT,
        VISIBILITY_PRIVATE,
    )

    created = await store.upsert(
        agent_id="expert_sales",
        entity_kind=EMPLOYEE_KIND_EXPERT,
        entity_id="sales",
        department_id="dept_1",
        visibility=VISIBILITY_DEPARTMENT,
        granted_departments=["dept_2", "dept_3"],
        owner_id="alice",
        updated_by="admin",
    )
    assert created.created_at is not None
    assert created.visibility == VISIBILITY_DEPARTMENT

    fetched = await store.get("expert_sales")
    assert fetched is not None
    assert fetched.granted_departments == ["dept_2", "dept_3"]
    assert fetched.owner_id == "alice"
    assert fetched.updated_by == "admin"

    overwritten = await store.upsert(
        agent_id="expert_sales",
        entity_kind=EMPLOYEE_KIND_EXPERT,
        entity_id="sales",
        department_id=None,
        visibility=VISIBILITY_PRIVATE,
        granted_departments=[],
        owner_id="bob",
        updated_by="admin2",
    )
    # A governance write must be able to clear the owning department.
    assert overwritten.department_id is None
    assert overwritten.granted_departments == []
    assert (await store.get("expert_sales")).owner_id == "bob"

    assert await store.get("expert_missing") is None
    rows = await store.list_all()
    assert [row.agent_id for row in rows] == ["expert_sales"]


async def test_batch_upsert_inserts_and_updates_in_one_statement(
    enterprise_env,
    store,
):
    payload = [
        {
            "agent_id": "default",
            "entity_kind": "agent",
            "entity_id": "default",
            "department_id": "dept_1",
            "visibility": "org",
            "granted_departments": [],
            "owner_id": None,
            "updated_by": "batch",
        },
        {
            "agent_id": "team_support",
            "entity_kind": "team",
            "entity_id": "support",
            "department_id": None,
            "visibility": "private",
            "granted_departments": ["dept_9"],
            "owner_id": "carol",
            "updated_by": "batch",
        },
    ]
    written = await store.batch_upsert(payload)
    assert len(written) == 2
    assert {row.agent_id for row in written} == {"default", "team_support"}

    # Partial batch: rows outside it keep their previous governance state.
    await store.batch_upsert([dict(payload[0], visibility="department")])
    assert (await store.get("default")).visibility == "department"
    assert (await store.get("team_support")).visibility == "private"

    assert await store.batch_upsert([]) == []


# ---------------------------------------------------------------------------
# backfill from the legacy experts columns
# ---------------------------------------------------------------------------


async def test_backfill_from_experts(enterprise_env, store):
    from qwenpaw.app.experts.store import get_expert_store
    from qwenpaw.app.orgs.service import get_org_service

    departments = await get_org_service().list_departments()
    if not departments:
        await get_org_service().bootstrap_default_org()
    sales = await get_org_service().create_department("Sales")

    expert_store = get_expert_store()
    # 1) private + known department name -> mapped onto the department id
    await expert_store.create_expert(
        "Scoped",
        expert_id="exp_scoped",
        visibility="private",
        department=sales.name,
        owner_id="alice",
    )
    # 2) org + no department -> default state, nothing to backfill
    await expert_store.create_expert("Plain", expert_id="exp_plain")
    # 3) unknown department text -> row is created, id stays NULL
    await expert_store.create_expert(
        "Legacy",
        expert_id="exp_legacy",
        visibility="department",
        department="Does Not Exist",
    )
    # 4) unknown visibility value -> normalized to org (never invented)
    await expert_store.create_expert(
        "Weird",
        expert_id="exp_weird",
        visibility="shared",
        department="Does Not Exist",
    )

    await _exec(enterprise_env, _load_revision()._BACKFILL_FROM_EXPERTS)

    rows = {row.agent_id: row for row in await store.list_all()}
    # Any human touch (non-org visibility OR a department text) gets a row;
    # the untouched "Plain" expert stays ungoverned.
    assert set(rows) == {
        "expert_exp_scoped",
        "expert_exp_legacy",
        "expert_exp_weird",
    }
    assert rows["expert_exp_scoped"].department_id == sales.id
    assert rows["expert_exp_scoped"].visibility == "private"
    assert rows["expert_exp_scoped"].owner_id == "alice"
    assert rows["expert_exp_scoped"].entity_kind == "expert"
    assert rows["expert_exp_scoped"].entity_id == "exp_scoped"
    assert rows["expert_exp_legacy"].department_id is None
    assert rows["expert_exp_legacy"].visibility == "department"
    # A legacy visibility value the governance plane never invents.
    assert rows["expert_exp_weird"].visibility == "org"
    assert rows["expert_exp_weird"].department_id is None
    assert rows["expert_exp_weird"].updated_by == "system_backfill"

    # Idempotent: running the backfill again never overwrites later edits.
    await store.upsert(
        agent_id="expert_exp_scoped",
        entity_kind="expert",
        entity_id="exp_scoped",
        department_id=sales.id,
        visibility="department",
        granted_departments=[],
        owner_id="alice",
        updated_by="admin",
    )
    await _exec(enterprise_env, _load_revision()._BACKFILL_FROM_EXPERTS)
    again = await store.get("expert_exp_scoped")
    assert again.visibility == "department"
    assert again.updated_by == "admin"
