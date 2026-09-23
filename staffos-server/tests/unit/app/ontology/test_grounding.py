# -*- coding: utf-8 -*-
"""T5 ontology grounding 单测：对象卡组装 / 关联知识 ACL 收敛 / 图遍历。

锁定三条安全与降级契约：

1. **卡片知识引用 ACL**：``object_card`` 的 ``linked_docs`` 只含所属库
   ∈ 绑定集的条目——对象企业可见，知识引用不越权（S0 同源收敛）；
2. **fail-soft**：平面不可用（工厂 None）与 store 异常都返回空/None，
   绝不让本体故障阻断知识检索主链路；
3. **图遍历**：``related_graph`` 边元组 → dict 形态转换 + 空 seeds 短路。

store 经 monkeypatch 注入 fake（绕过工厂与真 PG）。

@author qingfeng
"""

# pylint: disable=protected-access
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from qwenpaw.app.ontology import grounding
from qwenpaw.app.ontology.models import (
    KbObjectLink,
    OntologyObject,
    OntologyRelation,
)

pytestmark = pytest.mark.unit


class _FakeStore:
    """最小 store：对象/关系/互引字典直查。"""

    def __init__(
        self,
        obj: Optional[OntologyObject] = None,
        outbound: Optional[List[OntologyRelation]] = None,
        inbound: Optional[List[OntologyRelation]] = None,
        links: Optional[List[KbObjectLink]] = None,
        graph: Optional[List[tuple]] = None,
        boom: bool = False,
    ) -> None:
        self.obj = obj
        self.outbound = outbound or []
        self.inbound = inbound or []
        self.links = links or []
        self.graph = graph or []
        self.boom = boom

    async def get_object(self, object_id: str):
        del object_id
        if self.boom:
            raise RuntimeError("store boom")
        return self.obj

    async def list_relations(self, from_id: str = "", to_id: str = "", **_):
        if self.boom:
            raise RuntimeError("store boom")
        return self.outbound if from_id else self.inbound

    async def list_links_for_object(self, object_id: str):
        del object_id
        if self.boom:
            raise RuntimeError("store boom")
        return self.links

    async def graph_from_objects(self, seeds, max_depth=3, limit=100):
        del max_depth, limit
        if self.boom:
            raise RuntimeError("store boom")
        return self.graph


def _obj() -> OntologyObject:
    return OntologyObject(
        id="P1",
        type_id="l1.project",
        name="PROJECT-10001",
        state="执行中",
    )


def _link(space_id: str) -> KbObjectLink:
    return KbObjectLink(
        id=f"lnk_{space_id}",
        kb_space_id=space_id,
        kb_document_id=f"doc_{space_id}",
        object_type="l1.project",
        object_id="P1",
    )


# ---------------------------------------------------------------------------
# ground_objects
# ---------------------------------------------------------------------------


async def test_ground_empty_keyword_short_circuits() -> None:
    """空关键词：不触碰工厂直接返回空。"""
    assert await grounding.ground_objects("  ") == []


async def test_ground_plane_off_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """平面不可用（工厂 None）→ 空列表（fail-soft）。"""

    async def _none():
        return None

    monkeypatch.setattr(
        grounding,
        "get_ready_ontology_store",
        _none,
    )
    assert await grounding.ground_objects("PROJECT") == []


async def test_ground_store_boom_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """store 异常吞掉 → 空列表。"""

    async def _boom_store():
        return _FakeStore(boom=True)

    monkeypatch.setattr(
        grounding,
        "get_ready_ontology_store",
        _boom_store,
    )
    assert await grounding.ground_objects("PROJECT") == []


# ---------------------------------------------------------------------------
# object_card（ACL 收敛）
# ---------------------------------------------------------------------------


async def test_card_links_filtered_by_bound_spaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """关联知识只显示绑定库条目：kb_bound 进卡，kb_other 被滤。"""
    store = _FakeStore(
        obj=_obj(),
        links=[_link("kb_bound"), _link("kb_other")],
    )

    async def _factory():
        return store

    monkeypatch.setattr(grounding, "get_ready_ontology_store", _factory)
    card = await grounding.object_card("P1", bound_space_ids=["kb_bound"])
    assert card is not None
    doc_ids = [doc["doc_id"] for doc in card["linked_docs"]]
    assert doc_ids == ["doc_kb_bound"]


async def test_card_without_binding_shows_no_docs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无绑定信息 → 宁缺勿泄：知识引用整段不展示。"""
    store = _FakeStore(obj=_obj(), links=[_link("kb_any")])

    async def _factory():
        return store

    monkeypatch.setattr(grounding, "get_ready_ontology_store", _factory)
    card = await grounding.object_card("P1", bound_space_ids=[])
    assert card is not None
    assert card["linked_docs"] == []


async def test_card_missing_object_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """对象不存在 → None（工具层转 no-match 提示）。"""
    store = _FakeStore(obj=None)

    async def _factory():
        return store

    monkeypatch.setattr(grounding, "get_ready_ontology_store", _factory)
    assert await grounding.object_card("ghost") is None


async def test_card_store_boom_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """store 异常吞掉 → None（绝不抛穿）。"""
    store = _FakeStore(obj=_obj(), boom=True)

    async def _factory():
        return store

    monkeypatch.setattr(grounding, "get_ready_ontology_store", _factory)
    assert await grounding.object_card("P1") is None


async def test_card_relations_both_directions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """卡内关系双向形态（outbound/inbound 字段齐全）。"""
    store = _FakeStore(
        obj=_obj(),
        outbound=[
            OntologyRelation(
                id="r1",
                type="belongs_to",
                from_type="l1.project",
                from_id="P1",
                to_type="l1.org",
                to_id="org1",
            ),
        ],
        inbound=[],
    )

    async def _factory():
        return store

    monkeypatch.setattr(grounding, "get_ready_ontology_store", _factory)
    card = await grounding.object_card("P1", bound_space_ids=["kb_a"])
    assert card["relations"]["outbound"][0]["type"] == "belongs_to"
    assert card["relations"]["inbound"] == []


# ---------------------------------------------------------------------------
# related_graph
# ---------------------------------------------------------------------------


async def test_graph_empty_seeds_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空 seeds：不发查询。"""
    called = False

    async def _factory():
        nonlocal called
        called = True
        return _FakeStore()

    monkeypatch.setattr(grounding, "get_ready_ontology_store", _factory)
    assert await grounding.related_graph([]) == []
    assert called is False


async def test_graph_edge_tuple_to_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """边元组 → dict 形态（depth 保留）。"""
    store = _FakeStore(graph=[("P1", "org1", "belongs_to", 1)])

    async def _factory():
        return store

    monkeypatch.setattr(grounding, "get_ready_ontology_store", _factory)
    edges = await grounding.related_graph(["P1"], max_depth=3)
    assert edges == [
        {"from_id": "P1", "to_id": "org1", "type": "belongs_to", "depth": 1},
    ]


async def test_graph_boom_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """图查询异常吞掉 → 空列表。"""
    store = _FakeStore(boom=True)

    async def _factory():
        return store

    monkeypatch.setattr(grounding, "get_ready_ontology_store", _factory)
    assert await grounding.related_graph(["P1"]) == []
