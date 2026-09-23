# -*- coding: utf-8 -*-
"""T8: 存量 JSONL→PG 迁移脚本集成测（PG 门控）。

运行方式：宿主 ``QWENPAW_PG_DSN`` 未设时整文件 skip；DSN 派生隔离库
``qwenpaw_integration_test``（与 conftest._isolate_pg_database 同源规则，绝不
读写开发者库）。不依赖 ``app_server`` 子进程（避其本机偶发启动就绪超时）：
本文件自建隔离库（幂等 CREATE DATABASE），schema 由脚本内 ``run_migrations``
（alembic upgrade head，含 0034 六表 + pgvector 扩展）落地。固定 ID 空间首尾
清理，不往隔离库留残留。

@author qingfeng
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
from sqlalchemy.engine import make_url

pytestmark = [pytest.mark.integration, pytest.mark.p0]

#: 集成测试专用库（与 conftest._INTEGRATION_DB_NAME 保持一致）
_INTEGRATION_DB = "qwenpaw_integration_test"

#: 迁移脚本路径（根 scripts/，非包，importlib 按路径加载）
_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "migrate_kb_to_pg.py"
)

#: 固定迁移源 ID（首尾清理，不往隔离库留残留）
_SPACE_A = "kb_mig_a"
_SPACE_B = "kb_mig_b"
_ALL_SPACES = (_SPACE_A, _SPACE_B)

#: 迁移保真断言用显式旧创建时间（若 _preserve_created_at 失效，pg_store
#: upsert 的 INSERT 会用 now() 覆盖，读回年份即当前年而非 2020）
_OLD_TS = datetime(2020, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# DSN 派生 + 隔离库自建
# ---------------------------------------------------------------------------


def _base_dsn() -> str:
    dsn = os.environ.get("QWENPAW_PG_DSN", "")
    if not dsn:
        pytest.skip("QWENPAW_PG_DSN not set (PG-gated kb migration test)")
    return dsn


def _sqlalchemy_dsn() -> str:
    """隔离库的 SQLAlchemy asyncpg DSN（供脚本 create_async_engine）。"""
    url = make_url(_base_dsn()).set(database=_INTEGRATION_DB)
    if "+asyncpg" not in url.drivername:
        url = url.set(drivername="postgresql+asyncpg")
    return url.render_as_string(hide_password=False)


def _plain_dsn() -> str:
    """隔离库的 asyncpg 原生 DSN（供断言直连查询）。"""
    url = make_url(_base_dsn()).set(database=_INTEGRATION_DB)
    return url.render_as_string(hide_password=False).replace(
        "postgresql+asyncpg://",
        "postgresql://",
        1,
    )


@pytest.fixture(scope="module")
def isolated_db() -> str:
    """确保隔离库存在（幂等 CREATE DATABASE），返回 SQLAlchemy DSN。"""
    import asyncpg

    admin = make_url(_base_dsn()).set(database="postgres")
    admin_dsn = admin.render_as_string(hide_password=False).replace(
        "postgresql+asyncpg://",
        "postgresql://",
        1,
    )

    async def _ensure() -> None:
        conn = await asyncpg.connect(admin_dsn)
        try:
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1",
                _INTEGRATION_DB,
            )
            if not exists:
                await conn.execute(f'CREATE DATABASE "{_INTEGRATION_DB}"')
        finally:
            await conn.close()

    asyncio.run(_ensure())
    return _sqlalchemy_dsn()


def _load_script() -> Any:
    """importlib 按路径加载迁移脚本模块（非包）。"""
    spec = importlib.util.spec_from_file_location(
        "migrate_kb_to_pg",
        _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# 迁移源 fixture（json 面：2 库 / 3 文档 / 4 切片）
# ---------------------------------------------------------------------------


def _build_source(tmp_path: Path) -> Tuple[Path, Path]:
    """在 tmp 造 registry + chunks.jsonl 迁移源；返回 (registry_path, data_dir)。"""
    from qwenpaw.app.kb.file_engine import FileKbEngine
    from qwenpaw.app.kb.models import (
        KbChunk,
        KbDocumentMeta,
        KbRegistry,
        KnowledgeBase,
    )

    registry_path = tmp_path / "kb_registry.json"
    data_dir = tmp_path / "kb_data"
    file_engine = FileKbEngine(data_dir=data_dir)
    # 空间 A：2 文档、3 切片
    file_engine.save_chunks(
        _SPACE_A,
        [
            KbChunk(
                chunk_id="c1",
                kb_id=_SPACE_A,
                doc_id="doc_a1",
                seq=0,
                text="alpha deployment notes one",
            ),
            KbChunk(
                chunk_id="c2",
                kb_id=_SPACE_A,
                doc_id="doc_a1",
                seq=1,
                text="alpha deployment notes two",
            ),
            KbChunk(
                chunk_id="c3",
                kb_id=_SPACE_A,
                doc_id="doc_a2",
                seq=2,
                text="alpha second doc",
            ),
        ],
    )
    # 空间 B：1 文档、1 切片
    file_engine.save_chunks(
        _SPACE_B,
        [
            KbChunk(
                chunk_id="c4",
                kb_id=_SPACE_B,
                doc_id="doc_b1",
                seq=0,
                text="beta single chunk",
            ),
        ],
    )
    registry = KbRegistry(
        knowledge_bases={
            _SPACE_A: KnowledgeBase(
                id=_SPACE_A,
                name="Space A",
                scope="enterprise",
                created_at=_OLD_TS,
            ),
            _SPACE_B: KnowledgeBase(
                id=_SPACE_B,
                name="Space B",
                scope="enterprise",
                created_at=_OLD_TS,
            ),
        },
        documents={
            "doc_a1": KbDocumentMeta(
                doc_id="doc_a1",
                kb_id=_SPACE_A,
                title="A1",
                chunk_count=2,
                created_at=_OLD_TS,
            ),
            "doc_a2": KbDocumentMeta(
                doc_id="doc_a2",
                kb_id=_SPACE_A,
                title="A2",
                chunk_count=1,
                created_at=_OLD_TS,
            ),
            "doc_b1": KbDocumentMeta(
                doc_id="doc_b1",
                kb_id=_SPACE_B,
                title="B1",
                chunk_count=1,
                created_at=_OLD_TS,
            ),
        },
    )
    registry_path.write_text(
        json.dumps(registry.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    return registry_path, data_dir


def _args(dsn: str, registry: Path, data_dir: Path, dry_run: bool) -> Any:
    return argparse.Namespace(
        dsn=dsn,
        registry=str(registry),
        data_dir=str(data_dir),
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# pg 侧断言/清理辅助（asyncpg 直连隔离库）
# ---------------------------------------------------------------------------


def _cleanup() -> None:
    """删除固定 ID 空间的全部相关行（六表无外键，逐表清）。"""
    import asyncpg

    async def _do() -> None:
        conn = await asyncpg.connect(_plain_dsn())
        try:
            for table in (
                "kb_chunks",
                "kb_links",
                "agent_kb_bindings",
                "kb_document_versions",
                "kb_documents",
                "kb_spaces",
            ):
                col = "space_id" if table != "kb_spaces" else "id"
                if table in ("kb_document_versions",):
                    await conn.execute(
                        f"DELETE FROM {table} WHERE document_id IN "
                        "(SELECT id FROM kb_documents "
                        "WHERE space_id = ANY($1))",
                        list(_ALL_SPACES),
                    )
                else:
                    await conn.execute(
                        f"DELETE FROM {table} WHERE {col} = ANY($1)",
                        list(_ALL_SPACES),
                    )
        finally:
            await conn.close()

    asyncio.run(_do())


def _pg_state() -> Dict[str, Any]:
    """读回固定 ID 空间的 pg 计数（spaces/docs/chunks）。"""
    import asyncpg

    async def _do() -> Dict[str, Any]:
        conn = await asyncpg.connect(_plain_dsn())
        try:
            spaces = await conn.fetch(
                "SELECT id FROM kb_spaces WHERE id = ANY($1)",
                list(_ALL_SPACES),
            )
            docs = await conn.fetch(
                "SELECT space_id, COUNT(*) AS n FROM kb_documents "
                "WHERE space_id = ANY($1) AND is_delete = false "
                "GROUP BY space_id",
                list(_ALL_SPACES),
            )
            chunks = await conn.fetch(
                "SELECT space_id, COUNT(*) AS n FROM kb_chunks "
                "WHERE space_id = ANY($1) GROUP BY space_id",
                list(_ALL_SPACES),
            )
            return {
                "spaces": {r["id"] for r in spaces},
                "docs": {r["space_id"]: int(r["n"]) for r in docs},
                "chunks": {r["space_id"]: int(r["n"]) for r in chunks},
            }
        finally:
            await conn.close()

    return asyncio.run(_do())


def _pg_created_at_and_status() -> Dict[str, List[Dict[str, Any]]]:
    """读回固定 ID 空间的 created_at 年份（UTC）+ 文档 ingest_status。"""
    import asyncpg

    async def _do() -> Dict[str, List[Dict[str, Any]]]:
        conn = await asyncpg.connect(_plain_dsn())
        try:
            spaces = await conn.fetch(
                "SELECT id, "
                "EXTRACT(YEAR FROM created_at AT TIME ZONE 'UTC')::int AS yr "
                "FROM kb_spaces WHERE id = ANY($1)",
                list(_ALL_SPACES),
            )
            docs = await conn.fetch(
                "SELECT id, "
                "EXTRACT(YEAR FROM created_at AT TIME ZONE 'UTC')::int AS yr, "
                "ingest_status FROM kb_documents WHERE space_id = ANY($1)",
                list(_ALL_SPACES),
            )
            return {
                "spaces": [
                    {"id": r["id"], "year": int(r["yr"])} for r in spaces
                ],
                "docs": [
                    {
                        "id": r["id"],
                        "year": int(r["yr"]),
                        "status": r["ingest_status"],
                    }
                    for r in docs
                ],
            }
        finally:
            await conn.close()

    return asyncio.run(_do())


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------


def test_migration_double_validation(isolated_db: str, tmp_path: Path) -> None:
    """实跑：逐库双校验通过（rc=0）、pg 计数与源一致、receipt 落盘、源保留。"""
    registry_path, data_dir = _build_source(tmp_path)
    module = _load_script()
    _cleanup()
    try:
        rc = asyncio.run(
            module._run(_args(isolated_db, registry_path, data_dir, False)),
        )
        assert rc == 0
        state = _pg_state()
        # 双校验：文档数 + chunk 行数与源逐一吻合
        assert state["spaces"] == set(_ALL_SPACES)
        assert state["docs"] == {_SPACE_A: 2, _SPACE_B: 1}
        assert state["chunks"] == {_SPACE_A: 3, _SPACE_B: 1}
        # receipt 落盘 + 源文件绝不删（Non-destructive）
        receipt = registry_path.parent / module.RECEIPT_NAME
        assert receipt.is_file()
        assert json.loads(receipt.read_text(encoding="utf-8"))["failed"] == 0
        assert registry_path.is_file()
        assert (data_dir / _SPACE_A / "chunks.jsonl").is_file()
    finally:
        _cleanup()


def test_migration_dry_run_writes_nothing(
    isolated_db: str,
    tmp_path: Path,
) -> None:
    """--dry-run：零写 pg、无 receipt、rc=0。"""
    registry_path, data_dir = _build_source(tmp_path)
    module = _load_script()
    _cleanup()
    try:
        rc = asyncio.run(
            module._run(_args(isolated_db, registry_path, data_dir, True)),
        )
        assert rc == 0
        state = _pg_state()
        assert state["spaces"] == set()
        assert not (registry_path.parent / module.RECEIPT_NAME).exists()
    finally:
        _cleanup()


def test_migration_rerun_idempotent(
    isolated_db: str,
    tmp_path: Path,
) -> None:
    """重跑幂等：两轮计数完全一致（upsert + index_document 重建语义）。"""
    registry_path, data_dir = _build_source(tmp_path)
    module = _load_script()
    _cleanup()
    try:
        assert (
            asyncio.run(
                module._run(
                    _args(isolated_db, registry_path, data_dir, False),
                ),
            )
            == 0
        )
        first = _pg_state()
        assert (
            asyncio.run(
                module._run(
                    _args(isolated_db, registry_path, data_dir, False),
                ),
            )
            == 0
        )
        second = _pg_state()
        assert first == second
        assert second["chunks"] == {_SPACE_A: 3, _SPACE_B: 1}
    finally:
        _cleanup()


def test_migration_preserves_created_at_and_status(
    isolated_db: str,
    tmp_path: Path,
) -> None:
    """迁移保真（审查 P1-5/P1-2）：created_at 回写源值、文档推进 ready。

    pg_store 的 upsert_space/upsert_document INSERT 强制 created_at=now、
    upsert_document 强制 ingest_status=pending；迁移是保真搬运，故脚本须
    upsert 后回写源 created_at 并显式推进 ready。断言 pg 侧年份仍为源的
    2020（失效则被 now 覆盖为当前年）、文档状态全为 ready。
    """
    registry_path, data_dir = _build_source(tmp_path)
    module = _load_script()
    _cleanup()
    try:
        rc = asyncio.run(
            module._run(_args(isolated_db, registry_path, data_dir, False)),
        )
        assert rc == 0
        rows = _pg_created_at_and_status()
        # P1-5：空间/文档 created_at 保留源 2020（非 upsert 的 now）
        assert rows["spaces"] and rows["docs"]
        assert all(s["year"] == 2020 for s in rows["spaces"])
        assert all(d["year"] == 2020 for d in rows["docs"])
        # P1-2：文档 ingest_status 全部推进 ready（upsert 默认落 pending）
        assert all(d["status"] == "ready" for d in rows["docs"])
    finally:
        _cleanup()
