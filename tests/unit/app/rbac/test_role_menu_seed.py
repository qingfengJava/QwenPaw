# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""_write_role_menus 单测：升级差集补齐 + 幂等 + reseed 先删后建（无 PG）。

以伪 pg_store 模拟 ``_get_engine().begin()`` 与 ``_run(coro)`` 契约，守护
启动 seed 的增量补齐语义：版本升级新增的内置菜单（从未被任何角色绑定，
如本体管理 menu_admin_ontology）自动补进期望角色；存量绑定（含运营的
自定义/隐藏配置）一律不触碰、不复活。force=True（reseed）仍为先删后建。
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
    """伪连接：按 SQL 特征分派——绑定差集 / 角色查找 / 删除 / 插入。"""

    def __init__(self, bound_menu_ids, role_names):
        # bound_menu_ids：库中已被任意角色绑定过的菜单 id（差集基准）。
        self.bound_menu_ids = list(bound_menu_ids)
        self.role_names = set(role_names)
        self.inserts = []
        self.deletes = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "SELECT DISTINCT menu_id FROM rbac_role_menus" in sql:
            return _Result([(m,) for m in self.bound_menu_ids])
        if "FROM rbac_roles" in sql:
            name = params["name"]
            row = (f"rid_{name}",) if name in self.role_names else None
            return _Result([row] if row else [])
        if "DELETE FROM rbac_role_menus" in sql:
            self.deletes.append(params["rid"])
            return _Result([])
        if "INSERT INTO rbac_role_menus" in sql:
            self.inserts.append((params["rid"], params["mid"]))
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

    def __init__(self, bound_menu_ids, role_names):
        self.conn = _Conn(bound_menu_ids, role_names)

    def _get_engine(self):
        return _Engine(self.conn)

    @staticmethod
    def _run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


_PA = "rid_platform_admin"
_TL = "rid_team_lead"
_EP = "rid_employee"
_ROLES = ["platform_admin", "team_lead", "employee"]


def test_upgrade_backfills_never_bound_menus():
    """升级场景：存量角色已有历史绑定（不含本体管理），启动 seed 差集
    补齐 menu_admin_ontology 给期望角色；存量菜单不重复写入。"""
    # 存量绑定：旧版菜单（不含 menu_admin_ontology）。
    legacy_bound = {"menu_workbench", "menu_admin_kb", "menu_admin_users"}
    store = _FakePgStore(legacy_bound, _ROLES)
    seed._seed_role_menus(store)
    pairs = set(store.conn.inserts)
    # 新菜单按期望集补齐：platform_admin 与 team_lead 均含本体管理。
    assert (_PA, "menu_admin_ontology") in pairs
    assert (_TL, "menu_admin_ontology") in pairs
    # employee 期望集不含管理菜单，不应被补上。
    assert (_EP, "menu_admin_ontology") not in pairs
    # 存量菜单已在 bound 差集内：不重复写入、不复活。
    assert (_PA, "menu_admin_kb") not in pairs
    assert (_PA, "menu_workbench") not in pairs
    # 启动路径永不删除既有绑定。
    assert store.conn.deletes == []


def test_startup_idempotent_when_all_menus_bound():
    """所有内置菜单均已被绑定（重跑）：零写入，完全幂等。"""
    all_bound = set(seed._ALL_MENU_IDS)
    store = _FakePgStore(all_bound, _ROLES)
    seed._seed_role_menus(store)
    assert store.conn.inserts == []
    assert store.conn.deletes == []


def test_force_reseed_deletes_and_rebuilds():
    """force=True（reseed）：先删后建全量期望绑定，无视 bound 差集。"""
    all_bound = set(seed._ALL_MENU_IDS)
    store = _FakePgStore(all_bound, _ROLES)
    seed._write_role_menus(store, force=True)
    # 三个内置角色全部先删。
    assert sorted(store.conn.deletes) == sorted([_PA, _TL, _EP])
    pairs = set(store.conn.inserts)
    # 即便菜单在 bound 集合中，reseed 也全量重建。
    assert (_PA, "menu_admin_ontology") in pairs
    assert (_PA, "menu_admin_kb") in pairs


def test_missing_role_skipped_safely():
    """RBAC 角色缺失：安全跳过该角色，不产生其任何写入。"""
    store = _FakePgStore({"menu_admin_kb"}, ["platform_admin"])
    seed._seed_role_menus(store)
    assert all(rid == _PA for rid, _ in store.conn.inserts)
    assert all(rid != _TL for rid, _ in store.conn.inserts)
