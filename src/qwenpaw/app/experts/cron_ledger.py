# -*- coding: utf-8 -*-
"""Cron-plane ledger reader (T13 双台账收口 Phase 2 读层).

expert 两表（``expert_scheduled_tasks`` / ``expert_task_runs``）收口进
cron 权威双表后的**读侧单一出口**：从 ``cron_jobs`` + ``cron_job_history``
反推领域记录形状（:class:`ScheduledTaskRecord` / :class:`TaskRunRecord`）。
字段映射规则见设计文档
``docs/design/2026-09-18-cron-ledger-convergence.md`` §3.1。

映射要点：

- 归属键换算：cron 侧 ``agent_id = expert_{expert_id}``；UI 链路
  ``job_id = expert_task_{task_id}``，chat/api 链路 ``job_id = task_id``；
- ``name``/``description``/``source`` 优先读 ``spec.meta`` 注解（T13a
  Phase 1 起由 ``_build_spec`` 写入），未注解行剥 ``[数字员工] `` 前缀兑底；
- ``status``：``enabled`` → active/paused；``once`` 且存在 success 历史 →
  completed（对齐台账 finish_run 规则）；job 已删（archived）不再列出，
  历史随删除清理（决策 D2 语义变更）；
- ``run_count`` 读 ``cron_jobs.run_count`` 冗余列（决策 D3，不被
  history 50 条修剪窗截断）；
- ``next_run_at`` 属 APScheduler 运行态，读层恒 None，由调用方
  （:class:`SchedulingService`）注入；
- run 的 ``started_at``/``finished_at`` 同取 ``run_at``（决策 D5）；
  在途 running 行不可见（决策 D4，cron history 只在完成时 append）。

读平面单一出口：expert 两表已收口进 cron 双表并 DROP（T13d Phase 3），
本模块是专家定时任务/执行留痕的**唯一**读路径，不再有门控回退与
Phase 2 一次性回填/对账工具（已随收口完成删除）。json 存储后端下
cron 平面为空——专家域要求 dual/pg，:func:`warn_if_json_backend` 启动
告警（决策 D1）。

@author qingfeng
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from .models import (
    TASK_STATUS_ACTIVE,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_PAUSED,
    ScheduledTaskRecord,
    TaskRunRecord,
)

logger = logging.getLogger(__name__)

#: cron 侧归属前缀（expert_agent_id() 的逆运算）
EXPERT_AGENT_PREFIX = "expert_"

#: UI 链路权威 job id 前缀（与 scheduling.EXPERT_TASK_JOB_PREFIX 同值，
#: 此处独立常量避免与本模块的循环导入）
EXPERT_TASK_JOB_PREFIX = "expert_task_"

#: spec.name 的 UI 链路展示前缀（未回填注解时剥除兑底）
_AGENT_NAME_PREFIX = "[数字员工] "

_RUN_COLUMNS = (
    "agent_id, job_id, seq, run_at, status, error, result_summary, "
    "run_id, session_id, scheduled_for"
)

_TASK_COLUMNS = (
    "agent_id, job_id, CAST(spec AS TEXT) AS spec, enabled, run_count, "
    "created_at, updated_at"
)

_SELECT_TASKS_BY_AGENT = (
    "SELECT " + _TASK_COLUMNS + " FROM cron_jobs "
    "WHERE tenant_id = :tid AND agent_id = :aid "
    "ORDER BY created_at DESC"
)

_SELECT_TASKS_BY_JOB_IDS = (
    "SELECT " + _TASK_COLUMNS + " FROM cron_jobs "
    "WHERE tenant_id = :tid AND job_id = ANY(:jids) "
    "AND agent_id LIKE 'expert_%' "
    "ORDER BY job_id = :primary DESC, created_at DESC"
)

#: 每 job 最新一条历史 + 是否存在 success（completed/last_* 反推一次取齐）
_SELECT_HISTORY_STATS = (
    "WITH latest AS ( "
    "  SELECT DISTINCT ON (job_id) job_id, run_at, status "
    "  FROM cron_job_history "
    "  WHERE tenant_id = :tid AND agent_id = :aid "
    "  ORDER BY job_id, seq DESC "
    "), stats AS ( "
    "  SELECT job_id, bool_or(status = 'success') AS any_success "
    "  FROM cron_job_history "
    "  WHERE tenant_id = :tid AND agent_id = :aid "
    "  GROUP BY job_id "
    ") SELECT l.job_id, l.run_at, l.status, s.any_success "
    "FROM latest l JOIN stats s ON s.job_id = l.job_id"
)

_SELECT_RUNS_BY_JOB_IDS = (
    "SELECT " + _RUN_COLUMNS + " FROM cron_job_history "
    "WHERE tenant_id = :tid AND job_id = ANY(:jids) "
    "AND agent_id LIKE 'expert_%' "
    "ORDER BY run_at DESC, seq DESC LIMIT :lim"
)

_SELECT_RECENT_RUNS_BY_AGENT = (
    "SELECT " + _RUN_COLUMNS + " FROM cron_job_history "
    "WHERE tenant_id = :tid AND agent_id = :aid AND run_at >= :since "
    "ORDER BY run_at DESC"
)

#: 收件箱（pending-inbox）跨员工面：启用中且最新一次执行失败的专家
#: 定时任务。T13d 收口后 expert 两表已 DROP，本查询从 cron 双表反推，
#: 替代原 ``expert_scheduled_tasks WHERE status='active' AND
#: last_status='failed'`` 直查（latest CTE 取每 job 最新一条 history，
#: 与 _SELECT_HISTORY_STATS 同款 DISTINCT ON 口径，禁 N+1）。
_SELECT_ACTIVE_FAILED_TASKS = (
    "WITH latest AS ( "
    "  SELECT DISTINCT ON (job_id) agent_id, job_id, run_at, status "
    "  FROM cron_job_history "
    "  WHERE tenant_id = :tid AND agent_id LIKE 'expert_%' "
    "  ORDER BY job_id, seq DESC "
    ") SELECT cj.agent_id, cj.job_id, CAST(cj.spec AS TEXT) AS spec, "
    "cj.enabled, cj.run_count, cj.created_at, cj.updated_at, "
    "l.run_at AS last_run_at, l.status AS last_status "
    "FROM cron_jobs cj "
    "JOIN latest l ON l.job_id = cj.job_id AND l.agent_id = cj.agent_id "
    "WHERE cj.tenant_id = :tid AND cj.agent_id LIKE 'expert_%' "
    "AND cj.enabled AND l.status <> 'success' "
    "ORDER BY l.run_at DESC NULLS LAST LIMIT :lim"
)

#: completed 判定：once 且历史中存在 success（对齐台账终态）
_NOT_COMPLETED = (
    "NOT (COALESCE(cj.spec->'schedule'->>'type', '') = 'once' "
    "AND EXISTS (SELECT 1 FROM cron_job_history h WHERE "
    "h.tenant_id = cj.tenant_id AND h.agent_id = cj.agent_id "
    "AND h.job_id = cj.job_id AND h.status = 'success'))"
)

_COUNT_ACTIVE_SQL = (
    "SELECT count(*) AS n FROM cron_jobs cj "
    "WHERE cj.tenant_id = :tid AND cj.agent_id = :aid AND "
    + _NOT_COMPLETED
)

_COUNT_ACTIVE_BATCH_SQL = (
    "SELECT cj.agent_id, count(*) AS n FROM cron_jobs cj "
    "WHERE cj.tenant_id = :tid AND cj.agent_id = ANY(:aids) AND "
    + _NOT_COMPLETED
    + " GROUP BY cj.agent_id"
)


# ---------------------------------------------------------------------------
# 纯映射函数（行 → 记录；无 IO，黄金用例直接测）
# ---------------------------------------------------------------------------


def _as_mapping(value: Any) -> Dict[str, Any]:
    """JSONB 取值归一：asyncpg/text() 可能回 dict 或 JSON 字符串."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except ValueError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def _as_bool(value: Any) -> bool:
    """布尔列归一（text() 结果可能为 str 'true'/'t'/'1'）."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("t", "true", "1", "yes", "on")
    return bool(value)


def _strip_name_prefix(raw: Any, fallback: str) -> str:
    """剥 UI 链路展示前缀还原原始名（meta 注解缺失时兑底）."""
    name = str(raw or "").strip()
    if name.startswith(_AGENT_NAME_PREFIX):
        name = name[len(_AGENT_NAME_PREFIX):].strip()
    return name or fallback


def _task_id_from_job_id(job_id: str) -> str:
    """权威 job id → 台账 task id（去 expert_task_ 前缀，原样兑底）."""
    if job_id.startswith(EXPERT_TASK_JOB_PREFIX):
        return job_id[len(EXPERT_TASK_JOB_PREFIX):]
    return job_id


def _expert_id_from_agent_id(agent_id: str) -> Optional[str]:
    """cron 归属键 → expert id；非员工平面返回 None."""
    if not agent_id.startswith(EXPERT_AGENT_PREFIX):
        return None
    return agent_id[len(EXPERT_AGENT_PREFIX):]


def run_status_from_cron(raw: Any) -> str:
    """history.status → 台账 run status 命名空间.

    台账观察者口径（scheduling.record_execution）：success 之外一律
    failed（含 skipped/cancelled），本函数保持同一映射。
    """
    return "succeeded" if str(raw or "") == "success" else "failed"


def run_from_history_row(row: Dict[str, Any]) -> Optional[TaskRunRecord]:
    """One cron_job_history row → TaskRunRecord（非员工平面 None）."""
    expert_id = _expert_id_from_agent_id(str(row.get("agent_id") or ""))
    if expert_id is None:
        return None
    job_id = str(row.get("job_id") or "")
    run_at = row.get("run_at")
    return TaskRunRecord(
        id=f"{job_id}:{row.get('seq')}",
        task_id=_task_id_from_job_id(job_id),
        expert_id=expert_id,
        scheduled_for=row.get("scheduled_for"),
        status=run_status_from_cron(row.get("status")),
        result_summary=str(row.get("result_summary") or ""),
        error=str(row.get("error") or ""),
        run_id=str(row.get("run_id") or ""),
        session_id=str(row.get("session_id") or ""),
        started_at=run_at,
        finished_at=run_at,
    )


def task_from_cron_row(
    row: Dict[str, Any],
    *,
    any_success: bool = False,
    last_run_at: Any = None,
    last_run_status: Any = None,
) -> Optional[ScheduledTaskRecord]:
    """One cron_jobs row → ScheduledTaskRecord（非员工平面 None）.

    ``any_success``/``last_*`` 来自 :class:`CronLedgerReader` 的一次
    history 统计查询（禁止逐行 N+1）。
    """
    from ..crons.models import CronJobSpec
    from .scheduling import (
        _origin_from_spec,
        _schedule_json_from_spec,
        _task_prompt_from_spec,
    )

    agent_id = str(row.get("agent_id") or "")
    expert_id = _expert_id_from_agent_id(agent_id)
    if expert_id is None:
        return None
    spec_raw = row.get("spec")
    try:
        spec = CronJobSpec.model_validate(_as_mapping(spec_raw))
    except Exception:  # noqa: BLE001 - 脏行不拖垮整个列表
        logger.warning(
            "cron ledger: skip malformed spec agent=%s job=%s",
            agent_id,
            row.get("job_id"),
        )
        return None
    job_id = str(row.get("job_id") or "")
    meta = _as_mapping(spec.meta)
    schedule_type, schedule_json = _schedule_json_from_spec(spec)
    enabled = _as_bool(row.get("enabled", True))
    status = TASK_STATUS_ACTIVE if enabled else TASK_STATUS_PAUSED
    if schedule_type == "once" and any_success:
        status = TASK_STATUS_COMPLETED
    owner_id = spec.dispatch.target.user_id if spec.dispatch else ""
    if not owner_id or owner_id == "cron":
        owner_id = ""
    timezone = spec.schedule.timezone or "Asia/Shanghai"
    return ScheduledTaskRecord(
        id=_task_id_from_job_id(job_id),
        expert_id=expert_id,
        name=str(meta.get("expert_task_name") or "")
        or _strip_name_prefix(spec.name, job_id),
        description=str(meta.get("expert_description") or ""),
        task_prompt=_task_prompt_from_spec(spec),
        schedule_type=schedule_type,
        schedule_json=schedule_json,
        timezone=timezone,
        status=status,
        cron_job_id=job_id,
        next_run_at=None,
        last_run_at=last_run_at,
        last_status=(
            run_status_from_cron(last_run_status)
            if last_run_at is not None
            else ""
        ),
        run_count=int(row.get("run_count") or 0),
        source=str(meta.get("origin_source") or "chat"),
        origin=_origin_from_spec(spec),
        owner_id=owner_id or None,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


# ---------------------------------------------------------------------------
# 读层
# ---------------------------------------------------------------------------


class CronLedgerReader:
    """Read-only reverse projection over the cron double-table plane."""

    async def get_task(self, task_id: str) -> Optional[ScheduledTaskRecord]:
        """One task by ledger id (UI prefixed id or raw chat/api job id)."""
        from ..enterprise import current_tenant_id

        primary = f"{EXPERT_TASK_JOB_PREFIX}{task_id}"
        async with _connect() as conn:
            rows = (
                await conn.execute(
                    text(_SELECT_TASKS_BY_JOB_IDS),
                    {
                        "tid": current_tenant_id(),
                        "jids": [primary, task_id],
                        "primary": primary,
                    },
                )
            ).mappings().all()
        if not rows:
            return None
        return await self._first_with_history(list(rows))

    async def list_tasks(
        self,
        expert_id: str,
    ) -> List[ScheduledTaskRecord]:
        """One expert's tasks (archived absent by construction)."""
        from ..enterprise import current_tenant_id

        agent_id = f"{EXPERT_AGENT_PREFIX}{expert_id}"
        async with _connect() as conn:
            rows = (
                await conn.execute(
                    text(_SELECT_TASKS_BY_AGENT),
                    {"tid": current_tenant_id(), "aid": agent_id},
                )
            ).mappings().all()
            stats = await self._history_stats(
                conn, current_tenant_id(), agent_id,
            )
        tasks: List[ScheduledTaskRecord] = []
        for row in rows:
            item = dict(row)
            hint = stats.get(str(item.get("job_id") or ""), {})
            task = task_from_cron_row(
                item,
                any_success=bool(hint.get("any_success")),
                last_run_at=hint.get("run_at"),
                last_run_status=hint.get("status"),
            )
            if task is not None:
                tasks.append(task)
        return tasks

    async def count_active_by_expert(self, expert_id: str) -> int:
        """active+paused 计数（completed 与已删除不计）."""
        from ..enterprise import current_tenant_id

        async with _connect() as conn:
            result = await conn.execute(
                text(_COUNT_ACTIVE_SQL),
                {
                    "tid": current_tenant_id(),
                    "aid": f"{EXPERT_AGENT_PREFIX}{expert_id}",
                },
            )
            return int(result.scalar() or 0)

    async def count_active_by_experts(
        self,
        expert_ids: List[str],
    ) -> Dict[str, int]:
        """详情页批量计数（一次 GROUP BY，禁 N+1）."""
        from ..enterprise import current_tenant_id

        if not expert_ids:
            return {}
        aids = [f"{EXPERT_AGENT_PREFIX}{eid}" for eid in expert_ids]
        async with _connect() as conn:
            rows = (
                await conn.execute(
                    text(_COUNT_ACTIVE_BATCH_SQL),
                    {"tid": current_tenant_id(), "aids": aids},
                )
            ).mappings().all()
        return {
            str(r["agent_id"])[len(EXPERT_AGENT_PREFIX):]: int(r["n"])
            for r in rows
        }

    async def list_runs(
        self,
        task_id: str,
        limit: int = 50,
    ) -> List[TaskRunRecord]:
        """Recent runs of one task (newest first, completed only)."""
        from ..enterprise import current_tenant_id

        async with _connect() as conn:
            rows = (
                await conn.execute(
                    text(_SELECT_RUNS_BY_JOB_IDS),
                    {
                        "tid": current_tenant_id(),
                        "jids": [
                            f"{EXPERT_TASK_JOB_PREFIX}{task_id}",
                            task_id,
                        ],
                        "lim": limit,
                    },
                )
            ).mappings().all()
        return [
            run
            for run in (run_from_history_row(dict(r)) for r in rows)
            if run is not None
        ]

    async def recent_runs(
        self,
        expert_id: str,
        since: Any,
    ) -> List[TaskRunRecord]:
        """Window runs of one expert (work-record timeline source)."""
        from ..enterprise import current_tenant_id

        async with _connect() as conn:
            rows = (
                await conn.execute(
                    text(_SELECT_RECENT_RUNS_BY_AGENT),
                    {
                        "tid": current_tenant_id(),
                        "aid": f"{EXPERT_AGENT_PREFIX}{expert_id}",
                        "since": since,
                    },
                )
            ).mappings().all()
        return [
            run
            for run in (run_from_history_row(dict(r)) for r in rows)
            if run is not None
        ]

    async def list_active_failed_tasks(
        self,
        limit: int = 20,
    ) -> List[ScheduledTaskRecord]:
        """Tenant-wide active expert tasks whose latest run failed.

        收件箱（pending-inbox）运维关注项数据源：跨全部专家扫 cron
        双表，取启用中（enabled）且最新一次 history 非 success 的任务
        （对齐收口前 ``expert_scheduled_tasks.status='active' AND
        last_status='failed'`` 语义）。T13d 收口后 expert 两表已 DROP，
        本方法是该视图的唯一读路径（一条批查，禁 N+1）。
        """
        from ..enterprise import current_tenant_id

        async with _connect() as conn:
            rows = (
                await conn.execute(
                    text(_SELECT_ACTIVE_FAILED_TASKS),
                    {"tid": current_tenant_id(), "lim": limit},
                )
            ).mappings().all()
        tasks: List[ScheduledTaskRecord] = []
        for row in rows:
            item = dict(row)
            # 最新一次失败 → 必非 completed（completed 需 once+success），
            # any_success 传 False 即得 active 态；last_* 由本行携带
            task = task_from_cron_row(
                item,
                any_success=False,
                last_run_at=item.get("last_run_at"),
                last_run_status=item.get("last_status"),
            )
            if task is not None:
                tasks.append(task)
        return tasks

    # -- internal ----------------------------------------------------------

    async def _history_stats(
        self,
        conn: Any,
        tenant_id: str,
        agent_id: str,
    ) -> Dict[str, Dict[str, Any]]:
        """One batched stats query per agent (no per-row N+1)."""
        rows = (
            await conn.execute(
                text(_SELECT_HISTORY_STATS),
                {"tid": tenant_id, "aid": agent_id},
            )
        ).mappings().all()
        return {
            str(r["job_id"]): {
                "any_success": bool(r["any_success"]),
                "run_at": r["run_at"],
                "status": r["status"],
            }
            for r in rows
        }

    async def _first_with_history(
        self,
        rows: List[Any],
    ) -> Optional[ScheduledTaskRecord]:
        """Map the first readable row of a single-task lookup."""
        from ..enterprise import current_tenant_id

        item = dict(rows[0])
        agent_id = str(item.get("agent_id") or "")
        async with _connect() as conn:
            stats = await self._history_stats(
                conn, current_tenant_id(), agent_id,
            )
        hint = stats.get(str(item.get("job_id") or ""), {})
        return task_from_cron_row(
            item,
            any_success=bool(hint.get("any_success")),
            last_run_at=hint.get("run_at"),
            last_run_status=hint.get("status"),
        )


