# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""_seed_user_roles 单测：flat role 映射补齐 + 幂等 + 零绑定语义（无 PG）。

以伪 pg_store 模拟 ``_get_engine().begin()`` 与 ``_run(coro)`` 契约，验证：
1) 仅"零绑定"用户被补齐（DB 侧过滤语义由查询承载，本测传入零绑定行）；
2) admin→platform_admin、employee→employee 映射正确（FLAT_ROLE_TO_RBAC）；
3) 未知 flat role 与缺失 RBAC 角色均安全跳过、不产生写入；
4) 返回计数 = 实际补齐用户数（重跑为 0，幂等）。
"""
from __future__ import annotations

import asyncio

from qwenpaw.app.rbac import seed


class _Result:
    """伪 SQLAlchemy Result：仅提供 seed 用到的 fetchall/fetchone。"""

    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Conn:
    """伪连接：按 SQL 特征分派——用户清单 / 角色查找 / 绑定写入。"""

    def __init__(self, users, role_names):
        self.users = users
        self.role_names = set(role_names)
        self.inserts = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "FROM qwenpaw_users" in sql:
            return _Result(list(self.users))
        if "FROM rbac_roles" in sql:
            name = params["n"]
            row = (f"rid_{name}",) if name in self.role_names else None
            return _Result([row] if row else [])
        if "INSERT INTO rbac_user_roles" in sql:
            self.inserts.append((params["u"], params["rid"]))
            return _Result([])
        raise AssertionError(f"unexpected SQL: {sql}")


class _Ctx:
    """async with 上下文：begin() 的伪装。"""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_exc):
        return False


class _Engine:
    """伪引擎：begin() 返回 async 上下文。"""

    def __init__(self, conn):
        self._conn = conn

    def begin(self):
        return _Ctx(self._conn)


class _FakePgStore:
    """伪 PgRbacStore：满足 _get_engine 与 _run 两个被调用契约。"""

    def __init__(self, rows, role_names):
        # rows 为"零绑定"用户清单（(username, flat_role) 二元组）。
        self.conn = _Conn(rows, role_names)

    def _get_engine(self):
        return _Engine(self.conn)

    @staticmethod
    def _run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def test_backfills_flat_role_mapping_and_skips_unknown():
    store = _FakePgStore(
        [
            ("admin", "admin"),
            ("eve", "employee"),
            ("ghost", "mystery"),
        ],
        ["platform_admin", "employee"],
    )
    assert seed._seed_user_roles(store) == 2
    assert ("admin", "rid_platform_admin") in store.conn.inserts
    assert ("eve", "rid_employee") in store.conn.inserts
    # 未知 flat role（mystery）不产生任何写入。
    assert all(u != "ghost" for u, _ in store.conn.inserts)


def test_skips_missing_rbac_role():
    # rbac_roles 中不存在 platform_admin：安全跳过、计数 0、无写入。
    store = _FakePgStore([("admin", "admin")], [])
    assert seed._seed_user_roles(store) == 0
    assert store.conn.inserts == []


def test_idempotent_when_no_zero_binding_users():
    # 所有用户均已有绑定（查询返回空集）：不写入、计数 0 —— 幂等重跑。
    store = _FakePgStore([], ["platform_admin", "employee"])
    assert seed._seed_user_roles(store) == 0
    assert store.conn.inserts == []
