# -*- coding: utf-8 -*-
"""Admin RBAC role management API (M4)."""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...rbac import PERM_ADMIN_ROLES, require_perm
from ...rbac.models import RoleRecord
from ...rbac.store import get_rbac_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/roles",
    tags=["admin-roles"],
    dependencies=[Depends(require_perm(PERM_ADMIN_ROLES))],
)


class RoleBody(BaseModel):
    permissions: List[str] = Field(default_factory=list)
    description: str = ""


@router.get("", response_model=List[RoleRecord])
async def list_roles() -> List[RoleRecord]:
    """List all roles (built-in and custom)."""
    return get_rbac_store().list_roles()


@router.put("/{name}", response_model=RoleRecord)
async def upsert_role(name: str, body: RoleBody) -> RoleRecord:
    """Create or replace a custom role. Built-in roles are immutable."""
    record = get_rbac_store().upsert_role(
        name,
        body.permissions,
        description=body.description,
    )
    if record is None:
        raise HTTPException(
            status_code=400,
            detail="invalid name or attempt to modify a built-in role",
        )
    return record


@router.delete("/{name}", status_code=204)
async def delete_role(name: str) -> None:
    """Delete a custom role (also strips it from all user grants)."""
    if not get_rbac_store().delete_role(name):
        raise HTTPException(
            status_code=404,
            detail="role not found or built-in",
        )
