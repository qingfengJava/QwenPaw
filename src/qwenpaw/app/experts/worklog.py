# -*- coding: utf-8 -*-
"""Expert work-record aggregation (read-only, StaffDeck 工作记录对应物).

数据单一来源（决策 D6）：全部从既有权威表聚合，不建流水新表——
- 团队任务：``team_run_nodes``（assignee_expert_id 维度）→
  ``team_runs``（批查补齐 run 状态/目标）；
- 定时任务：``expert_task_runs``；
- 反馈：``message_feedback``；
- 成长记录：``evolution_proposals``（published/rolled_back 即成长点）；
- 能力分配：``expert_resource_bindings`` + ``expert_skills``（挂载时间线）。

性能约束：每类关联只查一次，按天统计用 SQL date_trunc 分组后内存
合并——禁止 N+1（项目规范 §3.4）。
@author qingfeng
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Dict, List

from sqlalchemy import text

from ..enterprise import current_tenant_id, require_enterprise_engine
from .capability import get_capability_store
from .models import WorkRecord
from .store import get_expert_store

#: 时间线最多条数（前端展示预算）
_TIMELINE_LIMIT = 50

#: 时间线单条最大标题长度
_TITLE_MAX = 80


def _truncate(value: str, limit: int = _TITLE_MAX) -> str:
    """Trim one timeline title (display budget)."""
    value = (value or "").strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _day_key(value: datetime | None) -> str:
    """Normalize one timestamp to a UTC date string (by_day group key)."""
    if value is None:
        return ""
    return value.astimezone(dt_timezone.utc).strftime("%Y-%m-%d")


class WorklogService:
    """Aggregate one expert's work record across authority tables."""

    async def build_work_record(
        self,
        expert_id: str,
        days: int = 30,
    ) -> WorkRecord:
        """Assemble :class:`WorkRecord` with batched per-source queries.

        五步范式：主键维度各自一次查询 → 内存组装 → 按天合并统计。
        """
        days = max(1, min(days, 90))
        since = datetime.now(dt_timezone.utc) - timedelta(days=days)
        tid = current_tenant_id()
        engine = require_enterprise_engine()

        # 1) 团队任务节点（该专家被委派的节点）
        async with engine.connect() as conn:
            nodes = (
                await conn.execute(
                    text(
                        "SELECT run_id, status, verdict, updated_at, "
                        "contract FROM team_run_nodes WHERE "
                        "tenant_id = :tid AND assignee_expert_id = :eid "
                        "AND updated_at >= :since"
                    ),
                    {"tid": tid, "eid": expert_id, "since": since},
                )
            ).all()
            # 2) 批查这些节点的 run 头（状态/目标），一次 IN 查询
            run_ids = list({n.run_id for n in nodes})
            runs: Dict[str, Any] = {}
            if run_ids:
                run_rows = await conn.execute(
                    text(
                        "SELECT id, status, goal, updated_at FROM team_runs "
                        "WHERE tenant_id = :tid AND id = ANY(:rids)"
                    ),
                    {"tid": tid, "rids": run_ids},
                )
                runs = {r.id: r for r in run_rows}
            # 3) 定时任务执行留痕（窗口内）
            task_runs = (
                await conn.execute(
                    text(
                        "SELECT id, task_id, status, result_summary, "
                        "started_at, finished_at FROM expert_task_runs "
                        "WHERE tenant_id = :tid AND expert_id = :eid "
                        "AND started_at >= :since "
                        "ORDER BY started_at DESC"
                    ),
                    {"tid": tid, "eid": expert_id, "since": since},
                )
            ).all()
            # 4) 反馈（窗口内）
            feedback_rows = (
                await conn.execute(
                    text(
                        "SELECT rating, created_at FROM message_feedback "
                        "WHERE tenant_id = :tid AND expert_id = :eid "
                        "AND created_at >= :since"
                    ),
                    {"tid": tid, "eid": expert_id, "since": since},
                )
            ).all()
            # 5) 成长记录（已发布/已回滚的演进提案，全量最近 20 条）
            proposals = (
                await conn.execute(
                    text(
                        "SELECT id, title, status, updated_at FROM "
                        "evolution_proposals WHERE tenant_id = :tid "
                        "AND expert_id = :eid "
                        "AND status IN ('published', 'rolled_back') "
                        "ORDER BY updated_at DESC LIMIT 20"
                    ),
                    {"tid": tid, "eid": expert_id},
                )
            ).all()

        # ---- 内存组装：按天统计 ----
        by_day: Dict[str, Dict[str, int]] = {}

        def _bump(day: str, field: str) -> None:
            """One-day counter bump (missing days default to zero)."""
            if not day:
                return
            bucket = by_day.setdefault(day, {"tasks": 0, "feedback": 0})
            bucket[field] += 1

        total_tasks = 0
        succeeded_tasks = 0
        timeline: List[Dict[str, Any]] = []

        for node in nodes:
            run = runs.get(node.run_id)
            ok = node.status == "done" or node.verdict.upper() == "PASS"
            total_tasks += 1
            succeeded_tasks += 1 if ok else 0
            day = _day_key(node.updated_at)
            _bump(day, "tasks")
            goal = getattr(run, "goal", "") if run is not None else ""
            timeline.append(
                {
                    "kind": "task",
                    "title": _truncate(goal or "团队任务节点"),
                    "status": "succeeded" if ok else node.status,
                    "at": node.updated_at,
                },
            )

        for tr in task_runs:
            ok = tr.status == "succeeded"
            total_tasks += 1
            succeeded_tasks += 1 if ok else 0
            _bump(_day_key(tr.started_at), "tasks")
            timeline.append(
                {
                    "kind": "scheduled",
                    "title": _truncate(
                        tr.result_summary or "定时任务执行",
                    ),
                    "status": tr.status,
                    "at": tr.finished_at or tr.started_at,
                },
            )

        feedback_up = 0
        feedback_down = 0
        for fb in feedback_rows:
            if fb.rating == "up":
                feedback_up += 1
            else:
                feedback_down += 1
            _bump(_day_key(fb.created_at), "feedback")

        positive_rate: float | None = None
        if feedback_up + feedback_down > 0:
            positive_rate = round(
                feedback_up / (feedback_up + feedback_down),
                4,
            )

        # 成长记录 + 能力分配事件（时间线补充，不参与任务统计）
        for prop in proposals:
            timeline.append(
                {
                    "kind": "growth",
                    "title": _truncate(prop.title),
                    "status": prop.status,
                    "at": prop.updated_at,
                },
            )
        binding_events = await self._binding_timeline(expert_id)
        timeline.extend(binding_events)

        # 时间线按时间倒序截断（缺时间的事件排最后）
        epoch = datetime.min.replace(tzinfo=dt_timezone.utc)
        timeline.sort(
            key=lambda e: e.get("at") or epoch,
            reverse=True,
        )
        timeline = timeline[:_TIMELINE_LIMIT]

        # by_day 补零到完整窗口（前端日历渲染友好）
        filled: List[Dict[str, Any]] = []
        cursor = datetime.now(dt_timezone.utc).date()
        for offset in range(days):
            day = (cursor - timedelta(days=offset)).isoformat()
            bucket = by_day.get(day, {"tasks": 0, "feedback": 0})
            filled.append({"date": day, **bucket})

        return WorkRecord(
            days=days,
            total_tasks=total_tasks,
            succeeded_tasks=succeeded_tasks,
            feedback_up=feedback_up,
            feedback_down=feedback_down,
            positive_rate=positive_rate,
            by_day=filled,
            timeline=timeline,
        )

    async def _binding_timeline(
        self,
        expert_id: str,
    ) -> List[Dict[str, Any]]:
        """Resource/skill mount events as timeline entries.

        两种挂载各查一次（expert_resource_bindings / expert_skills），
        内存合并成统一的 kind=resource 事件。
        """
        events: List[Dict[str, Any]] = []
        bindings = await get_capability_store().list_bindings(expert_id)
        for binding in bindings:
            name = binding.metadata.get("name") or binding.resource_id
            events.append(
                {
                    "kind": "resource",
                    "title": _truncate(f"挂载能力：{name}"),
                    "status": "enabled" if binding.enabled else "disabled",
                    "at": binding.metadata.get("mounted_at"),
                },
            )
        expert = await get_expert_store().get_expert(expert_id)
        for skill in expert.skills if expert else []:
            events.append(
                {
                    "kind": "resource",
                    "title": _truncate(f"挂载技能：{skill.skill_name}"),
                    "status": "enabled" if skill.enabled else "disabled",
                    "at": None,
                },
            )
        return events


_service: WorklogService | None = None


def get_worklog_service() -> WorklogService:
    """Process-wide singleton (stateless; engine shared per DSN)."""
    global _service  # pylint: disable=global-statement
    if _service is None:
        _service = WorklogService()
    return _service
