# -*- coding: utf-8 -*-
"""T3 LLM Wiki 知识层回归：生命周期 / 冲突候选 / 有效期过滤。

锁定三条治理闭环面：

1. **生命周期状态机**：submit/approve/reject/archive 目标状态映射正确、
   每次流转写 ``kb_reviews`` 流水、approve 盖章 ``reviewed_by`` 而
   reject/archive 不抹掉既有审核人（写参数白名单断言）；
2. **检索可见性**：pg_engine SQL 含 published+有效期过滤（权威面）；
   json 文件面按 registry meta 过滤 draft/过期文档（降级口径）；
3. **冲突候选**：同库同名规则命中 + 无序对查重幂等 + confidence 归档
   优先级；LLM 建议只产候选、任何失败返回 None（不落库不抛出）。

@author qingfeng
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from qwenpaw.app.kb import pg_engine
from qwenpaw.app.kb import service as svc_mod
from qwenpaw.app.kb import wiki as wiki_mod
from qwenpaw.app.kb.models import (
    KNOWLEDGE_DRAFT,
    KNOWLEDGE_IN_REVIEW,
    KNOWLEDGE_PUBLISHED,
    KbConflict,
    KbDocument,
    KbDocumentMeta,
    KbReview,
)
from qwenpaw.app.kb.service import KbService

pytestmark = pytest.mark.unit


def _doc(
    doc_id: str = "doc_1",
    space_id: str = "kb_1",
    *,
    title: str = "入职指南",
    confidence: float = 1.0,
    **kwargs: Any,
) -> KbDocument:
    return KbDocument(
        id=doc_id,
        space_id=space_id,
        path=f"{doc_id}.md",
        title=title,
        content_md=f"# {title}\n\n正文",
        confidence=confidence,
        **kwargs,
    )


class WikiStore:
    """替身 KbPgStore：文档/元数据/流水/冲突的内存态。"""

    def __init__(self) -> None:
        self.docs: Dict[str, KbDocument] = {}
        self.meta_updates: List[tuple] = []
        self.reviews: List[KbReview] = []
        self.conflicts: List[KbConflict] = []

    async def get_document(self, doc_id: str) -> Optional[KbDocument]:
        return self.docs.get(doc_id)

    async def list_documents(self, space_id: str) -> List[KbDocument]:
        return [
            doc
            for doc in self.docs.values()
            if doc.space_id == space_id and not doc.is_delete
        ]

    async def update_document_meta(
        self,
        doc_id: str,
        **fields: Any,
    ) -> bool:
        doc = self.docs.get(doc_id)
        if doc is None:
            return False
        self.meta_updates.append((doc_id, dict(fields)))
        for key, value in fields.items():
            setattr(doc, key, value)
        return True

    async def create_review(self, review: KbReview) -> bool:
        self.reviews.append(review)
        return True

    async def find_open_conflict(
        self,
        space_id: str,
        document_id_a: str,
        document_id_b: str,
        *,
        conflict_type: str = "duplicate_title",
    ) -> Optional[KbConflict]:
        for conflict in self.conflicts:
            same_pair = {
                conflict.document_id_a,
                conflict.document_id_b,
            } == {document_id_a, document_id_b}
            if (
                conflict.resolution_status == "open"
                and same_pair
                and conflict.conflict_type == conflict_type
            ):
                return conflict
        return None

    async def upsert_conflict(self, conflict: KbConflict) -> bool:
        self.conflicts.append(conflict)
        return True


# ---------------------------------------------------------------------------
# 生命周期状态机
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_submit_moves_to_in_review() -> None:
    """submit：draft → in_review，且写一条流水。"""
    store = WikiStore()
    store.docs["doc_1"] = _doc()

    doc = await wiki_mod.review_document(
        store, "kb_1", "doc_1", "submit", "alice",
    )

    assert doc is not None
    assert doc.knowledge_status == KNOWLEDGE_IN_REVIEW
    # submit 不盖章 reviewed_by（无审定事实）
    assert doc.reviewed_by == ""
    assert [r.action for r in store.reviews] == ["submit"]
    assert store.reviews[0].reviewer == "alice"


@pytest.mark.asyncio
async def test_review_approve_stamps_reviewer() -> None:
    """approve：→ published 并盖章 reviewed_by。"""
    store = WikiStore()
    store.docs["doc_1"] = _doc(knowledge_status=KNOWLEDGE_IN_REVIEW)

    doc = await wiki_mod.review_document(
        store, "kb_1", "doc_1", "approve", "bob", "lgtm",
    )

    assert doc.knowledge_status == KNOWLEDGE_PUBLISHED
    assert doc.reviewed_by == "bob"
    assert doc.review_note == "lgtm"


@pytest.mark.asyncio
async def test_review_reject_keeps_previous_reviewer() -> None:
    """reject：→ draft，且**不抹掉**最近一次 approve 的审核人。"""
    store = WikiStore()
    store.docs["doc_1"] = _doc(reviewed_by="bob")

    doc = await wiki_mod.review_document(
        store, "kb_1", "doc_1", "reject", "carol", "内容过期",
    )

    assert doc.knowledge_status == KNOWLEDGE_DRAFT
    assert doc.review_note == "内容过期"
    # reject 未提交 reviewed_by 键（白名单更新参数断言）
    reject_updates = [
        fields for _doc_id, fields in store.meta_updates
    ]
    assert all("reviewed_by" not in fields for fields in reject_updates)
    assert doc.reviewed_by == "bob"


@pytest.mark.asyncio
async def test_review_archive_and_invalid_action() -> None:
    """archive：→ archived；非法 action 抛 ValueError（值级拒绝）。"""
    store = WikiStore()
    store.docs["doc_1"] = _doc()

    doc = await wiki_mod.review_document(
        store, "kb_1", "doc_1", "archive", "alice", "下线",
    )
    assert doc.knowledge_status == "archived"

    with pytest.raises(ValueError):
        await wiki_mod.review_document(
            store, "kb_1", "doc_1", "publish", "alice",
        )


@pytest.mark.asyncio
async def test_review_missing_or_cross_space_doc_returns_none() -> None:
    """文档不存在/跨库/已删除 → None（路由映射 404）。"""
    store = WikiStore()
    store.docs["doc_1"] = _doc()
    store.docs["dead"] = _doc("dead", is_delete=True)

    assert (
        await wiki_mod.review_document(
            store, "kb_x", "doc_1", "submit", "a",
        )
        is None
    )
    assert (
        await wiki_mod.review_document(
            store, "kb_1", "ghost", "submit", "a",
        )
        is None
    )
    assert (
        await wiki_mod.review_document(
            store, "kb_1", "dead", "submit", "a",
        )
        is None
    )


# ---------------------------------------------------------------------------
# 冲突候选（规则判定 duplicate_title）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_conflicts_duplicate_title() -> None:
    """同库同名 → 建 1 个 open 候选；再次检测不重复建（查重幂等）。"""
    store = WikiStore()
    store.docs["doc_1"] = _doc("doc_1", title="入职指南")
    store.docs["doc_2"] = _doc("doc_2", title="入职指南 ")  # 归一后同名

    created = await wiki_mod.detect_conflicts(store, "kb_1", "doc_1")
    assert len(created) == 1
    assert created[0].conflict_type == "duplicate_title"

    again = await wiki_mod.detect_conflicts(store, "kb_1", "doc_2")
    assert again == []
    assert len(store.conflicts) == 1


@pytest.mark.asyncio
async def test_detect_conflicts_priority_and_miss() -> None:
    """不同名不建；低 confidence 对 → priority 4。"""
    store = WikiStore()
    store.docs["doc_1"] = _doc("doc_1", title="A")
    store.docs["doc_2"] = _doc("doc_2", title="B")
    store.docs["doc_3"] = _doc("doc_3", title="A")
    store.docs["doc_3"].confidence = 0.3

    assert await wiki_mod.detect_conflicts(store, "kb_1", "doc_2") == []

    created = await wiki_mod.detect_conflicts(store, "kb_1", "doc_3")
    assert len(created) == 1
    assert created[0].priority == 4
    assert created[0].document_id_a == "doc_3"


# ---------------------------------------------------------------------------
# 有效期与检索可见性
# ---------------------------------------------------------------------------


def test_is_effective_matrix() -> None:
    """published+无界可检；draft/过期/未生效不可检；缺属性放行降级。"""
    now = datetime.now(timezone.utc)
    published = _doc()
    assert wiki_mod.is_effective(published, now=now) is True

    assert (
        wiki_mod.is_effective(_doc(knowledge_status=KNOWLEDGE_DRAFT), now=now)
        is False
    )
    expired = _doc(valid_to=now - timedelta(days=1))
    assert wiki_mod.is_effective(expired, now=now) is False
    future = _doc(valid_from=now + timedelta(days=1))
    assert wiki_mod.is_effective(future, now=now) is False

    # 缺状态/有效期属性的对象（旧版 KbDocumentMeta）：放行（降级口径）
    assert wiki_mod.is_effective(SimpleNamespace(), now=now) is True


def test_pg_engine_sql_filters_lifecycle() -> None:
    """pg 权威面：检索/切片 SQL 均含 published+有效期过滤。"""
    sql = pg_engine._build_search_sql(True, True)
    assert "knowledge_status = 'published'" in sql
    assert "d.valid_from IS NULL OR d.valid_from <= now()" in sql
    assert "d.valid_to IS NULL OR d.valid_to > now()" in sql
    assert "d.is_delete = FALSE" in sql

    list_sql = pg_engine._LIST_DOCUMENT_CHUNKS_SQL
    assert "knowledge_status = 'published'" in list_sql


def test_json_plane_search_filters_lifecycle(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """json 文件面降级过滤：draft/过期文档命中被滤掉，published 命中保留。"""
    from qwenpaw.db import write_gateway

    # 本机开发者环境可能是 pg 后端：显式钉住 json 语义测文件面降级
    monkeypatch.setattr(
        write_gateway,
        "resolve_storage_backend",
        lambda: write_gateway.BACKEND_JSON,
    )
    svc = KbService(
        registry_path=tmp_path / "reg.json",
        data_dir=tmp_path / "data",
    )
    kb = svc.create_kb("Wiki", scope="enterprise")
    assert kb is not None
    doc = svc.ingest_text(kb.id, "hello world\n\nsecond para", title="T1")
    assert doc is not None
    doc_id = doc.doc_id

    def _set_meta(**fields: Any) -> None:
        data = svc._load()
        meta = data.documents[doc_id]
        for key, value in fields.items():
            setattr(meta, key, value)
        svc._save(data)

    assert svc.search(kb.id, "hello") != []

    _set_meta(knowledge_status=KNOWLEDGE_DRAFT)
    assert svc.search(kb.id, "hello") == []

    now = datetime.now(timezone.utc)
    _set_meta(
        knowledge_status=KNOWLEDGE_PUBLISHED,
        valid_to=now - timedelta(days=1),
    )
    assert svc.search(kb.id, "hello") == []

    _set_meta(valid_to=now + timedelta(days=1))
    assert svc.search(kb.id, "hello") != []


def test_doc_to_meta_carries_lifecycle() -> None:
    """pg 面 list → meta 转换携带状态与有效期（人侧列表展示数据源）。"""
    svc = KbService(
        registry_path="nonexistent/reg.json",
        data_dir="nonexistent/data",
    )
    now = datetime.now(timezone.utc)
    doc = _doc(knowledge_status=KNOWLEDGE_DRAFT, valid_from=now)
    meta = svc._doc_to_meta(doc)
    assert isinstance(meta, KbDocumentMeta)
    assert meta.knowledge_status == KNOWLEDGE_DRAFT
    assert meta.valid_from == now


# ---------------------------------------------------------------------------
# LLM 建议（候选生成器，任何失败返回 None）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggest_wiki_meta_parses_fenced_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模型返回 ```json 围栏 → 解析候选；doc_type 白名单外落 doc。"""
    payload = (
        "```json\n"
        '{"summary": "入职流程摘要", "domain": "企业基础", '
        '"doc_type": "handbook", "aliases": ["onboarding", "入职"]}\n'
        "```"
    )

    class _Response:
        def get_text_content(self) -> str:
            return payload

    class _Model:
        async def __call__(self, messages: list) -> _Response:
            return _Response()

    async def fake_factory(agent_id: Optional[str] = None, **_: Any) -> tuple:
        return _Model(), object()

    import qwenpaw.agents.model_factory as factory_mod

    monkeypatch.setattr(
        factory_mod,
        "create_model_and_formatter_async",
        fake_factory,
    )

    candidate = await wiki_mod.suggest_wiki_meta("# 指南\n\n正文")
    assert candidate is not None
    assert candidate["summary"] == "入职流程摘要"
    assert candidate["doc_type"] == "doc"  # 白名单外 → 默认
    assert candidate["aliases"] == ["onboarding", "入职"]


