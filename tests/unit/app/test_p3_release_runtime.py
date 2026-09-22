# -*- coding: utf-8 -*-
"""P3 固定执行与专属准入单元测试（纯单元，无 PG）。

覆盖：

- ``VersionedInstanceKey`` 不可变实例键构建与序列化；
- ``ResolvedTeamVersion`` 团队版本解析与成员查询；
- ``bind_session_team_version`` 会话绑定与防覆盖；
- ``check_expert_access`` team_only 专属准入判定；
- ``check_team_member_access`` 团队成员准入验证；
- ``compute_spec_hash`` 发布包内容哈希幂等性。

@author qingfeng
"""

from __future__ import annotations

import pytest

from qwenpaw.app.experts.models import (
    ExpertRecord,
    ExpertTeamRecord,
    TeamMember,
)
from qwenpaw.app.experts.release_runtime import (
    SESSION_META_TEAM_ID_KEY,
    SESSION_META_TEAM_VERSION_KEY,
    AccessDecision,
    VersionedInstanceKey,
    bind_session_team_version,
    build_instance_key,
    check_expert_access,
    check_team_member_access,
    compute_spec_hash,
    get_session_team_version,
    resolve_team_version,
)


# ---------------------------------------------------------------------------
# VersionedInstanceKey
# ---------------------------------------------------------------------------


class TestVersionedInstanceKey:
    """版本化实例键：不可变、可哈希、唯一性。"""

    def test_basic_construction(self):
        key = build_instance_key(
            tenant_id="default",
            expert_id="e-1",
            version=3,
        )
        assert key.tenant_id == "default"
        assert key.expert_id == "e-1"
        assert key.version == 3
        assert key.scope == ""

    def test_agent_id_format(self):
        key = build_instance_key(
            tenant_id="default",
            expert_id="e-1",
            version=1,
        )
        assert key.agent_id == "expert_e-1"

    def test_instance_key_without_scope(self):
        key = build_instance_key(
            tenant_id="default",
            expert_id="e-1",
            version=3,
        )
        assert key.instance_key == "default:expert_e-1:v3"

    def test_instance_key_with_scope(self):
        key = build_instance_key(
            tenant_id="default",
            expert_id="e-1",
            version=3,
            scope="run-abc",
        )
        assert key.instance_key == "default:expert_e-1:v3:run-abc"

    def test_frozen_dataclass_is_hashable(self):
        key = build_instance_key(
            tenant_id="default",
            expert_id="e-1",
            version=1,
        )
        # 可用作 dict key 和 set 成员
        d = {key: "value"}
        assert d[key] == "value"
        s = {key}
        assert key in s

    def test_different_versions_different_keys(self):
        k1 = build_instance_key(tenant_id="t", expert_id="e", version=1)
        k2 = build_instance_key(tenant_id="t", expert_id="e", version=2)
        assert k1.instance_key != k2.instance_key
        assert k1 != k2

    def test_different_tenants_different_keys(self):
        k1 = build_instance_key(tenant_id="a", expert_id="e", version=1)
        k2 = build_instance_key(tenant_id="b", expert_id="e", version=1)
        assert k1.instance_key != k2.instance_key

    def test_content_hash_is_stable(self):
        k = build_instance_key(tenant_id="t", expert_id="e", version=1)
        h1 = k.content_hash()
        h2 = k.content_hash()
        assert h1 == h2
        assert len(h1) == 16  # SHA-256 截断到 16 字符


# ---------------------------------------------------------------------------
# ResolvedTeamVersion
# ---------------------------------------------------------------------------


class TestResolvedTeamVersion:
    """团队版本解析：成员版本清单与查询。"""

    def _team(self, members=None, **kwargs):
        return ExpertTeamRecord(
            id="t-1",
            name="测试团队",
            members=members or [],
            **kwargs,
        )

    def test_empty_team(self):
        team = self._team()
        resolved = resolve_team_version(team)
        assert resolved.team_id == "t-1"
        assert resolved.member_versions == {}
        assert resolved.mode == "router"

    def test_member_versions_extracted(self):
        members = [
            TeamMember(expert_id="e-1", expert_version=2, member_role="lead"),
            TeamMember(expert_id="e-2", expert_version=5),
        ]
        team = self._team(members=members)
        resolved = resolve_team_version(team)
        assert resolved.member_version("e-1") == 2
        assert resolved.member_version("e-2") == 5

    def test_none_version_becomes_zero(self):
        members = [TeamMember(expert_id="e-1", expert_version=None)]
        team = self._team(members=members)
        resolved = resolve_team_version(team)
        assert resolved.member_version("e-1") == 0

    def test_has_member(self):
        members = [TeamMember(expert_id="e-1", expert_version=1)]
        team = self._team(members=members)
        resolved = resolve_team_version(team)
        assert resolved.has_member("e-1") is True
        assert resolved.has_member("e-missing") is False

    def test_mode_and_router_prompt(self):
        team = self._team(mode="pipeline", router_prompt="路由提示")
        resolved = resolve_team_version(team)
        assert resolved.mode == "pipeline"
        assert resolved.router_prompt == "路由提示"

    def test_published_version_carried(self):
        team = self._team(published_version=7)
        resolved = resolve_team_version(team)
        assert resolved.team_version == 7


# ---------------------------------------------------------------------------
# Session team version binding
# ---------------------------------------------------------------------------


