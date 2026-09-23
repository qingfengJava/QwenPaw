# -*- coding: utf-8 -*-
"""Expert scheduled tasks: cron-plane authority wiring (T13d 收口后).

员工定时任务（决策 D5「投影 + 权威分离」的收口终态）：

- **权威**：该专家 workspace 的 ``CronManager``（APScheduler）——
  job id 前缀 ``expert_task_``，``spec.meta`` 承载专家域注解
  （原始名/描述/来源）；规格与执行留痕只落 ``cron_jobs`` /
  ``cron_job_history``（Phase 1 已补齐 result_summary/run_id/
  session_id/scheduled_for/run_count）；
- **读**：:mod:`.cron_ledger` 的 ``CronLedgerReader`` 从 cron 双表
  反推 :class:`ScheduledTaskRecord` / :class:`TaskRunRecord`（expert
  两表已 DROP，不再有第二套台账与门控回退）；
- **执行**：task_type=agent、``request.input=task_prompt``——对该数字
  员工发起一次真实任务（走其自身 ReAct 引擎），独立会话累积
  （share_session=False → 会话 ``cron:{job_id}``）；执行留痕由
  CronManager 权威落 history，执行观察者只做结果自检（inbox 告警）。

存储后端约束（决策 D1）：专家域 cron 平面必须 PG 权威，即部署须
``QWENPAW_STORAGE_BACKEND ∈ {dual,pg}``；json 后端下双表为空，启动
经 :func:`.cron_ledger.warn_if_json_backend` 告警。
@author qingfeng
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .cron_ledger import get_cron_ledger_reader, warn_if_json_backend
from .models import (
    TASK_STATUS_ACTIVE,
    ScheduledTaskRecord,
    TaskRunRecord,
)

logger = logging.getLogger(__name__)

#: CronManager 权威 job id 前缀（观察者据此识别本域任务）
EXPERT_TASK_JOB_PREFIX = "expert_task_"


class SchedulingStore:
    """Read-only facade over the cron double-table plane (T13d 收口).

    expert 两表已 DROP：所有读经 :class:`CronLedgerReader` 反推 cron
    权威面；写路径唯一入口是 CronManager（:class:`SchedulingService`
    的注册/暂停/恢复/删除）。本类保留原方法签名以兼容既有调用方
    （router / worklog），内部一律委托 reader。
    """

    async def get_task(self, task_id: str) -> Optional[ScheduledTaskRecord]:
        """One task（cron 双表权威读）."""
        return await get_cron_ledger_reader().get_task(task_id)

    async def list_tasks(
        self,
        expert_id: str,
        include_archived: bool = False,
    ) -> List[ScheduledTaskRecord]:
        """List one expert's tasks.

        cron 平面读时 archived（job 已删）天然缺席（决策 D2），
        ``include_archived`` 收口后无对应语义，仅为兼容签名保留。
        """
        return await get_cron_ledger_reader().list_tasks(expert_id)

    async def count_active_by_expert(self, expert_id: str) -> int:
        """Detail-page 四计数之一：active+paused 任务数。"""
        return await get_cron_ledger_reader().count_active_by_expert(
            expert_id,
        )

    async def list_runs(
        self,
        task_id: str,
        limit: int = 50,
    ) -> List[TaskRunRecord]:
        """Recent runs of one task（cron 平面只存已完成 run，决策 D4）."""
        return await get_cron_ledger_reader().list_runs(task_id, limit)

    async def runs_in_window(
        self,
        expert_id: str,
        since: datetime,
    ) -> List[TaskRunRecord]:
        """Work-record 窗口内执行留痕（新→旧，cron 平面读）.

        worklog 专用：cron 分支按 run_at 过滤（started/finished 同值，
        决策 D5）。
        """
        return await get_cron_ledger_reader().recent_runs(expert_id, since)


class SchedulingService:
    """CronManager authority synchronization（收口后唯一写路径）.

    Router 层从 ``request.app.state.multi_agent_manager`` 解析出专家
    workspace 后把 ``cron_manager`` 传进来——service 不直接依赖 app
    状态（保持可测）。创建/更新即向权威注册 spec（``spec.meta`` 承载
    专家域注解），读回经 :class:`CronLedgerReader`；无投影行可回滚。
    """

    def __init__(self, cron_manager: Any, expert_id: Optional[str] = None):
        self._cron = cron_manager
        # 幂等挂执行观察者（manager 可能因 LRU 重建，每次接线都尝试）：
        # 收口后观察者只负责执行检查闭环（inbox 告警），不再写台账
        _attach_execution_observer(cron_manager, expert_id)

    def _job_id(self, task_id: str) -> str:
        """Authority job id for one projection task."""
        return f"{EXPERT_TASK_JOB_PREFIX}{task_id}"

    def _build_spec(self, task: ScheduledTaskRecord):
        """Map one task record to an authoritative CronJobSpec.

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
        # T13 收口：expert 台账专属字段落入权威 spec.meta，作为
        # CronLedgerReader 反推的单一来源；原始名/描述不依赖
        # "[数字员工] " 前缀剥离，来源标记 UI 链路补齐。
        spec_meta = {
            "expert_task_id": task.id,
            "expert_task_name": task.name,
            "expert_description": task.description or "",
            "origin_source": "ui",
        }
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
                # session_id 置空串：executor 的 share_session=False 分支
                # 据此派生专属会话 ``cron:{job_id}``（与本模块头注一致）；
                # DispatchTarget.session_id 为必填字段，缺失会直接
                # ValidationError（T13a 探查时修复的存量 Bug）。
                target=DispatchTarget(
                    user_id=task.owner_id or "cron",
                    session_id="",
                ),
                silent=True,
                meta=spec_meta,
            ),
            runtime=JobRuntimeSpec(
                tool_safety=False,
                share_session=False,
                timeout_seconds=600,
            ),
            meta=spec_meta,
        )

    async def create_task(
        self,
        task: ScheduledTaskRecord,
    ) -> Optional[ScheduledTaskRecord]:
        """Register the authority job for one task record.

        收口后注册即持久化到 ``cron_jobs``（spec.meta 承载注解），
        无投影行需回滚；注册失败直接抛出，读回经 cron 平面。
        """
        await self._cron.create_or_replace_job(self._build_spec(task))
        return await self._read_back(task.id)

    async def update_task(
        self,
        task: ScheduledTaskRecord,
    ) -> Optional[ScheduledTaskRecord]:
        """Replace the authority job (create_or_replace is idempotent)."""
        await self._cron.create_or_replace_job(self._build_spec(task))
        return await self._read_back(task.id)

    async def pause_task(self, task_id: str):
        """Pause the authority job（enabled=false → reader 派生 paused）."""
        await self._cron.pause_job(self._job_id(task_id))
        return await self._read_back(task_id)

    async def resume_task(self, task_id: str):
        """Resume the authority job（enabled=true → reader 派生 active）."""
        await self._cron.resume_job(self._job_id(task_id))
        return await self._read_back(task_id)

    async def delete_task(self, task_id: str) -> None:
        """注销权威 job（cron 行删除即从列表消失，决策 D2）."""
        job_id = self._job_id(task_id)
        try:
            await self._cron.delete_job(job_id)
        except Exception:  # pylint: disable=broad-except
            # 权威 job 可能已不存在（once 执行完被 APScheduler 移除）
            logger.info("authority job %s already gone", job_id)

    async def run_now(self, task_id: str) -> None:
        """Manual trigger (fire-and-forget; authority writes the record)."""
        await self._cron.run_job(self._job_id(task_id))

    async def _read_back(
        self,
        task_id: str,
    ) -> Optional[ScheduledTaskRecord]:
        """读回权威投影 + 注入 next_run_at 运行态（内存，不落库）."""
        task = await get_scheduling_store().get_task(task_id)
        if task is None:
            return None
        state = self._cron.get_state(self._job_id(task_id))
        next_run_at = getattr(state, "next_run_at", None)
        if next_run_at:
            return task.model_copy(update={"next_run_at": next_run_at})
        return task

    def annotate_next_run(
        self,
        tasks: List[ScheduledTaskRecord],
    ) -> List[ScheduledTaskRecord]:
        """读切换后的 next_run_at 注入（cron 平面只有规格与历史）。

        GET 列表类端点专用：逐任务查 APScheduler 运行态（内存字典，
        不触发任何 IO）；chat/api 链路 job_id 即任务 id，靠
        ``cron_job_id`` 定位。
        """
        annotated: List[ScheduledTaskRecord] = []
        for task in tasks:
            job_id = task.cron_job_id or self._job_id(task.id)
            state = self._cron.get_state(job_id)
            next_run_at = getattr(state, "next_run_at", None)
            annotated.append(
                task.model_copy(update={"next_run_at": next_run_at})
                if next_run_at
                else task,
            )
        return annotated


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
    """CronManager 执行观察者：执行检查闭环（收口后不再写台账）.

    执行留痕已由权威 CronManager 落 ``cron_job_history``（Phase 1 补齐
    result_summary/run_id/session_id/scheduled_for），本观察者只负责
    执行结果自检——异常时落 inbox 告警供运维介入，不再写第二套台账。
    任务信息经 :class:`CronLedgerReader` 从 cron 平面读回（UI 前缀 job
    去前缀、chat/api job 原样）。
    """
    job_id = getattr(job, "id", "") or ""
    store = get_scheduling_store()
    if job_id.startswith(EXPERT_TASK_JOB_PREFIX):
        task = await store.get_task(job_id[len(EXPERT_TASK_JOB_PREFIX):])
    else:
        task = await store.get_task(job_id)
    if task is None:
        logger.warning(
            "cron plane task missing for %s (expert_id=%s); "
            "skip run check alert",
            job_id,
            expert_id,
        )
        return

    cron_status = getattr(record, "status", "") or "error"
    status = "failed" if cron_status != "success" else "succeeded"
    # 执行记录与会话日志的关联键（agent 任务才产生 run_id/session_id）。
    # executor 自建 trace 的 uuid 与 hook 写入 agent_runs 的权威
    # run id 不同轨——详情页跳转以 agent_runs 为准，按 cron_job_id
    # 反查本次 run；查不到时保持 trace id 兑底（检查闭环另行告警）。
    run_id = str(execution_result.get("run_id") or "")
    session_id = str(execution_result.get("session_id") or "")
    if execution_result.get("task_type") == "agent":
        from ..run_log_pg_store import get_latest_run_id_for_cron_job

        authority_run_id = await get_latest_run_id_for_cron_job(job_id)
        if authority_run_id:
            run_id = authority_run_id

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
                    "run_id": run_id,
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
# CronJobSpec 反推工具（CronLedgerReader 复用；纯函数无 IO）
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


async def attach_expert_scheduling(
    cron_manager: Any,
    expert_id: str,
) -> None:
    """Workspace 装配点接线（收口后仅挂执行检查观察者）.

    注册观察者与台账回填已随 expert 两表退役移除：chat/api 创建的
    任务本就直接落 ``cron_jobs`` 权威面，:class:`CronLedgerReader`
    统一读取，无需二次投影。执行观察者仅保留执行检查闭环（inbox
    告警）；json 后端另出 D1 告警。
    """
    warn_if_json_backend(expert_id)
    _attach_execution_observer(cron_manager, expert_id)


_store: SchedulingStore | None = None


def get_scheduling_store() -> SchedulingStore:
    """Process-wide singleton (stateless; engine shared per DSN)."""
    global _store  # pylint: disable=global-statement
    if _store is None:
        _store = SchedulingStore()
    return _store
