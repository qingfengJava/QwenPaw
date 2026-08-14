# -*- coding: utf-8 -*-
"""Integration tests for the projects/tasks/feed domain (XianWork P2).

Cover the ProjectService against a real PostgreSQL (project lifecycle,
three-tier membership, kanban tasks, feed persistence) plus the pure
in-process EventBus broadcast/replay behavior. Runs only when
``QWENPAW_TEST_PG_DSN`` is set.
"""
from __future__ import annotations

import asyncio
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
    try:
        yield
    finally:
        engine_mod._engines.clear()
        ent_mod._schema_ready = False


@pytest.fixture
def svc():
    from qwenpaw.app.projects.service import get_project_service

    return get_project_service()


# ---------------------------------------------------------------------------
# project:{pid} owner semantics (pure functions, no PG required)
# ---------------------------------------------------------------------------


def test_project_owner_id_semantics():
    from qwenpaw.app.projects.service import (
        is_project_owner_id,
        project_id_from_owner,
        project_owner_id,
    )

    owner = project_owner_id("prj_123")
    assert owner == "project:prj_123"
    assert is_project_owner_id(owner) is True
    assert is_project_owner_id("alice") is False
    assert project_id_from_owner(owner) == "prj_123"
    assert project_id_from_owner("alice") is None


# ---------------------------------------------------------------------------
# EventBus broadcast + Last-Event-ID replay (no PG required)
# ---------------------------------------------------------------------------


async def test_event_bus_broadcast_and_replay():
    from qwenpaw.app.events.bus import InProcessEventBus, feed_topic

    bus = InProcessEventBus()
    topic = feed_topic("default", "prj_x")

    received_a: list[dict] = []
    received_b: list[dict] = []

    async def subscriber(target: list[dict]):
        async for event in bus.subscribe(topic):
            target.append(event)
            if len(target) >= 2:
                return

    task_a = asyncio.create_task(subscriber(received_a))
    task_b = asyncio.create_task(subscriber(received_b))
    await asyncio.sleep(0.05)  # let both subscribers attach

    await bus.publish(topic, {"kind": "task_created", "n": 1})
    await bus.publish(topic, {"kind": "task_status", "n": 2})
    await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=5)

    assert [e.data["kind"] for e in received_a] == [
        "task_created",
        "task_status",
    ]
    assert [e.data["kind"] for e in received_b] == [
        "task_created",
        "task_status",
    ]
    assert received_a[0].seq < received_a[1].seq

    # Replay: a late subscriber with Last-Event-ID still sees both events.
    replayed: list[dict] = []
    async def late_subscriber():
        async for event in bus.subscribe(topic, last_event_id="0"):
            replayed.append(event)
            if len(replayed) >= 2:
                return

    await asyncio.wait_for(late_subscriber(), timeout=5)
    assert [e.data["kind"] for e in replayed] == [
        "task_created",
        "task_status",
    ]


# ---------------------------------------------------------------------------
# Project lifecycle + membership (PG required)
# ---------------------------------------------------------------------------


async def test_project_lifecycle(enterprise_env, svc):
    project = await svc.create_project("Apollo", created_by="alice")
    assert project.id.startswith("prj_")
    assert project.name == "Apollo"
    assert project.status == "active"

    # Creator becomes owner member automatically.
    assert await svc.member_role(project.id, "alice") == "owner"

    listed = await svc.list_projects(username="alice")
    match = [p for p in listed if p.id == project.id]
    assert len(match) == 1
    assert match[0].member_role == "owner"

    got = await svc.get_project(project.id, username="alice")
    assert got is not None and got.member_role == "owner"

    updated = await svc.update_project(project.id, name="Apollo 2")
    assert updated.name == "Apollo 2"

    assert await svc.delete_project(project.id) is True
    assert await svc.get_project(project.id) is None


async def test_membership_three_tiers(enterprise_env, svc):
    project = await svc.create_project("Boreas", created_by="alice")

    # Invalid role is rejected; valid tiers round-trip.
    assert await svc.upsert_member(project.id, "bob", "viewer") is True
    assert await svc.member_role(project.id, "bob") == "viewer"
    assert await svc.upsert_member(project.id, "bob", "editor") is True
    assert await svc.member_role(project.id, "bob") == "editor"
    assert await svc.upsert_member(project.id, "bob", "intern") is False

    members = await svc.list_members(project.id)
    roles = {m.username: m.role for m in members}
    assert roles == {"alice": "owner", "bob": "editor"}

    # The owner cannot be removed; editors can.
    assert await svc.remove_member(project.id, "alice") is False
    assert await svc.remove_member(project.id, "bob") is True
    assert await svc.member_role(project.id, "bob") == ""

    # Upserting onto a missing project is rejected.
    assert await svc.upsert_member("prj_missing", "bob", "viewer") is False


async def test_task_kanban_flow(enterprise_env, svc):
    project = await svc.create_project("Charon", created_by="alice")

    t1 = await svc.create_task(project.id, creator="alice", title="调研")
    t2 = await svc.create_task(project.id, creator="alice", title="开发")
    assert t1.status == "todo"
    assert t1.sort_order == 1
    assert t2.sort_order == 2

    # Board drag: status + sort_order together.
    moved = await svc.update_task(
        t1.id,
        actor="alice",
        status="doing",
        sort_order=5,
    )
    assert moved.status == "doing"
    assert moved.sort_order == 5

    tasks = await svc.list_tasks(project.id)
    assert {t.id for t in tasks} == {t1.id, t2.id}

    mine = await svc.list_tasks(project.id, assignee="alice")
    assert mine == []  # nobody assigned yet

    assigned = await svc.update_task(t1.id, actor="alice", assignee="alice")
    assert assigned.assignee == "alice"
    mine = await svc.list_tasks(project.id, assignee="alice")
    assert [t.id for t in mine] == [t1.id]

    with pytest.raises(ValueError, match="status"):
        await svc.update_task(t1.id, actor="alice", status="blocked")

    assert await svc.delete_task(t2.id) is True
    assert await svc.get_task(t2.id) is None


async def test_feed_persistence(enterprise_env, svc):
    project = await svc.create_project("Daphne", created_by="alice")
    await svc.create_task(project.id, creator="alice", title="t")
    await svc.record_feed(
        project.id,
        actor="alice",
        kind="comment",
        payload={"text": "hello"},
    )

    feed = await svc.list_feed(project.id)
    kinds = [e.kind for e in feed]
    # Newest first: comment > task_created > project_created.
    assert kinds[0] == "comment"
    assert "task_created" in kinds
    assert "project_created" in kinds
    comment = feed[0]
    assert comment.payload["text"] == "hello"

    # Pagination via before_id excludes the newest event.
    older = await svc.list_feed(project.id, before_id=comment.id)
    assert all(e.id < comment.id for e in older)
