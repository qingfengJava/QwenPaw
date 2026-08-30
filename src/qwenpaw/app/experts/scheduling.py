# -*- coding: utf-8 -*-
"""Expert scheduled tasks: projection ledger + CronManager wiring.

员工定时任务（决策 D5，复用 automations 的「投影 + 权威分离」模式）：
- 台账：``expert_scheduled_tasks``（UI 管理/统计投影）；
- 权威：该专家 workspace 的 ``CronManager``（APScheduler），
  job id 前缀 ``expert_task_``，``meta.expert_task_id`` 双保险定位；
- 执行：task_type=agent、``request.input=task_prompt``——即对该数字
  员工发起一次真实任务（走其自身 ReAct 引擎），独立会话累积
  （share_session=False → 会话 ``cron:{job_id}``）；
- 留痕：CronManager 执行观察者把每次执行写 ``expert_task_runs``
  并回写投影（last_run_at/last_status/run_count/next_run_at）。

逆向：delete=注销权威 job + 行置 archived；pause/resume 双侧同步；
创建时注册失败回滚投影行。
@author qingfeng
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from ..enterprise import current_tenant_id, new_id, require_enterprise_engine
from .models import (
    TASK_STATUS_ACTIVE,
    TASK_STATUS_ARCHIVED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_PAUSED,
    ScheduledTaskRecord,
    TaskRunRecord,
)

logger = logging.getLogger(__name__)

#: CronManager 权威 job id 前缀（观察者据此识别本域任务）
EXPERT_TASK_JOB_PREFIX = "expert_task_"

_TASK_COLS = (
    "id, expert_id, name, description, task_prompt, schedule_type, "
    "schedule_json, timezone, status, cron_job_id, next_run_at, "
    "last_run_at, last_status, run_count, owner_id, created_at, updated_at"
)

_RUN_COLS = (
    "id, task_id, expert_id, scheduled_for, status, result_summary, "
    "error, started_at, finished_at"
)


def _row_to_task(row) -> ScheduledTaskRecord:
    """Map one expert_scheduled_tasks row."""
    return ScheduledTaskRecord(
        id=row.id,
        expert_id=row.expert_id,
        name=row.name,
        description=row.description or "",
        task_prompt=row.task_prompt,
        schedule_type=row.schedule_type,
        schedule_json=row.schedule_json or {},
        timezone=row.timezone or "Asia/Shanghai",
        status=row.status,
        cron_job_id=row.cron_job_id or "",
        next_run_at=row.next_run_at,
        last_run_at=row.last_run_at,
        last_status=row.last_status or "",
        run_count=int(row.run_count or 0),
        owner_id=row.owner_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_run(row) -> TaskRunRecord:
    """Map one expert_task_runs row."""
    return TaskRunRecord(
        id=row.id,
        task_id=row.task_id,
        expert_id=row.expert_id,
        scheduled_for=row.scheduled_for,
        status=row.status,
        result_summary=row.result_summary or "",
        error=row.error or "",
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


class SchedulingStore:
    """CRUD over ``expert_scheduled_tasks`` / ``expert_task_runs``."""

    async def create_task(
        self,
        expert_id: str,
        name: str,
        task_prompt: str,
        schedule_type: str = "cron",
        schedule_json: Optional[dict] = None,
        timezone: str = "Asia/Shanghai",
        description: str = "",
        owner_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> ScheduledTaskRecord:
        """Insert the projection row (authority registration is the
        service layer's job — this stays a pure table writer)."""
        tid = current_tenant_id()
        task_id = task_id or new_id("stk")
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO expert_scheduled_tasks (tenant_id, id, "
                    "expert_id, name, description, task_prompt, "
                    "schedule_type, schedule_json, timezone, status, "
                    "owner_id) VALUES (:tid, :id, :eid, :name, :desc, "
                    ":prompt, :stype, CAST(:sjson AS JSONB), :tz, "
                    ":status, :owner) RETURNING " + _TASK_COLS
                ),
                {
                    "tid": tid,
                    "id": task_id,
                    "eid": expert_id,
                    "name": name,
                    "desc": description,
                    "prompt": task_prompt,
                    "stype": schedule_type,
                    "sjson": _dumps(schedule_json or {}),
                    "tz": timezone,
                    "status": TASK_STATUS_ACTIVE,
                    "owner": owner_id,
                },
            )
            return _row_to_task(result.one())

    async def get_task(self, task_id: str) -> Optional[ScheduledTaskRecord]:
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT " + _TASK_COLS + " FROM expert_scheduled_tasks "
                    "WHERE tenant_id = :tid AND id = :id"
                ),
                {"tid": current_tenant_id(), "id": task_id},
            )
            row = result.first()
            return _row_to_task(row) if row else None

    async def list_tasks(
        self,
        expert_id: str,
        include_archived: bool = False,
    ) -> List[ScheduledTaskRecord]:
        """List one expert's tasks (archived hidden by default)."""
        engine = require_enterprise_engine()
        clauses = ["tenant_id = :tid", "expert_id = :eid"]
        params: Dict[str, object] = {
            "tid": current_tenant_id(),
            "eid": expert_id,
        }
        if not include_archived:
            clauses.append("status <> :archived")
            params["archived"] = TASK_STATUS_ARCHIVED
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT " + _TASK_COLS + " FROM expert_scheduled_tasks "
                    "WHERE " + " AND ".join(clauses) + " ORDER BY created_at DESC"
                ),
                params,
            )
            return [_row_to_task(r) for r in result]

    async def update_task(
        self,
        task_id: str,
        **fields,
    ) -> Optional[ScheduledTaskRecord]:
        """Partial update (None=不修改；schedule_json 传 dict 整体替换)."""
        sets = []
        params: Dict[str, object] = {
            "tid": current_tenant_id(),
            "id": task_id,
        }
        if fields.get("name") is not None:
            sets.append("name = :name")
            params["name"] = fields["name"]
        if fields.get("description") is not None:
            sets.append("description = :desc")
            params["desc"] = fields["description"]
        if fields.get("task_prompt") is not None:
            sets.append("task_prompt = :prompt")
            params["prompt"] = fields["task_prompt"]
        if fields.get("schedule_json") is not None:
            sets.append("schedule_json = CAST(:sjson AS JSONB)")
            params["sjson"] = _dumps(fields["schedule_json"])
        if fields.get("timezone") is not None:
            sets.append("timezone = :tz")
            params["tz"] = fields["timezone"]
        if fields.get("status") is not None:
            sets.append("status = :status")
            params["status"] = fields["status"]
        if not sets:
            return await self.get_task(task_id)
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE expert_scheduled_tasks SET "
                    + ", ".join(sets)
                    + ", updated_at = now() WHERE tenant_id = :tid "
                    "AND id = :id RETURNING " + _TASK_COLS
                ),
                params,
            )
            row = result.first()
            return _row_to_task(row) if row else None

    async def delete_task(self, task_id: str) -> bool:
        """Archive (delete 语义：权威 job 由 service 层先注销)."""
        updated = await self.update_task(
            task_id,
            status=TASK_STATUS_ARCHIVED,
        )
        return updated is not None

    async def count_active_by_expert(self, expert_id: str) -> int:
        """Detail-page 四计数之一：active+paused 任务数。"""
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT count(*) AS n FROM expert_scheduled_tasks "
                    "WHERE tenant_id = :tid AND expert_id = :eid "
                    "AND status IN (:a, :p)"
                ),
                {
                    "tid": current_tenant_id(),
                    "eid": expert_id,
                    "a": TASK_STATUS_ACTIVE,
                    "p": TASK_STATUS_PAUSED,
                },
            )
            return int(result.scalar() or 0)

    # ------------------------------------------------------------------
    # execution records（观察者写，worklog 读）
    # ------------------------------------------------------------------

    async def begin_run(
        self,
        task: ScheduledTaskRecord,
        scheduled_for: Optional[datetime],
    ) -> TaskRunRecord:
        """Create one running record (idempotent per scheduled_for)."""
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        run_id = new_id("trn")
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO expert_task_runs (tenant_id, id, task_id, "
                    "expert_id, scheduled_for, status) VALUES "
                    "(:tid, :id, :task, :eid, :sfor, 'running') "
                    "ON CONFLICT (tenant_id, task_id, scheduled_for) "
                    "WHERE scheduled_for IS NOT NULL DO NOTHING"
                ),
                {
                    "tid": tid,
                    "id": run_id,
                    "task": task.id,
                    "eid": task.expert_id,
                    "sfor": scheduled_for,
                },
            )
            # 幂等命中时取回已存在行（DO NOTHING 不返回 id）
            result = await conn.execute(
                text(
                    "SELECT " + _RUN_COLS + " FROM expert_task_runs WHERE "
                    "tenant_id = :tid AND task_id = :task "
                    "AND scheduled_for IS NOT DISTINCT FROM :sfor "
                    "ORDER BY started_at DESC LIMIT 1"
                ),
                {
                    "tid": tid,
                    "task": task.id,
                    "sfor": scheduled_for,
                },
            )
            return _row_to_run(result.one())

    async def finish_run(
        self,
        run: TaskRunRecord,
        status: str,
        result_summary: str = "",
        error: str = "",
    ) -> None:
        """Finalize one run record (succeeded/failed)."""
        engine = require_enterprise_engine()
        tid = current_tenant_id()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE expert_task_runs SET status = :status, "
                    "result_summary = :summary, error = :error, "
                    "finished_at = now() WHERE tenant_id = :tid "
                    "AND id = :id"
                ),
                {
                    "tid": tid,
                    "id": run.id,
                    "status": status,
                    "summary": result_summary,
                    "error": error,
                },
            )
            # 同步投影台账（run_count 只在终结时 +1，重试不重复计数）
            await conn.execute(
                text(
                    "UPDATE expert_scheduled_tasks SET last_run_at = now(), "
                    "last_status = :status, run_count = run_count + 1, "
                    "updated_at = now() WHERE tenant_id = :tid "
                    "AND id = :task"
                ),
                {
                    "tid": tid,
                    "status": status,
                    "task": run.task_id,
                },
            )
            # 一次性任务成功即完结（completed 终态）
            if status == "succeeded":
                await conn.execute(
                    text(
                        "UPDATE expert_scheduled_tasks SET "
                        "status = :completed, updated_at = now() "
                        "WHERE tenant_id = :tid AND id = :task "
                        "AND schedule_type = 'once'"
                    ),
                    {
                        "tid": tid,
                        "task": run.task_id,
                        "completed": TASK_STATUS_COMPLETED,
                    },
                )

    async def list_runs(
        self,
        task_id: str,
        limit: int = 50,
    ) -> List[TaskRunRecord]:
        """Recent runs of one task (newest first)."""
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT " + _RUN_COLS + " FROM expert_task_runs WHERE "
                    "tenant_id = :tid AND task_id = :task "
                    "ORDER BY started_at DESC LIMIT :lim"
                ),
                {
                    "tid": current_tenant_id(),
                    "task": task_id,
                    "lim": limit,
                },
            )
            return [_row_to_run(r) for r in result]


