# -*- coding: utf-8 -*-
"""M6（T6）: 摄入管线——解析路由 / 状态机 / 幂等 / 重触发。

单测面零 PG、零网络：store/engine 注入 fake，embedding 一律降级 None。

@author qingfeng
"""

from __future__ import annotations

import pytest

from qwenpaw.app.kb import ingest
from qwenpaw.app.kb.models import (
    INGEST_FAILED,
    INGEST_PROCESSING,
    INGEST_READY,
    KbDocument,
)
from qwenpaw.app.kb.pg_store import content_hash

pytestmark = pytest.mark.unit


class _FakeStore:
    """内存 KbPgStore：documents + 状态机 + links + 版本计数。"""

    def __init__(self) -> None:
        self.docs: dict[str, KbDocument] = {}
        self.version_count = 0
        self.upsert_calls: list = []
        self.status_updates: list = []
        self.links: dict = {}

    async def get_document_by_path(
        self,
        space_id,
        path,
        *,
        include_deleted=False,
    ):
        for doc in self.docs.values():
            if doc.space_id == space_id and doc.path == path:
                return doc
        return None

    async def get_space(self, space_id):
        return None

    async def upsert_document(self, document):
        self.upsert_calls.append(document)
        digest = content_hash(document.content_md or "")
        existing = self.docs.get(document.id)
        if existing is not None and existing.content_hash == digest:
            return False
        self.version_count += 1
        self.docs[document.id] = document.model_copy(
            update={
                "content_hash": digest,
                "ingest_status": "pending",
                "error": "",
            },
        )
        return True

    async def update_ingest_status(
        self,
        doc_id,
        ingest_status,
        *,
        error="",
    ):
        self.status_updates.append((doc_id, ingest_status, error))
        doc = self.docs.get(doc_id)
        if doc is None:
            return False
        self.docs[doc_id] = doc.model_copy(
            update={"ingest_status": ingest_status, "error": error},
        )
        return True

    async def replace_document_links(self, space_id, src_document_id, edges):
        self.links[src_document_id] = list(edges)
        return len(edges)


class _FakeEngine:
    """内存引擎：记录 index_document 调用（fail 开关模拟写入面异常）。"""

    def __init__(self) -> None:
        self.indexed: list = []
        self.fail = False

    async def index_document(
        self,
        space_id,
        doc_id,
        chunks,
        embeddings=None,
        **kwargs,
    ):
        if self.fail:
            raise RuntimeError("engine boom")
        self.indexed.append((space_id, doc_id, list(chunks), embeddings))
        return len(chunks)


async def _no_embed(texts, model="", agent_id=""):
    """embedding 不可用（降级 BM25-only）。"""
    return None


def _md(body: str = "甲减用药说明。", link: str = "孕产/分期") -> str:
    return (
        "---\n"
        "title: 甲减指南\n"
        "tags: [用药]\n"
        "---\n"
        "# 用药\n\n"
        f"见 [[{link}]]。\n\n"
        f"{body}\n"
    )


def _args(**over):
    base = dict(
        space_id="kb_a",
        title="备选标题",
        path="孕产/用药/甲减.md",
        content_md=_md(),
        source="upload",
        source_meta={"filename": "guide.md"},
    )
    base.update(over)
    return base


def test_parse_upload_md_and_txt() -> None:
    """md / txt / markdown 直读（含 BOM 文本）。"""
    assert "甲减" in ingest.parse_upload("a.md", "甲减说明".encode("utf-8"))
    assert "乙" in ingest.parse_upload("b.txt", "\ufeff乙".encode("utf-8"))
    assert "丙" in ingest.parse_upload("c.markdown", "丙".encode("utf-8"))


def test_parse_html_to_markdown() -> None:
    """HTML 抽取标题与段落为 MD（脚本/样式剔除）。"""
    md = ingest.parse_upload(
        "guide.html",
        b"<h1>T</h1><script>x()</script><p>a</p>",
    )
    assert "# T" in md and "a" in md and "x()" not in md


def test_parse_upload_rejects_unknown() -> None:
    """一期白名单外的格式明确拒绝。"""
    with pytest.raises(ingest.UnsupportedFormat):
        ingest.parse_upload("setup.exe", b"MZ\x90\x00")


def test_parse_pdf_and_docx_routed(monkeypatch) -> None:
    """pdf/docx 进入解析器矩阵（mock 解析器断言分发正确）。"""
    calls: list[str] = []

    def _fake_pdf(data: bytes) -> str:
        calls.append("pdf")
        return "# pdf"

    def _fake_docx(data: bytes) -> str:
        calls.append("docx")
        return "# docx"

    monkeypatch.setattr(ingest, "_pdf_to_md", _fake_pdf)
    monkeypatch.setattr(ingest, "_docx_to_md", _fake_docx)
    assert ingest.parse_upload("a.pdf", b"%PDF-1.4 fake") == "# pdf"
    assert ingest.parse_upload("b.docx", b"PK\x03\x04 fake") == "# docx"
    assert calls == ["pdf", "docx"]


@pytest.mark.asyncio
async def test_ingest_happy_path(monkeypatch) -> None:
    """全绿链路：状态机 processing→ready + 切片 + links + fm 权威。"""
    monkeypatch.setattr(ingest, "embed_texts", _no_embed)
    store = _FakeStore()
    engine = _FakeEngine()
    result = await ingest.ingest_space_document(
        **_args(),
        store=store,
        engine=engine,
    )
    assert result.status == INGEST_READY
    assert result.doc_id.startswith("doc_")
    assert result.chunk_count > 0
    assert store.version_count == 1
    assert [item[1] for item in store.status_updates] == [
        INGEST_PROCESSING,
        INGEST_READY,
    ]
    doc = store.docs[result.doc_id]
    assert doc.title == "甲减指南"
    assert doc.source == "upload"
    assert doc.source_meta["filename"] == "guide.md"
    assert doc.source_meta["tags"] == ["用药"]
    edges = store.links[result.doc_id]
    assert edges[0][0] == "孕产/分期"
    assert edges[0][1] == ""
    assert engine.indexed and engine.indexed[0][1] == result.doc_id
    specs = engine.indexed[0][2]
    assert specs[0].seq == 0
    assert engine.indexed[0][3] is None


