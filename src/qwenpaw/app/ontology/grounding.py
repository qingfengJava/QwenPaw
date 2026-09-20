# -*- coding: utf-8 -*-
"""Ontology 只读运行时：grounding + 对象卡 + 关系图（T5）。

三层架构中「Ontology Runtime」的查询面（spec：只读 MVP）：

1. **grounding**：名称/别名 → 对象（ILIKE 模糊，**不做 LLM 抽取**）；
2. **对象卡**：对象 + 双向关系（top）+ 关联知识 doc（供 kb_read 深读）；
3. **关系图**：``WITH RECURSIVE`` CTE ≤3 跳（store.graph_from_objects）。

状态读取 = ``objects.state`` 直查（无独立状态运行时；状态迁移历史
见 ``ontology_state_transitions``，本期仅留档）。

本模块全部查询**只读**；平面不可用时对象卡/图返回空（fail-soft），
编排器与工具据此降级，不让本体故障阻断知识检索主链路。

@author qingfeng
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .models import OntologyObject
from .store import PgOntologyStore, get_ready_ontology_store

logger = logging.getLogger(__name__)

#: 对象卡里双向关系的展示上限（防高连通节点撑爆上下文）
_CARD_RELATIONS_LIMIT = 5

#: 关联知识 doc 展示上限（对象卡引用面）
_CARD_LINKS_LIMIT = 5


async def _store_or_none(
    store: Optional[PgOntologyStore],
) -> Optional[PgOntologyStore]:
    """显式注入优先；缺省走工厂（平面不可用返回 None）。"""
    if store is not None:
        return store
    return await get_ready_ontology_store()


async def ground_objects(
    keyword: str,
    type_id: str = "",
    limit: int = 3,
    store: Optional[PgOntologyStore] = None,
) -> List[OntologyObject]:
    """名称/别名 grounding：ILIKE 模糊匹配存活对象（无 LLM 抽取）。"""
    keyword = (keyword or "").strip()
    if not keyword:
        return []
    ready = await _store_or_none(store)
    if ready is None:
        return []
    try:
        return await ready.list_objects(
            type_id=type_id,
            keyword=keyword,
            limit=max(1, int(limit)),
        )
    except Exception:  # pylint: disable=broad-except
        logger.warning("[ontology] ground_objects failed", exc_info=True)
        return []


async def object_card(
    object_id: str,
    bound_space_ids: Optional[List[str]] = None,
    store: Optional[PgOntologyStore] = None,
) -> Optional[Dict[str, Any]]:
    """组装一张对象卡：对象 + 双向关系 + 关联知识（ACL 收敛）。

    ``bound_space_ids`` 为 Agent 绑定库集合（S0 语义）：关联知识 doc
    只显示所属库 ∈ 绑定集的条目——对象本身企业可见，但其知识引用面
    严格遵守绑定即授权，杜绝卡片侧越权泄露 doc。

    Returns:
        卡 dict（含 relations/linked_docs）；对象不存在或平面不可用
        返回 None。
    """
    ready = await _store_or_none(store)
    if ready is None:
        return None
    try:
        obj = await ready.get_object(object_id)
        if obj is None:
            return None
        outbound = await ready.list_relations(from_id=object_id)
        inbound = await ready.list_relations(to_id=object_id)
        links = await ready.list_links_for_object(object_id)

        # 关联知识 ACL 收敛：doc 所属库 ∈ 绑定集才进卡（无绑定信息时
        # 不展示知识引用——宁缺勿泄）
        allowed = set(bound_space_ids or [])
        linked_docs = [
            {
                "doc_id": link.kb_document_id,
                "kb_space_id": link.kb_space_id,
                "relation": link.relation,
            }
            for link in links
            if link.kb_space_id in allowed
        ][:_CARD_LINKS_LIMIT]

        return {
            "id": obj.id,
            "type_id": obj.type_id,
            "name": obj.name,
            "aliases": obj.aliases,
            "state": obj.state,
            "state_detail": obj.state_detail,
            "attributes": obj.attributes,
            "source": obj.source,
            "relations": {
                "outbound": [
                    {
                        "type": rel.type,
                        "to_id": rel.to_id,
                        "to_type": rel.to_type,
                    }
                    for rel in outbound[:_CARD_RELATIONS_LIMIT]
                ],
                "inbound": [
                    {
                        "type": rel.type,
                        "from_id": rel.from_id,
                        "from_type": rel.from_type,
                    }
                    for rel in inbound[:_CARD_RELATIONS_LIMIT]
                ],
            },
            "linked_docs": linked_docs,
        }
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "[ontology] object_card failed: id=%s", object_id,
            exc_info=True,
        )
        return None


async def related_graph(
    seed_ids: List[str],
    max_depth: int = 3,
    store: Optional[PgOntologyStore] = None,
) -> List[Dict[str, Any]]:
    """关系图遍历（CTE ≤depth）；平面不可用/异常返回空。"""
    if not seed_ids:
        return []
    ready = await _store_or_none(store)
    if ready is None:
        return []
    try:
        edges = await ready.graph_from_objects(
            seed_ids,
            max_depth=max_depth,
        )
    except Exception:  # pylint: disable=broad-except
        logger.warning("[ontology] related_graph failed", exc_info=True)
        return []
    return [
        {
            "from_id": from_id,
            "to_id": to_id,
            "type": edge_type,
            "depth": depth,
        }
        for from_id, to_id, edge_type, depth in edges
    ]


__all__ = [
    "ground_objects",
    "object_card",
    "related_graph",
]
