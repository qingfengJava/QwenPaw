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
    "last_run_at, last_status, run_count, source, origin, "
    "owner_id, created_at, updated_at"
)

_RUN_COLS = (
    "id, task_id, expert_id, scheduled_for, status, result_summary, "
    "error, run_id, session_id, started_at, finished_at"
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
        source=row.source or "ui",
        origin=row.origin or {},
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
        run_id=row.run_id or "",
        session_id=row.session_id or "",
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
        source: str = "ui",
        origin: Optional[dict] = None,
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
                    "source, origin, owner_id) VALUES "
                    "(:tid, :id, :eid, :name, :desc, :prompt, :stype, "
                    "CAST(:sjson AS JSONB), :tz, :status, :source, "
                    "CAST(:origin AS JSONB), :owner) RETURNING " + _TASK_COLS
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
                    "source": source,
                    "origin": _dumps(origin or {}),
                    "owner": owner_id,
                },
            )
            return _row_to_task(result.one())

    async def upsert_task_from_spec(
        self,
        expert_id: str,
        job_id: str,
        name: str,
        task_prompt: str,
        schedule_type: str,
        schedule_json: dict,
        timezone: str,
        status: str,
        source: str,
        origin: Optional[dict] = None,
        owner_id: Optional[str] = None,
    ) -> Optional[ScheduledTaskRecord]:
        """Idempotent ledger upsert for registration-observer projection.

        台账行 id 直接复用权威 job_id（对话/接口创建链路），重复注册
        事件（create_or_replace 幂等重放）只刷新调度语义字段，不重置
        run_count 等运行时统计。
        """
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO expert_scheduled_tasks (tenant_id, id, "
                    "expert_id, name, task_prompt, schedule_type, "
                    "schedule_json, timezone, status, cron_job_id, "
                    "source, origin, owner_id) VALUES "
                    "(:tid, :id, :eid, :name, :prompt, :stype, "
                    "CAST(:sjson AS JSONB), :tz, :status, :jid, "
                    ":source, CAST(:origin AS JSONB), :owner) "
                    "ON CONFLICT (tenant_id, id) DO UPDATE SET "
                    "name = EXCLUDED.name, "
                    "task_prompt = EXCLUDED.task_prompt, "
                    "schedule_type = EXCLUDED.schedule_type, "
                    "schedule_json = EXCLUDED.schedule_json, "
                    "timezone = EXCLUDED.timezone, status = EXCLUDED.status, "
                    "cron_job_id = EXCLUDED.cron_job_id, "
                    "origin = EXCLUDED.origin, updated_at = now() "
                    "RETURNING " + _TASK_COLS
                ),
                {
                    "tid": tid,
                    "id": job_id,
                    "eid": expert_id,
                    "name": name,
                    "prompt": task_prompt,
                    "stype": schedule_type,
                    "sjson": _dumps(schedule_json or {}),
                    "tz": timezone,
                    "status": status,
                    "jid": job_id,
                    "source": source,
                    "origin": _dumps(origin or {}),
                    "owner": owner_id,
                },
            )
            row = result.first()
            return _row_to_task(row) if row else None

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
                    "WHERE " + " AND ".join(clauses)
                    + " ORDER BY created_at DESC"
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
        run_id: str = "",
        session_id: str = "",
    ) -> TaskRunRecord:
        """Create one running record (idempotent per scheduled_for)."""
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        run_id_row = new_id("trn")
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO expert_task_runs (tenant_id, id, task_id, "
                    "expert_id, scheduled_for, status, run_id, session_id) "
                    "VALUES (:tid, :id, :task, :eid, :sfor, 'running', "
                    ":run_id, :session_id) "
                    "ON CONFLICT (tenant_id, task_id, scheduled_for) "
                    "WHERE scheduled_for IS NOT NULL DO NOTHING"
                ),
                {
                    "tid": tid,
                    "id": run_id_row,
                    "task": task.id,
                    "eid": task.expert_id,
                    "sfor": scheduled_for,
                    "run_id": run_id,
                    "session_id": session_id,
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

    def __init__(self, cron_manager: Any, expert_id: Optional[str] = None):
        self._cron = cron_manager
        # 幂等挂执行观察者（manager 可能因 LRU 重建，每次接线都尝试）
        _attach_execution_observer(cron_manager, expert_id)
        # 幂等挂注册观察者：对话/接口创建的任务自动投影入台账
        # （需 expert_id 定位台账行归属；UI 链路自身管理台账行）
        if expert_id:
            _attach_registration_observer(cron_manager, expert_id)

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


async def _verify_execution_result(
    job: Any,
    execution_result: Dict[str, Any],
) -> Optional[str]:
    """Post-run self-check; return a failure reason or None when OK.

    主动执行检查：agent 任务成功路径必须产出 run_id（会话日志
    权威结构的关联键）且投递未失败，否则视为检查不通过——执行
    结果本身照常落库，检查结论仅落 inbox 告警供运维介入。
    """
    if execution_result.get("task_type") != "agent":
        return None
    if not str(execution_result.get("run_id") or ""):
        return "agent task finished without run_id (session log missing)"
    if execution_result.get("delivery_status") == "failed":
        return (
            "agent task result delivery failed: "
            f"{execution_result.get('delivery_error') or 'unknown'}"
        )
    return None


async def record_execution(
    job: Any,
    record: Any,
    execution_result: Dict[str, Any],
    expert_id: Optional[str] = None,
) -> None:
    """CronManager 执行观察者：把一次执行落成 expert_task_runs。

    - expert_task_ 前缀 job：UI 链路任务，task_id 即去前缀 job id；
    - 其余（对话/接口创建）：台账行 id 复用 job_id；行缺失且已知
      expert_id 时先兜底补投影（观察者挂载前创建的历史任务）；
    - scheduled 触发以执行时刻为幂等锚 scheduled_for；
    - CronExecutionRecord.status → succeeded/failed 投影映射；
    - run_id/session_id 随行写入：详情层经 run_id 关联 agent_runs，
      复用会话日志权威结构（span 树 + 会话回放）。
    """
    job_id = getattr(job, "id", "") or ""
    store = get_scheduling_store()
    if job_id.startswith(EXPERT_TASK_JOB_PREFIX):
        task = await store.get_task(job_id[len(EXPERT_TASK_JOB_PREFIX):])
    else:
        task = await store.get_task(job_id)
        if task is None and expert_id:
            task = await _upsert_task_row(expert_id, job_id, job)
    if task is None:
        logger.warning(
            "task projection missing for %s (expert_id=%s); skip run record",
            job_id,
            expert_id,
        )
        return

    cron_status = getattr(record, "status", "") or "error"
    error = getattr(record, "error", "") or ""
    status = "failed" if cron_status != "success" else "succeeded"
    result_summary = str(execution_result.get("final_text") or "")[:500]
    # 执行记录与会话日志的关联键（agent 任务才产生 run_id/session_id）。
    # executor 自建 trace 的 uuid 与 hook 写入 agent_runs 的权威
    # run id 不同轨——详情页跳转以 agent_runs 为准，按 cron_job_id
    # 反查本次 run；查不到时保持 trace id 兑底（检查闭环另行告警）。
    run_id = str(execution_result.get("run_id") or "")
    session_id = str(execution_result.get("session_id") or "")
    if execution_result.get("task_type") == "agent":
        from ..run_log_pg_store import get_latest_run_id_for_cron_job

        authority_run_id = await get_latest_run_id_for_cron_job(
            job_id,
        )
        if authority_run_id:
            run_id = authority_run_id

    scheduled_for = (
        getattr(record, "run_at", None)
        if getattr(record, "trigger", "") == "scheduled"
        else None
    )
    run = await store.begin_run(
        task,
        scheduled_for,
        run_id=run_id,
        session_id=session_id,
    )
    await store.finish_run(
        run,
        status=status,
        result_summary=result_summary,
        error=error,
    )

    # 执行检查闭环：结论异常时落 inbox 告警（fire-and-forget 语义，
    # 检查本身不改变执行记录的真实状态）
    check_failure = await _verify_execution_result(job, execution_result)
    if check_failure:
        try:
            from ..inbox_store import append_event as append_inbox_event

            await append_inbox_event(
                agent_id=task.expert_id,
                source_type="cron",
                source_id=task.id,
                event_type="cron_run_check_failed",
                status="error",
                severity="error",
                title=f"Cron run check failed: {task.name}",
                body=check_failure,
                payload={
                    "task_id": task.id,
                    "run_id": run.id,
                    "agent_run_id": run_id,
                    "session_id": session_id,
                    "status": status,
                },
            )
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "failed to append cron run check event: task_id=%s",
                task.id,
            )


