# -*- coding: utf-8 -*-
"""Admin capability-plane API for digital employees (20260830 能力层).

承载 StaffDeck 式数字员工能力的管理面端点（设计文档
docs/design/2026-08-30-digital-employee-capability-layer.md §六）：

- 工作记录聚合（只读）        GET  /experts/{id}/work-record
- 能力挂载（sop/kb/tool）     GET/PUT /experts/{id}/resources
- 分桶记忆                    GET/POST/PATCH/DELETE /experts/{id}/memories
- 员工定时任务（投影+权威）   CRUD /experts/{id}/scheduled-tasks (+pause/resume/run-now/runs)
- 消息反馈                    POST /experts/{id}/feedback、GET feedback-summary
- SOP 资产（版本链）          CRUD /sops (+publish/rollback/versions/archive)
- 演进提案（人工审批闭环）    CRUD /evolution-proposals (+submit/review/publish/rollback)

路由前缀刻意避开 ``/experts/{expert_id}`` 两段式集合（该文件先注册，
两段路径会被详情端点吞掉），SOP 与提案挂 admin 根路径。
鉴权：整体挂 ``require_perm(PERM_ADMIN_EXPERTS)``。
@author qingfeng
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...experts.apikeys import get_api_key_store
from ...experts.capability import get_capability_store
from ...experts.feedback import (
    get_evolution_store,
    get_feedback_store,
)
from ...experts.memories import (
    get_memory_store,
    materialize_expert_memory,
)
from ...experts.models import (
    EXPERT_STATUS_PUBLISHED,
    RESOURCE_TYPES,
    ResourceBinding,
    SopCreateBody,
    SopRecord,
    SopUpdateBody,
    ScheduledTaskCreateBody,
    ScheduledTaskRecord,
    ScheduledTaskUpdateBody,
    WorkRecord,
    expert_agent_id,
)
from ...experts.publish import publish_expert
from ...experts.scheduling import SchedulingService, get_scheduling_store
from ...experts.sops import get_sop_store
from ...experts.store import get_expert_store
from ...experts.worklog import get_worklog_service
from ...rbac import PERM_ADMIN_EXPERTS, require_perm

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["admin-expert-capability"],
    dependencies=[Depends(require_perm(PERM_ADMIN_EXPERTS))],
)


def _manager(request: Request):
    """MultiAgentManager from app state (publish / cron authority)."""
    return getattr(request.app.state, "multi_agent_manager", None)


def _actor(request: Request) -> str:
    """Current username (audit trail)."""
    return getattr(request.state, "user", None) or "admin"


async def _require_expert(expert_id: str):
    """Load one expert or 404 (shared guard for scoped endpoints)."""
    record = await get_expert_store().get_expert(expert_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Expert not found")
    return record


async def _scheduling_service(
    request: Request,
    expert_id: str,
) -> SchedulingService:
    """Resolve the expert's CronManager (schedule authority).

    专家未发布（无 workspace / CronManager）时报 400——定时任务只对
    已上岗（published）的数字员工开放。
    """
    manager = _manager(request)
    if manager is None:
        raise HTTPException(status_code=500, detail="Agent runtime not ready")
    try:
        workspace = await manager.get_agent(expert_agent_id(expert_id))
        cron_manager = workspace.cron_manager
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(
            status_code=400,
            detail=f"expert runtime unavailable: {exc}",
        ) from exc
    if cron_manager is None:
        raise HTTPException(
            status_code=400,
            detail="CronManager not ready (expert not published?)",
        )
    return SchedulingService(cron_manager)


# ---------------------------------------------------------------------------
# 批量计数（列表页卡片条，五步范式：每类一次 GROUP BY，无 N+1）
# ---------------------------------------------------------------------------


@router.get("/experts-capability-counts")
async def capability_counts(
    expert_ids: str = "",
) -> Dict[str, Any]:
    """Per-expert capability counts for card grids.

    ``expert_ids`` 逗号分隔；四类各一条 GROUP BY 批查后内存组装。
    """
    from ...enterprise import current_tenant_id, require_enterprise_engine
    from sqlalchemy import text

    ids = [x for x in (expert_ids or "").split(",") if x.strip()]
    if not ids:
        return {"counts": {}}
    engine = require_enterprise_engine()
    tid = current_tenant_id()
    result: Dict[str, Dict[str, int]] = {
        eid: {
            "resources": 0,
            "skills": 0,
            "sops": 0,
            "scheduled_tasks": 0,
        }
        for eid in ids
    }
    async with engine.connect() as conn:
        resource_rows = await conn.execute(
            text(
                "SELECT expert_id, count(*) AS n FROM "
                "expert_resource_bindings WHERE tenant_id = :tid AND "
                "expert_id = ANY(:ids) GROUP BY expert_id"
            ),
            {"tid": tid, "ids": ids},
        )
        for row in resource_rows:
            result[row.expert_id]["resources"] = int(row.n)

        sop_rows = await conn.execute(
            text(
                "SELECT expert_id, count(*) AS n FROM "
                "expert_resource_bindings WHERE tenant_id = :tid AND "
                "expert_id = ANY(:ids) AND resource_type = 'sop' "
                "GROUP BY expert_id"
            ),
            {"tid": tid, "ids": ids},
        )
        for row in sop_rows:
            result[row.expert_id]["sops"] = int(row.n)

        skill_rows = await conn.execute(
            text(
                "SELECT expert_id, count(*) AS n FROM expert_skills "
                "WHERE tenant_id = :tid AND expert_id = ANY(:ids) "
                "AND enabled GROUP BY expert_id"
            ),
            {"tid": tid, "ids": ids},
        )
        for row in skill_rows:
            result[row.expert_id]["skills"] = int(row.n)

        task_rows = await conn.execute(
            text(
                "SELECT expert_id, count(*) AS n FROM "
                "expert_scheduled_tasks WHERE tenant_id = :tid AND "
                "expert_id = ANY(:ids) AND status IN "
                "('active', 'paused') GROUP BY expert_id"
            ),
            {"tid": tid, "ids": ids},
        )
        for row in task_rows:
            result[row.expert_id]["scheduled_tasks"] = int(row.n)
    return {"counts": result}


# ---------------------------------------------------------------------------
# 员工级 API Key（P4 /api/open 凭证面：签发/列表/吊销）
# ---------------------------------------------------------------------------


@router.get("/experts/{expert_id}/api-keys")
async def list_api_keys(expert_id: str) -> Dict[str, Any]:
    """One expert's API keys (hash 永不回传；仅前缀辨识)."""
    await _require_expert(expert_id)
    keys = await get_api_key_store().list_keys(expert_id)
    return {"keys": keys}


