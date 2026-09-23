#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline KB migration: JSONL registry/chunks -> PostgreSQL (T8, spec §13).

Migrates, per knowledge space in ``kb_registry.json``:

- ``kb_registry.json`` knowledge_bases -> ``kb_spaces``
- ``kb_registry.json`` documents       -> ``kb_documents``
- ``kb_data/<kb_id>/chunks.jsonl``     -> ``kb_chunks`` (via PgVectorEngine)

Properties（镜像 scripts/migrate_storage_to_pg.py）:

- **Idempotent**: 重跑 upsert 同一批行；``index_document`` 是「重建该文档切片」
  语义（先删后插），故 chunk 计数跨轮稳定，双校验可重复通过。
- **Verifiable**: 逐库双校验（spec §13 风险4）——registry 计数（文档数）+
  chunk 行数（源 jsonl vs pg ``kb_chunks``）；两项全等才算该库 ``OK``，任一
  不符标 ``MISMATCH`` 计入 failed 并以非零码退出。
- **Non-destructive**: 源 registry/jsonl 绝不修改或删除；30 天保留窗口是运维
  决定（spec §13）。成功后写 ``kb_migration_receipt.json`` 记录本轮，供后续清理。

Usage::

    python scripts/migrate_kb_to_pg.py \
        --dsn postgresql+asyncpg://qwenpaw:***@127.0.0.1:5432/qwenpaw \
        [--registry path/to/kb_registry.json] [--data-dir path/to/kb_data] \
        [--dry-run]

@author qingfeng
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("migrate_kb_to_pg")

#: 迁移标记文件名（写在 registry 同目录；供 30 天后运维清理，脚本绝不删源）
RECEIPT_NAME = "kb_migration_receipt.json"


# ---------------------------------------------------------------------------
# source readers (json 面)
# ---------------------------------------------------------------------------


def _load_registry(registry_path: Path) -> Optional[Any]:
    """读 kb_registry.json → KbRegistry；缺失返回 None。"""
    from qwenpaw.app.kb.models import KbRegistry

    if not registry_path.is_file():
        return None
    return KbRegistry.model_validate(
        json.loads(registry_path.read_text(encoding="utf-8")),
    )


def _load_space_chunks(data_dir: Path, kb_id: str) -> List[Any]:
    """读某库全部切片（委托 L0 文件引擎，与门面同一读取口径）。"""
    from qwenpaw.app.kb.file_engine import FileKbEngine

    return FileKbEngine(data_dir=data_dir).load_chunks(kb_id)


# ---------------------------------------------------------------------------
# model mapping (json 读写模型 → pg 权威模型)
# ---------------------------------------------------------------------------


def _kb_to_space(kb: Any) -> Any:
    """KnowledgeBase → KbSpace（grants 三列表收进 grants dict）。"""
    from qwenpaw.app.kb.models import KbSpace

    return KbSpace(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        scope=kb.scope,
        owner_id=kb.owner_id,
        team_id=kb.team_id,
        grants={
            "roles": list(kb.grants_roles),
            "users": list(kb.grants_users),
            "teams": list(kb.grants_teams),
        },
        created_at=kb.created_at,
    )


def _meta_to_document(doc: Any, chunk_count: int) -> Any:
    """KbDocumentMeta → KbDocument（chunk_count 存 source_meta 供门面回读）。"""
    from qwenpaw.app.kb.models import (
        INGEST_READY,
        SOURCE_MANUAL,
        VALID_SOURCES,
        KbDocument,
    )

    pg_source = doc.source if doc.source in VALID_SOURCES else SOURCE_MANUAL
    return KbDocument(
        id=doc.doc_id,
        space_id=doc.kb_id,
        path=f"{doc.doc_id}.md",
        title=doc.title,
        content_md="",
        source=pg_source,
        source_meta={
            "source": doc.source,
            "chunk_count": chunk_count,
            "via": "migrate_kb_to_pg",
        },
        ingest_status=INGEST_READY,
        created_at=doc.created_at,
    )


# ---------------------------------------------------------------------------
# per-space migration + double validation
# ---------------------------------------------------------------------------


