# -*- coding: utf-8 -*-
"""M6-7（T7）PG 真机集成：绑定授权往返（幂等 / 读回 / 删库回收）。

门控：宿主机 ``QWENPAW_TEST_PG_DSN`` 未设时整文件 skip；隔离库与清理
规则同 ``test_kb_ingest.py``。HTTP 形状（401/403/404/201/200/204）由
``tests/unit/app/routers/test_kb_bindings_router.py`` 零 PG 覆盖，本文件
专注真库闭环：bindings 三态分流 → KbPgStore 访问器 → 表行。

净注入面：bindings 的 backend 判定与 pg store 提供方均 monkeypatch 到
隔离引擎实例，不触碰默认工厂与共享单例；零网络、零模型依赖。

@author qingfeng
"""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy.engine import make_url

pytestmark = [pytest.mark.integration, pytest.mark.p0]

#: 集成测试专用库（与 conftest._INTEGRATION_DB_NAME 保持一致）
_INTEGRATION_DB = "qwenpaw_integration_test"

#: 本用例的固定空间 ID（首尾清理，不留残留）
_SPACE = "kb_it_t7"


def _isolation_asyncpg_engine():
    """用 SQLAlchemy async 引擎指向隔离库（NullPool，跨临时循环复用）。"""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    dsn = os.environ.get("QWENPAW_TEST_PG_DSN", "")
    if not dsn:
        pytest.skip("QWENPAW_TEST_PG_DSN not set (PG-gated kb binding tests)")
    url = make_url(dsn).set(database=_INTEGRATION_DB)
    if "+asyncpg" not in url.drivername:
        url = url.set(drivername="postgresql+asyncpg")
    return create_async_engine(
        url.render_as_string(hide_password=False),
        poolclass=NullPool,
    )


async def _cleanup(engine) -> None:
    """清除本用例写入的全部行（隔离库可反复跑的前提）。"""
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM agent_kb_bindings WHERE space_id = :space",
            ),
            {"space": _SPACE},
        )
        await conn.execute(
            text("DELETE FROM kb_spaces WHERE id = :space"),
            {"space": _SPACE},
        )


def test_kb_bindings_roundtrip(app_server, monkeypatch) -> None:
    """绑定真库往返：幂等插入 / 读回 / 解绑 / 删库回收绑定。"""
    del app_server  # 隔离库已由夹具 alembic upgrade head

    async def _run() -> None:
        from qwenpaw.app.kb import bindings
        from qwenpaw.app.kb.models import KbSpace
        from qwenpaw.app.kb.pg_store import KbPgStore

        engine = _isolation_asyncpg_engine()
        store = KbPgStore(engine=engine)
        try:
            await _cleanup(engine)
            assert await store.ensure_ready() is True
            assert (
                await store.upsert_space(
                    KbSpace(
                        id=_SPACE,
                        name="T7 绑定集成库",
                        description="绑定往返用例专用空间",
                        scope="personal",
                        owner_id="alice",
                    ),
                )
                is True
            )

            # bindings 三态分流切到隔离 store（pg 语义）
            monkeypatch.setattr(
                bindings.write_gateway,
                "resolve_storage_backend",
                lambda: "pg",
            )
            monkeypatch.setattr(bindings, "_pg_store", lambda: store)

            # 绑定：幂等插入
            assert (
                await bindings.bind_agent_kb(
                    agent_id="it_agent",
                    space_id=_SPACE,
                    granted_by="alice",
                    remark="集成授权",
                )
                is True
            )
            # 重复绑定：仍成立且不产生重复行
            assert (
                await bindings.bind_agent_kb(
                    agent_id="it_agent",
                    space_id=_SPACE,
                    granted_by="alice",
                )
                is True
            )
            assert await bindings.list_bound_space_ids("it_agent") == [
                _SPACE,
            ]

            # GET 组装：名称/scope/授权人经一次批量组装
            listed = await bindings.list_bindings("it_agent")
            assert len(listed) == 1
            assert listed[0]["space_name"] == "T7 绑定集成库"
            assert listed[0]["scope"] == "personal"
            assert listed[0]["granted_by"] == "alice"

            # 管理权：personal 库 owner 命中；非 owner 拒绝
            assert await bindings.can_manage_space(_SPACE, "alice") is True
            assert await bindings.can_manage_space(_SPACE, "bob") is False

            # 解绑：True → 再次 False
            assert (
                await bindings.unbind_agent_kb(
                    "it_agent",
                    _SPACE,
                )
                is True
            )
            assert await bindings.list_bound_space_ids("it_agent") == []
            assert await bindings.unbind_agent_kb("it_agent", _SPACE) is False

            # 删库回收：重绑后删空间，绑定行必须被同事务清走
            assert (
                await bindings.bind_agent_kb(
                    agent_id="it_agent",
                    space_id=_SPACE,
                    granted_by="alice",
                )
                is True
            )
            assert await store.delete_space(_SPACE) is True
            assert await store.list_agent_bindings("it_agent") == []

            # 版本链读端（T2 派生入口）：空文档返回空列表零异常
            assert await store.list_document_versions("no_such_doc") == []
        finally:
            await _cleanup(engine)
            await engine.dispose()

    asyncio.run(_run())
