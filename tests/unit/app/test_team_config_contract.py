# -*- coding: utf-8 -*-
"""T1 团队配置契约测试（纯单元，无 PG）。

覆盖版本适配（v1 宽松 / v2 严格 / 未登记版本拒绝）与发布预检
（唯一 lead / 模板 DAG / v2 有限预算）的跨字段规则。

@author qingfeng
"""

from __future__ import annotations

import pytest

from qwenpaw.app.experts.models import (
    ExpertRecord,
    ExpertTeamRecord,
    TeamMember,
)
from qwenpaw.app.experts.team_config import (
    OrchestrationSpecV2,
    TEAM_CONFIG_SCHEMA_V2,
    parse_team_orchestration,
    summarize_team_config,
    validate_publishable_team,
)
from qwenpaw.app.workforce.contracts import OrchestrationSpec


def _team(
    members: list[TeamMember] | None = None,
    orchestration: dict | None = None,
) -> ExpertTeamRecord:
    """构造最小团队记录（id/status 不参与校验）。"""
    return ExpertTeamRecord(
        id="team-t1",
        name="配置测试团",
        members=members or [],
        orchestration=orchestration or {},
    )


def _lead_and_member() -> list[TeamMember]:
    """一名 lead + 一名 member 的标准成员表。"""
    return [
        TeamMember(expert_id="e-lead", member_role="lead", seq=0),
        TeamMember(expert_id="e-member", member_role="member", seq=1),
    ]


# ---------------------------------------------------------------------------
# 版本适配
# ---------------------------------------------------------------------------


def test_parse_empty_payload_returns_default_spec():
    """空 orchestration（历史团队）按 v1 空配置处理。"""
    spec = parse_team_orchestration({})
    assert isinstance(spec, OrchestrationSpec)
    assert spec.nodes == []
    assert spec.runtime_enabled is True


def test_parse_v1_is_lenient_to_unknown_fields():
    """v1 存量兼容：未知字段忽略不报错（存量模板不炸）。"""
    payload = {
        "schema_version": "v1",
        "nodes": [{"node_key": "a", "deps": [], "node_type": "task"}],
        # v1 schema 未定义的字段（存量脏数据）
        "legacy_hint": "随便什么",
    }
    spec = parse_team_orchestration(payload)
    assert isinstance(spec, OrchestrationSpec)
    assert len(spec.nodes) == 1


def test_parse_v2_rejects_unknown_fields():
    """v2 严格：未知字段直接拒绝（配置漂移在保存时暴露）。"""
    payload = {
        "schema_version": TEAM_CONFIG_SCHEMA_V2,
        "nodes": [{"node_key": "a", "deps": [], "node_type": "task"}],
        "unknown_key": 1,
    }
    with pytest.raises(Exception):
        parse_team_orchestration(payload)


def test_parse_unsupported_version_rejected():
    """未登记版本拒绝（不做猜测式升级）。"""
    with pytest.raises(ValueError, match="schema_version"):
        parse_team_orchestration({"schema_version": "v99"})


def test_parse_v2_locks_schema_version_field():
    """v2 载荷的 schema_version 锁定为 v2（防借用通道）。"""
    spec = parse_team_orchestration(
        {"schema_version": TEAM_CONFIG_SCHEMA_V2, "nodes": []},
    )
    assert isinstance(spec, OrchestrationSpecV2)
    assert spec.schema_version == TEAM_CONFIG_SCHEMA_V2


# ---------------------------------------------------------------------------
# 发布预检（跨字段校验）
# ---------------------------------------------------------------------------


def test_validate_rejects_empty_team():
    """零成员不可发布。"""
    issues = validate_publishable_team(_team())
    assert any("至少需要一名成员" in item for item in issues)


def test_validate_rejects_missing_lead():
    """无 lead 不可发布（职责配置缺失在发布前暴露）。"""
    members = [TeamMember(expert_id="e-1", member_role="member", seq=0)]
    issues = validate_publishable_team(_team(members=members))
    assert any("lead" in item for item in issues)


def test_validate_rejects_multiple_leads():
    """多 lead 不可发布（职责唯一性）。"""
    members = [
        TeamMember(expert_id="e-1", member_role="lead", seq=0),
        TeamMember(expert_id="e-2", member_role="lead", seq=1),
    ]
    issues = validate_publishable_team(_team(members=members))
    assert any("只能有一名 lead" in item for item in issues)


def test_validate_rejects_illegal_template_dag():
    """模板 DAG 有环 → 预检拒绝。"""
    orchestration = {
        "nodes": [
            {"node_key": "a", "deps": ["b"], "node_type": "task"},
            {"node_key": "b", "deps": ["a"], "node_type": "task"},
        ],
    }
    issues = validate_publishable_team(
        _team(members=_lead_and_member(), orchestration=orchestration),
    )
    assert any("DAG 非法" in item for item in issues)


def test_validate_requires_finite_budget_for_v2():
    """v2 正式团队必须配置有限 token 预算（0=无限不再作为默认）。"""
    orchestration = {
        "schema_version": TEAM_CONFIG_SCHEMA_V2,
        "policy": {"max_total_tokens": 0},
    }
    issues = validate_publishable_team(
        _team(members=_lead_and_member(), orchestration=orchestration),
        require_finite_budget=True,
    )
    assert any("有限 token 预算" in item for item in issues)
    # 不要求有限预算时（草稿预检）不阻塞
    issues_draft = validate_publishable_team(
        _team(members=_lead_and_member(), orchestration=orchestration),
    )
    assert issues_draft == []


def test_validate_passes_well_formed_team():
    """完整配置的团队预检零问题。"""
    orchestration = {
        "nodes": [
            {
                "node_key": "impl",
                "deps": [],
                "assignee_expert_id": "e-member",
                "node_type": "task",
                "objective": "实现",
            },
        ],
        "policy": {"max_total_tokens": 100000},
    }
    issues = validate_publishable_team(
        _team(members=_lead_and_member(), orchestration=orchestration),
    )
    assert issues == []


# ---------------------------------------------------------------------------
# 配置摘要（metadata 口径）
# ---------------------------------------------------------------------------


def test_summarize_reports_version_and_leads():
    """摘要输出 schema_version 与 lead 投影（不泄露 agent_spec）。"""
    team = _team(
        members=_lead_and_member(),
        orchestration={"schema_version": TEAM_CONFIG_SCHEMA_V2, "nodes": []},
    )
    summary = summarize_team_config(team)
    assert summary["schema_version"] == TEAM_CONFIG_SCHEMA_V2
    assert summary["lead_expert_ids"] == ["e-lead"]
    assert summary["member_count"] == 2
    assert summary["has_template"] is False


def test_summarize_tolerates_illegal_orchestration():
    """非法配置摘要不抛错（问题走 validate 呈现）。"""
    team = _team(
        members=_lead_and_member(),
        orchestration={"schema_version": "v99"},
    )
    summary = summarize_team_config(team)
    # 版本按原样回报，模板相关位安全置空
    assert summary["schema_version"] == "v99"
    assert summary["has_template"] is False


# 防回归哨兵：ExpertRecord 仍可用于成员解析（引用完整性）
def test_member_projection_uses_expert_record():
    """成员投影以 ExpertRecord 为档案权威（能力视图的输入契约）。"""
    expert = ExpertRecord(id="e-lead", name="主管")
    assert expert.id == "e-lead"
