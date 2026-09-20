# -*- coding: utf-8 -*-
"""T2 Evidence 层接线回归：查询向量 / 结构化摄入 / milvus 文档切片。

锁定三条此前「机制就绪、生产断线」的装配面（ultra-review Critical）：

1. **读侧向量**：``KbService.search`` 的 pg 分支在 ``query_embedding``
   缺省时按库的 ``embedding_model`` 经 ``embed_query_cached`` 生成查询
   向量并喂给引擎（S1 混检激活）；embedding 不可用安全降级 BM25-only。
2. **写侧结构**：``_pg_ingest_async``（文本/admin 摄入后端）改走
   ``split_markdown`` + ``embed_texts(embed_input(spec))``，与权威摄入
   同一切片器——heading_path/parent_seq 不再恒空（S2 expand=section
   可达），向量随写。
3. **milvus 面**：``MilvusEngine.list_document_chunks`` 补齐后，milvus
   库的 S2 兄弟块取数不再被上层按「未实现」回退文件面。

monkeypatch 契约面：``qwenpaw.app.kb.engine.resolve_engine_for``（service
函数内 import，取 module attr）、``qwenpaw.app.kb.service.embed_texts`` /
``embed_query_cached``（顶层 import 绑定）、``write_gateway.
resolve_storage_backend``、``KbService._pg_get_space``（实例 seam）。

@author qingfeng
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List, Optional, Sequence

import pytest

from qwenpaw.app.kb import embedding as emb_mod
from qwenpaw.app.kb import engine as eng_mod
from qwenpaw.app.kb import milvus_engine, pg_engine
from qwenpaw.app.kb import service as svc_mod
from qwenpaw.app.kb.hits import KbSearchHit
from qwenpaw.app.kb.service import KbService
from qwenpaw.db import write_gateway

pytestmark = pytest.mark.unit

_DIM = 1024


def _vector(seed: float) -> List[float]:
    return [seed] * _DIM


def _hit(doc_id: str = "doc_1", seq: int = 0) -> KbSearchHit:
    """造一条最小命中（与引擎读回形态一致）。"""
    return KbSearchHit(
        space_id="kb_1",
        document_id=doc_id,
        chunk_id=f"{doc_id}_{seq}",
        seq=seq,
        heading_path="指南",
        text=f"正文 {seq}",
        score=0.9,
        parent_seq=None,
    )


class _RecordingEngine:
    """替身引擎：记录检索入参（space_ids/query/embedding/top_k）。"""

    def __init__(self, hits: Optional[List[KbSearchHit]] = None) -> None:
        self.hits = hits or []
        self.calls: List[tuple] = []

    async def search(
        self,
        space_ids: Sequence[str],
        query: str,
        query_embedding: Optional[Sequence[float]],
        top_k: int,
    ) -> List[KbSearchHit]:
        self.calls.append(
            (tuple(space_ids), query, query_embedding, top_k),
        )
        return list(self.hits)


# ---------------------------------------------------------------------------
# embed_query_cached：TTL 缓存（键隔离 / 命中 / 负缓存）
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_query_cache() -> None:
    emb_mod.clear_query_cache()


@pytest.mark.asyncio
async def test_embed_query_cached_hits_within_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TTL 内同键重复查询只打一次 provider，返回值一致。"""
    calls: List[str] = []

    async def fake_embed_query(
        query: str, model: str = "", agent_id: str = ""
    ) -> Optional[List[float]]:
        calls.append(query)
        return _vector(0.1)

    monkeypatch.setattr(emb_mod, "embed_query", fake_embed_query)

    first = await emb_mod.embed_query_cached("什么是知识库")
    second = await emb_mod.embed_query_cached("什么是知识库")

    assert calls == ["什么是知识库"]
    assert first == second == _vector(0.1)
    # 命中返回副本：外部修改不得污染缓存
    assert first is not second


