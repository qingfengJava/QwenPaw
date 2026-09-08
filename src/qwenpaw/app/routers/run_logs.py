# -*- coding: utf-8 -*-
"""Run-log query endpoints for the Console sessions page.

List reads the day-sharded JSONL index (:mod:`run_log_store`); detail
delegates to the per-run trace files (:mod:`inbox_trace_store`). The
router mounts under ``/api/agents/{agentId}`` (agent_scoped), so the
list defaults to the current agent's data domain.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request

from ..agent_context import get_agent_for_request
from ..inbox_trace_store import get_trace
from ..run_log_store import query_run_logs

router = APIRouter(prefix="/run-logs", tags=["run-logs"])
logger = logging.getLogger(__name__)


@router.get("")
async def list_run_logs(
    request: Request,
    agent_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    channel: str | None = Query(default=None),
    source: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    q: str | None = Query(default=None),
    start: float | None = Query(default=None),
    end: float | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """List run-log rows newest-first with server-side filters."""
    # Default to the request-scoped agent so workbench calls stay isolated.
    resolved_agent_id = agent_id
    if resolved_agent_id is None:
        try:
            workspace = await get_agent_for_request(request)
            resolved_agent_id = getattr(workspace, "agent_id", None)
        except Exception:  # pylint: disable=broad-except
            logger.debug("run-logs: agent resolve skipped", exc_info=True)

    items, total = await query_run_logs(
        agent_id=resolved_agent_id,
        status=status or None,
        channel=channel or None,
        source=source or None,
        environment=environment or None,
        keyword=q or None,
        start_ts=start,
        end_ts=end,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


@router.get("/{run_id}")
async def get_run_log_detail(run_id: str) -> dict:
    """Return the full trace (meta + events) for one run."""
    trace = await get_trace(run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Run log not found")
    return trace
