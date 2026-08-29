# -*- coding: utf-8 -*-
"""FastAPI dependencies for RBAC enforcement (M4).

``require_perm("resource:action")`` returns a dependency that rejects the
request with 403 unless the authenticated user holds the permission.
Enforcement is gated by ``QWENPAW_RBAC_ENFORCE``:

- **off** (default): every check passes — zero behavior change, routes
  can be annotated incrementally without risk;
- **on**: annotated routes enforce; unannotated routes stay open
  (per the M4 plan's gray-rollout semantics).

The identity comes from ``request.state.user`` (populated by
``AuthMiddleware`` after token verification) and the flat M1 role from
the user store, which keeps the bootstrap guarantee: a flat ``admin``
always passes, so RBAC can never lock operators out.
"""
from __future__ import annotations

import logging
from typing import Callable

from fastapi import HTTPException, Request

from ...constant import EnvVarLoader
from .store import get_rbac_store

logger = logging.getLogger(__name__)

RBAC_ENFORCE_ENV = "QWENPAW_RBAC_ENFORCE"


def rbac_enforcement_enabled() -> bool:
    """Whether ``require_perm`` actually rejects.

    默认值跟随认证开关（Governance Engine 的存在前提）：

    - ``QWENPAW_RBAC_ENFORCE`` 显式配置时以其为准（灰度微调仍可用）；
    - 未配置时：认证开启（多用户/企业部署）→ **默认强制**；认证关闭
      （本机单机桌面模式）→ 默认关闭。企业平面在多用户部署下不再
      依赖运维记得手动打开开关。
    """
    # 显式配置优先（true/on/1 开；false/off/0 关）
    explicit = EnvVarLoader.get_str(RBAC_ENFORCE_ENV, "").strip().lower()
    if explicit in ("1", "true", "on", "yes"):
        return True
    if explicit in ("0", "false", "off", "no"):
        return False
    # 未显式配置：跟随认证开关（延迟导入防循环依赖）
    try:
        from ..auth import is_auth_enabled

        return is_auth_enabled()
    except Exception:  # pylint: disable=broad-except
        return False


def _resolve_flat_role(username: str) -> str:
    """Look up the M1 flat role for *username* ("" when unknown)."""
    try:
        from ..users.store import get_user_store

        user = get_user_store().get_user(username)
        return user.role if user is not None else ""
    except Exception:  # pylint: disable=broad-except
        logger.debug("rbac: flat-role lookup failed", exc_info=True)
        return ""


def require_perm(permission: str) -> Callable:
    """Build a FastAPI dependency enforcing *permission* on this route.

    Usage::

        @router.get("/admin/users",
                    dependencies=[Depends(require_perm("admin:users"))])
    """

    async def _dependency(request: Request) -> None:
        if not rbac_enforcement_enabled():
            return
        username = getattr(request.state, "user", None) or ""
        if not username:
            # AuthMiddleware normally guarantees an identity; without one
            # (e.g. loopback whitelist bypass) fail closed under enforce.
            raise HTTPException(
                status_code=403,
                detail="RBAC: no authenticated identity",
            )
        flat_role = _resolve_flat_role(username)
        if get_rbac_store().user_has_permission(
            username,
            permission,
            flat_role=flat_role,
        ):
            return
        logger.warning(
            "rbac deny: user=%r permission=%r path=%s",
            username,
            permission,
            request.url.path,
        )
        raise HTTPException(
            status_code=403,
            detail=f"Missing permission: {permission}",
        )

    return _dependency
