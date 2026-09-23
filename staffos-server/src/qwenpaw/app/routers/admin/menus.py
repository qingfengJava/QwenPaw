# -*- coding: utf-8 -*-
"""Admin menu management API (M5 RBAC PG)."""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...rbac import require_perm
from ...rbac.store_pg import get_pg_rbac_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/menus",
    tags=["admin-menus"],
    dependencies=[Depends(require_perm("admin:menus"))],
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class MenuCreateBody(BaseModel):
    """创建菜单请求体."""

    name: str = Field(min_length=1, max_length=128)
    parent_id: Optional[str] = None
    menu_type: str = "menu"
    path: str = ""
    component: str = ""
    icon: str = ""
    perm_code: str = ""
    sort_order: int = 0
    is_visible: bool = True
    is_enabled: bool = True
    is_external: bool = False
    redirect: str = ""


class MenuUpdateBody(BaseModel):
    """更新菜单请求体（部分字段）."""

    name: Optional[str] = None
    parent_id: Optional[str] = None
    menu_type: Optional[str] = None
    path: Optional[str] = None
    component: Optional[str] = None
    icon: Optional[str] = None
    perm_code: Optional[str] = None
    sort_order: Optional[int] = None
    is_visible: Optional[bool] = None
    is_enabled: Optional[bool] = None
    is_external: Optional[bool] = None
    redirect: Optional[str] = None


class RoleMenusBody(BaseModel):
    """全量设置角色菜单请求体."""

    menu_ids: List[str] = Field(default_factory=list)


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
async def get_menu_tree() -> list:
    """获取菜单树（嵌套结构）."""
    store = _require_store()
    tree = store.get_menu_tree()
    return [asdict(m) for m in tree]


@router.get("/flat")
async def get_menu_flat() -> list:
    """获取菜单平铺列表."""
    store = _require_store()
    menus = store.list_menus()
    return [asdict(m) for m in menus]


@router.get("/role/{role_id}")
async def get_role_menus(role_id: str) -> list:
    """获取角色已分配的菜单 ID 列表."""
    store = _require_store()
    return store.get_role_menus(role_id)


@router.put("/role/{role_id}")
async def assign_role_menus(role_id: str, body: RoleMenusBody) -> dict:
    """全量设置角色菜单."""
    store = _require_store()
    if not store.assign_role_menus(role_id, body.menu_ids):
        raise HTTPException(
            status_code=400,
            detail="assign role menus failed",
        )
    return {"ok": True, "role_id": role_id, "menu_ids": body.menu_ids}


@router.post("/reseed")
async def reseed_default_menus() -> dict:
    """强制重置菜单为内置 seed 结构（覆盖当前所有菜单编辑）。

    启动 seed 已改为仅补齐不覆盖（DO NOTHING），菜单结构调整后需靠本
    入口把线上 rbac_menus 同步到最新内置定义。
    """
    _require_store()
    from ...rbac.seed import reseed_menus

    if not reseed_menus():
        raise HTTPException(
            status_code=500,
            detail="menu reseed failed (see server log)",
        )
    return {"ok": True}


@router.post("", status_code=201)
async def create_menu(body: MenuCreateBody) -> dict:
    """创建菜单."""
    store = _require_store()
    record = store.create_menu(
        body.name,
        parent_id=body.parent_id,
        menu_type=body.menu_type,
        path=body.path,
        component=body.component,
        icon=body.icon,
        perm_code=body.perm_code,
        sort_order=body.sort_order,
        is_visible=body.is_visible,
        is_enabled=body.is_enabled,
        is_external=body.is_external,
        redirect=body.redirect,
    )
    if record is None:
        raise HTTPException(
            status_code=400,
            detail="create menu failed (invalid payload)",
        )
    return asdict(record)


@router.patch("/{menu_id}")
async def update_menu(menu_id: str, body: MenuUpdateBody) -> dict:
    """更新菜单（部分字段）."""
    store = _require_store()
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    record = store.update_menu(menu_id, **fields)
    if record is None:
        raise HTTPException(status_code=404, detail="menu not found")
    return asdict(record)


@router.delete("/{menu_id}", status_code=204)
async def delete_menu(menu_id: str) -> None:
    """删除菜单（级联删除子菜单）."""
    store = _require_store()
    if not store.delete_menu(menu_id):
        raise HTTPException(status_code=404, detail="menu not found")