def _attach_execution_observer(
    cron_manager: Any,
    expert_id: Optional[str] = None,
) -> None:
    """Idempotently bind one expert's execution observer (replace-safe)."""
    observers = getattr(cron_manager, "execution_observers", None)
    if observers is None:
        return

    async def observe_execution(
        job: Any,
        record: Any,
        execution_result: Dict[str, Any],
    ) -> None:
        """Forward one execution record with the expert binding."""
        await record_execution(
            job,
            record,
            execution_result,
            expert_id=expert_id,
        )

    # 观察者身分标记：重挂时按 expert 替换旧闭包（幂等且支持重建）
    observe_execution._expert_id = expert_id  # type: ignore[attr-defined]
    observers[:] = [
        o for o in observers if getattr(o, "_expert_id", None) != expert_id
    ]
    observers.append(observe_execution)


# ---------------------------------------------------------------------------
# 注册观察者：对话/接口创建的任务自动投影入统一台账
# ---------------------------------------------------------------------------


def _task_prompt_from_spec(spec: Any) -> str:
    """Extract the prompt text carried by one CronJobSpec."""
    text = getattr(spec, "text", None)
    if text and str(text).strip():
        return str(text).strip()
    request = getattr(spec, "request", None)
    request_input = getattr(request, "input", None) if request else None
    if isinstance(request_input, str):
        return request_input.strip()
    return "" if request_input is None else str(request_input)


