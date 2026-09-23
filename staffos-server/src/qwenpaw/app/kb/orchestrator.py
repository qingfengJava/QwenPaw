# -*- coding: utf-8 -*-
"""统一检索编排器（T5）：意图计划 → 多路并发 → RRF 融合 → Context。

spec §6 定稿（不引入额外 LLM 调用）：

1. **检索计划**：轻量意图规则生成缺省 plan——编号形态（``ABC-123``）
   或实体词 → OBJECT+STATE 路优先；「当前/状态/能否」等状态词 →
   STATE 路优先；KNOWLEDGE 路恒在兜底（EVIDENCE 与 KNOWLEDGE 同路
   执行：命中块自带 doc_id/heading_path 即证据引用，RAG 层语义）。
2. **多路并发**：object/state（本体卡）与 knowledge（文档块）两执行
   路 ``asyncio.gather`` 并发，单路 ``wait_for`` 超时即弃（WARN 降级，
   绝不让单路故障拖垮整次检索）。
3. **融合**：对象/状态结构化卡置顶 + 跨库知识块 RRF（k=60，多库
   score 不同质，按名次归一）。
4. **检索前鉴权**（spec §3 决策点4）：knowledge 路只在绑定库集合内
   检索；本体卡的关联知识引用同样经绑定集过滤（grounding 层已收敛），
   禁止先搜后滤。

Context Builder 总预算对齐 ``tool._MAX_TOTAL_CHARS``（16000）惯例。

@author qingfeng
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: 检索路线（plan 枚举；EVIDENCE 执行层与 KNOWLEDGE 同路）
ROUTE_OBJECT = "object"
ROUTE_STATE = "state"
ROUTE_KNOWLEDGE = "knowledge"
ROUTE_EVIDENCE = "evidence"

#: 单路 retriever 超时（秒；spec §6 L189）
ROUTE_TIMEOUT_SECONDS = 3.0

#: Context 总预算（字符；对齐 tool._MAX_TOTAL_CHARS 惯例）
_MAX_TOTAL_CHARS = 16000

#: RRF 常数（与 S1 混检同款 k=60）
_RRF_K = 60

#: knowledge 路单库取回深度（RRF 归并前的 per-kb 候选）
_PER_KB_TOP_K = 8

#: 融合后的知识块渲染上限
_MAX_KNOWLEDGE_BLOCKS = 6

#: 状态意图词（命中 → STATE 路优先）
_STATE_HINTS = ("当前", "状态", "能否", "是否", "进度", "现在", "最新")

#: 编号形态（``PROJECT-10001``/``HT-2024``；命中 → OBJECT 路优先）
_CODE_PATTERN = re.compile(r"\b[A-Z][A-Za-z]{1,20}-\d{1,12}\b")


def build_plan(query: str) -> Dict[str, Any]:
    """轻量意图规则 → ``{"routes": [...], "reason": str}``。

    规则顺序即优先级：编号/实体 → OBJECT+STATE；状态词 → STATE；
    KNOWLEDGE 恒在兜底（保序去重）。
    """
    text = query or ""
    routes: List[str] = []
    if _CODE_PATTERN.search(text):
        routes += [ROUTE_OBJECT, ROUTE_STATE]
    if any(hint in text for hint in _STATE_HINTS):
        if ROUTE_STATE not in routes:
            routes.append(ROUTE_STATE)
    routes.append(ROUTE_KNOWLEDGE)
    # 保序去重
    seen: set = set()
    ordered = [r for r in routes if not (r in seen or seen.add(r))]
    return {"routes": ordered, "reason": "heuristic"}


# ---------------------------------------------------------------------------
# 路执行器（内部；异常一律收敛为空结果）
# ---------------------------------------------------------------------------


async def _object_state_route(
    query: str,
    bound_space_ids: Sequence[str],
    agent_id: str,
) -> List[Dict[str, Any]]:
    """本体路：grounding → 对象卡（关联知识经绑定集收敛）。"""
    from ..ontology.grounding import object_card, ground_objects

    objects = await ground_objects(query, limit=3)
    cards: List[Dict[str, Any]] = []
    for obj in objects:
        card = await object_card(
            obj.id,
            bound_space_ids=list(bound_space_ids),
        )
        if card is not None:
            cards.append(card)
    del agent_id
    return cards


def _knowledge_route_sync(
    query: str,
    svc: Any,
    bound_space_ids: Sequence[str],
) -> List[List[Any]]:
    """知识路同步体：per-kb 检索候选（阻塞面，调用方 to_thread 包裹）。"""
    allowed = set(bound_space_ids)
    per_kb: List[List[Any]] = []
    for kb in svc.list_kbs():
        if kb.id not in allowed:
            continue
        try:
            per_kb.append(
                list(svc.search(kb.id, query, top_k=_PER_KB_TOP_K)),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] orchestrator kb search failed; kb=%s",
                kb.id,
                exc_info=True,
            )
    return per_kb


def _rrf_merge(per_kb: List[List[Any]]) -> List[tuple]:
    """跨库 RRF 归并：``Σ 1/(k+rank)``；同 (doc, seq) 去重取首现。"""
    scores: Dict[int, float] = {}
    order: List[int] = []
    seen: set = set()
    for results in per_kb:
        for rank, (chunk, _score) in enumerate(results):
            key = (getattr(chunk, "doc_id", ""), getattr(chunk, "seq", -1))
            if key in seen:
                continue
            seen.add(key)
            scores[id(chunk)] = scores.get(id(chunk), 0.0) + 1.0 / (
                _RRF_K + rank + 1
            )
            order.append(id(chunk))
    # 恢复 chunk 对象（order 保首现序，排序稳定）
    chunk_by_id: Dict[int, Any] = {}
    for results in per_kb:
        for chunk, _score in results:
            chunk_by_id.setdefault(id(chunk), chunk)
    ranked = sorted(
        order,
        key=lambda cid: scores.get(cid, 0.0),
        reverse=True,
    )
    return [(chunk_by_id[cid], scores[cid]) for cid in ranked]


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------


def _render_card(card: Dict[str, Any], state_first: bool) -> str:
    """渲染一张对象卡（STATE 路优先时 state 行提到最前）。"""
    lines: List[str] = [f"[对象] {card['name']} ({card['type_id']})"]
    if state_first and card.get("state"):
        lines.append(f"状态: {card['state']}")
    if card.get("aliases"):
        lines.append(f"别名: {', '.join(card['aliases'][:5])}")
    if not state_first and card.get("state"):
        lines.append(f"状态: {card['state']}")
    attrs = card.get("attributes") or {}
    for key, value in list(attrs.items())[:5]:
        lines.append(f"{key}: {value}")
    rels = card.get("relations") or {}
    for rel in (rels.get("outbound") or [])[:3]:
        lines.append(f"—[{rel['type']}]→ {rel['to_id']}")
    for rel in (rels.get("inbound") or [])[:3]:
        lines.append(f"←[{rel['type']}]— {rel['from_id']}")
    for doc in (card.get("linked_docs") or [])[:3]:
        lines.append(f"关联知识: {doc['doc_id']} ({doc['relation']})")
    return "\n".join(lines)


def _clip(text: str, limit: int) -> str:
    """字符截断（块级）。"""
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


async def retrieve(
    query: str,
    svc: Any,
    bound_space_ids: Sequence[str],
    agent_id: str = "",
    plan: Optional[Dict[str, Any]] = None,
    max_chars: int = _MAX_TOTAL_CHARS,
    timeout_seconds: float = ROUTE_TIMEOUT_SECONDS,
) -> str:
    """编排一次多路检索并组装上下文（永不抛出；失败返回可读降级文本）。

    Args:
        query: 检索问句。
        svc: :class:`~qwenpaw.app.kb.service.KbService`（同步门面）。
        bound_space_ids: **检索前鉴权**的绑定库集合（S0 语义，必传）。
        agent_id: 触发 agent（日志追溯用）。
        plan: 显式检索计划；缺省由 :func:`build_plan` 意图规则生成。
        max_chars: Context 总预算（默认 16000）。
        timeout_seconds: 单路超时。

    Returns:
        组装好的上下文文本（对象/状态卡置顶 + RRF 知识块；超预算截断
        时带可观测的截断标记）。
    """
    query = (query or "").strip()
    if not query:
        return "(empty query)"
    if not bound_space_ids:
        return "(no bound knowledge bases)"
    plan = plan or build_plan(query)
    routes = plan.get("routes") or [ROUTE_KNOWLEDGE]

    want_object = ROUTE_OBJECT in routes or ROUTE_STATE in routes
    want_knowledge = (
        ROUTE_KNOWLEDGE in routes or ROUTE_EVIDENCE in routes
    )

    async def _run_object() -> Any:
        return await _object_state_route(
            query, bound_space_ids, agent_id,
        )

    async def _run_knowledge() -> Any:
        return await asyncio.to_thread(
            _knowledge_route_sync, query, svc, bound_space_ids,
        )

    tasks: Dict[str, Any] = {}
    if want_object:
        tasks["object"] = asyncio.wait_for(
            _run_object(), timeout=timeout_seconds,
        )
    if want_knowledge:
        tasks["knowledge"] = asyncio.wait_for(
            _run_knowledge(), timeout=timeout_seconds,
        )

    names = list(tasks)
    results = await asyncio.gather(
        *tasks.values(),
        return_exceptions=True,
    )
    outcome = dict(zip(names, results))

    cards: List[Dict[str, Any]] = []
    if isinstance(outcome.get("object"), list):
        cards = outcome["object"]
    elif outcome.get("object") is not None:
        # 超时/异常：降级为空卡，WARN 可观测（spec：单路故障不拖垮检索）
        logger.warning(
            "[kb] orchestrator object route failed: %r",
            outcome["object"],
        )

    per_kb: List[List[Any]] = []
    if isinstance(outcome.get("knowledge"), list):
        per_kb = outcome["knowledge"]
    elif outcome.get("knowledge") is not None:
        logger.warning(
            "[kb] orchestrator knowledge route failed: %r",
            outcome["knowledge"],
        )

    # ---- 融合渲染：卡置顶 + RRF 知识块，共享 max_chars 预算 ----
    state_first = ROUTE_STATE in routes
    parts: List[str] = []
    used = 0

    for card in cards:
        text = _render_card(card, state_first)
        if used + len(text) > max_chars:
            break
        parts.append(text)
        used += len(text) + 2

    budget = max_chars - used
    merged = _rrf_merge(per_kb)
    shown = 0
    for chunk, score in merged[:_MAX_KNOWLEDGE_BLOCKS]:
        block = _clip(
            getattr(chunk, "text", "") or "",
            min(1200, max(200, budget // max(1, _MAX_KNOWLEDGE_BLOCKS))),
        )
        heading = getattr(chunk, "heading_path", "") or ""
        crumb = f" #{heading}" if heading else ""
        title = getattr(chunk, "title", "") or getattr(
            chunk, "doc_id", "",
        )
        header = (
            f"===== {title}{crumb} [rrf={score:.4f}] =====\n{block}"
        )
        if used + len(header) > max_chars:
            break
        parts.append(header)
        used += len(header) + 2
        shown += 1

    if not parts:
        return "(no matching knowledge)"
    if len(merged) > shown:
        parts.append(
            f"[检索计划 {routes}；融合候选 {len(merged)} 条，"
            f"预算内渲染 {shown} 块]",
        )
    return "\n\n".join(parts)


__all__ = [
    "ROUTE_EVIDENCE",
    "ROUTE_KNOWLEDGE",
    "ROUTE_OBJECT",
    "ROUTE_STATE",
    "build_plan",
    "retrieve",
]
