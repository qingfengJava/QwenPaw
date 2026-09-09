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

router = APIRouter(prefix="/agent-stats", tags=["agent-stats"])


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


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
) -> AgentStatsSummary:
    end_d = _parse_date(end_date) or date.today()
    start_d = _parse_date(start_date) or (end_d - timedelta(days=30))
    if start_d > end_d:
        start_d, end_d = end_d, start_d

    workspace = await get_agent_for_request(request)
    service = get_agent_stats_service()
    return await service.get_summary(
        workspace_dir=workspace.workspace_dir,
        start_date=start_d,
        end_date=end_d,
        # pg 后端按 agent_id 隔离 chats/session_states，必须随请求传入
        agent_id=getattr(workspace, "agent_id", "default"),
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
) -> AgentStatsBrief:
    end_d = date.today()
    start_d = end_d - timedelta(days=window_days - 1)
    workspace = await get_agent_for_request(request)
    service = get_agent_stats_service()
    summary = await service.get_summary(
        workspace_dir=workspace.workspace_dir,
        start_date=start_d,
        end_date=end_d,
        # pg 后端按 agent_id 隔离 chats/session_states，必须随请求传入
        agent_id=getattr(workspace, "agent_id", "default"),
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