def _schedule_json_from_spec(spec: Any) -> tuple[str, dict]:
    """Reverse-map one CronJobSpec.schedule to the ledger schedule_json."""
    schedule = getattr(spec, "schedule", None)
    schedule_type = getattr(schedule, "type", "cron") or "cron"
    if schedule_type == "once":
        run_at = getattr(schedule, "run_at", None)
        payload: dict = {
            "run_at": run_at.isoformat() if run_at else None,
        }
        repeat_days = getattr(schedule, "repeat_every_days", None)
        if repeat_days:
            payload["repeat_every_days"] = repeat_days
            payload["repeat_end_type"] = (
                getattr(schedule, "repeat_end_type", None) or "never"
            )
            repeat_until = getattr(schedule, "repeat_until", None)
            if repeat_until is not None:
                payload["repeat_until"] = repeat_until.isoformat()
            repeat_count = getattr(schedule, "repeat_count", None)
            if repeat_count is not None:
                payload["repeat_count"] = repeat_count
        return "once", payload
    return "cron", {"cron": getattr(schedule, "cron", "") or ""}


def _origin_from_spec(spec: Any) -> dict:
    """Compact origin payload for traceability (dispatch/runtime 关键字段)."""
    dispatch = getattr(spec, "dispatch", None)
    runtime = getattr(spec, "runtime", None)
    silent = bool(getattr(dispatch, "silent", False)) if dispatch else False
    share_session = (
        bool(getattr(runtime, "share_session", True)) if runtime else True
    )
    tool_safety = (
        bool(getattr(runtime, "tool_safety", False)) if runtime else False
    )
    return {
        "task_type": getattr(spec, "task_type", "agent"),
        "channel": getattr(dispatch, "channel", "") if dispatch else "",
        "mode": getattr(dispatch, "mode", "") if dispatch else "",
        "silent": silent,
        "share_session": share_session,
        "tool_safety": tool_safety,
    }


