# -*- coding: utf-8 -*-
"""Agent statistics API for console."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Query, Request

from ...agent_stats import (
    AgentStatsBrief,
    AgentStatsSummary,
    DailyBrief,
    get_agent_stats_service,
)
from ..agent_context import get_agent_for_request
from ..rbac import manage_allowed, rbac_enforcement_enabled

router = APIRouter(prefix="/agent-stats", tags=["agent-stats"])


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


async def _resolve_stats_scope(
    request: Request,
    agent_id: str,
    claimed_scope: str | None,
) -> tuple[str, str | None]:
    """解析统计 token 口径，返回 ``(scope, viewer)``。

    - 认证关闭（无 viewer）：单用户部署，按 agent 全量（scope 无意义）；
    - RBAC 未强制：不收敛，保留全量口径（与闸门直通一致）；
    - admin / team_lead / 对该员工有管理授权者：可选 mine/agent（默认 agent）；
    - 其余（普通 employee）：强制 mine（仅本人发起的用量），与 run_logs
      的 ``_scope_user_for_viewer`` 同语义。
    """
    viewer = getattr(request.state, "user", None)
    if not viewer:
        return "agent", None
    viewer = str(viewer)
    if not rbac_enforcement_enabled():
        return "agent", None
    # 管理授权者（含 admin / team_lead / grant / owner）可看员工全量口径
    if not await manage_allowed(viewer, agent_id):
        return "mine", viewer
    scope = claimed_scope if claimed_scope in ("mine", "agent") else "agent"
    return scope, (viewer if scope == "mine" else None)


@router.get(
    "",
    summary="Get agent statistics summary",
    description="Return comprehensive agent statistics for the date range",
)
async def get_agent_statistics(
    request: Request,
    start_date: str
    | None = Query(
        None,
        description="Start date YYYY-MM-DD (inclusive). Default: 30 days ago",
    ),
    end_date: str
    | None = Query(
        None,
        description="End date YYYY-MM-DD (inclusive). Default: today",
    ),
    scope: str
    | None = Query(
        None,
        description="mine=仅本人发起 / agent=全员工（默认；employee 强制 mine）",
    ),
) -> AgentStatsSummary:
    end_d = _parse_date(end_date) or date.today()
    start_d = _parse_date(start_date) or (end_d - timedelta(days=30))
    if start_d > end_d:
        start_d, end_d = end_d, start_d

    workspace = await get_agent_for_request(request)
    agent_id = getattr(workspace, "agent_id", "default")
    # 员工口径 + scope 收敛（employee 强制 mine，管理授权者可切 agent）
    eff_scope, viewer = await _resolve_stats_scope(request, agent_id, scope)
    service = get_agent_stats_service()
    return await service.get_summary(
        workspace_dir=workspace.workspace_dir,
        start_date=start_d,
        end_date=end_d,
        # pg 后端按 agent_id 隔离 chats/session_states，必须随请求传入
        agent_id=agent_id,
        scope=eff_scope,
        viewer=viewer,
    )


@router.get(
    "/summary-brief",
    summary="Get lightweight agent statistics brief",
    description=(
        "Aggregated brief for the employee profile aside and overview "
        "cards. Window defaults to the last 90 days; recent_daily keeps "
        "the last 7 days with density only."
    ),
)
async def get_agent_stats_brief(
    request: Request,
    window_days: int = Query(
        90,
        ge=1,
        le=365,
        description="Aggregation window length in days ending today",
    ),
    scope: str
    | None = Query(
        None,
        description="mine=仅本人发起 / agent=全员工（默认；employee 强制 mine）",
    ),
) -> AgentStatsBrief:
    end_d = date.today()
    start_d = end_d - timedelta(days=window_days - 1)
    workspace = await get_agent_for_request(request)
    agent_id = getattr(workspace, "agent_id", "default")
    # 员工口径 + scope 收敛（与 /agent-stats 同一解析器）
    eff_scope, viewer = await _resolve_stats_scope(request, agent_id, scope)
    service = get_agent_stats_service()
    summary = await service.get_summary(
        workspace_dir=workspace.workspace_dir,
        start_date=start_d,
        end_date=end_d,
        # pg 后端按 agent_id 隔离 chats/session_states，必须随请求传入
        agent_id=agent_id,
        scope=eff_scope,
        viewer=viewer,
    )
    # 今天无会话时 by_date 可能缺行，取不到则今日为 0。
    today_iso = end_d.isoformat()
    today_row = next(
        (d for d in summary.by_date if d.date == today_iso), None
    )
    # 按日期升序取末 7 天密度行，供时间线/迷你柱图使用。
    recent_daily = sorted(summary.by_date, key=lambda d: d.date)[-7:]
    return AgentStatsBrief(
        today_chats=today_row.chats if today_row else 0,
        total_chats=sum(d.chats for d in summary.by_date),
        total_messages=summary.total_messages,
        total_tokens=(
            summary.total_prompt_tokens + summary.total_completion_tokens
        ),
        active_sessions=summary.total_active_sessions,
        recent_daily=[
            DailyBrief(date=d.date, chats=d.chats, messages=d.total_messages)
            for d in recent_daily
        ],
    )
