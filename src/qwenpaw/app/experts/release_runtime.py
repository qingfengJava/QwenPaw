# -*- coding: utf-8 -*-
"""P3 版本化运行实例解析与专属准入。

核心职责：

1. **版本化实例键**：内部实例键包含租户、逻辑员工 ID、发布版本、
   执行作用域；不再仅靠 ``agent_id`` 复用实例。
2. **根会话绑定**：团队聊天首轮由服务端绑定已发布团队版本并存入
   会话内部元数据；后续轮次继续使用该版本。
3. **统一版本解析**：planner、执行成员、验收 lead 均使用同一份
   绑定版本配置。
4. **专属准入**：``team_only`` 员工只能经授权团队调用；校验提前至
   请求准入，不等到工具调用时才拒绝。

@author qingfeng
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import (
    USAGE_MODE_TEAM_ONLY,
    ExpertRecord,
    ExpertTeamRecord,
    TeamMember,
    expert_agent_id,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 版本化实例键
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VersionedInstanceKey:
    """版本化运行实例键。

    不可变（frozen dataclass），保证哈希稳定性，可安全用作 dict key
    或 set 成员。与旧 ``agent_id`` 字符串的区别：包含版本号与执行
    作用域，不同版本/团队/运行的实例不会互相覆盖。
    """

    #: 租户标识（多租户隔离硬边界）
    tenant_id: str
    #: 逻辑员工 ID（页面/授权/审计用，不创建版本账号）
    expert_id: str
    #: 发布版本号（0=草稿/未发布）
    version: int
    #: 执行作用域（team_run_id / session_id / 空串表示独立使用）
    scope: str = ""

    @property
    def agent_id(self) -> str:
        """兼容旧 ``expert_{id}`` 格式的 agent 标识。"""
        return expert_agent_id(self.expert_id)

    @property
    def instance_key(self) -> str:
        """完整实例键字符串（workspace 注册/缓存用）。

        格式：``{tenant}:{agent_id}:v{version}[:{scope}]``
        """
        base = f"{self.tenant_id}:{self.agent_id}:v{self.version}"
        if self.scope:
            return f"{base}:{self.scope}"
        return base

    def content_hash(self) -> str:
        """实例键的 SHA-256 摘要（短哈希，用于缓存键/日志脱敏）。"""
        return hashlib.sha256(
            self.instance_key.encode("utf-8"),
        ).hexdigest()[:16]


def build_instance_key(
    *,
    tenant_id: str,
    expert_id: str,
    version: int,
    scope: str = "",
) -> VersionedInstanceKey:
    """构建版本化实例键（工厂函数，参数显式命名防误传）。"""
    return VersionedInstanceKey(
        tenant_id=tenant_id,
        expert_id=expert_id,
        version=version,
        scope=scope,
    )


# ---------------------------------------------------------------------------
# 团队版本解析
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedTeamVersion:
    """解析后的团队版本快照。

    不可变：一旦解析完成，成员版本清单、基础配置均固定。
    planner/engine/verifier 共享此对象，保证同一运行内所有阶段
    使用同一份绑定版本。
    """

    team_id: str
    team_version: int
    #: 成员版本清单：{expert_id: version}
    member_versions: Dict[str, int] = field(default_factory=dict)
    #: 团队模式（router / pipeline）
    mode: str = "router"
    #: 路由提示词
    router_prompt: str = ""
    #: 编排配置快照
    orchestration: Dict[str, Any] = field(default_factory=dict)

    def member_version(self, expert_id: str) -> Optional[int]:
        """查询某成员的绑定版本（None=未在团队中）。"""
        return self.member_versions.get(expert_id)

    def has_member(self, expert_id: str) -> bool:
        """判断某员工是否为该团队版本的成员。"""
        return expert_id in self.member_versions


def resolve_team_version(
    team: ExpertTeamRecord,
) -> ResolvedTeamVersion:
    """从团队草稿记录解析出版本化快照（草稿视图；测试/预检用）。

    运行时权威口径请用 :func:`resolve_team_version_from_store`——
    本函数读取的是可变草稿，不满足"运行固定发布版本"约束。

    Args:
        team: 团队记录（草稿或已发布版本投影）

    Returns:
        不可变的解析结果
    """
    member_versions: Dict[str, int] = {}
    for member in team.members:
        # expert_version=None 表示尚未指定版本，按 0（未发布）处理
        member_versions[member.expert_id] = member.expert_version or 0

    return ResolvedTeamVersion(
        team_id=team.id,
        team_version=team.published_version,
        member_versions=member_versions,
        mode=team.mode,
        router_prompt=team.router_prompt,
        orchestration=team.orchestration or {},
    )


async def resolve_team_version_from_store(
    store,
    team_id: str,
) -> Optional[ResolvedTeamVersion]:
    """从 ``expert_team_versions`` 最新发布快照解析版本化配置。

    快照口径（运行时权威）：运行绑定的成员版本清单、编排配置均
    来自不可变发布快照，不再读可变草稿（协议 8.1）。团队从未发布
    或快照缺失时返回 None——调用方按"无版本基准"降级处理。

    Args:
        store: ExpertStore（需提供 ``list_team_versions`` /
            ``get_team_version``）
        team_id: 团队 ID

    Returns:
        不可变解析结果；无快照返回 None
    """
    # 最新审计摘要（version 降序第一项即最新发布版本）
    snapshots = await store.list_team_versions(team_id)
    if not snapshots:
        return None
    latest_version = int(snapshots[0]["version"] or 0)
    row = await store.get_team_version(team_id, latest_version)
    if row is None:
        return None
    # 快照 spec 结构见 publish.snapshot_spec：members 为 TeamMember
    # model_dump 列表（expert_version 可能为 None → 归一 0）
    spec = row.get("spec") or {}
    member_versions: Dict[str, int] = {}
    for member in spec.get("members") or []:
        expert_id = str(member.get("expert_id") or "")
        if not expert_id:
            continue
        member_versions[expert_id] = int(member.get("expert_version") or 0)
    return ResolvedTeamVersion(
        team_id=team_id,
        team_version=int(row.get("version") or 0),
        member_versions=member_versions,
        mode=str(spec.get("mode") or "router"),
        router_prompt=str(spec.get("router_prompt") or ""),
        orchestration=spec.get("orchestration") or {},
    )


# ---------------------------------------------------------------------------
# 会话版本绑定
# ---------------------------------------------------------------------------


#: 会话元数据中存储团队版本绑定的键名
SESSION_META_TEAM_VERSION_KEY = "team_version"
SESSION_META_TEAM_ID_KEY = "team_id"
SESSION_META_BOUND_AT_KEY = "team_version_bound_at"


def bind_session_team_version(
    session_meta: Dict[str, Any],
    *,
    team_id: str,
    team_version: int,
) -> None:
    """将会话绑定到指定团队版本（首轮由服务端写入）。

    绑定后不可覆盖：后续轮次必须继续使用已绑定版本，切换新版
    通过明确的新会话操作完成。客户端或模型传来的版本号不能覆盖。

    Args:
        session_meta: 会话内部元数据 dict（可变）
        team_id: 团队 ID
        team_version: 已发布的团队版本号

    Raises:
        ValueError: 已绑定不同版本时（表示试图覆盖）
    """
    existing_team = session_meta.get(SESSION_META_TEAM_ID_KEY)
    existing_ver = session_meta.get(SESSION_META_TEAM_VERSION_KEY)

    # 已绑定相同版本：幂等，不重复写入
    if existing_team == team_id and existing_ver == team_version:
        return

    # 已绑定不同版本/团队：拒绝覆盖
    if existing_team is not None and existing_ver is not None:
        raise ValueError(
            f"Session already bound to team {existing_team} "
            f"version {existing_ver}; cannot rebind to "
            f"team {team_id} version {team_version}"
        )

    # 首次绑定
    session_meta[SESSION_META_TEAM_ID_KEY] = team_id
    session_meta[SESSION_META_TEAM_VERSION_KEY] = team_version
    # 绑定时间戳（审计用，不用于过期判定）
    from datetime import datetime, timezone
    session_meta[SESSION_META_BOUND_AT_KEY] = (
        datetime.now(timezone.utc).isoformat()
    )


def get_session_team_version(
    session_meta: Dict[str, Any],
) -> Optional[tuple]:
    """读取会话绑定的团队版本。

    Returns:
        ``(team_id, team_version)`` 元组；未绑定时返回 None。
    """
    team_id = session_meta.get(SESSION_META_TEAM_ID_KEY)
    team_version = session_meta.get(SESSION_META_TEAM_VERSION_KEY)
    if team_id is None or team_version is None:
        return None
    return (team_id, team_version)


# ---------------------------------------------------------------------------
# team_only 专属准入
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AccessDecision:
    """准入判定结果。

    不可变，可安全传递给下游组件。
    """

    allowed: bool
    reason: str = ""
    #: 拒绝时的 HTTP 状态码建议（403/428 等）
    suggested_status: int = 403


def check_expert_access(
    *,
    expert: ExpertRecord,
    user_id: str,
    owner_id: Optional[str],
    is_admin: bool = False,
    team_context: Optional[str] = None,
    is_debug_session: bool = False,
) -> AccessDecision:
    """检查用户是否可以直接使用某员工。

    核心规则：
    - ``shared`` 员工：按现有授权逻辑（此处不重复判定，只判定
      usage_mode 维度）。
    - ``team_only`` 员工：普通用户不能单独直接对话，只能通过
      已授权团队使用。管理员调试走明确的管理员草稿入口。

    Args:
        expert: 员工记录
        user_id: 当前用户标识
        owner_id: 员工所有者 ID（可为空）
        is_admin: 是否为 admin:experts 管理员
        team_context: 当前请求是否经过团队上下文（team_id 或 None）
        is_debug_session: 是否为管理员显式调试入口

    Returns:
        AccessDecision 判定结果
    """
    # shared 员工：usage_mode 维度不限制，放行（其他维度由调用方判定）
    if expert.usage_mode != USAGE_MODE_TEAM_ONLY:
        return AccessDecision(allowed=True)

    # team_only 员工：必须有团队上下文
    if not team_context:
        # 管理员调试入口：允许（走明确的管理员草稿调试路径）
        if is_admin and is_debug_session:
            return AccessDecision(
                allowed=True,
                reason="admin debug session allowed for team_only expert",
            )
        return AccessDecision(
            allowed=False,
            reason=(
                f"Expert '{expert.name}' is team_only; "
                "direct access requires team context"
            ),
            suggested_status=403,
        )

    # 有团队上下文：放行（团队级别的成员授权由调用方在运行创建时校验）
    return AccessDecision(
        allowed=True,
        reason=f"team context '{team_context}' provided",
    )


def check_team_member_access(
    *,
    expert: ExpertRecord,
    team: ExpertTeamRecord,
    user_id: str,
    is_admin: bool = False,
) -> AccessDecision:
    """检查用户是否可以通过指定团队使用某员工。

    比 ``check_expert_access`` 更严格：不仅要求 team_only 有团队
    上下文，还验证该员工确实是团队成员。

    Args:
        expert: 目标员工
        team: 目标团队
        user_id: 当前用户
        is_admin: 管理员权限

    Returns:
        AccessDecision
    """
    # 先检查基础 usage_mode 准入
    base = check_expert_access(
        expert=expert,
        user_id=user_id,
        owner_id=expert.owner_id,
        is_admin=is_admin,
        team_context=team.id,
    )
    if not base.allowed:
        return base

    # 验证员工确实在团队中
    member_ids = {m.expert_id for m in team.members}
    if expert.id not in member_ids:
        return AccessDecision(
            allowed=False,
            reason=(
                f"Expert '{expert.id}' is not a member of "
                f"team '{team.id}'"
            ),
            suggested_status=403,
        )

    return AccessDecision(allowed=True)


# ---------------------------------------------------------------------------
# 发布包内容哈希
# ---------------------------------------------------------------------------


def compute_spec_hash(spec: Dict[str, Any]) -> str:
    """计算发布包内容摘要（SHA-256）。

    用于幂等发布和完整性校验：相同 spec 产生相同哈希，不同 spec
    哈希碰撞概率极低。

    Args:
        spec: 发布包内容（dict，会排序后序列化）

    Returns:
        SHA-256 十六进制摘要字符串
    """
    import json
    # 排序序列化保证确定性（同内容同哈希）
    canonical = json.dumps(spec, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "AccessDecision",
    "ResolvedTeamVersion",
    "SESSION_META_BOUND_AT_KEY",
    "SESSION_META_TEAM_ID_KEY",
    "SESSION_META_TEAM_VERSION_KEY",
    "VersionedInstanceKey",
    "bind_session_team_version",
    "build_instance_key",
    "check_expert_access",
    "check_team_member_access",
    "compute_spec_hash",
    "get_session_team_version",
    "resolve_team_version",
    "resolve_team_version_from_store",
]