class ApiKeyIssueBody(BaseModel):
    """Issue payload（明文只在本次响应返回一次）."""

    name: str = ""
    expires_at: Optional[str] = None


@router.post("/experts/{expert_id}/api-keys", status_code=201)
async def issue_api_key(
    expert_id: str,
    body: ApiKeyIssueBody,
    request: Request,
) -> Dict[str, Any]:
    """Issue one key（明文仅本次返回，落库只存哈希）."""
    await _require_expert(expert_id)
    expires_at = datetime.fromisoformat(body.expires_at) if body.expires_at else None
    return await get_api_key_store().issue_key(
        expert_id,
        name=body.name,
        created_by=_actor(request),
        expires_at=expires_at,
    )


@router.delete("/experts/{expert_id}/api-keys/{key_id}", status_code=204)
async def revoke_api_key(expert_id: str, key_id: str) -> None:
    """Soft-revoke（即时生效，幂等）."""
    if not await get_api_key_store().revoke_key(expert_id, key_id):
        raise HTTPException(status_code=404, detail="Key not found")


# ---------------------------------------------------------------------------
# 渠道多员工意图分发（P5 内核：LLM 分类 + 粘性保护 + 低置信降级）
# ---------------------------------------------------------------------------


class DispatchIntentBody(BaseModel):
    """Dispatch request（渠道网关/上游调用面）."""

    text: str
    candidate_expert_ids: List[str]
    current_expert_id: str = ""
    sticky: bool = False


