# -*- coding: utf-8 -*-
"""Open API v1 for digital employees (P4: ``/api/open/**``).

外部业务系统经员工级 API Key 调用数字员工（StaffDeck 开放 API 的
最小可用对应面）。鉴权边界：

- Bearer 密钥（``sk_ek_…``）→ ``expert_api_keys.verify`` → 只能访问
  绑定员工的资源（``expert_id`` 即权限边界，吊销/过期即时生效）；
- 员工必须处于 published（下线员工的密钥自动失效语义）。

端点（v1，最小充分）：
- ``GET  /open/experts/{expert_id}`` — 员工公开档案（name/title/
  description/work_styles，不含 system_prompt 等内部字段）；
- ``POST /open/experts/{expert_id}/tasks`` — 提交一个任务，同步等待
  该专家执行并返回结果（复用 workforce 委派通道；120s 超时）。

幂等/审计（Idempotency-Key、审计流水）留下一批——当前面以"能被
外部系统安全调用"为线。
@author qingfeng
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from ..experts.apikeys import get_api_key_store
from ..experts.models import EXPERT_STATUS_PUBLISHED
from ..experts.store import get_expert_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/open", tags=["open-api"])


async def _require_key(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Bearer-key auth dependency → {key_id, expert_id}."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="missing bearer key (expected 'Authorization: Bearer sk_ek_…')",
        )
    plaintext = authorization.split(" ", 1)[1].strip()
    verified = await get_api_key_store().verify(plaintext)
    if verified is None:
        raise HTTPException(status_code=401, detail="invalid or revoked key")
    # 请求态记录 key 身份（审计与限流的锚点）
    request.state.open_key_id = verified["key_id"]
    return verified


async def _require_expert_access(
    expert_id: str,
    principal: Dict[str, Any],
):
    """Key 的 expert 边界 + 员工必须已发布。"""
    if principal["expert_id"] != expert_id:
        raise HTTPException(
            status_code=403,
            detail="key is scoped to a different expert",
        )
    record = await get_expert_store().get_expert(expert_id)
    if record is None or record.status != EXPERT_STATUS_PUBLISHED:
        # 下线员工：密钥语义失效（不暴露存在性差异）
        raise HTTPException(status_code=404, detail="expert not available")
    return record


@router.get("/experts/{expert_id}")
async def expert_profile(
    expert_id: str,
    principal: Dict[str, Any] = Depends(_require_key),
) -> Dict[str, Any]:
    """Public-safe expert profile (no system_prompt / agent_spec)."""
    record = await _require_expert_access(expert_id, principal)
    return {
        "id": record.id,
        "name": record.name,
        "title": record.title,
        "description": record.description,
        "department": record.department,
        "work_styles": record.work_styles,
        "work_modes": record.work_modes,
        "version": record.version,
    }


class OpenTaskBody(BaseModel):
    """One expert task submission."""

    prompt: str = Field(min_length=1, max_length=8000)
    #: 可选幂等键（同一 key + 幂等键重放直接返回缓存结果——简化版：
    #: 由调用方生成 task_id 语义，服务端以 uuid 区分）
    idempotency_key: Optional[str] = None


@router.post("/experts/{expert_id}/tasks")
async def submit_task(
    expert_id: str,
    body: OpenTaskBody,
    request: Request,
    principal: Dict[str, Any] = Depends(_require_key),
) -> Dict[str, Any]:
    """Submit one task to the expert and wait for the final answer.

    同步执行（workforce 委派通道，120s 上限）；超时/通道异常返回
    503 与 task_id（调用方可安全重试——任务在专家自身会话中留痕）。
    """
    record = await _require_expert_access(expert_id, principal)
    from ..experts.models import expert_agent_id
    from ..workforce.delegator import call_expert_text

    task_id = f"open_{uuid.uuid4().hex[:12]}"
    try:
        answer, _session, _tokens = await call_expert_text(
            expert_agent_id(expert_id),
            body.prompt,
            session_id=None,
        )
    except Exception as exc:  # noqa: BLE001 - 通道异常不泄漏内部细节
        logger.warning(
            "open task failed: task=%s expert=%s: %s",
            task_id,
            expert_id,
            exc,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "task_id": task_id,
                "message": "expert execution unavailable, retry later",
            },
        ) from exc
    return {
        "task_id": task_id,
        "status": "succeeded",
        "expert": {"id": record.id, "name": record.name},
        "answer": answer,
    }