@pytest.mark.asyncio
async def test_ingest_hash_dedup_short_circuit(monkeypatch) -> None:
    """同 path 同 hash 且 ready：二次摄入零写短路（不重切不重建）。"""
    monkeypatch.setattr(ingest, "embed_texts", _no_embed)
    calls: list[str] = []

    async def _fake_write(*args, **kwargs):
        calls.append("w")
        return 1

    monkeypatch.setattr(ingest, "_write_chunks", _fake_write)
    store = _FakeStore()
    engine = _FakeEngine()
    r1 = await ingest.ingest_space_document(
        **_args(),
        store=store,
        engine=engine,
    )
    r2 = await ingest.ingest_space_document(
        **_args(),
        store=store,
        engine=engine,
    )
    assert r1.doc_id == r2.doc_id
    assert calls == ["w"]
    assert r2.status == INGEST_READY
    assert r2.chunk_count == 0
    assert store.version_count == 1
    assert len(store.upsert_calls) == 1


@pytest.mark.asyncio
async def test_ingest_failed_retry_rebuilds(monkeypatch) -> None:
    """失败重触发：同内容重摄不被短路吞掉，重建至 ready 且版本不抖。"""
    monkeypatch.setattr(ingest, "embed_texts", _no_embed)
    store = _FakeStore()
    bad = _FakeEngine()
    bad.fail = True
    r1 = await ingest.ingest_space_document(
        **_args(),
        store=store,
        engine=bad,
    )
    assert r1.status == INGEST_FAILED
    assert store.docs[r1.doc_id].error
    good = _FakeEngine()
    r2 = await ingest.ingest_space_document(
        **_args(),
        store=store,
        engine=good,
    )
    assert r2.status == INGEST_READY
    assert r2.doc_id == r1.doc_id
    assert store.version_count == 1
    assert good.indexed


@pytest.mark.asyncio
async def test_ingest_content_change_bumps_version(monkeypatch) -> None:
    """同 path 内容变更：同 doc_id 更新，版本 +1 并重建索引。"""
    monkeypatch.setattr(ingest, "embed_texts", _no_embed)
    store = _FakeStore()
    engine = _FakeEngine()
    r1 = await ingest.ingest_space_document(
        **_args(),
        store=store,
        engine=engine,
    )
    r2 = await ingest.ingest_space_document(
        **_args(content_md=_md(body="修改后的说明。")),
        store=store,
        engine=engine,
    )
    assert r1.doc_id == r2.doc_id
    assert store.version_count == 2
    assert r2.status == INGEST_READY


@pytest.mark.asyncio
async def test_ingest_blank_content_rejected() -> None:
    """空白正文不是可摄入文档（编程错误，值级拒绝）。"""
    with pytest.raises(ValueError):
        await ingest.ingest_space_document(
            **_args(content_md="   \n"),
            store=_FakeStore(),
            engine=_FakeEngine(),
        )


@pytest.mark.asyncio
async def test_ingest_archive_upload(monkeypatch, tmp_path) -> None:
    """上传原文归档落盘（fail-soft 附加能力）。"""
    monkeypatch.setattr(ingest, "embed_texts", _no_embed)
    monkeypatch.setattr(ingest, "_UPLOAD_ROOT", tmp_path)
    result = await ingest.ingest_space_document(
        **_args(),
        uploaded_from=b"raw-bytes",
        store=_FakeStore(),
        engine=_FakeEngine(),
    )
    archived = list(tmp_path.rglob("*.md"))
    assert any(item.name.startswith(result.doc_id) for item in archived)
    assert archived[0].read_bytes() == b"raw-bytes"


@pytest.mark.asyncio
async def test_ingest_store_errors_converge_failed(monkeypatch) -> None:
    """工厂异常与短路探测异常均收敛为 failed（不向上抛，审查 F3）。"""

    async def _boom_factory():
        raise RuntimeError("factory boom")

    monkeypatch.setattr(ingest, "get_ready_kb_pg_store", _boom_factory)
    result = await ingest.ingest_space_document(
        **_args(), engine=_FakeEngine()
    )
    assert result.status == INGEST_FAILED
    assert result.doc_id == ""

    class _BoomProbe(_FakeStore):
        async def get_document_by_path(
            self,
            space_id,
            path,
            *,
            include_deleted=False,
        ):
            raise RuntimeError("probe boom")

    result2 = await ingest.ingest_space_document(
        **_args(),
        store=_BoomProbe(),
        engine=_FakeEngine(),
    )
    assert result2.status == INGEST_FAILED


@pytest.mark.asyncio
async def test_ingest_resolves_engine_when_not_injected(monkeypatch) -> None:
    """engine 未注入：按 space 路由解析（space 缺失传 None，R14 分支）。"""
    monkeypatch.setattr(ingest, "embed_texts", _no_embed)
    captured: list = []

    def _fake_resolve(space):
        captured.append(space)
        return _FakeEngine()

    monkeypatch.setattr(ingest, "resolve_engine_for", _fake_resolve)
    result = await ingest.ingest_space_document(**_args(), store=_FakeStore())
    assert result.status == INGEST_READY
    # _FakeStore.get_space 返回 None：路由解析收到 None（R14 不阻断）
    assert captured == [None]
