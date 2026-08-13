# -*- coding: utf-8 -*-
"""Admin audit query API (M4)."""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ....governance.audit import AuditLog
from ...rbac import PERM_ADMIN_AUDIT, require_perm

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/audit",
    tags=["admin-audit"],
    dependencies=[Depends(require_perm(PERM_ADMIN_AUDIT))],
)


class AuditEventView(BaseModel):
    ts: int
    workspace_dir: str
    agent_id: str
    session_id: str
    tool_name: str
    target: str
    decision: str
    reason: str = ""
    actor_id: str = ""


class AuditPage(BaseModel):
    events: List[AuditEventView] = Field(default_factory=list)
    total: int = 0


@router.get("", response_model=AuditPage)
async def query_audit(
    workspace_dir: Optional[str] = None,
    agent_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    decision: Optional[str] = None,
    since: Optional[int] = None,
    until: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
) -> AuditPage:
    """Query the governance audit log (newest first, paginated)."""
    rows, total = AuditLog.get_instance().query(
        workspace_dir=workspace_dir,
        agent_id=agent_id,
        tool_name=tool_name,
        decision=decision,
        since=since,
        until=until,
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
    )
    return AuditPage(
        events=[
            AuditEventView(
                ts=row.ts,
                workspace_dir=row.workspace_dir,
                agent_id=row.agent_id,
                session_id=row.session_id,
                tool_name=row.tool_name,
                target=row.target,
                decision=row.decision,
                reason=row.reason,
                actor_id=row.actor_id,
            )
            for row in rows
        ],
        total=total,
    )
