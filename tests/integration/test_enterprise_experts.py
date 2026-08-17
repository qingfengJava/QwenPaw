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
    "expert_skills, published_experts, expert_teams, experts, "
    "token_usage_events RESTART IDENTITY"
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


def test_team_roster_renders_lead_badge_and_title():
    """member_role=lead renders the 主理人 badge; titles show too."""
    from qwenpaw.app.experts.models import (
        ExpertRecord,
        ExpertTeamRecord,
        TeamMember,
    )
    from qwenpaw.app.experts.team_runtime import build_team_supervisor_spec

    team = ExpertTeamRecord(
        id="team_y",
        name="交付专家团",
        description="",
        mode="router",
        members=[
            TeamMember(
                expert_id="exp_a",
                role_hint="方案",
                member_role="lead",
            ),
            TeamMember(expert_id="exp_b", role_hint="执行"),
        ],
    )
    members = [
        ExpertRecord(id="exp_a", name="架构师", title="首席架构师"),
        ExpertRecord(id="exp_b", name="工程师"),
    ]
    _, soul = build_team_supervisor_spec(
        "team_team_y",
        "/tmp/workspaces/team_y",
        team,
        members,
    )
    assert "主理人" in soul
    assert "首席架构师" in soul


# ---------------------------------------------------------------------------
# publish-chain pure helpers (no PG)
# ---------------------------------------------------------------------------


def _make_expert_record():
    from qwenpaw.app.experts.models import ExpertRecord

    return ExpertRecord(
        id="exp_z",
        name="法务专家",
        title="高级法务专家",
        description="合同审查",
        system_prompt="你是合同审查专家。",
        tags=["合同", "风险"],
        agent_spec={"language": "zh", "approval_level": "AUTO"},
    )


def test_expert_spec_never_contains_skills():
    """Regression guard: AgentProfileConfig silently drops a skills key,
    so the binding set must never enter the spec (it is materialized
    into the workspace skills/ directory instead)."""
    from pathlib import Path

    from qwenpaw.app.experts.publish import _build_expert_spec

    record = _make_expert_record()
    spec = _build_expert_spec(record, "expert_exp_z", Path("/tmp/ws"))

    assert "skills" not in spec
    # And the assembled spec stays AgentProfileConfig-compatible.
    _spec_config_cls()(**spec)
    assert spec["id"] == "expert_exp_z"


def test_expert_profile_md_renders_react_workflow():
    """PROFILE.md carries the persona, the ReAct loop steps, and the
    configured skill list."""
    from qwenpaw.app.experts.publish import _expert_profile_md

    record = _make_expert_record()
    md = _expert_profile_md(record, ["contract-review", "web-search"])

    assert "法务专家" in md
    assert "你是合同审查专家。" in md
    assert "高级法务专家" in md
    for step in ("理解", "规划", "决策", "生成", "核验"):
        assert step in md
    assert "contract-review" in md and "web-search" in md

    # Empty persona falls back to a title-derived default.
    bare = record.model_copy(update={"system_prompt": ""})
    md2 = _expert_profile_md(bare, [])
    assert "法务专家" in md2
    assert "未绑定技能" in md2


def test_sync_workspace_skills_reconciles(tmp_path, monkeypatch):
    """Diff sync: stale dirs removed, kept dirs untouched, missing ones
    tolerated as warnings (never raise). The default-workspace fallback
    stays silent because the requested name cannot exist anywhere."""
    from qwenpaw.app.experts import publish as publish_mod

    # Keep the fallback source out of the test: no default workspace.
    monkeypatch.setattr(
        publish_mod,
        "_default_workspace_dir",
        lambda: None,
    )
    skills_dir = tmp_path / "skills"
    (skills_dir / "stale-skill").mkdir(parents=True)
    (skills_dir / "kept-skill").mkdir()
    (skills_dir / "kept-skill" / "SKILL.md").write_text("x", encoding="utf-8")

    publish_mod._sync_workspace_skills(
        tmp_path,
        ["kept-skill", "zz-definitely-missing-skill"],
    )

    assert not (skills_dir / "stale-skill").exists()
    assert (skills_dir / "kept-skill" / "SKILL.md").exists()
    assert not (skills_dir / "zz-definitely-missing-skill").exists()


# ---------------------------------------------------------------------------
# catalog fields / market queries / skill bindings (PG required)
# ---------------------------------------------------------------------------


async def test_expert_catalog_fields_roundtrip(enterprise_env, store):
    created = await store.create_expert(
        name="合同专家",
        description="合同审查与风险提示",
        agent_spec={"language": "zh"},
        owner_id="alice",
        visibility="private",
        title="高级法务专家",
        category="business",
        badge="特邀专家",
        tags=["合同", "风险"],
        system_prompt="你是合同审查专家。",
        featured=True,
    )
    assert created.owner_id == "alice"
    assert created.visibility == "private"
    assert created.is_builtin is False
    assert created.title == "高级法务专家"
    assert created.category == "business"
    assert created.badge == "特邀专家"
    assert created.tags == ["合同", "风险"]
    assert created.system_prompt == "你是合同审查专家。"
    assert created.featured is True
    assert created.usage_count == 0

    updated = await store.update_expert(
        created.id,
        title="首席法务专家",
        tags=["合同"],
        visibility="org",
    )
    assert updated.title == "首席法务专家"
    assert updated.tags == ["合同"]
    assert updated.visibility == "org"


