# -*- coding: utf-8 -*-
"""团队配置服务：元数据、发布预检与版本查询（T1）。

应用服务层（项目规范四层映射中的 Service）：路由只做参数校验，
本模块编排"读团队 → 跑校验 → 汇总问题"与"元数据组装"，Store 负责
持久化。不在此重复实现业务规则——规则唯一来源是
:mod:`qwenpaw.app.experts.team_config`。

@author qingfeng
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..workforce.contracts import RunPolicy
from .capability_view import team_capability_view
from .models import (
    TEAM_MEMBER_ROLE_LEAD,
    TEAM_MEMBER_ROLE_MEMBER,
    TEAM_MODES,
    ExpertRecord,
    TeamMember,
)
from .store import get_expert_store
from .team_config import summarize_team_config, validate_publishable_team

#: 协作模式说明（团队详情页"协作机制卡"唯一数据源，前端禁止硬编码文案）。
#: 键与 TEAM_MODES 对齐；未知模式回退空串由前端降级展示。
TEAM_MODE_DESCRIPTIONS: Dict[str, str] = {
    "router": (
        "主理人（中央大脑）接收需求后，判断最匹配的成员专家并派发任务；"
        "未预置编排模板时由中央大脑按需求单次规划分工，跨专业问题先给结论再分成员视角补充。"
    ),
    "pipeline": (
        "成员按预设顺序接力完成各自阶段的产出，后一阶段在前一阶段产出的基础上深化，"
        "最终由收尾环节汇总收束，形成完整交付。"
    ),
}

#: 提案状态元数据（前端唯一文案来源；与 team_changes.py 状态机对齐，
#: color 为 antd Tag 色板语义值，前端可覆盖）。本地声明避免依赖 DB 层。
CHANGE_REQUEST_STATUSES: List[Dict[str, str]] = [
    {"value": "pending", "label": "待确认", "color": "blue"},
    {"value": "applying", "label": "执行中", "color": "processing"},
    {"value": "applied", "label": "已生效", "color": "success"},
    {"value": "rejected", "label": "已拒绝", "color": "default"},
    {"value": "expired", "label": "已过期", "color": "warning"},
    {"value": "conflict", "label": "冲突", "color": "error"},
    {"value": "failed", "label": "失败", "color": "error"},
]


async def team_metadata() -> Dict[str, Any]:
    """团队配置元数据（前端枚举/限额唯一来源，禁止前端硬编码）。"""
    # 默认熔断策略（引擎默认值即有效限额起点；治理上限最终由平台收紧）
    default_policy = RunPolicy()
    return {
        "member_roles": [
            {"value": TEAM_MEMBER_ROLE_LEAD, "label": "主理人（Leader）"},
            {"value": TEAM_MEMBER_ROLE_MEMBER, "label": "成员"},
        ],
        "team_modes": [
            {
                "value": mode,
                "label": mode,
                "description": TEAM_MODE_DESCRIPTIONS.get(mode, ""),
            }
            for mode in TEAM_MODES
        ],
        "limits": {
            "default_max_repair_per_node": default_policy.max_repair_per_node,
            "default_max_replan": default_policy.max_replan,
            "default_parallelism": default_policy.parallelism,
            "default_max_total_seconds": default_policy.max_total_seconds,
            "default_max_total_tokens": default_policy.max_total_tokens,
        },
        # 运行时编排缺省启用（前端展示"有效配置"的唯一来源，禁止前端硬编码 true/false）
        "default_runtime_enabled": True,
        # 提案状态枚举（前端唯一文案来源，禁止硬编码中文状态文案）
        "change_request_statuses": CHANGE_REQUEST_STATUSES,
    }


async def validate_team(team_id: str) -> Dict[str, Any]:
    """团队预检：配置跨字段校验 + 成员能力可用性（POST /validate 数据源）。

    返回 ``{"ok": bool, "issues": [...], "config": {...},
    "members": [能力投影]}``；``ok=False`` 时 issues 非空。
    """
    store = get_expert_store()
    team = await store.get_team(team_id)
    if team is None:
        return {"ok": False, "issues": ["团队不存在"], "config": {}, "members": []}
    # 规则校验（唯一权威：team_config.validate_publishable_team）
    issues: List[str] = list(validate_publishable_team(team))
    # 能力可用性：未发布成员是发布阻塞项（与 publish 链同口径）
    view = await team_capability_view(team_id)
    for member in view.get("members", []):
        if not member.get("published"):
            issues.append(
                f"成员 [{member.get('name') or member.get('expert_id')}] 未发布："
                f"{member.get('unavailable_reason')}",
            )
    # 模板引用的成员必须真实存在（悬空 assignee 在发布前暴露）
    member_ids = {m.expert_id for m in team.members}
    for node in (team.orchestration or {}).get("nodes", []) or []:
        assignee = str(node.get("assignee_expert_id") or "")
        if assignee and assignee not in member_ids:
            issues.append(
                f"模板节点 [{node.get('node_key')}] 指派了非团队成员: {assignee}",
            )
    return {
        "ok": not issues,
        "issues": issues,
        "config": summarize_team_config(team),
        "members": view.get("members", []),
    }


def compute_member_upgrades(
    members: List[TeamMember],
    expert_cards: List[ExpertRecord],
) -> List[Dict[str, Any]]:
    """成员升级判定：批量比较团队绑定版本与成员最新发布版本。

    ``member-updates`` 端点与单测共用的唯一实现（消除双份维护的
    漂移风险）。

    Args:
        members: 团队成员列表（含 expert_version 绑定）
        expert_cards: 员工卡片列表（ExpertRecord 投影）

    Returns:
        每项含 expert_id / expert_name / bound_version /
        latest_version / upgradable
    """
    by_id = {e.id: e for e in expert_cards}
    result: List[Dict[str, Any]] = []
    for member in members:
        expert = by_id.get(member.expert_id)
        bound = member.expert_version
        latest = int(expert.published_version or 0) if expert else 0
        result.append({
            "expert_id": member.expert_id,
            "expert_name": expert.name if expert else "",
            "bound_version": bound,
            "latest_version": latest,
            "upgradable": latest > (bound or 0),
        })
    return result


__all__ = [
    "CHANGE_REQUEST_STATUSES",
    "compute_member_upgrades",
    "team_metadata",
    "validate_team",
]
