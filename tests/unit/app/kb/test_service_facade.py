# -*- coding: utf-8 -*-
"""T8: KbService 门面三态分流单测。

覆盖裁定基准 task-8-brief.md：
- json 后端逐条回归基线（现状文件面行为不变）；
- pg 后端权威路由（create/get/list/delete/ingest/search 落 FakeStore/FakeEngine，
  KbSpace↔KnowledgeBase、KbDocument↔KbDocumentMeta 双向转换）；
- dual 后端 json primary 读写 + 每个写操作触发 submit_shadow_write；
- 三态读结果一致（同组逻辑操作后 list_kbs/list_documents 断言相同）；
- pg 不可用 fail-soft 回退文件面（不抛穿、不 500）。

零真库：pg 后端由 FakeStore/FakeEngine 注入，桥接 helper 打桩为 asyncio.run；
真库×迁移脚本往返由 tests/integration/test_kb_migrate_script.py 门控覆盖。

@author qingfeng
"""

# pylint: disable=protected-access
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Sequence

import pytest

from qwenpaw.app.kb import service as service_mod
from qwenpaw.app.kb.chunker import ChunkSpec
from qwenpaw.app.kb.hits import KbSearchHit
from qwenpaw.app.kb.models import (
    INGEST_PENDING,
    INGEST_READY,
    KbChunk,
    KbDocument,
    KbSpace,
)
from qwenpaw.db import write_gateway

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 桩：内存态 pg_store / 检索引擎（异步面，忠实镜像真签名）
# ---------------------------------------------------------------------------


class FakeStore:
    """内存态 KbPgStore 桩：异步方法 + 调用记录 + fail 开关。"""

    def __init__(self) -> None:
        self.spaces: Dict[str, KbSpace] = {}
        self.docs: Dict[str, KbDocument] = {}
        self.calls: List[Any] = []
        self.fail = False

    async def ensure_ready(self) -> bool:
        return not self.fail

    async def upsert_space(self, space: KbSpace) -> bool:
        self.calls.append(("upsert_space", space.id))
        if self.fail:
            return False
        self.spaces[space.id] = space
        return True

    async def get_space(self, space_id: str) -> Optional[KbSpace]:
        self.calls.append(("get_space", space_id))
        if self.fail:
            return None
        return self.spaces.get(space_id)

    async def list_spaces(self) -> List[KbSpace]:
        self.calls.append(("list_spaces",))
        if self.fail:
            return []
        return list(self.spaces.values())

    async def delete_space(self, space_id: str) -> bool:
        self.calls.append(("delete_space", space_id))
        if self.fail:
            return False
        return self.spaces.pop(space_id, None) is not None

    async def upsert_document(self, document: KbDocument) -> bool:
        self.calls.append(("upsert_document", document.id))
        if self.fail:
            return False
        # 镜像真 pg_store：upsert 一律落 pending，ready 只能由 update_ingest_status 推进
        document.ingest_status = INGEST_PENDING
        self.docs[document.id] = document
        return True

    async def update_ingest_status(
        self,
        doc_id: str,
        ingest_status: str,
        *,
        error: str = "",
    ) -> bool:
        self.calls.append(("update_ingest_status", doc_id, ingest_status))
        doc = self.docs.get(doc_id)
        if doc is None or self.fail:
            return False
        doc.ingest_status = ingest_status
        return True

    async def get_document(self, doc_id: str) -> Optional[KbDocument]:
        self.calls.append(("get_document", doc_id))
        if self.fail:
            return None
        return self.docs.get(doc_id)

    async def list_documents(
        self,
        space_id: str,
        *,
        include_deleted: bool = False,
    ) -> List[KbDocument]:
        self.calls.append(("list_documents", space_id))
        if self.fail:
            return []
        return [
            doc
            for doc in self.docs.values()
            if doc.space_id == space_id
            and (include_deleted or not doc.is_delete)
        ]

    async def delete_document(self, doc_id: str) -> bool:
        self.calls.append(("delete_document", doc_id))
        doc = self.docs.get(doc_id)
        if doc is None or self.fail:
            return False
        doc.is_delete = True
        return True


