# -*- coding: utf-8 -*-
"""Admin permission management API (M5 RBAC PG)."""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ...rbac import require_perm
from ...rbac.store_pg import get_pg_rbac_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/permissions",
    tags=["admin-permissions"],
    dependencies=[Depends(require_perm("admin:permissions"))],
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class PermissionCreateBody(BaseModel):
    """创建权限请求体."""

    code: str = Field(min_length=1, max_length=128)
    name: str = ""
    resource: str = ""
    action: str = ""
    perm_type: str = "api"
    description: str = ""


class PermissionUpdateBody(BaseModel):
    """更新权限请求体（部分字段）."""

    code: Optional[str] = None
    name: Optional[str] = None
    resource: Optional[str] = None
    action: Optional[str] = None
    perm_type: Optional[str] = None
    description: Optional[str] = None


class RolePermissionsBody(BaseModel):
    """全量设置角色权限请求体."""

    permission_ids: List[str] = Field(default_factory=list)


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
# Routes — 静态路径必须先于动态路径注册
# ---------------------------------------------------------------------------


@router.get("")
async def list_permissions(
    resource: Optional[str] = Query(None, description="按 resource 筛选"),
) -> list:
    """获取权限列表（支持 ?resource=xxx 筛选）."""
    store = _require_store()
    perms = store.list_permissions()
    if resource:
        perms = [p for p in perms if p.resource == resource]
    return [asdict(p) for p in perms]


@router.get("/role/{role_id}")
async def get_role_permission_ids(role_id: str) -> list:
    """获取角色已分配的权限 ID 列表."""
    store = _require_store()
    # get_role_permissions 返回 code 列表，需交叉引用获取 ID
    codes = store.get_role_permissions(role_id)
    all_perms = store.list_permissions()
    code_to_id = {p.code: p.id for p in all_perms}
    return [code_to_id[c] for c in codes if c in code_to_id]


@router.put("/role/{role_id}")
async def assign_role_permissions(
    role_id: str, body: RolePermissionsBody,
) -> dict:
    """全量设置角色权限."""
    store = _require_store()
    if not store.assign_role_permissions(role_id, body.permission_ids):
        raise HTTPException(
            status_code=400,
            detail="assign role permissions failed",
        )
    return {
        "ok": True,
        "role_id": role_id,
        "permission_ids": body.permission_ids,
    }


@router.post("", status_code=201)
async def create_permission(body: PermissionCreateBody) -> dict:
    """创建权限."""
    store = _require_store()
    record = store.create_permission(
        code=body.code,
        name=body.name,
        resource=body.resource,
        action=body.action,
        perm_type=body.perm_type,
        description=body.description,
    )
    if record is None:
        raise HTTPException(
            status_code=400,
            detail="create permission failed (invalid or duplicate code)",
        )
    return asdict(record)


@router.patch("/{perm_id}")
async def update_permission(perm_id: str, body: PermissionUpdateBody) -> dict:
    """更新权限（部分字段）."""
    store = _require_store()
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    record = store.update_permission(perm_id, **fields)
    if record is None:
        raise HTTPException(status_code=404, detail="permission not found")
    return asdict(record)


@router.delete("/{perm_id}", status_code=204)
async def delete_permission(perm_id: str) -> None:
    """删除权限."""
    store = _require_store()
    if not store.delete_permission(perm_id):
        raise HTTPException(status_code=404, detail="permission not found")