@pytest.mark.asyncio
async def test_embed_query_cached_key_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不同 model（库级覆盖）不串缓存。"""
    calls: List[str] = []

    async def fake_embed_query(
        query: str, model: str = "", agent_id: str = ""
    ) -> Optional[List[float]]:
        calls.append(model)
        return _vector(0.2)

    monkeypatch.setattr(emb_mod, "embed_query", fake_embed_query)

    await emb_mod.embed_query_cached("问题", model="m1")
    await emb_mod.embed_query_cached("问题", model="m2")

    assert sorted(calls) == ["m1", "m2"]


@pytest.mark.asyncio
async def test_embed_query_cached_negative_caching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """provider 失败（None）同样按 TTL 负缓存，不高频重试。"""
    calls: List[int] = []

    async def fake_embed_query(
        query: str, model: str = "", agent_id: str = ""
    ) -> Optional[List[float]]:
        calls.append(1)
        return None

    monkeypatch.setattr(emb_mod, "embed_query", fake_embed_query)

    assert await emb_mod.embed_query_cached("问题") is None
    assert await emb_mod.embed_query_cached("问题") is None

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_embed_query_cached_blank_query_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空白查询短路返 None，不触达 provider。"""
    calls: List[int] = []

    async def fake_embed_query(
        query: str, model: str = "", agent_id: str = ""
    ) -> Optional[List[float]]:
        calls.append(1)
        return None

    monkeypatch.setattr(emb_mod, "embed_query", fake_embed_query)

    assert await emb_mod.embed_query_cached("   ") is None
    assert calls == []


# ---------------------------------------------------------------------------
# service.search：查询向量接线（S1 混检激活点）
# ---------------------------------------------------------------------------


def _make_service(tmp_path: Any) -> KbService:
    return KbService(
        registry_path=tmp_path / "reg.json",
        data_dir=tmp_path / "data",
    )


def _patch_pg_world(
    monkeypatch: pytest.MonkeyPatch,
    svc: KbService,
    *,
    space: Any,
    engine: Any,
) -> None:
    """把 pg 读写世界替换为替身（backend / space / 引擎路由 / 桥接面）。"""
    monkeypatch.setattr(
        write_gateway,
        "resolve_storage_backend",
        lambda: write_gateway.BACKEND_PG,
    )
    monkeypatch.setattr(
        svc,
        "_pg_get_space",
        lambda kb_id: space,
    )
    monkeypatch.setattr(
        eng_mod,
        "resolve_engine_for",
        lambda space: engine,
    )
    monkeypatch.setattr(svc, "_engine", lambda: engine)


def test_search_resolves_query_vector_from_space_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """query 缺向量时按库 embedding_model 解析并喂给引擎（S1 激活）。"""
    svc = _make_service(tmp_path)
    engine = _RecordingEngine([_hit()])
    space = SimpleNamespace(id="kb_1", engine="auto", embedding_model="m1")
    _patch_pg_world(monkeypatch, svc, space=space, engine=engine)
    seen_models: List[str] = []

    async def fake_cached(
        query: str, model: str = "", agent_id: str = ""
    ) -> Optional[List[float]]:
        seen_models.append(model)
        return _vector(0.3)

    monkeypatch.setattr(svc_mod, "embed_query_cached", fake_cached)

    results = svc.search("kb_1", "语义问题", top_k=5)

    assert seen_models == ["m1"]
    # 引擎收到非 None 向量（此前恒 None → 向量分支永不拼接）
    assert engine.calls[0][2] == _vector(0.3)
    assert results[0][0].doc_id == "doc_1"


def test_search_degrades_to_bm25_when_embedding_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """embedding 不可用（None）：安全降级 BM25-only，检索不报错。"""
    svc = _make_service(tmp_path)
    engine = _RecordingEngine([])
    space = SimpleNamespace(id="kb_1", engine="auto", embedding_model="")
    _patch_pg_world(monkeypatch, svc, space=space, engine=engine)

    async def fake_cached(
        query: str, model: str = "", agent_id: str = ""
    ) -> Optional[List[float]]:
        return None

    monkeypatch.setattr(svc_mod, "embed_query_cached", fake_cached)

    assert svc.search("kb_1", "关键词", top_k=5) == []
    assert engine.calls[0][2] is None