class FakeEngine:
    """内存态检索引擎桩：index_document / search / delete_document。"""

    def __init__(self) -> None:
        self.indexed: Dict[str, List[ChunkSpec]] = {}
        self.hits: List[KbSearchHit] = []
        self.calls: List[Any] = []

    async def index_document(
        self,
        space_id: str,
        document_id: str,
        chunks: Sequence[ChunkSpec],
        embeddings: Optional[Sequence[Sequence[float]]] = None,
        *,
        title: str = "",
        model_name: str = "",
    ) -> int:
        self.calls.append(("index_document", document_id))
        self.indexed[document_id] = list(chunks)
        return len(chunks)

    async def delete_document(self, space_id: str, document_id: str) -> int:
        self.calls.append(("engine_delete_document", document_id))
        return len(self.indexed.pop(document_id, []))

    async def search(
        self,
        space_ids: Sequence[str],
        query: str,
        query_embedding: Optional[Sequence[float]] = None,
        top_k: int = 5,
    ) -> List[KbSearchHit]:
        self.calls.append(("search", tuple(space_ids)))
        return [h for h in self.hits if h.space_id in set(space_ids)][:top_k]


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


@pytest.fixture()
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture()
def engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture()
def shadows(monkeypatch: pytest.MonkeyPatch) -> List[Any]:
    """记录 dual 态 submit_shadow_write 触发（domain 一并记下）。"""
    recorded: List[Any] = []

    def _fake_shadow(op: Any, *, domain: str = "") -> None:
        recorded.append((op, domain))

    monkeypatch.setattr(
        write_gateway,
        "submit_shadow_write",
        _fake_shadow,
    )
    return recorded


@pytest.fixture()
def svc(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    store: FakeStore,
    engine: FakeEngine,
) -> Any:
    """构造注入了 FakeStore/FakeEngine + 同步桥的门面（seam 全 monkeypatch）。"""
    # 桥接打桩为 asyncio.run（单测同步上下文，无后台 loop）
    monkeypatch.setattr(
        service_mod.KbService,
        "_run_async",
        lambda self, coro, *, write=False: asyncio.run(coro),
        raising=False,
    )
    # pg_store / engine seam 注入
    monkeypatch.setattr(
        service_mod.KbService,
        "_pg_store",
        lambda self: store,
        raising=False,
    )
    monkeypatch.setattr(
        service_mod.KbService,
        "_engine",
        lambda self: engine,
        raising=False,
    )
    return service_mod.KbService(
        registry_path=tmp_path / "kb_registry.json",
        data_dir=tmp_path / "kb_data",
    )


def _set_backend(monkeypatch: pytest.MonkeyPatch, backend: str) -> None:
    """切换解析后端（打桩 canonical 模块函数，绕过进程级缓存）。"""
    monkeypatch.setattr(
        write_gateway,
        "resolve_storage_backend",
        lambda: backend,
    )


def _seed_space(store: FakeStore, space_id: str, name: str) -> KbSpace:
    space = KbSpace(
        id=space_id,
        name=name,
        scope="enterprise",
        grants={"roles": ["r1"], "users": ["u1"], "teams": ["t1"]},
    )
    store.spaces[space_id] = space
    return space


# ---------------------------------------------------------------------------
# json 后端：回归基线（现状行为逐条不变）
# ---------------------------------------------------------------------------


