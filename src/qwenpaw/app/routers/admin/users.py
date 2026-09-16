# -*- coding: utf-8 -*-
"""Admin user management API (M4): accounts + role grants.

All routes require ``admin:users`` when ``QWENPAW_RBAC_ENFORCE`` is on.
Password material never leaves the store: responses carry a redacted
view of :class:`UserRecord`.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...rbac import PERM_ADMIN_USERS, require_perm
from ...users.models import ROLE_ADMIN, VALID_ROLES
from ...users.store import get_user_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/users",
    tags=["admin-users"],
    dependencies=[Depends(require_perm(PERM_ADMIN_USERS))],
)


class UserView(BaseModel):
    """Redacted user record for admin listing (no password fields)."""

    username: str
    role: str
    display_name: str = ""
    # 头像 URL（空 = 前端 DiceBear 兑底）。
    avatar: str = ""
    disabled: bool = False
    created_at: str = ""
    org_id: str = "default"
    rbac_roles: List[str] = Field(default_factory=list)
    teams: List[str] = Field(default_factory=list)


class CreateUserBody(BaseModel):
    username: str
    password: str
    role: str = "employee"
    display_name: str = ""
    org_id: str = "default"


class UpdateUserBody(BaseModel):
    disabled: Optional[bool] = None
    role: Optional[str] = None
    display_name: Optional[str] = None
    org_id: Optional[str] = None


class PasswordBody(BaseModel):
    password: str


class RoleGrantBody(BaseModel):
    role: str


def _view(username: str) -> UserView:
    store = get_user_store()
    user = store.get_user(username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    from ...rbac.store import get_rbac_store

    rbac = get_rbac_store()
    return UserView(
        username=user.username,
        role=user.role,
        display_name=user.display_name,
        avatar=user.avatar,
        disabled=user.disabled,
        created_at=user.created_at.isoformat(),
        org_id=user.org_id,
        rbac_roles=rbac.roles_for_user(user.username, user.role),
        teams=rbac.teams_for_user(user.username),
    )


@router.get("", response_model=List[UserView])
async def list_users() -> List[UserView]:
    """List all accounts (redacted)."""
    return [_view(u.username) for u in get_user_store().list_users()]


@router.post("", status_code=201, response_model=UserView)
async def create_user(body: CreateUserBody) -> UserView:
    """Create an account. Only flat roles are accepted here; finer
    grants go through the RBAC role endpoints."""
    if body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"role must be one of {sorted(VALID_ROLES)}",
        )
    record = get_user_store().create_user(
        body.username,
        body.password,
        role=body.role,
        display_name=body.display_name,
        org_id=body.org_id,
    )
    if record is None:
        raise HTTPException(
            status_code=409,
            detail="User exists or invalid payload",
        )
    return _view(record.username)


def _guard_self_lockout(
    request: Request,
    username: str,
    body: UpdateUserBody,
) -> None:
    """Never let an admin disable or demote *themselves* — the deployment
    must always retain at least one interactive admin."""
    actor = getattr(request.state, "user", None) or ""
    if actor != username:
        return
    if body.disabled is True:
        raise HTTPException(
            status_code=400,
            detail="Refusing to disable your own admin account",
        )
    if body.role is not None and body.role != ROLE_ADMIN:
        raise HTTPException(
            status_code=400,
            detail="Refusing to demote your own admin account",
        )


@router.patch("/{username}", response_model=UserView)
async def update_user(
    username: str,
    body: UpdateUserBody,
    request: Request,
) -> UserView:
    """Update disabled/role/display_name flags of one account."""
    store = get_user_store()
    if store.get_user(username) is None:
        raise HTTPException(status_code=404, detail="User not found")
    _guard_self_lockout(request, username, body)
    if body.role is not None:
        if body.role not in VALID_ROLES:
            raise HTTPException(
                status_code=400,
                detail=f"role must be one of {sorted(VALID_ROLES)}",
            )
        if not store.set_role(username, body.role):
            raise HTTPException(status_code=400, detail="role update failed")
    if body.disabled is not None:
        if not store.set_disabled(username, body.disabled):
            raise HTTPException(status_code=400, detail="disable failed")
    if body.display_name is not None:
        if not store.set_display_name(username, body.display_name):
            raise HTTPException(
                status_code=400,
                detail="display_name update failed",
            )
    if body.org_id is not None:
        if not store.set_org_id(username, body.org_id):
            raise HTTPException(
                status_code=400,
                detail="org_id update failed",
            )
    return _view(username)


# ── Channel identity bindings（渠道外部身份 → 账号绑定管理）──
# 静态路径必须注册在 GET /{username} 之前，否则会被动态段吞掉。


class IdentityBindingView(BaseModel):
    """One channel-identity → account binding row."""

    channel: str
    external_user_id: str
    username: str


class IdentityBindingBody(BaseModel):
    """Create-one-binding request."""

    channel: str = Field(min_length=1, max_length=32)
    external_user_id: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=64)


@router.get("/identity-bindings", response_model=List[IdentityBindingView])
async def list_identity_bindings() -> List[IdentityBindingView]:
    """List all channel identity bindings（绑定管理页数据源）。"""
    rows = get_user_store().list_identity_bindings()
    return [IdentityBindingView(**row) for row in rows]


@router.post(
    "/identity-bindings",
    status_code=201,
    response_model=IdentityBindingView,
)
async def create_identity_binding(
    body: IdentityBindingBody,
) -> IdentityBindingView:
    """Bind one channel identity to a registered account."""
    if not get_user_store().bind_identity(
        body.channel.strip(),
        body.external_user_id.strip(),
        body.username.strip(),
    ):
        raise HTTPException(
            status_code=400,
            detail="binding failed (unknown user or invalid payload)",
        )
    return IdentityBindingView(
        channel=body.channel.strip(),
        external_user_id=body.external_user_id.strip(),
        username=body.username.strip(),
    )


@router.delete(
    "/identity-bindings/{channel}/{external_user_id}",
    status_code=204,
)
async def delete_identity_binding(
    channel: str,
    external_user_id: str,
) -> None:
    """Remove one channel identity binding."""
    if not get_user_store().unbind_identity(channel, external_user_id):
        raise HTTPException(status_code=404, detail="Binding not found")


@router.post("/{username}/password", status_code=204)
async def reset_password(username: str, body: PasswordBody) -> None:
    """Reset one account's password (argon2id re-hash)."""
    if not get_user_store().update_password(username, body.password):
        raise HTTPException(
            status_code=400,
            detail="password reset failed (unknown user or empty password)",
        )


@router.get("/{username}", response_model=UserView)
async def get_user(username: str) -> UserView:
    """One account with its resolved RBAC roles and teams."""
    return _view(username)


@router.post("/{username}/roles", status_code=204)
async def grant_role(username: str, body: RoleGrantBody) -> None:
    """Additively grant an RBAC role to the account."""
    from ...rbac.store import get_rbac_store

    if get_user_store().get_user(username) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not get_rbac_store().grant_role(username, body.role):
        raise HTTPException(status_code=400, detail="unknown role")


@router.delete("/{username}/roles/{role}", status_code=204)
async def revoke_role(username: str, role: str) -> None:
    """Revoke one explicit RBAC role grant."""
    from ...rbac.store import get_rbac_store

    if not get_rbac_store().revoke_role(username, role):
        raise HTTPException(status_code=404, detail="grant not found")
