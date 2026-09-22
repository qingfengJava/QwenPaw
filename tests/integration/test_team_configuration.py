# -*- coding: utf-8 -*-
"""T1 团队配置集成测试（PG 门控，QWENPAW_TEST_PG_DSN）。

覆盖：发布预检阻塞（无 lead / v2 无限预算）、发布成功写版本快照、
版本清单、能力投影与元数据服务。无 DSN 时整组跳过。

@author qingfeng
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

DSN = os.environ.get("QWENPAW_TEST_PG_DSN", "").strip()

_TRUNCATE_SQL = (
    "TRUNCATE team_run_nodes, team_runs, feed_events, project_members, "
    "tasks, projects, expert_team_members, expert_team_versions, "
    "expert_skills, published_experts, expert_teams, experts, "
    "employee_governance, token_usage_events RESTART IDENTITY"
)


@pytest.fixture
async def enterprise_env(monkeypatch):
    """与 test_workforce_runs 同款企业环境装置（隔离测试库）。"""
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
        await engine_mod.dispose_engines()
        ent_mod._schema_ready = False


async def _seed_experts():
    """建两名 draft 员工，返回 (lead, member)。"""
    from qwenpaw.app.experts.store import ExpertStore

    store = ExpertStore()
    lead = await store.create_expert(name="T1主管", icon="L", description="")
    member = await store.create_expert(name="T1成员", icon="M", description="")
    return lead, member


async def test_t1_publish_blocked_without_lead(enterprise_env):
    """无 lead 的团队发布被预检拒绝（ValueError）。"""
    from qwenpaw.app.experts.models import TeamMember
    from qwenpaw.app.experts.publish import publish_expert_team
    from qwenpaw.app.experts.store import ExpertStore

    lead, member = await _seed_experts()
    # 双双发布为可执行员工（成员可用性通过，仅缺 lead 职责）
    store = ExpertStore()
    await store.set_expert_status(lead.id, "published")
    await store.set_expert_status(member.id, "published")
    team = await store.create_team(
        name="无主理人团",
        members=[
            TeamMember(expert_id=lead.id, member_role="member", seq=0),
            TeamMember(expert_id=member.id, member_role="member", seq=1),
        ],
    )
    with pytest.raises(ValueError, match="lead"):
        await publish_expert_team(team.id, published_by="tester")


async def test_t1_publish_records_version_snapshot(enterprise_env):
    """发布成功写入不可变版本快照；重发布追加新版本行。"""
    from qwenpaw.app.experts.models import TeamMember
    from qwenpaw.app.experts.publish import publish_expert_team
    from qwenpaw.app.experts.store import ExpertStore

    lead, member = await _seed_experts()
    store = ExpertStore()
    await store.set_expert_status(lead.id, "published")
    await store.set_expert_status(member.id, "published")
    team = await store.create_team(
        name="快照团",
        members=[
            TeamMember(expert_id=lead.id, member_role="lead", seq=0),
            TeamMember(expert_id=member.id, member_role="member", seq=1),
        ],
        orchestration={
            "policy": {"max_total_tokens": 50000},
        },
    )
    published = await publish_expert_team(team.id, published_by="tester")
    versions = await store.list_team_versions(team.id)
    assert len(versions) == 1
    assert versions[0]["version"] == published.version
    assert versions[0]["published_by"] == "tester"
    # 重发布 → 新版本行（不可变快照，追加而非覆盖）
    republished = await publish_expert_team(team.id, published_by="tester2")
    versions2 = await store.list_team_versions(team.id)
    assert len(versions2) == 2
    assert versions2[0]["version"] == republished.version
    assert versions2[0]["published_by"] == "tester2"


async def test_t1_validate_team_reports_issues(enterprise_env):
    """预检服务汇总配置与成员可用性问题（未发布成员阻塞）。"""
    from qwenpaw.app.experts.models import TeamMember
    from qwenpaw.app.experts.store import ExpertStore
    from qwenpaw.app.experts.team_service import validate_team

    lead, member = await _seed_experts()
    store = ExpertStore()
    team = await store.create_team(
        name="预检团",
        members=[
            TeamMember(expert_id=lead.id, member_role="lead", seq=0),
            TeamMember(expert_id=member.id, member_role="member", seq=1),
        ],
    )
    # 成员均未发布：预检应同时报告两条可用性问题
    result = await validate_team(team.id)
    assert result["ok"] is False
    joined = "\n".join(result["issues"])
    assert "未发布" in joined
    # 配置摘要可用
    assert result["config"]["lead_expert_ids"] == [lead.id]


async def test_t1_capability_view_projects_members(enterprise_env):
    """能力投影返回成员职责与已发布标记（声明≠可执行）。"""
    from qwenpaw.app.experts.capability_view import team_capability_view
    from qwenpaw.app.experts.models import TeamMember
    from qwenpaw.app.experts.store import ExpertStore

    lead, member = await _seed_experts()
    store = ExpertStore()
    await store.set_expert_status(lead.id, "published")
    team = await store.create_team(
        name="投影团",
        members=[
            TeamMember(expert_id=lead.id, member_role="lead", seq=0),
            TeamMember(expert_id=member.id, member_role="member", seq=1),
        ],
    )
    view = await team_capability_view(team.id)
    by_id = {m["expert_id"]: m for m in view["members"]}
    # 已发布 lead：可执行
    assert by_id[lead.id]["published"] is True
    assert by_id[lead.id]["member_role"] == "lead"
    # 未发布 member：标注不可执行原因
    assert by_id[member.id]["published"] is False
    assert "未发布" in by_id[member.id]["unavailable_reason"]


async def test_t1_team_metadata_shape(enterprise_env):
    """元数据服务提供角色/模式/限额（前端枚举唯一来源）。"""
    from qwenpaw.app.experts.team_service import team_metadata

    meta = await team_metadata()
    roles = {item["value"] for item in meta["member_roles"]}
    assert "lead" in roles and "member" in roles
    assert meta["limits"]["default_max_repair_per_node"] > 0
    # 协作模式携带机制说明（团队详情页"协作机制卡"数据源，禁止前端硬编码）
    mode_desc = {
        item["value"]: item.get("description", "")
        for item in meta["team_modes"]
    }
    assert mode_desc.get("router"), "router 模式必须提供协作机制说明"
    assert mode_desc.get("pipeline"), "pipeline 模式必须提供协作机制说明"
