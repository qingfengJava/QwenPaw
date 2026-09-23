# -*- coding: utf-8 -*-
"""Project resource bindings (connectors / skills) for XianWork.

``project_bindings`` records which shared resources a project's AI may
use. The resource registries themselves stay console-managed; this plane
only owns the project ↔ resource relation.
"""
from __future__ import annotations

import json
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text

from ...enterprise import current_tenant_id, new_id, require_enterprise_engine
from ...projects.models import PROJECT_EDITOR
from ...projects.service import ProjectService, get_project_service
from .projects import _require_role, caller_username

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["xian-bindings"])

BINDING_KINDS = ("connector", "skill")


class BindingBody(BaseModel):
    kind: str
    ref_id: str
    enabled: bool = True
    config: dict = {}


def _row_to_view(row) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "kind": row.kind,
        "ref_id": row.ref_id,
        "enabled": bool(row.enabled),
        "config": row.config or {},
    }


@router.get("/{project_id}/bindings")
async def list_bindings(
    project_id: str,
    request: Request,
    service: ProjectService = Depends(get_project_service),
) -> List[dict]:
    await _require_role(service, request, project_id, "")
    engine = require_enterprise_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id, project_id, kind, ref_id, enabled, config "
                "FROM project_bindings WHERE tenant_id = :tid "
                "AND project_id = :pid ORDER BY kind, ref_id"
            ),
            {"tid": current_tenant_id(), "pid": project_id},
        )
        return [_row_to_view(r) for r in result]


@router.post("/{project_id}/bindings", status_code=201)
async def add_binding(
    project_id: str,
    body: BindingBody,
    request: Request,
    service: ProjectService = Depends(get_project_service),
) -> dict:
    await _require_role(service, request, project_id, PROJECT_EDITOR)
    if body.kind not in BINDING_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"kind must be one of {BINDING_KINDS}",
        )
    engine = require_enterprise_engine()
    bid = new_id("bind")
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "INSERT INTO project_bindings (tenant_id, id, project_id, "
                "kind, ref_id, enabled, config) VALUES (:tid, :id, :pid, "
                ":kind, :ref, :enabled, CAST(:config AS JSONB)) "
                "ON CONFLICT (tenant_id, project_id, kind, ref_id) "
                "DO UPDATE SET enabled = EXCLUDED.enabled, "
                "config = EXCLUDED.config, updated_at = now() "
                "RETURNING id, project_id, kind, ref_id, enabled, config"
            ),
            {
                "tid": current_tenant_id(),
                "id": bid,
                "pid": project_id,
                "kind": body.kind,
                "ref": body.ref_id,
                "enabled": body.enabled,
                "config": json.dumps(body.config),
            },
        )
        row = result.one()
    await service.record_feed(
        project_id,
        actor=caller_username(request),
        kind="binding_added",
        payload={"kind": body.kind, "ref_id": body.ref_id},
    )
    return _row_to_view(row)


@router.delete("/{project_id}/bindings/{binding_id}", status_code=204)
async def remove_binding(
    project_id: str,
    binding_id: str,
    request: Request,
    service: ProjectService = Depends(get_project_service),
):
    await _require_role(service, request, project_id, PROJECT_EDITOR)
    engine = require_enterprise_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "DELETE FROM project_bindings WHERE tenant_id = :tid "
                "AND project_id = :pid AND id = :bid RETURNING kind, ref_id"
            ),
            {
                "tid": current_tenant_id(),
                "pid": project_id,
                "bid": binding_id,
            },
        )
        row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Binding not found")
    await service.record_feed(
        project_id,
        actor=caller_username(request),
        kind="binding_removed",
        payload={"kind": row.kind, "ref_id": row.ref_id},
    )