async def _preserve_created_at(
    engine: Any,
    table: str,
    id_val: str,
    ts: Any,
) -> None:
    """迁移保真：pg_store upsert 强制 created_at=now，此处回写源时间戳。

    upsert_space/upsert_document 的 INSERT 一律用 now() 覆盖 created_at
    （pg_store.py:346/517），迁移会丢失原始创建时间并打乱 list_spaces 的
    created_at 排序；迁移是保真搬运，故 upsert 后按源值回写（审查 P1-5）。
    """
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(
            text(f"UPDATE {table} SET created_at = :ts WHERE id = :id"),
            {"ts": ts, "id": id_val},
        )


async def _migrate_space(
    kb: Any,
    docs: List[Any],
    chunks: List[Any],
    store: Any,
    pg_engine: Any,
    engine: Any,
    dry_run: bool,
) -> int:
    """迁移单库：upsert space + 逐文档 upsert doc + 引擎重建切片索引。

    返回本库实际迁移的切片数（仅计 registry 文档名下切片，孤儿切片不计），
    供双校验用正确期望值（审查 P2-6）。
    """
    from qwenpaw.app.kb.chunker import ChunkSpec
    from qwenpaw.app.kb.models import INGEST_READY

    if not dry_run:
        await store.upsert_space(_kb_to_space(kb))
        await _preserve_created_at(engine, "kb_spaces", kb.id, kb.created_at)
    # 按 doc_id 分组源切片（保持 seq 升序，与文件面读序一致）
    by_doc: Dict[str, List[Any]] = {}
    for chunk in chunks:
        by_doc.setdefault(chunk.doc_id, []).append(chunk)
    migrated_chunks = 0
    for doc in docs:
        doc_chunks = sorted(by_doc.get(doc.doc_id, []), key=lambda c: c.seq)
        migrated_chunks += len(doc_chunks)
        if dry_run:
            continue
        await store.upsert_document(_meta_to_document(doc, len(doc_chunks)))
        await _preserve_created_at(
            engine, "kb_documents", doc.doc_id, doc.created_at
        )
        # upsert_document 一律落 pending，显式推进 ready（对齐门面/T6，P1-2）
        await store.update_ingest_status(doc.doc_id, INGEST_READY)
        if not doc_chunks:
            continue
        specs = [
            ChunkSpec(
                seq=index,
                heading_path="",
                text=chunk.text,
                parent_seq=None,
                token_count=len(chunk.text),
            )
            for index, chunk in enumerate(doc_chunks)
        ]
        # 仅当全部切片都带向量时才回传 embeddings（否则走 BM25-only，避免
        # 维度不齐撞 vector(1024) 插入失败）
        embeddings: Optional[List[Any]] = None
        if all(chunk.embedding for chunk in doc_chunks):
            embeddings = [chunk.embedding for chunk in doc_chunks]
        await pg_engine.index_document(
            kb.id,
            doc.doc_id,
            specs,
            embeddings,
            title=doc.title,
        )
    return migrated_chunks


async def _validate_space(
    kb_id: str,
    expected_docs: int,
    expected_chunks: int,
    store: Any,
    engine: Any,
) -> Dict[str, Any]:
    """双校验：pg 文档数 == 源；pg kb_chunks 行数 == 源 jsonl 切片数。"""
    from sqlalchemy import text

    pg_docs = await store.list_documents(kb_id, include_deleted=False)
    async with engine.connect() as conn:
        pg_chunks = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM kb_chunks WHERE space_id = :sid",
                ),
                {"sid": kb_id},
            )
        ).scalar()
    got_docs = len(pg_docs)
    got_chunks = int(pg_chunks or 0)
    return {
        "exp_docs": expected_docs,
        "got_docs": got_docs,
        "exp_chunks": expected_chunks,
        "got_chunks": got_chunks,
        "ok": got_docs == expected_docs and got_chunks == expected_chunks,
    }


# ---------------------------------------------------------------------------
# receipt (30 天保留标记；脚本绝不删源)
# ---------------------------------------------------------------------------


