# -*- coding: utf-8 -*-
"""M6-1: 0034 知识库 PG 平面迁移断言（PG 门控集成用例）。

运行方式：``QWENPAW_TEST_PG_DSN`` 未设时由 ``app_server`` 派生规则决定；
DSN 走宿主机 ``QWENPAW_PG_DSN`` 同实例的独立库 ``qwenpaw_integration_test``
（绝不读写开发者库，见 conftest._isolate_pg_database 事故注释）。
``app_server`` 夹具启动集成实例时会自动执行 alembic upgrade head，
本用例直连同一隔离库断言 0034 的结构与幂等性。

@author qingfeng
"""
from __future__ import annotations

import asyncio
import os
from typing import List

import asyncpg
import pytest
from sqlalchemy.engine import make_url

pytestmark = [pytest.mark.integration, pytest.mark.p0]

#: 集成测试专用库（与 conftest._INTEGRATION_DB_NAME 保持一致）
_INTEGRATION_DB = "qwenpaw_integration_test"

#: 0034 应交付的六张知识库表
_EXPECTED_TABLES = (
    "kb_spaces",
    "kb_documents",
    "kb_document_versions",
    "kb_chunks",
    "kb_links",
    "agent_kb_bindings",
)

#: 0034 应交付的关键索引（检索前提：HNSW 向量 + GIN 全文）
_EXPECTED_INDEXES = (
    "ix_kb_chunks_embedding",
    "ix_kb_chunks_tsv",
    "uq_kb_documents_path",
)


def _isolation_dsn() -> str:
    """派生隔离库 asyncpg DSN（与 conftest._isolate_pg_database 同源规则）。"""
    dsn = os.environ.get("QWENPAW_PG_DSN", "")
    if not dsn:
        pytest.skip("QWENPAW_PG_DSN not set (PG-gated knowledge base tests)")
    url = make_url(dsn).set(database=_INTEGRATION_DB)
    return url.render_as_string(hide_password=False).replace(
        "postgresql+asyncpg://",
        "postgresql://",
        1,
    )


def test_kb_tables_exist_after_upgrade(app_server) -> None:
    """集成实例启动自动迁移后，六张表与关键索引齐备。"""

    async def _check() -> None:
        conn = await asyncpg.connect(_isolation_dsn())
        try:
            # 断言六张表全部存在
            rows: List[str] = [
                r["table_name"]
                for r in await conn.fetch(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'",
                )
            ]
            missing = [t for t in _EXPECTED_TABLES if t not in rows]
            assert not missing, f"missing kb tables: {missing}"
            # 断言关键索引存在（pgvector HNSW / tsvector GIN / 路径唯一）
            idx_rows = await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = ANY($1)",
                list(_EXPECTED_TABLES),
            )
            indexes = {r["indexname"] for r in idx_rows}
            missing_idx = [i for i in _EXPECTED_INDEXES if i not in indexes]
            assert not missing_idx, f"missing kb indexes: {missing_idx}"
            # 断言 pgvector 扩展与 embedding 列维度（1024，spec §4.2）
            ext = await conn.fetchval(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'",
            )
            assert ext, "pgvector extension not installed"
            col = await conn.fetchval(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = 'kb_chunks'::regclass AND attname = 'embedding'",
            )
            assert col == "vector(1024)", f"unexpected embedding column type: {col}"
        finally:
            await conn.close()

    asyncio.run(_check())


def test_upgrade_is_idempotent(app_server) -> None:
    """0034 重复执行零副作用（幂等 DDL 验证，跑两遍不报错）。"""

    async def _twice() -> None:
        from qwenpaw.db.engine import create_pg_engine
        from qwenpaw.db.migrate import run_migrations

        # 以隔离库 DSN 构造引擎，连续两次应用全部迁移至 head
        engine = create_pg_engine(_pg_sqla_dsn())
        try:
            await run_migrations(engine)
            await run_migrations(engine)
        finally:
            await engine.dispose()

    asyncio.run(_twice())


def _pg_sqla_dsn() -> str:
    """隔离库的 SQLAlchemy asyncpg DSN（run_migrations 用）。"""
    dsn = os.environ.get("QWENPAW_PG_DSN", "")
    return make_url(dsn).set(database=_INTEGRATION_DB).render_as_string(
        hide_password=False,
    )
