# -*- coding: utf-8 -*-
"""通用数据范围过滤器（M5+）。

配合 :class:`qwenpaw.app.rbac.store_pg.PgRbacStore` 的
``resolve_user_scope()`` 使用，向业务 Service 层提供统一的
"哪些数据可见 / 按什么字段过滤" 决策入口。

数据范围类型（与 ``rbac_data_scopes.scope_type`` 对齐）：

- ``all``            —— 全部可见，不过滤
- ``dept_and_child`` —— 本部门 + 所有子部门
- ``dept``           —— 仅本部门
- ``self``           —— 仅本人创建/拥有
- ``custom``         —— 指定的自定义部门集合

典型使用方式::

    from qwenpaw.app.rbac.data_scope import DataScopeFilter

    scope = DataScopeFilter.resolve_scope(username, "project")
    visible_items = DataScopeFilter.apply_to_list(
        items=all_projects,
        scope=scope,
        username=username,
        user_dept_id=user.dept_id,
        dept_id_field="department_id",
        owner_field="created_by",
        all_child_dept_ids=org_service.descendant_dept_ids(user.dept_id),
    )
"""
from __future__ import annotations

from typing import Any, List, Optional, Set

# ---------------------------------------------------------------------------
# 数据范围类型常量（与 rbac_data_scopes.scope_type 列一致）
# ---------------------------------------------------------------------------

SCOPE_ALL = "all"
SCOPE_DEPT_AND_CHILD = "dept_and_child"
SCOPE_DEPT = "dept"
SCOPE_SELF = "self"
SCOPE_CUSTOM = "custom"


class DataScopeFilter:
    """通用数据范围过滤器（无状态静态工具类）。"""

    # ------------------------------------------------------------------
    # 范围解析
    # ------------------------------------------------------------------

    @staticmethod
    def resolve_scope(username: str, resource: str):
        """解析用户对某资源的最终数据范围（取所有角色中最宽松的）。

        PG 可用时委托 ``PgRbacStore.resolve_user_scope``；PG 不可用时
        fallback 到最宽松的 ``all``，保证单机/文件后端部署零阻断。
        """
        try:
            from qwenpaw.app.rbac.store_pg import get_pg_rbac_store

            pg_store = get_pg_rbac_store()
        except Exception:  # pylint: disable=broad-except
            pg_store = None
        if pg_store is not None:
            return pg_store.resolve_user_scope(username, resource)
        from qwenpaw.app.rbac.models import DataScopeRecord

        return DataScopeRecord(
            id="", role_id="", resource=resource,
            scope_type=SCOPE_ALL, custom_dept_ids=[],
        )

    # ------------------------------------------------------------------
    # 部门可见集
    # ------------------------------------------------------------------

    @staticmethod
    def get_visible_dept_ids(
        scope: Any,
        username: str,
        user_dept_id: Optional[str],
        all_child_dept_ids: Optional[List[str]] = None,
    ) -> Optional[Set[str]]:
        """根据数据范围计算可见的部门 ID 集合。

        Returns:
            - ``None`` 表示"全部可见"（无需过滤，调用方直接放行）；
            - ``set()`` 表示"无可见部门数据"（``self`` 模式或用户无部门时）；
            - 非空 ``set`` 表示可见部门白名单。
        """
        scope_type = getattr(scope, "scope_type", SCOPE_ALL)
        if scope_type == SCOPE_ALL:
            return None
        if scope_type == SCOPE_SELF:
            # self 模式不按部门过滤，由调用方按 owner_field 过滤
            return set()
        if scope_type == SCOPE_DEPT:
            if user_dept_id:
                return {user_dept_id}
            return set()
        if scope_type == SCOPE_DEPT_AND_CHILD:
            if all_child_dept_ids is not None:
                return set(all_child_dept_ids)
            if user_dept_id:
                return {user_dept_id}
            return set()
        if scope_type == SCOPE_CUSTOM:
            custom = getattr(scope, "custom_dept_ids", None) or []
            return set(custom)
        # 未知 scope_type 保守返回全部可见，避免误伤
        return None

    # ------------------------------------------------------------------
    # owner 过滤判定
    # ------------------------------------------------------------------

    @staticmethod
    def should_filter_by_owner(scope: Any) -> bool:
        """判断是否需要按 created_by/owner 过滤（``self`` 模式）。"""
        return getattr(scope, "scope_type", "") == SCOPE_SELF

    # ------------------------------------------------------------------
    # 列表应用
    # ------------------------------------------------------------------

    @staticmethod
    def apply_to_list(
        items: List[Any],
        scope: Any,
        username: str,
        user_dept_id: Optional[str],
        dept_id_field: str = "department_id",
        owner_field: str = "created_by",
        all_child_dept_ids: Optional[List[str]] = None,
    ) -> List[Any]:
        """对内存中的列表数据应用数据范围过滤（适用于已查出的数据）。

        Args:
            items: 数据列表（dict 或对象）。
            scope: :class:`DataScopeRecord`（``resolve_scope`` 的返回值）。
            username: 当前用户名（``self`` 模式按 owner_field 匹配）。
            user_dept_id: 用户所属部门 ID（``dept`` / ``dept_and_child``
                模式无 ``all_child_dept_ids`` 时使用）。
            dept_id_field: 数据中部门 ID 字段名。
            owner_field: 数据中创建者/拥有者字段名。
            all_child_dept_ids: 用户部门及其所有子部门 ID 列表
                （``dept_and_child`` 模式由调用方通过 org service 提前查询）。

        Returns:
            过滤后的列表（原列表不会被修改）。
        """
        scope_type = getattr(scope, "scope_type", SCOPE_ALL)
        if scope_type == SCOPE_ALL:
            return list(items)

        if scope_type == SCOPE_SELF:
            return [
                item for item in items
                if _get_field(item, owner_field) == username
            ]

        visible_depts = DataScopeFilter.get_visible_dept_ids(
            scope, username, user_dept_id, all_child_dept_ids,
        )
        if visible_depts is None:
            return list(items)

        return [
            item for item in items
            if _get_field(item, dept_id_field) in visible_depts
        ]


def _get_field(item: Any, field_name: str) -> Any:
    """从 dict 或对象中获取字段值（兼容两种数据形态）。"""
    if isinstance(item, dict):
        return item.get(field_name)
    return getattr(item, field_name, None)