class SchedulingService:
    """Projection ↔ CronManager authority synchronization.

    Router 层从 ``request.app.state.multi_agent_manager`` 解析出专家
    workspace 后把 ``cron_manager`` 传进来——service 不直接依赖 app
    状态（保持可测）。
    """

    def __init__(self, cron_manager: Any):
        self._cron = cron_manager
        # 幂等挂执行观察者（manager 可能因 LRU 重建，每次接线都尝试）
        _attach_execution_observer(cron_manager)

    def _job_id(self, task_id: str) -> str:
        """Authority job id for one projection task."""
        return f"{EXPERT_TASK_JOB_PREFIX}{task_id}"

    def _build_spec(self, task: ScheduledTaskRecord):
        """Map one projection task to an authoritative CronJobSpec.

        - share_session=False → 每任务独立会话 ``cron:{job_id}``，执行
          历史在对话端可追溯；
        - tool_safety=False → 无人值守执行不弹审批（定时任务语义）。
        """
        from ..crons.models import (
            CronJobRequest,
            CronJobSpec,
            DispatchSpec,
            DispatchTarget,
            JobRuntimeSpec,
            ScheduleSpec,
        )

        schedule = dict(task.schedule_json or {})
        if task.schedule_type == "once":
            run_at = schedule.get("run_at")
            if isinstance(run_at, str):
                schedule_spec = ScheduleSpec(
                    type="once",
                    run_at=datetime.fromisoformat(run_at),
                    timezone=task.timezone,
                )
            else:
                raise ValueError("once 任务缺少 run_at")
        else:
            cron_expr = schedule.get("cron", "")
            if not cron_expr:
                raise ValueError("cron 任务缺少 cron 表达式")
            schedule_spec = ScheduleSpec(
                type="cron",
                cron=cron_expr,
                timezone=task.timezone,
            )
        return CronJobSpec(
            id=self._job_id(task.id),
            name=f"[数字员工] {task.name}",
            enabled=task.status == TASK_STATUS_ACTIVE,
            schedule=schedule_spec,
            task_type="agent",
            request=CronJobRequest(input=task.task_prompt),
            dispatch=DispatchSpec(
                type="channel",
                channel="console",
                target=DispatchTarget(user_id=task.owner_id or "cron"),
                silent=True,
                meta={"expert_task_id": task.id},
            ),
            runtime=JobRuntimeSpec(
                tool_safety=False,
                share_session=False,
                timeout_seconds=600,
            ),
            meta={"expert_task_id": task.id},
        )

    async def create_task(
        self,
        task: ScheduledTaskRecord,
    ) -> ScheduledTaskRecord:
        """Register the authority job for a fresh projection row.

        逆向保护：注册失败时归档投影行（不留孤儿 active 台账）。
        """
        spec = self._build_spec(task)
        try:
            await self._cron.create_or_replace_job(spec)
        except Exception:
            await get_scheduling_store().delete_task(task.id)
            raise
        return await self._refresh_projection(task.id)

    async def update_task(self, task: ScheduledTaskRecord):
        """Replace the authority job (create_or_replace is idempotent)."""
        await self._cron.create_or_replace_job(self._build_spec(task))
        return await self._refresh_projection(task.id)

    async def pause_task(self, task_id: str):
        await self._cron.pause_job(self._job_id(task_id))
        store = get_scheduling_store()
        await store.update_task(task_id, status=TASK_STATUS_PAUSED)
        return await self._refresh_projection(task_id)

    async def resume_task(self, task_id: str):
        await self._cron.resume_job(self._job_id(task_id))
        store = get_scheduling_store()
        await store.update_task(task_id, status=TASK_STATUS_ACTIVE)
        return await self._refresh_projection(task_id)

    async def delete_task(self, task_id: str):
        """Authority first, projection second（先注销调度再归档台账）."""
        job_id = self._job_id(task_id)
        try:
            await self._cron.delete_job(job_id)
        except Exception:  # pylint: disable=broad-except
            # 权威 job 可能已不存在（once 执行完被 APScheduler 移除）
            logger.info(
                "authority job %s already gone; archive projection only",
                job_id,
            )
        await get_scheduling_store().delete_task(task_id)

    async def run_now(self, task_id: str) -> None:
        """Manual trigger (fire-and-forget; observer writes the record)."""
        await self._cron.run_job(self._job_id(task_id))

    async def _refresh_projection(
        self,
        task_id: str,
    ) -> Optional[ScheduledTaskRecord]:
        """Best-effort next_run_at sync from the authority state."""
        store = get_scheduling_store()
        task = await store.get_task(task_id)
        if task is None:
            return None
        state = self._cron.get_state(self._job_id(task_id))
        next_run_at = getattr(state, "next_run_at", None)
        if not next_run_at or next_run_at == task.next_run_at:
            return task
        # next_run_at 不开放给用户编辑（派生字段），这里走专用 SQL 直更
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE expert_scheduled_tasks SET "
                    "next_run_at = :next, updated_at = now() "
                    "WHERE tenant_id = :tid AND id = :id"
                ),
                {
                    "tid": current_tenant_id(),
                    "id": task_id,
                    "next": next_run_at,
                },
            )
        return await store.get_task(task_id)


