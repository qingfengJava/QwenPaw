# -*- coding: utf-8 -*-
"""Admin grant management API (M4-3): agent and model ACLs."""
from __future__ import annotations

import logging
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException

from ...rbac import PERM_ADMIN_ROLES, require_perm
from ...rbac.models import GrantRecord
from ...rbac.store import get_rbac_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/grants",
    tags=["admin-grants"],
    dependencies=[Depends(require_perm(PERM_ADMIN_ROLES))],
)


@router.get("/agents", response_model=Dict[str, GrantRecord])
async def list_agent_grants() -> Dict[str, GrantRecord]:
    """All agent ACLs (agents absent here are unrestricted)."""
    return get_rbac_store().list_agent_grants()


@router.put("/agents/{agent_id}", response_model=GrantRecord)
async def set_agent_grant(agent_id: str, body: GrantRecord) -> GrantRecord:
    """Create or replace the ACL for one agent."""
    if not get_rbac_store().set_agent_grant(agent_id, body):
        raise HTTPException(status_code=400, detail="invalid agent grant")
    return body


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent_grant(agent_id: str) -> None:
    """Remove the ACL (the agent becomes unrestricted again)."""
    if not get_rbac_store().delete_agent_grant(agent_id):
        raise HTTPException(status_code=404, detail="grant not found")


@router.get("/models", response_model=Dict[str, GrantRecord])
async def list_model_grants() -> Dict[str, GrantRecord]:
    """All model ACLs, keyed by ``provider:model`` (``*`` = wildcard)."""
    return get_rbac_store().list_model_grants()


@router.put("/models/{model_key:path}", response_model=GrantRecord)
async def set_model_grant(model_key: str, body: GrantRecord) -> GrantRecord:
    """Create or replace the ACL for one model (``provider:model``)."""
    if not get_rbac_store().set_model_grant(model_key, body):
        raise HTTPException(status_code=400, detail="invalid model grant")
    return body


@router.delete("/models/{model_key:path}", status_code=204)
async def delete_model_grant(model_key: str) -> None:
    """Remove the ACL for one model."""
    if not get_rbac_store().delete_model_grant(model_key):
        raise HTTPException(status_code=404, detail="grant not found")
