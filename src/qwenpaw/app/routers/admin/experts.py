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
    )


@router.get("/{expert_id}", response_model=ExpertRecord)
async def get_expert(expert_id: str) -> ExpertRecord:
    record = await get_expert_store().get_expert(expert_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Expert not found")
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
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Expert not found")
    return record


@router.delete("/{expert_id}", status_code=204)
async def delete_expert(expert_id: str) -> None:
    """Delete a draft (published history is immutable)."""
    if not await get_expert_store().delete_expert(expert_id):
        raise HTTPException(
            status_code=400,
            detail="only draft experts can be deleted",
        )


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
