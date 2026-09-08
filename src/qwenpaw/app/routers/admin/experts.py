# -*- coding: utf-8 -*-
"""Admin expert management API: drafts, publish, archive (XianWork P3)."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from ...experts.models import (
    EXPERT_STATUS_PUBLISHED,
    ExpertCreateBody,
    ExpertRecord,
    ExpertUpdateBody,
    expert_agent_id,
)
from ...experts.preview import (
    preview_status,
    start_expert_preview,
    stop_expert_preview,
)
from ...experts.publish import archive_expert, publish_expert
from ...experts.store import get_expert_store
from ...rbac import PERM_ADMIN_EXPERTS, require_perm

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/experts",
    tags=["admin-experts"],
    dependencies=[Depends(require_perm(PERM_ADMIN_EXPERTS))],
)


def _manager(request: Request):
    return getattr(request.app.state, "multi_agent_manager", None)


@router.get("", response_model=List[ExpertRecord])
async def list_experts(status: Optional[str] = None) -> List[ExpertRecord]:
    """All experts (optionally filtered by status)."""
    return await get_expert_store().list_experts(status=status)


@router.post("", status_code=201, response_model=ExpertRecord)
async def create_expert(body: ExpertCreateBody) -> ExpertRecord:
    """Create a draft expert (nothing loads until publish)."""
    return await get_expert_store().create_expert(
        name=body.name,
        icon=body.icon,
        description=body.description,
        agent_spec=body.agent_spec,
        title=body.title,
        category=body.category,
        badge=body.badge,
        tags=body.tags,
        system_prompt=body.system_prompt,
        visibility=body.visibility,
        sample_tasks=body.sample_tasks,
        showcase=body.showcase,
    )


@router.get("/{expert_id}", response_model=ExpertRecord)
async def get_expert(expert_id: str) -> ExpertRecord:
    record = await get_expert_store().get_expert(expert_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Expert not found")
    # skills 由详情端点填充（非持久化列，见 ExpertRecord.skills 注释）
    record.skills = await get_expert_store().list_skills(expert_id)
    return record


@router.patch("/{expert_id}", response_model=ExpertRecord)
async def update_expert(
    expert_id: str,
    body: ExpertUpdateBody,
) -> ExpertRecord:
    """Edit draft metadata/spec (published experts need re-publish)."""
    record = await get_expert_store().update_expert(
        expert_id,
        name=body.name,
        icon=body.icon,
        description=body.description,
        agent_spec=body.agent_spec,
        title=body.title,
        category=body.category,
        badge=body.badge,
        tags=body.tags,
        system_prompt=body.system_prompt,
        visibility=body.visibility,
        sample_tasks=body.sample_tasks,
        showcase=body.showcase,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Expert not found")
    return record


@router.delete("/{expert_id}", status_code=204)
async def delete_expert(expert_id: str) -> None:
    """Delete a draft (published history is immutable).

    级联清理能力层数据（绑定/记忆），避免删除后残留悬挂挂载。
    """
    if not await get_expert_store().delete_expert(expert_id):
        raise HTTPException(
            status_code=400,
            detail="only draft experts can be deleted",
        )
    from ...experts.capability import get_capability_store
    from ...experts.memories import get_memory_store

    # 绑定与记忆跟 draft 一起物理清理（published 归档路径不清理）
    await get_capability_store().delete_expert_bindings(expert_id)
    await get_memory_store().clear_memories(expert_id)


@router.post("/{expert_id}/publish", response_model=ExpertRecord)
async def publish(
    expert_id: str,
    request: Request,
) -> ExpertRecord:
    """Materialize the expert as a live agent and snapshot it."""
    actor = getattr(request.state, "user", None) or "admin"
    try:
        return await publish_expert(
            expert_id,
            published_by=actor,
            manager=_manager(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{expert_id}/archive", response_model=ExpertRecord)
async def archive(expert_id: str, request: Request) -> ExpertRecord:
    """Unload the runtime agent and mark the expert archived."""
    record = await archive_expert(
        expert_id,
        manager=_manager(request),
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Expert not found")
    return record


@router.get("/{expert_id}/agent_id")
async def runtime_agent_id(expert_id: str) -> dict:
    """The runtime agent id for wiring X-Agent-Id / project bindings."""
    record = await get_expert_store().get_expert(expert_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Expert not found")
    return {
        "expert_id": expert_id,
        "agent_id": expert_agent_id(expert_id),
        "status": record.status,
        "published": record.status == EXPERT_STATUS_PUBLISHED,
    }


# ----------------------------------------------------------------------
# Draft preview (debug) instance: 与线上 expert_{id} 完全隔离的草稿运行时。
# 前端工作台调试开关经这三个接口启停；发布成功后 publish_expert 联动销毁。
# ----------------------------------------------------------------------


def _preview_http_error(exc: ValueError) -> HTTPException:
    """Map preview ValueError to 404 (missing) / 400 (state conflict)."""
    detail = str(exc)
    return HTTPException(
        status_code=404 if "not found" in detail else 400,
        detail=detail,
    )


@router.post("/{expert_id}/preview/start")
async def preview_start(expert_id: str, request: Request) -> dict:
    """Materialize the draft as an isolated debug agent and hot-load it."""
    try:
        return await start_expert_preview(
            expert_id,
            manager=_manager(request),
        )
    except ValueError as exc:
        raise _preview_http_error(exc) from exc


@router.post("/{expert_id}/preview/stop")
async def preview_stop(expert_id: str, request: Request) -> dict:
    """Unload the debug agent and remove its draft workspace."""
    try:
        return await stop_expert_preview(
            expert_id,
            manager=_manager(request),
        )
    except ValueError as exc:
        raise _preview_http_error(exc) from exc


@router.get("/{expert_id}/preview/status")
async def preview_state(expert_id: str) -> dict:
    """Debug instance state + whether the draft has unpublished changes."""
    try:
        return await preview_status(expert_id)
    except ValueError as exc:
        raise _preview_http_error(exc) from exc


# ----------------------------------------------------------------------
# Version history: published_experts 不可变快照链（只增）。
# 回滚 = 快照 spec 写回草稿，需再次发布才影响线上。
# ----------------------------------------------------------------------

#: 快照 spec 内嵌的运行时字段，写回草稿时剥离（属于物化产物而非源配置）。
_SPEC_RUNTIME_KEYS = {"id", "name", "description", "workspace_dir"}


@router.get("/{expert_id}/versions")
async def list_versions(expert_id: str) -> dict:
    """All published snapshots of one expert (newest first)."""
    store = get_expert_store()
    if await store.get_expert(expert_id) is None:
        raise HTTPException(status_code=404, detail="Expert not found")
    snapshots = await store.list_snapshots(expert_id)
    return {
        "versions": [
            {
                "version": s.version,
                "published_by": s.published_by,
                "published_at": (
                    s.published_at.isoformat() if s.published_at else None
                ),
            }
            for s in snapshots
        ]
    }


@router.post("/{expert_id}/versions/{version}/restore")
async def restore_version(expert_id: str, version: int) -> dict:
    """Restore one snapshot's spec into the draft (publish again to go live).

    快照只增不可变：恢复仅覆盖草稿 agent_spec（剥离运行时字段），
    线上与已发布版本均不受影响；工作台随后显示「有未发布变更」。
    """
    store = get_expert_store()
    snapshot = await store.get_snapshot(expert_id, version)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    draft_spec = {
        key: value
        for key, value in (snapshot.spec or {}).items()
        if key not in _SPEC_RUNTIME_KEYS
    }
    record = await store.update_expert(expert_id, agent_spec=draft_spec)
    if record is None:
        raise HTTPException(status_code=404, detail="Expert not found")
    return {
        "expert_id": expert_id,
        "restored_version": version,
        "agent_spec": draft_spec,
    }
