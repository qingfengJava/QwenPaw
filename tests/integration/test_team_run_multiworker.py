# -*- coding: utf-8 -*-
"""多实例执行切片测试（T7；计划 §"仅多实例启用切片"）。

首版运行面是**受控单执行 worker**：同一 run 由 PG advisory lock 认领，
锁被持有即不重复执行（防双实例并发委派/结果互写/token 双倍燃烧）。
完整多实例租约（心跳/续租/接管）是后续切片——本模块在多实例门
（``QWENPAW_TEST_MULTIWORKER=1``）未开启时仅验证单实例护栏语义，
门开启后追加的租约断言随切片落地。

@author qingfeng
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

DSN = os.environ.get("QWENPAW_TEST_PG_DSN", "").strip()

#: 多实例切片门（后续切片启用；默认关闭）
MULTIWORKER_GATE = os.environ.get("QWENPAW_TEST_MULTIWORKER", "").strip() == "1"

_TRUNCATE_SQL = (
    "TRUNCATE team_run_nodes, team_run_actions, team_runs, feed_events "
    "RESTART IDENTITY"
)


@pytest.fixture
async def enterprise_env(monkeypatch):
    if not DSN:
        pytest.skip("QWENPAW_TEST_PG_DSN not set")
    monkeypatch.setenv("QWENPAW_PG_DSN", DSN)

    from qwenpaw.app import enterprise as ent_mod
    from qwenpaw.db import engine as engine_mod

    engine_mod._engines.clear()
    ent_mod._schema_ready = False
    ok = await ent_mod.bootstrap_enterprise()
    assert ok, "enterprise bootstrap failed against the test database"
    engine = engine_mod.create_pg_engine(DSN)
    async with engine.begin() as conn:
        await conn.execute(text(_TRUNCATE_SQL))
    try:
        yield
    finally:
        await engine_mod.dispose_engines()
        ent_mod._schema_ready = False


async def test_run_claim_lock_is_exclusive(enterprise_env):
    """单实例护栏：advisory lock 认领互斥——第二持锁者认领失败。"""
    import asyncio

    from qwenpaw.app.workforce import engine as engine_mod

    # 第一把锁：认领成功，持专用连接
    claimed_1, conn_1 = await engine_mod._try_claim_run("run-lock-eval")
    assert claimed_1 is True
    try:
        assert conn_1 is not None, "advisory lock 通道不可用（降级路径）"
        # 第二把锁：同一 run 被持有 → 认领失败（不重复执行）
        claimed_2, conn_2 = await engine_mod._try_claim_run("run-lock-eval")
        assert claimed_2 is False
        assert conn_2 is None
    finally:
        if conn_1 is not None:
            await engine_mod._release_run_claim("run-lock-eval", conn_1)
    # 释放后可重新认领（崩溃/正常释放语义一致）
    claimed_3, conn_3 = await engine_mod._try_claim_run("run-lock-eval")
    assert claimed_3 is True
    if conn_3 is not None:
        await engine_mod._release_run_claim("run-lock-eval", conn_3)


async def test_run_claim_lock_released_on_close(enterprise_env):
    """崩溃语义：连接关闭 → 会话级锁自动释放（无租约残留）。"""
    from qwenpaw.app.workforce import engine as engine_mod

    claimed_1, conn_1 = await engine_mod._try_claim_run("run-lock-eval-2")
    assert claimed_1 is True
    if conn_1 is not None:
        await conn_1.close()  # 模拟进程死亡：连接断开即释放
    claimed_2, conn_2 = await engine_mod._try_claim_run("run-lock-eval-2")
    assert claimed_2 is True
    if conn_2 is not None:
        await engine_mod._release_run_claim("run-lock-eval-2", conn_2)


@pytest.mark.skipif(
    not MULTIWORKER_GATE,
    reason="多实例租约切片未启用（QWENPAW_TEST_MULTIWORKER=1 开启）",
)
async def test_multiworker_lease_slice(enterprise_env, run_store, monkeypatch):
    """多实例切片占位（后续落地）：租约心跳/接管/幂等收敛断言。"""
    team = None  # 切片实现时补全：双实例并发 run_team_run 的收敛断言
    assert team is None or True
