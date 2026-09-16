# -*- coding: utf-8 -*-
"""Digital-employee registry / governance domain models.

四层职责中本包只做「数字员工治理面」：

- :mod:`store` 对接 ``employee_governance`` 单表（归属部门 + 可见范围权威）；
- :mod:`registry` 聚合 agents / experts / expert_teams / departments 四个
  权威源，产出列表页唯一数据面 :class:`DigitalEmployeeVO`；
- :mod:`projection` 把治理态投影到 RBAC ``agent_grants``（运行期唯一鉴权面）。

形态（kind）语义与运行时 agent id 命名严格对齐：

- ``agent``   —— root config 里的原生智能体（``default`` / 第三方后端）
- ``expert``  —— 已发布专家物化的 ``expert_<id>``（业务数字员工）
- ``team``    —— 专家团物化的 supervisor ``team_<id>``
- ``workflow``—— 外部工作流平台对接预留位（当前无实体，注册表不返回）

@author qingfeng
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from ..experts.models import (
    expert_agent_id,
    expert_team_agent_id,
)

# ---------------------------------------------------------------------------
# 形态（entity kind）常量
# ---------------------------------------------------------------------------

#: 原生智能体：root config 中的 agent profile。
EMPLOYEE_KIND_AGENT = "agent"
#: 数字员工（专家）：``experts`` 表发布后物化的单体员工。
EMPLOYEE_KIND_EXPERT = "expert"
#: 专家团：``expert_teams`` 发布后物化的 supervisor。
EMPLOYEE_KIND_TEAM = "team"
#: 工作流：外部平台对接预留（本期不产出行）。
EMPLOYEE_KIND_WORKFLOW = "workflow"

EMPLOYEE_KINDS = (
    EMPLOYEE_KIND_AGENT,
    EMPLOYEE_KIND_EXPERT,
    EMPLOYEE_KIND_TEAM,
    EMPLOYEE_KIND_WORKFLOW,
)

#: 控制台「智能体」Tab 的形态集合（单体形态 = 原生 + 数字员工）。
EMPLOYEE_KIND_TAB_AGENT = (EMPLOYEE_KIND_AGENT, EMPLOYEE_KIND_EXPERT)

#: 运行时 agent id 前缀（分类回退用：权威源缺行时按前缀判定）。
EXPERT_AGENT_PREFIX = "expert_"
TEAM_AGENT_PREFIX = "team_"

#: 草稿调试实例 agent id 后缀（与线上员工去重，不进注册表）。
DRAFT_AGENT_SUFFIX = "__draft"


def employee_kind_of(agent_id: str) -> str:
    """按运行时 agent id 前缀推断形态（权威源缺行时的兜底判定）。"""
    if agent_id.startswith(EXPERT_AGENT_PREFIX):
        return EMPLOYEE_KIND_EXPERT
    if agent_id.startswith(TEAM_AGENT_PREFIX):
        return EMPLOYEE_KIND_TEAM
    return EMPLOYEE_KIND_AGENT


def employee_entity_id_of(agent_id: str, kind: str) -> str:
    """从运行时 agent id 反解领域主键（agent 形态与 agent_id 同值）。"""
    if kind == EMPLOYEE_KIND_EXPERT:
        return agent_id.removeprefix(EXPERT_AGENT_PREFIX)
    if kind == EMPLOYEE_KIND_TEAM:
        return agent_id.removeprefix(TEAM_AGENT_PREFIX)
    return agent_id


# ---------------------------------------------------------------------------
# 可见范围（visibility）常量
# ---------------------------------------------------------------------------

#: 全员共享：所有部门可见可用（RBAC 无 grant = 不限制）。
VISIBILITY_ORG = "org"
#: 部门专属：仅「归属部门 ∪ 授权部门」成员可见可用。
VISIBILITY_DEPARTMENT = "department"
#: 仅创建者：只归属人自己可见可用。
VISIBILITY_PRIVATE = "private"

VISIBILITIES = (
    VISIBILITY_ORG,
    VISIBILITY_DEPARTMENT,
    VISIBILITY_PRIVATE,
)


# ---------------------------------------------------------------------------
# 治理记录与写入载荷
# ---------------------------------------------------------------------------


class GovernanceRecord(BaseModel):
    """One ``employee_governance`` row (ownership + visibility authority)."""

    agent_id: str
    entity_kind: str = EMPLOYEE_KIND_AGENT
    entity_id: str = ""
    department_id: Optional[str] = None
    visibility: str = VISIBILITY_ORG
    granted_departments: List[str] = Field(default_factory=list)
    owner_id: Optional[str] = None
    updated_by: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("visibility")
    @classmethod
    def _check_visibility(cls, value: str) -> str:
        """可见性白名单校验（非法值直接 422，不落库）。"""
        if value not in VISIBILITIES:
            raise ValueError("可见范围只能是 org / department / private")
        return value

    @field_validator("entity_kind")
    @classmethod
    def _check_kind(cls, value: str) -> str:
        """形态白名单校验（含未来 workflow 预留位）。"""
        if value not in EMPLOYEE_KINDS:
            raise ValueError("员工形态只能是 agent / expert / team / workflow")
        return value


class GovernanceUpdateBody(BaseModel):
    """单员工治理写入载荷（``None`` = 不修改该维度）。"""

    department_id: Optional[str] = None
    visibility: Optional[str] = None
    granted_departments: Optional[List[str]] = None

    @field_validator("visibility")
    @classmethod
    def _check_visibility(cls, value: Optional[str]) -> Optional[str]:
        """显式传值时才校验（不传表示保持原可见性）。"""
        if value is not None and value not in VISIBILITIES:
            raise ValueError("可见范围只能是 org / department / private")
        return value


class GovernanceBatchUpdateBody(BaseModel):
    """批量治理载荷：一次把同一套治理态套用到多个员工。"""

    agent_ids: List[str] = Field(min_length=1)
    department_id: Optional[str] = None
    visibility: Optional[str] = None
    granted_departments: Optional[List[str]] = None

    @field_validator("visibility")
    @classmethod
    def _check_visibility(cls, value: Optional[str]) -> Optional[str]:
        """批量写入同样只在显式传值时校验可见性。"""
        if value is not None and value not in VISIBILITIES:
            raise ValueError("可见范围只能是 org / department / private")
        return value

    @field_validator("agent_ids")
    @classmethod
    def _dedupe_agent_ids(cls, value: List[str]) -> List[str]:
        """去重且保序，避免同一员工被重复投影。"""
        seen = set()
        unique: List[str] = []
        for agent_id in value:
            cleaned = (agent_id or "").strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                unique.append(cleaned)
        if not unique:
            raise ValueError("待治理的员工不能为空")
        return unique


# ---------------------------------------------------------------------------
# 注册表视图对象
# ---------------------------------------------------------------------------


class TeamMemberVO(BaseModel):
    """专家团的一个成员（供卡片头像堆叠与详情展示）。"""

    expert_id: str
    name: str = ""
    icon: str = ""
    role_hint: str = ""
    member_role: str = "member"


class DigitalEmployeeVO(BaseModel):
    """数字员工注册表行：列表页的唯一数据面。

    三个权威源（root config agents / experts / expert_teams）+ 治理表 +
    部门表在内存装配而成，任何字段都不再二次硬编码。
    """

    agent_id: str
    entity_kind: str = EMPLOYEE_KIND_AGENT
    entity_id: str = ""
    name: str = ""
    title: str = ""
    description: str = ""
    icon: str = ""
    enabled: bool = True
    pinned: bool = False
    startup_status: str = ""
    lifecycle_status: str = ""
    #: 专家团编排模式（router-智能调度 / pipeline-顺序流水线），非团为空。
    mode: str = ""
    backend: str = ""
    model_label: str = ""
    department_id: Optional[str] = None
    department_name: str = ""
    visibility: str = VISIBILITY_ORG
    #: 是否已有治理行。未治理行的 visibility 是默认语义而非人工决策，
    #: 前端据此决定徽标是否展示（数据诚实：不在前端猜“有没有被治理过”）。
    governed: bool = False
    granted_departments: List[str] = Field(default_factory=list)
    granted_department_names: List[str] = Field(default_factory=list)
    member_count: int = 0
    members: List[TeamMemberVO] = Field(default_factory=list)
    usage_count: int = 0
    is_builtin: bool = False
    tags: List[str] = Field(default_factory=list)
    workspace_dir: str = ""
    available_in_chat: bool = True
    managed_by_app: Optional[str] = None
    backend_capabilities: Dict[str, Any] = Field(default_factory=dict)
    owner_id: Optional[str] = None
    usable: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


__all__ = [
    "DRAFT_AGENT_SUFFIX",
    "DigitalEmployeeVO",
    "EMPLOYEE_KINDS",
    "EMPLOYEE_KIND_AGENT",
    "EMPLOYEE_KIND_EXPERT",
    "EMPLOYEE_KIND_TEAM",
    "EMPLOYEE_KIND_WORKFLOW",
    "GovernanceBatchUpdateBody",
    "GovernanceRecord",
    "GovernanceUpdateBody",
    "TeamMemberVO",
    "VISIBILITIES",
    "VISIBILITY_DEPARTMENT",
    "VISIBILITY_ORG",
    "VISIBILITY_PRIVATE",
    "employee_entity_id_of",
    "employee_kind_of",
    "expert_agent_id",
    "expert_team_agent_id",
]
