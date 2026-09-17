# -*- coding: utf-8 -*-
"""M6-1: 0034 知识库 PG 平面迁移断言（PG 门控集成用例）。

运行方式：宿主机 ``QWENPAW_PG_DSN`` 未设时整文件 skip；
DSN 走同一 PG 实例的独立库 ``qwenpaw_integration_test``
（经 ``_isolate_pg_database`` 同源规则派生，绝不读写开发者库）。
``app_server`` 夹具启动集成实例时会自动执行 alembic upgrade head，
本文件直连同一隔离库断言 0034 的结构契约与 DDL 幂等性。

@author qingfeng
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
from typing import List

import asyncpg
import pytest
from sqlalchemy.engine import make_url

pytestmark = [pytest.mark.integration, pytest.mark.p0]

#: 集成测试专用库（与 conftest._INTEGRATION_DB_NAME 保持一致）
_INTEGRATION_DB = "qwenpaw_integration_test"

#: 0034 迁移文件路径（_load_migration 动态加载，文件名以数字开头不可直接 import）
_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "qwenpaw"
    / "db"
    / "alembic"
    / "versions"
    / "0034_kb_pg_plane.py"
)

#: 0034 应交付的六张知识库表
_EXPECTED_TABLES = (
    "kb_spaces",
    "kb_documents",
    "kb_document_versions",
    "kb_chunks",
    "kb_links",
    "agent_kb_bindings",
)

#: 0034 应交付的全部索引（检索前提：HNSW 向量 + GIN 全文 + 路径唯一）
_EXPECTED_INDEXES = (
    "ix_kb_spaces_scope",
    "ix_kb_documents_space",
    "uq_kb_documents_path",
    "ix_kb_document_versions_doc",
    "ix_kb_chunks_space",
    "ix_kb_chunks_document",
    "ix_kb_chunks_tsv",
    "ix_kb_chunks_embedding",
    "ix_kb_links_src",
    "ix_kb_links_dst",
    "ix_agent_kb_bindings_space",
)

#: 0034 应交付的枚举 CHECK 约束
_EXPECTED_CHECKS = (
    "ck_kb_spaces_scope",
    "ck_kb_spaces_engine",
    "ck_kb_documents_source",
    "ck_kb_documents_ingest_status",
)

#: 缺列注释体检 SQL（项目规范：所有字段必须填写 COMMENT）
_SQL_COLUMNS_WITHOUT_COMMENT = """
    SELECT count(*)
    FROM information_schema.columns c
    WHERE c.table_schema = 'public'
      AND c.table_name = ANY($1)
      AND NOT EXISTS (
          SELECT 1
          FROM pg_description d
          JOIN pg_attribute a
            ON a.attrelid = d.objoid AND a.attnum = d.objsubid
          JOIN pg_class cl ON cl.oid = a.attrelid
          WHERE cl.relname = c.table_name
            AND a.attname = c.column_name
            AND d.description IS NOT NULL
            AND d.description <> ''
      )
"""


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


def _load_migration():
    """动态加载 0034 迁移模块，取其语句元组（幂等重放不依赖 alembic 版本表）。"""
    spec = importlib.util.spec_from_file_location(
        "m0034_kb_pg_plane",
        _MIGRATION_PATH,
    )
    assert (
        spec is not None and spec.loader is not None
    ), f"cannot load migration module: {_MIGRATION_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migration_statements() -> List[str]:
    """展开 0034 的全部语句（扩展/建表/CHECK/索引/注释）。"""
    module = _load_migration()
    return (
        [module._CREATE_EXTENSION]
        + list(module._CREATE_TABLES)
        + list(module._ADD_DOC_CHECKS)
        + list(module._INDEXES)
        + list(module._COMMENTS)
    )


def test_kb_structure_contract_after_upgrade(app_server) -> None:
    """结构契约：六表 / 全部索引 / CHECK 枚举 / 列注释零缺失 / 向量维度。"""

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
            # 断言 0034 交付的全部索引存在（含 HNSW 向量与 GIN 全文）
            idx_rows = await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = ANY($1)",
                list(_EXPECTED_TABLES),
            )
            indexes = {r["indexname"] for r in idx_rows}
            missing_idx = [i for i in _EXPECTED_INDEXES if i not in indexes]
            assert not missing_idx, f"missing kb indexes: {missing_idx}"
            # 断言枚举 CHECK 约束齐备（DO 块路径易遗漏，此处守住）
            checks = await conn.fetch(
                "SELECT conname FROM pg_constraint WHERE conname = ANY($1)",
                list(_EXPECTED_CHECKS),
            )
            got_checks = {r["conname"] for r in checks}
            missing_checks = [
                c for c in _EXPECTED_CHECKS if c not in got_checks
            ]
            assert (
                not missing_checks
            ), f"missing check constraints: {missing_checks}"
            # 断言六表列注释零缺失（项目强制条款）
            no_comment = await conn.fetchval(
                _SQL_COLUMNS_WITHOUT_COMMENT,
                list(_EXPECTED_TABLES),
            )
            assert no_comment == 0, f"columns without COMMENT: {no_comment}"
            # 断言 pgvector 扩展与 embedding 列维度（1024，spec §4.2）
            ext = await conn.fetchval(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'",
            )
            assert ext, "pgvector extension not installed"
            col = await conn.fetchval(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = 'kb_chunks'::regclass AND attname = 'embeddi"
                "ng'",
            )
            assert (
                col == "vector(1024)"
            ), f"unexpected embedding column type: {col}"
        finally:
            await conn.close()

    asyncio.run(_check())


def test_migration_ddl_is_idempotent(app_server) -> None:
    """幂等验证：绕开 alembic 版本表，直接重放 0034 全部语句两遍零报错。

    alembic 的 upgrade 由 alembic_version 驱动，对已应用 revision 是 no-op，
    故不能用来验证 DDL 文本幂等；此处直接逐条重放建表/约束/索引/注释语句，
    第二轮必须零报错（IF NOT EXISTS / DO 块 / COMMENT 可重入）。
    重放对象是迁移自身写入的同一套 schema，不引入新对象。
    """

    async def _replay_once(conn) -> None:
        """重放一轮迁移语句，失败时附带语句前缀便于定位。"""
        for stmt in _migration_statements():
            try:
                await conn.execute(stmt)
            except Exception as exc:  # noqa: BLE001
                raise AssertionError(
                    f"stmt failed: {stmt[:120]} -> {exc}",
                ) from exc  # noqa: B904

    async def _twice() -> None:
        conn = await asyncpg.connect(_isolation_dsn())
        try:
            # 连续两轮：首轮对齐现状，次轮验证幂等
            for _ in (1, 2):
                await _replay_once(conn)
        finally:
            await conn.close()

    asyncio.run(_twice())