@router.post("/experts/dispatch-intent")
async def dispatch_intent(body: DispatchIntentBody) -> Dict[str, Any]:
    """Classify one inbound message to the best-fit expert.

    返回 ``{"dispatched": bool, "expert_id", "confidence", "reason"}``；
    低置信/降级场景 dispatched=False（调用方保持默认员工路由）。
    """
    from ...experts.intent_dispatch import (
        DispatchCandidate,
        dispatch_expert_intent,
    )

    store = get_expert_store()
    candidates: List[DispatchCandidate] = []
    for expert_id in body.candidate_expert_ids:
        record = await store.get_expert(expert_id)
        if record is None or record.status != EXPERT_STATUS_PUBLISHED:
            continue
        candidates.append(
            DispatchCandidate(
                expert_id=record.id,
                name=record.name,
                title=record.title,
                description=record.description,
            ),
        )
    choice = await dispatch_expert_intent(
        body.text,
        candidates,
        current_expert_id=body.current_expert_id,
        sticky=body.sticky,
    )
    if choice is None:
        return {"dispatched": False}
    return {"dispatched": True, **choice}


# ---------------------------------------------------------------------------
# 工作记录（只读聚合）
# ---------------------------------------------------------------------------


@router.get("/experts/{expert_id}/work-record", response_model=WorkRecord)
async def work_record(expert_id: str, days: int = 30) -> WorkRecord:
    """Aggregated work record (tasks / feedback / timeline, D6)."""
    await _require_expert(expert_id)
    return await get_worklog_service().build_work_record(
        expert_id,
        days=days,
    )


# ---------------------------------------------------------------------------
# 能力挂载（sop / knowledge_base / tool）
# ---------------------------------------------------------------------------


class ResourceBindingsPutBody(BaseModel):
    """Whole-list replacement payload (per-expert, all types)."""

    bindings: List[ResourceBinding] = Field(default_factory=list)


@router.get("/experts/{expert_id}/resources")
async def list_resources(expert_id: str) -> Dict[str, Any]:
    """One expert's bindings grouped by resource type."""
    await _require_expert(expert_id)
    bindings = await get_capability_store().list_bindings(expert_id)
    grouped: Dict[str, List[Dict[str, Any]]] = {
        resource_type: [] for resource_type in RESOURCE_TYPES
    }
    for binding in bindings:
        grouped.setdefault(binding.resource_type, []).append(
            binding.model_dump(mode="json"),
        )
    return {"bindings": grouped}


@router.put("/experts/{expert_id}/resources")
async def replace_resources(
    expert_id: str,
    body: ResourceBindingsPutBody,
    request: Request,
) -> Dict[str, Any]:
    """Replace all bindings (PUT empty list = clear; idempotent).

    metadata.name 快照在此填充：sop 取 SopStore 现名，kb/tool 取调用方
    传入的 name（防资源本体删除后列表悬挂）。
    """
    await _require_expert(expert_id)
    sop_store = get_sop_store()
    enriched: List[ResourceBinding] = []
    for binding in body.bindings:
        metadata = dict(binding.metadata or {})
        if binding.resource_type == "sop" and not metadata.get("name"):
            sop = await sop_store.get_sop(binding.resource_id)
            if sop is not None:
                metadata["name"] = sop.name
        metadata.setdefault("mounted_at", None)
        enriched.append(
            ResourceBinding(
                expert_id=expert_id,
                resource_type=binding.resource_type,
                resource_id=binding.resource_id,
                enabled=binding.enabled,
                seq=binding.seq,
                metadata=metadata,
            ),
        )
    saved = await get_capability_store().replace_bindings(
        expert_id,
        enriched,
    )
    # 发布边界收紧（20260908）：绑定变更只落草稿域。若调试实例正在
    # 运行，仅重写草稿 PROFILE.md（调试会话即时感知）；线上 PROFILE.md
    # 由发布流程物化，后台调试期的绑定变更不再泄漏到线上。
    try:
        from ...experts.preview import refresh_expert_preview_profile

        await refresh_expert_preview_profile(
            expert_id,
            manager=_manager(request),
        )
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "expert %s binding changed but preview profile refresh "
            "failed (next preview start / publish will refresh)",
            expert_id,
            exc_info=True,
        )
    return {
        "bindings": [b.model_dump(mode="json") for b in saved],
    }


