# -*- coding: utf-8 -*-
"""P2 两级发布单元测试（纯单元，无 PG）。

覆盖：

- ``USAGE_MODE`` 常量正确性；
- ``ExpertRecord`` P2 字段（usage_mode / published_version）默认值与序列化；
- ``TeamMember.expert_version`` 版本绑定语义；
- ``ExpertTeamRecord.published_version`` 团队发布指针；
- ``member-updates`` 端点升级判定逻辑（纯函数提取）。

@author qingfeng
"""

from __future__ import annotations

import pytest

from qwenpaw.app.experts.models import (
    USAGE_MODE_SHARED,
    USAGE_MODE_TEAM_ONLY,
    USAGE_MODES,
    ExpertRecord,
    ExpertTeamRecord,
    TeamMember,
)
from qwenpaw.app.experts.team_service import compute_member_upgrades

#: 端点与单测共用的唯一实现（服务层纯函数；原测试副本已删除，
#: 避免双份维护漂移导致断言与实现脱节）
_compute_upgrades = compute_member_upgrades


# ---------------------------------------------------------------------------
# USAGE_MODE constants
# ---------------------------------------------------------------------------


class TestUsageModeConstants:
    """使用范围常量：值与元组完整性。"""

    def test_team_only_value(self):
        assert USAGE_MODE_TEAM_ONLY == "team_only"

    def test_shared_value(self):
        assert USAGE_MODE_SHARED == "shared"

    def test_modes_tuple_contains_both(self):
        assert USAGE_MODE_TEAM_ONLY in USAGE_MODES
        assert USAGE_MODE_SHARED in USAGE_MODES
        assert len(USAGE_MODES) == 2


# ---------------------------------------------------------------------------
# ExpertRecord P2 fields
# ---------------------------------------------------------------------------


class TestExpertRecordP2Fields:
    """员工记录 P2 新增字段：默认值与显式赋值。"""

    def _minimal_expert(self, **overrides):
        base = {"id": "e-1", "name": "测试员工"}
        base.update(overrides)
        return ExpertRecord(**base)

    def test_default_usage_mode_is_shared(self):
        expert = self._minimal_expert()
        assert expert.usage_mode == "shared"

    def test_default_published_version_is_zero(self):
        expert = self._minimal_expert()
        assert expert.published_version == 0

    def test_explicit_team_only(self):
        expert = self._minimal_expert(usage_mode="team_only")
        assert expert.usage_mode == "team_only"

    def test_explicit_published_version(self):
        expert = self._minimal_expert(published_version=5)
        assert expert.published_version == 5

    def test_model_dump_includes_p2_fields(self):
        expert = self._minimal_expert(usage_mode="team_only", published_version=3)
        dumped = expert.model_dump()
        assert dumped["usage_mode"] == "team_only"
        assert dumped["published_version"] == 3

    def test_p2_fields_do_not_break_existing_fields(self):
        expert = self._minimal_expert(
            status="published",
            version=2,
            usage_mode="shared",
            published_version=7,
        )
        assert expert.status == "published"
        assert expert.version == 2
        assert expert.usage_mode == "shared"
        assert expert.published_version == 7


# ---------------------------------------------------------------------------
# TeamMember P2 fields
# ---------------------------------------------------------------------------


class TestTeamMemberP2Fields:
    """团队成员 P2 版本绑定：expert_version 默认 None，可显式指定。"""

    def test_default_expert_version_is_none(self):
        member = TeamMember(expert_id="e-1")
        assert member.expert_version is None

    def test_explicit_expert_version(self):
        member = TeamMember(expert_id="e-1", expert_version=3)
        assert member.expert_version == 3

    def test_expert_version_zero(self):
        """版本 0 是合法值（表示"选定但尚未发布"），不应等同于 None。"""
        member = TeamMember(expert_id="e-1", expert_version=0)
        assert member.expert_version == 0
        assert member.expert_version is not None

    def test_model_dump_preserves_version(self):
        member = TeamMember(expert_id="e-1", expert_version=5)
        dumped = member.model_dump()
        assert dumped["expert_version"] == 5

    def test_model_dump_none_version(self):
        member = TeamMember(expert_id="e-1")
        dumped = member.model_dump()
        assert dumped["expert_version"] is None


# ---------------------------------------------------------------------------
# ExpertTeamRecord P2 fields
# ---------------------------------------------------------------------------