class TestSessionTeamVersionBinding:
    """会话版本绑定：首轮绑定、防覆盖、幂等。"""

    def test_first_bind_succeeds(self):
        meta = {}
        bind_session_team_version(meta, team_id="t-1", team_version=3)
        assert meta[SESSION_META_TEAM_ID_KEY] == "t-1"
        assert meta[SESSION_META_TEAM_VERSION_KEY] == 3
        assert "team_version_bound_at" in meta

    def test_same_bind_is_idempotent(self):
        meta = {}
        bind_session_team_version(meta, team_id="t-1", team_version=3)
        original_ts = meta["team_version_bound_at"]
        # 重复绑定相同值：不报错，不更新时间戳
        bind_session_team_version(meta, team_id="t-1", team_version=3)
        assert meta["team_version_bound_at"] == original_ts

    def test_rebind_different_version_raises(self):
        meta = {}
        bind_session_team_version(meta, team_id="t-1", team_version=3)
        with pytest.raises(ValueError, match="already bound"):
            bind_session_team_version(meta, team_id="t-1", team_version=5)

    def test_rebind_different_team_raises(self):
        meta = {}
        bind_session_team_version(meta, team_id="t-1", team_version=3)
        with pytest.raises(ValueError, match="already bound"):
            bind_session_team_version(meta, team_id="t-2", team_version=1)

    def test_get_session_team_version_unbound(self):
        meta = {}
        assert get_session_team_version(meta) is None

    def test_get_session_team_version_bound(self):
        meta = {}
        bind_session_team_version(meta, team_id="t-1", team_version=3)
        result = get_session_team_version(meta)
        assert result == ("t-1", 3)


# ---------------------------------------------------------------------------
# check_expert_access (team_only)
# ---------------------------------------------------------------------------


class TestCheckExpertAccess:
    """team_only 专属准入判定。"""

    def _shared_expert(self):
        return ExpertRecord(id="e-s", name="共享员工", usage_mode="shared")

    def _team_only_expert(self):
        return ExpertRecord(
            id="e-t", name="团队专属", usage_mode="team_only",
        )

    def test_shared_always_allowed(self):
        expert = self._shared_expert()
        result = check_expert_access(
            expert=expert,
            user_id="u-1",
            owner_id=None,
        )
        assert result.allowed is True

    def test_team_only_without_context_denied(self):
        expert = self._team_only_expert()
        result = check_expert_access(
            expert=expert,
            user_id="u-1",
            owner_id=None,
        )
        assert result.allowed is False
        assert "team_only" in result.reason

    def test_team_only_with_team_context_allowed(self):
        expert = self._team_only_expert()
        result = check_expert_access(
            expert=expert,
            user_id="u-1",
            owner_id=None,
            team_context="t-1",
        )
        assert result.allowed is True

    def test_team_only_admin_debug_allowed(self):
        expert = self._team_only_expert()
        result = check_expert_access(
            expert=expert,
            user_id="admin",
            owner_id=None,
            is_admin=True,
            is_debug_session=True,
        )
        assert result.allowed is True

    def test_team_only_admin_without_debug_denied(self):
        """管理员但非调试入口：仍然拒绝（必须走明确调试路径）。"""
        expert = self._team_only_expert()
        result = check_expert_access(
            expert=expert,
            user_id="admin",
            owner_id=None,
            is_admin=True,
            is_debug_session=False,
        )
        assert result.allowed is False


# ---------------------------------------------------------------------------
# check_team_member_access
# ---------------------------------------------------------------------------


class TestCheckTeamMemberAccess:
    """团队成员准入：usage_mode + 成员身份双重校验。"""

    def _team_with_members(self):
        return ExpertTeamRecord(
            id="t-1",
            name="测试团队",
            members=[
                TeamMember(expert_id="e-1", expert_version=1),
                TeamMember(expert_id="e-2", expert_version=2),
            ],
        )

    def test_member_in_team_allowed(self):
        expert = ExpertRecord(
            id="e-1", name="成员1", usage_mode="team_only",
        )
        team = self._team_with_members()
        result = check_team_member_access(
            expert=expert, team=team, user_id="u-1",
        )
        assert result.allowed is True

    def test_non_member_denied(self):
        expert = ExpertRecord(
            id="e-99", name="非成员", usage_mode="team_only",
        )
        team = self._team_with_members()
        result = check_team_member_access(
            expert=expert, team=team, user_id="u-1",
        )
        assert result.allowed is False
        assert "not a member" in result.reason

    def test_shared_expert_in_team_allowed(self):
        """shared 员工在团队中：自然放行。"""
        expert = ExpertRecord(
            id="e-1", name="共享成员", usage_mode="shared",
        )
        team = self._team_with_members()
        result = check_team_member_access(
            expert=expert, team=team, user_id="u-1",
        )
        assert result.allowed is True


# ---------------------------------------------------------------------------
# compute_spec_hash
# ---------------------------------------------------------------------------


class TestComputeSpecHash:
    """发布包内容哈希：幂等性与碰撞抗性。"""

    def test_same_spec_same_hash(self):
        spec = {"nodes": [{"key": "a"}], "policy": {"max_tokens": 1000}}
        h1 = compute_spec_hash(spec)
        h2 = compute_spec_hash(spec)
        assert h1 == h2

    def test_different_spec_different_hash(self):
        s1 = {"nodes": [{"key": "a"}]}
        s2 = {"nodes": [{"key": "b"}]}
        assert compute_spec_hash(s1) != compute_spec_hash(s2)

    def test_key_order_does_not_matter(self):
        """JSON key 顺序不影响哈希（sort_keys=True）。"""
        s1 = {"b": 2, "a": 1}
        s2 = {"a": 1, "b": 2}
        assert compute_spec_hash(s1) == compute_spec_hash(s2)

    def test_hash_is_hex_string(self):
        h = compute_spec_hash({"test": True})
        assert len(h) == 64  # SHA-256 完整十六进制
        assert all(c in "0123456789abcdef" for c in h)

    def test_empty_spec_hash(self):
        h = compute_spec_hash({})
        assert len(h) == 64
