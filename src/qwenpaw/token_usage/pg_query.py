# -*- coding: utf-8 -*-
"""PG 权威 token 计量聚合（``token_usage_events`` 按 agent / 日 / 用户）。

agent_stats 的「员工口径」token 叠加在 PG 可用时改查本模块：按 agent_id
（``scope=mine`` 时再按 user_id 收敛到本人）在日期范围内按日聚合
prompt / completion / call，替代旧的全局文件缓冲口径（Token 卡此前是全站
口径，与单个员工无关）。

日期分桶与 session/文件口径对齐——统一用**本地日期**（``created_at`` 先转
UTC 墙钟再平移本地时区偏移取 date），保证按日 merge 时 key 命中。

PG 不可用（json/dual 后端或企业平面未就绪）或查询失败时返回 ``None``，由
调用方回退会话现算的 ``agent_*`` 字段，绝不因计量缺 PG 而整页报错。

@author qingfeng
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def aggregate_agent_token_usage(
    agent_id: str,
    start_date: date,
    end_date: date,
    *,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """按 agent_id（可选 user_id）在 ``[start_date, end_date]`` 内按日聚合。

    Args:
        agent_id: 目标员工运行时 agent id（``token_usage_events.agent_id``）。
        start_date: 起始日（含，本地日期）。
        end_date: 结束日（含，本地日期）。
        user_id: 非空时再按发起用户收敛（``scope=mine`` 个人口径）。

    Returns:
        ``{"total_prompt", "total_completion", "total_calls", "by_date":
        {iso_date: {"prompt", "completion", "calls"}}}``；PG 不可用或查询
        失败返回 ``None``（调用方据此回退会话口径）。
    """
    # 企业平面引擎缺失（无 PG）时直接返回 None，交调用方回退会话口径
    try:
        from sqlalchemy import text

        from ..app.enterprise import (
            current_tenant_id,
            require_enterprise_engine,
        )

        engine = require_enterprise_engine()
        tenant_id = current_tenant_id()
    except Exception:  # pylint: disable=broad-except
        return None

    # 本地时区偏移（小时）：用于把 UTC 墙钟平移到本地日期分桶
    now_local = datetime.now().astimezone()
    utc_offset = now_local.utcoffset() or timedelta(0)
    offset_hours = utc_offset.total_seconds() / 3600.0
    local_tz = now_local.tzinfo
    # 过滤用本地日界的 aware 半开区间 [start 00:00, end+1 00:00)
    start_ts = datetime.combine(start_date, time.min, tzinfo=local_tz)
    end_ts = datetime.combine(
        end_date + timedelta(days=1), time.min, tzinfo=local_tz
    )

    clauses: List[str] = [
        "tenant_id = :tid",
        "agent_id = :agent_id",
        "created_at >= :start_ts",
        "created_at < :end_ts",
    ]
    params: Dict[str, Any] = {
        "tid": tenant_id,
        "agent_id": agent_id,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "off_h": offset_hours,
    }
    # scope=mine：再按发起用户收敛（token_usage_events.user_id）
    if user_id:
        clauses.append("user_id = :user_id")
        params["user_id"] = user_id

    sql = (
        "SELECT (created_at AT TIME ZONE 'UTC' "
        "+ make_interval(hours => :off_h))::date AS day, "
        "COALESCE(SUM(prompt_tokens), 0) AS prompt, "
        "COALESCE(SUM(completion_tokens), 0) AS completion, "
        "COUNT(*) AS calls "
        f"FROM token_usage_events WHERE {' AND '.join(clauses)} "
        "GROUP BY day ORDER BY day"
    )

    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(sql), params)
            rows = result.fetchall()
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "token_usage pg aggregate failed for agent=%s",
            agent_id,
            exc_info=True,
        )
        return None

    by_date: Dict[str, Dict[str, int]] = {}
    total_prompt = 0
    total_completion = 0
    total_calls = 0
    for row in rows:
        day = row.day
        day_str = day.isoformat() if hasattr(day, "isoformat") else str(day)
        prompt = int(row.prompt or 0)
        completion = int(row.completion or 0)
        calls = int(row.calls or 0)
        by_date[day_str] = {
            "prompt": prompt,
            "completion": completion,
            "calls": calls,
        }
        total_prompt += prompt
        total_completion += completion
        total_calls += calls

    return {
        "total_prompt": total_prompt,
        "total_completion": total_completion,
        "total_calls": total_calls,
        "by_date": by_date,
    }
