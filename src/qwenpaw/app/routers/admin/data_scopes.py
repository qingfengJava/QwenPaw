# -*- coding: utf-8 -*-
"""Admin data-scope management API (M5 RBAC PG)."""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...rbac import PERM_ADMIN_ROLES, require_perm
from ...rbac.store_pg import get_pg_rbac_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/data-scopes",
    tags=["admin-data-scopes"],
    dependencies=[Depends(require_perm(PERM_ADMIN_ROLES))],
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class DataScopeBody(BaseModel):
    """设置角色数据范围请求体."""

    resource: str = Field(min_length=1, max_length=128)
    scope_type: str = Field(min_length=1, max_length=32)
    custom_dept_ids: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_store():
    """获取 PG RBAC store，不可用时抛 503."""
    store = get_pg_rbac_store()
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="PG RBAC store unavailable",
        )
    return store


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/role/{role_id}")
async def get_role_data_scopes(role_id: str) -> list:
    """获取角色的数据范围配置列表."""
    store = _require_store()
    scopes = store.get_data_scopes(role_id)
    return [asdict(s) for s in scopes]


@router.put("/role/{role_id}")
async def set_role_data_scope(role_id: str, body: DataScopeBody) -> dict:
    """设置角色某资源的数据范围."""
    store = _require_store()
    ok = store.set_data_scope(
        role_id,
        body.resource,
        body.scope_type,
        custom_dept_ids=body.custom_dept_ids,
    )
    if not ok:
        raise HTTPException(
            status_code=400,
            detail="set data scope failed",
        )
    return {
        "ok": True,
        "role_id": role_id,
        "resource": body.resource,
        "scope_type": body.scope_type,
    }


@router.delete("/role/{role_id}/{resource}", status_code=204)
async def delete_role_data_scope(role_id: str, resource: str) -> None:
    """删除角色某资源的数据范围."""
    store = _require_store()
    if not store.delete_data_scope(role_id, resource):
        raise HTTPException(
            status_code=404,
            detail="data scope not found",
        )
