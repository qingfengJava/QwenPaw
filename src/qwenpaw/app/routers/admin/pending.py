# -*- coding: utf-8 -*-
"""Admin pending-inbox API (P3)：人工介入点的统一聚合视图.

把散落在各权威表中的"需要人处理"事项聚合为一个收件箱：
- 专家团 run：``escalated``（熔断升级）/ ``awaiting_confirm``（待澄清）；
- 演进提案：``ready_for_review``（待审批）；
- 员工定时任务：active 且最近一次执行失败（需运维关注）。

只读聚合（单表批查 + 内存组装），不建流水新表；每项给前端跳转链接。
@author qingfeng
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import text

from ...enterprise import current_tenant_id, require_enterprise_engine
from ...rbac import PERM_ADMIN_EXPERTS, require_perm

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["admin-pending"],
    dependencies=[Depends(require_perm(PERM_ADMIN_EXPERTS))],
)

#: 各分区拉取上限（收件箱是待办视图，不是全量审计）
_SECTION_LIMIT = 20


def _since(days: int) -> datetime:
    """Window start helper (UTC)."""
    return datetime.now(dt_timezone.utc) - timedelta(days=days)


@router.get("/pending-items")
async def pending_items() -> Dict[str, Any]:
    """Aggregate all human-gate items (P3 收件箱).

    返回 ``{items: [...], counts: {kind: n}}``，items 按 at 倒序。
    """
    tid = current_tenant_id()
    engine = require_enterprise_engine()
    items: List[Dict[str, Any]] = []

    async with engine.connect() as conn:
        # 1) 专家团 run：熔断升级 / 待澄清
        run_rows = (
            await conn.execute(
                text(
                    "SELECT id, team_id, goal, status, escalation_reason, "
                    "error, updated_at FROM team_runs WHERE "
                    "tenant_id = :tid AND status IN "
                    "('escalated', 'awaiting_confirm') "
                    "ORDER BY updated_at DESC LIMIT :lim"
                ),
                {"tid": tid, "lim": _SECTION_LIMIT},
            )
        ).all()
        for row in run_rows:
            escalated = row.status == "escalated"
            items.append(
                {
                    "kind": "run_escalated" if escalated else "run_confirm",
                    "id": row.id,
                    "title": row.goal or "（无目标描述）",
                    "detail": (
                        (row.escalation_reason or row.error or "")
                        if escalated
                        else "任务发起时提出了澄清问题，等待答复"
                    ),
                    "at": row.updated_at,
                    "link": f"/admin/workforce-runs?runId={row.id}",
                },
            )
        # 2) 演进提案：待审批
        proposal_rows = (
            await conn.execute(
                text(
                    "SELECT id, expert_id, title, hypothesis, updated_at "
                    "FROM evolution_proposals WHERE tenant_id = :tid "
                    "AND status = 'ready_for_review' "
                    "ORDER BY updated_at DESC LIMIT :lim"
                ),
                {"tid": tid, "lim": _SECTION_LIMIT},
            )
        ).all()
        for row in proposal_rows:
            items.append(
                {
                    "kind": "proposal_review",
                    "id": row.id,
                    "title": row.title,
                    "detail": row.hypothesis or "",
                    "at": row.updated_at,
                    "link": f"/admin/experts/{row.expert_id}?tab=work",
                },
            )
        # 3) 员工定时任务：启用中且最近一次执行失败
        task_rows = (
            await conn.execute(
                text(
                    "SELECT id, expert_id, name, last_run_at, last_status, "
                    "updated_at FROM expert_scheduled_tasks WHERE "
                    "tenant_id = :tid AND status = 'active' "
                    "AND last_status = 'failed' "
                    "ORDER BY last_run_at DESC NULLS LAST LIMIT :lim"
                ),
                {"tid": tid, "lim": _SECTION_LIMIT},
            )
        ).all()
        for row in task_rows:
            items.append(
                {
                    "kind": "task_failed",
                    "id": row.id,
                    "title": f"定时任务「{row.name}」最近一次执行失败",
                    "detail": f"任务 id：{row.id}",
                    "at": row.last_run_at or row.updated_at,
                    "link": f"/admin/experts/{row.expert_id}",
                },
            )

    items.sort(
        key=lambda x: x.get("at") or datetime.min.replace(tzinfo=dt_timezone.utc),
        reverse=True,
    )
    counts: Dict[str, int] = {}
    for item in items:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    return {"items": items, "counts": counts}
