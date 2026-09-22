# -*- coding: utf-8 -*-
"""P1 领域契约单元测试（纯单元，无 PG）。

覆盖：

- ``DraftRevisionConflict`` 异常属性；
- ``PublishedTeamCard`` 安全 DTO 字段投影；
- ``TeamActionCapabilities`` 默认值与序列化；
- ``resolve_effective_config`` 有效配置合并（默认值填充、lead 投影）。

@author qingfeng
"""

from __future__ import annotations

import pytest

from qwenpaw.app.experts.models import (
    ExpertTeamRecord,
    PublishedTeamCard,
    TeamActionCapabilities,
    TeamMember,
)
from qwenpaw.app.experts.store import DraftRevisionConflict
from qwenpaw.app.experts.team_config import resolve_effective_config


# ---------------------------------------------------------------------------
# DraftRevisionConflict
# ---------------------------------------------------------------------------


class TestDraftRevisionConflict:
    """CAS 乐观锁异常：属性暴露与 str 表示。"""

    def test_attributes_are_accessible(self):
        exc = DraftRevisionConflict(team_id="t-1", expected=3, actual=5)
        assert exc.team_id == "t-1"
        assert exc.expected == 3
        assert exc.actual == 5

    def test_str_contains_conflict_info(self):
        exc = DraftRevisionConflict(team_id="t-1", expected=3, actual=5)
        msg = str(exc)
        assert "t-1" in msg
        assert "3" in msg
        assert "5" in msg

    def test_is_exception_subclass(self):
        exc = DraftRevisionConflict(team_id="t-1", expected=0, actual=1)
        assert isinstance(exc, Exception)


# ---------------------------------------------------------------------------
# PublishedTeamCard
# ---------------------------------------------------------------------------


class TestPublishedTeamCard:
    """安全 DTO：只暴露公开面字段，不泄露草稿/内部指令。"""

    def test_minimal_construction(self):
        card = PublishedTeamCard(id="t-1", name="测试团")
        assert card.id == "t-1"
        assert card.name == "测试团"
        assert card.description == ""
        assert card.version == 1
        assert card.member_count == 0
        assert card.members == []
        assert card.sample_tasks == []
        assert card.showcase == []

    def test_full_construction(self):
        card = PublishedTeamCard(
            id="t-2",
            name="全量团",
            description="描述",
            mode="pipeline",
            version=3,
            agent_id="team_t-2",
            category="research",
            tags=["tag1", "tag2"],
            member_count=2,
            members=[{"expert_id": "e1", "name": "专家1"}],
            sample_tasks=[{"title": "示例", "prompt": "do it"}],
            showcase=[{"title": "案例"}],
        )
        assert card.mode == "pipeline"
        assert card.version == 3
        assert card.agent_id == "team_t-2"
        assert card.member_count == 2
        assert len(card.members) == 1
        assert len(card.tags) == 2

    def test_model_dump_excludes_no_fields(self):
        """model_dump 输出包含所有公开面字段。"""
        card = PublishedTeamCard(id="t-1", name="测试")
        dumped = card.model_dump()
        assert "id" in dumped
        assert "name" in dumped
        assert "agent_id" in dumped
        assert "member_count" in dumped
        assert "sample_tasks" in dumped
        assert "showcase" in dumped
        # 不应包含草稿内部字段
        assert "draft_revision" not in dumped
        assert "router_prompt" not in dumped
        assert "orchestration" not in dumped


# ---------------------------------------------------------------------------
# TeamActionCapabilities
# ---------------------------------------------------------------------------


class TestTeamActionCapabilities:
    """动作能力矩阵默认值与序列化。"""

    def test_defaults_are_safe(self):
        cap = TeamActionCapabilities(team_id="t-1")
        assert cap.can_view_published is True
        assert cap.can_edit_draft is False
        assert cap.can_publish is False
        assert cap.can_execute is False
        assert cap.manageable is False

    def test_full_capabilities(self):
        cap = TeamActionCapabilities(
            team_id="t-1",
            can_view_published=True,
            can_edit_draft=True,
            can_publish=True,
            can_execute=True,
            manageable=True,
        )
        assert cap.manageable is True
        assert cap.can_publish is True

    def test_model_dump_roundtrip(self):
        cap = TeamActionCapabilities(
            team_id="t-1",
            can_edit_draft=True,
            manageable=True,
        )
        dumped = cap.model_dump()
        assert dumped["team_id"] == "t-1"
        assert dumped["can_edit_draft"] is True
        assert dumped["manageable"] is True


# ---------------------------------------------------------------------------
# resolve_effective_config
# ---------------------------------------------------------------------------


def _team(
    members: list[TeamMember] | None = None,
    orchestration: dict | None = None,
) -> ExpertTeamRecord:
    """构造最小团队记录。"""
    return ExpertTeamRecord(
        id="team-ec",
        name="有效配置测试",
        members=members or [],
        orchestration=orchestration or {},
    )


class TestResolveEffectiveConfig:
    """统一有效配置解析：默认值填充 + lead 投影 + 成员投影。"""

    def test_empty_team_defaults(self):
        """空团队空配置：返回引擎默认 policy 和空投影。"""
        team = _team()
        result = resolve_effective_config(team)
        assert result["schema_version"] == "v1"
        assert result["runtime_enabled"] is True
        assert result["lead_expert_ids"] == []
        assert result["member_expert_ids"] == []
        assert result["has_template"] is False
        # policy 应填充为引擎默认值（非空 dict）
        assert isinstance(result["policy"], dict)
        assert "max_total_tokens" in result["policy"]

    def test_lead_projection(self):
        """lead 成员正确投影到 lead_expert_ids。"""
        members = [
            TeamMember(expert_id="e-lead", member_role="lead", seq=0),
            TeamMember(expert_id="e-member", member_role="member", seq=1),
        ]
        team = _team(members=members)
        result = resolve_effective_config(team)
        assert result["lead_expert_ids"] == ["e-lead"]
        assert result["member_expert_ids"] == ["e-lead", "e-member"]

    def test_invalid_orchestration_returns_empty_spec(self):
        """非法 orchestration 不崩溃：spec 为空，policy 回退默认。"""
        team = _team(orchestration={"schema_version": "v99_unknown"})
        result = resolve_effective_config(team)
        # 非法版本解析失败，spec 为空
        assert result["spec"] == {}
        assert result["has_template"] is False
        # policy 回退到引擎默认
        assert "max_total_tokens" in result["policy"]

    def test_valid_v1_orchestration_extracts_fields(self):
        """v1 合法配置：正确提取 runtime_enabled / nodes 投影。"""
        team = _team(
            members=[TeamMember(expert_id="e1", member_role="lead")],
            orchestration={
                "schema_version": "v1",
                "runtime_enabled": False,
                "nodes": [
                    {"node_key": "a", "deps": [], "node_type": "task"},
                ],
            },
        )
        result = resolve_effective_config(team)
        assert result["schema_version"] == "v1"
        assert result["runtime_enabled"] is False
        assert result["has_template"] is True
        assert result["spec"]["nodes"][0]["node_key"] == "a"
