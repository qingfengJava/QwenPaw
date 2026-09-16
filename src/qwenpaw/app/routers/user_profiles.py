# -*- coding: utf-8 -*-
"""User profile lookup endpoints for display surfaces (run logs, etc.).

任何已登录用户可查询账号的**展示型**字段（username/display_name/avatar），
不含密码、角色、组织等敏感信息；认证关闭（本地单用户模式）时直接放行，
与全站免认证体验保持一致。
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["user-profiles"])

# 单次批量查询的 username 上限（防御性裁剪，常规页面一次不足 50 个）。
_MAX_BATCH = 200


class UserProfileView(BaseModel):
    """Display-safe profile fields of one account."""

    username: str
    display_name: str
    avatar: str


class UserProfileBatchResponse(BaseModel):
    """Batch profile response (unknown usernames are silently omitted)."""

    items: List[UserProfileView]


@router.get("/profiles", response_model=UserProfileBatchResponse)
async def get_user_profiles(
    request: Request,
    usernames: str = Query(
        ...,
        description="Comma-separated usernames to resolve",
    ),
) -> UserProfileBatchResponse:
    """Resolve display profiles for a batch of usernames.

    运行日志等列表页用本接口把 user_id 批量组装成「昵称 + 头像」，
    一次请求完成全部解析（禁止列表渲染时逐条回源）。
    """
    # 认证关闭时不暴露敏感面（本接口本就只含展示字段），直接放行。
    viewer = getattr(request.state, "user", None)
    if not viewer:
        return UserProfileBatchResponse(items=[])

    # 拆分、去空白、去重并截断到批量上限。
    requested: List[str] = []
    for raw in usernames.split(","):
        name = raw.strip()
        if name and name not in requested:
            requested.append(name)
    requested = requested[:_MAX_BATCH]
    if not requested:
        return UserProfileBatchResponse(items=[])

    from ..users.store import get_user_store

    store = get_user_store()
    items: List[UserProfileView] = []
    for name in requested:
        record: Optional[object] = store.get_user(name)
        if record is None:
            # 未注册身份（渠道原始 external id 等）不返回占位行。
            continue
        items.append(
            UserProfileView(
                username=record.username,
                display_name=record.display_name,
                avatar=record.avatar,
            ),
        )
    return UserProfileBatchResponse(items=items)