def test_json_create_get_list_delete(
    svc: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_backend(monkeypatch, "json")
    kb = svc.create_kb("Alpha", scope="enterprise")
    assert kb is not None
    assert svc.get_kb(kb.id).name == "Alpha"
    assert [k.name for k in svc.list_kbs()] == ["Alpha"]
    assert svc.delete_kb(kb.id) is True
    assert svc.get_kb(kb.id) is None
    assert svc.delete_kb(kb.id) is False


def test_json_ingest_list_search(
    svc: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_backend(monkeypatch, "json")
    kb = svc.create_kb("Beta", scope="enterprise")
    doc = svc.ingest_text(kb.id, "hello world\n\nsecond para", title="T1")
    assert doc is not None
    assert doc.chunk_count >= 1
    assert [d.title for d in svc.list_documents(kb.id)] == ["T1"]
    hits = svc.search(kb.id, "hello")
    assert hits and isinstance(hits[0][0], KbChunk)
    assert svc.delete_document(doc.doc_id) is True
    assert svc.list_documents(kb.id) == []


def test_json_backend_zero_pg_touch(
    svc: Any,
    store: FakeStore,
    engine: FakeEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """json 后端不得触碰 pg 面（零 PG 动作，spec §4.3）。"""
    _set_backend(monkeypatch, "json")
    kb = svc.create_kb("Gamma", scope="enterprise")
    svc.ingest_text(kb.id, "some text", title="T")
    svc.search(kb.id, "some")
    assert store.calls == []
    assert engine.calls == []


# ---------------------------------------------------------------------------
# pg 后端：权威路由 + 模型双向转换
# ---------------------------------------------------------------------------


def test_pg_create_routes_to_store(
    svc: Any,
    store: FakeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_backend(monkeypatch, "pg")
    kb = svc.create_kb("Delta", scope="enterprise", description="d")
    assert kb is not None
    assert ("upsert_space", kb.id) in store.calls
    space = store.spaces[kb.id]
    assert space.name == "Delta"
    assert space.scope == "enterprise"


def test_pg_get_list_convert_grants(
    svc: Any,
    store: FakeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pg 读回 KnowledgeBase，grants dict 摊平回三列表。"""
    _set_backend(monkeypatch, "pg")
    _seed_space(store, "kb_x", "Seeded")
    got = svc.get_kb("kb_x")
    assert got is not None
    assert got.name == "Seeded"
    assert got.grants_roles == ["r1"]
    assert got.grants_users == ["u1"]
    assert got.grants_teams == ["t1"]
    assert [k.id for k in svc.list_kbs()] == ["kb_x"]


def test_pg_delete_removes_docs_then_space(
    svc: Any,
    store: FakeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """delete_space 拒删非空库 → 门面须先逐文档软删再删空间。"""
    _set_backend(monkeypatch, "pg")
    _seed_space(store, "kb_del", "ToDelete")
    store.docs["doc_1"] = KbDocument(id="doc_1", space_id="kb_del", path="a")
    assert svc.delete_kb("kb_del") is True
    assert ("delete_document", "doc_1") in store.calls
    assert ("delete_space", "kb_del") in store.calls
    assert "kb_del" not in store.spaces


def test_pg_delete_missing_returns_false(
    svc: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_backend(monkeypatch, "pg")
    assert svc.delete_kb("nope") is False


def test_pg_ingest_upserts_doc_and_indexes(
    svc: Any,
    store: FakeStore,
    engine: FakeEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_backend(monkeypatch, "pg")
    _seed_space(store, "kb_ing", "Ingest")
    doc = svc.ingest_text("kb_ing", "para one\n\npara two", title="Doc")
    assert doc is not None
    assert doc.kb_id == "kb_ing"
    assert doc.chunk_count >= 1
    assert any(c[0] == "upsert_document" for c in store.calls)
    assert any(c[0] == "index_document" for c in engine.calls)
    # 切片确实落到引擎（ChunkSpec 形状）
    indexed = list(engine.indexed.values())[0]
    assert all(isinstance(spec, ChunkSpec) for spec in indexed)


def test_pg_ingest_missing_kb_returns_none(
    svc: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_backend(monkeypatch, "pg")
    assert svc.ingest_text("ghost", "text", title="T") is None


def test_pg_search_converts_hits_to_chunks(
    svc: Any,
    store: FakeStore,
    engine: FakeEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pg search 走引擎，KbSearchHit 转回 (KbChunk, score)，签名不变。"""
    _set_backend(monkeypatch, "pg")
    _seed_space(store, "kb_s", "Searchable")
    engine.hits = [
        KbSearchHit(
            space_id="kb_s",
            document_id="doc_s",
            chunk_id="c1",
            seq=0,
            heading_path="",
            text="matched text",
            score=0.87,
        ),
    ]
    hits = svc.search("kb_s", "match")
    assert len(hits) == 1
    chunk, score = hits[0]
    assert isinstance(chunk, KbChunk)
    assert chunk.chunk_id == "c1"
    assert chunk.text == "matched text"
    assert score == pytest.approx(0.87)


def test_pg_list_documents_convert(
    svc: Any,
    store: FakeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_backend(monkeypatch, "pg")
    _seed_space(store, "kb_ld", "Docs")
    store.docs["d1"] = KbDocument(
        id="d1",
        space_id="kb_ld",
        path="p1",
        title="Doc One",
        source="manual",
    )
    metas = svc.list_documents("kb_ld")
    assert [m.title for m in metas] == ["Doc One"]
    assert metas[0].doc_id == "d1"
    assert metas[0].kb_id == "kb_ld"


def test_pg_delete_document_hits_store_and_engine(
    svc: Any,
    store: FakeStore,
    engine: FakeEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_backend(monkeypatch, "pg")
    _seed_space(store, "kb_dd", "Docs")
    store.docs["dz"] = KbDocument(id="dz", space_id="kb_dd", path="pz")
    engine.indexed["dz"] = [ChunkSpec(0, "", "t", None, 1)]
    assert svc.delete_document("dz") is True
    assert ("delete_document", "dz") in store.calls
    assert ("engine_delete_document", "dz") in engine.calls


def test_pg_update_grants_persists(
    svc: Any,
    store: FakeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_backend(monkeypatch, "pg")
    _seed_space(store, "kb_g", "Grants")
    updated = svc.update_grants("kb_g", roles=["admin"], users=["bob"])
    assert updated is not None
    assert store.spaces["kb_g"].grants["roles"] == ["admin"]
    assert store.spaces["kb_g"].grants["users"] == ["bob"]


# ---------------------------------------------------------------------------
# dual 后端：json primary + 影子写
# ---------------------------------------------------------------------------


def test_dual_writes_json_and_shadows(
    svc: Any,
    shadows: List[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_backend(monkeypatch, "dual")
    kb = svc.create_kb("Dual", scope="enterprise")
    # json primary 生效（读得到）
    assert svc.get_kb(kb.id) is not None
    # 影子写被触发一次（domain=kb）
    assert len(shadows) == 1
    assert shadows[0][1] == "kb"


def test_dual_reads_from_json_primary(
    svc: Any,
    store: FakeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dual 读仍走 json：pg 空但 json 有 → list_kbs 返回 json 数据。"""
    _set_backend(monkeypatch, "dual")
    svc.create_kb("JsonPrimary", scope="enterprise")
    store.spaces.clear()
    assert [k.name for k in svc.list_kbs()] == ["JsonPrimary"]


# ---------------------------------------------------------------------------
# 三态读一致性
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", ["json", "pg", "dual"])
def test_three_state_read_consistency(
    svc: Any,
    store: FakeStore,
    engine: FakeEngine,
    shadows: List[Any],
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
) -> None:
    """同组逻辑操作后，三态 list_kbs / list_documents 读结果一致。"""
    _set_backend(monkeypatch, backend)
    kb = svc.create_kb("Consistent", scope="enterprise")
    assert kb is not None
    svc.ingest_text(kb.id, "alpha\n\nbeta", title="ConsistentDoc")
    assert [k.name for k in svc.list_kbs()] == ["Consistent"]
    docs = svc.list_documents(kb.id)
    assert [d.title for d in docs] == ["ConsistentDoc"]
    assert docs[0].chunk_count >= 1


# ---------------------------------------------------------------------------
# fail-soft：pg 不可用回退文件面
# ---------------------------------------------------------------------------


def test_pg_unavailable_list_falls_back_to_file(
    svc: Any,
    store: FakeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pg 后端但 store 不可用 → list_kbs 回退文件面，不抛异常。"""
    # 先在 json 面写一条（作为回退可读数据）
    _set_backend(monkeypatch, "json")
    svc.create_kb("Fallback", scope="enterprise")
    # 切 pg 且令 store 失效
    _set_backend(monkeypatch, "pg")
    store.fail = True
    names = [k.name for k in svc.list_kbs()]
    assert "Fallback" in names


def test_pg_unavailable_get_returns_none_not_raise(
    svc: Any,
    store: FakeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_backend(monkeypatch, "pg")
    store.fail = True
    assert svc.get_kb("anything") is None


# ---------------------------------------------------------------------------
# ACL 签名不变（纯逻辑，零存储）
# ---------------------------------------------------------------------------


def test_acl_unchanged(svc: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_backend(monkeypatch, "json")
    kb = svc.create_kb("Acl", scope="personal", owner_id="alice")
    assert svc.can_access(kb, "alice") is True
    assert svc.can_access(kb, "bob") is False
    assert svc.can_access(kb, "root", flat_role="admin") is True
    visible = svc.accessible_kbs("alice")
    assert [k.id for k in visible] == [kb.id]


# ---------------------------------------------------------------------------
# 审查轮守护（P1-1 摄入推进 ready / P1-4 pg 就绪不复活 / P1-3 dual doc_id 复用）
# ---------------------------------------------------------------------------


def test_pg_ingest_advances_status_to_ready(
    svc: Any,
    store: FakeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-1：upsert 落 pending 后，门面摄入须显式推进 ready（否则永久卡 pending）。"""
    _set_backend(monkeypatch, "pg")
    _seed_space(store, "kb_st", "Status")
    doc = svc.ingest_text("kb_st", "some text here", title="T")
    assert doc is not None
    # FakeStore 镜像真库：upsert 强制 pending，仅 update_ingest_status 能推进
    assert store.docs[doc.doc_id].ingest_status == INGEST_READY
    assert ("update_ingest_status", doc.doc_id, INGEST_READY) in store.calls


def test_pg_ready_but_absent_no_json_fallback(
    svc: Any,
    store: FakeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-4：pg 就绪即权威——不存在的库不得被 30 天保留的 json 复活。"""
    # 先在 json 面建库（模拟 30 天保留的旧源）
    _set_backend(monkeypatch, "json")
    kb = svc.create_kb("Ghost", scope="enterprise")
    # 切 pg：store 就绪（fail=False）但无该空间
    _set_backend(monkeypatch, "pg")
    store.fail = False
    assert svc.get_kb(kb.id) is None
    assert svc.list_kbs() == []


def test_dual_shadow_ingest_reuses_doc_id(
    svc: Any,
    store: FakeStore,
    shadows: List[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-3：dual 影子摄入须复用 json 主写 doc_id，否则影子删除找不到 pg 行。"""
    _set_backend(monkeypatch, "dual")
    kb = svc.create_kb("DualIngest", scope="enterprise")
    # 先执行 create 影子（建 pg 空间），否则 ingest 影子 get_space 落空
    asyncio.run(shadows[-1][0]())
    doc = svc.ingest_text(kb.id, "dual text", title="D")
    assert doc is not None
    # 执行摄入影子写
    asyncio.run(shadows[-1][0]())
    # pg 中的 doc_id 必须与 json 主写一致（P1-3），且已推进 ready
    assert doc.doc_id in store.docs
    assert store.docs[doc.doc_id].ingest_status == INGEST_READY


# ---------------------------------------------------------------------------
# T9：kb_read 数据源——read_document / get_document_meta 的 pg 权威分支
# ---------------------------------------------------------------------------


def test_pg_read_document_returns_content_md(
    svc: Any,
    store: FakeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC3 pg 分支：read_document 返回 kb_documents.content_md 权威全文。"""
    _set_backend(monkeypatch, "pg")
    _seed_space(store, "kb_read", "Readable")
    store.docs["doc_r1"] = KbDocument(
        id="doc_r1",
        space_id="kb_read",
        path="孕产/甲减.md",
        title="甲减指南",
        content_md="# 甲减\n\n左甲状腺素剂量权威全文。",
    )
    assert svc.read_document("doc_r1") == "# 甲减\n\n左甲状腺素剂量权威全文。"


def test_pg_get_document_meta_converts(
    svc: Any,
    store: FakeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC3 pg 分支：get_document_meta 将 KbDocument 转 Meta（space_id→kb_id）。"""
    _set_backend(monkeypatch, "pg")
    _seed_space(store, "kb_meta", "Meta")
    store.docs["doc_m1"] = KbDocument(
        id="doc_m1",
        space_id="kb_meta",
        path="p.md",
        title="元文档",
        content_md="正文",
    )
    meta = svc.get_document_meta("doc_m1")
    assert meta is not None
    assert meta.kb_id == "kb_meta"
    assert meta.title == "元文档"


def test_pg_read_document_absent_no_json_fallback(
    svc: Any,
    store: FakeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-4 同源：pg 就绪即权威——不存在文档不被 json 复活（返 None）。"""
    # json 面先造一篇同名文档（模拟 30 天保留的旧源）
    _set_backend(monkeypatch, "json")
    kb = svc.create_kb("GhostDoc", scope="enterprise")
    doc = svc.ingest_text(kb.id, "legacy text", title="L")
    # 切 pg：store 就绪但无该文档 → 权威空结果，不回退 json
    _set_backend(monkeypatch, "pg")
    store.fail = False
    assert svc.read_document(doc.doc_id) is None
    assert svc.get_document_meta(doc.doc_id) is None