def test_search_explicit_embedding_skips_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """调用方显式传向量：不触发 embed_query_cached（显式优先）。"""
    svc = _make_service(tmp_path)
    engine = _RecordingEngine([])
    space = SimpleNamespace(id="kb_1", engine="auto", embedding_model="m1")
    _patch_pg_world(monkeypatch, svc, space=space, engine=engine)
    calls: List[int] = []

    async def fake_cached(
        query: str, model: str = "", agent_id: str = ""
    ) -> Optional[List[float]]:
        calls.append(1)
        return None

    monkeypatch.setattr(svc_mod, "embed_query_cached", fake_cached)

    svc.search("kb_1", "问题", top_k=5, query_embedding=_vector(0.5))

    assert calls == []
    assert engine.calls[0][2] == _vector(0.5)


def test_search_without_space_keeps_default_engine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """space 不可达：保留旧行为（默认引擎 + 不解析向量），不新增故障面。"""
    svc = _make_service(tmp_path)
    default_engine = _RecordingEngine([])
    _patch_pg_world(
        monkeypatch,
        svc,
        space=None,
        engine=default_engine,
    )

    results = svc.search("kb_1", "问题", top_k=5)

    assert results == []
    assert default_engine.calls[0][2] is None


def test_document_chunks_routes_via_space_engine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """S2/T11 取数按库级路由（milvus 库不再错落默认引擎）。"""
    svc = _make_service(tmp_path)
    routed = _RecordingEngine()
    space = SimpleNamespace(id="kb_1", engine="milvus", embedding_model="")
    monkeypatch.setattr(
        write_gateway,
        "resolve_storage_backend",
        lambda: write_gateway.BACKEND_PG,
    )
    monkeypatch.setattr(svc, "_pg_get_space", lambda kb_id: space)
    monkeypatch.setattr(eng_mod, "resolve_engine_for", lambda s: routed)
    monkeypatch.setattr(svc, "_engine", lambda: _RecordingEngine())

    async def lister(space_id: str, document_id: str) -> list:
        return [_hit(seq=1)]

    routed.list_document_chunks = lister  # type: ignore[attr-defined]

    chunks = svc.document_chunks("kb_1", "doc_1")

    assert [c.seq for c in chunks] == [1]


# ---------------------------------------------------------------------------
# _pg_ingest_async：结构化切片 + 自动向量（修 heading_path Critical）
# ---------------------------------------------------------------------------


class _FakeStore:
    """替身 KbPgStore：记录 upsert 与状态推进。"""

    def __init__(self, space: Any) -> None:
        self._space = space
        self.upserted: List[Any] = []
        self.statuses: List[tuple] = []

    async def get_space(self, kb_id: str) -> Any:
        return self._space

    async def upsert_document(self, document: Any) -> None:
        self.upserted.append(document)

    async def update_ingest_status(self, doc_id: str, status: str) -> None:
        self.statuses.append((doc_id, status))


class _IndexEngine:
    """替身引擎：记录 index_document 入参。"""

    def __init__(self) -> None:
        self.indexed: List[tuple] = []

    async def index_document(
        self,
        space_id: str,
        document_id: str,
        chunks: Sequence[Any],
        embeddings: Any,
        *,
        title: str = "",
    ) -> int:
        self.indexed.append(
            (space_id, document_id, list(chunks), embeddings, title),
        )
        return len(chunks)


_MD = "# 指南\n\n正文一段。\n\n## 子节\n\n子节正文。\n"


