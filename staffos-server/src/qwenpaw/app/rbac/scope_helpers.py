# -*- coding: utf-8 -*-
"""数据范围辅助工具 —— 获取用户部门信息的便捷方法。

配合 :class:`qwenpaw.app.rbac.data_scope.DataScopeFilter` 使用：业务列表
接口在返回结果前，需要「用户所属主部门 ID」与「该部门及其所有子部门 ID
列表」来落地 ``dept`` / ``dept_and_child`` 两类数据范围。本模块把这两次
查询收敛为一次性上下文获取（:func:`get_user_scope_context`），供各业务
路由/service 直接调用。

设计要点
--------
- **同步 API**：与 ``DataScopeFilter.resolve_scope`` 保持一致。内部复用
  :class:`~qwenpaw.app.rbac.store_pg.PgRbacStore` 的后台事件循环桥接与共享
  asyncpg 引擎池，调用方无需 ``await``，可在 async 路由里同步调用。
- **优雅降级**：PG 不可用 / SQLAlchemy 缺失 / 查询异常时一律返回空值
  （``None`` / ``[]``），绝不抛出。数据范围过滤属于「附加收敛层」，其失败
  不应阻断正常业务请求——调用方拿到空上下文后，``DataScopeFilter`` 会自然
  回落到「不按部门过滤」，保持向后兼容。
- **租户口径**：行级过滤固定使用 ``default`` 租户（与 ``store_pg._TENANT``
  及 ``enterprise.DEFAULT_TENANT`` 对齐），覆盖单组织的常规部署形态。
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

#: 行级租户过滤默认值（与 ``store_pg._TENANT`` / ``enterprise.DEFAULT_TENANT`` 一致）。
_DEFAULT_TENANT = "default"


# ---------------------------------------------------------------------------
# PG store / 引擎桥接（同包内复用 PgRbacStore 的后台事件循环）
# ---------------------------------------------------------------------------


def _pg_store() -> Optional[Any]:
    """返回 :class:`PgRbacStore` 单例；PG 不可用/未安装时返回 ``None``。"""
    try:
        from .store_pg import get_pg_rbac_store

        return get_pg_rbac_store()
    except Exception:  # pylint: disable=broad-except
        return None


async def _fetch_user_department_id(store: Any, username: str) -> Optional[str]:
    """查询用户所属主部门 ID（多个时取排序后的第一个）。"""
    from sqlalchemy import text

    async with store._get_engine().connect() as conn:  # noqa: SLF001
        row = (
            await conn.execute(
                text(
                    "SELECT department_id FROM department_members "
                    "WHERE tenant_id = :tid AND username = :u "
                    "ORDER BY department_id LIMIT 1"
                ),
                {"tid": _DEFAULT_TENANT, "u": username},
            )
        ).first()
    return str(row[0]) if row and row[0] else None


async def _fetch_dept_and_children(store: Any, dept_id: str) -> List[str]:
    """查询指定部门及其所有子部门的 ID 列表。

    部门树用物化路径（``departments.path``，形如 ``root/child/grandchild``）
    表达层级：子部门 path 以父部门 path 为前缀。据此一次 ``LIKE`` 前缀匹配
    即可取回整棵子树，无需递归 CTE。
    """
    from sqlalchemy import text

    async with store._get_engine().connect() as conn:  # noqa: SLF001
        current = (
            await conn.execute(
                text(
                    "SELECT path FROM departments "
                    "WHERE tenant_id = :tid AND id = :id"
                ),
                {"tid": _DEFAULT_TENANT, "id": dept_id},
            )
        ).first()
        if current is None:
            # 部门行缺失（已删除/跨租户）：至少含本部门，交由上层按 dept 收敛
            return [dept_id]
        path = str(current[0] or "")
        if not path:
            return [dept_id]
        rows = (
            await conn.execute(
                text(
                    "SELECT id FROM departments "
                    "WHERE tenant_id = :tid "
                    "AND (id = :id OR path = :path OR path LIKE :prefix)"
                ),
                {
                    "tid": _DEFAULT_TENANT,
                    "id": dept_id,
                    "path": path,
                    # 子部门 path = "{父path}/{子id}"，前缀匹配整棵子树
                    "prefix": path + "/%",
                },
            )
        ).fetchall()
    ids = {str(r[0]) for r in rows if r[0]}
    ids.add(dept_id)
    return sorted(ids)


# ---------------------------------------------------------------------------
# 对外同步 API
# ---------------------------------------------------------------------------


def get_user_department_id(username: str) -> Optional[str]:
    """获取用户所属的主部门 ID（如有多个取第一个）。

    PG 不可用或查询异常时返回 ``None``（优雅降级，不抛出）。
    """
    if not username:
        return None
    store = _pg_store()
    if store is None:
        return None
    try:
        return store._run(  # noqa: SLF001
            _fetch_user_department_id(store, username),
        )
    except Exception:  # pylint: disable=broad-except
        logger.debug(
            "scope_helpers: department lookup failed for %r",
            username,
            exc_info=True,
        )
        return None


def get_department_and_children_ids(dept_id: str) -> List[str]:
    """获取指定部门及其所有子部门的 ID 列表。

    PG 不可用或查询异常时回落到 ``[dept_id]``（至少含本部门，避免
    ``dept_and_child`` 范围被误收敛为空集）；``dept_id`` 为空时返回 ``[]``。
    """
    if not dept_id:
        return []
    store = _pg_store()
    if store is None:
        return [dept_id]
    try:
        result = store._run(  # noqa: SLF001
            _fetch_dept_and_children(store, dept_id),
        )
        return list(result) if result else [dept_id]
    except Exception:  # pylint: disable=broad-except
        logger.debug(
            "scope_helpers: descendant lookup failed for %r",
            dept_id,
            exc_info=True,
        )
        return [dept_id]


def get_user_scope_context(username: str) -> dict:
    """一次性获取用户的数据范围上下文信息。

    Returns:
        ``{'username': str, 'dept_id': Optional[str],
        'dept_and_child_ids': List[str]}``

        任何异常/PG 不可用都回落到「无部门」上下文（``dept_id=None``、
        ``dept_and_child_ids=[]``），此时 :class:`DataScopeFilter` 的
        ``dept`` / ``dept_and_child`` 范围会收敛为空可见集，``all`` /
        ``self`` 范围不受影响——保证调用链永不因数据范围查询而中断。
    """
    dept_id = get_user_department_id(username)
    dept_and_child_ids = (
        get_department_and_children_ids(dept_id) if dept_id else []
    )
    return {
        "username": username,
        "dept_id": dept_id,
        "dept_and_child_ids": dept_and_child_ids,
    }
