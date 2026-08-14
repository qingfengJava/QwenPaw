# -*- coding: utf-8 -*-
"""Integration tests for the orgs/department domain (XianWork P1).

Cover the OrgService against a real PostgreSQL (departments tree with
materialized paths, membership mapping, delete guards). RBAC team
mirroring is spied (not executed) so tests never touch the developer's
rbac.json. Runs only when ``QWENPAW_TEST_PG_DSN`` is set.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

DSN = os.environ.get("QWENPAW_TEST_PG_DSN", "").strip()

_TRUNCATE_SQL = (
    "TRUNCATE project_members, tasks, feed_events, projects, "
    "department_members, departments, orgs, expert_team_members, "
    "published_experts, expert_teams, experts, token_usage_events "
    "RESTART IDENTITY"
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

    # Spy on the RBAC mirror: record the call, skip the JSON-store write.
    mirror_calls: list[str] = []

    async def _spy_sync(self, record):
        mirror_calls.append(record.path)

    from qwenpaw.app.orgs.service import OrgService

    monkeypatch.setattr(OrgService, "_sync_department_team", _spy_sync)
    try:
        yield {"mirror_calls": mirror_calls}
    finally:
        engine_mod._engines.clear()
        ent_mod._schema_ready = False


@pytest.fixture
def svc():
    from qwenpaw.app.orgs.service import get_org_service

    return get_org_service()


async def test_bootstrap_is_idempotent(enterprise_env, svc):
    await svc.bootstrap_default_org()
    await svc.bootstrap_default_org()

    orgs = await svc.list_orgs()
    defaults = [o for o in orgs if o.id == "default"]
    assert len(defaults) == 1


async def test_department_tree_materialized_paths(enterprise_env, svc):
    root = await svc.create_department("Engineering")
    child = await svc.create_department("Platform", parent_id=root.id)
    grand = await svc.create_department("Runtime", parent_id=child.id)

    assert root.path == root.id
    assert child.path == f"{root.id}/{child.id}"
    assert grand.path == f"{root.id}/{child.id}/{grand.id}"

    tree = await svc.department_tree()
    assert len(tree) == 1
    assert tree[0].id == root.id
    assert [c.id for c in tree[0].children] == [child.id]
    assert tree[0].children[0].children[0].id == grand.id

    # Every create mirrors the department onto its RBAC team path.
    assert len(enterprise_env["mirror_calls"]) == 3


async def test_create_department_missing_parent(enterprise_env, svc):
    with pytest.raises(ValueError, match="not found"):
        await svc.create_department("Orphan", parent_id="dept_missing")


async def test_update_department(enterprise_env, svc):
    dept = await svc.create_department("Sales")
    updated = await svc.update_department(
        dept.id,
        name="Revenue",
        description="updated",
    )
    assert updated.name == "Revenue"
    assert updated.description == "updated"
    assert await svc.update_department("dept_missing", name="x") is None


async def test_delete_department_guards(enterprise_env, svc):
    root = await svc.create_department("Root")
    child = await svc.create_department("Child", parent_id=root.id)

    with pytest.raises(ValueError, match="child"):
        await svc.delete_department(root.id)

    await svc.assign_member(child.id, "alice")
    with pytest.raises(ValueError, match="members"):
        await svc.delete_department(child.id)

    assert await svc.remove_member(child.id, "alice") is True
    assert await svc.delete_department(child.id) is True
    assert await svc.delete_department(root.id) is True
    assert await svc.delete_department("dept_missing") is False


async def test_member_lifecycle_and_scope(enterprise_env, svc):
    dept = await svc.create_department("Design")
    assert await svc.department_members(dept.id) == []

    assert await svc.assign_member(dept.id, "bob") is True
    assert await svc.department_members(dept.id) == ["bob"]

    org_id, dept_path = await svc.resolve_user_scope("bob")
    assert org_id == "default"
    assert dept_path == dept.path

    # Unknown user resolves to no department.
    org_id2, dept_path2 = await svc.resolve_user_scope("nobody")
    assert org_id2 == "default"
    assert dept_path2 is None

    # Assigning to a missing department is rejected.
    assert await svc.assign_member("dept_missing", "bob") is False

    assert await svc.remove_member(dept.id, "bob") is True
    assert await svc.department_members(dept.id) == []