# ---------------------------------------------------------------------------
# 分桶记忆
# ---------------------------------------------------------------------------


@router.get("/experts/{expert_id}/memories")
async def list_memories(
    expert_id: str,
    user_id: str = "",
    kind: str = "",
) -> Dict[str, Any]:
    """One expert's bucketed memories (optionally scoped)."""
    await _require_expert(expert_id)
    records = await get_memory_store().list_memories(
        expert_id,
        user_id=user_id,
        kind=kind,
    )
    return {"memories": [m.model_dump(mode="json") for m in records]}


@router.post("/experts/{expert_id}/memories", status_code=201)
async def upsert_memory(expert_id: str, body: dict) -> Dict[str, Any]:
    """Create/overwrite one memory (dedup_key = idempotent anchor)."""
    await _require_expert(expert_id)
    store = get_memory_store()
    record = await store.upsert_memory(
        expert_id,
        user_id=str(body.get("user_id") or ""),
        kind=str(body.get("kind") or "fact"),
        content=str(body.get("content") or ""),
        importance=float(body.get("importance") or 0.5),
        dedup_key=str(body.get("dedup_key") or ""),
        metadata=body.get("metadata") or {},
    )
    # 记忆变更即重建物化文件（best-effort，未发布专家静默跳过）
    await materialize_expert_memory(expert_id)
    return record.model_dump(mode="json")


