# -*- coding: utf-8 -*-
"""Integration tests for the expert / expert-team domain (XianWork P3).

Cover the ExpertStore CRUD against a real PostgreSQL plus the pure
team-supervisor spec builder (both orchestration modes), asserting the
generated spec stays AgentProfileConfig-compatible — the contract the
publish pipeline relies on. Runs only when ``QWENPAW_TEST_PG_DSN`` is set.
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
    try:
        yield
    finally:
        engine_mod._engines.clear()
        ent_mod._schema_ready = False


@pytest.fixture
def store():
    from qwenpaw.app.experts.store import get_expert_store

    return get_expert_store()


# ---------------------------------------------------------------------------
# agent id helpers (pure, no PG)
# ---------------------------------------------------------------------------


def test_agent_id_helpers():
    from qwenpaw.app.experts.models import (
        expert_agent_id,
        expert_team_agent_id,
    )

    assert expert_agent_id("exp_1") == "expert_exp_1"
    assert expert_team_agent_id("team_1") == "team_team_1"


def test_member_validation_dedup_and_cap():
    from qwenpaw.app.experts.models import TeamMember
    from qwenpaw.app.experts.store import ExpertStore

    members = [
        TeamMember(expert_id="a", seq=3),
        TeamMember(expert_id="b", seq=1),
        TeamMember(expert_id="a", seq=2),  # duplicate id
        TeamMember(expert_id="c", seq=2),
        TeamMember(expert_id="d", seq=0),  # seq=0 means "unset" -> input index
        TeamMember(expert_id="e", seq=4),
    ]
    # Ordering: explicit seq first (b=1, c=2, a=3); "d" fell back to its
    # input index (4) and ties with e=4 (stable: d before e).
    router = ExpertStore._validate_members(members, "router")
    assert [m.expert_id for m in router] == ["b", "c", "a", "d", "e"]

    pipeline = ExpertStore._validate_members(members, "pipeline")
    assert [m.expert_id for m in pipeline] == ["b", "c", "a"]


# ---------------------------------------------------------------------------
# store CRUD (PG required)
# ---------------------------------------------------------------------------


async def test_expert_draft_lifecycle(enterprise_env, store):
    draft = await store.create_expert(
        name="法务专家",
        icon="⚖️",
        description="合同审查",
        agent_spec={"language": "zh"},
    )
    assert draft.id.startswith("exp_")
    assert draft.status == "draft"
    assert draft.version == 1

    got = await store.get_expert(draft.id)
    assert got is not None
    assert got.name == "法务专家"
    assert got.agent_spec == {"language": "zh"}

    assert await store.get_expert("exp_missing") is None

    drafts = await store.list_experts(status="draft")
    assert any(e.id == draft.id for e in drafts)

    updated = await store.update_expert(
        draft.id,
        name="资深法务专家",
    )
    assert updated.name == "资深法务专家"

    assert await store.delete_expert(draft.id) is True
    assert await store.get_expert(draft.id) is None


async def test_team_lifecycle_with_members(enterprise_env, store):
    from qwenpaw.app.experts.models import TeamMember

    e1 = await store.create_expert(name="写手", description="文案撰写")
    e2 = await store.create_expert(name="审校", description="质量把关")

    team = await store.create_team(
        name="内容流水线",
        description="写作与审校",
        mode="pipeline",
        router_prompt="",
        members=[],
    )
    assert team.mode == "pipeline"
    assert team.status == "draft"
    assert team.members == []

    # Members are replaced wholesale via update_team (validated + ordered).
    updated = await store.update_team(
        team.id,
        members=[
            TeamMember(expert_id=e1.id, role_hint="执笔", seq=0),
            TeamMember(expert_id=e2.id, role_hint="终审", seq=1),
        ],
    )
    assert [m.expert_id for m in updated.members] == [e1.id, e2.id]
    assert updated.members[0].role_hint == "执笔"

    got = await store.get_team(team.id)
    assert got is not None
    assert [m.expert_id for m in got.members] == [e1.id, e2.id]

    teams = await store.list_teams()
    assert any(t.id == team.id for t in teams)

    # Snapshot upsert is idempotent (ON CONFLICT DO NOTHING).
    await store.insert_snapshot(
        expert_id=e1.id,
        version=1,
        spec={"id": f"expert_{e1.id}"},
        published_by="admin",
    )
    await store.insert_snapshot(
        expert_id=e1.id,
        version=1,
        spec={"id": f"expert_{e1.id}"},
        published_by="admin",
    )
    snap = await store.latest_snapshot(e1.id)
    assert snap is not None
    assert snap.version == 1
    assert snap.published_by == "admin"


# ---------------------------------------------------------------------------
# team supervisor spec builder (pure, no PG)
# ---------------------------------------------------------------------------


def _spec_config_cls():
    from qwenpaw.config.config import AgentProfileConfig

    return AgentProfileConfig


def _make_team(mode: str, router_prompt: str = ""):
    from qwenpaw.app.experts.models import (
        ExpertTeamRecord,
        TeamMember,
    )

    return ExpertTeamRecord(
        id="team_x",
        name="交付专家团",
        description="端到端交付",
        mode=mode,
        router_prompt=router_prompt,
        members=[
            TeamMember(expert_id="exp_a", role_hint="方案", seq=0),
            TeamMember(expert_id="exp_b", role_hint="执行", seq=1),
        ],
    )


def _make_members():
    from qwenpaw.app.experts.models import ExpertRecord

    return [
        ExpertRecord(id="exp_a", name="架构师", description="总体方案设计"),
        ExpertRecord(id="exp_b", name="工程师", description="编码实现"),
    ]


def test_build_team_supervisor_spec_router_mode():
    from qwenpaw.app.experts.team_runtime import build_team_supervisor_spec

    spec, soul = build_team_supervisor_spec(
        "team_team_x",
        "/tmp/workspaces/team_x",
        _make_team("router", router_prompt="按预算选择成员"),
        _make_members(),
    )

    # The spec must stay AgentProfileConfig-compatible: this is exactly
    # the validation the publish pipeline applies before writing
    # agent.json.
    _spec_config_cls()(**spec)

    assert spec["id"] == "team_team_x"
    assert "SOUL.md" in spec["system_prompt_files"]

    # SOUL.md carries the member roster, routing rules, and the custom
    # router prompt.
    assert "架构师" in soul and "工程师" in soul
    assert "expert_exp_a" in soul  # runtime ids exposed for routing
    assert "按预算选择成员" in soul


def test_build_team_supervisor_spec_pipeline_mode():
    from qwenpaw.app.experts.team_runtime import build_team_supervisor_spec

    spec, soul = build_team_supervisor_spec(
        "team_team_x",
        "/tmp/workspaces/team_x",
        _make_team("pipeline"),
        _make_members(),
    )

    _spec_config_cls()(**spec)

    assert "端到端交付" in soul
    assert "未配置自定义路由提示词" in soul
    # Pipeline ordering (方案 → 执行) must appear in sequence.
    assert soul.index("架构师") < soul.index("工程师")
