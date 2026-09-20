# -*- coding: utf-8 -*-
"""KB 检索评测门控与夹具（T8）。

运行门控：宿主机 ``QWENPAW_PG_DSN`` 未设时整目录 skip——评测语义是
「真实 PG 检索管线的质量回归」，无 PG 无从评测。

隔离语义：统一指向同实例的 ``qwenpaw_eval_test`` 一次性库（幂等建库 +
alembic 全量迁移），绝不读写开发者库（2026-09-10 provider 配置覆盖
事故的隔离教训）。评测用独立 ``KbService`` 实例（不取模块级单例），
夹具 teardown 还原全部环境变量并重置 pg store 单例缓存。

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

#: 夹具涉及、teardown 必须还原的环境变量
_EVAL_ENV_KEYS = (
    "QWENPAW_PG_DSN",
    "QWENPAW_STORAGE_BACKEND",
    "QWENPAW_KB_DEFAULT_ENGINE",
)


async def _ensure_database(maint_url, db_name: str) -> None:
    """幂等建库：连维护库查 pg_database，缺则 CREATE DATABASE。"""
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


async def _pin_engine_pgvector(dsn: str, kb_id: str) -> None:
    """把评测库钉到 pgvector 引擎（评测不依赖外部 Milvus 服务）。"""
    import asyncpg

    from sqlalchemy.engine import make_url

    url = make_url(dsn)
    conn = await asyncpg.connect(
        host=url.host,
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database=url.database,
    )
    try:
        await conn.execute(
            "UPDATE kb_spaces SET engine = 'pgvector' WHERE id = $1",
            kb_id,
        )
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def eval_kb():
    """评测库 + 评测语料库的会话级夹具（teardown 全量还原）。"""
    from sqlalchemy.engine import make_url

    from qwenpaw.app.kb.pg_store import reset_store_for_tests
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

    # 一次性库：幂等建库 + 全量迁移（评测进程独占，不碰开发者库）
    asyncio.run(_ensure_database(eval_url.set(database="postgres"), _EVAL_DB))
    engine = create_pg_engine(eval_dsn, dedicated=True)
    try:
        asyncio.run(run_migrations(engine))
    finally:
        asyncio.run(engine.dispose())

    # 环境切换：先记原值，评测结束后逐键还原 + 重置单例缓存
    saved = {key: os.environ.get(key) for key in _EVAL_ENV_KEYS}
    os.environ["QWENPAW_PG_DSN"] = eval_dsn
    os.environ["QWENPAW_STORAGE_BACKEND"] = "pg"
    os.environ["QWENPAW_KB_DEFAULT_ENGINE"] = "pgvector"
    reset_store_for_tests()

    svc = KbService()
    kb = svc.create_kb(
        "kb-eval-corpus",
        scope="personal",
        owner_id="eval",
        description="T8 retrieval eval corpus",
    )
    if kb is None:
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
            raise RuntimeError(f"eval ingest failed: doc{index}")
    try:
        yield SimpleNamespace(svc=svc, kb_id=kb.id)
    finally:
        # 评测数据清理 + 环境还原（best-effort，库本身一次性）
        try:
            svc.delete_kb(kb.id)
        except Exception:  # noqa: BLE001 - teardown 不阻断
            pass
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_store_for_tests()
