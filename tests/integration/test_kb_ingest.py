# -*- coding: utf-8 -*-
"""M6（T6）PG 真机集成：摄入往返（状态机 / 版本链 / links / BM25 可见）。

门控：宿主机 ``QWENPAW_PG_DSN`` 未设时整文件 skip；DSN 走同一 PG 实例
的独立库 ``qwenpaw_integration_test``（与 conftest 同源派生规则），绝不
读写开发者库。``app_server`` 夹具保证隔离库已 alembic upgrade head。

净注入面：``store`` / ``engine`` 直连隔离引擎（不触碰默认工厂与共享
单例），embedding 一律降级 ``None``——整链零网络、零模型依赖。

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
_SPACE = "kb_it_t6"

#: 主文档正文（frontmatter 权威 + 归一化链接 + 悬挂链接 + BM25 关键词）
_MAIN_MD = (
    "---\n"
    "title: 主文档\n"
    "tags: [用药]\n"
    "---\n"
    "# 甲减 > 用药\n\n"
    "见 [[ref]] 与 [[悬挂/目标]]。\n\n"
    "左甲状腺素的妊娠早期剂量调整需要监测 TSH。\n"
)


def _isolation_asyncpg_engine():
    """用 SQLAlchemy async 引擎指向隔离库（NullPool，跨临时循环复用）。"""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    dsn = os.environ.get("QWENPAW_PG_DSN", "")
    if not dsn:
        pytest.skip("QWENPAW_PG_DSN not set (PG-gated knowledge base tests)")
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
                "DELETE FROM kb_document_versions WHERE document_id "
                "IN (SELECT id FROM kb_documents WHERE space_id = :space)",
            ),
            {"space": _SPACE},
        )
        await conn.execute(
            text("DELETE FROM kb_chunks WHERE space_id = :space"),
            {"space": _SPACE},
        )
        await conn.execute(
            text("DELETE FROM kb_links WHERE space_id = :space"),
            {"space": _SPACE},
        )
        await conn.execute(
            text("DELETE FROM kb_documents WHERE space_id = :space"),
            {"space": _SPACE},
        )
        await conn.execute(
            text("DELETE FROM kb_spaces WHERE id = :space"),
            {"space": _SPACE},
        )


async def _version_count(engine, document_id: str) -> int:
    """当前文档的版本快照条数。"""
    from sqlalchemy import text

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT count(*) AS c FROM kb_document_versions "
                    "WHERE document_id = :doc_id",
                ),
                {"doc_id": document_id},
            )
        ).first()
    return int(row.c or 0)


def test_kb_ingest_roundtrip(app_server, monkeypatch) -> None:
    """T6 摄入真库往返：状态机 / frontmatter / links 解析 / 检索 / 幂等。"""

    async def _no_embed(texts, model="", agent_id=""):
        """向量能力禁用：集成链只验 BM25（零网络）。"""
        return None

    from qwenpaw.app.kb import ingest

    monkeypatch.setattr(ingest, "embed_texts", _no_embed)

    async def _run() -> None:
        from qwenpaw.app.kb.models import KbSpace
        from qwenpaw.app.kb.pg_engine import PgVectorEngine
        from qwenpaw.app.kb.pg_store import KbPgStore

        engine = _isolation_asyncpg_engine()
        store = KbPgStore(engine=engine)
        l1 = PgVectorEngine(engine=engine)
        try:
            await _cleanup(engine)
            assert await store.ensure_ready() is True
            assert (
                await store.upsert_space(
                    KbSpace(
                        id=_SPACE,
                        name="T6 摄入集成库",
                        description="集成相关内容时检索我",
                        engine="pgvector",
                    ),
                )
                is True
            )

            # 先摄被引用文档：[[ref]] 经 .md 归一化应解析到它
            ref = await ingest.ingest_space_document(
                space_id=_SPACE,
                title="参考",
                path="ref.md",
                content_md="# 参考\n\n被引用的内容。\n",
                source="upload",
                store=store,
                engine=l1,
            )
            assert ref.status == "ready"
            assert ref.chunk_count > 0

            # 主文档：frontmatter 权威 + 归一化/悬挂链接 + 唯一关键词
            main = await ingest.ingest_space_document(
                space_id=_SPACE,
                title="备选标题",
                path="main.md",
                content_md=_MAIN_MD,
                source="upload",
                source_meta={"filename": "main.md"},
                store=store,
                engine=l1,
            )
            assert main.status == "ready"
            assert main.doc_id.startswith("doc_")
            assert main.chunk_count > 0
            assert main.doc_id != ref.doc_id

            # 状态机 + frontmatter 权威 + 版本链
            detail = await store.get_document(main.doc_id)
            assert detail is not None
            assert detail.ingest_status == "ready"
            assert detail.error == ""
            assert detail.title == "主文档"
            assert detail.source_meta["filename"] == "main.md"
            assert detail.source_meta["tags"] == ["用药"]
            assert await _version_count(engine, main.doc_id) == 1

            # links 出边：[[ref]] 归一化命中 / 悬挂目标落空串
            edges = await store.list_document_links(main.doc_id)
            resolved = {dst: dst_id for dst, dst_id, _ in edges}
            assert resolved["ref"] == ref.doc_id
            assert resolved["悬挂/目标"] == ""

            # BM25 检索可见（中文分词两端同源）
            hits = await l1.search([_SPACE], "左甲状腺素", None, 5)
            assert hits, "ingested chunks must be retrievable via tsvector"
            assert hits[0].document_id == main.doc_id

            # 重摄（同 path 同 hash 且 ready）：短路零写、版本不抖
            again = await ingest.ingest_space_document(
                space_id=_SPACE,
                title="备选标题",
                path="main.md",
                content_md=_MAIN_MD,
                source="upload",
                source_meta={"filename": "main.md"},
                store=store,
                engine=l1,
            )
            assert again.doc_id == main.doc_id
            assert again.status == "ready"
            assert again.chunk_count == 0
            assert await _version_count(engine, main.doc_id) == 1

            # 内容变更：同 doc_id 更新、版本 +1、索引重建
            changed = await ingest.ingest_space_document(
                space_id=_SPACE,
                title="备选标题",
                path="main.md",
                content_md=_MAIN_MD.replace(
                    "剂量调整需要",
                    "剂量调整与监测需要",
                ),
                source="upload",
                source_meta={"filename": "main.md"},
                store=store,
                engine=l1,
            )
            assert changed.doc_id == main.doc_id
            assert changed.status == "ready"
            assert changed.chunk_count > 0
            assert await _version_count(engine, main.doc_id) == 2
        finally:
            await _cleanup(engine)
            await engine.dispose()

    asyncio.run(_run())
