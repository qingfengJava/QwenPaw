# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""create_pg_engine 的 per-(DSN, loop) 缓存契约（跨 loop 池防腐）。

asyncpg 池绑定创建时的事件循环：共享池被影子写守护 loop / KB 桥接 loop /
lifespan 主 loop 跨 loop 复用时，协程会永久挂在语句上，泄漏
``idle in transaction`` 连接直至池耗尽（治理/文档接口转圈的根因）。
本套件守护「每 loop 一池、同 loop 内共享」的缓存语义。
"""

from __future__ import annotations

import asyncio

from qwenpaw.db import engine as engine_mod

_DSN = "postgresql+asyncpg://x"


def _set_dsn(monkeypatch) -> None:
    monkeypatch.setenv("QWENPAW_PG_DSN", _DSN)


def test_same_loop_reuses_cached_engine(monkeypatch):
    """同一事件循环内重复获取返回同一 engine（同 loop 内 shadow/权威共享）。"""
    _set_dsn(monkeypatch)

    async def _driver():
        first = engine_mod.create_pg_engine(_DSN)
        second = engine_mod.create_pg_engine(_DSN)
        assert first is second

    try:
        asyncio.run(_driver())
    finally:
        asyncio.run(engine_mod.dispose_engines())


def test_different_loops_get_distinct_engines(monkeypatch):
    """不同 loop 各自建池（跨 loop 复用共享池会挂死连接）。"""
    _set_dsn(monkeypatch)
    results = {}

    async def _driver(key):
        results[key] = engine_mod.create_pg_engine(_DSN)

    try:
        asyncio.run(_driver("a"))
        asyncio.run(_driver("b"))
        assert results["a"] is not results["b"]
    finally:
        asyncio.run(engine_mod.dispose_engines())


def test_dedicated_engine_never_cached(monkeypatch):
    """dedicated=True 恒新建不入缓存；共享引擎仍按 loop 缓存。"""
    _set_dsn(monkeypatch)

    async def _driver():
        dedicated_a = engine_mod.create_pg_engine(_DSN, dedicated=True)
        dedicated_b = engine_mod.create_pg_engine(_DSN, dedicated=True)
        shared_a = engine_mod.create_pg_engine(_DSN)
        shared_b = engine_mod.create_pg_engine(_DSN)
        assert dedicated_a is not dedicated_b
        assert shared_a is shared_b

    try:
        asyncio.run(_driver())
    finally:
        asyncio.run(engine_mod.dispose_engines())
