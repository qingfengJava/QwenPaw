# -*- coding: utf-8 -*-
"""Admin RBAC role management API (M4)."""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...rbac import PERM_ADMIN_ROLES, require_perm
from ...rbac.models import RoleRecord
from ...rbac.store import get_rbac_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/roles",
    tags=["admin-roles"],
    dependencies=[Depends(require_perm(PERM_ADMIN_ROLES))],
)


class RoleBody(BaseModel):
    permissions: List[str] = Field(default_factory=list)
    description: str = ""
    display_name: str = ""


class RoleMemberView(BaseModel):
    """One member row for the 角色-员工列表 tab."""

    username: str
    real_name: str = ""
    phone: str = ""
    display_name: str = ""
    disabled: bool = False
    department_names: List[str] = Field(default_factory=list)


@router.get("", response_model=List[RoleRecord])
async def list_roles() -> List[RoleRecord]:
    """List all roles (built-in and custom).

    角色定义取自文件 store；若 PG 平面可用，则按角色名合并其
    ``display_name``/``data_scope``/``sort_order``（内置角色中文名由 seed
    写入 PG rbac_roles，文件 store 不持久化这些展示字段）。
    """
    roles = get_rbac_store().list_roles()
    try:
        from ...rbac.store_pg import get_pg_rbac_store

        pg = get_pg_rbac_store()
    except Exception:  # pylint: disable=broad-except
        pg = None
    if pg is not None:
        try:
            pg_roles = {r.name: r for r in pg.list_roles()}
        except Exception:  # pylint: disable=broad-except
            pg_roles = {}
        for role in roles:
            src = pg_roles.get(role.name)
            if src is None:
                continue
            if not role.display_name:
                role.display_name = src.display_name
            if not role.description or role.description == "built-in role":
                role.description = src.description or role.description
            role.data_scope = src.data_scope or role.data_scope
            role.sort_order = src.sort_order
    return roles


@router.get("/{name}/users", response_model=List[RoleMemberView])
async def list_role_users(name: str) -> List[RoleMemberView]:
    """Members holding one RBAC role (角色-员工列表 tab).

    Resolves the grant set from the PG RBAC store (authoritative plane,
    matched by role *name*); falls back to the file store's reverse
    lookup when PG is unavailable. Profile + department names are
    batch-assembled (no N+1).
    """
    usernames: List[str] = []
    from ...rbac.store_pg import get_pg_rbac_store
    from ...users.store import get_user_store

    pg_store = get_pg_rbac_store()
    if pg_store is not None:
        usernames = pg_store.get_role_users(name)
    if not usernames:
        # 文件回退：扫描全部账号的角色解析结果反查成员。
        rbac = get_rbac_store()

        for user in get_user_store().list_users():
            if name in rbac.roles_for_user(user.username, user.role):
                usernames.append(user.username)

    store = get_user_store()
    users = [store.get_user(u) for u in usernames]
    users = [u for u in users if u is not None]
    views = [
        RoleMemberView(
            username=u.username,
            real_name=u.real_name,
            phone=u.phone,
            display_name=u.display_name,
            disabled=u.disabled,
        )
        for u in users
    ]
    # 部门名批量组装（PG 部门平面，失败降级为空）。
    if views:
        try:
            from ...orgs.service import get_org_service

            grouped = await get_org_service().department_names_by_users(
                [v.username for v in views],
            )
            for view in views:
                view.department_names = grouped.get(view.username, [])
        except Exception:  # pylint: disable=broad-except
            logger.debug(
                "role members: department names unavailable",
                exc_info=True,
            )
    return views


@router.put("/{name}", response_model=RoleRecord)
async def upsert_role(name: str, body: RoleBody) -> RoleRecord:
    """Create or replace a custom role. Built-in roles are immutable."""
    record = get_rbac_store().upsert_role(
        name,
        body.permissions,
        description=body.description,
        display_name=body.display_name,
    )
    if record is None:
        raise HTTPException(
            status_code=400,
            detail="invalid name or attempt to modify a built-in role",
        )
    return record


@router.delete("/{name}", status_code=204)
async def delete_role(name: str) -> None:
    """Delete a custom role (also strips it from all user grants)."""
    if not get_rbac_store().delete_role(name):
        raise HTTPException(
            status_code=404,
            detail="role not found or built-in",
        )