async def _upsert_task_row(
    expert_id: str,
    job_id: str,
    spec: Any,
) -> Any:
    """Reverse-map one CronJobSpec and upsert its unified ledger row.

    注册观察者（事件驱动）与执行留痕/启动回填（兑底）共用：
    字段映射单一出口；来源标记 meta.origin_source 优先（api），
    缺省 chat；enabled=False → paused。
    """
    schedule_type, schedule_json = _schedule_json_from_spec(spec)
    meta = getattr(spec, "meta", None) or {}
    source = str(meta.get("origin_source") or "chat")
    target = getattr(getattr(spec, "dispatch", None), "target", None)
    owner_id = getattr(target, "user_id", None) if target else None
    if not owner_id or owner_id == "cron":
        owner_id = None
    schedule = getattr(spec, "schedule", None)
    timezone = getattr(schedule, "timezone", "") or "Asia/Shanghai"
    enabled = bool(getattr(spec, "enabled", True))
    return await get_scheduling_store().upsert_task_from_spec(
        expert_id=expert_id,
        job_id=job_id,
        name=getattr(spec, "name", "") or job_id,
        task_prompt=_task_prompt_from_spec(spec),
        schedule_type=schedule_type,
        schedule_json=schedule_json,
        timezone=timezone,
        status=(TASK_STATUS_ACTIVE if enabled else TASK_STATUS_PAUSED),
        source=source,
        origin=_origin_from_spec(spec),
        owner_id=owner_id,
    )


def _make_registration_observer(expert_id: str):
    """Build one registration observer bound to one expert (ledger row)."""

    async def observe_registration(
        event: str,
        spec: Any,
        job_id: str,
    ) -> None:
        """Project one CronManager registration event into the ledger.

        - expert_task_ 前缀 job：UI 链路已管理台账行，观察者跳过；
        - 其余（对话 slash cron-create / 开放接口）：台账行 id 复用
          job_id，created/paused/resumed 幂等 upsert，deleted 归档；
        - 来源标记：spec.meta.origin_source 优先（api），缺省 chat。
        """
        if job_id.startswith(EXPERT_TASK_JOB_PREFIX):
            return
        store = get_scheduling_store()
        if event == "deleted":
            # 权威 job 已删，对应台账行归档（行不存在时 update 无效，幂等）
            await store.update_task(job_id, status=TASK_STATUS_ARCHIVED)
            return
        if spec is None:
            return
        await _upsert_task_row(expert_id, job_id, spec)

    # 观察者身分标记：重挂时按 expert 替换旧闭包（幂等且支持重建）
    observe_registration._expert_id = expert_id  # type: ignore[attr-defined]
    return observe_registration


def _attach_registration_observer(cron_manager: Any, expert_id: str) -> None:
    """Idempotently bind one expert's registration observer."""
    observers = getattr(cron_manager, "registration_observers", None)
    if observers is None:
        return
    observers[:] = [
        o for o in observers if getattr(o, "_expert_id", None) != expert_id
    ]
    observers.append(_make_registration_observer(expert_id))


async def _backfill_tasks_from_authority(
    cron_manager: Any,
    expert_id: str,
) -> None:
    """Startup backfill: project pre-existing chat/api jobs.

    以权威 cron jobs 为源补台账行（幂等）：
    - expert_task_ 前缀 job 由 UI 链路管理，跳过；
    - 已入账（含 archived）的 job 跳过——已删任务台账行不复活；
    - 行缺失（观察者挂载前创建的任务）→ upsert 补投影。
    """
    list_jobs = getattr(cron_manager, "list_jobs", None)
    if not callable(list_jobs):
        return
    store = get_scheduling_store()
    for job in await list_jobs():
        job_id = getattr(job, "id", "") or ""
        if not job_id or job_id.startswith(EXPERT_TASK_JOB_PREFIX):
            continue
        if await store.get_task(job_id) is not None:
            continue
        await _upsert_task_row(expert_id, job_id, job)


async def attach_expert_scheduling(
    cron_manager: Any,
    expert_id: str,
) -> None:
    """Workspace 装配点一次性接线（对话创建任务入统一台账的根）。

    观察者此前只在对台账的写操作（SchedulingService factory）时
    挂载，而对话链路（/cron/jobs）从不过 factory——created 与
    执行事件全部丢失。专家 workspace 启动时在此挂注册+执行观察
    者，并回填挂载前已存在的任务。
    """
    _attach_registration_observer(cron_manager, expert_id)
    _attach_execution_observer(cron_manager, expert_id)
    await _backfill_tasks_from_authority(cron_manager, expert_id)


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
