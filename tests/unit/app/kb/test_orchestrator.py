# -*- coding: utf-8 -*-
"""T5 检索编排器单测：意图计划 / 并发超时降级 / RRF 融合 / 预算。

锁定四条行为：

1. **意图规则零 LLM**：编号形态 → OBJECT+STATE；状态词 → STATE；
   KNOWLEDGE 恒在兜底；
2. **并发与超时**：单路超时不拖垮整次检索（WARN 降级空结果）；
3. **RRF 融合**：跨库按名次归一、同 (doc, seq) 去重取首现；
4. **预算**：总输出不超 max_chars，截断可观测。

本体路经 monkeypatch ``grounding`` 函数注入（函数内 import 每次取
模块属性，patched 生效）；knowledge 路用 fake svc（同步门面语义）。

@author qingfeng
"""

# pylint: disable=protected-access
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from qwenpaw.app.kb import orchestrator as orch

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# build_plan
# ---------------------------------------------------------------------------


def test_plan_code_pattern_routes_object_state() -> None:
    """编号形态（PROJECT-10001）→ OBJECT+STATE 优先 + knowledge 兜底。"""
    plan = orch.build_plan("PROJECT-10001 的验收标准是什么")
    assert plan["routes"][0] == orch.ROUTE_OBJECT
    assert plan["routes"][1] == orch.ROUTE_STATE
    assert orch.ROUTE_KNOWLEDGE in plan["routes"]


def test_plan_state_hints_route_state() -> None:
    """状态词（当前/能否）→ STATE 路。"""
    plan = orch.build_plan("这个流程当前处于什么阶段")
    assert orch.ROUTE_STATE in plan["routes"]
    assert orch.ROUTE_OBJECT not in plan["routes"]


def test_plan_plain_query_knowledge_only() -> None:
    """普通问句只走 knowledge 路。"""
    plan = orch.build_plan("新员工入职流程是什么")
    assert plan["routes"] == [orch.ROUTE_KNOWLEDGE]


def test_plan_routes_dedup_preserve_order() -> None:
    """规则叠加时路由保序去重。"""
    plan = orch.build_plan("HT-2024 合同当前状态")
    routes = plan["routes"]
    assert len(routes) == len(set(routes))
    assert routes.index(orch.ROUTE_OBJECT) < routes.index(
        orch.ROUTE_KNOWLEDGE,
    )


# ---------------------------------------------------------------------------
# fake svc / grounding 打桩
# ---------------------------------------------------------------------------


def _chunk(doc_id: str, seq: int, text: str, heading: str = "") -> Any:
    """构造检索命中块（鸭子类型，orchestrator 只取属性）。"""
    return SimpleNamespace(
        doc_id=doc_id,
        seq=seq,
        text=text,
        title=f"文档{doc_id}",
        heading_path=heading,
    )


class _FakeSvc:
    """同步门面语义的最小 svc（list_kbs + search）。"""

    def __init__(
        self,
        kb_ids: List[str],
        results: Dict[str, List[Any]],
    ) -> None:
        self.kbs = [SimpleNamespace(id=k) for k in kb_ids]
        self.results = results
        self.searched: List[str] = []

    def list_kbs(self) -> List[Any]:
        return self.kbs

    def search(self, kb_id: str, query: str, top_k: int = 8):
        del query, top_k
        self.searched.append(kb_id)
        return self.results.get(kb_id, [])


def _stub_grounding(
    monkeypatch: pytest.MonkeyPatch,
    cards: List[Dict[str, Any]],
) -> None:
    """钉 grounding：ground_objects 返回一个对象、object_card 回放 cards。"""
    from qwenpaw.app.ontology import grounding

    async def _ground(keyword, type_id="", limit=3, store=None):
        del keyword, type_id, limit, store
        return [SimpleNamespace(id=cards[0]["id"] if cards else "obj_1")]

    async def _card(object_id, bound_space_ids=None, store=None):
        del object_id, bound_space_ids, store
        return cards[0] if cards else None

    monkeypatch.setattr(grounding, "ground_objects", _ground)
    monkeypatch.setattr(grounding, "object_card", _card)


