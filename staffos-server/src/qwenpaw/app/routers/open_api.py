# -*- coding: utf-8 -*-
"""Open API v1 for digital employees (P4: ``/api/open/**``).

外部业务系统经员工级 API Key 调用数字员工（StaffDeck 开放 API 的
最小可用对应面）。鉴权边界：

- Bearer 密钥（``sk_ek_…``）→ ``expert_api_keys.verify`` → 只能访问
  绑定员工的资源（``expert_id`` 即权限边界，吊销/过期即时生效）；
- 员工必须处于 published（下线员工的密钥自动失效语义）。

端点（v1）：
- ``GET  /open/experts/{expert_id}`` — 员工公开档案（name/title/
  description/work_styles，不含 system_prompt 等内部字段）；
- ``POST /open/experts/{expert_id}/tasks`` — 提交一个任务，同步等待
  该专家执行并返回结果（复用 workforce 委派通道；120s 超时）。

横切协议（P4 收尾批次）：
- **限流**：per-key 滑动窗口（写面 429 + Retry-After；读面不限流）；
- **幂等**：POST 携带 ``Idempotency-Key`` header（兼容 body 字段）时
  同键同指纹直接回放缓存响应，同键不同指纹 409；仅缓存成功响应
  （失败不缓存，调用方可安全重试）；
- **审计**：全部请求（含 4xx/5xx）best-effort 落 ``open_api_audit``。
@author qingfeng
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..experts.apikeys import get_api_key_store
from ..experts.models import EXPERT_STATUS_PUBLISHED
from ..experts.openapi_governance import (
    IdempotencyConflict,
    fingerprint_payload,
    get_open_governance,
)
from ..experts.store import get_expert_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/open", tags=["open-api"])

#: fire-and-forget 审计任务的强引用集（防止 Task 被 GC 丢弃）
_background_tasks: Set[asyncio.Task] = set()


def _client_ip(request: Request) -> str:
    """Client IP（X-Forwarded-For 首段优先，回退 socket peer）."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _schedule_audit(**kwargs: Any) -> None:
    """Fire-and-forget audit write（best-effort，绝不阻塞响应）."""
    task = asyncio.create_task(get_open_governance().record_audit(**kwargs))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


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


async def _enforce_rate_limit(
    request: Request,
    principal: Dict[str, Any] = Depends(_require_key),
) -> Dict[str, Any]:
    """写面鉴权 + per-key 限流（超限 429 + Retry-After）."""
    allowed, retry_after = await get_open_governance().check_rate_limit(
        principal["key_id"],
    )
    if not allowed:
        _schedule_audit(
            method=request.method,
            path=request.url.path,
            status_code=429,
            latency_ms=0,
            key_id=principal["key_id"],
            expert_id=principal.get("expert_id", ""),
            client_ip=_client_ip(request),
        )
        raise HTTPException(
            status_code=429,
            detail="rate limit exceeded, slow down",
            headers={"Retry-After": str(retry_after)},
        )
    return principal


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
    request: Request,
    principal: Dict[str, Any] = Depends(_require_key),
) -> Dict[str, Any]:
    """Public-safe expert profile (no system_prompt / agent_spec)."""
    started = time.perf_counter()
    try:
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
    finally:
        # 读面仅审计不限流；耗时以毫秒计
        _schedule_audit(
            method=request.method,
            path=request.url.path,
            status_code=200,
            latency_ms=int((time.perf_counter() - started) * 1000),
            key_id=principal["key_id"],
            expert_id=expert_id,
            client_ip=_client_ip(request),
        )


class OpenTaskBody(BaseModel):
    """One expert task submission."""

    prompt: str = Field(min_length=1, max_length=8000)
    #: 幂等键兼容位（推荐改用 ``Idempotency-Key`` header，语义一致）
    idempotency_key: Optional[str] = None


@router.post("/experts/{expert_id}/tasks")
async def submit_task(
    expert_id: str,
    body: OpenTaskBody,
    request: Request,
    principal: Dict[str, Any] = Depends(_enforce_rate_limit),
) -> Any:
    """Submit one task to the expert and wait for the final answer.

    同步执行（workforce 委派通道，120s 上限）；超时/通道异常返回
    503 与 task_id（调用方可安全重试——任务在专家自身会话中留痕）。
    幂等：携带 Idempotency-Key 时同键同指纹回放缓存响应（仅缓存
    成功结果；同键不同指纹 409）。
    """
    started = time.perf_counter()
    idem_key = (
        request.headers.get("idempotency-key")
        or body.idempotency_key
        or ""
    ).strip()[:128]
    fingerprint = fingerprint_payload(body.model_dump())
    governance = get_open_governance()

    # 幂等前置检查：命中即回放（不重算、不计新限流窗口外语义）
    if idem_key:
        try:
            cached = await governance.check_idempotency(
                principal["key_id"],
                idem_key,
                fingerprint,
            )
        except IdempotencyConflict as exc:
            _schedule_audit(
                method=request.method,
                path=request.url.path,
                status_code=409,
                latency_ms=int((time.perf_counter() - started) * 1000),
                key_id=principal["key_id"],
                expert_id=expert_id,
                idem_key=idem_key,
                client_ip=_client_ip(request),
            )
            raise HTTPException(
                status_code=409,
                detail="idempotency key reused with a different payload",
            ) from exc
        if cached is not None:
            _schedule_audit(
                method=request.method,
                path=request.url.path,
                status_code=cached["status_code"],
                latency_ms=int((time.perf_counter() - started) * 1000),
                key_id=principal["key_id"],
                expert_id=expert_id,
                idem_key=idem_key,
                client_ip=_client_ip(request),
            )
            return JSONResponse(
                status_code=cached["status_code"],
                content=cached["response"],
                headers={"Idempotency-Replayed": "true"},
            )

    record = await _require_expert_access(expert_id, principal)
    from ..experts.models import expert_agent_id
    from ..workforce.delegator import call_expert_text

    task_id = f"open_{uuid.uuid4().hex[:12]}"
    status_code = 200
    response: Dict[str, Any] = {}
    try:
        answer, _session, _tokens = await call_expert_text(
            expert_agent_id(expert_id),
            body.prompt,
            session_id=None,
        )
        response = {
            "task_id": task_id,
            "status": "succeeded",
            "expert": {"id": record.id, "name": record.name},
            "answer": answer,
        }
    except Exception as exc:  # noqa: BLE001 - 通道异常不泄漏内部细节
        logger.warning(
            "open task failed: task=%s expert=%s: %s",
            task_id,
            expert_id,
            exc,
        )
        # 失败不缓存（调用方可安全重试重新执行）
        status_code = 503
        raise HTTPException(
            status_code=503,
            detail={
                "task_id": task_id,
                "message": "expert execution unavailable, retry later",
            },
        ) from exc
    finally:
        if idem_key and status_code == 200:
            # 成功响应写入幂等缓存（best-effort）
            await governance.store_idempotent_response(
                principal["key_id"],
                idem_key,
                fingerprint,
                status_code,
                response,
            )
        _schedule_audit(
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            latency_ms=int((time.perf_counter() - started) * 1000),
            key_id=principal["key_id"],
            expert_id=expert_id,
            idem_key=idem_key,
            client_ip=_client_ip(request),
        )
    return response
