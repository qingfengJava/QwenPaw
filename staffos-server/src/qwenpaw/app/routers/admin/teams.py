# -*- coding: utf-8 -*-
"""Admin team management API (M4)."""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...rbac import PERM_ADMIN_USERS, require_perm
from ...rbac.models import TeamRecord
from ...rbac.store import get_rbac_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/teams",
    tags=["admin-teams"],
    dependencies=[Depends(require_perm(PERM_ADMIN_USERS))],
)


class TeamBody(BaseModel):
    members: List[str] = Field(default_factory=list)
    description: str = ""


@router.get("", response_model=List[TeamRecord])
async def list_teams() -> List[TeamRecord]:
    """List all teams."""
    return get_rbac_store().list_teams()


@router.put("/{name}", response_model=TeamRecord)
async def upsert_team(name: str, body: TeamBody) -> TeamRecord:
    """Create or replace a team roster."""
    record = get_rbac_store().upsert_team(
        name,
        body.members,
        description=body.description,
    )
    if record is None:
        raise HTTPException(status_code=400, detail="invalid team name")
    return record


@router.delete("/{name}", status_code=204)
async def delete_team(name: str) -> None:
    """Delete a team."""
    if not get_rbac_store().delete_team(name):
        raise HTTPException(status_code=404, detail="team not found")