async def record_execution(
    cron_manager: Any,
    job: Any,
    record: Any,
    execution_result: Dict[str, Any],
) -> None:
    """CronManager 执行观察者：把一次执行落成 expert_task_runs。

    - 仅处理本域 job id（expert_task_ 前缀）；
    - scheduled 触发以执行时刻为幂等锚 scheduled_for；
    - CronExecutionRecord.status → succeeded/failed 投影映射。
    """
    job_id = getattr(job, "id", "") or ""
    if not job_id.startswith(EXPERT_TASK_JOB_PREFIX):
        return
    prefix_len = len(EXPERT_TASK_JOB_PREFIX)
    task_id = job_id[prefix_len:]
    store = get_scheduling_store()
    task = await store.get_task(task_id)
    if task is None:
        logger.warning(
            "expert task projection missing for %s; skip run record",
            task_id,
        )
        return

    cron_status = getattr(record, "status", "") or "error"
    error = getattr(record, "error", "") or ""
    status = "failed" if cron_status != "success" else "succeeded"
    result_summary = str(execution_result.get("final_text") or "")[:500]

    scheduled_for = (
        getattr(record, "run_at", None)
        if getattr(record, "trigger", "") == "scheduled"
        else None
    )
    run = await store.begin_run(task, scheduled_for)
    await store.finish_run(
        run,
        status=status,
        result_summary=result_summary,
        error=error,
    )


def _attach_execution_observer(cron_manager: Any) -> None:
    """Idempotently register :func:`record_execution` on one manager."""
    observers = getattr(cron_manager, "execution_observers", None)
    if observers is None:
        return
    if record_execution not in observers:
        observers.append(record_execution)


def _dumps(value: object) -> str:
    """JSON dump helper (keeps the SQL blocks terse)."""
    import json

    return json.dumps(value or {})


_store: SchedulingStore | None = None


def get_scheduling_store() -> SchedulingStore:
    """Process-wide singleton (stateless; engine shared per DSN)."""
    global _store  # pylint: disable=global-statement
    if _store is None:
        _store = SchedulingStore()
    return _store