async def test_retrieve_renders_cards_first_then_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """卡置顶 + 知识块随后的融合渲染形态。"""
    _stub_grounding(monkeypatch, [
        {
            "id": "obj_1",
            "type_id": "l1.project",
            "name": "PROJECT-10001",
            "aliases": ["P1"],
            "state": "执行中",
            "state_detail": {},
            "attributes": {"code": "PROJECT-10001"},
            "relations": {"outbound": [], "inbound": []},
            "linked_docs": [],
        },
    ])
    svc = _FakeSvc(
        ["kb_a"],
        {"kb_a": [(_chunk("d1", 0, "验收标准正文"), 0.9)]},
    )
    out = await orch.retrieve(
        "PROJECT-10001 验收",
        svc,
        ["kb_a"],
        timeout_seconds=2.0,
    )
    assert "[对象] PROJECT-10001" in out
    assert "状态: 执行中" in out
    assert "验收标准正文" in out
    assert out.index("[对象]") < out.index("验收标准正文")


async def test_retrieve_object_route_timeout_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单路超时 → 卡缺失但 knowledge 正常（WARN 降级不拖垮检索）。"""
    from qwenpaw.app.ontology import grounding

    async def _slow_ground(*args: Any, **kwargs: Any):
        await asyncio.sleep(0.5)
        return []

    async def _fast_card(*args: Any, **kwargs: Any):
        del args, kwargs
        return None

    monkeypatch.setattr(grounding, "ground_objects", _slow_ground)
    monkeypatch.setattr(grounding, "object_card", _fast_card)
    svc = _FakeSvc(
        ["kb_a"],
        {"kb_a": [(_chunk("d1", 0, "流程正文"), 0.8)]},
    )
    out = await orch.retrieve(
        "PROJECT-10001 流程",
        svc,
        ["kb_a"],
        timeout_seconds=0.01,
    )
    assert "[对象]" not in out
    assert "流程正文" in out


async def test_retrieve_empty_bound_short_circuits() -> None:
    """空绑定集：检索前鉴权短路，不触碰 svc。"""
    svc = _FakeSvc(["kb_a"], {})
    out = await orch.retrieve("任意问题", svc, [])
    assert out == "(no bound knowledge bases)"
    assert svc.searched == []


async def test_retrieve_no_match_returns_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """全部为空 → 可读提示（不抛错不返回空串）。"""
    _stub_grounding(monkeypatch, [])
    svc = _FakeSvc(["kb_a"], {"kb_a": []})
    out = await orch.retrieve(
        "普通问题", svc, ["kb_a"], timeout_seconds=1.0,
    )
    assert out == "(no matching knowledge)"


async def test_retrieve_budget_truncation_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """预算截断：超预算块被跳过并附可观测标记。"""
    _stub_grounding(monkeypatch, [])
    blocks = [(_chunk(f"d{i}", 0, "x" * 300), 0.9 - i * 0.1) for i in range(4)]
    svc = _FakeSvc(["kb_a"], {"kb_a": blocks})
    out = await orch.retrieve(
        "问题", svc, ["kb_a"], max_chars=500, timeout_seconds=1.0,
    )
    assert len(out) <= 700
    assert "预算内渲染" in out


# ---------------------------------------------------------------------------
# RRF 归并
# ---------------------------------------------------------------------------


def test_rrf_merge_dedup_and_cross_kb() -> None:
    """同 (doc, seq) 去重取首现；跨库同名次累加。"""
    a1 = _chunk("d1", 0, "a1")
    b1 = _chunk("d1", 0, "b1")
    a2 = _chunk("d2", 0, "a2")
    merged = orch._rrf_merge(
        [
            [(a1, 0.9), (a2, 0.5)],
            [(b1, 0.8)],
        ],
    )
    ids = [id(chunk) for chunk, _score in merged]
    assert ids[0] == id(a1)
    assert id(b1) not in ids
    assert id(a2) in ids
    # a1 在两路都第 1 名与第 2 名出现场景：只计首现一路
    scores = {id(chunk): score for chunk, score in merged}
    assert scores[id(a1)] == pytest.approx(1.0 / (orch._RRF_K + 1))


def test_rrf_merge_rank_normalization() -> None:
    """第 1 名得分高于第 2 名（RRF 名次衰减）。"""
    c1 = _chunk("d1", 0, "c1")
    c2 = _chunk("d2", 0, "c2")
    merged = orch._rrf_merge([[(c1, 0.9), (c2, 0.8)]])
    scores = [score for _chunk, score in merged]
    assert scores[0] > scores[1]