def _mk_expert_kwargs(name: str, **overrides):
    base = {
        "name": name,
        "description": f"{name} 的描述",
        "agent_spec": {"language": "zh"},
    }
    base.update(overrides)
    return base


async def test_list_experts_filters_and_sorts(enterprise_env, store):
    hot = await store.create_expert(
        **_mk_expert_kwargs("热门专家", category="dev", title="开发")
    )
    new_one = await store.create_expert(
        **_mk_expert_kwargs("新专家", category="writing")
    )
    private_one = await store.create_expert(
        **_mk_expert_kwargs(
            "私有权家",
            owner_id="alice",
            visibility="private",
        )
    )
    await store.bump_usage(hot.id)
    await store.bump_usage(hot.id)
    await store.bump_usage(new_one.id)

    # Keyword search hits name/description/title.
    hits = await store.list_experts(q="开发")
    assert {e.id for e in hits} == {hot.id}

    # Category filter.
    devs = await store.list_experts(category="dev")
    assert {e.id for e in devs} == {hot.id}

    # Hot sort: usage_count descending.
    ranked = await store.list_experts(sort="hot")
    assert ranked[0].id == hot.id

    # New sort: created_at descending (latest insert first).
    newest = await store.list_experts(sort="new")
    assert newest[0].id == private_one.id

    # Owner scope.
    mine = await store.list_experts(owner="alice")
    assert {e.id for e in mine} == {private_one.id}

    # Visibility widening for the owner under a status filter.
    visible = await store.list_experts(
        status="published",
        include_private_for="alice",
    )
    # Nothing published yet; the private draft is not surfaced by a
    # published-status query even for its owner.
    assert visible == []
    assert {e.id for e in await store.list_experts()} >= {
        hot.id,
        new_one.id,
        private_one.id,
    }


async def test_skill_bindings_replace_and_cap(enterprise_env, store):
    from qwenpaw.app.experts.models import ExpertSkillBinding

    expert = await store.create_expert(**_mk_expert_kwargs("带技能专家"))

    await store.replace_skills(
        expert.id,
        [
            ExpertSkillBinding(skill_name="b-skill", seq=1),
            ExpertSkillBinding(skill_name="a-skill", seq=0),
            ExpertSkillBinding(skill_name="a-skill", seq=2),  # dup
        ],
    )
    bindings = await store.list_skills(expert.id)
    assert [b.skill_name for b in bindings] == ["a-skill", "b-skill"]
    assert await store.enabled_skill_names(expert.id) == [
        "a-skill",
        "b-skill",
    ]

    # Disabled bindings stay stored but leave the enabled set.
    await store.replace_skills(
        expert.id,
        [
            ExpertSkillBinding(skill_name="a-skill"),
            ExpertSkillBinding(skill_name="off-skill", enabled=False),
        ],
    )
    assert await store.enabled_skill_names(expert.id) == ["a-skill"]
    assert len(await store.list_skills(expert.id)) == 2

    # Cap: 12 requested → MAX_EXPERT_SKILLS (8) kept.
    many = [ExpertSkillBinding(skill_name=f"s{i}") for i in range(12)]
    capped = await store.replace_skills(expert.id, many)
    assert len(capped) == 8

    # Draft deletion clears the bindings with it.
    assert await store.delete_expert(expert.id) is True
    assert await store.list_skills(expert.id) == []


async def test_bump_usage_atomic(enterprise_env, store):
    expert = await store.create_expert(**_mk_expert_kwargs("计数专家"))
    for expected in (1, 2, 3):
        assert await store.bump_usage(expert.id) == expected
    assert (await store.get_expert(expert.id)).usage_count == 3
    # Missing experts report 0 instead of raising.
    assert await store.bump_usage("exp_missing") == 0


async def test_list_teams_returns_member_roles(enterprise_env, store):
    from qwenpaw.app.experts.models import TeamMember

    e1 = await store.create_expert(**_mk_expert_kwargs("写手"))
    e2 = await store.create_expert(**_mk_expert_kwargs("审校"))
    team = await store.create_team(name="内容团队")
    await store.update_team(
        team.id,
        members=[
            TeamMember(
                expert_id=e1.id,
                role_hint="执笔",
                member_role="lead",
            ),
            TeamMember(expert_id=e2.id, role_hint="终审"),
        ],
    )
    teams = await store.list_teams()
    target = next(t for t in teams if t.id == team.id)
    assert target.members[0].member_role == "lead"
    assert target.members[1].member_role == "member"