class TestExpertTeamRecordP2Fields:
    """团队记录 P2 发布指针：published_version 默认 0。"""

    def _minimal_team(self, **overrides):
        base = {"id": "t-1", "name": "测试团队"}
        base.update(overrides)
        return ExpertTeamRecord(**base)

    def test_default_published_version_is_zero(self):
        team = self._minimal_team()
        assert team.published_version == 0

    def test_explicit_published_version(self):
        team = self._minimal_team(published_version=10)
        assert team.published_version == 10

    def test_model_dump_includes_published_version(self):
        team = self._minimal_team(published_version=4)
        dumped = team.model_dump()
        assert dumped["published_version"] == 4

    def test_published_version_coexists_with_draft_revision(self):
        """P1 draft_revision 与 P2 published_version 并存不冲突。"""
        team = self._minimal_team(draft_revision=7, published_version=3)
        assert team.draft_revision == 7
        assert team.published_version == 3


# ---------------------------------------------------------------------------
# member-upgrades upgrade logic（服务层唯一实现）
# ---------------------------------------------------------------------------


class TestMemberUpgradeLogic:
    """成员升级判定：绑定版本 vs 最新发布版本。"""

    def test_no_members_returns_empty(self):
        assert _compute_upgrades([], []) == []

    def test_expert_not_found_latest_is_zero(self):
        """成员关联的员工不存在时，latest=0，不可升级。"""
        members = [TeamMember(expert_id="e-missing", expert_version=None)]
        result = _compute_upgrades(members, [])
        assert len(result) == 1
        assert result[0]["latest_version"] == 0
        assert result[0]["upgradable"] is False

    def test_bound_none_not_upgradable_when_same_version(self):
        """绑定为 None（未指定）且 latest=0：不可升级。"""
        members = [TeamMember(expert_id="e-1", expert_version=None)]
        cards = [ExpertRecord(id="e-1", name="专家", published_version=0)]
        result = _compute_upgrades(members, cards)
        assert result[0]["upgradable"] is False

    def test_upgradable_when_latest_greater_than_bound(self):
        """最新发布版本 > 绑定版本：可升级。"""
        members = [TeamMember(expert_id="e-1", expert_version=2)]
        cards = [ExpertRecord(id="e-1", name="专家", published_version=5)]
        result = _compute_upgrades(members, cards)
        assert result[0]["bound_version"] == 2
        assert result[0]["latest_version"] == 5
        assert result[0]["upgradable"] is True

    def test_not_upgradable_when_bound_equals_latest(self):
        """绑定版本 == 最新版本：不可升级。"""
        members = [TeamMember(expert_id="e-1", expert_version=3)]
        cards = [ExpertRecord(id="e-1", name="专家", published_version=3)]
        result = _compute_upgrades(members, cards)
        assert result[0]["upgradable"] is False

    def test_not_upgradable_when_bound_greater(self):
        """绑定版本 > 最新版本（理论上不应出现，但防御性验证）：不可升级。"""
        members = [TeamMember(expert_id="e-1", expert_version=10)]
        cards = [ExpertRecord(id="e-1", name="专家", published_version=3)]
        result = _compute_upgrades(members, cards)
        assert result[0]["upgradable"] is False

    def test_bound_none_with_positive_latest_is_upgradable(self):
        """绑定为 None（未指定），但员工已发布（latest > 0）：可升级。"""
        members = [TeamMember(expert_id="e-1", expert_version=None)]
        cards = [ExpertRecord(id="e-1", name="专家", published_version=1)]
        result = _compute_upgrades(members, cards)
        # None or 0 = 0, latest=1 > 0 → upgradable
        assert result[0]["upgradable"] is True

    def test_multiple_members_mixed(self):
        """多成员混合场景：部分可升级、部分不可。"""
        members = [
            TeamMember(expert_id="e-1", expert_version=1),  # 可升级
            TeamMember(expert_id="e-2", expert_version=3),  # 已是最新
            TeamMember(expert_id="e-3", expert_version=None),  # 未指定，未发布
        ]
        cards = [
            ExpertRecord(id="e-1", name="专家1", published_version=5),
            ExpertRecord(id="e-2", name="专家2", published_version=3),
            ExpertRecord(id="e-3", name="专家3", published_version=0),
        ]
        result = _compute_upgrades(members, cards)
        assert result[0]["upgradable"] is True
        assert result[1]["upgradable"] is False
        assert result[2]["upgradable"] is False

    def test_expert_name_included_in_result(self):
        """结果包含员工名称，便于前端展示。"""
        members = [TeamMember(expert_id="e-1", expert_version=1)]
        cards = [ExpertRecord(id="e-1", name="小助手", published_version=2)]
        result = _compute_upgrades(members, cards)
        assert result[0]["expert_name"] == "小助手"

    def test_missing_expert_name_is_empty_string(self):
        """员工不存在时名称为空串。"""
        members = [TeamMember(expert_id="e-missing", expert_version=1)]
        result = _compute_upgrades(members, [])
        assert result[0]["expert_name"] == ""