@router.patch("/experts/{expert_id}/memories/{memory_id}")
async def patch_memory(
    expert_id: str,
    memory_id: str,
    body: dict,
) -> Dict[str, Any]:
    """Direct fix of one memory (content / importance / kind)."""
    existing = await get_memory_store().get_memory(expert_id, memory_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    store = get_memory_store()
    record = await store.upsert_memory(
        expert_id,
        user_id=existing.user_id,
        kind=str(body.get("kind") or existing.kind),
        content=str(body.get("content") or existing.content),
        importance=float(
            (
                body.get("importance")
                if body.get("importance") is not None
                else existing.importance
            ),
        ),
        dedup_key=existing.dedup_key,
        metadata=body.get("metadata") or existing.metadata,
        memory_id=memory_id,
    )
    await materialize_expert_memory(expert_id)
    return record.model_dump(mode="json")


@router.delete("/experts/{expert_id}/memories/{memory_id}", status_code=204)
async def delete_memory(expert_id: str, memory_id: str) -> None:
    """物理删除=记忆修正语义（认知可被人工纠偏）。"""
    if not await get_memory_store().delete_memory(expert_id, memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    await materialize_expert_memory(expert_id)


@router.delete("/experts/{expert_id}/memories", status_code=204)
async def clear_memories(expert_id: str, user_id: str = "") -> None:
    """Clear one expert's memories (optionally per user)."""
    await get_memory_store().clear_memories(expert_id, user_id=user_id)
    await materialize_expert_memory(expert_id)


# ---------------------------------------------------------------------------
# 员工定时任务（投影 + CronManager 权威）
# ---------------------------------------------------------------------------


@router.get("/experts/{expert_id}/scheduled-tasks")
async def list_scheduled_tasks(expert_id: str) -> Dict[str, Any]:
    """One expert's scheduled tasks (archived hidden)."""
    await _require_expert(expert_id)
    tasks = await get_scheduling_store().list_tasks(expert_id)
    return {"tasks": [t.model_dump(mode="json") for t in tasks]}


@router.post("/experts/{expert_id}/scheduled-tasks", status_code=201)
async def create_scheduled_task(
    expert_id: str,
    body: ScheduledTaskCreateBody,
    request: Request,
) -> ScheduledTaskRecord:
    """Create + register (projection row first, authority second).

    注册失败回滚投影行（不留孤儿 active 台账，service 层保证）。
    """
    await _require_expert(expert_id)
    store = get_scheduling_store()
    task = await store.create_task(
        expert_id=expert_id,
        name=body.name,
        task_prompt=body.task_prompt,
        schedule_type=body.schedule_type,
        schedule_json=body.schedule_json,
        timezone=body.timezone,
        description=body.description,
        owner_id=_actor(request),
    )
    service = await _scheduling_service(request, expert_id)
    try:
        return await service.create_task(task)
    except HTTPException:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/experts/{expert_id}/scheduled-tasks/{task_id}")
async def update_scheduled_task(
    expert_id: str,
    task_id: str,
    body: ScheduledTaskUpdateBody,
    request: Request,
) -> ScheduledTaskRecord:
    """Update fields + replace the authority job (None=不修改)."""
    store = get_scheduling_store()
    task = await store.get_task(task_id)
    if task is None or task.expert_id != expert_id:
        raise HTTPException(status_code=404, detail="Task not found")
    updated = await store.update_task(
        task_id,
        name=body.name,
        description=body.description,
        task_prompt=body.task_prompt,
        schedule_json=body.schedule_json,
        timezone=body.timezone,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Task not found")
    service = await _scheduling_service(request, expert_id)
    try:
        return await service.update_task(updated)
    except HTTPException:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/experts/{expert_id}/scheduled-tasks/{task_id}", status_code=204)
async def delete_scheduled_task(
    expert_id: str,
    task_id: str,
    request: Request,
) -> None:
    """Authority job first, projection archived second."""
    task = await get_scheduling_store().get_task(task_id)
    if task is None or task.expert_id != expert_id:
        raise HTTPException(status_code=404, detail="Task not found")
    service = await _scheduling_service(request, expert_id)
    await service.delete_task(task_id)


def _task_action_guard(task: Optional[ScheduledTaskRecord], expert_id: str):
    """Shared 404 guard for task sub-actions."""
    if task is None or task.expert_id != expert_id:
        raise HTTPException(status_code=404, detail="Task not found")


@router.post("/experts/{expert_id}/scheduled-tasks/{task_id}/pause")
async def pause_scheduled_task(
    expert_id: str,
    task_id: str,
    request: Request,
) -> ScheduledTaskRecord:
    """Pause both sides (authority + projection)."""
    task = await get_scheduling_store().get_task(task_id)
    _task_action_guard(task, expert_id)
    service = await _scheduling_service(request, expert_id)
    return await service.pause_task(task_id)


@router.post("/experts/{expert_id}/scheduled-tasks/{task_id}/resume")
async def resume_scheduled_task(
    expert_id: str,
    task_id: str,
    request: Request,
) -> ScheduledTaskRecord:
    """Resume both sides (authority + projection)."""
    task = await get_scheduling_store().get_task(task_id)
    _task_action_guard(task, expert_id)
    service = await _scheduling_service(request, expert_id)
    return await service.resume_task(task_id)


@router.post("/experts/{expert_id}/scheduled-tasks/{task_id}/run-now")
async def run_scheduled_task_now(
    expert_id: str,
    task_id: str,
    request: Request,
) -> Dict[str, Any]:
    """Manual trigger (fire-and-forget; observer writes the record)."""
    task = await get_scheduling_store().get_task(task_id)
    _task_action_guard(task, expert_id)
    service = await _scheduling_service(request, expert_id)
    await service.run_now(task_id)
    return {"task_id": task_id, "triggered": True}


@router.get("/experts/{expert_id}/scheduled-tasks/{task_id}/runs")
async def list_task_runs(
    expert_id: str,
    task_id: str,
) -> Dict[str, Any]:
    """Execution records of one task (newest first)."""
    task = await get_scheduling_store().get_task(task_id)
    _task_action_guard(task, expert_id)
    runs = await get_scheduling_store().list_runs(task_id)
    return {"runs": [r.model_dump(mode="json") for r in runs]}


# ---------------------------------------------------------------------------
# 消息反馈（采集 + 窗口汇总）
# ---------------------------------------------------------------------------


@router.post("/experts/{expert_id}/feedback")
async def rate_message(
    expert_id: str,
    request: Request,
    body: dict,
) -> Dict[str, Any]:
    """Upsert one message rating (repeated submit = overwrite)."""
    await _require_expert(expert_id)
    rating = str(body.get("rating") or "")
    if rating not in ("up", "down"):
        raise HTTPException(status_code=400, detail="rating must be up/down")
    if not str(body.get("message_id") or "").strip():
        raise HTTPException(status_code=400, detail="message_id required")
    result = await get_feedback_store().rate(
        message_id=str(body["message_id"]),
        user_id=str(body.get("user_id") or _actor(request)),
        rating=rating,
        session_id=str(body.get("session_id") or ""),
        expert_id=expert_id,
        comment=str(body.get("comment") or ""),
    )
    # 差评触发专家自省归因（fire-and-forget，自动起草演进提案）
    from ...experts.feedback import maybe_schedule_attribution

    maybe_schedule_attribution(expert_id, rating)
    return result


@router.get("/experts/{expert_id}/feedback-summary")
async def feedback_summary(
    expert_id: str,
    days: int = 30,
) -> Dict[str, Any]:
    """Windowed rating summary + recent samples (详情页反馈区)."""
    await _require_expert(expert_id)
    days = max(1, min(days, 90))
    summary = await get_feedback_store().summary(expert_id, days=days)
    summary["recent"] = await get_feedback_store().recent_for_expert(
        expert_id,
        days=days,
    )
    return summary


# ---------------------------------------------------------------------------
# SOP 资产（版本链）
# ---------------------------------------------------------------------------


@router.get("/sops", response_model=List[SopRecord])
async def list_sops(status: str = "", q: str = "") -> List[SopRecord]:
    """SOP assets (light projection, newest first)."""
    return await get_sop_store().list_sops(status=status, q=q)


@router.post("/sops", status_code=201, response_model=SopRecord)
async def create_sop(body: SopCreateBody, request: Request) -> SopRecord:
    """Create a draft SOP (publish snapshots it)."""
    return await get_sop_store().create_sop(
        name=body.name,
        description=body.description,
        business_domain=body.business_domain,
        goal=body.goal,
        nodes=body.nodes,
        edges=body.edges,
        slots=body.slots,
        owner_id=_actor(request),
    )


@router.get("/sops/{sop_id}", response_model=SopRecord)
async def get_sop(sop_id: str) -> SopRecord:
    sop = await get_sop_store().get_sop(sop_id)
    if sop is None:
        raise HTTPException(status_code=404, detail="SOP not found")
    return sop


@router.patch("/sops/{sop_id}", response_model=SopRecord)
async def update_sop(sop_id: str, body: SopUpdateBody) -> SopRecord:
    """Draft-only field update (published SOPs mutate via versions)."""
    try:
        sop = await get_sop_store().update_sop(
            sop_id,
            name=body.name,
            description=body.description,
            business_domain=body.business_domain,
            goal=body.goal,
            nodes=body.nodes,
            edges=body.edges,
            slots=body.slots,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if sop is None:
        raise HTTPException(status_code=404, detail="SOP not found")
    return sop


@router.delete("/sops/{sop_id}", status_code=204)
async def delete_sop(sop_id: str) -> None:
    """Drafts only (published history is auditable → archive instead)."""
    if not await get_sop_store().delete_sop(sop_id):
        raise HTTPException(
            status_code=400,
            detail="only draft SOPs can be deleted",
        )


@router.post("/sops/{sop_id}/publish", response_model=SopRecord)
async def publish_sop(sop_id: str, request: Request) -> SopRecord:
    """Publish: version+1 + immutable snapshot."""
    try:
        return await get_sop_store().publish_sop(
            sop_id,
            published_by=_actor(request),
        )
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class SopRollbackBody(BaseModel):
    """Rollback target version."""

    to_version: int


@router.post("/sops/{sop_id}/rollback", response_model=SopRecord)
async def rollback_sop(
    sop_id: str,
    body: SopRollbackBody,
    request: Request,
) -> SopRecord:
    """Restore a historical snapshot as a NEW version (audit-first)."""
    sop = await get_sop_store().rollback_sop(
        sop_id,
        to_version=body.to_version,
        published_by=_actor(request),
    )
    if sop is None:
        raise HTTPException(
            status_code=404,
            detail="SOP or target version not found",
        )
    return sop


@router.get("/sops/{sop_id}/versions")
async def list_sop_versions(sop_id: str) -> Dict[str, Any]:
    """Immutable version history (newest first)."""
    versions = await get_sop_store().list_versions(sop_id)
    return {"versions": [v.model_dump(mode="json") for v in versions]}


@router.post("/sops/{sop_id}/archive", response_model=SopRecord)
async def archive_sop(sop_id: str) -> SopRecord:
    """Archive (unbind建议由调用方先清理绑定；历史保留可审计)."""
    sop = await get_sop_store().archive_sop(sop_id)
    if sop is None:
        raise HTTPException(status_code=404, detail="SOP not found")
    return sop


# ---------------------------------------------------------------------------
# 演进提案（人工审批闭环）
# ---------------------------------------------------------------------------


@router.get("/evolution-proposals")
async def list_proposals(
    expert_id: str = "",
    status: str = "",
) -> Dict[str, Any]:
    """Proposals (filters optional, newest first)."""
    proposals = await get_evolution_store().list_proposals(
        expert_id=expert_id,
        status=status,
    )
    return {"proposals": [p.model_dump(mode="json") for p in proposals]}


@router.post("/evolution-proposals", status_code=201)
async def create_proposal(request: Request, body: dict) -> Dict[str, Any]:
    """Create a draft proposal (feedback evidence / manual)."""
    expert_id = str(body.get("expert_id") or "")
    if not expert_id or not str(body.get("title") or "").strip():
        raise HTTPException(status_code=400, detail="expert_id/title required")
    await _require_expert(expert_id)
    proposal = await get_evolution_store().create_proposal(
        expert_id=expert_id,
        title=str(body["title"]),
        trigger_type=str(body.get("trigger_type") or "manual"),
        risk_level=str(body.get("risk_level") or "low"),
        hypothesis=str(body.get("hypothesis") or ""),
        evidence=body.get("evidence") or [],
        candidate=body.get("candidate") or {},
    )
    return proposal.model_dump(mode="json")


@router.post("/evolution-proposals/{proposal_id}/submit")
async def submit_proposal(proposal_id: str) -> Dict[str, Any]:
    """draft → ready_for_review."""
    try:
        proposal = await get_evolution_store().submit_for_review(proposal_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    assert proposal is not None
    return proposal.model_dump(mode="json")


@router.post("/evolution-proposals/{proposal_id}/review")
async def review_proposal(
    proposal_id: str,
    body: dict,
    request: Request,
) -> Dict[str, Any]:
    """ready_for_review → approved | rejected (human gate)."""
    try:
        proposal = await get_evolution_store().review(
            proposal_id,
            action=str(body.get("action") or ""),
            reviewer=_actor(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    assert proposal is not None
    return proposal.model_dump(mode="json")


async def _apply_candidate(
    request: Request,
    proposal: dict,
) -> None:
    """Apply an approved proposal's candidate via the authority modules.

    支持的 target（P2 完整版）：
    - system_prompt：写 experts.system_prompt 并重发布（重新物化
      PROFILE.md，保证已上线员工同步生效）；
    - sop：经 ``SopStore.publish_new_version`` 进入版本链（不改历史）；
    - none：仅证据草稿（人工跟进），无可应用动作；
    - previous_value / previous_nodes 随 candidate 留存，供 rollback 恢复。
    """
    candidate = proposal.get("candidate") or {}
    target = candidate.get("target")
    expert_id = proposal["expert_id"]
    if target == "system_prompt":
        store = get_expert_store()
        record = await store.update_expert(
            expert_id,
            system_prompt=str(candidate.get("new_value") or ""),
        )
        if record is None:
            raise ValueError(f"expert {expert_id} not found")
        # 已发布员工重发布（重新物化 PROFILE.md + 热重载）
        from ...experts.models import EXPERT_STATUS_PUBLISHED

        if record.status == EXPERT_STATUS_PUBLISHED:
            await publish_expert(
                expert_id,
                published_by=_actor(request),
                manager=_manager(request),
            )
        return
    if target == "sop":
        from ...experts.sops import get_sop_store

        new_nodes = candidate.get("new_nodes")
        if (
            not isinstance(new_nodes, list)
            or not str(
                candidate.get("sop_id") or "",
            ).strip()
        ):
            raise ValueError("sop candidate requires sop_id/new_nodes")
        updated = await get_sop_store().publish_new_version(
            str(candidate["sop_id"]),
            nodes=new_nodes,
            change_note=f"evolution proposal {proposal['id']}",
            published_by=_actor(request),
        )
        if updated is None:
            raise ValueError(
                f"SOP {candidate.get('sop_id')} not found or archived",
            )
        return
    if target == "none":
        # 仅证据草稿：无可应用动作（人工跟进后走 reject/归档语义）
        return
    raise ValueError(f"unsupported candidate target: {target}")


@router.post("/evolution-proposals/{proposal_id}/publish")
async def publish_proposal(
    proposal_id: str,
    request: Request,
) -> Dict[str, Any]:
    """approved → apply candidate → 记差评基线 → published（失败停 approved）。"""
    store = get_evolution_store()
    proposal = await store.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    payload = proposal.model_dump(mode="json")
    try:
        await _apply_candidate(request, payload)
        # 发布即记录差评基线（自动回滚监控的判定锚点，P2）
        from ...experts.feedback import attach_publish_baseline

        await attach_publish_baseline(store, proposal_id)
        await store.mark_published(proposal_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return (await store.get_proposal(proposal_id)).model_dump(mode="json")


@router.post("/evolution-proposals/{proposal_id}/rollback")
async def rollback_proposal(
    proposal_id: str,
    request: Request,
) -> Dict[str, Any]:
    """published → restore previous_value → rolled_back（留痕）."""
    store = get_evolution_store()
    proposal = await store.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    candidate = proposal.candidate or {}
    if candidate.get("target") == "system_prompt":
        expert_id = proposal.expert_id
        record = await get_expert_store().update_expert(
            expert_id,
            system_prompt=str(candidate.get("previous_value") or ""),
        )
        if record is None:
            raise HTTPException(status_code=404, detail="Expert not found")
        from ...experts.models import EXPERT_STATUS_PUBLISHED

        if record.status == EXPERT_STATUS_PUBLISHED:
            await publish_expert(
                expert_id,
                published_by=_actor(request),
                manager=_manager(request),
            )
    try:
        await store.mark_rolled_back(proposal_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return (await store.get_proposal(proposal_id)).model_dump(mode="json")
