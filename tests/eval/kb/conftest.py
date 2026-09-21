# -*- coding: utf-8 -*-
"""KB 检索评测门控与夹具（T8）。

运行门控：宿主机 ``QWENPAW_PG_DSN`` 未设时整目录 skip——评测语义是
「真实 PG 检索管线的质量回归」，无 PG 无从评测。

隔离语义：统一指向同实例的 ``qwenpaw_eval_test`` 一次性库（幂等建库 +
alembic 全量迁移），绝不读写开发者库（2026-09-10 provider 配置覆盖
事故的隔离教训）。评测用独立 ``KbService`` 实例（不取模块级单例）。

环境切换三件套（2026-09-20 诊断定稿，缺一即静默错路由）：
1. ``pg_store.reset_store_for_tests()``——store 单例绑定旧 DSN；
2. ``write_gateway.reset_backend_cache()``——backend 双检锁缓存
   （env 不可变假设），不清则 ``resolve_storage_backend`` 沿用宿主值；
3. teardown 逐键还原 env 后再次双 reset，保证同进程后续测试干净。

清理语义：``delete_space`` 拒删有活文档的库（软删守卫），teardown 的
``delete_kb`` 链路（逐文档软删+引擎清片）脆弱；评测库本身一次性，
清理统一走**直连 SQL 按库名幂等清除**，不依赖业务删除链路。

@author qingfeng
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest

#: 无 PG 配置时整目录 skip（评测语义需要真实检索管线）
if not os.environ.get("QWENPAW_PG_DSN"):
    pytest.skip(
        "KB eval requires QWENPAW_PG_DSN pointing at a real PostgreSQL",
        allow_module_level=True,
    )

#: 评测专用库（与集成测试 qwenpaw_integration_test 平行，互不干扰）
_EVAL_DB = "qwenpaw_eval_test"

#: 评测语料库固定名（幂等清理的锚点）
_EVAL_KB_NAME = "kb-eval-corpus"

#: 夹具涉及、teardown 必须还原的环境变量
_EVAL_ENV_KEYS = (
    "QWENPAW_PG_DSN",
    "QWENPAW_STORAGE_BACKEND",
    "QWENPAW_KB_DEFAULT_ENGINE",
)


def _apply_eval_env(eval_dsn: str) -> dict[str, str | None]:
    """Switch env to the eval database; return saved values for restore."""
    saved = {key: os.environ.get(key) for key in _EVAL_ENV_KEYS}
    os.environ["QWENPAW_PG_DSN"] = eval_dsn
    os.environ["QWENPAW_STORAGE_BACKEND"] = "pg"
    os.environ["QWENPAW_KB_DEFAULT_ENGINE"] = "pgvector"

    # 三件套之 store 单例（绑定旧 DSN 必须丢弃）
    from qwenpaw.app.kb.pg_store import reset_store_for_tests

    reset_store_for_tests()

    # 三件套之 backend 双检锁缓存（env 切换不清则沿用宿主判定）
    from qwenpaw.db import write_gateway

    write_gateway.reset_backend_cache()
    return saved


def _restore_env(saved: dict[str, str | None]) -> None:
    """逐键还原 env 并再次双 reset（保证后续测试干净）。"""
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    from qwenpaw.app.kb.pg_store import reset_store_for_tests
    from qwenpaw.db import write_gateway

    reset_store_for_tests()
    write_gateway.reset_backend_cache()


async def _eval_db_connect(dsn: str):
    """按 DSN 建立评测库 asyncpg 直连（测试专用，不入任何池）。"""
    import asyncpg
    from sqlalchemy.engine import make_url

    url = make_url(dsn)
    return (
        await asyncpg.connect(
            host=url.host,
            port=url.port or 5432,
            user=url.username,
            password=url.password,
            database=url.database,
        ),
        url,
    )


async def _ensure_database_exists(maint_url, db_name: str) -> None:
    """幂等建库（连 postgres 目录库）。"""
    import asyncpg

    conn = await asyncpg.connect(
        host=maint_url.host,
        port=maint_url.port or 5432,
        user=maint_url.username,
        password=maint_url.password,
        database="postgres",
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            db_name,
        )
        if not exists:
            # CREATE DATABASE 不支持参数绑定，库名为常量非用户输入
            await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()


async def _migrate_and_wipe(eval_dsn: str) -> None:
    """迁移到 head + 幂等清理旧评测残留（同一 loop 内建迁移引擎并销毁）。"""
    from qwenpaw.db.engine import create_pg_engine
    from qwenpaw.db.migrate import run_migrations

    # 迁移与 dispose 必须同一 asyncio.run：引擎池的 asyncpg 连接绑定
    # 创建时的 loop，跨 loop dispose 会报 "attached to a different loop"
    async def _run() -> None:
        engine = create_pg_engine(eval_dsn, dedicated=True)
        try:
            await run_migrations(engine)
        finally:
            await engine.dispose()

    await _run()

    # 幂等清理旧残留（含幽灵孤儿：space 已删但 docs/chunks 未清）
    await _wipe_eval_kb(eval_dsn)


async def _pin_engine_pgvector(eval_dsn: str, kb_id: str) -> None:
    """把评测库钉到 pgvector 引擎（评测不依赖外部 Milvus 服务）。"""
    conn, _ = await _eval_db_connect(eval_dsn)
    try:
        await conn.execute(
            "UPDATE kb_spaces SET engine = 'pgvector' WHERE id = $1",
            kb_id,
        )
    finally:
        await conn.close()


async def _wipe_eval_kb(eval_dsn: str) -> None:
    """teardown 直连清理（按库名 + 孤儿行双口径，幂等）。

    孤儿口径：kb_documents/chunks/bindings 无外键（0034），space 行删除后
    子行可残留为幽灵（space_id 指向已不存在的 space），按 name 锚点永远
    匹配不到——评测库是一次性库，孤儿一并物理清除。孤儿必须走**反连接**
    （``NOT IN``），``= ANY(空数组)`` 在 SQL 语义上恒 FALSE 删不到任何行。
    """
    conn, _ = await _eval_db_connect(eval_dsn)
    try:
        for table in ("kb_chunks", "kb_documents", "agent_kb_bindings"):
            # 幽灵孤儿（space 行已删的残留子行；反连接口径）
            await conn.execute(
                f"DELETE FROM {table} WHERE space_id NOT IN "
                "(SELECT id FROM kb_spaces)",
            )
            # 命名库的子行（space 行尚在，按库名锚定）
            await conn.execute(
                f"DELETE FROM {table} WHERE space_id IN "
                "(SELECT id FROM kb_spaces WHERE name = $1)",
                _EVAL_KB_NAME,
            )
        await conn.execute(
            "DELETE FROM kb_spaces WHERE name = $1",
            _EVAL_KB_NAME,
        )
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def eval_kb():
    """评测库 + 评测语料库的会话级夹具（teardown 全量还原）。"""
    from sqlalchemy.engine import make_url

    from qwenpaw.app.kb.service import KbService
    from qwenpaw.db.engine import create_pg_engine
    from qwenpaw.db.migrate import run_migrations
    from tests.eval.kb import corpus

    url = make_url(os.environ["QWENPAW_PG_DSN"])
    if url.database == _EVAL_DB:
        eval_url = url
    else:
        eval_url = url.set(database=_EVAL_DB)
    eval_dsn = eval_url.render_as_string(hide_password=False)

    # 一次性库：幂等建库 + 全量迁移 + 残留清理（绝不碰开发者库）
    asyncio.run(
        _ensure_database_exists(
            eval_url.set(database="postgres"),
            _EVAL_DB,
        ),
    )
    asyncio.run(_migrate_and_wipe(eval_dsn))

    # 环境切换（store 单例 + backend 缓存双 reset）
    saved = _apply_eval_env(eval_dsn)

    svc = KbService()
    kb = svc.create_kb(
        _EVAL_KB_NAME,
        scope="personal",
        owner_id="eval",
        description="T8 retrieval eval corpus",
    )
    if kb is None:
        _restore_env(saved)
        raise RuntimeError("eval kb creation failed")
    asyncio.run(_pin_engine_pgvector(eval_dsn, kb.id))

    # 摄入语料（pg 权威面；默认 knowledge_status=published 可直检）
    for index, doc in enumerate(corpus.DOCUMENTS):
        result = svc.pg_ingest_document(
            space_id=kb.id,
            title=doc["title"],
            path=f"eval/doc{index}.md",
            content_md=doc["text"],
            source="manual",
        )
        if result is None or result.status == "failed":
            _restore_env(saved)
            raise RuntimeError(f"eval ingest failed: doc{index}")
    try:
        yield SimpleNamespace(svc=svc, kb_id=kb.id, eval_dsn=eval_dsn)
    finally:
        # 直连 SQL 清理（不依赖 delete_kb 软删守卫链路）+ 环境还原
        try:
            asyncio.run(_wipe_eval_kb(eval_dsn))
        except Exception:  # noqa: BLE001 - teardown 不阻断
            pass
        _restore_env(saved)