@pytest.mark.asyncio
async def test_suggest_wiki_meta_failures_return_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空白正文/模型不可用/非 JSON 响应 → 一律 None（不抛出不落库）。"""
    assert await wiki_mod.suggest_wiki_meta("   ") is None

    import qwenpaw.agents.model_factory as factory_mod

    async def broken_factory(
        agent_id: Optional[str] = None,
        **_: Any,
    ) -> tuple:
        raise RuntimeError("no model configured")

    monkeypatch.setattr(
        factory_mod,
        "create_model_and_formatter_async",
        broken_factory,
    )
    assert await wiki_mod.suggest_wiki_meta("正文") is None

    class _BadResponse:
        def get_text_content(self) -> str:
            return "抱歉，我无法输出 JSON"

    class _Model:
        async def __call__(self, messages: list) -> _BadResponse:
            return _BadResponse()

    async def ok_factory(agent_id: Optional[str] = None, **_: Any) -> tuple:
        return _Model(), object()

    monkeypatch.setattr(
        factory_mod,
        "create_model_and_formatter_async",
        ok_factory,
    )
    assert await wiki_mod.suggest_wiki_meta("正文") is None


def test_extract_json_object_variants() -> None:
    """JSON 提取：围栏/裸对象/垃圾输入。"""
    assert wiki_mod._extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert wiki_mod._extract_json_object('前缀 {"a": 1} 后缀') == {"a": 1}
    assert wiki_mod._extract_json_object("no json here") is None


def test_review_action_normalization() -> None:
    """service 门面把 ValueError 透传（非法 action → 400 的契约锚）。"""
    # 直接断言 wiki.review_document 对非法 action 的异常类型
    import asyncio

    store = WikiStore()
    store.docs["doc_1"] = _doc()
    with pytest.raises(ValueError):
        asyncio.run(
            wiki_mod.review_document(
                store, "kb_1", "doc_1", "unknown", "a",
            ),
        )


def test_normalize_title() -> None:
    assert wiki_mod.normalize_title("  入职指南 ") == "入职指南"
    assert wiki_mod.normalize_title("README") == "readme"


def test_service_wiki_facade_seams_exist() -> None:
    """门面方法齐备（路由依赖的契约面锚定）。"""
    for name in (
        "pg_review_document",
        "pg_list_reviews",
        "pg_update_knowledge_meta",
        "pg_detect_conflicts",
        "pg_list_conflicts",
        "pg_resolve_conflict",
    ):
        assert callable(getattr(svc_mod.KbService, name))
