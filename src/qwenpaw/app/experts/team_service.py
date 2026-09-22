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
from .models import TEAM_MEMBER_ROLE_LEAD, TEAM_MEMBER_ROLE_MEMBER, TEAM_MODES
from .store import get_expert_store
from .team_config import summarize_team_config, validate_publishable_team


async def team_metadata() -> Dict[str, Any]:
    """团队配置元数据（前端枚举/限额唯一来源，禁止前端硬编码）。"""
    # 默认熔断策略（引擎默认值即有效限额起点；治理上限最终由平台收紧）
    default_policy = RunPolicy()
    return {
        "member_roles": [
            {"value": TEAM_MEMBER_ROLE_LEAD, "label": "主理人（Leader）"},
            {"value": TEAM_MEMBER_ROLE_MEMBER, "label": "成员"},
        ],
        "team_modes": [{"value": mode, "label": mode} for mode in TEAM_MODES],
        "limits": {
            "default_max_repair_per_node": default_policy.max_repair_per_node,
            "default_max_replan": default_policy.max_replan,
            "default_parallelism": default_policy.parallelism,
            "default_max_total_seconds": default_policy.max_total_seconds,
            "default_max_total_tokens": default_policy.max_total_tokens,
        },
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


__all__ = ["team_metadata", "validate_team"]