@pytest.mark.asyncio
async def test_pg_ingest_structured_chunks_with_headings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """文本摄入走 split_markdown：heading_path 非空（S2 可达）。"""
    svc = _make_service(tmp_path)
    space = SimpleNamespace(id="kb_1", engine="auto", embedding_model="m1")
    store = _FakeStore(space)
    engine = _IndexEngine()
    monkeypatch.setattr(svc, "_pg_store", lambda: store)
    monkeypatch.setattr(eng_mod, "resolve_engine_for", lambda s: engine)
    models: List[str] = []

    async def fake_embed_texts(
        texts: Sequence[str], model: str = "", agent_id: str = ""
    ) -> List[List[float]]:
        models.append(model)
        return [_vector(0.1) for _ in texts]

    monkeypatch.setattr(svc_mod, "embed_texts", fake_embed_texts)

    meta = await svc._pg_ingest_async(
        "kb_1",
        _MD,
        title="",
        source="manual",
        embeddings=None,
    )

    assert meta is not None and meta.chunk_count == 2
    specs = engine.indexed[0][2]
    # 结构化切片：标题路径随行（此前恒空串 → S2 不可达）
    assert specs[0].heading_path == "指南"
    assert specs[1].heading_path == "指南 > 子节"
    # chunker 父子不变式：节首块 parent_seq=None（两节各一块，均为首块）
    assert specs[0].parent_seq is None
    assert specs[1].parent_seq is None
    # 向量随写：按库模型生成，embed_input 拼标题路径
    assert models == ["m1"]
    vectors = engine.indexed[0][3]
    assert vectors is not None and len(vectors) == 2
    # 状态机：写入完成后推进 ready
    assert store.statuses[-1][1] == "ready"


