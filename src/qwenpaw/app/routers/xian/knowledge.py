# -*- coding: utf-8 -*-
"""Employee-facing knowledge flow（``/api/xian/knowledge/**``，T6）。

员工自建库 → 绑定自己数字员工（expert）的人侧最小闭环：

- **列我的库**：``owner == viewer`` 的 personal 库（上传/文档管理复用
  既有 ``/api/kb`` 人侧端点，不在此重复造面）；
- **绑定我的 experts**：把我 ``owner`` 的库绑到我 ``owner`` 的 expert
  （agent 直绑类型，``principal_type='agent'``）；双向归属校验——
  库非我拥有 403、expert 非我拥有 404（不泄露他人资源存在性）。

管理权门复用 :func:`kb.bindings.can_manage_space`（personal=owner
本人），绑定即授权不另立规则。

@author qingfeng
"""
from __future__ import annotations

import logging
from typing import Any, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ...experts.models import expert_agent_id
from ...kb import bindings as kb_bindings
from ...kb.models import SCOPE_PERSONAL
from ...kb.service import get_kb_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["xian-knowledge"])


def _viewer(request: Request) -> str:
    """Current viewer identity（匿名回退 ``local``，与 xian 面一致）。"""
    return getattr(request.state, "user", None) or "local"


class ExpertBindingBody(BaseModel):
    """Body for binding one of my knowledge bases to one of my experts."""

    expert_id: str


def _require_owned_kb(kb_id: str, viewer: str):
    """Return the viewer-owned personal kb or raise 404/403."""
    kb = get_kb_service().get_kb(kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="kb not found")
    if kb.owner_id != viewer or kb.scope != SCOPE_PERSONAL:
        # 不区分「非个人库」与「非我拥有」：不泄露他人资源存在性
        raise HTTPException(
            status_code=403,
            detail="you do not own this knowledge base",
        )
    return kb


async def _require_owned_expert(expert_id: str, viewer: str) -> None:
    """404 unless the expert exists and is owned by the viewer."""
    from ...experts.store import get_expert_store

    record = await get_expert_store().get_expert(expert_id)
    if record is None or getattr(record, "owner_id", None) != viewer:
        # expert 非我拥有合并 not-found：不泄露他人专家存在性
        raise HTTPException(status_code=404, detail="expert not found")


@router.get("/bases")
async def list_my_bases(request: Request) -> List[dict]:
    """My personal knowledge bases（owner == viewer，绑定流下拉源）。"""
    viewer = _viewer(request)
    bases = []
    for kb in get_kb_service().list_kbs():
        if kb.scope == SCOPE_PERSONAL and kb.owner_id == viewer:
            bases.append(
                {
                    "id": kb.id,
                    "name": kb.name,
                    "description": kb.description,
                    "scope": kb.scope,
                },
            )
    return bases


async def _my_bound_experts(kb_id: str, viewer: str) -> List[dict]:
    """Experts of mine that hold a binding on *kb_id*（内存组装）。

    员工专家量级有上限（``MAX_USER_EXPERTS``），逐 expert 读绑定行后
    内存过滤即可；绑定行没有按 space 的反查索引，不为员工小流量面
    增设存储接口。
    """
    from ...experts.store import get_expert_store

    store = get_expert_store()
    cards = await store.list_expert_cards(owner=viewer)
    bound: List[dict] = []
    for card in cards:
        # 绑定消费方是运行态 agent id（expert_{id}），非裸 expert id
        stored_id = expert_agent_id(card.id)
        rows = await kb_bindings.list_bindings(stored_id)
        hit = next(
            (r for r in rows if r["space_id"] == kb_id),
            None,
        )
        if hit is not None:
            bound.append(
                {
                    "expert_id": card.id,
                    "expert_name": card.name,
                    "space_id": kb_id,
                    "granted_by": hit["granted_by"],
                    "created_at": hit["created_at"],
                },
            )
    return bound


@router.get("/bases/{kb_id}/expert-bindings")
async def list_expert_bindings(kb_id: str, request: Request) -> List[dict]:
    """Experts bound to one of my bases（仅我的专家域）。"""
    viewer = _viewer(request)
    _require_owned_kb(kb_id, viewer)
    return await _my_bound_experts(kb_id, viewer)


@router.put("/bases/{kb_id}/expert-bindings")
async def bind_expert(
    kb_id: str,
    body: ExpertBindingBody,
    request: Request,
) -> Any:
    """Bind one of my bases to one of my experts（201/200 幂等）。"""
    viewer = _viewer(request)
    _require_owned_kb(kb_id, viewer)
    await _require_owned_expert(body.expert_id, viewer)
    ok = await kb_bindings.bind_agent_kb(
        agent_id=expert_agent_id(body.expert_id),
        space_id=kb_id,
        granted_by=viewer,
        remark="employee self-binding",
    )
    if ok is not True:
        raise HTTPException(
            status_code=503,
            detail="kb binding storage unavailable",
        )
    rows = await kb_bindings.list_bindings(
        expert_agent_id(body.expert_id),
    )
    row = next((r for r in rows if r["space_id"] == kb_id), None)
    if row is None:
        raise HTTPException(
            status_code=409,
            detail="binding was concurrently removed; retry",
        )
    return JSONResponse(status_code=201, content={**row, "created": True})


@router.delete(
    "/bases/{kb_id}/expert-bindings/{expert_id}",
    status_code=204,
)
async def unbind_expert(
    kb_id: str,
    expert_id: str,
    request: Request,
) -> None:
    """Unbind one of my experts from one of my bases（行不存在 404）。"""
    viewer = _viewer(request)
    _require_owned_kb(kb_id, viewer)
    removed = await kb_bindings.unbind_agent_kb(
        expert_agent_id(expert_id),
        kb_id,
    )
    if not removed:
        raise HTTPException(status_code=404, detail="binding not found")
