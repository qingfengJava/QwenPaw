# -*- coding: utf-8 -*-
"""团队能力投影：声明能力 × 实际可用性的批量读视图（T1）。

对齐计划第五节"能力矩阵"分区：配置页展示的不是一份可手填的能力表，
而是从各权威来源（员工档案 / expert_skills / 资源挂载 / 发布状态）
动态投影的"当前有效能力"，并标注缺失原因。

性能约束（项目规范 2.4）：专家、技能、挂载快照各一次批量查询，
内存组装，禁止 N+1。

@author qingfeng
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import text

from ..enterprise import current_tenant_id, require_enterprise_engine
from .capability import get_capability_store
from .store import get_expert_store


async def _batched_skills(expert_ids: List[str]) -> Dict[str, List[str]]:
    """一次查询取全部成员的启用技能（expert_skills 权威）。"""
    # 空集合直接返回（避免空 IN 查询）
    if not expert_ids:
        return {}
    engine = require_enterprise_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT expert_id, skill_name FROM expert_skills "
                "WHERE tenant_id = :tid AND enabled = TRUE "
                "AND expert_id = ANY(:eids) ORDER BY expert_id, seq, skill_name"
            ),
            {
                "tid": current_tenant_id(),
                "eids": list(expert_ids),
            },
        )
        grouped: Dict[str, List[str]] = {}
        for row in result:
            grouped.setdefault(row.expert_id, []).append(row.skill_name)
        return grouped


async def team_capability_view(team_id: str) -> Dict[str, Any]:
    """团队有效能力投影（详情页能力矩阵数据源）。

    返回::

        {
          "team_id": ...,
          "members": [
            {
              "expert_id", "name", "title", "member_role", "role_hint",
              "published": bool,          # 员工是否已发布（可执行前提）
              "skills": [...],            # 已启用技能绑定（权威）
              "tools": [...],             # 挂载工具名
              "kb_ids": [...],            # 绑定知识库
              "sops": [...],              # 绑定 SOP 紧凑投影
              "unavailable_reason": "",   # 未发布等不可执行原因
            }
          ],
        }
    """
    # 一次取团队（成员即权威绑定）
    store = get_expert_store()
    team = await store.get_team(team_id)
    if team is None:
        return {}
    member_ids = [m.expert_id for m in team.members]
    # 批量 1：成员专家档案（全库一次列表 + 内存过滤，复用既有列表查询）
    experts = {e.id: e for e in await store.list_experts()}
    # 批量 2：成员技能绑定（单查询 IN）
    skills_by_id = await _batched_skills(member_ids)
    # 批量 3：资源挂载快照（sop/kb/tools 已批量的既有投影）
    mounts = await get_capability_store().member_capability_snapshot(member_ids)
    # 内存组装（不再触发任何查询）
    members_view: List[Dict[str, Any]] = []
    for member in team.members:
        expert = experts.get(member.expert_id)
        mount = mounts.get(member.expert_id, {})
        published = bool(expert and expert.status == "published")
        members_view.append(
            {
                "expert_id": member.expert_id,
                "name": expert.name if expert else "",
                "title": expert.title if expert else "",
                "member_role": member.member_role,
                "role_hint": member.role_hint,
                "published": published,
                "skills": list(skills_by_id.get(member.expert_id, [])),
                "tools": list(mount.get("tools", [])),
                "kb_ids": list(mount.get("kb_ids", [])),
                "sops": list(mount.get("sops", [])),
                # 不可执行原因：档案缺失或未发布（能力声明≠可执行）
                "unavailable_reason": ""
                if published
                else ("员工不存在" if expert is None else "员工未发布"),
            },
        )
    return {"team_id": team_id, "members": members_view}


__all__ = ["team_capability_view"]
