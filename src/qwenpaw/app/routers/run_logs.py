# -*- coding: utf-8 -*-
"""Run-log query endpoints for the Console sessions page.

List reads the day-sharded JSONL index (:mod:`run_log_store`); detail
delegates to the per-run trace files (:mod:`inbox_trace_store`). The
router mounts under ``/api/agents/{agentId}`` (agent_scoped), so the
list defaults to the current agent's data domain.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ..agent_context import get_agent_for_request
from ..inbox_trace_store import get_trace
from ..run_log_pg_store import (
    get_run_trace_pg,
    list_run_users_pg,
    pg_available,
    query_run_logs_pg,
)
from ..run_log_store import list_run_users, query_run_logs

router = APIRouter(prefix="/run-logs", tags=["run-logs"])
logger = logging.getLogger(__name__)


def _viewer_role(username: str) -> str:
    """Return the flat role of an authenticated viewer.

    角色查询失败时按 admin 兜底：与 AuthMiddleware 的 org 解析失败继续放行
    同一策略，避免账号存储抖动把整个运行日志页面锁死（会话层另有 RLS）。
    """
    try:
        from ..users.store import get_user_store

        record = get_user_store().get_user(username)
        return record.role if record is not None else "admin"
    except Exception:  # pylint: disable=broad-except
        logger.warning("run-logs: role lookup failed for %s", username)
        return "admin"


def _scope_user_for_viewer(
    request: Request,
    claimed_user: str | None,
) -> str | None:
    """Resolve the effective ``user`` filter for one list request.

    employee 角色被强制限定在自己发起的运行上（客户端传入的 user 参数
    只能在自己的身份范围内收窄）；admin 可任意筛选；认证关闭（本地单
    用户模式）时透传原值，保持零配置体验。
    """
    viewer = getattr(request.state, "user", None)
    if not viewer:
        return claimed_user
    # employee 一律收窄到自己；admin 保留客户端筛选能力。
    if _viewer_role(str(viewer)) != "admin":
        return str(viewer)
    return claimed_user


def _can_view_run(request: Request, run_user_id: Any) -> bool:
    """Whether the viewer may open one run's detail (ownership gate)."""
    viewer = getattr(request.state, "user", None)
    if not viewer:
        return True
    # admin 全量可见；employee 仅限本人发起的运行。
    if _viewer_role(str(viewer)) == "admin":
        return True
    return str(run_user_id or "") == str(viewer)


@router.get("")
async def list_run_logs(
    request: Request,
    agent_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    channel: str | None = Query(default=None),
    source: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    user: str | None = Query(default=None),
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

    # P2 数据权限：employee 角色只能看到自己发起的运行（认证关闭时不限制）。
    effective_user = _scope_user_for_viewer(request, user)

    # PG store first (spans available, SQL filtering); fall back to the
    # file-era JSONL index when no DSN is configured or PG errors out.
    if pg_available():
        try:
            items, total = await query_run_logs_pg(
                agent_id=resolved_agent_id,
                status=status or None,
                channel=channel or None,
                source=source or None,
                environment=environment or None,
                user_id=effective_user,
                keyword=q or None,
                start_ts=start,
                end_ts=end,
                limit=limit,
                offset=offset,
            )
            return {"items": items, "total": total}
        except Exception:  # pylint: disable=broad-except
            logger.warning("run-logs pg query failed; file fallback")

    items, total = await query_run_logs(
        agent_id=resolved_agent_id,
        status=status or None,
        channel=channel or None,
        source=source or None,
        environment=environment or None,
        user_id=effective_user,
        keyword=q or None,
        start_ts=start,
        end_ts=end,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


@router.get("/users")
async def list_run_log_users(
    request: Request,
    agent_id: str | None = Query(default=None),
) -> dict:
    """Distinct sender identities for the run-log user filter dropdown."""
    # 默认落到当前请求域的 agent，与列表端点保持一致。
    resolved_agent_id = agent_id
    if resolved_agent_id is None:
        try:
            workspace = await get_agent_for_request(request)
            resolved_agent_id = getattr(workspace, "agent_id", None)
        except Exception:  # pylint: disable=broad-except
            logger.debug("run-logs: agent resolve skipped", exc_info=True)

    # PG 优先；无 DSN 或查询失败时回退文件索引（与列表端点同策略）。
    if pg_available():
        try:
            users = await list_run_users_pg(agent_id=resolved_agent_id)
            return {"users": users}
        except Exception:  # pylint: disable=broad-except
            logger.warning("run-logs pg user list failed; file fallback")

    users = await list_run_users(agent_id=resolved_agent_id)
    return {"users": users}


@router.get("/{run_id}")
async def get_run_log_detail(request: Request, run_id: str) -> dict:
    """Return one run's trace: spans (PG) or message snapshot (file)."""
    # PG runs carry the real span tree; file traces serve legacy data and
    # non-PG deployments (events-based, frontend guesses the tree).
    if pg_available():
        try:
            trace = await get_run_trace_pg(run_id)
            if trace is not None:
                # P2 数据权限：employee 不能查看他人发起的运行详情。
                if not _can_view_run(request, trace.get("user_id")):
                    raise HTTPException(
                        status_code=404,
                        detail="Run log not found",
                    )
                return trace
        except HTTPException:
            raise
        except Exception:  # pylint: disable=broad-except
            logger.warning("run-log pg detail failed; file fallback")

    trace = await get_trace(run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Run log not found")
    # 文件路径同样执行归属校验（meta.user_id 承载发起人）。
    if not _can_view_run(request, (trace.get("meta") or {}).get("user_id")):
        raise HTTPException(status_code=404, detail="Run log not found")
    return trace
