# -*- coding: utf-8 -*-
"""XianWork user-plane views of the digital-employee capability layer.

员工侧只读 + 反馈写入（管理面在 ``routers/admin/expert_capability.py``）：
- 工作记录聚合：可见性对齐市场详情（org 已发布 / owner）；
- 消息反馈：任何可访问该专家的用户可对其消息打 👍/👎（每人每消息
  一票，重复提交 = 覆盖）。

记忆/定时任务/SOP 管理本期收敛在管理面；xianwork 前端同步列入 P5。
路由顺序：本模块在 experts_router 之后注册，避开两段式详情路由吞路径。
可见性助手直接复用 experts 路由的私有实现（单一来源，不另立 guard）。
@author qingfeng
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from ...experts.feedback import get_feedback_store
from ...experts.models import (
    EXPERT_STATUS_PUBLISHED,
    EXPERT_VISIBILITY_ORG,
    WorkRecord,
    expert_agent_id,
)
from ...experts.store import get_expert_store
from ...experts.worklog import get_worklog_service
from .experts import _agent_visible, _viewer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["xian-expert-capability"])


async def _require_viewable(expert_id: str, request: Request):
    """Market-detail-aligned visibility guard (published/org or owner)."""
    username = _viewer(request)
    record = await get_expert_store().get_expert(expert_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Expert not found")
    is_owner = record.owner_id == username
    if record.status != EXPERT_STATUS_PUBLISHED and not is_owner:
        raise HTTPException(status_code=404, detail="Expert not found")
    if (
        record.status == EXPERT_STATUS_PUBLISHED
        and not is_owner
        and record.visibility != EXPERT_VISIBILITY_ORG
    ):
        raise HTTPException(status_code=403, detail="private expert")
    if (
        record.status == EXPERT_STATUS_PUBLISHED
        and not is_owner
        and not _agent_visible(username, expert_agent_id(expert_id))
    ):
        raise HTTPException(status_code=403, detail="No access to this expert")
    return record


@router.get("/experts/{expert_id}/work-record", response_model=WorkRecord)
async def work_record(
    expert_id: str,
    request: Request,
    days: int = 30,
) -> WorkRecord:
    """Aggregated work record, visibility aligned with the market detail."""
    await _require_viewable(expert_id, request)
    return await get_worklog_service().build_work_record(
        expert_id,
        days=days,
    )


@router.post("/experts/{expert_id}/feedback")
async def rate_message(
    expert_id: str,
    request: Request,
    body: Dict[str, Any],
) -> Dict[str, Any]:
    """Upsert the caller's 👍/👎 on one expert message."""
    record = await _require_viewable(expert_id, request)
    if record.status != EXPERT_STATUS_PUBLISHED:
        raise HTTPException(status_code=404, detail="Expert not found")
    rating = str(body.get("rating") or "")
    if rating not in ("up", "down"):
        raise HTTPException(status_code=400, detail="rating must be up/down")
    message_id = str(body.get("message_id") or "").strip()
    if not message_id:
        raise HTTPException(status_code=400, detail="message_id required")
    result = await get_feedback_store().rate(
        message_id=message_id,
        user_id=_viewer(request),
        rating=rating,
        session_id=str(body.get("session_id") or ""),
        expert_id=expert_id,
        comment=str(body.get("comment") or ""),
    )
    # 差评触发专家自省归因（fire-and-forget，自动起草演进提案）
    from ...experts.feedback import maybe_schedule_attribution

    maybe_schedule_attribution(expert_id, rating)
    return result