def _connect() -> Any:
    """Enterprise engine connection context (single source of engine)."""
    from ..enterprise import require_enterprise_engine

    return require_enterprise_engine().connect()


_reader: Optional[CronLedgerReader] = None


def get_cron_ledger_reader() -> CronLedgerReader:
    """Process-wide singleton (stateless; engine shared per DSN)."""
    global _reader  # pylint: disable=global-statement
    if _reader is None:
        _reader = CronLedgerReader()
    return _reader


def reset_reader_for_tests() -> None:
    """Drop the cached singleton (test isolation only)."""
    global _reader  # pylint: disable=global-statement
    _reader = None


_json_backend_warned = False


def warn_if_json_backend(expert_id: str) -> None:
    """D1 前置：专家域 cron 平面必须 PG 权威，json 后端只警一次.

    收口后 cron 双表是专家定时任务的唯一读平面；json 后端下双表
    为空（列表/统计将全空），启动日志提醒运维切换 dual/pg。
    """
    global _json_backend_warned  # pylint: disable=global-statement
    if _json_backend_warned:
        return
    from ...db.write_gateway import resolve_storage_backend

    if resolve_storage_backend() not in ("dual", "pg"):
        _json_backend_warned = True
        logger.warning(
            "expert cron plane stays EMPTY under storage backend=json "
            "(expert=%s): set QWENPAW_STORAGE_BACKEND=dual|pg before the "
            "T13 ledger convergence; expert scheduling requires dual|pg",
            expert_id,
        )
