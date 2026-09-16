# -*- coding: utf-8 -*-
"""数字员工注册表：多权威源聚合装配（列表页唯一数据面）。

装配遵循列表接口五步范式，**每种数据在一次请求内只查一次**，全部内存建
索引后组装，禁止任何逐行回查：

1. 运行时 agent 清单（复用 ``GET /agents`` 的既有装配逻辑，零重复实现）；
2. ``experts`` 轻投影一次（卡片列，不拉 agent_spec 重 JSONB）；
3. ``expert_teams`` 一次（成员清单由其既有批量查询随带返回）+
   ``employee_governance`` 一次 + ``departments`` 一次；
4. 权限快照一次（grants / roles / teams）；
5. 组装阶段所有关联数据只从内存 Map 取。

企业平面（PG）未配置时自动降级：只出运行时 agent 行，治理维度取默认语义，
保证单机/桌面部署不因缺 PG 而整页报错。

@author qingfeng
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..experts.models import (
    ExpertRecord,
    ExpertTeamRecord,
    expert_agent_id,
    expert_team_agent_id,
)
from ..experts.store import get_expert_store
from ..orgs.models import DepartmentRecord
from ..orgs.service import get_org_service
from ..rbac.deps import _resolve_flat_role
from ..rbac.models import GrantRecord
from ..rbac.store import get_rbac_store
from .models import (
    DRAFT_AGENT_SUFFIX,
    EMPLOYEE_KIND_AGENT,
    EMPLOYEE_KIND_EXPERT,
    EMPLOYEE_KIND_TAB_AGENT,
    EMPLOYEE_KIND_TEAM,
    VISIBILITY_ORG,
    DigitalEmployeeVO,
    GovernanceRecord,
    TeamMemberVO,
    employee_kind_of,
)
from .store import get_employee_governance_store

logger = logging.getLogger(__name__)

#: 草稿行排序兜底（更新时间缺失时排到末尾）。
_EPOCH = datetime.min


@dataclass
class EmployeeSources:
    """一次请求内取齐的全部权威源快照。"""

    #: 运行时 agent 清单（agent_id → AgentSummary），已剔除草稿调试实例。
    agents: Dict[str, Any] = field(default_factory=dict)
    #: 展示顺序（default → pinned → regular，沿用 ``GET /agents`` 的顺序）。
    agent_order: List[str] = field(default_factory=list)
    #: 专家卡片（agent_id → ExpertRecord）。
    experts: Dict[str, ExpertRecord] = field(default_factory=dict)
    #: 专家团（agent_id → ExpertTeamRecord）。
    teams: Dict[str, ExpertTeamRecord] = field(default_factory=dict)
    #: 治理行（agent_id → GovernanceRecord）。
    governance: Dict[str, GovernanceRecord] = field(default_factory=dict)
    #: 部门全量列表（id → name/path 索引在使用侧构建）。
    departments: List[DepartmentRecord] = field(default_factory=list)


def is_draft_preview_agent(agent_id: str) -> bool:
    """草稿调试实例（``expert_x__draft``）不进注册表。"""
    return agent_id.endswith(DRAFT_AGENT_SUFFIX)


async def load_sources(request: Any = None) -> EmployeeSources:
    """取齐注册表所需的所有权威源（每种各一次查询）。"""
    # 函数内导入：避免 routers.agents ↔ employees 的模块级循环依赖
    from ..routers.agents import list_agents

    sources = EmployeeSources()
    response = await list_agents(request)
    for summary in response.agents:
        # 调试实例是临时物化，展示在员工清单里只会形成噪音
        if is_draft_preview_agent(summary.id):
            continue
        sources.agents[summary.id] = summary
        sources.agent_order.append(summary.id)

    # 企业平面缺 PG 时降级为空表（治理维度回落默认语义），不阻断列表
    try:
        store = get_expert_store()
        experts = await store.list_expert_cards()
        sources.experts = {
            expert_agent_id(expert.id): expert for expert in experts
        }
        teams = await store.list_teams()
        sources.teams = {
            expert_team_agent_id(team.id): team for team in teams
        }
        governance = await get_employee_governance_store().list_all()
        sources.governance = {row.agent_id: row for row in governance}
        sources.departments = await get_org_service().list_departments()
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "employee registry: enterprise plane unavailable, degrading to "
            "runtime agents only",
            exc_info=True,
        )
    return sources


def _model_label_of(summary: Any) -> str:
    """员工默认模型展示名（员工级 slot 优先，回退第三方后端模型）。"""
    if summary is None:
        return ""
    active_model = getattr(summary, "active_model", None)
    model = getattr(active_model, "model", "") if active_model else ""
    return model or (getattr(summary, "backend_model", "") or "")


def _summary_field(summary: Any, name: str, default: Any) -> Any:
    """安全读取 AgentSummary 字段（未物化行无 summary 时回落默认）。

    只把 ``None`` 归一为默认值，不能顺手 ``or``——否则 ``False``（如
    ``available_in_chat=False``）会被误读为真值默认。
    """
    if summary is None:
        return default
    value = getattr(summary, name, default)
    return default if value is None else value


def _record_field(
    expert: Optional[ExpertRecord],
    team: Optional[ExpertTeamRecord],
    name: str,
    default: Any,
) -> Any:
    """按 expert → team 优先级读领域记录字段（两者互斥，同一行只有一个）。"""
    record = expert if expert is not None else team
    if record is None:
        return default
    value = getattr(record, name, default)
    return default if value is None else value


def _resolve_kind(agent_id: str, sources: EmployeeSources) -> str:
    """形态判定：权威源命中优先，缺行时按 agent id 前缀兜底。"""
    if agent_id in sources.teams:
        return EMPLOYEE_KIND_TEAM
    if agent_id in sources.experts:
        return EMPLOYEE_KIND_EXPERT
    return employee_kind_of(agent_id)


def _members_of(
    team: ExpertTeamRecord,
    sources: EmployeeSources,
) -> List[TeamMemberVO]:
    """专家团成员清单（名称从已加载的 experts 内存索引取，零额外查询）。"""
    members: List[TeamMemberVO] = []
    for member in team.members:
        expert = sources.experts.get(expert_agent_id(member.expert_id))
        members.append(
            TeamMemberVO(
                expert_id=member.expert_id,
                name=expert.name if expert else member.expert_id,
                icon=expert.icon if expert else "",
                role_hint=member.role_hint,
                member_role=member.member_role,
            ),
        )
    return members


def build_row(
    agent_id: str,
    sources: EmployeeSources,
    name_by_department: Dict[str, str],
) -> DigitalEmployeeVO:
    """装配一行注册表数据（所有关联值只从内存 Map 取）。"""
    summary = sources.agents.get(agent_id)
    kind = _resolve_kind(agent_id, sources)
    expert = (
        sources.experts.get(agent_id)
        if kind == EMPLOYEE_KIND_EXPERT
        else None
    )
    team = sources.teams.get(agent_id) if kind == EMPLOYEE_KIND_TEAM else None
    governance = sources.governance.get(agent_id)

    department_id = governance.department_id if governance else None
    granted_ids = (
        list(governance.granted_departments) if governance else []
    )
    visibility = governance.visibility if governance else VISIBILITY_ORG
    entity_id = expert.id if expert else (team.id if team else agent_id)
    # 归属人：治理行优先（可人工改派），回落领域记录创建者
    owner_id = (
        governance.owner_id if governance else None
    ) or _record_field(expert, team, "owner_id", None)
    members = _members_of(team, sources) if team else []
    # 展示名优先取领域权威源（专家/团），未物化行回落 agent 清单或 id
    name = (
        _record_field(expert, team, "name", "")
        or _summary_field(summary, "name", "")
        or agent_id
    )
    description = (
        _record_field(expert, team, "description", "")
        or _summary_field(summary, "description", "")
    )
    # 未物化为运行时 agent 的草稿员工不开放对话：与 usable 同判
    available_in_chat = (
        _summary_field(summary, "available_in_chat", True)
        if summary
        else False
    )

    return DigitalEmployeeVO(
        agent_id=agent_id,
        entity_kind=kind,
        entity_id=entity_id,
        name=name,
        title=_record_field(expert, None, "title", ""),
        description=description,
        icon=_record_field(expert, None, "icon", ""),
        enabled=_summary_field(summary, "enabled", False),
        pinned=_summary_field(summary, "pinned", False),
        startup_status=_summary_field(summary, "startup_status", ""),
        lifecycle_status=_record_field(expert, team, "status", ""),
        # 编排模式是专家团独有维度（router / pipeline）
        mode=_record_field(None, team, "mode", ""),
        backend=_summary_field(summary, "backend", ""),
        model_label=_model_label_of(summary),
        department_id=department_id,
        department_name=name_by_department.get(department_id or "", ""),
        visibility=visibility,
        # 无治理行 = 从未人工设置过（默认 org），前端不展示治理徽标
        governed=governance is not None,
        granted_departments=granted_ids,
        granted_department_names=[
            name_by_department.get(item, item) for item in granted_ids
        ],
        member_count=len(members),
        members=members,
        usage_count=_record_field(expert, None, "usage_count", 0),
        is_builtin=_record_field(expert, None, "is_builtin", False),
        tags=list(_record_field(expert, team, "tags", []) or []),
        workspace_dir=_summary_field(summary, "workspace_dir", ""),
        available_in_chat=available_in_chat,
        managed_by_app=_summary_field(summary, "managed_by_app", None),
        backend_capabilities=dict(
            _summary_field(summary, "backend_capabilities", {}) or {},
        ),
        owner_id=owner_id,
        # 未物化为运行时 agent 的草稿员工尚不可对话，识别为不可用
        usable=summary is not None,
        created_at=_record_field(expert, team, "created_at", None),
        updated_at=_record_field(expert, team, "updated_at", None),
    )


def _updated_at_of(
    agent_id: str,
    sources: EmployeeSources,
) -> Optional[datetime]:
    """取领域记录的更新时间（草稿行排序键）。"""
    record = sources.experts.get(agent_id) or sources.teams.get(agent_id)
    return getattr(record, "updated_at", None) if record else None


def _ordered_agent_ids(sources: EmployeeSources) -> List[str]:
    """展示顺序：先运行时清单顺序，再补未物化的草稿员工（按更新时间倒序）。"""
    extra = [
        agent_id
        for agent_id in list(sources.experts) + list(sources.teams)
        if agent_id not in sources.agents
    ]
    extra.sort(
        key=lambda agent_id: _updated_at_of(agent_id, sources) or _EPOCH,
        reverse=True,
    )
    return [*sources.agent_order, *extra]


def apply_filters(
    rows: List[DigitalEmployeeVO],
    *,
    kind: str = "",
    department_id: str = "",
    visibility: str = "",
    status: str = "",
    q: str = "",
    unassigned: bool = False,
) -> List[DigitalEmployeeVO]:
    """按控制台筛选维度过滤（服务端与前端快筛共用同一语义）。"""
    keyword = (q or "").strip().lower()
    filtered: List[DigitalEmployeeVO] = []
    for row in rows:
        # 「智能体」Tab 覆盖单体形态（原生 agent + 数字员工专家）
        is_agent_tab = kind in ("", "all", "agents")
        if kind == "agents" and row.entity_kind not in EMPLOYEE_KIND_TAB_AGENT:
            continue
        if not is_agent_tab and row.entity_kind != kind:
            continue
        if department_id and row.department_id != department_id:
            continue
        # 待归属视角：只出还没指定归属部门的员工
        if unassigned and row.department_id:
            continue
        if visibility and row.visibility != visibility:
            continue
        if status and row.lifecycle_status != status:
            continue
        if keyword and keyword not in (
            f"{row.name} {row.title} {row.description} "
            f"{' '.join(row.tags)}".lower()
        ):
            continue
        filtered.append(row)
    return filtered


async def build_registry(
    request: Any = None,
    *,
    kind: str = "",
    department_id: str = "",
    visibility: str = "",
    status: str = "",
    q: str = "",
    unassigned: bool = False,
) -> List[DigitalEmployeeVO]:
    """注册表读接口主流程：取数 → 装配 → 视角收敛 → 筛选。"""
    sources = await load_sources(request)
    name_by_department = {
        item.id: item.name for item in sources.departments
    }
    rows = [
        build_row(agent_id, sources, name_by_department)
        for agent_id in _ordered_agent_ids(sources)
    ]
    scoped = _apply_viewer_scope(request, rows)
    return apply_filters(
        scoped,
        kind=kind,
        department_id=department_id,
        visibility=visibility,
        status=status,
        q=q,
        unassigned=unassigned,
    )


def _viewer_of(request: Any) -> str:
    """当前请求身份（AuthMiddleware 注入，未认证部署回落 ``local``）。"""
    return getattr(getattr(request, "state", None), "user", None) or "local"


def _is_privileged(viewer: str, flat_role: str) -> bool:
    """管理员或单机免认证部署：看全量（含他人私有员工）。"""
    if flat_role == "admin":
        return True
    try:
        from ..auth import is_auth_enabled

        return not is_auth_enabled()
    except Exception:  # pylint: disable=broad-except
        logger.debug("registry: auth switch unavailable", exc_info=True)
        return False


def _apply_viewer_scope(
    request: Any,
    rows: List[DigitalEmployeeVO],
) -> List[DigitalEmployeeVO]:
    """非管理员视角收敛：只保留可见可用（判定与运行期 grant 同源）。"""
    viewer = _viewer_of(request)
    flat_role = _resolve_flat_role(viewer) if viewer else ""
    if _is_privileged(viewer, flat_role):
        # 管理员/免认证部署只解除 ACL 限制；“未物化就没有工作台”是
        # 客观事实，不能顺手把 usable 抬成 True（否则前端会跳到空工作台）
        return rows

    rbac = get_rbac_store()
    # 权限快照一次取回，逐行内存判定（禁止每行读一次 rbac.json）
    grants: Dict[str, GrantRecord] = rbac.list_agent_grants()
    role_names = rbac.roles_for_user(viewer, flat_role)
    team_names = rbac.teams_for_user(viewer)

    visible: List[DigitalEmployeeVO] = []
    for row in rows:
        allowed = rbac.grant_allows(
            grants.get(row.agent_id),
            viewer,
            role_names,
            team_names,
        )
        row.usable = allowed and row.usable
        if allowed:
            visible.append(row)
    return visible


def target_of(
    agent_id: str,
    sources: EmployeeSources,
) -> Dict[str, Any]:
    """从已加载快照解析治理目标（批量写入共用一份快照，零重复取数）。

    返回 ``{entity_kind, entity_id, owner_id, exists}``；草稿调试实例与
    任何权威源都不认识的 id 会给出 ``exists=False``，由服务层转 404。
    """
    if is_draft_preview_agent(agent_id):
        return {"exists": False}
    kind = _resolve_kind(agent_id, sources)
    expert = sources.experts.get(agent_id)
    team = sources.teams.get(agent_id)
    # 前缀兜底判定为 expert/team 但权威源已无行：说明物化残留，按 agent 处理
    if kind == EMPLOYEE_KIND_EXPERT and expert is None:
        kind = EMPLOYEE_KIND_AGENT
    if kind == EMPLOYEE_KIND_TEAM and team is None:
        kind = EMPLOYEE_KIND_AGENT
    return {
        "agent_id": agent_id,
        "entity_kind": kind,
        "entity_id": expert.id if expert else team.id if team else agent_id,
        "owner_id": (
            expert.owner_id
            if expert
            else team.owner_id if team else None
        ),
        "exists": (
            agent_id in sources.agents
            or expert is not None
            or team is not None
        ),
    }


async def resolve_governance_target(
    agent_id: str,
    request: Any = None,
) -> Optional[Dict[str, Any]]:
    """解析单个治理目标（内部自取快照，供非批量场景使用）。

    治理写入必须落在真实存在的员工上；草稿调试实例与未知 id 一律拒绝
    （返回 ``None`` 由接口层转 404）。
    """
    sources = await load_sources(request)
    target = target_of(agent_id, sources)
    return target or None