@pytest.mark.asyncio
async def test_pg_ingest_explicit_embeddings_win(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """显式传入 embeddings 时优先使用（向后兼容既有调用方）。"""
    svc = _make_service(tmp_path)
    space = SimpleNamespace(id="kb_1", engine="auto", embedding_model="m1")
    store = _FakeStore(space)
    engine = _IndexEngine()
    monkeypatch.setattr(svc, "_pg_store", lambda: store)
    monkeypatch.setattr(eng_mod, "resolve_engine_for", lambda s: engine)
    calls: List[int] = []

    async def fake_embed_texts(
        texts: Sequence[str], model: str = "", agent_id: str = ""
    ) -> List[List[float]]:
        calls.append(1)
        return []

    monkeypatch.setattr(svc_mod, "embed_texts", fake_embed_texts)
    explicit = [_vector(0.7)]

    await svc._pg_ingest_async(
        "kb_1",
        _MD,
        title="t",
        source="manual",
        embeddings=explicit,
    )

    assert calls == []
    assert engine.indexed[0][3] is explicit


@pytest.mark.asyncio
async def test_pg_ingest_blank_text_returns_none(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """空白正文：切片为空 → None（摄入拒绝），不写任何行。"""
    svc = _make_service(tmp_path)
    space = SimpleNamespace(id="kb_1", engine="auto", embedding_model="")
    store = _FakeStore(space)
    engine = _IndexEngine()
    monkeypatch.setattr(svc, "_pg_store", lambda: store)
    monkeypatch.setattr(eng_mod, "resolve_engine_for", lambda s: engine)

    meta = await svc._pg_ingest_async(
        "kb_1",
        "   \n  ",
        title="",
        source="manual",
        embeddings=None,
    )

    assert meta is None
    assert store.upserted == []
    assert engine.indexed == []


@pytest.mark.asyncio
async def test_pg_ingest_missing_space_returns_none(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """库不存在：None（与既有契约一致），不触碰引擎。"""
    svc = _make_service(tmp_path)
    store = _FakeStore(space=None)
    engine = _IndexEngine()
    monkeypatch.setattr(svc, "_pg_store", lambda: store)
    monkeypatch.setattr(eng_mod, "resolve_engine_for", lambda s: engine)

    meta = await svc._pg_ingest_async(
        "kb_x",
        _MD,
        title="",
        source="manual",
        embeddings=None,
    )

    assert meta is None
    assert engine.indexed == []


# ---------------------------------------------------------------------------
# MilvusEngine.list_document_chunks：S2/T11 的 milvus 面实现
# ---------------------------------------------------------------------------


def _milvus_engine_with_rows(rows: Any) -> Any:
    """不经 __init__ 造 MilvusEngine，注入 fake client。"""
    engine = milvus_engine.MilvusEngine.__new__(milvus_engine.MilvusEngine)
    queries: List[tuple] = []

    class _Client:
        def query(self, collection: str, **kwargs: Any) -> Any:
            queries.append((collection, kwargs.get("filter")))
            if isinstance(rows, Exception):
                raise rows
            return rows

    client = _Client()
    engine._get_client = lambda: client  # type: ignore[method-assign]
    engine._ensure_collection = lambda c: None  # type: ignore[method-assign]
    engine._queries = queries  # type: ignore[attr-defined]
    return engine


@pytest.mark.asyncio
async def test_milvus_list_document_chunks_sorted_by_seq() -> None:
    """query 直查：按 seq 升序回填（score 恒 0），filter 双谓词。"""
    engine = _milvus_engine_with_rows(
        [
            {
                "chunk_id": "doc_1_2",
                "space_id": "kb_1",
                "document_id": "doc_1",
                "seq": 2,
                "heading_path": "指南 > 子节",
                "content_text": "第二块",
                "parent_seq": 0,
            },
            {
                "chunk_id": "doc_1_1",
                "space_id": "kb_1",
                "document_id": "doc_1",
                "seq": 1,
                "heading_path": "指南",
                "content_text": "第一块",
                "parent_seq": -1,
            },
        ],
    )

    hits = await engine.list_document_chunks("kb_1", "doc_1")

    assert [h.seq for h in hits] == [1, 2]
    assert hits[0].chunk_id == "doc_1_1"
    assert hits[0].score == 0.0
    # 无父块哨兵还原为 None（与 pg 引擎读回语义一致）
    assert hits[0].parent_seq is None
    assert hits[1].parent_seq == 0
    assert engine._queries[0][0] == milvus_engine.COLLECTION_NAME
    assert 'document_id == "doc_1"' in engine._queries[0][1]
    assert 'space_id == "kb_1"' in engine._queries[0][1]


@pytest.mark.asyncio
async def test_milvus_list_document_chunks_fail_soft() -> None:
    """客户端不可用/查询异常：fail-soft 返回空列表（调用方降级单块）。"""
    dead = _milvus_engine_with_rows([])
    dead._get_client = lambda: None  # type: ignore[method-assign]
    assert await dead.list_document_chunks("kb_1", "doc_1") == []

    boom = _milvus_engine_with_rows(RuntimeError("milvus down"))
    assert await boom.list_document_chunks("kb_1", "doc_1") == []


@pytest.mark.asyncio
async def test_milvus_list_document_chunks_blank_args() -> None:
    """空参数短路：不触达客户端。"""
    engine = _milvus_engine_with_rows([])
    assert await engine.list_document_chunks("", "doc_1") == []
    assert engine._queries == []


# ---------------------------------------------------------------------------
# pg_engine 向量分支 SQL（S1 混检回归锁）
# ---------------------------------------------------------------------------


def test_build_search_sql_with_vector_branch() -> None:
    """带向量查询：SQL 含向量 CTE 与 qv 参数位（RRF 双分支）。"""
    sql = pg_engine._build_search_sql(True, True)

    assert "vec AS" in sql
    assert "kw AS" in sql
    assert "CAST(:qv AS vector)" in sql
    assert str(pg_engine.VECTOR_WEIGHT) in sql
    assert str(pg_engine.KEYWORD_WEIGHT) in sql


def test_build_search_sql_keyword_only_branch() -> None:
    """无向量（降级 BM25）：不拼向量 CTE，全文分支仍在。"""
    sql = pg_engine._build_search_sql(False, True)

    assert "vec AS" not in sql
    assert "kw AS" in sql