def _write_receipt(
    directory: Path,
    migrated: int,
    skipped: int,
    failed: int,
    details: List[Dict[str, Any]],
) -> Path:
    """写迁移标记（时间戳 + 计数 + 明细），供 30 天后运维清理决策。"""
    receipt = {
        "migrated_at": datetime.now(timezone.utc).isoformat(),
        "migrated": migrated,
        "skipped": skipped,
        "failed": failed,
        "spaces": details,
        "note": (
            "source registry/jsonl retained for 30 days (spec §13); "
            "cleanup is an operator decision, this script never deletes"
        ),
        "caveat": (
            "json 面无文档全文（仅切片），故 kb_documents.content_md 迁移后为空；"
            "切片文本已保全于 kb_chunks。30 天清理源前如需全文须人工确认（P2-7）"
        ),
    }
    path = directory / RECEIPT_NAME
    path.write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def _run(args: argparse.Namespace) -> int:
    from sqlalchemy.ext.asyncio import create_async_engine

    from qwenpaw.app.kb.file_engine import DEFAULT_KB_DATA_DIR
    from qwenpaw.app.kb.pg_engine import PgVectorEngine
    from qwenpaw.app.kb.pg_store import KbPgStore
    from qwenpaw.constant import SECRET_DIR
    from qwenpaw.db.migrate import run_migrations

    registry_path = (
        Path(args.registry).expanduser().resolve()
        if args.registry
        else SECRET_DIR / "kb_registry.json"
    )
    data_dir = (
        Path(args.data_dir).expanduser().resolve()
        if args.data_dir
        else DEFAULT_KB_DATA_DIR
    )
    registry = _load_registry(registry_path)
    if registry is None:
        print(f"registry not found: {registry_path}", file=sys.stderr)
        return 2

    dsn = args.dsn or os.environ.get("QWENPAW_PG_DSN", "")
    if not dsn:
        print(
            "no DSN: pass --dsn or set QWENPAW_PG_DSN",
            file=sys.stderr,
        )
        return 2
    engine = create_async_engine(dsn, pool_pre_ping=True)
    migrated = skipped = failed = 0
    details: List[Dict[str, Any]] = []
    try:
        if not args.dry_run:
            await run_migrations(engine)
        store = KbPgStore(engine=engine)
        pg_engine = PgVectorEngine(engine=engine)
        for kb_id, kb in registry.knowledge_bases.items():
            docs = [d for d in registry.documents.values() if d.kb_id == kb_id]
            chunks = _load_space_chunks(data_dir, kb_id)
            # 逐库 try：单库失败不阻断其余库（裁定 R15）
            try:
                migrated_chunks = await _migrate_space(
                    kb, docs, chunks, store, pg_engine, engine, args.dry_run
                )
                if args.dry_run:
                    skipped += 1
                    details.append(
                        {
                            "space": kb_id,
                            "status": "DRY",
                            "docs": len(docs),
                            "chunks": migrated_chunks,
                        },
                    )
                    continue
                # 期望切片数用「registry 文档名下」计数，孤儿切片不计（P2-6）
                result = await _validate_space(
                    kb_id, len(docs), migrated_chunks, store, engine
                )
                if result["ok"]:
                    migrated += 1
                    details.append({"space": kb_id, "status": "OK", **result})
                else:
                    failed += 1
                    details.append(
                        {"space": kb_id, "status": "MISMATCH", **result},
                    )
            except Exception as exc:  # pylint: disable=broad-except
                failed += 1
                logger.warning(
                    "space %s migration failed: %s", kb_id, exc, exc_info=True
                )
                details.append(
                    {"space": kb_id, "status": "ERROR", "error": str(exc)},
                )
    finally:
        await engine.dispose()

    mode = "DRY-RUN" if args.dry_run else "APPLIED"
    print(f"\n=== kb migration {mode} ===")
    for detail in details:
        print(f"  {detail}")
    print(
        f"  summary: migrated={migrated} skipped={skipped} failed={failed}",
    )
    ok = failed == 0
    # 仅在实跑且全库通过时落 receipt（dry-run 不留痕）
    if ok and not args.dry_run:
        receipt = _write_receipt(
            registry_path.parent, migrated, skipped, failed, details
        )
        print(f"  receipt: {receipt}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dsn",
        default="",
        help="SQLAlchemy async DSN (default: $QWENPAW_PG_DSN)",
    )
    parser.add_argument(
        "--registry",
        default="",
        help="kb_registry.json path (default: SECRET_DIR/kb_registry.json)",
    )
    parser.add_argument(
        "--data-dir",
        default="",
        help="kb_data dir (default: SECRET_DIR/kb_data)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="count only, write nothing",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
