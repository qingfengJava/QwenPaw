# -*- coding: utf-8 -*-
"""PostgreSQL-backed RBAC store (M5 权限体系 PG 权威存储).

与 :class:`store.RbacStore` 方法集兼容（鸭子类型同接口），并扩展了
PG 独有的菜单、数据范围、细粒度权限等能力。

架构严格参照 :mod:`qwenpaw.app.users.store_pg`：
- 后台 asyncio event loop 线程 + ``run_coroutine_threadsafe`` 桥接同步调用；
- 30s TTL 内存缓存（热路径：has_permission / get_user_permissions 等）；
- fail-closed 语义：存储不可读时权限校验返回 False。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import shortuuid

from ...db.engine import create_pg_engine
from .models import (
    BUILTIN_ROLE_PERMISSIONS,
    DataScopeRecord,
    MenuRecord,
    PermissionRecord,
    RbacFile,
    RoleRecord,
    TeamRecord,
)
from .permissions import has_permission as _match_permission

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 30.0
_BRIDGE_TIMEOUT_SECONDS = 10.0
_TENANT = "default"


class _MissSentinel:
    """Unique sentinel for cache miss (distinct from None)."""
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover
        return "<MISS>"


_MISS = _MissSentinel()


def _uid() -> str:
    """Generate a short unique ID (VARCHAR(64) safe)."""
    return shortuuid.uuid()


class PgRbacStore:
    """PG-backed implementation of the RBAC store contract."""

    def __init__(self, engine=None) -> None:
        self._engine = engine
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._loop_lock = threading.Lock()
        # TTL cache: key -> (monotonic_ts, value)
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._cache_lock = threading.Lock()

    # ------------------------------------------------------------------
    # async bridge (dedicated background loop)
    # ------------------------------------------------------------------

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._loop_lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop
            loop = asyncio.new_event_loop()

            def _run_loop() -> None:
                asyncio.set_event_loop(loop)
                loop.run_forever()

            self._loop_thread = threading.Thread(
                target=_run_loop,
                name="qwenpaw-rbac-store-pg",
                daemon=True,
            )
            self._loop_thread.start()
            self._loop = loop
            return loop

    def _run(self, coro) -> Any:
        loop = self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(coro, loop).result(
            timeout=_BRIDGE_TIMEOUT_SECONDS,
        )

    def _get_engine(self):
        if self._engine is None:
            # 专属引擎：本 store 的连接只在其后台桥接循环上创建/复用，
            # 避免与主循环（迁移 / orgs）共享引擎导致跨循环污染。
            self._engine = create_pg_engine(dedicated=True)
        return self._engine

    # ------------------------------------------------------------------
    # TTL cache helpers
    # ------------------------------------------------------------------

    def _cache_get(self, key: str) -> Any:
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return _MISS
            ts, value = entry
            if time.monotonic() - ts >= _CACHE_TTL_SECONDS:
                del self._cache[key]
                return _MISS
            return value

    def _cache_set(self, key: str, value: Any) -> None:
        with self._cache_lock:
            self._cache[key] = (time.monotonic(), value)

    def _invalidate(self) -> None:
        """Drop all caches after a write."""
        with self._cache_lock:
            self._cache.clear()

    # ------------------------------------------------------------------
    # readiness
    # ------------------------------------------------------------------

    def ensure_ready(self) -> bool:
        """Verify RBAC tables exist. Returns False if migration not run."""
        try:
            self._run(self._ensure_tables_async())
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg rbac tables not ready", exc_info=True)
            return False
        return True

    async def _ensure_tables_async(self) -> None:
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            for tbl in (
                "rbac_roles", "rbac_permissions", "rbac_user_roles",
                "rbac_menus", "rbac_teams",
            ):
                row = (
                    await conn.execute(
                        text(f"SELECT to_regclass('public.{tbl}')"),
                    )
                ).fetchone()
                if row is None or row[0] is None:
                    raise RuntimeError(
                        f"{tbl} missing (run alembic upgrade)",
                    )

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    async def _ensure_permission_async(self, conn, code: str) -> str:
        """Return permission_id for *code*, creating the row if absent."""
        from sqlalchemy import text

        row = (
            await conn.execute(
                text(
                    "SELECT id FROM rbac_permissions "
                    "WHERE tenant_id = :tid AND code = :code",
                ),
                {"tid": _TENANT, "code": code},
            )
        ).fetchone()
        if row is not None:
            return str(row[0])
        pid = _uid()
        resource, _, action = code.partition(":")
        await conn.execute(
            text(
                "INSERT INTO rbac_permissions "
                "(id, code, name, resource, action, perm_type) "
                "VALUES (:id, :code, :code, :res, :act, 'api') "
                "ON CONFLICT (tenant_id, code) DO NOTHING",
            ),
            {"id": pid, "code": code,
             "res": resource, "act": action or code},
        )
        row = (
            await conn.execute(
                text(
                    "SELECT id FROM rbac_permissions "
                    "WHERE tenant_id = :tid AND code = :code",
                ),
                {"tid": _TENANT, "code": code},
            )
        ).fetchone()
        return str(row[0]) if row else pid

    @staticmethod
    def _row_to_menu(row) -> MenuRecord:
        return MenuRecord(
            id=str(row[0]),
            parent_id=str(row[1]) if row[1] else None,
            name=str(row[2] or ""),
            menu_type=str(row[3] or "menu"),
            path=str(row[4] or ""),
            component=str(row[5] or ""),
            icon=str(row[6] or ""),
            perm_code=str(row[7] or ""),
            sort_order=int(row[8] or 0),
            is_visible=bool(row[9]),
            is_enabled=bool(row[10]),
            is_external=bool(row[11]),
            redirect=str(row[12] or ""),
        )

    @staticmethod
    def _build_tree(menus: List[MenuRecord]) -> List[MenuRecord]:
        by_id = {m.id: m for m in menus}
        roots: List[MenuRecord] = []
        for m in menus:
            m.children = []
        for m in menus:
            if m.parent_id and m.parent_id in by_id:
                by_id[m.parent_id].children.append(m)
            else:
                roots.append(m)
        return roots

    # Scope-type priority (higher = more permissive).
    _SCOPE_PRI = {
        "all": 4, "dept_and_child": 3, "dept": 2, "custom": 1, "self": 0,
    }

    # ==================================================================
    # Role management
    # ==================================================================

    def list_roles(self) -> List[RoleRecord]:
        try:
            return self._run(self._list_roles_async())
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg list_roles failed", exc_info=True)
            return []

    async def _list_roles_async(self) -> List[RoleRecord]:
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT r.id, r.name, r.description, r.is_builtin, "
                        "r.display_name, r.data_scope, r.sort_order, p.code "
                        "FROM rbac_roles r "
                        "LEFT JOIN rbac_role_permissions rp "
                        "  ON rp.tenant_id = r.tenant_id "
                        "  AND rp.role_id = r.id "
                        "LEFT JOIN rbac_permissions p "
                        "  ON p.tenant_id = rp.tenant_id "
                        "  AND p.id = rp.permission_id "
                        "WHERE r.tenant_id = :tid AND r.is_enabled = TRUE "
                        "ORDER BY r.sort_order, r.name",
                    ),
                    {"tid": _TENANT},
                )
            ).fetchall()
        roles: Dict[str, RoleRecord] = {}
        for row in rows:
            rid = str(row[0])
            if rid not in roles:
                roles[rid] = RoleRecord(
                    name=str(row[1]),
                    permissions=[],
                    builtin=bool(row[3]),
                    description=str(row[2] or ""),
                    display_name=str(row[4] or ""),
                    data_scope=str(row[5] or "self"),
                    sort_order=int(row[6] or 0),
                )
            if row[7]:
                roles[rid].permissions.append(str(row[7]))
        return list(roles.values())

    def get_role(self, name: str) -> Optional[RoleRecord]:
        try:
            return self._run(self._get_role_async(name))
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg get_role failed", exc_info=True)
            return None

    async def _get_role_async(self, name: str) -> Optional[RoleRecord]:
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id, name, description, is_builtin "
                        "FROM rbac_roles "
                        "WHERE tenant_id = :tid AND name = :name "
                        "AND is_enabled = TRUE",
                    ),
                    {"tid": _TENANT, "name": name},
                )
            ).fetchone()
            if row is None:
                return None
            rid = str(row[0])
            perm_rows = (
                await conn.execute(
                    text(
                        "SELECT p.code FROM rbac_role_permissions rp "
                        "JOIN rbac_permissions p "
                        "  ON p.tenant_id = rp.tenant_id "
                        "  AND p.id = rp.permission_id "
                        "WHERE rp.tenant_id = :tid AND rp.role_id = :rid",
                    ),
                    {"tid": _TENANT, "rid": rid},
                )
            ).fetchall()
        return RoleRecord(
            name=str(row[1]),
            permissions=[str(pr[0]) for pr in perm_rows],
            builtin=bool(row[3]),
            description=str(row[2] or ""),
        )

    def create_role(
        self,
        name: str,
        display_name: str = "",
        description: str = "",
        permissions: Optional[List[str]] = None,
        data_scope: str = "self",
    ) -> Optional[RoleRecord]:
        name = name.strip()
        if not name:
            return None
        try:
            record = self._run(
                self._create_role_async(
                    name, display_name, description,
                    permissions or [], data_scope,
                ),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg create_role failed", exc_info=True)
            return None
        self._invalidate()
        return record

    async def _create_role_async(
        self, name: str, display_name: str, description: str,
        permissions: List[str], data_scope: str,
    ) -> RoleRecord:
        from sqlalchemy import text

        rid = _uid()
        async with self._get_engine().begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO rbac_roles "
                    "(id, name, display_name, description, "
                    "is_builtin, data_scope) "
                    "VALUES (:id, :name, :dn, :desc, FALSE, :ds)",
                ),
                {"id": rid, "name": name, "dn": display_name,
                 "desc": description, "ds": data_scope},
            )
            for code in permissions:
                pid = await self._ensure_permission_async(conn, code)
                await conn.execute(
                    text(
                        "INSERT INTO rbac_role_permissions "
                        "(role_id, permission_id) "
                        "VALUES (:rid, :pid) ON CONFLICT DO NOTHING",
                    ),
                    {"rid": rid, "pid": pid},
                )
        return RoleRecord(
            name=name, permissions=list(permissions),
            builtin=False, description=description,
        )

    def update_role(self, name: str, **fields) -> Optional[RoleRecord]:
        try:
            record = self._run(self._update_role_async(name, fields))
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg update_role failed", exc_info=True)
            return None
        if record is not None:
            self._invalidate()
        return record

    async def _update_role_async(
        self, name: str, fields: dict,
    ) -> Optional[RoleRecord]:
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id, is_builtin FROM rbac_roles "
                        "WHERE tenant_id = :tid AND name = :name",
                    ),
                    {"tid": _TENANT, "name": name},
                )
            ).fetchone()
            if row is None:
                return None
            if bool(row[1]):
                logger.warning(
                    "Refusing to modify built-in role '%s'", name,
                )
                return None
            rid = str(row[0])
            updatable = {
                "display_name", "description", "data_scope",
                "sort_order", "is_enabled",
            }
            sets = {k: v for k, v in fields.items() if k in updatable}
            if sets:
                clause = ", ".join(f"{k} = :{k}" for k in sets)
                await conn.execute(
                    text(
                        f"UPDATE rbac_roles SET {clause}, "
                        "updated_at = now() "
                        "WHERE tenant_id = :tid AND id = :rid",
                    ),
                    {**sets, "tid": _TENANT, "rid": rid},
                )
            if "permissions" in fields:
                await conn.execute(
                    text(
                        "DELETE FROM rbac_role_permissions "
                        "WHERE tenant_id = :tid AND role_id = :rid",
                    ),
                    {"tid": _TENANT, "rid": rid},
                )
                for code in fields["permissions"]:
                    pid = await self._ensure_permission_async(conn, code)
                    await conn.execute(
                        text(
                            "INSERT INTO rbac_role_permissions "
                            "(role_id, permission_id) "
                            "VALUES (:rid, :pid) "
                            "ON CONFLICT DO NOTHING",
                        ),
                        {"rid": rid, "pid": pid},
                    )
        return await self._get_role_async(name)

    def delete_role(self, name: str) -> bool:
        try:
            deleted = self._run(self._delete_role_async(name))
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg delete_role failed", exc_info=True)
            return False
        if deleted:
            self._invalidate()
        return deleted

    async def _delete_role_async(self, name: str) -> bool:
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id, is_builtin FROM rbac_roles "
                        "WHERE tenant_id = :tid AND name = :name",
                    ),
                    {"tid": _TENANT, "name": name},
                )
            ).fetchone()
            if row is None or bool(row[1]):
                return False
            rid = str(row[0])
            for tbl in (
                "rbac_role_permissions", "rbac_user_roles",
                "rbac_role_menus", "rbac_data_scopes",
            ):
                await conn.execute(
                    text(
                        f"DELETE FROM {tbl} "
                        "WHERE tenant_id = :tid AND role_id = :rid",
                    ),
                    {"tid": _TENANT, "rid": rid},
                )
            await conn.execute(
                text(
                    "DELETE FROM rbac_roles "
                    "WHERE tenant_id = :tid AND id = :rid",
                ),
                {"tid": _TENANT, "rid": rid},
            )
        return True

    def get_role_permissions(self, role_id: str) -> List[str]:
        try:
            return self._run(self._get_role_permissions_async(role_id))
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "pg get_role_permissions failed", exc_info=True,
            )
            return []

    async def _get_role_permissions_async(self, role_id: str) -> List[str]:
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT p.code FROM rbac_role_permissions rp "
                        "JOIN rbac_permissions p "
                        "  ON p.tenant_id = rp.tenant_id "
                        "  AND p.id = rp.permission_id "
                        "WHERE rp.tenant_id = :tid "
                        "AND rp.role_id = :rid",
                    ),
                    {"tid": _TENANT, "rid": role_id},
                )
            ).fetchall()
        return [str(r[0]) for r in rows]

    # ==================================================================
    # Permission management
    # ==================================================================

    def list_permissions(self) -> List[PermissionRecord]:
        try:
            return self._run(self._list_permissions_async())
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg list_permissions failed", exc_info=True)
            return []

    async def _list_permissions_async(self) -> List[PermissionRecord]:
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, code, name, resource, action, "
                        "perm_type, description "
                        "FROM rbac_permissions "
                        "WHERE tenant_id = :tid ORDER BY code",
                    ),
                    {"tid": _TENANT},
                )
            ).fetchall()
        return [
            PermissionRecord(
                id=str(r[0]), code=str(r[1]), name=str(r[2] or ""),
                resource=str(r[3] or ""), action=str(r[4] or ""),
                perm_type=str(r[5] or "api"),
                description=str(r[6] or ""),
            )
            for r in rows
        ]

    def create_permission(
        self, code: str, name: str = "", resource: str = "",
        action: str = "", perm_type: str = "api", description: str = "",
    ) -> Optional[PermissionRecord]:
        code = code.strip()
        if not code:
            return None
        res = resource or code.split(":")[0]
        act = action or (code.split(":")[1] if ":" in code else code)
        try:
            rec = self._run(
                self._create_permission_async(
                    code, name or code, res, act, perm_type, description,
                ),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg create_permission failed", exc_info=True)
            return None
        self._invalidate()
        return rec

    async def _create_permission_async(
        self, code: str, name: str, resource: str,
        action: str, perm_type: str, description: str,
    ) -> PermissionRecord:
        from sqlalchemy import text

        pid = _uid()
        async with self._get_engine().begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO rbac_permissions "
                    "(id, code, name, resource, action, "
                    "perm_type, description) "
                    "VALUES (:id, :code, :name, :res, :act, :pt, :desc) "
                    "ON CONFLICT (tenant_id, code) DO UPDATE SET "
                    "name = EXCLUDED.name, resource = EXCLUDED.resource, "
                    "action = EXCLUDED.action, "
                    "perm_type = EXCLUDED.perm_type, "
                    "description = EXCLUDED.description",
                ),
                {"id": pid, "code": code, "name": name,
                 "res": resource, "act": action,
                 "pt": perm_type, "desc": description},
            )
            row = (
                await conn.execute(
                    text(
                        "SELECT id FROM rbac_permissions "
                        "WHERE tenant_id = :tid AND code = :code",
                    ),
                    {"tid": _TENANT, "code": code},
                )
            ).fetchone()
            if row:
                pid = str(row[0])
        return PermissionRecord(
            id=pid, code=code, name=name, resource=resource,
            action=action, perm_type=perm_type, description=description,
        )

    def update_permission(
        self, perm_id: str, **fields,
    ) -> Optional[PermissionRecord]:
        try:
            rec = self._run(
                self._update_permission_async(perm_id, fields),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg update_permission failed", exc_info=True)
            return None
        if rec is not None:
            self._invalidate()
        return rec

    async def _update_permission_async(
        self, perm_id: str, fields: dict,
    ) -> Optional[PermissionRecord]:
        from sqlalchemy import text

        updatable = {
            "code", "name", "resource", "action",
            "perm_type", "description",
        }
        sets = {k: v for k, v in fields.items() if k in updatable}
        if not sets:
            return None
        clause = ", ".join(f"{k} = :{k}" for k in sets)
        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    f"UPDATE rbac_permissions SET {clause} "
                    "WHERE tenant_id = :tid AND id = :pid",
                ),
                {**sets, "tid": _TENANT, "pid": perm_id},
            )
            if not result.rowcount:
                return None
            row = (
                await conn.execute(
                    text(
                        "SELECT id, code, name, resource, action, "
                        "perm_type, description "
                        "FROM rbac_permissions "
                        "WHERE tenant_id = :tid AND id = :pid",
                    ),
                    {"tid": _TENANT, "pid": perm_id},
                )
            ).fetchone()
        if row is None:
            return None
        return PermissionRecord(
            id=str(row[0]), code=str(row[1]), name=str(row[2] or ""),
            resource=str(row[3] or ""), action=str(row[4] or ""),
            perm_type=str(row[5] or "api"),
            description=str(row[6] or ""),
        )

    def delete_permission(self, perm_id: str) -> bool:
        try:
            deleted = self._run(
                self._delete_permission_async(perm_id),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg delete_permission failed", exc_info=True)
            return False
        if deleted:
            self._invalidate()
        return deleted

    async def _delete_permission_async(self, perm_id: str) -> bool:
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM rbac_role_permissions "
                    "WHERE tenant_id = :tid AND permission_id = :pid",
                ),
                {"tid": _TENANT, "pid": perm_id},
            )
            result = await conn.execute(
                text(
                    "DELETE FROM rbac_permissions "
                    "WHERE tenant_id = :tid AND id = :pid",
                ),
                {"tid": _TENANT, "pid": perm_id},
            )
        return bool(result.rowcount)

    def assign_role_permissions(
        self, role_id: str, permission_ids: List[str],
    ) -> bool:
        try:
            self._run(
                self._assign_role_perms_async(role_id, permission_ids),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "pg assign_role_permissions failed", exc_info=True,
            )
            return False
        self._invalidate()
        return True

    async def _assign_role_perms_async(
        self, role_id: str, permission_ids: List[str],
    ) -> None:
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM rbac_role_permissions "
                    "WHERE tenant_id = :tid AND role_id = :rid",
                ),
                {"tid": _TENANT, "rid": role_id},
            )
            for pid in permission_ids:
                await conn.execute(
                    text(
                        "INSERT INTO rbac_role_permissions "
                        "(role_id, permission_id) "
                        "VALUES (:rid, :pid) "
                        "ON CONFLICT DO NOTHING",
                    ),
                    {"rid": role_id, "pid": pid},
                )

    # ==================================================================
    # User-role binding
    # ==================================================================

    def get_user_roles(self, username: str) -> List[str]:
        cached = self._cache_get(f"ur:{username}")
        if cached is not _MISS:
            return cached  # type: ignore[return-value]
        try:
            roles = self._run(self._get_user_roles_async(username))
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg get_user_roles failed", exc_info=True)
            return []
        self._cache_set(f"ur:{username}", roles)
        return roles

    async def _get_user_roles_async(self, username: str) -> List[str]:
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT r.name FROM rbac_user_roles ur "
                        "JOIN rbac_roles r "
                        "  ON r.tenant_id = ur.tenant_id "
                        "  AND r.id = ur.role_id "
                        "WHERE ur.tenant_id = :tid "
                        "AND ur.username = :u "
                        "AND r.is_enabled = TRUE",
                    ),
                    {"tid": _TENANT, "u": username},
                )
            ).fetchall()
        return [str(r[0]) for r in rows]

    def assign_user_role(self, username: str, role_name: str) -> bool:
        if not username or not role_name:
            return False
        try:
            ok = self._run(
                self._assign_user_role_async(username, role_name),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg assign_user_role failed", exc_info=True)
            return False
        if ok:
            self._invalidate()
        return ok

    async def _assign_user_role_async(
        self, username: str, role_name: str,
    ) -> bool:
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id FROM rbac_roles "
                        "WHERE tenant_id = :tid AND name = :n",
                    ),
                    {"tid": _TENANT, "n": role_name},
                )
            ).fetchone()
            if row is None:
                return False
            await conn.execute(
                text(
                    "INSERT INTO rbac_user_roles (username, role_id) "
                    "VALUES (:u, :rid) ON CONFLICT DO NOTHING",
                ),
                {"u": username, "rid": str(row[0])},
            )
        return True

    def revoke_user_role(self, username: str, role_name: str) -> bool:
        try:
            ok = self._run(
                self._revoke_user_role_async(username, role_name),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg revoke_user_role failed", exc_info=True)
            return False
        if ok:
            self._invalidate()
        return ok

    async def _revoke_user_role_async(
        self, username: str, role_name: str,
    ) -> bool:
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id FROM rbac_roles "
                        "WHERE tenant_id = :tid AND name = :n",
                    ),
                    {"tid": _TENANT, "n": role_name},
                )
            ).fetchone()
            if row is None:
                return False
            result = await conn.execute(
                text(
                    "DELETE FROM rbac_user_roles "
                    "WHERE tenant_id = :tid "
                    "AND username = :u AND role_id = :rid",
                ),
                {"tid": _TENANT, "u": username, "rid": str(row[0])},
            )
        return bool(result.rowcount)

    def get_role_users(self, role_name: str) -> List[str]:
        try:
            return self._run(self._get_role_users_async(role_name))
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg get_role_users failed", exc_info=True)
            return []

    async def _get_role_users_async(self, role_name: str) -> List[str]:
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT ur.username FROM rbac_user_roles ur "
                        "JOIN rbac_roles r "
                        "  ON r.tenant_id = ur.tenant_id "
                        "  AND r.id = ur.role_id "
                        "WHERE ur.tenant_id = :tid AND r.name = :n",
                    ),
                    {"tid": _TENANT, "n": role_name},
                )
            ).fetchall()
        return [str(r[0]) for r in rows]

    # ==================================================================
    # Menu management
    # ==================================================================

    def list_menus(self) -> List[MenuRecord]:
        try:
            return self._run(self._list_menus_async())
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg list_menus failed", exc_info=True)
            return []

    async def _list_menus_async(self) -> List[MenuRecord]:
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, parent_id, name, menu_type, path, "
                        "component, icon, perm_code, sort_order, "
                        "is_visible, is_enabled, is_external, redirect "
                        "FROM rbac_menus WHERE tenant_id = :tid "
                        "ORDER BY sort_order, name",
                    ),
                    {"tid": _TENANT},
                )
            ).fetchall()
        return [self._row_to_menu(r) for r in rows]

    def get_menu_tree(self) -> List[MenuRecord]:
        return self._build_tree(self.list_menus())

    def create_menu(
        self, name: str, *, parent_id: Optional[str] = None,
        menu_type: str = "menu", path: str = "", component: str = "",
        icon: str = "", perm_code: str = "", sort_order: int = 0,
        is_visible: bool = True, is_enabled: bool = True,
        is_external: bool = False, redirect: str = "",
    ) -> Optional[MenuRecord]:
        try:
            rec = self._run(
                self._create_menu_async(
                    name, parent_id, menu_type, path, component, icon,
                    perm_code, sort_order, is_visible, is_enabled,
                    is_external, redirect,
                ),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg create_menu failed", exc_info=True)
            return None
        self._invalidate()
        return rec

    async def _create_menu_async(
        self, name: str, parent_id: Optional[str], menu_type: str,
        path: str, component: str, icon: str, perm_code: str,
        sort_order: int, is_visible: bool, is_enabled: bool,
        is_external: bool, redirect: str,
    ) -> MenuRecord:
        from sqlalchemy import text

        mid = _uid()
        async with self._get_engine().begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO rbac_menus "
                    "(id, parent_id, name, menu_type, path, component, "
                    "icon, perm_code, sort_order, is_visible, "
                    "is_enabled, is_external, redirect) "
                    "VALUES (:id, :pid, :name, :mt, :path, :comp, "
                    ":icon, :pc, :so, :vis, :en, :ext, :redir)",
                ),
                {"id": mid, "pid": parent_id, "name": name,
                 "mt": menu_type, "path": path, "comp": component,
                 "icon": icon, "pc": perm_code, "so": sort_order,
                 "vis": is_visible, "en": is_enabled,
                 "ext": is_external, "redir": redirect},
            )
        return MenuRecord(
            id=mid, parent_id=parent_id, name=name,
            menu_type=menu_type, path=path, component=component,
            icon=icon, perm_code=perm_code, sort_order=sort_order,
            is_visible=is_visible, is_enabled=is_enabled,
            is_external=is_external, redirect=redirect,
        )

    def update_menu(
        self, menu_id: str, **fields,
    ) -> Optional[MenuRecord]:
        try:
            rec = self._run(self._update_menu_async(menu_id, fields))
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg update_menu failed", exc_info=True)
            return None
        if rec is not None:
            self._invalidate()
        return rec

    async def _update_menu_async(
        self, menu_id: str, fields: dict,
    ) -> Optional[MenuRecord]:
        from sqlalchemy import text

        updatable = {
            "parent_id", "name", "menu_type", "path", "component",
            "icon", "perm_code", "sort_order", "is_visible",
            "is_enabled", "is_external", "redirect",
        }
        sets = {k: v for k, v in fields.items() if k in updatable}
        if not sets:
            return None
        clause = ", ".join(f"{k} = :{k}" for k in sets)
        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    f"UPDATE rbac_menus SET {clause}, "
                    "updated_at = now() "
                    "WHERE tenant_id = :tid AND id = :mid",
                ),
                {**sets, "tid": _TENANT, "mid": menu_id},
            )
            if not result.rowcount:
                return None
            row = (
                await conn.execute(
                    text(
                        "SELECT id, parent_id, name, menu_type, path, "
                        "component, icon, perm_code, sort_order, "
                        "is_visible, is_enabled, is_external, redirect "
                        "FROM rbac_menus "
                        "WHERE tenant_id = :tid AND id = :mid",
                    ),
                    {"tid": _TENANT, "mid": menu_id},
                )
            ).fetchone()
        return self._row_to_menu(row) if row else None

    def delete_menu(self, menu_id: str) -> bool:
        """Delete menu and all descendants (cascade)."""
        try:
            deleted = self._run(self._delete_menu_async(menu_id))
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg delete_menu failed", exc_info=True)
            return False
        if deleted:
            self._invalidate()
        return deleted

    async def _delete_menu_async(self, menu_id: str) -> bool:
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            ids = [menu_id]
            queue = [menu_id]
            while queue:
                cur = queue.pop(0)
                rows = (
                    await conn.execute(
                        text(
                            "SELECT id FROM rbac_menus "
                            "WHERE tenant_id = :tid "
                            "AND parent_id = :pid",
                        ),
                        {"tid": _TENANT, "pid": cur},
                    )
                ).fetchall()
                for r in rows:
                    cid = str(r[0])
                    ids.append(cid)
                    queue.append(cid)
            for mid in ids:
                await conn.execute(
                    text(
                        "DELETE FROM rbac_role_menus "
                        "WHERE tenant_id = :tid AND menu_id = :mid",
                    ),
                    {"tid": _TENANT, "mid": mid},
                )
            for mid in reversed(ids):
                await conn.execute(
                    text(
                        "DELETE FROM rbac_menus "
                        "WHERE tenant_id = :tid AND id = :mid",
                    ),
                    {"tid": _TENANT, "mid": mid},
                )
        return True

    def get_role_menus(self, role_id: str) -> List[str]:
        try:
            return self._run(self._get_role_menus_async(role_id))
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg get_role_menus failed", exc_info=True)
            return []

    async def _get_role_menus_async(self, role_id: str) -> List[str]:
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT menu_id FROM rbac_role_menus "
                        "WHERE tenant_id = :tid AND role_id = :rid",
                    ),
                    {"tid": _TENANT, "rid": role_id},
                )
            ).fetchall()
        return [str(r[0]) for r in rows]

    def assign_role_menus(
        self, role_id: str, menu_ids: List[str],
    ) -> bool:
        try:
            self._run(
                self._assign_role_menus_async(role_id, menu_ids),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "pg assign_role_menus failed", exc_info=True,
            )
            return False
        self._invalidate()
        return True

    async def _assign_role_menus_async(
        self, role_id: str, menu_ids: List[str],
    ) -> None:
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM rbac_role_menus "
                    "WHERE tenant_id = :tid AND role_id = :rid",
                ),
                {"tid": _TENANT, "rid": role_id},
            )
            for mid in menu_ids:
                await conn.execute(
                    text(
                        "INSERT INTO rbac_role_menus "
                        "(role_id, menu_id) "
                        "VALUES (:rid, :mid) "
                        "ON CONFLICT DO NOTHING",
                    ),
                    {"rid": role_id, "mid": mid},
                )

    def get_user_menus(self, username: str) -> List[MenuRecord]:
        """Get menu tree visible to *username* (aggregated from roles)."""
        cached = self._cache_get(f"um:{username}")
        if cached is not _MISS:
            return cached  # type: ignore[return-value]
        try:
            menus = self._run(self._get_user_menus_async(username))
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg get_user_menus failed", exc_info=True)
            return []
        self._cache_set(f"um:{username}", menus)
        return menus

    async def _get_user_menus_async(
        self, username: str,
    ) -> List[MenuRecord]:
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT DISTINCT m.id, m.parent_id, m.name, "
                        "m.menu_type, m.path, m.component, m.icon, "
                        "m.perm_code, m.sort_order, m.is_visible, "
                        "m.is_enabled, m.is_external, m.redirect "
                        "FROM rbac_menus m "
                        "JOIN rbac_role_menus rm "
                        "  ON rm.tenant_id = m.tenant_id "
                        "  AND rm.menu_id = m.id "
                        "JOIN rbac_user_roles ur "
                        "  ON ur.tenant_id = rm.tenant_id "
                        "  AND ur.role_id = rm.role_id "
                        "WHERE m.tenant_id = :tid "
                        "AND ur.username = :u "
                        "AND m.is_enabled = TRUE "
                        "ORDER BY m.sort_order, m.name",
                    ),
                    {"tid": _TENANT, "u": username},
                )
            ).fetchall()
        menus = [self._row_to_menu(r) for r in rows]
        return self._build_tree(menus)

    # ==================================================================
    # Data scope
    # ==================================================================

    def get_data_scopes(self, role_id: str) -> List[DataScopeRecord]:
        try:
            return self._run(self._get_data_scopes_async(role_id))
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg get_data_scopes failed", exc_info=True)
            return []

    async def _get_data_scopes_async(
        self, role_id: str,
    ) -> List[DataScopeRecord]:
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, role_id, resource, scope_type, "
                        "custom_dept_ids "
                        "FROM rbac_data_scopes "
                        "WHERE tenant_id = :tid AND role_id = :rid",
                    ),
                    {"tid": _TENANT, "rid": role_id},
                )
            ).fetchall()
        return [self._row_to_scope(r) for r in rows]

    @staticmethod
    def _row_to_scope(row) -> DataScopeRecord:
        raw = row[4]
        if isinstance(raw, str):
            dept_ids = json.loads(raw)
        else:
            dept_ids = raw or []
        return DataScopeRecord(
            id=str(row[0]), role_id=str(row[1]),
            resource=str(row[2] or ""),
            scope_type=str(row[3] or "self"),
            custom_dept_ids=list(dept_ids),
        )

    def set_data_scope(
        self, role_id: str, resource: str, scope_type: str,
        custom_dept_ids: Optional[List[str]] = None,
    ) -> bool:
        try:
            self._run(
                self._set_data_scope_async(
                    role_id, resource, scope_type,
                    custom_dept_ids or [],
                ),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg set_data_scope failed", exc_info=True)
            return False
        self._invalidate()
        return True

    async def _set_data_scope_async(
        self, role_id: str, resource: str, scope_type: str,
        custom_dept_ids: List[str],
    ) -> None:
        from sqlalchemy import text

        sid = _uid()
        async with self._get_engine().begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO rbac_data_scopes "
                    "(id, role_id, resource, scope_type, "
                    "custom_dept_ids) "
                    "VALUES (:id, :rid, :res, :st, "
                    "CAST(:cdi AS jsonb)) "
                    "ON CONFLICT (tenant_id, role_id, resource) "
                    "DO UPDATE SET "
                    "scope_type = EXCLUDED.scope_type, "
                    "custom_dept_ids = EXCLUDED.custom_dept_ids, "
                    "updated_at = now()",
                ),
                {"id": sid, "rid": role_id, "res": resource,
                 "st": scope_type,
                 "cdi": json.dumps(custom_dept_ids)},
            )

    def delete_data_scope(self, role_id: str, resource: str) -> bool:
        try:
            deleted = self._run(
                self._delete_data_scope_async(role_id, resource),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "pg delete_data_scope failed", exc_info=True,
            )
            return False
        if deleted:
            self._invalidate()
        return deleted

    async def _delete_data_scope_async(
        self, role_id: str, resource: str,
    ) -> bool:
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM rbac_data_scopes "
                    "WHERE tenant_id = :tid "
                    "AND role_id = :rid AND resource = :res",
                ),
                {"tid": _TENANT, "rid": role_id, "res": resource},
            )
        return bool(result.rowcount)

    def resolve_user_scope(
        self, username: str, resource: str,
    ) -> DataScopeRecord:
        """Resolve the most permissive data scope across all user roles."""
        try:
            return self._run(
                self._resolve_user_scope_async(username, resource),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "pg resolve_user_scope failed", exc_info=True,
            )
        return DataScopeRecord(
            id="", role_id="", resource=resource, scope_type="self",
        )

    async def _resolve_user_scope_async(
        self, username: str, resource: str,
    ) -> DataScopeRecord:
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT ds.id, ds.role_id, ds.resource, "
                        "ds.scope_type, ds.custom_dept_ids "
                        "FROM rbac_data_scopes ds "
                        "JOIN rbac_user_roles ur "
                        "  ON ur.tenant_id = ds.tenant_id "
                        "  AND ur.role_id = ds.role_id "
                        "WHERE ds.tenant_id = :tid "
                        "AND ur.username = :u "
                        "AND ds.resource = :res",
                    ),
                    {"tid": _TENANT, "u": username, "res": resource},
                )
            ).fetchall()
        if not rows:
            return DataScopeRecord(
                id="", role_id="", resource=resource,
                scope_type="self",
            )
        best, best_pri = None, -1
        for r in rows:
            pri = self._SCOPE_PRI.get(str(r[3]), 0)
            if pri > best_pri:
                best_pri, best = pri, r
        return self._row_to_scope(best)

    # ==================================================================
    # Team management
    # ==================================================================

    def list_teams(self) -> List[TeamRecord]:
        try:
            return self._run(self._list_teams_async())
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg list_teams failed", exc_info=True)
            return []

    async def _list_teams_async(self) -> List[TeamRecord]:
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT t.id, t.name, t.description, "
                        "tm.username "
                        "FROM rbac_teams t "
                        "LEFT JOIN rbac_team_members tm "
                        "  ON tm.tenant_id = t.tenant_id "
                        "  AND tm.team_id = t.id "
                        "WHERE t.tenant_id = :tid ORDER BY t.name",
                    ),
                    {"tid": _TENANT},
                )
            ).fetchall()
        teams: Dict[str, TeamRecord] = {}
        for row in rows:
            tid = str(row[0])
            if tid not in teams:
                teams[tid] = TeamRecord(
                    name=str(row[1]), members=[],
                    description=str(row[2] or ""),
                )
            if row[3]:
                teams[tid].members.append(str(row[3]))
        return list(teams.values())

    def create_team(
        self, name: str, display_name: str = "",
        description: str = "",
        members: Optional[List[str]] = None,
    ) -> Optional[TeamRecord]:
        name = name.strip()
        if not name:
            return None
        try:
            rec = self._run(
                self._create_team_async(
                    name, display_name, description, members or [],
                ),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg create_team failed", exc_info=True)
            return None
        self._invalidate()
        return rec

    async def _create_team_async(
        self, name: str, display_name: str,
        description: str, members: List[str],
    ) -> TeamRecord:
        from sqlalchemy import text

        tid = _uid()
        async with self._get_engine().begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO rbac_teams "
                    "(id, name, display_name, description) "
                    "VALUES (:id, :name, :dn, :desc)",
                ),
                {"id": tid, "name": name, "dn": display_name,
                 "desc": description},
            )
            for u in members:
                await conn.execute(
                    text(
                        "INSERT INTO rbac_team_members "
                        "(team_id, username) "
                        "VALUES (:tid, :u) "
                        "ON CONFLICT DO NOTHING",
                    ),
                    {"tid": tid, "u": u},
                )
        return TeamRecord(
            name=name, members=list(members),
            description=description,
        )

    def update_team(
        self, name: str, **fields,
    ) -> Optional[TeamRecord]:
        try:
            rec = self._run(self._update_team_async(name, fields))
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg update_team failed", exc_info=True)
            return None
        if rec is not None:
            self._invalidate()
        return rec

    async def _update_team_async(
        self, name: str, fields: dict,
    ) -> Optional[TeamRecord]:
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id FROM rbac_teams "
                        "WHERE tenant_id = :tid AND name = :name",
                    ),
                    {"tid": _TENANT, "name": name},
                )
            ).fetchone()
            if row is None:
                return None
            tid = str(row[0])
            updatable = {"display_name", "description"}
            sets = {
                k: v for k, v in fields.items() if k in updatable
            }
            if sets:
                clause = ", ".join(f"{k} = :{k}" for k in sets)
                await conn.execute(
                    text(
                        f"UPDATE rbac_teams SET {clause}, "
                        "updated_at = now() "
                        "WHERE tenant_id = :t AND id = :tid",
                    ),
                    {**sets, "t": _TENANT, "tid": tid},
                )
            if "members" in fields:
                await conn.execute(
                    text(
                        "DELETE FROM rbac_team_members "
                        "WHERE tenant_id = :t AND team_id = :tid",
                    ),
                    {"t": _TENANT, "tid": tid},
                )
                for u in fields["members"]:
                    await conn.execute(
                        text(
                            "INSERT INTO rbac_team_members "
                            "(team_id, username) "
                            "VALUES (:tid, :u) "
                            "ON CONFLICT DO NOTHING",
                        ),
                        {"tid": tid, "u": u},
                    )
        return await self._get_team_by_name_async(name)

    async def _get_team_by_name_async(
        self, name: str,
    ) -> Optional[TeamRecord]:
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id, name, description "
                        "FROM rbac_teams "
                        "WHERE tenant_id = :tid AND name = :name",
                    ),
                    {"tid": _TENANT, "name": name},
                )
            ).fetchone()
            if row is None:
                return None
            tid = str(row[0])
            mrows = (
                await conn.execute(
                    text(
                        "SELECT username FROM rbac_team_members "
                        "WHERE tenant_id = :tid AND team_id = :t",
                    ),
                    {"tid": _TENANT, "t": tid},
                )
            ).fetchall()
        return TeamRecord(
            name=str(row[1]), description=str(row[2] or ""),
            members=[str(m[0]) for m in mrows],
        )

    def delete_team(self, name: str) -> bool:
        try:
            deleted = self._run(self._delete_team_async(name))
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg delete_team failed", exc_info=True)
            return False
        if deleted:
            self._invalidate()
        return deleted

    async def _delete_team_async(self, name: str) -> bool:
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id FROM rbac_teams "
                        "WHERE tenant_id = :tid AND name = :name",
                    ),
                    {"tid": _TENANT, "name": name},
                )
            ).fetchone()
            if row is None:
                return False
            tid = str(row[0])
            await conn.execute(
                text(
                    "DELETE FROM rbac_team_members "
                    "WHERE tenant_id = :t AND team_id = :tid",
                ),
                {"t": _TENANT, "tid": tid},
            )
            await conn.execute(
                text(
                    "DELETE FROM rbac_teams "
                    "WHERE tenant_id = :t AND id = :tid",
                ),
                {"t": _TENANT, "tid": tid},
            )
        return True

    def get_team_members(self, team_name: str) -> List[str]:
        try:
            return self._run(
                self._get_team_members_async(team_name),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "pg get_team_members failed", exc_info=True,
            )
            return []

    async def _get_team_members_async(
        self, team_name: str,
    ) -> List[str]:
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT tm.username "
                        "FROM rbac_team_members tm "
                        "JOIN rbac_teams t "
                        "  ON t.tenant_id = tm.tenant_id "
                        "  AND t.id = tm.team_id "
                        "WHERE tm.tenant_id = :tid "
                        "AND t.name = :name",
                    ),
                    {"tid": _TENANT, "name": team_name},
                )
            ).fetchall()
        return [str(r[0]) for r in rows]

    def add_team_member(self, team_name: str, username: str) -> bool:
        if not team_name or not username:
            return False
        try:
            ok = self._run(
                self._add_team_member_async(team_name, username),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "pg add_team_member failed", exc_info=True,
            )
            return False
        if ok:
            self._invalidate()
        return ok

    async def _add_team_member_async(
        self, team_name: str, username: str,
    ) -> bool:
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id FROM rbac_teams "
                        "WHERE tenant_id = :tid AND name = :name",
                    ),
                    {"tid": _TENANT, "name": team_name},
                )
            ).fetchone()
            if row is None:
                return False
            await conn.execute(
                text(
                    "INSERT INTO rbac_team_members "
                    "(team_id, username) "
                    "VALUES (:tid, :u) "
                    "ON CONFLICT DO NOTHING",
                ),
                {"tid": str(row[0]), "u": username},
            )
        return True

    def remove_team_member(
        self, team_name: str, username: str,
    ) -> bool:
        try:
            ok = self._run(
                self._remove_team_member_async(team_name, username),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "pg remove_team_member failed", exc_info=True,
            )
            return False
        if ok:
            self._invalidate()
        return ok

    async def _remove_team_member_async(
        self, team_name: str, username: str,
    ) -> bool:
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id FROM rbac_teams "
                        "WHERE tenant_id = :tid AND name = :name",
                    ),
                    {"tid": _TENANT, "name": team_name},
                )
            ).fetchone()
            if row is None:
                return False
            result = await conn.execute(
                text(
                    "DELETE FROM rbac_team_members "
                    "WHERE tenant_id = :t "
                    "AND team_id = :tid AND username = :u",
                ),
                {"t": _TENANT, "tid": str(row[0]), "u": username},
            )
        return bool(result.rowcount)

    # ==================================================================
    # Permission checks (hot path, cached)
    # ==================================================================

    def get_user_permissions(self, username: str) -> List[str]:
        cached = self._cache_get(f"up:{username}")
        if cached is not _MISS:
            return cached  # type: ignore[return-value]
        try:
            perms = self._run(
                self._get_user_permissions_async(username),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "pg get_user_permissions failed", exc_info=True,
            )
            return []
        self._cache_set(f"up:{username}", perms)
        return perms

    async def _get_user_permissions_async(
        self, username: str,
    ) -> List[str]:
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT DISTINCT p.code "
                        "FROM rbac_user_roles ur "
                        "JOIN rbac_role_permissions rp "
                        "  ON rp.tenant_id = ur.tenant_id "
                        "  AND rp.role_id = ur.role_id "
                        "JOIN rbac_permissions p "
                        "  ON p.tenant_id = rp.tenant_id "
                        "  AND p.id = rp.permission_id "
                        "JOIN rbac_roles r "
                        "  ON r.tenant_id = ur.tenant_id "
                        "  AND r.id = ur.role_id "
                        "WHERE ur.tenant_id = :tid "
                        "AND ur.username = :u "
                        "AND r.is_enabled = TRUE",
                    ),
                    {"tid": _TENANT, "u": username},
                )
            ).fetchall()
        return [str(r[0]) for r in rows]

    def has_permission(self, username: str, perm_code: str) -> bool:
        """Check if user has *perm_code* (supports ``*`` / ``res:*``)."""
        perms = self.get_user_permissions(username)
        if not perms:
            return False
        return _match_permission(perms, perm_code)

    # ==================================================================
    # Data migration (rbac.json -> PG, idempotent)
    # ==================================================================

    def migrate_from_json(self, rbac_file_data) -> bool:
        """Idempotent import from RbacFile (or dict) into PG."""
        if isinstance(rbac_file_data, dict):
            try:
                rbac_file_data = RbacFile.model_validate(
                    rbac_file_data,
                )
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "migrate_from_json: invalid data", exc_info=True,
                )
                return False
        if not isinstance(rbac_file_data, RbacFile):
            return False
        try:
            self._run(self._migrate_async(rbac_file_data))
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "pg migrate_from_json failed", exc_info=True,
            )
            return False
        self._invalidate()
        logger.info("RBAC data migrated from rbac.json to PG")
        return True

    async def _migrate_async(self, data: RbacFile) -> None:
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            # 1. Seed built-in roles first.
            for bname, bperms in BUILTIN_ROLE_PERMISSIONS.items():
                row = (
                    await conn.execute(
                        text(
                            "SELECT id FROM rbac_roles "
                            "WHERE tenant_id = :tid AND name = :n",
                        ),
                        {"tid": _TENANT, "n": bname},
                    )
                ).fetchone()
                if row is None:
                    rid = _uid()
                    await conn.execute(
                        text(
                            "INSERT INTO rbac_roles "
                            "(id, name, display_name, description, "
                            "is_builtin) "
                            "VALUES (:id, :n, :n, "
                            "'built-in role', TRUE) "
                            "ON CONFLICT DO NOTHING",
                        ),
                        {"id": rid, "n": bname},
                    )
                    row = (
                        await conn.execute(
                            text(
                                "SELECT id FROM rbac_roles "
                                "WHERE tenant_id = :tid "
                                "AND name = :n",
                            ),
                            {"tid": _TENANT, "n": bname},
                        )
                    ).fetchone()
                if row:
                    actual_rid = str(row[0])
                    for code in bperms:
                        pid = await self._ensure_permission_async(
                            conn, code,
                        )
                        await conn.execute(
                            text(
                                "INSERT INTO rbac_role_permissions "
                                "(role_id, permission_id) "
                                "VALUES (:rid, :pid) "
                                "ON CONFLICT DO NOTHING",
                            ),
                            {"rid": actual_rid, "pid": pid},
                        )
            # 2. Custom roles from file.
            for name, role in data.roles.items():
                if role.builtin:
                    continue
                rid = _uid()
                await conn.execute(
                    text(
                        "INSERT INTO rbac_roles "
                        "(id, name, display_name, description, "
                        "is_builtin) "
                        "VALUES (:id, :n, :n, :desc, FALSE) "
                        "ON CONFLICT (tenant_id, name) DO UPDATE "
                        "SET description = EXCLUDED.description",
                    ),
                    {"id": rid, "n": name,
                     "desc": role.description},
                )
                row = (
                    await conn.execute(
                        text(
                            "SELECT id FROM rbac_roles "
                            "WHERE tenant_id = :tid AND name = :n",
                        ),
                        {"tid": _TENANT, "n": name},
                    )
                ).fetchone()
                actual_rid = str(row[0]) if row else rid
                for code in role.permissions:
                    pid = await self._ensure_permission_async(
                        conn, code,
                    )
                    await conn.execute(
                        text(
                            "INSERT INTO rbac_role_permissions "
                            "(role_id, permission_id) "
                            "VALUES (:rid, :pid) "
                            "ON CONFLICT DO NOTHING",
                        ),
                        {"rid": actual_rid, "pid": pid},
                    )
            # 3. User-role bindings.
            for username, role_names in data.user_roles.items():
                for rn in role_names:
                    row = (
                        await conn.execute(
                            text(
                                "SELECT id FROM rbac_roles "
                                "WHERE tenant_id = :tid "
                                "AND name = :n",
                            ),
                            {"tid": _TENANT, "n": rn},
                        )
                    ).fetchone()
                    if row:
                        await conn.execute(
                            text(
                                "INSERT INTO rbac_user_roles "
                                "(username, role_id) "
                                "VALUES (:u, :rid) "
                                "ON CONFLICT DO NOTHING",
                            ),
                            {"u": username, "rid": str(row[0])},
                        )
            # 4. Teams.
            for name, team in data.teams.items():
                tid = _uid()
                await conn.execute(
                    text(
                        "INSERT INTO rbac_teams "
                        "(id, name, display_name, description) "
                        "VALUES (:id, :n, :n, :desc) "
                        "ON CONFLICT (tenant_id, name) DO UPDATE "
                        "SET description = EXCLUDED.description",
                    ),
                    {"id": tid, "n": name,
                     "desc": team.description},
                )
                row = (
                    await conn.execute(
                        text(
                            "SELECT id FROM rbac_teams "
                            "WHERE tenant_id = :tid AND name = :n",
                        ),
                        {"tid": _TENANT, "n": name},
                    )
                ).fetchone()
                actual_tid = str(row[0]) if row else tid
                for member in team.members:
                    await conn.execute(
                        text(
                            "INSERT INTO rbac_team_members "
                            "(team_id, username) "
                            "VALUES (:tid, :u) "
                            "ON CONFLICT DO NOTHING",
                        ),
                        {"tid": actual_tid, "u": member},
                    )


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_default_store: Optional[PgRbacStore] = None


def get_pg_rbac_store() -> Optional[PgRbacStore]:
    """Return the process-wide PgRbacStore, or None if PG unavailable.

    调用方在 ``None`` 时应 fallback 到文件后端
    :func:`qwenpaw.app.rbac.store.get_rbac_store`。
    """
    global _default_store  # noqa: PLW0603
    if _default_store is not None:
        return _default_store
    try:
        from ..run_log_pg_store import pg_available

        if not pg_available():
            return None
    except Exception:  # pylint: disable=broad-except
        return None
    try:
        store = PgRbacStore()
        if store.ensure_ready():
            logger.info("RBAC store backend: postgresql")
            _default_store = store
            return store
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "PgRbacStore init failed; falling back to file backend",
            exc_info=True,
        )
    return None


def reset_pg_rbac_store() -> None:
    """Drop the singleton (tests)."""
    global _default_store  # noqa: PLW0603
    _default_store = None
