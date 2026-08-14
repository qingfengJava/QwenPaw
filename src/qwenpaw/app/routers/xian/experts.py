# -*- coding: utf-8 -*-
"""Published expert catalog for XianWork users (read-only, ACL-filtered).

Employees see only ``published`` experts whose runtime agent is either
unrestricted or explicitly granted to them (directly, via role, or via
their department-mirrored RBAC team — see ``orgs.service``).
"""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Request

from ...experts.models import (
    EXPERT_STATUS_PUBLISHED,
    expert_agent_id,
    expert_team_agent_id,
)
from ...experts.store import get_expert_store
from ...rbac.store import get_rbac_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/experts", tags=["xian-experts"])


def _viewer(request: Request) -> str:
    return getattr(request.state, "user", None) or "local"


def _agent_visible(username: str, agent_id: str) -> bool:
    """Grant check: absent ACL = org-wide; present = role/user/team hit."""
    try:
        from ...users.store import get_user_store

        flat_role = get_user_store().get_user(username).role
    except Exception:  # pylint: disable=broad-except
        flat_role = ""
    try:
        return get_rbac_store().agent_allowed(
            username,
            agent_id,
            flat_role=flat_role,
        )
    except Exception:  # pylint: disable=broad-except
        logger.warning("expert ACL check failed for %s", agent_id)
        return False


@router.get("")
async def list_experts(request: Request) -> List[dict]:
    """Published experts visible to the caller (agent_id for X-Agent-Id)."""
    username = _viewer(request)
    experts = await get_expert_store().list_experts(
        status=EXPERT_STATUS_PUBLISHED,
    )
    visible = []
    for expert in experts:
        agent_id = expert_agent_id(expert.id)
        if not _agent_visible(username, agent_id):
            continue
        visible.append(
            {
                "id": expert.id,
                "name": expert.name,
                "icon": expert.icon,
                "description": expert.description,
                "version": expert.version,
                "agent_id": agent_id,
            }
        )
    return visible


@router.get("/teams")
async def list_expert_teams(request: Request) -> List[dict]:
    """Published expert teams visible to the caller."""
    username = _viewer(request)
    teams = await get_expert_store().list_teams(
        status=EXPERT_STATUS_PUBLISHED,
    )
    visible = []
    for team in teams:
        agent_id = expert_team_agent_id(team.id)
        if not _agent_visible(username, agent_id):
            continue
        visible.append(
            {
                "id": team.id,
                "name": team.name,
                "description": team.description,
                "mode": team.mode,
                "version": team.version,
                "agent_id": agent_id,
                "member_count": len(team.members),
            }
        )
    return visible
