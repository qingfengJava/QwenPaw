# -*- coding: utf-8 -*-
"""Admin expert-team management API: member orchestration + publishing."""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from ...experts.models import (
    ExpertTeamCreateBody,
    ExpertTeamRecord,
    ExpertTeamUpdateBody,
    TeamMember,
    expert_team_agent_id,
)
from ...experts.publish import archive_expert_team, publish_expert_team
from ...experts.store import get_expert_store
from ...rbac import PERM_ADMIN_EXPERTS, require_perm

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/expert-teams",
    tags=["admin-expert-teams"],
    dependencies=[Depends(require_perm(PERM_ADMIN_EXPERTS))],
)


def _manager(request: Request):
    return getattr(request.app.state, "multi_agent_manager", None)


@router.get("", response_model=List[ExpertTeamRecord])
async def list_teams(status: Optional[str] = None) -> List[ExpertTeamRecord]:
    return await get_expert_store().list_teams(status=status)


@router.post("", status_code=201, response_model=ExpertTeamRecord)
async def create_team(body: ExpertTeamCreateBody) -> ExpertTeamRecord:
    return await get_expert_store().create_team(
        name=body.name,
        description=body.description,
        mode=body.mode,
        router_prompt=body.router_prompt,
        members=[
            TeamMember(
                expert_id=m.expert_id,
                role_hint=m.role_hint,
                seq=m.seq,
            )
            for m in body.members
        ],
    )


@router.get("/{team_id}", response_model=ExpertTeamRecord)
async def get_team(team_id: str) -> ExpertTeamRecord:
    record = await get_expert_store().get_team(team_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Expert team not found")
    return record


@router.patch("/{team_id}", response_model=ExpertTeamRecord)
async def update_team(
    team_id: str,
    body: ExpertTeamUpdateBody,
) -> ExpertTeamRecord:
    members = None
    if body.members is not None:
        members = [
            TeamMember(
                expert_id=m.expert_id,
                role_hint=m.role_hint,
                seq=m.seq,
            )
            for m in body.members
        ]
    try:
        record = await get_expert_store().update_team(
            team_id,
            name=body.name,
            description=body.description,
            mode=body.mode,
            router_prompt=body.router_prompt,
            members=members,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Expert team not found")
    return record


@router.delete("/{team_id}", status_code=204)
async def delete_team(team_id: str) -> None:
    if not await get_expert_store().delete_team(team_id):
        raise HTTPException(status_code=404, detail="Expert team not found")


@router.post("/{team_id}/publish", response_model=ExpertTeamRecord)
async def publish(team_id: str, request: Request) -> ExpertTeamRecord:
    """Publish members (validated) then materialize the supervisor."""
    actor = getattr(request.state, "user", None) or "admin"
    try:
        return await publish_expert_team(
            team_id,
            published_by=actor,
            manager=_manager(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{team_id}/archive", response_model=ExpertTeamRecord)
async def archive(team_id: str, request: Request) -> ExpertTeamRecord:
    record = await archive_expert_team(
        team_id,
        manager=_manager(request),
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Expert team not found")
    return record


@router.get("/{team_id}/agent_id")
async def runtime_agent_id(team_id: str) -> dict:
    return {
        "team_id": team_id,
        "agent_id": expert_team_agent_id(team_id),
    }
